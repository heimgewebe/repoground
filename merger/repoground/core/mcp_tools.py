"""Explicit RepoGround MCP-shaped tools.

This module is not a protocol server. It provides deterministic tool handlers
that a future MCP adapter can expose. Read-only RepoGround access helpers must
not call these handlers as a fallback or side effect.
"""

from __future__ import annotations

import argparse
import re
import signal
import threading
import time
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
_MIN_ITIMER_DELAY_SECONDS = 1e-6
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


class _NestedItimerGuard:
    def __init__(self, seconds: int) -> None:
        self.seconds = seconds
        self.previous_handler = signal.getsignal(signal.SIGALRM)
        self.started = time.monotonic()
        previous_timer = signal.setitimer(signal.ITIMER_REAL, 0)
        self.previous_interval = previous_timer[1]
        self.inner_deadline = self.started + float(seconds)
        self.outer_deadline = (
            self.started + max(previous_timer[0], _MIN_ITIMER_DELAY_SECONDS)
            if previous_timer[0] > 0
            else None
        )
        self.outer_timer_native = False

    def _inner_timeout(self) -> RepoGroundMcpToolTimeout:
        return RepoGroundMcpToolTimeout(
            f"snapshot_create exceeded {self.seconds}s timeout"
        )

    def _arm_inner_timer(self) -> None:
        self.outer_timer_native = False
        delay = max(
            self.inner_deadline - time.monotonic(), _MIN_ITIMER_DELAY_SECONDS
        )
        signal.signal(signal.SIGALRM, self._handle_alarm)
        signal.setitimer(signal.ITIMER_REAL, delay)

    def _invoke_previous_handler(self, signum: int, frame: object) -> None:
        handler = self.previous_handler
        if handler == signal.SIG_DFL:
            signal.raise_signal(signal.SIGALRM)
            return
        if handler == signal.SIG_IGN:
            return
        if not callable(handler):
            raise RepoGroundMcpToolError("unsupported pre-existing SIGALRM handler")
        handler(signum, frame)

    def _dispatch_outer_alarm(self, signum: int, frame: object) -> None:
        signal.signal(signal.SIGALRM, self.previous_handler)
        try:
            self._invoke_previous_handler(signum, frame)
        finally:
            self.previous_handler = signal.getsignal(signal.SIGALRM)

    def _capture_suspended_outer(
        self, observed_at: float, timer: tuple[float, float]
    ) -> None:
        if timer[0] <= 0 and timer[1] <= 0:
            self.outer_deadline = None
            self.previous_interval = 0.0
            return
        self.outer_deadline = observed_at + max(
            timer[0], _MIN_ITIMER_DELAY_SECONDS
        )
        self.previous_interval = timer[1]

    def _resume_after_outer_alarm(self, now: float) -> None:
        current_outer = signal.getitimer(signal.ITIMER_REAL)
        if current_outer[0] <= 0 and current_outer[1] <= 0:
            self.outer_deadline = None
            self.previous_interval = 0.0
            self._arm_inner_timer()
            return
        self.previous_interval = current_outer[1]
        if current_outer[0] <= self.inner_deadline - now:
            self.outer_timer_native = True
            signal.signal(signal.SIGALRM, self._handle_alarm)
            return
        observed_at = time.monotonic()
        suspended_outer = signal.setitimer(signal.ITIMER_REAL, 0)
        self._capture_suspended_outer(observed_at, suspended_outer)
        self._arm_inner_timer()

    def _handle_alarm(self, signum: int, frame: object) -> None:
        if not self.outer_timer_native:
            raise self._inner_timeout()
        if self.previous_interval <= 0:
            self.outer_deadline = None
        self._dispatch_outer_alarm(signum, frame)
        now = time.monotonic()
        if now >= self.inner_deadline:
            raise self._inner_timeout()
        self._resume_after_outer_alarm(now)

    def start(self) -> None:
        signal.signal(signal.SIGALRM, self._handle_alarm)
        if self.outer_deadline is None:
            self._arm_inner_timer()
            return
        outer_delay = max(
            self.outer_deadline - self.started, _MIN_ITIMER_DELAY_SECONDS
        )
        if outer_delay > float(self.seconds):
            self._arm_inner_timer()
            return
        self.outer_timer_native = True
        signal.setitimer(
            signal.ITIMER_REAL, outer_delay, self.previous_interval
        )

    def _capture_native_outer_for_restore(self) -> None:
        observed_at = time.monotonic()
        current_outer = signal.setitimer(signal.ITIMER_REAL, 0)
        if current_outer[0] <= 0 and current_outer[1] <= 0:
            self.outer_deadline = None
            return
        self.outer_deadline = observed_at + max(
            current_outer[0], _MIN_ITIMER_DELAY_SECONDS
        )
        self.previous_interval = current_outer[1]

    def restore(self) -> None:
        if self.outer_timer_native:
            self._capture_native_outer_for_restore()
        else:
            signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, self.previous_handler)
        if self.outer_deadline is None:
            return
        restore_after = max(
            self.outer_deadline - time.monotonic(), _MIN_ITIMER_DELAY_SECONDS
        )
        signal.setitimer(
            signal.ITIMER_REAL, restore_after, self.previous_interval
        )


@contextmanager
def _timeout_guard(seconds: int) -> Iterator[None]:
    if seconds <= 0:
        raise RepoGroundMcpToolError("timeout_seconds must be positive")
    if threading.current_thread() is not threading.main_thread():
        raise RepoGroundMcpToolError(
            "timeout guard requires main thread or an external process-level timeout wrapper"
        )
    timer_guard = _NestedItimerGuard(seconds)
    timer_guard.start()
    try:
        yield
    finally:
        timer_guard.restore()


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


def _resolve_output_dir(
    output_root: str | Path, output_subdir: str | None
) -> tuple[Path, Path]:
    root = _guarded_path(output_root, label="output_root")
    if output_subdir is None or output_subdir == "":
        return root, root
    raw = Path(output_subdir)
    if raw.is_absolute() or ".." in raw.parts:
        raise RepoGroundMcpToolError(
            "output_subdir must be relative and must not contain '..'"
        )
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
        raise RepoGroundMcpToolError(
            "output directory must not be the repository or inside it"
        )
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
    max_context_bytes: int | None = None,
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
        max_context_bytes=max_context_bytes,
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


def snapshot_status(
    *,
    bundle_manifest: str | Path,
    verbose: bool = False,
) -> dict[str, Any]:
    """Return one existing snapshot status with normalized availability semantics."""
    from merger.repoground.core.ask_context import _availability_block, _freshness_block
    from merger.repoground.core.bundle_access import (
        snapshot_status as access_snapshot_status,
    )
    from merger.repoground.core.bundle_catalog import inspect_bundle_health

    snapshot = access_snapshot_status(bundle_manifest)
    availability = _availability_block(snapshot)
    freshness = _freshness_block(snapshot)
    health = inspect_bundle_health(bundle_manifest)
    if availability["status"] != "available":
        status = availability["status"]
    elif health["health_status"] != "pass":
        status = "unhealthy"
    else:
        status = "available"
    return {
        "kind": READ_ONLY_KIND,
        "version": READ_ONLY_VERSION,
        "tool": "snapshot_status",
        "status": status,
        "snapshot": snapshot
        if verbose
        else {
            "bundle_manifest": snapshot.get("bundle_manifest"),
            "bundle_run_id": snapshot.get("bundle_run_id"),
            "profile": snapshot.get("profile"),
            "artifact_count": snapshot.get("artifact_count"),
            "roles": snapshot.get("roles"),
            "health_status": health.get("health_status"),
        },
        "health": health,
        "availability": availability,
        "freshness": freshness,
        "result_semantics": "repobrief.snapshot_status.v1",
        "mutation_boundary": _read_only_boundary(verbose=verbose),
        "does_not_establish": _read_only_does_not_establish(verbose=verbose),
    }


_SYMBOL_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SYMBOL_IN_BACKTICKS_RE = re.compile(r"`([A-Za-z_][A-Za-z0-9_]*)`")
_SYMBOL_AFTER_KIND_RE = re.compile(
    r"\b(?:function|class|method|funktion|klasse|methode)\s+([A-Za-z_][A-Za-z0-9_]*)",
    re.IGNORECASE,
)
_SYMBOL_BEFORE_DEFINITION_RE = re.compile(
    r"\b([A-Za-z_][A-Za-z0-9_]*)\s+(?:defined|definiert)\b",
    re.IGNORECASE,
)
_DEFINITION_INTENT_RE = re.compile(
    r"\b(?:defined|definition|function|class|method|definiert|definition|funktion|klasse|methode)\b",
    re.IGNORECASE,
)


def _symbol_definition_intent(query: str) -> str | None:
    """Extract one conservative identifier from an explicit definition question."""
    if not isinstance(query, str) or not _DEFINITION_INTENT_RE.search(query):
        return None
    for pattern in (
        _SYMBOL_IN_BACKTICKS_RE,
        _SYMBOL_AFTER_KIND_RE,
        _SYMBOL_BEFORE_DEFINITION_RE,
    ):
        match = pattern.search(query)
        if match and _SYMBOL_NAME_RE.fullmatch(match.group(1)):
            return match.group(1)
    return None


def _compact_symbol_hits(
    symbol_result: dict[str, Any], *, name: str, k: int
) -> tuple[list[dict[str, Any]], int]:
    inner = symbol_result.get("result") if isinstance(symbol_result, dict) else None
    hits = inner.get("hits") if isinstance(inner, dict) else []
    exact = []
    for hit in hits if isinstance(hits, list) else []:
        if not isinstance(hit, dict):
            continue
        qualified = hit.get("qualified_name")
        if (
            hit.get("name") != name
            and qualified != name
            and not (isinstance(qualified, str) and qualified.endswith(f".{name}"))
        ):
            continue
        path = hit.get("path")
        if not isinstance(path, str) or not path:
            continue
        exact.append(
            {
                "id": hit.get("id"),
                "kind": hit.get("kind"),
                "name": hit.get("name"),
                "qualified_name": qualified,
                "path": path,
                "start_line": hit.get("start_line"),
                "end_line": hit.get("end_line"),
                "range_ref": hit.get("range_ref"),
                "source_range": hit.get("source_range"),
            }
        )
    exact.sort(
        key=lambda hit: (
            "/tests/" in str(hit["path"]) or str(hit["path"]).startswith("tests/"),
            str(hit["path"]),
            int(hit.get("start_line") or 0),
            str(hit.get("qualified_name") or ""),
        )
    )
    return exact[:k], len(exact)


def _filter_language_structure_for_exact_symbol(
    response: dict[str, Any], *, symbol_name: str
) -> dict[str, Any]:
    document = response.get("content_json")
    if not isinstance(document, dict):
        return response
    records = document.get("records")
    if not isinstance(records, list):
        return response
    expected = symbol_name.casefold()
    exact_records = [
        record
        for record in records
        if isinstance(record, dict)
        and any(
            isinstance(record.get(field), str)
            and record[field].casefold() == expected
            for field in ("symbol", "target_symbol")
        )
    ]
    filtered_document = {**document, "records": exact_records}
    if "record_count" in filtered_document:
        filtered_document["record_count"] = len(exact_records)
    return {**response, "content_json": filtered_document}


def _symbol_query_result(
    *,
    bundle_manifest: str | Path,
    query: str,
    symbol_name: str,
    max_context_tokens: int,
    k: int,
    verbose: bool,
) -> dict[str, Any] | None:
    symbol_result = find_symbol(
        bundle_manifest=bundle_manifest,
        name=symbol_name,
        k=max(k, 10),
        verbose=verbose,
    )
    navigation_hits, exact_hit_count = _compact_symbol_hits(
        symbol_result, name=symbol_name, k=k
    )
    if not navigation_hits:
        return None
    inner = symbol_result.get("result") if isinstance(symbol_result, dict) else {}
    from merger.repoground.core.ask_context import (
        _availability_block,
        _context_budget,
        _freshness_block,
        _language_structure_for_query,
        _merge_language_context,
    )
    from merger.repoground.core.language_structure_access import (
        load_language_structure_artifact,
    )
    from merger.repoground.core.manifest_snapshot import resolve_manifest_path

    availability = _availability_block(
        {"availability_model": inner.get("availability")}
        if isinstance(inner, dict)
        else {}
    )
    freshness = _freshness_block(
        {"freshness": inner.get("freshness")} if isinstance(inner, dict) else {}
    )
    token_derived_byte_ceiling, total_context_bytes = _context_budget(
        max_context_tokens, None
    )
    navigation_retrieval_hits = [
        {
            "artifact_role": "python_symbol_index_json",
            "ref": str(hit.get("id") or hit.get("range_ref") or "symbol"),
            "score": 0.0,
            "purpose": "exact symbol-definition navigation candidate",
        }
        for hit in navigation_hits
    ]
    state: dict[str, Any] = {
        "retrieval_hits": navigation_retrieval_hits,
        "resolved_ranges": [],
        "used_bytes": 0,
        "used_characters": 0,
        "omissions": [],
        "truncated": exact_hit_count > len(navigation_hits),
    }
    manifest_path = resolve_manifest_path(bundle_manifest)
    language_response = _filter_language_structure_for_exact_symbol(
        load_language_structure_artifact(manifest_path), symbol_name=symbol_name
    )
    language_context = _language_structure_for_query(
        manifest_path,
        query=symbol_name,
        k=k,
        max_bytes=total_context_bytes,
        preloaded=language_response,
    )
    language_caveats: list[dict[str, Any]] = []
    structured_evidence = _merge_language_context(
        state, language_caveats, language_context
    )
    result = {
        "kind": READ_ONLY_KIND,
        "version": READ_ONLY_VERSION,
        "tool": "query_existing_index",
        "status": "available",
        "route": "symbol_definition",
        "intent": {"kind": "symbol_definition", "symbol": symbol_name},
        "retrieval": {
            "raw_query": query,
            "fts_query": None,
            "strategy": "symbol_definition",
            "match_count": len(navigation_hits) + len(state["resolved_ranges"]),
        },
        "retrieval_hits": state["retrieval_hits"],
        "navigation_hits": navigation_hits,
        "resolved_ranges": state["resolved_ranges"],
        "budget": {
            "max_context_tokens": max_context_tokens,
            "token_derived_byte_ceiling": token_derived_byte_ceiling,
            "max_context_bytes": total_context_bytes,
            "context_bytes_used": state["used_bytes"],
            "context_unicode_characters_used": state["used_characters"],
            "approx_context_chars_used": state["used_characters"],
            "byte_budget_is_hard": True,
            "unit": "utf8_bytes",
            "accounting": (
                "canonical JSON UTF-8 bytes of emitted language_structure.evidence; "
                "symbol navigation addresses and envelope metadata are outside the "
                "evidence payload budget"
            ),
            "omissions": state["omissions"],
            "truncated": state["truncated"],
            "does_not_establish_quality": True,
        },
        "availability": availability,
        "freshness": freshness,
        "answer_caveats": [
            {
                "kind": "navigation_only",
                "detail": (
                    "Symbol-index hits establish a snapshot path and source line range, "
                    "not source semantics or runtime behavior."
                ),
            },
            *language_caveats,
        ],
        "result_semantics": "repobrief.query_existing_index.agent_frontdoor.v1",
        "mutation_boundary": _read_only_boundary(verbose=verbose),
        "does_not_establish": _read_only_does_not_establish(verbose=verbose),
    }
    if structured_evidence:
        result["structured_evidence"] = structured_evidence
    return result


def query_existing_index(
    *,
    bundle_manifest: str | Path,
    query: str,
    task_profile: str = "basic_repo_question",
    max_context_tokens: int = 2000,
    k: int = 5,
    verbose: bool = False,
) -> dict[str, Any]:
    """Query one existing index through the canonical ask retrieval strategy."""
    from merger.repoground.core.ask_context import build_ask_context_pack

    symbol_name = _symbol_definition_intent(query)
    if symbol_name is not None:
        routed = _symbol_query_result(
            bundle_manifest=bundle_manifest,
            query=query,
            symbol_name=symbol_name,
            max_context_tokens=max_context_tokens,
            k=k,
            verbose=verbose,
        )
        if routed is not None:
            return routed

    pack = build_ask_context_pack(
        bundle_manifest,
        query=query,
        task_profile=task_profile,
        max_context_tokens=max_context_tokens,
        max_answer_tokens=1,
        k=k,
    )
    # The frontdoor status must follow the search backend, not the fact that a
    # pack was produced. A pack is always produced — including when no index
    # exists to query — so hardcoding "available" here is what turned a missing
    # `sqlite_index` into a silent zero-result answer.
    retrieval_infrastructure = pack["retrieval_infrastructure"]
    result = {
        "kind": READ_ONLY_KIND,
        "version": READ_ONLY_VERSION,
        "tool": "query_existing_index",
        # `missing` for an absent index, `invalid` for a rejected request — the
        # same vocabulary `_invalid_read_result` uses for the other read tools.
        "status": (
            "available"
            if retrieval_infrastructure["index_resolved"]
            else retrieval_infrastructure["status"]
        ),
        "route": "text_retrieval",
        "intent": {"kind": "text_retrieval"},
        "retrieval": pack["retrieval"],
        "retrieval_infrastructure": retrieval_infrastructure,
        "retrieval_hits": pack["retrieval_hits"],
        "resolved_ranges": pack["resolved_ranges"],
        "budget": pack["budget"],
        "availability": pack["availability"],
        "freshness": pack["freshness"],
        "answer_caveats": pack["answer_scaffold"]["caveats_to_surface"],
        "result_semantics": "repobrief.query_existing_index.agent_frontdoor.v1",
        "mutation_boundary": _read_only_boundary(verbose=verbose),
        "does_not_establish": _read_only_does_not_establish(verbose=verbose),
    }
    if "structured_evidence" in pack:
        result["structured_evidence"] = pack["structured_evidence"]
    if verbose:
        result["context_pack"] = pack
    return result


def range_get(
    *,
    bundle_manifest: str | Path,
    range_ref: dict[str, Any],
    verbose: bool = False,
) -> dict[str, Any]:
    """Resolve one exact range from an existing bundle without live workspace reads."""
    from merger.repoground.core.bundle_access import range_get as access_range_get

    result = access_range_get(bundle_manifest, range_ref)
    return {
        "kind": READ_ONLY_KIND,
        "version": READ_ONLY_VERSION,
        "tool": "range_get",
        "status": result.get("status", "invalid"),
        "result": result,
        "result_semantics": "repobrief.range_get.v1",
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
    from merger.repoground.core.answer_grounding import (
        verify_answer_grounding_for_task_profile,
    )

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


def _find_symbol_result(
    status: str, result: dict[str, Any], *, verbose: bool = False
) -> dict[str, Any]:
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

    result = access_get_callers(bundle_manifest, name, path=path, k=k, verbose=verbose)
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

    result = access_get_callees(bundle_manifest, name, path=path, k=k, verbose=verbose)
    return _call_navigation_result(
        "get_callees",
        result.get("status", "invalid"),
        result,
        "repobrief.call_callees.v1",
        verbose=verbose,
    )
