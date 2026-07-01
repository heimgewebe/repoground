"""Diagnostic promotion gate for retrieval-v2 style surfaces.

This module compares existing measurement reports. It does not execute retrieval,
change ranking, or promote any runtime path.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DOES_NOT_ESTABLISH = [
    "retrieval_correctness",
    "review_completeness",
    "answer_correctness",
    "default_promotion_readiness_beyond_this_goldset",
    "runtime_behavior",
]


def _metric(report: dict[str, Any], key: str, default: float = 0.0) -> float:
    value = (report.get("metrics") or {}).get(key, default)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return default


def _expected_target_recall(report: dict[str, Any]) -> float:
    metrics = report.get("metrics") or {}
    hits = metrics.get("expected_target_hits", 0)
    total = metrics.get("expected_target_total", 0)
    if not isinstance(hits, (int, float)) or isinstance(hits, bool):
        hits = 0
    if not isinstance(total, (int, float)) or isinstance(total, bool) or total <= 0:
        return 0.0
    return round(float(hits) / float(total), 6)


def _category_stats(report: dict[str, Any], category: str, recall_key: str) -> tuple[float, float]:
    stats = (report.get("categories") or {}).get(category) or {}
    recall = stats.get(recall_key, 0.0)
    mrr = stats.get("MRR", 0.0)
    if not isinstance(recall, (int, float)) or isinstance(recall, bool):
        recall = 0.0
    if not isinstance(mrr, (int, float)) or isinstance(mrr, bool):
        mrr = 0.0
    return float(recall), float(mrr)


def _miss_count(report: dict[str, Any]) -> int:
    diagnostics = report.get("miss_diagnostics") or []
    return len(diagnostics) if isinstance(diagnostics, list) else 0


def _fallback_count(report: dict[str, Any]) -> int:
    conditions = report.get("measurement_conditions") or {}
    review = conditions.get("review_intent") or {}
    for key in ("fallback_count", "legacy_fallback_count", "fallbacks"):
        value = review.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return 0


def _graph_is_fresh(graph_report: dict[str, Any] | None) -> bool:
    if graph_report is None:
        return True
    status = graph_report.get("graph_status") or graph_report.get("status")
    if status in {"stale", "stale_or_mismatched", "mismatched"}:
        return False
    if graph_report.get("stale") is True:
        return False
    return True


def _range_health_ok(range_report: dict[str, Any] | None) -> bool:
    if range_report is None:
        return True
    status = range_report.get("status") or range_report.get("range_citation_health")
    if status in {"fail", "error", "unhealthy"}:
        return False
    malformed = ((range_report.get("counts") or {}).get("malformed_hits"))
    if isinstance(malformed, int) and malformed > 0:
        return False
    return True


def build_promotion_gate_report(
    legacy_report: dict[str, Any],
    review_report: dict[str, Any],
    *,
    graph_report: dict[str, Any] | None = None,
    range_report: dict[str, Any] | None = None,
    recall_key: str = "recall@10",
) -> dict[str, Any]:
    """Compare diagnostic baselines and return a conservative gate decision."""
    gates: list[dict[str, Any]] = []

    legacy_recall = _metric(legacy_report, recall_key)
    review_recall = _metric(review_report, recall_key)
    gates.append({
        "name": "global_recall_non_regression",
        "passed": review_recall >= legacy_recall,
        "legacy": legacy_recall,
        "candidate": review_recall,
    })

    legacy_mrr = _metric(legacy_report, "MRR")
    review_mrr = _metric(review_report, "MRR")
    gates.append({
        "name": "global_mrr_non_regression",
        "passed": review_mrr >= legacy_mrr,
        "legacy": legacy_mrr,
        "candidate": review_mrr,
    })

    legacy_target = _expected_target_recall(legacy_report)
    review_target = _expected_target_recall(review_report)
    gates.append({
        "name": "expected_target_recall_non_regression",
        "passed": review_target >= legacy_target,
        "legacy": legacy_target,
        "candidate": review_target,
    })

    category_reports = []
    categories = sorted(set((legacy_report.get("categories") or {})) | set((review_report.get("categories") or {})))
    category_passed = True
    for category in categories:
        legacy_cat_recall, legacy_cat_mrr = _category_stats(legacy_report, category, recall_key)
        review_cat_recall, review_cat_mrr = _category_stats(review_report, category, recall_key)
        passed = review_cat_recall >= legacy_cat_recall and review_cat_mrr >= legacy_cat_mrr
        category_passed = category_passed and passed
        category_reports.append({
            "category": category,
            "passed": passed,
            "legacy": {recall_key: legacy_cat_recall, "MRR": legacy_cat_mrr},
            "candidate": {recall_key: review_cat_recall, "MRR": review_cat_mrr},
        })
    gates.append({
        "name": "per_category_non_regression",
        "passed": category_passed,
        "categories": category_reports,
    })

    gates.append({
        "name": "miss_count_non_regression",
        "passed": _miss_count(review_report) <= _miss_count(legacy_report),
        "legacy": _miss_count(legacy_report),
        "candidate": _miss_count(review_report),
    })
    gates.append({
        "name": "fallback_count_zero",
        "passed": _fallback_count(review_report) == 0,
        "candidate": _fallback_count(review_report),
    })
    gates.append({
        "name": "fresh_graph_if_supplied",
        "passed": _graph_is_fresh(graph_report),
        "graph_supplied": graph_report is not None,
    })
    gates.append({
        "name": "range_citation_health_ok_if_supplied",
        "passed": _range_health_ok(range_report),
        "range_report_supplied": range_report is not None,
    })

    passed = all(gate["passed"] for gate in gates)
    return {
        "kind": "lenskit.retrieval_promotion_gate",
        "version": "1.0",
        "status": "passed" if passed else "blocked",
        "promote_default": False,
        "gates": gates,
        "decision": {
            "default_promotion_allowed": False,
            "reason": "diagnostic gate only; promotion requires explicit later decision even when gates pass" if passed else "one or more diagnostic gates failed",
        },
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"expected JSON object: {path}")
    return data
