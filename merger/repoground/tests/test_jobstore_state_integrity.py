import json
from pathlib import Path

import pytest

from merger.repoground.core.merge import MERGES_DIR_NAME
from merger.repoground.service.jobstore import JobStore
from merger.repoground.service.models import Artifact, Job, JobRequest


LEGACY_REQUEST_V1 = {
    "hub": "/legacy/hub",
    "merges_dir": None,
    "repos": ["demo"],
    "level": "dev",
    "mode": "gesamt",
    "max_bytes": "0",
    "split_size": "25MB",
    "plan_only": False,
    "code_only": False,
    "extensions": None,
    "path_filter": None,
    "include_paths": None,
    "include_paths_by_repo": None,
    "strict_include_paths_by_repo": False,
    "extras": "json_sidecar,augment_sidecar",
    "meta_density": "auto",
    "json_sidecar": True,
    "force_new": False,
    "pre_pull": True,
    "output_mode": "dual",
    "redact_secrets": False,
    "include_hidden": True,
    "repo_source_mode": "local_current",
    "remote_ref": None,
    "remote_ref_policy": "upstream",
}


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


def _legacy_record(*, kind: str, request: dict) -> tuple[str, str, dict]:
    if kind == "job":
        return (
            "jobs.json",
            "legacy-job",
            {
                "id": "legacy-job",
                "status": "succeeded",
                "created_at": "2026-08-01T00:00:00+00:00",
                "started_at": None,
                "finished_at": "2026-08-01T00:01:00+00:00",
                "request": request,
                "hub_resolved": "/legacy/hub",
                "content_hash": "legacy-hash",
                "logs": [],
                "warnings": [],
                "artifact_ids": [],
                "error": None,
            },
        )

    return (
        "artifacts.json",
        "legacy-artifact",
        {
            "id": "legacy-artifact",
            "job_id": "legacy-job",
            "hub": "/legacy/hub",
            "repos": ["demo"],
            "created_at": "2026-08-01T00:01:00+00:00",
            "paths": {},
            "params": request,
            "merges_dir": None,
        },
    )


def _rewrite_loaded_record(store: JobStore, *, kind: str, record_id: str) -> None:
    if kind == "job":
        job = store.get_job(record_id)
        assert job is not None
        store.update_job(job)
        return

    artifact = store.get_artifact(record_id)
    assert artifact is not None
    store.add_artifact(artifact)


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
def test_v2_round_trip_preserves_complete_values_and_fields_set(
    tmp_path: Path,
    kind: str,
    mode: str,
) -> None:
    request = JobRequest(
        hub=str(tmp_path),
        repos=["demo"],
        repo_source_mode=mode,
    )
    original_values = request.model_dump()
    original_fields_set = set(request.model_fields_set)
    assert "pre_pull" not in original_fields_set

    store = JobStore(tmp_path)
    filename, record_id = _persist_request(store, kind=kind, request=request)

    persisted = json.loads((_state_dir(tmp_path) / filename).read_text(encoding="utf-8"))
    request_key = "request" if kind == "job" else "params"
    assert persisted[0][request_key] == original_values
    assert set(persisted[0][request_key]) == set(JobRequest.model_fields)
    assert persisted[0][request_key]["pre_pull"] is True
    assert persisted[0]["_jobstore"]["version"] == 2
    assert set(persisted[0]["_jobstore"]["request_fields"]) == set(
        JobRequest.model_fields
    )
    assert set(persisted[0]["_jobstore"]["request_fields_set"]) == original_fields_set

    reloaded = _reloaded_request(JobStore(tmp_path), kind=kind, record_id=record_id)
    assert reloaded.model_dump() == original_values
    assert reloaded.model_fields_set == original_fields_set


@pytest.mark.parametrize("kind", ["job", "artifact"])
@pytest.mark.parametrize("mode", ["local_current", "remote_snapshot"])
def test_explicit_pre_pull_false_remains_explicit_after_v2_round_trip(
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
    original_fields_set = set(request.model_fields_set)

    store = JobStore(tmp_path)
    filename, record_id = _persist_request(store, kind=kind, request=request)

    persisted = json.loads((_state_dir(tmp_path) / filename).read_text(encoding="utf-8"))
    request_key = "request" if kind == "job" else "params"
    assert persisted[0][request_key]["pre_pull"] is False
    assert "pre_pull" in persisted[0]["_jobstore"]["request_fields_set"]

    reloaded = _reloaded_request(JobStore(tmp_path), kind=kind, record_id=record_id)
    assert reloaded.pre_pull is False
    assert reloaded.model_fields_set == original_fields_set


@pytest.mark.parametrize("kind", ["job", "artifact"])
def test_v2_uses_persisted_implicit_effective_value_not_current_default(
    tmp_path: Path,
    kind: str,
) -> None:
    request = JobRequest(hub=str(tmp_path), repos=["demo"])
    assert request.include_hidden is True
    assert "include_hidden" not in request.model_fields_set

    store = JobStore(tmp_path)
    filename, record_id = _persist_request(store, kind=kind, request=request)
    state_path = _state_dir(tmp_path) / filename
    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    request_key = "request" if kind == "job" else "params"

    # Simulate a persisted historical effective value differing from today's
    # model default. Loading must use the stored value, not silently inherit the
    # current default just because the field was implicit at request time.
    persisted[0][request_key]["include_hidden"] = False
    state_path.write_text(json.dumps(persisted, indent=2), encoding="utf-8")

    reloaded = _reloaded_request(JobStore(tmp_path), kind=kind, record_id=record_id)
    assert reloaded.include_hidden is False
    assert "include_hidden" not in reloaded.model_fields_set


@pytest.mark.parametrize("kind", ["job", "artifact"])
@pytest.mark.parametrize(
    ("mode", "expected_pre_pull_explicit"),
    [
        ("local_current", False),
        ("remote_snapshot", False),
        ("local_ff", True),
        (None, True),
    ],
)
def test_frozen_legacy_v1_fixture_loads_and_migrates_to_v2(
    tmp_path: Path,
    kind: str,
    mode: str | None,
    expected_pre_pull_explicit: bool,
) -> None:
    legacy_request = dict(LEGACY_REQUEST_V1)
    legacy_request["hub"] = str(tmp_path)
    legacy_request["repo_source_mode"] = mode
    filename, record_id, record = _legacy_record(kind=kind, request=legacy_request)
    if kind == "job":
        record["hub_resolved"] = str(tmp_path)
    else:
        record["hub"] = str(tmp_path)

    state_path = _state_dir(tmp_path) / filename
    state_path.write_text(json.dumps([record], indent=2), encoding="utf-8")

    store = JobStore(tmp_path)
    reloaded = _reloaded_request(store, kind=kind, record_id=record_id)
    assert reloaded.model_dump() == legacy_request
    assert ("pre_pull" in reloaded.model_fields_set) is expected_pre_pull_explicit

    _rewrite_loaded_record(store, kind=kind, record_id=record_id)
    migrated = json.loads(state_path.read_text(encoding="utf-8"))
    request_key = "request" if kind == "job" else "params"
    assert migrated[0]["_jobstore"]["version"] == 2
    assert migrated[0][request_key] == legacy_request
    assert (
        "pre_pull" in migrated[0]["_jobstore"]["request_fields_set"]
    ) is expected_pre_pull_explicit


@pytest.mark.parametrize("kind", ["job", "artifact"])
@pytest.mark.parametrize("shape", ["partial", "unknown"])
def test_unknown_legacy_shape_remains_fail_closed(
    tmp_path: Path,
    kind: str,
    shape: str,
) -> None:
    legacy_request = dict(LEGACY_REQUEST_V1)
    legacy_request["hub"] = str(tmp_path)
    if shape == "partial":
        legacy_request.pop("include_hidden")
    else:
        legacy_request["future_field"] = "unknown"

    filename, _, record = _legacy_record(kind=kind, request=legacy_request)
    if kind == "job":
        record["hub_resolved"] = str(tmp_path)
    else:
        record["hub"] = str(tmp_path)
    state_path = _state_dir(tmp_path) / filename
    original = json.dumps([record], indent=2).encode("utf-8")
    state_path.write_bytes(original)

    with pytest.raises(RuntimeError, match="refusing to start"):
        JobStore(tmp_path)

    assert state_path.read_bytes() == original


@pytest.mark.parametrize("kind", ["job", "artifact"])
@pytest.mark.parametrize(
    "corruption",
    [
        "unknown-version",
        "extra-meta-field",
        "duplicate-fields-set",
        "non-string-field",
        "unknown-request-field",
        "declared-fields-mismatch",
    ],
)
def test_malformed_v2_metadata_fails_closed_and_preserves_bytes(
    tmp_path: Path,
    kind: str,
    corruption: str,
) -> None:
    request = JobRequest(hub=str(tmp_path), repos=["demo"])
    store = JobStore(tmp_path)
    filename, _ = _persist_request(store, kind=kind, request=request)
    state_path = _state_dir(tmp_path) / filename
    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    entry = persisted[0]
    request_key = "request" if kind == "job" else "params"
    meta = entry["_jobstore"]

    if corruption == "unknown-version":
        meta["version"] = 99
    elif corruption == "extra-meta-field":
        meta["unexpected"] = True
    elif corruption == "duplicate-fields-set":
        meta["request_fields_set"].append(meta["request_fields_set"][0])
    elif corruption == "non-string-field":
        meta["request_fields_set"].append(7)
    elif corruption == "unknown-request-field":
        entry[request_key]["future_field"] = "unknown"
        meta["request_fields"].append("future_field")
    else:
        meta["request_fields"].remove("include_hidden")

    original = json.dumps(persisted, indent=2).encode("utf-8")
    state_path.write_bytes(original)

    with pytest.raises(RuntimeError, match="refusing to start"):
        JobStore(tmp_path)

    assert state_path.read_bytes() == original


@pytest.mark.parametrize(
    ("kind", "defaulted_field"),
    [("job", "artifact_ids"), ("artifact", "merges_dir")],
)
@pytest.mark.parametrize("corruption", ["missing", "extra"])
def test_malformed_v2_record_shape_fails_closed_and_preserves_bytes(
    tmp_path: Path,
    kind: str,
    defaulted_field: str,
    corruption: str,
) -> None:
    request = JobRequest(hub=str(tmp_path), repos=["demo"])
    store = JobStore(tmp_path)
    filename, _ = _persist_request(store, kind=kind, request=request)
    state_path = _state_dir(tmp_path) / filename
    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    entry = persisted[0]

    if corruption == "missing":
        entry.pop(defaulted_field)
    else:
        entry["future_record_field"] = "unknown"

    original = json.dumps(persisted, indent=2).encode("utf-8")
    state_path.write_bytes(original)

    with pytest.raises(RuntimeError, match="refusing to start"):
        JobStore(tmp_path)

    assert state_path.read_bytes() == original


@pytest.mark.parametrize("kind", ["job", "artifact"])
def test_v2_explicit_source_mode_conflict_remains_fail_closed(
    tmp_path: Path,
    kind: str,
) -> None:
    request = JobRequest(
        hub=str(tmp_path),
        repos=["demo"],
        repo_source_mode="local_current",
    )
    store = JobStore(tmp_path)
    filename, _ = _persist_request(store, kind=kind, request=request)
    state_path = _state_dir(tmp_path) / filename
    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    fields_set = persisted[0]["_jobstore"]["request_fields_set"]
    assert "pre_pull" not in fields_set
    fields_set.append("pre_pull")
    fields_set.sort()

    original = json.dumps(persisted, indent=2).encode("utf-8")
    state_path.write_bytes(original)

    with pytest.raises(RuntimeError, match="refusing to start"):
        JobStore(tmp_path)

    assert state_path.read_bytes() == original
