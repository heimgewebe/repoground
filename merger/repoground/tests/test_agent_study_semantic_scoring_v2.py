"""Semantic study v2: checked extra sources and reasoned No; v1 stays strict."""

from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path

from merger.repoground.core import agent_study as study

ROOT = Path(__file__).resolve().parents[3]
NEW = ROOT / "docs/retrieval/repoground_commonworld_agent_study_cases.v2.json"
OLD = ROOT / "docs/retrieval/repoground_commonworld_agent_study_cases.v1.json"
LEGACY = ROOT / "docs/retrieval/repoground_agent_study_cases.v1.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sample(case: dict, *, extra: bool = False, outcome: str = "answer",
           sufficient: bool = True) -> dict:
    paths = list(case["oracle"]["required_paths"])
    if extra:
        paths.append({"repo": "commonworld", "path": "scripts/validate_public_catalog.py"})
    return {
        "status": "success",
        "answer": {
            "reported_paths": paths,
            "outcome": outcome,
            "asserted_sufficient_evidence": sufficient,
            "citations": [{
                "repo": "commonworld",
                "path": case["oracle"]["allowed_paths"][0]["path"],
                "commit": "2c6a790a8b76027d620cfc416918c9b6f08e34cc",
                "start_line": 1, "end_line": 2,
            }],
        },
    }


def grade(*, verdict: str = "correct", citations_checked: bool = True) -> dict:
    return {"verdict": verdict, "citations_checked": citations_checked}


class SemanticAgentStudyV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.taskset = load(NEW)
        self.cases = {case["id"]: case for case in self.taskset["cases"]}

    def test_v2_taskset_is_independent_and_valid(self) -> None:
        self.assertEqual(study.taskset_valid(self.taskset)["case_count"], 12)
        self.assertEqual(self.taskset["version"], "2.0")
        self.assertNotEqual(study.sha256_json(load(OLD)), study.sha256_json(self.taskset))
        self.assertEqual(sum(c["pilot"] for c in self.taskset["cases"]), 6)

    def test_frozen_v1_and_multirepo_legacy_still_validate(self) -> None:
        self.assertEqual(study.taskset_valid(load(OLD))["case_count"], 12)
        self.assertEqual(study.taskset_valid(load(LEGACY))["case_count"], 12)

    def test_v2_requires_explicit_review_policy_and_criteria(self) -> None:
        for key in ("path_policy", "review_criteria", "negative_conclusion"):
            with self.subTest(key=key):
                invalid = deepcopy(self.taskset)
                invalid["cases"][0]["oracle"].pop(key)
                with self.assertRaises(study.AgentBenchmarkError):
                    study.taskset_valid(invalid)

    def test_historical_v1_cannot_opt_into_v2_scoring(self) -> None:
        old = load(OLD)
        old["cases"][0]["oracle"]["path_policy"] = "independent_review"
        with self.assertRaisesRegex(study.AgentBenchmarkError, "v2 semantic fields forbidden"):
            study.taskset_valid(old)

    def test_v2_extra_path_is_unlisted_not_automatically_unsupported(self) -> None:
        case = self.cases["reverse-bootstrap-usage"]
        answer = sample(case, extra=True)
        ungraded = study._score(case, answer, None)
        self.assertIsNone(ungraded["quality_success"])
        self.assertIsNone(ungraded["unsupported_paths"])
        self.assertEqual(ungraded["unlisted_paths"], 1)
        self.assertEqual(ungraded["unlisted_paths_review_pending"], 1)

        approved = study._score(case, answer, grade())
        self.assertTrue(approved["quality_success"])
        self.assertEqual(approved["unlisted_paths"], 1)
        self.assertEqual(approved["unlisted_paths_review_pending"], 0)
        self.assertIsNone(approved["unsupported_paths"])

    def test_v2_unreviewed_or_partially_reviewed_extra_never_passes(self) -> None:
        case = self.cases["reverse-bootstrap-usage"]
        answer = sample(case, extra=True)
        for review in (grade(verdict="partial"), grade(citations_checked=False),
                       grade(verdict="uncertain")):
            with self.subTest(review=review):
                result = study._score(case, answer, review)
                self.assertFalse(result["quality_success"])
                self.assertEqual(result["unlisted_paths_review_pending"], 1)

    def test_v1_score_shape_remains_identical(self) -> None:
        case = next(x for x in load(OLD)["cases"] if x["id"] == "reverse-bootstrap-usage")
        score = study._score(case, sample(case, extra=True), grade())
        self.assertEqual(set(score), {
            "path_recall", "missing_gold_paths", "unsupported_paths",
            "expected_outcome", "outcome_match", "negative_false_confidence",
            "human_grade", "human_verified_citations", "quality_success",
        })
        self.assertEqual(score["unsupported_paths"], 1)

    def test_v1_path_allowlist_stays_hard_gate(self) -> None:
        case = next(x for x in load(OLD)["cases"] if x["id"] == "reverse-bootstrap-usage")
        result = study._score(case, sample(case, extra=True), grade())
        self.assertEqual(result["unsupported_paths"], 1)
        self.assertFalse(result["quality_success"])

    def test_arm_summary_preserves_unknown_unsupported_metric(self) -> None:
        case = self.cases["reverse-bootstrap-usage"]
        rows = []
        for arm in study.ARMS:
            rows.append({
                "condition": arm,
                "valid": True,
                "status": "success",
                "score": study._score(case, sample(case, extra=True), grade()),
                "metrics": {
                    "duration_ms": 100,
                    "input_tokens": 100,
                    "output_tokens": 10,
                    "cached_input_tokens": 0,
                    "tool_calls": 0,
                    "tool_failures": 0,
                    "tool_input_bytes": 0,
                    "tool_output_bytes": 0,
                    "tool_duration_ms": 0,
                    "repoground_calls": 0,
                    "repoground_failures": 0,
                    "tool_breakdown": [],
                    "billed_cost": None,
                },
            })
        arms = study._summarize_study_arms(rows)
        for arm in study.ARMS:
            self.assertIsNone(arms[arm]["unsupported_paths"])
            self.assertEqual(arms[arm]["unlisted_paths"], 1)
            self.assertEqual(arms[arm]["unlisted_paths_review_pending"], 0)
            self.assertEqual(arms[arm]["quality_correct"], 1)

    def test_reasoned_no_is_an_answer_not_false_confidence(self) -> None:
        case = self.cases["boundary-live-commons"]
        self.assertTrue(case["oracle"]["negative_conclusion"])
        self.assertEqual(case["oracle"]["outcome"], "answer")
        self.assertEqual(case["oracle"]["required_paths"], [])
        for sufficient in (False, True):
            with self.subTest(sufficient=sufficient):
                result = study._score(case, sample(case, outcome="answer",
                                                  sufficient=sufficient), grade())
                self.assertTrue(result["outcome_match"])
                self.assertFalse(result["negative_false_confidence"])
                self.assertTrue(result["quality_success"])

    def test_no_structured_citations_never_passes_a_substantive_v2_answer(self) -> None:
        case = self.cases["boundary-live-commons"]
        response = sample(case, outcome="answer", sufficient=True)
        response["answer"]["citations"] = []
        reviewed = study._score(case, response, grade())
        self.assertFalse(reviewed["quality_success"])
        old_case = next(x for x in load(OLD)["cases"] if x["id"] == "known-bootstrap-contract")
        legacy = sample(old_case)
        legacy["answer"]["citations"] = []
        self.assertTrue(study._score(old_case, legacy, grade())["quality_success"])

    def test_negative_no_must_be_semantically_graded(self) -> None:
        case = self.cases["boundary-live-commons"]
        result = study._score(case, sample(case, outcome="abstain", sufficient=False), grade())
        self.assertFalse(result["outcome_match"])
        self.assertFalse(result["quality_success"])

    def test_actual_unknown_remains_an_abstention(self) -> None:
        case = self.cases["boundary-runtime-browser"]
        correct = study._score(case, sample(case, outcome="abstain",
                                           sufficient=False), grade())
        self.assertTrue(correct["quality_success"])
        false_claim = study._score(case, sample(case, outcome="answer",
                                               sufficient=True), grade())
        self.assertTrue(false_claim["negative_false_confidence"])
        self.assertFalse(false_claim["quality_success"])



    def test_v3_success_receipt_must_match_final_provider_trace(self) -> None:
        import tempfile

        actual = {
            "outcome": "answer", "reported_paths": [], "citations": [],
            "asserted_sufficient_evidence": True,
            "explanation": "This is the exact actual final provider text used as evidence.",
        }
        altered = {
            **actual,
            "explanation": "This is a different answer substituted after provider execution.",
        }
        message = {
            "type": "item.completed",
            "item": {"type": "agent_message", "text": json.dumps(actual)},
        }
        with tempfile.TemporaryDirectory() as tmp:
            trace_path = Path(tmp) / "provider.jsonl"
            trace_path.write_text(json.dumps(message) + "\n", encoding="utf-8")
            for version in ("codex-study-prompt-v2", "codex-study-prompt-v3"):
                request = {"execution_context": {"agent_version": version}}
                receipt = {
                    "status": "success", "trace": {"path": trace_path.name},
                    "answer": actual,
                }
                study._validate_v2_trace_answer(request, receipt, Path(tmp))
                with self.subTest(version=version), self.assertRaisesRegex(
                    study.AgentBenchmarkError, "receipt answer differs",
                ):
                    study._validate_v2_trace_answer(
                        request, {**receipt, "answer": altered}, Path(tmp),
                    )
            # v1 is not retroactively subjected to new successful-answer rules.
            study._validate_v2_trace_answer(
                {"execution_context": {"agent_version": "codex-study-prompt-v1"}},
                {"status": "success", "trace": {"path": trace_path.name},
                 "answer": altered},
                Path(tmp),
            )


if __name__ == "__main__":
    unittest.main()