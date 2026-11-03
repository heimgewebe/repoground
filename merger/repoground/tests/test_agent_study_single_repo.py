"""Single-repository A/B/C study validation without weakening legacy cohorts."""

from __future__ import annotations

import json
import unittest
from collections import Counter
from copy import deepcopy
from pathlib import Path

from merger.repoground.core.agent_study import AgentBenchmarkError, taskset_valid

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


if __name__ == "__main__":
    unittest.main()
