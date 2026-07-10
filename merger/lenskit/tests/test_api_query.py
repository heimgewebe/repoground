import pytest
from fastapi.testclient import TestClient
from pathlib import Path
from merger.lenskit.service.app import app
from merger.lenskit.service import app as service_app
import json
from merger.lenskit.retrieval import index_db

# jsonschema is an optional dependency; tests that need it skip gracefully.
try:
    import jsonschema as _jsonschema
except ImportError:
    _jsonschema = None

@pytest.fixture
def mini_index(tmp_path):
    dump_path = tmp_path / "dump.json"
    chunk_path = tmp_path / "chunks.jsonl"
    db_path = tmp_path / ".index.sqlite"

    chunk_data = [
        {
            "chunk_id": "c1", "repo_id": "r1", "path": "src/main.py",
            "content": "def main():\n    print('hello world')\n    return 0",
            "start_line": 10, "end_line": 12, "layer": "core", "artifact_type": "code", "content_sha256": "h1"
        },
        {
            "chunk_id": "c2", "repo_id": "r1", "path": "src/main.py",
            "content": "def helper():\n    pass",
            "start_line": 15, "end_line": 16, "layer": "core", "artifact_type": "code", "content_sha256": "h2"
        },
    ]
    with chunk_path.open("w", encoding="utf-8") as f:
        for c in chunk_data:
            f.write(json.dumps(c) + "\n")

    dump_path.write_text(json.dumps({"dummy": "data"}), encoding="utf-8")
    index_db.build_index(dump_path, chunk_path, db_path)
    return db_path

client = TestClient(app)

def setup_test_artifact(mini_index=None, merges_dir_name=None, key="sqlite_index", filename=None):
    hub_path = Path("/tmp")
    if mini_index and merges_dir_name:
        hub_path = Path(mini_index.parent.parent)

    service_app.init_service(hub_path=hub_path, token="test_token")
    from merger.lenskit.service.models import Artifact, JobRequest
    from merger.lenskit.service.app import state

    req = JobRequest(repos=["repo"], level="max", mode="gesamt")

    hub_str = str(mini_index.parent.parent) if (mini_index and merges_dir_name) else "/tmp"
    merges_dir_val = merges_dir_name if merges_dir_name else (str(mini_index.parent) if mini_index else "/tmp")

    art = Artifact(
        id="test", job_id="test", hub=hub_str, repos=["repo"],
        created_at="now", paths={}, params=req, merges_dir=merges_dir_val
    )
    if key and mini_index:
        art.paths[key] = filename if filename else mini_index.name
    state.job_store.add_artifact(art)
    return art


def test_api_query_valid(mini_index):
    art = setup_test_artifact(mini_index)

    request_data = {
        "index_id": art.id,
        "q": "hello",
        "k": 1,
        "explain": True, "stale_policy": "ignore"
    }

    response = client.post("/api/query", json=request_data, headers={"Authorization": "Bearer test_token"})
    assert response.status_code == 200

    data = response.json()
    assert "hits" not in data # Because we didn't use an output profile, it returns the raw wrapper
    assert "results" in data
    assert len(data["results"]) == 1
    assert "explain" in data

    # Internal fields should not be present
    assert "_raw_content" not in str(data)

def test_api_query_agent_minimal(mini_index):
    art = setup_test_artifact(mini_index)

    request_data = {
        "index_id": art.id,
        "q": "hello",
        "k": 1,
        "output_profile": "agent_minimal",
        "explain": True, "stale_policy": "ignore"
    }

    response = client.post("/api/query", json=request_data, headers={"Authorization": "Bearer test_token"})
    assert response.status_code == 200

    data = response.json()
    assert "hits" in data
    hit = data["hits"][0]

    # Agent minimal should strip explain and surrounding_context (if null)
    assert "explain" not in hit
    assert "graph_context" not in hit
    assert "surrounding_context" not in hit

def test_api_query_context_bundle(mini_index):
    art = setup_test_artifact(mini_index)

    request_data = {
        "index_id": art.id,
        "q": "hello",
        "k": 1,
        "build_context_bundle": True, "stale_policy": "ignore"
    }

    response = client.post("/api/query", json=request_data, headers={"Authorization": "Bearer test_token"})
    assert response.status_code == 200

    data = response.json()
    assert "context_bundle" in data
    assert "hits" in data["context_bundle"]

def test_api_query_trace(mini_index):
    art = setup_test_artifact(mini_index)

    request_data = {
        "index_id": art.id,
        "q": "hello",
        "k": 1,
        "trace": True, "stale_policy": "ignore"
    }

    response = client.post("/api/query", json=request_data, headers={"Authorization": "Bearer test_token"})
    assert response.status_code == 200

    data = response.json()
    assert "query_trace" in data
    assert "timings" in data["query_trace"]

def test_api_query_invalid_params(mini_index):
    art = setup_test_artifact(mini_index)

    request_data = {
        "index_id": art.id,
        "q": "hello",
        "context_mode": "window",
        "context_window_lines": 0, "stale_policy": "ignore" # Invalid
    }

    response = client.post("/api/query", json=request_data, headers={"Authorization": "Bearer test_token"})
    assert response.status_code == 400
    assert "requires" in response.json()["detail"]

# This test verifies the generic API wrapper contract (context_bundle + query_trace)
# when trace=True, independently of specific agent session payloads.
def test_api_query_trace_wrapper(mini_index):
    art = setup_test_artifact(mini_index)

    request_data = {
        "index_id": art.id,
        "q": "hello",
        "k": 1,
        "output_profile": "agent_minimal",
        "trace": True,
        "stale_policy": "ignore"
    }

    response = client.post("/api/query", json=request_data, headers={"Authorization": "Bearer test_token"})
    assert response.status_code == 200

    data = response.json()
    assert "context_bundle" in data
    assert "query_trace" in data
    assert "query_trace" not in data["context_bundle"]

    hit = data["context_bundle"]["hits"][0]
    # Agent minimal should strip explain and surrounding_context (if null)
    assert "explain" not in hit
    assert "graph_context" not in hit
    assert "surrounding_context" not in hit

def test_api_query_relative_merges_dir(mini_index):
    art = setup_test_artifact(mini_index, merges_dir_name=mini_index.parent.name)

    request_data = {
        "index_id": art.id,
        "q": "hello",
        "k": 1,
        "explain": True, "stale_policy": "ignore"
    }

    response = client.post("/api/query", json=request_data, headers={"Authorization": "Bearer test_token"})
    assert response.status_code == 200

def test_api_query_missing_sqlite_key():
    art = setup_test_artifact(mini_index=None, key=None)

    request_data = {
        "index_id": art.id,
        "q": "hello"
    }
    response = client.post("/api/query", json=request_data, headers={"Authorization": "Bearer test_token"})
    assert response.status_code == 400
    assert "does not contain an SQLite index" in response.json()["detail"]

def test_api_query_legacy_index_sqlite_key(mini_index):
    art = setup_test_artifact(mini_index, key="index_sqlite")

    request_data = {
        "index_id": art.id,
        "q": "hello",
        "stale_policy": "ignore"
    }
    response = client.post("/api/query", json=request_data, headers={"Authorization": "Bearer test_token"})
    assert response.status_code == 200

def test_api_query_file_not_found(mini_index):
    art = setup_test_artifact(mini_index, filename="does_not_exist.sqlite")

    request_data = {
        "index_id": art.id,
        "q": "hello",
        "stale_policy": "ignore"
    }
    response = client.post("/api/query", json=request_data, headers={"Authorization": "Bearer test_token"})
    assert response.status_code == 404

def test_api_query_graph_index_not_found(mini_index):
    art = setup_test_artifact(mini_index)

    request_data = {
        "index_id": art.id,
        "q": "hello",
        "stale_policy": "ignore",
        "graph_index": "does_not_exist.json"
    }
    response = client.post("/api/query", json=request_data, headers={"Authorization": "Bearer test_token"})
    assert response.status_code == 404
    assert "graph index" in response.json()["detail"].lower()

def test_api_query_invalid_paths(mini_index):
    art = setup_test_artifact(mini_index)

    # Test backslash (Windows-style traversal attack)
    request_data = {
        "index_id": art.id,
        "q": "hello",
        "stale_policy": "ignore",
        "graph_index": "..\\evil.json"
    }
    response = client.post("/api/query", json=request_data, headers={"Authorization": "Bearer test_token"})
    assert response.status_code == 400
    assert "Invalid graph_index path" in response.json()["detail"]

    # Test colon (Drive letter attack)
    request_data["graph_index"] = "C:evil.json"
    response = client.post("/api/query", json=request_data, headers={"Authorization": "Bearer test_token"})
    assert response.status_code == 400
    assert "Invalid graph_index path" in response.json()["detail"]

    # Test slash (Linux-style traversal attack)
    request_data["graph_index"] = "../evil.json"
    response = client.post("/api/query", json=request_data, headers={"Authorization": "Bearer test_token"})
    assert response.status_code == 400
    assert "Invalid graph_index path" in response.json()["detail"]

    # Test embedding policy
    request_data["graph_index"] = None
    request_data["embedding_policy"] = "..\\evil.json"
    response = client.post("/api/query", json=request_data, headers={"Authorization": "Bearer test_token"})
    assert response.status_code == 400
    assert "Invalid embedding_policy path" in response.json()["detail"]

def test_agent_query_contract_roundtrip(mini_index):
    art = setup_test_artifact(mini_index)

    request_data = {
        "index_id": art.id,
        "q": "hello",
        "k": 1,
        "output_profile": "agent_minimal",
        "trace": True,
        "explain": True,
        "stale_policy": "ignore"
    }

    response = client.post("/api/query", json=request_data, headers={"Authorization": "Bearer test_token"})
    assert response.status_code == 200

    data = response.json()
    # Contract validation
    # Wrapper is expected since trace=True
    assert "context_bundle" in data
    assert isinstance(data["context_bundle"], dict)
    assert "query_trace" in data
    assert isinstance(data["query_trace"], dict)
    assert "hits" not in data

    bundle = data["context_bundle"]
    assert "hits" in bundle
    assert isinstance(bundle["hits"], list)

    assert len(bundle["hits"]) == 1
    hit = bundle["hits"][0]
    # Core fields must be present
    assert "hit_identity" in hit
    assert "resolved_code_snippet" in hit
    assert "path" in hit

    # Profile specific assert (agent_minimal strips explain and graph_context)
    assert "explain" not in hit
    assert "graph_context" not in hit

def test_api_query_lookup_minimal(mini_index):
    art = setup_test_artifact(mini_index)

    request_data = {
        "index_id": art.id,
        "q": "hello",
        "k": 1,
        "output_profile": "lookup_minimal",
        "explain": True, "stale_policy": "ignore"
    }

    response = client.post("/api/query", json=request_data, headers={"Authorization": "Bearer test_token"})
    assert response.status_code == 200

    data = response.json()
    assert "hits" in data
    assert "context_bundle" not in data
    assert "query_trace" not in data
    assert len(data["hits"]) == 1
    hit = data["hits"][0]
    # lookup_minimal should strip explain, graph_context, surrounding_context
    assert "explain" not in hit
    assert "graph_context" not in hit
    assert "surrounding_context" not in hit
    # But core fields are retained
    assert "resolved_code_snippet" in hit

def test_api_query_review_context(mini_index):
    art = setup_test_artifact(mini_index)

    # Case A: Explicitly request context generation so surrounding_context is definitely present
    request_data_with_context = {
        "index_id": art.id,
        "q": "hello",
        "k": 1,
        "context_mode": "window",
        "context_window_lines": 5,
        "output_profile": "review_context",
        "explain": True,
        "stale_policy": "ignore"
    }

    response_with_ctx = client.post("/api/query", json=request_data_with_context, headers={"Authorization": "Bearer test_token"})
    assert response_with_ctx.status_code == 200

    data_with_ctx = response_with_ctx.json()
    assert "hits" in data_with_ctx
    assert "context_bundle" not in data_with_ctx
    assert "query_trace" not in data_with_ctx
    assert len(data_with_ctx["hits"]) == 1
    hit_with_ctx = data_with_ctx["hits"][0]

    # review_context MUST keep explain
    assert "explain" in hit_with_ctx
    # review_context MUST strip graph_context
    assert "graph_context" not in hit_with_ctx
    # surrounding_context MUST be present and not None because we requested window context
    assert "surrounding_context" in hit_with_ctx
    assert hit_with_ctx["surrounding_context"] is not None

    # Case B: Standard query without window context, surrounding_context defaults to None internally and should be STRIPPED.
    request_data_without_context = {
        "index_id": art.id,
        "q": "hello",
        "k": 1,
        "output_profile": "review_context",
        "explain": True,
        "stale_policy": "ignore"
    }

    response_no_ctx = client.post("/api/query", json=request_data_without_context, headers={"Authorization": "Bearer test_token"})
    assert response_no_ctx.status_code == 200

    data_no_ctx = response_no_ctx.json()
    assert "hits" in data_no_ctx
    assert "context_bundle" not in data_no_ctx
    assert "query_trace" not in data_no_ctx
    assert len(data_no_ctx["hits"]) == 1
    hit_no_ctx = data_no_ctx["hits"][0]

    # explain MUST be present
    assert "explain" in hit_no_ctx
    # graph_context MUST be stripped
    assert "graph_context" not in hit_no_ctx
    # surrounding_context MUST be strictly ABSENT (since it was None and should be removed)
    assert "surrounding_context" not in hit_no_ctx


def test_api_query_lookup_minimal_with_trace(mini_index):
    art = setup_test_artifact(mini_index)

    request_data = {
        "index_id": art.id,
        "q": "hello",
        "k": 1,
        "output_profile": "lookup_minimal",
        "trace": True,
        "explain": True,
        "stale_policy": "ignore"
    }

    response = client.post("/api/query", json=request_data, headers={"Authorization": "Bearer test_token"})
    assert response.status_code == 200

    data = response.json()
    assert "context_bundle" in data
    assert isinstance(data["context_bundle"], dict)
    assert "query_trace" in data
    assert isinstance(data["query_trace"], dict)
    assert "hits" not in data

    bundle = data["context_bundle"]
    assert "hits" in bundle

    assert len(bundle["hits"]) == 1
    hit = bundle["hits"][0]
    # lookup_minimal should strip explain, graph_context, surrounding_context
    assert "explain" not in hit
    assert "graph_context" not in hit
    assert "surrounding_context" not in hit
    # But core fields are retained
    assert "resolved_code_snippet" in hit

def test_api_query_review_context_with_trace(mini_index):
    art = setup_test_artifact(mini_index)

    # Use context_mode="window" to guarantee surrounding_context is generated
    request_data = {
        "index_id": art.id,
        "q": "hello",
        "k": 1,
        "context_mode": "window",
        "context_window_lines": 5,
        "output_profile": "review_context",
        "trace": True,
        "explain": True,
        "stale_policy": "ignore"
    }

    response = client.post("/api/query", json=request_data, headers={"Authorization": "Bearer test_token"})
    assert response.status_code == 200

    data = response.json()
    assert "context_bundle" in data
    assert isinstance(data["context_bundle"], dict)
    assert "query_trace" in data
    assert isinstance(data["query_trace"], dict)
    assert "hits" not in data

    bundle = data["context_bundle"]
    assert "hits" in bundle

    assert len(bundle["hits"]) == 1
    hit = bundle["hits"][0]
    # review_context MUST keep explain
    assert "explain" in hit
    # review_context MUST strip graph_context
    assert "graph_context" not in hit
    # surrounding_context MUST be present and not None because we requested window context
    assert "surrounding_context" in hit
    assert hit["surrounding_context"] is not None

def test_agent_response_surfaces_uncertainty(mini_index):
    art = setup_test_artifact(mini_index)

    request_data = {
        "index_id": art.id,
        "q": "hello",
        "k": 1,
        "output_profile": "review_context",
        "trace": True,
        "explain": True,
        "stale_policy": "ignore"
    }

    response = client.post("/api/query", json=request_data, headers={"Authorization": "Bearer test_token"})
    assert response.status_code == 200

    data = response.json()
    assert "context_bundle" in data
    bundle = data["context_bundle"]
    assert "hits" in bundle

    assert len(bundle["hits"]) == 1
    hit = bundle["hits"][0]

    # Check for epistemic object markers
    assert "epistemics" in hit
    epist = hit["epistemics"]

    # Values check strictly grounded in fixture data
    assert epist["provenance_type"] == "derived" # Fixture provides chunks without explicit range_ref
    assert epist["bundle_origin"] == "r1"  # Derived from local repository
    assert epist["resolver_status"] == "unresolved" # The fixture chunks lack structural data to generate a derived_range_ref
    assert epist["graph_status"] == "unknown" # No active graph index in this fixture
    assert epist["semantic_status"] == "unknown" # Semantic search is strictly unknown/unproven
    assert epist["federation_status"] == "local" # No federation bundle present

    unc = epist["uncertainty"]
    assert unc["explicit_provenance"] is False # Because provenance is derived
    assert unc["graph_used"] is False # Not used in this fixture
    assert unc["semantic_supported"] is False # Not used in this fixture

    interp = epist["interpolation"]
    # The fixture chunks lack structural data (start_byte, end_byte) to generate a derived_range_ref.
    # Therefore, no interpolation could be performed.
    assert interp["used"] is False
    assert interp["reason"] is None

def test_agent_response_surfaces_uncertainty_contrasts():
    # Strict grammar test for epistemic status translations within build_context_bundle.
    from merger.lenskit.retrieval.query_core import build_context_bundle
    import sqlite3

    with sqlite3.connect(":memory:") as conn:
        mock_hits = [
            {
                "chunk_id": "c1", "repo_id": "r1", "path": "file1.py",
                "range": "1-10", "score": 1.0, "why": {},
                "range_ref": {"file_path": "file1.py", "start_byte": 0} # Explicit
            },
            {
                "chunk_id": "c2", "repo_id": "r1", "path": "file2.py",
                "range": "11-20", "score": 0.8, "why": {},
                "derived_range_ref": {"file_path": "file2.py", "start_byte": 100} # Derived + successfully interpolated
            },
            {
                "chunk_id": "c3", "repo_id": "r1", "path": "file3.py",
                "range": "21-30", "score": 0.5, "why": {}
                # Derived but unresolved (no range_ref, no derived_range_ref)
            }
        ]

        bundle = build_context_bundle("hello", mock_hits, {"c1": "c", "c2": "c", "c3": "c"}, conn, context_mode="exact")

        assert len(bundle["hits"]) == 3

        # 1. Explicit Hit
        hit1_epist = bundle["hits"][0]["epistemics"]
        assert hit1_epist["provenance_type"] == "explicit"
        assert hit1_epist["resolver_status"] == "resolved_explicit"
        assert hit1_epist["interpolation"]["used"] is False

        # 2. Derived + Interpolated Hit
        hit2_epist = bundle["hits"][1]["epistemics"]
        assert hit2_epist["provenance_type"] == "derived"
        assert hit2_epist["resolver_status"] == "resolved_derived"
        assert hit2_epist["interpolation"]["used"] is True
        assert hit2_epist["interpolation"]["reason"] == "derived_from_source"

        # 3. Derived + Unresolved Hit
        hit3_epist = bundle["hits"][2]["epistemics"]
        assert hit3_epist["provenance_type"] == "derived"
        assert hit3_epist["resolver_status"] == "unresolved"
        assert hit3_epist["interpolation"]["used"] is False
        assert hit3_epist["interpolation"]["reason"] is None


# This test verifies the semantic payload of the inline v2 agent_query_session
# within the API trace wrapper (including resolved bundles).
# It explicitly does not validate the CLI v1 artifact contract (i.e. `refs`).
def test_api_query_agent_session_trace_exists(mini_index):
    art = setup_test_artifact(mini_index)

    request_data = {
        "index_id": art.id,
        "q": "hello",
        "k": 1,
        "output_profile": "agent_minimal",
        "trace": True,
        "stale_policy": "ignore"
    }

    response = client.post("/api/query", json=request_data, headers={"Authorization": "Bearer test_token"})
    assert response.status_code == 200

    data = response.json()
    assert "context_bundle" in data
    assert "agent_query_session" in data

    session = data["agent_query_session"]
    assert "query" in session
    assert session["query"] == "hello"
    assert "resolved_bundles" in session
    assert isinstance(session["resolved_bundles"], list)
    assert "r1" in session["resolved_bundles"]
    assert "hits_count" in session
    assert "session_meta" in session
    assert session["session_meta"]["context_source"] == "projected"


def test_api_query_agent_session_artifact_refs_crosscheck(mini_index):
    """artifact_refs in agent_query_session must match artifact_ids in the response.

    Verifies:
    - artifact_ids.query_trace, artifact_ids.context_bundle, artifact_ids.agent_query_session
      are all present when trace=True and storage is active.
    - agent_query_session.artifact_refs.query_trace_id == artifact_ids.query_trace
    - agent_query_session.artifact_refs.context_bundle_id == artifact_ids.context_bundle
    - agent_query_session.artifact_refs.agent_query_session_id is None (Path 2 honest null:
      self-ID is circular; it is available via artifact_ids.agent_query_session instead).
    """
    art = setup_test_artifact(mini_index)

    request_data = {
        "index_id": art.id,
        "q": "hello",
        "k": 1,
        "output_profile": "agent_minimal",
        "trace": True,
        "stale_policy": "ignore",
    }

    response = client.post("/api/query", json=request_data, headers={"Authorization": "Bearer test_token"})
    assert response.status_code == 200

    data = response.json()
    assert "context_bundle" in data, "expected context_bundle wrapper when trace=True + profile"
    assert "agent_query_session" in data, "expected agent_query_session in response"

    # All three artifact IDs must be present in the top-level artifact_ids map.
    assert "artifact_ids" in data, "artifact_ids missing from response"
    artifact_ids = data["artifact_ids"]
    assert "query_trace" in artifact_ids, "artifact_ids.query_trace missing"
    assert "context_bundle" in artifact_ids, "artifact_ids.context_bundle missing"
    assert "agent_query_session" in artifact_ids, "artifact_ids.agent_query_session missing"

    session = data["agent_query_session"]
    refs = session["artifact_refs"]

    # Cross-check: refs inside the session must match the top-level artifact_ids.
    assert refs["query_trace_id"] == artifact_ids["query_trace"], (
        f"query_trace_id mismatch: refs={refs['query_trace_id']!r} vs artifact_ids={artifact_ids['query_trace']!r}"
    )
    assert refs["context_bundle_id"] == artifact_ids["context_bundle"], (
        f"context_bundle_id mismatch: refs={refs['context_bundle_id']!r} vs artifact_ids={artifact_ids['context_bundle']!r}"
    )

    # Path 2: agent_query_session_id is intentionally null in the payload.
    # The self-ID is circular and is exposed via artifact_ids.agent_query_session instead.
    assert refs["agent_query_session_id"] is None, (
        "agent_query_session_id must be null in the payload (self-ID is carried via "
        f"artifact_ids.agent_query_session={artifact_ids['agent_query_session']!r})"
    )

    # Stored-session lookup roundtrip: the returned agent_query_session ID must resolve
    # to a valid artifact, and its artifact_refs must match what was in the inline response.
    session_lookup_resp = client.post(
        "/api/artifact_lookup",
        json={
            "artifact_type": "agent_query_session",
            "id": artifact_ids["agent_query_session"],
        },
        headers={"Authorization": "Bearer test_token"},
    )
    assert session_lookup_resp.status_code == 200
    lookup_data = session_lookup_resp.json()
    assert lookup_data["status"] == "ok", f"agent_query_session lookup failed: {lookup_data}"

    artifact = lookup_data["artifact"]
    assert artifact["authority"] == "runtime_observation"
    assert artifact["canonicality"] == "observation"
    assert artifact["artifact_shape"] == "wrapper"
    assert artifact["retention_policy"] == "unbounded_currently"
    assert artifact["lifecycle_status"] == "active"
    assert artifact["expires_at"] is None

    stored_session = artifact["data"]
    stored_refs = stored_session["artifact_refs"]
    assert stored_refs["query_trace_id"] == artifact_ids["query_trace"], (
        f"stored query_trace_id mismatch: {stored_refs['query_trace_id']!r} vs {artifact_ids['query_trace']!r}"
    )
    assert stored_refs["context_bundle_id"] == artifact_ids["context_bundle"], (
        f"stored context_bundle_id mismatch: {stored_refs['context_bundle_id']!r} vs {artifact_ids['context_bundle']!r}"
    )
    assert stored_refs["agent_query_session_id"] is None, (
        "stored agent_query_session_id must be null (self-ID is circular)"
    )

    # Stored provenance must use index_id (the schema-defined field name).
    assert artifact["provenance"]["index_id"] == art.id, (
        f"provenance.index_id mismatch: {artifact['provenance'].get('index_id')!r} vs {art.id!r}"
    )

    # Contract validation: lookup response must conform to artifact-lookup.v1.schema.json.
    if _jsonschema is not None:
        _lookup_schema = json.loads(
            (Path(__file__).parents[1] / "contracts" / "artifact-lookup.v1.schema.json").read_text()
        )
        _jsonschema.validate(instance=lookup_data, schema=_lookup_schema)


def test_api_query_agent_session_no_trace(mini_index):
    art = setup_test_artifact(mini_index)

    request_data = {
        "index_id": art.id,
        "q": "hello",
        "k": 1,
        "output_profile": "agent_minimal",
        "trace": False,
        "stale_policy": "ignore"
    }

    response = client.post("/api/query", json=request_data, headers={"Authorization": "Bearer test_token"})
    assert response.status_code == 200

    data = response.json()
    # When trace is False and there are no conflicts/warnings, output profile "agent_minimal"
    # returns the bundle contents directly at the top level, without the "context_bundle" wrapper.
    assert "hits" in data
    assert "agent_query_session" not in data


def test_api_query_guardrail_low_result_coverage(mini_index):
    # Tests that the agent guardrail 'Low result coverage' is correctly surfaced
    # when the number of returned hits is less than half of k.
    art = setup_test_artifact(mini_index)

    request_data = {
        "index_id": art.id,
        "q": "hello",
        "k": 10,  # Requesting 10, but mini_index only has 1 match
        "output_profile": "agent_minimal",
        "trace": True,
        "stale_policy": "ignore"
    }

    response = client.post("/api/query", json=request_data, headers={"Authorization": "Bearer test_token"})
    assert response.status_code == 200

    data = response.json()
    assert "warnings" in data
    assert "Low result coverage" in data["warnings"]

    assert "context_bundle" in data
    assert len(data["context_bundle"].get("hits", [])) == 1


def test_api_query_guardrail_sufficient_coverage(mini_index):
    # Tests that the agent guardrail 'Low result coverage' is NOT surfaced
    # when the number of returned hits is equal to or greater than half of k.
    art = setup_test_artifact(mini_index)

    request_data = {
        "index_id": art.id,
        "q": "hello",
        "k": 2,  # Requesting 2, mini_index has 1 match, 1 >= (2/2)
        "output_profile": "agent_minimal",
        "trace": True,
        "stale_policy": "ignore"
    }

    response = client.post("/api/query", json=request_data, headers={"Authorization": "Bearer test_token"})
    assert response.status_code == 200

    data = response.json()
    # The warnings key might not exist, or if it does, it should not contain the specific warning
    warnings = data.get("warnings", [])
    assert "Low result coverage" not in warnings


def test_api_query_runtime_error_is_redacted(mini_index, monkeypatch):
    art = setup_test_artifact(mini_index)
    secret = "/home/operator/.secrets/query-token"

    def fail_query(*args, **kwargs):
        raise RuntimeError(f"database failure at {secret}")

    from merger.lenskit.retrieval import query_core

    monkeypatch.setattr(query_core, "execute_query", fail_query)
    response = client.post(
        "/api/query",
        json={
            "index_id": art.id,
            "q": "hello",
            "k": 1,
            "stale_policy": "ignore",
        },
        headers={"Authorization": "Bearer test_token"},
    )

    assert response.status_code == 500
    assert response.json() == {"detail": "Query execution failed"}
    assert secret not in response.text
    assert "database failure" not in response.text
