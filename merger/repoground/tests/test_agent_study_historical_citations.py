"""Frozen historical citation revisions: source-bound, never open-ended."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import unittest

from merger.repoground.core import agent_study as study

TASKSET_V2 = (
    Path(__file__).resolve().parents[3]
    / "docs/retrieval/repoground_system_evidence_agent_study_cases.v2.json"
)


def _gold() -> dict:
    return json.loads(TASKSET_V2.read_text(encoding="utf-8"))


def _request_and_receipt() -> tuple[dict, dict]:
    taskset = _gold()
    case = next(c for c in taskset["cases"] if c["id"] == "historic-split-pin")
    request = {
        "repositories": {
            repo: taskset["repositories"][repo] for repo in case["repositories"]
        },
        "citation_commits": case["citation_commits"],
    }
    receipt = {
        "status": "success",
        "answer": {
            "outcome": "answer",
            "reported_paths": [{"repo": "heim-pc", "path": "flake.lock"}],
            "citations": [{
                "repo": "heim-pc", "path": "flake.lock",
                "commit": "12a8c6af34e5aedfa98f795c1261c782f97731d8",
                "start_line": 1, "end_line": 10,
            }],
            "asserted_sufficient_evidence": True,
            "explanation": "Die historische Flake.lock-Revision ist explizit gebunden.",
        },
    }
    return request, receipt


class HistoricalCitationTests(unittest.TestCase):
    def test_v2_historical_case_keeps_original_12_case_contract(self):
        result = study.taskset_valid(_gold())
        assert result["case_count"] == 12
        assert result["taskset_id"] == "repoground-system-evidence-20261102-v2"


    def test_historical_citation_accepted_only_when_bound_to_case(self):
        request, receipt = _request_and_receipt()
        study._validate_receipt_answer(request, receipt)
        without = dict(request)
        without.pop("citation_commits")
        with self.assertRaisesRegex(study.AgentBenchmarkError, "citation revision mismatch"):
            study._validate_receipt_answer(without, receipt)
        forged = deepcopy(receipt)
        forged["answer"]["citations"][0]["commit"] = "f" * 40
        with self.assertRaisesRegex(study.AgentBenchmarkError, "citation revision mismatch"):
            study._validate_receipt_answer(request, forged)


    def test_invalid_historical_citation_types_cannot_escape_validator(self):
        for value in ([{"not": "a commit"}], ["b" * 40, "b" * 40], ["bad"]):
            taskset = _gold()
            case = next(c for c in taskset["cases"] if c["id"] == "historic-split-pin")
            case["citation_commits"]["nixer"] = value
            with self.assertRaises(study.AgentBenchmarkError):
                study.taskset_valid(taskset)