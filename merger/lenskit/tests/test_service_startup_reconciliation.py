"""Tests for startup reconciliation of persisted active jobs."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from merger.lenskit.service.app import ACTIVE_JOB_STATUSES, app, init_service, state
from merger.lenskit.service.models import Job, JobRequest


@pytest.fixture
def persisted_jobs_hub(tmp_path):
    hub = tmp_path / "hub"
    hub.mkdir()
    (hub / "repo1").mkdir()

    storage_dir = hub / "merges" / ".rlens-service"
    storage_dir.mkdir(parents=True)

    return hub


def _make_job(job_id: str, status: str) -> Job:
    request = JobRequest(repos=["repo1"])
    job = Job.create(request=request)
    job.id = job_id
    job.status = status
    job.created_at = "2026-05-15T00:00:00+00:00"
    if status in {"running", "canceling"}:
        job.started_at = "2026-05-15T00:01:00+00:00"
    return job


def _write_jobs_file(hub: Path, jobs: list[Job]) -> None:
    jobs_file = hub / "merges" / ".rlens-service" / "jobs.json"
    jobs_file.write_text(
        json.dumps([job.model_dump() for job in jobs], indent=2),
        encoding="utf-8",
    )


def test_init_service_reconciles_persisted_active_jobs(persisted_jobs_hub):
    jobs = [
        _make_job("queued-job", "queued"),
        _make_job("running-job", "running"),
        _make_job("canceling-job", "canceling"),
        _make_job("succeeded-job", "succeeded"),
        _make_job("failed-job", "failed"),
        _make_job("canceled-job", "canceled"),
    ]
    _write_jobs_file(persisted_jobs_hub, jobs)

    app.middleware_stack = None
    init_service(persisted_jobs_hub, token="test-token")

    store = state.job_store
    assert store is not None

    active_after_restart = [job for job in store.get_all_jobs() if job.status in ACTIVE_JOB_STATUSES]
    assert active_after_restart == []

    for job_id in ("queued-job", "running-job", "canceling-job"):
        job = store.get_job(job_id)
        assert job is not None
        assert job.status == "failed"
        assert job.error == "interrupted by service restart; job was not resumed"
        assert job.finished_at is not None
        assert any("service startup" in line for line in store.read_log_lines(job_id))

    for job_id, expected_status in (
        ("succeeded-job", "succeeded"),
        ("failed-job", "failed"),
        ("canceled-job", "canceled"),
    ):
        job = store.get_job(job_id)
        assert job is not None
        assert job.status == expected_status
        assert job.error is None

    with TestClient(app) as client:
        response = client.get("/api/health", headers={"Authorization": "Bearer test-token"})
        assert response.status_code == 200
        assert response.json()["running_jobs"] == 0


def test_init_service_leaves_terminal_jobs_unchanged(persisted_jobs_hub):
    jobs = [
        _make_job("succeeded-job", "succeeded"),
        _make_job("failed-job", "failed"),
        _make_job("canceled-job", "canceled"),
    ]
    _write_jobs_file(persisted_jobs_hub, jobs)

    app.middleware_stack = None
    init_service(persisted_jobs_hub, token="test-token")

    store = state.job_store
    assert store is not None

    for job_id, expected_status in (
        ("succeeded-job", "succeeded"),
        ("failed-job", "failed"),
        ("canceled-job", "canceled"),
    ):
        job = store.get_job(job_id)
        assert job is not None
        assert job.status == expected_status
        assert job.error is None
