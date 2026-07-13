"""Deterministic contracts and evaluation for paired RepoBrief agent benchmarks.

This module prepares and evaluates benchmark runs. It does not provide an LLM,
model credentials, token estimation, or a claim that synthetic fixtures measure
real agent usefulness.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

TASKSET_KIND = "repobrief.agent_benchmark_taskset"
REQUEST_KIND = "repobrief.agent_benchmark_run_request"
RECEIPT_KIND = "repobrief.agent_benchmark_run_receipt"
EVALUATION_KIND = "repobrief.agent_benchmark_evaluation"
VERSION = "1.0"
CATEGORIES = ("navigation", "structural", "grounding_freshness")
CONDITIONS = ("baseline", "treatment")
NON_ANSWER_OUTCOMES = {
    "abstain",
    "stale",
    "not_comparable",
    "invalid_evidence",
}
MAX_JSON_BYTES = 16 * 1024 * 1024
MAX_RUNNER_STDERR_BYTES = 256 * 1024
DOES_NOT_ESTABLISH = (
    "real_agent_usefulness",
    "answer_correctness_outside_fixed_expectations",
    "complete_repository_understanding",
    "test_sufficiency",
    "review_completeness",
    "merge_readiness",
    "default_promotion",
)


class AgentBenchmarkError(ValueError):
    """A benchmark contract or evidence boundary was violated."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def load_json(path: str | Path, *, max_bytes: int = MAX_JSON_BYTES) -> dict[str, Any]:
    candidate = Path(path).expanduser().resolve()
    try:
        with candidate.open("rb") as handle:
            raw = handle.read(max_bytes + 1)
    except OSError as exc:
        raise AgentBenchmarkError(f"cannot read JSON document: {candidate}") from exc
    if len(raw) > max_bytes:
        raise AgentBenchmarkError(f"JSON document exceeds {max_bytes} bytes: {candidate}")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AgentBenchmarkError(f"invalid UTF-8 JSON document: {candidate}") from exc
    if not isinstance(value, dict):
        raise AgentBenchmarkError(f"JSON document must be an object: {candidate}")
    return value


def write_json_atomic(path: str | Path, value: Mapping[str, Any]) -> None:
    destination = Path(path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", dir=destination.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def is_repository_relative_path(value: Any) -> bool:
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
    return bool(PurePosixPath(text).parts)


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _validate_paths(values: Any, *, label: str, errors: list[str]) -> set[str]:
    paths: set[str] = set()
    for value in _list(values):
        if not is_repository_relative_path(value):
            errors.append(f"{label} contains a non-canonical repository path: {value!r}")
            continue
        path = str(value).strip()
        if path in paths:
            errors.append(f"{label} contains duplicate path {path!r}")
        paths.add(path)
    return paths


def _validate_expectation(
    expectation: Mapping[str, Any], *, case_id: str, condition: str, errors: list[str]
) -> None:
    prefix = f"case {case_id} {condition}"
    required = _validate_paths(
        expectation.get("required_paths"),
        label=f"{prefix}.required_paths",
        errors=errors,
    )
    allowed = _validate_paths(
        expectation.get("allowed_paths"),
        label=f"{prefix}.allowed_paths",
        errors=errors,
    )
    forbidden = _validate_paths(
        expectation.get("forbidden_paths"),
        label=f"{prefix}.forbidden_paths",
        errors=errors,
    )
    if not required.issubset(allowed):
        errors.append(f"{prefix}: required_paths must be a subset of allowed_paths")
    if allowed.intersection(forbidden):
        errors.append(f"{prefix}: allowed_paths and forbidden_paths overlap")
    for citation in _list(expectation.get("required_citations")):
        item = _mapping(citation)
        path = item.get("path")
        start = item.get("start_line")
        end = item.get("end_line")
        if not is_repository_relative_path(path):
            errors.append(f"{prefix}: citation path is not repository-relative: {path!r}")
        if not isinstance(start, int) or not isinstance(end, int) or start < 1 or end < start:
            errors.append(f"{prefix}: citation range is invalid: {citation!r}")


def validate_taskset(taskset: Mapping[str, Any]) -> list[str]:
    """Return deterministic semantic errors not covered by the JSON schema."""

    errors: list[str] = []
    if taskset.get("kind") != TASKSET_KIND or taskset.get("version") != VERSION:
        errors.append("taskset kind/version mismatch")
    if taskset.get("measurement_scope") != "frozen_paired_agent_ab":
        errors.append("taskset measurement_scope must be frozen_paired_agent_ab")
    if taskset.get("default_promoted") is not False:
        errors.append("taskset default_promoted must remain false")

    repositories = _list(taskset.get("repositories"))
    repository_ids = [str(_mapping(item).get("id", "")) for item in repositories]
    if len(repository_ids) < 3 or len(set(repository_ids)) != len(repository_ids):
        errors.append("taskset must contain at least three uniquely identified repositories")

    policy = _mapping(taskset.get("tool_policy"))
    baseline_tools = {str(item) for item in _list(policy.get("baseline"))}
    treatment_tools = {str(item) for item in _list(policy.get("treatment"))}
    if not baseline_tools:
        errors.append("baseline tool policy must not be empty")
    if not baseline_tools.issubset(treatment_tools):
        errors.append("treatment tools must include every baseline tool")
    required_treatment = {
        "ask_context",
        "repobrief_resource_read",
        "grounding_verify",
        "live_freshness",
    }
    if not required_treatment.issubset(treatment_tools):
        errors.append("treatment tool policy misses required RepoBrief tools")
    if baseline_tools.intersection(required_treatment):
        errors.append("baseline tool policy must not expose RepoBrief tools")

    cases = _list(taskset.get("cases"))
    if len(cases) != 24:
        errors.append(f"taskset must contain exactly 24 cases, got {len(cases)}")
    ids = [str(_mapping(case).get("id", "")) for case in cases]
    if len(set(ids)) != len(ids):
        errors.append("taskset case ids must be unique")
    categories = Counter(str(_mapping(case).get("category", "")) for case in cases)
    for category in CATEGORIES:
        if categories[category] != 8:
            errors.append(f"taskset category {category} must contain 8 cases")
    unknown_categories = set(categories).difference(CATEGORIES)
    if unknown_categories:
        errors.append(f"taskset contains unknown categories: {sorted(unknown_categories)!r}")

    negative_cases = 0
    repository_id_set = set(repository_ids)
    for case in cases:
        item = _mapping(case)
        case_id = str(item.get("id", ""))
        if item.get("repository_id") not in repository_id_set:
            errors.append(f"case {case_id} references an unknown repository")
        expectations = _mapping(item.get("expectations"))
        for condition in CONDITIONS:
            expectation = _mapping(expectations.get(condition))
            _validate_expectation(
                expectation,
                case_id=case_id,
                condition=condition,
                errors=errors,
            )
        if any(
            _mapping(expectations.get(condition)).get("outcome") in NON_ANSWER_OUTCOMES
            for condition in CONDITIONS
        ):
            negative_cases += 1
    if negative_cases < 6:
        errors.append("taskset must contain at least six abstention/negative cases")
    return errors


def require_valid_taskset(taskset: Mapping[str, Any]) -> None:
    errors = validate_taskset(taskset)
    if errors:
        raise AgentBenchmarkError("; ".join(errors))


def _repository_map(taskset: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item["id"]): dict(item)
        for item in _list(taskset.get("repositories"))
        if isinstance(item, Mapping) and isinstance(item.get("id"), str)
    }


def _request_identity(
    *, taskset_id: str, case_id: str, repetition: int, condition: str
) -> tuple[str, str, str, str]:
    pair_id = f"{taskset_id}:{case_id}:r{repetition}"
    request_id = f"{pair_id}:{condition}"
    session_id = f"session:{request_id}"
    workspace_id = f"workspace:{request_id}"
    return pair_id, request_id, session_id, workspace_id


def build_run_requests(
    taskset: Mapping[str, Any],
    *,
    runner: Mapping[str, Any],
    manifest_bindings: Mapping[str, Mapping[str, Any]],
    repetitions: int = 2,
) -> list[dict[str, Any]]:
    """Build isolated and deterministically balanced paired run requests."""

    require_valid_taskset(taskset)
    if repetitions < 1:
        raise AgentBenchmarkError("repetitions must be at least 1")
    if not runner.get("provider") or not runner.get("model"):
        raise AgentBenchmarkError("runner provider and model are required")
    repositories = _repository_map(taskset)
    taskset_hash = sha256_json(taskset)
    result: list[dict[str, Any]] = []
    for repetition in range(1, repetitions + 1):
        for case_index, raw_case in enumerate(_list(taskset.get("cases"))):
            case = _mapping(raw_case)
            case_id = str(case["id"])
            repository = repositories[str(case["repository_id"])]
            baseline_first = (case_index + repetition - 1) % 2 == 0
            condition_order = (
                ("baseline", "treatment")
                if baseline_first
                else ("treatment", "baseline")
            )
            for order, condition in enumerate(condition_order, start=1):
                pair_id, request_id, session_id, workspace_id = _request_identity(
                    taskset_id=str(taskset["id"]),
                    case_id=case_id,
                    repetition=repetition,
                    condition=condition,
                )
                repobrief: dict[str, Any] | None = None
                if condition == "treatment":
                    binding = manifest_bindings.get(str(case["repository_id"]))
                    if not isinstance(binding, Mapping):
                        raise AgentBenchmarkError(
                            f"missing RepoBrief manifest binding for {case['repository_id']}"
                        )
                    repobrief = {
                        "manifest": str(binding["manifest"]),
                        "manifest_sha256": str(binding["manifest_sha256"]),
                        "mcp_command": list(binding["mcp_command"]),
                    }
                result.append(
                    {
                        "kind": REQUEST_KIND,
                        "version": VERSION,
                        "request_id": request_id,
                        "pair_id": pair_id,
                        "case_id": case_id,
                        "condition": condition,
                        "order": order,
                        "repetition": repetition,
                        "taskset_id": str(taskset["id"]),
                        "taskset_sha256": taskset_hash,
                        "repository": {
                            "id": str(repository["id"]),
                            "repository": str(repository["repository"]),
                            "commit": str(repository["commit"]),
                        },
                        "session_id": session_id,
                        "workspace_id": workspace_id,
                        "prompt": str(case["prompt"]),
                        "allowed_tools": list(
                            _mapping(taskset["tool_policy"])[condition]
                        ),
                        "budgets": dict(_mapping(taskset["budgets"])),
                        "runner": {
                            "provider": str(runner["provider"]),
                            "model": str(runner["model"]),
                            "sampling": dict(_mapping(runner.get("sampling"))),
                        },
                        "repobrief": repobrief,
                        "isolation": {
                            "fresh_session": True,
                            "fresh_workspace": True,
                            "cross_condition_reuse_allowed": False,
                        },
                        "does_not_establish": list(DOES_NOT_ESTABLISH),
                    }
                )
    return result


def _resolve_artifact(path: str, root: Path) -> Path | None:
    candidate = (root / path).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    return candidate


def validate_receipt(
    request: Mapping[str, Any],
    receipt: Mapping[str, Any],
    *,
    transcript_root: str | Path | None = None,
) -> list[str]:
    """Validate identity, budget, tool policy and transcript evidence."""

    errors: list[str] = []
    if receipt.get("kind") != RECEIPT_KIND or receipt.get("version") != VERSION:
        errors.append("receipt kind/version mismatch")
    if receipt.get("request_id") != request.get("request_id"):
        errors.append("receipt request_id does not match request")
    if receipt.get("request_sha256") != sha256_json(request):
        errors.append("receipt request_sha256 does not match request")

    request_runner = _mapping(request.get("runner"))
    provider = _mapping(receipt.get("provider"))
    if provider.get("name") != request_runner.get("provider"):
        errors.append("receipt provider does not match request")
    if provider.get("model") != request_runner.get("model"):
        errors.append("receipt model does not match request")
    if _mapping(provider.get("sampling")) != _mapping(request_runner.get("sampling")):
        errors.append("receipt sampling settings do not match request")
    if provider.get("token_source") != "provider_reported":
        errors.append("receipt tokens are not provider-reported")

    budgets = _mapping(request.get("budgets"))
    for field in ("input_tokens", "output_tokens"):
        value = provider.get(field)
        if not isinstance(value, int) or value < 0:
            errors.append(f"receipt {field} is invalid")
        elif value > int(budgets.get(field, -1)):
            errors.append(f"receipt exceeds {field} budget")
    duration = receipt.get("duration_ms")
    if not isinstance(duration, int) or duration < 0:
        errors.append("receipt duration_ms is invalid")
    elif duration > int(budgets.get("wall_seconds", 0)) * 1000:
        errors.append("receipt exceeds wall-clock budget")

    allowed_tools = set(_list(request.get("allowed_tools")))
    calls = _list(receipt.get("tool_calls"))
    if len(calls) > int(budgets.get("max_tool_calls", -1)):
        errors.append("receipt exceeds tool-call budget")
    total_input_bytes = 0
    total_output_bytes = 0
    for expected_sequence, raw_call in enumerate(calls, start=1):
        call = _mapping(raw_call)
        if call.get("sequence") != expected_sequence:
            errors.append("tool-call sequence is not contiguous")
        if call.get("name") not in allowed_tools:
            errors.append(f"disallowed tool call: {call.get('name')!r}")
        input_bytes = call.get("input_bytes")
        output_bytes = call.get("output_bytes")
        if not isinstance(input_bytes, int) or input_bytes < 0:
            errors.append("tool-call input_bytes is invalid")
        else:
            total_input_bytes += input_bytes
        if not isinstance(output_bytes, int) or output_bytes < 0:
            errors.append("tool-call output_bytes is invalid")
        else:
            total_output_bytes += output_bytes
    if total_input_bytes > int(budgets.get("max_tool_input_bytes", -1)):
        errors.append("receipt exceeds tool-input byte budget")
    if total_output_bytes > int(budgets.get("max_tool_output_bytes", -1)):
        errors.append("receipt exceeds tool-output byte budget")

    transcript = _mapping(receipt.get("transcript"))
    storage = transcript.get("storage")
    expected_hash = transcript.get("sha256")
    expected_bytes = transcript.get("bytes")
    content: bytes | None = None
    if storage == "inline":
        inline = transcript.get("inline")
        if not isinstance(inline, str) or transcript.get("artifact") is not None:
            errors.append("inline transcript storage is inconsistent")
        else:
            content = inline.encode("utf-8")
    elif storage == "artifact":
        artifact = transcript.get("artifact")
        if not isinstance(artifact, str) or transcript.get("inline") is not None:
            errors.append("artifact transcript storage is inconsistent")
        elif transcript_root is None:
            errors.append("artifact transcript requires transcript_root")
        else:
            resolved = _resolve_artifact(artifact, Path(transcript_root).expanduser())
            if resolved is None or not resolved.is_file():
                errors.append("transcript artifact is missing or outside transcript_root")
            else:
                content = resolved.read_bytes()
    else:
        errors.append("transcript storage is invalid")
    if content is not None:
        if expected_bytes != len(content):
            errors.append("transcript byte count mismatch")
        if expected_hash != sha256_bytes(content):
            errors.append("transcript SHA-256 mismatch")

    status = receipt.get("status")
    exit_code = receipt.get("exit_code")
    error = receipt.get("error")
    if status == "success" and (exit_code != 0 or error is not None):
        errors.append("successful receipt must have exit_code 0 and no error")
    if status in {"failed", "timeout", "invalid"} and error is None:
        errors.append("non-success receipt requires structured error evidence")
    return errors


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
    return {str(item) for item in _list(value) if isinstance(item, str) and item}


def score_receipt(
    case: Mapping[str, Any],
    condition: str,
    request: Mapping[str, Any],
    receipt: Mapping[str, Any],
    *,
    transcript_root: str | Path | None = None,
) -> dict[str, Any]:
    errors = validate_receipt(request, receipt, transcript_root=transcript_root)
    expectation = _mapping(_mapping(case.get("expectations")).get(condition))
    answer = _mapping(receipt.get("answer"))
    observed_paths = _set_of_strings(answer.get("reported_paths"))
    observed_symbols = _set_of_strings(answer.get("reported_symbols"))
    observed_claims = _set_of_strings(answer.get("claims"))
    required_paths = _set_of_strings(expectation.get("required_paths"))
    allowed_paths = _set_of_strings(expectation.get("allowed_paths"))
    forbidden_paths = _set_of_strings(expectation.get("forbidden_paths"))
    required_symbols = _set_of_strings(expectation.get("required_symbols"))
    required_claims = _set_of_strings(expectation.get("required_claims"))
    forbidden_claims = _set_of_strings(expectation.get("forbidden_claims"))

    target_items = required_paths.union(required_symbols).union(required_claims)
    matched_items = (
        required_paths.intersection(observed_paths)
        .union(required_symbols.intersection(observed_symbols))
        .union(required_claims.intersection(observed_claims))
    )
    target_hit_rate = len(matched_items) / len(target_items) if target_items else 1.0
    outside_allowed = observed_paths.difference(allowed_paths) if allowed_paths else observed_paths
    false_paths = outside_allowed.union(observed_paths.intersection(forbidden_paths))
    false_claims = observed_claims.intersection(forbidden_claims)

    required_citations = {
        key
        for item in _list(expectation.get("required_citations"))
        if (key := _citation_key(_mapping(item))) is not None
    }
    observed_citations = {
        key
        for item in _list(answer.get("citations"))
        if (key := _citation_key(_mapping(item))) is not None
    }
    citation_match_rate = (
        len(required_citations.intersection(observed_citations)) / len(required_citations)
        if required_citations
        else 1.0
    )
    expected_outcome = expectation.get("outcome")
    outcome_match = answer.get("outcome") == expected_outcome
    false_confidence = bool(
        expected_outcome in NON_ANSWER_OUTCOMES
        and (
            answer.get("outcome") == "answer"
            or answer.get("asserted_sufficient_evidence") is True
        )
    )
    valid = not errors and receipt.get("status") == "success"
    success = bool(
        valid
        and outcome_match
        and target_hit_rate == 1.0
        and not false_paths
        and not false_claims
        and citation_match_rate == 1.0
        and not false_confidence
    )
    provider = _mapping(receipt.get("provider"))
    calls = _list(receipt.get("tool_calls"))
    return {
        "valid": valid,
        "success": success,
        "outcome_match": outcome_match,
        "target_hit_rate": target_hit_rate,
        "false_hit_count": len(false_paths) + len(false_claims),
        "citation_match_rate": citation_match_rate,
        "false_confidence": false_confidence,
        "duration_ms": int(receipt.get("duration_ms") or 0),
        "tool_call_count": len(calls),
        "input_tokens": int(provider.get("input_tokens") or 0),
        "output_tokens": int(provider.get("output_tokens") or 0),
        "tool_bytes": sum(
            int(_mapping(call).get("input_bytes") or 0)
            + int(_mapping(call).get("output_bytes") or 0)
            for call in calls
        ),
        "invalid_reasons": errors,
    }


def _mean(values: Sequence[int | float]) -> float:
    return float(sum(values) / len(values)) if values else 0.0


def _improvement(baseline: float, treatment: float) -> float | None:
    return (baseline - treatment) / baseline if baseline > 0 else None


def _efficiency_metric(
    baseline_scores: Sequence[Mapping[str, Any]],
    treatment_scores: Sequence[Mapping[str, Any]],
    field: str,
) -> dict[str, Any]:
    baseline_mean = _mean([float(score[field]) for score in baseline_scores])
    treatment_mean = _mean([float(score[field]) for score in treatment_scores])
    return {
        "baseline_mean": baseline_mean,
        "treatment_mean": treatment_mean,
        "improvement_ratio": _improvement(baseline_mean, treatment_mean),
    }


def _positive_direction_by_repetition(
    pairs: Sequence[Mapping[str, Any]], *, threshold_field: str | None = None
) -> bool:
    by_repetition: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
    for pair in pairs:
        by_repetition[int(pair["repetition"])].append(pair)
    if len(by_repetition) < 2:
        return False
    for repetition_pairs in by_repetition.values():
        baseline_success = _mean(
            [1.0 if _mapping(pair["baseline"]).get("success") else 0.0 for pair in repetition_pairs]
        )
        treatment_success = _mean(
            [1.0 if _mapping(pair["treatment"]).get("success") else 0.0 for pair in repetition_pairs]
        )
        if treatment_success > baseline_success:
            continue
        if threshold_field is None:
            return False
        baseline_value = _mean(
            [float(_mapping(pair["baseline"])[threshold_field]) for pair in repetition_pairs]
        )
        treatment_value = _mean(
            [float(_mapping(pair["treatment"])[threshold_field]) for pair in repetition_pairs]
        )
        if baseline_value <= 0 or treatment_value >= baseline_value:
            return False
    return True


def _classify_category(
    pairs: Sequence[Mapping[str, Any]],
    *,
    thresholds: Mapping[str, Any],
    measurement_scope: str,
) -> tuple[dict[str, Any], str]:
    baseline = [_mapping(pair["baseline"]) for pair in pairs]
    treatment = [_mapping(pair["treatment"]) for pair in pairs]
    valid_pairs = [pair for pair in pairs if pair.get("pair_valid") is True]
    valid_baseline = [_mapping(pair["baseline"]) for pair in valid_pairs]
    valid_treatment = [_mapping(pair["treatment"]) for pair in valid_pairs]
    baseline_success = _mean([1.0 if score.get("success") else 0.0 for score in valid_baseline])
    treatment_success = _mean([1.0 if score.get("success") else 0.0 for score in valid_treatment])
    baseline_false = _mean([1.0 if score.get("false_confidence") else 0.0 for score in valid_baseline])
    treatment_false = _mean([1.0 if score.get("false_confidence") else 0.0 for score in valid_treatment])
    success_delta = treatment_success - baseline_success
    false_delta = treatment_false - baseline_false
    efficiency = {
        field: _efficiency_metric(valid_baseline, valid_treatment, field)
        for field in (
            "duration_ms",
            "tool_call_count",
            "input_tokens",
            "output_tokens",
            "tool_bytes",
        )
    }
    efficiency = {
        "duration": efficiency["duration_ms"],
        "tool_calls": efficiency["tool_call_count"],
        "input_tokens": efficiency["input_tokens"],
        "output_tokens": efficiency["output_tokens"],
        "tool_bytes": efficiency["tool_bytes"],
    }

    if measurement_scope == "synthetic_contract_fixture":
        classification = "synthetic_only"
    elif len(valid_pairs) != len(pairs) or not valid_pairs:
        classification = "insufficient_evidence"
    elif (
        success_delta < -float(thresholds["maximum_class_success_regression"])
        or false_delta > float(thresholds["maximum_false_confidence_increase"])
    ):
        classification = "harmful"
    else:
        success_gain = success_delta >= float(thresholds["minimum_success_rate_gain"])
        qualifying_fields = [
            field
            for field, metric in efficiency.items()
            if metric["improvement_ratio"] is not None
            and metric["improvement_ratio"]
            >= float(thresholds["minimum_efficiency_improvement"])
        ]
        reproduced = bool(
            success_gain and _positive_direction_by_repetition(valid_pairs)
        ) or any(
            _positive_direction_by_repetition(valid_pairs, threshold_field={
                "duration": "duration_ms",
                "tool_calls": "tool_call_count",
                "input_tokens": "input_tokens",
                "output_tokens": "output_tokens",
                "tool_bytes": "tool_bytes",
            }[field])
            for field in qualifying_fields
        )
        classification = "useful" if reproduced else "neutral"

    category_result = {
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
    return category_result, classification


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
        raise AgentBenchmarkError("unsupported measurement_scope")
    request_by_id = {str(item["request_id"]): item for item in requests}
    receipt_by_id = {str(item.get("request_id")): item for item in receipts}
    cases = {str(item["id"]): item for item in _list(taskset.get("cases"))}
    grouped: dict[tuple[str, int], dict[str, tuple[Mapping[str, Any], Mapping[str, Any]]]] = defaultdict(dict)
    for request_id, request in request_by_id.items():
        receipt = receipt_by_id.get(request_id, {})
        key = (str(request["case_id"]), int(request["repetition"]))
        grouped[key][str(request["condition"])] = (request, receipt)

    case_results: list[dict[str, Any]] = []
    for (case_id, repetition), pair in sorted(grouped.items()):
        case = cases[case_id]
        scores: dict[str, dict[str, Any]] = {}
        pair_valid = True
        sessions: set[str] = set()
        workspaces: set[str] = set()
        for condition in CONDITIONS:
            request, receipt = pair.get(condition, ({}, {}))
            score = score_receipt(
                case,
                condition,
                request,
                receipt,
                transcript_root=transcript_root,
            )
            if not request:
                score["invalid_reasons"].append(f"missing {condition} request")
                score["valid"] = False
                score["success"] = False
            sessions.add(str(request.get("session_id", "")))
            workspaces.add(str(request.get("workspace_id", "")))
            scores[condition] = score
            pair_valid = pair_valid and bool(score["valid"])
        if len(sessions) != 2 or len(workspaces) != 2 or "" in sessions or "" in workspaces:
            pair_valid = False
            for score in scores.values():
                score["invalid_reasons"].append("paired conditions reused session/workspace identity")
                score["valid"] = False
                score["success"] = False
        case_results.append(
            {
                "case_id": case_id,
                "category": str(case["category"]),
                "repetition": repetition,
                "pair_valid": pair_valid,
                "baseline": scores["baseline"],
                "treatment": scores["treatment"],
            }
        )

    class_results: list[dict[str, Any]] = []
    classifications: dict[str, str] = {}
    thresholds = _mapping(taskset.get("thresholds"))
    for category in CATEGORIES:
        category_pairs = [item for item in case_results if item["category"] == category]
        result, classification = _classify_category(
            category_pairs,
            thresholds=thresholds,
            measurement_scope=measurement_scope,
        )
        result["category"] = category
        class_results.append(result)
        classifications[category] = classification

    useful = sorted(category for category, value in classifications.items() if value == "useful")
    harmful = sorted(category for category, value in classifications.items() if value == "harmful")
    if measurement_scope == "synthetic_contract_fixture":
        status = "synthetic_only"
        reason = "synthetic fixtures validate contracts but cannot establish agent usefulness"
    elif harmful:
        status = "harmful"
        reason = "at least one task class crossed a registered quality or safety regression threshold"
    elif "insufficient_evidence" in classifications.values():
        status = "insufficient_evidence"
        reason = "one or more task classes lack complete valid paired evidence"
    elif useful:
        status = "useful_class"
        reason = "at least one task class met a registered reproducible benefit threshold without regression"
    else:
        status = "neutral"
        reason = "no task class met a registered benefit or harm threshold"

    run_count = len(receipts)
    valid_run_count = sum(
        1
        for item in case_results
        for condition in CONDITIONS
        if _mapping(item[condition]).get("valid") is True
    )
    return {
        "kind": EVALUATION_KIND,
        "version": VERSION,
        "taskset_id": str(taskset["id"]),
        "taskset_sha256": sha256_json(taskset),
        "measurement_scope": measurement_scope,
        "run_count": run_count,
        "valid_run_count": valid_run_count,
        "invalid_run_count": max(run_count - valid_run_count, 0),
        "cases": case_results,
        "classes": class_results,
        "decision": {
            "status": status,
            "useful_classes": useful,
            "harmful_classes": harmful,
            "default_promoted": False,
            "reason": reason,
        },
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }


def execute_runner(
    command: Sequence[str],
    request: Mapping[str, Any],
    *,
    timeout_seconds: int,
    max_stdout_bytes: int = MAX_JSON_BYTES,
) -> dict[str, Any]:
    """Execute one explicit runner command with JSON stdin and bounded outputs."""

    if not command or any(not isinstance(item, str) or not item for item in command):
        raise AgentBenchmarkError("runner command must be a non-empty string array")
    if timeout_seconds < 1:
        raise AgentBenchmarkError("runner timeout must be positive")
    request_bytes = (canonical_json(request) + "\n").encode("utf-8")
    with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
        try:
            process = subprocess.Popen(
                list(command),
                stdin=subprocess.PIPE,
                stdout=stdout_file,
                stderr=stderr_file,
                shell=False,
                env=os.environ.copy(),
            )
            process.communicate(request_bytes, timeout=timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            process.kill()
            process.wait()
            raise AgentBenchmarkError("runner timed out") from exc
        except OSError as exc:
            raise AgentBenchmarkError("runner could not be started") from exc
        stdout_file.seek(0)
        raw = stdout_file.read(max_stdout_bytes + 1)
        stderr_file.seek(0)
        stderr = stderr_file.read(MAX_RUNNER_STDERR_BYTES + 1)
    if len(raw) > max_stdout_bytes:
        raise AgentBenchmarkError("runner stdout exceeds configured limit")
    if len(stderr) > MAX_RUNNER_STDERR_BYTES:
        raise AgentBenchmarkError("runner stderr exceeds configured limit")
    if process.returncode != 0:
        detail = stderr.decode("utf-8", errors="replace").strip()
        raise AgentBenchmarkError(
            f"runner exited with {process.returncode}: {detail[:1000]}"
        )
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AgentBenchmarkError("runner stdout is not one UTF-8 JSON object") from exc
    if not isinstance(value, dict):
        raise AgentBenchmarkError("runner stdout must be one JSON object")
    return value


__all__ = [
    "AgentBenchmarkError",
    "DOES_NOT_ESTABLISH",
    "build_run_requests",
    "canonical_json",
    "evaluate_paired_runs",
    "execute_runner",
    "is_repository_relative_path",
    "load_json",
    "require_valid_taskset",
    "score_receipt",
    "sha256_bytes",
    "sha256_json",
    "validate_receipt",
    "validate_taskset",
    "write_json_atomic",
]
