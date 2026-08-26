from __future__ import annotations

from scripts.docmeta.check_status_truth_ci import defer_external_bureau_resolution


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
