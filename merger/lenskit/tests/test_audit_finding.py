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


def _finding_id():
    return make_audit_finding_id(
        "cache_publication", _candidate()["claim"], [CIT_A, CIT_B]
    )


def _verdict(state="verified"):
    return {
        "finding_id": _finding_id(),
        "state": state,
        "verifier_id": "independent-reviewer-v1",
        "note": "Citation ranges reproduce the recorded review decision.",
    }


def _count(result, state):
    return next(row["count"] for row in result["state_counts"] if row["state"] == state)


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
    assert _count(result, "candidate") == 1


def test_fresh_resolved_verdict_can_be_applied():
    result = _adapt(verifier_verdicts=[_verdict()])
    finding = result["findings"][0]
    assert finding["state"] == "verified"
    assert finding["verification_applied"] is True
    assert _count(result, "verified") == 1


def test_stale_revision_overrides_but_preserves_verifier_decision():
    result = _adapt(current_revision=REV_B, verifier_verdicts=[_verdict()])
    finding = result["findings"][0]
    assert finding["state"] == "stale"
    assert finding["verification_record"]["state"] == "verified"
    assert finding["verification_applied"] is False
    assert result["revision_fresh"] is False


def test_unresolved_citation_overrides_verifier_decision():
    result = _adapt(
        resolvable_citation_ids=[CIT_A],
        verifier_verdicts=[_verdict()],
    )
    finding = result["findings"][0]
    assert finding["state"] == "unresolved"
    assert finding["unresolved_citation_ids"] == [CIT_B]
    assert finding["verification_applied"] is False


@pytest.mark.parametrize("state", ["wrong", "unresolved"])
def test_supported_negative_verdicts_are_preserved(state):
    result = _adapt(verifier_verdicts=[_verdict(state)])
    assert result["findings"][0]["state"] == state
    assert result["findings"][0]["verification_applied"] is True


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
        {
            "lane_id": "cache_publication",
            "claim": "x",
            "citation_ids": [CIT_A],
            "hidden": "not admitted",
        },
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


def test_rejects_plan_with_wrong_authority():
    plan = _plan()
    plan["authority"] = "diagnostic_signal"
    with pytest.raises(AuditFindingError, match="authority"):
        _adapt(plan=plan)


def test_rejects_plan_with_invalid_lane_identifier():
    plan = _plan()
    plan["lanes"][0]["id"] = "Bad-Lane"
    with pytest.raises(AuditFindingError, match="identifier"):
        _adapt(plan=plan)


def test_rejects_verdict_for_unknown_finding():
    verdict = _verdict()
    verdict["finding_id"] = "af_0000000000000000"
    with pytest.raises(AuditFindingError, match="unknown finding"):
        _adapt(verifier_verdicts=[verdict])


def test_rejects_invalid_verdict_finding_identifier():
    verdict = _verdict()
    verdict["finding_id"] = "finding-1"
    with pytest.raises(AuditFindingError, match="identifier"):
        _adapt(verifier_verdicts=[verdict])


def test_rejects_duplicate_verdicts():
    verdict = _verdict()
    with pytest.raises(AuditFindingError, match="duplicate verifier verdict"):
        _adapt(verifier_verdicts=[verdict, verdict])


@pytest.mark.parametrize("verdicts", [None, "verdict", 123])
def test_rejects_malformed_verdict_collections(verdicts):
    with pytest.raises(AuditFindingError):
        _adapt(verifier_verdicts=verdicts)


def test_rejects_extra_verdict_fields():
    verdict = _verdict()
    verdict["hidden"] = "not admitted"
    with pytest.raises(AuditFindingError, match="verdict fields"):
        _adapt(verifier_verdicts=[verdict])


def test_rejects_invalid_citation_registry():
    with pytest.raises(AuditFindingError):
        _adapt(resolvable_citation_ids=[CIT_A, 1])


def test_rejects_oversized_claim_and_citation_set():
    candidate = _candidate()
    candidate["claim"] = "x" * 8193
    with pytest.raises(AuditFindingError, match="exceeds"):
        _adapt(candidates=[candidate])

    candidate = _candidate()
    candidate["citation_ids"] = [f"cit_{index:016x}" for index in range(65)]
    with pytest.raises(AuditFindingError, match="at most"):
        _adapt(candidates=[candidate])


def test_output_validates_against_contract():
    schema_path = (
        Path(__file__).parents[1] / "contracts" / "audit-finding-set.v1.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    result = _adapt()
    Draft7Validator.check_schema(schema)
    Draft7Validator(schema).validate(result)


def test_does_not_prove_blocks_authority_upgrade():
    result = _adapt()
    boundary = " ".join(result["does_not_prove"])
    assert "repository truth" in boundary
    assert "review completeness" in boundary
    assert "merges" in boundary
