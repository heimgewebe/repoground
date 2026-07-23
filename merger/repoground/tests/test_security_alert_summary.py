import json
from pathlib import Path

import pytest
from jsonschema import Draft7Validator

from merger.repoground.retrieval.security_alert_summary import (
    SecurityAlertSummaryError,
    classify_security_alert_state,
    known_states,
)


def _schema():
    path = Path(__file__).parents[1] / "contracts" / "security-alert-summary.v1.schema.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _validate(summary):
    Draft7Validator(_schema()).validate(summary)
    return summary


def test_known_states_are_the_closed_fail_closed_vocabulary():
    assert known_states() == (
        "clean",
        "alerts_present",
        "unavailable",
        "unauthorized",
        "unknown",
    )


def test_zero_alerts_from_sarif_alone_is_clean():
    summary = _validate(
        classify_security_alert_state(
            sarif_evidence={"available": True, "alert_count": 0},
        )
    )
    assert summary["state"] == "clean"
    assert summary["state_reason"] == "sarif_result_count"
    assert summary["evidence_source"] == "sarif"
    assert summary["alert_count"] == 0
    assert summary["fail_closed"] is False


def test_zero_alerts_from_api_alone_is_clean():
    summary = _validate(
        classify_security_alert_state(
            api_evidence={"status_code": 200, "open_alert_count": 0, "paginated": True, "page_count": 1},
        )
    )
    assert summary["state"] == "clean"
    assert summary["state_reason"] == "api_result_count"
    assert summary["evidence_source"] == "api"
    assert summary["fail_closed"] is False


def test_zero_alerts_from_api_without_pagination_proof_is_unknown():
    summary = _validate(
        classify_security_alert_state(
            api_evidence={"status_code": 200, "open_alert_count": 0},
        )
    )
    assert summary["state"] == "unknown"
    assert summary["state_reason"] == "api_zero_count_pagination_unproven"
    assert summary["fail_closed"] is True


def test_sarif_alerts_present():
    summary = _validate(
        classify_security_alert_state(
            sarif_evidence={"available": True, "alert_count": 3},
        )
    )
    assert summary["state"] == "alerts_present"
    assert summary["alert_count"] == 3
    assert summary["fail_closed"] is True


def test_api_alerts_present():
    summary = _validate(
        classify_security_alert_state(
            api_evidence={"status_code": 200, "open_alert_count": 5},
        )
    )
    assert summary["state"] == "alerts_present"
    assert summary["alert_count"] == 5
    assert summary["fail_closed"] is True


def test_api_404_alone_is_unavailable_not_clean():
    """The motivating bug: a live 404 must never be read as zero alerts."""
    summary = _validate(
        classify_security_alert_state(
            api_evidence={"status_code": 404, "open_alert_count": None},
        )
    )
    assert summary["state"] == "unavailable"
    assert summary["state_reason"] == "api_unavailable"
    assert summary["alert_count"] is None
    assert summary["fail_closed"] is True


def test_sarif_clean_dominates_a_concurrent_api_404():
    """Deterministic CI-local SARIF evidence outranks an unreachable live API."""
    summary = _validate(
        classify_security_alert_state(
            sarif_evidence={"available": True, "alert_count": 0},
            api_evidence={"status_code": 404, "open_alert_count": None},
        )
    )
    assert summary["state"] == "clean"
    assert summary["state_reason"] == "sarif_result_count"
    assert summary["evidence_source"] == "sarif"


def test_sarif_unavailable_falls_back_to_api_403_unauthorized():
    summary = _validate(
        classify_security_alert_state(
            sarif_evidence={"available": False, "alert_count": None},
            api_evidence={"status_code": 403, "open_alert_count": None},
        )
    )
    assert summary["state"] == "unauthorized"
    assert summary["state_reason"] == "api_unauthorized"


@pytest.mark.parametrize("status_code", [401, 403])
def test_api_unauthorized_status_codes(status_code):
    summary = _validate(
        classify_security_alert_state(
            api_evidence={"status_code": status_code, "open_alert_count": None},
        )
    )
    assert summary["state"] == "unauthorized"
    assert summary["fail_closed"] is True


def test_sarif_unavailable_and_no_api_is_unavailable():
    summary = _validate(
        classify_security_alert_state(
            sarif_evidence={"available": False, "alert_count": None},
        )
    )
    assert summary["state"] == "unavailable"
    assert summary["state_reason"] == "sarif_unavailable"
    assert summary["evidence_source"] == "sarif"


def test_no_evidence_supplied_fails_closed_to_unknown_not_clean():
    summary = _validate(classify_security_alert_state())
    assert summary["state"] == "unknown"
    assert summary["state_reason"] == "no_evidence_supplied"
    assert summary["evidence_source"] == "none"
    assert summary["fail_closed"] is True


def test_disagreeing_definitive_sources_fail_closed_to_unknown():
    summary = _validate(
        classify_security_alert_state(
            sarif_evidence={"available": True, "alert_count": 0},
            api_evidence={"status_code": 200, "open_alert_count": 2},
        )
    )
    assert summary["state"] == "unknown"
    assert summary["state_reason"] == "sarif_api_state_disagreement"
    assert summary["fail_closed"] is True


def test_documents_least_privilege_required_permissions():
    summary = _validate(classify_security_alert_state(sarif_evidence={"available": True, "alert_count": 0}))
    assert "security-events: read" in summary["required_permissions"]["api"]
    assert "write" not in summary["required_permissions"]["api"].split("security-events: read")[0]


@pytest.mark.parametrize(
    "sarif_evidence",
    [
        {"available": "yes", "alert_count": 0},
        {"available": True, "alert_count": -1},
        {"available": True, "alert_count": None},
        {"available": False, "alert_count": 0},
        {"available": True, "alert_count": 0, "extra": 1},
    ],
)
def test_invalid_sarif_evidence_is_rejected(sarif_evidence):
    with pytest.raises(SecurityAlertSummaryError):
        classify_security_alert_state(sarif_evidence=sarif_evidence)


@pytest.mark.parametrize(
    "api_evidence",
    [
        {"status_code": 200, "open_alert_count": None},
        {"status_code": 200, "open_alert_count": -1},
        {"status_code": 404, "open_alert_count": 0},
        {"status_code": 999, "open_alert_count": None},
        {"status_code": 200},
    ],
)
def test_invalid_api_evidence_is_rejected(api_evidence):
    with pytest.raises(SecurityAlertSummaryError):
        classify_security_alert_state(api_evidence=api_evidence)


def test_repository_and_commit_sha_binding_and_validation():
    summary = _validate(
        classify_security_alert_state(
            sarif_evidence={
                "available": True,
                "alert_count": 0,
                "repository": "owner/repo",
                "commit_sha": "abc123def456",
            },
            repository="owner/repo",
            commit_sha="abc123def456",
        )
    )
    assert summary["repository"] == "owner/repo"
    assert summary["commit_sha"] == "abc123def456"


def test_mismatched_repository_or_commit_sha_is_rejected():
    with pytest.raises(SecurityAlertSummaryError, match="repository mismatch"):
        classify_security_alert_state(
            sarif_evidence={"available": True, "alert_count": 0, "repository": "owner/repo-a"},
            api_evidence={"status_code": 200, "open_alert_count": 0, "repository": "owner/repo-b"},
        )

    with pytest.raises(SecurityAlertSummaryError, match="commit_sha mismatch"):
        classify_security_alert_state(
            sarif_evidence={"available": True, "alert_count": 0, "commit_sha": "sha1"},
            api_evidence={"status_code": 200, "open_alert_count": 0, "commit_sha": "sha2"},
        )

    with pytest.raises(SecurityAlertSummaryError, match="does not match requested repository"):
        classify_security_alert_state(
            sarif_evidence={"available": True, "alert_count": 0, "repository": "owner/repo-a"},
            repository="owner/repo-b",
        )


def test_stale_evidence_is_rejected():
    with pytest.raises(SecurityAlertSummaryError, match="sarif_evidence is marked stale"):
        classify_security_alert_state(
            sarif_evidence={"available": True, "alert_count": 0, "stale": True}
        )

    with pytest.raises(SecurityAlertSummaryError, match="api_evidence is marked stale"):
        classify_security_alert_state(
            api_evidence={"status_code": 200, "open_alert_count": 0, "stale": True}
        )


def test_paginated_api_evidence_is_supported_and_validated():
    summary = _validate(
        classify_security_alert_state(
            api_evidence={
                "status_code": 200,
                "open_alert_count": 45,
                "paginated": True,
                "page_count": 2,
            }
        )
    )
    assert summary["state"] == "alerts_present"
    assert summary["api_evidence"]["paginated"] is True
    assert summary["api_evidence"]["page_count"] == 2

    with pytest.raises(SecurityAlertSummaryError, match="paginated must be a boolean"):
        classify_security_alert_state(
            api_evidence={"status_code": 200, "open_alert_count": 0, "paginated": "yes"}
        )

    with pytest.raises(SecurityAlertSummaryError, match="page_count must be a non-negative integer"):
        classify_security_alert_state(
            api_evidence={"status_code": 200, "open_alert_count": 0, "page_count": -1}
        )



def test_sarif_unavailable_api_clean_with_pagination_is_clean():
    summary = _validate(classify_security_alert_state(
        sarif_evidence={"available": False, "alert_count": None},
        api_evidence={"status_code": 200, "open_alert_count": 0, "paginated": True, "page_count": 1},
    ))
    assert summary["state"] == "clean"
    assert summary["state_reason"] == "api_result_count"
    assert summary["evidence_source"] == "sarif+api"


@pytest.mark.parametrize("source", ["sarif", "api"])
@pytest.mark.parametrize("stale", ["yes", 1, "false", 0])
def test_non_boolean_stale_is_rejected(source, stale):
    evidence = ({"available": True, "alert_count": 0, "stale": stale} if source == "sarif" else {"status_code": 200, "open_alert_count": 0, "paginated": True, "stale": stale})
    with pytest.raises(SecurityAlertSummaryError, match="stale must be a boolean"):
        classify_security_alert_state(**{f"{source}_evidence": evidence})
