"""Conservative call-graph coverage and task-profile confidence boundaries.

This module scores only the static resolution surface already present in a
``python_call_graph_json`` document. The score is a coverage proxy, not a
statistical confidence estimate and not evidence of runtime completeness.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping
from typing import Any

RESOLUTION_STATUSES = ("resolved", "candidate", "ambiguous", "unresolved")
TASK_PROFILE_MIN_RESOLVED_RATIO = {
    "basic_repo_question": 0.50,
    "review": 0.80,
    "change_impact": 0.75,
    "find_relevant_tests": 0.70,
    "ground_claim": 0.90,
}
DOES_NOT_ESTABLISH = (
    "complete_call_graph",
    "caller_completeness",
    "callee_completeness",
    "unresolved_edges_are_irrelevant",
    "runtime_reachability",
    "runtime_behavior",
    "statistical_confidence",
    "test_sufficiency",
    "change_impact_outside_the_model",
    "review_completeness",
    "merge_readiness",
)


def _ratio(value: int, total: int) -> float | None:
    return round(value / total, 6) if total > 0 else None


def _counts(data: Mapping[str, Any]) -> dict[str, int] | None:
    raw = data.get("resolution_counts")
    if not isinstance(raw, Mapping):
        return None
    counts: dict[str, int] = {}
    for status in RESOLUTION_STATUSES:
        value = raw.get(status, 0)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return None
        counts[status] = value
    return counts


def _unresolved_causes(data: Mapping[str, Any]) -> dict[str, dict[str, int]]:
    causes: dict[str, Counter[str]] = defaultdict(Counter)
    calls = data.get("calls")
    if not isinstance(calls, list):
        return {}
    for call in calls:
        if not isinstance(call, Mapping):
            continue
        status = call.get("resolution_status")
        if status not in RESOLUTION_STATUSES or status == "resolved":
            continue
        reason = call.get("resolution_reason")
        label = reason if isinstance(reason, str) and reason else "unspecified"
        causes[str(status)][label] += 1
    return {
        status: dict(sorted(counter.items()))
        for status, counter in sorted(causes.items())
    }


def _profile_assessments(
    *,
    resolved_ratio: float | None,
    skipped_files_count: int,
) -> dict[str, dict[str, Any]]:
    assessments: dict[str, dict[str, Any]] = {}
    for profile, threshold in TASK_PROFILE_MIN_RESOLVED_RATIO.items():
        if resolved_ratio is None:
            status = "unknown"
            caveat = "No observed call edges are available for a coverage judgement."
        elif skipped_files_count > 0:
            status = "insufficient"
            caveat = (
                "Python files were skipped during parsing; repository-wide call "
                "completeness cannot be inferred."
            )
        elif resolved_ratio < threshold:
            status = "insufficient"
            caveat = (
                f"Observed resolved ratio {resolved_ratio:.6f} is below the "
                f"{profile} threshold {threshold:.2f}."
            )
        else:
            status = "sufficient"
            caveat = None
        assessments[profile] = {
            "status": status,
            "minimum_resolved_ratio": threshold,
            "observed_resolved_ratio": resolved_ratio,
            "completeness_caveat": caveat,
        }
    return assessments


def call_graph_coverage_confidence(data: Mapping[str, Any]) -> dict[str, Any]:
    """Project ratios, causes and explicit task-profile confidence boundaries."""
    counts = _counts(data)
    skipped = data.get("skipped_files_count", 0)
    skipped_files_count = (
        skipped
        if isinstance(skipped, int) and not isinstance(skipped, bool) and skipped >= 0
        else 0
    )
    if counts is None:
        return {
            "scope": "observed_call_edges",
            "model_scope": "observed_static_python_call_edges",
            "completeness": "unknown",
            "reason": "call_graph_resolution_counts_unavailable",
            "resolved_call_edges": None,
            "total_call_edges": None,
            "resolved_ratio": None,
            "status_ratios": {status: None for status in RESOLUTION_STATUSES},
            "unresolved_by_status": {},
            "unresolved_by_reason": {},
            "skipped_files_count": skipped_files_count,
            "confidence_model": "observed_resolution_coverage_proxy",
            "task_profile_confidence": _profile_assessments(
                resolved_ratio=None,
                skipped_files_count=skipped_files_count,
            ),
            "does_not_establish": list(DOES_NOT_ESTABLISH),
        }

    total = sum(counts.values())
    resolved = counts["resolved"]
    resolved_ratio = _ratio(resolved, total)
    unresolved_by_status = {
        status: value
        for status, value in counts.items()
        if status != "resolved" and value
    }
    if total <= 0:
        completeness = "unknown"
    elif unresolved_by_status or skipped_files_count:
        completeness = "partial"
    else:
        completeness = "complete"
    return {
        "scope": "observed_call_edges",
        "model_scope": "observed_static_python_call_edges",
        "completeness": completeness,
        "reason": None,
        "resolved_call_edges": resolved,
        "total_call_edges": total,
        "resolved_ratio": resolved_ratio,
        "status_ratios": {
            status: _ratio(value, total) for status, value in counts.items()
        },
        "unresolved_by_status": unresolved_by_status,
        "unresolved_by_reason": _unresolved_causes(data),
        "skipped_files_count": skipped_files_count,
        "confidence_model": "observed_resolution_coverage_proxy",
        "task_profile_confidence": _profile_assessments(
            resolved_ratio=resolved_ratio,
            skipped_files_count=skipped_files_count,
        ),
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }


__all__ = [
    "DOES_NOT_ESTABLISH",
    "RESOLUTION_STATUSES",
    "TASK_PROFILE_MIN_RESOLVED_RATIO",
    "call_graph_coverage_confidence",
]
