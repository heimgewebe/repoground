from __future__ import annotations

import pytest

from scripts.docmeta.capture_bureau_status_snapshot import build_snapshot


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
    with pytest.raises(ValueError, match="StateStore task authority"):
        build_snapshot(projection, candidates)
