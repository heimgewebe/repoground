import json
import pytest
from pathlib import Path

# Use the strict degradation pattern according to epistemic limits in memory
try:
    import jsonschema
    from jsonschema import ValidationError
except ImportError:
    jsonschema = None
    ValidationError = None

def _require_module():
    if jsonschema is None:
        raise RuntimeError("jsonschema not installed")

def test_agent_session_schema_valid():
    try:
        _require_module()
    except RuntimeError:
        pytest.skip("jsonschema not installed")

    schema_path = Path(__file__).parent.parent / "contracts" / "agent-query-session.v1.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    # Simulate a valid query session
    mock_session = {
        "request": {
            "query": "hello world",
            "k": 10,
            "output_profile": "agent_minimal",
            "explain": True
        },
        "resolved_bundles": ["r1", "r2"],
        "refs": {
            "query_trace_ref": "traces/trace_123.json",
            "context_bundle_ref": "bundles/bundle_123.json",
            "diagnostics_ref": None,
            "integrity": {
                "query_trace_sha256": "abcdef",
                "context_bundle_sha256": "123456"
            }
        },
        "environment": {
            "lenskit_version": "1.0",
            "index_path": "/tmp/idx",
            "timestamp_utc": "2024-01-01T00:00:00Z"
        },
        "warnings": ["Low result coverage"]
    }

    # Should not raise
    jsonschema.validate(instance=mock_session, schema=schema)


def test_agent_session_schema_invalid_missing_ref():
    try:
        _require_module()
    except RuntimeError:
        pytest.skip("jsonschema not installed")

    schema_path = Path(__file__).parent.parent / "contracts" / "agent-query-session.v1.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    mock_session = {
        "request": {"query": "hello"},
        "resolved_bundles": [],
        "refs": {
            "query_trace_ref": "traces/123.json"
            # Missing context_bundle_ref
        },
        "warnings": []
    }

    with pytest.raises(ValidationError):
        jsonschema.validate(instance=mock_session, schema=schema)


# ---------------------------------------------------------------------------
# v2 schema provenance field tests
# ---------------------------------------------------------------------------

def _v2_schema():
    schema_path = Path(__file__).parent.parent / "contracts" / "agent-query-session.v2.schema.json"
    return json.loads(schema_path.read_text(encoding="utf-8"))


def _minimal_v2_session(**overrides):
    """Minimal valid v2 session without optional provenance fields."""
    base = {
        "query": "test",
        "resolved_bundles": ["repo-a"],
        "hits_count": 1,
        "session_meta": {
            "context_source": "projected",
            "federation_bundle_count": None,
            "federation_effective_count": None,
        },
    }
    base.update(overrides)
    return base


def test_agent_session_v2_accepts_minimal_without_provenance_fields():
    """v2 schema is valid without the new optional provenance fields (backward compat)."""
    try:
        _require_module()
    except RuntimeError:
        pytest.skip("jsonschema not installed")

    jsonschema.validate(instance=_minimal_v2_session(), schema=_v2_schema())


def test_agent_session_v2_accepts_full_provenance_fields():
    """v2 schema accepts all four new optional provenance fields together."""
    try:
        _require_module()
    except RuntimeError:
        pytest.skip("jsonschema not installed")

    session = _minimal_v2_session(
        session_authority="agent_context_projection",
        context_source="projected",
        artifact_refs={
            "query_trace_id": "qart-abc123",
            "context_bundle_id": "qart-def456",
            "agent_query_session_id": None,
        },
        claim_boundaries={
            "proves": ["This session was built from these query results."],
            "does_not_prove": [
                "This session does not prove live repository state.",
            ],
        },
    )
    jsonschema.validate(instance=session, schema=_v2_schema())


def test_agent_session_v2_accepts_null_artifact_ids():
    """artifact_refs with all null IDs is valid."""
    try:
        _require_module()
    except RuntimeError:
        pytest.skip("jsonschema not installed")

    session = _minimal_v2_session(
        session_authority="agent_context_projection",
        context_source="unknown",
        artifact_refs={
            "query_trace_id": None,
            "context_bundle_id": None,
            "agent_query_session_id": None,
        },
        claim_boundaries={
            "proves": ["Built from query results."],
            "does_not_prove": ["Does not prove live state."],
        },
    )
    jsonschema.validate(instance=session, schema=_v2_schema())


def test_agent_session_v2_rejects_wrong_session_authority():
    """session_authority must be exactly 'agent_context_projection' (const)."""
    try:
        _require_module()
    except RuntimeError:
        pytest.skip("jsonschema not installed")

    session = _minimal_v2_session(session_authority="canonical_repository")
    with pytest.raises(ValidationError):
        jsonschema.validate(instance=session, schema=_v2_schema())


def test_agent_session_v2_rejects_unknown_context_source():
    """Top-level context_source must be one of the allowed enum values."""
    try:
        _require_module()
    except RuntimeError:
        pytest.skip("jsonschema not installed")

    session = _minimal_v2_session(context_source="live_index")
    with pytest.raises(ValidationError):
        jsonschema.validate(instance=session, schema=_v2_schema())


def test_agent_session_v2_rejects_claim_boundaries_missing_proves():
    """claim_boundaries requires both 'proves' and 'does_not_prove' arrays."""
    try:
        _require_module()
    except RuntimeError:
        pytest.skip("jsonschema not installed")

    session = _minimal_v2_session(
        claim_boundaries={
            "does_not_prove": ["Does not prove live state."],
            # "proves" missing
        }
    )
    with pytest.raises(ValidationError):
        jsonschema.validate(instance=session, schema=_v2_schema())


def test_agent_session_v2_rejects_extra_artifact_ref_properties():
    """artifact_refs has additionalProperties: false — extra keys must be rejected."""
    try:
        _require_module()
    except RuntimeError:
        pytest.skip("jsonschema not installed")

    session = _minimal_v2_session(
        artifact_refs={
            "query_trace_id": None,
            "context_bundle_id": None,
            "agent_query_session_id": None,
            "unknown_id": "surprise",
        }
    )
    with pytest.raises(ValidationError):
        jsonschema.validate(instance=session, schema=_v2_schema())


def test_agent_session_v2_rejects_partial_artifact_refs():
    """artifact_refs must contain all three known keys when present."""
    try:
        _require_module()
    except RuntimeError:
        pytest.skip("jsonschema not installed")

    session = _minimal_v2_session(
        artifact_refs={
            "context_bundle_id": "qart-context-only"
        }
    )
    with pytest.raises(ValidationError):
        jsonschema.validate(instance=session, schema=_v2_schema())


def test_agent_session_v2_context_source_enum_values():
    """All four allowed context_source values are accepted by the schema."""
    try:
        _require_module()
    except RuntimeError:
        pytest.skip("jsonschema not installed")

    schema = _v2_schema()
    for value in ("projected", "federated", "mixed", "unknown"):
        session = _minimal_v2_session(context_source=value)
        jsonschema.validate(instance=session, schema=schema)

