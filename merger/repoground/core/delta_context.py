"""Delta-Lens PR context compiler for RepoGround.

This module reads a unified diff and optional existing RepoGround bundle artifacts
and returns bounded review context. It deliberately emits no review verdict,
risk score, approval, rejection or merge readiness claim.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any, Mapping

from merger.repoground.core.graph_degradation import graph_gap_from_availability
from merger.repoground.core.lens_cards import produce_lens_card
from merger.repoground.core.bundle_access import query_existing_index, search_symbol_index, snapshot_status

KIND = "repobrief.delta_context_compiler"
VERSION = "v1"
MAX_DIFF_BYTES = 5_000_000
MAX_FILES = 200
MAX_HUNKS_PER_FILE = 100
MAX_SIGNAL_HITS = 50
MAX_RELATION_CARDS_BYTES = 25_000_000
MAX_RELATION_CARD_LINE_BYTES = 250_000
MAX_RELATION_CARD_SCAN_ROWS = 200_000
DEFAULT_CONTEXT_BUDGET_TOKENS = 8_000
DEFAULT_BYTES_PER_TOKEN = 4.0

DOES_NOT_ESTABLISH = (
    "review_verdict",
    "approval",
    "rejection",
    "merge_readiness",
    "correctness",
    "test_sufficiency",
    "regression_absence",
    "runtime_behavior",
    "security_correctness",
    "risk_score",
    "blast_radius_completeness",
    "all_relevant_context_used",
    "repo_understood",
    "claims_true",
)

_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_DIFF_GIT_RE = re.compile(r"^diff --git (.+?) (.+)$")


def _read_only_boundary() -> dict[str, Any]:
    return {
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
    }


def _invalid_result(*, error: str, error_code: str, diff_path: str | Path | None, task: str | None) -> dict[str, Any]:
    return {
        "kind": KIND,
        "version": VERSION,
        "status": "invalid",
        "diff_path": str(diff_path) if diff_path is not None else None,
        "task": task,
        "error": error,
        "error_code": error_code,
        "changed_files": [],
        "review_context": [],
        "signals": {},
        "gaps": [],
        "mutation_boundary": _read_only_boundary(),
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }


def _rough_size_bytes(value: Any, *, depth: int = 0) -> int:
    if depth > 8:
        return len(str(type(value)).encode("utf-8"))
    if value is None or isinstance(value, bool):
        return 4
    if isinstance(value, (int, float)):
        return len(str(value).encode("utf-8"))
    if isinstance(value, str):
        return len(value.encode("utf-8"))
    if isinstance(value, Mapping):
        total = 2
        for key, item in value.items():
            total += _rough_size_bytes(str(key), depth=depth + 1)
            total += _rough_size_bytes(item, depth=depth + 1)
            total += 2
        return total
    if isinstance(value, list | tuple):
        return sum(_rough_size_bytes(item, depth=depth + 1) + 1 for item in value) + 2
    return len(str(value).encode("utf-8"))


def _estimate_tokens(value: Any, bytes_per_token: float) -> int:
    return max(1, int(math.ceil(_rough_size_bytes(value) / bytes_per_token)))


def _compact(value: str) -> str:
    return "".join(ch for ch in value.casefold() if ch.isalnum())


def _gap(source: str, status: str, reason: str, *, severity: str = "info", **extra: Any) -> dict[str, Any]:
    return {
        "source": source,
        "status": status,
        "severity": severity,
        "reason": reason,
        **extra,
    }


def _has_warn_or_error(gaps: list[dict[str, Any]]) -> bool:
    return any(gap.get("severity") in {"warn", "error"} for gap in gaps)


def _dedupe_ordered(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _safe_path(raw: str | None) -> str | None:
    if raw is None:
        return None
    path = raw.strip()
    if not path or path == "/dev/null":
        return None
    if path.startswith("a/") or path.startswith("b/"):
        path = path[2:]
    if path.startswith("/") or "\\" in path or "//" in path or path.endswith("/"):
        return None
    parts = path.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        return None
    return path


def _line_range(start: int, count: int, *, fallback_old: bool = False) -> dict[str, Any]:
    if count <= 0:
        return {"start_line": start, "end_line": start, "line_count": 0, "empty": True, "basis": "old" if fallback_old else "new"}
    return {"start_line": start, "end_line": start + count - 1, "line_count": count, "empty": False, "basis": "old" if fallback_old else "new"}


def _surrounding_range(range_info: Mapping[str, Any], *, window: int) -> dict[str, Any]:
    start = int(range_info.get("start_line") or 1)
    end = int(range_info.get("end_line") or start)
    return {
        "start_line": max(1, start - window),
        "end_line": max(start, end + window),
        "window_lines": window,
        "basis": range_info.get("basis"),
    }


def parse_unified_diff(diff_text: str, *, context_window_lines: int = 20, max_files: int = MAX_FILES) -> dict[str, Any]:
    """Parse a bounded subset of unified git diff metadata.

    The parser extracts file status and hunk ranges only. It does not apply the
    patch, inspect the repository, or infer semantic impact.
    """
    if not isinstance(diff_text, str):
        raise TypeError("diff_text must be a string")
    files: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    old_path: str | None = None
    new_path: str | None = None
    old_mode_deleted = False
    new_mode_added = False
    rename_from: str | None = None
    rename_to: str | None = None
    binary_change = False
    truncated = False

    def finalize() -> None:
        nonlocal current, old_path, new_path, old_mode_deleted, new_mode_added, rename_from, rename_to, binary_change
        if current is None:
            return
        path = new_path or old_path or current.get("path")
        if rename_to:
            path = rename_to
        status = "modified"
        if old_mode_deleted or (old_path and not new_path):
            status = "deleted"
        if new_mode_added or (new_path and not old_path):
            status = "added"
        if rename_from or rename_to:
            status = "renamed"
        current["path"] = path
        current["old_path"] = rename_from or old_path
        current["new_path"] = rename_to or new_path
        current["change_status"] = status
        current["hunk_count"] = len(current["hunks"])
        current["binary"] = binary_change
        files.append(current)
        current = None
        old_path = None
        new_path = None
        old_mode_deleted = False
        new_mode_added = False
        rename_from = None
        rename_to = None
        binary_change = False

    for line in diff_text.splitlines():
        m = _DIFF_GIT_RE.match(line)
        if m:
            finalize()
            a_path = _safe_path(m.group(1))
            b_path = _safe_path(m.group(2))
            current = {"path": b_path or a_path, "old_path": a_path, "new_path": b_path, "hunks": []}
            old_path = a_path
            new_path = b_path
            continue
        if current is None:
            continue
        if line.startswith("Binary files ") or line.startswith("GIT binary patch"):
            binary_change = True
            continue
        if line.startswith("deleted file mode"):
            old_mode_deleted = True
            continue
        if line.startswith("new file mode"):
            new_mode_added = True
            continue
        if line.startswith("rename from "):
            rename_from = _safe_path(line[len("rename from "):])
            continue
        if line.startswith("rename to "):
            rename_to = _safe_path(line[len("rename to "):])
            continue
        if line.startswith("--- "):
            old_path = _safe_path(line[4:])
            continue
        if line.startswith("+++ "):
            new_path = _safe_path(line[4:])
            continue
        hm = _HUNK_RE.match(line)
        if hm:
            if len(current["hunks"]) >= MAX_HUNKS_PER_FILE:
                truncated = True
                continue
            old_start = int(hm.group(1))
            old_count = int(hm.group(2) or "1")
            new_start = int(hm.group(3))
            new_count = int(hm.group(4) or "1")
            old_range = _line_range(old_start, old_count, fallback_old=True)
            new_range = _line_range(new_start, new_count)
            effective = old_range if new_count == 0 else new_range
            current["hunks"].append({
                "old_range": old_range,
                "new_range": new_range,
                "changed_range": effective,
                "surrounding_range": _surrounding_range(effective, window=context_window_lines),
                "header": line,
            })
    finalize()

    safe_files = []
    for item in files:
        path = item.get("path")
        if isinstance(path, str) and _safe_path(path):
            safe_files.append(item)
    if len(safe_files) > max_files:
        truncated = True
        safe_files = safe_files[:max_files]
    counts: dict[str, int] = {}
    for item in safe_files:
        status = str(item.get("change_status"))
        counts[status] = counts.get(status, 0) + 1
    return {
        "file_count": len(safe_files),
        "change_status_counts": counts,
        "files": safe_files,
        "truncated": truncated,
        "context_window_lines": context_window_lines,
    }


def _load_diff(diff_path: str | Path) -> tuple[str, dict[str, Any]]:
    path = Path(diff_path).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"diff file not found: {path}")
    size = path.stat().st_size
    if size > MAX_DIFF_BYTES:
        raise ValueError(f"diff file exceeds max bytes: {size} > {MAX_DIFF_BYTES}")
    return path.read_text(encoding="utf-8"), {"path": str(path), "bytes": size}


def _path_query(path: str) -> str:
    p = Path(path)
    stem = p.stem.replace("_", " ").replace("-", " ")
    parts = [path, p.name, stem]
    return " ".join(part for part in parts if part)


def _implementation_hints_for_test_path(path: str) -> list[str]:
    p = Path(path)
    stem = p.stem.removeprefix("test_")
    suffix = p.suffix or ".py"
    hints: list[str] = []
    parts = list(p.parts)
    if "tests" in parts:
        idx = parts.index("tests")
        package_root = "/".join(parts[:idx])
        tail_parts = parts[idx + 1 : -1]
        if package_root:
            hints.append("/".join([package_root, *tail_parts, f"{stem}{suffix}"]))
            hints.append("/".join([package_root, "core", f"{stem}{suffix}"]))
        hints.append("/".join([*tail_parts, f"{stem}{suffix}"]))
    hints.append(f"{stem}{suffix}")
    return [hint for hint in _dedupe_ordered(hints) if hint and hint != path]


def _likely_refs(path: str, status: str) -> list[dict[str, Any]]:
    p = Path(path)
    name = p.name
    stem = p.stem
    refs: list[dict[str, Any]] = []
    if "/tests/" in f"/{path}" or name.startswith("test_"):
        for hint in _implementation_hints_for_test_path(path):
            refs.append({"kind": "implementation_candidate", "path_hint": hint, "reason": "changed_file_is_test"})
    elif p.suffix == ".py":
        refs.append({"kind": "test_candidate", "path_hint": f"tests/test_{stem}.py", "reason": "python_module_name_heuristic"})
        refs.append({"kind": "test_candidate", "path_hint": f"merger/repoground/tests/test_{stem}.py", "reason": "lenskit_test_layout_heuristic"})
    if path.endswith(".schema.json") or "/contracts/" in path:
        refs.append({"kind": "contract_validation_candidate", "path_hint": path, "reason": "contract_schema_path"})
    if path.startswith("docs/"):
        refs.append({"kind": "doc_context", "path_hint": path, "reason": "documentation_path"})
    if status == "deleted":
        refs.append({"kind": "deletion_followup", "path_hint": path, "reason": "deleted_file_needs_reference_check"})
    return refs


def _bundle_signals(bundle_manifest: str | Path | None) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any] | None]:
    if bundle_manifest is None:
        return {"status": "not_requested"}, [_gap("bundle_manifest", "not_requested", "no bundle manifest supplied", severity="info")], None
    try:
        status = snapshot_status(bundle_manifest)
    except ValueError as exc:
        return {"status": "invalid", "error": str(exc)}, [_gap("bundle_manifest", "invalid", str(exc), severity="error")], None
    availability = status.get("availability_model") if isinstance(status.get("availability_model"), dict) else {}
    freshness = availability.get("freshness") if isinstance(availability, dict) and isinstance(availability.get("freshness"), dict) else None
    graph = availability.get("graph_availability") if isinstance(availability, dict) and isinstance(availability.get("graph_availability"), dict) else None
    signal = {
        "status": status.get("status"),
        "bundle_run_id": status.get("bundle_run_id"),
        "availability_status": availability.get("status") if isinstance(availability, dict) else None,
        "freshness": freshness,
        "graph_availability": graph,
    }
    gaps: list[dict[str, Any]] = []
    if signal["status"] not in {"ok", "available", "pass"}:
        gaps.append(_gap("bundle_manifest", str(signal["status"]), "bundle manifest status is not fully available", severity="warn"))
    if signal["availability_status"] not in {None, "pass", "available", "ok"}:
        gaps.append(_gap(
            "freshness",
            str(signal["availability_status"]),
            "bundle availability/freshness is degraded for delta review context",
            severity="warn",
            freshness_status=freshness.get("status") if isinstance(freshness, dict) else None,
            freshness_reason=freshness.get("reason") if isinstance(freshness, dict) else None,
        ))
    graph_status = graph.get("status") if isinstance(graph, dict) else None
    if graph_status not in {None, "available", "profile_excluded"}:
        gaps.append(graph_gap_from_availability("graph_availability", graph))
    return signal, gaps, status


def _artifact_by_role(status: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    if not isinstance(status, Mapping):
        return result
    artifacts = status.get("artifacts")
    if not isinstance(artifacts, list):
        return result
    for artifact in artifacts:
        if isinstance(artifact, dict) and isinstance(artifact.get("role"), str):
            result.setdefault(artifact["role"], artifact)
    return result


def _relation_hints(status: Mapping[str, Any] | None, changed_paths: set[str], *, max_hits: int) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    if status is None:
        return [], {"status": "not_requested", "hit_count": 0}, []
    artifacts = _artifact_by_role(status)
    artifact = artifacts.get("relation_cards_jsonl")
    if not artifact or not artifact.get("absolute_path"):
        return [], {"status": "missing", "hit_count": 0}, [_gap("relation_cards_jsonl", "missing", "relation card artifact unavailable", severity="info")]
    path = Path(str(artifact["absolute_path"]))
    if not path.is_file():
        return [], {"status": "missing", "hit_count": 0}, [_gap("relation_cards_jsonl", "missing", "relation card file unavailable", severity="info")]
    size = path.stat().st_size
    if size > MAX_RELATION_CARDS_BYTES:
        return [], {"status": "limited", "hit_count": 0, "bytes": size}, [_gap(
            "relation_cards_jsonl",
            "limited",
            "relation card artifact exceeds bounded scan size",
            severity="warn",
            bytes=size,
            max_bytes=MAX_RELATION_CARDS_BYTES,
        )]
    hints: list[dict[str, Any]] = []
    errors = 0
    skipped_by_prefilter = 0
    scanned_rows = 0
    changed_needles = tuple(changed_paths)
    with path.open("r", encoding="utf-8") as handle:
        for row_number, line in enumerate(handle, start=1):
            scanned_rows = row_number
            if row_number > MAX_RELATION_CARD_SCAN_ROWS:
                break
            if not line.strip():
                continue
            if len(line.encode("utf-8")) > MAX_RELATION_CARD_LINE_BYTES:
                errors += 1
                continue
            if changed_needles and not any(needle in line for needle in changed_needles):
                skipped_by_prefilter += 1
                continue
            try:
                card = json.loads(line)
            except ValueError:
                errors += 1
                continue
            if not isinstance(card, dict):
                errors += 1
                continue
            source = card.get("source") if isinstance(card.get("source"), dict) else {}
            target = card.get("target") if isinstance(card.get("target"), dict) else {}
            source_path = source.get("path") if isinstance(source.get("path"), str) else None
            target_path = target.get("path") if isinstance(target.get("path"), str) else None
            if source_path not in changed_paths and target_path not in changed_paths:
                continue
            hints.append({
                "source": "relation_cards_jsonl",
                "row": row_number,
                "relation": card.get("relation"),
                "source_path": source_path,
                "target_path": target_path,
                "evidence": card.get("evidence"),
                "evidence_level": card.get("evidence_level"),
                "does_not_establish": card.get("does_not_establish"),
            })
            if len(hints) >= max_hits:
                break
    gaps: list[dict[str, Any]] = []
    if errors:
        gaps.append(_gap("relation_cards_jsonl", "invalid_rows", "some relation-card rows were invalid or too large", severity="warn", invalid_row_count=errors))
    if scanned_rows > MAX_RELATION_CARD_SCAN_ROWS:
        gaps.append(_gap("relation_cards_jsonl", "scan_limited", "relation-card scan row limit reached", severity="warn", max_rows=MAX_RELATION_CARD_SCAN_ROWS))
    if not hints:
        gaps.append(_gap("relation_cards_jsonl", "empty", "no relation cards matched changed paths", severity="info"))
    return hints, {
        "status": "warn" if errors or scanned_rows > MAX_RELATION_CARD_SCAN_ROWS else ("available" if hints else "empty"),
        "hit_count": len(hints),
        "invalid_row_count": errors,
        "scanned_rows": min(scanned_rows, MAX_RELATION_CARD_SCAN_ROWS),
        "skipped_by_prefilter": skipped_by_prefilter,
    }, gaps


def _symbol_hints(bundle_manifest: str | Path | None, changed_paths: list[str], *, max_hits: int) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    if bundle_manifest is None:
        return [], {"status": "not_requested", "hit_count": 0}, []
    hints: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    seen: set[tuple[str | None, str | None]] = set()
    for path in changed_paths:
        if len(hints) >= max_hits:
            break
        p = Path(path)
        queries = []
        for query in (_path_query(path), p.name, p.stem, _compact(p.stem)):
            if query and query not in queries:
                queries.append(query)
        result: dict[str, Any] | None = None
        hits: list[Any] = []
        for query in queries:
            result = search_symbol_index(bundle_manifest, query, k=min(10, max_hits))
            if result.get("status") != "available":
                continue
            hits = result.get("hits") if isinstance(result.get("hits"), list) else []
            if hits:
                break
        if result is None or result.get("status") != "available":
            gaps.append(_gap(
                "python_symbol_index_json",
                str(None if result is None else result.get("status")),
                "symbol index query unavailable for changed path",
                severity="warn" if result is not None and result.get("status") == "invalid" else "info",
                path=path,
                error_code=None if result is None else result.get("error_code"),
            ))
            continue
        for hit in hits:
            if not isinstance(hit, dict):
                continue
            key = (hit.get("path"), hit.get("qualified_name"))
            if key in seen:
                continue
            seen.add(key)
            hints.append({"source": "python_symbol_index_json", "changed_path": path, "symbol": hit})
            if len(hints) >= max_hits:
                break
    if not hints and not gaps:
        gaps.append(_gap("python_symbol_index_json", "empty", "no symbol hits for changed paths", severity="info"))
    status = "available" if hints else ("warn" if _has_warn_or_error(gaps) else "empty")
    return hints, {"status": status, "hit_count": len(hints)}, gaps


def _citation_hints(bundle_manifest: str | Path | None, changed_paths: list[str], *, max_hits: int) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    if bundle_manifest is None:
        return [], {"status": "not_requested", "hit_count": 0}, []
    hints: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    for path in changed_paths:
        if len(hints) >= max_hits:
            break
        result = query_existing_index(bundle_manifest, _path_query(path), k=min(5, max_hits), resolve_evidence=True, project_sources=True)
        if result.get("status") != "available":
            gaps.append(_gap(
                "resolved_evidence",
                str(result.get("status")),
                "resolved evidence query unavailable for changed path",
                severity="warn" if result.get("status") == "invalid" else "info",
                path=path,
                error_code=result.get("error_code"),
            ))
            continue
        projection = result.get("source_citation_projection") if isinstance(result.get("source_citation_projection"), dict) else {}
        for item in projection.get("items", []) if isinstance(projection.get("items"), list) else []:
            if not isinstance(item, dict):
                continue
            hints.append({
                "source": "resolved_evidence",
                "changed_path": path,
                "path": item.get("path"),
                "chunk_id": item.get("chunk_id"),
                "source_range": item.get("source_range"),
                "citation_id": item.get("citation_id"),
                "citation_status": item.get("citation_status"),
                "text_excerpt": item.get("text_excerpt"),
                "text_truncated": item.get("text_truncated"),
            })
            if len(hints) >= max_hits:
                break
    if not hints and not gaps:
        gaps.append(_gap("resolved_evidence", "empty", "no resolved evidence hits for changed paths", severity="info"))
    status = "available" if hints else ("warn" if _has_warn_or_error(gaps) else "empty")
    return hints, {"status": status, "hit_count": len(hints)}, gaps


def _select_context(candidates: list[dict[str, Any]], *, budget: int, bytes_per_token: float) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    selected: list[dict[str, Any]] = []
    omitted: list[dict[str, Any]] = []
    used = 0
    for candidate in sorted(candidates, key=lambda c: (c.get("priority", 999), c.get("id", ""))):
        estimate = _estimate_tokens(candidate, bytes_per_token)
        item = {**candidate, "estimated_tokens": estimate}
        if used + estimate <= budget:
            item["selection_status"] = "selected"
            item["budget_before_tokens"] = used
            used += estimate
            item["budget_after_tokens"] = used
            selected.append(item)
        else:
            item["selection_status"] = "omitted"
            item["omission_reason"] = "estimated_tokens_exceed_remaining_budget"
            item["budget_remaining_tokens"] = max(budget - used, 0)
            omitted.append(item)
    return selected, omitted, used


def compile_delta_context(
    *,
    diff_path: str | Path | None = None,
    diff_text: str | None = None,
    bundle_manifest: str | Path | None = None,
    task: str = "Review pull request delta",
    context_budget_tokens: int = DEFAULT_CONTEXT_BUDGET_TOKENS,
    signal_k: int = 10,
    context_window_lines: int = 20,
    bytes_per_token: float = DEFAULT_BYTES_PER_TOKEN,
) -> dict[str, Any]:
    if not isinstance(context_budget_tokens, int) or isinstance(context_budget_tokens, bool) or context_budget_tokens < 1:
        return _invalid_result(error="context_budget_tokens must be a positive integer", error_code="context_budget_invalid", diff_path=diff_path, task=task)
    if not isinstance(signal_k, int) or isinstance(signal_k, bool) or signal_k < 1 or signal_k > MAX_SIGNAL_HITS:
        return _invalid_result(error=f"signal_k must be between 1 and {MAX_SIGNAL_HITS}", error_code="signal_k_invalid", diff_path=diff_path, task=task)
    if not isinstance(context_window_lines, int) or isinstance(context_window_lines, bool) or context_window_lines < 0 or context_window_lines > 200:
        return _invalid_result(error="context_window_lines must be an integer between 0 and 200", error_code="context_window_invalid", diff_path=diff_path, task=task)
    if not isinstance(bytes_per_token, (int, float)) or isinstance(bytes_per_token, bool) or bytes_per_token <= 0:
        return _invalid_result(error="bytes_per_token must be a number greater than 0", error_code="bytes_per_token_invalid", diff_path=diff_path, task=task)
    bytes_per_token = float(bytes_per_token)

    diff_meta: dict[str, Any]
    try:
        if diff_text is None:
            if diff_path is None:
                return _invalid_result(error="either diff_path or diff_text is required", error_code="diff_missing", diff_path=diff_path, task=task)
            diff_text, diff_meta = _load_diff(diff_path)
        else:
            diff_meta = {"path": str(diff_path) if diff_path else None, "bytes": len(diff_text.encode("utf-8"))}
            if diff_meta["bytes"] > MAX_DIFF_BYTES:
                return _invalid_result(error="diff_text exceeds max bytes", error_code="diff_too_large", diff_path=diff_path, task=task)
        parsed = parse_unified_diff(diff_text, context_window_lines=context_window_lines)
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        return _invalid_result(error=str(exc), error_code="diff_invalid", diff_path=diff_path, task=task)

    gaps: list[dict[str, Any]] = []
    if parsed["file_count"] == 0:
        gaps.append(_gap("diff", "empty", "no changed files parsed from diff", severity="error"))

    bundle_signal, bundle_gaps, bundle_status = _bundle_signals(bundle_manifest)
    gaps.extend(bundle_gaps)
    changed_paths = _dedupe_ordered([str(item["path"]) for item in parsed["files"] if isinstance(item.get("path"), str)])
    changed_path_set = set(changed_paths)

    symbol_hints, symbol_signal, symbol_gaps = _symbol_hints(bundle_manifest, changed_paths, max_hits=signal_k)
    relation_hints, relation_signal, relation_gaps = _relation_hints(bundle_status, changed_path_set, max_hits=signal_k)
    citation_hints, citation_signal, citation_gaps = _citation_hints(bundle_manifest, changed_paths, max_hits=signal_k)
    gaps.extend(symbol_gaps)
    gaps.extend(relation_gaps)
    gaps.extend(citation_gaps)

    file_context: list[dict[str, Any]] = []
    for ordinal, item in enumerate(parsed["files"]):
        path = str(item["path"])
        status = str(item.get("change_status"))
        try:
            lens_card = produce_lens_card(path)
        except (TypeError, ValueError) as exc:
            lens_card = {"status": "unavailable", "reason": str(exc)}
        file_context.append({
            "id": f"changed-file:{ordinal}",
            "priority": 10 + ordinal,
            "source": "diff",
            "path": path,
            "old_path": item.get("old_path"),
            "new_path": item.get("new_path"),
            "change_status": status,
            "hunks": item.get("hunks", []),
            "hunk_count": item.get("hunk_count", 0),
            "lens_card": lens_card,
            "likely_refs": _likely_refs(path, status),
        })

    candidates: list[dict[str, Any]] = []
    candidates.extend(file_context)
    for ordinal, hint in enumerate(citation_hints):
        candidates.append({"id": f"citation-hint:{ordinal}", "priority": 100 + ordinal, **hint})
    for ordinal, hint in enumerate(symbol_hints):
        candidates.append({"id": f"symbol-hint:{ordinal}", "priority": 200 + ordinal, **hint})
    for ordinal, hint in enumerate(relation_hints):
        candidates.append({"id": f"relation-hint:{ordinal}", "priority": 250 + ordinal, **hint})

    selected, omitted, used = _select_context(candidates, budget=context_budget_tokens, bytes_per_token=bytes_per_token)

    input_validity = "invalid" if parsed["file_count"] == 0 else "valid"
    signal_quality = "degraded" if _has_warn_or_error(gaps) else "complete_or_not_requested"
    context_completeness = "budget_truncated" if omitted else "within_budget"
    status = "pass"
    if input_validity == "invalid":
        status = "invalid"
    elif signal_quality == "degraded" or context_completeness == "budget_truncated":
        status = "warn"

    return {
        "kind": KIND,
        "version": VERSION,
        "status": status,
        "task": task,
        "diff": {
            **diff_meta,
            "file_count": parsed["file_count"],
            "change_status_counts": parsed["change_status_counts"],
            "truncated": parsed["truncated"],
            "context_window_lines": parsed["context_window_lines"],
        },
        "bundle_manifest": str(Path(bundle_manifest).expanduser().resolve()) if bundle_manifest is not None else None,
        "budget": {
            "context_budget_tokens": context_budget_tokens,
            "estimated_used_tokens": used,
            "estimated_remaining_tokens": max(context_budget_tokens - used, 0),
            "bytes_per_token": bytes_per_token,
            "exact_tokenizer": False,
        },
        "input_validity": input_validity,
        "signal_quality": signal_quality,
        "context_completeness": context_completeness,
        "changed_files": parsed["files"],
        "review_context": selected,
        "omitted_context": omitted,
        "signals": {
            "bundle": bundle_signal,
            "python_symbol_index_json": symbol_signal,
            "relation_cards_jsonl": relation_signal,
            "resolved_evidence": citation_signal,
        },
        "gaps": gaps,
        "selection_trace": {
            "ordering": "diff_changed_ranges_then_citation_then_symbol_then_relation_hints",
            "priority_bands": [
                {"source": "diff", "priority": "10+"},
                {"source": "resolved_evidence", "priority": "100+"},
                {"source": "python_symbol_index_json", "priority": "200+"},
                {"source": "relation_cards_jsonl", "priority": "250+"},
            ],
            "omission_reasons": sorted({item.get("omission_reason") for item in omitted if item.get("omission_reason")}),
        },
        "review_boundary": {
            "context_only": True,
            "verdict": None,
            "approval": False,
            "rejection": False,
            "merge_authorization": False,
        },
        "mutation_boundary": _read_only_boundary(),
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }
