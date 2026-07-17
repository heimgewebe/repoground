import json
from pathlib import Path

import pytest
from jsonschema import Draft7Validator

from merger.lenskit.retrieval.audit_finding import (
    AuditFindingError,
    adapt_audit_findings,
    make_audit_finding_id,
)
from merger.lenskit.retrieval.audit_lane import plan_audit_lanes

REV_A = "a" * 40
REV_B = "b" * 40
CIT_A = "cit_1111111111111111"
CIT_B = "cit_2222222222222222"
VERIFICATION_NEG = [
    "repository truth",
    "review completeness",
    "freshness beyond the recorded revision",
    "permission to create issues, patches, commits, pushes, or merges",
]


def _plan():
    return plan_audit_lanes(["src/cache/publish.py"], review_query="race stale cache")


def _candidate():
    return {
        "lane_id": "cache_publication",
        "claim": "Pointer publication can expose stale content.",
        "citation_ids": [CIT_A, CIT_B],
    }


def _finding_id():
    return make_audit_finding_id(
        "cache_publication", _candidate()["claim"], [CIT_A, CIT_B]
    )


def _record(decision="accepted", revision=REV_A):
    return {
        "version": "audit_verification_record.v1",
        "authority": "diagnostic_signal",
        "risk_class": "diagnostic",
        "finding_id": _finding_id(),
        "reviewed_revision": revision,
        "decision": decision,
        "verifier_id": "independent-reviewer-v1",
        "note": "Citation ranges reproduce the recorded review decision.",
        "does_not_prove": list(VERIFICATION_NEG),
    }


def _adapt(**overrides):
    kwargs = {
        "plan": _plan(),
        "candidates": [_candidate()],
        "reviewed_revision": REV_A,
        "current_revision": REV_A,
        "resolvable_citation_ids": [CIT_A, CIT_B],
    }
    kwargs.update(overrides)
    return adapt_audit_findings(**kwargs)


def _count(result, state):
    return next(row["count"] for row in result["state_counts"] if row["state"] == state)


def test_finding_id_is_stable_and_version_domain_separated():
    first = make_audit_finding_id(
        "cache_publication",
        "Pointer  publication\ncan expose stale content.",
        [CIT_B, CIT_A],
    )
    second = make_audit_finding_id(
        "cache_publication",
        "Pointer publication can expose stale content.",
        [CIT_A, CIT_B],
    )
    assert first == second
    assert first.startswith("af2_")
    assert _adapt()["finding_id_algorithm"] == "lenskit.audit_finding_id.v2"


def test_fresh_unverified_candidate_remains_candidate():
    result = _adapt()
    finding = result["findings"][0]
    assert finding["state"] == "candidate"
    assert finding["state_reason"] == "verification_missing"
    assert finding["verification_disposition"] == "not_supplied"
    assert _count(result, "candidate") == 1


def test_fresh_resolved_neutral_decision_can_be_applied():
    result = _adapt(verification_records=[_record()])
    finding = result["findings"][0]
    assert finding["state"] == "verified"
    assert finding["verification_applied"] is True
    assert finding["verification_disposition"] == "applied"
    assert finding["verification_record"]["decision"] == "accepted"


def test_stale_revision_overrides_but_preserves_record_explicitly():
    result = _adapt(current_revision=REV_B, verification_records=[_record()])
    finding = result["findings"][0]
    assert finding["state"] == "stale"
    assert finding["verification_record"]["decision"] == "accepted"
    assert finding["verification_applied"] is False
    assert finding["verification_disposition"] == "blocked_revision"


def test_unresolved_citation_overrides_but_preserves_record_explicitly():
    result = _adapt(
        resolvable_citation_ids=[CIT_A],
        verification_records=[_record()],
    )
    finding = result["findings"][0]
    assert finding["state"] == "unresolved"
    assert finding["unresolved_citation_ids"] == [CIT_B]
    assert finding["verification_disposition"] == "blocked_citation"


@pytest.mark.parametrize(
    ("decision", "state"),
    [("rejected", "wrong"), ("unresolved", "unresolved")],
)
def test_neutral_decisions_map_to_output_states(decision, state):
    result = _adapt(verification_records=[_record(decision)])
    assert result["findings"][0]["state"] == state


def test_verification_record_revision_must_match_adapter_revision():
    with pytest.raises(AuditFindingError, match="does not match"):
        _adapt(verification_records=[_record(revision=REV_B)])


@pytest.mark.parametrize(
    "mutation",
    [
        {"version": "wrong"},
        {"authority": "canonical_content"},
        {"decision": "verified"},
        {"finding_id": "af2_0000000000000000"},
        {"does_not_prove": ["A", "B", "C", "D"]},
    ],
)
def test_rejects_invalid_verification_contracts(mutation):
    record = _record()
    record.update(mutation)
    with pytest.raises(AuditFindingError):
        _adapt(verification_records=[record])


def test_accepts_verification_negative_semantics_in_any_order():
    record = _record()
    record["does_not_prove"].reverse()
    result = _adapt(verification_records=[record])
    assert result["findings"][0]["verification_applied"] is True


def test_rejects_oversized_candidate_and_verification_text():
    candidate = _candidate()
    candidate["claim"] = "x" * 4097
    with pytest.raises(AuditFindingError, match="4096"):
        _adapt(candidates=[candidate])

    record = _record()
    record["verifier_id"] = "v" * 257
    with pytest.raises(AuditFindingError, match="256"):
        _adapt(verification_records=[record])

    record = _record()
    record["note"] = "n" * 2049
    with pytest.raises(AuditFindingError, match="2048"):
        _adapt(verification_records=[record])


def test_rejects_duplicate_registry_and_bounded_candidate_overflow():
    with pytest.raises(AuditFindingError, match="duplicates"):
        _adapt(resolvable_citation_ids=[CIT_A, CIT_A])
    with pytest.raises(AuditFindingError, match="at most 200"):
        _adapt(candidates=[_candidate()] * 201)


def test_output_order_is_stable_by_finding_id():
    second = {
        "lane_id": "concurrency_toctou",
        "claim": "Lock acquisition can race with pointer replacement.",
        "citation_ids": [CIT_A],
    }
    first = adapt_audit_findings(
        _plan(),
        [_candidate(), second],
        reviewed_revision=REV_A,
        current_revision=REV_A,
        resolvable_citation_ids=[CIT_A, CIT_B],
    )
    reversed_input = adapt_audit_findings(
        _plan(),
        [second, _candidate()],
        reviewed_revision=REV_A,
        current_revision=REV_A,
        resolvable_citation_ids=[CIT_A, CIT_B],
    )
    assert first == reversed_input


@pytest.mark.parametrize(
    "candidate",
    [
        {"lane_id": "unknown", "claim": "x", "citation_ids": [CIT_A]},
        {"lane_id": "Bad-Lane", "claim": "x", "citation_ids": [CIT_A]},
        {"lane_id": "cache_publication", "claim": "", "citation_ids": [CIT_A]},
        {"lane_id": "cache_publication", "claim": "x", "citation_ids": []},
        {"lane_id": "cache_publication", "claim": "x", "citation_ids": ["bad"]},
        {"lane_id": "cache_publication", "claim": "x", "citation_ids": [CIT_A, CIT_A]},
        {"lane_id": "cache_publication", "claim": "x", "citation_ids": [1]},
        {"lane_id": "cache_publication", "claim": "x", "citation_ids": [CIT_A], "hidden": "x"},
        "not-an-object",
    ],
)
def test_rejects_malformed_or_unselected_candidates(candidate):
    with pytest.raises(AuditFindingError):
        _adapt(candidates=[candidate])


@pytest.mark.parametrize("candidates", [None, "candidate", 123])
def test_rejects_malformed_candidate_collections(candidates):
    with pytest.raises(AuditFindingError):
        _adapt(candidates=candidates)


def test_rejects_duplicate_semantic_candidates():
    with pytest.raises(AuditFindingError, match="duplicate semantic candidate"):
        _adapt(candidates=[_candidate(), _candidate()])


@pytest.mark.parametrize("revision", ["", "A" * 40, "a" * 39, "g" * 40])
def test_rejects_invalid_revisions(revision):
    with pytest.raises(AuditFindingError):
        _adapt(reviewed_revision=revision)


def test_output_and_verification_record_validate_against_contracts():
    root = Path(__file__).parents[1] / "contracts"
    output_schema = json.loads((root / "audit-finding-set.v2.schema.json").read_text())
    record_schema = json.loads((root / "audit-verification-record.v1.schema.json").read_text())
    record = _record()
    result = _adapt(verification_records=[record])
    Draft7Validator.check_schema(output_schema)
    Draft7Validator.check_schema(record_schema)
    Draft7Validator(record_schema).validate(record)
    Draft7Validator(output_schema).validate(result)


def test_rejects_unhashable_verification_negative_semantics_as_contract_error():
    record = _record()
    record["does_not_prove"] = [
        "repository truth",
        "review completeness",
        ["not", "hashable"],
        "permission to create issues, patches, commits, pushes, or merges",
    ]
    with pytest.raises(AuditFindingError, match="does_not_prove"):
        _adapt(verification_records=[record])
