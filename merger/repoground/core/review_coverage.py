"""Proof-of-reading coverage for RepoGround delta reviews.

This module compares task/PR-relevant ranges from a delta-context report with
ranges cited in a review artifact. It measures citation coverage only. It does
not evaluate review correctness, quality, approval, risk or merge readiness.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping

KIND = "repobrief.review_coverage"
VERSION = "v1"
MAX_REVIEW_BYTES = 2_000_000
MAX_DELTA_CONTEXT_BYTES = 5_000_000
DEFAULT_MIN_RANGE_COVERAGE = 0.6

DOES_NOT_ESTABLISH = (
    "review_correctness",
    "review_completeness",
    "test_sufficiency",
    "security_correctness",
    "runtime_behavior",
    "regression_absence",
    "merge_readiness",
    "approval",
    "rejection",
    "risk_score",
    "all_relevant_context_used",
    "claims_true",
)

_LINE_CITATION_RE = re.compile(
    r"(?P<path>(?:(?:[A-Za-z0-9_.-]+/)+)?[A-Za-z0-9_.-]+)"
    r"(?:#L|:L|:|\s+lines?\s+)"
    r"(?P<start>\d+)"
    r"(?:\s*-\s*(?:L)?(?P<end>\d+))?"
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
            "bureau_registry",
        ],
        "read_paths_do_not_refresh": True,
    }


def _invalid_result(*, error: str, error_code: str) -> dict[str, Any]:
    return {
        "kind": KIND,
        "version": VERSION,
        "status": "invalid",
        "error": error,
        "error_code": error_code,
        "coverage": {},
        "uncovered_ranges": [],
        "cited_ranges": [],
        "citations": [],
        "thresholds": {},
        "bureau_evidence": _bureau_evidence_boundary(),
        "mutation_boundary": _read_only_boundary(),
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }


def _bureau_evidence_boundary() -> dict[str, Any]:
    return {
        "role": "evidence_signal",
        "consumer": "bureau",
        "advisory_by_default": True,
        "requires_external_policy_to_gate": True,
        "does_not_authorize_merge": True,
        "does_not_close_tasks_by_itself": True,
    }


def _safe_path(raw: Any) -> str | None:
    if not isinstance(raw, str):
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


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _normalize_range(
    *,
    path: Any,
    start_line: Any = None,
    end_line: Any = None,
    range_id: str,
    source: str,
    basis: str | None = None,
    range_kind: str = "line_range",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    safe_path = _safe_path(path)
    if safe_path is None:
        return None
    start = _as_int(start_line)
    end = _as_int(end_line)
    if start is None and end is None:
        return {
            "id": range_id,
            "source": source,
            "path": safe_path,
            "range_kind": "file",
            "start_line": None,
            "end_line": None,
            "basis": basis,
            "metadata": metadata or {},
        }
    if start is None:
        start = end
    if end is None:
        end = start
    if start is None or end is None or start < 0 or end < 0:
        return None
    if end < start:
        start, end = end, start
    return {
        "id": range_id,
        "source": source,
        "path": safe_path,
        "range_kind": range_kind,
        "start_line": start,
        "end_line": end,
        "basis": basis,
        "metadata": metadata or {},
    }


def _range_overlap(a: Mapping[str, Any], b: Mapping[str, Any]) -> bool:
    if a.get("path") != b.get("path"):
        return False
    if a.get("range_kind") == "file":
        return True
    if b.get("range_kind") == "file":
        return False
    a_start = _as_int(a.get("start_line"))
    a_end = _as_int(a.get("end_line"))
    b_start = _as_int(b.get("start_line"))
    b_end = _as_int(b.get("end_line"))
    if None in {a_start, a_end, b_start, b_end}:
        return False
    return not (a_end < b_start or b_end < a_start)


def _range_line_count(item: Mapping[str, Any]) -> int:
    if item.get("range_kind") == "file":
        return 0
    start = _as_int(item.get("start_line"))
    end = _as_int(item.get("end_line"))
    if start is None or end is None or end < start:
        return 0
    return end - start + 1


def _load_json_file(path: str | Path, *, max_bytes: int) -> tuple[dict[str, Any] | None, str | None]:
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        return None, f"file not found: {p}"
    size = p.stat().st_size
    if size > max_bytes:
        return None, f"file exceeds max bytes: {size} > {max_bytes}"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        return None, str(exc)
    if not isinstance(data, dict):
        return None, "json root must be an object"
    return data, None


def _load_review_payload(path: str | Path) -> tuple[str, Any, str | None]:
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        return "", None, f"file not found: {p}"
    size = p.stat().st_size
    if size > MAX_REVIEW_BYTES:
        return "", None, f"review file exceeds max bytes: {size} > {MAX_REVIEW_BYTES}"
    try:
        text = p.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return "", None, str(exc)
    parsed: Any = None
    try:
        parsed = json.loads(text)
    except ValueError:
        parsed = None
    return text, parsed, None


def _target_ranges_from_delta_context(delta_context: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ranges: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    files = delta_context.get("changed_files")
    if not isinstance(files, list):
        return [], [{"source": "delta_context", "status": "invalid", "severity": "error", "reason": "changed_files missing or not a list"}]
    for file_index, file_item in enumerate(files):
        if not isinstance(file_item, dict):
            gaps.append({"source": "delta_context", "status": "invalid_file", "severity": "warn", "index": file_index})
            continue
        path = file_item.get("path")
        hunks = file_item.get("hunks")
        if isinstance(hunks, list) and hunks:
            for hunk_index, hunk in enumerate(hunks):
                if not isinstance(hunk, dict):
                    continue
                changed = hunk.get("changed_range") if isinstance(hunk.get("changed_range"), dict) else {}
                item = _normalize_range(
                    path=path,
                    start_line=changed.get("start_line"),
                    end_line=changed.get("end_line"),
                    basis=changed.get("basis") if isinstance(changed.get("basis"), str) else None,
                    range_id=f"delta:{file_index}:{hunk_index}",
                    source="delta_context.changed_range",
                    metadata={
                        "change_status": file_item.get("change_status"),
                        "hunk_header": hunk.get("header"),
                        "binary": file_item.get("binary"),
                    },
                )
                if item is not None:
                    ranges.append(item)
        else:
            item = _normalize_range(
                path=path,
                range_id=f"delta:{file_index}:file",
                source="delta_context.file",
                range_kind="file",
                metadata={
                    "change_status": file_item.get("change_status"),
                    "binary": file_item.get("binary"),
                    "reason": "file-level delta without line hunks",
                },
            )
            if item is not None:
                ranges.append(item)
    if not ranges:
        gaps.append({"source": "delta_context", "status": "empty", "severity": "error", "reason": "no reviewable ranges found"})
    return ranges, gaps


def _range_from_dict(obj: Mapping[str, Any], *, source: str, range_id: str) -> dict[str, Any] | None:
    path = obj.get("path") or obj.get("file_path") or obj.get("source_path") or obj.get("changed_path")
    start = obj.get("start_line")
    end = obj.get("end_line")
    line_range = obj.get("line_range") or obj.get("range") or obj.get("source_range")
    if (start is None or end is None) and isinstance(line_range, dict):
        start = line_range.get("start_line") or line_range.get("start")
        end = line_range.get("end_line") or line_range.get("end")
    if (start is None or end is None) and isinstance(line_range, list) and len(line_range) >= 2:
        start = line_range[0]
        end = line_range[1]
    if (start is None or end is None) and isinstance(line_range, str):
        match = re.search(r"L?(\d+)\s*-\s*L?(\d+)", line_range)
        if match:
            start = match.group(1)
            end = match.group(2)
    return _normalize_range(path=path, start_line=start, end_line=end, range_id=range_id, source=source)


def _walk_json_citations(value: Any, *, citations: list[dict[str, Any]], seen: set[tuple[Any, ...]], prefix: str) -> None:
    if isinstance(value, Mapping):
        source_range = value.get("source_range") if isinstance(value.get("source_range"), Mapping) else None
        if source_range is not None:
            _walk_json_citations(source_range, citations=citations, seen=seen, prefix=f"{prefix}.source_range")
        item = _range_from_dict(value, source="review_json", range_id=f"review-json:{len(citations)}")
        if item is not None:
            key = (item.get("path"), item.get("start_line"), item.get("end_line"), item.get("range_kind"))
            if key not in seen:
                seen.add(key)
                citations.append(item)
        for child in value.values():
            _walk_json_citations(child, citations=citations, seen=seen, prefix=prefix)
    elif isinstance(value, list):
        for child in value:
            _walk_json_citations(child, citations=citations, seen=seen, prefix=prefix)


def _text_line_citations(text: str) -> list[dict[str, Any]]:
    citations: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for match in _LINE_CITATION_RE.finditer(text):
        item = _normalize_range(
            path=match.group("path"),
            start_line=match.group("start"),
            end_line=match.group("end") or match.group("start"),
            range_id=f"review-text:{len(citations)}",
            source="review_text",
        )
        if item is None:
            continue
        key = (item.get("path"), item.get("start_line"), item.get("end_line"))
        if key in seen:
            continue
        seen.add(key)
        citations.append(item)
    return citations


def _file_mentions(text: str, target_paths: Iterable[str]) -> list[dict[str, Any]]:
    mentions: list[dict[str, Any]] = []
    for path in sorted(set(target_paths)):
        if path and path in text:
            item = _normalize_range(path=path, range_id=f"review-file:{len(mentions)}", source="review_text_file_mention")
            if item is not None:
                mentions.append(item)
    return mentions


def extract_review_citations(review_text: str, review_json: Any, *, target_paths: Iterable[str] = ()) -> dict[str, Any]:
    citations = _text_line_citations(review_text)
    seen = {(item.get("path"), item.get("start_line"), item.get("end_line"), item.get("range_kind")) for item in citations}
    if review_json is not None:
        _walk_json_citations(review_json, citations=citations, seen=seen, prefix="review")
    mentions = _file_mentions(review_text, target_paths)
    return {
        "line_citations": citations,
        "file_mentions": mentions,
        "citation_count": len(citations),
        "file_mention_count": len(mentions),
    }


def _cited_line_intersection_count(target: Mapping[str, Any], citations: list[dict[str, Any]]) -> int:
    if target.get("range_kind") == "file":
        return 0
    target_start = _as_int(target.get("start_line"))
    target_end = _as_int(target.get("end_line"))
    if target_start is None or target_end is None:
        return 0
    intervals: list[tuple[int, int]] = []
    for citation in citations:
        if citation.get("path") != target.get("path") or citation.get("range_kind") == "file":
            continue
        citation_start = _as_int(citation.get("start_line"))
        citation_end = _as_int(citation.get("end_line"))
        if citation_start is None or citation_end is None:
            continue
        start = max(target_start, citation_start)
        end = min(target_end, citation_end)
        if end >= start:
            intervals.append((start, end))
    if not intervals:
        return 0
    intervals.sort()
    merged: list[tuple[int, int]] = []
    for start, end in intervals:
        if not merged or start > merged[-1][1] + 1:
            merged.append((start, end))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    return sum(end - start + 1 for start, end in merged)


def _coverage_for_ranges(target_ranges: list[dict[str, Any]], citations: list[dict[str, Any]], file_mentions: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    covered: list[dict[str, Any]] = []
    uncovered: list[dict[str, Any]] = []
    cited_lines = 0
    total_lines = 0
    for target in target_ranges:
        matches = [citation for citation in citations if _range_overlap(target, citation)]
        mention_matches = [mention for mention in file_mentions if mention.get("path") == target.get("path")]
        line_count = _range_line_count(target)
        cited_line_count = _cited_line_intersection_count(target, matches)
        total_lines += line_count
        if matches or (target.get("range_kind") == "file" and mention_matches):
            item = {
                **target,
                "coverage_status": "covered",
                "matching_citations": matches,
                "matching_file_mentions": mention_matches,
                "cited_line_count": cited_line_count,
            }
            covered.append(item)
            cited_lines += cited_line_count
        else:
            uncovered.append({
                **target,
                "coverage_status": "uncovered",
                "matching_citations": [],
                "matching_file_mentions": mention_matches,
                "cited_line_count": 0,
            })
    total = len(target_ranges)
    cited = len(covered)
    return covered, uncovered, {
        "total_relevant_ranges": total,
        "cited_relevant_ranges": cited,
        "uncovered_relevant_ranges": len(uncovered),
        "range_coverage_ratio": (cited / total) if total else 0.0,
        "total_relevant_lines": total_lines,
        "cited_relevant_lines": cited_lines,
        "line_coverage_ratio": (cited_lines / total_lines) if total_lines else None,
    }


def compile_review_coverage(
    *,
    delta_context_path: str | Path | None = None,
    delta_context: Mapping[str, Any] | None = None,
    review_path: str | Path | None = None,
    review_text: str | None = None,
    review_json: Any = None,
    min_range_coverage: float = DEFAULT_MIN_RANGE_COVERAGE,
    policy_name: str = "advisory",
) -> dict[str, Any]:
    if not isinstance(min_range_coverage, (int, float)) or isinstance(min_range_coverage, bool) or not 0 <= float(min_range_coverage) <= 1:
        return _invalid_result(error="min_range_coverage must be between 0 and 1", error_code="threshold_invalid")
    if delta_context is None:
        if delta_context_path is None:
            return _invalid_result(error="delta_context_path or delta_context is required", error_code="delta_context_missing")
        delta_context_obj, error = _load_json_file(delta_context_path, max_bytes=MAX_DELTA_CONTEXT_BYTES)
        if error:
            return _invalid_result(error=error, error_code="delta_context_invalid")
        delta_context = delta_context_obj
    if not isinstance(delta_context, Mapping):
        return _invalid_result(error="delta_context must be an object", error_code="delta_context_invalid")

    if review_text is None:
        if review_path is None:
            return _invalid_result(error="review_path or review_text is required", error_code="review_missing")
        review_text, parsed_review_json, error = _load_review_payload(review_path)
        if error:
            return _invalid_result(error=error, error_code="review_invalid")
        if review_json is None:
            review_json = parsed_review_json
    else:
        if review_json is None:
            try:
                review_json = json.loads(review_text)
            except ValueError:
                review_json = None

    target_ranges, range_gaps = _target_ranges_from_delta_context(delta_context)
    target_paths = [item["path"] for item in target_ranges if isinstance(item.get("path"), str)]
    citation_payload = extract_review_citations(review_text or "", review_json, target_paths=target_paths)
    covered, uncovered, metrics = _coverage_for_ranges(
        target_ranges,
        citation_payload["line_citations"],
        citation_payload["file_mentions"],
    )
    threshold_met = metrics["range_coverage_ratio"] >= float(min_range_coverage)
    gaps = list(range_gaps)
    if not citation_payload["line_citations"] and not citation_payload["file_mentions"]:
        gaps.append({"source": "review", "status": "no_citations", "severity": "warn", "reason": "review contains no parseable citations or file mentions"})
    if uncovered:
        gaps.append({"source": "coverage", "status": "uncovered_ranges", "severity": "info", "reason": "some relevant ranges were not cited", "count": len(uncovered)})
    if not threshold_met:
        gaps.append({"source": "threshold", "status": "below_threshold", "severity": "warn", "reason": "range coverage is below advisory threshold"})

    has_warning = any(gap.get("severity") in {"warn", "error"} for gap in gaps)
    status = "invalid" if range_gaps and any(g.get("severity") == "error" for g in range_gaps) else ("warn" if has_warning or not threshold_met else "pass")
    return {
        "kind": KIND,
        "version": VERSION,
        "status": status,
        "policy_name": policy_name,
        "delta_context": {
            "kind": delta_context.get("kind"),
            "version": delta_context.get("version"),
            "status": delta_context.get("status"),
            "diff": delta_context.get("diff"),
        },
        "coverage": metrics,
        "thresholds": {
            "min_range_coverage": float(min_range_coverage),
            "range_threshold_met": threshold_met,
            "advisory": True,
            "external_policy_required_to_gate": True,
        },
        "relevant_ranges": target_ranges,
        "cited_ranges": covered,
        "uncovered_ranges": uncovered,
        "citations": citation_payload,
        "gaps": gaps,
        "bureau_evidence": _bureau_evidence_boundary(),
        "mutation_boundary": _read_only_boundary(),
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }
