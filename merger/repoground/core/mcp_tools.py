"""Explicit RepoGround MCP-shaped tools.

This module is not a protocol server. It provides deterministic tool handlers
that a future MCP adapter can expose. Read-only RepoGround access helpers must
not call these handlers as a fallback or side effect.
"""
from __future__ import annotations

import argparse
import signal
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from merger.repoground.cli.cmd_ground import build_snapshot_create_result
from merger.repoground.core.merge import parse_human_size
from merger.repoground.core.response_projection import (
    compact_does_not_establish,
    compact_mutation_boundary,
)
from merger.repoground.core.snapshot_profiles import profile_names

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


class RepoGroundMcpToolError(ValueError):
    """Raised when an explicit MCP tool request violates RepoGround bounds."""


class RepoGroundMcpToolTimeout(TimeoutError):
    """Raised when an explicit MCP tool exceeds its timeout guard."""


@contextmanager
def _timeout_guard(seconds: int) -> Iterator[None]:
    if seconds <= 0:
        raise RepoGroundMcpToolError("timeout_seconds must be positive")
    if threading.current_thread() is not threading.main_thread():
        raise RepoGroundMcpToolError(
            "timeout guard requires main thread or an external process-level timeout wrapper"
        )
    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.setitimer(signal.ITIMER_REAL, 0)

    def _handler(_signum: int, _frame: object) -> None:
        raise RepoGroundMcpToolTimeout(f"snapshot_create exceeded {seconds}s timeout")

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
        raise RepoGroundMcpToolError(f"{label} is required")
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
        raise RepoGroundMcpToolError("output_subdir must be relative and must not contain '..'")
    out = (root / raw).resolve()
    if not _path_is_within(out, root):
        raise RepoGroundMcpToolError("output_subdir must remain inside output_root")
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
    """Run the explicit RepoGround snapshot_create tool under MCP guards."""
    repo_path = _guarded_path(repo, label="repo")
    if not repo_path.is_dir():
        raise RepoGroundMcpToolError(f"repo is not a directory: {repo_path}")
    output_root_path, out_path = _resolve_output_dir(output_root, output_subdir)
    if out_path == repo_path or _path_is_within(out_path, repo_path):
        raise RepoGroundMcpToolError("output directory must not be the repository or inside it")
    if profile not in profile_names():
        raise RepoGroundMcpToolError(f"unsupported profile: {profile}")
    if timeout_seconds > MAX_TIMEOUT_SECONDS:
        raise RepoGroundMcpToolError(
            f"timeout_seconds exceeds maximum {MAX_TIMEOUT_SECONDS}: {timeout_seconds}"
        )
    max_total = parse_human_size(max_total_bytes)
    estimated_total = _estimate_repo_bytes(repo_path, include_hidden=include_hidden)
    if max_total and estimated_total > max_total:
        raise RepoGroundMcpToolError(
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


def _read_only_boundary(*, verbose: bool = False) -> dict[str, Any]:
    full = {
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
    return full if verbose else compact_mutation_boundary(full)


def _read_only_does_not_establish(*, verbose: bool = False) -> Any:
    full = list(DOES_NOT_ESTABLISH)
    return full if verbose else compact_does_not_establish(full)


def ask_context(
    *,
    bundle_manifest: str | Path,
    query: str,
    task_profile: str = "basic_repo_question",
    max_context_tokens: int = 8000,
    max_answer_tokens: int = 1200,
    k: int = 5,
    verbose: bool = False,
) -> dict[str, Any]:
    """MCP-shaped read-only frontdoor for RepoGround ask context packs.

    The ``context_pack`` itself keeps its full, schema-pinned shape
    regardless of ``verbose`` (its freshness/availability/non-claim fields
    are already the compact form defined by that contract). ``verbose``
    controls only this wrapper's own repeated mutation-boundary and
    non-claim envelope, which is otherwise projected to a compact reference
    by default.
    """
    from merger.repoground.core.ask_context import build_ask_context_pack

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
        "mutation_boundary": _read_only_boundary(verbose=verbose),
        "does_not_establish": _read_only_does_not_establish(verbose=verbose),
    }


def grounding_verify(
    *,
    declaration: dict[str, Any],
    bundle_manifest: str | Path,
    citation_map: str | Path | None = None,
    task_profile: str | None = None,
    verbose: bool = False,
) -> dict[str, Any]:
    """MCP-shaped read-only frontdoor for Answer Grounding verification.

    The verdict itself is untouched by ``verbose``; only this wrapper's own
    repeated mutation-boundary and non-claim envelope is projected to a
    compact reference by default.
    """
    from merger.repoground.core.answer_grounding import verify_answer_grounding_for_task_profile

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
        "mutation_boundary": _read_only_boundary(verbose=verbose),
        "does_not_establish": _read_only_does_not_establish(verbose=verbose),
    }


FIND_SYMBOL_KINDS = ("class", "function", "async_function")


def _find_symbol_result(status: str, result: dict[str, Any], *, verbose: bool = False) -> dict[str, Any]:
    return {
        "kind": READ_ONLY_KIND,
        "version": READ_ONLY_VERSION,
        "tool": "find_symbol",
        "status": status,
        "result": result,
        "result_semantics": "repobrief.symbol_search.v1",
        "mutation_boundary": _read_only_boundary(verbose=verbose),
        "does_not_establish": _read_only_does_not_establish(verbose=verbose),
    }


def find_symbol(
    *,
    bundle_manifest: str | Path,
    name: str,
    kind: str | None = None,
    path: str | None = None,
    k: int = 25,
    verbose: bool = False,
) -> dict[str, Any]:
    """MCP-shaped read-only frontdoor for symbol-definition lookup.

    Locates Python symbol definitions (function/class/async_function) in the
    snapshot's deterministic symbol index, ranking exact matches first. Answers
    "where is X defined?" with a path and line range — the navigation primitive
    that content retrieval (ask_context) does not provide. It does not establish
    that a symbol is called, correct, or fresh against the working tree.

    Fails closed: an empty name or an unknown kind is rejected rather than
    silently listing the first ``k`` symbols.

    By default (``verbose=False``) the response is the compact projection:
    hits, status, truncation and any explicit availability/freshness gap, but
    not the full per-role availability/graph inventory. Pass ``verbose=True``
    for the complete diagnostic inventory (not deleted, just not the default).
    """
    from merger.repoground.core.bundle_access import search_symbol_index

    def _invalid(error: str, error_code: str) -> dict[str, Any]:
        return _find_symbol_result(
            "invalid",
            {
                "kind": "repobrief.symbol_search",
                "version": "v1",
                "status": "invalid",
                "error": error,
                "error_code": error_code,
                "hits": [],
                "hit_count": 0,
            },
            verbose=verbose,
        )

    if not isinstance(name, str) or not name.strip():
        return _invalid("name must be a non-empty string", "name_invalid")
    if kind is not None and kind not in FIND_SYMBOL_KINDS:
        return _invalid(
            f"kind must be one of {list(FIND_SYMBOL_KINDS)} or null", "kind_invalid"
        )

    result = search_symbol_index(
        bundle_manifest, name, k=k, kind=kind, path=path, verbose=verbose
    )
    return _find_symbol_result(result.get("status", "invalid"), result, verbose=verbose)


MAX_CALL_NAVIGATION_K = 200


def _call_navigation_result(
    tool: str,
    status: str,
    result: dict[str, Any],
    result_semantics: str,
    *,
    verbose: bool = False,
) -> dict[str, Any]:
    return {
        "kind": READ_ONLY_KIND,
        "version": READ_ONLY_VERSION,
        "tool": tool,
        "status": status,
        "result": result,
        "result_semantics": result_semantics,
        "mutation_boundary": _read_only_boundary(verbose=verbose),
        "does_not_establish": _read_only_does_not_establish(verbose=verbose),
    }


def find_references(
    *,
    bundle_manifest: str | Path,
    name: str,
    path: str | None = None,
    k: int = 25,
    verbose: bool = False,
) -> dict[str, Any]:
    """MCP-shaped read-only frontdoor for static call-site reference lookup.

    Answers "where is X called?" from the snapshot's python_call_graph artifact:
    exact callee-name matches first, stable order, bounded by ``k``. It does not
    establish a complete call graph, runtime reachability or dynamic dispatch.

    Fails closed: an empty name is rejected; a missing or invalid call graph
    artifact yields a missing/invalid result and never triggers a refresh.

    By default (``verbose=False``) the response is the compact projection
    (see ``find_symbol``); pass ``verbose=True`` for the full inventory.
    """
    from merger.repoground.core.bundle_access import (
        find_references as access_find_references,
    )

    result = access_find_references(
        bundle_manifest, name, path=path, k=k, verbose=verbose
    )
    return _call_navigation_result(
        "find_references",
        result.get("status", "invalid"),
        result,
        "repobrief.call_reference_search.v1",
        verbose=verbose,
    )


def get_callers(
    *,
    bundle_manifest: str | Path,
    name: str,
    path: str | None = None,
    k: int = 25,
    verbose: bool = False,
) -> dict[str, Any]:
    """MCP-shaped read-only frontdoor for grouped caller lookup.

    Answers "who calls X?" after selecting one exact symbol from the coherent
    symbol index. Only S1 call edges to that symbol become callers; unresolved
    textual similarities stay separately visible.

    Fails closed like ``find_references``; reads never refresh the snapshot.
    By default (``verbose=False``) the response is the compact projection;
    pass ``verbose=True`` for the full inventory.
    """
    from merger.repoground.core.bundle_access import (
        get_callers as access_get_callers,
    )

    result = access_get_callers(
        bundle_manifest, name, path=path, k=k, verbose=verbose
    )
    return _call_navigation_result(
        "get_callers",
        result.get("status", "invalid"),
        result,
        "repobrief.call_callers.v1",
        verbose=verbose,
    )


def get_callees(
    *,
    bundle_manifest: str | Path,
    name: str,
    path: str | None = None,
    k: int = 25,
    verbose: bool = False,
) -> dict[str, Any]:
    """MCP-shaped read-only frontdoor for one symbol's outgoing calls.

    The caller symbol must resolve exactly in the coherent symbol index. Unique
    S1 targets are grouped as callees; S0 call sites remain separately visible.
    Reads never refresh the snapshot and do not establish runtime reachability.
    By default (``verbose=False``) the response is the compact projection;
    pass ``verbose=True`` for the full inventory.
    """
    from merger.repoground.core.bundle_access import (
        get_callees as access_get_callees,
    )

    result = access_get_callees(
        bundle_manifest, name, path=path, k=k, verbose=verbose
    )
    return _call_navigation_result(
        "get_callees",
        result.get("status", "invalid"),
        result,
        "repobrief.call_callees.v1",
        verbose=verbose,
    )
