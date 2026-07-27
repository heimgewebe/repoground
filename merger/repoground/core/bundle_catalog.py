"""Bounded, fail-closed discovery of existing RepoGround bundle publications.

The catalog is read-only. It never refreshes a snapshot or mutates a publication.
Historical runs may coexist; selection is deterministic only when one newest,
healthy bundle matches the requested repository identity and optional stem.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from merger.repoground.core.bundle_identity import is_bundle_manifest
from merger.repoground.core.manifest_snapshot import (
    active_manifest_snapshot,
    resolve_manifest_path,
)
from merger.repoground.core.post_health_binding import post_health_binding_status

KIND = "repoground.bundle_catalog"
VERSION = "v1"
MANIFEST_SUFFIX = ".bundle.manifest.json"
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_HEALTH_BYTES = 4 * 1024 * 1024
MAX_DISCOVERED_MANIFESTS = 2000
_OPEN_TIMEOUT_SECONDS = 1.0
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_GITHUB_SCP_RE = re.compile(r"^[^@]+@github\.com:(?P<slug>[^/]+/[^/]+?)(?:\.git)?$")
_GITHUB_URL_RE = re.compile(
    r"^(?:https?|ssh)://(?:[^@/]+@)?github\.com/(?P<slug>[^/]+/[^/]+?)(?:\.git)?/?$"
)

DOES_NOT_ESTABLISH = [
    "freshness_against_remote",
    "runtime_correctness",
    "repo_understood",
    "claims_true",
    "merge_readiness",
]


class BundleCatalogError(ValueError):
    """Raised when discovery or selection cannot remain deterministic."""


@dataclass(frozen=True, slots=True)
class _StableRead:
    selected_path: Path
    resolved_path: Path
    raw: bytes
    identity: tuple[int, int, int, int, int, int]


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_identity(metadata: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        int(metadata.st_dev),
        int(metadata.st_ino),
        int(metadata.st_mode),
        int(metadata.st_size),
        int(metadata.st_mtime_ns),
        int(metadata.st_ctime_ns),
    )


def _absolute_path(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path.expanduser())))


def _resolve_read_path(
    path: Path,
    *,
    root: Path | None,
    label: str,
) -> Path:
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise BundleCatalogError(f"file cannot be resolved: {path}") from exc
    if root is not None:
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise BundleCatalogError(
                f"{label} resolves outside catalog root: {path}"
            ) from exc
    return resolved


_PORTABLE_READ_HELPER = r"""
import json
import os
import stat
import sys

path = sys.argv[1]
limit = int(sys.argv[2])
expected = tuple(json.loads(sys.argv[3]))


def emit(status, **fields):
    payload = {"status": status, **fields}
    sys.stdout.buffer.write(
        json.dumps(payload, separators=(",", ":")).encode("utf-8") + b"\n"
    )


flags = (
    os.O_RDONLY
    | getattr(os, "O_BINARY", 0)
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_NOFOLLOW", 0)
)
try:
    descriptor = os.open(path, flags)
except OSError as exc:
    emit("error", reason=f"file cannot be opened: {exc}")
    raise SystemExit(0)

try:
    before = os.fstat(descriptor)
    identity = (
        int(before.st_dev),
        int(before.st_ino),
        int(before.st_mode),
        int(before.st_size),
        int(before.st_mtime_ns),
        int(before.st_ctime_ns),
    )
    if not stat.S_ISREG(before.st_mode):
        emit("error", reason="file is not regular")
        raise SystemExit(0)
    if identity != expected:
        emit("error", reason="file identity changed before reading")
        raise SystemExit(0)
    if before.st_size > limit:
        emit("error", reason="file exceeds bounded catalog read")
        raise SystemExit(0)

    chunks = []
    remaining = limit + 1
    while remaining:
        chunk = os.read(descriptor, min(1024 * 1024, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    raw = b"".join(chunks)
    after = os.fstat(descriptor)
    after_identity = (
        int(after.st_dev),
        int(after.st_ino),
        int(after.st_mode),
        int(after.st_size),
        int(after.st_mtime_ns),
        int(after.st_ctime_ns),
    )
    if after_identity != identity or len(raw) != after.st_size:
        emit("error", reason="file changed while reading")
        raise SystemExit(0)
finally:
    os.close(descriptor)

emit("ok", identity=list(identity), raw_length=len(raw))
sys.stdout.buffer.write(raw)
"""


def _nonblocking_open_available() -> bool:
    value = getattr(os, "O_NONBLOCK", 0)
    return isinstance(value, int) and bool(value)


def _portable_reader_output(
    stdout: bytes,
    *,
    path: Path,
    max_bytes: int,
) -> tuple[dict[str, Any], bytes]:
    if len(stdout) > max_bytes + 4096:
        raise BundleCatalogError(f"portable file reader exceeded output bound: {path}")
    header, separator, raw = stdout.partition(b"\n")
    if not separator:
        raise BundleCatalogError(f"portable file reader returned no header: {path}")
    try:
        metadata = json.loads(header.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BundleCatalogError(
            f"portable file reader returned an invalid header: {path}"
        ) from exc
    if not isinstance(metadata, dict):
        raise BundleCatalogError(
            f"portable file reader returned an invalid header: {path}"
        )
    return metadata, raw


def _portable_reader_identity(
    metadata: dict[str, Any],
    raw: bytes,
    *,
    path: Path,
    expected_identity: tuple[int, int, int, int, int, int],
) -> tuple[int, int, int, int, int, int]:
    if metadata.get("status") != "ok":
        reason = metadata.get("reason")
        detail = reason if isinstance(reason, str) and reason else "file cannot be read"
        raise BundleCatalogError(f"{detail}: {path}")
    raw_identity = metadata.get("identity")
    valid_identity = (
        isinstance(raw_identity, list)
        and len(raw_identity) == 6
        and all(isinstance(item, int) for item in raw_identity)
    )
    if not valid_identity:
        raise BundleCatalogError(
            f"portable file reader returned invalid identity: {path}"
        )
    identity = tuple(raw_identity)
    if identity != expected_identity:
        raise BundleCatalogError(f"file identity changed before reading: {path}")
    if metadata.get("raw_length") != len(raw):
        raise BundleCatalogError(
            f"portable file reader returned truncated bytes: {path}"
        )
    return identity


def _read_bounded_portable(
    path: Path,
    max_bytes: int,
    expected_identity: tuple[int, int, int, int, int, int],
) -> tuple[bytes, tuple[int, int, int, int, int, int]]:
    command = [
        sys.executable,
        "-I",
        "-c",
        _PORTABLE_READ_HELPER,
        os.fspath(path),
        str(max_bytes),
        json.dumps(expected_identity, separators=(",", ":")),
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            check=False,
            timeout=_OPEN_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise BundleCatalogError(
            f"file open exceeded time bound: {path}"
        ) from exc
    if completed.returncode != 0:
        raise BundleCatalogError(f"portable file reader failed: {path}")
    metadata, raw = _portable_reader_output(
        completed.stdout,
        path=path,
        max_bytes=max_bytes,
    )
    identity = _portable_reader_identity(
        metadata,
        raw,
        path=path,
        expected_identity=expected_identity,
    )
    return raw, identity


def _open_binary(path: Path) -> Any:
    nonblocking = getattr(os, "O_NONBLOCK", 0)
    if not isinstance(nonblocking, int) or not nonblocking:
        raise BundleCatalogError("nonblocking descriptor open is unavailable")
    flags = (
        os.O_RDONLY
        | nonblocking
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = os.open(path, flags)
    try:
        return os.fdopen(descriptor, "rb")
    except Exception:
        os.close(descriptor)
        raise


def _assert_stable_read_path(
    *,
    selected_path: Path,
    resolved_path: Path,
    identity: tuple[int, int, int, int, int, int],
    root: Path | None,
    label: str,
) -> None:
    current_resolved = _resolve_read_path(
        selected_path,
        root=root,
        label=label,
    )
    if current_resolved != resolved_path:
        raise BundleCatalogError(f"file target changed while reading: {selected_path}")
    try:
        current_identity = _file_identity(current_resolved.stat())
    except OSError as exc:
        raise BundleCatalogError(
            f"file identity cannot be verified: {selected_path}"
        ) from exc
    if current_identity != identity:
        raise BundleCatalogError(f"file identity changed while reading: {selected_path}")


def _preliminary_regular_identity(
    resolved_path: Path,
    selected_path: Path,
    max_bytes: int,
) -> tuple[int, int, int, int, int, int]:
    preliminary = resolved_path.stat()
    if not stat.S_ISREG(preliminary.st_mode):
        raise BundleCatalogError(f"file is not regular: {selected_path}")
    if preliminary.st_size > max_bytes:
        raise BundleCatalogError(
            f"file exceeds bounded catalog read: {selected_path}"
        )
    return _file_identity(preliminary)


def _read_nonblocking_stable(
    resolved_path: Path,
    selected_path: Path,
    max_bytes: int,
    preliminary_identity: tuple[int, int, int, int, int, int],
    *,
    root: Path | None,
    label: str,
) -> tuple[bytes, tuple[int, int, int, int, int, int], tuple[int, int, int, int, int, int]]:
    with _open_binary(resolved_path) as handle:
        descriptor = handle.fileno()
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise BundleCatalogError(f"file is not regular: {selected_path}")
        identity = _file_identity(before)
        if identity != preliminary_identity:
            raise BundleCatalogError(
                f"file identity changed before reading: {selected_path}"
            )
        if before.st_size > max_bytes:
            raise BundleCatalogError(
                f"file exceeds bounded catalog read: {selected_path}"
            )
        _assert_stable_read_path(
            selected_path=selected_path,
            resolved_path=resolved_path,
            identity=identity,
            root=root,
            label=label,
        )
        raw = handle.read(max_bytes + 1)
        after_identity = _file_identity(os.fstat(descriptor))
    return raw, identity, after_identity


def _read_bounded_stable(
    path: Path,
    max_bytes: int,
    *,
    root: Path | None = None,
    label: str = "file",
) -> _StableRead:
    selected_path = _absolute_path(path)
    resolved_path = _resolve_read_path(
        selected_path,
        root=root,
        label=label,
    )
    try:
        preliminary_identity = _preliminary_regular_identity(
            resolved_path,
            selected_path,
            max_bytes,
        )
        _assert_stable_read_path(
            selected_path=selected_path,
            resolved_path=resolved_path,
            identity=preliminary_identity,
            root=root,
            label=label,
        )
        if _nonblocking_open_available():
            raw, identity, after_identity = _read_nonblocking_stable(
                resolved_path,
                selected_path,
                max_bytes,
                preliminary_identity,
                root=root,
                label=label,
            )
        else:
            raw, identity = _read_bounded_portable(
                resolved_path,
                max_bytes,
                preliminary_identity,
            )
            after_identity = identity
    except BundleCatalogError:
        raise
    except OSError as exc:
        raise BundleCatalogError(f"file cannot be read: {path}") from exc

    if len(raw) > max_bytes:
        raise BundleCatalogError(
            f"file exceeds bounded catalog read: {selected_path}"
        )
    if identity != after_identity or len(raw) != identity[3]:
        raise BundleCatalogError(f"file changed while reading: {selected_path}")
    _assert_stable_read_path(
        selected_path=selected_path,
        resolved_path=resolved_path,
        identity=identity,
        root=root,
        label=label,
    )
    return _StableRead(
        selected_path=selected_path,
        resolved_path=resolved_path,
        raw=raw,
        identity=identity,
    )


def _read_bounded(
    path: Path,
    max_bytes: int,
    *,
    root: Path | None = None,
    label: str = "file",
) -> bytes:
    return _read_bounded_stable(
        path,
        max_bytes,
        root=root,
        label=label,
    ).raw


def _decode_json_object(path: Path, raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BundleCatalogError(f"file is not valid UTF-8 JSON: {path}") from exc
    if not isinstance(value, dict):
        raise BundleCatalogError(f"JSON document must be an object: {path}")
    return value


def _load_json_object(
    path: Path,
    max_bytes: int,
    *,
    root: Path | None = None,
    label: str = "file",
) -> tuple[dict[str, Any], bytes]:
    raw = _read_bounded(path, max_bytes, root=root, label=label)
    return _decode_json_object(path, raw), raw


def _validate_manifest_document(
    path: Path,
    document: dict[str, Any],
    raw: bytes,
) -> tuple[dict[str, Any], bytes]:
    if (
        not is_bundle_manifest(document)
        or not isinstance(document.get("run_id"), str)
        or not isinstance(document.get("artifacts"), list)
    ):
        raise BundleCatalogError(f"invalid RepoGround bundle manifest: {path}")
    return document, raw


def _manifest_document(path: Path) -> tuple[dict[str, Any], bytes]:
    snapshot = active_manifest_snapshot(path)
    if snapshot is None:
        document, raw = _load_json_object(path, MAX_MANIFEST_BYTES)
    else:
        document, raw = snapshot.json_object(), snapshot.raw
    return _validate_manifest_document(path, document, raw)


def _safe_child(root: Path, raw_path: Any) -> Path | None:
    if not isinstance(raw_path, str) or not raw_path:
        return None
    candidate = (root / raw_path).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    return candidate


def normalize_repo_remote(value: Any) -> str | None:
    """Return a stable owner/repository identity for common GitHub remotes."""
    if not isinstance(value, str) or not value.strip():
        return None
    remote = value.strip()
    match = _GITHUB_SCP_RE.fullmatch(remote) or _GITHUB_URL_RE.fullmatch(remote)
    if match:
        return match.group("slug").removesuffix(".git").strip("/").casefold()
    trimmed = remote.removesuffix(".git").rstrip("/")
    if "/" in trimmed:
        parts = [part for part in trimmed.replace(":", "/").split("/") if part]
        if len(parts) >= 2:
            return "/".join(parts[-2:]).casefold()
    return None


def _canonical_name_aliases(name: Any) -> set[str]:
    if not isinstance(name, str) or not name.strip():
        return set()
    raw = name.strip()
    aliases = {raw.casefold()}
    parts = raw.split("__")
    if len(parts) >= 3 and parts[0] and parts[1]:
        owner_repo = f"{parts[0]}/{parts[1]}".casefold()
        aliases.update(
            {owner_repo, f"{parts[0]}__{parts[1]}".casefold(), parts[1].casefold()}
        )
    else:
        aliases.add(Path(raw).name.casefold())
    return aliases


def _canonical_repo_identity(value: Any) -> str | None:
    remote = normalize_repo_remote(value)
    if remote:
        return remote
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip().casefold()
    parts = raw.split("__")
    if len(parts) >= 2 and parts[0] and parts[1]:
        return f"{parts[0]}/{parts[1]}"
    return None


def manifest_repo_identities(document: Mapping[str, Any]) -> list[str]:
    """Return canonical owner/repository identities, preferring explicit remotes."""
    provenance = document.get("snapshot_provenance")
    repositories = (
        provenance.get("repositories") if isinstance(provenance, Mapping) else None
    )
    identities: set[str] = set()
    fallback: set[str] = set()
    for record in repositories if isinstance(repositories, list) else []:
        if not isinstance(record, Mapping):
            continue
        remote = normalize_repo_remote(record.get("repo_remote"))
        if remote:
            identities.add(remote)
            continue
        for key in ("name", "repo"):
            identity = _canonical_repo_identity(record.get(key))
            if identity:
                fallback.add(identity)
    return sorted(identities or fallback)


def _normalized_created_at(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BundleCatalogError("bundle created_at is missing or invalid")
    raw = value.strip()
    candidate = f"{raw[:-1]}+00:00" if raw.endswith(("Z", "z")) else raw
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise BundleCatalogError("bundle created_at is not valid ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise BundleCatalogError("bundle created_at must include a timezone")
    return (
        parsed.astimezone(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def manifest_repo_aliases(document: Mapping[str, Any]) -> list[str]:
    aliases: set[str] = set()
    provenance = document.get("snapshot_provenance")
    repositories = (
        provenance.get("repositories") if isinstance(provenance, Mapping) else None
    )
    for record in repositories if isinstance(repositories, list) else []:
        if not isinstance(record, Mapping):
            continue
        aliases.update(_canonical_name_aliases(record.get("name")))
        aliases.update(_canonical_name_aliases(record.get("repo")))
        remote = normalize_repo_remote(record.get("repo_remote"))
        if remote:
            aliases.add(remote)
            owner, repo = remote.split("/", 1)
            aliases.update({f"{owner}__{repo}", repo})
    return sorted(aliases)


def _health_metadata_issue(
    *,
    expected_sha256: Any,
    expected_bytes: Any,
    require_integrity: bool,
) -> str | None:
    if not require_integrity:
        return None
    if (
        not isinstance(expected_bytes, int)
        or isinstance(expected_bytes, bool)
        or expected_bytes < 0
    ):
        return "health artifact byte size missing or invalid in manifest"
    if not isinstance(expected_sha256, str) or not _SHA256_RE.fullmatch(
        expected_sha256
    ):
        return "health artifact sha256 missing or invalid in manifest"
    return None


def _health_content_issue(
    raw: bytes,
    *,
    expected_sha256: Any,
    expected_bytes: Any,
) -> str | None:
    if isinstance(expected_bytes, int) and len(raw) != expected_bytes:
        return "health artifact byte size does not match manifest"
    if (
        isinstance(expected_sha256, str)
        and _SHA256_RE.fullmatch(expected_sha256)
        and _sha256_bytes(raw) != expected_sha256
    ):
        return "health artifact sha256 does not match manifest"
    return None


def _health_binding_issue(
    document: Mapping[str, Any],
    *,
    expected_manifest_path: Path | None,
    expected_manifest_run_id: Any,
    expected_manifest_sha256: str | None,
    require_manifest_binding: bool,
) -> str | None:
    if not require_manifest_binding:
        return None
    if expected_manifest_path is None:
        return "post_emit_health manifest path expectation is missing"
    binding_status, binding_detail = post_health_binding_status(
        document,
        resolved_manifest=expected_manifest_path,
        manifest_run_id=expected_manifest_run_id,
        manifest_sha256=expected_manifest_sha256,
    )
    return None if binding_status == "pass" else binding_detail


def _health_document_status(
    document: Mapping[str, Any],
    raw: bytes,
    *,
    expected_sha256: Any = None,
    expected_bytes: Any = None,
    require_integrity: bool = False,
    expected_manifest_path: Path | None = None,
    expected_manifest_run_id: Any = None,
    expected_manifest_sha256: str | None = None,
    require_manifest_binding: bool = False,
) -> tuple[str, str | None]:
    issue = _health_metadata_issue(
        expected_sha256=expected_sha256,
        expected_bytes=expected_bytes,
        require_integrity=require_integrity,
    )
    if issue is not None:
        return "invalid", issue
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return "invalid", "health artifact is not valid UTF-8 JSON"
    if not isinstance(decoded, dict):
        return "invalid", "health artifact must be a JSON object"
    if decoded != document:
        return "invalid", "health document does not match supplied artifact bytes"
    issue = _health_content_issue(
        raw,
        expected_sha256=expected_sha256,
        expected_bytes=expected_bytes,
    )
    if issue is not None:
        return "invalid", issue
    status = document.get("status") or document.get("verdict")
    if status != "pass":
        return "invalid", f"health status is {status!r}, expected 'pass'"
    issue = _health_binding_issue(
        document,
        expected_manifest_path=expected_manifest_path,
        expected_manifest_run_id=expected_manifest_run_id,
        expected_manifest_sha256=expected_manifest_sha256,
        require_manifest_binding=require_manifest_binding,
    )
    return ("invalid", issue) if issue is not None else ("pass", None)


def _health_json_status(
    path: Path,
    *,
    expected_sha256: Any = None,
    expected_bytes: Any = None,
    require_integrity: bool = False,
    expected_manifest_path: Path | None = None,
    expected_manifest_run_id: Any = None,
    expected_manifest_sha256: str | None = None,
    require_manifest_binding: bool = False,
    read_root: Path | None = None,
) -> tuple[str, str | None]:
    issue = _health_metadata_issue(
        expected_sha256=expected_sha256,
        expected_bytes=expected_bytes,
        require_integrity=require_integrity,
    )
    if issue is not None:
        return "invalid", issue
    try:
        document, raw = _load_json_object(
            path,
            MAX_HEALTH_BYTES,
            root=read_root,
            label="bundle artifact",
        )
    except BundleCatalogError as exc:
        return "invalid", str(exc)
    return _health_document_status(
        document,
        raw,
        expected_sha256=expected_sha256,
        expected_bytes=expected_bytes,
        require_integrity=require_integrity,
        expected_manifest_path=expected_manifest_path,
        expected_manifest_run_id=expected_manifest_run_id,
        expected_manifest_sha256=expected_manifest_sha256,
        require_manifest_binding=require_manifest_binding,
    )


def _post_health_issue(
    path: Path,
    document: Mapping[str, Any],
    *,
    manifest_sha256: str,
    post_health_source: tuple[Path, Mapping[str, Any], bytes] | None,
    read_root: Path | None,
) -> str | None:
    links = document.get("links") if isinstance(document.get("links"), Mapping) else {}
    post_path = _safe_child(path.parent, links.get("post_emit_health_path"))
    if post_path is None:
        return "post_emit_health path missing or invalid"
    if post_health_source is None:
        status, reason = _health_json_status(
            post_path,
            expected_manifest_path=path,
            expected_manifest_run_id=document.get("run_id"),
            expected_manifest_sha256=manifest_sha256,
            require_manifest_binding=True,
            read_root=read_root,
        )
        return None if status == "pass" else reason or "post_emit_health invalid"

    source_path, source_document, source_raw = post_health_source
    if source_path.resolve() != post_path:
        return "supplied post_emit_health path does not match manifest link"
    status, reason = _health_document_status(
        source_document,
        source_raw,
        expected_manifest_path=path,
        expected_manifest_run_id=document.get("run_id"),
        expected_manifest_sha256=manifest_sha256,
        require_manifest_binding=True,
    )
    return None if status == "pass" else reason or "post_emit_health invalid"


def _candidate_health(
    path: Path,
    document: Mapping[str, Any],
    *,
    manifest_sha256: str,
    post_health_source: tuple[Path, Mapping[str, Any], bytes] | None = None,
    read_root: Path | None = None,
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    links = document.get("links") if isinstance(document.get("links"), Mapping) else {}
    for key in (
        "agent_export_gate_status",
        "bundle_surface_validation_status",
        "export_safety_report_status",
    ):
        value = links.get(key)
        if value is not None and value != "pass":
            reasons.append(f"{key}={value!r}")

    artifacts = (
        document.get("artifacts") if isinstance(document.get("artifacts"), list) else []
    )
    output_health = next(
        (
            item
            for item in artifacts
            if isinstance(item, Mapping) and item.get("role") == "output_health"
        ),
        None,
    )
    if not isinstance(output_health, Mapping):
        reasons.append("output_health artifact missing")
    else:
        output_path = _safe_child(path.parent, output_health.get("path"))
        if output_path is None:
            reasons.append("output_health path invalid")
        else:
            status, reason = _health_json_status(
                output_path,
                expected_sha256=output_health.get("sha256"),
                expected_bytes=output_health.get("bytes"),
                require_integrity=True,
                read_root=read_root,
            )
            if status != "pass":
                reasons.append(reason or "output_health invalid")

    post_issue = _post_health_issue(
        path,
        document,
        manifest_sha256=manifest_sha256,
        post_health_source=post_health_source,
        read_root=read_root,
    )
    if post_issue is not None:
        reasons.append(post_issue)

    return ("pass", []) if not reasons else ("invalid", reasons)


def inspect_bundle_health_documents(
    bundle_manifest: str | Path,
    *,
    manifest_document: Mapping[str, Any],
    manifest_bytes: bytes,
    post_health_path: str | Path,
    post_health_document: Mapping[str, Any],
    post_health_bytes: bytes,
) -> dict[str, Any]:
    """Inspect whole-bundle health from one already-read manifest/health pair."""
    path = resolve_manifest_path(bundle_manifest)
    try:
        decoded_manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        decoded_manifest = None
    if (
        not isinstance(decoded_manifest, dict)
        or decoded_manifest != manifest_document
        or not is_bundle_manifest(manifest_document)
        or not isinstance(manifest_document.get("run_id"), str)
        or not isinstance(manifest_document.get("artifacts"), list)
    ):
        return {
            "kind": "repoground.bundle_health",
            "version": VERSION,
            "status": "invalid",
            "health_status": "invalid",
            "bundle_manifest": str(path),
            "manifest_sha256": None,
            "reasons": ["invalid RepoGround bundle manifest"],
            "mutation_boundary": {"writes": [], "read_paths_do_not_refresh": True},
        }
    manifest_sha256 = _sha256_bytes(manifest_bytes)
    health_status, reasons = _candidate_health(
        path,
        manifest_document,
        manifest_sha256=manifest_sha256,
        post_health_source=(
            Path(post_health_path).expanduser().resolve(),
            post_health_document,
            post_health_bytes,
        ),
    )
    return {
        "kind": "repoground.bundle_health",
        "version": VERSION,
        "status": "available" if health_status == "pass" else "unhealthy",
        "health_status": health_status,
        "bundle_manifest": str(path),
        "manifest_sha256": manifest_sha256,
        "reasons": reasons,
        "mutation_boundary": {"writes": [], "read_paths_do_not_refresh": True},
    }


def inspect_bundle_health(bundle_manifest: str | Path) -> dict[str, Any]:
    """Inspect manifest-bound health without selecting or refreshing a bundle."""
    path = resolve_manifest_path(bundle_manifest)
    try:
        document, raw = _manifest_document(path)
    except BundleCatalogError as exc:
        return {
            "kind": "repoground.bundle_health",
            "version": VERSION,
            "status": "invalid",
            "health_status": "invalid",
            "bundle_manifest": str(path),
            "manifest_sha256": None,
            "reasons": [str(exc)],
            "mutation_boundary": {"writes": [], "read_paths_do_not_refresh": True},
        }
    health_status, reasons = _candidate_health(
        path, document, manifest_sha256=_sha256_bytes(raw)
    )
    return {
        "kind": "repoground.bundle_health",
        "version": VERSION,
        "status": "available" if health_status == "pass" else "unhealthy",
        "health_status": health_status,
        "bundle_manifest": str(path),
        "manifest_sha256": _sha256_bytes(raw),
        "reasons": reasons,
        "mutation_boundary": {"writes": [], "read_paths_do_not_refresh": True},
    }


def _manifest_paths(root: Path) -> list[Path]:
    if root.is_file():
        return [root]
    if not root.is_dir():
        return (
            [root]
            if root.name.endswith(MANIFEST_SUFFIX)
            and (root.exists() or root.is_symlink())
            else []
        )
    paths: list[Path] = []
    for path in root.rglob(f"*{MANIFEST_SUFFIX}"):
        relative = path.relative_to(root)
        if any(part.startswith(".") for part in relative.parts[:-1]):
            continue
        paths.append(path)
        if len(paths) > MAX_DISCOVERED_MANIFESTS:
            raise BundleCatalogError(
                f"bundle discovery exceeded {MAX_DISCOVERED_MANIFESTS} manifests"
            )
    return sorted(paths)


def discover_bundle_catalog(bundle_root: str | Path) -> dict[str, Any]:
    selected_root = _absolute_path(Path(bundle_root))
    root = selected_root.resolve()
    if selected_root.is_dir():
        discovery_root = root
        read_root = root
    else:
        discovery_root = selected_root
        read_root = selected_root.parent.resolve()
    candidates: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []
    seen_resolved_paths: set[Path] = set()
    for selected_path in _manifest_paths(discovery_root):
        try:
            stable_read = _read_bounded_stable(
                selected_path,
                MAX_MANIFEST_BYTES,
                root=read_root,
                label="bundle manifest candidate",
            )
            path = stable_read.resolved_path
            if path in seen_resolved_paths:
                continue
            seen_resolved_paths.add(path)
            document = _decode_json_object(path, stable_read.raw)
            document, raw = _validate_manifest_document(
                path,
                document,
                stable_read.raw,
            )
        except BundleCatalogError as exc:
            rejected.append(
                {"manifest_path": str(selected_path), "reason": str(exc)}
            )
            continue
        try:
            created_at_utc = _normalized_created_at(document.get("created_at"))
            timestamp_status = "valid"
            timestamp_reason = None
        except BundleCatalogError as exc:
            created_at_utc = None
            timestamp_status = "invalid"
            timestamp_reason = str(exc)
        health_status, health_reasons = _candidate_health(
            path,
            document,
            manifest_sha256=_sha256_bytes(raw),
            read_root=read_root,
        )
        try:
            _assert_stable_read_path(
                selected_path=stable_read.selected_path,
                resolved_path=stable_read.resolved_path,
                identity=stable_read.identity,
                root=read_root,
                label="bundle manifest candidate",
            )
        except BundleCatalogError as exc:
            rejected.append(
                {"manifest_path": str(selected_path), "reason": str(exc)}
            )
            continue
        candidates.append(
            {
                "stem": path.name[: -len(MANIFEST_SUFFIX)],
                "manifest_path": str(path),
                "manifest_sha256": _sha256_bytes(raw),
                "run_id": document.get("run_id"),
                "created_at": document.get("created_at"),
                "created_at_utc": created_at_utc,
                "timestamp_status": timestamp_status,
                "timestamp_reason": timestamp_reason,
                "repo_aliases": manifest_repo_aliases(document),
                "repo_identities": manifest_repo_identities(document),
                "health_status": health_status,
                "health_reasons": health_reasons,
                "selection_eligible": (
                    health_status == "pass" and timestamp_status == "valid"
                ),
            }
        )
    return {
        "kind": KIND,
        "version": VERSION,
        "status": "available" if candidates else "missing",
        "bundle_root": str(root),
        "candidate_count": len(candidates),
        "candidates": candidates,
        "rejected_count": len(rejected),
        "rejected": rejected[:50],
        "mutation_boundary": {"writes": [], "read_paths_do_not_refresh": True},
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }


def _normalized_requested_repo(repo: Any) -> tuple[str | None, bool]:
    if repo is None:
        return None, False
    if not isinstance(repo, str) or not repo.strip():
        raise BundleCatalogError("repo must be null or a non-empty repository identity")
    raw = repo.strip()
    canonical = _canonical_repo_identity(raw)
    if canonical:
        return canonical, True
    return raw.casefold(), False


def _candidate_matches_repo(
    candidate: Mapping[str, Any], requested_repo: str | None, qualified: bool
) -> bool:
    if requested_repo is None:
        return True
    if qualified:
        identities = candidate.get("repo_identities")
        return isinstance(identities, list) and requested_repo in identities
    aliases = candidate.get("repo_aliases")
    return isinstance(aliases, list) and requested_repo in aliases


def _short_repo_identity_groups(
    matches: list[dict[str, Any]], requested_repo: str
) -> set[str]:
    groups: set[str] = set()
    for candidate in matches:
        identities = candidate.get("repo_identities")
        if isinstance(identities, list) and identities:
            groups.update(str(identity) for identity in identities)
        else:
            groups.add(f"unqualified:{requested_repo}")
    return groups


def select_bundle_manifest(
    bundle_root: str | Path,
    *,
    repo: str | None = None,
    stem: str | None = None,
    require_healthy: bool = True,
) -> dict[str, Any]:
    catalog = discover_bundle_catalog(bundle_root)
    requested_repo, requested_repo_qualified = _normalized_requested_repo(repo)
    if stem is not None and (not isinstance(stem, str) or not stem.strip()):
        raise BundleCatalogError("stem must be null or a non-empty string")

    identity_matches = []
    for candidate in catalog["candidates"]:
        if stem is not None and candidate["stem"] != stem:
            continue
        if not _candidate_matches_repo(
            candidate, requested_repo, requested_repo_qualified
        ):
            continue
        if candidate.get("timestamp_status") != "valid":
            continue
        identity_matches.append(candidate)

    if requested_repo is not None and not requested_repo_qualified:
        identity_groups = _short_repo_identity_groups(identity_matches, requested_repo)
        if len(identity_groups) > 1:
            return {
                "kind": "repoground.bundle_selection",
                "version": VERSION,
                "status": "ambiguous",
                "bundle_root": catalog["bundle_root"],
                "requested_repo": requested_repo,
                "requested_stem": stem,
                "selected": None,
                "reason": "repository_identity_ambiguous",
                "repo_identity_groups": sorted(identity_groups),
                "matches": identity_matches,
                "does_not_establish": list(DOES_NOT_ESTABLISH),
            }

    matches = [
        candidate
        for candidate in identity_matches
        if not require_healthy or candidate["health_status"] == "pass"
    ]
    if not matches:
        return {
            "kind": "repoground.bundle_selection",
            "version": VERSION,
            "status": "missing",
            "bundle_root": catalog["bundle_root"],
            "requested_repo": requested_repo,
            "requested_stem": stem,
            "selected": None,
            "reason": "no_matching_healthy_bundle"
            if require_healthy
            else "no_matching_bundle",
            "candidate_count": catalog["candidate_count"],
            "does_not_establish": list(DOES_NOT_ESTABLISH),
        }

    matches.sort(
        key=lambda item: (
            str(item.get("created_at_utc") or ""),
            str(item.get("run_id") or ""),
            str(item["manifest_path"]),
        ),
        reverse=True,
    )
    newest_key = (
        str(matches[0].get("created_at_utc") or ""),
        str(matches[0].get("run_id") or ""),
    )
    tied = [
        item
        for item in matches
        if (str(item.get("created_at_utc") or ""), str(item.get("run_id") or ""))
        == newest_key
    ]
    if len(tied) != 1:
        return {
            "kind": "repoground.bundle_selection",
            "version": VERSION,
            "status": "ambiguous",
            "bundle_root": catalog["bundle_root"],
            "requested_repo": requested_repo,
            "requested_stem": stem,
            "selected": None,
            "reason": "newest_bundle_identity_ambiguous",
            "matches": tied,
            "does_not_establish": list(DOES_NOT_ESTABLISH),
        }
    return {
        "kind": "repoground.bundle_selection",
        "version": VERSION,
        "status": "available",
        "bundle_root": catalog["bundle_root"],
        "requested_repo": requested_repo,
        "requested_stem": stem,
        "selected": matches[0],
        "match_count": len(matches),
        "selection_policy": "newest_healthy_by_created_at_utc_then_run_id",
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }


def checkout_repo_identity(repo_root: str | Path) -> str:
    """Derive owner/repository from the configured origin without network access."""
    root = Path(repo_root).expanduser().resolve()
    env = os.environ.copy()
    env.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_TERMINAL_PROMPT": "0",
        }
    )
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), "config", "--get", "remote.origin.url"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            env=env,
        )
    except (OSError, subprocess.SubprocessError):
        completed = None
    if completed is not None and completed.returncode == 0:
        identity = normalize_repo_remote(completed.stdout.strip())
        if identity:
            return identity
    if root.name:
        return root.name.casefold()
    raise BundleCatalogError("repository identity could not be derived")
