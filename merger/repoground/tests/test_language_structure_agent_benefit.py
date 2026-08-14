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
    validate_language_structure_agent_benefit,
)

ROOT = Path(__file__).resolve().parents[3]
CONTRACTS = ROOT / "merger" / "repoground" / "contracts"
REVISION = "a" * 40
GOLDSET_SHA256 = "b" * 64
CASE_IDS = ["bash-positive", "rust-positive", "bash-null", "rust-null"]


def _pairs() -> dict:
    return {
        "kind": "repoground.language_structure_agent_benefit_pairs",
        "version": "1.0",
        "measurement_id": "paired-benefit-unit",
        "fallback_route": "text_fallback",
        "candidate_route": "language_structure_v1",
        "comparison": {
            "same_model": True,
            "same_prompt": True,
            "same_budget": True,
            "same_source_revision": True,
            "same_grader": True,
            "model_identity_sha256": "1" * 64,
            "harness_identity_sha256": "2" * 64,
            "environment_identity_sha256": "3" * 64,
            "grader_identity_sha256": "4" * 64,
        },
        "treatment": {
            "variable": "language_structure_json",
            "fallback_excludes": True,
            "candidate_includes": True,
        },
        "cases": [
            {
                "id": case_id,
                "task_sha256": hashlib.sha256(case_id.encode("utf-8")).hexdigest(),
                "fallback": {
                    "success": index != 0,
                    "evidence_refs": [f"artifact:fallback:{case_id}"],
                },
                "candidate": {
                    "success": True,
                    "evidence_refs": [f"artifact:candidate:{case_id}"],
                },
            }
            for index, case_id in enumerate(CASE_IDS)
        ],
        "does_not_establish": [
            "default_activation",
            "causal_generalization_beyond_bound_cases",
        ],
    }


def _benefit() -> dict:
    return build_language_structure_agent_benefit(
        _pairs(),
        source_revision=REVISION,
        goldset_sha256=GOLDSET_SHA256,
        expected_case_ids=CASE_IDS,
    )


def test_builder_derives_paired_summary_and_schema_validates() -> None:
    benefit = _benefit()

    assert benefit["summary"] == {
        "sample_count": 4,
        "fallback_success_rate": 0.75,
        "candidate_success_rate": 1.0,
        "candidate_wins": 1,
        "fallback_wins": 0,
        "ties": 3,
    }
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
            lambda value: value["cases"][1].__setitem__(
                "task_sha256", value["cases"][0]["task_sha256"]
            ),
            "benefit task_sha256 values must be unique",
        ),
        (
            lambda value: value["comparison"].__setitem__("same_model", False),
            "comparison.same_model must be true",
        ),
        (
            lambda value: value["treatment"].__setitem__("variable", "canonical_md"),
            "treatment.variable must equal",
        ),
        (
            lambda value: value["cases"][0]["fallback"].__setitem__(
                "evidence_refs", []
            ),
            "must contain 1..8 evidence refs",
        ),
    ],
)
def test_builder_rejects_unpaired_or_unfair_input(mutation, message: str) -> None:
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


@pytest.mark.parametrize(
    ("field", "expected", "message"),
    [
        ("source_revision", "c" * 40, "source_revision mismatch"),
        ("goldset_sha256", "d" * 64, "goldset_sha256 mismatch"),
    ],
)
def test_validator_rejects_benchmark_binding_mismatch(
    field: str, expected: str, message: str
) -> None:
    benefit = _benefit()
    kwargs = {
        "source_revision": REVISION,
        "goldset_sha256": GOLDSET_SHA256,
        "expected_case_ids": CASE_IDS,
    }
    kwargs[field] = expected

    with pytest.raises(AgentBenefitEvidenceError, match=message):
        validate_language_structure_agent_benefit(benefit, **kwargs)


def test_validator_rejects_legacy_aggregate_only_v1() -> None:
    legacy = {
        "kind": "repoground.language_structure_agent_benefit",
        "version": "1.0",
        "source_revision": REVISION,
        "goldset_sha256": GOLDSET_SHA256,
        "sample_count": len(CASE_IDS),
        "fallback_route": "text_fallback",
        "candidate_route": "language_structure_v1",
        "fallback_success_rate": 0.5,
        "candidate_success_rate": 1.0,
    }

    with pytest.raises(AgentBenefitEvidenceError, match="fields mismatch"):
        validate_language_structure_agent_benefit(
            legacy,
            source_revision=REVISION,
            goldset_sha256=GOLDSET_SHA256,
            expected_case_ids=CASE_IDS,
        )


def test_cli_builds_evidence_from_bound_benchmark_and_pairs(
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
