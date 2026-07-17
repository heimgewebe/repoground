"""Integrity wrapper for complete and taskset-bound benchmark evaluation."""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from merger.repoground.core.agent_benchmark_common import (
    AgentBenchmarkError,
    CONDITIONS,
    DOES_NOT_ESTABLISH,
    EVALUATION_KIND,
    VERSION,
    list_value,
    mapping_value,
    require_valid_taskset,
    sha256_json,
)
from merger.repoground.core.agent_benchmark_evaluation import (
    _class_results,
    _decision,
    evaluate_paired_runs as _evaluate_existing_pairs,
)
from merger.repoground.core.agent_benchmark_requests import (
    expected_pair_keys,
    pair_request_errors,
    validate_request,
)


def _invalid_score(reason: str) -> dict[str, Any]:
    return {
        "valid": False,
        "success": False,
        "outcome_match": False,
        "target_hit_rate": 0.0,
        "false_hit_count": 0,
        "citation_match_rate": 0.0,
        "false_confidence": False,
        "duration_ms": 0,
        "tool_call_count": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "tool_bytes": 0,
        "invalid_reasons": [reason],
    }


def _missing_pair(
    case_id: str, repetition: int, category: str
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "category": category,
        "repetition": repetition,
        "pair_valid": False,
        "baseline": _invalid_score("missing baseline request"),
        "treatment": _invalid_score("missing treatment request"),
    }


def _request_groups(
    requests: Sequence[Mapping[str, Any]],
) -> dict[tuple[str, int], list[Mapping[str, Any]]]:
    grouped: dict[tuple[str, int], list[Mapping[str, Any]]] = defaultdict(list)
    for request in requests:
        case_id = str(request.get("case_id", ""))
        repetition = request.get("repetition")
        if isinstance(repetition, int):
            grouped[(case_id, repetition)].append(request)
    return grouped


def _append_errors(score: dict[str, Any], errors: Sequence[str]) -> None:
    if not errors:
        return
    current = list(score.get("invalid_reasons") or [])
    current.extend(error for error in errors if error not in current)
    score["invalid_reasons"] = current
    score["valid"] = False
    score["success"] = False


def _condition_request_errors(
    taskset: Mapping[str, Any],
    requests: Sequence[Mapping[str, Any]],
) -> dict[str, list[str]]:
    errors: dict[str, list[str]] = defaultdict(list)
    for request in requests:
        condition = str(request.get("condition", ""))
        errors[condition].extend(validate_request(taskset, request))
    return errors


def _harden_pair(
    taskset: Mapping[str, Any],
    result: dict[str, Any],
    requests: Sequence[Mapping[str, Any]],
) -> None:
    condition_errors = _condition_request_errors(taskset, requests)
    for condition in CONDITIONS:
        score = result.get(condition)
        if isinstance(score, dict):
            _append_errors(score, condition_errors.get(condition, []))
    pair_errors = pair_request_errors(requests)
    if pair_errors:
        for condition in CONDITIONS:
            score = result.get(condition)
            if isinstance(score, dict):
                _append_errors(score, pair_errors)
    result["pair_valid"] = bool(
        not pair_errors
        and all(
            mapping_value(result.get(condition)).get("valid") is True
            for condition in CONDITIONS
        )
    )


def _complete_case_results(
    taskset: Mapping[str, Any],
    existing: Sequence[Mapping[str, Any]],
    requests: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    cases = {
        str(case.get("id")): case
        for case in list_value(taskset.get("cases"))
        if isinstance(case, Mapping)
    }
    existing_by_key = {
        (str(item.get("case_id")), int(item.get("repetition") or 0)): dict(item)
        for item in existing
    }
    grouped_requests = _request_groups(requests)
    completed: list[dict[str, Any]] = []
    for case_id, repetition in expected_pair_keys(taskset):
        key = (case_id, repetition)
        result = existing_by_key.get(key)
        if result is None:
            result = _missing_pair(
                case_id,
                repetition,
                str(mapping_value(cases.get(case_id)).get("category", "navigation")),
            )
        _harden_pair(taskset, result, grouped_requests.get(key, []))
        completed.append(result)
    return completed


def evaluate_paired_runs(
    taskset: Mapping[str, Any],
    requests: Sequence[Mapping[str, Any]],
    receipts: Sequence[Mapping[str, Any]],
    *,
    measurement_scope: str,
    transcript_root: str | Path | None = None,
) -> dict[str, Any]:
    """Evaluate every frozen pair and reject request-side manipulation."""

    require_valid_taskset(taskset)
    if measurement_scope not in {"synthetic_contract_fixture", "real_paired_agent_runs"}:
        raise AgentBenchmarkError("unsupported measurement_scope")
    base = _evaluate_existing_pairs(
        taskset,
        requests,
        receipts,
        measurement_scope=measurement_scope,
        transcript_root=transcript_root,
    )
    cases = _complete_case_results(
        taskset,
        list_value(base.get("cases")),
        requests,
    )
    classes = _class_results(
        cases,
        thresholds=mapping_value(taskset.get("thresholds")),
        measurement_scope=measurement_scope,
    )
    valid_run_count = sum(
        int(mapping_value(item.get(condition)).get("valid") is True)
        for item in cases
        for condition in CONDITIONS
    )
    expected_run_count = len(expected_pair_keys(taskset)) * len(CONDITIONS)
    run_count = max(expected_run_count, len(requests), len(receipts))
    return {
        "kind": EVALUATION_KIND,
        "version": VERSION,
        "taskset_id": str(taskset["id"]),
        "taskset_sha256": sha256_json(taskset),
        "measurement_scope": measurement_scope,
        "run_count": run_count,
        "valid_run_count": valid_run_count,
        "invalid_run_count": run_count - valid_run_count,
        "cases": cases,
        "classes": classes,
        "decision": _decision(classes, measurement_scope=measurement_scope),
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }


__all__ = ["evaluate_paired_runs"]
