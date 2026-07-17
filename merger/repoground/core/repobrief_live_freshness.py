"""Compare a RepoGround snapshot with one explicit local Git working tree."""
from __future__ import annotations

from .bundle_identity import is_bundle_manifest

import json
import os
import subprocess
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

KIND = "repobrief.live_freshness"
VERSION = "v1"
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
GIT_TIMEOUT_SECONDS = 5
FRESHNESS_VALUES = ("fresh", "stale", "unknown", "not_comparable")
DOES_NOT_ESTABLISH = (
    "freshness_against_remote",
    "remote_branch_state",
    "pull_request_diff_current",
    "runtime_correctness",
    "repo_understood",
    "merge_readiness",
)

Probe = Callable[[str | Path], dict[str, Any]]


def _load_manifest(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            raw = handle.read(MAX_MANIFEST_BYTES + 1)
    except OSError as exc:
        raise ValueError(f"bundle manifest cannot be read: {path}") from exc
    if len(raw) > MAX_MANIFEST_BYTES:
        raise ValueError("bundle manifest exceeds live-freshness size limit")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("bundle manifest is not valid UTF-8 JSON") from exc
    if not isinstance(data, dict):
        raise ValueError("bundle manifest must be a JSON object")
    if (
        not is_bundle_manifest(data)
        or not isinstance(data.get("run_id"), str)
        or not isinstance(data.get("artifacts"), list)
    ):
        raise ValueError("bundle manifest does not have RepoGround manifest shape")
    return data


def _git_environment() -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_TERMINAL_PROMPT": "0",
        }
    )
    return env


def _git(repo_root: Path, *args: str) -> tuple[str | None, str | None]:
    command = [
        "git",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.untrackedCache=false",
        "-C",
        str(repo_root),
        *args,
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SECONDS,
            check=False,
            env=_git_environment(),
        )
    except (OSError, RuntimeError, subprocess.SubprocessError):
        return None, "git_unavailable"
    if completed.returncode != 0:
        return None, "git_error"
    return completed.stdout.strip(), None


def repository_live_provenance(repo_root: str | Path) -> dict[str, Any]:
    """Collect bounded local Git state without network access or optional locks."""
    root = Path(repo_root).expanduser().resolve()
    base: dict[str, Any] = {
        "name": root.name,
        "repo_root": str(root),
        "git_commit": None,
        "git_dirty": None,
        "git_branch": None,
        "provenance_status": "producer_did_not_collect",
        "freshness_basis": "unknown",
        "probe_guards": {
            "network": False,
            "optional_locks": False,
            "fsmonitor": False,
            "global_git_config": False,
        },
    }
    if sys.platform == "ios":
        base["provenance_status"] = "unavailable_environment"
        return base
    if not root.is_dir():
        base["provenance_status"] = "not_git_checkout"
        return base

    top, error = _git(root, "rev-parse", "--show-toplevel")
    if error == "git_unavailable":
        base["provenance_status"] = "git_unavailable"
        return base
    if error is not None or not top:
        base["provenance_status"] = "not_git_checkout"
        return base

    commit, error = _git(root, "rev-parse", "HEAD")
    if error == "git_unavailable":
        base["provenance_status"] = "git_unavailable"
        return base
    if error is not None or not commit:
        base["provenance_status"] = "not_git_checkout"
        return base

    branch, _branch_error = _git(root, "symbolic-ref", "--short", "-q", "HEAD")
    status, status_error = _git(
        root,
        "status",
        "--porcelain=v1",
        "--untracked-files=normal",
    )
    base.update(
        {
            "git_commit": commit,
            "git_dirty": None if status_error is not None else bool(status),
            "git_branch": branch or None,
            "provenance_status": "present",
            "freshness_basis": "git_commit_and_working_tree",
        }
    )
    return base


def _repository_records(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    provenance = manifest.get("snapshot_provenance")
    repositories = provenance.get("repositories") if isinstance(provenance, dict) else None
    if not isinstance(repositories, list):
        return []
    return [record for record in repositories if isinstance(record, dict)]


def _record_for_repo(
    records: list[dict[str, Any]],
    repo_root: Path,
) -> dict[str, Any] | None:
    resolved = str(repo_root.resolve())
    exact = [record for record in records if record.get("repo_root") == resolved]
    if len(exact) == 1:
        return exact[0]
    named = [record for record in records if record.get("name") == repo_root.name]
    if len(named) == 1 and not named[0].get("repo_root"):
        return named[0]
    return None


def _base(
    *,
    status: str,
    reason: str,
    manifest_path: Path,
    repo_root: Path | None,
    snapshot: Mapping[str, Any] | None = None,
    current: Mapping[str, Any] | None = None,
    read_only_git_probe: bool = True,
) -> dict[str, Any]:
    return {
        "kind": KIND,
        "version": VERSION,
        "status": status,
        "reason": reason,
        "freshness_values": list(FRESHNESS_VALUES),
        "bundle_manifest": str(manifest_path),
        "repo_root": str(repo_root) if repo_root is not None else None,
        "snapshot_provenance": dict(snapshot) if snapshot is not None else None,
        "current_provenance": dict(current) if current is not None else None,
        "read_only_git_probe": read_only_git_probe,
        "implicit_refresh": False,
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }


def _snapshot_gate(
    snapshot: Mapping[str, Any],
    *,
    manifest_path: Path,
    repo_root: Path,
) -> dict[str, Any] | None:
    if snapshot.get("provenance_status") != "present" or not snapshot.get("git_commit"):
        return _base(
            status="unknown",
            reason="snapshot_git_provenance_unavailable",
            manifest_path=manifest_path,
            repo_root=repo_root,
            snapshot=snapshot,
        )
    if snapshot.get("git_dirty") is True:
        return _base(
            status="stale",
            reason="snapshot_was_created_from_dirty_working_tree",
            manifest_path=manifest_path,
            repo_root=repo_root,
            snapshot=snapshot,
        )
    if snapshot.get("git_dirty") is not False:
        return _base(
            status="unknown",
            reason="snapshot_working_tree_cleanliness_unavailable",
            manifest_path=manifest_path,
            repo_root=repo_root,
            snapshot=snapshot,
        )
    return None


def _current_gate(
    current: Mapping[str, Any],
    *,
    manifest_path: Path,
    repo_root: Path,
    snapshot: Mapping[str, Any],
) -> dict[str, Any] | None:
    common = {
        "manifest_path": manifest_path,
        "repo_root": repo_root,
        "snapshot": snapshot,
        "current": current,
    }
    if current.get("provenance_status") != "present" or not current.get("git_commit"):
        return _base(
            status="not_comparable",
            reason="current_git_provenance_unavailable",
            **common,
        )
    if current.get("git_dirty") is True:
        return _base(
            status="stale",
            reason="current_working_tree_is_dirty",
            **common,
        )
    if current.get("git_dirty") is not False:
        return _base(
            status="not_comparable",
            reason="current_working_tree_cleanliness_unavailable",
            **common,
        )
    return None


def evaluate_live_freshness(
    bundle_manifest: str | Path,
    *,
    repo_root: str | Path | None = None,
    probe: Probe = repository_live_provenance,
) -> dict[str, Any]:
    """Compare snapshot provenance with one explicitly authorized local checkout."""
    manifest_path = Path(bundle_manifest).expanduser().resolve()
    records = _repository_records(_load_manifest(manifest_path))
    if repo_root is None:
        return _base(
            status="not_comparable",
            reason="repo_root_not_configured",
            manifest_path=manifest_path,
            repo_root=None,
            read_only_git_probe=False,
        )

    explicit_root = Path(repo_root).expanduser().resolve()
    snapshot = _record_for_repo(records, explicit_root)
    if snapshot is None:
        reason = "snapshot_provenance_missing" if not records else "repository_selection_ambiguous"
        return _base(
            status="unknown",
            reason=reason,
            manifest_path=manifest_path,
            repo_root=explicit_root,
        )

    blocked = _snapshot_gate(
        snapshot,
        manifest_path=manifest_path,
        repo_root=explicit_root,
    )
    if blocked is not None:
        return blocked

    current = probe(explicit_root)
    blocked = _current_gate(
        current,
        manifest_path=manifest_path,
        repo_root=explicit_root,
        snapshot=snapshot,
    )
    if blocked is not None:
        return blocked

    if current.get("git_commit") != snapshot.get("git_commit"):
        return _base(
            status="stale",
            reason="git_head_mismatch",
            manifest_path=manifest_path,
            repo_root=explicit_root,
            snapshot=snapshot,
            current=current,
        )
    return _base(
        status="fresh",
        reason="git_head_matches_and_working_tree_is_clean",
        manifest_path=manifest_path,
        repo_root=explicit_root,
        snapshot=snapshot,
        current=current,
    )
