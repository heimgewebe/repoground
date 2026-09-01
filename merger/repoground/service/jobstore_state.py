from __future__ import annotations

from typing import Any

from pydantic import BaseModel, TypeAdapter

from .models import JobRequest

_STATE_META_KEY = "_jobstore"
_STATE_VERSION = 2
_META_FIELDS = frozenset({"version", "request_fields", "request_fields_set"})

# Frozen signatures of the unversioned JobStore serializer that predates v2.
# Do not derive these from live Pydantic model fields: compatibility must remain
# bound to the historical format even when the current schemas evolve.
#
# The active RepoGround state path was hard-cut from `.rlens-service` to
# `.repoground-service` on 2026-07-19 (fa5b1e897929e41488a661916ec218cb0cf25c09).
# At that boundary JobRequest, Job and Artifact already had the exact shapes
# frozen below. Older `.rlens-service` files are a retired runtime path rather
# than earlier generations of this active state file.
_LEGACY_JOB_REQUEST_FIELDS_V1 = frozenset(
    {
        "hub",
        "merges_dir",
        "repos",
        "level",
        "mode",
        "max_bytes",
        "split_size",
        "plan_only",
        "code_only",
        "extensions",
        "path_filter",
        "include_paths",
        "include_paths_by_repo",
        "strict_include_paths_by_repo",
        "extras",
        "meta_density",
        "json_sidecar",
        "force_new",
        "pre_pull",
        "output_mode",
        "redact_secrets",
        "include_hidden",
        "repo_source_mode",
        "remote_ref",
        "remote_ref_policy",
    }
)
_LEGACY_RECORD_FIELDS_V1 = {
    "request": frozenset(
        {
            "id",
            "status",
            "created_at",
            "started_at",
            "finished_at",
            "request",
            "hub_resolved",
            "content_hash",
            "logs",
            "warnings",
            "artifact_ids",
            "error",
        }
    ),
    "params": frozenset(
        {
            "id",
            "job_id",
            "hub",
            "repos",
            "created_at",
            "paths",
            "params",
            "merges_dir",
        }
    ),
}

# v2 intentionally freezes the *outer* record shape too. Pydantic defaults must
# never turn a malformed persisted record into an apparently valid one (for
# example, a missing artifact_ids must not silently become []). Future top-level
# schema evolution therefore requires an explicit JobStore state-version change
# or migration instead of inheriting whatever the live model happens to accept.
_V2_RECORD_FIELDS = {
    "request": frozenset(
        {
            "id",
            "status",
            "created_at",
            "started_at",
            "finished_at",
            "request",
            "hub_resolved",
            "content_hash",
            "logs",
            "warnings",
            "artifact_ids",
            "error",
            _STATE_META_KEY,
        }
    ),
    "params": frozenset(
        {
            "id",
            "job_id",
            "hub",
            "repos",
            "created_at",
            "paths",
            "params",
            "merges_dir",
            _STATE_META_KEY,
        }
    ),
}
_BOOL_ADAPTER = TypeAdapter(bool)


def _restore_fields_set(request: JobRequest, fields_set: frozenset[str]) -> None:
    request.model_fields_set.clear()
    request.model_fields_set.update(fields_set)


def _field_name_set(value: Any, *, label: str) -> frozenset[str]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a JSON array")
    if any(not isinstance(item, str) for item in value):
        raise ValueError(f"{label} entries must be strings")
    if len(set(value)) != len(value):
        raise ValueError(f"{label} must not contain duplicates")
    return frozenset(value)


def _v2_fields_set(
    raw_record: dict[str, Any],
    raw_request: dict[str, Any],
    raw_meta: Any,
    *,
    request_key: str,
) -> frozenset[str]:
    expected_record_fields = _V2_RECORD_FIELDS.get(request_key)
    if expected_record_fields is None or frozenset(raw_record) != expected_record_fields:
        raise ValueError("JobStore v2 record does not match frozen v2 shape")
    if not isinstance(raw_meta, dict):
        raise ValueError("JobStore v2 metadata must be an object")
    if set(raw_meta) != _META_FIELDS:
        raise ValueError("JobStore v2 metadata has an unknown or missing field")
    if raw_meta.get("version") != _STATE_VERSION:
        raise ValueError("unsupported JobStore state version")

    request_fields = _field_name_set(
        raw_meta.get("request_fields"), label="request_fields"
    )
    fields_set = _field_name_set(
        raw_meta.get("request_fields_set"), label="request_fields_set"
    )
    current_fields = frozenset(JobRequest.model_fields)

    if request_fields != frozenset(raw_request):
        raise ValueError("persisted request fields do not match JobStore metadata")
    if not request_fields.issubset(current_fields):
        raise ValueError("persisted request uses fields unknown to this RepoGround")
    if not fields_set.issubset(request_fields):
        raise ValueError("request_fields_set contains a field absent from the request")
    return fields_set


def _legacy_v1_fields_set(
    raw_record: dict[str, Any],
    raw_request: dict[str, Any],
    *,
    request_key: str,
) -> frozenset[str]:
    expected_record_fields = _LEGACY_RECORD_FIELDS_V1.get(request_key)
    if expected_record_fields is None or frozenset(raw_record) != expected_record_fields:
        raise ValueError("unversioned JobStore record does not match legacy v1")
    if frozenset(raw_request) != _LEGACY_JOB_REQUEST_FIELDS_V1:
        raise ValueError("unversioned JobStore request does not match legacy v1")

    fields_set = set(_LEGACY_JOB_REQUEST_FIELDS_V1)
    # v1 wrote a full model_dump and therefore lost Pydantic's distinction
    # between an explicit pre_pull and its default. The public source-mode
    # validator could never have accepted explicit pre_pull=True together with
    # local_current or remote_snapshot, while a bare mode was valid. This exact
    # historical-record carve-out is the only ambiguity we repair.
    if (
        raw_request.get("repo_source_mode") in {"local_current", "remote_snapshot"}
        and raw_request.get("pre_pull") is True
    ):
        fields_set.remove("pre_pull")
    return frozenset(fields_set)


def _validate_request(
    raw_request: dict[str, Any], *, fields_set: frozenset[str]
) -> JobRequest:
    validation_payload = dict(raw_request)
    persisted_pre_pull: bool | None = None

    # JobRequest's source-mode validator intentionally treats pre_pull as
    # tri-state: a value only conflicts when the caller explicitly supplied it.
    # Full v2 persistence must retain the effective value without making an
    # implicit value explicit during Pydantic reconstruction.
    if "pre_pull" not in fields_set and "pre_pull" in validation_payload:
        persisted_pre_pull = _BOOL_ADAPTER.validate_python(
            validation_payload.pop("pre_pull")
        )

    request = JobRequest.model_validate(validation_payload)
    if persisted_pre_pull is not None:
        request.pre_pull = persisted_pre_pull
    _restore_fields_set(request, fields_set)
    return request


def load_record(
    raw_record: dict[str, Any], *, record_type: type[BaseModel], request_key: str
) -> BaseModel:
    raw_request = raw_record.get(request_key)
    if not isinstance(raw_request, dict):
        raise ValueError(f"{request_key} must be an object")

    if _STATE_META_KEY in raw_record:
        fields_set = _v2_fields_set(
            raw_record,
            raw_request,
            raw_record[_STATE_META_KEY],
            request_key=request_key,
        )
    else:
        fields_set = _legacy_v1_fields_set(
            raw_record,
            raw_request,
            request_key=request_key,
        )

    request = _validate_request(raw_request, fields_set=fields_set)
    record_payload = dict(raw_record)
    record_payload.pop(_STATE_META_KEY, None)
    record_payload[request_key] = request
    record = record_type.model_validate(record_payload)

    # Pydantic may re-run nested model validators for an existing model instance;
    # bind the persisted explicit/default marker again after parent validation.
    nested_request = getattr(record, request_key)
    _restore_fields_set(nested_request, fields_set)
    return record


def dump_record(record: BaseModel, *, request_key: str) -> dict[str, Any]:
    request = getattr(record, request_key)
    if not isinstance(request, JobRequest):
        raise TypeError(f"{request_key} must be a JobRequest")

    current_fields = frozenset(JobRequest.model_fields)
    request_payload = request.model_dump()
    if frozenset(request_payload) != current_fields:
        raise ValueError("JobRequest dump is not complete")

    fields_set = frozenset(request.model_fields_set)
    if not fields_set.issubset(current_fields):
        raise ValueError("JobRequest fields_set contains an unknown field")

    data = record.model_dump()
    data[request_key] = request_payload
    data[_STATE_META_KEY] = {
        "version": _STATE_VERSION,
        "request_fields": sorted(current_fields),
        "request_fields_set": sorted(fields_set),
    }
    return data
