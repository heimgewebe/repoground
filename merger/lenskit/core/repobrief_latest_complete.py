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
import stat as statmod
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Mapping

KIND = "repobrief.latest_complete_registry"
VERSION = "v1"
STATUS_KIND = "repobrief.latest_complete_status"
WRITE_KIND = "repobrief.latest_complete_registry_write"

FRESHNESS_VALUES = ("fresh", "stale", "unknown", "not_comparable")
HEALTH_VALUES = ("pass", "warn", "fail", "unknown")
MAX_FUTURE_SKEW_SECONDS = 300

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


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"{label} does not exist: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} is not valid JSON: {path}") from exc
    except UnicodeError as exc:
        raise ValueError(f"{label} is not valid UTF-8: {path}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{label} must be a JSON object")
    return data


def _manifest_stem(path: Path) -> str:
    suffix = ".bundle.manifest.json"
    if path.name.endswith(suffix):
        return path.name[: -len(suffix)]
    return path.stem


def _relative_or_absolute(target: Path, base_dir: Path | None) -> str:
    target = target.resolve()
    if base_dir is None:
        return str(target)
    try:
        return Path(os.path.relpath(target, base_dir.resolve())).as_posix()
    except ValueError:
        return str(target)


def _safe_bundle_path(registry_path: Path, raw_path: Any) -> Path | None:
    if not isinstance(raw_path, str) or not raw_path:
        return None
    candidate = (registry_path.parent / raw_path).resolve()
    if candidate.is_file():
        return candidate
    absolute = Path(raw_path).expanduser().resolve()
    if absolute.is_file():
        return absolute
    return candidate


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
        result.append(
            {
                "name": repo.get("name") if isinstance(repo.get("name"), str) else None,
                "repo_remote": repo.get("repo_remote")
                if isinstance(repo.get("repo_remote"), str)
                else None,
                "repo_root_recorded": isinstance(repo.get("repo_root"), str)
                and bool(repo.get("repo_root")),
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
        candidate = (manifest_path.parent / raw_path).resolve()
        try:
            candidate.relative_to(manifest_path.parent.resolve())
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
    repo_path = Path(repo).expanduser().resolve()
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
        remote = (
            repository.get("repo_remote")
            if isinstance(repository.get("repo_remote"), str)
            else ""
        )
        if name or remote:
            lane.add((name, remote))
    return [[name, remote] for name, remote in sorted(lane)]


def _latest_complete_eligibility(
    manifest_path: Path,
    manifest: Mapping[str, Any],
    *,
    signals: Mapping[str, Any],
    source_commit: str | None,
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
    source_lane = _source_lane(source)
    if not source_lane:
        raise ValueError("latest-complete registry source lane is missing")
    return {
        "basis": "generated_at_fail_closed_ties_v1",
        "generated_at": generated_at,
        "run_id": run_id,
        "manifest_sha256": manifest_sha256,
        "source_lane": source_lane,
        "order_key": [generated_at],
    }


def _publication_target(output_path: str | Path) -> Path:
    raw = Path(output_path).expanduser()
    parent = raw.parent.resolve()
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


def _open_lock_file(path: Path) -> int:
    flags = (
        os.O_CREAT
        | os.O_RDWR
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        fd = os.open(path, flags, 0o600)
    except OSError as exc:
        raise ValueError(
            f"latest-complete lock cannot be opened safely: {path}"
        ) from exc
    try:
        metadata = os.fstat(fd)
        if not statmod.S_ISREG(metadata.st_mode):
            raise ValueError(f"latest-complete lock must be a regular file: {path}")
        if metadata.st_uid != os.geteuid() or metadata.st_nlink != 1:
            raise ValueError(
                f"latest-complete lock must be singly linked and owned by the current user: {path}"
            )
    except Exception:
        os.close(fd)
        raise
    return fd


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)
    fd = os.open(path, flags)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _read_existing_registry(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise ValueError(
            f"latest-complete registry target must be a regular file: {path}"
        )
    registry = _read_json_object(path, label="existing latest-complete registry")
    if registry.get("kind") != KIND or registry.get("version") != VERSION:
        raise ValueError("existing latest-complete registry kind/version mismatch")
    return registry


def _atomic_publish_registry(path: Path, registry: Mapping[str, Any]) -> None:
    payload = (json.dumps(registry, indent=2, sort_keys=True) + "\n").encode("utf-8")
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            delete=False,
            dir=str(path.parent),
            prefix=f".{path.name}.",
            suffix=".tmp",
        ) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
            tmp_path = Path(handle.name)
        os.replace(tmp_path, path)
        _fsync_directory(path.parent)
        if path.read_bytes() != payload:
            raise OSError(f"latest-complete registry readback mismatch: {path}")
    finally:
        if tmp_path is not None and tmp_path.exists():
            tmp_path.unlink()


def build_latest_complete_registry(
    bundle_manifest: str | Path,
    *,
    registry_path: str | Path | None = None,
    checked_at: str | None = None,
) -> dict[str, Any]:
    manifest_path = Path(bundle_manifest).expanduser().resolve()
    manifest = _read_json_object(manifest_path, label="bundle manifest")
    registry_target = (
        Path(registry_path).expanduser().resolve()
        if registry_path is not None
        else None
    )
    base_dir = registry_target.parent if registry_target is not None else None
    publication_time = checked_at or _now_iso()
    _parse_timestamp(publication_time, label="latest-complete publication time")
    repositories = _source_repositories(manifest)
    source_commit, source_reason = _primary_source_commit(repositories)
    signals = _health_signals(manifest_path, manifest)
    eligibility = _latest_complete_eligibility(
        manifest_path,
        manifest,
        signals=signals,
        source_commit=source_commit,
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
            "manifest_sha256": _sha256_file(manifest_path),
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
            "serialization": "advisory_file_lock",
            "atomic_replace": True,
            "file_fsync": True,
            "directory_fsync": True,
            "readback_verified": True,
        },
        "mutation_boundary": {
            "writes": [
                "latest_complete_registry",
                "latest_complete_registry_lock",
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


def write_latest_complete_registry(
    bundle_manifest: str | Path,
    output_path: str | Path,
    *,
    checked_at: str | None = None,
) -> dict[str, Any]:
    out = _publication_target(output_path)
    candidate = build_latest_complete_registry(
        bundle_manifest,
        registry_path=out,
        checked_at=checked_at,
    )
    candidate_selection = _selection_from_registry(candidate)
    out.parent.mkdir(parents=True, exist_ok=True)
    out = _publication_target(out)
    lock_path = out.parent / f".{out.name}.lock"
    lock_fd = _open_lock_file(lock_path)
    publication_result = "published"
    published_registry: dict[str, Any] = candidate
    reason = "first_publication"
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        existing = _read_existing_registry(out)
        if existing is not None:
            existing_selection = _selection_from_registry(existing)
            if existing_selection["source_lane"] != candidate_selection["source_lane"]:
                raise ValueError("latest-complete registry source lane mismatch")
            candidate_time = candidate_selection["generated_at"]
            existing_time = existing_selection["generated_at"]
            if candidate_time < existing_time:
                publication_result = "unchanged"
                published_registry = existing
                reason = "candidate_older_than_published"
            elif candidate_time == existing_time:
                if (
                    candidate_selection["manifest_sha256"]
                    != existing_selection["manifest_sha256"]
                ):
                    raise ValueError(
                        "latest-complete candidate order is ambiguous: generated_at collision"
                    )
                publication_result = "unchanged"
                published_registry = existing
                reason = "candidate_already_published"
            else:
                reason = "candidate_newer_than_published"
        if publication_result == "published":
            _atomic_publish_registry(out, candidate)
    finally:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        finally:
            os.close(lock_fd)
    observed_writes = ["latest_complete_registry_lock"]
    if publication_result == "published":
        observed_writes.insert(0, "latest_complete_registry")
    return {
        "kind": WRITE_KIND,
        "version": VERSION,
        "status": "ok",
        "publication_result": publication_result,
        "reason": reason,
        "registry_path": str(out),
        "lock_path": str(lock_path),
        "registry": published_registry,
        "candidate_registry": candidate,
        "mutation_boundary": {
            "writes": [
                "latest_complete_registry",
                "latest_complete_registry_lock",
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


def latest_complete_status(
    registry_path: str | Path,
    *,
    repo: str | Path | None = None,
    checked_at: str | None = None,
) -> dict[str, Any]:
    path = Path(registry_path).expanduser().resolve()
    registry = _read_json_object(path, label="latest-complete registry")
    if registry.get("kind") != KIND:
        raise ValueError(f"latest-complete registry kind must be {KIND}")
    bundle_info = (
        registry.get("bundle") if isinstance(registry.get("bundle"), dict) else {}
    )
    bundle_path = _safe_bundle_path(
        path,
        bundle_info.get("manifest_path") if isinstance(bundle_info, dict) else None,
    )
    manifest_hash_status = "unknown"
    observed_manifest_sha256 = None
    if bundle_path is not None and bundle_path.is_file():
        observed_manifest_sha256 = _sha256_file(bundle_path)
        expected = (
            bundle_info.get("manifest_sha256")
            if isinstance(bundle_info, dict)
            else None
        )
        manifest_hash_status = (
            "match" if expected == observed_manifest_sha256 else "mismatch"
        )
    elif bundle_path is not None:
        manifest_hash_status = "missing"
    freshness = evaluate_registry_freshness(registry, repo=repo, checked_at=checked_at)
    stored_eligibility = (
        registry.get("eligibility")
        if isinstance(registry.get("eligibility"), dict)
        else None
    )
    observed_eligibility: dict[str, Any] | None = None
    sidecar_hash_drift: list[str] = []
    if (
        bundle_path is not None
        and bundle_path.is_file()
        and manifest_hash_status == "match"
    ):
        try:
            manifest = _read_json_object(bundle_path, label="bundle manifest")
            repositories = _source_repositories(manifest)
            source_commit, _ = _primary_source_commit(repositories)
            observed_signals = _health_signals(bundle_path, manifest)
            observed_eligibility = _latest_complete_eligibility(
                bundle_path,
                manifest,
                signals=observed_signals,
                source_commit=source_commit,
                reference_time=str(
                    registry.get("updated_at") or checked_at or _now_iso()
                ),
            )
            stored_signals = (
                registry.get("health", {}).get("signals")
                if isinstance(registry.get("health"), dict)
                else {}
            )
            if isinstance(stored_signals, dict):
                for role, signal in observed_signals.items():
                    stored = stored_signals.get(role)
                    stored_sha = (
                        stored.get("sha256") if isinstance(stored, dict) else None
                    )
                    observed_sha = (
                        signal.get("sha256") if isinstance(signal, dict) else None
                    )
                    if stored_sha is not None and stored_sha != observed_sha:
                        sidecar_hash_drift.append(role)
        except (OSError, ValueError) as exc:
            observed_eligibility = {
                "status": "fail",
                "errors": [str(exc)],
                "checks": {},
            }
    status = "ok"
    if manifest_hash_status in {"mismatch", "missing"}:
        status = "warn"
    if stored_eligibility is None or stored_eligibility.get("status") != "pass":
        status = "warn"
    if (
        observed_eligibility is not None
        and observed_eligibility.get("status") != "pass"
    ):
        status = "warn"
    if sidecar_hash_drift:
        status = "warn"
    return {
        "kind": STATUS_KIND,
        "version": VERSION,
        "status": status,
        "registry_path": str(path),
        "registry": registry,
        "bundle_manifest": str(bundle_path) if bundle_path is not None else None,
        "manifest_hash": {
            "status": manifest_hash_status,
            "expected_sha256": bundle_info.get("manifest_sha256")
            if isinstance(bundle_info, dict)
            else None,
            "observed_sha256": observed_manifest_sha256,
        },
        "eligibility": {
            "stored": stored_eligibility,
            "observed": observed_eligibility,
            "sidecar_hash_drift": sorted(sidecar_hash_drift),
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
