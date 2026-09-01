import json
import types
from pathlib import Path

import pytest
from pydantic import ConfigDict, model_validator

from merger.repoground.core.merge import MERGES_DIR_NAME
from merger.repoground.service.jobstore import JobStore
from merger.repoground.service.jobstore_schema import (
    _callable_graph,
    assert_frozen_model_schema,
)
from merger.repoground.service.models import Artifact, Job, JobRequest

_SCHEMA_DEPENDENCY_MODULE = types.ModuleType("jobstore_schema_dependency")
_SCHEMA_DEPENDENCY_MODULE.FLAG = "alpha"


def _uses_module_dependency() -> str:
    return _SCHEMA_DEPENDENCY_MODULE.FLAG


def _state_dir(hub: Path) -> Path:
    return hub / MERGES_DIR_NAME / ".repoground-service"


def _artifact(request: JobRequest) -> Artifact:
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


@pytest.mark.parametrize("kind", ["job", "artifact"])
def test_duplicate_persisted_ids_fail_closed_and_preserve_bytes(
    tmp_path: Path,
    kind: str,
) -> None:
    request = JobRequest(hub=str(tmp_path), repos=["demo"])
    store = JobStore(tmp_path)
    if kind == "job":
        record = Job.create(request)
        store.add_job(record)
        state_path = _state_dir(tmp_path) / "jobs.json"
    else:
        record = _artifact(request)
        store.add_artifact(record)
        state_path = _state_dir(tmp_path) / "artifacts.json"

    entries = json.loads(state_path.read_text(encoding="utf-8"))
    entries.append(dict(entries[0]))
    original = json.dumps(entries, indent=2).encode("utf-8")
    state_path.write_bytes(original)

    with pytest.raises(RuntimeError, match="refusing to start"):
        JobStore(tmp_path)

    assert state_path.read_bytes() == original


@pytest.mark.parametrize("kind", ["job", "artifact"])
def test_legacy_v1_requires_exact_top_level_record_shape(
    tmp_path: Path,
    kind: str,
) -> None:
    request = JobRequest(hub=str(tmp_path), repos=["demo"])
    if kind == "job":
        payload = Job.create(request).model_dump()
        state_path = _state_dir(tmp_path) / "jobs.json"
    else:
        payload = _artifact(request).model_dump()
        state_path = _state_dir(tmp_path) / "artifacts.json"

    state_path.parent.mkdir(parents=True, exist_ok=True)
    payload["unexpected_legacy_field"] = True
    original = json.dumps([payload], indent=2).encode("utf-8")
    state_path.write_bytes(original)

    with pytest.raises(RuntimeError, match="refusing to start"):
        JobStore(tmp_path)

    assert state_path.read_bytes() == original


@pytest.mark.parametrize(
    ("kind", "mutation", "field"),
    [
        ("job", "missing", "artifact_ids"),
        ("job", "missing", "warnings"),
        ("artifact", "missing", "merges_dir"),
        ("job", "extra", "future_top_level"),
        ("artifact", "extra", "future_top_level"),
    ],
)
def test_v2_requires_exact_top_level_record_shape(
    tmp_path: Path,
    kind: str,
    mutation: str,
    field: str,
) -> None:
    request = JobRequest(hub=str(tmp_path), repos=["demo"])
    store = JobStore(tmp_path)
    if kind == "job":
        store.add_job(Job.create(request))
        state_path = _state_dir(tmp_path) / "jobs.json"
    else:
        store.add_artifact(_artifact(request))
        state_path = _state_dir(tmp_path) / "artifacts.json"

    entries = json.loads(state_path.read_text(encoding="utf-8"))
    entry = entries[0]
    assert entry["_jobstore"]["version"] == 2

    if mutation == "missing":
        entry.pop(field)
    else:
        entry[field] = "unknown"

    original = json.dumps(entries, indent=2).encode("utf-8")
    state_path.write_bytes(original)

    with pytest.raises(RuntimeError, match="refusing to start"):
        JobStore(tmp_path)

    assert state_path.read_bytes() == original


@pytest.mark.parametrize("kind", ["job", "artifact"])
def test_v2_rejects_self_consistent_incomplete_request_shape(
    tmp_path: Path,
    kind: str,
) -> None:
    request = JobRequest(hub=str(tmp_path), repos=["demo"])
    store = JobStore(tmp_path)
    if kind == "job":
        store.add_job(Job.create(request))
        state_path = _state_dir(tmp_path) / "jobs.json"
        request_key = "request"
    else:
        store.add_artifact(_artifact(request))
        state_path = _state_dir(tmp_path) / "artifacts.json"
        request_key = "params"

    entries = json.loads(state_path.read_text(encoding="utf-8"))
    entry = entries[0]
    entry[request_key].pop("include_hidden")
    entry["_jobstore"]["request_fields"].remove("include_hidden")

    # The request bytes and request_fields metadata still agree with each other.
    # The frozen v2 shape must nevertheless reject the missing field instead of
    # allowing Pydantic to reintroduce today's include_hidden default.
    assert set(entry[request_key]) == set(entry["_jobstore"]["request_fields"])

    original = json.dumps(entries, indent=2).encode("utf-8")
    state_path.write_bytes(original)

    with pytest.raises(RuntimeError, match="refusing to start"):
        JobStore(tmp_path)

    assert state_path.read_bytes() == original


def test_schema_fingerprint_rejects_same_name_type_and_default_drift() -> None:
    class DriftedJobRequest(JobRequest):
        include_hidden: int = 1

    DriftedJobRequest.__name__ = "JobRequest"

    with pytest.raises(ValueError, match="schema fingerprint changed"):
        assert_frozen_model_schema(DriftedJobRequest)


def test_schema_fingerprint_rejects_validation_config_drift() -> None:
    class DriftedJobRequest(JobRequest):
        model_config = ConfigDict(str_strip_whitespace=True)

    DriftedJobRequest.__name__ = "JobRequest"
    assert set(DriftedJobRequest.model_fields) == set(JobRequest.model_fields)

    with pytest.raises(ValueError, match="schema fingerprint changed"):
        assert_frozen_model_schema(DriftedJobRequest)


def test_schema_fingerprint_rejects_validator_drift_without_field_drift() -> None:
    class DriftedJobRequest(JobRequest):
        @model_validator(mode="after")
        def _new_state_rule(self) -> "DriftedJobRequest":
            if self.plan_only and self.force_new:
                raise ValueError("new persisted-state rule")
            return self

    DriftedJobRequest.__name__ = "JobRequest"
    assert set(DriftedJobRequest.model_fields) == set(JobRequest.model_fields)

    with pytest.raises(ValueError, match="schema fingerprint changed"):
        assert_frozen_model_schema(DriftedJobRequest)


def test_callable_fingerprint_tracks_module_attribute_values(monkeypatch) -> None:
    before = _callable_graph(_uses_module_dependency)
    monkeypatch.setattr(_SCHEMA_DEPENDENCY_MODULE, "FLAG", "beta")
    after = _callable_graph(_uses_module_dependency)

    assert before != after
