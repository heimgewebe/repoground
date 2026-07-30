from __future__ import annotations

import json
import logging
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, BinaryIO, Iterator

from merger.repoground.core import call_graph_validation as _call_graph_validation
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
    project_source_citations as _project_source_citations,
)
from merger.repoground.core.manifest_snapshot import (
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


from merger.repoground.core import artifact_source_access as _artifact_source_access

_stat_identity_is_strong = _artifact_source_access._stat_identity_is_strong
_stat_matches_identity = _artifact_source_access._stat_matches_identity
_manifest_stat_matches_fingerprint = (
    _artifact_source_access._manifest_stat_matches_fingerprint
)
_artifact_stat_matches_fingerprint = (
    _artifact_source_access._artifact_stat_matches_fingerprint
)
_fingerprint_matches_active_manifest_snapshot = (
    _artifact_source_access._fingerprint_matches_active_manifest_snapshot
)
_manifest_source_is_current = _artifact_source_access._manifest_source_is_current
_artifact_bytes_match_fingerprint = (
    _artifact_source_access._artifact_bytes_match_fingerprint
)
_bound_artifact_source_is_current = (
    _artifact_source_access._bound_artifact_source_is_current
)
_fast_artifact_source_validation = (
    _artifact_source_access._fast_artifact_source_validation
)
_source_bytes_match_fingerprint = (
    _artifact_source_access._source_bytes_match_fingerprint
)
_cache_validation_mode = _artifact_source_access._cache_validation_mode
_source_identity_is_strong = _artifact_source_access._source_identity_is_strong
_source_content_verification_required = (
    _artifact_source_access._source_content_verification_required
)
_read_stable_artifact_bytes = _artifact_source_access._read_stable_artifact_bytes
_read_stable_regular_file_bytes = (
    _artifact_source_access._read_stable_regular_file_bytes
)
_read_artifact_manifest_source = _artifact_source_access._read_artifact_manifest_source
_read_registered_artifact_source = (
    _artifact_source_access._read_registered_artifact_source
)
_artifact_source_is_current = _artifact_source_access._artifact_source_is_current





from merger.repoground.core import query_index_access as _query_index_access

MAX_QUERY_EXISTING_INDEX_K = _query_index_access.MAX_QUERY_EXISTING_INDEX_K
query_existing_index = _query_index_access.query_existing_index
_empty_citation_map_status = _query_index_access._empty_citation_map_status
_load_citation_lookup = _query_index_access._load_citation_lookup
_resolve_hit_evidence = _query_index_access._resolve_hit_evidence
_availability_model_for_manifest = _query_index_access._availability_model_for_manifest
_resolve_query_evidence = _query_index_access._resolve_query_evidence

from merger.repoground.core import symbol_index_access as _symbol_index_access

SYMBOL_INDEX_ROLE = _symbol_index_access.SYMBOL_INDEX_ROLE
SYMBOL_SEARCH_KIND = _symbol_index_access.SYMBOL_SEARCH_KIND
MAX_SYMBOL_SEARCH_K = _symbol_index_access.MAX_SYMBOL_SEARCH_K
_registered_source_error = _symbol_index_access._registered_source_error
_symbol_source_range = _symbol_index_access._symbol_source_range
_symbol_record = _symbol_index_access._symbol_record
_load_symbol_index_source = _symbol_index_access._load_symbol_index_source
_load_symbol_index = _symbol_index_access._load_symbol_index
search_symbol_index = _symbol_index_access.search_symbol_index
_search_symbol_index_full = _symbol_index_access._search_symbol_index_full

from merger.repoground.core import call_graph_navigation as _call_graph_navigation

CALL_GRAPH_ROLE = _call_graph_navigation.CALL_GRAPH_ROLE
CALL_GRAPH_KIND = _call_graph_navigation.CALL_GRAPH_KIND
CALL_GRAPH_VERSION = _call_graph_navigation.CALL_GRAPH_VERSION
CALL_REFERENCES_KIND = _call_graph_navigation.CALL_REFERENCES_KIND
CALL_CALLERS_KIND = _call_graph_navigation.CALL_CALLERS_KIND
CALL_CALLEES_KIND = _call_graph_navigation.CALL_CALLEES_KIND
MAX_CALL_SEARCH_K = _call_graph_navigation.MAX_CALL_SEARCH_K
CALL_RESOLUTION_STATUSES = _call_graph_navigation.CALL_RESOLUTION_STATUSES
CALL_EVIDENCE_LEVELS = _call_graph_navigation.CALL_EVIDENCE_LEVELS
CALL_RELATION_TYPES = _call_graph_navigation.CALL_RELATION_TYPES
_clear_call_navigation_caches = _call_graph_navigation._clear_call_navigation_caches
find_references = _call_graph_navigation.find_references
get_callers = _call_graph_navigation.get_callers
get_callees = _call_graph_navigation.get_callees
_call_record_is_valid = _call_graph_navigation._call_record_is_valid
_call_graph_identity_error = _call_graph_navigation._call_graph_identity_error
_call_graph_model_error = _call_graph_navigation._call_graph_model_error
_call_graph_manifest_binding_error = (
    _call_graph_navigation._call_graph_manifest_binding_error
)
_cache_validation_mode = _call_graph_navigation._cache_validation_mode
_artifact_source_is_current = _call_graph_navigation._artifact_source_is_current
_read_registered_artifact_source = (
    _call_graph_navigation._read_registered_artifact_source
)
_read_stable_artifact_bytes = _artifact_source_access._read_stable_artifact_bytes
_read_stable_regular_file_bytes = (
    _artifact_source_access._read_stable_regular_file_bytes
)

_load_call_graph_source = _call_graph_navigation._load_call_graph_source
_CALL_NAVIGATION_CACHE = _call_graph_navigation._CALL_NAVIGATION_CACHE
_SYMBOL_NAVIGATION_CACHE = _call_graph_navigation._SYMBOL_NAVIGATION_CACHE
_CALL_NAVIGATION_CACHE_MAX_ENTRIES = (
    _call_graph_navigation._CALL_NAVIGATION_CACHE_MAX_ENTRIES
)
_find_references_full = _call_graph_navigation._find_references_full
_get_callers_full = _call_graph_navigation._get_callers_full
_get_callees_full = _call_graph_navigation._get_callees_full

_CALL_GRAPH_REQUIRED_NONCLAIMS = _call_graph_navigation._CALL_GRAPH_REQUIRED_NONCLAIMS
_CALL_GRAPH_DOES_NOT_ESTABLISH = _call_graph_navigation._CALL_GRAPH_DOES_NOT_ESTABLISH
_CALL_NAV_DOES_NOT_ESTABLISH = _call_graph_navigation._CALL_NAV_DOES_NOT_ESTABLISH

