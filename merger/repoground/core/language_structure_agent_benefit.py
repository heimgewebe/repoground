"""Paired, revision-bound agent-benefit evidence for language_structure promotion."""

from __future__ import annotations

import argparse
import json
import math
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from merger.repoground.core.bounded_artifact_read import read_stable_regular_file_bytes

KIND = "repoground.language_structure_agent_benefit"
VERSION = "2.0"
PAIR_KIND = "repoground.language_structure_agent_benefit_pairs"
PAIR_VERSION = "1.0"
TREATMENT_VARIABLE = "language_structure_json"
_REVISION_RE = re.compile(r"^[a-f0-9]{40}(?:[a-f0-9]{24})?$")
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_MAX_INPUT_BYTES = 1024 * 1024
_MAX_CASES = 256
_MAX_EVIDENCE_REFS = 8
_MAX_REF_LENGTH = 512

_TOP_LEVEL_FIELDS = frozenset(
    {
        "kind",
        "version",
        "measurement_id",
        "source_revision",
        "goldset_sha256",
        "fallback_route",
        "candidate_route",
        "comparison",
        "treatment",
        "cases",
        "summary",
        "does_not_establish",
    }
)
_PAIR_FIELDS = frozenset(
    {
        "kind",
        "version",
        "measurement_id",
        "fallback_route",
        "candidate_route",
        "comparison",
        "treatment",
        "cases",
        "does_not_establish",
    }
)
_COMPARISON_FIELDS = frozenset(
    {
        "same_model",
        "same_prompt",
        "same_budget",
        "same_source_revision",
        "same_grader",
        "model_identity_sha256",
        "harness_identity_sha256",
        "environment_identity_sha256",
        "grader_identity_sha256",
    }
)
_TREATMENT_FIELDS = frozenset(
    {
        "variable",
        "fallback_excludes",
        "candidate_includes",
    }
)
_CASE_FIELDS = frozenset({"id", "task_sha256", "fallback", "candidate"})
_RESULT_FIELDS = frozenset({"success", "evidence_refs"})
_SUMMARY_FIELDS = frozenset(
    {
        "sample_count",
        "fallback_success_rate",
        "candidate_success_rate",
        "candidate_wins",
        "fallback_wins",
        "ties",
    }
)


class AgentBenefitEvidenceError(ValueError):
    """Raised when paired agent-benefit evidence is malformed or unbound."""


def _nonempty_text(value: Any, *, field: str, max_length: int = 256) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > max_length:
        raise AgentBenefitEvidenceError(f"{field} must be a bounded non-empty string")
    return value


def _validate_hash(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise AgentBenefitEvidenceError(f"{field} must be a lowercase SHA-256")
    return value


def _validate_revision(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or _REVISION_RE.fullmatch(value) is None:
        raise AgentBenefitEvidenceError(
            f"{field} must be a lowercase 40- or 64-character revision"
        )
    return value


def _validate_exact_fields(
    value: Mapping[str, Any], expected: frozenset[str], *, field: str
) -> None:
    observed = set(value)
    if observed != expected:
        missing = sorted(expected - observed)
        unexpected = sorted(observed - expected)
        raise AgentBenefitEvidenceError(
            f"{field} fields mismatch: missing={missing} unexpected={unexpected}"
        )


def _validate_comparison(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise AgentBenefitEvidenceError("comparison must be an object")
    _validate_exact_fields(value, _COMPARISON_FIELDS, field="comparison")
    for field in (
        "same_model",
        "same_prompt",
        "same_budget",
        "same_source_revision",
        "same_grader",
    ):
        if value.get(field) is not True:
            raise AgentBenefitEvidenceError(
                f"comparison.{field} must be true for promotion evidence"
            )
    normalized = dict(value)
    for field in (
        "model_identity_sha256",
        "harness_identity_sha256",
        "environment_identity_sha256",
        "grader_identity_sha256",
    ):
        normalized[field] = _validate_hash(
            value.get(field), field=f"comparison.{field}"
        )
    return normalized


def _validate_treatment(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise AgentBenefitEvidenceError("treatment must be an object")
    _validate_exact_fields(value, _TREATMENT_FIELDS, field="treatment")
    if value.get("variable") != TREATMENT_VARIABLE:
        raise AgentBenefitEvidenceError(
            f"treatment.variable must equal {TREATMENT_VARIABLE!r}"
        )
    if value.get("fallback_excludes") is not True:
        raise AgentBenefitEvidenceError("treatment.fallback_excludes must be true")
    if value.get("candidate_includes") is not True:
        raise AgentBenefitEvidenceError("treatment.candidate_includes must be true")
    return dict(value)


def _validate_evidence_refs(value: Any, *, field: str) -> list[str]:
    if not isinstance(value, list) or not 1 <= len(value) <= _MAX_EVIDENCE_REFS:
        raise AgentBenefitEvidenceError(
            f"{field} must contain 1..{_MAX_EVIDENCE_REFS} evidence refs"
        )
    refs: list[str] = []
    for index, raw in enumerate(value):
        ref = _nonempty_text(
            raw,
            field=f"{field}[{index}]",
            max_length=_MAX_REF_LENGTH,
        )
        refs.append(ref)
    if len(set(refs)) != len(refs):
        raise AgentBenefitEvidenceError(f"{field} must not contain duplicate refs")
    return refs


def _validate_result(value: Any, *, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise AgentBenefitEvidenceError(f"{field} must be an object")
    _validate_exact_fields(value, _RESULT_FIELDS, field=field)
    success = value.get("success")
    if not isinstance(success, bool):
        raise AgentBenefitEvidenceError(f"{field}.success must be boolean")
    return {
        "success": success,
        "evidence_refs": _validate_evidence_refs(
            value.get("evidence_refs"), field=f"{field}.evidence_refs"
        ),
    }


def _validate_cases(
    value: Any, *, expected_case_ids: Sequence[str]
) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not 1 <= len(value) <= _MAX_CASES:
        raise AgentBenefitEvidenceError(f"cases must contain 1..{_MAX_CASES} items")
    expected = list(expected_case_ids)
    if len(expected) != len(set(expected)) or any(
        not isinstance(case_id, str) or not case_id for case_id in expected
    ):
        raise AgentBenefitEvidenceError("benchmark case ids are invalid or duplicated")
    if len(value) != len(expected):
        raise AgentBenefitEvidenceError("benefit case count does not match benchmark")
    normalized: list[dict[str, Any]] = []
    observed_ids: list[str] = []
    for index, raw in enumerate(value):
        if not isinstance(raw, Mapping):
            raise AgentBenefitEvidenceError(f"cases[{index}] must be an object")
        _validate_exact_fields(raw, _CASE_FIELDS, field=f"cases[{index}]")
        case_id = _nonempty_text(raw.get("id"), field=f"cases[{index}].id")
        observed_ids.append(case_id)
        normalized.append(
            {
                "id": case_id,
                "task_sha256": _validate_hash(
                    raw.get("task_sha256"), field=f"cases[{index}].task_sha256"
                ),
                "fallback": _validate_result(
                    raw.get("fallback"), field=f"cases[{index}].fallback"
                ),
                "candidate": _validate_result(
                    raw.get("candidate"), field=f"cases[{index}].candidate"
                ),
            }
        )
    if len(observed_ids) != len(set(observed_ids)):
        raise AgentBenefitEvidenceError("benefit case ids must be unique")
    task_hashes = [item["task_sha256"] for item in normalized]
    if len(task_hashes) != len(set(task_hashes)):
        raise AgentBenefitEvidenceError("benefit task_sha256 values must be unique")
    if set(observed_ids) != set(expected):
        raise AgentBenefitEvidenceError("benefit case ids do not match benchmark")
    by_id = {item["id"]: item for item in normalized}
    return [by_id[case_id] for case_id in expected]


def _summary(cases: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    sample_count = len(cases)
    fallback_successes = sum(bool(case["fallback"]["success"]) for case in cases)
    candidate_successes = sum(bool(case["candidate"]["success"]) for case in cases)
    candidate_wins = sum(
        (not bool(case["fallback"]["success"])) and bool(case["candidate"]["success"])
        for case in cases
    )
    fallback_wins = sum(
        bool(case["fallback"]["success"]) and (not bool(case["candidate"]["success"]))
        for case in cases
    )
    ties = sample_count - candidate_wins - fallback_wins
    return {
        "sample_count": sample_count,
        "fallback_success_rate": round(fallback_successes / sample_count, 6),
        "candidate_success_rate": round(candidate_successes / sample_count, 6),
        "candidate_wins": candidate_wins,
        "fallback_wins": fallback_wins,
        "ties": ties,
    }


def _validate_summary(value: Any, *, expected: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise AgentBenefitEvidenceError("summary must be an object")
    _validate_exact_fields(value, _SUMMARY_FIELDS, field="summary")
    for field in ("sample_count", "candidate_wins", "fallback_wins", "ties"):
        raw = value.get(field)
        if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
            raise AgentBenefitEvidenceError(
                f"summary.{field} must be a non-negative integer"
            )
    for field in ("fallback_success_rate", "candidate_success_rate"):
        raw = value.get(field)
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise AgentBenefitEvidenceError(f"summary.{field} must be a finite rate")
        number = float(raw)
        if not math.isfinite(number) or not 0.0 <= number <= 1.0:
            raise AgentBenefitEvidenceError(f"summary.{field} must be a finite rate")
    if dict(value) != dict(expected):
        raise AgentBenefitEvidenceError("summary does not match paired case outcomes")
    return dict(expected)


def _validate_does_not_establish(value: Any) -> list[str]:
    if not isinstance(value, list) or not value:
        raise AgentBenefitEvidenceError("does_not_establish must be a non-empty list")
    result = [
        _nonempty_text(item, field="does_not_establish[]", max_length=256)
        for item in value
    ]
    if len(result) != len(set(result)):
        raise AgentBenefitEvidenceError("does_not_establish must be unique")
    required = {"default_activation", "causal_generalization_beyond_bound_cases"}
    if not required <= set(result):
        raise AgentBenefitEvidenceError(
            "does_not_establish must retain default-activation and generalization limits"
        )
    return result


def build_language_structure_agent_benefit(
    pair_document: Mapping[str, Any],
    *,
    source_revision: str,
    goldset_sha256: str,
    expected_case_ids: Sequence[str],
) -> dict[str, Any]:
    """Bind externally executed paired outcomes to one exact benchmark identity."""
    _validate_exact_fields(pair_document, _PAIR_FIELDS, field="pair document")
    if (
        pair_document.get("kind") != PAIR_KIND
        or pair_document.get("version") != PAIR_VERSION
    ):
        raise AgentBenefitEvidenceError("pair document kind/version is unsupported")
    source_revision = _validate_revision(source_revision, field="source_revision")
    goldset_sha256 = _validate_hash(goldset_sha256, field="goldset_sha256")
    measurement_id = _nonempty_text(
        pair_document.get("measurement_id"), field="measurement_id"
    )
    fallback_route = _nonempty_text(
        pair_document.get("fallback_route"), field="fallback_route"
    )
    candidate_route = _nonempty_text(
        pair_document.get("candidate_route"), field="candidate_route"
    )
    if fallback_route == candidate_route:
        raise AgentBenefitEvidenceError(
            "fallback_route and candidate_route must differ"
        )
    comparison = _validate_comparison(pair_document.get("comparison"))
    treatment = _validate_treatment(pair_document.get("treatment"))
    cases = _validate_cases(
        pair_document.get("cases"), expected_case_ids=expected_case_ids
    )
    summary = _summary(cases)
    return {
        "kind": KIND,
        "version": VERSION,
        "measurement_id": measurement_id,
        "source_revision": source_revision,
        "goldset_sha256": goldset_sha256,
        "fallback_route": fallback_route,
        "candidate_route": candidate_route,
        "comparison": comparison,
        "treatment": treatment,
        "cases": cases,
        "summary": summary,
        "does_not_establish": _validate_does_not_establish(
            pair_document.get("does_not_establish")
        ),
    }


def validate_language_structure_agent_benefit(
    document: Mapping[str, Any],
    *,
    source_revision: str,
    goldset_sha256: str,
    expected_case_ids: Sequence[str],
) -> dict[str, Any]:
    """Validate a promotion input and recompute all aggregate benefit rates."""
    if not isinstance(document, Mapping):
        raise AgentBenefitEvidenceError("agent benefit must be an object")
    _validate_exact_fields(document, _TOP_LEVEL_FIELDS, field="agent benefit")
    if document.get("kind") != KIND or document.get("version") != VERSION:
        raise AgentBenefitEvidenceError("agent benefit kind/version is unsupported")
    if document.get("source_revision") != source_revision:
        raise AgentBenefitEvidenceError("agent benefit source_revision mismatch")
    if document.get("goldset_sha256") != goldset_sha256:
        raise AgentBenefitEvidenceError("agent benefit goldset_sha256 mismatch")
    _validate_revision(document.get("source_revision"), field="source_revision")
    _validate_hash(document.get("goldset_sha256"), field="goldset_sha256")
    _nonempty_text(document.get("measurement_id"), field="measurement_id")
    fallback_route = _nonempty_text(
        document.get("fallback_route"), field="fallback_route"
    )
    candidate_route = _nonempty_text(
        document.get("candidate_route"), field="candidate_route"
    )
    if fallback_route == candidate_route:
        raise AgentBenefitEvidenceError(
            "fallback_route and candidate_route must differ"
        )
    _validate_comparison(document.get("comparison"))
    _validate_treatment(document.get("treatment"))
    cases = _validate_cases(document.get("cases"), expected_case_ids=expected_case_ids)
    derived = _summary(cases)
    _validate_summary(document.get("summary"), expected=derived)
    _validate_does_not_establish(document.get("does_not_establish"))
    return derived


def _load_json(path: str | Path, *, label: str) -> Mapping[str, Any]:
    raw, _identity, failure, detail = read_stable_regular_file_bytes(
        Path(path), max_bytes=_MAX_INPUT_BYTES
    )
    if failure is not None or raw is None:
        suffix = f": {detail}" if detail else ""
        raise AgentBenefitEvidenceError(
            f"{label} read failed: {failure or 'unreadable'}{suffix}"
        )
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AgentBenefitEvidenceError(f"{label} is not valid UTF-8 JSON") from exc
    if not isinstance(value, Mapping):
        raise AgentBenefitEvidenceError(f"{label} must be a JSON object")
    return value


def _benchmark_binding(document: Mapping[str, Any]) -> tuple[str, str, list[str]]:
    if (
        document.get("kind") != "repoground.language_structure_benchmark"
        or document.get("version") != "1.0"
    ):
        raise AgentBenefitEvidenceError("benchmark kind/version is unsupported")
    source_revision = _validate_revision(
        document.get("source_revision"), field="benchmark.source_revision"
    )
    goldset_sha256 = _validate_hash(
        document.get("goldset_sha256"), field="benchmark.goldset_sha256"
    )
    case_results = document.get("case_results")
    if not isinstance(case_results, list) or not case_results:
        raise AgentBenefitEvidenceError("benchmark.case_results must be non-empty")
    case_ids: list[str] = []
    for index, case in enumerate(case_results):
        if not isinstance(case, Mapping):
            raise AgentBenefitEvidenceError(
                f"benchmark.case_results[{index}] must be an object"
            )
        case_ids.append(
            _nonempty_text(case.get("id"), field=f"benchmark.case_results[{index}].id")
        )
    if len(case_ids) != len(set(case_ids)):
        raise AgentBenefitEvidenceError("benchmark case ids must be unique")
    return source_revision, goldset_sha256, case_ids


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build paired language_structure agent-benefit evidence from external run receipts"
    )
    parser.add_argument("--benchmark", required=True)
    parser.add_argument("--pairs", required=True)
    args = parser.parse_args(argv)
    benchmark = _load_json(args.benchmark, label="benchmark")
    pairs = _load_json(args.pairs, label="pairs")
    source_revision, goldset_sha256, case_ids = _benchmark_binding(benchmark)
    document = build_language_structure_agent_benefit(
        pairs,
        source_revision=source_revision,
        goldset_sha256=goldset_sha256,
        expected_case_ids=case_ids,
    )
    print(json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
