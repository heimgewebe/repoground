"""Tests for artifact_lookup: QueryArtifactStore + /api/artifact_lookup endpoint.

Auth convention (confirmed via merger/repoground/service/auth.py):
  verify_token accepts HTTPBearer credentials only.
  Canonical header: "Authorization": "Bearer <token>"
  "x-rlens-token" appears in CORS allow_headers but is NOT read by verify_token.
"""
import json
import pytest
from pathlib import Path

from merger.repoground.service.query_artifact_store import QueryArtifactStore, VALID_ARTIFACT_TYPES

# jsonschema is an optional dependency; tests that need it skip gracefully.
try:
    import jsonschema
except ImportError:
    jsonschema = None

try:
    from fastapi.testclient import TestClient
    from merger.repoground.service.app import app
    from merger.repoground.service import app as service_app
    from merger.repoground.retrieval import index_db
    _HAS_FASTAPI = True
except ImportError:
    _HAS_FASTAPI = False

requires_fastapi = pytest.mark.skipif(not _HAS_FASTAPI, reason="fastapi not installed")

# Canonical auth header — matches HTTPBearer in verify_token.
_AUTH = {"Authorization": "Bearer test_token"}

# Path to the artifact-lookup schema for contract validation.
_SCHEMA_PATH = Path(__file__).parent.parent / "contracts" / "artifact-lookup.v1.schema.json"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def store(tmp_path):
    return QueryArtifactStore(tmp_path / ".repoground-service")


@pytest.fixture
def mini_index(tmp_path):
    if not _HAS_FASTAPI:
        pytest.skip("fastapi not installed")
    dump_path = tmp_path / "dump.json"
    chunk_path = tmp_path / "chunks.jsonl"
    db_path = tmp_path / ".index.sqlite"

    chunk_data = [
        {
            "chunk_id": "c1", "repo_id": "r1", "path": "src/main.py",
            "content": "def main():\n    return 0",
            "start_line": 1, "end_line": 2, "layer": "core",
            "artifact_type": "code", "content_sha256": "h1",
        },
    ]
    with chunk_path.open("w", encoding="utf-8") as f:
        for c in chunk_data:
            f.write(json.dumps(c) + "\n")
    dump_path.write_text(json.dumps({"dummy": "data"}), encoding="utf-8")
    index_db.build_index(dump_path, chunk_path, db_path)
    return db_path


@pytest.fixture
def api_client(tmp_path, mini_index):
    hub_path = mini_index.parent.parent
    service_app.init_service(hub_path=hub_path, token="test_token")

    from merger.repoground.service.models import Artifact, JobRequest
    from merger.repoground.service.app import state

    req = JobRequest(repos=["repo"], level="max", mode="gesamt")
    art = Artifact(
        id="test-art", job_id="test-job", hub=str(hub_path), repos=["repo"],
        created_at="2024-01-01T00:00:00+00:00",
        paths={"sqlite_index": mini_index.name},
        params=req,
        merges_dir=str(mini_index.parent),
    )
    state.job_store.add_artifact(art)
    return TestClient(app)


@pytest.fixture
def api_client_custom_merges(tmp_path, mini_index):
    """Fixture that uses an explicit merges_dir to verify store-path drift fix."""
    hub_path = mini_index.parent.parent
    custom_merges = tmp_path / "custom_merges"
    custom_merges.mkdir(parents=True, exist_ok=True)
    service_app.init_service(hub_path=hub_path, token="test_token", merges_dir=custom_merges)

    from merger.repoground.service.models import Artifact, JobRequest
    from merger.repoground.service.app import state

    req = JobRequest(repos=["repo"], level="max", mode="gesamt")
    art = Artifact(
        id="test-art", job_id="test-job", hub=str(hub_path), repos=["repo"],
        created_at="2024-01-01T00:00:00+00:00",
        paths={"sqlite_index": mini_index.name},
        params=req,
        merges_dir=str(mini_index.parent),
    )
    state.job_store.add_artifact(art)
    return TestClient(app), custom_merges


# ---------------------------------------------------------------------------
# QueryArtifactStore unit tests
# ---------------------------------------------------------------------------

class TestQueryArtifactStore:
    def test_store_and_get_roundtrip(self, store):
        data = {"query_input": "hello", "timings": {}}
        provenance = {"source_query": "hello", "timestamp": "2024-01-01T00:00:00+00:00"}
        artifact_id = store.store("query_trace", data, provenance)

        assert artifact_id.startswith("qart-")
        entry = store.get(artifact_id)
        assert entry is not None
        assert entry["artifact_type"] == "query_trace"
        assert entry["data"] == data
        assert entry["provenance"]["source_query"] == "hello"
        assert entry["provenance"]["run_id"] is None

    def test_store_with_run_id(self, store):
        provenance = {"source_query": "q", "timestamp": "2024-01-01T00:00:00+00:00"}
        aid = store.store("context_bundle", {"query": "q", "hits": []}, provenance, run_id="abc123")
        entry = store.get(aid)
        assert entry["provenance"]["run_id"] == "abc123"

    def test_get_missing_returns_none(self, store):
        assert store.get("qart-nonexistent") is None

    def test_invalid_artifact_type_raises(self, store):
        with pytest.raises(ValueError, match="Invalid artifact_type"):
            store.store("federation_trace", {}, {"source_query": "q", "timestamp": "t"})

    def test_all_valid_types_accepted(self, store):
        prov = {"source_query": "q", "timestamp": "2024-01-01T00:00:00+00:00"}
        for art_type in VALID_ARTIFACT_TYPES:
            aid = store.store(art_type, {}, prov)
            assert store.get(aid) is not None

    def test_persistence_survives_reload(self, tmp_path):
        storage_dir = tmp_path / ".repoground-service"
        store1 = QueryArtifactStore(storage_dir)
        prov = {"source_query": "persist test", "timestamp": "2024-01-01T00:00:00+00:00"}
        aid = store1.store("query_trace", {"data": "value"}, prov)

        store2 = QueryArtifactStore(storage_dir)
        entry = store2.get(aid)
        assert entry is not None
        assert entry["data"] == {"data": "value"}

    def test_get_all_returns_most_recent_first(self, store):
        prov = {"source_query": "q", "timestamp": "2024-01-01T00:00:00+00:00"}
        ids = [store.store("query_trace", {}, prov) for _ in range(3)]
        all_entries = store.get_all()
        assert len(all_entries) == 3
        stored_ids = {e["id"] for e in all_entries}
        assert stored_ids == set(ids)

    def test_id_is_stable_and_unique(self, store):
        prov = {"source_query": "q", "timestamp": "2024-01-01T00:00:00+00:00"}
        ids = {store.store("query_trace", {}, prov) for _ in range(5)}
        assert len(ids) == 5

    def test_store_contains_runtime_metadata_query_trace(self, store):
        prov = {"source_query": "q", "timestamp": "2024-01-01T00:00:00+00:00"}
        aid = store.store("query_trace", {}, prov)
        entry = store.get(aid)
        assert entry["authority"] == "runtime_observation"
        assert entry["canonicality"] == "observation"
        assert entry["artifact_shape"] == "raw"
        assert entry["retention_policy"] == "unbounded_currently"
        assert entry["lifecycle_status"] == "active"
        assert entry["expires_at"] is None
        assert "claim_boundaries" in entry
        assert "does_not_prove" in entry["claim_boundaries"]
        assert len(entry["claim_boundaries"]["does_not_prove"]) >= 1

    def test_context_bundle_artifact_shape_is_projected(self, store):
        prov = {"source_query": "q", "timestamp": "2024-01-01T00:00:00+00:00"}
        aid = store.store("context_bundle", {"query": "q", "hits": []}, prov)
        entry = store.get(aid)
        assert entry["artifact_shape"] == "projected"
        assert "Context bundle is stored in projected API form" in " ".join(
            entry["claim_boundaries"]["does_not_prove"]
        )

    def test_agent_query_session_artifact_shape_is_wrapper(self, store):
        prov = {"source_query": "q", "timestamp": "2024-01-01T00:00:00+00:00"}
        aid = store.store("agent_query_session", {"query": "q"}, prov)
        entry = store.get(aid)
        assert entry["artifact_shape"] == "wrapper"
        assert entry["authority"] == "runtime_observation"

    def test_runtime_metadata_survives_persistence_reload(self, tmp_path):
        storage_dir = tmp_path / ".repoground-service"
        store1 = QueryArtifactStore(storage_dir)
        prov = {"source_query": "persist", "timestamp": "2024-01-01T00:00:00+00:00"}
        aid = store1.store("context_bundle", {}, prov)

        store2 = QueryArtifactStore(storage_dir)
        entry = store2.get(aid)
        assert entry is not None
        assert entry["authority"] == "runtime_observation"
        assert entry["artifact_shape"] == "projected"
        assert "claim_boundaries" in entry

    def test_legacy_entry_without_runtime_metadata_is_backfilled(self, tmp_path):
        """Entries written before the metadata PR are backfilled by get()."""
        import json as _json
        storage_dir = tmp_path / ".repoground-service"
        storage_dir.mkdir(parents=True, exist_ok=True)
        store_file = storage_dir / "query_artifacts.json"
        legacy_entry = {
            "id": "qart-legacy001",
            "artifact_type": "query_trace",
            "data": {"query_input": "legacy"},
            "provenance": {"source_query": "legacy", "timestamp": "2024-01-01T00:00:00+00:00"},
            "created_at": "2024-01-01T00:00:00+00:00",
            # deliberately omits: authority, canonicality, artifact_shape,
            # retention_policy, lifecycle_status, expires_at, claim_boundaries
        }
        store_file.write_text(_json.dumps([legacy_entry]), encoding="utf-8")

        store = QueryArtifactStore(storage_dir)
        entry = store.get("qart-legacy001")
        assert entry is not None
        assert entry["authority"] == "runtime_observation"
        assert entry["canonicality"] == "observation"
        assert entry["artifact_shape"] == "raw"
        assert entry["retention_policy"] == "unbounded_currently"
        assert entry["lifecycle_status"] == "active"
        assert entry["expires_at"] is None
        assert "claim_boundaries" in entry
        assert "does_not_prove" in entry["claim_boundaries"]
        # Original fields must be preserved
        assert entry["data"] == {"query_input": "legacy"}
        assert entry["provenance"]["source_query"] == "legacy"

    def test_legacy_context_bundle_backfill_uses_projected_shape(self, tmp_path):
        """Legacy context_bundle entries are backfilled with artifact_shape='projected'."""
        import json as _json
        storage_dir = tmp_path / ".repoground-service"
        storage_dir.mkdir(parents=True, exist_ok=True)
        store_file = storage_dir / "query_artifacts.json"
        legacy_entry = {
            "id": "qart-legacy002",
            "artifact_type": "context_bundle",
            "data": {"query": "q", "hits": []},
            "provenance": {"source_query": "q", "timestamp": "2024-01-01T00:00:00+00:00"},
            "created_at": "2024-01-01T00:00:00+00:00",
        }
        store_file.write_text(_json.dumps([legacy_entry]), encoding="utf-8")

        store = QueryArtifactStore(storage_dir)
        entry = store.get("qart-legacy002")
        assert entry is not None
        assert entry["artifact_shape"] == "projected"
        assert entry["authority"] == "runtime_observation"

    def test_backfill_does_not_overwrite_existing_fields(self, tmp_path):
        """If a field is already in the stored entry, backfill must not overwrite it."""
        import json as _json
        storage_dir = tmp_path / ".repoground-service"
        storage_dir.mkdir(parents=True, exist_ok=True)
        store_file = storage_dir / "query_artifacts.json"
        # Entry already has authority (e.g. from a future schema that uses a different value)
        entry_with_authority = {
            "id": "qart-has-auth",
            "artifact_type": "query_trace",
            "data": {},
            "provenance": {"source_query": "q", "timestamp": "2024-01-01T00:00:00+00:00"},
            "created_at": "2024-01-01T00:00:00+00:00",
            "authority": "runtime_observation",  # already present
            "artifact_shape": "raw",              # already present
        }
        store_file.write_text(_json.dumps([entry_with_authority]), encoding="utf-8")

        store = QueryArtifactStore(storage_dir)
        entry = store.get("qart-has-auth")
        assert entry["authority"] == "runtime_observation"
        assert entry["artifact_shape"] == "raw"

    def test_runtime_metadata_claim_boundaries_are_not_shared_between_entries(self, store):
        """claim_boundaries lists must not be shared between independently stored artifacts."""
        prov = {"source_query": "q", "timestamp": "2024-01-01T00:00:00+00:00"}
        first_id = store.store("query_trace", {}, prov)
        second_id = store.store("query_trace", {}, prov)
        first = store.get(first_id)
        # Mutate the returned entry's claim_boundaries in-place.
        first["claim_boundaries"]["does_not_prove"].append("MUTATION_SENTINEL")
        second = store.get(second_id)
        assert "MUTATION_SENTINEL" not in second["claim_boundaries"]["does_not_prove"]
        # A third entry stored after the mutation must also be clean.
        third_id = store.store("query_trace", {}, prov)
        third = store.get(third_id)
        assert "MUTATION_SENTINEL" not in third["claim_boundaries"]["does_not_prove"]

    def test_get_returns_deepcopy_not_mutable_cache_entry(self, store):
        """Mutating a get() return value must not affect subsequent get() calls for the same id."""
        prov = {"source_query": "q", "timestamp": "2024-01-01T00:00:00+00:00"}
        aid = store.store("query_trace", {}, prov)
        first = store.get(aid)
        first["claim_boundaries"]["does_not_prove"].append("MUTATION_SENTINEL")
        again = store.get(aid)
        assert "MUTATION_SENTINEL" not in again["claim_boundaries"]["does_not_prove"]


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------

@requires_fastapi
class TestApiArtifactLookup:
    def test_lookup_not_found(self, api_client):
        resp = api_client.post(
            "/api/artifact_lookup",
            json={"artifact_type": "query_trace", "id": "qart-doesnotexist"},
            headers=_AUTH,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "not_found"
        assert data["artifact"] is None
        assert len(data["warnings"]) > 0

    def test_lookup_after_query_with_trace(self, api_client):
        resp = api_client.post(
            "/api/query",
            json={
                "index_id": "test-art",
                "q": "main",
                "k": 5,
                "trace": True,
                "build_context_bundle": True,
                "stale_policy": "ignore",
            },
            headers=_AUTH,
        )
        assert resp.status_code == 200
        query_result = resp.json()

        assert "artifact_ids" in query_result, (
            "artifact_ids missing from query response — store integration failed"
        )
        artifact_ids = query_result["artifact_ids"]
        # trace=True must always produce a query_trace artifact — no skip allowed here.
        assert "query_trace" in artifact_ids, (
            "query_trace not stored despite trace=True"
        )

        trace_id = artifact_ids["query_trace"]
        assert trace_id.startswith("qart-")

        lookup_resp = api_client.post(
            "/api/artifact_lookup",
            json={"artifact_type": "query_trace", "id": trace_id},
            headers=_AUTH,
        )
        assert lookup_resp.status_code == 200
        lookup_data = lookup_resp.json()
        assert lookup_data["status"] == "ok"
        assert lookup_data["id"] == trace_id
        assert lookup_data["artifact"] is not None
        assert "provenance" in lookup_data["artifact"]
        assert lookup_data["artifact"]["provenance"]["source_query"] == "main"
        assert lookup_data["artifact"]["provenance"]["index_id"] == "test-art"
        assert "data" in lookup_data["artifact"]

    def test_lookup_type_mismatch_returns_not_found(self, api_client):
        resp = api_client.post(
            "/api/query",
            json={
                "index_id": "test-art",
                "q": "main",
                "trace": True,
                "stale_policy": "ignore",
            },
            headers=_AUTH,
        )
        assert resp.status_code == 200
        artifact_ids = resp.json().get("artifact_ids", {})
        # trace=True must always store query_trace — no skip here.
        assert "query_trace" in artifact_ids, (
            "query_trace not stored despite trace=True"
        )
        trace_id = artifact_ids["query_trace"]

        # Look up a query_trace ID under the wrong type.
        lookup_resp = api_client.post(
            "/api/artifact_lookup",
            json={"artifact_type": "context_bundle", "id": trace_id},
            headers=_AUTH,
        )
        assert lookup_resp.status_code == 200
        data = lookup_resp.json()
        assert data["status"] == "not_found"
        assert len(data["warnings"]) > 0
        assert "query_trace" in data["warnings"][0]  # warning names the actual type

    def test_lookup_requires_auth(self, api_client):
        resp = api_client.post(
            "/api/artifact_lookup",
            json={"artifact_type": "query_trace", "id": "qart-test"},
        )
        assert resp.status_code == 401

    def test_lookup_rejects_extra_fields(self, api_client):
        """Extra fields must be rejected with 422 — contract says additionalProperties: false."""
        resp = api_client.post(
            "/api/artifact_lookup",
            json={"artifact_type": "query_trace", "id": "qart-test", "unexpected": True},
            headers=_AUTH,
        )
        assert resp.status_code == 422

    def test_lookup_rejects_empty_id(self, api_client):
        """Empty id must be rejected with 422 — contract says id.minLength: 1."""
        resp = api_client.post(
            "/api/artifact_lookup",
            json={"artifact_type": "query_trace", "id": ""},
            headers=_AUTH,
        )
        assert resp.status_code == 422

    def test_no_artifact_ids_without_trace_or_build_context(self, api_client):
        resp = api_client.post(
            "/api/query",
            json={
                "index_id": "test-art",
                "q": "main",
                "k": 5,
                "trace": False,
                "build_context_bundle": False,
                "stale_policy": "ignore",
            },
            headers=_AUTH,
        )
        assert resp.status_code == 200
        result = resp.json()
        assert "artifact_ids" not in result, (
            "artifact_ids must not appear when trace=False and build_context_bundle=False"
        )

    def test_context_bundle_lookup_roundtrip(self, api_client):
        resp = api_client.post(
            "/api/query",
            json={
                "index_id": "test-art",
                "q": "main",
                "build_context_bundle": True,
                "stale_policy": "ignore",
            },
            headers=_AUTH,
        )
        assert resp.status_code == 200
        query_result = resp.json()

        artifact_ids = query_result.get("artifact_ids", {})
        assert "context_bundle" in artifact_ids, (
            "context_bundle not stored despite build_context_bundle=True"
        )
        cb_id = artifact_ids["context_bundle"]

        lookup_resp = api_client.post(
            "/api/artifact_lookup",
            json={"artifact_type": "context_bundle", "id": cb_id},
            headers=_AUTH,
        )
        assert lookup_resp.status_code == 200
        data = lookup_resp.json()
        assert data["status"] == "ok"
        assert data["artifact"]["data"]["query"] == "main"

    def test_lookup_response_conforms_to_contract(self, api_client):
        """Response must validate against artifact-lookup.v1.schema.json."""
        if jsonschema is None:
            pytest.skip("jsonschema not available")

        resp = api_client.post(
            "/api/query",
            json={
                "index_id": "test-art",
                "q": "main",
                "trace": True,
                "stale_policy": "ignore",
            },
            headers=_AUTH,
        )
        assert resp.status_code == 200
        artifact_ids = resp.json().get("artifact_ids", {})
        # trace=True must always store query_trace.
        assert "query_trace" in artifact_ids, (
            "query_trace not stored despite trace=True"
        )
        trace_id = artifact_ids["query_trace"]

        lookup_resp = api_client.post(
            "/api/artifact_lookup",
            json={"artifact_type": "query_trace", "id": trace_id},
            headers=_AUTH,
        )
        assert lookup_resp.status_code == 200
        data = lookup_resp.json()

        schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
        jsonschema.validate(instance=data, schema=schema)

    def test_direct_bundle_artifact_ids_wrapping(self, api_client):
        """artifact_ids must not be injected into a bare context bundle.

        When output_profile produces a direct bundle (hits at top level, no
        context_bundle wrapper), the app must wrap it:
          {"context_bundle": <bundle>, "artifact_ids": {...}}

        Regression guard for the additionalProperties: false contract break.
        """
        resp = api_client.post(
            "/api/query",
            json={
                "index_id": "test-art",
                "q": "main",
                "build_context_bundle": True,
                "output_profile": "agent_minimal",
                "stale_policy": "ignore",
            },
            headers=_AUTH,
        )
        assert resp.status_code == 200
        data = resp.json()

        assert "artifact_ids" in data, "artifact_ids missing despite build_context_bundle=True"
        assert "context_bundle" in data, (
            "Direct bundle must be wrapped under 'context_bundle' key when artifact_ids are present"
        )
        assert "hits" not in data, (
            "Top-level 'hits' must not appear — injecting into a strict context bundle violates schema"
        )
        assert "context_bundle" in data["artifact_ids"], (
            "context_bundle artifact ID must be stored"
        )

    def test_lookup_response_includes_runtime_metadata(self, api_client):
        resp = api_client.post(
            "/api/query",
            json={
                "index_id": "test-art",
                "q": "main",
                "trace": True,
                "stale_policy": "ignore",
            },
            headers=_AUTH,
        )
        assert resp.status_code == 200
        artifact_ids = resp.json().get("artifact_ids", {})
        assert "query_trace" in artifact_ids
        trace_id = artifact_ids["query_trace"]

        lookup_resp = api_client.post(
            "/api/artifact_lookup",
            json={"artifact_type": "query_trace", "id": trace_id},
            headers=_AUTH,
        )
        assert lookup_resp.status_code == 200
        data = lookup_resp.json()
        assert data["status"] == "ok"
        art = data["artifact"]
        assert art["authority"] == "runtime_observation"
        assert art["canonicality"] == "observation"
        assert art["artifact_shape"] == "raw"
        assert art["retention_policy"] == "unbounded_currently"
        assert art["lifecycle_status"] == "active"
        assert art["expires_at"] is None
        assert "claim_boundaries" in art
        assert "does_not_prove" in art["claim_boundaries"]

    def test_context_bundle_lookup_includes_projected_shape(self, api_client):
        resp = api_client.post(
            "/api/query",
            json={
                "index_id": "test-art",
                "q": "main",
                "build_context_bundle": True,
                "stale_policy": "ignore",
            },
            headers=_AUTH,
        )
        assert resp.status_code == 200
        artifact_ids = resp.json().get("artifact_ids", {})
        assert "context_bundle" in artifact_ids
        cb_id = artifact_ids["context_bundle"]

        lookup_resp = api_client.post(
            "/api/artifact_lookup",
            json={"artifact_type": "context_bundle", "id": cb_id},
            headers=_AUTH,
        )
        assert lookup_resp.status_code == 200
        data = lookup_resp.json()
        assert data["status"] == "ok"
        assert data["artifact"]["artifact_shape"] == "projected"
        assert data["artifact"]["authority"] == "runtime_observation"

    def test_artifact_lookup_ok_with_runtime_metadata_conforms_to_contract(self, api_client):
        """ok response including runtime metadata must validate against artifact-lookup.v1.schema.json."""
        if jsonschema is None:
            pytest.skip("jsonschema not available")

        resp = api_client.post(
            "/api/query",
            json={
                "index_id": "test-art",
                "q": "main",
                "trace": True,
                "stale_policy": "ignore",
            },
            headers=_AUTH,
        )
        assert resp.status_code == 200
        trace_id = resp.json().get("artifact_ids", {}).get("query_trace")
        assert trace_id is not None, "query_trace not stored despite trace=True"

        lookup_resp = api_client.post(
            "/api/artifact_lookup",
            json={"artifact_type": "query_trace", "id": trace_id},
            headers=_AUTH,
        )
        assert lookup_resp.status_code == 200
        data = lookup_resp.json()
        assert data["status"] == "ok"
        assert "authority" in data["artifact"], "runtime metadata missing from artifact payload"

        schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
        jsonschema.validate(instance=data, schema=schema)

    def test_schema_rejects_wrong_authority_value(self):
        """Schema const enforcement: authority must be 'runtime_observation'."""
        if jsonschema is None:
            pytest.skip("jsonschema not available")

        schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
        bad_payload = {
            "artifact_type": "query_trace",
            "id": "qart-test",
            "status": "ok",
            "artifact": {
                "provenance": {"source_query": "q", "timestamp": "2024-01-01T00:00:00+00:00"},
                "created_at": "2024-01-01T00:00:00+00:00",
                "data": {},
                "authority": "canonical_content",  # wrong value — must fail
            },
            "warnings": [],
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=bad_payload, schema=schema)

    def test_schema_rejects_unknown_artifact_shape(self):
        """Schema enum enforcement: artifact_shape must be raw|projected|wrapper."""
        if jsonschema is None:
            pytest.skip("jsonschema not available")

        schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
        bad_payload = {
            "artifact_type": "query_trace",
            "id": "qart-test",
            "status": "ok",
            "artifact": {
                "provenance": {"source_query": "q", "timestamp": "2024-01-01T00:00:00+00:00"},
                "created_at": "2024-01-01T00:00:00+00:00",
                "data": {},
                "artifact_shape": "unknown_shape",  # not in enum — must fail
            },
            "warnings": [],
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=bad_payload, schema=schema)

    def test_schema_rejects_ok_artifact_missing_lifecycle_status(self):
        """ok artifact missing lifecycle_status must fail schema validation."""
        if jsonschema is None:
            pytest.skip("jsonschema not available")

        schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
        bad_payload = {
            "artifact_type": "query_trace",
            "id": "qart-test",
            "status": "ok",
            "artifact": {
                "provenance": {"source_query": "q", "timestamp": "2024-01-01T00:00:00+00:00"},
                "created_at": "2024-01-01T00:00:00+00:00",
                "data": {},
                "authority": "runtime_observation",
                "canonicality": "observation",
                "artifact_shape": "raw",
                "retention_policy": "unbounded_currently",
                # deliberately omits lifecycle_status
                "expires_at": None,
                "claim_boundaries": {"does_not_prove": ["Artifact ID stability is limited to this store location."]},
            },
            "warnings": [],
        }
        with pytest.raises(jsonschema.ValidationError) as exc:
            jsonschema.validate(instance=bad_payload, schema=schema)
        assert "lifecycle_status" in str(exc.value)

    def test_schema_rejects_ok_artifact_missing_expires_at(self):
        """ok artifact missing expires_at must fail schema validation."""
        if jsonschema is None:
            pytest.skip("jsonschema not available")

        schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
        bad_payload = {
            "artifact_type": "query_trace",
            "id": "qart-test",
            "status": "ok",
            "artifact": {
                "provenance": {"source_query": "q", "timestamp": "2024-01-01T00:00:00+00:00"},
                "created_at": "2024-01-01T00:00:00+00:00",
                "data": {},
                "authority": "runtime_observation",
                "canonicality": "observation",
                "artifact_shape": "raw",
                "retention_policy": "unbounded_currently",
                "lifecycle_status": "active",
                # deliberately omits expires_at
                "claim_boundaries": {"does_not_prove": ["Artifact ID stability is limited to this store location."]},
            },
            "warnings": [],
        }
        with pytest.raises(jsonschema.ValidationError) as exc:
            jsonschema.validate(instance=bad_payload, schema=schema)
        assert "expires_at" in str(exc.value)

    def test_schema_not_found_valid_without_lifecycle_fields(self):
        """not_found response without runtime metadata must remain schema-valid."""
        if jsonschema is None:
            pytest.skip("jsonschema not available")

        schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
        not_found_payload = {
            "artifact_type": "query_trace",
            "id": "qart-nonexistent",
            "status": "not_found",
            "artifact": None,
            "warnings": ["Artifact not found."],
        }
        # Must not raise
        jsonschema.validate(instance=not_found_payload, schema=schema)

    def test_store_path_uses_merges_dir_when_set(self, api_client_custom_merges):
        """QueryArtifactStore must use merges_dir/.repoground-service when merges_dir is set."""
        client, custom_merges = api_client_custom_merges
        resp = client.post(
            "/api/query",
            json={
                "index_id": "test-art",
                "q": "main",
                "trace": True,
                "stale_policy": "ignore",
            },
            headers=_AUTH,
        )
        assert resp.status_code == 200
        artifact_ids = resp.json().get("artifact_ids", {})
        assert "query_trace" in artifact_ids, (
            "query_trace not stored despite trace=True"
        )

        # The query_artifacts.json must exist inside the custom merges dir.
        store_file = custom_merges / ".repoground-service" / "query_artifacts.json"
        assert store_file.exists(), (
            f"QueryArtifactStore did not write to custom merges_dir: {store_file}"
        )
