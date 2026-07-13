"""Shared deterministic helpers for the RepoBrief agent benchmark."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections import Counter
from collections.abc import Mapping
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
REPOBRIEF_TOOLS = {
    "ask_context",
    "repobrief_resource_read",
    "grounding_verify",
    "live_freshness",
}


class AgentBenchmarkError(ValueError):
    """A benchmark contract or evidence boundary was violated."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def list_value(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def mapping_value(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


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


def _validate_paths(values: Any, *, label: str) -> tuple[set[str], list[str]]:
    errors: list[str] = []
    paths: set[str] = set()
    for value in list_value(values):
        if not is_repository_relative_path(value):
            errors.append(f"{label} contains a non-canonical repository path: {value!r}")
            continue
        path = str(value).strip()
        if path in paths:
            errors.append(f"{label} contains duplicate path {path!r}")
        paths.add(path)
    return paths, errors


def _validate_expectation(
    expectation: Mapping[str, Any], *, case_id: str, condition: str
) -> list[str]:
    prefix = f"case {case_id} {condition}"
    required, errors = _validate_paths(
        expectation.get("required_paths"), label=f"{prefix}.required_paths"
    )
    allowed, allowed_errors = _validate_paths(
        expectation.get("allowed_paths"), label=f"{prefix}.allowed_paths"
    )
    forbidden, forbidden_errors = _validate_paths(
        expectation.get("forbidden_paths"), label=f"{prefix}.forbidden_paths"
    )
    errors.extend(allowed_errors)
    errors.extend(forbidden_errors)
    if not required.issubset(allowed):
        errors.append(f"{prefix}: required_paths must be a subset of allowed_paths")
    if allowed.intersection(forbidden):
        errors.append(f"{prefix}: allowed_paths and forbidden_paths overlap")
    errors.extend(_validate_citations(expectation, prefix=prefix))
    return errors


def _validate_citations(expectation: Mapping[str, Any], *, prefix: str) -> list[str]:
    errors: list[str] = []
    for citation in list_value(expectation.get("required_citations")):
        item = mapping_value(citation)
        path = item.get("path")
        start = item.get("start_line")
        end = item.get("end_line")
        if not is_repository_relative_path(path):
            errors.append(f"{prefix}: citation path is not repository-relative: {path!r}")
        if not isinstance(start, int) or not isinstance(end, int) or start < 1 or end < start:
            errors.append(f"{prefix}: citation range is invalid: {citation!r}")
    return errors


def _validate_taskset_identity(taskset: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if taskset.get("kind") != TASKSET_KIND or taskset.get("version") != VERSION:
        errors.append("taskset kind/version mismatch")
    if taskset.get("measurement_scope") != "frozen_paired_agent_ab":
        errors.append("taskset measurement_scope must be frozen_paired_agent_ab")
    if taskset.get("default_promoted") is not False:
        errors.append("taskset default_promoted must remain false")
    return errors


def _repository_ids(taskset: Mapping[str, Any]) -> tuple[set[str], list[str]]:
    repositories = list_value(taskset.get("repositories"))
    identifiers = [str(mapping_value(item).get("id", "")) for item in repositories]
    errors: list[str] = []
    if len(identifiers) < 3 or len(set(identifiers)) != len(identifiers):
        errors.append("taskset must contain at least three uniquely identified repositories")
    return set(identifiers), errors


def _validate_tool_policy(taskset: Mapping[str, Any]) -> list[str]:
    policy = mapping_value(taskset.get("tool_policy"))
    baseline = {str(item) for item in list_value(policy.get("baseline"))}
    treatment = {str(item) for item in list_value(policy.get("treatment"))}
    errors: list[str] = []
    if not baseline:
        errors.append("baseline tool policy must not be empty")
    if not baseline.issubset(treatment):
        errors.append("treatment tools must include every baseline tool")
    if not REPOBRIEF_TOOLS.issubset(treatment):
        errors.append("treatment tool policy misses required RepoBrief tools")
    if baseline.intersection(REPOBRIEF_TOOLS):
        errors.append("baseline tool policy must not expose RepoBrief tools")
    return errors


def _validate_case_shape(cases: list[Any]) -> list[str]:
    errors: list[str] = []
    if len(cases) != 24:
        errors.append(f"taskset must contain exactly 24 cases, got {len(cases)}")
    identifiers = [str(mapping_value(case).get("id", "")) for case in cases]
    if len(set(identifiers)) != len(identifiers):
        errors.append("taskset case ids must be unique")
    categories = Counter(str(mapping_value(case).get("category", "")) for case in cases)
    for category in CATEGORIES:
        if categories[category] != 8:
            errors.append(f"taskset category {category} must contain 8 cases")
    unknown = set(categories).difference(CATEGORIES)
    if unknown:
        errors.append(f"taskset contains unknown categories: {sorted(unknown)!r}")
    return errors


def _validate_case(
    case: Mapping[str, Any], *, repository_ids: set[str]
) -> tuple[list[str], bool]:
    case_id = str(case.get("id", ""))
    errors: list[str] = []
    if case.get("repository_id") not in repository_ids:
        errors.append(f"case {case_id} references an unknown repository")
    expectations = mapping_value(case.get("expectations"))
    negative = False
    for condition in CONDITIONS:
        expectation = mapping_value(expectations.get(condition))
        errors.extend(
            _validate_expectation(
                expectation, case_id=case_id, condition=condition
            )
        )
        negative = negative or expectation.get("outcome") in NON_ANSWER_OUTCOMES
    return errors, negative


def validate_taskset(taskset: Mapping[str, Any]) -> list[str]:
    """Return deterministic semantic errors not covered by the JSON schema."""

    errors = _validate_taskset_identity(taskset)
    repository_ids, repository_errors = _repository_ids(taskset)
    errors.extend(repository_errors)
    errors.extend(_validate_tool_policy(taskset))
    cases = list_value(taskset.get("cases"))
    errors.extend(_validate_case_shape(cases))
    negative_count = 0
    for raw_case in cases:
        case_errors, negative = _validate_case(
            mapping_value(raw_case), repository_ids=repository_ids
        )
        errors.extend(case_errors)
        negative_count += int(negative)
    if negative_count < 6:
        errors.append("taskset must contain at least six abstention/negative cases")
    return errors


def require_valid_taskset(taskset: Mapping[str, Any]) -> None:
    errors = validate_taskset(taskset)
    if errors:
        raise AgentBenchmarkError("; ".join(errors))


__all__ = [
    "AgentBenchmarkError",
    "CATEGORIES",
    "CONDITIONS",
    "DOES_NOT_ESTABLISH",
    "EVALUATION_KIND",
    "MAX_JSON_BYTES",
    "MAX_RUNNER_STDERR_BYTES",
    "NON_ANSWER_OUTCOMES",
    "RECEIPT_KIND",
    "REQUEST_KIND",
    "TASKSET_KIND",
    "VERSION",
    "canonical_json",
    "is_repository_relative_path",
    "list_value",
    "load_json",
    "mapping_value",
    "require_valid_taskset",
    "sha256_bytes",
    "sha256_json",
    "validate_taskset",
    "write_json_atomic",
]
