"""Integrity wrapper for complete and taskset-bound benchmark evaluation."""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from merger.repoground.core.agent_benchmark_common import (
    AgentBenchmarkError,
    CONDITIONS,
    COMPONENT_DELTA_MODE,
    DOES_NOT_ESTABLISH,
    EVALUATION_KIND,
    VERSION,
    comparison_contract,
    comparison_mode,
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
    pair_errors = pair_request_errors(taskset, requests)
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



def _comparison_evidence(
    taskset: Mapping[str, Any], requests: Sequence[Mapping[str, Any]], cases: Sequence[Mapping[str, Any]]
) -> dict[str, Any] | None:
    if comparison_mode(taskset) != COMPONENT_DELTA_MODE:
        return None
    comparison = comparison_contract(taskset)
    treatment_artifacts = sorted(
        {
            (
                str(mapping_value(request.get("repository")).get("id")),
                str(mapping_value(request.get("component_delta")).get("artifact")),
                str(mapping_value(request.get("component_delta")).get("artifact_sha256")),
            )
            for request in requests
            if request.get("condition") == "treatment"
            and isinstance(mapping_value(request.get("repository")).get("id"), str)
            and isinstance(mapping_value(request.get("component_delta")).get("artifact"), str)
            and isinstance(mapping_value(request.get("component_delta")).get("artifact_sha256"), str)
        }
    )
    expected = set(expected_pair_keys(taskset))
    observed = {
        (str(item.get("case_id")), int(item.get("repetition") or 0)) for item in cases
    }
    return {
        "mode": COMPONENT_DELTA_MODE,
        "component": str(comparison.get("component", "")),
        "source_revision": str(comparison.get("source_revision", "")),
        "treatment_artifacts": [
            {
                "repository_id": repository_id,
                "artifact": artifact,
                "artifact_sha256": artifact_sha256,
            }
            for repository_id, artifact, artifact_sha256 in treatment_artifacts
        ],
        "pair_isolation_verified": (
            bool(expected)
            and observed == expected
            and len(cases) == len(expected)
            and all(item.get("pair_valid") is True for item in cases)
        ),
    }



def _evaluation_input_evidence(
    taskset: Mapping[str, Any],
    requests: Sequence[Mapping[str, Any]],
    receipts: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    ordered_requests = sorted(
        (dict(item) for item in requests), key=lambda item: str(item.get("request_id", ""))
    )
    ordered_receipts = sorted(
        (dict(item) for item in receipts), key=lambda item: str(item.get("request_id", ""))
    )
    transcripts = [
        {
            "request_id": str(item.get("request_id", "")),
            "sha256": str(mapping_value(item.get("transcript")).get("sha256", "")),
        }
        for item in ordered_receipts
    ]
    return {
        "taskset_sha256": sha256_json(taskset),
        "requests_sha256": sha256_json(ordered_requests),
        "receipts_sha256": sha256_json(ordered_receipts),
        "transcripts": transcripts,
    }

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
    result = {
        "kind": EVALUATION_KIND,
        "version": VERSION,
        "taskset_id": str(taskset["id"]),
        "taskset_sha256": sha256_json(taskset),
        "measurement_scope": measurement_scope,
        "evidence": _evaluation_input_evidence(taskset, requests, receipts),
        "thresholds": dict(mapping_value(taskset.get("thresholds"))),
        "run_count": run_count,
        "valid_run_count": valid_run_count,
        "invalid_run_count": run_count - valid_run_count,
        "cases": cases,
        "classes": classes,
        "decision": _decision(classes, measurement_scope=measurement_scope),
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }
    comparison = _comparison_evidence(taskset, requests, cases)
    if comparison is not None:
        result["comparison"] = comparison
    return result


def validate_evaluation_evidence(
    evaluation: Mapping[str, Any],
    taskset: Mapping[str, Any],
    requests: Sequence[Mapping[str, Any]],
    receipts: Sequence[Mapping[str, Any]],
    *,
    transcript_root: str | Path | None = None,
) -> list[str]:
    """Re-evaluate the bound run inputs and require byte/digest-equivalent evidence."""

    measurement_scope = evaluation.get("measurement_scope")
    if measurement_scope not in {"synthetic_contract_fixture", "real_paired_agent_runs"}:
        return ["evaluation measurement_scope is invalid"]
    try:
        recomputed = evaluate_paired_runs(
            taskset,
            requests,
            receipts,
            measurement_scope=str(measurement_scope),
            transcript_root=transcript_root,
        )
    except (AgentBenchmarkError, KeyError, TypeError, ValueError, OverflowError) as exc:
        return [f"evaluation input revalidation failed: {exc}"]
    if dict(evaluation) != recomputed:
        return ["evaluation does not match re-evaluated taskset, requests, receipts, and transcripts"]
    return []


__all__ = ["evaluate_paired_runs", "validate_evaluation_evidence"]
