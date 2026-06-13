import pytest
from fastapi.testclient import TestClient

import merger.lenskit.service.app as service_app
from merger.lenskit.service.app import app, init_service
from merger.lenskit.service.models import Job, JobRequest


def _add_job(store, status: str) -> Job:
    job = Job.create(request=JobRequest(repos=["repo-test"]))
    job.status = status
    store.add_job(job)
    return job


@pytest.fixture(autouse=True)
def _clear_restart_env(monkeypatch):
    monkeypatch.delenv("RLENS_ENABLE_SERVICE_RESTART", raising=False)
    monkeypatch.delenv("RLENS_SERVICE_UNIT", raising=False)


def test_admin_capabilities_false_when_restart_disabled(service_client):
    resp = service_client.client.get("/api/admin/capabilities", headers=service_client.headers)
    assert resp.status_code == 200
    assert resp.json() == {"service_restart_enabled": False}


def test_admin_restart_forbidden_when_feature_disabled(service_client, monkeypatch):
    called = []
    monkeypatch.setattr(service_app, "_schedule_service_restart", lambda unit: called.append(unit))

    resp = service_client.client.post("/api/admin/restart", headers=service_client.headers)

    assert resp.status_code == 403
    assert resp.json()["detail"] == "Service restart is disabled"
    assert called == []


def test_admin_restart_returns_202_when_enabled(service_client, monkeypatch):
    monkeypatch.setenv("RLENS_ENABLE_SERVICE_RESTART", "1")
    monkeypatch.setenv("RLENS_SERVICE_UNIT", "rlens")
    called = []
    monkeypatch.setattr(service_app, "_schedule_service_restart", lambda unit: called.append(unit))

    resp = service_client.client.post("/api/admin/restart", headers=service_client.headers)

    assert resp.status_code == 202
    assert resp.json() == {
        "status": "scheduled",
        "unit": "rlens",
        "message": "rLens restart scheduled",
    }
    assert called == ["rlens"]


def test_admin_capabilities_true_when_restart_enabled(service_client, monkeypatch):
    monkeypatch.setenv("RLENS_ENABLE_SERVICE_RESTART", "1")
    monkeypatch.setenv("RLENS_SERVICE_UNIT", "rlens")
    resp = service_client.client.get("/api/admin/capabilities", headers=service_client.headers)
    assert resp.status_code == 200
    assert resp.json() == {"service_restart_enabled": True}


def test_admin_restart_fail_closed_for_invalid_unit(service_client, monkeypatch):
    monkeypatch.setenv("RLENS_ENABLE_SERVICE_RESTART", "1")
    monkeypatch.setenv("RLENS_SERVICE_UNIT", "rlens;rm -rf /")
    called = []
    monkeypatch.setattr(service_app, "_schedule_service_restart", lambda unit: called.append(unit))

    resp = service_client.client.post("/api/admin/restart", headers=service_client.headers)

    assert resp.status_code == 403
    assert resp.json()["detail"] == "Service restart is disabled"
    assert called == []


def test_admin_restart_blocked_when_jobs_running(service_client, monkeypatch):
    monkeypatch.setenv("RLENS_ENABLE_SERVICE_RESTART", "1")
    monkeypatch.setenv("RLENS_SERVICE_UNIT", "rlens")
    called = []
    monkeypatch.setattr(service_app, "_schedule_service_restart", lambda unit: called.append(unit))
    _add_job(service_client.store, "running")

    resp = service_client.client.post("/api/admin/restart", headers=service_client.headers)

    assert resp.status_code == 409
    assert resp.json()["status"] == "blocked"
    assert resp.json()["reason"] == "jobs_running"
    assert resp.json()["running_jobs"] == 1
    assert called == []


def test_admin_restart_returns_scheduler_error_without_traceback(service_client, monkeypatch):
    monkeypatch.setenv("RLENS_ENABLE_SERVICE_RESTART", "1")
    monkeypatch.setenv("RLENS_SERVICE_UNIT", "rlens")

    def _boom(unit: str) -> None:
        raise RuntimeError("dbus unavailable")

    monkeypatch.setattr(service_app, "_schedule_service_restart", _boom)

    resp = service_client.client.post("/api/admin/restart", headers=service_client.headers)

    assert resp.status_code == 503
    assert resp.json() == {
        "status": "error",
        "reason": "scheduler_failed",
    }


def test_admin_restart_forbidden_when_service_is_not_loopback(tmp_path, monkeypatch):
    monkeypatch.setenv("RLENS_ENABLE_SERVICE_RESTART", "1")
    monkeypatch.setenv("RLENS_SERVICE_UNIT", "rlens")
    called = []
    monkeypatch.setattr(service_app, "_schedule_service_restart", lambda unit: called.append(unit))

    hub = tmp_path / "hub"
    hub.mkdir()
    (hub / "repo-test").mkdir()

    app.middleware_stack = None
    init_service(hub, token="test-token", host="0.0.0.0")

    with TestClient(app) as client:
        headers = {"Authorization": "Bearer test-token"}

        caps = client.get("/api/admin/capabilities", headers=headers)
        assert caps.status_code == 200
        assert caps.json() == {"service_restart_enabled": False}

        resp = client.post("/api/admin/restart", headers=headers)
        assert resp.status_code == 403
        assert resp.json()["detail"] == "Service restart is disabled"

    assert called == []
