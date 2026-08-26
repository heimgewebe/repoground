from __future__ import annotations

from scripts.docmeta.capture_bureau_status_snapshot import build_snapshot
from scripts.docmeta.check_status_truth_ci import defer_external_bureau_resolution


def test_build_snapshot_uses_state_store_projection() -> None:
    projection = {
        "state_store": {"available": True},
        "task_authority": {
            "status": "state-store",
            "task_spec_root_sha256": "a" * 64,
        },
        "tasks": [{"task_id": "T1", "effective_state": "ready"}],
    }
    candidates = {
        "coverage_complete": True,
        "projection_source": "state-store",
        "summary": {
            "latest_candidates": [
                {
                    "record": {
                        "candidate_id": "candidate-deadbeef",
                        "status": "observed",
                    }
                }
            ]
        },
    }
    result = build_snapshot(
        projection,
        candidates,
        observed_at="2026-08-26T18:00:00Z",
    )
    assert result["tasks"]["T1"]["state"] == "ready"
    assert result["candidates"]["candidate-deadbeef"]["status"] == "observed"
    assert result["source"]["candidate_coverage_complete"] is True


def test_build_snapshot_rejects_non_authoritative_task_projection() -> None:
    projection = {
        "state_store": {"available": True},
        "task_authority": {
            "status": "legacy-git-bootstrap",
            "task_spec_root_sha256": "a" * 64,
        },
        "tasks": [],
    }
    candidates = {"coverage_complete": True, "summary": {"latest_candidates": []}}
    try:
        build_snapshot(projection, candidates)
    except ValueError as exc:
        assert "StateStore task authority" in str(exc)
    else:
        raise AssertionError("non-authoritative task projection must be rejected")


def test_ci_defers_only_bureau_unavailable() -> None:
    report = {
        "status": "fail",
        "summary": {"finding_count": 2},
        "findings": [
            {
                "code": "STATUS_TRUTH_BUREAU_UNAVAILABLE",
                "path": "x",
                "detail": "T1",
            },
            {"code": "OTHER", "path": "x", "detail": "bad"},
        ],
        "bureau_reference_resolution": {"status": "unavailable"},
        "does_not_establish": [],
    }
    result = defer_external_bureau_resolution(report)
    assert result["status"] == "fail"
    assert [item["code"] for item in result["findings"]] == ["OTHER"]
    assert result["summary"]["deferred_bureau_reference_count"] == 1
    assert result["bureau_reference_resolution"]["status"] == "deferred_external"


def test_ci_can_pass_when_only_external_bureau_resolution_is_unavailable() -> None:
    report = {
        "status": "fail",
        "summary": {"finding_count": 1},
        "findings": [
            {
                "code": "STATUS_TRUTH_BUREAU_UNAVAILABLE",
                "path": "x",
                "detail": "T1",
            }
        ],
        "bureau_reference_resolution": {"status": "unavailable"},
        "does_not_establish": [],
    }
    result = defer_external_bureau_resolution(report)
    assert result["status"] == "pass"
    assert result["findings"] == []
    assert result["summary"]["deferred_bureau_reference_count"] == 1
