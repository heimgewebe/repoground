"""Pure validation for Observed Call Overlay v1 (S2) artifacts.

Mirrors :mod:`merger.repoground.core.call_graph_validation` in shape and error
vocabulary, and adds the two checks that only exist because S2 is observed
rather than derived:

``run binding``
    every relation names the observation it was recorded under, and that
    observation names a command, an environment, a run identity and a source
    revision;

``static separation``
    an overlay never carries a static evidence level and never claims to
    resolve a static call site, so no consumer can read S2 as an upgrade of
    S0 or S1.
"""

from __future__ import annotations

from typing import Any, Mapping

from merger.repoground.architecture.observed_call_overlay_contract import (
    BINDING_REASONS,
    BINDING_STATUSES,
    MAX_SKIPPED_ERRORS,
    OBSERVED_EVIDENCE_LEVEL,
    OVERLAY_KIND,
    OVERLAY_VERSION,
    RELATION_TYPES,
    REQUIRED_NONCLAIMS,
)
from merger.repoground.core.citation_projection import (
    is_int_not_bool,
    is_non_empty_string,
    is_sha256,
)

OVERLAY_ROLE = "python_observed_call_overlay_json"
_EXIT_STATUSES = ("completed", "exited", "failed")
_BOUND_KINDS = ("class", "function", "async_function")


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


def identity_error(data: Any) -> dict[str, Any] | None:
    if not isinstance(data, dict) or data.get("kind") != OVERLAY_KIND:
        return error(
            "observed_call_overlay_invalid_kind",
            f"observed_call_overlay must be a {OVERLAY_KIND} object",
        )
    if data.get("version") != OVERLAY_VERSION:
        return error(
            "observed_call_overlay_version_unsupported",
            f"observed_call_overlay version must be {OVERLAY_VERSION}",
        )
    if not is_non_empty_string(data.get("run_id")) or not is_sha256(
        data.get("canonical_dump_index_sha256")
    ):
        return error(
            "observed_call_overlay_binding_invalid",
            "observed_call_overlay must carry run_id and canonical_dump_index_sha256",
        )
    if data.get("language") != "python":
        return error(
            "observed_call_overlay_language_invalid",
            "observed_call_overlay language must be python",
        )
    return None


def _environment_valid(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    required = ("python_version", "python_implementation", "platform", "executable")
    if not all(is_non_empty_string(value.get(field)) for field in required):
        return False
    seed = value.get("hash_randomization_seed")
    return seed is None or isinstance(seed, str)


def _source_revision_valid(value: Any) -> bool:
    """A relation that cannot name its revision is not observed evidence."""

    if not isinstance(value, dict) or value.get("vcs") != "git":
        return False
    commit = value.get("commit")
    dirty = value.get("dirty")
    status = value.get("status")
    if not isinstance(commit, str) or len(commit) != 40:
        return False
    if not all(char in "0123456789abcdef" for char in commit):
        return False
    if not isinstance(dirty, bool):
        return False
    return status == ("dirty" if dirty else "clean")


def observation_error(data: Mapping[str, Any]) -> dict[str, Any] | None:
    observation = data.get("observation")
    if not isinstance(observation, dict):
        return error(
            "observed_call_overlay_observation_invalid",
            "observed_call_overlay observation must be an object",
        )
    command = observation.get("command")
    if (
        not isinstance(command, list)
        or not command
        or not all(is_non_empty_string(item) for item in command)
    ):
        return error(
            "observed_call_overlay_command_invalid",
            "observed_call_overlay observation must name a non-empty command",
        )
    if observation.get("command_string") != " ".join(command):
        return error(
            "observed_call_overlay_command_string_mismatch",
            "observed_call_overlay command_string does not match command",
        )
    if not is_non_empty_string(observation.get("observation_run_id")):
        return error(
            "observed_call_overlay_run_identity_invalid",
            "observed_call_overlay observation must carry an observation_run_id",
        )
    if not is_non_empty_string(observation.get("observed_at")):
        return error(
            "observed_call_overlay_observed_at_invalid",
            "observed_call_overlay observation must carry observed_at",
        )
    if not _environment_valid(observation.get("environment")):
        return error(
            "observed_call_overlay_environment_invalid",
            "observed_call_overlay observation must describe its environment",
        )
    if not _source_revision_valid(observation.get("source_revision")):
        return error(
            "observed_call_overlay_source_revision_invalid",
            "observed_call_overlay observation must name a resolved source revision",
        )
    if not is_sha256(observation.get("observation_fingerprint_sha256")):
        return error(
            "observed_call_overlay_fingerprint_invalid",
            "observed_call_overlay observation fingerprint must be a sha256 digest",
        )
    return None


def model_error(data: Mapping[str, Any]) -> dict[str, Any] | None:
    if data.get("relation_types") != list(RELATION_TYPES):
        return error(
            "observed_call_overlay_relation_model_invalid",
            "observed_call_overlay relation_types are not the v1 model",
        )
    if data.get("binding_statuses") != list(BINDING_STATUSES):
        return error(
            "observed_call_overlay_binding_model_invalid",
            "observed_call_overlay binding_statuses are not the v1 model",
        )
    evidence_model = data.get("evidence_model")
    if (
        not isinstance(evidence_model, dict)
        or set(evidence_model) != {OBSERVED_EVIDENCE_LEVEL}
        or not is_non_empty_string(evidence_model.get(OBSERVED_EVIDENCE_LEVEL))
    ):
        return error(
            "observed_call_overlay_evidence_model_invalid",
            "observed_call_overlay evidence_model must define only S2 semantics",
        )
    outcome = data.get("execution_outcome")
    if (
        not isinstance(outcome, dict)
        or outcome.get("exit_status") not in _EXIT_STATUSES
        or not (
            outcome.get("exit_code") is None or is_int_not_bool(outcome.get("exit_code"))
        )
        or not is_int_not_bool(outcome.get("observed_frame_event_count"))
        or outcome["observed_frame_event_count"] < 0
    ):
        return error(
            "observed_call_overlay_execution_outcome_invalid",
            "observed_call_overlay execution_outcome is invalid",
        )
    if not is_non_empty_string(data.get("absence_semantics")):
        return error(
            "observed_call_overlay_absence_semantics_missing",
            "observed_call_overlay must state that absence is not dead code",
        )
    nonclaims = data.get("does_not_establish")
    if not _string_list_valid(nonclaims) or not set(REQUIRED_NONCLAIMS).issubset(
        nonclaims
    ):
        return error(
            "observed_call_overlay_nonclaims_invalid",
            "observed_call_overlay does_not_establish is incomplete",
        )
    return None


def _endpoint_runtime_valid(
    row: Mapping[str, Any], prefix: str, *, optional_path: bool
) -> bool:
    """Check the raw runtime coordinates every endpoint carries."""

    status = row.get(f"{prefix}_binding_status")
    reason = row.get(f"{prefix}_binding_reason")
    if status not in BINDING_STATUSES or reason not in BINDING_REASONS:
        return False
    if not is_non_empty_string(row.get(f"{prefix}_runtime_name")):
        return False
    first_line = row.get(f"{prefix}_runtime_first_line")
    if not is_int_not_bool(first_line) or first_line < 0:
        return False
    path = row.get(f"{prefix}_path")
    if path is None:
        # Only a caller may lack a path, and only because it is not repo-local.
        return optional_path and status == "unbound"
    return is_non_empty_string(path)


def _endpoint_symbol_valid(row: Mapping[str, Any], prefix: str) -> bool:
    """Check that symbol identity is present exactly when the endpoint bound."""

    status = row.get(f"{prefix}_binding_status")
    symbol_id = row.get(f"{prefix}_symbol_id")
    qualified_name = row.get(f"{prefix}_qualified_name")
    kind = row.get(f"{prefix}_kind")
    start = row.get(f"{prefix}_start_line")
    end = row.get(f"{prefix}_end_line")
    if status == "bound":
        return (
            is_non_empty_string(symbol_id)
            and is_non_empty_string(qualified_name)
            and kind in _BOUND_KINDS
            and is_int_not_bool(start)
            and is_int_not_bool(end)
            and start >= 1
            and end >= start
        )
    if symbol_id is not None or qualified_name is not None:
        return False
    if start is not None or end is not None:
        return False
    if status == "module_scope":
        return kind == "module" and row.get(f"{prefix}_binding_reason") == "module_frame"
    return kind is None


def _endpoint_valid(row: Mapping[str, Any], prefix: str, *, optional_path: bool) -> bool:
    return _endpoint_runtime_valid(
        row, prefix, optional_path=optional_path
    ) and _endpoint_symbol_valid(row, prefix)


def relation_record_is_valid(row: Any) -> bool:
    """An S2 relation is well formed only if it stays an S2 relation."""

    if not isinstance(row, dict):
        return False
    if row.get("relation_type") not in RELATION_TYPES:
        return False
    # Separation: an overlay record may never carry a static evidence level.
    if row.get("evidence_level") != OBSERVED_EVIDENCE_LEVEL:
        return False
    if not is_non_empty_string(row.get("observation_run_id")):
        return False
    count = row.get("observed_call_count")
    if not is_int_not_bool(count) or count < 1:
        return False
    if not _call_site_valid(row):
        return False
    return _endpoint_valid(row, "caller", optional_path=True) and _endpoint_valid(
        row, "callee", optional_path=False
    )


def _call_site_valid(row: Mapping[str, Any]) -> bool:
    """A call site is citable only when the calling frame has a repository path."""

    call_site_line = row.get("call_site_line")
    call_site_range_ref = row.get("call_site_range_ref")
    caller_path = row.get("caller_path")
    if call_site_line is None:
        return call_site_range_ref is None
    if not is_int_not_bool(call_site_line) or call_site_line < 1:
        return False
    if caller_path is None:
        # A line number without a file is not addressable evidence.
        return False
    return call_site_range_ref == f"file:{caller_path}#L{call_site_line}-L{call_site_line}"


def records_error(data: Mapping[str, Any]) -> dict[str, Any] | None:
    relations = data.get("relations")
    if not isinstance(relations, list):
        return error(
            "observed_call_overlay_relations_invalid",
            "observed_call_overlay relations must be an array",
        )
    observation_run_id = data.get("observation", {}).get("observation_run_id")
    for position, row in enumerate(relations):
        if not relation_record_is_valid(row):
            return error(
                "observed_call_overlay_relation_record_invalid",
                f"observed_call_overlay relation at index {position} is invalid",
            )
        if row["observation_run_id"] != observation_run_id:
            return error(
                "observed_call_overlay_relation_run_binding_mismatch",
                (
                    f"observed_call_overlay relation at index {position} is not bound "
                    "to the document observation_run_id"
                ),
            )
    if data.get("relation_count") != len(relations):
        return error(
            "observed_call_overlay_relation_count_invalid",
            "observed_call_overlay relation_count does not match relations",
        )
    return None


def counts_error(data: Mapping[str, Any]) -> dict[str, Any] | None:
    relations = data["relations"]
    binding_counts = data.get("callee_binding_counts")
    if (
        not isinstance(binding_counts, dict)
        or set(binding_counts) != set(BINDING_STATUSES)
        or not all(
            is_int_not_bool(value) and value >= 0 for value in binding_counts.values()
        )
    ):
        return error(
            "observed_call_overlay_callee_binding_counts_invalid",
            "observed_call_overlay callee_binding_counts is invalid",
        )
    actual = {status: 0 for status in BINDING_STATUSES}
    for row in relations:
        actual[row["callee_binding_status"]] += 1
    if binding_counts != actual:
        return error(
            "observed_call_overlay_callee_binding_counts_mismatch",
            "observed_call_overlay callee_binding_counts does not match relations",
        )
    observed_total = sum(row["observed_call_count"] for row in relations)
    if data.get("observed_call_total") != observed_total:
        return error(
            "observed_call_overlay_observed_call_total_mismatch",
            "observed_call_overlay observed_call_total does not match relations",
        )
    fully_bound = sum(
        1
        for row in relations
        if row["callee_binding_status"] == "bound"
        and row["caller_binding_status"] in ("bound", "module_scope")
    )
    if data.get("fully_bound_relation_count") != fully_bound:
        return error(
            "observed_call_overlay_fully_bound_count_mismatch",
            "observed_call_overlay fully_bound_relation_count does not match relations",
        )
    total = data.get("observed_relation_total_count")
    truncated = data.get("relations_truncated")
    if (
        not is_int_not_bool(total)
        or total < len(relations)
        or not isinstance(truncated, bool)
        or truncated != (total > len(relations))
    ):
        return error(
            "observed_call_overlay_truncation_invalid",
            "observed_call_overlay truncation counters are inconsistent",
        )
    return _parse_diagnostics_error(data)


def _parse_diagnostics_error(data: Mapping[str, Any]) -> dict[str, Any] | None:
    skipped_files_count = data.get("skipped_files_count")
    skipped_errors = data.get("skipped_errors")
    total = data.get("skipped_errors_total_count")
    truncated = data.get("skipped_errors_truncated")
    if (
        not is_int_not_bool(skipped_files_count)
        or skipped_files_count < 0
        or not isinstance(skipped_errors, list)
        or len(skipped_errors) > MAX_SKIPPED_ERRORS
        or not all(isinstance(item, str) for item in skipped_errors)
        or not is_int_not_bool(total)
        or total < len(skipped_errors)
        or not isinstance(truncated, bool)
        or truncated != (total > len(skipped_errors))
    ):
        return error(
            "observed_call_overlay_parse_diagnostics_invalid",
            "observed_call_overlay parse diagnostics are invalid",
        )
    return None


def static_separation_error(
    overlay: Mapping[str, Any],
    call_graph: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Refuse an overlay that has been merged into, or over, the static graph.

    The static graph and the overlay are different artifacts with different
    kinds. Sharing a ``run_id`` and canonical binding is required; sharing a
    record array is not allowed.
    """

    if "calls" in overlay or "resolution_statuses" in overlay:
        return error(
            "observed_call_overlay_static_fields_present",
            "observed_call_overlay must not carry static call-graph fields",
        )
    if any(
        row.get("evidence_level") in ("S0", "S1") for row in overlay.get("relations", [])
    ):
        return error(
            "observed_call_overlay_static_evidence_level_present",
            "observed_call_overlay relations must not carry static evidence levels",
        )
    if call_graph is None:
        return None
    if any(
        row.get("evidence_level") == OBSERVED_EVIDENCE_LEVEL
        for row in call_graph.get("calls", [])
    ):
        return error(
            "python_call_graph_observed_evidence_present",
            "python_call_graph calls must not carry observed S2 evidence",
        )
    if call_graph.get("canonical_dump_index_sha256") != overlay.get(
        "canonical_dump_index_sha256"
    ):
        return error(
            "observed_call_overlay_canonical_binding_mismatch",
            (
                "observed_call_overlay canonical_dump_index_sha256 does not match "
                "the static call graph it is read next to"
            ),
        )
    return None


def validate_observed_call_overlay(
    data: Any,
    call_graph: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Return the first validation error, or ``None`` when the overlay holds."""

    for check in (identity_error,):
        failure = check(data)
        if failure is not None:
            return failure
    for check in (observation_error, model_error, records_error, counts_error):
        failure = check(data)
        if failure is not None:
            return failure
    return static_separation_error(data, call_graph)
