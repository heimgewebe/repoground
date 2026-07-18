import pytest

import merger.repoground.service.app as service_app
from merger.repoground.service.models import Job, JobRequest


def _add_job(store, status: str) -> Job:
    job = Job.create(request=JobRequest(repos=["repo-test"]))
    job.status = status
    store.add_job(job)
    return job


@pytest.fixture(autouse=True)
def _clear_restart_env(monkeypatch):
    for name in (
        "REPOGROUND_ENABLE_SERVICE_RESTART",
        "REPOGROUND_SERVICE_UNIT",
        "RLENS_ENABLE_SERVICE_RESTART",
        "RLENS_SERVICE_UNIT",
    ):
        monkeypatch.delenv(name, raising=False)


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
    monkeypatch.setenv("REPOGROUND_ENABLE_SERVICE_RESTART", "1")
    monkeypatch.setenv("REPOGROUND_SERVICE_UNIT", "repoground")
    called = []
    monkeypatch.setattr(service_app, "_schedule_service_restart", lambda unit: called.append(unit))

    resp = service_client.client.post("/api/admin/restart", headers=service_client.headers)

    assert resp.status_code == 202
    assert resp.json() == {
        "status": "scheduled",
        "unit": "repoground",
        "message": "RepoGround restart scheduled",
    }
    assert called == ["repoground"]


def test_admin_restart_ignores_legacy_unit_name_after_cutover(
    service_client, monkeypatch
):
    # The legacy feature flag remains a bounded configuration fallback, but the
    # retired rlens.service unit can no longer be selected.
    monkeypatch.setenv("RLENS_ENABLE_SERVICE_RESTART", "1")
    monkeypatch.setenv("RLENS_SERVICE_UNIT", "rlens")
    called = []
    monkeypatch.setattr(service_app, "_schedule_service_restart", lambda unit: called.append(unit))

    resp = service_client.client.post("/api/admin/restart", headers=service_client.headers)

    assert resp.status_code == 202
    assert resp.json() == {
        "status": "scheduled",
        "unit": "repoground",
        "message": "RepoGround restart scheduled",
    }
    assert called == ["repoground"]


def test_admin_capabilities_true_when_restart_enabled(service_client, monkeypatch):
    monkeypatch.setenv("REPOGROUND_ENABLE_SERVICE_RESTART", "1")
    monkeypatch.setenv("REPOGROUND_SERVICE_UNIT", "repoground")
    resp = service_client.client.get("/api/admin/capabilities", headers=service_client.headers)
    assert resp.status_code == 200
    assert resp.json() == {"service_restart_enabled": True}


def test_admin_restart_fail_closed_for_invalid_unit(service_client, monkeypatch):
    monkeypatch.setenv("REPOGROUND_ENABLE_SERVICE_RESTART", "1")
    monkeypatch.setenv("REPOGROUND_SERVICE_UNIT", "repoground;rm -rf /")
    called = []
    monkeypatch.setattr(service_app, "_schedule_service_restart", lambda unit: called.append(unit))

    resp = service_client.client.post("/api/admin/restart", headers=service_client.headers)

    assert resp.status_code == 403
    assert resp.json()["detail"] == "Service restart is disabled"
    assert called == []


def test_admin_restart_blocked_when_jobs_running(service_client, monkeypatch):
    monkeypatch.setenv("REPOGROUND_ENABLE_SERVICE_RESTART", "1")
    monkeypatch.setenv("REPOGROUND_SERVICE_UNIT", "repoground")
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
    monkeypatch.setenv("REPOGROUND_ENABLE_SERVICE_RESTART", "1")
    monkeypatch.setenv("REPOGROUND_SERVICE_UNIT", "repoground")

    def _boom(unit: str) -> None:
        raise RuntimeError("dbus unavailable")

    monkeypatch.setattr(service_app, "_schedule_service_restart", _boom)

    resp = service_client.client.post("/api/admin/restart", headers=service_client.headers)

    assert resp.status_code == 503
    assert resp.json() == {
        "status": "error",
        "reason": "scheduler_failed",
    }

def test_admin_restart_forbidden_when_service_is_not_loopback(service_client, monkeypatch):
    monkeypatch.setenv("REPOGROUND_ENABLE_SERVICE_RESTART", "1")
    monkeypatch.setenv("REPOGROUND_SERVICE_UNIT", "repoground")
    monkeypatch.setattr(service_app.state, "host", "0.0.0.0")
    called = []
    monkeypatch.setattr(service_app, "_schedule_service_restart", lambda unit: called.append(unit))

    caps = service_client.client.get("/api/admin/capabilities", headers=service_client.headers)
    assert caps.status_code == 200
    assert caps.json() == {"service_restart_enabled": False}

    resp = service_client.client.post("/api/admin/restart", headers=service_client.headers)
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Service restart is disabled"
    assert called == []
