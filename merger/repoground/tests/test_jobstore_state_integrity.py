import json
from pathlib import Path

import pytest

from merger.repoground.core.merge import MERGES_DIR_NAME
from merger.repoground.service.jobstore import JobStore
from merger.repoground.service.models import Artifact, Job, JobRequest


def _state_dir(tmp_path: Path) -> Path:
    state_dir = tmp_path / MERGES_DIR_NAME / ".repoground-service"
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir


def _artifact_for(request: JobRequest) -> Artifact:
    job = Job.create(request)
    return Artifact(
        id="artifact-1",
        job_id=job.id,
        hub=request.hub or "",
        repos=request.repos or [],
        created_at=job.created_at,
        paths={},
        params=request,
    )


def _persist_request(
    store: JobStore, *, kind: str, request: JobRequest
) -> tuple[str, str]:
    if kind == "job":
        job = Job.create(request)
        store.add_job(job)
        return "jobs.json", job.id

    artifact = _artifact_for(request)
    store.add_artifact(artifact)
    return "artifacts.json", artifact.id


def _reloaded_request(store: JobStore, *, kind: str, record_id: str) -> JobRequest:
    if kind == "job":
        job = store.get_job(record_id)
        assert job is not None
        return job.request

    artifact = store.get_artifact(record_id)
    assert artifact is not None
    return artifact.params


@pytest.mark.parametrize(
    ("filename", "payload"),
    [
        ("jobs.json", b"[{broken-json"),
        ("jobs.json", b"[{}]"),
        ("artifacts.json", b"[{broken-json"),
        ("artifacts.json", b"[{}]"),
    ],
    ids=[
        "jobs-invalid-json",
        "jobs-invalid-record",
        "artifacts-invalid-json",
        "artifacts-invalid-record",
    ],
)
def test_existing_invalid_state_fails_closed_and_preserves_bytes(
    tmp_path: Path,
    filename: str,
    payload: bytes,
) -> None:
    state_path = _state_dir(tmp_path) / filename
    state_path.write_bytes(payload)

    with pytest.raises(RuntimeError, match="refusing to start"):
        JobStore(tmp_path)

    assert state_path.read_bytes() == payload
    assert not state_path.with_suffix(".tmp").exists()


def test_valid_empty_state_still_loads(tmp_path: Path) -> None:
    state_dir = _state_dir(tmp_path)
    (state_dir / "jobs.json").write_text("[]", encoding="utf-8")
    (state_dir / "artifacts.json").write_text("[]", encoding="utf-8")

    store = JobStore(tmp_path)

    assert store.get_all_jobs() == []
    assert store.get_all_artifacts() == []


@pytest.mark.parametrize("kind", ["job", "artifact"])
@pytest.mark.parametrize("mode", ["local_current", "remote_snapshot"])
def test_bare_source_mode_round_trip_preserves_unset_pre_pull(
    tmp_path: Path,
    kind: str,
    mode: str,
) -> None:
    request = JobRequest(
        hub=str(tmp_path),
        repos=["demo"],
        repo_source_mode=mode,
    )
    assert "pre_pull" not in request.model_fields_set

    store = JobStore(tmp_path)
    filename, record_id = _persist_request(store, kind=kind, request=request)

    persisted = json.loads((_state_dir(tmp_path) / filename).read_text(encoding="utf-8"))
    request_key = "request" if kind == "job" else "params"
    assert "pre_pull" not in persisted[0][request_key]

    reloaded = _reloaded_request(JobStore(tmp_path), kind=kind, record_id=record_id)
    assert reloaded.repo_source_mode == mode
    assert "pre_pull" not in reloaded.model_fields_set


@pytest.mark.parametrize("kind", ["job", "artifact"])
@pytest.mark.parametrize("mode", ["local_current", "remote_snapshot"])
def test_explicit_pre_pull_false_remains_explicit_after_round_trip(
    tmp_path: Path,
    kind: str,
    mode: str,
) -> None:
    request = JobRequest(
        hub=str(tmp_path),
        repos=["demo"],
        repo_source_mode=mode,
        pre_pull=False,
    )

    store = JobStore(tmp_path)
    filename, record_id = _persist_request(store, kind=kind, request=request)

    persisted = json.loads((_state_dir(tmp_path) / filename).read_text(encoding="utf-8"))
    request_key = "request" if kind == "job" else "params"
    assert persisted[0][request_key]["pre_pull"] is False

    reloaded = _reloaded_request(JobStore(tmp_path), kind=kind, record_id=record_id)
    assert reloaded.pre_pull is False
    assert "pre_pull" in reloaded.model_fields_set


@pytest.mark.parametrize("kind", ["job", "artifact"])
@pytest.mark.parametrize("mode", ["local_current", "remote_snapshot"])
def test_legacy_full_dump_restores_bare_source_mode_semantics(
    tmp_path: Path,
    kind: str,
    mode: str,
) -> None:
    request = JobRequest(
        hub=str(tmp_path),
        repos=["demo"],
        repo_source_mode=mode,
    )
    request_key = "request" if kind == "job" else "params"

    if kind == "job":
        record = Job.create(request)
        filename = "jobs.json"
    else:
        record = _artifact_for(request)
        filename = "artifacts.json"

    legacy_payload = record.model_dump()
    assert set(legacy_payload[request_key]) == set(JobRequest.model_fields)
    assert legacy_payload[request_key]["pre_pull"] is True

    state_path = _state_dir(tmp_path) / filename
    state_path.write_text(json.dumps([legacy_payload], indent=2), encoding="utf-8")

    store = JobStore(tmp_path)
    reloaded = _reloaded_request(store, kind=kind, record_id=record.id)
    assert reloaded.repo_source_mode == mode
    assert "pre_pull" not in reloaded.model_fields_set

    if kind == "job":
        loaded_job = store.get_job(record.id)
        assert loaded_job is not None
        store.update_job(loaded_job)
    else:
        loaded_artifact = store.get_artifact(record.id)
        assert loaded_artifact is not None
        store.add_artifact(loaded_artifact)

    migrated = json.loads(state_path.read_text(encoding="utf-8"))
    assert "pre_pull" not in migrated[0][request_key]


def test_partial_source_mode_conflict_remains_fail_closed(tmp_path: Path) -> None:
    request = JobRequest(
        hub=str(tmp_path),
        repos=["demo"],
        repo_source_mode="local_current",
    )
    payload = Job.create(request).model_dump()
    payload["request"] = {
        "hub": str(tmp_path),
        "repos": ["demo"],
        "repo_source_mode": "local_current",
        "pre_pull": True,
    }
    state_path = _state_dir(tmp_path) / "jobs.json"
    original = json.dumps([payload], indent=2).encode("utf-8")
    state_path.write_bytes(original)

    with pytest.raises(RuntimeError, match="refusing to start"):
        JobStore(tmp_path)

    assert state_path.read_bytes() == original
