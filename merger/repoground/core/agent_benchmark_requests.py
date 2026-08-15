"""Validate agent benchmark requests against the frozen taskset."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from merger.repoground.core.agent_benchmark_common import (
    AgentBenchmarkError,
    COMPONENT_DELTA_MODE,
    CONDITIONS,
    REQUEST_KIND,
    VERSION,
    comparison_contract,
    comparison_mode,
    list_value,
    mapping_value,
    sha256_json,
)
from merger.repoground.core.agent_benchmark_policy import BENCHMARK_REPETITIONS
from merger.repoground.core.agent_benchmark_components import verify_component_manifest_delta


def _repository_map(taskset: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        str(item.get("id")): item
        for item in list_value(taskset.get("repositories"))
        if isinstance(item, Mapping)
    }


def _case_map(taskset: Mapping[str, Any]) -> dict[str, tuple[int, Mapping[str, Any]]]:
    return {
        str(item.get("id")): (index, item)
        for index, item in enumerate(list_value(taskset.get("cases")))
        if isinstance(item, Mapping)
    }


def expected_condition_order(case_index: int, repetition: int) -> tuple[str, str]:
    """Return the deterministic order registered by the v1 planner."""

    if (case_index + repetition - 1) % 2 == 0:
        return "baseline", "treatment"
    return "treatment", "baseline"


def expected_request_identity(
    taskset_id: str,
    case_id: str,
    repetition: int,
    condition: str,
) -> dict[str, str]:
    pair_id = f"{taskset_id}:{case_id}:r{repetition}"
    request_id = f"{pair_id}:{condition}"
    return {
        "pair_id": pair_id,
        "request_id": request_id,
        "session_id": f"session:{request_id}",
        "workspace_id": f"workspace:{request_id}",
    }


def _validate_identity(
    taskset: Mapping[str, Any],
    request: Mapping[str, Any],
    *,
    case_index: int,
    case: Mapping[str, Any],
) -> list[str]:
    errors: list[str] = []
    condition = request.get("condition")
    repetition = request.get("repetition")
    if condition not in CONDITIONS:
        return ["request condition is invalid"]
    if not isinstance(repetition, int) or not 1 <= repetition <= BENCHMARK_REPETITIONS:
        return ["request repetition is outside the frozen v1 plan"]
    expected = expected_request_identity(
        str(taskset.get("id")),
        str(case.get("id")),
        repetition,
        str(condition),
    )
    for field, value in expected.items():
        if request.get(field) != value:
            errors.append(f"request {field} does not match frozen plan")
    order = expected_condition_order(case_index, repetition).index(str(condition)) + 1
    if request.get("order") != order:
        errors.append("request order does not match balanced plan")
    return errors


def _validate_repository(
    repository: Mapping[str, Any], request: Mapping[str, Any]
) -> list[str]:
    actual = mapping_value(request.get("repository"))
    errors: list[str] = []
    for field in ("id", "repository", "commit"):
        if actual.get(field) != repository.get(field):
            errors.append(f"request repository.{field} does not match taskset")
    return errors


def _validate_policy(
    taskset: Mapping[str, Any],
    request: Mapping[str, Any],
    *,
    condition: str,
) -> list[str]:
    errors: list[str] = []
    expected_tools = list(mapping_value(taskset.get("tool_policy")).get(condition, []))
    if request.get("allowed_tools") != expected_tools:
        errors.append("request allowed_tools does not match taskset policy")
    if mapping_value(request.get("budgets")) != mapping_value(taskset.get("budgets")):
        errors.append("request budgets do not match taskset")
    isolation = mapping_value(request.get("isolation"))
    if isolation != {
        "fresh_session": True,
        "fresh_workspace": True,
        "cross_condition_reuse_allowed": False,
    }:
        errors.append("request isolation contract is invalid")
    repobrief = request.get("repobrief")
    if comparison_mode(taskset) == COMPONENT_DELTA_MODE:
        if not isinstance(repobrief, Mapping):
            errors.append("component_delta request requires RepoGround binding")
        errors.extend(_validate_component_delta(taskset, request, condition=condition))
    else:
        if condition == "baseline" and repobrief is not None:
            errors.append("baseline request must not contain RepoGround binding")
        if condition == "treatment" and not isinstance(repobrief, Mapping):
            errors.append("treatment request requires RepoGround binding")
        if "component_delta" in request:
            errors.append("legacy request must not contain component_delta binding")
    return errors


def _validate_component_delta(
    taskset: Mapping[str, Any], request: Mapping[str, Any], *, condition: str
) -> list[str]:
    comparison = comparison_contract(taskset)
    binding = mapping_value(request.get("component_delta"))
    errors: list[str] = []
    if binding.get("component") != comparison.get("component"):
        errors.append("component_delta component does not match taskset")
    if binding.get("source_revision") != comparison.get("source_revision"):
        errors.append("component_delta source_revision does not match taskset")
    artifact = binding.get("artifact")
    artifact_sha256 = binding.get("artifact_sha256")
    if condition == "baseline":
        if artifact is not None or artifact_sha256 is not None:
            errors.append("component_delta baseline must not bind an artifact")
    elif (
        not isinstance(artifact, str)
        or not artifact
        or not isinstance(artifact_sha256, str)
        or len(artifact_sha256) != 64
        or any(ch not in "0123456789abcdef" for ch in artifact_sha256)
    ):
        errors.append("component_delta treatment artifact binding is invalid")
    return errors


def validate_request(
    taskset: Mapping[str, Any], request: Mapping[str, Any]
) -> list[str]:
    """Validate one request against the immutable taskset and v1 plan."""

    errors: list[str] = []
    if request.get("kind") != REQUEST_KIND or request.get("version") != VERSION:
        errors.append("request kind/version mismatch")
    if request.get("taskset_id") != taskset.get("id"):
        errors.append("request taskset_id does not match taskset")
    if request.get("taskset_sha256") != sha256_json(taskset):
        errors.append("request taskset_sha256 does not match taskset")
    cases = _case_map(taskset)
    case_entry = cases.get(str(request.get("case_id", "")))
    if case_entry is None:
        errors.append("request references unknown case")
        return errors
    case_index, case = case_entry
    repositories = _repository_map(taskset)
    repository = repositories.get(str(case.get("repository_id", "")))
    if repository is None:
        errors.append("taskset case references unknown repository")
        return errors
    errors.extend(
        _validate_identity(taskset, request, case_index=case_index, case=case)
    )
    errors.extend(_validate_repository(repository, request))
    if request.get("prompt") != case.get("prompt"):
        errors.append("request prompt does not match frozen case")
    condition = request.get("condition")
    if condition in CONDITIONS:
        errors.extend(
            _validate_policy(taskset, request, condition=str(condition))
        )
    return errors


def expected_pair_keys(taskset: Mapping[str, Any]) -> list[tuple[str, int]]:
    """Return every case/repetition pair required by benchmark v1."""

    return [
        (str(case.get("id")), repetition)
        for repetition in range(1, BENCHMARK_REPETITIONS + 1)
        for case in list_value(taskset.get("cases"))
        if isinstance(case, Mapping)
    ]


def _component_delta_pair_errors(
    baseline: Mapping[str, Any], treatment: Mapping[str, Any]
) -> list[str]:
    errors: list[str] = []
    for field in ("repository", "prompt", "allowed_tools", "budgets", "isolation"):
        if baseline.get(field) != treatment.get(field):
            errors.append(f"component_delta paired requests disagree on {field}")
    baseline_repobrief = mapping_value(baseline.get("repobrief"))
    treatment_repobrief = mapping_value(treatment.get("repobrief"))
    if baseline_repobrief.get("mcp_command") != treatment_repobrief.get("mcp_command"):
        errors.append("component_delta paired requests disagree on RepoGround MCP command")
    baseline_delta = mapping_value(baseline.get("component_delta"))
    treatment_delta = mapping_value(treatment.get("component_delta"))
    for field in ("component", "source_revision"):
        if baseline_delta.get(field) != treatment_delta.get(field):
            errors.append(f"component_delta paired requests disagree on {field}")
    if baseline_delta.get("artifact") is not None or baseline_delta.get("artifact_sha256") is not None:
        errors.append("component_delta baseline unexpectedly contains artifact evidence")
    artifact = treatment_delta.get("artifact")
    artifact_sha256 = treatment_delta.get("artifact_sha256")
    if artifact is None or artifact_sha256 is None:
        errors.append("component_delta treatment is missing artifact evidence")
        return errors
    repository = mapping_value(treatment.get("repository"))
    repository_id = repository.get("id")
    repository_commit = repository.get("commit")
    component = treatment_delta.get("component")
    if not all(
        isinstance(value, str) and value
        for value in (repository_id, repository_commit, component, artifact, artifact_sha256)
    ):
        errors.append("component_delta manifest isolation binding is incomplete")
        return errors
    try:
        verify_component_manifest_delta(
            baseline_repobrief,
            treatment_repobrief,
            repository_id=str(repository_id),
            repository_commit=str(repository_commit),
            source_revision=str(treatment_delta.get("source_revision", "")),
            component=str(component),
            artifact_path=str(artifact),
            expected_sha256=str(artifact_sha256),
        )
    except AgentBenchmarkError as exc:
        errors.append(f"component_delta manifest isolation invalid: {exc}")
    return errors


def pair_request_errors(
    taskset: Mapping[str, Any],
    requests: Sequence[Mapping[str, Any]],
) -> list[str]:
    """Validate cross-condition provider and pairing invariants."""

    if len(requests) != 2:
        return [f"expected two condition requests, got {len(requests)}"]
    errors: list[str] = []
    first, second = requests
    for field in ("pair_id", "case_id", "repetition", "taskset_id", "taskset_sha256"):
        if first.get(field) != second.get(field):
            errors.append(f"paired requests disagree on {field}")
    if mapping_value(first.get("runner")) != mapping_value(second.get("runner")):
        errors.append("paired requests use different runner configuration")
    if {first.get("condition"), second.get("condition")} != set(CONDITIONS):
        errors.append("paired requests do not contain baseline and treatment")
    if comparison_mode(taskset) == COMPONENT_DELTA_MODE:
        baseline = first if first.get("condition") == "baseline" else second
        treatment = second if baseline is first else first
        errors.extend(_component_delta_pair_errors(baseline, treatment))
    return errors


__all__ = [
    "expected_condition_order",
    "expected_pair_keys",
    "expected_request_identity",
    "pair_request_errors",
    "validate_request",
]
