"""Source-repository provenance for RepoBrief snapshots."""
from __future__ import annotations

import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

PROVENANCE_STATUS_VALUES = (
    "present",
    "not_git_checkout",
    "git_unavailable",
    "unavailable_environment",
    "producer_did_not_collect",
)

DOES_NOT_ESTABLISH = (
    "freshness_against_remote",
    "working_tree_clean_for_all_tools",
    "pull_request_diff_current",
    "runtime_correctness",
    "repo_understood",
    "merge_readiness",
)


def _supports_git_subprocess_probe() -> bool:
    return sys.platform != "ios"


def _git(repo_root: Path, *args: str) -> tuple[str | None, str | None]:
    try:
        out = subprocess.run(
            ["git", "-C", str(repo_root), *args],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, RuntimeError, subprocess.SubprocessError):
        return None, "git_unavailable"
    if out.returncode != 0:
        return None, "git_error"
    return out.stdout.strip(), None


def repository_snapshot_provenance(repo_root: str | Path, *, redact: bool = False) -> dict[str, Any]:
    """Return explicit provenance/freshness fields for one scanned repo."""
    root = Path(repo_root).resolve()
    base: dict[str, Any] = {
        "name": root.name,
        "repo_root": None if redact else str(root),
        "repo_remote": None,
        "git_commit": None,
        "git_dirty": None,
        "git_branch": None,
        "provenance_status": "producer_did_not_collect",
        "freshness_basis": "unknown",
    }

    if not _supports_git_subprocess_probe():
        base["provenance_status"] = "unavailable_environment"
        return base

    top, err = _git(root, "rev-parse", "--show-toplevel")
    if err == "git_unavailable":
        base["provenance_status"] = "git_unavailable"
        return base
    if err is not None or not top:
        base["provenance_status"] = "not_git_checkout"
        return base

    commit, err = _git(root, "rev-parse", "HEAD")
    if err == "git_unavailable":
        base["provenance_status"] = "git_unavailable"
        return base
    if err is not None or not commit:
        base["provenance_status"] = "not_git_checkout"
        return base

    branch, _ = _git(root, "rev-parse", "--abbrev-ref", "HEAD")
    remote, remote_err = _git(root, "config", "--get", "remote.origin.url")
    status, status_err = _git(root, "status", "--porcelain")

    base.update(
        {
            "repo_remote": remote if remote_err is None and remote else None,
            "git_commit": commit,
            "git_dirty": None if status_err is not None else bool(status),
            "git_branch": branch if branch else None,
            "provenance_status": "present",
            "freshness_basis": "git_commit",
        }
    )
    return base


def build_snapshot_provenance(
    repo_summaries: Sequence[Mapping[str, Any]],
    *,
    redact: bool = False,
) -> dict[str, Any]:
    repositories = [
        repository_snapshot_provenance(summary.get("root"), redact=redact)
        for summary in repo_summaries
        if summary.get("root") is not None
    ]
    return {
        "version": "v1",
        "repositories": repositories,
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }
