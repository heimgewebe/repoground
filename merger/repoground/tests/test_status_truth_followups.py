from __future__ import annotations

from scripts.docmeta.status_truth_followups import (
    EXPECTED_POLICY,
    validate_outcome_followups,
)


def _truth(binding: dict | None = None) -> dict:
    binding = binding or {
        "kind": "no_task",
        "rationale": "A separate product-level decision is required before a task exists.",
    }
    return {
        "outcome_followup_policy": dict(EXPECTED_POLICY),
        "system_maturity": {
            "operational_readiness": "established",
            "product_readiness": "not_established",
            "release_readiness": "established",
        },
        "audit_packages": [],
        "open_followups": [
            {
                "axis": "product_readiness",
                "reason": "Product readiness is not established by slice completion.",
                "covers": ["system_maturity:product_readiness"],
                "binding": binding,
            }
        ],
    }


def _codes(
    truth: dict,
    bureau_snapshot: dict | None = None,
    *,
    local_tasks: list[dict] | None = None,
) -> set[str]:
    findings, _ = validate_outcome_followups(
        truth,
        bureau_snapshot,
        local_tasks=local_tasks,
    )
    return {item.code for item in findings}


def test_no_task_rationale_needs_no_bureau_snapshot() -> None:
    findings, resolution = validate_outcome_followups(_truth())
    assert findings == []
    assert resolution == {
        "status": "not_required",
        "checked_reference_count": 0,
        "valid_reference_count": 0,
    }


def test_current_outcome_gap_requires_coverage() -> None:
    truth = _truth()
    truth["open_followups"] = []
    assert "STATUS_TRUTH_OUTCOME_FOLLOWUP_MISSING" in _codes(truth)


def test_stale_structured_followup_is_rejected() -> None:
    truth = _truth()
    truth["system_maturity"]["product_readiness"] = "established"
    assert "STATUS_TRUTH_OUTCOME_FOLLOWUP_STALE" in _codes(truth)


def test_blocked_audit_promotion_requires_coverage() -> None:
    truth = _truth()
    truth["audit_packages"] = [{"task_id": "TASK-RETRIEVAL", "promotion": "blocked"}]
    assert "STATUS_TRUTH_OUTCOME_FOLLOWUP_MISSING" in _codes(truth)
    truth["open_followups"].append(
        {
            "axis": "product_readiness",
            "reason": "Retrieval promotion remains blocked.",
            "covers": ["audit_package:TASK-RETRIEVAL:promotion"],
            "binding": {
                "kind": "no_task",
                "rationale": "Fresh improvement evidence is required before new work exists.",
            },
        }
    )
    assert "STATUS_TRUTH_OUTCOME_FOLLOWUP_MISSING" not in _codes(truth)


def test_noncompleted_task_missing_evidence_requires_coverage() -> None:
    truth = _truth()
    local_tasks = [
        {
            "id": "TASK-OPEN",
            "status": "open",
            "missing_evidence": ["Implementation is still open."],
        }
    ]
    assert "STATUS_TRUTH_OUTCOME_FOLLOWUP_MISSING" in _codes(
        truth,
        local_tasks=local_tasks,
    )
    truth["open_followups"].append(
        {
            "axis": "operational_readiness",
            "reason": "The open task still lacks implementation evidence.",
            "covers": ["task:TASK-OPEN:missing_evidence"],
            "binding": {"kind": "bureau_task", "id": "REPOGROUND-OPEN-T001"},
        }
    )
    snapshot = {
        "available": True,
        "tasks": {
            "REPOGROUND-OPEN-T001": {
                "canonical_id": "REPOGROUND-OPEN-T001",
                "state": "ready",
            }
        },
        "candidates": {},
    }
    assert _codes(truth, snapshot, local_tasks=local_tasks) == set()


def test_done_task_missing_evidence_remains_task_local_limitation() -> None:
    truth = _truth()
    local_tasks = [
        {
            "id": "TASK-DONE",
            "status": "done",
            "missing_evidence": ["A deliberate non-goal remains outside this slice."],
        }
    ]
    assert _codes(truth, local_tasks=local_tasks) == set()


def test_repo_cannot_claim_bureau_authority() -> None:
    truth = _truth()
    truth["outcome_followup_policy"]["bureau_authority"] = "repoground"
    assert "STATUS_TRUTH_FOLLOWUP_AUTHORITY" in _codes(truth)


def test_open_bureau_task_reference_is_valid_with_read_only_snapshot() -> None:
    truth = _truth({"kind": "bureau_task", "id": "REPOGROUND-TEST-T001"})
    snapshot = {
        "available": True,
        "tasks": {
            "REPOGROUND-TEST-T001": {
                "canonical_id": "REPOGROUND-TEST-T001",
                "state": "ready",
            }
        },
        "candidates": {},
    }
    findings, resolution = validate_outcome_followups(truth, snapshot)
    assert findings == []
    assert resolution["status"] == "verified"
    assert resolution["valid_reference_count"] == 1


def test_open_bureau_candidate_reference_is_valid() -> None:
    truth = _truth({"kind": "bureau_candidate", "id": "candidate-deadbeef"})
    snapshot = {
        "available": True,
        "tasks": {},
        "candidates": {
            "candidate-deadbeef": {
                "canonical_id": "candidate-deadbeef",
                "status": "observed",
            }
        },
    }
    assert _codes(truth, snapshot) == set()


def test_bureau_reference_fails_closed_when_snapshot_is_unavailable() -> None:
    truth = _truth({"kind": "bureau_task", "id": "REPOGROUND-TEST-T001"})
    findings, resolution = validate_outcome_followups(truth)
    assert {item.code for item in findings} == {"STATUS_TRUTH_BUREAU_UNAVAILABLE"}
    assert resolution["status"] == "unavailable"
    assert resolution["valid_reference_count"] == 0


def test_missing_bureau_reference_is_rejected() -> None:
    truth = _truth({"kind": "bureau_task", "id": "REPOGROUND-TEST-T001"})
    snapshot = {"available": True, "tasks": {}, "candidates": {}}
    assert "STATUS_TRUTH_BUREAU_REF_MISSING" in _codes(truth, snapshot)


def test_renamed_bureau_reference_is_rejected() -> None:
    truth = _truth({"kind": "bureau_task", "id": "REPOGROUND-TEST-T001"})
    snapshot = {
        "available": True,
        "tasks": {
            "REPOGROUND-TEST-T001": {
                "canonical_id": "REPOGROUND-TEST-T002",
                "state": "ready",
            }
        },
        "candidates": {},
    }
    assert "STATUS_TRUTH_BUREAU_REF_RENAMED" in _codes(truth, snapshot)


def test_verified_bureau_followup_is_rejected_as_closed() -> None:
    truth = _truth({"kind": "bureau_task", "id": "REPOGROUND-TEST-T001"})
    snapshot = {
        "available": True,
        "tasks": {
            "REPOGROUND-TEST-T001": {
                "canonical_id": "REPOGROUND-TEST-T001",
                "state": "verified",
            }
        },
        "candidates": {},
    }
    assert "STATUS_TRUTH_BUREAU_REF_CLOSED" in _codes(truth, snapshot)


def test_superseded_bureau_followup_is_rejected() -> None:
    truth = _truth({"kind": "bureau_task", "id": "REPOGROUND-TEST-T001"})
    snapshot = {
        "available": True,
        "tasks": {
            "REPOGROUND-TEST-T001": {
                "canonical_id": "REPOGROUND-TEST-T001",
                "state": "superseded",
            }
        },
        "candidates": {},
    }
    assert "STATUS_TRUTH_BUREAU_REF_SUPERSEDED" in _codes(truth, snapshot)


def test_unknown_bureau_state_is_rejected() -> None:
    truth = _truth({"kind": "bureau_task", "id": "REPOGROUND-TEST-T001"})
    snapshot = {
        "available": True,
        "tasks": {
            "REPOGROUND-TEST-T001": {
                "canonical_id": "REPOGROUND-TEST-T001",
                "state": "mystery",
            }
        },
        "candidates": {},
    }
    assert "STATUS_TRUTH_BUREAU_REF_STATE_UNKNOWN" in _codes(truth, snapshot)


def test_wrong_coverage_key_does_not_hide_product_gap() -> None:
    truth = _truth()
    truth["open_followups"][0]["covers"] = ["system_maturity:release_readiness"]
    codes = _codes(truth)
    assert "STATUS_TRUTH_OUTCOME_FOLLOWUP_MISSING" in codes
    assert "STATUS_TRUTH_OUTCOME_FOLLOWUP_STALE" in codes
