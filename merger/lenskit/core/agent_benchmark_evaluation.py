"""Score paired benchmark receipts and classify bounded task classes."""
from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from merger.lenskit.core.agent_benchmark_common import (
    CATEGORIES,
    CONDITIONS,
    DOES_NOT_ESTABLISH,
    EVALUATION_KIND,
    NON_ANSWER_OUTCOMES,
    VERSION,
    is_repository_relative_path,
    list_value,
    mapping_value,
    require_valid_taskset,
    sha256_json,
)
from merger.lenskit.core.agent_benchmark_receipts import validate_receipt


def _citation_key(value: Mapping[str, Any]) -> tuple[str, int, int] | None:
    path = value.get("path")
    start = value.get("start_line")
    end = value.get("end_line")
    if not is_repository_relative_path(path):
        return None
    if not isinstance(start, int) or not isinstance(end, int):
        return None
    return str(path).strip(), start, end


def _set_of_strings(value: Any) -> set[str]:
    return {str(item) for item in list_value(value) if isinstance(item, str) and item}


def _target_hit_rate(expectation: Mapping[str, Any], answer: Mapping[str, Any]) -> float:
    required_paths = _set_of_strings(expectation.get("required_paths"))
    required_symbols = _set_of_strings(expectation.get("required_symbols"))
    required_claims = _set_of_strings(expectation.get("required_claims"))
    observed_paths = _set_of_strings(answer.get("reported_paths"))
    observed_symbols = _set_of_strings(answer.get("reported_symbols"))
    observed_claims = _set_of_strings(answer.get("claims"))
    targets = required_paths | required_symbols | required_claims
    matched = (
        required_paths.intersection(observed_paths)
        | required_symbols.intersection(observed_symbols)
        | required_claims.intersection(observed_claims)
    )
    return len(matched) / len(targets) if targets else 1.0


def _false_hit_count(expectation: Mapping[str, Any], answer: Mapping[str, Any]) -> int:
    observed_paths = _set_of_strings(answer.get("reported_paths"))
    allowed_paths = _set_of_strings(expectation.get("allowed_paths"))
    forbidden_paths = _set_of_strings(expectation.get("forbidden_paths"))
    observed_claims = _set_of_strings(answer.get("claims"))
    forbidden_claims = _set_of_strings(expectation.get("forbidden_claims"))
    outside_allowed = observed_paths - allowed_paths if allowed_paths else observed_paths
    false_paths = outside_allowed | observed_paths.intersection(forbidden_paths)
    false_claims = observed_claims.intersection(forbidden_claims)
    return len(false_paths) + len(false_claims)


def _citation_match_rate(
    expectation: Mapping[str, Any], answer: Mapping[str, Any]
) -> float:
    required = {
        key
        for item in list_value(expectation.get("required_citations"))
        if (key := _citation_key(mapping_value(item))) is not None
    }
    observed = {
        key
        for item in list_value(answer.get("citations"))
        if (key := _citation_key(mapping_value(item))) is not None
    }
    return len(required.intersection(observed)) / len(required) if required else 1.0


def _false_confidence(expectation: Mapping[str, Any], answer: Mapping[str, Any]) -> bool:
    return bool(
        expectation.get("outcome") in NON_ANSWER_OUTCOMES
        and (
            answer.get("outcome") == "answer"
            or answer.get("asserted_sufficient_evidence") is True
        )
    )


def _tool_bytes(receipt: Mapping[str, Any]) -> int:
    return sum(
        int(mapping_value(call).get("input_bytes") or 0)
        + int(mapping_value(call).get("output_bytes") or 0)
        for call in list_value(receipt.get("tool_calls"))
    )


def score_receipt(
    case: Mapping[str, Any],
    condition: str,
    request: Mapping[str, Any],
    receipt: Mapping[str, Any],
    *,
    transcript_root: str | Path | None = None,
) -> dict[str, Any]:
    errors = validate_receipt(request, receipt, transcript_root=transcript_root)
    expectation = mapping_value(mapping_value(case.get("expectations")).get(condition))
    answer = mapping_value(receipt.get("answer"))
    target_hit_rate = _target_hit_rate(expectation, answer)
    false_hit_count = _false_hit_count(expectation, answer)
    citation_match_rate = _citation_match_rate(expectation, answer)
    false_confidence = _false_confidence(expectation, answer)
    outcome_match = answer.get("outcome") == expectation.get("outcome")
    valid = not errors and receipt.get("status") == "success"
    success = bool(
        valid
        and outcome_match
        and target_hit_rate == 1.0
        and false_hit_count == 0
        and citation_match_rate == 1.0
        and not false_confidence
    )
    provider = mapping_value(receipt.get("provider"))
    calls = list_value(receipt.get("tool_calls"))
    return {
        "valid": valid,
        "success": success,
        "outcome_match": outcome_match,
        "target_hit_rate": target_hit_rate,
        "false_hit_count": false_hit_count,
        "citation_match_rate": citation_match_rate,
        "false_confidence": false_confidence,
        "duration_ms": int(receipt.get("duration_ms") or 0),
        "tool_call_count": len(calls),
        "input_tokens": int(provider.get("input_tokens") or 0),
        "output_tokens": int(provider.get("output_tokens") or 0),
        "tool_bytes": _tool_bytes(receipt),
        "invalid_reasons": errors,
    }


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


def _duplicate_ids(items: Sequence[Mapping[str, Any]], field: str) -> set[str]:
    counts = Counter(str(item.get(field, "")) for item in items)
    return {identifier for identifier, count in counts.items() if identifier and count > 1}


def _group_requests(
    requests: Sequence[Mapping[str, Any]],
) -> dict[tuple[str, int], dict[str, list[Mapping[str, Any]]]]:
    grouped: dict[tuple[str, int], dict[str, list[Mapping[str, Any]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for request in requests:
        key = (str(request.get("case_id", "")), int(request.get("repetition") or 0))
        grouped[key][str(request.get("condition", ""))].append(request)
    return grouped


def _receipt_index(
    receipts: Sequence[Mapping[str, Any]],
) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for receipt in receipts:
        identifier = str(receipt.get("request_id", ""))
        result.setdefault(identifier, receipt)
    return result


def _score_condition(
    *,
    case: Mapping[str, Any],
    condition: str,
    candidates: Sequence[Mapping[str, Any]],
    receipts: Mapping[str, Mapping[str, Any]],
    duplicate_request_ids: set[str],
    duplicate_receipt_ids: set[str],
    transcript_root: str | Path | None,
) -> tuple[Mapping[str, Any], dict[str, Any]]:
    if len(candidates) != 1:
        return {}, _invalid_score(f"expected one {condition} request, got {len(candidates)}")
    request = candidates[0]
    request_id = str(request.get("request_id", ""))
    if request_id in duplicate_request_ids:
        return request, _invalid_score("duplicate request_id")
    if request_id in duplicate_receipt_ids:
        return request, _invalid_score("duplicate receipt request_id")
    receipt = receipts.get(request_id)
    if receipt is None:
        return request, _invalid_score("missing receipt")
    return request, score_receipt(
        case,
        condition,
        request,
        receipt,
        transcript_root=transcript_root,
    )


def _isolation_errors(
    requests: Sequence[Mapping[str, Any]],
) -> list[str]:
    sessions = {str(request.get("session_id", "")) for request in requests}
    workspaces = {str(request.get("workspace_id", "")) for request in requests}
    errors: list[str] = []
    if len(sessions) != 2 or "" in sessions:
        errors.append("paired conditions reused session identity")
    if len(workspaces) != 2 or "" in workspaces:
        errors.append("paired conditions reused workspace identity")
    return errors


def _score_pair(
    *,
    case: Mapping[str, Any],
    candidates: Mapping[str, Sequence[Mapping[str, Any]]],
    receipts: Mapping[str, Mapping[str, Any]],
    duplicate_request_ids: set[str],
    duplicate_receipt_ids: set[str],
    transcript_root: str | Path | None,
) -> tuple[bool, dict[str, dict[str, Any]]]:
    requests: list[Mapping[str, Any]] = []
    scores: dict[str, dict[str, Any]] = {}
    for condition in CONDITIONS:
        request, score = _score_condition(
            case=case,
            condition=condition,
            candidates=candidates.get(condition, []),
            receipts=receipts,
            duplicate_request_ids=duplicate_request_ids,
            duplicate_receipt_ids=duplicate_receipt_ids,
            transcript_root=transcript_root,
        )
        if request:
            requests.append(request)
        scores[condition] = score
    isolation_errors = _isolation_errors(requests)
    for error in isolation_errors:
        for score in scores.values():
            score["invalid_reasons"].append(error)
            score["valid"] = False
            score["success"] = False
    pair_valid = not isolation_errors and all(score["valid"] for score in scores.values())
    return pair_valid, scores


def _case_results(
    taskset: Mapping[str, Any],
    requests: Sequence[Mapping[str, Any]],
    receipts: Sequence[Mapping[str, Any]],
    *,
    transcript_root: str | Path | None,
) -> list[dict[str, Any]]:
    cases = {str(item["id"]): item for item in list_value(taskset.get("cases"))}
    grouped = _group_requests(requests)
    receipt_by_id = _receipt_index(receipts)
    duplicate_request_ids = _duplicate_ids(requests, "request_id")
    duplicate_receipt_ids = _duplicate_ids(receipts, "request_id")
    results: list[dict[str, Any]] = []
    for (case_id, repetition), candidates in sorted(grouped.items()):
        case = cases.get(case_id)
        if case is None:
            continue
        pair_valid, scores = _score_pair(
            case=case,
            candidates=candidates,
            receipts=receipt_by_id,
            duplicate_request_ids=duplicate_request_ids,
            duplicate_receipt_ids=duplicate_receipt_ids,
            transcript_root=transcript_root,
        )
        results.append(
            {
                "case_id": case_id,
                "category": str(case["category"]),
                "repetition": repetition,
                "pair_valid": pair_valid,
                "baseline": scores["baseline"],
                "treatment": scores["treatment"],
            }
        )
    return results


def _mean(values: Sequence[int | float]) -> float:
    return float(sum(values) / len(values)) if values else 0.0


def _improvement(baseline: float, treatment: float) -> float | None:
    return (baseline - treatment) / baseline if baseline > 0 else None


def _efficiency_metric(
    baseline: Sequence[Mapping[str, Any]],
    treatment: Sequence[Mapping[str, Any]],
    field: str,
) -> dict[str, Any]:
    baseline_mean = _mean([float(score[field]) for score in baseline])
    treatment_mean = _mean([float(score[field]) for score in treatment])
    return {
        "baseline_mean": baseline_mean,
        "treatment_mean": treatment_mean,
        "improvement_ratio": _improvement(baseline_mean, treatment_mean),
    }


def _efficiency(
    baseline: Sequence[Mapping[str, Any]], treatment: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    fields = {
        "duration": "duration_ms",
        "tool_calls": "tool_call_count",
        "input_tokens": "input_tokens",
        "output_tokens": "output_tokens",
        "tool_bytes": "tool_bytes",
    }
    return {
        label: _efficiency_metric(baseline, treatment, field)
        for label, field in fields.items()
    }


def _positive_direction(
    pairs: Sequence[Mapping[str, Any]], *, score_field: str | None
) -> bool:
    by_repetition: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
    for pair in pairs:
        by_repetition[int(pair["repetition"])].append(pair)
    if len(by_repetition) < 2:
        return False
    return all(
        _repetition_positive(repetition_pairs, score_field=score_field)
        for repetition_pairs in by_repetition.values()
    )


def _repetition_positive(
    pairs: Sequence[Mapping[str, Any]], *, score_field: str | None
) -> bool:
    baseline_success = _mean(
        [1.0 if mapping_value(pair["baseline"]).get("success") else 0.0 for pair in pairs]
    )
    treatment_success = _mean(
        [1.0 if mapping_value(pair["treatment"]).get("success") else 0.0 for pair in pairs]
    )
    if treatment_success > baseline_success:
        return True
    if score_field is None:
        return False
    baseline_value = _mean(
        [float(mapping_value(pair["baseline"])[score_field]) for pair in pairs]
    )
    treatment_value = _mean(
        [float(mapping_value(pair["treatment"])[score_field]) for pair in pairs]
    )
    return baseline_value > 0 and treatment_value < baseline_value


def _quality_metrics(
    baseline: Sequence[Mapping[str, Any]], treatment: Sequence[Mapping[str, Any]]
) -> tuple[float, float, float, float, float, float]:
    baseline_success = _mean([1.0 if score.get("success") else 0.0 for score in baseline])
    treatment_success = _mean([1.0 if score.get("success") else 0.0 for score in treatment])
    baseline_false = _mean(
        [1.0 if score.get("false_confidence") else 0.0 for score in baseline]
    )
    treatment_false = _mean(
        [1.0 if score.get("false_confidence") else 0.0 for score in treatment]
    )
    return (
        baseline_success,
        treatment_success,
        treatment_success - baseline_success,
        baseline_false,
        treatment_false,
        treatment_false - baseline_false,
    )


def _is_harmful(
    success_delta: float, false_delta: float, thresholds: Mapping[str, Any]
) -> bool:
    return bool(
        success_delta < -float(thresholds["maximum_class_success_regression"])
        or false_delta > float(thresholds["maximum_false_confidence_increase"])
    )


def _is_useful(
    pairs: Sequence[Mapping[str, Any]],
    *,
    success_delta: float,
    efficiency: Mapping[str, Mapping[str, Any]],
    thresholds: Mapping[str, Any],
) -> bool:
    success_gain = success_delta >= float(thresholds["minimum_success_rate_gain"])
    if success_gain and _positive_direction(pairs, score_field=None):
        return True
    fields = {
        "duration": "duration_ms",
        "tool_calls": "tool_call_count",
        "input_tokens": "input_tokens",
        "output_tokens": "output_tokens",
        "tool_bytes": "tool_bytes",
    }
    minimum = float(thresholds["minimum_efficiency_improvement"])
    qualifying = [
        label
        for label, metric in efficiency.items()
        if metric["improvement_ratio"] is not None
        and float(metric["improvement_ratio"]) >= minimum
    ]
    return any(
        _positive_direction(pairs, score_field=fields[label]) for label in qualifying
    )


def _class_result(
    pairs: Sequence[Mapping[str, Any]],
    *,
    thresholds: Mapping[str, Any],
    measurement_scope: str,
) -> dict[str, Any]:
    valid_pairs = [pair for pair in pairs if pair.get("pair_valid") is True]
    baseline = [mapping_value(pair["baseline"]) for pair in valid_pairs]
    treatment = [mapping_value(pair["treatment"]) for pair in valid_pairs]
    quality = _quality_metrics(baseline, treatment)
    baseline_success, treatment_success, success_delta = quality[:3]
    baseline_false, treatment_false, false_delta = quality[3:]
    efficiency = _efficiency(baseline, treatment)
    if measurement_scope == "synthetic_contract_fixture":
        classification = "synthetic_only"
    elif not valid_pairs or len(valid_pairs) != len(pairs):
        classification = "insufficient_evidence"
    elif _is_harmful(success_delta, false_delta, thresholds):
        classification = "harmful"
    elif _is_useful(
        valid_pairs,
        success_delta=success_delta,
        efficiency=efficiency,
        thresholds=thresholds,
    ):
        classification = "useful"
    else:
        classification = "neutral"
    return {
        "valid_pair_count": len(valid_pairs),
        "baseline_success_rate": baseline_success,
        "treatment_success_rate": treatment_success,
        "success_rate_delta": success_delta,
        "baseline_false_confidence_rate": baseline_false,
        "treatment_false_confidence_rate": treatment_false,
        "false_confidence_delta": false_delta,
        "efficiency": efficiency,
        "classification": classification,
    }


def _class_results(
    case_results: Sequence[Mapping[str, Any]],
    *,
    thresholds: Mapping[str, Any],
    measurement_scope: str,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for category in CATEGORIES:
        pairs = [item for item in case_results if item["category"] == category]
        result = _class_result(
            pairs,
            thresholds=thresholds,
            measurement_scope=measurement_scope,
        )
        result["category"] = category
        results.append(result)
    return results


def _decision(
    class_results: Sequence[Mapping[str, Any]], *, measurement_scope: str
) -> dict[str, Any]:
    classifications = {
        str(item["category"]): str(item["classification"]) for item in class_results
    }
    useful = sorted(key for key, value in classifications.items() if value == "useful")
    harmful = sorted(key for key, value in classifications.items() if value == "harmful")
    if measurement_scope == "synthetic_contract_fixture":
        status = "synthetic_only"
        reason = "synthetic fixtures validate contracts but cannot establish agent usefulness"
    elif harmful:
        status = "harmful"
        reason = "at least one task class crossed a quality or safety regression threshold"
    elif "insufficient_evidence" in classifications.values():
        status = "insufficient_evidence"
        reason = "one or more task classes lack complete valid paired evidence"
    elif useful:
        status = "useful_class"
        reason = "at least one class met a reproducible benefit threshold without regression"
    else:
        status = "neutral"
        reason = "no task class met a registered benefit or harm threshold"
    return {
        "status": status,
        "useful_classes": useful,
        "harmful_classes": harmful,
        "default_promoted": False,
        "reason": reason,
    }


def evaluate_paired_runs(
    taskset: Mapping[str, Any],
    requests: Sequence[Mapping[str, Any]],
    receipts: Sequence[Mapping[str, Any]],
    *,
    measurement_scope: str,
    transcript_root: str | Path | None = None,
) -> dict[str, Any]:
    require_valid_taskset(taskset)
    if measurement_scope not in {"synthetic_contract_fixture", "real_paired_agent_runs"}:
        raise ValueError("unsupported measurement_scope")
    case_results = _case_results(
        taskset,
        requests,
        receipts,
        transcript_root=transcript_root,
    )
    classes = _class_results(
        case_results,
        thresholds=mapping_value(taskset.get("thresholds")),
        measurement_scope=measurement_scope,
    )
    valid_run_count = sum(
        int(mapping_value(item[condition]).get("valid") is True)
        for item in case_results
        for condition in CONDITIONS
    )
    expected_run_count = len(requests)
    extra_receipts = max(len(receipts) - expected_run_count, 0)
    return {
        "kind": EVALUATION_KIND,
        "version": VERSION,
        "taskset_id": str(taskset["id"]),
        "taskset_sha256": sha256_json(taskset),
        "measurement_scope": measurement_scope,
        "run_count": max(expected_run_count, len(receipts)),
        "valid_run_count": valid_run_count,
        "invalid_run_count": expected_run_count - valid_run_count + extra_receipts,
        "cases": case_results,
        "classes": classes,
        "decision": _decision(classes, measurement_scope=measurement_scope),
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }


__all__ = ["evaluate_paired_runs", "score_receipt"]
