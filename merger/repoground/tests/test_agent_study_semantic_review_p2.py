"""Synthetic P2 safety regressions; never treat these fixtures as provider evidence."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import jsonschema

from merger.repoground.core import agent_study as study

ROOT = Path(__file__).resolve().parents[3]
TASKSET_V1 = ROOT / "docs/retrieval/repoground_commonworld_agent_study_cases.v1.json"
TASKSET_V2 = ROOT / "docs/retrieval/repoground_commonworld_agent_study_cases.v2.json"
SCHEMA_V1 = ROOT / "merger/repoground/contracts/agent-study-evaluation.v1.schema.json"
SCHEMA_V2 = ROOT / "merger/repoground/contracts/agent-study-evaluation.v2.schema.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def fake_plan(taskset: dict) -> dict:
    """Plan-only test data; no real agents, manifests, or result receipts."""
    profile = {
        "provider": "synthetic-test-provider", "model": "synthetic-test-model",
        "sampling": {"temperature": 0}, "agent_version": "synthetic-test-agent",
        "runner_version": "synthetic-test-runner", "host_class": "synthetic-test-host",
        "cache_policy": "controlled", "tool_contract": "synthetic-contract",
        "tool_names": {
            "git": ["git_search"], "file": ["read_file"],
            "repoground": ["repoground_query"],
        },
    }
    sources = {
        key: {
            "source_commit": val["commit"],
            "generator_commit": "a" * 40,
            "manifest_path": "/synthetic/not-a-real-bundle",
            "manifest_sha256": "b" * 64,
            "health": "pass",
        }
        for key, val in taskset["repositories"].items()
    }
    with patch.object(study, "verify_sources", return_value={"synthetic": 1}), (
        patch.object(study, "_check_snapshots", side_effect=lambda _ts, snapshots: snapshots)
    ):
        return study.create_plan(
            taskset, profile, sources,
            run_id="semantic-p2-contract-synthetic-plan",
            suite="pilot", repetitions=2, roots={},
        )


def full_study_inputs() -> tuple[list[dict], dict, dict, dict]:
    """Twelve complete task IDs × two repetitions × three arms."""
    rows = [
        {
            "case_id": f"case-{i:02d}",
            "valid": True, "status": "success",
            "score": {"human_grade": "partial", "human_verified_citations": True},
        }
        for i in range(12) for _ in range(6)
    ]
    arms = {
        arm: {
            "valid_success": 24, "quality_correct": 0, "quality_incorrect": 0,
            "unsupported_paths": None, "negative_false_confidence": 0,
            "unlisted_paths_review_pending": 0,
            "repoground_calls_total": 20 if arm == "repoground_selective" else 0,
            "repoground_failures_total": 0,
        }
        for arm in study.ARMS
    }
    effects = {"selective_vs_git": {
        "duration_delta_ms_bootstrap_95ci": [-200, -100]
    }}
    plan = {"suite": "full", "repetitions": 2}
    return rows, arms, effects, plan


class ReviewP2Tests(unittest.TestCase):
    def test_published_v1_schema_rejects_null_unsupported_paths(self) -> None:
        schema = load(SCHEMA_V1)
        jsonschema.Draft7Validator.check_schema(schema)
        for arm in study.ARMS:
            prop = schema["properties"]["conditions"]["properties"][arm]
            self.assertEqual(prop["properties"]["unsupported_paths"]["type"], "integer")

    def test_new_v2_schema_is_separate_and_strict(self) -> None:
        schema = load(SCHEMA_V2)
        jsonschema.Draft7Validator.check_schema(schema)
        self.assertEqual(schema["properties"]["version"]["const"], "2.0")
        for arm in study.ARMS:
            prop = schema["properties"]["conditions"]["properties"][arm]
            self.assertEqual(
                prop["properties"]["unsupported_paths"]["type"],
                ["integer", "null"],
            )
            self.assertIn("unlisted_paths", prop["required"])
            self.assertIn("unlisted_paths_review_pending", prop["required"])

    def test_real_report_shape_valid_for_both_taskset_versions_without_results(self) -> None:
        for taskset_path, schema_path, version in (
            (TASKSET_V1, SCHEMA_V1, "1.0"),
            (TASKSET_V2, SCHEMA_V2, "2.0"),
        ):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as dirname:
                taskset = load(taskset_path)
                plan = fake_plan(taskset)
                report = study.evaluate(
                    plan, taskset, [], [],
                    trace_root=Path(dirname),
                    measurement_scope="synthetic_contract_fixture",
                )
                self.assertEqual(report["version"], version)
                self.assertEqual(report["decision"]["status"], "not_established")
                self.assertEqual(report["supplied_trials"], 0)
                jsonschema.validate(report, load(schema_path))
                for arm in study.ARMS:
                    summary = report["conditions"][arm]
                    if version == "2.0":
                        self.assertIsNone(summary["unsupported_paths"])
                        self.assertEqual(summary["unlisted_paths_review_pending"], 0)
                    else:
                        self.assertEqual(summary["unsupported_paths"], 0)
                        self.assertNotIn("unlisted_paths_review_pending", summary)

    def test_v2_report_with_valid_success_receipt_matches_schema(self) -> None:
        import hashlib
        taskset = load(TASKSET_V2)
        plan = fake_plan(taskset)
        request = next(r for r in plan["requests"] if r["condition"] == "git_only")
        case = next(c for c in taskset["cases"] if c["id"] == request["case_id"])
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            raw = b'{"event":"synthetic-test-only"}\\n'
            trace = root / "test-trace.jsonl"
            trace.write_bytes(raw)
            paths = list(case["oracle"]["required_paths"])
            citation = [{
                "repo": paths[0]["repo"],
                "path": paths[0]["path"],
                "commit": request["repositories"][paths[0]["repo"]]["commit"],
                "start_line": 1,
                "end_line": 2,
            }] if paths else []
            receipt = {
                "kind": study.RECEIPT_KIND,
                "version": study.VERSION,
                "request_id": request["request_id"],
                "request_sha256": study.sha256_json(request),
                "condition": request["condition"],
                "session_id": request["session_id"],
                "workspace_id": request["workspace_id"],
                "runner": request["runner"],
                "execution_context": request["execution_context"],
                "status": "success",
                "started_at": "2026-11-04T00:00:00+00:00",
                "ended_at": "2026-11-04T00:00:01+00:00",
                "duration_ms": 1000,
                "usage": {
                    "source": "provider_reported", "input_tokens": 250,
                    "output_tokens": 30, "cached_input_tokens": 40,
                },
                "tool_calls": [{
                    "sequence": 1, "name": request["git_file_tool_names"][0],
                    "status": "success", "duration_ms": 150,
                    "input_bytes": 10, "output_bytes": 100,
                }],
                "answer": {
                    "outcome": case["oracle"]["outcome"],
                    "reported_paths": paths,
                    "citations": citation,
                    "asserted_sufficient_evidence": (
                        case["oracle"]["outcome"] == "answer"
                    ),
                },
                "trace": {
                    "path": "test-trace.jsonl", "bytes": len(raw),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                },
                "error": None, "billed_cost": None,
                "resources": {"cpu_ms": None, "peak_rss_kib": None},
            }
            self.assertEqual(
                study.validate_receipt(request, receipt, trace_root=root),
                [],
            )
            report = study.evaluate(
                plan, taskset, [receipt], [],
                trace_root=root, measurement_scope="synthetic_contract_fixture",
            )
        self.assertEqual(report["valid_success_trials"], 1)
        self.assertIsNone(report["conditions"]["git_only"]["unsupported_paths"])
        jsonschema.validate(report, load(SCHEMA_V2))
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(report, load(SCHEMA_V1))

    def test_report_schema_requires_explicit_v2_pending_paths(self) -> None:
        taskset = load(TASKSET_V2)
        plan = fake_plan(taskset)
        with tempfile.TemporaryDirectory() as dirname:
            report = study.evaluate(
                plan, taskset, [], [], trace_root=Path(dirname),
                measurement_scope="synthetic_contract_fixture",
            )
        schema = load(SCHEMA_V2)
        report["conditions"]["git_only"].pop("unlisted_paths_review_pending")
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(report, schema)

    def test_all_partial_grades_cannot_pass_even_with_clean_extra_paths(self) -> None:
        rows, arms, effects, plan = full_study_inputs()
        decision, reviewed = study._select_study_decision(
            rows, [], plan, arms, effects, "real_runner_reported",
            semantic_v2=True,
        )
        self.assertTrue(reviewed)
        self.assertEqual(decision, "no_selective_benefit_established")

    def test_all_partial_grades_with_pending_paths_cannot_pass(self) -> None:
        rows, arms, effects, plan = full_study_inputs()
        arms["repoground_selective"]["unlisted_paths_review_pending"] = 24
        decision, reviewed = study._select_study_decision(
            rows, [], plan, arms, effects, "real_runner_reported",
            semantic_v2=True,
        )
        self.assertTrue(reviewed)
        self.assertEqual(decision, "no_selective_benefit_established")

    def test_even_high_quality_cannot_pass_pending_source_reviews(self) -> None:
        rows, arms, effects, plan = full_study_inputs()
        arms["git_only"]["quality_correct"] = 23
        arms["repoground_selective"]["quality_correct"] = 23
        arms["repoground_mandatory"]["unlisted_paths_review_pending"] = 1
        decision, _ = study._select_study_decision(
            rows, [], plan, arms, effects, "real_runner_reported",
            semantic_v2=True,
        )
        self.assertEqual(decision, "no_selective_benefit_established")

    def test_no_actual_selective_repoground_call_no_benefit(self) -> None:
        rows, arms, effects, plan = full_study_inputs()
        arms["git_only"]["quality_correct"] = 23
        arms["repoground_selective"]["quality_correct"] = 23
        arms["repoground_selective"]["repoground_calls_total"] = 0
        decision, _ = study._select_study_decision(
            rows, [], plan, arms, effects, "real_runner_reported",
            semantic_v2=True,
        )
        self.assertEqual(decision, "no_selective_benefit_established")

    def test_failed_repoground_calls_cannot_be_counted_as_use(self) -> None:
        rows, arms, effects, plan = full_study_inputs()
        arms["git_only"]["quality_correct"] = 23
        arms["repoground_selective"]["quality_correct"] = 23
        arms["repoground_selective"]["repoground_failures_total"] = 20
        decision, _ = study._select_study_decision(
            rows, [], plan, arms, effects, "real_runner_reported",
            semantic_v2=True,
        )
        self.assertEqual(decision, "no_selective_benefit_established")

    def test_correct_fraction_below_floor_does_not_pass(self) -> None:
        rows, arms, effects, plan = full_study_inputs()
        arms["git_only"]["quality_correct"] = 17
        arms["repoground_selective"]["quality_correct"] = 17
        decision, _ = study._select_study_decision(
            rows, [], plan, arms, effects, "real_runner_reported",
            semantic_v2=True,
        )
        self.assertEqual(decision, "no_selective_benefit_established")

    def test_sufficient_reviewed_quality_and_real_usage_not_overblocked(self) -> None:
        rows, arms, effects, plan = full_study_inputs()
        arms["git_only"]["quality_correct"] = 18
        arms["repoground_selective"]["quality_correct"] = 18
        decision, _ = study._select_study_decision(
            rows, [], plan, arms, effects, "real_runner_reported",
            semantic_v2=True,
        )
        self.assertEqual(decision, "selective_benefit_candidate")

    def test_ungraded_results_never_promote(self) -> None:
        rows, arms, effects, plan = full_study_inputs()
        rows[0]["score"]["human_verified_citations"] = False
        arms["git_only"]["quality_correct"] = 23
        arms["repoground_selective"]["quality_correct"] = 23
        decision, reviewed = study._select_study_decision(
            rows, [], plan, arms, effects, "real_runner_reported",
            semantic_v2=True,
        )
        self.assertFalse(reviewed)
        self.assertEqual(decision, "not_established")


if __name__ == "__main__":
    unittest.main()