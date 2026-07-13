"""Deterministic usefulness evaluator for agent impact context candidates."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from merger.lenskit.core.agent_impact_refinement import (
    is_repository_relative_path,
)

KIND = "repobrief.agent_impact_usefulness_eval"
VERSION = "1.0"

DOES_NOT_ESTABLISH = (
    "agent_quality_improvement",
    "answer_correctness",
    "repository_understanding",
    "complete_blast_radius",
    "test_sufficiency",
    "review_completeness",
    "merge_readiness",
    "general_retrieval_quality",
    "default_promotion",
)


@dataclass(frozen=True)
class _Case:
    case_id: str
    expected_paths: tuple[str, ...]


def _clean_paths(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    return list(
        dict.fromkeys(
            str(value).strip()
            for value in values
            if is_repository_relative_path(value)
        )
    )


def _section_paths(context: Mapping[str, Any]) -> list[str]:
    paths: list[str] = []
    for section in (
        "target_symbols",
        "related_tests",
        "supporting_context",
        "entrypoints",
    ):
        values = context.get(section)
        if not isinstance(values, list):
            continue
        paths.extend(
            str(item["path"]).strip()
            for item in values
            if isinstance(item, Mapping)
            and is_repository_relative_path(item.get("path"))
        )
    return paths


def _relation_paths(context: Mapping[str, Any]) -> list[str]:
    paths: list[str] = []
    relations = context.get("relations")
    if not isinstance(relations, list):
        return paths
    for relation in relations:
        if not isinstance(relation, Mapping):
            continue
        for side in ("target", "peer"):
            endpoint = relation.get(side)
            if isinstance(endpoint, Mapping) and is_repository_relative_path(
                endpoint.get("path")
            ):
                paths.append(str(endpoint["path"]).strip())
    return paths


def _paths_from_context(context: Mapping[str, Any]) -> list[str]:
    target = context.get("target")
    target_paths = (
        _clean_paths(target.get("paths"))
        if isinstance(target, Mapping)
        else []
    )
    paths = target_paths + _section_paths(context) + _relation_paths(context)
    return list(dict.fromkeys(paths))


def _recall(expected: tuple[str, ...], observed: list[str]) -> float:
    if not expected:
        return 1.0
    observed_set = set(observed)
    return sum(path in observed_set for path in expected) / len(expected)


def _number_threshold(
    goldset: Mapping[str, Any],
    *,
    field: str,
    default: float,
) -> float:
    value = goldset.get(field, default)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{field} must be a number")
    threshold = float(value)
    if not 0.0 <= threshold <= 1.0:
        raise ValueError(f"{field} must be between 0 and 1")
    return threshold


def _case(raw_case: Any) -> _Case:
    if not isinstance(raw_case, Mapping):
        raise TypeError("goldset cases must be mappings")
    case_id = raw_case.get("id")
    expected = raw_case.get("expected_paths")
    if not isinstance(case_id, str) or not case_id:
        raise ValueError("goldset case id must be a non-empty string")
    if not isinstance(expected, list) or not all(
        is_repository_relative_path(path) for path in expected
    ):
        raise ValueError(
            f"{case_id}.expected_paths must be repository-relative strings"
        )
    return _Case(
        case_id=case_id,
        expected_paths=tuple(str(path).strip() for path in expected),
    )


def _baseline_paths(observation: Mapping[str, Any]) -> list[str]:
    return _clean_paths(observation.get("baseline_paths"))


def _impact_context(observation: Mapping[str, Any]) -> Mapping[str, Any]:
    value = observation.get("impact_context")
    return value if isinstance(value, Mapping) else {}


def _missing_visible(context: Mapping[str, Any]) -> bool:
    gaps = context.get("gaps")
    if isinstance(gaps, list) and gaps:
        return True
    statuses = context.get("source_statuses")
    return bool(
        isinstance(statuses, list)
        and any(
            isinstance(item, Mapping)
            and item.get("status") not in {"available", None}
            for item in statuses
        )
    )


def _context_reduction(baseline_count: int, impact_count: int) -> float:
    if baseline_count == 0:
        return 0.0 if impact_count == 0 else -1.0
    return (baseline_count - impact_count) / baseline_count


def _evaluate_case(
    case: _Case,
    observation: Mapping[str, Any],
) -> dict[str, Any]:
    baseline_paths = _baseline_paths(observation)
    context = _impact_context(observation)
    impact_paths = _paths_from_context(context)
    baseline_recall = _recall(case.expected_paths, baseline_paths)
    impact_recall = _recall(case.expected_paths, impact_paths)
    baseline_count = len(baseline_paths)
    impact_count = len(impact_paths)
    return {
        "id": case.case_id,
        "expected_paths": list(case.expected_paths),
        "baseline_paths": baseline_paths,
        "impact_paths": impact_paths,
        "baseline_recall": baseline_recall,
        "impact_recall": impact_recall,
        "recall_advantage": impact_recall - baseline_recall,
        "baseline_context_path_count": baseline_count,
        "impact_context_path_count": impact_count,
        "context_path_reduction_ratio": _context_reduction(
            baseline_count,
            impact_count,
        ),
        "missing_evidence_visible": _missing_visible(context),
    }


def _raw_cases(goldset: Mapping[str, Any]) -> list[Any]:
    raw_cases = goldset.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ValueError("goldset.cases must be a non-empty list")
    return raw_cases


def _aggregate(
    cases: list[dict[str, Any]],
    *,
    minimum_recall_advantage: float,
    minimum_context_reduction: float,
) -> tuple[dict[str, Any], bool, str]:
    count = len(cases)
    baseline_recall = sum(item["baseline_recall"] for item in cases) / count
    impact_recall = sum(item["impact_recall"] for item in cases) / count
    advantage = impact_recall - baseline_recall
    no_case_regression = all(
        item["impact_recall"] >= item["baseline_recall"] for item in cases
    )
    missing_visible = sum(
        bool(item["missing_evidence_visible"]) for item in cases
    )
    baseline_paths = sum(
        int(item["baseline_context_path_count"]) for item in cases
    )
    impact_paths = sum(
        int(item["impact_context_path_count"]) for item in cases
    )
    context_reduction = _context_reduction(baseline_paths, impact_paths)
    recall_route = advantage >= minimum_recall_advantage
    compression_route = (
        impact_recall >= baseline_recall
        and context_reduction >= minimum_context_reduction
    )
    established = no_case_regression and (recall_route or compression_route)
    if established and recall_route:
        reason = "fixed_goldset_recall_threshold_met_without_case_regression"
    elif established:
        reason = (
            "fixed_goldset_compression_threshold_met_at_equal_or_better_recall"
        )
    else:
        reason = "fixed_goldset_threshold_or_non_regression_not_met"
    metrics = {
        "baseline_target_recall": baseline_recall,
        "impact_target_recall": impact_recall,
        "target_recall_advantage": advantage,
        "minimum_target_recall_advantage": minimum_recall_advantage,
        "baseline_mean_context_path_count": baseline_paths / count,
        "impact_mean_context_path_count": impact_paths / count,
        "context_path_reduction_ratio": context_reduction,
        "minimum_context_path_reduction_at_equal_or_better_recall": (
            minimum_context_reduction
        ),
        "no_case_regression": no_case_regression,
        "missing_evidence_visibility_rate": missing_visible / count,
    }
    return metrics, established, reason


def _decision(established: bool, reason: str) -> dict[str, Any]:
    return {
        "navigation_utility_established_for_goldset": established,
        "default_promoted": False,
        "reason": reason,
    }


def evaluate_agent_impact_goldset(
    goldset: Any,
    observations: Any,
) -> dict[str, Any]:
    """Compare baseline navigation with impact contexts for a fixed goldset."""

    if not isinstance(goldset, Mapping):
        raise TypeError("goldset must be a mapping")
    if not isinstance(observations, Mapping):
        raise TypeError("observations must be a mapping")
    minimum_recall_advantage = _number_threshold(
        goldset,
        field="minimum_target_recall_advantage",
        default=0.2,
    )
    minimum_context_reduction = _number_threshold(
        goldset,
        field="minimum_context_path_reduction_at_equal_or_better_recall",
        default=0.2,
    )
    case_specs = [_case(raw) for raw in _raw_cases(goldset)]
    cases = [
        _evaluate_case(
            case,
            _mapping_observation(observations, case.case_id),
        )
        for case in case_specs
    ]

    metrics, established, reason = _aggregate(
        cases,
        minimum_recall_advantage=minimum_recall_advantage,
        minimum_context_reduction=minimum_context_reduction,
    )
    return {
        "kind": KIND,
        "version": VERSION,
        "goldset_id": goldset.get("id"),
        "case_count": len(cases),
        "cases": cases,
        "metrics": metrics,
        "decision": _decision(established, reason),
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }


def _mapping_observation(
    observations: Mapping[str, Any],
    case_id: str,
) -> Mapping[str, Any]:
    value = observations.get(case_id)
    return value if isinstance(value, Mapping) else {}


__all__ = ["evaluate_agent_impact_goldset"]
