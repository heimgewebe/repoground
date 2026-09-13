import json
from pathlib import Path

import jsonschema
import pytest

from merger.repoground.core.ask_context import (
    _resolved_ranges_with_budget,
    render_ask_context_pack_text,
)

CONTEXT_SCHEMA = (
    Path(__file__).parent.parent
    / "contracts"
    / "repobrief-ask-context-pack.v1.schema.json"
)

HISTORICAL_AUTHORITY = {
    "classification": "historical_only",
    "frontmatter_present": True,
    "establishes_current_state": False,
    "does_not_establish": [
        "current_state",
        "current_architecture",
        "current_service_necessity",
        "preferred_access_path",
    ],
    "status": "deprecated",
}

POINT_IN_TIME_AUTHORITY = {
    "classification": "point_in_time_observation",
    "frontmatter_present": True,
    "establishes_current_state": False,
    "does_not_establish": [
        "current_state",
        "current_architecture",
        "current_service_necessity",
        "preferred_access_path",
    ],
    "temporal_scope": "point_in_time",
    "observed_at": "2026-09-12T12:34:56Z",
    "role": "runtime_observation",
}


def _projected_range(source_authority: dict) -> dict:
    query_result = {
        "resolved_evidence": {
            "hits": [
                {
                    "artifact_role": "canonical_md",
                    "chunk_id": "authority-test",
                    "range_status": "resolved",
                    "range_ref": {"ref": "authority-test"},
                    "range": {"text": "historical evidence"},
                    "source_authority": source_authority,
                }
            ]
        }
    }
    ranges, used_bytes, _used_characters, truncated, omissions = (
        _resolved_ranges_with_budget(query_result, 100)
    )
    assert used_bytes == len("historical evidence".encode("utf-8"))
    assert truncated is False
    assert omissions == []
    assert len(ranges) == 1
    return ranges[0]


@pytest.mark.parametrize(
    "authority",
    [HISTORICAL_AUTHORITY, POINT_IN_TIME_AUTHORITY],
)
def test_ask_resolved_range_preserves_source_authority_and_renders_caveats(authority):
    item = _projected_range(authority)

    assert item["source_authority"] == authority
    rendered = render_ask_context_pack_text({"resolved_ranges": [item]})
    assert f"source_authority: {authority['classification']}" in rendered
    for field in (
        "status",
        "canonicality",
        "role",
        "temporal_scope",
        "observed_at",
        "last_reviewed",
    ):
        if field in authority:
            assert f"source_authority.{field}: {authority[field]}" in rendered
    for caveat in authority["does_not_establish"]:
        assert f"does_not_establish: {caveat}" in rendered


def test_ask_resolved_range_fails_closed_when_authority_is_missing():
    query_result = {
        "resolved_evidence": {
            "hits": [
                {
                    "artifact_role": "canonical_md",
                    "chunk_id": "missing-authority",
                    "range_status": "resolved",
                    "range_ref": {"ref": "missing-authority"},
                    "range": {"text": "legacy evidence"},
                }
            ]
        }
    }
    ranges, *_ = _resolved_ranges_with_budget(query_result, 100)
    authority = ranges[0]["source_authority"]
    assert authority["classification"] == "unclassified"
    assert authority["frontmatter_present"] is False
    assert authority["does_not_establish"] == [
        "current_state_without_fresh_verification"
    ]


def test_evidence_contracts_require_source_authority():
    contracts = Path(__file__).parent.parent / "contracts"
    query_result = json.loads(
        (contracts / "query-result.v1.schema.json").read_text(encoding="utf-8")
    )
    context_bundle = json.loads(
        (contracts / "query-context-bundle.v1.schema.json").read_text(encoding="utf-8")
    )
    ask_context = json.loads(CONTEXT_SCHEMA.read_text(encoding="utf-8"))

    assert "source_authority" in query_result["properties"]["results"]["items"][
        "required"
    ]
    assert "source_authority" in context_bundle["properties"]["hits"]["items"][
        "required"
    ]
    assert "source_authority" in ask_context["properties"]["resolved_ranges"][
        "items"
    ]["required"]


def test_ask_context_contract_enforces_source_authority_invariants():
    schema = json.loads(CONTEXT_SCHEMA.read_text(encoding="utf-8"))
    authority_schema = schema["definitions"]["sourceAuthority"]

    jsonschema.validate(instance=HISTORICAL_AUTHORITY, schema=authority_schema)
    jsonschema.validate(instance=POINT_IN_TIME_AUTHORITY, schema=authority_schema)

    missing_caveats = dict(HISTORICAL_AUTHORITY)
    missing_caveats["does_not_establish"] = ["current_state"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=missing_caveats, schema=authority_schema)

    contradictory = {
        "classification": "current_candidate",
        "frontmatter_present": True,
        "establishes_current_state": None,
        "does_not_establish": ["current_state_without_fresh_verification"],
        "status": "deprecated",
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=contradictory, schema=authority_schema)
