"""Refine agent-impact output with already resolved read-only query evidence.

The refinement layer never promotes retrieval hits to graph edges, runtime
relationships, test coverage, or review authority. It only adds explicitly
labelled navigation candidates to an already built impact context.
"""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from pathlib import PurePosixPath
from typing import Any

from merger.repoground.architecture.path_classification import is_test_path as _is_test_path

_EVIDENCE_RANK = {
    "graph_edge": 0,
    "symbol_index_path_match": 1,
    "changed_test_path": 2,
    "resolved_query": 3,
    "heuristic": 4,
}


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _items(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def is_repository_relative_path(value: Any) -> bool:
    """Return whether *value* is a canonical non-empty repository path."""

    if not isinstance(value, str):
        return False
    text = value.strip()
    if (
        not text
        or text.startswith("/")
        or "\\" in text
        or "//" in text
        or text.endswith("/")
    ):
        return False
    raw_parts = text.split("/")
    if any(part in {"", ".", ".."} for part in raw_parts):
        return False
    path = PurePosixPath(text)
    return bool(path.parts)


def _query_items(query_context: Any) -> list[dict[str, Any]]:
    root = _mapping(query_context)
    query = _mapping(root.get("query"))
    projection = _mapping(query.get("source_citation_projection"))
    if not projection:
        projection = _mapping(root.get("source_citation_projection"))
    return [
        dict(item)
        for item in _items(projection.get("items"))
        if isinstance(item, Mapping)
    ]


def resolved_query_test_candidates(query_context: Any) -> list[dict[str, Any]]:
    """Extract test-like paths from the resolved source projection."""

    candidates: list[dict[str, Any]] = []
    for item in _query_items(query_context):
        path = item.get("path")
        if not is_repository_relative_path(path):
            continue
        clean_path = str(path).strip()
        if not _is_test_path(clean_path):
            continue
        candidates.append(
            {
                "path": clean_path,
                "evidence_type": "resolved_query",
                "reason": "test_like_path_from_resolved_query_projection",
                "citation_id": item.get("citation_id"),
                "source_range": item.get("source_range"),
                "range_status": item.get("range_status"),
                "authority": "resolved_navigation_evidence",
                "canonicality": "derived",
            }
        )
    candidates.sort(
        key=lambda item: (
            str(item.get("path", "")),
            str(item.get("citation_id", "")),
            str(item.get("source_range", "")),
        )
    )
    unique: dict[tuple[str, str], dict[str, Any]] = {}
    for item in candidates:
        key = (str(item["path"]), str(item.get("citation_id") or ""))
        unique.setdefault(key, item)
    return list(unique.values())


def _valid_test_candidates(current: Any) -> list[dict[str, Any]]:
    return [
        dict(item)
        for item in _items(current)
        if isinstance(item, Mapping)
        and is_repository_relative_path(item.get("path"))
        and isinstance(item.get("evidence_type"), str)
    ]


def _suppress_heuristics(
    candidates: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    retained = [
        item
        for item in candidates
        if item.get("evidence_type") != "heuristic"
    ]
    return retained, len(candidates) - len(retained)


def _ordered_related_tests(
    current: Any,
    resolved: list[dict[str, Any]],
    *,
    max_items: int,
) -> tuple[list[dict[str, Any]], bool, int]:
    candidates, suppressed = _suppress_heuristics(_valid_test_candidates(current))
    candidates.extend(resolved)
    unique: dict[tuple[str, str], dict[str, Any]] = {}
    for item in candidates:
        key = (str(item["path"]), str(item["evidence_type"]))
        unique.setdefault(key, item)
    ordered = sorted(
        unique.values(),
        key=lambda item: (
            _EVIDENCE_RANK.get(str(item.get("evidence_type")), 99),
            str(item.get("path", "")),
        ),
    )
    return ordered[:max_items], len(ordered) > max_items, suppressed


def _read_priority(reason: Any) -> int:
    text = str(reason or "")
    if text == "target_symbol":
        return 0
    if text == "target_path":
        return 1
    if text.endswith("_graph_relation"):
        return 2
    if text == "related_test:graph_edge":
        return 3
    if text == "related_test:symbol_index_path_match":
        return 4
    if text == "related_test:changed_test_path":
        return 5
    if text == "related_test:resolved_query":
        return 6
    if text == "related_test:heuristic":
        return 7
    if text.startswith("supporting_"):
        return 8
    return 9


def _valid_first_reads(
    edit_context: Mapping[str, Any],
) -> list[dict[str, Any]]:
    return [
        dict(item)
        for item in _items(edit_context.get("recommended_first_reads"))
        if isinstance(item, Mapping)
        and is_repository_relative_path(item.get("path"))
        and item.get("reason") != "related_test:heuristic"
    ]


def _refine_first_reads(
    edit_context: Any,
    resolved: list[dict[str, Any]],
    *,
    max_items: int,
) -> dict[str, Any] | None:
    if not isinstance(edit_context, Mapping):
        return None
    refined = dict(edit_context)
    reads = _valid_first_reads(edit_context)
    reads.extend(
        {
            "path": item["path"],
            "range_ref": None,
            "qualified_name": None,
            "reason": "related_test:resolved_query",
        }
        for item in resolved
    )
    unique: dict[tuple[str, Any], dict[str, Any]] = {}
    for item in reads:
        unique.setdefault((str(item["path"]), item.get("range_ref")), item)
    ordered = sorted(
        unique.values(),
        key=lambda item: (
            _read_priority(item.get("reason")),
            str(item.get("path", "")),
            str(item.get("range_ref", "")),
        ),
    )
    refined["recommended_first_reads"] = ordered[:max_items]
    return refined


def refine_agent_impact_context(
    result: Any,
    query_context: Any,
    *,
    max_items: int,
) -> dict[str, Any]:
    """Add resolved-query test candidates to an impact context."""

    if not isinstance(result, Mapping):
        raise TypeError("result must be a mapping")
    refined = deepcopy(dict(result))
    if refined.get("status") in {"invalid", "blocked"}:
        return refined

    resolved = resolved_query_test_candidates(query_context)
    related, truncated, suppressed = _ordered_related_tests(
        refined.get("related_tests"),
        resolved,
        max_items=max_items,
    )
    refined["related_tests"] = related
    truncation = dict(_mapping(refined.get("truncation")))
    truncation["related_tests"] = bool(
        truncation.get("related_tests") or truncated
    )
    refined["truncation"] = truncation

    edit_context = _refine_first_reads(
        refined.get("edit_context"),
        resolved,
        max_items=max_items,
    )
    if edit_context is not None:
        edit_context["related_test_count"] = len(related)
        refined["edit_context"] = edit_context

    composition = dict(_mapping(refined.get("composition")))
    composition.update(
        {
            "resolved_query_test_candidates_added": len(resolved),
            "heuristic_test_candidates_suppressed": suppressed,
            "heuristics_suppressed_only_with_resolved_query_tests": False,
            "heuristic_test_candidates_always_suppressed": True,
            "resolved_query_tests_are_graph_edges": False,
            "resolved_query_tests_establish_coverage": False,
        }
    )
    refined["composition"] = composition
    return refined


__all__ = [
    "is_repository_relative_path",
    "refine_agent_impact_context",
    "resolved_query_test_candidates",
]
