import hashlib
import json
from pathlib import Path

import jsonschema

from merger.repoground.architecture.call_graph_quality_eval import (
    evaluate_python_call_graph_goldset,
)
from merger.repoground.core.call_graph_confidence import call_graph_coverage_confidence
from merger.repoground.core.system_relation_overlay import normalize_system_relation_evidence


REPO_ROOT = Path(__file__).resolve().parents[3]
GOLDSET_PATH = REPO_ROOT / "docs/retrieval/repoground_agent_utility_t020_goldset.v1.json"
OVERLAY_SCHEMA = (
    REPO_ROOT / "merger/repoground/contracts/system-relation-overlay.v1.schema.json"
)


def _load_goldset() -> dict:
    return json.loads(GOLDSET_PATH.read_text(encoding="utf-8"))


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def test_t020_goldset_binds_python_resolution_and_structural_relation_evidence() -> None:
    goldset = _load_goldset()
    python_goldset = REPO_ROOT / goldset["python_call_goldset"]
    report = evaluate_python_call_graph_goldset(python_goldset)
    cases = {case["id"]: case for case in report["cases"]}

    assert goldset["task_id"] == "REPOGROUND-AGENT-UTILITY-V1-T020"
    assert set(goldset["required_python_case_ids"]) <= set(cases)
    assert all(cases[case_id]["passed"] for case_id in goldset["required_python_case_ids"])
    thresholds = goldset["required_python_metrics"]
    assert report["metrics"]["s1_precision"] >= thresholds["minimum_s1_precision"]
    assert report["metrics"]["target_recall"] >= thresholds["minimum_target_recall"]
    assert report["metrics"]["false_positive_count"] <= thresholds["maximum_false_positive_count"]

    evidence = goldset["structural_relation_evidence"]
    overlay = normalize_system_relation_evidence(
        evidence,
        evidence_sha256=_canonical_sha256(evidence),
        repository_commit="b" * 40,
    )
    jsonschema.validate(
        overlay,
        json.loads(OVERLAY_SCHEMA.read_text(encoding="utf-8")),
    )
    assert overlay["status"] == "available"
    assert overlay["relation_kinds"] == goldset["expected_structural_relations"]
    assert set(goldset["expected_structural_nonclaims"]) <= set(
        overlay["does_not_establish"]
    )

    config_records = [
        record
        for record in overlay["records"]
        if record["contract_identity"]
        and record["contract_identity"]["kind"] == "config"
    ]
    assert {record["relation"] for record in config_records} == {
        "declares_config",
        "references_config",
    }
    assert all(record["relation"] not in {"calls", "constructs"} for record in config_records)
    assert all(record["evidence"]["level"] == "S1" for record in config_records)


def test_t020_confidence_boundaries_expose_ratios_causes_and_profile_caveats() -> None:
    graph = {
        "resolution_counts": {
            "resolved": 7,
            "candidate": 1,
            "ambiguous": 1,
            "unresolved": 1,
        },
        "calls": [
            {
                "resolution_status": "candidate",
                "resolution_reason": "name_match_not_unique",
            },
            {
                "resolution_status": "ambiguous",
                "resolution_reason": "local_module_function_multiple_definitions",
            },
            {
                "resolution_status": "unresolved",
                "resolution_reason": "dynamic_callee_expression",
            },
        ],
        "skipped_files_count": 0,
    }

    coverage = call_graph_coverage_confidence(graph)

    assert coverage["resolved_ratio"] == 0.7
    assert coverage["status_ratios"] == {
        "resolved": 0.7,
        "candidate": 0.1,
        "ambiguous": 0.1,
        "unresolved": 0.1,
    }
    assert coverage["unresolved_by_reason"] == {
        "ambiguous": {"local_module_function_multiple_definitions": 1},
        "candidate": {"name_match_not_unique": 1},
        "unresolved": {"dynamic_callee_expression": 1},
    }
    assert coverage["task_profile_confidence"]["basic_repo_question"]["status"] == "sufficient"
    assert coverage["task_profile_confidence"]["find_relevant_tests"]["status"] == "sufficient"
    for profile in ("change_impact", "review", "ground_claim"):
        assessment = coverage["task_profile_confidence"][profile]
        assert assessment["status"] == "insufficient"
        assert "below" in assessment["completeness_caveat"]
    assert "statistical_confidence" in coverage["does_not_establish"]
    assert "change_impact_outside_the_model" in coverage["does_not_establish"]


def test_t020_skipped_python_files_force_profile_caveats() -> None:
    coverage = call_graph_coverage_confidence(
        {
            "resolution_counts": {
                "resolved": 10,
                "candidate": 0,
                "ambiguous": 0,
                "unresolved": 0,
            },
            "calls": [],
            "skipped_files_count": 1,
        }
    )

    assert coverage["completeness"] == "partial"
    assert coverage["resolved_ratio"] == 1.0
    assert all(
        assessment["status"] == "insufficient"
        for assessment in coverage["task_profile_confidence"].values()
    )
    assert all(
        "skipped" in assessment["completeness_caveat"]
        for assessment in coverage["task_profile_confidence"].values()
    )
