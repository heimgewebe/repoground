import json
from pathlib import Path

import merger.repoground.core as core_api
from merger.repoground.tests.git_fixture import commit_fixture


GOLDSET_PATH = (
    Path(__file__).resolve().parents[3]
    / "docs"
    / "retrieval"
    / "repoground_agent_utility_t022_goldset.v1.json"
)


def _load_goldset() -> dict:
    return json.loads(GOLDSET_PATH.read_text(encoding="utf-8"))


def _write_case(root: Path, files: dict[str, str]) -> None:
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def _semantic_key(record: dict) -> tuple[str, str, str, str]:
    return (
        str(record["relation"]),
        str(record["target"]["identity"]),
        str(record["source"]["path"]),
        str(record["evidence"]["level"]),
    )


def _expected_key(record: dict) -> tuple[str, str, str, str]:
    return (
        str(record["relation"]),
        str(record["target_identity"]),
        str(record["path"]),
        str(record["evidence_level"]),
    )


def test_t022_goldset_meets_precision_recall_range_and_omission_gates(tmp_path):
    goldset = _load_goldset()
    assert goldset["kind"] == "repoground.agent_utility_t022_goldset"
    assert goldset["version"] == "1.0"
    assert goldset["task_id"] == "REPOGROUND-AGENT-UTILITY-V1-T022"
    assert goldset["revision_policy"] == "materialized_fixture_git_head"
    assert {case["class"] for case in goldset["cases"]} >= {
        "positive",
        "ambiguous",
        "true_null",
    }

    predicted_count = 0
    expected_count = 0
    true_positive_count = 0
    range_match_count = 0
    s1_false_positive_count = 0
    omission_mismatches: list[dict] = []

    for case in goldset["cases"]:
        case_root = tmp_path / case["id"]
        case_root.mkdir()
        _write_case(case_root, case["files"])
        commit = commit_fixture(case_root)
        result = core_api.collect_system_relation_evidence(
            case_root,
            repository_identity=goldset["repository_identity"],
            repository_commit=commit,
        )
        assert result["revision_binding"] == {
            "mode": "git_commit_object",
            "repository_commit": commit,
            "verified": True,
        }
        predicted = result["overlay"]["records"]
        expected = case["expected_records"]
        predicted_by_key = {_semantic_key(record): record for record in predicted}
        expected_by_key = {_expected_key(record): record for record in expected}

        predicted_keys = set(predicted_by_key)
        expected_keys = set(expected_by_key)
        matched = predicted_keys & expected_keys
        false_positive_keys = predicted_keys - expected_keys

        predicted_count += len(predicted_keys)
        expected_count += len(expected_keys)
        true_positive_count += len(matched)
        s1_false_positive_count += sum(
            1 for key in false_positive_keys if key[3] == "S1"
        )
        for key in matched:
            actual_range = predicted_by_key[key]["source"]["range"]
            expected_line = int(expected_by_key[key]["start_line"])
            if (
                actual_range["start_line"] == expected_line
                and actual_range["end_line"] == expected_line
            ):
                range_match_count += 1

        observed_omissions = sorted(item["reason"] for item in result["omissions"])
        expected_omissions = sorted(case["expected_omission_reasons"])
        if observed_omissions != expected_omissions:
            omission_mismatches.append(
                {
                    "case_id": case["id"],
                    "expected": expected_omissions,
                    "observed": observed_omissions,
                }
            )

    false_positive_count = predicted_count - true_positive_count
    false_negative_count = expected_count - true_positive_count
    precision = (
        true_positive_count / predicted_count if predicted_count else 1.0
    )
    recall = true_positive_count / expected_count if expected_count else 1.0
    range_accuracy = (
        range_match_count / true_positive_count if true_positive_count else 1.0
    )
    metrics = {
        "cases": len(goldset["cases"]),
        "predicted_records": predicted_count,
        "expected_records": expected_count,
        "true_positives": true_positive_count,
        "false_positives": false_positive_count,
        "false_negatives": false_negative_count,
        "precision": precision,
        "recall": recall,
        "range_accuracy": range_accuracy,
        "s1_false_positive_count": s1_false_positive_count,
        "omission_mismatches": omission_mismatches,
    }
    gates = goldset["gates"]

    assert precision >= gates["minimum_precision"], metrics
    assert recall >= gates["minimum_recall"], metrics
    assert range_accuracy >= gates["minimum_range_accuracy"], metrics
    assert s1_false_positive_count <= gates["maximum_s1_false_positive_count"], metrics
    if gates["require_exact_omission_reasons"]:
        assert omission_mismatches == [], metrics

    assert metrics == {
        "cases": 7,
        "predicted_records": 3,
        "expected_records": 3,
        "true_positives": 3,
        "false_positives": 0,
        "false_negatives": 0,
        "precision": 1.0,
        "recall": 1.0,
        "range_accuracy": 1.0,
        "s1_false_positive_count": 0,
        "omission_mismatches": [],
    }
