"""Single-repository A/B/C study validation without weakening legacy cohorts."""

from __future__ import annotations

import json
import unittest
from collections import Counter
from copy import deepcopy
from pathlib import Path

from merger.repoground.core.agent_study import AgentBenchmarkError, taskset_valid, _validate_receipt_tools

ROOT = Path(__file__).resolve().parents[3]
COMMONWORLD_TASKSET = ROOT / "docs/retrieval/repoground_commonworld_agent_study_cases.v1.json"
LEGACY_TASKSET = ROOT / "docs/retrieval/repoground_agent_study_cases.v1.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class SingleRepositoryAgentStudyTests(unittest.TestCase):
    def test_commonworld_single_repository_contract(self) -> None:
        taskset = load(COMMONWORLD_TASKSET)
        validated = taskset_valid(taskset)
        self.assertEqual(validated["case_count"], 12)
        self.assertEqual(list(taskset["repositories"]), ["commonworld"])
        self.assertEqual(sum(case["pilot"] for case in taskset["cases"]), 6)
        self.assertEqual(Counter(case["class"] for case in taskset["cases"]), {
            "known_target": 3,
            "reverse_relations": 3,
            "impact_tests": 3,
            "boundary": 3,
        })
        self.assertGreaterEqual(sum(case["oracle"]["outcome"] != "answer" for case in taskset["cases"]), 2)
        self.assertTrue(all(case["repositories"] == ["commonworld"] for case in taskset["cases"]))

    def test_existing_multirepository_study_remains_valid(self) -> None:
        self.assertEqual(taskset_valid(load(LEGACY_TASKSET))["case_count"], 12)

    def test_zero_repositories_still_rejected(self) -> None:
        taskset = deepcopy(load(COMMONWORLD_TASKSET))
        taskset["repositories"] = {}
        with self.assertRaisesRegex(AgentBenchmarkError, "at least one repository"):
            taskset_valid(taskset)

    def test_single_repository_rejects_foreign_oracle_path(self) -> None:
        taskset = deepcopy(load(COMMONWORLD_TASKSET))
        taskset["cases"][0]["oracle"]["required_paths"][0]["repo"] = "repoground"
        with self.assertRaisesRegex(AgentBenchmarkError, "unknown repository"):
            taskset_valid(taskset)

    def test_mandatory_v3_only_accepts_real_bound_source_read_after_search(self):
        bound = {
            "source_commit": "a" * 40, "generator_commit": "b" * 40,
            "manifest_sha256": "c" * 64, "observed_status": "available",
            "freshness": "pinned_exact",
        }
        def call(name, sequence, *, source_sha=None):
            row = {
                "sequence": sequence, "name": name, "status": "success",
                "duration_ms": 1, "input_bytes": 1, "output_bytes": 7,
                "repoground_evidence": {"repo": "grabowski", **bound},
            }
            if source_sha is not None:
                row["source_content_sha256"] = source_sha
            return row
        req = {
            "condition": "repoground_mandatory",
            "execution_context": {"agent_version": "codex-study-prompt-v3"},
            "git_file_tool_names": ["codex_file_command"],
            "repoground_tool_names": [
                "repoground_bundle_discover", "repoground_ask_context",
                "repoground_range_get",
            ],
            "repoground": {"grabowski": bound},
        }
        req["tools_allowed"] = sorted(req["git_file_tool_names"] + req["repoground_tool_names"])
        receipt = {"status": "success", "tool_calls": [
            call("repoground_bundle_discover", 1),
            call("repoground_bundle_discover", 2),
        ]}
        with self.assertRaisesRegex(AgentBenchmarkError, "mandatory v3"):
            _validate_receipt_tools(req, receipt)
        search = call("repoground_ask_context", 1)
        read = call("repoground_range_get", 2, source_sha="e" * 64)
        with self.assertRaisesRegex(AgentBenchmarkError, "mandatory v3"):
            _validate_receipt_tools(req, {"status":"success","tool_calls":[
                {**read, "sequence": 1}, {**search, "sequence": 2},
            ]})
        _validate_receipt_tools(req, {"status":"success","tool_calls":[search,read]})
        old = {**req, "execution_context": {"agent_version": "codex-study-prompt-v2"}}
        _validate_receipt_tools(old, receipt)

if __name__ == "__main__":
    unittest.main()
