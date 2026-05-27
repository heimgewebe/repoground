import pytest
import importlib
from fastapi.testclient import TestClient
from pathlib import Path
import tempfile
import logging
from types import SimpleNamespace
from merger.lenskit.service.app import app, init_service, state
from merger.lenskit.service.models import JobRequest, Artifact
from datetime import datetime, timezone
import uuid

@pytest.fixture
def client_and_hub():
    with tempfile.TemporaryDirectory() as tmp:
        hub = Path(tmp) / "hub"
        hub.mkdir()
        (hub / "repo1").mkdir() # Required for validation
        (hub / "repo_reuse").mkdir()
        (hub / "repo3").mkdir()
        (hub / "repo_rob").mkdir()
        (hub / "repo_safe").mkdir()
        (hub / "repoA").mkdir()

        init_service(hub, token="test-token")

        # Mock runner to avoid real execution
        if state.runner:
            original_submit = state.runner.submit_job
            state.runner.submit_job = lambda jid: None # Do nothing
        else:
            original_submit = None

        with TestClient(app) as c:
            yield c, str(hub.resolve())

        if state.runner and original_submit:
            state.runner.submit_job = original_submit

def test_idempotency_and_decoupling(client_and_hub):
    client, hub_path = client_and_hub
    req = {
        "hub": hub_path,
        "repos": ["repo1"],
        "level": "max"
    }
    headers = {"Authorization": "Bearer test-token"}

    # First create
    resp1 = client.post("/api/jobs", json=req, headers=headers)
    assert resp1.status_code == 200, resp1.text
    job1 = resp1.json()

    # Different output dir -> Should be SAME job (hash decoupling)
    req["merges_dir"] = "/tmp/out_different"
    resp2 = client.post("/api/jobs", json=req, headers=headers)
    assert resp2.status_code == 200
    job2 = resp2.json()

    assert job1["id"] == job2["id"], "Hash should ignore merges_dir"

def test_reuse_finished(client_and_hub):
    client, hub_path = client_and_hub
    req = {"hub": hub_path, "repos": ["repo_reuse"]}
    headers = {"Authorization": "Bearer test-token"}

    # 1. Create and finish
    resp1 = client.post("/api/jobs", json=req, headers=headers)
    job1 = resp1.json()
    job_id = job1["id"]

    job = state.job_store.get_job(job_id)
    job.status = "succeeded"
    state.job_store.update_job(job)

    # 2. Create again -> Should match
    resp2 = client.post("/api/jobs", json=req, headers=headers)
    job2 = resp2.json()
    assert job2["id"] == job1["id"]

def test_log_resume(client_and_hub):
    client, hub_path = client_and_hub
    req = {"hub": hub_path, "repos": ["repo3"]}
    headers = {"Authorization": "Bearer test-token"}
    resp = client.post("/api/jobs", json=req, headers=headers)
    job_id = resp.json()["id"]

    state.job_store.append_log_line(job_id, "Line 1")
    state.job_store.append_log_line(job_id, "Line 2")

    job = state.job_store.get_job(job_id)
    job.status = "succeeded"
    state.job_store.update_job(job)

    # Resume test (skip 1st line)
    headers["Last-Event-ID"] = "1"
    resp_stream = client.get(f"/api/jobs/{job_id}/logs", headers=headers)
    content = resp_stream.content.decode("utf-8")
    assert "Line 1" not in content
    assert "Line 2" in content
    assert "id: 2" in content

def test_log_robustness(client_and_hub):
    # Test missing file (simulate GC race)
    client, hub_path = client_and_hub
    req = {"hub": hub_path, "repos": ["repo_rob"]}
    headers = {"Authorization": "Bearer test-token"}
    resp = client.post("/api/jobs", json=req, headers=headers)
    job_id = resp.json()["id"]

    job = state.job_store.get_job(job_id)
    job.status = "succeeded"
    state.job_store.update_job(job)

    # Ensure no file
    log_p = state.job_store.logs_dir / f"{job_id}.log"
    if log_p.exists():
        log_p.unlink()

    resp_stream = client.get(f"/api/jobs/{job_id}/logs", headers=headers)
    assert resp_stream.status_code == 200

def test_gc_artifacts_physical(client_and_hub):
    client, hub_path = client_and_hub
    req = {"hub": hub_path, "repos": ["repo1"]}
    headers = {"Authorization": "Bearer test-token"}
    resp = client.post("/api/jobs", json=req, headers=headers)
    job_id = resp.json()["id"]

    # Create physical file
    hub_p = Path(hub_path)
    merges_dir = hub_p / "merges"
    merges_dir.mkdir(parents=True, exist_ok=True)
    fpath = merges_dir / "test_artifact.md"
    fpath.write_text("content")

    # Add artifact
    art_id = str(uuid.uuid4())
    req_obj = JobRequest(**req)
    art = Artifact(
        id=art_id, job_id=job_id, hub=hub_path, repos=["repo1"],
        created_at=datetime.now(timezone.utc).isoformat(), paths={"md": "test_artifact.md"}, params=req_obj
    )
    state.job_store.add_artifact(art)

    job = state.job_store.get_job(job_id)
    job.artifact_ids.append(art_id)
    state.job_store.update_job(job)

    # GC
    state.job_store.remove_job(job_id)

    # Verify metadata gone
    assert state.job_store.get_job(job_id) is None
    assert state.job_store.get_artifact(art_id) is None
    # Verify physical file gone
    assert not fpath.exists(), "Physical file should be deleted"

def test_gc_artifacts_physical_safe_join(client_and_hub):
    # Ensure GC cannot delete outside merges dir via traversal
    client, hub_path = client_and_hub
    headers = {"Authorization": "Bearer test-token"}
    req = {"hub": hub_path, "repos": ["repo_safe"]}
    resp = client.post("/api/jobs", json=req, headers=headers)
    job_id = resp.json()["id"]

    hub_p = Path(hub_path)
    merges_dir = hub_p / "merges"
    merges_dir.mkdir(parents=True, exist_ok=True)
    outside = hub_p / "DO_NOT_DELETE.txt"
    outside.write_text("nope")

    art_id = str(uuid.uuid4())
    req_obj = JobRequest(**req)
    art = Artifact(
        id=art_id, job_id=job_id, hub=hub_path, repos=["repo_safe"],
        created_at=datetime.now(timezone.utc).isoformat(),
        paths={"md": "../DO_NOT_DELETE.txt"},
        params=req_obj
    )
    state.job_store.add_artifact(art)
    job = state.job_store.get_job(job_id)
    job.artifact_ids.append(art_id)
    state.job_store.update_job(job)

    state.job_store.remove_job(job_id)
    assert outside.exists(), "Traversal path must not be deleted"

def test_create_job_blocks_dirty_repo_keys(client_and_hub):
    """
    Backend Hardening: Ensure that sending a dirty repo key (e.g. traversal attempt)
    results in a 400 Bad Request, even if the frontend check is bypassed.
    Strict Allowlist Check: alphanumeric, dot, underscore, dash.
    """
    client, hub_path = client_and_hub
    headers = {"Authorization": "Bearer test-token"}

    invalid_keys = [
        "../dirty",       # traversal
        "repo/sub",       # slash
        "repo\\sub",      # backslash
        ".",              # dot strict
        "..",             # double dot strict
        "repo$name",      # invalid char
        "repo name",      # space
    ]

    for key in invalid_keys:
        payload = {
            "repos": ["repoA", key],
            "hub": hub_path,
            "level": "max",
            "mode": "gesamt"
        }

        response = client.post("/api/jobs", json=payload, headers=headers)
        assert response.status_code == 400, f"Backend accepted invalid key: {key}"
        assert "Invalid repo name" in response.json()["detail"], f"Wrong error for key: {key}"

def test_create_job_allows_valid_keys(client_and_hub):
    """
    Backend Hardening: Verify that valid keys pass the strict filter.
    """
    client, hub_path = client_and_hub
    headers = {"Authorization": "Bearer test-token"}

    # Mock existence of folders for these valid names
    for name in ["repo-name", "repo_name", "repo.name", "123"]:
        (Path(hub_path) / name).mkdir(exist_ok=True)

    valid_keys = ["repo-name", "repo_name", "repo.name", "123"]

    for key in valid_keys:
        payload = {
            "repos": [key],
            "hub": hub_path,
            "level": "max",
            "mode": "gesamt"
        }
        response = client.post("/api/jobs", json=payload, headers=headers)
        assert response.status_code == 200, f"Backend rejected valid key: {key}"

def test_create_job_blocks_absolute_path_repo(client_and_hub):
    """
    Backend Hardening: Ensure absolute paths are rejected as repo names.
    """
    client, hub_path = client_and_hub
    headers = {"Authorization": "Bearer test-token"}

    # Use a platform-agnostic absolute path
    abs_path = str(Path.cwd().resolve())

    payload = {
        "repos": [abs_path],
        "hub": hub_path,
        "level": "max",
        "mode": "gesamt"
    }

    response = client.post("/api/jobs", json=payload, headers=headers)
    assert response.status_code == 400

def test_create_job_fresh_hub_no_state_dir(client_and_hub):
    """
    Job creation recreates the missing .rlens-service state directory.
    """
    client, hub_path = client_and_hub

    # 1. Simulate fresh state by deleting the .rlens-service directory
    from merger.lenskit.core.merge import MERGES_DIR_NAME
    storage_dir = Path(hub_path) / MERGES_DIR_NAME / ".rlens-service"

    import shutil
    if storage_dir.exists():
        shutil.rmtree(storage_dir)

    assert not storage_dir.exists(), "Setup failed: .rlens-service must not exist"

    # 2. Test saving with the existing JobStore instance when the state directory is gone.
    # Note: init_service in the fixture already created the directory,
    # but when we call /api/jobs, it uses the existing `state.job_store`.
    # Since we just deleted the directory, the next write operation (save_jobs)
    # will fail if not handled properly.

    headers = {"Authorization": "Bearer test-token"}
    payload = {
        "repos": ["repo1"],
        "hub": hub_path,
        "level": "max",
        "mode": "gesamt"
    }

    # 3. Create a job. This should trigger _save_jobs which should now recreate the parent dir.
    response = client.post("/api/jobs", json=payload, headers=headers)

    # 4. Assert that it worked and no FileNotFoundError was raised
    assert response.status_code == 200, f"Failed to create job on fresh hub: {response.text}"
    job_data = response.json()
    assert "id" in job_data

    # 5. Verify the directory and jobs.json were created
    assert storage_dir.exists(), "State directory was not recreated"
    assert (storage_dir / "jobs.json").exists(), "jobs.json was not created"

def test_get_server_version_logs_debug_on_git_failure(monkeypatch, caplog):
    import subprocess
    import merger.lenskit.service.app as service_app

    monkeypatch.delenv("RLENS_VERSION", raising=False)

    def fail_check_output(*args, **kwargs):
        raise RuntimeError("git unavailable")

    monkeypatch.setattr(subprocess, "check_output", fail_check_output)

    with caplog.at_level(logging.DEBUG, logger="merger.lenskit.service.app"):
        version = service_app._get_server_version()

    assert version == "dev"
    assert any("Falling back to dev server version" in rec.message for rec in caplog.records)

def test_app_module_reload_survives_git_failure_during_server_version_init(monkeypatch, caplog):
    import subprocess
    import merger.lenskit.service.app as service_app

    monkeypatch.delenv("RLENS_VERSION", raising=False)

    def fail_check_output(*args, **kwargs):
        raise RuntimeError("git unavailable during import")

    monkeypatch.setattr(subprocess, "check_output", fail_check_output)

    with caplog.at_level(logging.DEBUG, logger="merger.lenskit.service.app"):
        reloaded = importlib.reload(service_app)

    assert reloaded.SERVER_VERSION == "dev"
    assert reloaded.logger.name == "merger.lenskit.service.app"
    assert any("Falling back to dev server version" in rec.message for rec in caplog.records)

def test_api_fs_list_logs_debug_when_parent_token_generation_fails(monkeypatch, caplog, tmp_path):
    import merger.lenskit.service.app as service_app

    trusted_path = tmp_path / "allowed" / "child"
    trusted_path.mkdir(parents=True)

    monkeypatch.setattr(
        service_app,
        "resolve_fs_path",
        lambda **kwargs: SimpleNamespace(path=trusted_path),
    )
    monkeypatch.setattr(service_app, "_list_dir", lambda path: {"entries": []})

    class FailingSecurityConfig:
        def validate_path(self, path):
            raise RuntimeError("parent blocked")

    monkeypatch.setattr(service_app, "get_security_config", lambda: FailingSecurityConfig())
    monkeypatch.setattr(service_app.state, "hub", tmp_path)
    monkeypatch.setattr(service_app.state, "merges_dir", tmp_path / "merges", raising=False)

    with caplog.at_level(logging.DEBUG, logger="merger.lenskit.service.app"):
        payload = service_app.api_fs_list(token="opaque")

    assert "parent_token" not in payload
    assert any("Skipping parent token generation" in rec.message for rec in caplog.records)
