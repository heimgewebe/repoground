import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft7Validator, ValidationError

from merger.lenskit.retrieval.audit_finding import adapt_audit_findings
from merger.lenskit.retrieval.audit_lane import plan_audit_lanes

REVISION = "a" * 40
CITATION = "cit_1111111111111111"


def _schema(version="v2"):
    path = Path(__file__).parents[1] / "contracts" / f"audit-finding-set.{version}.schema.json"
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


def test_v2_contract_rejects_weak_negative_semantics():
    schema = _schema()
    result = _result()
    result["does_not_prove"] = ["A", "B", "C", "D", "E"]
    with pytest.raises(ValidationError):
        Draft7Validator(schema).validate(result)


def test_v1_contract_now_rejects_weak_negative_semantics():
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
