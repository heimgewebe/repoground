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

client = TestClient(app)

@pytest.fixture
def fed_setup(tmp_path):
    hub_path = tmp_path / "hub"
    hub_path.mkdir()
    merges_dir = tmp_path / "merges"
    merges_dir.mkdir()

    # repo 1: API-visible bundle content stays beneath the federation directory.
    bundle_dir1 = merges_dir / "bundle-r1"
    bundle_dir1.mkdir()
    dump_path1 = bundle_dir1 / "dump1.json"
    chunk_path1 = bundle_dir1 / "chunks1.jsonl"
    db_path1 = bundle_dir1 / "1.chunk_index.index.sqlite"

    chunk_data1 = [{"chunk_id": "c1", "repo_id": "r1", "path": "src/main.py", "content": "def main(): print('hello r1')", "start_line": 1, "end_line": 2, "layer": "core", "artifact_type": "code", "content_sha256": "h1"}]
    with chunk_path1.open("w", encoding="utf-8") as f:
        for c in chunk_data1: f.write(json.dumps(c) + "\n")
    dump_path1.write_text(json.dumps({"dummy": "data"}), encoding="utf-8")
    index_db.build_index(dump_path1, chunk_path1, db_path1)

    fed_index = merges_dir / "federation.json"
    fed_data = {
        "kind": "repolens.federation.index", "version": "1.0", "created_at": "2026-04-03T16:30:36.125043+00:00", "updated_at": "2026-04-03T16:30:55.046944+00:00", "federation_id": "fed1",
        "bundles": [
            {"repo_id": "r1", "bundle_path": "bundle-r1"}
        ]
    }
    fed_index.write_text(json.dumps(fed_data), encoding="utf-8")

    service_app.init_service(hub_path=hub_path, token="test_token", merges_dir=merges_dir)
    return fed_index

def test_api_federation_query_valid(fed_setup):
    request_data = {
        "federation_index": "federation.json",
        "q": "hello r1",
        "k": 1,
        "explain": True,
        "trace": True,
        "output_profile": "agent_minimal",
    }

    response = client.post("/api/federation/query", json=request_data, headers={"Authorization": "Bearer test_token"})
    assert response.status_code == 200

    data = response.json()
    # Contract constraint: with trace=True and a profile, we must receive a wrapper
    assert "context_bundle" in data
    assert "federation_trace" in data
    assert "agent_query_session" in data
    assert "hits" not in data  # hits must be strictly inside context_bundle

    bundle = data["context_bundle"]
    assert "hits" in bundle

    # Verify agent_minimal projection acted on federation hits
    # Note: `agent_minimal` projection applies only to existing fields on the federated hits structure.
    # It does not construct full semantic bundle context, only strips what exists.
    if len(bundle["hits"]) > 0:
        hit = bundle["hits"][0]
        assert "explain" not in hit  # stripped by agent_minimal
        assert "graph_context" not in hit

    session = data["agent_query_session"]
    assert "r1" in session["resolved_bundles"]
    assert "session_meta" in session
    assert session["session_meta"]["context_source"] == "both"


def test_api_federation_query_invalid_path(fed_setup):
    request_data = {
        "federation_index": "../federation.json",
        "q": "hello",
        "k": 1
    }
    response = client.post("/api/federation/query", json=request_data, headers={"Authorization": "Bearer test_token"})
    assert response.status_code == 400
    assert "Invalid federation_index path" in response.json()["detail"]


def test_api_federation_query_no_trace(fed_setup):
    request_data = {
        "federation_index": "federation.json",
        "q": "hello r1",
        "k": 1,
        "trace": False,
        "output_profile": "agent_minimal",
    }
    response = client.post("/api/federation/query", json=request_data, headers={"Authorization": "Bearer test_token"})
    assert response.status_code == 200

    data = response.json()
    # When trace is False, output profile "agent_minimal" returns the bundle contents directly at the top level
    assert "hits" in data
    assert "context_bundle" not in data
    assert "federation_trace" not in data
    assert "agent_query_session" not in data

def test_api_federation_query_invalid_output_profile(fed_setup):
    request_data = {
        "federation_index": "federation.json",
        "q": "hello",
        "k": 1,
        "output_profile": "invalid_profile"
    }
    response = client.post("/api/federation/query", json=request_data, headers={"Authorization": "Bearer test_token"})
    assert response.status_code == 422 # Pydantic validation error

def test_api_federation_query_file_not_found(fed_setup):
    request_data = {
        "federation_index": "does_not_exist.json",
        "q": "hello",
        "k": 1
    }
    response = client.post("/api/federation/query", json=request_data, headers={"Authorization": "Bearer test_token"})
    assert response.status_code == 404

def test_api_federation_query_schema_validation_error(fed_setup):
    merges_dir = fed_setup.parent
    invalid_index = merges_dir / "invalid_fed.json"
    invalid_index.write_text('{"kind": "not_a_federation"}', encoding="utf-8")

    request_data = {
        "federation_index": "invalid_fed.json",
        "q": "hello",
        "k": 1
    }
    response = client.post("/api/federation/query", json=request_data, headers={"Authorization": "Bearer test_token"})
    assert response.status_code == 400


def test_api_federation_query_agent_session_artifact_refs_crosscheck(fed_setup):
    """artifact_refs in agent_query_session must match artifact_ids in the federation response.

    Verifies:
    - artifact_ids.context_bundle and artifact_ids.agent_query_session are present.
    - artifact_ids.query_trace is absent (federation has no standalone query_trace artifact).
    - agent_query_session.artifact_refs.context_bundle_id == artifact_ids.context_bundle
    - agent_query_session.artifact_refs.query_trace_id is None (no standalone trace)
    - agent_query_session.artifact_refs.agent_query_session_id is None (Path 2: self-ID
      is circular; the assigned ID is surfaced via artifact_ids.agent_query_session).
    """
    request_data = {
        "federation_index": "federation.json",
        "q": "hello r1",
        "k": 1,
        "output_profile": "agent_minimal",
        "trace": True,
    }

    response = client.post(
        "/api/federation/query",
        json=request_data,
        headers={"Authorization": "Bearer test_token"},
    )
    assert response.status_code == 200

    data = response.json()
    assert "context_bundle" in data, "expected context_bundle wrapper"
    assert "agent_query_session" in data, "expected agent_query_session in response"

    # artifact_ids must include context_bundle and agent_query_session.
    assert "artifact_ids" in data, "artifact_ids missing from federation response"
    artifact_ids = data["artifact_ids"]
    assert "context_bundle" in artifact_ids, "artifact_ids.context_bundle missing"
    assert "agent_query_session" in artifact_ids, "artifact_ids.agent_query_session missing"
    # Federation does not produce a standalone query_trace artifact.
    assert "query_trace" not in artifact_ids, (
        "artifact_ids.query_trace must not be present in federation response"
    )

    session = data["agent_query_session"]
    refs = session["artifact_refs"]

    # Cross-check: context_bundle_id in refs must match artifact_ids.
    assert refs["context_bundle_id"] == artifact_ids["context_bundle"], (
        f"context_bundle_id mismatch: refs={refs['context_bundle_id']!r} vs "
        f"artifact_ids={artifact_ids['context_bundle']!r}"
    )

    # No standalone query_trace for federation — query_trace_id must be null.
    assert refs["query_trace_id"] is None, (
        "query_trace_id must be null for federation (no standalone query_trace artifact)"
    )

    # Path 2: agent_query_session_id is intentionally null (self-ID circular).
    # The assigned ID is available via artifact_ids.agent_query_session.
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
    assert stored_refs["query_trace_id"] is None, (
        "stored query_trace_id must be null for federation (no standalone query_trace artifact)"
    )
    assert stored_refs["context_bundle_id"] == artifact_ids["context_bundle"], (
        f"stored context_bundle_id mismatch: {stored_refs['context_bundle_id']!r} vs {artifact_ids['context_bundle']!r}"
    )
    assert stored_refs["agent_query_session_id"] is None, (
        "stored agent_query_session_id must be null (self-ID is circular)"
    )

    # Contract validation: lookup response must conform to artifact-lookup.v1.schema.json.
    if _jsonschema is not None:
        _lookup_schema = json.loads(
            (Path(__file__).parents[1] / "contracts" / "artifact-lookup.v1.schema.json").read_text()
        )
        _jsonschema.validate(instance=lookup_data, schema=_lookup_schema)

    # Stored provenance must use index_id (not the raw field name federation_index).
    assert artifact["provenance"]["index_id"] == "federation.json", (
        f"provenance.index_id mismatch: {artifact['provenance'].get('index_id')!r}"
    )
    assert "federation_index" not in artifact["provenance"], (
        "provenance must not contain federation_index (not allowed by ArtifactProvenance schema)"
    )


def test_api_federation_build_context_bundle_direct_form_stores_artifact(fed_setup):
    """build_context_bundle=True with trace=False triggers context_bundle storage even when
    project_output() returns the bundle directly (no context_bundle wrapper key).

    With trace=False and no conflicts/warnings, project_output() returns the bundle at the
    top level (hits key, no context_bundle key). The previous code used
    projected.get("context_bundle") which missed this form. The fix uses
    _extract_projected_context_bundle() which handles both shapes.

    After storage, the wrapping rule fires (direct bundle + artifact_ids → wrapped under
    context_bundle key), so the response has the form {"context_bundle": {...}, "artifact_ids": {...}}.

    Verifies:
    - artifact_ids.context_bundle is present.
    - artifact_ids.query_trace is absent (trace=False).
    - agent_query_session is absent (trace=False, no session built).
    - /api/artifact_lookup with the returned ID returns status=ok with runtime metadata.
    """
    request_data = {
        "federation_index": "federation.json",
        "q": "hello r1",
        "k": 1,
        "output_profile": "agent_minimal",
        "build_context_bundle": True,
        "trace": False,
    }

    response = client.post(
        "/api/federation/query",
        json=request_data,
        headers={"Authorization": "Bearer test_token"},
    )
    assert response.status_code == 200

    data = response.json()
    # project_output() returns the bundle directly; after storage the wrapping rule fires,
    # so the response carries the bundle under "context_bundle".
    assert "context_bundle" in data, (
        "context_bundle must be present in response (wrapping rule fires after storage)"
    )
    assert "artifact_ids" in data, (
        "artifact_ids missing — context_bundle was not stored for direct-bundle form"
    )
    artifact_ids = data["artifact_ids"]
    assert "context_bundle" in artifact_ids, (
        "artifact_ids.context_bundle missing despite build_context_bundle=True"
    )

    # No trace, no session.
    assert "query_trace" not in artifact_ids, "artifact_ids.query_trace must be absent (trace=False)"
    assert "agent_query_session" not in artifact_ids, (
        "artifact_ids.agent_query_session must be absent (no session when trace=False)"
    )
    assert "agent_query_session" not in data, "agent_query_session must not appear (trace=False)"

    # Artifact lookup roundtrip: the returned ID must resolve to a valid context_bundle.
    cb_id = artifact_ids["context_bundle"]
    lookup_resp = client.post(
        "/api/artifact_lookup",
        json={"artifact_type": "context_bundle", "id": cb_id},
        headers={"Authorization": "Bearer test_token"},
    )
    assert lookup_resp.status_code == 200
    lookup_data = lookup_resp.json()

    assert lookup_data["status"] == "ok", f"lookup failed: {lookup_data}"

    artifact = lookup_data["artifact"]
    # Stored artifact must carry the runtime classification metadata.
    assert artifact.get("authority") == "runtime_observation"
    assert artifact.get("canonicality") == "observation"
    assert artifact.get("artifact_shape") == "projected"
    assert artifact.get("retention_policy") == "unbounded_currently"
    assert artifact.get("lifecycle_status") == "active"
    assert artifact.get("expires_at") is None


@pytest.fixture
def fed_setup_multi(tmp_path):
    hub_path = tmp_path / "hub"
    hub_path.mkdir()
    merges_dir = tmp_path / "merges"
    merges_dir.mkdir()

    # Bundle 1
    b1_dir = merges_dir / "repo1"
    b1_dir.mkdir()
    b1_dump = b1_dir / "dump.json"
    b1_chunks = b1_dir / "chunks.jsonl"
    b1_db = b1_dir / "chunk_index.index.sqlite"

    chunk_data_1 = [
        {
            "chunk_id": "c1",
            "repo_id": "repo1",
            "path": "src/main.py",
            "content": "def main(): print('hello shared')",
            "start_line": 1,
            "end_line": 1,
            "layer": "core",
            "artifact_type": "code",
            "content_sha256": "h1",
            "source_file": "src/main.py",
            "start_byte": 0,
            "end_byte": 100,
        }
    ]
    with b1_chunks.open("w", encoding="utf-8") as f:
        for c in chunk_data_1:
            f.write(json.dumps(c) + "\n")
    b1_dump.write_text(json.dumps({"dummy": "data"}), encoding="utf-8")
    index_db.build_index(b1_dump, b1_chunks, b1_db)

    # Bundle 2 (different path to avoid federation_conflicts and isolate cross_repo_links wrapper trigger)
    b2_dir = merges_dir / "repo2"
    b2_dir.mkdir()
    b2_dump = b2_dir / "dump.json"
    b2_chunks = b2_dir / "chunks.jsonl"
    b2_db = b2_dir / "chunk_index.index.sqlite"

    chunk_data_2 = [
        {
            "chunk_id": "c2",
            "repo_id": "repo2",
            "path": "lib/feature.py",
            "content": "def feature(): print('hello shared')",
            "start_line": 1,
            "end_line": 1,
            "layer": "core",
            "artifact_type": "code",
            "content_sha256": "h2",
            "source_file": "lib/feature.py",
            "start_byte": 0,
            "end_byte": 100,
        }
    ]
    with b2_chunks.open("w", encoding="utf-8") as f:
        for c in chunk_data_2:
            f.write(json.dumps(c) + "\n")
    b2_dump.write_text(json.dumps({"dummy": "data"}), encoding="utf-8")
    index_db.build_index(b2_dump, b2_chunks, b2_db)

    fed_index = merges_dir / "federation_multi.json"
    fed_data = {
        "kind": "repolens.federation.index",
        "version": "1.0",
        "created_at": "2026-04-03T16:30:36.125043+00:00",
        "updated_at": "2026-04-03T16:30:55.046944+00:00",
        "federation_id": "fed-multi",
        "bundles": [
            {"repo_id": "repo1", "bundle_path": "repo1"},
            {"repo_id": "repo2", "bundle_path": "repo2"},
        ],
    }
    fed_index.write_text(json.dumps(fed_data), encoding="utf-8")

    service_app.init_service(hub_path=hub_path, token="test_token", merges_dir=merges_dir)
    return fed_index


def test_api_federation_query_profile_preserves_cross_repo_links(fed_setup_multi):
    request_data = {
        "federation_index": "federation_multi.json",
        "q": "hello shared",
        "k": 5,
        "trace": False,
        "output_profile": "agent_minimal",
    }

    response = client.post(
        "/api/federation/query",
        json=request_data,
        headers={"Authorization": "Bearer test_token"},
    )
    assert response.status_code == 200

    data = response.json()

    # cross_repo_links must survive output_profile projection.
    assert "context_bundle" in data
    assert "cross_repo_links" in data
    assert "hits" not in data

    # No trace requested; this wrapper should be triggered by cross_repo_links, not by federation_trace.
    assert "federation_trace" not in data

    links = data["cross_repo_links"]
    assert isinstance(links, list)
    assert len(links) >= 1

    # Schema validation for projected cross_repo_links.
    if _jsonschema is not None:
        schema = json.loads(
            (Path(__file__).parents[1] / "contracts" / "cross-repo-links.v1.schema.json").read_text()
        )
        _jsonschema.validate(instance=links, schema=schema)

    # evidence_refs must be traceable to chunk IDs present in the profiled context bundle.
    hits = data["context_bundle"].get("hits", [])
    hit_chunk_ids = {h.get("chunk_id") for h in hits if h.get("chunk_id")}
    assert hit_chunk_ids, "expected profiled hits with chunk_id values"

    for link in links:
        assert link["link_type"] == "co_occurrence"
        assert link["confidence"] == "inferred"
        for ref in link["evidence_refs"]:
            assert ref in hit_chunk_ids

    # Result count and ranking surface must remain coherent.
    assert len(hits) >= 2


def test_api_federation_query_profile_preserves_federation_trace(fed_setup):
    """output_profile='agent_minimal' + trace=True: federation_trace must survive projection.

    This test specifically covers the API servicepath (not just project_output() unit level):
    the /api/federation/query endpoint must return federation_trace inside the wrapper
    when both output_profile and trace=True are set.
    """
    request_data = {
        "federation_index": "federation.json",
        "q": "hello r1",
        "k": 1,
        "trace": True,
        "output_profile": "agent_minimal",
    }

    response = client.post(
        "/api/federation/query",
        json=request_data,
        headers={"Authorization": "Bearer test_token"},
    )
    assert response.status_code == 200

    data = response.json()
    assert "context_bundle" in data, "expected wrapper form with context_bundle"
    assert "federation_trace" in data, (
        "federation_trace must not be lost through output_profile projection"
    )
    assert "hits" not in data, "hits must not appear at top level (must be inside context_bundle)"

    # Verify federation_trace has the expected structure
    ft = data["federation_trace"]
    # The API response carries the RUNTIME federation_trace (from execute_federated_query),
    # which is structurally distinct from the CLI-written federation_trace.json artifact.
    # The schema (federation-trace.v1.schema.json with additionalProperties:false) governs
    # the FILE artifact (query/timestamp/total_results/bundles[]). The runtime form carries
    # execution telemetry: queried_bundles_total, bundle_status, bundle_traces, etc.
    # Schema validation is intentionally not applied here — the schema describes the file
    # artifact, not this inline API form. Asserting the runtime contract instead:
    assert isinstance(ft.get("queried_bundles_total"), int), (
        "federation_trace.queried_bundles_total must be an integer"
    )
    assert isinstance(ft.get("queried_bundles_effective"), int), (
        "federation_trace.queried_bundles_effective must be an integer"
    )
    assert isinstance(ft.get("bundle_status"), dict), (
        "federation_trace.bundle_status must be a dict"
    )
    assert ft["bundle_status"], "bundle_status must have at least one entry"
    valid_statuses = frozenset({
        "ok", "stale", "filtered_out", "index_missing",
        "query_error", "bundle_path_unsupported", "missing", "error",
    })
    for repo_id, status in ft["bundle_status"].items():
        assert status in valid_statuses, (
            f"bundle_status[{repo_id!r}]={status!r} is not a valid status enum value"
        )


def test_api_federation_runtime_error_is_redacted(fed_setup, monkeypatch):
    secret = "/home/operator/.secrets/federation-token"

    def fail_query(*args, **kwargs):
        raise RuntimeError(f"federation failure at {secret}")

    from merger.lenskit.retrieval import federation_query

    monkeypatch.setattr(federation_query, "execute_federated_query", fail_query)
    response = client.post(
        "/api/federation/query",
        json={"federation_index": "federation.json", "q": "hello", "k": 1},
        headers={"Authorization": "Bearer test_token"},
    )

    assert response.status_code == 500
    assert response.json() == {"detail": "Federation query failed"}
    assert secret not in response.text
    assert "federation failure" not in response.text
