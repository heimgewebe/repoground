"""Deterministic usefulness evaluator for agent impact context candidates."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

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
            str(item["path"])
            for item in values
            if isinstance(item, Mapping) and isinstance(item.get("path"), str)
        )
    return paths


def _relation_paths(context: Mapping[str, Any]) -> list[str]:
    paths: list[str] = []
    for relation in context.get("relations", []):
        if not isinstance(relation, Mapping):
            continue
        for side in ("target", "peer"):
            endpoint = relation.get(side)
            if isinstance(endpoint, Mapping) and isinstance(
                endpoint.get("path"),
                str,
            ):
                paths.append(str(endpoint["path"]))
    return paths


def _paths_from_context(context: Mapping[str, Any]) -> list[str]:
    target = context.get("target")
    target_paths = (
        [
            str(item)
            for item in target.get("paths", [])
            if isinstance(item, str)
        ]
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


def _threshold(goldset: Mapping[str, Any]) -> float:
    value = goldset.get("minimum_target_recall_advantage", 0.2)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(
            "minimum_target_recall_advantage must be a number"
        )
    threshold = float(value)
    if not 0.0 <= threshold <= 1.0:
        raise ValueError(
            "minimum_target_recall_advantage must be between 0 and 1"
        )
    return threshold


def _case(raw_case: Any) -> _Case:
    if not isinstance(raw_case, Mapping):
        raise TypeError("goldset cases must be mappings")
    case_id = raw_case.get("id")
    expected = raw_case.get("expected_paths")
    if not isinstance(case_id, str) or not case_id:
        raise ValueError("goldset case id must be a non-empty string")
    if not isinstance(expected, list) or not all(
        isinstance(path, str) and path for path in expected
    ):
        raise ValueError(f"{case_id}.expected_paths must be strings")
    return _Case(case_id=case_id, expected_paths=tuple(expected))


def _baseline_paths(observation: Mapping[str, Any]) -> list[str]:
    values = observation.get("baseline_paths")
    if not isinstance(values, list):
        return []
    return [path for path in values if isinstance(path, str) and path]


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


def _evaluate_case(
    case: _Case,
    observation: Mapping[str, Any],
) -> dict[str, Any]:
    baseline_paths = _baseline_paths(observation)
    context = _impact_context(observation)
    impact_paths = _paths_from_context(context)
    baseline_recall = _recall(case.expected_paths, baseline_paths)
    impact_recall = _recall(case.expected_paths, impact_paths)
    return {
        "id": case.case_id,
        "expected_paths": list(case.expected_paths),
        "baseline_paths": baseline_paths,
        "impact_paths": impact_paths,
        "baseline_recall": baseline_recall,
        "impact_recall": impact_recall,
        "recall_advantage": impact_recall - baseline_recall,
        "baseline_context_path_count": len(baseline_paths),
        "impact_context_path_count": len(impact_paths),
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
    minimum_advantage: float,
) -> tuple[dict[str, Any], bool]:
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
    metrics = {
        "baseline_target_recall": baseline_recall,
        "impact_target_recall": impact_recall,
        "target_recall_advantage": advantage,
        "minimum_target_recall_advantage": minimum_advantage,
        "no_case_regression": no_case_regression,
        "missing_evidence_visibility_rate": missing_visible / count,
    }
    established = advantage >= minimum_advantage and no_case_regression
    return metrics, established


def _decision(established: bool) -> dict[str, Any]:
    return {
        "navigation_utility_established_for_goldset": established,
        "default_promoted": False,
        "reason": (
            "fixed_goldset_threshold_met_without_case_regression"
            if established
            else "fixed_goldset_threshold_or_non_regression_not_met"
        ),
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
    minimum_advantage = _threshold(goldset)
    case_specs = [_case(raw) for raw in _raw_cases(goldset)]
    cases = [
        _evaluate_case(
            case,
            _mapping_observation(observations, case.case_id),
        )
        for case in case_specs
    ]

    metrics, established = _aggregate(
        cases,
        minimum_advantage=minimum_advantage,
    )
    return {
        "kind": KIND,
        "version": VERSION,
        "goldset_id": goldset.get("id"),
        "case_count": len(cases),
        "cases": cases,
        "metrics": metrics,
        "decision": _decision(established),
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }


def _mapping_observation(
    observations: Mapping[str, Any],
    case_id: str,
) -> Mapping[str, Any]:
    value = observations.get(case_id)
    return value if isinstance(value, Mapping) else {}


__all__ = ["evaluate_agent_impact_goldset"]
