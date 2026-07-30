"""Existing-index query and citation-map evidence resolution.

Extracted from bundle_access as a T011 residual slice so SQLite query + citation
evidence is not entangled with range_get orchestration.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from merger.repoground.core import artifact_source_access as _artifact_source_access
from merger.repoground.core.bundle_roles import (
    DOES_NOT_ESTABLISH as _DOES_NOT_ESTABLISH,
    read_json_object as _read_json_object,
    read_only_mutation_boundary as _read_only_mutation_boundary,
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
from merger.repoground.core import citation_projection as _citation_projection_module
from merger.repoground.core.manifest_snapshot import resolve_manifest_path
from merger.repoground.core.response_projection import project_read_result
from merger.repoground.core import sqlite_artifact_read as _sqlite_artifact_read

logger = logging.getLogger(__name__)

_FILE_DESCRIPTOR_ROOTS = (Path("/proc/self/fd"), Path("/dev/fd"))

_read_registered_artifact_source = (
    _artifact_source_access._read_registered_artifact_source
)
_artifact_availability = _citation_projection_module.artifact_availability
_empty_source_citation_projection = (
    _citation_projection_module.empty_source_citation_projection
)
_SqliteArtifactValidationError = (
    _sqlite_artifact_read.SqliteArtifactValidationError
)

MAX_QUERY_EXISTING_INDEX_K = 100


def _bundle_access():
    from merger.repoground.core import bundle_access as _ba

    return _ba


def _invalid_read_result(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return _bundle_access()._invalid_read_result(*args, **kwargs)


def _resolve_sqlite_artifact(*args: Any, **kwargs: Any):
    return _bundle_access()._resolve_sqlite_artifact(*args, **kwargs)


def _verified_sqlite_query_path(*args: Any, **kwargs: Any):
    return _bundle_access()._verified_sqlite_query_path(*args, **kwargs)


def range_get(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return _bundle_access().range_get(*args, **kwargs)


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


