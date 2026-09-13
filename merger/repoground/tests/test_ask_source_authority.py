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
    for caveat in authority["does_not_establish"]:
        assert f"does_not_establish: {caveat}" in rendered


def test_ask_context_contract_enforces_historical_authority_caveats():
    schema = json.loads(CONTEXT_SCHEMA.read_text(encoding="utf-8"))
    authority_schema = schema["properties"]["resolved_ranges"]["items"]["properties"][
        "source_authority"
    ]

    jsonschema.validate(instance=HISTORICAL_AUTHORITY, schema=authority_schema)

    invalid = dict(HISTORICAL_AUTHORITY)
    invalid["does_not_establish"] = ["current_state"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=invalid, schema=authority_schema)
