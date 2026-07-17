import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft7Validator, ValidationError

from merger.repoground.retrieval.audit_finding import adapt_audit_findings
from merger.repoground.retrieval.audit_lane import plan_audit_lanes

REVISION = "a" * 40
CITATION = "cit_1111111111111111"


def _schema(version="v2"):
    path = Path(__file__).parents[1] / "contracts" / f"audit-finding-set.{version}.schema.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _verification_schema():
    path = Path(__file__).parents[1] / "contracts" / "audit-verification-record.v1.schema.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _result():
    return adapt_audit_findings(
        plan_audit_lanes(["src/cache/publish.py"]),
        [{"lane_id": "cache_publication", "claim": "Pointer publication can expose stale content.", "citation_ids": [CITATION]}],
        reviewed_revision=REVISION,
        current_revision=REVISION,
        resolvable_citation_ids=[CITATION],
    )


def test_contract_binds_state_count_order():
    schema = _schema()
    result = _result()
    result["state_counts"][0], result["state_counts"][1] = result["state_counts"][1], result["state_counts"][0]
    with pytest.raises(ValidationError):
        Draft7Validator(schema).validate(result)


def test_contract_rejects_applied_verification_without_record():
    schema = _schema()
    result = _result()
    finding = result["findings"][0]
    finding["verification_applied"] = True
    finding["verification_disposition"] = "applied"
    finding["state_reason"] = "verification_decision"
    with pytest.raises(ValidationError):
        Draft7Validator(schema).validate(result)


def test_contract_rejects_blocked_disposition_without_record():
    schema = _schema()
    result = copy.deepcopy(_result())
    result["findings"][0]["verification_disposition"] = "blocked_revision"
    with pytest.raises(ValidationError):
        Draft7Validator(schema).validate(result)


def test_v2_contract_rejects_weak_negative_semantics_id():
    schema = _schema()
    result = _result()
    result["does_not_prove"] = ["A", "B", "C", "D", "E"]
    with pytest.raises(ValidationError):
        Draft7Validator(schema).validate(result)


def test_v1_contract_now_rejects_weak_negative_semantics_id():
    schema = _schema("v1")
    legacy = {
        "version": "audit_finding_set.v1",
        "authority": "diagnostic_signal",
        "risk_class": "diagnostic",
        "plan_version": "audit_lane_plan.v1",
        "reviewed_revision": REVISION,
        "current_revision": REVISION,
        "revision_fresh": True,
        "findings": [],
        "state_counts": [
            {"state": "candidate", "count": 0},
            {"state": "verified", "count": 0},
            {"state": "stale", "count": 0},
            {"state": "wrong", "count": 0},
            {"state": "unresolved", "count": 0},
        ],
        "allowed_inferences": [
            "which candidate claims were bound to selected lanes and known citations",
            "whether verifier decisions were applied under the recorded revision",
        ],
        "does_not_prove": ["A", "B", "C", "D", "E"],
    }
    with pytest.raises(ValidationError):
        Draft7Validator(schema).validate(legacy)


def _accepted_record(result):
    finding_id = result["findings"][0]["finding_id"]
    return {
        "version": "audit_verification_record.v1",
        "authority": "diagnostic_signal",
        "risk_class": "diagnostic",
        "finding_id": finding_id,
        "reviewed_revision": REVISION,
        "decision": "accepted",
        "verifier_id": "reviewer-v1",
        "note": "Evidence was independently checked.",
        "does_not_prove": [
            "repository truth",
            "review completeness",
            "freshness beyond the recorded revision",
            "permission to create issues, patches, commits, pushes, or merges",
        ],
    }


def test_verification_contract_rejects_omitted_required_negative_semantic():
    schema = _verification_schema()
    record = _accepted_record(_result())
    record["does_not_prove"].pop()
    with pytest.raises(ValidationError):
        Draft7Validator(schema).validate(record)


def test_contract_rejects_record_marked_not_supplied():
    schema = _schema()
    result = _result()
    finding = result["findings"][0]
    finding["verification_record"] = _accepted_record(result)
    with pytest.raises(ValidationError):
        Draft7Validator(schema).validate(result)


@pytest.mark.parametrize(
    ("disposition", "state", "reason"),
    [
        ("blocked_revision", "candidate", "verification_missing"),
        ("blocked_citation", "candidate", "verification_missing"),
    ],
)
def test_contract_binds_blocked_disposition_to_state_and_reason(disposition, state, reason):
    schema = _schema()
    result = _result()
    finding = result["findings"][0]
    finding["verification_record"] = _accepted_record(result)
    finding["verification_disposition"] = disposition
    finding["verification_applied"] = False
    finding["state"] = state
    finding["state_reason"] = reason
    with pytest.raises(ValidationError):
        Draft7Validator(schema).validate(result)


@pytest.mark.parametrize(
    ("decision", "wrong_state"),
    [("accepted", "wrong"), ("rejected", "verified"), ("unresolved", "verified")],
)
def test_contract_binds_applied_decision_to_output_state(decision, wrong_state):
    schema = _schema()
    result = _result()
    finding = result["findings"][0]
    record = _accepted_record(result)
    record["decision"] = decision
    finding["verification_record"] = record
    finding["verification_disposition"] = "applied"
    finding["verification_applied"] = True
    finding["state_reason"] = "verification_decision"
    finding["state"] = wrong_state
    with pytest.raises(ValidationError):
        Draft7Validator(schema).validate(result)
