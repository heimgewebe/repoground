"""Latest-complete RepoBrief bundle registry.

The registry is a small, machine-readable pointer to the latest known complete
bundle for a repository/ref lane. It is not an automatic refresh mechanism.
Read paths may compare recorded snapshot provenance to an explicitly supplied
local repo HEAD, but they must never create snapshots, mutate Git, or update the
registry as a side effect.
"""

from __future__ import annotations

import datetime as _dt
import fcntl
import hashlib
import json
import os
import secrets
import stat as statmod
import subprocess
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from typing import Any, Mapping

KIND = "repobrief.latest_complete_registry"
VERSION = "v2"
LEGACY_VERSION = "v1"
SUPPORTED_VERSIONS = (LEGACY_VERSION, VERSION)
STATUS_KIND = "repobrief.latest_complete_status"
WRITE_KIND = "repobrief.latest_complete_registry_write"

FRESHNESS_VALUES = ("fresh", "stale", "unknown", "not_comparable")
HEALTH_VALUES = ("pass", "warn", "fail", "unknown")
MAX_FUTURE_SKEW_SECONDS = 300


class LatestCompletePublicationError(ValueError):
    """Publication failed with a machine-readable mutation receipt."""

    def __init__(self, message: str, receipt: Mapping[str, Any]):
        super().__init__(message)
        self.receipt = dict(receipt)


DOES_NOT_ESTABLISH = (
    "truth",
    "correctness",
    "completeness",
    "runtime_behavior",
    "test_sufficiency",
    "regression_absence",
    "repo_understood",
    "claims_true",
    "forensic_ready",
    "freshness_against_remote",
    "merge_readiness",
    "agent_quality_improvement",
)


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _resolve_path(value: str | Path, *, label: str) -> Path:
    try:
        return Path(value).expanduser().resolve()
    except (OSError, RuntimeError) as exc:
        raise ValueError(f"{label} cannot be resolved safely: {value}") from exc


def _prepare_directory_tree(path: Path, created: list[Path]) -> Path:
    resolved = _resolve_path(path, label="latest-complete publication directory")
    current = Path(resolved.anchor)
    for part in resolved.parts[1:]:
        current /= part
        try:
            os.mkdir(current, 0o777)
        except FileExistsError:
            try:
                metadata = os.stat(current, follow_symlinks=False)
            except OSError as exc:
                raise OSError(
                    f"latest-complete publication directory cannot be inspected: {current}"
                ) from exc
            if not statmod.S_ISDIR(metadata.st_mode):
                raise NotADirectoryError(
                    f"latest-complete publication path component is not a directory: {current}"
                )
        except OSError:
            raise
        else:
            created.append(current)
    return resolved


def _decode_json_object(payload: bytes, *, path: Path, label: str) -> dict[str, Any]:
    try:
        data = json.loads(payload.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} is not valid JSON: {path}") from exc
    except UnicodeError as exc:
        raise ValueError(f"{label} is not valid UTF-8: {path}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{label} must be a JSON object")
    return data


def _capture_json_object(path: Path, *, label: str) -> tuple[dict[str, Any], bytes, str]:
    try:
        payload = path.read_bytes()
    except FileNotFoundError as exc:
        raise ValueError(f"{label} does not exist: {path}") from exc
    except OSError as exc:
        raise ValueError(f"{label} cannot be read: {path}") from exc
    return (
        _decode_json_object(payload, path=path, label=label),
        payload,
        hashlib.sha256(payload).hexdigest(),
    )


def _read_json_object(path: Path, *, label: str) -> dict[str, Any]:
    return _capture_json_object(path, label=label)[0]


def _manifest_stem(path: Path) -> str:
    suffix = ".bundle.manifest.json"
    if path.name.endswith(suffix):
        return path.name[: -len(suffix)]
    return path.stem


def _relative_or_absolute(target: Path, base_dir: Path | None) -> str:
    target = _resolve_path(target, label="latest-complete artifact path")
    if base_dir is None:
        return str(target)
    try:
        resolved_base = _resolve_path(
            base_dir, label="latest-complete registry base directory"
        )
        return Path(os.path.relpath(target, resolved_base)).as_posix()
    except ValueError:
        return str(target)


def _safe_bundle_path(registry_path: Path, raw_path: Any) -> Path | None:
    if not isinstance(raw_path, str) or not raw_path:
        return None
    candidate = _resolve_path(
        registry_path.parent / raw_path, label="latest-complete bundle path"
    )
    if candidate.is_file():
        return candidate
    absolute = _resolve_path(raw_path, label="latest-complete absolute bundle path")
    if absolute.is_file():
        return absolute
    return candidate


def _normalized_remote(value: str) -> str | None:
    remote = value.strip().rstrip("/")
    if not remote:
        return None
    if "://" not in remote:
        if "@" not in remote:
            return None
        _, host_path = remote.split("@", 1)
        if ":" not in host_path:
            return None
        host, path = host_path.split(":", 1)
        if not host or not path:
            return None
        return f"ssh://{host.lower()}/{path.lstrip('/')}".rstrip("/")
    parsed = urlsplit(remote)
    if parsed.scheme.lower() == "file" or parsed.hostname is None:
        return None
    host = parsed.hostname.lower()
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    netloc = host
    if parsed.port is not None:
        netloc += f":{parsed.port}"
    return urlunsplit(
        (parsed.scheme.lower(), netloc, parsed.path.rstrip("/"), "", "")
    )


def _root_identity(value: str) -> str | None:
    root = Path(value.strip()).expanduser()
    if not root.is_absolute():
        return None
    normalized = os.path.normpath(str(root))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _source_repositories(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    provenance = manifest.get("snapshot_provenance")
    repositories = (
        provenance.get("repositories") if isinstance(provenance, dict) else None
    )
    if not isinstance(repositories, list):
        return []
    result: list[dict[str, Any]] = []
    for repo in repositories:
        if not isinstance(repo, dict):
            continue
        raw_remote = repo.get("repo_remote")
        remote = (
            _normalized_remote(raw_remote)
            if isinstance(raw_remote, str) and raw_remote.strip()
            else None
        )
        remote_sanitized = (
            isinstance(raw_remote, str)
            and remote is not None
            and raw_remote.strip().rstrip("/") != remote
        )
        raw_root = repo.get("repo_root")
        root_sha256 = (
            _root_identity(raw_root)
            if isinstance(raw_root, str) and raw_root.strip()
            else None
        )
        result.append(
            {
                "name": repo.get("name") if isinstance(repo.get("name"), str) else None,
                "repo_remote": remote,
                "repo_remote_sanitized": remote_sanitized,
                "repo_root_recorded": root_sha256 is not None,
                "repo_root_sha256": root_sha256,
                "source_identity_basis": "repo_remote" if remote else ("repo_root_sha256" if root_sha256 else "missing"),
                "git_commit": repo.get("git_commit")
                if isinstance(repo.get("git_commit"), str)
                else None,
                "git_dirty": repo.get("git_dirty")
                if isinstance(repo.get("git_dirty"), bool)
                else None,
                "git_branch": repo.get("git_branch")
                if isinstance(repo.get("git_branch"), str)
                else None,
                "provenance_status": repo.get("provenance_status")
                if isinstance(repo.get("provenance_status"), str)
                else "unknown",
                "freshness_basis": repo.get("freshness_basis")
                if isinstance(repo.get("freshness_basis"), str)
                else "unknown",
            }
        )
    return result


def _primary_source_commit(
    repositories: list[dict[str, Any]],
) -> tuple[str | None, str]:
    present = [
        repo
        for repo in repositories
        if repo.get("provenance_status") == "present"
        and isinstance(repo.get("git_commit"), str)
        and repo.get("git_commit")
    ]
    if not present:
        return None, "snapshot_commit_missing"
    if len(present) > 1:
        commits = {repo["git_commit"] for repo in present}
        if len(commits) == 1:
            return present[0]["git_commit"], "single_commit_multi_repo"
        return None, "multiple_source_commits_not_comparable"
    return present[0]["git_commit"], "single_repo_commit"


def _artifact_by_role(manifest: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    artifacts = manifest.get("artifacts")
    result: dict[str, dict[str, Any]] = {}
    if not isinstance(artifacts, list):
        return result
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        role = artifact.get("role")
        if isinstance(role, str) and role not in result:
            result[role] = artifact
    return result


def _linked_path_for_role(manifest: Mapping[str, Any], role: str) -> str | None:
    role_to_link = {
        "post_emit_health": "post_emit_health_path",
        "bundle_surface_validation": "bundle_surface_validation_path",
        "output_health": "output_health_path",
        "agent_export_gate": "agent_export_gate_path",
        "export_safety_report": "export_safety_report_path",
    }
    links = manifest.get("links")
    key = role_to_link.get(role)
    if isinstance(links, dict) and key and isinstance(links.get(key), str):
        return links[key]
    return None


def _status_from_doc(role: str, doc: Mapping[str, Any]) -> str | None:
    if role == "output_health":
        value = doc.get("verdict") or doc.get("status")
    else:
        value = doc.get("status") or doc.get("verdict")
    if isinstance(value, str) and value in {"pass", "warn", "fail"}:
        return value
    if isinstance(value, str) and value in {"blocked", "invalid"}:
        return "fail"
    return None


def _health_signals(manifest_path: Path, manifest: Mapping[str, Any]) -> dict[str, Any]:
    artifacts = _artifact_by_role(manifest)
    signals: dict[str, Any] = {}
    for role in (
        "output_health",
        "post_emit_health",
        "bundle_surface_validation",
        "agent_export_gate",
        "export_safety_report",
    ):
        artifact = artifacts.get(role)
        raw_path = artifact.get("path") if isinstance(artifact, dict) else None
        if raw_path is None:
            raw_path = _linked_path_for_role(manifest, role)
        if not isinstance(raw_path, str) or not raw_path:
            signals[role] = {"status": "unknown", "path": None, "reason": "not_listed"}
            continue
        candidate = _resolve_path(
            manifest_path.parent / raw_path, label=f"{role} sidecar path"
        )
        try:
            candidate.relative_to(
                _resolve_path(manifest_path.parent, label="bundle root")
            )
        except ValueError:
            signals[role] = {
                "status": "fail",
                "path": raw_path,
                "reason": "path_escapes_bundle_root",
            }
            continue
        if not candidate.is_file():
            signals[role] = {
                "status": "unknown",
                "path": raw_path,
                "reason": "file_missing",
            }
            continue
        try:
            payload = candidate.read_bytes()
            doc = json.loads(payload.decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            signals[role] = {
                "status": "fail",
                "path": raw_path,
                "reason": "unreadable",
                "error": str(exc),
            }
            continue
        if not isinstance(doc, dict):
            signals[role] = {"status": "fail", "path": raw_path, "reason": "not_object"}
            continue
        status = _status_from_doc(role, doc)
        signals[role] = {
            "status": status or "unknown",
            "path": raw_path,
            "reason": None if status else "status_missing_or_unrecognized",
            "kind": doc.get("kind") if isinstance(doc.get("kind"), str) else None,
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
    return signals


def _aggregate_health(signals: Mapping[str, Any]) -> str:
    statuses = [
        signal.get("status")
        for signal in signals.values()
        if isinstance(signal, Mapping) and isinstance(signal.get("status"), str)
    ]
    if any(status == "fail" for status in statuses):
        return "fail"
    if any(status == "warn" for status in statuses):
        return "warn"
    if any(status == "pass" for status in statuses):
        return "pass"
    return "unknown"


def _unknown_freshness(reason: str, *, checked_at: str | None = None) -> dict[str, Any]:
    return {
        "status": "unknown",
        "reason": reason,
        "checked_at": checked_at,
        "snapshot_commit": None,
        "live_head": None,
        "head_drift": None,
        "basis": "git_commit",
    }


def _git(repo: Path, *args: str) -> tuple[str | None, str | None]:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        return None, str(exc)
    if result.returncode != 0:
        return None, (result.stderr or result.stdout or "git command failed").strip()
    return result.stdout.strip(), None


def evaluate_registry_freshness(
    registry: Mapping[str, Any],
    *,
    repo: str | Path | None = None,
    checked_at: str | None = None,
) -> dict[str, Any]:
    checked_at = checked_at or _now_iso()
    snapshot_commit = (
        registry.get("source", {}).get("commit")
        if isinstance(registry.get("source"), Mapping)
        else None
    )
    if not isinstance(snapshot_commit, str) or not snapshot_commit:
        return _unknown_freshness("snapshot_commit_missing", checked_at=checked_at)
    if repo is None:
        result = _unknown_freshness("live_repo_not_provided", checked_at=checked_at)
        result["snapshot_commit"] = snapshot_commit
        return result
    repo_path = _resolve_path(repo, label="live repository")
    if not repo_path.is_dir():
        result = _unknown_freshness("live_repo_not_directory", checked_at=checked_at)
        result["snapshot_commit"] = snapshot_commit
        return result
    live_head, err = _git(repo_path, "rev-parse", "HEAD")
    if err is not None or not live_head:
        result = _unknown_freshness("live_head_unavailable", checked_at=checked_at)
        result["snapshot_commit"] = snapshot_commit
        result["error"] = err
        return result
    status, status_err = _git(repo_path, "status", "--porcelain")
    dirty = None if status_err is not None else bool(status)
    head_drift = live_head != snapshot_commit
    return {
        "status": "stale" if head_drift else "fresh",
        "reason": "head_drift" if head_drift else "head_matches_snapshot_commit",
        "checked_at": checked_at,
        "snapshot_commit": snapshot_commit,
        "live_head": live_head,
        "head_drift": head_drift,
        "live_git_dirty": dirty,
        "basis": "git_commit",
    }


def _parse_timestamp(value: Any, *, label: str) -> _dt.datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} is missing")
    text = value.strip()
    try:
        parsed = _dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} is not RFC3339") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must include a timezone")
    return parsed.astimezone(_dt.timezone.utc)


def _normalized_generated_at(value: Any) -> str:
    return (
        _parse_timestamp(value, label="latest-complete candidate generated_at")
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _source_lane(source: Mapping[str, Any]) -> list[list[str]]:
    repositories = source.get("repositories")
    if not isinstance(repositories, list):
        return []
    lane: set[tuple[str, str]] = set()
    for repository in repositories:
        if not isinstance(repository, Mapping):
            continue
        name = repository.get("name") if isinstance(repository.get("name"), str) else ""
        remote = repository.get("repo_remote")
        normalized_remote = (
            _normalized_remote(remote) if isinstance(remote, str) else None
        )
        root_sha256 = repository.get("repo_root_sha256")
        if normalized_remote is not None:
            identity = f"remote:{normalized_remote}"
        elif (
            isinstance(root_sha256, str)
            and len(root_sha256) == 64
            and all(character in "0123456789abcdef" for character in root_sha256)
        ):
            identity = f"root-sha256:{root_sha256}"
        else:
            continue
        lane.add((name, identity))
    return [[name, identity] for name, identity in sorted(lane)]


def _legacy_source_lane(source: Mapping[str, Any]) -> list[list[str]]:
    repositories = source.get("repositories")
    if not isinstance(repositories, list):
        return []
    lane: set[tuple[str, str]] = set()
    for repository in repositories:
        if not isinstance(repository, Mapping):
            continue
        name = repository.get("name") if isinstance(repository.get("name"), str) else ""
        remote = repository.get("repo_remote")
        normalized_remote = (
            _normalized_remote(remote) if isinstance(remote, str) else None
        )
        if normalized_remote is None:
            raise ValueError(
                "legacy latest-complete registry source lane is ambiguous without "
                "a non-local repo_remote"
            )
        lane.add((name, f"remote:{normalized_remote}"))
    return [[name, identity] for name, identity in sorted(lane)]


def _latest_complete_eligibility(
    manifest_path: Path,
    manifest: Mapping[str, Any],
    *,
    signals: Mapping[str, Any],
    source_commit: str | None,
    source_lane: list[list[str]],
    source_lane_complete: bool,
    reference_time: str,
) -> dict[str, Any]:
    from merger.lenskit.core.repobrief_profiles import (
        REQ_RECOMMENDED,
        REQ_REQUIRED,
        profile_export_semantics,
        profile_policy,
    )

    checks: dict[str, dict[str, Any]] = {}
    errors: list[str] = []

    def record(name: str, passed: bool, observed: Any, expected: Any) -> None:
        checks[name] = {
            "status": "pass" if passed else "fail",
            "observed": observed,
            "expected": expected,
        }
        if not passed:
            errors.append(name)

    record(
        "manifest_kind",
        manifest.get("kind") == "repolens.bundle.manifest",
        manifest.get("kind"),
        "repolens.bundle.manifest",
    )
    commit_valid = (
        isinstance(source_commit, str)
        and len(source_commit) in {40, 64}
        and all(character in "0123456789abcdef" for character in source_commit)
    )
    record(
        "source_commit_unambiguous",
        commit_valid,
        source_commit,
        "one full lowercase hexadecimal Git object id",
    )
    record(
        "source_lane_unambiguous",
        bool(source_lane) and source_lane_complete,
        {"lane": source_lane, "complete": source_lane_complete},
        "every repository identity bound to remote or hashed root",
    )

    bundle_generated_at = manifest.get("created_at")
    generated_time: _dt.datetime | None = None
    try:
        generated_time = _parse_timestamp(
            bundle_generated_at,
            label="latest-complete candidate generated_at",
        )
        normalized_generated_at = generated_time.isoformat(
            timespec="microseconds"
        ).replace("+00:00", "Z")
    except ValueError:
        normalized_generated_at = None
    record(
        "generated_at_rfc3339",
        generated_time is not None,
        bundle_generated_at,
        "timezone-aware RFC3339 timestamp",
    )
    reference = _parse_timestamp(
        reference_time,
        label="latest-complete publication time",
    )
    generated_not_future = (
        generated_time is not None
        and generated_time <= reference + _dt.timedelta(seconds=MAX_FUTURE_SKEW_SECONDS)
    )
    record(
        "generated_at_not_future",
        generated_not_future,
        normalized_generated_at,
        f"not later than publication time plus {MAX_FUTURE_SKEW_SECONDS} seconds",
    )

    capabilities = manifest.get("capabilities")
    capabilities = capabilities if isinstance(capabilities, Mapping) else {}
    profile = capabilities.get("repobrief_profile")
    profile_evaluation = capabilities.get("repobrief_profile_evaluation")
    profile_status = (
        profile_evaluation.get("status")
        if isinstance(profile_evaluation, Mapping)
        else None
    )
    profile_known = False
    export_semantics: dict[str, bool] = {}
    export_safety_requirement = None
    if isinstance(profile, str):
        try:
            export_semantics = profile_export_semantics(profile)
            export_safety_requirement = profile_policy(profile)["artifact_rules"][
                "export_safety_report"
            ]
            profile_known = True
        except ValueError:
            pass
    record("profile_known", profile_known, profile, "known RepoBrief profile")
    record(
        "profile_evaluation",
        profile_status in {"pass", "warn"},
        profile_status,
        ["pass", "warn"],
    )

    def signal_status(role: str) -> str | None:
        signal = signals.get(role)
        return signal.get("status") if isinstance(signal, Mapping) else None

    expected_signals = {
        "output_health": ({"pass", "warn"}, ["pass", "warn"]),
        "post_emit_health": ({"pass"}, "pass"),
        "bundle_surface_validation": ({"pass", "warn"}, ["pass", "warn"]),
    }
    for role, (accepted, expected) in expected_signals.items():
        status = signal_status(role)
        record(role, status in accepted, status, expected)

    gate_required = (
        bool(export_semantics.get("agent_export_gate_required"))
        if profile_known
        else True
    )
    gate_status = signal_status("agent_export_gate")
    record(
        "agent_export_gate",
        not gate_required or gate_status == "pass",
        gate_status,
        "pass" if gate_required else "not_required",
    )
    export_safety_required = export_safety_requirement in {
        REQ_REQUIRED,
        REQ_RECOMMENDED,
    }
    export_status = signal_status("export_safety_report")
    record(
        "export_safety_report",
        not export_safety_required or export_status == "pass",
        export_status,
        "pass" if export_safety_required else "not_required",
    )

    return {
        "status": "pass" if not errors else "fail",
        "profile": profile if isinstance(profile, str) else None,
        "manifest_name": manifest_path.name,
        "generated_at": normalized_generated_at,
        "reference_time": reference.isoformat(timespec="microseconds").replace(
            "+00:00", "Z"
        ),
        "checks": checks,
        "errors": errors,
    }


def _selection_from_registry(registry: Mapping[str, Any]) -> dict[str, Any]:
    bundle = (
        registry.get("bundle") if isinstance(registry.get("bundle"), Mapping) else {}
    )
    source = (
        registry.get("source") if isinstance(registry.get("source"), Mapping) else {}
    )
    generated_at = _normalized_generated_at(bundle.get("generated_at"))
    run_id = bundle.get("run_id") if isinstance(bundle.get("run_id"), str) else None
    manifest_sha256 = bundle.get("manifest_sha256")
    if (
        not isinstance(manifest_sha256, str)
        or len(manifest_sha256) != 64
        or any(character not in "0123456789abcdef" for character in manifest_sha256)
    ):
        raise ValueError(
            "latest-complete registry manifest SHA-256 is missing or invalid"
        )
    version = registry.get("version")
    if version == LEGACY_VERSION:
        source_lane = _legacy_source_lane(source)
        basis = "generated_at_fail_closed_ties_v1_migrated"
    elif version == VERSION:
        source_lane = _source_lane(source)
        basis = "generated_at_fail_closed_ties_v2"
    else:
        raise ValueError("latest-complete registry version is unsupported")
    if not source_lane:
        raise ValueError("latest-complete registry source lane is missing")
    return {
        "basis": basis,
        "generated_at": generated_at,
        "run_id": run_id,
        "manifest_sha256": manifest_sha256,
        "source_lane": source_lane,
        "order_key": [generated_at],
        "registry_version": version,
    }


def _registry_future_clock_fields(
    registry: Mapping[str, Any], *, reference_time: str
) -> list[str]:
    reference = _parse_timestamp(
        reference_time, label="latest-complete publication time"
    )
    future_fields: list[str] = []
    for field, value in (
        ("updated_at", registry.get("updated_at")),
        (
            "bundle.generated_at",
            registry.get("bundle", {}).get("generated_at")
            if isinstance(registry.get("bundle"), Mapping)
            else None,
        ),
    ):
        observed = _parse_timestamp(
            value, label=f"existing latest-complete registry {field}"
        )
        if observed > reference + _dt.timedelta(seconds=MAX_FUTURE_SKEW_SECONDS):
            future_fields.append(field)
    return future_fields


def _publication_target(output_path: str | Path) -> Path:
    raw = Path(output_path).expanduser()
    parent = _resolve_path(raw.parent, label="latest-complete output parent")
    out = parent / raw.name
    if out.is_symlink():
        raise ValueError(
            f"latest-complete registry target must not be a symlink: {out}"
        )
    if out.exists() and not out.is_file():
        raise ValueError(
            f"latest-complete registry target must be a regular file: {out}"
        )
    return out


def _open_directory_lock(path: Path) -> int:
    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise ValueError(
            f"latest-complete publication directory cannot be opened safely: {path}"
        ) from exc
    try:
        metadata = os.fstat(fd)
        if not statmod.S_ISDIR(metadata.st_mode):
            raise ValueError(
                f"latest-complete publication parent must be a directory: {path}"
            )
    except Exception:
        os.close(fd)
        raise
    return fd


def _fsync_locked_directory(directory_fd: int) -> None:
    os.fsync(directory_fd)


def _assert_directory_identity(path: Path, directory_fd: int) -> None:
    try:
        path_metadata = os.stat(path)
        fd_metadata = os.fstat(directory_fd)
    except OSError as exc:
        raise OSError(
            f"latest-complete publication directory identity cannot be verified: {path}"
        ) from exc
    if (path_metadata.st_dev, path_metadata.st_ino) != (
        fd_metadata.st_dev,
        fd_metadata.st_ino,
    ):
        raise OSError(
            f"latest-complete publication directory identity changed: {path}"
        )


def _read_target_bytes(path: Path, *, directory_fd: int | None = None) -> bytes:
    if directory_fd is None:
        return path.read_bytes()
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    target_fd = os.open(path.name, flags, dir_fd=directory_fd)
    try:
        metadata = os.fstat(target_fd)
        if not statmod.S_ISREG(metadata.st_mode):
            raise OSError(f"latest-complete registry target is not regular: {path}")
        with os.fdopen(target_fd, "rb", closefd=False) as handle:
            return handle.read()
    finally:
        os.close(target_fd)


def _target_exists(path: Path, *, directory_fd: int | None = None) -> bool:
    if directory_fd is None:
        return path.exists()
    try:
        os.stat(path.name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return False
    except OSError:
        return True
    return True


def _read_existing_registry(
    path: Path, *, directory_fd: int
) -> dict[str, Any] | None:
    try:
        payload = _read_target_bytes(path, directory_fd=directory_fd)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ValueError(
            f"latest-complete registry target cannot be read safely: {path}"
        ) from exc
    registry = _decode_json_object(
        payload, path=path, label="existing latest-complete registry"
    )
    if registry.get("kind") != KIND or registry.get("version") not in SUPPORTED_VERSIONS:
        raise ValueError("existing latest-complete registry kind/version mismatch")
    return registry


def _target_observation(
    path: Path, expected_sha256: str, *, directory_fd: int | None = None
) -> dict[str, Any]:
    try:
        payload = _read_target_bytes(path, directory_fd=directory_fd)
    except OSError as exc:
        return {
            "namespace": (
                "locked_directory_fd" if directory_fd is not None else "resolved_path"
            ),
            "visible": _target_exists(path, directory_fd=directory_fd),
            "readable": False,
            "expected_sha256": expected_sha256,
            "observed_sha256": None,
            "matches_expected": None,
            "error": str(exc),
        }
    observed = hashlib.sha256(payload).hexdigest()
    return {
        "namespace": (
            "locked_directory_fd" if directory_fd is not None else "resolved_path"
        ),
        "visible": True,
        "readable": True,
        "expected_sha256": expected_sha256,
        "observed_sha256": observed,
        "matches_expected": observed == expected_sha256,
        "error": None,
    }


def _serialized_registry(registry: Mapping[str, Any]) -> bytes:
    return (json.dumps(registry, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _stable_registry_identity_sha256(registry: Mapping[str, Any]) -> str:
    projection = json.loads(json.dumps(registry))
    if not isinstance(projection, dict):
        raise ValueError("latest-complete registry identity must be an object")
    projection.pop("updated_at", None)
    eligibility = projection.get("eligibility")
    if isinstance(eligibility, dict):
        eligibility.pop("reference_time", None)
    return hashlib.sha256(_serialized_registry(projection)).hexdigest()


def _publication_failure_receipt(
    *,
    path: Path,
    phase: str,
    error_code: str,
    message: str,
    replace_performed: bool,
    expected_sha256: str,
    directory_fd: int | None = None,
    uncertain: bool | None = None,
    publication_state: str | None = None,
    observed_writes: list[str] | None = None,
    recovery_required: bool | None = None,
    recovery_action: str | None = None,
    temporary_file_created: bool = False,
    temporary_file_cleanup: str = "not_required",
    temporary_file_name: str | None = None,
    target_directories_created: list[str] | None = None,
) -> dict[str, Any]:
    created_directories = list(target_directories_created or [])
    observation = _target_observation(
        path, expected_sha256, directory_fd=directory_fd
    )
    if uncertain is None:
        uncertain = replace_performed
    if publication_state is None:
        publication_state = (
            "uncertain_after_replace" if uncertain else "failed_before_replace"
        )
    if observed_writes is None:
        observed_writes = []
        if created_directories:
            observed_writes.append("latest_complete_registry_parent_directory")
        if temporary_file_created:
            observed_writes.append("latest_complete_registry_temporary_file")
        if replace_performed:
            observed_writes.append("latest_complete_registry")
    if recovery_required is None:
        recovery_required = uncertain
    if recovery_action is None:
        recovery_action = (
            "retry the same candidate; the retry revalidates file and directory durability"
            if uncertain
            else "fix the reported pre-replace error and retry"
        )
    temporary_file_write = (
        "failed"
        if phase == "temp_write"
        else "pass"
        if phase
        in {
            "file_fsync",
            "atomic_replace",
            "directory_fsync",
            "readback",
            "directory_identity_post",
        }
        else "not_reached"
    )
    file_fsync = (
        "failed"
        if phase == "file_fsync"
        else "pass"
        if phase
        in {
            "atomic_replace",
            "directory_fsync",
            "readback",
            "directory_identity_post",
        }
        else "not_reached"
    )
    atomic_replace = (
        "failed"
        if phase == "atomic_replace"
        else "pass"
        if replace_performed
        else "not_reached"
    )
    directory_fsync = (
        "failed"
        if phase == "directory_fsync"
        else "pass"
        if phase in {"readback", "directory_identity_post"}
        else "not_reached"
    )
    directory_identity = (
        "failed"
        if phase
        in {
            "directory_identity_pre",
            "directory_identity_post",
            "directory_identity_post_selection",
        }
        else "match"
        if phase == "complete"
        else "not_reached"
    )
    readback = (
        "match"
        if observation.get("matches_expected") is True
        else "mismatch"
        if observation.get("matches_expected") is False
        else "unavailable"
    )
    return {
        "kind": WRITE_KIND,
        "version": VERSION,
        "status": "error",
        "publication_result": "uncertain" if uncertain else "not_published",
        "publication_state": publication_state,
        "registry_path": str(path),
        "serialization_resource": str(path.parent),
        "target_directory_created": bool(created_directories),
        "target_directories_created": created_directories,
        "error": {
            "code": error_code,
            "phase": phase,
            "message": message,
        },
        "transaction": {
            "replace_performed": replace_performed,
            "temporary_file_write": temporary_file_write,
            "file_fsync": file_fsync,
            "atomic_replace": atomic_replace,
            "directory_fsync": directory_fsync,
            "readback": readback,
            "directory_identity": directory_identity,
            "temporary_file_created": temporary_file_created,
            "temporary_file_cleanup": temporary_file_cleanup,
            "temporary_file_name": temporary_file_name,
            "target": observation,
        },
        "recovery": {
            "required": recovery_required,
            "action": recovery_action,
            "automatic_rollback_claimed": False,
        },
        "mutation_boundary": {
            "writes": [
                "latest_complete_registry_parent_directory",
                "latest_complete_registry_temporary_file",
                "latest_complete_registry",
            ],
            "observed_writes": observed_writes,
            "does_not_mutate": [
                "git",
                "pull_requests",
                "patches",
                "source_working_tree",
                "brief_bundle_artifacts",
            ],
            "read_paths_do_not_refresh": True,
            "hidden_refresh_allowed": False,
        },
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }


def _open_unique_temp(directory_fd: int, target_name: str) -> tuple[int, str]:
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    for _ in range(128):
        name = f".{target_name}.{secrets.token_hex(12)}.tmp"
        try:
            return os.open(name, flags, 0o600, dir_fd=directory_fd), name
        except FileExistsError:
            continue
    raise OSError("cannot allocate unique latest-complete temporary file")


def _atomic_publish_registry(
    path: Path, registry: Mapping[str, Any], *, directory_fd: int
) -> dict[str, Any]:
    payload = _serialized_registry(registry)
    expected_sha256 = hashlib.sha256(payload).hexdigest()
    tmp_name: str | None = None
    temporary_file_created = False
    temporary_file_cleanup = "not_required"
    temporary_file_name: str | None = None
    replace_performed = False
    phase = "temp_create"
    failure: OSError | None = None
    observation: dict[str, Any] | None = None
    try:
        temp_fd, tmp_name = _open_unique_temp(directory_fd, path.name)
        temporary_file_created = True
        temporary_file_name = tmp_name
        with os.fdopen(temp_fd, "wb") as handle:
            phase = "temp_write"
            handle.write(payload)
            handle.flush()
            phase = "file_fsync"
            os.fsync(handle.fileno())
        phase = "atomic_replace"
        os.replace(
            tmp_name,
            path.name,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
        replace_performed = True
        temporary_file_cleanup = "renamed_to_target"
        tmp_name = None
        phase = "directory_fsync"
        _fsync_locked_directory(directory_fd)
        phase = "readback"
        observation = _target_observation(
            path, expected_sha256, directory_fd=directory_fd
        )
        if observation.get("matches_expected") is not True:
            raise OSError(f"latest-complete registry readback mismatch: {path}")
        phase = "directory_identity_post"
        _assert_directory_identity(path.parent, directory_fd)
    except OSError as exc:
        failure = exc
    finally:
        if tmp_name is not None:
            try:
                os.unlink(tmp_name, dir_fd=directory_fd)
                temporary_file_cleanup = "removed"
            except OSError:
                temporary_file_cleanup = "failed"
    if failure is not None:
        code = {
            "temp_create": "temp_create_failed",
            "temp_write": "temp_write_failed",
            "file_fsync": "file_fsync_failed",
            "atomic_replace": "atomic_replace_failed",
            "directory_fsync": "directory_fsync_failed_after_replace",
            "readback": "readback_failed_after_replace",
            "directory_identity_post": "directory_identity_changed_after_replace",
        }[phase]
        cleanup_failed = temporary_file_cleanup == "failed"
        publication_state = None
        recovery_required = None
        recovery_action = None
        if cleanup_failed and not replace_performed:
            publication_state = "failed_before_replace_with_temp_artifact"
            recovery_required = True
            recovery_action = (
                "remove the reported temporary publication artifact, fix the original "
                "error and retry"
            )
        receipt = _publication_failure_receipt(
            path=path,
            phase=phase,
            error_code=code,
            message=str(failure),
            replace_performed=replace_performed,
            expected_sha256=expected_sha256,
            directory_fd=directory_fd,
            publication_state=publication_state,
            recovery_required=recovery_required,
            recovery_action=recovery_action,
            temporary_file_created=temporary_file_created,
            temporary_file_cleanup=temporary_file_cleanup,
            temporary_file_name=temporary_file_name,
        )
        raise LatestCompletePublicationError(str(failure), receipt) from failure
    if observation is None:
        raise AssertionError("latest-complete publication completed without readback")
    return {
        "status": "committed",
        "phase": "readback_verified",
        "replace_performed": True,
        "temporary_file_write": "pass",
        "file_fsync": "pass",
        "atomic_replace": "pass",
        "directory_fsync": "pass",
        "readback": "match",
        "directory_identity": "match",
        "temporary_file_created": True,
        "temporary_file_cleanup": "renamed_to_target",
        "temporary_file_name": temporary_file_name,
        "target": observation,
    }


def _revalidate_registry_durability(
    path: Path, registry: Mapping[str, Any], *, directory_fd: int
) -> dict[str, Any]:
    payload = _serialized_registry(registry)
    expected_sha256 = hashlib.sha256(payload).hexdigest()
    observation = _target_observation(
        path, expected_sha256, directory_fd=directory_fd
    )
    if observation.get("matches_expected") is not True:
        receipt = _publication_failure_receipt(
            path=path,
            phase="readback",
            error_code="durability_revalidation_readback_failed",
            message="existing registry does not match the expected candidate bytes",
            replace_performed=False,
            expected_sha256=expected_sha256,
            directory_fd=directory_fd,
            uncertain=True,
            publication_state="durability_unconfirmed",
            observed_writes=[],
        )
        raise LatestCompletePublicationError(
            "existing registry does not match the expected candidate bytes", receipt
        )
    phase = "file_fsync"
    try:
        flags = (
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        target_fd = os.open(path.name, flags, dir_fd=directory_fd)
        try:
            metadata = os.fstat(target_fd)
            if not statmod.S_ISREG(metadata.st_mode):
                raise OSError(
                    f"latest-complete registry target is not regular: {path}"
                )
            os.fsync(target_fd)
        finally:
            os.close(target_fd)
        phase = "directory_fsync"
        _fsync_locked_directory(directory_fd)
        phase = "directory_identity_post"
        _assert_directory_identity(path.parent, directory_fd)
    except OSError as exc:
        code = (
            "durability_revalidation_file_fsync_failed"
            if phase == "file_fsync"
            else "durability_revalidation_directory_fsync_failed"
            if phase == "directory_fsync"
            else "durability_revalidation_directory_identity_changed"
        )
        receipt = _publication_failure_receipt(
            path=path,
            phase=phase,
            error_code=code,
            message=str(exc),
            replace_performed=False,
            expected_sha256=expected_sha256,
            directory_fd=directory_fd,
            uncertain=True,
            publication_state="durability_unconfirmed",
            observed_writes=[],
        )
        raise LatestCompletePublicationError(str(exc), receipt) from exc
    return {
        "status": "committed",
        "phase": "durability_revalidated",
        "replace_performed": False,
        "temporary_file_write": "not_performed",
        "file_fsync": "pass",
        "atomic_replace": "not_performed",
        "directory_fsync": "pass",
        "readback": "match",
        "directory_identity": "match",
        "temporary_file_created": False,
        "temporary_file_cleanup": "not_required",
        "temporary_file_name": None,
        "target": observation,
    }


def build_latest_complete_registry(
    bundle_manifest: str | Path,
    *,
    registry_path: str | Path | None = None,
    checked_at: str | None = None,
) -> dict[str, Any]:
    manifest_path = _resolve_path(bundle_manifest, label="bundle manifest")
    manifest, manifest_payload, manifest_sha256 = _capture_json_object(
        manifest_path, label="bundle manifest"
    )
    registry_target = (
        _resolve_path(registry_path, label="latest-complete registry path")
        if registry_path is not None
        else None
    )
    base_dir = registry_target.parent if registry_target is not None else None
    publication_time = checked_at or _now_iso()
    _parse_timestamp(publication_time, label="latest-complete publication time")
    repositories = _source_repositories(manifest)
    source = {"repositories": repositories}
    source_lane = _source_lane(source)
    source_commit, source_reason = _primary_source_commit(repositories)
    signals = _health_signals(manifest_path, manifest)
    eligibility = _latest_complete_eligibility(
        manifest_path,
        manifest,
        signals=signals,
        source_commit=source_commit,
        source_lane=source_lane,
        source_lane_complete=bool(repositories) and all(
            repository.get("source_identity_basis") in {"repo_remote", "repo_root_sha256"}
            for repository in repositories
        ),
        reference_time=publication_time,
    )
    if eligibility["status"] != "pass":
        raise ValueError(
            "bundle manifest is not eligible for latest-complete publication: "
            + ", ".join(eligibility["errors"])
        )
    registry: dict[str, Any] = {
        "kind": KIND,
        "version": VERSION,
        "updated_at": publication_time,
        "bundle": {
            "stem": _manifest_stem(manifest_path),
            "manifest_path": _relative_or_absolute(manifest_path, base_dir),
            "manifest_sha256": manifest_sha256,
            "manifest_bytes": len(manifest_payload),
            "manifest_capture": "single_read_bytes_sha256_bound",
            "run_id": manifest.get("run_id")
            if isinstance(manifest.get("run_id"), str)
            else None,
            "generated_at": manifest.get("created_at")
            if isinstance(manifest.get("created_at"), str)
            else None,
        },
        "source": {
            "commit": source_commit,
            "commit_status": source_reason,
            "repositories": repositories,
        },
        "health": {
            "status": _aggregate_health(signals),
            "signals": signals,
            "health_values": list(HEALTH_VALUES),
        },
        "freshness": {
            "status": "unknown",
            "reason": "live_repo_not_checked",
            "checked_at": None,
            "snapshot_commit": source_commit,
            "live_head": None,
            "head_drift": None,
            "basis": "git_commit" if source_commit else "unknown",
            "freshness_values": list(FRESHNESS_VALUES),
        },
        "eligibility": eligibility,
        "publication": {
            "protocol": "atomic_replace_with_durability_receipt_v2",
            "serialization": "advisory_directory_lock",
            "file_fsync_required": True,
            "directory_fsync_required": True,
            "readback_required": True,
            "uncertain_after_replace_reported": True,
            "idempotent_durability_revalidation": True,
        },
        "mutation_boundary": {
            "writes": [
                "latest_complete_registry_parent_directory",
                "latest_complete_registry_temporary_file",
                "latest_complete_registry",
            ]
            if registry_target is not None
            else [],
            "does_not_mutate": [
                "git",
                "pull_requests",
                "patches",
                "source_working_tree",
                "brief_bundle_artifacts",
            ],
            "read_paths_do_not_refresh": True,
            "hidden_refresh_allowed": False,
        },
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }
    registry["selection"] = _selection_from_registry(registry)
    return registry


def _initial_publication_transaction() -> dict[str, Any]:
    return {
        "status": "not_started",
        "phase": "selection",
        "replace_performed": False,
        "temporary_file_write": "not_reached",
        "file_fsync": "not_reached",
        "atomic_replace": "not_reached",
        "directory_fsync": "not_reached",
        "readback": "not_reached",
        "directory_identity": "not_reached",
        "temporary_file_created": False,
        "temporary_file_cleanup": "not_required",
        "temporary_file_name": None,
        "target": None,
    }


def _verified_no_change_transaction() -> dict[str, Any]:
    return {
        "status": "verified_no_change",
        "phase": "selection_verified",
        "replace_performed": False,
        "temporary_file_write": "not_performed",
        "file_fsync": "not_performed",
        "atomic_replace": "not_performed",
        "directory_fsync": "not_performed",
        "readback": "not_performed",
        "directory_identity": "match",
        "temporary_file_created": False,
        "temporary_file_cleanup": "not_required",
        "temporary_file_name": None,
        "target": None,
    }


def _prepare_publication_directory(
    out: Path, expected_sha256: str
) -> tuple[Path, int, list[str]]:
    created: list[Path] = []
    try:
        _prepare_directory_tree(out.parent, created)
    except (OSError, ValueError) as exc:
        created_strings = [str(directory) for directory in created]
        receipt = _publication_failure_receipt(
            path=out,
            phase="target_directory_prepare",
            error_code="target_directory_prepare_failed",
            message=str(exc),
            replace_performed=False,
            expected_sha256=expected_sha256,
            target_directories_created=created_strings,
        )
        raise LatestCompletePublicationError(str(exc), receipt) from exc
    created_strings = [str(directory) for directory in created]
    try:
        resolved = _publication_target(out)
        lock_fd = _open_directory_lock(resolved.parent)
    except ValueError as exc:
        receipt = _publication_failure_receipt(
            path=out,
            phase="directory_lock_open",
            error_code="directory_lock_open_failed",
            message=str(exc),
            replace_performed=False,
            expected_sha256=expected_sha256,
            target_directories_created=created_strings,
        )
        raise LatestCompletePublicationError(str(exc), receipt) from exc
    return resolved, lock_fd, created_strings


def _acquire_publication_lock(
    out: Path,
    lock_fd: int,
    expected_sha256: str,
    created_directories: list[str],
) -> None:
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
    except OSError as exc:
        receipt = _publication_failure_receipt(
            path=out,
            phase="directory_lock_acquire",
            error_code="directory_lock_acquire_failed",
            message=str(exc),
            replace_performed=False,
            expected_sha256=expected_sha256,
            directory_fd=lock_fd,
            target_directories_created=created_directories,
        )
        raise LatestCompletePublicationError(str(exc), receipt) from exc


def _assert_publication_directory_identity(
    out: Path,
    lock_fd: int,
    expected_sha256: str,
    created_directories: list[str],
    *,
    phase: str,
    error_code: str,
) -> None:
    try:
        _assert_directory_identity(out.parent, lock_fd)
    except OSError as exc:
        receipt = _publication_failure_receipt(
            path=out,
            phase=phase,
            error_code=error_code,
            message=str(exc),
            replace_performed=False,
            expected_sha256=expected_sha256,
            directory_fd=lock_fd,
            target_directories_created=created_directories,
        )
        raise LatestCompletePublicationError(str(exc), receipt) from exc


def _select_publication_decision(
    existing: Mapping[str, Any] | None,
    candidate: dict[str, Any],
    candidate_selection: Mapping[str, Any],
    *,
    publication_time: str,
    out: Path,
    lock_fd: int,
) -> dict[str, Any]:
    decision: dict[str, Any] = {
        "publication_result": "published",
        "published_registry": candidate,
        "reason": "first_publication",
        "transaction": _initial_publication_transaction(),
        "existing_registry_version": None,
        "existing_future_clock_fields": [],
    }
    if existing is None:
        return decision
    existing_version = (
        existing.get("version") if isinstance(existing.get("version"), str) else None
    )
    decision["existing_registry_version"] = existing_version
    existing_selection = _selection_from_registry(existing)
    if existing_selection["source_lane"] != candidate_selection["source_lane"]:
        raise ValueError("latest-complete registry source lane mismatch")
    future_fields = _registry_future_clock_fields(
        existing, reference_time=publication_time
    )
    decision["existing_future_clock_fields"] = list(future_fields)
    if future_fields and existing_version != LEGACY_VERSION:
        raise ValueError(
            "existing latest-complete registry clock is implausibly future: "
            + ", ".join(future_fields)
        )
    if "bundle.generated_at" in future_fields:
        decision["reason"] = "legacy_registry_future_bundle_clock_replaced"
        return decision
    candidate_time = candidate_selection["generated_at"]
    existing_time = existing_selection["generated_at"]
    if candidate_time < existing_time:
        decision.update(
            publication_result="unchanged",
            published_registry=existing,
            reason="candidate_older_than_published",
        )
        return decision
    if candidate_time > existing_time:
        decision["reason"] = (
            "legacy_registry_migrated_with_newer_candidate"
            if existing_version == LEGACY_VERSION
            else "candidate_newer_than_published"
        )
        return decision
    if candidate_selection["manifest_sha256"] != existing_selection["manifest_sha256"]:
        raise ValueError(
            "latest-complete candidate order is ambiguous: generated_at collision"
        )
    if existing_version != VERSION:
        decision["reason"] = "legacy_registry_migrated"
        return decision
    if _stable_registry_identity_sha256(existing) != _stable_registry_identity_sha256(
        candidate
    ):
        raise ValueError(
            "latest-complete existing v2 registry stable identity does not match "
            "the current candidate"
        )
    decision.update(
        publication_result="unchanged",
        published_registry=existing,
        reason="candidate_already_published_durability_revalidated",
        transaction=_revalidate_registry_durability(
            out, existing, directory_fd=lock_fd
        ),
    )
    return decision


def _finalize_publication_decision(
    decision: dict[str, Any],
    candidate: Mapping[str, Any],
    *,
    out: Path,
    lock_fd: int,
    expected_sha256: str,
    created_directories: list[str],
) -> dict[str, Any]:
    if decision["publication_result"] == "published":
        decision["transaction"] = _atomic_publish_registry(
            out, candidate, directory_fd=lock_fd
        )
        return decision
    transaction = decision["transaction"]
    if transaction.get("phase") != "selection":
        return decision
    _assert_publication_directory_identity(
        out,
        lock_fd,
        expected_sha256,
        created_directories,
        phase="directory_identity_post_selection",
        error_code="directory_identity_changed_before_result",
    )
    decision["transaction"] = _verified_no_change_transaction()
    return decision


def _enrich_publication_error(
    exc: LatestCompletePublicationError, created_directories: list[str]
) -> None:
    exc.receipt["target_directory_created"] = bool(created_directories)
    exc.receipt["target_directories_created"] = list(created_directories)
    if not created_directories:
        return
    observed = exc.receipt.get("mutation_boundary", {}).get("observed_writes")
    if isinstance(observed, list) and (
        "latest_complete_registry_parent_directory" not in observed
    ):
        observed.insert(0, "latest_complete_registry_parent_directory")


def _wrap_publication_precondition_error(
    exc: ValueError,
    *,
    out: Path,
    lock_fd: int,
    expected_sha256: str,
    created_directories: list[str],
) -> LatestCompletePublicationError:
    receipt = _publication_failure_receipt(
        path=out,
        phase="selection",
        error_code="publication_precondition_failed",
        message=str(exc),
        replace_performed=False,
        expected_sha256=expected_sha256,
        directory_fd=lock_fd,
        target_directories_created=created_directories,
    )
    return LatestCompletePublicationError(str(exc), receipt)


def _run_locked_publication(
    out: Path,
    lock_fd: int,
    candidate: dict[str, Any],
    candidate_selection: Mapping[str, Any],
    *,
    publication_time: str,
    expected_sha256: str,
    created_directories: list[str],
) -> dict[str, Any]:
    locked = False
    try:
        _acquire_publication_lock(
            out, lock_fd, expected_sha256, created_directories
        )
        locked = True
        _assert_publication_directory_identity(
            out,
            lock_fd,
            expected_sha256,
            created_directories,
            phase="directory_identity_pre",
            error_code="directory_identity_changed_before_replace",
        )
        try:
            existing = _read_existing_registry(out, directory_fd=lock_fd)
            decision = _select_publication_decision(
                existing,
                candidate,
                candidate_selection,
                publication_time=publication_time,
                out=out,
                lock_fd=lock_fd,
            )
            return _finalize_publication_decision(
                decision,
                candidate,
                out=out,
                lock_fd=lock_fd,
                expected_sha256=expected_sha256,
                created_directories=created_directories,
            )
        except LatestCompletePublicationError as exc:
            _enrich_publication_error(exc, created_directories)
            raise
        except ValueError as exc:
            raise _wrap_publication_precondition_error(
                exc,
                out=out,
                lock_fd=lock_fd,
                expected_sha256=expected_sha256,
                created_directories=created_directories,
            ) from exc
    finally:
        if locked:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            except OSError:
                pass
        try:
            os.close(lock_fd)
        except OSError:
            pass


def _publication_state(decision: Mapping[str, Any]) -> str:
    if decision["publication_result"] == "published":
        return "committed"
    transaction = decision["transaction"]
    if transaction.get("phase") == "durability_revalidated":
        return "durability_revalidated"
    return "unchanged_existing"


def _successful_publication_receipt(
    out: Path,
    candidate: dict[str, Any],
    decision: Mapping[str, Any],
    created_directories: list[str],
) -> dict[str, Any]:
    observed_writes: list[str] = []
    if created_directories:
        observed_writes.append("latest_complete_registry_parent_directory")
    if decision["publication_result"] == "published":
        observed_writes.extend(
            [
                "latest_complete_registry_temporary_file",
                "latest_complete_registry",
            ]
        )
    return {
        "kind": WRITE_KIND,
        "version": VERSION,
        "status": "ok",
        "publication_result": decision["publication_result"],
        "publication_state": _publication_state(decision),
        "reason": decision["reason"],
        "registry_path": str(out),
        "serialization_resource": str(out.parent),
        "persistent_lock_artifact": False,
        "target_directory_created": bool(created_directories),
        "target_directories_created": list(created_directories),
        "existing_registry_version": decision["existing_registry_version"],
        "existing_future_clock_fields": decision["existing_future_clock_fields"],
        "registry": decision["published_registry"],
        "candidate_registry": candidate,
        "transaction": decision["transaction"],
        "recovery": {
            "required": False,
            "automatic_rollback_claimed": False,
        },
        "mutation_boundary": {
            "writes": [
                "latest_complete_registry_parent_directory",
                "latest_complete_registry_temporary_file",
                "latest_complete_registry",
            ],
            "observed_writes": observed_writes,
            "does_not_mutate": [
                "git",
                "pull_requests",
                "patches",
                "source_working_tree",
                "brief_bundle_artifacts",
            ],
            "read_paths_do_not_refresh": True,
            "hidden_refresh_allowed": False,
        },
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }


def write_latest_complete_registry(
    bundle_manifest: str | Path,
    output_path: str | Path,
    *,
    checked_at: str | None = None,
) -> dict[str, Any]:
    out = _publication_target(output_path)
    publication_time = checked_at or _now_iso()
    candidate = build_latest_complete_registry(
        bundle_manifest,
        registry_path=out,
        checked_at=publication_time,
    )
    candidate_selection = _selection_from_registry(candidate)
    expected_sha256 = hashlib.sha256(_serialized_registry(candidate)).hexdigest()
    out, lock_fd, created_directories = _prepare_publication_directory(
        out, expected_sha256
    )
    decision = _run_locked_publication(
        out,
        lock_fd,
        candidate,
        candidate_selection,
        publication_time=publication_time,
        expected_sha256=expected_sha256,
        created_directories=created_directories,
    )
    return _successful_publication_receipt(
        out, candidate, decision, created_directories
    )


def _capture_status_manifest(
    bundle_path: Path | None, bundle_info: Mapping[str, Any]
) -> tuple[str, str | None, dict[str, Any] | None]:
    if bundle_path is None:
        return "unknown", None, None
    if not bundle_path.is_file():
        return "missing", None, None
    try:
        manifest, _, observed_sha256 = _capture_json_object(
            bundle_path, label="bundle manifest"
        )
    except ValueError:
        return "unreadable", None, None
    expected_sha256 = bundle_info.get("manifest_sha256")
    status = "match" if expected_sha256 == observed_sha256 else "mismatch"
    return status, observed_sha256, manifest


def _observe_status_eligibility(
    registry: Mapping[str, Any],
    bundle_path: Path | None,
    captured_manifest: dict[str, Any] | None,
    manifest_hash_status: str,
    *,
    checked_at: str | None,
) -> tuple[dict[str, Any] | None, list[str]]:
    if bundle_path is None or captured_manifest is None:
        return None, []
    if manifest_hash_status != "match":
        return None, []
    try:
        repositories = _source_repositories(captured_manifest)
        source_commit, _ = _primary_source_commit(repositories)
        observed_signals = _health_signals(bundle_path, captured_manifest)
        observed = _latest_complete_eligibility(
            bundle_path,
            captured_manifest,
            signals=observed_signals,
            source_commit=source_commit,
            source_lane=_source_lane({"repositories": repositories}),
            source_lane_complete=bool(repositories)
            and all(
                repository.get("source_identity_basis")
                in {"repo_remote", "repo_root_sha256"}
                for repository in repositories
            ),
            reference_time=str(registry.get("updated_at") or checked_at or _now_iso()),
        )
        stored_health = registry.get("health")
        stored_signals = (
            stored_health.get("signals")
            if isinstance(stored_health, dict)
            else {}
        )
        drift = _sidecar_hash_drift(stored_signals, observed_signals)
        return observed, drift
    except (OSError, ValueError) as exc:
        return {
            "status": "fail",
            "errors": [str(exc)],
            "checks": {},
        }, []


def _sidecar_hash_drift(
    stored_signals: Any, observed_signals: Mapping[str, Any]
) -> list[str]:
    if not isinstance(stored_signals, dict):
        return []
    drift: list[str] = []
    for role, signal in observed_signals.items():
        stored = stored_signals.get(role)
        stored_sha = stored.get("sha256") if isinstance(stored, dict) else None
        observed_sha = signal.get("sha256") if isinstance(signal, dict) else None
        if stored_sha is not None and stored_sha != observed_sha:
            drift.append(role)
    return drift


def _latest_complete_status_value(
    manifest_hash_status: str,
    stored_eligibility: Mapping[str, Any] | None,
    observed_eligibility: Mapping[str, Any] | None,
    sidecar_hash_drift: list[str],
) -> str:
    warnings = [
        manifest_hash_status in {"mismatch", "missing", "unreadable"},
        stored_eligibility is None,
        stored_eligibility is not None
        and stored_eligibility.get("status") != "pass",
        observed_eligibility is not None
        and observed_eligibility.get("status") != "pass",
        bool(sidecar_hash_drift),
    ]
    return "warn" if any(warnings) else "ok"


def latest_complete_status(
    registry_path: str | Path,
    *,
    repo: str | Path | None = None,
    checked_at: str | None = None,
) -> dict[str, Any]:
    path = _resolve_path(registry_path, label="latest-complete registry path")
    registry = _read_json_object(path, label="latest-complete registry")
    if registry.get("kind") != KIND:
        raise ValueError(f"latest-complete registry kind must be {KIND}")
    if registry.get("version") not in SUPPORTED_VERSIONS:
        raise ValueError("latest-complete registry version is unsupported")
    bundle_info = (
        registry.get("bundle") if isinstance(registry.get("bundle"), dict) else {}
    )
    bundle_path = _safe_bundle_path(
        path,
        bundle_info.get("manifest_path"),
    )
    manifest_status, observed_sha256, captured_manifest = _capture_status_manifest(
        bundle_path, bundle_info
    )
    freshness = evaluate_registry_freshness(registry, repo=repo, checked_at=checked_at)
    stored_eligibility = (
        registry.get("eligibility")
        if isinstance(registry.get("eligibility"), dict)
        else None
    )
    observed_eligibility, sidecar_drift = _observe_status_eligibility(
        registry,
        bundle_path,
        captured_manifest,
        manifest_status,
        checked_at=checked_at,
    )
    return {
        "kind": STATUS_KIND,
        "version": VERSION,
        "status": _latest_complete_status_value(
            manifest_status,
            stored_eligibility,
            observed_eligibility,
            sidecar_drift,
        ),
        "registry_path": str(path),
        "registry": registry,
        "bundle_manifest": str(bundle_path) if bundle_path is not None else None,
        "manifest_hash": {
            "status": manifest_status,
            "expected_sha256": bundle_info.get("manifest_sha256"),
            "observed_sha256": observed_sha256,
        },
        "eligibility": {
            "stored": stored_eligibility,
            "observed": observed_eligibility,
            "sidecar_hash_drift": sorted(sidecar_drift),
        },
        "freshness": freshness,
        "mutation_boundary": {
            "writes": [],
            "does_not_mutate": [
                "git",
                "pull_requests",
                "patches",
                "source_working_tree",
                "brief_bundle_artifacts",
                "latest_complete_registry",
            ],
            "read_paths_do_not_refresh": True,
            "hidden_refresh_allowed": False,
        },
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }
