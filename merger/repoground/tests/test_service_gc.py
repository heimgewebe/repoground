
import uuid
import logging
import os
from pathlib import Path
from merger.repoground.service.models import Job, Artifact, JobRequest

def test_gc_deletes_real_artifacts(service_client):
    ctx = service_client

    # 1. Create a dummy physical file inside merges_dir
    dummy_file = ctx.merges_dir / "dummy-artifact.md"
    dummy_file.write_text("content", encoding="utf-8")
    assert dummy_file.exists()

    # 2. Create Job and Artifact
    # Construct Job cleanly
    req = JobRequest()
    job = Job.create(req)
    # Override ID to match our test setup if needed, but create() gives random UUID.
    # We can just use the returned object.

    job.status = "succeeded"
    ctx.store.add_job(job)

    art_id = str(uuid.uuid4())

    art = Artifact(
        id=art_id,
        job_id=job.id,
        hub=str(ctx.hub_path),
        repos=[],
        created_at=job.created_at,
        paths={"md": dummy_file.name}, # relative filename
        params=req
    )
    ctx.store.add_artifact(art)

    job.artifact_ids.append(art_id)
    ctx.store.update_job(job)

    # 3. Call remove_job
    ctx.store.remove_job(job.id)

    # 4. Assert Job gone
    assert ctx.store.get_job(job.id) is None

    # 5. Assert Artifact gone from DB
    assert ctx.store.get_artifact(art_id) is None

    # 6. Assert Physical File gone
    assert not dummy_file.exists()

def test_gc_safe_unlink(service_client):
    """Ensure GC doesn't delete files outside merges dir"""
    ctx = service_client

    # Create sensitive file outside merges (in parent temp dir)
    # ctx.merges_dir is inside temp/hub/merges
    # We go up to temp root
    sensitive_file = ctx.merges_dir.parent.parent / "sensitive.txt"
    sensitive_file.write_text("secret")

    # Create Job/Artifact pointing to it via traversal
    req = JobRequest()
    job = Job.create(req)
    ctx.store.add_job(job)

    art_id = str(uuid.uuid4())
    # Try to traverse up: ../../sensitive.txt
    # merges_dir is usually absolute.
    # Artifact.paths are joined with merges_dir.
    # We simulate a path that tries to escape.

    # Note: The service logic usually does: (base / rel).resolve().relative_to(base)
    # We rely on that check in _safe_unlink or similar.

    rel_path = f"../../{sensitive_file.name}"

    art = Artifact(
        id=art_id,
        job_id=job.id,
        hub=str(ctx.hub_path),
        repos=[],
        created_at=job.created_at,
        paths={"secret": rel_path},
        params=req
    )
    ctx.store.add_artifact(art)
    job.artifact_ids.append(art_id)
    ctx.store.update_job(job)

    ctx.store.remove_job(job.id)

    # Verify sensitive file still exists
    assert sensitive_file.exists()
    assert sensitive_file.read_text() == "secret"

def test_gc_logs_warning_when_artifact_delete_fails(service_client, monkeypatch, caplog):
    ctx = service_client

    dummy_file = ctx.merges_dir / "warn-artifact.md"
    dummy_file.write_text("content", encoding="utf-8")

    req = JobRequest()
    job = Job.create(req)
    job.status = "succeeded"
    ctx.store.add_job(job)

    art_id = str(uuid.uuid4())
    art = Artifact(
        id=art_id,
        job_id=job.id,
        hub=str(ctx.hub_path),
        repos=[],
        created_at=job.created_at,
        paths={"md": dummy_file.name},
        params=req,
    )
    ctx.store.add_artifact(art)
    job.artifact_ids.append(art_id)
    ctx.store.update_job(job)

    original_unlink = Path.unlink

    def fail_once(path_obj, *args, **kwargs):
        if path_obj == dummy_file:
            raise OSError("simulated unlink failure")
        return original_unlink(path_obj, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_once)

    with caplog.at_level(logging.WARNING, logger="merger.repoground.service.jobstore"):
        ctx.store.remove_job(job.id)

    assert ctx.store.get_job(job.id) is None
    assert ctx.store.get_artifact(art_id) is None
    assert dummy_file.exists()
    assert any("Failed to delete artifact file" in rec.message for rec in caplog.records)

def test_cleanup_jobs_logs_warning_for_invalid_created_at(service_client, caplog):
    ctx = service_client

    req = JobRequest()
    job = Job.create(req)
    job.created_at = "not-a-timestamp"
    job.status = "succeeded"
    ctx.store.add_job(job)

    with caplog.at_level(logging.WARNING, logger="merger.repoground.service.jobstore"):
        ctx.store.cleanup_jobs(max_jobs=100, max_age_hours=0)

    assert ctx.store.get_job(job.id) is not None
    assert any("Skipping cleanup age check" in rec.message for rec in caplog.records)


def test_snapshot_cleanup_protects_active_jobs_and_removes_terminal_old_jobs(
    service_client,
):
    ctx = service_client
    root = ctx.merges_dir / ".repoground-source-snapshots"
    active = Job.create(JobRequest())
    active.status = "running"
    terminal = Job.create(JobRequest())
    terminal.status = "succeeded"
    ctx.store.add_job(active)
    ctx.store.add_job(terminal)
    for job in (active, terminal):
        directory = root / job.id
        directory.mkdir(parents=True)
        (directory / "payload").write_text(job.id, encoding="utf-8")
        os.utime(directory, (1, 1))

    report = ctx.store.cleanup_source_snapshots(
        apply=True, keep=0, max_age_hours=0, max_bytes=0
    )

    assert report["status"] == "ok"
    assert (root / active.id).is_dir()
    assert not (root / terminal.id).exists()


def test_remove_job_removes_its_source_snapshot(service_client):
    ctx = service_client
    job = Job.create(JobRequest())
    ctx.store.add_job(job)
    snapshot = ctx.merges_dir / ".repoground-source-snapshots" / job.id
    snapshot.mkdir(parents=True)
    (snapshot / "payload").write_text("data", encoding="utf-8")

    ctx.store.remove_job(job.id)

    assert not snapshot.exists()
