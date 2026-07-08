from __future__ import annotations

from typing import Any, Mapping

GRAPH_AVAILABILITY_STATUS_VALUES = (
    "available",
    "stale",
    "not_generated",
    "profile_excluded",
    "blocked_by_missing_source",
    "blocked_by_missing_provenance",
    "invalid",
)

GRAPH_DEGRADATION_VALUES = (
    "none",
    "missing",
    "missing_source",
    "missing_provenance",
    "stale",
    "profile_excluded",
    "invalid",
    "degraded",
)

GRAPH_DOES_NOT_ESTABLISH = (
    "graph_completeness",
    "dependency_completeness",
    "runtime_reachability",
    "runtime_causality",
    "runtime_behavior",
    "change_impact",
    "impact_completeness",
    "test_sufficiency",
    "review_impact",
    "retrieval_improvement",
    "default_promotion_readiness",
    "merge_readiness",
)

_LOAD_STATUS_MAP: dict[str, tuple[str, str]] = {
    "ok": ("none", "pass"),
    "stale_or_mismatched": ("stale", "warn"),
    "not_found": ("missing_source", "warn"),
    "unreadable": ("missing_source", "warn"),
    "invalid_path": ("invalid", "error"),
    "invalid_json": ("invalid", "error"),
    "invalid_schema": ("invalid", "error"),
    "validation_unavailable": ("degraded", "warn"),
}

_AVAILABILITY_STATUS_MAP: dict[str, tuple[str, str]] = {
    "available": ("none", "pass"),
    "stale": ("stale", "warn"),
    "not_generated": ("missing", "info"),
    "profile_excluded": ("profile_excluded", "info"),
    "blocked_by_missing_source": ("missing_source", "warn"),
    "blocked_by_missing_provenance": ("missing_provenance", "warn"),
    "invalid": ("invalid", "error"),
}


def _base_report(
    *,
    status: str,
    degradation: str,
    severity: str,
    retrieval_eligible: bool,
    reason: str | None = None,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "status": status,
        "degradation": degradation,
        "severity": severity,
        "retrieval_eligible": bool(retrieval_eligible),
        "graph_must_not_influence_retrieval": not bool(retrieval_eligible),
        "does_not_establish": list(GRAPH_DOES_NOT_ESTABLISH),
    }
    if reason:
        report["reason"] = reason
    return report


def graph_load_degradation(status: str | None, *, graph_used: bool) -> dict[str, Any]:
    """Describe whether a loaded Graph Index may influence retrieval.

    Only ``status=ok`` is retrieval-eligible. Every other loader state stays
    diagnostic and must not be read as runtime reachability, causality, impact
    completeness or default-promotion readiness.
    """

    raw_status = status if isinstance(status, str) and status else "unknown"
    degradation, severity = _LOAD_STATUS_MAP.get(raw_status, ("degraded", "warn"))
    retrieval_eligible = raw_status == "ok"
    report = _base_report(
        status=raw_status,
        degradation=degradation,
        severity=severity,
        retrieval_eligible=retrieval_eligible,
    )
    report["graph_used"] = bool(graph_used)
    report["graph_used_consistent_with_status"] = bool(graph_used) is retrieval_eligible
    return report


def graph_availability_degradation(
    status: str | None,
    *,
    load_status: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    """Describe Graph availability without upgrading it to a correctness claim."""

    raw_status = status if isinstance(status, str) and status else "unknown"
    degradation, severity = _AVAILABILITY_STATUS_MAP.get(raw_status, ("degraded", "warn"))
    retrieval_eligible = raw_status == "available" and (load_status in {None, "ok"})
    report = _base_report(
        status=raw_status,
        degradation=degradation,
        severity=severity,
        retrieval_eligible=retrieval_eligible,
        reason=reason,
    )
    if load_status is not None:
        report["load_status"] = load_status
    return report


def graph_degradation_report(
    status: str | None,
    *,
    retrieval_eligible: bool,
    graph_used: bool | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    """Backward-compatible generic Graph degradation report.

    Prefer ``graph_load_degradation`` for loader diagnostics and
    ``graph_availability_degradation`` for snapshot availability.
    """

    if graph_used is not None:
        return graph_load_degradation(status, graph_used=graph_used)
    raw_status = status if isinstance(status, str) and status else "unknown"
    if raw_status in _LOAD_STATUS_MAP and raw_status not in _AVAILABILITY_STATUS_MAP:
        degradation, severity = _LOAD_STATUS_MAP[raw_status]
        eligible = bool(retrieval_eligible) and degradation == "none"
        return _base_report(
            status=raw_status,
            degradation=degradation,
            severity=severity,
            retrieval_eligible=eligible,
            reason=reason,
        )
    report = graph_availability_degradation(raw_status, reason=reason)
    if retrieval_eligible and report["degradation"] == "none":
        report["retrieval_eligible"] = True
        report["graph_must_not_influence_retrieval"] = False
    return report


def graph_gap_from_availability(source: str, graph: Mapping[str, Any]) -> dict[str, Any]:
    """Project graph availability into a context-compiler gap item."""

    status = graph.get("status") if isinstance(graph.get("status"), str) else "unknown"
    graph_index = graph.get("graph_index") if isinstance(graph.get("graph_index"), Mapping) else {}
    load_status = graph_index.get("load_status") if isinstance(graph_index.get("load_status"), str) else None
    degradation = graph_availability_degradation(
        status,
        load_status=load_status,
        reason=graph.get("reason") if isinstance(graph.get("reason"), str) else None,
    )
    return {
        "source": source,
        "status": status,
        "reason": graph.get("reason") if isinstance(graph.get("reason"), str) else "graph availability is unknown",
        "severity": degradation["severity"],
        "degradation": degradation["degradation"],
        "graph_must_not_influence_retrieval": degradation["graph_must_not_influence_retrieval"],
        "retrieval_eligible": degradation["retrieval_eligible"],
        "does_not_establish": degradation["does_not_establish"],
    }
