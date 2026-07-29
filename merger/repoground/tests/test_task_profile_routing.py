from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

import jsonschema
import pytest

from merger.repoground.cli.cmd_diagnostics import run_diagnostics
from merger.repoground.retrieval.task_profile_routing import (
    METRIC_KEYS,
    TASK_PROFILES,
    evaluate_evidence,
    load_evidence,
    sha256_file,
    validate_evidence,
)

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = ROOT / "docs/retrieval/task-profile-routing-evidence.v1.json"
SCHEMA = ROOT / "merger/repoground/contracts/retrieval-task-profile-routing.v1.schema.json"


def test_committed_evidence_is_schema_and_semantically_valid() -> None:
    evidence = load_evidence(EVIDENCE)
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(evidence)
    assert validate_evidence(evidence) == []
    assert [profile["task_profile"] for profile in evidence["profiles"]] == list(TASK_PROFILES)


def test_committed_source_bindings_match_repository_files() -> None:
    evidence = load_evidence(EVIDENCE)
    bindings = [evidence["goldset"]]
    for profile in evidence["profiles"]:
        for measurement in profile["measurements"]:
            bindings.extend(
                measurement[key]
                for key in ("dataset", "source_artifact")
                if measurement[key]["status"] == "available"
            )
            bindings.append(measurement["evaluator"])
    for binding in bindings:
        assert sha256_file(ROOT / binding["path"]) == binding["sha256"]


def test_composite_goldset_binds_profiles_repositories_sources_and_metric_coverage() -> None:
    evidence = load_evidence(EVIDENCE)
    goldset = json.loads((ROOT / evidence["goldset"]["path"]).read_text(encoding="utf-8"))
    assert goldset["kind"] == "repoground.retrieval_task_profile_goldset"
    assert sorted(goldset["task_profiles"]) == sorted(TASK_PROFILES)
    assert len(goldset["repositories"]) >= 2
    assert sorted(goldset["required_metrics"]) == sorted(METRIC_KEYS)
    assert goldset["measurement_coverage"] == evidence["goldset"]["measurement_coverage"]
    for source in goldset["source_sets"].values():
        assert sha256_file(ROOT / source["path"]) == source["sha256"]


def test_impact_context_bytes_and_tool_calls_are_reproducible() -> None:
    evidence = load_evidence(EVIDENCE)
    measurement = next(
        item
        for profile in evidence["profiles"]
        for item in profile["measurements"]
        if item["id"] == "agent-impact-live-rerun-20260713"
    )
    source = json.loads((ROOT / measurement["source_artifact"]["path"]).read_text(encoding="utf-8"))
    payload = json.dumps(
        [case["impact_paths"] for case in source["cases"]],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    assert len(payload) == measurement["metrics"]["context_bytes"] == 711
    assert len(source["cases"]) * 2 == measurement["metrics"]["tool_calls"] == 6


def test_metric_coverage_cannot_reference_null_or_unknown_measurements() -> None:
    evidence = load_evidence(EVIDENCE)
    null_reference = copy.deepcopy(evidence)
    null_reference["goldset"]["measurement_coverage"]["context_bytes"] = [
        "canonical-review-retrieval-20260711"
    ]
    assert any(
        "references an unmeasured value" in error for error in validate_evidence(null_reference)
    )

    unknown_reference = copy.deepcopy(evidence)
    unknown_reference["goldset"]["measurement_coverage"]["tool_calls"] = [
        "missing-measurement"
    ]
    assert any(
        "references unknown measurement" in error
        for error in validate_evidence(unknown_reference)
    )


def test_evaluator_keeps_partial_special_routes_opt_in_and_blocks_unmeasured() -> None:
    decision = evaluate_evidence(load_evidence(EVIDENCE))
    by_profile = {item["task_profile"]: item for item in decision["profile_decisions"]}
    assert by_profile["basic_repo_question"]["decision"] == "blocked"
    assert by_profile["review"]["decision"] == "keep_opt_in"
    assert by_profile["change_impact"]["decision"] == "keep_opt_in"
    assert by_profile["find_relevant_tests"]["decision"] == "keep_opt_in"
    assert by_profile["ground_claim"]["decision"] == "blocked"
    assert decision["global_default_promoted"] is False
    assert decision["global_decision"] == "no_global_promotion_by_aggregation"


def test_complete_profile_can_only_promote_with_explicit_profile_authority() -> None:
    evidence = load_evidence(EVIDENCE)
    profile = next(item for item in evidence["profiles"] if item["task_profile"] == "review")
    measurement = profile["measurements"][-1]
    measurement["status"] = "measured"
    measurement["metrics"] = {
        "recall_at_k": 0.95,
        "mrr": 0.5,
        "expected_target_recall": 0.5,
        "citation_health": 1.0,
        "range_health": 1.0,
        "miss_taxonomy": {"target_exists_not_in_top_k": 1},
        "context_bytes": 4096,
        "tool_calls": 4,
    }
    assert evaluate_evidence(evidence)["profile_decisions"][1]["decision"] == "keep_opt_in"
    profile["promotion_authority"] = "explicit_profile_decision"
    assert evaluate_evidence(evidence)["profile_decisions"][1]["decision"] == "promote"


def test_measured_status_rejects_null_metrics() -> None:
    evidence = load_evidence(EVIDENCE)
    profile = evidence["profiles"][0]
    profile["measurements"][0]["status"] = "measured"
    errors = validate_evidence(evidence)
    assert any("is measured but has null metrics" in error for error in errors)


def test_candidate_measurement_must_be_explicit_and_match_the_route() -> None:
    evidence = load_evidence(EVIDENCE)
    profile = evidence["profiles"][1]
    profile["candidate_measurement_id"] = "canonical-review-retrieval-20260711"
    with pytest.raises(ValueError, match="must use candidate_route"):
        evaluate_evidence(evidence)


def test_cli_semantic_validation_rejects_schema_level_metric_errors() -> None:
    evidence = load_evidence(EVIDENCE)
    evidence["profiles"][0]["measurements"][0]["metrics"]["recall_at_k"] = 1.5
    with pytest.raises(ValueError, match="number from 0 to 1"):
        evaluate_evidence(evidence)


def test_missing_profile_or_metric_fails_closed() -> None:
    evidence = load_evidence(EVIDENCE)
    missing_profile = copy.deepcopy(evidence)
    missing_profile["profiles"].pop()
    assert any("each canonical task profile" in error for error in validate_evidence(missing_profile))

    missing_metric = copy.deepcopy(evidence)
    del missing_metric["profiles"][0]["measurements"][0]["metrics"][METRIC_KEYS[0]]
    with pytest.raises(ValueError, match="metrics missing"):
        evaluate_evidence(missing_metric)


def test_diagnostics_cli_exposes_read_only_routing_gate(capsys: pytest.CaptureFixture[str]) -> None:
    args = argparse.Namespace(
        diagnostics_help=False,
        diagnostics_args=["routing-gates", "--evidence", str(EVIDENCE)],
    )
    assert run_diagnostics(args) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["global_decision"] == "no_global_promotion_by_aggregation"
    assert output["global_default_promoted"] is False
