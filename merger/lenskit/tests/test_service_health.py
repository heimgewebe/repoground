"""Tests for /api/health endpoint — specifically running_jobs correctness."""
import pytest
from merger.lenskit.service.app import app, init_service, state
from merger.lenskit.service.models import Job, JobRequest


@pytest.fixture
def health_client(tmp_path):
    hub = tmp_path / "hub"
    hub.mkdir()
    (hub / "repo1").mkdir()

    import os
    os.environ["RLENS_TOKEN"] = "test-health-token"

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
