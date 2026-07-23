"""Tests for /api/health endpoint — specifically running_jobs correctness."""
import pytest
from merger.repoground.service import app as app_module
from merger.repoground.service.app import app, init_service, state
from merger.repoground.service.models import Job, JobRequest


@pytest.fixture
def health_client(tmp_path):
    hub = tmp_path / "hub"
    hub.mkdir()
    (hub / "repo1").mkdir()

    import os
    os.environ["REPOGROUND_TOKEN"] = "test-health-token"

    app.middleware_stack = None
    init_service(hub, token="test-health-token")

    from fastapi.testclient import TestClient
    with TestClient(app) as client:
        yield client, state.job_store


def _add_job(store, status: str) -> Job:
    req = JobRequest(repos=["repo1"])
    job = Job.create(request=req)
    job.status = status
    store.add_job(job)
    return job


def test_health_running_jobs_zero_when_all_succeeded(health_client):
    client, store = health_client

    _add_job(store, "succeeded")
    _add_job(store, "succeeded")
    _add_job(store, "failed")
    _add_job(store, "canceled")

    resp = client.get("/api/health", headers={"Authorization": "Bearer test-health-token"})
    assert resp.status_code == 200
    assert resp.json()["running_jobs"] == 0


def test_health_running_jobs_counts_active_statuses(health_client):
    client, store = health_client

    _add_job(store, "succeeded")
    _add_job(store, "running")
    _add_job(store, "queued")
    _add_job(store, "canceling")
    _add_job(store, "failed")

    resp = client.get("/api/health", headers={"Authorization": "Bearer test-health-token"})
    assert resp.status_code == 200
    # running + queued + canceling = 3
    assert resp.json()["running_jobs"] == 3


def test_health_running_jobs_excludes_terminal(health_client):
    client, store = health_client

    for status in ("succeeded", "failed", "canceled"):
        _add_job(store, status)

    resp = client.get("/api/health", headers={"Authorization": "Bearer test-health-token"})
    assert resp.status_code == 200
    assert resp.json()["running_jobs"] == 0


def test_health_product_version_is_distinct_from_contract_version(health_client):
    """Guards against the historical bug where the product release (e.g. 3.0.0)
    and the report/spec contract version (e.g. 2.4) were conflated under a
    single ambiguous "version" key."""
    client, _ = health_client

    resp = client.get("/api/health", headers={"Authorization": "Bearer test-health-token"})
    assert resp.status_code == 200
    body = resp.json()

    assert body["product_version"] == app_module.PRODUCT_VERSION
    assert body["contract_version"] == app_module.CONTRACT_VERSION
    assert body["build_commit"] == app_module.BUILD_COMMIT


def test_health_fields_are_wired_to_their_authoritative_source(health_client, monkeypatch):
    """Each unambiguous field must reflect its own module-level source of truth,
    independently of the other two — proving they aren't accidentally aliased
    to the same underlying value."""
    client, _ = health_client

    monkeypatch.setattr(app_module, "PRODUCT_VERSION", "9.9.9")
    monkeypatch.setattr(app_module, "CONTRACT_VERSION", "1.1")
    monkeypatch.setattr(app_module, "BUILD_COMMIT", "deadbeef")

    resp = client.get("/api/health", headers={"Authorization": "Bearer test-health-token"})
    assert resp.status_code == 200
    body = resp.json()

    assert body["product_version"] == "9.9.9"
    assert body["contract_version"] == "1.1"
    assert body["build_commit"] == "deadbeef"


def test_health_legacy_fields_preserve_backward_compatible_semantics(health_client, monkeypatch):
    """"version" and "server_version" are deprecated but must keep aliasing
    exactly what they historically meant (contract version and build commit,
    respectively) so existing clients do not silently break."""
    client, _ = health_client

    monkeypatch.setattr(app_module, "CONTRACT_VERSION", "1.1")
    monkeypatch.setattr(app_module, "BUILD_COMMIT", "deadbeef")

    resp = client.get("/api/health", headers={"Authorization": "Bearer test-health-token"})
    body = resp.json()

    assert body["version"] == body["contract_version"] == "1.1"
    assert body["server_version"] == body["build_commit"] == "deadbeef"


def test_api_version_exposes_product_version_and_build_commit(health_client, monkeypatch):
    client, _ = health_client

    monkeypatch.setattr(app_module, "PRODUCT_VERSION", "9.9.9")
    monkeypatch.setattr(app_module, "BUILD_COMMIT", "deadbeef")

    resp = client.get("/api/version", headers={"Authorization": "Bearer test-health-token"})
    assert resp.status_code == 200
    body = resp.json()

    assert body["product_version"] == "9.9.9"
    assert body["build_commit"] == "deadbeef"
    # Legacy alias: "version" here historically mirrored the build commit, not
    # the product release version — must be preserved for older clients.
    assert body["version"] == "deadbeef"
    assert "build_id" in body
    assert "started_at" in body
