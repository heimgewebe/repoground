"""Pure validation for registered Python call-graph bundle artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from merger.repoground.architecture.call_graph_contract import (
    MAX_SKIPPED_ERRORS,
    REQUIRED_NONCLAIMS,
)
from merger.repoground.core.bundle_roles import artifact_list, read_json_object
from merger.repoground.core.citation_projection import (
    is_int_not_bool,
    is_non_empty_string,
    is_sha256,
)

CALL_GRAPH_KIND = "lenskit.python_call_graph"
CALL_GRAPH_VERSION = "1.0"
CALL_RESOLUTION_STATUSES = ("resolved", "candidate", "ambiguous", "unresolved")
CALL_EVIDENCE_LEVELS = ("S0", "S1")
CALL_RELATION_TYPES = ("calls", "constructs")
_CALLER_KINDS = ("module", "class", "function", "async_function")


def error(
    error_code: str,
    message: str,
    *,
    status: str = "invalid",
) -> dict[str, Any]:
    return {"status": status, "error_code": error_code, "error": message}


def _string_list_valid(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) == len(set(value))
        and all(is_non_empty_string(item) for item in value)
    )


def _position_fields_valid(row: dict[str, Any]) -> bool:
    numeric_fields = (
        ("start_line", 1),
        ("start_col", 0),
        ("end_line", 1),
        ("end_col", 0),
    )
    if not all(
        is_int_not_bool(row.get(field)) and row[field] >= minimum
        for field, minimum in numeric_fields
    ):
        return False
    return (
        row["end_line"] > row["start_line"]
        or (
            row["end_line"] == row["start_line"]
            and row["end_col"] >= row["start_col"]
        )
    )


def _caller_fields_valid(row: dict[str, Any]) -> bool:
    caller_scope = row.get("caller_scope")
    caller_kind = row.get("caller_kind")
    caller_start = row.get("caller_start_line")
    caller_end = row.get("caller_end_line")
    if caller_kind not in _CALLER_KINDS:
        return False
    if caller_scope == "module":
        return (
            row.get("caller_symbol_id") is None
            and row.get("caller_qualified_name") is None
            and caller_kind == "module"
            and caller_start is None
            and caller_end is None
        )
    if caller_scope != "symbol":
        return False
    return (
        is_non_empty_string(row.get("caller_symbol_id"))
        and is_non_empty_string(row.get("caller_qualified_name"))
        and caller_kind != "module"
        and is_int_not_bool(caller_start)
        and is_int_not_bool(caller_end)
        and caller_start >= 1
        and caller_end >= caller_start
        and caller_start <= row["start_line"] <= caller_end
    )


def _resolution_fields_valid(row: dict[str, Any]) -> bool:
    status = row.get("resolution_status")
    evidence = row.get("evidence_level")
    relation = row.get("relation_type")
    resolved = row.get("resolved_target_ids")
    candidates = row.get("candidate_target_ids")
    if status not in CALL_RESOLUTION_STATUSES:
        return False
    if evidence not in CALL_EVIDENCE_LEVELS or relation not in CALL_RELATION_TYPES:
        return False
    if not is_non_empty_string(row.get("resolution_reason")):
        return False
    if not _string_list_valid(resolved) or not _string_list_valid(candidates):
        return False
    if status == "resolved":
        return evidence == "S1" and len(resolved) == 1 and not candidates
    return evidence == "S0" and not resolved


def call_record_is_valid(row: Any) -> bool:
    if not isinstance(row, dict) or not is_non_empty_string(row.get("path")):
        return False
    if not _position_fields_valid(row):
        return False
    expected_range = f"file:{row['path']}#L{row['start_line']}-L{row['end_line']}"
    return (
        row.get("range_ref") == expected_range
        and is_non_empty_string(row.get("callee_expression"))
        and (
            row.get("simple_name") is None
            or is_non_empty_string(row.get("simple_name"))
        )
        and _caller_fields_valid(row)
        and _resolution_fields_valid(row)
    )


def _count_map_valid(value: Any, keys: tuple[str, ...]) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == set(keys)
        and all(is_int_not_bool(item) and item >= 0 for item in value.values())
    )


def identity_error(data: Any) -> dict[str, Any] | None:
    if not isinstance(data, dict) or data.get("kind") != CALL_GRAPH_KIND:
        return error(
            "python_call_graph_json_invalid_kind",
            f"python_call_graph_json must be a {CALL_GRAPH_KIND} object",
        )
    if data.get("version") != CALL_GRAPH_VERSION:
        return error(
            "python_call_graph_json_version_unsupported",
            f"python_call_graph_json version must be {CALL_GRAPH_VERSION}",
        )
    if not is_non_empty_string(data.get("run_id")) or not is_sha256(
        data.get("canonical_dump_index_sha256")
    ):
        return error(
            "python_call_graph_json_binding_invalid",
            "python_call_graph_json must carry run_id and canonical_dump_index_sha256",
        )
    if data.get("language") != "python":
        return error(
            "python_call_graph_language_invalid",
            "python_call_graph_json language must be python",
        )
    return None


def parse_diagnostics(data: dict[str, Any]) -> dict[str, Any]:
    """Project current and legacy parse diagnostics through one code path."""
    skipped_files_count = data.get("skipped_files_count")
    skipped_errors = data.get("skipped_errors")
    skipped_errors_total_count = data.get(
        "skipped_errors_total_count",
        skipped_files_count,
    )
    skipped_errors_truncated = data.get(
        "skipped_errors_truncated",
        (
            isinstance(skipped_errors, list)
            and is_int_not_bool(skipped_errors_total_count)
            and skipped_errors_total_count > len(skipped_errors)
        ),
    )
    return {
        "skipped_files_count": skipped_files_count,
        "skipped_errors": (
            list(skipped_errors)
            if isinstance(skipped_errors, list)
            else skipped_errors
        ),
        "skipped_errors_total_count": skipped_errors_total_count,
        "skipped_errors_truncated": skipped_errors_truncated,
    }


def model_error(data: dict[str, Any]) -> dict[str, Any] | None:
    if data.get("resolution_statuses") != list(CALL_RESOLUTION_STATUSES):
        return error(
            "python_call_graph_resolution_model_invalid",
            "python_call_graph_json resolution_statuses are not the v1 model",
        )
    if data.get("relation_types") != list(CALL_RELATION_TYPES):
        return error(
            "python_call_graph_relation_model_invalid",
            "python_call_graph_json relation_types are not the v1 model",
        )
    evidence_model = data.get("evidence_model")
    if (
        not isinstance(evidence_model, dict)
        or set(evidence_model) != set(CALL_EVIDENCE_LEVELS)
        or not all(is_non_empty_string(value) for value in evidence_model.values())
    ):
        return error(
            "python_call_graph_evidence_model_invalid",
            "python_call_graph_json evidence_model must define non-empty S0 and S1 semantics",
        )
    diagnostics = parse_diagnostics(data)
    if not _parse_diagnostics_valid(diagnostics):
        return error(
            "python_call_graph_parse_diagnostics_invalid",
            "python_call_graph_json parse diagnostics are invalid",
        )
    nonclaims = data.get("does_not_establish")
    if (
        not _string_list_valid(nonclaims)
        or not set(REQUIRED_NONCLAIMS).issubset(nonclaims)
    ):
        return error(
            "python_call_graph_nonclaims_invalid",
            "python_call_graph_json does_not_establish is incomplete",
        )
    return None


def _parse_diagnostics_valid(diagnostics: dict[str, Any]) -> bool:
    skipped_files_count = diagnostics["skipped_files_count"]
    skipped_errors = diagnostics["skipped_errors"]
    total_count = diagnostics["skipped_errors_total_count"]
    truncated = diagnostics["skipped_errors_truncated"]
    return (
        is_int_not_bool(skipped_files_count)
        and skipped_files_count >= 0
        and isinstance(skipped_errors, list)
        and len(skipped_errors) <= MAX_SKIPPED_ERRORS
        and all(isinstance(item, str) for item in skipped_errors)
        and is_int_not_bool(total_count)
        and total_count == skipped_files_count
        and total_count >= len(skipped_errors)
        and isinstance(truncated, bool)
        and truncated == (total_count > len(skipped_errors))
    )


def records_error(data: dict[str, Any]) -> dict[str, Any] | None:
    calls = data.get("calls")
    if not isinstance(calls, list):
        return error(
            "python_call_graph_calls_invalid",
            "python_call_graph_json calls must be an array",
        )
    for position, row in enumerate(calls):
        if not call_record_is_valid(row):
            return error(
                "python_call_graph_call_record_invalid",
                f"python_call_graph_json call record at index {position} is invalid",
            )
    if data.get("call_count") != len(calls):
        return error(
            "python_call_graph_call_count_invalid",
            "python_call_graph_json call_count does not match calls",
        )
    return None


def counts_error(data: dict[str, Any]) -> dict[str, Any] | None:
    count_specs = (
        ("resolution_counts", CALL_RESOLUTION_STATUSES, "resolution_status"),
        ("evidence_counts", CALL_EVIDENCE_LEVELS, "evidence_level"),
        ("relation_counts", CALL_RELATION_TYPES, "relation_type"),
    )
    calls = data["calls"]
    for field, keys, row_field in count_specs:
        counts = data.get(field)
        if not _count_map_valid(counts, keys):
            return error(
                f"python_call_graph_{field}_invalid",
                f"python_call_graph_json {field} is invalid",
            )
        actual = {key: 0 for key in keys}
        for row in calls:
            actual[row[row_field]] += 1
        if counts != actual:
            return error(
                f"python_call_graph_{field}_mismatch",
                f"python_call_graph_json {field} does not match calls",
            )
    return None


def manifest_binding_error(
    data: dict[str, Any],
    manifest_path: Path,
    *,
    manifest: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    manifest_payload = manifest if manifest is not None else read_json_object(
        manifest_path
    )
    manifest_run_id = manifest_payload.get("run_id")
    if (
        is_non_empty_string(manifest_run_id)
        and manifest_run_id != data["run_id"]
    ):
        return error(
            "python_call_graph_json_run_id_mismatch",
            "python_call_graph_json run_id does not match the bundle manifest run_id",
        )
    dump_index = next(
        (
            item
            for item in artifact_list(manifest_payload)
            if item.get("role") == "dump_index_json"
        ),
        None,
    )
    if (
        dump_index is not None
        and is_sha256(dump_index.get("sha256"))
        and dump_index["sha256"] != data["canonical_dump_index_sha256"]
    ):
        return error(
            "python_call_graph_json_canonical_binding_mismatch",
            (
                "python_call_graph_json canonical_dump_index_sha256 does not "
                "match the dump_index_json artifact"
            ),
        )
    return None
