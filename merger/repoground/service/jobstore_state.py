from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, TypeAdapter

from .models import JobRequest

_STATE_META_KEY = "_jobstore"
_STATE_VERSION = 2
_META_FIELDS = frozenset({"version", "request_fields", "request_fields_set"})

# Frozen signatures of the unversioned JobStore serializer that predates v2.
# Do not derive these from live Pydantic model fields: compatibility must remain
# bound to the historical format even when the current schemas evolve.
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
# v2 was introduced with the same complete JobRequest field set as legacy v1,
# but it is a distinct versioned persistence contract. Keep a dedicated frozen
# signature so both loading and writing stay bound to v2 rather than accepting
# arbitrary subsets of the live Pydantic model.
_V2_JOB_REQUEST_FIELDS = frozenset(_LEGACY_JOB_REQUEST_FIELDS_V1)

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
_V2_RECORD_FIELDS = {
    request_key: fields | frozenset({_STATE_META_KEY})
    for request_key, fields in _LEGACY_RECORD_FIELDS_V1.items()
}
_SCHEMA_COSMETIC_KEYS = frozenset({"title", "description"})
_SCHEMA_MODES = ("validation", "serialization")
_V2_RECORD_SCHEMA_SHA256 = {
    "request": {
        "validation": "7c2745e175f139292fa5829b57b8443d0ac168f79fda4ce9f3d0513e9e98a05b",
        "serialization": "7c2745e175f139292fa5829b57b8443d0ac168f79fda4ce9f3d0513e9e98a05b",
    },
    "params": {
        "validation": "34184f65512449db21dd8e07c97d4f7ee95668845590c0886f50a8ec89f44036",
        "serialization": "34184f65512449db21dd8e07c97d4f7ee95668845590c0886f50a8ec89f44036",
    },
}
_BOOL_ADAPTER = TypeAdapter(bool)


def _persistence_schema(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _persistence_schema(item)
            for key, item in value.items()
            if key not in _SCHEMA_COSMETIC_KEYS
        }
    if isinstance(value, list):
        return [_persistence_schema(item) for item in value]
    return value


def _model_schema_sha256(record_type: type[BaseModel], *, mode: str) -> str:
    schema = _persistence_schema(record_type.model_json_schema(mode=mode))
    payload = json.dumps(
        schema,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _validate_v2_model_schema(
    record_type: type[BaseModel], *, request_key: str
) -> None:
    expected = _V2_RECORD_SCHEMA_SHA256.get(request_key)
    if expected is None:
        raise ValueError(f"unsupported JobStore v2 request key: {request_key}")
    observed = {
        mode: _model_schema_sha256(record_type, mode=mode) for mode in _SCHEMA_MODES
    }
    if observed != expected:
        raise ValueError("current persisted record schema requires a JobStore version bump")


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
    raw_request: dict[str, Any], raw_meta: Any
) -> frozenset[str]:
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
    if request_fields != _V2_JOB_REQUEST_FIELDS:
        raise ValueError("persisted request does not match JobStore v2 field signature")
    if current_fields != _V2_JOB_REQUEST_FIELDS:
        raise ValueError("current JobRequest schema requires a JobStore state version bump")
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
    raw_request: dict[str, Any],
    *,
    fields_set: frozenset[str],
    strict: bool,
) -> JobRequest:
    validation_payload = dict(raw_request)
    persisted_pre_pull: bool | None = None

    # JobRequest's source-mode validator intentionally treats pre_pull as
    # tri-state: a value only conflicts when the caller explicitly supplied it.
    # Full v2 persistence must retain the effective value without making an
    # implicit value explicit during Pydantic reconstruction.
    if "pre_pull" not in fields_set and "pre_pull" in validation_payload:
        persisted_pre_pull = _BOOL_ADAPTER.validate_python(
            validation_payload.pop("pre_pull"),
            strict=strict,
        )

    request = JobRequest.model_validate(validation_payload, strict=strict)
    if persisted_pre_pull is not None:
        request.pre_pull = persisted_pre_pull
    _restore_fields_set(request, fields_set)
    return request


def _validate_v2_record_shape(
    raw_record: dict[str, Any], *, request_key: str
) -> None:
    expected_fields = _V2_RECORD_FIELDS.get(request_key)
    if expected_fields is None or frozenset(raw_record) != expected_fields:
        raise ValueError(
            "JobStore v2 record has an unknown or missing top-level field"
        )


def load_record(
    raw_record: dict[str, Any], *, record_type: type[BaseModel], request_key: str
) -> BaseModel:
    raw_request = raw_record.get(request_key)
    if not isinstance(raw_request, dict):
        raise ValueError(f"{request_key} must be an object")

    is_v2 = _STATE_META_KEY in raw_record
    if is_v2:
        _validate_v2_record_shape(raw_record, request_key=request_key)
        _validate_v2_model_schema(record_type, request_key=request_key)
        fields_set = _v2_fields_set(raw_request, raw_record[_STATE_META_KEY])
    else:
        fields_set = _legacy_v1_fields_set(
            raw_record,
            raw_request,
            request_key=request_key,
        )

    request = _validate_request(raw_request, fields_set=fields_set, strict=is_v2)
    record_payload = dict(raw_record)
    record_payload.pop(_STATE_META_KEY, None)
    record_payload[request_key] = request
    record = record_type.model_validate(record_payload, strict=is_v2)

    # Pydantic may re-run nested model validators for an existing model instance;
    # bind the persisted explicit/default marker again after parent validation.
    nested_request = getattr(record, request_key)
    _restore_fields_set(nested_request, fields_set)
    return record


def dump_record(record: BaseModel, *, request_key: str) -> dict[str, Any]:
    _validate_v2_model_schema(type(record), request_key=request_key)

    request = getattr(record, request_key)
    if not isinstance(request, JobRequest):
        raise TypeError(f"{request_key} must be a JobRequest")

    current_fields = frozenset(JobRequest.model_fields)
    if current_fields != _V2_JOB_REQUEST_FIELDS:
        raise ValueError("current JobRequest schema requires a JobStore state version bump")

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

    expected_fields = _V2_RECORD_FIELDS.get(request_key)
    if expected_fields is None or frozenset(data) != expected_fields:
        raise ValueError("record dump does not match JobStore v2 top-level shape")

    return data
