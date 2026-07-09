"""Explicit RepoBrief MCP-shaped tools.

This module is not a protocol server. It provides deterministic tool handlers
that a future MCP adapter can expose. Read-only RepoBrief access helpers must
not call these handlers as a fallback or side effect.
"""
from __future__ import annotations

import argparse
import signal
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from merger.lenskit.cli.cmd_repobrief import build_snapshot_create_result
from merger.lenskit.core.merge import parse_human_size
from merger.lenskit.core.repobrief_profiles import profile_names

KIND = "repobrief.mcp.snapshot_create"
VERSION = "v1"
DEFAULT_TIMEOUT_SECONDS = 300
MAX_TIMEOUT_SECONDS = 1800
DEFAULT_MAX_FILE_BYTES = "25MB"
DEFAULT_MAX_TOTAL_BYTES = "512MB"
DEFAULT_SPLIT_SIZE = "25MB"
MCP_PLATFORM = "mcp-explicit-tool"

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
    "review_complete",
    "pr_mergeable",
    "mcp_server_available",
)

FORBIDDEN_OPERATIONS = (
    "git_push",
    "git_pull",
    "git_fetch",
    "create_pr",
    "apply_patch",
    "run_shell",
    "auto_review",
    "auto_fix",
    "auto_merge",
    "secret_read",
)


class RepoBriefMcpToolError(ValueError):
    """Raised when an explicit MCP tool request violates RepoBrief bounds."""


class RepoBriefMcpToolTimeout(TimeoutError):
    """Raised when an explicit MCP tool exceeds its timeout guard."""


@contextmanager
def _timeout_guard(seconds: int) -> Iterator[None]:
    if seconds <= 0:
        raise RepoBriefMcpToolError("timeout_seconds must be positive")
    if threading.current_thread() is not threading.main_thread():
        raise RepoBriefMcpToolError(
            "timeout guard requires main thread or an external process-level timeout wrapper"
        )
    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.setitimer(signal.ITIMER_REAL, 0)

    def _handler(_signum: int, _frame: object) -> None:
        raise RepoBriefMcpToolTimeout(f"snapshot_create exceeded {seconds}s timeout")

    signal.signal(signal.SIGALRM, _handler)
    signal.setitimer(signal.ITIMER_REAL, float(seconds))
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        if previous_timer[0] > 0:
            signal.setitimer(signal.ITIMER_REAL, previous_timer[0], previous_timer[1])


def _guarded_path(raw: str | Path, *, label: str) -> Path:
    path = Path(raw).expanduser().resolve()
    if not str(path):
        raise RepoBriefMcpToolError(f"{label} is required")
    return path


def _path_is_within(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
    except ValueError:
        return False
    return True


def _resolve_output_dir(output_root: str | Path, output_subdir: str | None) -> tuple[Path, Path]:
    root = _guarded_path(output_root, label="output_root")
    if output_subdir is None or output_subdir == "":
        return root, root
    raw = Path(output_subdir)
    if raw.is_absolute() or ".." in raw.parts:
        raise RepoBriefMcpToolError("output_subdir must be relative and must not contain '..'")
    out = (root / raw).resolve()
    if not _path_is_within(out, root):
        raise RepoBriefMcpToolError("output_subdir must remain inside output_root")
    return root, out


def _file_visible(path: Path, repo: Path, include_hidden: bool) -> bool:
    try:
        rel = path.relative_to(repo)
    except ValueError:
        return False
    if ".git" in rel.parts:
        return False
    if include_hidden:
        return True
    return not any(part.startswith(".") for part in rel.parts)


def _estimate_repo_bytes(repo: Path, *, include_hidden: bool) -> int:
    total = 0
    for path in repo.rglob("*"):
        if not path.is_file() or not _file_visible(path, repo, include_hidden):
            continue
        total += path.stat().st_size
    return total


def _mutation_boundary() -> dict[str, Any]:
    return {
        "writes": ["brief_bundle_artifacts"],
        "does_not_mutate": ["git", "pull_requests", "patches", "source_working_tree"],
        "read_paths_do_not_refresh": True,
        "explicit_write_tool": True,
        "not_reachable_from_read_tools": True,
        "forbidden_operations": list(FORBIDDEN_OPERATIONS),
    }


def _tool_args(
    *,
    repo: Path,
    out: Path,
    profile: str,
    output_mode: str | None,
    max_file_bytes: str,
    split_size: str,
    include_hidden: bool,
    path_filter: str | None,
    ext: list[str] | None,
    redact_secrets: bool,
) -> argparse.Namespace:
    return argparse.Namespace(
        repo=str(repo),
        out=str(out),
        profile=profile,
        output_mode=output_mode,
        mode="gesamt",
        max_bytes=max_file_bytes,
        split_size=split_size,
        path_filter=path_filter,
        ext=ext,
        include_hidden=include_hidden,
        redact_secrets=redact_secrets,
        platform=MCP_PLATFORM,
    )


def snapshot_create(
    *,
    repo: str | Path,
    output_root: str | Path,
    profile: str,
    output_subdir: str | None = None,
    output_mode: str | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    max_file_bytes: str = DEFAULT_MAX_FILE_BYTES,
    max_total_bytes: str = DEFAULT_MAX_TOTAL_BYTES,
    split_size: str = DEFAULT_SPLIT_SIZE,
    include_hidden: bool = False,
    path_filter: str | None = None,
    ext: list[str] | None = None,
    redact_secrets: bool = True,
) -> dict[str, Any]:
    """Run the explicit RepoBrief snapshot_create tool under MCP guards."""
    repo_path = _guarded_path(repo, label="repo")
    if not repo_path.is_dir():
        raise RepoBriefMcpToolError(f"repo is not a directory: {repo_path}")
    output_root_path, out_path = _resolve_output_dir(output_root, output_subdir)
    if out_path == repo_path or _path_is_within(out_path, repo_path):
        raise RepoBriefMcpToolError("output directory must not be the repository or inside it")
    if profile not in profile_names():
        raise RepoBriefMcpToolError(f"unsupported profile: {profile}")
    if timeout_seconds > MAX_TIMEOUT_SECONDS:
        raise RepoBriefMcpToolError(
            f"timeout_seconds exceeds maximum {MAX_TIMEOUT_SECONDS}: {timeout_seconds}"
        )
    max_total = parse_human_size(max_total_bytes)
    estimated_total = _estimate_repo_bytes(repo_path, include_hidden=include_hidden)
    if max_total and estimated_total > max_total:
        raise RepoBriefMcpToolError(
            f"repo content estimate {estimated_total} exceeds max_total_bytes {max_total}"
        )
    args = _tool_args(
        repo=repo_path,
        out=out_path,
        profile=profile,
        output_mode=output_mode,
        max_file_bytes=max_file_bytes,
        split_size=split_size,
        include_hidden=include_hidden,
        path_filter=path_filter,
        ext=ext,
        redact_secrets=redact_secrets,
    )
    with _timeout_guard(timeout_seconds):
        created = build_snapshot_create_result(args)
    return {
        "kind": KIND,
        "version": VERSION,
        "status": "ok",
        "tool": "snapshot_create",
        "repo": str(repo_path),
        "output_root": str(output_root_path),
        "out": str(out_path),
        "profile": profile,
        "timeout_seconds": timeout_seconds,
        "size_guards": {
            "max_file_bytes": max_file_bytes,
            "max_total_bytes": max_total_bytes,
            "estimated_repo_bytes": estimated_total,
            "include_hidden": include_hidden,
        },
        "created_snapshot": created,
        "bundle_manifest": created.get("bundle_manifest"),
        "mutation_boundary": _mutation_boundary(),
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }

READ_ONLY_KIND = "repobrief.mcp.read_only_frontdoor"
READ_ONLY_VERSION = "v1"
READ_ONLY_FORBIDDEN_OPERATIONS = (
    "git_push",
    "git_pull",
    "git_fetch",
    "create_pr",
    "apply_patch",
    "run_shell",
    "auto_review",
    "auto_fix",
    "auto_merge",
    "secret_read",
    "snapshot_create_side_effect",
)


def _read_only_boundary() -> dict[str, Any]:
    return {
        "writes": [],
        "does_not_mutate": [
            "git",
            "pull_requests",
            "patches",
            "source_working_tree",
            "brief_bundle_artifacts",
            "secrets",
        ],
        "read_paths_do_not_refresh": True,
        "explicit_write_tool": False,
        "not_reachable_from_snapshot_create": True,
        "forbidden_operations": list(READ_ONLY_FORBIDDEN_OPERATIONS),
    }


def ask_context(
    *,
    bundle_manifest: str | Path,
    query: str,
    task_profile: str = "basic_repo_question",
    max_context_tokens: int = 8000,
    max_answer_tokens: int = 1200,
    k: int = 5,
) -> dict[str, Any]:
    """MCP-shaped read-only frontdoor for RepoBrief ask context packs."""
    from merger.lenskit.core.repobrief_ask import build_ask_context_pack

    context_pack = build_ask_context_pack(
        bundle_manifest,
        query=query,
        task_profile=task_profile,
        max_context_tokens=max_context_tokens,
        max_answer_tokens=max_answer_tokens,
        k=k,
    )
    return {
        "kind": READ_ONLY_KIND,
        "version": READ_ONLY_VERSION,
        "tool": "ask_context",
        "status": "ok",
        "context_pack": context_pack,
        "request_semantics": "repobrief.ask_request.v1",
        "context_pack_semantics": "repobrief.ask_context_pack.v1",
        "mutation_boundary": _read_only_boundary(),
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }


def grounding_verify(
    *,
    declaration: dict[str, Any],
    bundle_manifest: str | Path,
    citation_map: str | Path | None = None,
    task_profile: str | None = None,
) -> dict[str, Any]:
    """MCP-shaped read-only frontdoor for Answer Grounding verification."""
    from merger.lenskit.core.answer_grounding import verify_answer_grounding_for_task_profile

    verdict = verify_answer_grounding_for_task_profile(
        declaration,
        bundle_manifest=bundle_manifest,
        citation_map=citation_map,
        task_profile=task_profile,
    )
    return {
        "kind": READ_ONLY_KIND,
        "version": READ_ONLY_VERSION,
        "tool": "grounding_verify",
        "status": verdict.get("status", "degraded"),
        "verdict": verdict,
        "declaration_semantics": "repobrief.answer_grounding_declaration.v1",
        "verdict_semantics": "repobrief.answer_grounding_verdict.v1",
        "mutation_boundary": _read_only_boundary(),
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }
