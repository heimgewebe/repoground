from __future__ import annotations

import json
import re
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
SOURCE_CITATION_PROJECTION_KIND = "repobrief.source_citation_projection"
SOURCE_CITATION_PROJECTION_VERSION = "v1"
TEXT_EXCERPT_MAX_CHARS = 1200
_CITATION_ID_RE = re.compile(r"^cit_[a-f0-9]{16}$")
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_CITATION_RANGE_KEY_FIELDS = ("file_path", "start_byte", "end_byte")


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
    from merger.lenskit.core.repobrief_availability import snapshot_availability_model

    availability_model = snapshot_availability_model(manifest_path, manifest)
    return {
        "kind": "repobrief.snapshot_status",
        "version": "v1",
        "status": "ok",
        "bundle_manifest": str(manifest_path),
        "bundle_run_id": manifest.get("run_id"),
        "profile": capabilities.get("repobrief_profile"),
        "profile_evaluation": capabilities.get("repobrief_profile_evaluation"),
        "availability_model": availability_model,
        "freshness": availability_model.get("freshness"),
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


def _is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value)


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and _SHA256_RE.fullmatch(value) is not None


def _is_int_not_bool(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _citation_range_key(value: Any) -> tuple[Any, ...] | None:
    if not isinstance(value, dict):
        return None
    file_path, start_byte, end_byte = (
        value.get(field) for field in _CITATION_RANGE_KEY_FIELDS
    )
    content_sha256 = value.get("range_content_sha256") or value.get("content_sha256")
    if not _is_non_empty_string(file_path):
        return None
    if not _is_int_not_bool(start_byte) or not _is_int_not_bool(end_byte):
        return None
    if start_byte < 0 or end_byte <= start_byte:
        return None
    if not _is_sha256(content_sha256):
        return None
    return (file_path, start_byte, end_byte, content_sha256)


def _range_ref_from_citation_row(row: dict[str, Any]) -> dict[str, Any] | None:
    citation_id = row.get("citation_id")
    repo_id = row.get("repo_id")
    canonical_range = row.get("canonical_range")
    if not isinstance(canonical_range, dict) or not _is_non_empty_string(repo_id):
        return None
    result = {
        "artifact_role": "canonical_md",
        "repo_id": repo_id,
        "file_path": canonical_range.get("file_path"),
        "start_byte": canonical_range.get("start_byte"),
        "end_byte": canonical_range.get("end_byte"),
        "start_line": canonical_range.get("start_line"),
        "end_line": canonical_range.get("end_line"),
        "content_sha256": canonical_range.get("content_sha256"),
    }
    chunk_id = row.get("chunk_id")
    if _is_non_empty_string(chunk_id):
        result["chunk_id"] = chunk_id
    # Preserve citation identity outside the strict range_ref itself; range-ref.v1
    # does not allow citation_id as an additional property.
    if not _is_non_empty_string(citation_id):
        return None
    return result


def _range_ref_is_valid_for_citation_row(value: Any, row: dict[str, Any]) -> bool:
    if not isinstance(value, dict):
        return False
    expected = _range_ref_from_citation_row(row)
    if expected is None:
        return False
    for key, expected_value in expected.items():
        if value.get(key) != expected_value:
            return False
    allowed_keys = set(expected) | {"chunk_id"}
    if set(value) - allowed_keys:
        return False
    return True


def _citation_row_is_valid(row: dict[str, Any]) -> bool:
    citation_id = row.get("citation_id")
    if not isinstance(citation_id, str) or _CITATION_ID_RE.fullmatch(citation_id) is None:
        return False
    if not _is_non_empty_string(row.get("repo_id")):
        return False

    snapshot = row.get("snapshot")
    if not isinstance(snapshot, dict):
        return False
    if not _is_non_empty_string(snapshot.get("run_id")):
        return False
    if not _is_non_empty_string(snapshot.get("canonical_md_path")):
        return False
    if not _is_sha256(snapshot.get("canonical_md_sha256")):
        return False

    canonical_range = row.get("canonical_range")
    if _citation_range_key(canonical_range) is None:
        return False
    if not isinstance(canonical_range, dict):
        return False
    start_line = canonical_range.get("start_line")
    end_line = canonical_range.get("end_line")
    if not _is_int_not_bool(start_line) or not _is_int_not_bool(end_line):
        return False
    if start_line < 1 or end_line < start_line:
        return False

    chunk_id = row.get("chunk_id")
    if chunk_id is not None and not _is_non_empty_string(chunk_id):
        return False
    range_ref = row.get("range_ref")
    if range_ref is not None and not _range_ref_is_valid_for_citation_row(range_ref, row):
        return False
    return True

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
    emitted_range_ref = row.get("range_ref")
    range_ref = (
        emitted_range_ref
        if _range_ref_is_valid_for_citation_row(emitted_range_ref, row)
        else _range_ref_from_citation_row(row)
    )
    return {
        "citation_id": row.get("citation_id"),
        "repo_id": row.get("repo_id"),
        "chunk_id": row.get("chunk_id"),
        "snapshot": row.get("snapshot"),
        "canonical_range": row.get("canonical_range"),
        "range_ref": range_ref,
        "source_range": row.get("source_range") if isinstance(row.get("source_range"), dict) else None,
        "live_repo_address": row.get("live_repo_address") if isinstance(row.get("live_repo_address"), dict) else None,
        "produced_by": row.get("produced_by"),
    }


def _artifact_availability(availability_model: dict[str, Any] | None, role: str) -> dict[str, Any]:
    if not isinstance(availability_model, dict):
        return {
            "role": role,
            "availability": "unknown",
            "requirement": None,
            "reason": "availability_model_unavailable",
        }
    artifacts = availability_model.get("artifacts")
    if isinstance(artifacts, list):
        for artifact in artifacts:
            if isinstance(artifact, dict) and artifact.get("role") == role:
                return {
                    "role": role,
                    "availability": artifact.get("availability"),
                    "requirement": artifact.get("requirement"),
                    "reason": artifact.get("reason"),
                }
    return {
        "role": role,
        "availability": "missing",
        "requirement": None,
        "reason": "role_not_reported_in_availability_model",
    }


def _line_range(start_line: Any, end_line: Any) -> dict[str, Any] | None:
    if not _is_int_not_bool(start_line) or not _is_int_not_bool(end_line):
        return None
    if start_line < 1 or end_line < start_line:
        return None
    return {
        "start_line": start_line,
        "end_line": end_line,
        "display": f"{start_line}-{end_line}",
    }


def _enrich_resolved_hit_for_direct_use(
    hit: dict[str, Any],
    *,
    availability_model: dict[str, Any] | None,
) -> None:
    range_value = hit.get("range")
    text = range_value.get("text") if isinstance(range_value, dict) else None
    raw_citation = hit.get("citation")
    citation = raw_citation if isinstance(raw_citation, dict) else None
    canonical_range = _source_range_projection(
        citation.get("canonical_range") if citation else None
    )
    citation_source_range = _source_range_projection(
        citation.get("source_range") if citation else None
    )
    live_repo_address = (
        citation.get("live_repo_address")
        if citation and isinstance(citation.get("live_repo_address"), dict)
        else None
    )
    range_ref_projection = (
        _source_range_projection(hit.get("range_ref"))
        if hit.get("range_status") == "resolved"
        else None
    )
    range_projection = _source_range_projection(range_value)
    candidates = [citation_source_range, range_ref_projection, canonical_range, range_projection]
    source_range = next(
        (candidate for candidate in candidates if _has_range_identity(candidate)),
        None,
    )
    if source_range is None:
        source_range = next(
            (candidate for candidate in candidates if isinstance(candidate, dict)),
            None,
        )

    source_path = None
    source_line_range = None
    artifact_path = None
    artifact_line_range = None
    artifact_role = None
    if isinstance(live_repo_address, dict):
        source_path = live_repo_address.get("path")
        source_line_range = _line_range(
            live_repo_address.get("start_line"),
            live_repo_address.get("end_line"),
        )
    if isinstance(source_range, dict):
        source_path = _first_not_none(
            source_path,
            source_range.get("source_file_path"),
            source_range.get("file_path"),
            hit.get("path"),
        )
        source_line_range = source_line_range or _line_range(
            _first_not_none(source_range.get("source_start_line"), source_range.get("start_line")),
            _first_not_none(source_range.get("source_end_line"), source_range.get("end_line")),
        )
        artifact_path = _first_not_none(source_range.get("artifact_path"), source_range.get("file_path"))
        artifact_line_range = _line_range(
            _first_not_none(source_range.get("artifact_start_line"), source_range.get("start_line")),
            _first_not_none(source_range.get("artifact_end_line"), source_range.get("end_line")),
        )
        artifact_role = source_range.get("artifact_role")
    if source_path is None:
        source_path = hit.get("path")

    hit["text_excerpt"] = text[:TEXT_EXCERPT_MAX_CHARS] if isinstance(text, str) else None
    hit["text_truncated"] = isinstance(text, str) and len(text) > TEXT_EXCERPT_MAX_CHARS
    hit["source_path"] = source_path
    hit["line_range"] = source_line_range or artifact_line_range
    hit["source_line_range"] = source_line_range
    hit["artifact_path"] = artifact_path
    hit["artifact_role"] = artifact_role
    hit["artifact_line_range"] = artifact_line_range
    hit["canonical_authority"] = {
        "authority": "canonical_brief_source",
        "artifact_role": "canonical_md",
        "range": canonical_range,
        "citation_id": hit.get("citation_id"),
    }
    hit["live_repo_address"] = live_repo_address
    hit["live_repo_address_status"] = (
        live_repo_address.get("status")
        if isinstance(live_repo_address, dict)
        else "unavailable"
    )
    hit["range_ref_verified"] = hit.get("range_status") == "resolved"
    hit["citation_verified"] = hit.get("citation_status") == "resolved" and isinstance(
        hit.get("citation_id"),
        str,
    )
    hit["availability"] = {
        "snapshot_status": availability_model.get("status")
        if isinstance(availability_model, dict)
        else "unknown",
        "artifact": _artifact_availability(
            availability_model,
            str(artifact_role or "canonical_md"),
        ),
        "index_artifact": _artifact_availability(availability_model, "sqlite_index"),
    }
    hit["freshness"] = (
        availability_model.get("freshness") if isinstance(availability_model, dict) else None
    )


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
    from merger.lenskit.core.repobrief_availability import snapshot_availability_model

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


def _first_not_none(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _line_pair(value: Any) -> tuple[int | None, int | None]:
    if not isinstance(value, list) or len(value) != 2:
        return None, None
    start, end = value
    if isinstance(start, bool) or isinstance(end, bool):
        return None, None
    if not isinstance(start, int) or not isinstance(end, int):
        return None, None
    return start, end


def _has_range_identity(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    file_path = value.get("file_path")
    start_byte = value.get("start_byte")
    end_byte = value.get("end_byte")
    if not _is_non_empty_string(file_path):
        return False
    if not _is_int_not_bool(start_byte) or not _is_int_not_bool(end_byte):
        return False
    return start_byte >= 0 and end_byte > start_byte


def _source_range_projection(range_value: Any) -> dict[str, Any] | None:
    if not isinstance(range_value, dict):
        return None
    provenance = range_value.get("provenance")
    if not isinstance(provenance, dict):
        provenance = {}
    start_line, end_line = _line_pair(range_value.get("lines"))
    artifact_path = _first_not_none(
        range_value.get("artifact_path"),
        range_value.get("file_path"),
        range_value.get("path"),
        provenance.get("artifact_path"),
        provenance.get("file_path"),
    )
    artifact_start_byte = _first_not_none(
        range_value.get("artifact_byte_start"),
        range_value.get("start_byte"),
        provenance.get("artifact_byte_start"),
        provenance.get("start_byte"),
    )
    artifact_end_byte = _first_not_none(
        range_value.get("artifact_byte_end"),
        range_value.get("end_byte"),
        provenance.get("artifact_byte_end"),
        provenance.get("end_byte"),
    )
    artifact_start_line = _first_not_none(
        range_value.get("artifact_line_start"),
        range_value.get("start_line"),
        start_line,
    )
    artifact_end_line = _first_not_none(
        range_value.get("artifact_line_end"),
        range_value.get("end_line"),
        end_line,
    )
    source_file_path = _first_not_none(
        range_value.get("source_file_path"),
        provenance.get("source_file_path"),
    )
    source_start_line = _first_not_none(
        range_value.get("source_line_start"),
        provenance.get("source_line_start"),
    )
    source_end_line = _first_not_none(
        range_value.get("source_line_end"),
        provenance.get("source_line_end"),
    )
    has_source_axis = _is_non_empty_string(source_file_path)
    return {
        "artifact_role": _first_not_none(range_value.get("artifact_role"), provenance.get("artifact_role")),
        "file_path": artifact_path,
        "start_byte": artifact_start_byte,
        "end_byte": artifact_end_byte,
        "start_line": artifact_start_line,
        "end_line": artifact_end_line,
        "content_sha256": _first_not_none(range_value.get("range_content_sha256"), range_value.get("content_sha256"), range_value.get("sha256")),
        "artifact_path": artifact_path,
        "artifact_start_byte": artifact_start_byte,
        "artifact_end_byte": artifact_end_byte,
        "artifact_start_line": artifact_start_line,
        "artifact_end_line": artifact_end_line,
        "source_file_path": source_file_path,
        "source_start_line": source_start_line,
        "source_end_line": source_end_line,
        "coordinate_basis": "artifact_bytes_with_source_lines" if has_source_axis else "artifact_bytes",
    }


def _empty_source_citation_projection(status: str = "unavailable") -> dict[str, Any]:
    return {
        "kind": SOURCE_CITATION_PROJECTION_KIND,
        "version": SOURCE_CITATION_PROJECTION_VERSION,
        "status": status,
        "hit_count": 0,
        "citation_count": 0,
        "unresolved_count": 0,
        "range_unresolved_count": 0,
        "citation_unresolved_count": 0,
        "text_excerpt_max_chars": TEXT_EXCERPT_MAX_CHARS,
        "items": [],
        "does_not_establish": list(_DOES_NOT_ESTABLISH),
    }


def _project_source_citations(resolved_evidence: Any) -> dict[str, Any]:
    if not isinstance(resolved_evidence, dict):
        return _empty_source_citation_projection()

    hits = resolved_evidence.get("hits")
    hit_list = [hit for hit in (hits if isinstance(hits, list) else []) if isinstance(hit, dict)]
    items: list[dict[str, Any]] = []
    citation_count = 0
    unresolved_count = 0
    range_unresolved_count = 0
    citation_unresolved_count = 0
    for ordinal, hit in enumerate(hit_list):
        range_value = hit.get("range")
        text = range_value.get("text") if isinstance(range_value, dict) else None
        raw_citation = hit.get("citation")
        citation = raw_citation if isinstance(raw_citation, dict) else None
        citation_range = _source_range_projection(
            citation.get("canonical_range") if citation else None
        )
        citation_source_range = _source_range_projection(
            citation.get("source_range") if citation else None
        )
        live_repo_address = (
            citation.get("live_repo_address")
            if citation and isinstance(citation.get("live_repo_address"), dict)
            else None
        )
        range_ref_projection = (
            _source_range_projection(hit.get("range_ref"))
            if hit.get("range_status") == "resolved"
            else None
        )
        range_projection = _source_range_projection(range_value)
        candidates = [citation_source_range, range_ref_projection, citation_range, range_projection]
        source_range = next(
            (candidate for candidate in candidates if _has_range_identity(candidate)),
            None,
        )
        if source_range is None:
            source_range = next(
                (candidate for candidate in candidates if isinstance(candidate, dict)),
                None,
            )
        range_status = hit.get("range_status")
        citation_status = hit.get("citation_status")
        citation_id = hit.get("citation_id")
        if range_status != "resolved":
            range_unresolved_count += 1
        citation_resolved = (
            citation_status == "resolved"
            and isinstance(citation_id, str)
            and _CITATION_ID_RE.fullmatch(citation_id) is not None
        )
        if citation_resolved:
            citation_count += 1
        else:
            citation_unresolved_count += 1
        if range_status != "resolved" or not citation_resolved:
            unresolved_count += 1
        items.append({
            "ordinal": ordinal,
            "chunk_id": hit.get("chunk_id"),
            "path": hit.get("path"),
            "range_status": range_status,
            "range_ref_source": hit.get("range_ref_source"),
            "source_range": source_range,
            "text_excerpt": text[:TEXT_EXCERPT_MAX_CHARS] if isinstance(text, str) else None,
            "text_truncated": isinstance(text, str) and len(text) > TEXT_EXCERPT_MAX_CHARS,
            "citation_status": citation_status,
            "citation_resolved": citation_resolved,
            "citation_id": citation_id,
            "citation_range": citation_range,
            "citation_source_range": citation_source_range,
            "live_repo_address": live_repo_address,
            "live_repo_address_status": (
                live_repo_address.get("status")
                if isinstance(live_repo_address, dict)
                else "unavailable"
            ),
            "canonical_authority": {
                "authority": "canonical_brief_source",
                "artifact_role": "canonical_md",
                "range": citation_range,
                "citation_id": citation_id,
            },
        })
    return {
        "kind": SOURCE_CITATION_PROJECTION_KIND,
        "version": SOURCE_CITATION_PROJECTION_VERSION,
        "status": "available",
        "hit_count": len(items),
        "citation_count": citation_count,
        "unresolved_count": unresolved_count,
        "range_unresolved_count": range_unresolved_count,
        "citation_unresolved_count": citation_unresolved_count,
        "text_excerpt_max_chars": TEXT_EXCERPT_MAX_CHARS,
        "items": items,
        "does_not_establish": list(_DOES_NOT_ESTABLISH),
    }


def query_existing_index(
    bundle_manifest: str | Path,
    query: str,
    k: int = 10,
    filters: dict[str, str | None] | None = None,
    resolve_evidence: bool = False,
    project_sources: bool = False,
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

    if not isinstance(project_sources, bool):
        return _invalid_read_result(
            kind="repobrief.query_existing_index",
            bundle_manifest=manifest_path,
            status="invalid",
            error="project_sources must be a boolean",
            error_code="project_sources_invalid",
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

    return {
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
