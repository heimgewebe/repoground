"""Tests for POST /api/trace_lookup: typed read-only facade over query_trace artifacts.

Auth convention (confirmed via merger/repoground/service/auth.py):
  verify_token accepts HTTPBearer credentials only.
  Canonical header: "Authorization": "Bearer <token>"
"""
import json
import pytest
from pathlib import Path

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

_AUTH = {"Authorization": "Bearer test_token"}

_SCHEMA_PATH = Path(__file__).parent.parent / "contracts" / "trace-lookup.v1.schema.json"


# ---------------------------------------------------------------------------
# Fixtures (mirrored from test_artifact_lookup.py)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@requires_fastapi
class TestApiTraceLookup:

    def test_trace_lookup_after_query_with_trace(self, api_client):
        resp = api_client.post(
            "/api/query",
            json={
                "index_id": "test-art",
                "q": "main",
                "k": 5,
                "trace": True,
                "stale_policy": "ignore",
            },
            headers=_AUTH,
        )
        assert resp.status_code == 200
        query_result = resp.json()

        assert "artifact_ids" in query_result, (
            "artifact_ids missing from query response"
        )
        artifact_ids = query_result["artifact_ids"]
        assert "query_trace" in artifact_ids, (
            "query_trace not stored despite trace=True"
        )

        trace_id = artifact_ids["query_trace"]
        assert trace_id.startswith("qart-")

        lookup_resp = api_client.post(
            "/api/trace_lookup",
            json={"id": trace_id},
            headers=_AUTH,
        )
        assert lookup_resp.status_code == 200
        data = lookup_resp.json()
        assert data["status"] == "ok"
        assert data["id"] == trace_id
        assert data["trace"] is not None
        assert data["provenance"] is not None
        assert data["provenance"]["source_query"] == "main"
        assert data["created_at"] is not None
        assert data["warnings"] == []

    def test_trace_lookup_not_found(self, api_client):
        resp = api_client.post(
            "/api/trace_lookup",
            json={"id": "qart-doesnotexist"},
            headers=_AUTH,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "not_found"
        assert data["trace"] is None
        assert data["provenance"] is None
        assert data["created_at"] is None
        assert len(data["warnings"]) > 0

    def test_trace_lookup_type_mismatch_hides_non_trace_artifact(self, api_client):
        """Looking up a context_bundle ID via /api/trace_lookup must return not_found."""
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
        assert "context_bundle" in artifact_ids, (
            "context_bundle not stored despite build_context_bundle=True"
        )
        cb_id = artifact_ids["context_bundle"]

        lookup_resp = api_client.post(
            "/api/trace_lookup",
            json={"id": cb_id},
            headers=_AUTH,
        )
        assert lookup_resp.status_code == 200
        data = lookup_resp.json()
        assert data["status"] == "not_found"
        assert data["trace"] is None
        assert data["provenance"] is None
        assert len(data["warnings"]) > 0
        # Warning must name the actual type, not expose the artifact data.
        assert "context_bundle" in data["warnings"][0]

    def test_trace_lookup_requires_auth(self, api_client):
        resp = api_client.post(
            "/api/trace_lookup",
            json={"id": "qart-test"},
        )
        assert resp.status_code == 401

    def test_trace_lookup_rejects_empty_id(self, api_client):
        resp = api_client.post(
            "/api/trace_lookup",
            json={"id": ""},
            headers=_AUTH,
        )
        assert resp.status_code == 422

    def test_trace_lookup_rejects_extra_fields(self, api_client):
        """Extra fields must be rejected with 422 — contract says additionalProperties: false."""
        resp = api_client.post(
            "/api/trace_lookup",
            json={"id": "qart-test", "unexpected": True},
            headers=_AUTH,
        )
        assert resp.status_code == 422

    def test_trace_lookup_response_conforms_to_contract(self, api_client):
        """Response must validate against trace-lookup.v1.schema.json."""
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
        assert "query_trace" in artifact_ids, (
            "query_trace not stored despite trace=True"
        )
        trace_id = artifact_ids["query_trace"]

        lookup_resp = api_client.post(
            "/api/trace_lookup",
            json={"id": trace_id},
            headers=_AUTH,
        )
        assert lookup_resp.status_code == 200
        data = lookup_resp.json()

        schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
        jsonschema.validate(instance=data, schema=schema)

    def test_trace_lookup_not_found_conforms_to_contract(self, api_client):
        """not_found response must also validate against the contract schema."""
        if jsonschema is None:
            pytest.skip("jsonschema not available")

        resp = api_client.post(
            "/api/trace_lookup",
            json={"id": "qart-nonexistent"},
            headers=_AUTH,
        )
        assert resp.status_code == 200
        data = resp.json()

        schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
        jsonschema.validate(instance=data, schema=schema)

    def test_trace_lookup_ok_includes_runtime_metadata(self, api_client):
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
            "/api/trace_lookup",
            json={"id": trace_id},
            headers=_AUTH,
        )
        assert lookup_resp.status_code == 200
        data = lookup_resp.json()
        assert data["status"] == "ok"
        assert data["authority"] == "runtime_observation"
        assert data["canonicality"] == "observation"
        assert data["artifact_shape"] == "raw"
        assert data["retention_policy"] == "unbounded_currently"
        assert data["lifecycle_status"] == "active"
        assert data["expires_at"] is None
        assert "claim_boundaries" in data
        assert "does_not_prove" in data["claim_boundaries"]

    def test_trace_lookup_runtime_metadata_conforms_to_contract(self, api_client):
        """ok response with runtime metadata must validate against schema."""
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
        assert trace_id is not None

        lookup_resp = api_client.post(
            "/api/trace_lookup",
            json={"id": trace_id},
            headers=_AUTH,
        )
        assert lookup_resp.status_code == 200
        data = lookup_resp.json()

        schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
        jsonschema.validate(instance=data, schema=schema)

    def test_schema_rejects_ok_trace_missing_lifecycle_status(self):
        """ok trace response missing lifecycle_status must fail schema validation."""
        if jsonschema is None:
            pytest.skip("jsonschema not available")

        schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
        bad_payload = {
            "status": "ok",
            "id": "qart-test",
            "trace": {"query_input": "q"},
            "provenance": {"source_query": "q", "timestamp": "2024-01-01T00:00:00+00:00"},
            "created_at": "2024-01-01T00:00:00+00:00",
            "warnings": [],
            "authority": "runtime_observation",
            "canonicality": "observation",
            "artifact_shape": "raw",
            "retention_policy": "unbounded_currently",
            # deliberately omits lifecycle_status
            "expires_at": None,
            "claim_boundaries": {"does_not_prove": ["Artifact ID stability is limited to this store location."]},
        }
        with pytest.raises(jsonschema.ValidationError) as exc:
            jsonschema.validate(instance=bad_payload, schema=schema)
        assert "lifecycle_status" in str(exc.value)

    def test_schema_rejects_ok_trace_missing_expires_at(self):
        """ok trace response missing expires_at must fail schema validation."""
        if jsonschema is None:
            pytest.skip("jsonschema not available")

        schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
        bad_payload = {
            "status": "ok",
            "id": "qart-test",
            "trace": {"query_input": "q"},
            "provenance": {"source_query": "q", "timestamp": "2024-01-01T00:00:00+00:00"},
            "created_at": "2024-01-01T00:00:00+00:00",
            "warnings": [],
            "authority": "runtime_observation",
            "canonicality": "observation",
            "artifact_shape": "raw",
            "retention_policy": "unbounded_currently",
            "lifecycle_status": "active",
            # deliberately omits expires_at
            "claim_boundaries": {"does_not_prove": ["Artifact ID stability is limited to this store location."]},
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
            "status": "not_found",
            "id": "qart-nonexistent",
            "trace": None,
            "provenance": None,
            "created_at": None,
            "warnings": ["Artifact not found."],
        }
        # Must not raise — not_found does not require lifecycle fields
        jsonschema.validate(instance=not_found_payload, schema=schema)
