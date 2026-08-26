from __future__ import annotations

from datetime import datetime, timedelta, timezone

from scripts.docmeta.status_truth_followups import (
    EXPECTED_POLICY,
    validate_outcome_followups,
)

NOW = datetime(2026, 8, 26, 18, 0, tzinfo=timezone.utc)
TASK_ROOT = "a" * 64


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


def _snapshot(
    *,
    tasks: dict | None = None,
    candidates: dict | None = None,
    observed_at: datetime = NOW,
    candidate_coverage_complete: bool = True,
) -> dict:
    candidate_records = candidates or {}
    return {
        "kind": "bureau_status_truth_snapshot",
        "schema_version": 1,
        "available": True,
        "observed_at": observed_at.isoformat().replace("+00:00", "Z"),
        "source": {
            "authority": "bureau-state-store",
            "task_authority": "state-store",
            "task_spec_root_sha256": TASK_ROOT,
            "candidate_coverage_complete": candidate_coverage_complete,
            "candidate_projection_source": "complete_event_scan",
            "candidate_projection_records": len(candidate_records),
        },
        "tasks": tasks or {},
        "candidates": candidate_records,
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
        now=NOW,
    )
    return {item.code for item in findings}


def test_no_task_rationale_needs_no_bureau_snapshot() -> None:
    findings, resolution = validate_outcome_followups(_truth(), now=NOW)
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
    snapshot = _snapshot(
        tasks={
            "REPOGROUND-OPEN-T001": {
                "canonical_id": "REPOGROUND-OPEN-T001",
                "state": "ready",
            }
        }
    )
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
    snapshot = _snapshot(
        tasks={
            "REPOGROUND-TEST-T001": {
                "canonical_id": "REPOGROUND-TEST-T001",
                "state": "ready",
            }
        }
    )
    findings, resolution = validate_outcome_followups(truth, snapshot, now=NOW)
    assert findings == []
    assert resolution["status"] == "verified"
    assert resolution["valid_reference_count"] == 1


def test_open_bureau_candidate_reference_is_valid() -> None:
    truth = _truth({"kind": "bureau_candidate", "id": "candidate-deadbeef"})
    snapshot = _snapshot(
        candidates={
            "candidate-deadbeef": {
                "canonical_id": "candidate-deadbeef",
                "status": "observed",
            }
        }
    )
    assert _codes(truth, snapshot) == set()


def test_bureau_reference_fails_closed_when_snapshot_is_unavailable() -> None:
    truth = _truth({"kind": "bureau_task", "id": "REPOGROUND-TEST-T001"})
    findings, resolution = validate_outcome_followups(truth, now=NOW)
    assert {item.code for item in findings} == {"STATUS_TRUTH_BUREAU_UNAVAILABLE"}
    assert resolution["status"] == "unavailable"
    assert resolution["valid_reference_count"] == 0


def test_stale_bureau_snapshot_is_rejected() -> None:
    truth = _truth({"kind": "bureau_task", "id": "REPOGROUND-TEST-T001"})
    snapshot = _snapshot(
        observed_at=NOW - timedelta(seconds=301),
        tasks={"REPOGROUND-TEST-T001": {"state": "ready"}},
    )
    findings, resolution = validate_outcome_followups(truth, snapshot, now=NOW)
    assert {item.code for item in findings} == {"STATUS_TRUTH_BUREAU_SNAPSHOT_STALE"}
    assert resolution["status"] == "stale"


def test_undated_bureau_snapshot_is_rejected() -> None:
    truth = _truth({"kind": "bureau_task", "id": "REPOGROUND-TEST-T001"})
    snapshot = _snapshot(tasks={"REPOGROUND-TEST-T001": {"state": "ready"}})
    snapshot.pop("observed_at")
    assert "STATUS_TRUTH_BUREAU_SNAPSHOT_INVALID" in _codes(truth, snapshot)


def test_future_bureau_snapshot_is_rejected() -> None:
    truth = _truth({"kind": "bureau_task", "id": "REPOGROUND-TEST-T001"})
    snapshot = _snapshot(
        observed_at=NOW + timedelta(seconds=31),
        tasks={"REPOGROUND-TEST-T001": {"state": "ready"}},
    )
    assert "STATUS_TRUTH_BUREAU_SNAPSHOT_FUTURE" in _codes(truth, snapshot)


def test_candidate_snapshot_requires_complete_projection() -> None:
    truth = _truth({"kind": "bureau_candidate", "id": "candidate-deadbeef"})
    snapshot = _snapshot(
        candidate_coverage_complete=False,
        candidates={"candidate-deadbeef": {"status": "observed"}},
    )
    assert "STATUS_TRUTH_BUREAU_SNAPSHOT_INVALID" in _codes(truth, snapshot)


def test_missing_bureau_reference_is_rejected() -> None:
    truth = _truth({"kind": "bureau_task", "id": "REPOGROUND-TEST-T001"})
    assert "STATUS_TRUTH_BUREAU_REF_MISSING" in _codes(truth, _snapshot())


def test_renamed_bureau_reference_is_rejected() -> None:
    truth = _truth({"kind": "bureau_task", "id": "REPOGROUND-TEST-T001"})
    snapshot = _snapshot(
        tasks={
            "REPOGROUND-TEST-T001": {
                "canonical_id": "REPOGROUND-TEST-T002",
                "state": "ready",
            }
        }
    )
    assert "STATUS_TRUTH_BUREAU_REF_RENAMED" in _codes(truth, snapshot)


def test_verified_bureau_followup_is_rejected_as_closed() -> None:
    truth = _truth({"kind": "bureau_task", "id": "REPOGROUND-TEST-T001"})
    snapshot = _snapshot(
        tasks={
            "REPOGROUND-TEST-T001": {
                "canonical_id": "REPOGROUND-TEST-T001",
                "state": "verified",
            }
        }
    )
    assert "STATUS_TRUTH_BUREAU_REF_CLOSED" in _codes(truth, snapshot)


def test_superseded_bureau_followup_is_rejected() -> None:
    truth = _truth({"kind": "bureau_task", "id": "REPOGROUND-TEST-T001"})
    snapshot = _snapshot(
        tasks={
            "REPOGROUND-TEST-T001": {
                "canonical_id": "REPOGROUND-TEST-T001",
                "state": "superseded",
            }
        }
    )
    assert "STATUS_TRUTH_BUREAU_REF_SUPERSEDED" in _codes(truth, snapshot)


def test_unknown_bureau_state_is_rejected() -> None:
    truth = _truth({"kind": "bureau_task", "id": "REPOGROUND-TEST-T001"})
    snapshot = _snapshot(
        tasks={
            "REPOGROUND-TEST-T001": {
                "canonical_id": "REPOGROUND-TEST-T001",
                "state": "mystery",
            }
        }
    )
    assert "STATUS_TRUTH_BUREAU_REF_STATE_UNKNOWN" in _codes(truth, snapshot)


def test_wrong_coverage_key_does_not_hide_product_gap() -> None:
    truth = _truth()
    truth["open_followups"][0]["covers"] = ["system_maturity:release_readiness"]
    codes = _codes(truth)
    assert "STATUS_TRUTH_OUTCOME_FOLLOWUP_MISSING" in codes
    assert "STATUS_TRUTH_OUTCOME_FOLLOWUP_STALE" in codes
