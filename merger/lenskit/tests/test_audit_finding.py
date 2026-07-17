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


def _plan():
    return plan_audit_lanes(["src/cache/publish.py"], review_query="race stale cache")


def _candidate():
    return {
        "lane_id": "cache_publication",
        "claim": "Pointer publication can expose stale content.",
        "citation_ids": [CIT_A, CIT_B],
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


def test_finding_id_is_stable_across_whitespace_and_citation_order():
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
    assert first.startswith("af_")


def test_fresh_unverified_candidate_remains_candidate():
    result = _adapt()
    finding = result["findings"][0]
    assert finding["state"] == "candidate"
    assert finding["state_reason"] == "verification_missing"
    assert result["summary"]["candidate"] == 1


def test_fresh_resolved_verdict_can_be_applied():
    finding_id = make_audit_finding_id(
        "cache_publication", _candidate()["claim"], [CIT_A, CIT_B]
    )
    result = _adapt(
        verifier_verdicts=[
            {
                "finding_id": finding_id,
                "state": "verified",
                "verifier_id": "independent-reviewer-v1",
                "note": "Citation ranges reproduce the claimed publication window.",
            }
        ]
    )
    finding = result["findings"][0]
    assert finding["state"] == "verified"
    assert finding["verifier_verdict_applied"] is True
    assert result["summary"]["verified"] == 1


def test_stale_revision_overrides_but_preserves_verifier_verdict():
    finding_id = make_audit_finding_id(
        "cache_publication", _candidate()["claim"], [CIT_A, CIT_B]
    )
    result = _adapt(
        current_revision=REV_B,
        verifier_verdicts=[
            {
                "finding_id": finding_id,
                "state": "verified",
                "verifier_id": "reviewer",
                "note": "Verdict belongs to the older revision.",
            }
        ],
    )
    finding = result["findings"][0]
    assert finding["state"] == "stale"
    assert finding["verifier_verdict"]["state"] == "verified"
    assert finding["verifier_verdict_applied"] is False
    assert result["revision_fresh"] is False


def test_unresolved_citation_overrides_verifier_verdict():
    finding_id = make_audit_finding_id(
        "cache_publication", _candidate()["claim"], [CIT_A, CIT_B]
    )
    result = _adapt(
        resolvable_citation_ids=[CIT_A],
        verifier_verdicts=[
            {
                "finding_id": finding_id,
                "state": "verified",
                "verifier_id": "reviewer",
                "note": "One address is no longer resolvable.",
            }
        ],
    )
    finding = result["findings"][0]
    assert finding["state"] == "unresolved"
    assert finding["unresolved_citation_ids"] == [CIT_B]
    assert finding["verifier_verdict_applied"] is False


@pytest.mark.parametrize("state", ["wrong", "unresolved"])
def test_supported_negative_verdicts_are_preserved(state):
    finding_id = make_audit_finding_id(
        "cache_publication", _candidate()["claim"], [CIT_A, CIT_B]
    )
    result = _adapt(
        verifier_verdicts=[
            {
                "finding_id": finding_id,
                "state": state,
                "verifier_id": "reviewer",
                "note": "Independent result.",
            }
        ]
    )
    assert result["findings"][0]["state"] == state
    assert result["findings"][0]["verifier_verdict_applied"] is True


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
        {"lane_id": "cache_publication", "claim": "", "citation_ids": [CIT_A]},
        {"lane_id": "cache_publication", "claim": "x", "citation_ids": []},
        {"lane_id": "cache_publication", "claim": "x", "citation_ids": ["bad"]},
        {"lane_id": "cache_publication", "claim": "x", "citation_ids": [CIT_A, CIT_A]},
        "not-an-object",
    ],
)
def test_rejects_malformed_or_unselected_candidates(candidate):
    with pytest.raises(AuditFindingError):
        _adapt(candidates=[candidate])


def test_rejects_duplicate_semantic_candidates():
    with pytest.raises(AuditFindingError, match="duplicate semantic candidate"):
        _adapt(candidates=[_candidate(), _candidate()])


@pytest.mark.parametrize("revision", ["", "A" * 40, "a" * 39, "g" * 40])
def test_rejects_invalid_revisions(revision):
    with pytest.raises(AuditFindingError):
        _adapt(reviewed_revision=revision)


def test_rejects_verdict_for_unknown_finding():
    with pytest.raises(AuditFindingError, match="unknown finding"):
        _adapt(
            verifier_verdicts=[
                {
                    "finding_id": "af_0000000000000000",
                    "state": "verified",
                    "verifier_id": "reviewer",
                    "note": "No matching candidate.",
                }
            ]
        )


def test_rejects_duplicate_verdicts():
    finding_id = make_audit_finding_id(
        "cache_publication", _candidate()["claim"], [CIT_A, CIT_B]
    )
    verdict = {
        "finding_id": finding_id,
        "state": "verified",
        "verifier_id": "reviewer",
        "note": "Repeated verdict.",
    }
    with pytest.raises(AuditFindingError, match="duplicate verifier verdict"):
        _adapt(verifier_verdicts=[verdict, verdict])


def test_output_validates_against_contract():
    schema_path = (
        Path(__file__).parents[1] / "contracts" / "audit-finding-set.v1.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    result = _adapt()
    Draft7Validator.check_schema(schema)
    Draft7Validator(schema).validate(result)


def test_forbidden_inferences_block_authority_upgrade():
    result = _adapt()
    forbidden = " ".join(result["forbidden_inferences"])
    assert "repository truth" in forbidden
    assert "review completeness" in forbidden
    assert "merges" in forbidden
