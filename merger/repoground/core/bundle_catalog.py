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
import subprocess
from pathlib import Path
from typing import Any, Mapping

from merger.repoground.core.bundle_identity import is_bundle_manifest

KIND = "repoground.bundle_catalog"
VERSION = "v1"
MANIFEST_SUFFIX = ".bundle.manifest.json"
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_HEALTH_BYTES = 4 * 1024 * 1024
MAX_DISCOVERED_MANIFESTS = 2000
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


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_bounded(path: Path, max_bytes: int) -> bytes:
    try:
        with path.open("rb") as handle:
            data = handle.read(max_bytes + 1)
    except OSError as exc:
        raise BundleCatalogError(f"file cannot be read: {path}") from exc
    if len(data) > max_bytes:
        raise BundleCatalogError(f"file exceeds bounded catalog read: {path}")
    return data


def _load_json_object(path: Path, max_bytes: int) -> tuple[dict[str, Any], bytes]:
    raw = _read_bounded(path, max_bytes)
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BundleCatalogError(f"file is not valid UTF-8 JSON: {path}") from exc
    if not isinstance(value, dict):
        raise BundleCatalogError(f"JSON document must be an object: {path}")
    return value, raw


def _manifest_document(path: Path) -> tuple[dict[str, Any], bytes]:
    document, raw = _load_json_object(path, MAX_MANIFEST_BYTES)
    if (
        not is_bundle_manifest(document)
        or not isinstance(document.get("run_id"), str)
        or not isinstance(document.get("artifacts"), list)
    ):
        raise BundleCatalogError(f"invalid RepoGround bundle manifest: {path}")
    return document, raw


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


def _health_json_status(
    path: Path,
    *,
    expected_sha256: Any = None,
    expected_bytes: Any = None,
    require_integrity: bool = False,
) -> tuple[str, str | None]:
    if require_integrity:
        if (
            not isinstance(expected_bytes, int)
            or isinstance(expected_bytes, bool)
            or expected_bytes < 0
        ):
            return "invalid", "health artifact byte size missing or invalid in manifest"
        if not isinstance(expected_sha256, str) or not _SHA256_RE.fullmatch(
            expected_sha256
        ):
            return "invalid", "health artifact sha256 missing or invalid in manifest"
    try:
        document, raw = _load_json_object(path, MAX_HEALTH_BYTES)
    except BundleCatalogError as exc:
        return "invalid", str(exc)
    if isinstance(expected_bytes, int) and len(raw) != expected_bytes:
        return "invalid", "health artifact byte size does not match manifest"
    if isinstance(expected_sha256, str) and _SHA256_RE.fullmatch(expected_sha256):
        if _sha256_bytes(raw) != expected_sha256:
            return "invalid", "health artifact sha256 does not match manifest"
    status = document.get("status") or document.get("verdict")
    if status == "pass":
        return "pass", None
    return "invalid", f"health status is {status!r}, expected 'pass'"


def _candidate_health(path: Path, document: Mapping[str, Any]) -> tuple[str, list[str]]:
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
            )
            if status != "pass":
                reasons.append(reason or "output_health invalid")

    post_path = _safe_child(path.parent, links.get("post_emit_health_path"))
    if post_path is None:
        reasons.append("post_emit_health path missing or invalid")
    else:
        status, reason = _health_json_status(post_path)
        if status != "pass":
            reasons.append(reason or "post_emit_health invalid")

    return ("pass", []) if not reasons else ("invalid", reasons)


def _manifest_paths(root: Path) -> list[Path]:
    if root.is_file():
        return [root]
    if not root.is_dir():
        return []
    paths: list[Path] = []
    for path in root.rglob(f"*{MANIFEST_SUFFIX}"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if any(part.startswith(".") for part in relative.parts[:-1]):
            continue
        paths.append(path.resolve())
        if len(paths) > MAX_DISCOVERED_MANIFESTS:
            raise BundleCatalogError(
                f"bundle discovery exceeded {MAX_DISCOVERED_MANIFESTS} manifests"
            )
    return sorted(set(paths))


def discover_bundle_catalog(bundle_root: str | Path) -> dict[str, Any]:
    root = Path(bundle_root).expanduser().resolve()
    candidates: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []
    for path in _manifest_paths(root):
        try:
            document, raw = _manifest_document(path)
        except BundleCatalogError as exc:
            rejected.append({"manifest_path": str(path), "reason": str(exc)})
            continue
        health_status, health_reasons = _candidate_health(path, document)
        candidates.append(
            {
                "stem": path.name[: -len(MANIFEST_SUFFIX)],
                "manifest_path": str(path),
                "manifest_sha256": _sha256_bytes(raw),
                "run_id": document.get("run_id"),
                "created_at": document.get("created_at"),
                "repo_aliases": manifest_repo_aliases(document),
                "health_status": health_status,
                "health_reasons": health_reasons,
                "selection_eligible": health_status == "pass",
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


def _normalized_requested_repo(repo: Any) -> str | None:
    if repo is None:
        return None
    if not isinstance(repo, str) or not repo.strip():
        raise BundleCatalogError("repo must be null or a non-empty repository identity")
    return normalize_repo_remote(repo) or repo.strip().casefold()


def select_bundle_manifest(
    bundle_root: str | Path,
    *,
    repo: str | None = None,
    stem: str | None = None,
    require_healthy: bool = True,
) -> dict[str, Any]:
    catalog = discover_bundle_catalog(bundle_root)
    requested_repo = _normalized_requested_repo(repo)
    if stem is not None and (not isinstance(stem, str) or not stem.strip()):
        raise BundleCatalogError("stem must be null or a non-empty string")

    matches = []
    for candidate in catalog["candidates"]:
        if stem is not None and candidate["stem"] != stem:
            continue
        if (
            requested_repo is not None
            and requested_repo not in candidate["repo_aliases"]
        ):
            continue
        if require_healthy and not candidate["selection_eligible"]:
            continue
        matches.append(candidate)
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
            str(item.get("created_at") or ""),
            str(item.get("run_id") or ""),
            str(item["manifest_path"]),
        ),
        reverse=True,
    )
    newest_key = (
        str(matches[0].get("created_at") or ""),
        str(matches[0].get("run_id") or ""),
    )
    tied = [
        item
        for item in matches
        if (str(item.get("created_at") or ""), str(item.get("run_id") or ""))
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
        "selection_policy": "newest_healthy_by_created_at_then_run_id",
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
