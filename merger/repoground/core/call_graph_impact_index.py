"""Bounded, integrity-bound projections from large Python call-graph artifacts.

This module exists for agent-impact reads that need only call records related to
already selected target symbols.  It deliberately does not widen the generic
read-only artifact payload limit.  A cold generation is hashed and scanned once,
then a process-local offset index (maximum two generations) is reused while the
bound manifest and artifact identities remain unchanged.
"""

from __future__ import annotations

import hashlib
import json
import mmap
import os
from array import array
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any, Mapping

from merger.repoground.core import bundle_access

MAX_SOURCE_BYTES = 256 * 1024 * 1024
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_CALLS = 100_000
MAX_INDEX_KEYS = 500_000
MAX_KEY_BYTES = 4096
MAX_PROJECTED_CALLS = 20_000
MAX_PROJECTED_BYTES = 8 * 1024 * 1024
CACHE_MAX_ENTRIES = 2
_HASH_CHUNK_BYTES = 1024 * 1024
_METADATA_FIELDS = frozenset(
    {
        "kind",
        "version",
        "run_id",
        "canonical_dump_index_sha256",
        "language",
        "evidence_model",
        "resolution_statuses",
        "relation_types",
        "call_count",
        "resolution_counts",
        "evidence_counts",
        "relation_counts",
        "skipped_files_count",
        "skipped_errors",
        "skipped_errors_total_count",
        "skipped_errors_truncated",
        "does_not_establish",
    }
)


@dataclass(frozen=True, slots=True)
class _SourceFingerprint:
    manifest_path: str
    manifest_sha256: str
    manifest_identity: tuple[int, int, int, int, int]
    artifact_path: str
    artifact_sha256: str
    artifact_identity: tuple[int, int, int, int, int]


@dataclass(slots=True)
class _ImpactIndexState:
    metadata: dict[str, Any]
    artifact: dict[str, Any]
    fingerprint: _SourceFingerprint
    call_starts: array
    call_ends: array
    caller_positions: dict[str, array]
    resolved_target_positions: dict[str, array]
    candidate_target_positions: dict[str, array]
    simple_name_positions: dict[str, array]
    expression_positions: dict[str, array]


_CACHE: OrderedDict[_SourceFingerprint, _ImpactIndexState] = OrderedDict()
_CACHE_LOCK = RLock()


def _identity(stat_result: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        stat_result.st_dev,
        stat_result.st_ino,
        stat_result.st_size,
        stat_result.st_mtime_ns,
        stat_result.st_ctime_ns,
    )


def _identity_strong(identity: tuple[int, int, int, int, int]) -> bool:
    device, inode, _size, mtime_ns, ctime_ns = identity
    return all(value != 0 for value in (device, inode, mtime_ns, ctime_ns))


def _read_stable_small_file(
    path: Path, *, max_bytes: int = MAX_MANIFEST_BYTES
) -> tuple[bytes, os.stat_result]:
    try:
        with path.open("rb") as handle:
            before = os.fstat(handle.fileno())
            if before.st_size > max_bytes:
                raise ValueError(
                    f"call graph manifest exceeds bounded size: {before.st_size} > {max_bytes}"
                )
            payload = handle.read(max_bytes + 1)
            after = os.fstat(handle.fileno())
    except OSError as exc:
        raise ValueError(f"call graph manifest is unavailable: {exc}") from exc
    if _identity(before) != _identity(after):
        raise ValueError("call graph manifest changed while it was being read")
    if len(payload) > max_bytes:
        raise ValueError("call graph manifest exceeds bounded size")
    try:
        current = path.stat()
    except OSError as exc:
        raise ValueError(f"call graph manifest is unavailable: {exc}") from exc
    if _identity(after) != _identity(current):
        raise ValueError("call graph manifest changed while it was being read")
    return payload, after


def _hash_stable_artifact(
    path: Path, *, max_bytes: int = MAX_SOURCE_BYTES
) -> tuple[int, str, os.stat_result]:
    digest = hashlib.sha256()
    observed = 0
    try:
        with path.open("rb") as handle:
            before = os.fstat(handle.fileno())
            if before.st_size > max_bytes:
                raise ValueError(
                    "python_call_graph_json exceeds bounded impact-index source limit: "
                    f"{before.st_size} > {max_bytes}"
                )
            while True:
                chunk = handle.read(_HASH_CHUNK_BYTES)
                if not chunk:
                    break
                observed += len(chunk)
                if observed > max_bytes:
                    raise ValueError(
                        "python_call_graph_json exceeds bounded impact-index source limit"
                    )
                digest.update(chunk)
            after = os.fstat(handle.fileno())
    except OSError as exc:
        raise ValueError(f"python_call_graph_json is unavailable: {exc}") from exc
    if _identity(before) != _identity(after):
        raise ValueError("python_call_graph_json changed while it was being hashed")
    try:
        current = path.stat()
    except OSError as exc:
        raise ValueError(f"python_call_graph_json is unavailable: {exc}") from exc
    if _identity(after) != _identity(current):
        raise ValueError("python_call_graph_json changed while it was being hashed")
    return observed, digest.hexdigest(), after


def _resolve_verified_source(
    manifest_path: Path,
) -> tuple[dict[str, Any], dict[str, Any], Path, _SourceFingerprint]:
    manifest_path = manifest_path.resolve()
    manifest_bytes, manifest_stat = _read_stable_small_file(manifest_path)
    try:
        manifest = json.loads(manifest_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("bundle manifest is not valid UTF-8 JSON") from exc
    if not isinstance(manifest, dict):
        raise ValueError("bundle manifest must be a JSON object")
    artifact_payload = next(
        (
            item
            for item in bundle_access._artifact_list(manifest)
            if item.get("role") == bundle_access.CALL_GRAPH_ROLE
        ),
        None,
    )
    if not isinstance(artifact_payload, dict):
        raise FileNotFoundError("python_call_graph_json is not present in the bundle manifest")
    artifact = bundle_access._artifact_record(manifest_path, artifact_payload)
    artifact_path = bundle_access._safe_artifact_path(
        manifest_path.parent, artifact_payload.get("path")
    )
    if artifact_path is None:
        raise FileNotFoundError("python_call_graph_json artifact path is unavailable")
    declared_bytes = artifact_payload.get("bytes")
    declared_sha256 = artifact_payload.get("sha256")
    if (
        not isinstance(declared_bytes, int)
        or isinstance(declared_bytes, bool)
        or declared_bytes < 0
        or not bundle_access._is_sha256(declared_sha256)
    ):
        raise ValueError("python_call_graph_json manifest integrity fields are invalid")
    actual_bytes, actual_sha256, artifact_stat = _hash_stable_artifact(artifact_path)
    if actual_bytes != declared_bytes:
        raise ValueError("python_call_graph_json byte count does not match the bundle manifest")
    if actual_sha256 != declared_sha256:
        raise ValueError("python_call_graph_json content hash does not match the bundle manifest")
    fingerprint = _SourceFingerprint(
        manifest_path=str(manifest_path),
        manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
        manifest_identity=_identity(manifest_stat),
        artifact_path=str(artifact_path),
        artifact_sha256=actual_sha256,
        artifact_identity=_identity(artifact_stat),
    )
    return manifest, artifact, artifact_path, fingerprint


def _source_is_current(fingerprint: _SourceFingerprint) -> bool:
    manifest_path = Path(fingerprint.manifest_path)
    artifact_path = Path(fingerprint.artifact_path)
    try:
        manifest_stat = manifest_path.stat()
        artifact_stat = artifact_path.stat()
    except OSError:
        return False
    if _identity(manifest_stat) != fingerprint.manifest_identity:
        return False
    if _identity(artifact_stat) != fingerprint.artifact_identity:
        return False
    try:
        manifest_bytes, manifest_after = _read_stable_small_file(manifest_path)
    except ValueError:
        return False
    if (
        _identity(manifest_after) != fingerprint.manifest_identity
        or hashlib.sha256(manifest_bytes).hexdigest() != fingerprint.manifest_sha256
    ):
        return False
    strict = bundle_access._cache_validation_mode() == "strict"
    if strict or not _identity_strong(fingerprint.artifact_identity):
        try:
            observed, digest, artifact_after = _hash_stable_artifact(artifact_path)
        except ValueError:
            return False
        return (
            observed == fingerprint.artifact_identity[2]
            and digest == fingerprint.artifact_sha256
            and _identity(artifact_after) == fingerprint.artifact_identity
        )
    return True


def _skip_ws(data: mmap.mmap, position: int, end: int) -> int:
    while position < end and data[position] in b" \t\r\n":
        position += 1
    return position


def _scan_string_end(data: mmap.mmap, position: int, end: int) -> int:
    if position >= end or data[position] != 0x22:
        raise ValueError("expected JSON string")
    position += 1
    escaped = False
    while position < end:
        byte = data[position]
        if escaped:
            escaped = False
        elif byte == 0x5C:
            escaped = True
        elif byte == 0x22:
            return position + 1
        position += 1
    raise ValueError("unterminated JSON string")


def _scan_container_end(data: mmap.mmap, position: int, end: int) -> int:
    first = data[position]
    stack = [0x7D if first == 0x7B else 0x5D]
    cursor = position + 1
    while cursor < end:
        byte = data[cursor]
        if byte == 0x22:
            cursor = _scan_string_end(data, cursor, end)
            continue
        if byte == 0x7B:
            stack.append(0x7D)
        elif byte == 0x5B:
            stack.append(0x5D)
        elif byte in (0x7D, 0x5D):
            if not stack or byte != stack.pop():
                raise ValueError("mismatched JSON container")
            if not stack:
                return cursor + 1
        cursor += 1
    raise ValueError("unterminated JSON container")


def _scan_primitive_end(data: mmap.mmap, position: int, end: int) -> int:
    cursor = position
    while cursor < end and data[cursor] not in b",]} \t\r\n":
        cursor += 1
    if cursor == position:
        raise ValueError("invalid JSON primitive")
    return cursor


def _scan_value_end(data: mmap.mmap, position: int, end: int) -> int:
    position = _skip_ws(data, position, end)
    if position >= end:
        raise ValueError("missing JSON value")
    first = data[position]
    if first == 0x22:
        return _scan_string_end(data, position, end)
    if first in (0x7B, 0x5B):
        return _scan_container_end(data, position, end)
    return _scan_primitive_end(data, position, end)

def _decode_slice(data: mmap.mmap, start: int, end: int, *, label: str) -> Any:
    try:
        return json.loads(data[start:end])
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON in {label}") from exc


def _append_posting(
    postings: dict[str, array],
    key: Any,
    position: int,
    *,
    key_counter: list[int],
) -> None:
    if not isinstance(key, str) or not key:
        return
    normalized = key.casefold()
    if len(normalized.encode("utf-8")) > MAX_KEY_BYTES:
        raise ValueError("call graph impact index key exceeds bounded key size")
    bucket = postings.get(normalized)
    if bucket is None:
        key_counter[0] += 1
        if key_counter[0] > MAX_INDEX_KEYS:
            raise ValueError("call graph impact index exceeds bounded key count")
        bucket = array("I")
        postings[normalized] = bucket
    bucket.append(position)


def _validate_stream_counts(
    metadata: Mapping[str, Any],
    *,
    call_count: int,
    resolution_counts: Mapping[str, int],
    evidence_counts: Mapping[str, int],
    relation_counts: Mapping[str, int],
) -> None:
    if metadata.get("call_count") != call_count:
        raise ValueError("python_call_graph_json call_count does not match streamed calls")
    expected = (
        ("resolution_counts", resolution_counts),
        ("evidence_counts", evidence_counts),
        ("relation_counts", relation_counts),
    )
    for field, actual in expected:
        if metadata.get(field) != dict(actual):
            raise ValueError(f"python_call_graph_json {field} does not match streamed calls")


@dataclass(slots=True)
class _IndexBuilder:
    metadata: dict[str, Any]
    call_starts: array
    call_ends: array
    caller_positions: dict[str, array]
    resolved_target_positions: dict[str, array]
    candidate_target_positions: dict[str, array]
    simple_name_positions: dict[str, array]
    expression_positions: dict[str, array]
    key_counter: list[int]
    resolution_counts: dict[str, int]
    evidence_counts: dict[str, int]
    relation_counts: dict[str, int]
    calls_seen: bool = False


def _new_index_builder() -> _IndexBuilder:
    return _IndexBuilder(
        metadata={},
        call_starts=array("Q"),
        call_ends=array("Q"),
        caller_positions={},
        resolved_target_positions={},
        candidate_target_positions={},
        simple_name_positions={},
        expression_positions={},
        key_counter=[0],
        resolution_counts={key: 0 for key in bundle_access.CALL_RESOLUTION_STATUSES},
        evidence_counts={key: 0 for key in bundle_access.CALL_EVIDENCE_LEVELS},
        relation_counts={key: 0 for key in bundle_access.CALL_RELATION_TYPES},
    )


def _index_call_record(
    builder: _IndexBuilder, raw: dict[str, Any], call_start: int, call_end: int
) -> None:
    if len(builder.call_starts) >= MAX_CALLS:
        raise ValueError("python_call_graph_json exceeds bounded impact-index call count")
    call_position = len(builder.call_starts)
    builder.call_starts.append(call_start)
    builder.call_ends.append(call_end)
    _append_posting(
        builder.caller_positions,
        raw.get("caller_symbol_id"),
        call_position,
        key_counter=builder.key_counter,
    )
    for target_id in raw.get("resolved_target_ids", []):
        _append_posting(
            builder.resolved_target_positions,
            target_id,
            call_position,
            key_counter=builder.key_counter,
        )
    for target_id in raw.get("candidate_target_ids", []):
        _append_posting(
            builder.candidate_target_positions,
            target_id,
            call_position,
            key_counter=builder.key_counter,
        )
    _append_posting(
        builder.simple_name_positions,
        raw.get("simple_name"),
        call_position,
        key_counter=builder.key_counter,
    )
    _append_posting(
        builder.expression_positions,
        raw.get("callee_expression"),
        call_position,
        key_counter=builder.key_counter,
    )
    builder.resolution_counts[raw["resolution_status"]] += 1
    builder.evidence_counts[raw["evidence_level"]] += 1
    builder.relation_counts[raw["relation_type"]] += 1


def _scan_calls_array(
    data: mmap.mmap, position: int, end: int, builder: _IndexBuilder
) -> int:
    if position >= end or data[position] != 0x5B:
        raise ValueError("python_call_graph_json calls must be an array")
    position += 1
    while True:
        position = _skip_ws(data, position, end)
        if position >= end:
            raise ValueError("unterminated python_call_graph_json calls array")
        if data[position] == 0x5D:
            return position + 1
        call_start = position
        call_end = _scan_value_end(data, call_start, end)
        raw = _decode_slice(data, call_start, call_end, label="call graph call record")
        if not isinstance(raw, dict) or not bundle_access._call_record_is_valid(raw):
            raise ValueError(
                f"python_call_graph_json call record at index {len(builder.call_starts)} is invalid"
            )
        _index_call_record(builder, raw, call_start, call_end)
        position = _skip_ws(data, call_end, end)
        if position < end and data[position] == 0x2C:
            position += 1
            continue
        if position < end and data[position] == 0x5D:
            continue
        raise ValueError("invalid separator in python_call_graph_json calls array")


def _scan_object_key(data: mmap.mmap, position: int, end: int) -> tuple[str, int]:
    key_end = _scan_string_end(data, position, end)
    key = _decode_slice(data, position, key_end, label="call graph key")
    if not isinstance(key, str):
        raise ValueError("python_call_graph_json object key must be a string")
    position = _skip_ws(data, key_end, end)
    if position >= end or data[position] != 0x3A:
        raise ValueError("python_call_graph_json object key is missing ':'")
    return key, _skip_ws(data, position + 1, end)


def _advance_object_separator(data: mmap.mmap, position: int, end: int) -> int:
    position = _skip_ws(data, position, end)
    if position < end and data[position] == 0x2C:
        return position + 1
    if position < end and data[position] == 0x7D:
        return position
    raise ValueError("invalid separator in python_call_graph_json object")


def _scan_document(data: mmap.mmap, builder: _IndexBuilder) -> None:
    end = len(data)
    position = _skip_ws(data, 0, end)
    if position >= end or data[position] != 0x7B:
        raise ValueError("python_call_graph_json must be a JSON object")
    position += 1
    while True:
        position = _skip_ws(data, position, end)
        if position >= end:
            raise ValueError("unterminated python_call_graph_json object")
        if data[position] == 0x7D:
            position += 1
            break
        key, position = _scan_object_key(data, position, end)
        if key == "calls":
            if builder.calls_seen:
                raise ValueError("python_call_graph_json calls field is duplicated")
            builder.calls_seen = True
            position = _scan_calls_array(data, position, end, builder)
        else:
            value_end = _scan_value_end(data, position, end)
            if key in _METADATA_FIELDS:
                builder.metadata[key] = _decode_slice(
                    data, position, value_end, label=f"call graph {key}"
                )
            position = value_end
        position = _advance_object_separator(data, position, end)
    if _skip_ws(data, position, end) != end:
        raise ValueError("unexpected trailing data in python_call_graph_json")


def _scan_artifact(
    artifact_path: Path, fingerprint: _SourceFingerprint, builder: _IndexBuilder
) -> tuple[os.stat_result, os.stat_result]:
    try:
        with artifact_path.open("rb") as handle:
            before = os.fstat(handle.fileno())
            if _identity(before) != fingerprint.artifact_identity:
                raise ValueError("python_call_graph_json changed before impact-index scan")
            with mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as data:
                _scan_document(data, builder)
            after = os.fstat(handle.fileno())
    except OSError as exc:
        raise ValueError(f"python_call_graph_json could not be indexed: {exc}") from exc
    return before, after


def _validate_index_builder(
    builder: _IndexBuilder, fingerprint: _SourceFingerprint, manifest: dict[str, Any]
) -> None:
    if not builder.calls_seen:
        raise ValueError("python_call_graph_json calls field is missing")
    identity_error = bundle_access._call_graph_identity_error(builder.metadata)
    if identity_error is not None:
        raise ValueError(str(identity_error.get("error")))
    model_error = bundle_access._call_graph_model_error(builder.metadata)
    if model_error is not None:
        raise ValueError(str(model_error.get("error")))
    _validate_stream_counts(
        builder.metadata,
        call_count=len(builder.call_starts),
        resolution_counts=builder.resolution_counts,
        evidence_counts=builder.evidence_counts,
        relation_counts=builder.relation_counts,
    )
    binding_error = bundle_access._call_graph_manifest_binding_error(
        builder.metadata, Path(fingerprint.manifest_path), manifest=manifest
    )
    if binding_error is not None:
        raise ValueError(str(binding_error.get("error")))


def _scan_index(
    artifact_path: Path,
    *,
    artifact: dict[str, Any],
    fingerprint: _SourceFingerprint,
    manifest: dict[str, Any],
) -> _ImpactIndexState:
    builder = _new_index_builder()
    before, after = _scan_artifact(artifact_path, fingerprint, builder)
    if (
        _identity(before) != _identity(after)
        or _identity(after) != fingerprint.artifact_identity
    ):
        raise ValueError("python_call_graph_json changed while impact index was built")
    _validate_index_builder(builder, fingerprint, manifest)
    return _ImpactIndexState(
        metadata=builder.metadata,
        artifact=artifact,
        fingerprint=fingerprint,
        call_starts=builder.call_starts,
        call_ends=builder.call_ends,
        caller_positions=builder.caller_positions,
        resolved_target_positions=builder.resolved_target_positions,
        candidate_target_positions=builder.candidate_target_positions,
        simple_name_positions=builder.simple_name_positions,
        expression_positions=builder.expression_positions,
    )

def _cached_state(manifest_path: Path) -> _ImpactIndexState | None:
    resolved = str(manifest_path.resolve())
    with _CACHE_LOCK:
        candidates = [
            (fingerprint, state)
            for fingerprint, state in reversed(list(_CACHE.items()))
            if fingerprint.manifest_path == resolved
        ]
    for fingerprint, state in candidates:
        if not _source_is_current(fingerprint):
            with _CACHE_LOCK:
                if _CACHE.get(fingerprint) is state:
                    _CACHE.pop(fingerprint, None)
            continue
        with _CACHE_LOCK:
            if _CACHE.get(fingerprint) is state:
                _CACHE.move_to_end(fingerprint)
                return state
    return None


def _load_state(manifest_path: Path) -> _ImpactIndexState:
    cached = _cached_state(manifest_path)
    if cached is not None:
        return cached
    manifest, artifact, artifact_path, fingerprint = _resolve_verified_source(manifest_path)
    state = _scan_index(
        artifact_path,
        artifact=artifact,
        fingerprint=fingerprint,
        manifest=manifest,
    )
    if not _source_is_current(fingerprint):
        raise ValueError("python_call_graph_json changed after impact index was built")
    with _CACHE_LOCK:
        _CACHE[fingerprint] = state
        _CACHE.move_to_end(fingerprint)
        while len(_CACHE) > CACHE_MAX_ENTRIES:
            _CACHE.popitem(last=False)
    return state


def _positions_for_targets(
    state: _ImpactIndexState, target_symbols: list[dict[str, Any]]
) -> list[int]:
    target_ids = {
        str(item["id"]).casefold()
        for item in target_symbols
        if isinstance(item, dict) and isinstance(item.get("id"), str) and item.get("id")
    }
    qualified_names = {
        str(item["qualified_name"]).casefold()
        for item in target_symbols
        if isinstance(item, dict)
        and isinstance(item.get("qualified_name"), str)
        and item.get("qualified_name")
    }
    simple_names = {
        str(item["name"]).casefold()
        for item in target_symbols
        if isinstance(item, dict) and isinstance(item.get("name"), str) and item.get("name")
    }
    simple_names.update(name.rsplit(".", 1)[-1] for name in qualified_names)
    positions: set[int] = set()

    def add(values: array | None) -> None:
        if values is None:
            return
        for position in values:
            positions.add(int(position))
            if len(positions) > MAX_PROJECTED_CALLS:
                raise ValueError(
                    "call graph impact projection exceeds bounded candidate call count"
                )

    for target_id in target_ids:
        add(state.caller_positions.get(target_id))
        add(state.resolved_target_positions.get(target_id))
        add(state.candidate_target_positions.get(target_id))
    for name in simple_names:
        add(state.simple_name_positions.get(name))
    for name in qualified_names:
        add(state.expression_positions.get(name))
    return sorted(positions)


def _read_projected_calls(
    state: _ImpactIndexState, positions: list[int]
) -> list[dict[str, Any]]:
    artifact_path = Path(state.fingerprint.artifact_path)
    calls: list[dict[str, Any]] = []
    projected_bytes = 0
    try:
        with artifact_path.open("rb") as handle:
            before = os.fstat(handle.fileno())
            if _identity(before) != state.fingerprint.artifact_identity:
                raise ValueError("python_call_graph_json changed before impact projection read")
            for position in positions:
                start = int(state.call_starts[position])
                end = int(state.call_ends[position])
                size = end - start
                projected_bytes += size
                if projected_bytes > MAX_PROJECTED_BYTES:
                    raise ValueError(
                        "call graph impact projection exceeds bounded projected byte count"
                    )
                handle.seek(start)
                payload = handle.read(size)
                if len(payload) != size:
                    raise ValueError("python_call_graph_json changed during impact projection read")
                try:
                    call = json.loads(payload)
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise ValueError("projected python call record is invalid JSON") from exc
                if not isinstance(call, dict) or not bundle_access._call_record_is_valid(call):
                    raise ValueError("projected python call record violates the v1 contract")
                calls.append(call)
            after = os.fstat(handle.fileno())
    except OSError as exc:
        raise ValueError(f"python_call_graph_json projection read failed: {exc}") from exc
    if _identity(before) != _identity(after) or _identity(after) != state.fingerprint.artifact_identity:
        raise ValueError("python_call_graph_json changed during impact projection read")
    return calls


def project_call_graph_for_impact(
    manifest_path: str | Path,
    target_symbols: list[dict[str, Any]],
) -> dict[str, Any]:
    """Return an integrity-bound call-graph projection for selected target symbols."""

    path = Path(manifest_path).resolve()
    try:
        state = _load_state(path)
        positions = _positions_for_targets(state, target_symbols)
        calls = _read_projected_calls(state, positions)
    except FileNotFoundError as exc:
        return {
            "status": "missing",
            "error_code": "python_call_graph_json_missing",
            "error": str(exc),
        }
    except ValueError as exc:
        return {
            "status": "blocked",
            "error_code": "python_call_graph_impact_projection_blocked",
            "error": str(exc),
        }
    document = dict(state.metadata)
    document["calls"] = calls
    document["projection"] = {
        "kind": "impact_relevant_calls",
        "source_call_count": len(state.call_starts),
        "selected_call_count": len(calls),
        "max_source_bytes": MAX_SOURCE_BYTES,
        "max_calls": MAX_CALLS,
        "max_index_keys": MAX_INDEX_KEYS,
        "max_projected_calls": MAX_PROJECTED_CALLS,
        "max_projected_bytes": MAX_PROJECTED_BYTES,
        "source_sha256": state.fingerprint.artifact_sha256,
        "selection_complete_for": [
            "caller_symbol_id",
            "resolved_target_ids",
            "candidate_target_ids",
            "simple_name",
            "callee_expression_exact",
        ],
        "does_not_establish": [
            "complete_call_graph",
            "runtime_reachability",
            "dynamic_dispatch_resolution",
            "test_sufficiency",
        ],
    }
    return {
        "status": "available",
        "artifact": dict(state.artifact),
        "content_json": document,
        "projection": dict(document["projection"]),
    }


def clear_call_graph_impact_index_cache() -> None:
    """Clear process-local projection state for tests and bounded diagnostics."""

    with _CACHE_LOCK:
        _CACHE.clear()


__all__ = [
    "CACHE_MAX_ENTRIES",
    "MAX_CALLS",
    "MAX_INDEX_KEYS",
    "MAX_MANIFEST_BYTES",
    "MAX_PROJECTED_BYTES",
    "MAX_PROJECTED_CALLS",
    "MAX_SOURCE_BYTES",
    "clear_call_graph_impact_index_cache",
    "project_call_graph_for_impact",
]
