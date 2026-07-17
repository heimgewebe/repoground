import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft7Validator, ValidationError

from merger.lenskit.retrieval.audit_finding import adapt_audit_findings
from merger.lenskit.retrieval.audit_lane import plan_audit_lanes

REVISION = "a" * 40
CITATION = "cit_1111111111111111"


def _schema():
    path = Path(__file__).parents[1] / "contracts" / "audit-finding-set.v1.schema.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _result():
    return adapt_audit_findings(
        plan_audit_lanes(["src/cache/publish.py"]),
        [
            {
                "lane_id": "cache_publication",
                "claim": "Pointer publication can expose stale content.",
                "citation_ids": [CITATION],
            }
        ],
        reviewed_revision=REVISION,
        current_revision=REVISION,
        resolvable_citation_ids=[CITATION],
    )


def test_contract_binds_state_count_order():
    schema = _schema()
    result = _result()
    result["state_counts"][0], result["state_counts"][1] = (
        result["state_counts"][1],
        result["state_counts"][0],
    )

    with pytest.raises(ValidationError):
        Draft7Validator(schema).validate(result)


def test_contract_rejects_applied_verification_without_record():
    schema = _schema()
    result = _result()
    finding = result["findings"][0]
    finding["verification_applied"] = True
    finding["state_reason"] = "verifier_verdict"

    with pytest.raises(ValidationError):
        Draft7Validator(schema).validate(result)


def test_contract_rejects_verifier_reason_without_applied_record():
    schema = _schema()
    result = copy.deepcopy(_result())
    result["findings"][0]["state_reason"] = "verifier_verdict"

    with pytest.raises(ValidationError):
        Draft7Validator(schema).validate(result)
