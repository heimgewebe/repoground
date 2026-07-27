from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any, BinaryIO, Iterator, Mapping, Sequence

from merger.repoground.architecture.call_graph_contract import (
    PRODUCER_NONCLAIMS as CALL_GRAPH_PRODUCER_NONCLAIMS,
    REQUIRED_NONCLAIMS as CALL_GRAPH_REQUIRED_NONCLAIMS,
)
from merger.repoground.core import call_graph_validation as _call_graph_validation
from merger.repoground.core.call_navigation_index import (
    CallNavigationIndex,
    SymbolNavigationIndex,
)
from merger.repoground.core.bundle_identity import is_bundle_manifest
from merger.repoground.core.bounded_artifact_read import (
    MAX_REGISTERED_ARTIFACT_BYTES,
    ArtifactSourceFingerprint as _ArtifactSourceFingerprint,
    LoadedArtifactSource as _LoadedArtifactSource,
    declared_artifact_integrity,
    file_identity as _file_identity,
    read_stable_regular_file_bytes,
)
from merger.repoground.core import bundle_roles as _bundle_roles
from merger.repoground.core import citation_projection as _citation_projection_module
from merger.repoground.core import sqlite_artifact_read as _sqlite_artifact_read
from merger.repoground.core.bundle_roles import (
    DOES_NOT_ESTABLISH as _DOES_NOT_ESTABLISH,
    read_json_object as _read_json_object,
    read_only_mutation_boundary as _read_only_mutation_boundary,
    resolve_unique_artifact as _resolve_unique_artifact,
    safe_artifact_path as _safe_artifact_path,
)
from merger.repoground.core.citation_projection import (
    CITATION_MAP_ROLE,
    RESOLVED_EVIDENCE_KIND,
    RESOLVED_EVIDENCE_VERSION,
    citation_range_key as _citation_range_key,
    citation_record as _citation_record,
    citation_row_is_valid as _citation_row_is_valid,
    enrich_resolved_hit_for_direct_use as _enrich_resolved_hit_for_direct_use,
    is_int_not_bool as _is_int_not_bool,
    is_non_empty_string as _is_non_empty_string,
    project_source_citations as _project_source_citations,
)
from merger.repoground.core.manifest_snapshot import (
    MAX_MANIFEST_BYTES,
    active_manifest_snapshot,
    resolve_manifest_path,
)
from merger.repoground.core.response_projection import project_read_result

available_roles = _bundle_roles.available_roles
get_artifact = _bundle_roles.get_artifact
list_artifacts = _bundle_roles.list_artifacts
resolve_required_reading_for_bundle = (
    _bundle_roles.resolve_required_reading_for_bundle
)
snapshot_check = _bundle_roles.snapshot_check
snapshot_status = _bundle_roles.snapshot_status
_artifact_list = _bundle_roles.artifact_list
_artifact_record = _bundle_roles.artifact_record

SOURCE_CITATION_PROJECTION_KIND = (
    _citation_projection_module.SOURCE_CITATION_PROJECTION_KIND
)
SOURCE_CITATION_PROJECTION_VERSION = (
    _citation_projection_module.SOURCE_CITATION_PROJECTION_VERSION
)
TEXT_EXCERPT_MAX_CHARS = _citation_projection_module.TEXT_EXCERPT_MAX_CHARS
_artifact_availability = _citation_projection_module.artifact_availability
_empty_source_citation_projection = (
    _citation_projection_module.empty_source_citation_projection
)
_first_not_none = _citation_projection_module.first_not_none
_has_range_identity = _citation_projection_module.has_range_identity
_is_sha256 = _citation_projection_module.is_sha256
_line_range = _citation_projection_module.line_range
_range_ref_from_citation_row = (
    _citation_projection_module.range_ref_from_citation_row
)
_range_ref_is_valid_for_citation_row = (
    _citation_projection_module.range_ref_is_valid_for_citation_row
)
_source_range_projection = _citation_projection_module.source_range_projection
_call_graph_error = _call_graph_validation.error
_call_graph_identity_error = _call_graph_validation.identity_error
_call_graph_parse_diagnostics = _call_graph_validation.parse_diagnostics
_call_graph_model_error = _call_graph_validation.model_error
_call_graph_records_error = _call_graph_validation.records_error
_call_graph_counts_error = _call_graph_validation.counts_error
_call_graph_manifest_binding_error = _call_graph_validation.manifest_binding_error
_call_record_is_valid = _call_graph_validation.call_record_is_valid
_SqliteArtifactValidationError = (
    _sqlite_artifact_read.SqliteArtifactValidationError
)
_sqlite_file_identity = _sqlite_artifact_read.sqlite_file_identity
_write_portable_sqlite_copy = _sqlite_artifact_read.write_portable_sqlite_copy
_verify_portable_sqlite_copy = _sqlite_artifact_read.verify_portable_sqlite_copy
_sqlite_integrity_contract = _sqlite_artifact_read.sqlite_integrity_contract
_open_sqlite_artifact = _sqlite_artifact_read.open_sqlite_artifact
_verify_sqlite_handle = _sqlite_artifact_read.verify_sqlite_handle
_require_current_sqlite_path = (
    _sqlite_artifact_read.require_current_sqlite_path
)

logger = logging.getLogger(__name__)


MAX_QUERY_EXISTING_INDEX_K = 100
MAX_SQLITE_ARTIFACT_BYTES = _sqlite_artifact_read.MAX_SQLITE_ARTIFACT_BYTES
_SQLITE_HASH_CHUNK_BYTES = _sqlite_artifact_read.SQLITE_HASH_CHUNK_BYTES
_FILE_DESCRIPTOR_ROOTS = (Path("/proc/self/fd"), Path("/dev/fd"))


def _query_path_for_descriptor(
    descriptor: int,
    expected_identity: tuple[int, int, int, int, int],
) -> Path:
    for root in _FILE_DESCRIPTOR_ROOTS:
        candidate = root / str(descriptor)
        try:
            observed_identity = _sqlite_file_identity(candidate.stat())
        except OSError:
            continue
        if observed_identity == expected_identity:
            return candidate
    raise _SqliteArtifactValidationError(
        "sqlite_index_descriptor_unavailable",
        "sqlite_index cannot be pinned to a verified file descriptor",
    )


@contextmanager
def _portable_verified_sqlite_copy(
    handle: BinaryIO,
    *,
    expected_bytes: int,
    expected_sha256: str,
    expected_identity: tuple[int, int, int, int, int],
) -> Iterator[Path]:
    try:
        temporary = tempfile.TemporaryDirectory(prefix="repoground-sqlite-")
    except OSError as exc:
        raise _SqliteArtifactValidationError(
            "sqlite_index_portable_copy_failed",
            f"sqlite_index private temporary directory could not be created: {exc}",
        ) from exc

    with temporary as directory:
        query_path = Path(directory) / "verified.index.sqlite"
        _write_portable_sqlite_copy(
            handle,
            query_path,
            expected_bytes=expected_bytes,
            expected_sha256=expected_sha256,
            expected_identity=expected_identity,
        )
        _verify_portable_sqlite_copy(
            query_path,
            expected_bytes=expected_bytes,
            expected_sha256=expected_sha256,
        )
        yield query_path
        _verify_portable_sqlite_copy(
            query_path,
            expected_bytes=expected_bytes,
            expected_sha256=expected_sha256,
        )


@contextmanager
def _verified_sqlite_query_path(
    manifest_path: Path,
    artifact: dict[str, Any],
) -> Iterator[Path]:
    from merger.repoground.retrieval.query_core import (
        validate_read_only_sqlite_source_path,
    )

    index_path = _safe_artifact_path(manifest_path.parent, artifact.get("path"))
    if index_path is None:
        raise _SqliteArtifactValidationError(
            "sqlite_index_path_invalid",
            "sqlite_index artifact path is invalid",
        )
    try:
        validate_read_only_sqlite_source_path(index_path)
    except ValueError as exc:
        raise _SqliteArtifactValidationError(
            "sqlite_index_path_invalid",
            str(exc),
        ) from exc

    handle = _open_sqlite_artifact(index_path)
    with handle:
        expected_bytes, expected_sha256 = _sqlite_integrity_contract(artifact)
        identity = _verify_sqlite_handle(
            handle,
            expected_bytes=expected_bytes,
            expected_sha256=expected_sha256,
        )
        _require_current_sqlite_path(index_path, identity)
        try:
            try:
                descriptor_path = _query_path_for_descriptor(
                    handle.fileno(),
                    identity,
                )
            except _SqliteArtifactValidationError as exc:
                if exc.error_code != "sqlite_index_descriptor_unavailable":
                    raise
                with _portable_verified_sqlite_copy(
                    handle,
                    expected_bytes=expected_bytes,
                    expected_sha256=expected_sha256,
                    expected_identity=identity,
                ) as portable_path:
                    yield portable_path
            else:
                yield descriptor_path
        finally:
            if _sqlite_file_identity(os.fstat(handle.fileno())) != identity:
                raise _SqliteArtifactValidationError(
                    "sqlite_index_integrity_mismatch",
                    "sqlite_index changed while it was queried",
                )


def _invalid_read_result(
    *,
    kind: str,
    bundle_manifest: Path,
    status: str,
    error: str,
    error_code: str,
    extra: dict[str, Any] | None = None,
    verbose: bool = True,
) -> dict[str, Any]:
    result = {
        "kind": kind,
        "version": "v1",
        "status": status,
        "bundle_manifest": str(bundle_manifest),
        "error": error,
        "error_code": error_code,
        "mutation_boundary": _read_only_mutation_boundary(),
        "does_not_establish": list(_DOES_NOT_ESTABLISH),
    }
    if extra:
        result.update(extra)
    return project_read_result(result, bundle_manifest, verbose=verbose)


def _range_error_code(exc: Exception) -> tuple[str, str]:
    if isinstance(exc, FileNotFoundError):
        return "missing", "missing_artifact"
    message = str(exc).lower()
    if "not found in manifest" in message or "not found" in message:
        return "missing", "missing_artifact"
    if "hash mismatch" in message or "content hash mismatch" in message:
        return "invalid", "content_hash_mismatch"
    if "schema" in message or "range_ref" in message or "artifact_role" in message:
        return "invalid", "range_ref_invalid"
    return "invalid", "range_resolution_failed"


def _resolve_sqlite_artifact(
    manifest_path: Path,
) -> tuple[dict[str, Any] | None, str | None, str | None]:
    manifest = _read_json_object(manifest_path)
    _payload, artifact, failure = _resolve_unique_artifact(
        manifest_path,
        manifest,
        "sqlite_index",
    )
    errors = {
        "missing": (
            "sqlite_index_missing",
            "sqlite_index artifact is not present in the bundle manifest",
        ),
        "role_ambiguous": (
            "sqlite_index_role_ambiguous",
            "bundle manifest contains multiple sqlite_index artifacts",
        ),
        "path_invalid": (
            "sqlite_index_path_invalid",
            "sqlite_index artifact path escapes the bundle root",
        ),
    }
    if failure is None:
        return artifact, None, None
    error_code, error = errors[failure]
    return artifact, error_code, error


def range_get(
    bundle_manifest: str | Path,
    range_ref: dict[str, Any],
    *,
    verbose: bool = True,
    compact: bool | None = None,
) -> dict[str, Any]:
    if compact is not None:
        verbose = not compact
    manifest_path = resolve_manifest_path(bundle_manifest)
    if not isinstance(range_ref, dict):
        return _invalid_read_result(
            kind="repobrief.range_get",
            bundle_manifest=manifest_path,
            status="invalid",
            error="range_ref must be a JSON object",
            error_code="range_ref_invalid",
            extra={"range_ref": range_ref, "range": None},
            verbose=verbose,
        )

    if range_ref.get("artifact_role") == "source_file":
        return _invalid_read_result(
            kind="repobrief.range_get",
            bundle_manifest=manifest_path,
            status="invalid",
            error=(
                "source_file range_refs are outside the read-only RepoGround "
                "bundle artifact boundary"
            ),
            error_code="source_file_outside_bundle_boundary",
            extra={"range_ref": range_ref, "range": None},
            verbose=verbose,
        )

    from merger.repoground.core.range_resolver import resolve_range_ref

    try:
        resolved = resolve_range_ref(manifest_path, range_ref)
    except Exception as exc:
        status, error_code = _range_error_code(exc)
        return _invalid_read_result(
            kind="repobrief.range_get",
            bundle_manifest=manifest_path,
            status=status,
            error=str(exc),
            error_code=error_code,
            extra={"range_ref": range_ref, "range": None},
            verbose=verbose,
        )

    return project_read_result(
        {
            "kind": "repobrief.range_get",
            "version": "v1",
            "status": "available",
            "bundle_manifest": str(manifest_path),
            "range_ref": range_ref,
            "range": resolved,
            "mutation_boundary": _read_only_mutation_boundary(),
            "does_not_establish": list(_DOES_NOT_ESTABLISH),
        },
        manifest_path,
        verbose=verbose,
    )


def _empty_citation_map_status(
    *,
    status: str,
    error_code: str | None,
    artifact_path: str | None,
    error: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": status,
        "error_code": error_code,
        "artifact_path": artifact_path,
        "row_count": 0,
        "invalid_row_count": 0,
    }
    if error is not None:
        result["error"] = error
    return result


def _load_citation_lookup(
    manifest_path: Path,
) -> tuple[dict[str, dict[str, Any]], dict[tuple[Any, ...], dict[str, Any]], dict[str, Any]]:
    source, artifact, failure, detail = _read_registered_artifact_source(
        manifest_path,
        CITATION_MAP_ROLE,
    )
    artifact_path_str = artifact.get("absolute_path") if isinstance(artifact, dict) else None
    if failure == "missing" and not artifact_path_str:
        return {}, {}, _empty_citation_map_status(
            status="missing",
            error_code="citation_map_jsonl_missing",
            artifact_path=None,
        )
    if failure == "file_missing":
        return {}, {}, _empty_citation_map_status(
            status="missing",
            error_code="citation_map_jsonl_file_missing",
            artifact_path=artifact_path_str,
        )
    failure_codes = {
        "manifest_too_large": "bundle_manifest_too_large",
        "manifest_invalid": "bundle_manifest_invalid",
        "role_ambiguous": "citation_map_jsonl_role_ambiguous",
        "path_invalid": "citation_map_jsonl_path_invalid",
        "integrity_unavailable": "citation_map_jsonl_integrity_unavailable",
        "too_large": "citation_map_jsonl_too_large",
        "bytes_mismatch": "citation_map_jsonl_bytes_mismatch",
        "sha256_mismatch": "citation_map_jsonl_sha256_mismatch",
        "source_changed": "citation_map_jsonl_source_changed_during_load",
        "unreadable": "citation_map_jsonl_unreadable",
    }
    if failure is not None:
        return {}, {}, _empty_citation_map_status(
            status="invalid",
            error_code=failure_codes.get(failure, "citation_map_jsonl_unreadable"),
            artifact_path=artifact_path_str,
            error=detail,
        )
    assert source is not None

    by_chunk_id: dict[str, dict[str, Any]] = {}
    by_range: dict[tuple[Any, ...], dict[str, Any]] = {}
    row_count = 0
    invalid_row_count = 0
    for line in source.raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError):
            invalid_row_count += 1
            continue
        if not isinstance(row, dict) or not _citation_row_is_valid(row):
            invalid_row_count += 1
            continue
        row_count += 1
        chunk_id = row.get("chunk_id")
        if isinstance(chunk_id, str) and chunk_id and chunk_id not in by_chunk_id:
            by_chunk_id[chunk_id] = row
        range_key = _citation_range_key(row.get("canonical_range"))
        if range_key is not None and range_key not in by_range:
            by_range[range_key] = row

    return by_chunk_id, by_range, {
        "status": "available",
        "error_code": None,
        "artifact_path": artifact_path_str,
        "row_count": row_count,
        "invalid_row_count": invalid_row_count,
    }


def _resolve_hit_evidence(
    manifest_path: Path,
    hit: dict[str, Any],
    by_chunk_id: dict[str, dict[str, Any]],
    by_range: dict[tuple[Any, ...], dict[str, Any]],
    citation_map_available: bool,
    *,
    availability_model: dict[str, Any] | None = None,
) -> dict[str, Any]:
    range_candidates: list[tuple[str, dict[str, Any]]] = []
    range_ref = hit.get("range_ref")
    if isinstance(range_ref, dict):
        range_candidates.append(("range_ref", range_ref))
    derived_range_ref = hit.get("derived_range_ref")
    if isinstance(derived_range_ref, dict):
        range_candidates.append(("derived_range_ref", derived_range_ref))

    selected_range_ref: dict[str, Any] | None = None
    range_ref_source = range_candidates[0][0] if range_candidates else None

    record: dict[str, Any] = {
        "chunk_id": hit.get("chunk_id"),
        "path": hit.get("path"),
        "range_ref_source": range_ref_source,
        "range_ref": None,
        "range_status": "unresolved",
        "range": None,
        "range_error": None,
        "range_error_code": None,
        "citation_status": "unmatched" if citation_map_available else "unavailable",
        "citation_id": None,
        "citation": None,
    }

    if not range_candidates:
        record["range_error_code"] = "range_ref_missing"
    else:
        for candidate_source, candidate_ref in range_candidates:
            range_result = range_get(manifest_path, candidate_ref)
            record["range_ref_source"] = candidate_source
            if range_result.get("status") == "available":
                selected_range_ref = candidate_ref
                record["range_ref"] = selected_range_ref
                record["range_status"] = "resolved"
                record["range"] = range_result.get("range")
                record["range_error"] = None
                record["range_error_code"] = None
                break
            record["range_error"] = range_result.get("error")
            record["range_error_code"] = range_result.get("error_code")

    if citation_map_available:
        row = None
        chunk_id = hit.get("chunk_id")
        if isinstance(chunk_id, str):
            row = by_chunk_id.get(chunk_id)
        range_key = _citation_range_key(selected_range_ref)
        if row is None and range_key is not None:
            row = by_range.get(range_key)
        if row is not None:
            record["citation_status"] = "resolved"
            record["citation_id"] = row.get("citation_id")
            record["citation"] = _citation_record(row)

    _enrich_resolved_hit_for_direct_use(record, availability_model=availability_model)
    return record


def _availability_model_for_manifest(manifest_path: Path) -> dict[str, Any]:
    from merger.repoground.core.availability import snapshot_availability_model

    manifest = _read_json_object(manifest_path)
    return snapshot_availability_model(manifest_path, manifest)


def _resolve_query_evidence(
    manifest_path: Path,
    query_result: Any,
    *,
    availability_model: dict[str, Any] | None = None,
) -> dict[str, Any]:
    hits = query_result.get("results") if isinstance(query_result, dict) else None
    hit_list = [hit for hit in (hits if isinstance(hits, list) else []) if isinstance(hit, dict)]
    if availability_model is None:
        availability_model = _availability_model_for_manifest(manifest_path)
    freshness = availability_model.get("freshness") if isinstance(availability_model, dict) else None
    if not hit_list:
        return {
            "kind": RESOLVED_EVIDENCE_KIND,
            "version": RESOLVED_EVIDENCE_VERSION,
            "availability": availability_model,
            "freshness": freshness,
            "citation_map": {
                "status": "skipped",
                "error_code": None,
                "artifact_path": None,
                "row_count": 0,
                "invalid_row_count": 0,
                "reason": "no_hits",
            },
            "hit_count": 0,
            "hits": [],
            "does_not_establish": list(_DOES_NOT_ESTABLISH),
        }

    by_chunk_id, by_range, citation_map_status = _load_citation_lookup(manifest_path)
    citation_map_available = citation_map_status["status"] == "available"
    resolved_hits = [
        _resolve_hit_evidence(
            manifest_path,
            hit,
            by_chunk_id,
            by_range,
            citation_map_available,
            availability_model=availability_model,
        )
        for hit in hit_list
    ]
    return {
        "kind": RESOLVED_EVIDENCE_KIND,
        "version": RESOLVED_EVIDENCE_VERSION,
        "availability": availability_model,
        "freshness": freshness,
        "citation_map": citation_map_status,
        "hit_count": len(resolved_hits),
        "hits": resolved_hits,
        "does_not_establish": list(_DOES_NOT_ESTABLISH),
    }


def query_existing_index(
    bundle_manifest: str | Path,
    query: str,
    k: int = 10,
    filters: dict[str, str | None] | None = None,
    resolve_evidence: bool = False,
    project_sources: bool = False,
    prepared_fts_query: str | None = None,
    *,
    verbose: bool = True,
    compact: bool | None = None,
) -> dict[str, Any]:
    if compact is not None:
        verbose = not compact
    manifest_path = resolve_manifest_path(bundle_manifest)
    if not isinstance(query, str):
        return _invalid_read_result(
            kind="repobrief.query_existing_index",
            bundle_manifest=manifest_path,
            status="invalid",
            error="query must be a string",
            error_code="query_invalid",
            extra={"query": query, "k": k, "query_result": None, "index_artifact": None},
            verbose=verbose,
        )
    if not isinstance(k, int) or isinstance(k, bool) or k < 1 or k > MAX_QUERY_EXISTING_INDEX_K:
        return _invalid_read_result(
            kind="repobrief.query_existing_index",
            bundle_manifest=manifest_path,
            status="invalid",
            error=f"k must be an integer between 1 and {MAX_QUERY_EXISTING_INDEX_K}",
            error_code="k_out_of_bounds",
            extra={"query": query, "k": k, "query_result": None, "index_artifact": None},
            verbose=verbose,
        )
    if not isinstance(resolve_evidence, bool):
        return _invalid_read_result(
            kind="repobrief.query_existing_index",
            bundle_manifest=manifest_path,
            status="invalid",
            error="resolve_evidence must be a boolean",
            error_code="resolve_evidence_invalid",
            extra={"query": query, "k": k, "query_result": None, "index_artifact": None},
            verbose=verbose,
        )

    if not isinstance(project_sources, bool):
        return _invalid_read_result(
            kind="repobrief.query_existing_index",
            bundle_manifest=manifest_path,
            status="invalid",
            error="project_sources must be a boolean",
            error_code="project_sources_invalid",
            extra={"query": query, "k": k, "query_result": None, "index_artifact": None},
            verbose=verbose,
        )

    artifact, artifact_error_code, artifact_error = _resolve_sqlite_artifact(
        manifest_path
    )
    if artifact_error_code is not None:
        return _invalid_read_result(
            kind="repobrief.query_existing_index",
            bundle_manifest=manifest_path,
            status=(
                "missing"
                if artifact_error_code == "sqlite_index_missing"
                else "invalid"
            ),
            error=artifact_error or "sqlite_index artifact cannot be resolved",
            error_code=artifact_error_code,
            extra={"query": query, "k": k, "query_result": None, "index_artifact": artifact},
            verbose=verbose,
        )
    assert artifact is not None

    index_path = Path(str(artifact["absolute_path"]))

    from merger.repoground.retrieval.query_core import execute_query

    try:
        with _verified_sqlite_query_path(manifest_path, artifact) as query_path:
            validated_source_path = (
                index_path
                if query_path.parent in _FILE_DESCRIPTOR_ROOTS
                and query_path.name.isdecimal()
                else None
            )
            query_result = execute_query(
                query_path,
                query,
                k=k,
                filters=filters or {},
                trace=False,
                build_context=False,
                read_only=True,
                _prepared_fts_query=prepared_fts_query,
                _validated_read_only_source_path=validated_source_path,
            )
    except _SqliteArtifactValidationError as exc:
        status = (
            "missing" if exc.error_code == "sqlite_index_file_missing" else "invalid"
        )
        return _invalid_read_result(
            kind="repobrief.query_existing_index",
            bundle_manifest=manifest_path,
            status=status,
            error=str(exc),
            error_code=exc.error_code,
            extra={
                "query": query,
                "k": k,
                "query_result": None,
                "index_artifact": artifact,
            },
            verbose=verbose,
        )
    except Exception as exc:
        return _invalid_read_result(
            kind="repobrief.query_existing_index",
            bundle_manifest=manifest_path,
            status="invalid",
            error=str(exc),
            error_code="query_execution_failed",
            extra={"query": query, "k": k, "query_result": None, "index_artifact": artifact},
            verbose=verbose,
        )

    availability_model = _availability_model_for_manifest(manifest_path)
    freshness = availability_model.get("freshness") if isinstance(availability_model, dict) else None
    resolved_evidence = (
        _resolve_query_evidence(
            manifest_path,
            query_result,
            availability_model=availability_model,
        )
        if (resolve_evidence or project_sources)
        else None
    )
    source_citation_projection = (
        _project_source_citations(resolved_evidence) if project_sources else None
    )

    return project_read_result(
        {
            "kind": "repobrief.query_existing_index",
            "version": "v1",
            "status": "available",
            "bundle_manifest": str(manifest_path),
            "query": query,
            "k": k,
            "filters": filters or {},
            "resolve_evidence": resolve_evidence,
            "project_sources": project_sources,
            "index_artifact": artifact,
            "availability": availability_model,
            "freshness": freshness,
            "query_result": query_result,
            "evidence_resolution_used": resolve_evidence or project_sources,
            "resolved_evidence": resolved_evidence if resolve_evidence else None,
            "source_citation_projection": source_citation_projection,
            "mutation_boundary": _read_only_mutation_boundary(),
            "does_not_establish": list(_DOES_NOT_ESTABLISH),
        },
        manifest_path,
        verbose=verbose,
    )


SYMBOL_INDEX_ROLE = "python_symbol_index_json"
SYMBOL_SEARCH_KIND = "repobrief.symbol_search"
MAX_SYMBOL_SEARCH_K = 200

_SYMBOL_SOURCE_ERRORS = {
    "missing": (
        "missing",
        "python_symbol_index_json_missing",
        "python_symbol_index_json artifact is not present in the bundle manifest",
    ),
    "file_missing": (
        "missing",
        "python_symbol_index_json_file_missing",
        "python_symbol_index_json artifact file does not exist",
    ),
    "role_ambiguous": (
        "invalid",
        "python_symbol_index_json_role_ambiguous",
        "bundle manifest contains multiple python_symbol_index_json artifacts",
    ),
    "path_invalid": (
        "invalid",
        "python_symbol_index_json_path_invalid",
        "python_symbol_index_json artifact path escapes the bundle root",
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
        "python_symbol_index_json_integrity_unavailable",
        (
            "python_symbol_index_json requires valid bytes and sha256 metadata "
            "in the bundle manifest"
        ),
    ),
    "too_large": (
        "invalid",
        "python_symbol_index_json_too_large",
        "python_symbol_index_json exceeds the bounded read limit",
    ),
    "bytes_mismatch": (
        "invalid",
        "python_symbol_index_json_bytes_mismatch",
        "python_symbol_index_json byte count does not match the bundle manifest",
    ),
    "sha256_mismatch": (
        "invalid",
        "python_symbol_index_json_sha256_mismatch",
        "python_symbol_index_json content hash does not match the bundle manifest",
    ),
    "source_changed": (
        "invalid",
        "python_symbol_index_source_changed_during_load",
        (
            "python_symbol_index_json source changed while navigation state "
            "was loading"
        ),
    ),
    "unreadable": (
        "invalid",
        "python_symbol_index_json_unreadable",
        "python_symbol_index_json could not be read",
    ),
}


def _registered_source_error(
    failure: str | None,
    detail: str | None,
    errors: dict[str, tuple[str, str, str]],
) -> dict[str, Any] | None:
    if failure is None:
        return None
    status, error_code, error = errors.get(failure, errors["unreadable"])
    return {
        "status": status,
        "error_code": error_code,
        "error": detail or error,
    }


def _symbol_source_range(symbol: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": symbol.get("path"),
        "start_line": symbol.get("start_line"),
        "end_line": symbol.get("end_line"),
        "range_ref": symbol.get("range_ref"),
        "coordinate_basis": "source_lines",
    }


def _symbol_record(symbol: dict[str, Any]) -> dict[str, Any]:
    decorators = symbol.get("decorators")
    return {
        "id": symbol.get("id"),
        "kind": symbol.get("kind"),
        "name": symbol.get("name"),
        "qualified_name": symbol.get("qualified_name"),
        "module": symbol.get("module"),
        "path": symbol.get("path"),
        "start_line": symbol.get("start_line"),
        "end_line": symbol.get("end_line"),
        "range_ref": symbol.get("range_ref"),
        "source_range": _symbol_source_range(symbol),
        "decorators": list(decorators) if isinstance(decorators, list) else [],
    }


def _load_symbol_index_source(
    manifest_path: Path,
) -> tuple[
    dict[str, Any] | None,
    dict[str, Any] | None,
    _LoadedArtifactSource | None,
    dict[str, Any] | None,
]:
    source, artifact, failure, detail = _read_registered_artifact_source(
        manifest_path, SYMBOL_INDEX_ROLE
    )
    source_error = _registered_source_error(
        failure,
        detail,
        _SYMBOL_SOURCE_ERRORS,
    )
    if source_error is not None:
        return None, artifact, None, source_error
    assert source is not None
    try:
        data = json.loads(source.raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, artifact, None, {
            "status": "invalid",
            "error_code": "python_symbol_index_json_unreadable",
            "error": str(exc),
        }
    if not isinstance(data, dict) or data.get("kind") != "lenskit.python_symbol_index":
        return None, artifact, None, {
            "status": "invalid",
            "error_code": "python_symbol_index_json_invalid_kind",
            "error": "python_symbol_index_json must be a lenskit.python_symbol_index object",
        }
    symbols = data.get("symbols")
    if not isinstance(symbols, list):
        return None, artifact, None, {
            "status": "invalid",
            "error_code": "python_symbol_index_symbols_invalid",
            "error": "python_symbol_index_json symbols must be an array",
        }
    return data, artifact, source, None


def _load_symbol_index(
    manifest_path: Path,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None]:
    data, artifact, _source, error = _load_symbol_index_source(manifest_path)
    return data, artifact, error


def search_symbol_index(
    bundle_manifest: str | Path,
    query: str = "",
    *,
    k: int = 25,
    kind: str | None = None,
    path: str | None = None,
    verbose: bool = True,
    compact: bool | None = None,
) -> dict[str, Any]:
    """Symbol lookup with the historical full contract by default.

    Pass ``compact=True`` (or ``verbose=False``) for the bounded agent projection.
    """
    if compact is not None:
        verbose = not compact
    manifest_path = resolve_manifest_path(bundle_manifest)
    return project_read_result(
        _search_symbol_index_full(manifest_path, query, k=k, kind=kind, path=path),
        manifest_path,
        verbose=verbose,
    )


def _search_symbol_index_full(
    manifest_path: Path,
    query: str = "",
    *,
    k: int = 25,
    kind: str | None = None,
    path: str | None = None,
) -> dict[str, Any]:
    if not isinstance(query, str):
        return _invalid_read_result(
            kind=SYMBOL_SEARCH_KIND,
            bundle_manifest=manifest_path,
            status="invalid",
            error="query must be a string",
            error_code="query_invalid",
            extra={"query": query, "k": k, "symbol_index": None, "hits": []},
        )
    if not isinstance(k, int) or isinstance(k, bool) or k < 1 or k > MAX_SYMBOL_SEARCH_K:
        return _invalid_read_result(
            kind=SYMBOL_SEARCH_KIND,
            bundle_manifest=manifest_path,
            status="invalid",
            error=f"k must be an integer between 1 and {MAX_SYMBOL_SEARCH_K}",
            error_code="k_out_of_bounds",
            extra={"query": query, "k": k, "symbol_index": None, "hits": []},
        )
    data, artifact, error = _load_symbol_index(manifest_path)
    if error is not None:
        return _invalid_read_result(
            kind=SYMBOL_SEARCH_KIND,
            bundle_manifest=manifest_path,
            status=error["status"],
            error=error["error"],
            error_code=error["error_code"],
            extra={"query": query, "k": k, "symbol_index": artifact, "hits": []},
        )
    assert data is not None
    symbols = [item for item in data.get("symbols", []) if isinstance(item, dict)]
    q = query.strip().casefold()
    kind_filter = kind.strip() if isinstance(kind, str) and kind.strip() else None
    path_filter = path.strip().casefold() if isinstance(path, str) and path.strip() else None
    matched: list[tuple[int, int, dict[str, Any]]] = []
    omitted_by_filter = 0
    for position, symbol in enumerate(symbols):
        haystack = " ".join(
            str(symbol.get(field, ""))
            for field in ("name", "qualified_name", "module", "path", "kind")
        ).casefold()
        if q and q not in haystack:
            omitted_by_filter += 1
            continue
        if kind_filter and symbol.get("kind") != kind_filter:
            omitted_by_filter += 1
            continue
        if path_filter and path_filter not in str(symbol.get("path", "")).casefold():
            omitted_by_filter += 1
            continue
        # Rank exact name/qualified_name matches before substring matches so a
        # definition lookup surfaces the symbol itself first. Ties keep index
        # order (stable), preserving prior behavior when no exact match exists.
        exact = 0 if q and (
            str(symbol.get("name", "")).casefold() == q
            or str(symbol.get("qualified_name", "")).casefold() == q
        ) else 1
        matched.append((exact, position, symbol))
    matched.sort(key=lambda item: (item[0], item[1]))
    # Build the (heavier) records only for the k rows that are actually returned.
    hits = [_symbol_record(symbol) for _, _, symbol in matched[:k]]
    availability = _availability_model_for_manifest(manifest_path)
    return {
        "kind": SYMBOL_SEARCH_KIND,
        "version": "v1",
        "status": "available",
        "bundle_manifest": str(manifest_path),
        "query": query,
        "k": k,
        "filters": {"kind": kind, "path": path},
        "symbol_index": artifact,
        "symbol_index_metadata": {
            "language": data.get("language"),
            "symbol_kinds": data.get("symbol_kinds"),
            "skipped_files_count": data.get("skipped_files_count"),
            "skipped_errors": data.get("skipped_errors"),
            "canonical_dump_index_sha256": data.get("canonical_dump_index_sha256"),
        },
        "availability": availability,
        "freshness": availability.get("freshness") if isinstance(availability, dict) else None,
        "hit_count": len(hits),
        "omitted_by_filter_count": omitted_by_filter,
        "truncated": len(matched) > k,
        "hits": hits,
        "mutation_boundary": _read_only_mutation_boundary(),
        "does_not_establish": list(_DOES_NOT_ESTABLISH) + [
            "call_graph_completeness",
            "dependency_completeness",
            "import_success",
            "review_impact",
            "merge_readiness",
        ],
    }


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
_CALL_NAVIGATION_CACHE_VALIDATION_ENV = "REPOGROUND_CACHE_VALIDATION"
_CALL_NAVIGATION_STRICT_SOURCE_HASH_ENV = "REPOGROUND_STRICT_CACHE_HASH"


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
_WARNED_INVALID_CACHE_VALIDATION_VALUES: set[str] = set()


def _clear_call_navigation_caches() -> None:
    """Clear process-local derived state; intended for bounded tests and diagnostics."""
    with _CALL_NAVIGATION_CACHE_LOCK:
        _CALL_NAVIGATION_CACHE.clear()
        _SYMBOL_NAVIGATION_CACHE.clear()


def _stat_identity_is_strong(stat_result: os.stat_result) -> bool:
    return all(
        value != 0
        for value in (
            stat_result.st_dev,
            stat_result.st_ino,
            stat_result.st_mtime_ns,
            stat_result.st_ctime_ns,
        )
    )


def _stat_matches_identity(
    stat_result: os.stat_result,
    *,
    device: int,
    inode: int,
    size: int,
    mtime_ns: int,
    ctime_ns: int,
) -> bool:
    def available(expected: int, observed: int) -> bool:
        return expected == 0 or observed == expected

    return (
        available(device, stat_result.st_dev)
        and available(inode, stat_result.st_ino)
        and stat_result.st_size == size
        and available(mtime_ns, stat_result.st_mtime_ns)
        and available(ctime_ns, stat_result.st_ctime_ns)
    )


def _manifest_stat_matches_fingerprint(
    fingerprint: _ArtifactSourceFingerprint,
    stat_result: os.stat_result,
) -> bool:
    return _stat_matches_identity(
        stat_result,
        device=fingerprint.manifest_device,
        inode=fingerprint.manifest_inode,
        size=fingerprint.manifest_size,
        mtime_ns=fingerprint.manifest_mtime_ns,
        ctime_ns=fingerprint.manifest_ctime_ns,
    )


def _artifact_stat_matches_fingerprint(
    fingerprint: _ArtifactSourceFingerprint,
    stat_result: os.stat_result,
) -> bool:
    return _stat_matches_identity(
        stat_result,
        device=fingerprint.device,
        inode=fingerprint.inode,
        size=fingerprint.size,
        mtime_ns=fingerprint.mtime_ns,
        ctime_ns=fingerprint.ctime_ns,
    )


def _fingerprint_matches_active_manifest_snapshot(
    fingerprint: _ArtifactSourceFingerprint,
) -> bool | None:
    snapshot = active_manifest_snapshot(fingerprint.manifest_path)
    if snapshot is None:
        return None
    return fingerprint.manifest_sha256 == snapshot.binding.sha256


def _manifest_source_is_current(
    fingerprint: _ArtifactSourceFingerprint,
) -> bool:
    active_match = _fingerprint_matches_active_manifest_snapshot(fingerprint)
    if active_match is not None:
        return active_match
    raw, current, failure, _detail = _read_stable_regular_file_bytes(
        Path(fingerprint.manifest_path)
    )
    if failure is not None or raw is None or current is None:
        return False
    return (
        _manifest_stat_matches_fingerprint(fingerprint, current)
        and hashlib.sha256(raw).hexdigest() == fingerprint.manifest_sha256
    )


def _artifact_bytes_match_fingerprint(
    fingerprint: _ArtifactSourceFingerprint,
    artifact_path: Path,
) -> bool:
    artifact_bytes, artifact_stat, failure, _detail = _read_stable_artifact_bytes(
        artifact_path
    )
    if failure is not None or artifact_bytes is None or artifact_stat is None:
        return False
    if not _artifact_stat_matches_fingerprint(fingerprint, artifact_stat):
        return False
    if hashlib.sha256(artifact_bytes).hexdigest() != fingerprint.artifact_sha256:
        return False
    try:
        artifact_after_stat = artifact_path.stat()
    except OSError:
        return False
    return _artifact_stat_matches_fingerprint(
        fingerprint,
        artifact_after_stat,
    )


def _bound_artifact_source_is_current(
    fingerprint: _ArtifactSourceFingerprint,
    artifact_path: Path,
    *,
    requires_content: bool,
) -> bool:
    if not requires_content:
        try:
            artifact_stat = artifact_path.stat()
        except OSError:
            return False
        if _stat_identity_is_strong(artifact_stat):
            return _artifact_stat_matches_fingerprint(
                fingerprint,
                artifact_stat,
            )
    return _artifact_bytes_match_fingerprint(fingerprint, artifact_path)


def _fast_artifact_source_validation(
    fingerprint: _ArtifactSourceFingerprint,
    manifest_path: Path,
    artifact_path: Path,
) -> bool | None:
    try:
        manifest_stat = manifest_path.stat()
        artifact_stat = artifact_path.stat()
    except OSError:
        return False
    if not (
        _stat_identity_is_strong(manifest_stat)
        and _stat_identity_is_strong(artifact_stat)
    ):
        return None
    return _manifest_stat_matches_fingerprint(
        fingerprint,
        manifest_stat,
    ) and _artifact_stat_matches_fingerprint(fingerprint, artifact_stat)


def _source_bytes_match_fingerprint(
    fingerprint: _ArtifactSourceFingerprint,
    manifest_path: Path,
    artifact_path: Path,
) -> bool:
    manifest_bytes, manifest_stat, manifest_failure, _manifest_detail = (
        _read_stable_regular_file_bytes(manifest_path)
    )
    if (
        manifest_failure is not None
        or manifest_bytes is None
        or manifest_stat is None
        or not _manifest_stat_matches_fingerprint(fingerprint, manifest_stat)
        or hashlib.sha256(manifest_bytes).hexdigest() != fingerprint.manifest_sha256
    ):
        return False
    if not _artifact_bytes_match_fingerprint(fingerprint, artifact_path):
        return False
    try:
        manifest_after_stat = manifest_path.stat()
    except OSError:
        return False
    return _manifest_stat_matches_fingerprint(
        fingerprint,
        manifest_after_stat,
    )


def _cache_validation_mode() -> str:
    """Return the cache-validation mode while preserving legacy semantics.

    ``REPOGROUND_CACHE_VALIDATION`` accepts only ``auto`` and ``strict``.
    Any other non-empty value falls back to ``strict`` and is logged once per
    distinct invalid value. The legacy
    ``REPOGROUND_STRICT_CACHE_HASH`` switch remains supported when the
    new variable is unset or empty: unset/empty/0/false/no/off means ``auto``;
    every other non-empty legacy value means ``strict``.
    """
    configured_raw = os.environ.get(_CALL_NAVIGATION_CACHE_VALIDATION_ENV, "")
    configured = configured_raw.strip().lower()
    if configured in {"auto", "strict"}:
        return configured
    if configured:
        with _CALL_NAVIGATION_CACHE_LOCK:
            if configured_raw not in _WARNED_INVALID_CACHE_VALIDATION_VALUES:
                _WARNED_INVALID_CACHE_VALIDATION_VALUES.add(configured_raw)
                logger.warning(
                    "Invalid %s value %r; falling back to strict cache validation",
                    _CALL_NAVIGATION_CACHE_VALIDATION_ENV,
                    configured_raw,
                )
        return "strict"

    legacy = os.environ.get(
        _CALL_NAVIGATION_STRICT_SOURCE_HASH_ENV, ""
    ).strip().lower()
    if legacy in {"", "0", "false", "no", "off"}:
        return "auto"
    return "strict"


def _source_identity_is_strong(
    fingerprint: _ArtifactSourceFingerprint,
) -> bool:
    """Whether metadata can support the fast warm-cache validation path."""
    return all(
        value != 0
        for value in (
            fingerprint.manifest_device,
            fingerprint.manifest_inode,
            fingerprint.manifest_mtime_ns,
            fingerprint.manifest_ctime_ns,
            fingerprint.device,
            fingerprint.inode,
            fingerprint.mtime_ns,
            fingerprint.ctime_ns,
        )
    )


def _source_content_verification_required(
    fingerprint: _ArtifactSourceFingerprint,
    *,
    verify_content: bool,
) -> bool:
    return (
        verify_content
        or _cache_validation_mode() == "strict"
        or not _source_identity_is_strong(fingerprint)
    )


def _read_stable_artifact_bytes(
    artifact_path: Path,
) -> tuple[bytes | None, os.stat_result | None, str | None, str | None]:
    return read_stable_regular_file_bytes(
        artifact_path,
        max_bytes=MAX_REGISTERED_ARTIFACT_BYTES,
    )


def _read_stable_regular_file_bytes(
    path: Path,
    *,
    max_bytes: int = MAX_MANIFEST_BYTES,
) -> tuple[bytes | None, os.stat_result | None, str | None, str | None]:
    return read_stable_regular_file_bytes(path, max_bytes=max_bytes)


def _read_artifact_manifest_source(
    manifest_path: Path,
) -> tuple[
    bytes | None,
    Any,
    tuple[int, int, int, int, int] | None,
    str | None,
    str | None,
]:
    snapshot = active_manifest_snapshot(manifest_path)
    if snapshot is not None:
        identity = snapshot.file_identity
        return (
            snapshot.raw,
            snapshot.json_object(),
            (identity[0], identity[1], identity[3], identity[4], identity[5]),
            None,
            None,
        )
    raw, manifest_stat, failure, detail = _read_stable_regular_file_bytes(
        manifest_path
    )
    if failure == "too_large":
        failure = "manifest_too_large"
    if failure is not None:
        return None, None, None, failure, detail
    assert raw is not None and manifest_stat is not None
    try:
        manifest = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, None, None, "unreadable", str(exc)
    if (
        not is_bundle_manifest(manifest)
        or not _is_non_empty_string(manifest.get("run_id"))
        or not isinstance(manifest.get("artifacts"), list)
    ):
        return (
            None,
            None,
            None,
            "manifest_invalid",
            "bundle manifest identity, run_id, or artifacts are invalid",
        )
    return raw, manifest, _file_identity(manifest_stat), None, None


def _read_registered_artifact_source(
    manifest_path: Path, role: str
) -> tuple[
    _LoadedArtifactSource | None,
    dict[str, Any] | None,
    str | None,
    str | None,
]:
    manifest_bytes, manifest, manifest_identity, failure, detail = (
        _read_artifact_manifest_source(manifest_path)
    )
    if failure is not None:
        return None, None, failure, detail
    assert manifest_bytes is not None and manifest_identity is not None
    if not isinstance(manifest, dict):
        return None, None, "unreadable", "bundle manifest must be a JSON object"
    try:
        artifact_payload, artifact, resolution_failure = _resolve_unique_artifact(
            manifest_path,
            manifest,
            role,
        )
    except ValueError as exc:
        return None, None, "unreadable", str(exc)
    if resolution_failure is not None:
        return None, artifact, resolution_failure, None
    assert artifact_payload is not None and artifact is not None
    artifact_path = Path(artifact["absolute_path"])
    declared_bytes, declared_sha256, integrity_failure = (
        declared_artifact_integrity(artifact_payload)
    )
    if integrity_failure is not None:
        return None, artifact, integrity_failure, None
    raw, artifact_stat, failure, detail = _read_stable_artifact_bytes(artifact_path)
    if failure is not None:
        return None, artifact, failure, detail
    assert raw is not None and artifact_stat is not None
    if declared_bytes is not None and declared_bytes != len(raw):
        return None, artifact, "bytes_mismatch", None
    actual_sha256 = hashlib.sha256(raw).hexdigest()
    if declared_sha256 is not None and actual_sha256 != declared_sha256:
        return None, artifact, "sha256_mismatch", None
    fingerprint = _ArtifactSourceFingerprint(
        manifest_path=str(resolve_manifest_path(manifest_path)),
        manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
        manifest_device=manifest_identity[0],
        manifest_inode=manifest_identity[1],
        manifest_size=manifest_identity[2],
        manifest_mtime_ns=manifest_identity[3],
        manifest_ctime_ns=manifest_identity[4],
        role=role,
        absolute_path=str(artifact_path),
        artifact_sha256=actual_sha256,
        device=artifact_stat.st_dev,
        inode=artifact_stat.st_ino,
        size=artifact_stat.st_size,
        mtime_ns=artifact_stat.st_mtime_ns,
        ctime_ns=artifact_stat.st_ctime_ns,
    )
    if not _manifest_source_is_current(fingerprint):
        return None, artifact, "source_changed", None
    return (
        _LoadedArtifactSource(
            manifest=manifest,
            artifact=artifact,
            raw=raw,
            fingerprint=fingerprint,
        ),
        artifact,
        None,
        None,
    )


def _artifact_source_is_current(
    fingerprint: _ArtifactSourceFingerprint,
    *,
    verify_content: bool = False,
) -> bool:
    """Validate one cached generation without reparsing its JSON payload.

    Cold loads and post-build checks always hash bytes read from one pinned file
    descriptor. Request-bound lookups authorize the cached manifest hash only
    from the active snapshot and never from transient path bytes. Other warm
    lookups use the manifest hash plus strong file identity metadata.
    ``REPOGROUND_CACHE_VALIDATION=strict`` forces a full hash on every lookup;
    the legacy strict-hash switch remains supported. Weak identities such as
    zero device or inode values automatically use strict validation.
    """
    manifest_path = Path(fingerprint.manifest_path)
    artifact_path = Path(fingerprint.absolute_path)
    active_manifest_match = _fingerprint_matches_active_manifest_snapshot(fingerprint)
    if active_manifest_match is False:
        return False

    requires_content = _source_content_verification_required(
        fingerprint,
        verify_content=verify_content,
    )
    if active_manifest_match is True:
        return _bound_artifact_source_is_current(
            fingerprint,
            artifact_path,
            requires_content=requires_content,
        )

    if not requires_content:
        fast_validation = _fast_artifact_source_validation(
            fingerprint,
            manifest_path,
            artifact_path,
        )
        if fast_validation is not None:
            return fast_validation
    return _source_bytes_match_fingerprint(
        fingerprint,
        manifest_path,
        artifact_path,
    )

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
