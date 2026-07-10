"""
Tests for build_agent_query_session_v2().

All test data uses the REAL runtime shapes produced by this repo:

context_bundle.hits shape (from query_core.build_context_bundle()):
  {
    "hit_identity": str,
    "file": str,
    "path": str,
    "range": str,
    "score": float,
    "resolved_code_snippet": str,
    "provenance_type": "explicit" | "derived",
    "bundle_source_references": [...],
    "epistemics": {
      "provenance_type": str,
      "bundle_origin": str,          # ← string, NOT an object
      "resolver_status": str,
      "graph_status": str,
      "semantic_status": str,
      "federation_status": str,
      "uncertainty": {...},
      "interpolation": {...}
    }
  }

federation_trace shape (from federation_query.execute_federated_query() with trace=True):
  {
    "queried_bundles_total": int,
    "queried_bundles_effective": int,
    "bundle_status": {repo_id: status_str, ...},   # dict, NOT a list
    "bundle_errors": {repo_id: error_str, ...},
    "bundle_traces": {repo_id: {...}, ...}
  }
  Successful statuses: "ok", "stale"
  Skip/error statuses: "filtered_out", "bundle_path_unsupported", "bundle_path_rejected", "index_missing", "query_error"
"""

import json
from pathlib import Path

import pytest

from merger.lenskit.retrieval.session import build_agent_query_session_v2


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


# ---------------------------------------------------------------------------
# Helpers – minimal but real-shaped fixtures
# ---------------------------------------------------------------------------

def _make_hit(bundle_origin: str, hit_id: str = "c1") -> dict:
    """Build a minimal context_bundle hit with the real epistemics shape."""
    return {
        "hit_identity": hit_id,
        "file": "src/main.py",
        "path": "src/main.py",
        "range": "L1-L5",
        "score": 0.9,
        "resolved_code_snippet": "def main(): pass",
        "provenance_type": "explicit",
        "bundle_source_references": ["src/main.py"],
        "epistemics": {
            "provenance_type": "explicit",
            "bundle_origin": bundle_origin,   # string, confirmed by schema + query_core.py
            "resolver_status": "resolved_explicit",
            "graph_status": "unknown",
            "semantic_status": "unknown",
            "federation_status": "federated" if bundle_origin != "local" else "local",
            "uncertainty": {
                "explicit_provenance": True,
                "graph_used": False,
                "semantic_supported": False,
            },
            "interpolation": {"used": False, "reason": None},
        },
    }


def _make_context_bundle(hits: list) -> dict:
    return {"query": "test query", "hits": hits}


def _make_federation_trace(bundle_status: dict, total: int = None, effective: int = None) -> dict:
    """Build a real federation_trace with bundle_status dict (not a list)."""
    successful = sum(1 for s in bundle_status.values() if s in ("ok", "stale"))
    return {
        "queried_bundles_total": total if total is not None else len(bundle_status),
        "queried_bundles_effective": effective if effective is not None else successful,
        "bundle_status": bundle_status,
        "bundle_errors": {},
        "bundle_traces": {},
    }


# ---------------------------------------------------------------------------
# Tests – projected context bundle (single source)
# ---------------------------------------------------------------------------

def test_build_session_from_projected_context_bundle():
    """resolved_bundles comes from context_bundle.hits[*].epistemics.bundle_origin (string)."""
    bundle = _make_context_bundle([
        _make_hit("proj-r1", "c1"),
        _make_hit("proj-r2", "c2"),
    ])
    session = build_agent_query_session_v2("test query", context_bundle=bundle)

    assert session["query"] == "test query"
    assert session["hits_count"] == 2
    assert session["resolved_bundles"] == ["proj-r1", "proj-r2"]
    assert session["session_meta"]["context_source"] == "projected"
    assert session["session_meta"]["federation_bundle_count"] is None
    assert session["session_meta"]["federation_effective_count"] is None


def test_build_session_deduplicates_bundle_origins():
    """Multiple hits from the same bundle produce exactly one resolved_bundle entry."""
    bundle = _make_context_bundle([
        _make_hit("proj-r1", "c1"),
        _make_hit("proj-r1", "c2"),
        _make_hit("proj-r1", "c3"),
    ])
    session = build_agent_query_session_v2("dedup query", context_bundle=bundle)

    assert session["resolved_bundles"] == ["proj-r1"]
    assert session["hits_count"] == 3


def test_build_session_empty_context_bundle():
    """Zero hits → empty resolved_bundles, hits_count = 0."""
    session = build_agent_query_session_v2("empty", context_bundle={"query": "empty", "hits": []})

    assert session["hits_count"] == 0
    assert session["resolved_bundles"] == []
    assert session["session_meta"]["context_source"] == "projected"


# ---------------------------------------------------------------------------
# Tests – federation_trace (single source, no context_bundle)
# ---------------------------------------------------------------------------

def test_build_session_from_federation_trace_ok_bundles():
    """
    resolved_bundles from federation_trace.bundle_status dict.
    Only "ok" and "stale" bundles are included — no "queried_bundles" list exists.
    """
    trace = _make_federation_trace({
        "repo-a": "ok",
        "repo-b": "ok",
        "repo-c": "filtered_out",
        "repo-d": "index_missing",
    })
    session = build_agent_query_session_v2("federated query", federation_trace=trace)

    assert session["session_meta"]["context_source"] == "federated"
    assert session["hits_count"] == 0  # no context_bundle
    # Only ok bundles resolved
    assert set(session["resolved_bundles"]) == {"repo-a", "repo-b"}
    # federation meta preserved
    assert session["session_meta"]["federation_bundle_count"] == 4
    assert session["session_meta"]["federation_effective_count"] == 2


def test_build_session_stale_bundle_is_resolved():
    """A "stale" bundle still ran the query — it must appear in resolved_bundles."""
    trace = _make_federation_trace({
        "repo-fresh": "ok",
        "repo-stale": "stale",   # query executed, index may be outdated
        "repo-broken": "query_error",
    })
    session = build_agent_query_session_v2("stale test", federation_trace=trace)

    assert "repo-fresh" in session["resolved_bundles"]
    assert "repo-stale" in session["resolved_bundles"]
    assert "repo-broken" not in session["resolved_bundles"]


def test_build_session_all_bundles_failed():
    """If every bundle errored or was filtered, resolved_bundles is empty."""
    trace = _make_federation_trace({
        "repo-x": "query_error",
        "repo-y": "filtered_out",
        "repo-z": "bundle_path_unsupported",
        "repo-rejected": "bundle_path_rejected",
    })
    session = build_agent_query_session_v2("all bad", federation_trace=trace)

    assert session["resolved_bundles"] == []


# ---------------------------------------------------------------------------
# Tests – combined projected + federated (both sources)
# ---------------------------------------------------------------------------

def test_build_session_combined_sources():
    """resolved_bundles is the union of context_bundle origins and federation successes."""
    bundle = _make_context_bundle([
        _make_hit("repo-a", "c1"),
        _make_hit("repo-b", "c2"),
    ])
    trace = _make_federation_trace({
        "repo-b": "ok",   # overlap with context bundle
        "repo-c": "ok",   # additional federated bundle
        "repo-d": "filtered_out",
    })
    session = build_agent_query_session_v2("combined", context_bundle=bundle, federation_trace=trace)

    assert session["session_meta"]["context_source"] == "both"
    assert set(session["resolved_bundles"]) == {"repo-a", "repo-b", "repo-c"}
    assert session["hits_count"] == 2


def test_build_session_combined_deduplicates_across_sources():
    """A bundle appearing in both sources appears only once in resolved_bundles."""
    bundle = _make_context_bundle([_make_hit("shared-repo", "c1")])
    trace = _make_federation_trace({"shared-repo": "ok"})

    session = build_agent_query_session_v2("dedup combined", context_bundle=bundle, federation_trace=trace)

    assert session["resolved_bundles"].count("shared-repo") == 1
    assert len(session["resolved_bundles"]) == 1


# ---------------------------------------------------------------------------
# Tests – edge cases
# ---------------------------------------------------------------------------

def test_build_session_no_inputs():
    """Both sources absent → session_meta.context_source == 'none', empty bundles."""
    session = build_agent_query_session_v2("bare query")

    assert session["query"] == "bare query"
    assert session["resolved_bundles"] == []
    assert session["hits_count"] == 0
    assert session["session_meta"]["context_source"] == "none"
    assert session["session_meta"]["federation_bundle_count"] is None


def test_build_session_resolved_bundles_sorted():
    """resolved_bundles is sorted for determinism."""
    bundle = _make_context_bundle([
        _make_hit("zzz-repo", "c1"),
        _make_hit("aaa-repo", "c2"),
        _make_hit("mmm-repo", "c3"),
    ])
    session = build_agent_query_session_v2("sort test", context_bundle=bundle)

    assert session["resolved_bundles"] == ["aaa-repo", "mmm-repo", "zzz-repo"]


# ---------------------------------------------------------------------------
# Tests – defensive / negative edges
# ---------------------------------------------------------------------------

def test_build_session_bundle_status_not_dict_logs_warning(caplog):
    """
    bundle_status that is not a dict must not crash the builder.
    A warning must be logged and federated resolved_bundles must stay empty.
    """
    import logging
    trace = {
        "queried_bundles_total": 1,
        "queried_bundles_effective": 1,
        "bundle_status": ["repo-a", "repo-b"],  # wrong type — list, not dict
        "bundle_errors": {},
        "bundle_traces": {},
    }
    with caplog.at_level(logging.WARNING, logger="merger.lenskit.retrieval.session"):
        session = build_agent_query_session_v2("bad trace", federation_trace=trace)

    assert session["resolved_bundles"] == []
    assert any("bundle_status" in rec.message for rec in caplog.records)


def test_build_session_bundle_origin_non_string_ignored():
    """
    Hits where epistemics.bundle_origin is missing, None, or a non-string value
    must be silently ignored — only valid non-empty strings enter resolved_bundles.
    """
    bundle = {
        "query": "edge test",
        "hits": [
            # valid
            _make_hit("valid-repo", "c1"),
            # bundle_origin is None
            {**_make_hit("x", "c2"), "epistemics": {**_make_hit("x", "c2")["epistemics"], "bundle_origin": None}},
            # bundle_origin is an object (not a string)
            {**_make_hit("x", "c3"), "epistemics": {**_make_hit("x", "c3")["epistemics"], "bundle_origin": {"repo_id": "wrong"}}},
            # epistemics key missing entirely
            {"hit_identity": "c4", "file": "f.py", "path": "f.py", "range": "L1-L1",
             "score": 0.1, "resolved_code_snippet": "", "provenance_type": "derived",
             "bundle_source_references": []},
        ],
    }
    session = build_agent_query_session_v2("non-string origins", context_bundle=bundle)

    assert session["resolved_bundles"] == ["valid-repo"]
    assert session["hits_count"] == 4


def test_build_session_empty_repo_id_in_bundle_status_ignored():
    """Empty-string keys in bundle_status must not be included in resolved_bundles."""
    trace = _make_federation_trace({
        "real-repo": "ok",
        "": "ok",  # empty key — must be ignored
    })
    session = build_agent_query_session_v2("empty key", federation_trace=trace)

    assert session["resolved_bundles"] == ["real-repo"]
    assert "" not in session["resolved_bundles"]


# ---------------------------------------------------------------------------
# Schema contract validation
# ---------------------------------------------------------------------------

def test_build_session_output_validates_against_schema():
    """The output must conform to agent-query-session.v2.schema.json."""
    try:
        _require_module()
    except RuntimeError:
        pytest.skip("jsonschema not available")

    schema_path = (
        Path(__file__).parent.parent / "contracts" / "agent-query-session.v2.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    bundle = _make_context_bundle([_make_hit("proj-r1", "c1"), _make_hit("proj-r2", "c2")])
    trace = _make_federation_trace({"proj-r1": "ok", "proj-r3": "stale", "proj-r4": "filtered_out"})
    session = build_agent_query_session_v2("schema test", context_bundle=bundle, federation_trace=trace)

    jsonschema.validate(instance=session, schema=schema)

# ---------------------------------------------------------------------------
# Backward Compatibility Tests (v1)
# ---------------------------------------------------------------------------

def test_build_agent_query_session_v1_backward_compatibility():
    """Ensure the old v1 builder still produces output valid against v1 schema."""
    from merger.lenskit.retrieval.session import build_agent_query_session
    try:
        _require_module()
    except RuntimeError:
        pytest.skip("jsonschema not available")

    schema_path = (
        Path(__file__).parent.parent / "contracts" / "agent-query-session.v1.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    # Simulate a raw result shape typical of v1
    mock_request = {"q": "legacy query"}
    mock_result = {
        "results": [
            {"repo_id": "legacy-repo-1"},
            {"repo_id": "legacy-repo-2"}
        ],
        "warnings": ["Legacy warning"]
    }

    session = build_agent_query_session(
        request_contract=mock_request,
        result=mock_result,
        query_trace_ref="trace.json",
        context_bundle_ref="bundle.json",
        diagnostics_ref=None
    )

    # Validate core fields
    assert session["request"] == mock_request
    assert set(session["resolved_bundles"]) == {"legacy-repo-1", "legacy-repo-2"}
    assert session["refs"]["query_trace_ref"] == "trace.json"
    assert session["warnings"] == ["Legacy warning"]

    # Validate against v1 schema
    jsonschema.validate(instance=session, schema=schema)


# ---------------------------------------------------------------------------
# Provenance field tests (session_authority, context_source, artifact_refs,
# claim_boundaries)
# ---------------------------------------------------------------------------

def test_builder_emits_session_authority():
    """build_agent_query_session_v2 always emits session_authority == 'agent_context_projection'."""
    session = build_agent_query_session_v2("authority test")
    assert session["session_authority"] == "agent_context_projection"


def test_builder_emits_session_authority_with_all_inputs():
    """session_authority is constant regardless of inputs."""
    bundle = _make_context_bundle([_make_hit("repo-a")])
    trace = _make_federation_trace({"repo-a": "ok"})
    session = build_agent_query_session_v2("q", context_bundle=bundle, federation_trace=trace)
    assert session["session_authority"] == "agent_context_projection"


def test_builder_emits_claim_boundaries():
    """build_agent_query_session_v2 always emits claim_boundaries with proves and does_not_prove."""
    session = build_agent_query_session_v2("claim test")
    cb = session["claim_boundaries"]
    assert isinstance(cb, dict)
    assert isinstance(cb["proves"], list) and len(cb["proves"]) >= 1
    assert isinstance(cb["does_not_prove"], list) and len(cb["does_not_prove"]) >= 1


def test_builder_claim_boundaries_content():
    """claim_boundaries content expresses provenance limits."""
    session = build_agent_query_session_v2("content test")
    does_not_prove = " ".join(session["claim_boundaries"]["does_not_prove"])
    assert "live repository state" in does_not_prove
    assert "canonical repository content" in does_not_prove


def test_builder_top_level_context_source_projected():
    """context_source (top-level) is 'projected' when only context_bundle is provided."""
    bundle = _make_context_bundle([_make_hit("repo-a")])
    session = build_agent_query_session_v2("ctx test", context_bundle=bundle)
    assert session["context_source"] == "projected"
    # session_meta.context_source stays on its own enum ("projected" is shared)
    assert session["session_meta"]["context_source"] == "projected"


def test_builder_top_level_context_source_federated():
    """context_source is 'federated' when only federation_trace is provided."""
    trace = _make_federation_trace({"repo-a": "ok"})
    session = build_agent_query_session_v2("fed test", federation_trace=trace)
    assert session["context_source"] == "federated"


def test_builder_top_level_context_source_mixed():
    """context_source is 'mixed' when both context_bundle and federation_trace are provided."""
    bundle = _make_context_bundle([_make_hit("repo-a")])
    trace = _make_federation_trace({"repo-a": "ok"})
    session = build_agent_query_session_v2("mixed test", context_bundle=bundle, federation_trace=trace)
    assert session["context_source"] == "mixed"
    # Internal session_meta still uses "both"
    assert session["session_meta"]["context_source"] == "both"


def test_builder_top_level_context_source_unknown():
    """context_source is 'unknown' when no sources are provided."""
    session = build_agent_query_session_v2("bare query")
    assert session["context_source"] == "unknown"
    assert session["session_meta"]["context_source"] == "none"


def test_builder_artifact_refs_are_null_when_ids_unavailable():
    """artifact_refs are all null when no IDs are supplied (default)."""
    session = build_agent_query_session_v2("null ids test")
    refs = session["artifact_refs"]
    assert refs["query_trace_id"] is None
    assert refs["context_bundle_id"] is None
    assert refs["agent_query_session_id"] is None


def test_builder_artifact_refs_set_when_ids_provided():
    """artifact_refs carry the supplied IDs without modification."""
    session = build_agent_query_session_v2(
        "ids test",
        query_trace_id="qart-abc",
        context_bundle_id="qart-def",
        agent_query_session_id="qart-ghi",
    )
    refs = session["artifact_refs"]
    assert refs["query_trace_id"] == "qart-abc"
    assert refs["context_bundle_id"] == "qart-def"
    assert refs["agent_query_session_id"] == "qart-ghi"


def test_builder_artifact_refs_partial_ids():
    """artifact_refs can have a mix of set and null IDs."""
    session = build_agent_query_session_v2("partial ids", query_trace_id="qart-trace-1")
    refs = session["artifact_refs"]
    assert refs["query_trace_id"] == "qart-trace-1"
    assert refs["context_bundle_id"] is None
    assert refs["agent_query_session_id"] is None


def test_builder_output_with_provenance_validates_against_v2_schema():
    """Full provenance output (with IDs) validates against agent-query-session.v2.schema.json."""
    try:
        _require_module()
    except RuntimeError:
        pytest.skip("jsonschema not available")

    schema_path = (
        Path(__file__).parent.parent / "contracts" / "agent-query-session.v2.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    bundle = _make_context_bundle([_make_hit("repo-x", "c1")])
    session = build_agent_query_session_v2(
        "schema provenance test",
        context_bundle=bundle,
        query_trace_id="qart-trace-111",
        context_bundle_id="qart-bundle-222",
    )
    jsonschema.validate(instance=session, schema=schema)

