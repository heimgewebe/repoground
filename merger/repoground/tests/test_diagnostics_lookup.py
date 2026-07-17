"""Tests for GET /api/diagnostics: read-only lookup of diagnostics snapshot."""
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta

import pytest

try:
    import jsonschema
except ImportError:
    jsonschema = None

try:
    from fastapi.testclient import TestClient
    from merger.repoground.service.app import app
    from merger.repoground.service import app as service_app
    _HAS_FASTAPI = True
except ImportError:
    _HAS_FASTAPI = False

requires_fastapi = pytest.mark.skipif(not _HAS_FASTAPI, reason="fastapi not installed")

_AUTH = {"Authorization": "Bearer test_token"}
_SCHEMA_PATH = Path(__file__).parent.parent / "contracts" / "diagnostics-lookup.v1.schema.json"


@pytest.fixture
def api_client(tmp_path):
    hub_path = tmp_path / "hub"
    cache_dir = hub_path / ".gewebe" / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    merges_dir = tmp_path / "merges"
    merges_dir.mkdir(parents=True, exist_ok=True)
    service_app.init_service(hub_path=hub_path, token="test_token", merges_dir=merges_dir)
    return TestClient(app), hub_path


@requires_fastapi
class TestApiDiagnosticsLookup:

    @pytest.mark.parametrize(
        "generated_at",
        [
            "2026-01-01T00:00:00Z",
            "2026-01-01T00:00:00+00:00",
        ],
    )
    def test_diagnostics_lookup_ok_reads_snapshot(self, api_client, generated_at):
        client, hub_path = api_client
        diag_path = hub_path / ".gewebe" / "cache" / "diagnostics.snapshot.json"
        diag_path.write_text(
            json.dumps(
                {
                    "schema_version": "diagnostics.snapshot.v1",
                    "status": "ok",
                    "generated_at": generated_at,
                    "summary": {"ok": 1, "issue": 0, "missing": 0, "issues_total": 0},
                    "data": {},
                }
            ),
            encoding="utf-8",
        )

        response = client.get("/api/diagnostics", headers=_AUTH)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["snapshot"]["schema_version"] == "diagnostics.snapshot.v1"
        assert data["freshness"] is not None
        assert data["freshness"]["generated_at"] == generated_at
        assert isinstance(data["freshness"]["is_stale"], bool)
        assert data["warnings"] == []

    def test_diagnostics_lookup_not_found(self, api_client):
        client, _ = api_client
        response = client.get("/api/diagnostics", headers=_AUTH)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "not_found"
        assert data["snapshot"] is None
        assert data["freshness"] is None
        assert len(data["warnings"]) > 0

    def test_diagnostics_lookup_invalid_json(self, api_client):
        client, hub_path = api_client
        diag_path = hub_path / ".gewebe" / "cache" / "diagnostics.snapshot.json"
        diag_path.write_text("{this is not json", encoding="utf-8")

        response = client.get("/api/diagnostics", headers=_AUTH)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "error"
        assert data["snapshot"] is None
        assert data["freshness"] is None
        assert len(data["warnings"]) > 0

    def test_diagnostics_lookup_requires_auth(self, api_client):
        client, _ = api_client
        response = client.get("/api/diagnostics")
        assert response.status_code == 401

    def test_diagnostics_lookup_response_conforms_to_contract(self, api_client):
        if jsonschema is None:
            pytest.skip("jsonschema not available")

        client, hub_path = api_client
        diag_path = hub_path / ".gewebe" / "cache" / "diagnostics.snapshot.json"
        diag_path.write_text(
            json.dumps(
                {
                    "schema_version": "diagnostics.snapshot.v1",
                    "status": "ok",
                    "generated_at": "2026-01-01T00:00:00Z",
                    "summary": {"ok": 1, "issue": 0, "missing": 0, "issues_total": 0},
                    "data": {},
                }
            ),
            encoding="utf-8",
        )

        response = client.get("/api/diagnostics", headers=_AUTH)
        assert response.status_code == 200
        data = response.json()

        schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
        jsonschema.validate(instance=data, schema=schema)

    def test_diagnostics_lookup_not_found_conforms_to_contract(self, api_client):
        if jsonschema is None:
            pytest.skip("jsonschema not available")

        client, _ = api_client
        response = client.get("/api/diagnostics", headers=_AUTH)
        assert response.status_code == 200

        data = response.json()
        schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
        jsonschema.validate(instance=data, schema=schema)

    def test_diagnostics_lookup_error_conforms_to_contract(self, api_client):
        if jsonschema is None:
            pytest.skip("jsonschema not available")

        client, hub_path = api_client
        diag_path = hub_path / ".gewebe" / "cache" / "diagnostics.snapshot.json"
        diag_path.write_text("{invalid", encoding="utf-8")

        response = client.get("/api/diagnostics", headers=_AUTH)
        assert response.status_code == 200

        data = response.json()
        schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
        jsonschema.validate(instance=data, schema=schema)

    @pytest.mark.parametrize("payload", ["[]", "\"x\"", "null", "123"])
    def test_diagnostics_lookup_non_object_json_returns_error(self, api_client, payload):
        client, hub_path = api_client
        diag_path = hub_path / ".gewebe" / "cache" / "diagnostics.snapshot.json"
        diag_path.write_text(payload, encoding="utf-8")

        response = client.get("/api/diagnostics", headers=_AUTH)
        assert response.status_code == 200
        data = response.json()

        assert data["status"] == "error"
        assert data["snapshot"] is None
        assert data["freshness"] is None
        assert any("expected JSON object" in w for w in data["warnings"])

    def test_diagnostics_lookup_non_object_json_conforms_to_contract(self, api_client):
        if jsonschema is None:
            pytest.skip("jsonschema not available")

        client, hub_path = api_client
        diag_path = hub_path / ".gewebe" / "cache" / "diagnostics.snapshot.json"
        diag_path.write_text("[]", encoding="utf-8")

        response = client.get("/api/diagnostics", headers=_AUTH)
        assert response.status_code == 200

        data = response.json()
        schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
        jsonschema.validate(instance=data, schema=schema)

    def test_diagnostics_lookup_does_not_rebuild_or_mutate_snapshot(self, api_client):
        client, hub_path = api_client
        diag_path = hub_path / ".gewebe" / "cache" / "diagnostics.snapshot.json"
        diag_path.write_text(
            json.dumps(
                {
                    "schema_version": "diagnostics.snapshot.v1",
                    "status": "ok",
                    "generated_at": "2026-01-01T00:00:00Z",
                    "summary": {"ok": 1, "issue": 0, "missing": 0, "issues_total": 0},
                    "data": {},
                }
            ),
            encoding="utf-8",
        )

        before_mtime = diag_path.stat().st_mtime_ns
        response = client.get("/api/diagnostics", headers=_AUTH)
        assert response.status_code == 200
        after_mtime = diag_path.stat().st_mtime_ns
        assert before_mtime == after_mtime

    def test_diagnostics_lookup_stale_snapshot_sets_freshness_without_mutation(self, api_client):
        client, hub_path = api_client
        diag_path = hub_path / ".gewebe" / "cache" / "diagnostics.snapshot.json"

        ttl_hours = service_app.diagnostics_rebuild.TTL_HOURS
        stale_generated_at = (
            datetime.now(timezone.utc) - timedelta(hours=ttl_hours + 1)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        diag_path.write_text(
            json.dumps(
                {
                    "schema_version": "diagnostics.snapshot.v1",
                    "status": "ok",
                    "generated_at": stale_generated_at,
                    "summary": {"ok": 1, "issue": 0, "missing": 0, "issues_total": 0},
                    "data": {},
                }
            ),
            encoding="utf-8",
        )

        before_mtime = diag_path.stat().st_mtime_ns
        response = client.get("/api/diagnostics", headers=_AUTH)
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "ok"
        assert data["freshness"] is not None
        assert data["freshness"]["is_stale"] is True
        assert data["freshness"]["ttl_hours"] > 0

        after_mtime = diag_path.stat().st_mtime_ns
        assert before_mtime == after_mtime
