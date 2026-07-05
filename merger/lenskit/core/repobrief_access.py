from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_DOES_NOT_ESTABLISH = (
    "truth",
    "correctness",
    "completeness",
    "runtime_behavior",
    "test_sufficiency",
    "regression_absence",
    "repo_understood",
    "claims_true",
    "forensic_ready",
    "freshness",
)

CITATION_MAP_ROLE = "citation_map_jsonl"
RESOLVED_EVIDENCE_KIND = "repobrief.resolved_evidence"
RESOLVED_EVIDENCE_VERSION = "v1"
_CITATION_RANGE_KEY_FIELDS = ("file_path", "start_byte", "end_byte", "content_sha256")


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"bundle manifest does not exist: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"bundle manifest is not valid JSON: {path}") from exc
    if not isinstance(data, dict):
        raise ValueError("bundle manifest must be a JSON object")
    return data


def _artifact_list(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    artifacts = manifest.get("artifacts", [])
    if not isinstance(artifacts, list):
        raise ValueError("bundle manifest artifacts must be an array")
    return [a for a in artifacts if isinstance(a, dict)]


def _safe_artifact_path(root: Path, raw_path: Any) -> Path | None:
    if not isinstance(raw_path, str) or not raw_path:
        return None
    candidate = (root / raw_path).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    return candidate


def _artifact_record(bundle_manifest: Path, artifact: dict[str, Any]) -> dict[str, Any]:
    root = bundle_manifest.parent
    artifact_path = _safe_artifact_path(root, artifact.get("path"))
    file_exists = bool(artifact_path and artifact_path.exists())
    return {
        "role": artifact.get("role"),
        "path": artifact.get("path"),
        "absolute_path": str(artifact_path) if artifact_path else None,
        "file_exists": file_exists,
        "content_type": artifact.get("content_type"),
        "bytes": artifact.get("bytes"),
        "sha256": artifact.get("sha256"),
        "authority": artifact.get("authority"),
        "canonicality": artifact.get("canonicality"),
        "risk_class": artifact.get("risk_class"),
        "contract": artifact.get("contract"),
        "interpretation": artifact.get("interpretation"),
    }


def available_roles(bundle_manifest: str | Path) -> list[str]:
    manifest_path = Path(bundle_manifest).expanduser().resolve()
    manifest = _read_json_object(manifest_path)
    roles: set[str] = {"bundle_manifest"}
    for artifact in _artifact_list(manifest):
        role = artifact.get("role")
        if isinstance(role, str) and role:
            roles.add(role)
    links = manifest.get("links")
    if isinstance(links, dict):
        linked_roles = {
            "post_emit_health_path": "post_emit_health",
            "bundle_surface_validation_path": "bundle_surface_validation",
            "export_safety_report_path": "export_safety_report",
        }
        for key, role in linked_roles.items():
            if links.get(key):
                roles.add(role)
    return sorted(roles)


def resolve_required_reading_for_bundle(
    bundle_manifest: str | Path,
    task_profile: str,
) -> dict[str, Any]:
    from merger.lenskit.core.required_reading import (
        default_required_reading_protocol,
        resolve_required_reading,
    )

    manifest_path = Path(bundle_manifest).expanduser().resolve()
    roles = available_roles(manifest_path)
    required = resolve_required_reading(
        default_required_reading_protocol(),
        set(roles),
        task_profile,
    )
    return {
        "kind": "repobrief.required_reading_resolution",
        "version": "v1",
        "status": required.get("status"),
        "bundle_manifest": str(manifest_path),
        "task_profile": task_profile,
        "available_roles": roles,
        "required_reading": required,
        "mutation_boundary": {
            "writes": [],
            "does_not_mutate": ["git", "pull_requests", "patches", "source_working_tree", "brief_bundle_artifacts"],
            "read_paths_do_not_refresh": True,
        },
        "does_not_establish": list(_DOES_NOT_ESTABLISH),
    }


def snapshot_status(bundle_manifest: str | Path) -> dict[str, Any]:
    manifest_path = Path(bundle_manifest).expanduser().resolve()
    manifest = _read_json_object(manifest_path)
    artifacts = [_artifact_record(manifest_path, a) for a in _artifact_list(manifest)]
    roles = sorted(str(a["role"]) for a in artifacts if isinstance(a.get("role"), str))
    capabilities = manifest.get("capabilities") if isinstance(manifest.get("capabilities"), dict) else {}
    return {
        "kind": "repobrief.snapshot_status",
        "version": "v1",
        "status": "ok",
        "bundle_manifest": str(manifest_path),
        "bundle_run_id": manifest.get("run_id"),
        "profile": capabilities.get("repobrief_profile"),
        "profile_evaluation": capabilities.get("repobrief_profile_evaluation"),
        "artifact_count": len(artifacts),
        "roles": roles,
        "artifacts": artifacts,
        "mutation_boundary": {
            "writes": [],
            "does_not_mutate": ["git", "pull_requests", "patches", "source_working_tree", "brief_bundle_artifacts"],
            "read_paths_do_not_refresh": True,
        },
        "does_not_establish": list(_DOES_NOT_ESTABLISH),
    }


def list_artifacts(bundle_manifest: str | Path) -> dict[str, Any]:
    status = snapshot_status(bundle_manifest)
    return {
        "kind": "repobrief.artifact_list",
        "version": "v1",
        "status": status["status"],
        "bundle_manifest": status["bundle_manifest"],
        "bundle_run_id": status["bundle_run_id"],
        "profile": status["profile"],
        "artifact_count": status["artifact_count"],
        "roles": status["roles"],
        "artifacts": status["artifacts"],
        "mutation_boundary": status["mutation_boundary"],
        "does_not_establish": status["does_not_establish"],
    }


def get_artifact(bundle_manifest: str | Path, role: str) -> dict[str, Any]:
    manifest_path = Path(bundle_manifest).expanduser().resolve()
    manifest = _read_json_object(manifest_path)
    matches = [a for a in _artifact_list(manifest) if a.get("role") == role]
    if not matches:
        return {
            "kind": "repobrief.artifact_ref",
            "version": "v1",
            "status": "missing",
            "bundle_manifest": str(manifest_path),
            "role": role,
            "artifact": None,
            "mutation_boundary": {
                "writes": [],
                "does_not_mutate": ["git", "pull_requests", "patches", "source_working_tree", "brief_bundle_artifacts"],
                "read_paths_do_not_refresh": True,
            },
            "does_not_establish": list(_DOES_NOT_ESTABLISH),
        }
    return {
        "kind": "repobrief.artifact_ref",
        "version": "v1",
        "status": "available",
        "bundle_manifest": str(manifest_path),
        "role": role,
        "artifact": _artifact_record(manifest_path, matches[0]),
        "mutation_boundary": {
            "writes": [],
            "does_not_mutate": ["git", "pull_requests", "patches", "source_working_tree", "brief_bundle_artifacts"],
            "read_paths_do_not_refresh": True,
        },
        "does_not_establish": list(_DOES_NOT_ESTABLISH),
    }


MAX_QUERY_EXISTING_INDEX_K = 100


def _read_only_mutation_boundary() -> dict[str, Any]:
    return {
        "writes": [],
        "does_not_mutate": [
            "git",
            "pull_requests",
            "patches",
            "source_working_tree",
            "brief_bundle_artifacts",
        ],
        "read_paths_do_not_refresh": True,
    }


def _invalid_read_result(
    *,
    kind: str,
    bundle_manifest: Path,
    status: str,
    error: str,
    error_code: str,
    extra: dict[str, Any] | None = None,
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
    return result


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


def range_get(bundle_manifest: str | Path, range_ref: dict[str, Any]) -> dict[str, Any]:
    manifest_path = Path(bundle_manifest).expanduser().resolve()
    if not isinstance(range_ref, dict):
        return _invalid_read_result(
            kind="repobrief.range_get",
            bundle_manifest=manifest_path,
            status="invalid",
            error="range_ref must be a JSON object",
            error_code="range_ref_invalid",
            extra={"range_ref": range_ref, "range": None},
        )

    if range_ref.get("artifact_role") == "source_file":
        return _invalid_read_result(
            kind="repobrief.range_get",
            bundle_manifest=manifest_path,
            status="invalid",
            error=(
                "source_file range_refs are outside the read-only RepoBrief "
                "bundle artifact boundary"
            ),
            error_code="source_file_outside_bundle_boundary",
            extra={"range_ref": range_ref, "range": None},
        )

    from merger.lenskit.core.range_resolver import resolve_range_ref

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
        )

    return {
        "kind": "repobrief.range_get",
        "version": "v1",
        "status": "available",
        "bundle_manifest": str(manifest_path),
        "range_ref": range_ref,
        "range": resolved,
        "mutation_boundary": _read_only_mutation_boundary(),
        "does_not_establish": list(_DOES_NOT_ESTABLISH),
    }


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


def _citation_range_key(value: Any) -> tuple[Any, ...] | None:
    if not isinstance(value, dict):
        return None
    key = tuple(value.get(field) for field in _CITATION_RANGE_KEY_FIELDS)
    if any(part is None for part in key):
        return None
    return key


def _load_citation_lookup(
    manifest_path: Path,
) -> tuple[dict[str, dict[str, Any]], dict[tuple[Any, ...], dict[str, Any]], dict[str, Any]]:
    artifact_result = get_artifact(manifest_path, CITATION_MAP_ROLE)
    artifact = artifact_result.get("artifact") if isinstance(artifact_result, dict) else None
    artifact_path_str = artifact.get("absolute_path") if isinstance(artifact, dict) else None
    if not artifact_path_str:
        return {}, {}, _empty_citation_map_status(
            status="missing",
            error_code="citation_map_jsonl_missing",
            artifact_path=None,
        )
    artifact_path = Path(str(artifact_path_str))
    if not artifact_path.exists():
        return {}, {}, _empty_citation_map_status(
            status="missing",
            error_code="citation_map_jsonl_file_missing",
            artifact_path=str(artifact_path),
        )

    by_chunk_id: dict[str, dict[str, Any]] = {}
    by_range: dict[tuple[Any, ...], dict[str, Any]] = {}
    row_count = 0
    invalid_row_count = 0
    try:
        with artifact_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    invalid_row_count += 1
                    continue
                if not isinstance(row, dict):
                    invalid_row_count += 1
                    continue
                citation_id = row.get("citation_id")
                if not isinstance(citation_id, str) or not citation_id:
                    invalid_row_count += 1
                    continue
                row_count += 1
                chunk_id = row.get("chunk_id")
                if isinstance(chunk_id, str) and chunk_id and chunk_id not in by_chunk_id:
                    by_chunk_id[chunk_id] = row
                range_key = _citation_range_key(row.get("canonical_range"))
                if range_key is not None and range_key not in by_range:
                    by_range[range_key] = row
    except (OSError, UnicodeDecodeError) as exc:
        return {}, {}, _empty_citation_map_status(
            status="invalid",
            error_code="citation_map_jsonl_unreadable",
            artifact_path=str(artifact_path),
            error=str(exc),
        )

    return by_chunk_id, by_range, {
        "status": "available",
        "error_code": None,
        "artifact_path": str(artifact_path),
        "row_count": row_count,
        "invalid_row_count": invalid_row_count,
    }


def _citation_record(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "citation_id": row.get("citation_id"),
        "repo_id": row.get("repo_id"),
        "chunk_id": row.get("chunk_id"),
        "snapshot": row.get("snapshot"),
        "canonical_range": row.get("canonical_range"),
        "produced_by": row.get("produced_by"),
    }


def _resolve_hit_evidence(
    manifest_path: Path,
    hit: dict[str, Any],
    by_chunk_id: dict[str, dict[str, Any]],
    by_range: dict[tuple[Any, ...], dict[str, Any]],
    citation_map_available: bool,
) -> dict[str, Any]:
    range_ref = hit.get("range_ref")
    range_ref_source = None
    if isinstance(range_ref, dict):
        range_ref_source = "range_ref"
    elif isinstance(hit.get("derived_range_ref"), dict):
        range_ref = hit["derived_range_ref"]
        range_ref_source = "derived_range_ref"

    record: dict[str, Any] = {
        "chunk_id": hit.get("chunk_id"),
        "path": hit.get("path"),
        "range_ref_source": range_ref_source,
        "range_status": "unresolved",
        "range": None,
        "range_error": None,
        "range_error_code": None,
        "citation_status": "unmatched" if citation_map_available else "unavailable",
        "citation_id": None,
        "citation": None,
    }

    if range_ref_source is None:
        record["range_error_code"] = "range_ref_missing"
    else:
        range_result = range_get(manifest_path, range_ref)
        if range_result.get("status") == "available":
            record["range_status"] = "resolved"
            record["range"] = range_result.get("range")
        else:
            record["range_error"] = range_result.get("error")
            record["range_error_code"] = range_result.get("error_code")

    if citation_map_available:
        row = None
        chunk_id = hit.get("chunk_id")
        if isinstance(chunk_id, str):
            row = by_chunk_id.get(chunk_id)
        range_key = _citation_range_key(range_ref)
        if row is None and range_key is not None:
            row = by_range.get(range_key)
        if row is not None:
            record["citation_status"] = "resolved"
            record["citation_id"] = row.get("citation_id")
            record["citation"] = _citation_record(row)

    return record


def _resolve_query_evidence(manifest_path: Path, query_result: Any) -> dict[str, Any]:
    hits = query_result.get("results") if isinstance(query_result, dict) else None
    hit_list = [hit for hit in (hits if isinstance(hits, list) else []) if isinstance(hit, dict)]
    if not hit_list:
        return {
            "kind": RESOLVED_EVIDENCE_KIND,
            "version": RESOLVED_EVIDENCE_VERSION,
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
        _resolve_hit_evidence(manifest_path, hit, by_chunk_id, by_range, citation_map_available)
        for hit in hit_list
    ]
    return {
        "kind": RESOLVED_EVIDENCE_KIND,
        "version": RESOLVED_EVIDENCE_VERSION,
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
) -> dict[str, Any]:
    manifest_path = Path(bundle_manifest).expanduser().resolve()
    if not isinstance(query, str):
        return _invalid_read_result(
            kind="repobrief.query_existing_index",
            bundle_manifest=manifest_path,
            status="invalid",
            error="query must be a string",
            error_code="query_invalid",
            extra={"query": query, "k": k, "query_result": None, "index_artifact": None},
        )
    if not isinstance(k, int) or isinstance(k, bool) or k < 1 or k > MAX_QUERY_EXISTING_INDEX_K:
        return _invalid_read_result(
            kind="repobrief.query_existing_index",
            bundle_manifest=manifest_path,
            status="invalid",
            error=f"k must be an integer between 1 and {MAX_QUERY_EXISTING_INDEX_K}",
            error_code="k_out_of_bounds",
            extra={"query": query, "k": k, "query_result": None, "index_artifact": None},
        )
    if not isinstance(resolve_evidence, bool):
        return _invalid_read_result(
            kind="repobrief.query_existing_index",
            bundle_manifest=manifest_path,
            status="invalid",
            error="resolve_evidence must be a boolean",
            error_code="resolve_evidence_invalid",
            extra={"query": query, "k": k, "query_result": None, "index_artifact": None},
        )

    artifact_result = get_artifact(manifest_path, "sqlite_index")
    artifact = artifact_result.get("artifact") if isinstance(artifact_result, dict) else None
    if not isinstance(artifact, dict) or not artifact.get("absolute_path"):
        return _invalid_read_result(
            kind="repobrief.query_existing_index",
            bundle_manifest=manifest_path,
            status="missing",
            error="sqlite_index artifact is not present in the bundle manifest",
            error_code="sqlite_index_missing",
            extra={"query": query, "k": k, "query_result": None, "index_artifact": artifact},
        )

    index_path = Path(str(artifact["absolute_path"]))
    if not index_path.exists():
        return _invalid_read_result(
            kind="repobrief.query_existing_index",
            bundle_manifest=manifest_path,
            status="missing",
            error="sqlite_index artifact file does not exist",
            error_code="sqlite_index_file_missing",
            extra={"query": query, "k": k, "query_result": None, "index_artifact": artifact},
        )

    from merger.lenskit.retrieval.query_core import execute_query

    try:
        query_result = execute_query(
            index_path,
            query,
            k=k,
            filters=filters or {},
            trace=False,
            build_context=False,
            read_only=True,
        )
    except Exception as exc:
        return _invalid_read_result(
            kind="repobrief.query_existing_index",
            bundle_manifest=manifest_path,
            status="invalid",
            error=str(exc),
            error_code="query_execution_failed",
            extra={"query": query, "k": k, "query_result": None, "index_artifact": artifact},
        )

    return {
        "kind": "repobrief.query_existing_index",
        "version": "v1",
        "status": "available",
        "bundle_manifest": str(manifest_path),
        "query": query,
        "k": k,
        "filters": filters or {},
        "resolve_evidence": resolve_evidence,
        "index_artifact": artifact,
        "query_result": query_result,
        "resolved_evidence": (
            _resolve_query_evidence(manifest_path, query_result) if resolve_evidence else None
        ),
        "mutation_boundary": _read_only_mutation_boundary(),
        "does_not_establish": list(_DOES_NOT_ESTABLISH),
    }


def snapshot_check(
    bundle_manifest: str | Path,
    task_profile: str = "basic_repo_question",
) -> dict[str, Any]:
    status = snapshot_status(bundle_manifest)
    artifacts = list_artifacts(bundle_manifest)
    required = resolve_required_reading_for_bundle(bundle_manifest, task_profile)
    required_status = str(required.get("status", "unknown"))
    profile_eval = status.get("profile_evaluation")
    profile_status = None
    if isinstance(profile_eval, dict):
        raw_profile_status = profile_eval.get("status")
        if isinstance(raw_profile_status, str):
            profile_status = raw_profile_status

    statuses = [required_status]
    if profile_status:
        statuses.append(profile_status)
    if "fail" in statuses or "not_applicable" in statuses:
        check_status = "fail"
    elif "warn" in statuses:
        check_status = "warn"
    elif all(item == "pass" for item in statuses):
        check_status = "pass"
    else:
        check_status = "unknown"
    return {
        "kind": "repobrief.snapshot_check",
        "version": "v1",
        "status": check_status,
        "bundle_manifest": status["bundle_manifest"],
        "bundle_run_id": status["bundle_run_id"],
        "profile": status["profile"],
        "profile_evaluation_status": profile_status,
        "task_profile": task_profile,
        "artifact_count": artifacts["artifact_count"],
        "roles": artifacts["roles"],
        "snapshot_status": status,
        "artifact_list": artifacts,
        "required_reading": required,
        "mutation_boundary": {
            "writes": [],
            "does_not_mutate": ["git", "pull_requests", "patches", "source_working_tree", "brief_bundle_artifacts"],
            "read_paths_do_not_refresh": True,
        },
        "does_not_establish": list(_DOES_NOT_ESTABLISH),
    }
