from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import jsonschema
import pytest

from merger.repoground.core.language_structure_agent_benefit import (
    AgentBenefitEvidenceError,
    build_language_structure_agent_benefit,
    main,
    receipt_sha256,
    validate_language_structure_agent_benefit,
)

ROOT = Path(__file__).resolve().parents[3]
CONTRACTS = ROOT / "merger" / "repoground" / "contracts"
REVISION = "a" * 40
GOLDSET_SHA256 = "b" * 64
CASE_IDS = ["bash-positive", "rust-positive", "bash-null", "rust-null"]
FALLBACK_ROUTE = "text_fallback"
CANDIDATE_ROUTE = "language_structure_v1"
TREATMENT_SHA256 = "9" * 64


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _comparison() -> dict:
    return {
        "same_model": True,
        "same_prompt": True,
        "same_budget": True,
        "same_source_revision": True,
        "same_grader": True,
        "model_identity_sha256": "1" * 64,
        "harness_identity_sha256": "2" * 64,
        "environment_identity_sha256": "3" * 64,
        "grader_identity_sha256": "4" * 64,
        "grader_rubric_sha256": "5" * 64,
    }


def _runner_receipt(
    *,
    case_id: str,
    task_sha256: str,
    route: str,
    treatment_artifact_sha256: str | None,
) -> dict:
    comparison = _comparison()
    return {
        "kind": "repoground.language_structure_agent_run_receipt",
        "version": "1.0",
        "source_revision": REVISION,
        "goldset_sha256": GOLDSET_SHA256,
        "task_sha256": task_sha256,
        "route": route,
        "model_identity_sha256": comparison["model_identity_sha256"],
        "harness_identity_sha256": comparison["harness_identity_sha256"],
        "environment_identity_sha256": comparison["environment_identity_sha256"],
        "prompt_sha256": _hash(f"prompt:{case_id}"),
        "budget_sha256": "6" * 64,
        "control_context_sha256": _hash(f"control-context:{case_id}"),
        "treatment_artifact_sha256": treatment_artifact_sha256,
        "output_sha256": _hash(f"output:{case_id}:{route}"),
        "completed": True,
    }


def _grader_receipt(*, runner: dict, verdict: str) -> dict:
    comparison = _comparison()
    return {
        "kind": "repoground.language_structure_agent_grader_receipt",
        "version": "1.0",
        "source_revision": runner["source_revision"],
        "goldset_sha256": runner["goldset_sha256"],
        "task_sha256": runner["task_sha256"],
        "route": runner["route"],
        "runner_receipt_sha256": receipt_sha256(runner),
        "output_sha256": runner["output_sha256"],
        "grader_identity_sha256": comparison["grader_identity_sha256"],
        "grader_rubric_sha256": comparison["grader_rubric_sha256"],
        "verdict": verdict,
    }


def _route_result(
    *,
    case_id: str,
    task_sha256: str,
    route: str,
    treatment_artifact_sha256: str | None,
    verdict: str,
) -> dict:
    runner = _runner_receipt(
        case_id=case_id,
        task_sha256=task_sha256,
        route=route,
        treatment_artifact_sha256=treatment_artifact_sha256,
    )
    return {
        "runner_receipt": runner,
        "grader_receipt": _grader_receipt(runner=runner, verdict=verdict),
    }


def _rebind_grader(route_result: dict) -> None:
    runner = route_result["runner_receipt"]
    grader = route_result["grader_receipt"]
    grader["runner_receipt_sha256"] = receipt_sha256(runner)
    grader["output_sha256"] = runner["output_sha256"]


def _mutate_candidate_runner(pairs: dict, field: str, value: object) -> None:
    route_result = pairs["cases"][0]["candidate"]
    route_result["runner_receipt"][field] = value
    _rebind_grader(route_result)


def _duplicate_second_task_hash(pairs: dict) -> None:
    duplicate = pairs["cases"][0]["task_sha256"]
    case = pairs["cases"][1]
    case["task_sha256"] = duplicate
    for route in ("fallback", "candidate"):
        result = case[route]
        result["runner_receipt"]["task_sha256"] = duplicate
        result["grader_receipt"]["task_sha256"] = duplicate
        _rebind_grader(result)


def _pairs() -> dict:
    cases = []
    for index, case_id in enumerate(CASE_IDS):
        task_sha256 = _hash(f"task:{case_id}")
        cases.append(
            {
                "id": case_id,
                "task_sha256": task_sha256,
                "fallback": _route_result(
                    case_id=case_id,
                    task_sha256=task_sha256,
                    route=FALLBACK_ROUTE,
                    treatment_artifact_sha256=None,
                    verdict="fail" if index == 0 else "pass",
                ),
                "candidate": _route_result(
                    case_id=case_id,
                    task_sha256=task_sha256,
                    route=CANDIDATE_ROUTE,
                    treatment_artifact_sha256=TREATMENT_SHA256,
                    verdict="pass",
                ),
            }
        )
    return {
        "kind": "repoground.language_structure_agent_benefit_pairs",
        "version": "1.0",
        "measurement_id": "paired-benefit-unit",
        "source_revision": REVISION,
        "goldset_sha256": GOLDSET_SHA256,
        "fallback_route": FALLBACK_ROUTE,
        "candidate_route": CANDIDATE_ROUTE,
        "comparison": _comparison(),
        "treatment": {
            "variable": "language_structure_json",
            "fallback_excludes": True,
            "candidate_includes": True,
            "candidate_artifact_sha256": TREATMENT_SHA256,
        },
        "cases": cases,
        "does_not_establish": [
            "default_activation",
            "causal_generalization_beyond_bound_cases",
            "receipt_hashes_do_not_attest_runner_or_grader_honesty",
        ],
    }


def _benefit() -> dict:
    return build_language_structure_agent_benefit(
        _pairs(),
        source_revision=REVISION,
        goldset_sha256=GOLDSET_SHA256,
        expected_case_ids=CASE_IDS,
    )


def test_builder_derives_receipt_bound_summary_and_schema_validates() -> None:
    benefit = _benefit()

    assert benefit["summary"] == {
        "sample_count": 4,
        "fallback_success_rate": 0.75,
        "candidate_success_rate": 1.0,
        "candidate_wins": 1,
        "fallback_wins": 0,
        "ties": 3,
    }
    assert benefit["cases"][0]["fallback"]["success"] is False
    assert benefit["cases"][0]["candidate"]["success"] is True
    assert (
        validate_language_structure_agent_benefit(
            benefit,
            source_revision=REVISION,
            goldset_sha256=GOLDSET_SHA256,
            expected_case_ids=CASE_IDS,
        )
        == benefit["summary"]
    )

    schema = json.loads(
        (CONTRACTS / "language-structure-agent-benefit.v2.schema.json").read_text(
            encoding="utf-8"
        )
    )
    jsonschema.validate(benefit, schema)


def test_builder_normalizes_case_order_to_benchmark_order() -> None:
    pairs = _pairs()
    pairs["cases"] = list(reversed(pairs["cases"]))

    benefit = build_language_structure_agent_benefit(
        pairs,
        source_revision=REVISION,
        goldset_sha256=GOLDSET_SHA256,
        expected_case_ids=CASE_IDS,
    )

    assert [case["id"] for case in benefit["cases"]] == CASE_IDS


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("source_revision", "c" * 40, "pair source_revision does not match benchmark"),
        ("goldset_sha256", "d" * 64, "pair goldset_sha256 does not match benchmark"),
    ],
)
def test_builder_rejects_pair_receipts_from_another_benchmark(
    field: str, value: str, message: str
) -> None:
    pairs = _pairs()
    pairs[field] = value

    with pytest.raises(AgentBenefitEvidenceError, match=message):
        build_language_structure_agent_benefit(
            pairs,
            source_revision=REVISION,
            goldset_sha256=GOLDSET_SHA256,
            expected_case_ids=CASE_IDS,
        )


def test_builder_rejects_runner_receipt_tamper_after_grading() -> None:
    pairs = _pairs()
    pairs["cases"][0]["candidate"]["runner_receipt"]["output_sha256"] = "f" * 64

    with pytest.raises(AgentBenefitEvidenceError, match="runner_receipt_sha256"):
        build_language_structure_agent_benefit(
            pairs,
            source_revision=REVISION,
            goldset_sha256=GOLDSET_SHA256,
            expected_case_ids=CASE_IDS,
        )


def test_builder_rejects_grader_output_not_bound_to_runner() -> None:
    pairs = _pairs()
    pairs["cases"][0]["candidate"]["grader_receipt"]["output_sha256"] = "f" * 64

    with pytest.raises(AgentBenefitEvidenceError, match="does not match runner output"):
        build_language_structure_agent_benefit(
            pairs,
            source_revision=REVISION,
            goldset_sha256=GOLDSET_SHA256,
            expected_case_ids=CASE_IDS,
        )


def test_builder_rejects_caller_asserted_success_in_pair_receipt() -> None:
    pairs = _pairs()
    pairs["cases"][0]["candidate"]["success"] = True

    with pytest.raises(AgentBenefitEvidenceError, match="fields mismatch"):
        build_language_structure_agent_benefit(
            pairs,
            source_revision=REVISION,
            goldset_sha256=GOLDSET_SHA256,
            expected_case_ids=CASE_IDS,
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda value: value["cases"].pop(),
            "benefit case count does not match benchmark",
        ),
        (
            lambda value: value["cases"].__setitem__(
                1, copy.deepcopy(value["cases"][0])
            ),
            "benefit case ids must be unique",
        ),
        (
            _duplicate_second_task_hash,
            "benefit task_sha256 values must be unique",
        ),
        (
            lambda value: _mutate_candidate_runner(value, "prompt_sha256", "e" * 64),
            "fallback/candidate prompt_sha256 mismatch",
        ),
        (
            lambda value: _mutate_candidate_runner(
                value, "control_context_sha256", "e" * 64
            ),
            "fallback/candidate control_context_sha256 mismatch",
        ),
        (
            lambda value: _mutate_candidate_runner(
                value, "treatment_artifact_sha256", "e" * 64
            ),
            "does not match treatment",
        ),
        (
            lambda value: _mutate_candidate_runner(
                value, "model_identity_sha256", "e" * 64
            ),
            "does not match comparison",
        ),
    ],
)
def test_builder_rejects_unpaired_or_unfair_receipts(mutation, message: str) -> None:
    pairs = _pairs()
    mutation(pairs)

    with pytest.raises(AgentBenefitEvidenceError, match=message):
        build_language_structure_agent_benefit(
            pairs,
            source_revision=REVISION,
            goldset_sha256=GOLDSET_SHA256,
            expected_case_ids=CASE_IDS,
        )


def test_validator_rejects_derived_summary_tamper() -> None:
    benefit = _benefit()
    benefit["summary"]["candidate_success_rate"] = 0.5

    with pytest.raises(
        AgentBenefitEvidenceError, match="summary does not match paired case outcomes"
    ):
        validate_language_structure_agent_benefit(
            benefit,
            source_revision=REVISION,
            goldset_sha256=GOLDSET_SHA256,
            expected_case_ids=CASE_IDS,
        )


def test_validator_rejects_success_not_derived_from_grader() -> None:
    benefit = _benefit()
    benefit["cases"][0]["fallback"]["success"] = True

    with pytest.raises(AgentBenefitEvidenceError, match="embedded grader verdict"):
        validate_language_structure_agent_benefit(
            benefit,
            source_revision=REVISION,
            goldset_sha256=GOLDSET_SHA256,
            expected_case_ids=CASE_IDS,
        )


def test_validator_rejects_legacy_aggregate_only_v1() -> None:
    legacy = {
        "kind": "repoground.language_structure_agent_benefit",
        "version": "1.0",
        "source_revision": REVISION,
        "goldset_sha256": GOLDSET_SHA256,
        "sample_count": len(CASE_IDS),
        "fallback_route": FALLBACK_ROUTE,
        "candidate_route": CANDIDATE_ROUTE,
        "fallback_success_rate": 0.0,
        "candidate_success_rate": 1.0,
    }

    with pytest.raises(AgentBenefitEvidenceError, match="fields mismatch"):
        validate_language_structure_agent_benefit(
            legacy,
            source_revision=REVISION,
            goldset_sha256=GOLDSET_SHA256,
            expected_case_ids=CASE_IDS,
        )


def test_cli_builds_evidence_from_bound_benchmark_and_receipts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    benchmark = {
        "kind": "repoground.language_structure_benchmark",
        "version": "1.0",
        "source_revision": REVISION,
        "goldset_sha256": GOLDSET_SHA256,
        "case_results": [{"id": case_id} for case_id in CASE_IDS],
    }
    benchmark_path = tmp_path / "benchmark.json"
    pairs_path = tmp_path / "pairs.json"
    benchmark_path.write_text(json.dumps(benchmark), encoding="utf-8")
    pairs_path.write_text(json.dumps(_pairs()), encoding="utf-8")

    assert (
        main(
            [
                "--benchmark",
                str(benchmark_path),
                "--pairs",
                str(pairs_path),
            ]
        )
        == 0
    )
    output = json.loads(capsys.readouterr().out)

    assert output["source_revision"] == REVISION
    assert output["goldset_sha256"] == GOLDSET_SHA256
    assert output["summary"]["candidate_wins"] == 1
    assert [case["id"] for case in output["cases"]] == CASE_IDS
