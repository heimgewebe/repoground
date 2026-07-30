"""Call-graph navigation over registered bundle artifacts.

Extracted from bundle_access as a T011 residual slice so reference/caller/callee
navigation is not entangled with query and range orchestration.
"""

from __future__ import annotations

import json
import logging
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any, Mapping, Sequence

from merger.repoground.core.citation_projection import (
    is_int_not_bool as _is_int_not_bool,
    is_non_empty_string as _is_non_empty_string,
)

from merger.repoground.architecture.call_graph_contract import (
    PRODUCER_NONCLAIMS as CALL_GRAPH_PRODUCER_NONCLAIMS,
    REQUIRED_NONCLAIMS as CALL_GRAPH_REQUIRED_NONCLAIMS,
)
from merger.repoground.core import call_graph_validation as _call_graph_validation
from merger.repoground.core.call_navigation_index import (
    CallNavigationIndex,
    SymbolNavigationIndex,
)
from merger.repoground.core.bounded_artifact_read import (
    ArtifactSourceFingerprint as _ArtifactSourceFingerprint,
    LoadedArtifactSource as _LoadedArtifactSource,
)
from merger.repoground.core import artifact_source_access as _artifact_source_access
from merger.repoground.core.bundle_roles import (
    DOES_NOT_ESTABLISH as _DOES_NOT_ESTABLISH,
    read_only_mutation_boundary as _read_only_mutation_boundary,
)
from merger.repoground.core.manifest_snapshot import resolve_manifest_path
from merger.repoground.core.response_projection import project_read_result

logger = logging.getLogger(__name__)

# Artifact-source helpers used by warm-cache validation.
_stat_identity_is_strong = _artifact_source_access._stat_identity_is_strong
_cache_validation_mode = _artifact_source_access._cache_validation_mode
_read_registered_artifact_source = (
    _artifact_source_access._read_registered_artifact_source
)
_artifact_source_is_current = _artifact_source_access._artifact_source_is_current
_fingerprint_matches_active_manifest_snapshot = (
    _artifact_source_access._fingerprint_matches_active_manifest_snapshot
)

_call_graph_error = _call_graph_validation.error
_call_graph_identity_error = _call_graph_validation.identity_error
_call_graph_parse_diagnostics = _call_graph_validation.parse_diagnostics
_call_graph_model_error = _call_graph_validation.model_error
_call_graph_records_error = _call_graph_validation.records_error
_call_graph_counts_error = _call_graph_validation.counts_error
_call_graph_manifest_binding_error = _call_graph_validation.manifest_binding_error
_call_record_is_valid = _call_graph_validation.call_record_is_valid


def _bundle_access():
    """Lazy import to resolve helpers that remain on the historical facade."""
    from merger.repoground.core import bundle_access as _ba

    return _ba


def _availability_model_for_manifest(manifest_path: Path) -> dict[str, Any]:
    return _bundle_access()._availability_model_for_manifest(manifest_path)


def _invalid_read_result(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return _bundle_access()._invalid_read_result(*args, **kwargs)


def _registered_source_error(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return _bundle_access()._registered_source_error(*args, **kwargs)


def _load_symbol_index_source(*args: Any, **kwargs: Any):
    return _bundle_access()._load_symbol_index_source(*args, **kwargs)


def _load_symbol_index(*args: Any, **kwargs: Any):
    return _bundle_access()._load_symbol_index(*args, **kwargs)


def _symbol_record(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return _bundle_access()._symbol_record(*args, **kwargs)


CALL_GRAPH_ROLE = "python_call_graph_json"
CALL_GRAPH_KIND = _call_graph_validation.CALL_GRAPH_KIND
CALL_GRAPH_VERSION = _call_graph_validation.CALL_GRAPH_VERSION
CALL_REFERENCES_KIND = "repobrief.call_reference_search"
CALL_CALLERS_KIND = "repobrief.call_callers"
CALL_CALLEES_KIND = "repobrief.call_callees"
MAX_CALL_SEARCH_K = 200
CALL_RESOLUTION_STATUSES = _call_graph_validation.CALL_RESOLUTION_STATUSES
CALL_EVIDENCE_LEVELS = _call_graph_validation.CALL_EVIDENCE_LEVELS
CALL_RELATION_TYPES = _call_graph_validation.CALL_RELATION_TYPES
_CALL_GRAPH_REQUIRED_NONCLAIMS = CALL_GRAPH_REQUIRED_NONCLAIMS
_CALL_GRAPH_DOES_NOT_ESTABLISH = CALL_GRAPH_PRODUCER_NONCLAIMS


_CALL_NAV_DOES_NOT_ESTABLISH = tuple(
    dict.fromkeys([*_DOES_NOT_ESTABLISH, *_CALL_GRAPH_DOES_NOT_ESTABLISH])
)
_CALL_NAVIGATION_CACHE_MAX_ENTRIES = 2


@dataclass(frozen=True, slots=True)
class _CallNavigationState:
    data: dict[str, Any]
    artifact: dict[str, Any] | None
    index: CallNavigationIndex
    fingerprint: _ArtifactSourceFingerprint


@dataclass(frozen=True, slots=True)
class _SymbolNavigationState:
    data: dict[str, Any]
    artifact: dict[str, Any] | None
    index: SymbolNavigationIndex
    call_fingerprint: _ArtifactSourceFingerprint
    symbol_fingerprint: _ArtifactSourceFingerprint


@dataclass(frozen=True, slots=True)
class _ValidatedCallQuery:
    state: _CallNavigationState
    query: str
    path_filter: str | None


_CALL_NAVIGATION_CACHE: OrderedDict[_ArtifactSourceFingerprint, _CallNavigationState] = OrderedDict()
_SYMBOL_NAVIGATION_CACHE: OrderedDict[tuple[_ArtifactSourceFingerprint, _ArtifactSourceFingerprint], _SymbolNavigationState] = OrderedDict()
_CALL_NAVIGATION_CACHE_LOCK = RLock()


def _clear_call_navigation_caches() -> None:
    """Clear process-local derived state; intended for bounded tests and diagnostics."""
    with _CALL_NAVIGATION_CACHE_LOCK:
        _CALL_NAVIGATION_CACHE.clear()
        _SYMBOL_NAVIGATION_CACHE.clear()

def _cache_state(
    cache: OrderedDict[Any, Any], key: Any, state: Any
) -> None:
    cache[key] = state
    cache.move_to_end(key)
    while len(cache) > _CALL_NAVIGATION_CACHE_MAX_ENTRIES:
        evicted_key, _evicted_state = cache.popitem(last=False)
        if cache is _CALL_NAVIGATION_CACHE:
            _drop_symbol_navigation_states_for_call_fingerprint(evicted_key)


def _drop_symbol_navigation_states_for_call_fingerprint(
    fingerprint: _ArtifactSourceFingerprint,
) -> None:
    for cache_key in list(_SYMBOL_NAVIGATION_CACHE):
        if cache_key[0] == fingerprint:
            _SYMBOL_NAVIGATION_CACHE.pop(cache_key, None)


def _drop_call_navigation_state_if_current(
    fingerprint: _ArtifactSourceFingerprint,
    state: _CallNavigationState,
) -> None:
    if _CALL_NAVIGATION_CACHE.get(fingerprint) is state:
        _CALL_NAVIGATION_CACHE.pop(fingerprint, None)
        _drop_symbol_navigation_states_for_call_fingerprint(fingerprint)


def _drop_symbol_navigation_state_if_current(
    cache_key: tuple[_ArtifactSourceFingerprint, _ArtifactSourceFingerprint],
    state: _SymbolNavigationState,
) -> None:
    if _SYMBOL_NAVIGATION_CACHE.get(cache_key) is state:
        _SYMBOL_NAVIGATION_CACHE.pop(cache_key, None)



def _cached_call_navigation_state(
    manifest_path: Path,
) -> _CallNavigationState | None:
    resolved_manifest = str(resolve_manifest_path(manifest_path))
    with _CALL_NAVIGATION_CACHE_LOCK:
        # Snapshot at most two LRU entries so validation can release the lock;
        # a live reversed iterator would become invalid under concurrent mutation.
        candidates = [
            (fingerprint, state)
            for fingerprint, state in reversed(list(_CALL_NAVIGATION_CACHE.items()))
            if fingerprint.manifest_path == resolved_manifest
    ]
    for fingerprint, state in candidates:
        if _fingerprint_matches_active_manifest_snapshot(fingerprint) is False:
            continue
        if not _artifact_source_is_current(fingerprint):
            with _CALL_NAVIGATION_CACHE_LOCK:
                _drop_call_navigation_state_if_current(fingerprint, state)
            continue
        with _CALL_NAVIGATION_CACHE_LOCK:
            if _CALL_NAVIGATION_CACHE.get(fingerprint) is state:
                _CALL_NAVIGATION_CACHE.move_to_end(fingerprint)
                return state
    return None


def _cached_symbol_navigation_state(
    manifest_path: Path, call_state: _CallNavigationState
) -> _SymbolNavigationState | None:
    resolved_manifest = str(resolve_manifest_path(manifest_path))
    with _CALL_NAVIGATION_CACHE_LOCK:
        # Keep the same bounded snapshot rule as the call-navigation cache.
        candidates = [
            (cache_key, state)
            for cache_key, state in reversed(list(_SYMBOL_NAVIGATION_CACHE.items()))
            if cache_key[0] == call_state.fingerprint
            and cache_key[1].manifest_path == resolved_manifest
    ]
    for cache_key, state in candidates:
        if _fingerprint_matches_active_manifest_snapshot(cache_key[1]) is False:
            continue
        if not _artifact_source_is_current(cache_key[1]):
            with _CALL_NAVIGATION_CACHE_LOCK:
                _drop_symbol_navigation_state_if_current(cache_key, state)
            continue
        if not _artifact_source_is_current(call_state.fingerprint):
            with _CALL_NAVIGATION_CACHE_LOCK:
                _drop_call_navigation_state_if_current(
                    call_state.fingerprint,
                    call_state,
                )
            return None
        with _CALL_NAVIGATION_CACHE_LOCK:
            if _SYMBOL_NAVIGATION_CACHE.get(cache_key) is state:
                _SYMBOL_NAVIGATION_CACHE.move_to_end(cache_key)
                return state
    return None


def _call_nav_does_not_establish() -> list[str]:
    return list(_CALL_NAV_DOES_NOT_ESTABLISH)


_CALL_GRAPH_SOURCE_ERRORS = {
    "missing": (
        "missing",
        "python_call_graph_json_missing",
        "python_call_graph_json artifact is not present in the bundle manifest",
    ),
    "file_missing": (
        "missing",
        "python_call_graph_json_file_missing",
        "python_call_graph_json artifact file does not exist",
    ),
    "role_ambiguous": (
        "invalid",
        "python_call_graph_json_role_ambiguous",
        "bundle manifest contains multiple python_call_graph_json artifacts",
    ),
    "path_invalid": (
        "invalid",
        "python_call_graph_json_path_invalid",
        "python_call_graph_json artifact path escapes the bundle root",
    ),
    "manifest_too_large": (
        "invalid",
        "bundle_manifest_too_large",
        "bundle manifest exceeds the bounded read limit",
    ),
    "manifest_invalid": (
        "invalid",
        "bundle_manifest_invalid",
        "bundle manifest identity, run_id, or artifacts are invalid",
    ),
    "integrity_unavailable": (
        "invalid",
        "python_call_graph_json_integrity_unavailable",
        (
            "python_call_graph_json requires valid bytes and sha256 metadata "
            "in the bundle manifest"
        ),
    ),
    "too_large": (
        "invalid",
        "python_call_graph_json_too_large",
        "python_call_graph_json exceeds the bounded read limit",
    ),
    "bytes_mismatch": (
        "invalid",
        "python_call_graph_json_bytes_mismatch",
        "python_call_graph_json byte count does not match the bundle manifest",
    ),
    "sha256_mismatch": (
        "invalid",
        "python_call_graph_json_sha256_mismatch",
        "python_call_graph_json content hash does not match the bundle manifest",
    ),
    "source_changed": (
        "invalid",
        "python_call_graph_source_changed_during_load",
        (
            "python_call_graph_json source changed while navigation state "
            "was loading"
        ),
    ),
    "unreadable": (
        "invalid",
        "python_call_graph_json_unreadable",
        "python_call_graph_json could not be read",
    ),
}


def _read_call_graph_source(
    manifest_path: Path,
) -> tuple[
    dict[str, Any] | None,
    dict[str, Any] | None,
    _LoadedArtifactSource | None,
    dict[str, Any] | None,
]:
    source, artifact, failure, detail = _read_registered_artifact_source(
        manifest_path, CALL_GRAPH_ROLE
    )
    source_error = _registered_source_error(
        failure,
        detail,
        _CALL_GRAPH_SOURCE_ERRORS,
    )
    if source_error is not None:
        return None, artifact, None, source_error
    assert source is not None
    try:
        data = json.loads(source.raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, artifact, None, _call_graph_error(
            "python_call_graph_json_unreadable", str(exc)
        )
    return data, artifact, source, None


def _read_call_graph_artifact(
    manifest_path: Path,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None]:
    data, artifact, _source, error = _read_call_graph_source(manifest_path)
    return data, artifact, error


def _load_call_graph_source(
    manifest_path: Path,
) -> tuple[
    dict[str, Any] | None,
    dict[str, Any] | None,
    _LoadedArtifactSource | None,
    dict[str, Any] | None,
]:
    data, artifact, source, error = _read_call_graph_source(manifest_path)
    if error is not None:
        return None, artifact, None, error
    assert data is not None and source is not None
    for validator in (
        _call_graph_identity_error,
        _call_graph_model_error,
        _call_graph_records_error,
        _call_graph_counts_error,
    ):
        error = validator(data)
        if error is not None:
            return None, artifact, None, error
    error = _call_graph_manifest_binding_error(
        data, manifest_path, manifest=source.manifest
    )
    if error is not None:
        return None, artifact, None, error
    return data, artifact, source, None


def _load_call_graph(
    manifest_path: Path,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None]:
    """Strictly load a registered, integrity-checked Python call graph."""
    data, artifact, _source, error = _load_call_graph_source(manifest_path)
    return data, artifact, error


def _load_call_navigation_state(
    manifest_path: Path,
) -> tuple[_CallNavigationState | None, dict[str, Any] | None, dict[str, Any] | None]:
    """Load and index one call graph, reusing it only while its source is unchanged."""
    cached = _cached_call_navigation_state(manifest_path)
    if cached is not None:
        return cached, cached.artifact, None

    data, artifact, source, error = _load_call_graph_source(manifest_path)
    if error is not None:
        return None, artifact, error
    assert data is not None and source is not None
    index = CallNavigationIndex.build(data["calls"])
    if not _artifact_source_is_current(source.fingerprint, verify_content=True):
        return None, artifact, _call_graph_error(
            "python_call_graph_source_changed_during_load",
            "python_call_graph_json source changed while navigation state was loading",
        )
    state = _CallNavigationState(
        data=data,
        artifact=artifact,
        index=index,
        fingerprint=source.fingerprint,
    )
    with _CALL_NAVIGATION_CACHE_LOCK:
        _cache_state(_CALL_NAVIGATION_CACHE, source.fingerprint, state)
    return state, artifact, None


def _load_symbol_navigation_state(
    manifest_path: Path, call_state: _CallNavigationState
) -> tuple[_SymbolNavigationState | None, dict[str, Any] | None, dict[str, Any] | None]:
    """Load a coherent symbol index bound to the cached call-graph source."""
    cached = _cached_symbol_navigation_state(manifest_path, call_state)
    if cached is not None:
        return cached, cached.artifact, None

    symbol_data, symbol_artifact, source, error = _load_symbol_index_source(
        manifest_path
    )
    if error is not None:
        return None, symbol_artifact, error
    assert symbol_data is not None and source is not None
    error = _symbol_index_identity_error(symbol_data, call_state.data)
    if error is not None:
        return None, symbol_artifact, error
    symbols, rows_by_id, error = _validated_symbol_rows(symbol_data)
    if error is not None:
        return None, symbol_artifact, error
    assert symbols is not None and rows_by_id is not None
    error = _call_symbol_reference_error(call_state.data, rows_by_id)
    if error is not None:
        return None, symbol_artifact, error
    index = SymbolNavigationIndex.build(symbols)
    if not _artifact_source_is_current(source.fingerprint, verify_content=True):
        return None, symbol_artifact, _call_graph_error(
            "python_symbol_index_source_changed_during_load",
            "python_symbol_index_json source changed while navigation state was loading",
        )
    if not _artifact_source_is_current(
        call_state.fingerprint, verify_content=True
    ):
        return None, symbol_artifact, _call_graph_error(
            "python_call_graph_source_changed_during_load",
            "python_call_graph_json source changed while navigation state was loading",
        )
    state = _SymbolNavigationState(
        data=symbol_data,
        artifact=symbol_artifact,
        index=index,
        call_fingerprint=call_state.fingerprint,
        symbol_fingerprint=source.fingerprint,
    )
    cache_key = (call_state.fingerprint, source.fingerprint)
    with _CALL_NAVIGATION_CACHE_LOCK:
        _cache_state(_SYMBOL_NAVIGATION_CACHE, cache_key, state)
    return state, symbol_artifact, None


def _call_source_range(call: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": call.get("path"),
        "start_line": call.get("start_line"),
        "end_line": call.get("end_line"),
        "range_ref": call.get("range_ref"),
        "coordinate_basis": "source_lines",
    }


def _call_site_record(call: dict[str, Any]) -> dict[str, Any]:
    resolved_target_ids = call.get("resolved_target_ids")
    candidate_target_ids = call.get("candidate_target_ids")
    return {
        "path": call.get("path"),
        "start_line": call.get("start_line"),
        "start_col": call.get("start_col"),
        "end_line": call.get("end_line"),
        "end_col": call.get("end_col"),
        "range_ref": call.get("range_ref"),
        "callee_expression": call.get("callee_expression"),
        "simple_name": call.get("simple_name"),
        "caller_scope": call.get("caller_scope"),
        "caller_symbol_id": call.get("caller_symbol_id"),
        "caller_qualified_name": call.get("caller_qualified_name"),
        "caller_kind": call.get("caller_kind"),
        "caller_start_line": call.get("caller_start_line"),
        "caller_end_line": call.get("caller_end_line"),
        "relation_type": call.get("relation_type"),
        "evidence_level": call.get("evidence_level"),
        "resolution_status": call.get("resolution_status"),
        "resolution_reason": call.get("resolution_reason"),
        "resolved_target_ids": (
            list(resolved_target_ids) if isinstance(resolved_target_ids, list) else []
        ),
        "candidate_target_ids": (
            list(candidate_target_ids) if isinstance(candidate_target_ids, list) else []
        ),
        "source_range": _call_source_range(call),
    }


def _detached_json_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _detached_json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_detached_json_value(item) for item in value]
    return value


def _detached_record(value: Any) -> dict[str, Any] | None:
    return _detached_json_value(value) if isinstance(value, dict) else None


def _call_graph_metadata(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": data.get("run_id"),
        "canonical_dump_index_sha256": data.get("canonical_dump_index_sha256"),
        "call_count": data.get("call_count"),
        "resolution_counts": _detached_record(data.get("resolution_counts")),
        "evidence_counts": _detached_record(data.get("evidence_counts")),
        "relation_counts": _detached_record(data.get("relation_counts")),
        **_call_graph_parse_diagnostics(data),
    }


def _call_empty(kind: str) -> dict[str, Any]:
    if kind == CALL_REFERENCES_KIND:
        return {"hits": []}
    if kind == CALL_CALLERS_KIND:
        return {"target_symbol": None, "target_candidates": [], "callers": [], "unresolved_references": []}
    return {"caller_symbol": None, "caller_candidates": [], "callees": [], "unresolved_call_sites": []}


def _validated_call_query(
    *,
    kind: str,
    manifest_path: Path,
    name: Any,
    k: Any,
    path: Any,
) -> _ValidatedCallQuery | dict[str, Any]:
    def _extra(artifact: dict[str, Any] | None) -> dict[str, Any]:
        return {
            "name": name,
            "k": k,
            "filters": {"path": path},
            "call_graph": _detached_record(artifact),
            **_call_empty(kind),
        }

    if not isinstance(name, str) or not name.strip():
        return _invalid_read_result(
            kind=kind,
            bundle_manifest=manifest_path,
            status="invalid",
            error="name must be a non-empty string",
            error_code="name_invalid",
            extra=_extra(None),
        )
    if not isinstance(k, int) or isinstance(k, bool) or k < 1 or k > MAX_CALL_SEARCH_K:
        return _invalid_read_result(
            kind=kind,
            bundle_manifest=manifest_path,
            status="invalid",
            error=f"k must be an integer between 1 and {MAX_CALL_SEARCH_K}",
            error_code="k_out_of_bounds",
            extra=_extra(None),
        )
    if path is not None and not isinstance(path, str):
        return _invalid_read_result(
            kind=kind,
            bundle_manifest=manifest_path,
            status="invalid",
            error="path must be null or a string",
            error_code="path_invalid",
            extra=_extra(None),
        )
    state, artifact, error = _load_call_navigation_state(manifest_path)
    if error is not None:
        return _invalid_read_result(
            kind=kind,
            bundle_manifest=manifest_path,
            status=error["status"],
            error=error["error"],
            error_code=error["error_code"],
            extra=_extra(artifact),
        )
    assert state is not None
    path_filter = path.strip().casefold() if isinstance(path, str) and path.strip() else None
    return _ValidatedCallQuery(
        state=state,
        query=name.strip().casefold(),
        path_filter=path_filter,
    )


def _symbol_index_identity_error(
    symbol_data: dict[str, Any], call_data: dict[str, Any]
) -> dict[str, Any] | None:
    if symbol_data.get("version") != "1.0":
        return _call_graph_error(
            "python_symbol_index_json_version_unsupported",
            "python_symbol_index_json version must be 1.0 for call navigation",
        )
    if symbol_data.get("run_id") != call_data.get("run_id"):
        return _call_graph_error(
            "call_symbol_run_id_mismatch",
            "python_call_graph_json and python_symbol_index_json run_id differ",
        )
    if symbol_data.get("canonical_dump_index_sha256") != call_data.get(
        "canonical_dump_index_sha256"
    ):
        return _call_graph_error(
            "call_symbol_canonical_binding_mismatch",
            "call graph and symbol index canonical bindings differ",
        )
    return None


def _validated_symbol_rows(
    symbol_data: dict[str, Any],
) -> tuple[
    list[dict[str, Any]] | None,
    dict[str, list[dict[str, Any]]] | None,
    dict[str, Any] | None,
]:
    symbols = symbol_data.get("symbols")
    if not isinstance(symbols, list):
        return None, None, _call_graph_error(
            "python_symbol_index_symbols_invalid",
            "python_symbol_index_json symbols must be an array",
        )
    rows_by_id: dict[str, list[dict[str, Any]]] = {}
    for position, symbol in enumerate(symbols):
        if not isinstance(symbol, dict):
            return None, None, _call_graph_error(
                "python_symbol_index_symbol_invalid",
                f"python_symbol_index_json symbol at index {position} is invalid",
            )
        if symbol.get("kind") not in ("class", "function", "async_function"):
            return None, None, _call_graph_error(
                "python_symbol_index_symbol_kind_invalid",
                f"python_symbol_index_json symbol at index {position} has invalid kind",
            )
        required_fields = ("id", "name", "qualified_name", "path")
        if not all(_is_non_empty_string(symbol.get(field)) for field in required_fields):
            return None, None, _call_graph_error(
                "python_symbol_index_symbol_shape_invalid",
                f"python_symbol_index_json symbol at index {position} has invalid shape",
            )
        start_line = symbol.get("start_line")
        end_line = symbol.get("end_line")
        if (
            not _is_int_not_bool(start_line)
            or not _is_int_not_bool(end_line)
            or start_line < 1
            or end_line < start_line
        ):
            return None, None, _call_graph_error(
                "python_symbol_index_symbol_range_invalid",
                f"python_symbol_index_json symbol at index {position} has invalid range",
            )
        rows_by_id.setdefault(symbol["id"], []).append(symbol)
    return symbols, rows_by_id, None


def _matching_caller_symbol_rows(
    call: dict[str, Any],
    rows_by_id: Mapping[str, Sequence[dict[str, Any]]],
) -> list[dict[str, Any]]:
    caller_id = call.get("caller_symbol_id")
    if not isinstance(caller_id, str):
        return []
    return [
        row
        for row in rows_by_id.get(caller_id, [])
        if row.get("path") == call.get("path")
        and row.get("qualified_name") == call.get("caller_qualified_name")
        and row.get("kind") == call.get("caller_kind")
        and row.get("start_line") == call.get("caller_start_line")
        and row.get("end_line") == call.get("caller_end_line")
    ]


def _call_symbol_reference_error(
    call_data: dict[str, Any],
    rows_by_id: Mapping[str, Sequence[dict[str, Any]]],
) -> dict[str, Any] | None:
    for position, call in enumerate(call_data.get("calls", [])):
        if call.get("caller_scope") == "symbol":
            caller_matches = _matching_caller_symbol_rows(call, rows_by_id)
            if not caller_matches:
                return _call_graph_error(
                    "python_call_graph_caller_symbol_mismatch",
                    f"call record {position} does not match a caller definition range",
                )
            if len(caller_matches) > 1:
                return _call_graph_error(
                    "python_call_graph_caller_symbol_ambiguous",
                    f"call record {position} matches more than one caller definition",
                )
        for target_id in call.get("resolved_target_ids", []):
            if target_id not in rows_by_id:
                return _call_graph_error(
                    "python_call_graph_target_symbol_missing",
                    f"call record {position} references an absent target symbol",
                )
    return None


def _coherent_symbol_index(
    manifest_path: Path, call_data: dict[str, Any]
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None]:
    symbol_data, symbol_artifact, error = _load_symbol_index(manifest_path)
    if error is not None:
        return None, symbol_artifact, error
    error = _symbol_index_identity_error(symbol_data, call_data)
    if error is not None:
        return None, symbol_artifact, error
    _, rows_by_id, error = _validated_symbol_rows(symbol_data)
    if error is not None:
        return None, symbol_artifact, error
    assert rows_by_id is not None
    error = _call_symbol_reference_error(call_data, rows_by_id)
    if error is not None:
        return None, symbol_artifact, error
    return symbol_data, symbol_artifact, None


def _symbol_rows_by_id(
    symbol_data: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    rows_by_id: dict[str, list[dict[str, Any]]] = {}
    for row in symbol_data.get("symbols", []):
        rows_by_id.setdefault(row["id"], []).append(row)
    return rows_by_id


def _call_belongs_to_symbol(call: dict[str, Any], symbol: dict[str, Any]) -> bool:
    return (
        call.get("caller_symbol_id") == symbol.get("id")
        and call.get("path") == symbol.get("path")
        and call.get("caller_qualified_name") == symbol.get("qualified_name")
        and call.get("caller_kind") == symbol.get("kind")
        and call.get("caller_start_line") == symbol.get("start_line")
        and call.get("caller_end_line") == symbol.get("end_line")
    )


def _select_symbols(
    symbol_data: dict[str, Any], query: str, path_filter: str | None
) -> list[dict[str, Any]]:
    matches = []
    for symbol in symbol_data.get("symbols", []):
        exact = (
            str(symbol.get("name", "")).casefold() == query
            or str(symbol.get("qualified_name", "")).casefold() == query
        )
        if not exact:
            continue
        if path_filter and path_filter not in str(symbol.get("path", "")).casefold():
            continue
        matches.append(symbol)
    return sorted(
        matches,
        key=lambda item: (
            str(item.get("path", "")),
            int(item.get("start_line", 0) or 0),
            str(item.get("qualified_name", "")),
            str(item.get("id", "")),
        ),
    )


def _selected_symbol_or_error(
    *,
    kind: str,
    manifest_path: Path,
    name: str,
    k: int,
    path: str | None,
    call_state: _CallNavigationState,
    query: str,
    path_filter: str | None,
    caller_mode: bool,
) -> tuple[dict[str, Any], _SymbolNavigationState] | dict[str, Any]:
    symbol_state, symbol_artifact, error = _load_symbol_navigation_state(
        manifest_path, call_state
    )
    candidate_key = "caller_candidates" if caller_mode else "target_candidates"
    symbol_key = "caller_symbol" if caller_mode else "target_symbol"
    empty = _call_empty(kind)
    if error is not None:
        return _invalid_read_result(
            kind=kind,
            bundle_manifest=manifest_path,
            status=error["status"],
            error=error["error"],
            error_code=error["error_code"],
            extra={
                "name": name,
                "k": k,
                "filters": {"path": path},
                "call_graph": _detached_record(call_state.artifact),
                "symbol_index": _detached_record(symbol_artifact),
                **empty,
            },
        )
    assert symbol_state is not None
    matches = symbol_state.index.select(query, path_filter)
    if len(matches) != 1:
        status = "missing" if not matches else "invalid"
        error_code = "symbol_not_found" if not matches else "symbol_ambiguous"
        error_text = (
            "no exact symbol matches name and path"
            if not matches
            else "name and path select more than one exact symbol"
        )
        empty[symbol_key] = None
        empty[candidate_key] = [_symbol_record(item) for item in matches]
        return _invalid_read_result(
            kind=kind,
            bundle_manifest=manifest_path,
            status=status,
            error=error_text,
            error_code=error_code,
            extra={
                "name": name,
                "k": k,
                "filters": {"path": path},
                "call_graph": _detached_record(call_state.artifact),
                "symbol_index": _detached_record(symbol_state.artifact),
                **empty,
            },
        )
    return _symbol_record(matches[0]), symbol_state


def find_references(
    bundle_manifest: str | Path,
    name: str,
    path: str | None = None,
    k: int = 25,
    *,
    verbose: bool = True,
    compact: bool | None = None,
) -> dict[str, Any]:
    """Search call-site text while keeping S0 and S1 evidence explicit.

    Returns the historical full contract by default. Pass ``compact=True`` (or
    ``verbose=False``) for the bounded agent projection.
    """
    if compact is not None:
        verbose = not compact
    manifest_path = resolve_manifest_path(bundle_manifest)
    return project_read_result(
        _find_references_full(manifest_path, name, path=path, k=k),
        manifest_path,
        verbose=verbose,
    )


def _find_references_full(
    manifest_path: Path,
    name: str,
    *,
    path: str | None = None,
    k: int = 25,
) -> dict[str, Any]:
    """Search call-site text while keeping S0 and S1 evidence explicit."""
    validated = _validated_call_query(
        kind=CALL_REFERENCES_KIND,
        manifest_path=manifest_path,
        name=name,
        k=k,
        path=path,
    )
    if isinstance(validated, dict):
        return validated
    state = validated.state
    data = state.data
    artifact = state.artifact
    query = validated.query
    path_filter = validated.path_filter
    matched = [
        call
        for call in state.index.reference_calls(query)
        if not path_filter
        or path_filter in str(call.get("path", "")).casefold()
    ]
    exact_match_count = sum(
        1
        for call in matched
        if isinstance(call.get("simple_name"), str)
        and call["simple_name"].casefold() == query
    )
    hits = [_call_site_record(call) for call in matched[:k]]
    availability = _availability_model_for_manifest(manifest_path)
    return {
        "kind": CALL_REFERENCES_KIND,
        "version": "v1",
        "status": "available",
        "bundle_manifest": str(manifest_path),
        "name": name,
        "k": k,
        "filters": {"path": path},
        "call_graph": _detached_record(artifact),
        "call_graph_metadata": _call_graph_metadata(data),
        "availability": availability,
        "freshness": availability.get("freshness") if isinstance(availability, dict) else None,
        "total_match_count": len(matched),
        "exact_match_count": exact_match_count,
        "hit_count": len(hits),
        "truncated": len(matched) > k,
        "hits": hits,
        "mutation_boundary": _read_only_mutation_boundary(),
        "does_not_establish": _call_nav_does_not_establish(),
    }


def get_callers(
    bundle_manifest: str | Path,
    name: str,
    path: str | None = None,
    k: int = 25,
    *,
    verbose: bool = True,
    compact: bool | None = None,
) -> dict[str, Any]:
    """Return only S1 callers of one uniquely selected target symbol.

    Returns the historical full contract by default. Pass ``compact=True`` (or
    ``verbose=False``) for the bounded agent projection.
    """
    if compact is not None:
        verbose = not compact
    manifest_path = resolve_manifest_path(bundle_manifest)
    return project_read_result(
        _get_callers_full(manifest_path, name, path=path, k=k),
        manifest_path,
        verbose=verbose,
    )


def _get_callers_full(
    manifest_path: Path,
    name: str,
    *,
    path: str | None = None,
    k: int = 25,
) -> dict[str, Any]:
    """Return only S1 callers of one uniquely selected target symbol."""
    validated = _validated_call_query(
        kind=CALL_CALLERS_KIND,
        manifest_path=manifest_path,
        name=name,
        k=k,
        path=path,
    )
    if isinstance(validated, dict):
        return validated
    state = validated.state
    data = state.data
    artifact = state.artifact
    query = validated.query
    path_filter = validated.path_filter
    selected = _selected_symbol_or_error(
        kind=CALL_CALLERS_KIND,
        manifest_path=manifest_path,
        name=name,
        k=k,
        path=path,
        call_state=state,
        query=query,
        path_filter=path_filter,
        caller_mode=False,
    )
    if isinstance(selected, dict):
        return selected
    target_symbol, symbol_state = selected
    symbol_artifact = symbol_state.artifact
    target_id = target_symbol["id"]
    rows_by_id = symbol_state.index.rows_by_id
    groups: dict[str, dict[str, Any]] = {}
    unresolved_references: list[dict[str, Any]] = []
    total_call_site_count = 0
    for call in state.index.target_related_calls(target_id, query):
        if target_id in call.get("resolved_target_ids", []):
            total_call_site_count += 1
            caller_symbol_id = call.get("caller_symbol_id")
            if isinstance(caller_symbol_id, str):
                caller_rows = _matching_caller_symbol_rows(call, rows_by_id)
                assert len(caller_rows) == 1
                caller_symbol = _symbol_record(caller_rows[0])
                group_key = (
                    f"{caller_symbol_id}@"
                    f"{call['caller_start_line']}-{call['caller_end_line']}"
                )
            else:
                caller_symbol = None
                group_key = f"module:{call.get('path')}"
            group = groups.setdefault(
                group_key,
                {
                    "caller_scope": call.get("caller_scope"),
                    "caller_symbol_id": caller_symbol_id,
                    "caller_qualified_name": call.get("caller_qualified_name"),
                    "caller_kind": call.get("caller_kind"),
                    "caller_start_line": call.get("caller_start_line"),
                    "caller_end_line": call.get("caller_end_line"),
                    "caller_symbol": caller_symbol,
                    "path": call.get("path"),
                    "call_sites": [],
                },
            )
            group["call_sites"].append(_call_site_record(call))
        elif (
            target_id in call.get("candidate_target_ids", [])
            or str(call.get("simple_name", "")).casefold() == query
        ):
            unresolved = _call_site_record(call)
            unresolved["relation_to_selected_target"] = (
                "candidate_target" if target_id in call.get("candidate_target_ids", []) else "textual_name_only"
            )
            unresolved_references.append(unresolved)
    ordered = sorted(
        groups.items(),
        key=lambda item: (
            str(item[1]["path"]),
            min(site["start_line"] for site in item[1]["call_sites"]),
            item[0],
        ),
    )
    callers = []
    for _, group in ordered[:k]:
        group["call_sites"].sort(key=lambda site: (site["start_line"], site["start_col"]))
        group["call_site_count"] = len(group["call_sites"])
        callers.append(group)
    unresolved_references.sort(
        key=lambda item: (str(item["path"]), item["start_line"], item["start_col"])
    )
    unresolved_visible = unresolved_references[:k]
    availability = _availability_model_for_manifest(manifest_path)
    return {
        "kind": CALL_CALLERS_KIND,
        "version": "v1",
        "status": "available",
        "bundle_manifest": str(manifest_path),
        "name": name,
        "k": k,
        "filters": {"path": path},
        "target_symbol": target_symbol,
        "target_candidates": [],
        "call_graph": _detached_record(artifact),
        "symbol_index": _detached_record(symbol_artifact),
        "call_graph_metadata": _call_graph_metadata(data),
        "availability": availability,
        "freshness": availability.get("freshness") if isinstance(availability, dict) else None,
        "total_caller_count": len(groups),
        "total_call_site_count": total_call_site_count,
        "hit_count": len(callers),
        "truncated": len(groups) > k,
        "callers": callers,
        "unresolved_reference_count": len(unresolved_references),
        "unresolved_references_truncated": len(unresolved_references) > k,
        "unresolved_references": unresolved_visible,
        "mutation_boundary": _read_only_mutation_boundary(),
        "does_not_establish": _call_nav_does_not_establish(),
    }


def get_callees(
    bundle_manifest: str | Path,
    name: str,
    path: str | None = None,
    k: int = 25,
    *,
    verbose: bool = True,
    compact: bool | None = None,
) -> dict[str, Any]:
    """Return S1 callees and separate unresolved sites for one caller symbol.

    Returns the historical full contract by default. Pass ``compact=True`` (or
    ``verbose=False``) for the bounded agent projection.
    """
    if compact is not None:
        verbose = not compact
    manifest_path = resolve_manifest_path(bundle_manifest)
    return project_read_result(
        _get_callees_full(manifest_path, name, path=path, k=k),
        manifest_path,
        verbose=verbose,
    )


def _get_callees_full(
    manifest_path: Path,
    name: str,
    *,
    path: str | None = None,
    k: int = 25,
) -> dict[str, Any]:
    """Return S1 callees and separate unresolved sites for one caller symbol."""
    validated = _validated_call_query(
        kind=CALL_CALLEES_KIND,
        manifest_path=manifest_path,
        name=name,
        k=k,
        path=path,
    )
    if isinstance(validated, dict):
        return validated
    state = validated.state
    data = state.data
    artifact = state.artifact
    query = validated.query
    path_filter = validated.path_filter
    selected = _selected_symbol_or_error(
        kind=CALL_CALLEES_KIND,
        manifest_path=manifest_path,
        name=name,
        k=k,
        path=path,
        call_state=state,
        query=query,
        path_filter=path_filter,
        caller_mode=True,
    )
    if isinstance(selected, dict):
        return selected
    caller_symbol, symbol_state = selected
    symbol_artifact = symbol_state.artifact
    rows_by_id = symbol_state.index.rows_by_id
    groups: dict[str, dict[str, Any]] = {}
    unresolved_call_sites: list[dict[str, Any]] = []
    caller_sites = state.index.calls_for_symbol(caller_symbol)
    for call in caller_sites:
        if call.get("resolution_status") == "resolved":
            target_id = call["resolved_target_ids"][0]
            target_rows = rows_by_id.get(target_id, [])
            if len(target_rows) != 1:
                return _invalid_read_result(
                    kind=CALL_CALLEES_KIND,
                    bundle_manifest=manifest_path,
                    status="invalid",
                    error="resolved callee id does not select exactly one symbol definition",
                    error_code="python_call_graph_target_symbol_ambiguous",
                    extra={
                        "name": name,
                        "k": k,
                        "filters": {"path": path},
                        "caller_symbol": caller_symbol,
                        "caller_candidates": [],
                        "call_graph": _detached_record(artifact),
                        "symbol_index": _detached_record(symbol_artifact),
                        "callees": [],
                        "unresolved_call_sites": [],
                    },
                )
            group = groups.setdefault(
                target_id,
                {
                    "callee_symbol": _symbol_record(target_rows[0]),
                    "relation_types": [],
                    "call_sites": [],
                },
            )
            group["relation_types"].append(call["relation_type"])
            group["call_sites"].append(_call_site_record(call))
        else:
            unresolved_call_sites.append(_call_site_record(call))
    ordered = sorted(
        groups.items(),
        key=lambda item: (
            str(item[1]["callee_symbol"]["path"]),
            int(item[1]["callee_symbol"]["start_line"] or 0),
            item[0],
        ),
    )
    callees = []
    for _, group in ordered[:k]:
        group["relation_types"] = sorted(set(group["relation_types"]))
        group["call_sites"].sort(key=lambda site: (site["start_line"], site["start_col"]))
        group["call_site_count"] = len(group["call_sites"])
        callees.append(group)
    unresolved_call_sites.sort(
        key=lambda item: (str(item["path"]), item["start_line"], item["start_col"])
    )
    unresolved_visible = unresolved_call_sites[:k]
    availability = _availability_model_for_manifest(manifest_path)
    return {
        "kind": CALL_CALLEES_KIND,
        "version": "v1",
        "status": "available",
        "bundle_manifest": str(manifest_path),
        "name": name,
        "k": k,
        "filters": {"path": path},
        "caller_symbol": caller_symbol,
        "caller_candidates": [],
        "call_graph": _detached_record(artifact),
        "symbol_index": _detached_record(symbol_artifact),
        "call_graph_metadata": _call_graph_metadata(data),
        "availability": availability,
        "freshness": availability.get("freshness") if isinstance(availability, dict) else None,
        "total_callee_count": len(groups),
        "total_call_site_count": len(caller_sites),
        "hit_count": len(callees),
        "truncated": len(groups) > k,
        "callees": callees,
        "unresolved_call_site_count": len(unresolved_call_sites),
        "unresolved_call_sites_truncated": len(unresolved_call_sites) > k,
        "unresolved_call_sites": unresolved_visible,
        "mutation_boundary": _read_only_mutation_boundary(),
        "does_not_establish": _call_nav_does_not_establish(),
    }
