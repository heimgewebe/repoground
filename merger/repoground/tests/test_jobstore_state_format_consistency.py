import json
from pathlib import Path

import pytest

from merger.repoground.core.merge import MERGES_DIR_NAME
from merger.repoground.service.jobstore import JobStore
from merger.repoground.service.models import Artifact, Job, JobRequest


def _state_path(tmp_path: Path, filename: str) -> Path:
    return tmp_path / MERGES_DIR_NAME / ".repoground-service" / filename


def _artifact(record_id: str, request: JobRequest) -> Artifact:
    return Artifact(
        id=record_id,
        job_id=f"job-for-{record_id}",
        hub=request.hub or "",
        repos=request.repos or [],
        created_at="2026-09-02T00:00:00+00:00",
        paths={},
        params=request,
    )


def _persist_two_records(store: JobStore, *, kind: str, request: JobRequest) -> str:
    if kind == "job":
        store.add_job(Job.create(request))
        store.add_job(Job.create(request))
        return "jobs.json"

    store.add_artifact(_artifact("artifact-1", request))
    store.add_artifact(_artifact("artifact-2", request))
    return "artifacts.json"


def _persist_one_record(store: JobStore, *, kind: str, request: JobRequest) -> str:
    if kind == "job":
        store.add_job(Job.create(request))
        return "jobs.json"

    store.add_artifact(_artifact("artifact-1", request))
    return "artifacts.json"


@pytest.mark.parametrize("kind", ["job", "artifact"])
def test_mixed_legacy_and_v2_state_fails_closed_and_preserves_bytes(
    tmp_path: Path,
    kind: str,
) -> None:
    request = JobRequest(hub=str(tmp_path), repos=["demo"])
    store = JobStore(tmp_path)
    filename = _persist_two_records(store, kind=kind, request=request)
    state_path = _state_path(tmp_path, filename)
    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    assert len(persisted) == 2
    assert all("_jobstore" in entry for entry in persisted)

    # A normal writer rewrites the whole state file in one format. Losing the
    # metadata from only one record is therefore corruption, not a v1 fallback.
    persisted[1].pop("_jobstore")
    original = json.dumps(persisted, indent=2).encode("utf-8")
    state_path.write_bytes(original)

    with pytest.raises(RuntimeError, match="refusing to start"):
        JobStore(tmp_path)

    assert state_path.read_bytes() == original


@pytest.mark.parametrize("kind", ["job", "artifact"])
@pytest.mark.parametrize("bad_version", [2.0, "2"])
def test_v2_version_token_requires_json_integer(
    tmp_path: Path,
    kind: str,
    bad_version: object,
) -> None:
    request = JobRequest(hub=str(tmp_path), repos=["demo"])
    store = JobStore(tmp_path)
    filename = _persist_one_record(store, kind=kind, request=request)
    state_path = _state_path(tmp_path, filename)
    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    persisted[0]["_jobstore"]["version"] = bad_version

    original = json.dumps(persisted, indent=2).encode("utf-8")
    state_path.write_bytes(original)

    with pytest.raises(RuntimeError, match="refusing to start"):
        JobStore(tmp_path)

    assert state_path.read_bytes() == original
