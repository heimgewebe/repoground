import time


def _wait_terminal(ctx, job_id, timeout_s=5.0):
    """Wait for the background runner to reach a terminal state so a later manual
    status write cannot be overwritten by the worker thread."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        job = ctx.store.get_job(job_id)
        if job and job.status in ("succeeded", "failed", "canceled"):
            return job
        time.sleep(0.02)
    return ctx.store.get_job(job_id)


def _force_status(ctx, job_id, status):
    _wait_terminal(ctx, job_id)
    job = ctx.store.get_job(job_id)
    job.status = status
    ctx.store.update_job(job)
    return job


def test_succeeded_not_reused_when_pre_pull_true(service_client):
    """A real pre_pull=True request must NOT reuse a cached succeeded job."""
    ctx = service_client
    req = {"repos": ["repo-test"], "level": "summary", "pre_pull": True}

    resp1 = ctx.client.post("/api/jobs", json=req, headers=ctx.headers)
    assert resp1.status_code == 200
    job1_id = resp1.json()["id"]
    _force_status(ctx, job1_id, "succeeded")

    resp2 = ctx.client.post("/api/jobs", json=req, headers=ctx.headers)
    assert resp2.status_code == 200
    assert resp2.json()["id"] != job1_id, "pre_pull=True must force a fresh job"


def test_succeeded_reused_when_pre_pull_false(service_client):
    """pre_pull=False may reuse a cached succeeded job (no fresh-sync expectation)."""
    ctx = service_client
    req = {"repos": ["repo-test"], "level": "summary", "pre_pull": False}

    resp1 = ctx.client.post("/api/jobs", json=req, headers=ctx.headers)
    assert resp1.status_code == 200
    job1_id = resp1.json()["id"]
    _force_status(ctx, job1_id, "succeeded")

    resp2 = ctx.client.post("/api/jobs", json=req, headers=ctx.headers)
    assert resp2.status_code == 200
    assert resp2.json()["id"] == job1_id, "pre_pull=False should reuse the succeeded job"


def test_active_job_reused_even_when_pre_pull_true(service_client):
    """An identical *active* job is still reusable even with pre_pull=True."""
    ctx = service_client
    req = {"repos": ["repo-test"], "level": "summary", "pre_pull": True}

    resp1 = ctx.client.post("/api/jobs", json=req, headers=ctx.headers)
    assert resp1.status_code == 200
    job1_id = resp1.json()["id"]
    # Let the worker finish, then re-mark active so the worker can't change it again.
    _force_status(ctx, job1_id, "running")

    resp2 = ctx.client.post("/api/jobs", json=req, headers=ctx.headers)
    assert resp2.status_code == 200
    assert resp2.json()["id"] == job1_id, "active identical job should be reused"


def test_explicit_reuse_policy(service_client):
    ctx = service_client

    # 1. Create initial job
    # We use a unique payload to ensure no collisions with other tests
    req_payload = {
        "repos": ["repo-test"],
        "level": "summary",
        "plan_only": True
    }

    resp1 = ctx.client.post("/api/jobs", json=req_payload, headers=ctx.headers)
    assert resp1.status_code == 200
    job1 = resp1.json()
    job1_id = job1["id"]

    # Simulate job completion to allow reuse
    # We access the store directly to update status
    job_obj = ctx.store.get_job(job1_id)
    assert job_obj is not None
    job_obj.status = "succeeded"
    ctx.store.update_job(job_obj)

    # 2. Create identical job (expect REUSE)
    resp2 = ctx.client.post("/api/jobs", json=req_payload, headers=ctx.headers)
    assert resp2.status_code == 200
    job2 = resp2.json()
    assert job2["id"] == job1_id

    # 3. Create identical job with force_new=True (expect NEW)
    req_payload_forced = req_payload.copy()
    req_payload_forced["force_new"] = True

    resp3 = ctx.client.post("/api/jobs", json=req_payload_forced, headers=ctx.headers)
    assert resp3.status_code == 200
    job3 = resp3.json()

    assert job3["id"] != job1_id

    # Verify job3 exists
    assert ctx.store.get_job(job3["id"]) is not None

def test_force_new_ignored_if_no_existing(service_client):
    ctx = service_client

    # Create job with force_new=True but no prior job exists
    req_payload = {
        "repos": ["repo-test"],
        "level": "max",
        "plan_only": True,
        "force_new": True
    }
    resp = ctx.client.post("/api/jobs", json=req_payload, headers=ctx.headers)
    assert resp.status_code == 200
    job = resp.json()

    assert ctx.store.get_job(job["id"]) is not None


def test_whitespace_only_include_paths_collapsed_to_none(service_client):
    """
    Ensure that whitespace-only paths (e.g. "   ") are treated consistently with ""
    and collapse the selection to None (All) under non-strict semantics.
    """
    ctx = service_client

    # Create job with an explicit empty string include path
    req_payload_empty = {
        "repos": ["repo-test"],
        "level": "summary",
        "plan_only": True,
        "strict_include_paths_by_repo": False,
        "include_paths_by_repo": {
            "repo-test": [""]
        }
    }
    resp1 = ctx.client.post("/api/jobs", json=req_payload_empty, headers=ctx.headers)
    assert resp1.status_code == 200
    job1_id = resp1.json()["id"]

    # Simulate completion
    job_obj = ctx.store.get_job(job1_id)
    job_obj.status = "succeeded"
    ctx.store.update_job(job_obj)

    # Create job with a whitespace-only include path
    req_payload_space = {
        "repos": ["repo-test"],
        "level": "summary",
        "plan_only": True,
        "strict_include_paths_by_repo": False,
        "include_paths_by_repo": {
            "repo-test": ["   "]
        }
    }
    resp2 = ctx.client.post("/api/jobs", json=req_payload_space, headers=ctx.headers)
    assert resp2.status_code == 200
    job2_id = resp2.json()["id"]

    # Should reuse the exact same job since both normalize to None
    assert job1_id == job2_id


def test_whitespace_only_global_include_paths_collapsed_to_none(service_client):
    """
    Ensure that global whitespace-only paths (e.g. "   ") in include_paths
    are treated consistently with "" and collapse the selection to None (All).
    """
    ctx = service_client

    # Create job with an explicit empty string global include path
    req_payload_empty = {
        "repos": ["repo-test"],
        "level": "summary",
        "plan_only": True,
        "include_paths": [""]
    }
    resp1 = ctx.client.post("/api/jobs", json=req_payload_empty, headers=ctx.headers)
    assert resp1.status_code == 200
    job1_id = resp1.json()["id"]

    # Simulate completion
    job_obj = ctx.store.get_job(job1_id)
    job_obj.status = "succeeded"
    ctx.store.update_job(job_obj)

    # Create job with a whitespace-only global include path
    req_payload_space = {
        "repos": ["repo-test"],
        "level": "summary",
        "plan_only": True,
        "include_paths": ["   "]
    }
    resp2 = ctx.client.post("/api/jobs", json=req_payload_space, headers=ctx.headers)
    assert resp2.status_code == 200
    job2_id = resp2.json()["id"]

    # Should reuse the exact same job since both normalize to None
    assert job1_id == job2_id


def test_plan_only_pre_pull_uses_effective_hash():
    """plan_only never mutates repos, so raw pre_pull must not split the job hash."""
    from merger.lenskit.service.models import JobRequest, calculate_job_hash

    hub = "/tmp/lenskit-test-hub"
    version = "test-version"

    plan_pre = JobRequest(repos=["repo-test"], level="summary", plan_only=True, pre_pull=True)
    plan_no_pre = JobRequest(repos=["repo-test"], level="summary", plan_only=True, pre_pull=False)
    real_pre = JobRequest(repos=["repo-test"], level="summary", plan_only=False, pre_pull=True)
    real_no_pre = JobRequest(repos=["repo-test"], level="summary", plan_only=False, pre_pull=False)

    assert calculate_job_hash(plan_pre, hub, version) == calculate_job_hash(plan_no_pre, hub, version)
    assert calculate_job_hash(real_pre, hub, version) != calculate_job_hash(real_no_pre, hub, version)


def test_succeeded_job_not_reused_when_source_mode_local_ff_even_if_pre_pull_false(service_client):
    """repo_source_mode='local_ff' enforces a fresh check even if legacy pre_pull is False."""
    ctx = service_client
    req = {
        "repos": ["repo-test"],
        "level": "summary",
        "repo_source_mode": "local_ff",
        "pre_pull": False,
    }
    resp1 = ctx.client.post("/api/jobs", json=req, headers=ctx.headers)
    assert resp1.status_code == 200
    job1_id = resp1.json()["id"]
    _force_status(ctx, job1_id, "succeeded")

    # Repeat exact request
    resp2 = ctx.client.post("/api/jobs", json=req, headers=ctx.headers)
    assert resp2.status_code == 200
    assert resp2.json()["id"] != job1_id


def test_succeeded_job_reused_when_source_mode_local_current_even_if_pre_pull_true(service_client):
    """repo_source_mode='local_current' prevents fresh check even if legacy pre_pull is True."""
    ctx = service_client
    req = {"repos": ["repo-test"], "level": "summary", "repo_source_mode": "local_current", "pre_pull": True}
    resp1 = ctx.client.post("/api/jobs", json=req, headers=ctx.headers)
    assert resp1.status_code == 200
    job1_id = resp1.json()["id"]
    _force_status(ctx, job1_id, "succeeded")

    # Repeat exact request
    resp2 = ctx.client.post("/api/jobs", json=req, headers=ctx.headers)
    assert resp2.status_code == 200
    assert resp2.json()["id"] == job1_id


def test_succeeded_job_not_reused_when_source_mode_remote_snapshot(service_client):
    """repo_source_mode='remote_snapshot' never reuses succeeded jobs (remote ref might have moved)."""
    ctx = service_client
    req = {"repos": ["repo-test"], "level": "summary", "repo_source_mode": "remote_snapshot"}
    resp1 = ctx.client.post("/api/jobs", json=req, headers=ctx.headers)
    assert resp1.status_code == 200
    job1_id = resp1.json()["id"]
    _force_status(ctx, job1_id, "succeeded")

    # Repeat exact request
    resp2 = ctx.client.post("/api/jobs", json=req, headers=ctx.headers)
    assert resp2.status_code == 200
    assert resp2.json()["id"] != job1_id
