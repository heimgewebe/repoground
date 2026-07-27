"""Validation and read-only projections for bundle citation evidence."""

from __future__ import annotations

import re
from typing import Any

from merger.repoground.core.bundle_roles import DOES_NOT_ESTABLISH

CITATION_MAP_ROLE = "citation_map_jsonl"
RESOLVED_EVIDENCE_KIND = "repobrief.resolved_evidence"
RESOLVED_EVIDENCE_VERSION = "v1"
SOURCE_CITATION_PROJECTION_KIND = "repobrief.source_citation_projection"
SOURCE_CITATION_PROJECTION_VERSION = "v1"
TEXT_EXCERPT_MAX_CHARS = 1200

_CITATION_ID_RE = re.compile(r"^cit_[a-f0-9]{16}$")
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_CITATION_RANGE_KEY_FIELDS = ("file_path", "start_byte", "end_byte")


def is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value)


def is_sha256(value: Any) -> bool:
    return isinstance(value, str) and _SHA256_RE.fullmatch(value) is not None


def is_int_not_bool(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def citation_range_key(value: Any) -> tuple[Any, ...] | None:
    if not isinstance(value, dict):
        return None
    file_path, start_byte, end_byte = (
        value.get(field) for field in _CITATION_RANGE_KEY_FIELDS
    )
    content_sha256 = value.get("range_content_sha256") or value.get(
        "content_sha256"
    )
    if not is_non_empty_string(file_path):
        return None
    if not is_int_not_bool(start_byte) or not is_int_not_bool(end_byte):
        return None
    if start_byte < 0 or end_byte <= start_byte:
        return None
    if not is_sha256(content_sha256):
        return None
    return (file_path, start_byte, end_byte, content_sha256)


def range_ref_from_citation_row(
    row: dict[str, Any],
) -> dict[str, Any] | None:
    citation_id = row.get("citation_id")
    repo_id = row.get("repo_id")
    canonical_range = row.get("canonical_range")
    if not isinstance(canonical_range, dict) or not is_non_empty_string(repo_id):
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
    if is_non_empty_string(chunk_id):
        result["chunk_id"] = chunk_id
    if not is_non_empty_string(citation_id):
        return None
    return result


def range_ref_is_valid_for_citation_row(
    value: Any,
    row: dict[str, Any],
) -> bool:
    if not isinstance(value, dict):
        return False
    expected = range_ref_from_citation_row(row)
    if expected is None:
        return False
    if any(value.get(key) != expected_value for key, expected_value in expected.items()):
        return False
    return not set(value).difference(set(expected) | {"chunk_id"})


def _snapshot_is_valid(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and is_non_empty_string(value.get("run_id"))
        and is_non_empty_string(value.get("canonical_md_path"))
        and is_sha256(value.get("canonical_md_sha256"))
    )


def _canonical_range_is_valid(value: Any) -> bool:
    if not isinstance(value, dict) or citation_range_key(value) is None:
        return False
    start_line = value.get("start_line")
    end_line = value.get("end_line")
    return (
        is_int_not_bool(start_line)
        and is_int_not_bool(end_line)
        and start_line >= 1
        and end_line >= start_line
    )


def citation_row_is_valid(row: dict[str, Any]) -> bool:
    """Validate one citation row without accepting partial identity metadata."""
    citation_id = row.get("citation_id")
    if (
        not isinstance(citation_id, str)
        or _CITATION_ID_RE.fullmatch(citation_id) is None
        or not is_non_empty_string(row.get("repo_id"))
    ):
        return False
    if not _snapshot_is_valid(row.get("snapshot")):
        return False
    if not _canonical_range_is_valid(row.get("canonical_range")):
        return False
    chunk_id = row.get("chunk_id")
    if chunk_id is not None and not is_non_empty_string(chunk_id):
        return False
    range_ref = row.get("range_ref")
    return range_ref is None or range_ref_is_valid_for_citation_row(range_ref, row)


def citation_record(row: dict[str, Any]) -> dict[str, Any]:
    emitted_range_ref = row.get("range_ref")
    range_ref = (
        emitted_range_ref
        if range_ref_is_valid_for_citation_row(emitted_range_ref, row)
        else range_ref_from_citation_row(row)
    )
    source_range = row.get("source_range")
    live_repo_address = row.get("live_repo_address")
    return {
        "citation_id": row.get("citation_id"),
        "repo_id": row.get("repo_id"),
        "chunk_id": row.get("chunk_id"),
        "snapshot": row.get("snapshot"),
        "canonical_range": row.get("canonical_range"),
        "range_ref": range_ref,
        "source_range": source_range if isinstance(source_range, dict) else None,
        "live_repo_address": (
            live_repo_address
            if isinstance(live_repo_address, dict)
            else None
        ),
        "produced_by": row.get("produced_by"),
    }


def artifact_availability(
    availability_model: dict[str, Any] | None,
    role: str,
) -> dict[str, Any]:
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


def line_range(start_line: Any, end_line: Any) -> dict[str, Any] | None:
    if not is_int_not_bool(start_line) or not is_int_not_bool(end_line):
        return None
    if start_line < 1 or end_line < start_line:
        return None
    return {
        "start_line": start_line,
        "end_line": end_line,
        "display": f"{start_line}-{end_line}",
    }


def first_not_none(*values: Any) -> Any:
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


def has_range_identity(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    file_path = value.get("file_path")
    start_byte = value.get("start_byte")
    end_byte = value.get("end_byte")
    if not is_non_empty_string(file_path):
        return False
    if not is_int_not_bool(start_byte) or not is_int_not_bool(end_byte):
        return False
    return start_byte >= 0 and end_byte > start_byte


def source_range_projection(range_value: Any) -> dict[str, Any] | None:
    if not isinstance(range_value, dict):
        return None
    provenance = range_value.get("provenance")
    if not isinstance(provenance, dict):
        provenance = {}
    start_line, end_line = _line_pair(range_value.get("lines"))
    artifact_path = first_not_none(
        range_value.get("artifact_path"),
        range_value.get("file_path"),
        range_value.get("path"),
        provenance.get("artifact_path"),
        provenance.get("file_path"),
    )
    artifact_start_byte = first_not_none(
        range_value.get("artifact_byte_start"),
        range_value.get("start_byte"),
        provenance.get("artifact_byte_start"),
        provenance.get("start_byte"),
    )
    artifact_end_byte = first_not_none(
        range_value.get("artifact_byte_end"),
        range_value.get("end_byte"),
        provenance.get("artifact_byte_end"),
        provenance.get("end_byte"),
    )
    artifact_start_line = first_not_none(
        range_value.get("artifact_line_start"),
        range_value.get("start_line"),
        start_line,
    )
    artifact_end_line = first_not_none(
        range_value.get("artifact_line_end"),
        range_value.get("end_line"),
        end_line,
    )
    source_file_path = first_not_none(
        range_value.get("source_file_path"),
        provenance.get("source_file_path"),
    )
    source_start_line = first_not_none(
        range_value.get("source_line_start"),
        provenance.get("source_line_start"),
    )
    source_end_line = first_not_none(
        range_value.get("source_line_end"),
        provenance.get("source_line_end"),
    )
    has_source_axis = is_non_empty_string(source_file_path)
    return {
        "artifact_role": first_not_none(
            range_value.get("artifact_role"),
            provenance.get("artifact_role"),
        ),
        "file_path": artifact_path,
        "start_byte": artifact_start_byte,
        "end_byte": artifact_end_byte,
        "start_line": artifact_start_line,
        "end_line": artifact_end_line,
        "content_sha256": first_not_none(
            range_value.get("range_content_sha256"),
            range_value.get("content_sha256"),
            range_value.get("sha256"),
        ),
        "artifact_path": artifact_path,
        "artifact_start_byte": artifact_start_byte,
        "artifact_end_byte": artifact_end_byte,
        "artifact_start_line": artifact_start_line,
        "artifact_end_line": artifact_end_line,
        "source_file_path": source_file_path,
        "source_start_line": source_start_line,
        "source_end_line": source_end_line,
        "coordinate_basis": (
            "artifact_bytes_with_source_lines"
            if has_source_axis
            else "artifact_bytes"
        ),
    }


def enrich_resolved_hit_for_direct_use(
    hit: dict[str, Any],
    *,
    availability_model: dict[str, Any] | None,
) -> None:
    range_value = hit.get("range")
    text = range_value.get("text") if isinstance(range_value, dict) else None
    raw_citation = hit.get("citation")
    citation = raw_citation if isinstance(raw_citation, dict) else None
    canonical_range = source_range_projection(
        citation.get("canonical_range") if citation else None
    )
    citation_source_range = source_range_projection(
        citation.get("source_range") if citation else None
    )
    live_repo_address = (
        citation.get("live_repo_address")
        if citation and isinstance(citation.get("live_repo_address"), dict)
        else None
    )
    range_ref_projection = (
        source_range_projection(hit.get("range_ref"))
        if hit.get("range_status") == "resolved"
        else None
    )
    range_projection = source_range_projection(range_value)
    candidates = [
        citation_source_range,
        range_ref_projection,
        canonical_range,
        range_projection,
    ]
    source_range = next(
        (candidate for candidate in candidates if has_range_identity(candidate)),
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
        source_line_range = line_range(
            live_repo_address.get("start_line"),
            live_repo_address.get("end_line"),
        )
    if isinstance(source_range, dict):
        source_path = first_not_none(
            source_path,
            source_range.get("source_file_path"),
            source_range.get("file_path"),
            hit.get("path"),
        )
        source_line_range = source_line_range or line_range(
            first_not_none(
                source_range.get("source_start_line"),
                source_range.get("start_line"),
            ),
            first_not_none(
                source_range.get("source_end_line"),
                source_range.get("end_line"),
            ),
        )
        artifact_path = first_not_none(
            source_range.get("artifact_path"),
            source_range.get("file_path"),
        )
        artifact_line_range = line_range(
            first_not_none(
                source_range.get("artifact_start_line"),
                source_range.get("start_line"),
            ),
            first_not_none(
                source_range.get("artifact_end_line"),
                source_range.get("end_line"),
            ),
        )
        artifact_role = source_range.get("artifact_role")
    if source_path is None:
        source_path = hit.get("path")

    hit["text_excerpt"] = (
        text[:TEXT_EXCERPT_MAX_CHARS] if isinstance(text, str) else None
    )
    hit["text_truncated"] = (
        isinstance(text, str) and len(text) > TEXT_EXCERPT_MAX_CHARS
    )
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
    hit["citation_verified"] = (
        hit.get("citation_status") == "resolved"
        and isinstance(hit.get("citation_id"), str)
    )
    hit["availability"] = {
        "snapshot_status": (
            availability_model.get("status")
            if isinstance(availability_model, dict)
            else "unknown"
        ),
        "artifact": artifact_availability(
            availability_model,
            str(artifact_role or "canonical_md"),
        ),
        "index_artifact": artifact_availability(
            availability_model,
            "sqlite_index",
        ),
    }
    hit["freshness"] = (
        availability_model.get("freshness")
        if isinstance(availability_model, dict)
        else None
    )


def empty_source_citation_projection(
    status: str = "unavailable",
) -> dict[str, Any]:
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
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }


def project_source_citations(resolved_evidence: Any) -> dict[str, Any]:
    if not isinstance(resolved_evidence, dict):
        return empty_source_citation_projection()
    hits = resolved_evidence.get("hits")
    hit_list = [
        hit
        for hit in (hits if isinstance(hits, list) else [])
        if isinstance(hit, dict)
    ]
    items = [_source_citation_item(ordinal, hit) for ordinal, hit in enumerate(hit_list)]
    citation_count = sum(item["citation_resolved"] for item in items)
    range_unresolved_count = sum(
        item["range_status"] != "resolved" for item in items
    )
    citation_unresolved_count = len(items) - citation_count
    unresolved_count = sum(
        item["range_status"] != "resolved" or not item["citation_resolved"]
        for item in items
    )
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
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }


def _source_citation_item(ordinal: int, hit: dict[str, Any]) -> dict[str, Any]:
    range_value = hit.get("range")
    text = range_value.get("text") if isinstance(range_value, dict) else None
    raw_citation = hit.get("citation")
    citation = raw_citation if isinstance(raw_citation, dict) else None
    citation_range = source_range_projection(
        citation.get("canonical_range") if citation else None
    )
    citation_source_range = source_range_projection(
        citation.get("source_range") if citation else None
    )
    live_repo_address = (
        citation.get("live_repo_address")
        if citation and isinstance(citation.get("live_repo_address"), dict)
        else None
    )
    range_ref_projection = (
        source_range_projection(hit.get("range_ref"))
        if hit.get("range_status") == "resolved"
        else None
    )
    range_projection = source_range_projection(range_value)
    candidates = [
        citation_source_range,
        range_ref_projection,
        citation_range,
        range_projection,
    ]
    source_range = next(
        (candidate for candidate in candidates if has_range_identity(candidate)),
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
    citation_resolved = (
        citation_status == "resolved"
        and isinstance(citation_id, str)
        and _CITATION_ID_RE.fullmatch(citation_id) is not None
    )
    return {
        "ordinal": ordinal,
        "chunk_id": hit.get("chunk_id"),
        "path": hit.get("path"),
        "range_status": range_status,
        "range_ref_source": hit.get("range_ref_source"),
        "source_range": source_range,
        "text_excerpt": (
            text[:TEXT_EXCERPT_MAX_CHARS] if isinstance(text, str) else None
        ),
        "text_truncated": (
            isinstance(text, str) and len(text) > TEXT_EXCERPT_MAX_CHARS
        ),
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
    }
