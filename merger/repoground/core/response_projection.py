"""Compact-by-default projection for RepoGround read-only frontdoor responses.

Symbol lookup, call navigation and retrieval all embed the same snapshot-wide
diagnostics on every call: a full per-role availability inventory, graph
availability internals, and fixed forbidden-operation / non-claim catalogs.
None of that varies with the query, so repeating it in full on every hit
overfetches. This module keeps the compaction in one place: the fail-closed
evidence a caller actually needs by default -- freshness status, commit
identity, actionable role/graph gaps, explicit non-claims, and the essential
read-only mutation boundary -- stays visible, while the full diagnostic
inventory remains available behind ``verbose``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

MUTATION_BOUNDARY_REF = "repobrief.mutation_boundary.read_only_frontdoor.v1"
DOES_NOT_ESTABLISH_REF = "repobrief.does_not_establish.default.v1"
COMPACT_PROJECTION = "repobrief.read_response.compact.v1"

# Role availability values that are normal/expected per call; anything
# else (missing_required, invalid, blocked_by_*, degraded, or a "missing"
# recommended artifact) is a gap and stays visible even in compact mode.
_GOOD_ROLE_AVAILABILITY = {"available", "not_applicable", "profile_excluded"}
_RECOMMENDED = "recommended"
_GOOD_GRAPH_STATUS = {"available", "profile_excluded"}
_CRITICAL_FORBIDDEN_OPERATIONS = {
    "secret_read",
    "snapshot_create_side_effect",
}


def _coerce_manifest_path(manifest_path: str | Path) -> Path:
    return Path(manifest_path).expanduser().resolve()


def _normalize_commit_identity(value: Any) -> dict[str, Any] | None:
    """Normalize commit values without accepting structurally empty identities."""
    if isinstance(value, str) and value:
        return {"repositories": [{"git_commit": value}]}
    if not isinstance(value, dict):
        return None
    repositories = value.get("repositories")
    if isinstance(repositories, list):
        normalized: list[dict[str, str]] = []
        for repo_entry in repositories:
            if not isinstance(repo_entry, dict):
                continue
            git_commit = repo_entry.get("git_commit")
            if not isinstance(git_commit, str) or not git_commit:
                continue
            identity = {"git_commit": git_commit}
            repo = repo_entry.get("repo")
            if isinstance(repo, str) and repo:
                identity["repo"] = repo
            normalized.append(identity)
        return {"repositories": normalized} if normalized else None
    git_commit = value.get("git_commit")
    if isinstance(git_commit, str) and git_commit:
        identity: dict[str, Any] = {"git_commit": git_commit}
        repo = value.get("repo")
        if isinstance(repo, str) and repo:
            identity["repo"] = repo
        return {"repositories": [identity]}
    return None


def compact_freshness(
    freshness: Any,
    manifest_path: str | Path | None = None,
) -> dict[str, Any]:
    """Keep freshness and the commit identity bound to that same freshness read.

    ``manifest_path`` is accepted for call-site compatibility but is never read
    here. Re-reading the manifest during projection could mix freshness evidence
    from one snapshot revision with commit provenance from a later replacement.
    """
    del manifest_path
    status = freshness.get("status") if isinstance(freshness, dict) else None
    status = status if isinstance(status, str) else "unknown"
    identity = None
    if isinstance(freshness, dict):
        identity = _normalize_commit_identity(
            freshness.get("commit_identity")
            or freshness.get("commit")
            or freshness.get("git_commit")
        )
    compact: dict[str, Any] = {"status": status, "commit_identity": identity}
    if status != "fresh" and isinstance(freshness, dict):
        if freshness.get("reason") is not None:
            compact["reason"] = freshness["reason"]
        if freshness.get("age_seconds") is not None:
            compact["age_seconds"] = freshness["age_seconds"]
    return compact


def compact_graph_availability(graph_model: Any) -> dict[str, Any]:
    status = graph_model.get("status") if isinstance(graph_model, dict) else None
    status = status if isinstance(status, str) else "unknown"
    compact: dict[str, Any] = {"status": status}
    if (
        status not in _GOOD_GRAPH_STATUS
        and isinstance(graph_model, dict)
        and graph_model.get("reason") is not None
    ):
        compact["reason"] = graph_model["reason"]
    return compact


def compact_role_gaps(artifacts: Any) -> list[dict[str, Any]]:
    """Keep only actionable role gaps while preserving their requirement class."""
    if not isinstance(artifacts, list):
        return []
    gaps = []
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        availability = artifact.get("availability")
        requirement = artifact.get("requirement")
        if availability in _GOOD_ROLE_AVAILABILITY:
            continue
        if availability == "missing" and requirement not in {"required", _RECOMMENDED}:
            continue
        gap: dict[str, Any] = {
            "role": artifact.get("role"),
            "availability": availability,
        }
        if isinstance(requirement, str):
            gap["requirement"] = requirement
        if artifact.get("reason") is not None:
            gap["reason"] = artifact["reason"]
        gaps.append(gap)
    return gaps


def compact_availability(
    availability_model: Any,
    manifest_path: str | Path,
) -> dict[str, Any]:
    if not isinstance(availability_model, dict):
        return {
            "status": "unknown",
            "freshness": compact_freshness(None, manifest_path),
            "graph_availability": {"status": "unknown"},
            "gaps": [],
        }
    compact: dict[str, Any] = {
        "status": availability_model.get("status", "unknown"),
        "freshness": compact_freshness(
            availability_model.get("freshness"), manifest_path
        ),
        "graph_availability": compact_graph_availability(
            availability_model.get("graph_availability")
        ),
        "gaps": compact_role_gaps(availability_model.get("artifacts")),
    }
    if availability_model.get("profile") is not None:
        compact["profile"] = availability_model["profile"]
    if availability_model.get("error") is not None:
        compact["error"] = availability_model["error"]
    if availability_model.get("error_code") is not None:
        compact["error_code"] = availability_model["error_code"]
    if availability_model.get("reason") is not None:
        compact["reason"] = availability_model["reason"]
    return compact


def compact_mutation_boundary(boundary: Any) -> dict[str, Any]:
    """Project mutation evidence without manufacturing a read-only conclusion."""
    if not isinstance(boundary, dict):
        return {
            "ref": MUTATION_BOUNDARY_REF,
            "writes": None,
            "read_only": None,
            "status": "unknown",
            "reason": "mutation_boundary_invalid",
        }

    raw_ref = boundary.get("ref")
    ref = raw_ref if isinstance(raw_ref, str) and raw_ref else MUTATION_BOUNDARY_REF
    writes = boundary.get("writes")
    if not isinstance(writes, list):
        return {
            "ref": ref,
            "writes": None,
            "read_only": None,
            "status": "unknown",
            "reason": "writes_not_explicit_list",
        }

    normalized_writes = list(writes)
    compact: dict[str, Any] = {
        "ref": ref,
        "writes": normalized_writes,
        "read_only": not normalized_writes,
    }
    if isinstance(boundary.get("read_paths_do_not_refresh"), bool):
        compact["read_paths_do_not_refresh"] = boundary["read_paths_do_not_refresh"]
    if isinstance(boundary.get("not_reachable_from_snapshot_create"), bool):
        compact["not_reachable_from_snapshot_create"] = boundary[
            "not_reachable_from_snapshot_create"
        ]

    forbidden = boundary.get("forbidden_operations")
    if isinstance(forbidden, list):
        critical_forbidden = [
            operation
            for operation in forbidden
            if operation in _CRITICAL_FORBIDDEN_OPERATIONS
        ]
        if critical_forbidden:
            compact["forbidden_operations"] = critical_forbidden
    return compact


def compact_does_not_establish(items: Any) -> dict[str, Any]:
    """Keep explicit non-claims visible; a bare opaque reference is insufficient."""
    if isinstance(items, dict) and isinstance(items.get("items"), list):
        return {
            "ref": items.get("ref") or DOES_NOT_ESTABLISH_REF,
            "items": list(items["items"]),
        }
    values = list(items) if isinstance(items, (list, tuple)) else []
    return {"ref": DOES_NOT_ESTABLISH_REF, "items": values}


_CALL_NAVIGATION_KINDS = {
    "repobrief.call_callers",
    "repobrief.call_callees",
}


def _copy_fields(value: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {field: value[field] for field in fields if field in value}


def _copy_nonempty_fields(value: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    compact = _copy_fields(value, fields)
    return {
        field: item
        for field, item in compact.items()
        if item is not None and item != [] and item != {}
    }


def _compact_symbol(value: Any) -> dict[str, Any] | None:
    """Keep stable symbol identity and its source address, not duplicate metadata."""
    if not isinstance(value, dict):
        return None
    return _copy_fields(
        value,
        (
            "id",
            "name",
            "qualified_name",
            "kind",
            "path",
            "start_line",
            "end_line",
            "range_ref",
        ),
    )


def _compact_artifact_descriptor(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return _copy_fields(value, ("role", "contract", "sha256"))


def _compact_call_graph_metadata(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return _copy_fields(
        value,
        (
            "call_count",
            "evidence_counts",
            "resolution_counts",
            "skipped_files_count",
        ),
    )


def _compact_call_graph_coverage(value: Any) -> dict[str, Any] | None:
    """Preserve completeness/confidence boundaries without diagnostic histograms."""
    if not isinstance(value, dict):
        return None
    compact = _copy_fields(
        value,
        (
            "scope",
            "completeness",
            "reason",
            "resolved_call_edges",
            "total_call_edges",
            "resolved_ratio",
            "skipped_files_count",
            "model_scope",
            "confidence_model",
            "does_not_establish",
        ),
    )
    profiles = value.get("task_profile_confidence")
    if isinstance(profiles, dict):
        compact_profiles: dict[str, Any] = {}
        for profile, confidence in profiles.items():
            if not isinstance(profile, str) or not isinstance(confidence, dict):
                continue
            compact_profiles[profile] = _copy_fields(
                confidence,
                ("status", "minimum_resolved_ratio"),
            )
        compact["task_profile_confidence"] = compact_profiles
    return compact


def _compact_resolved_call_site(value: Any) -> dict[str, Any]:
    """Keep the bounded S1 edge proof; the grouped symbol carries caller/callee identity."""
    return _copy_nonempty_fields(
        value,
        (
            "path",
            "range_ref",
            "callee_expression",
            "evidence_level",
            "resolution_status",
            "resolution_reason",
            "relation_type",
            "resolved_target_ids",
        ),
    )


def _compact_unresolved_call_site(
    value: Any,
    *,
    keep_caller_identity: bool,
) -> dict[str, Any]:
    """Keep S0 location and why it was not promoted to a resolved graph edge."""
    fields = [
        "path",
        "range_ref",
        "callee_expression",
        "evidence_level",
        "resolution_status",
        "resolution_reason",
        "relation_type",
        "relation_to_selected_target",
        "candidate_target_ids",
    ]
    if keep_caller_identity:
        fields.extend(("caller_symbol_id", "caller_qualified_name"))
    return _copy_nonempty_fields(value, tuple(fields))


def _compact_callers(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    callers: list[dict[str, Any]] = []
    for caller in value:
        if not isinstance(caller, dict):
            continue
        compact = _copy_fields(
            caller,
            (
                "caller_symbol_id",
                "caller_qualified_name",
                "caller_kind",
                "caller_scope",
                "path",
                "call_site_count",
            ),
        )
        compact["caller_symbol"] = _compact_symbol(caller.get("caller_symbol"))
        sites = caller.get("call_sites")
        compact["call_sites"] = (
            [_compact_resolved_call_site(site) for site in sites if isinstance(site, dict)]
            if isinstance(sites, list)
            else []
        )
        callers.append(compact)
    return callers


def _compact_callees(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    callees: list[dict[str, Any]] = []
    for callee in value:
        if not isinstance(callee, dict):
            continue
        compact = _copy_fields(callee, ("call_site_count", "relation_types"))
        compact["callee_symbol"] = _compact_symbol(callee.get("callee_symbol"))
        sites = callee.get("call_sites")
        compact["call_sites"] = (
            [_compact_resolved_call_site(site) for site in sites if isinstance(site, dict)]
            if isinstance(sites, list)
            else []
        )
        callees.append(compact)
    return callees


def compact_call_navigation(result: Any) -> dict[str, Any]:
    """Project callers/callees to decision evidence while leaving diagnostics verbose-only."""
    if not isinstance(result, dict) or result.get("kind") not in _CALL_NAVIGATION_KINDS:
        return dict(result) if isinstance(result, dict) else {}

    compact = dict(result)
    for key in ("symbol_index", "call_graph"):
        if key in compact:
            compact[key] = _compact_artifact_descriptor(compact.get(key))
    if "call_graph_metadata" in compact:
        compact["call_graph_metadata"] = _compact_call_graph_metadata(
            compact.get("call_graph_metadata")
        )
    if "call_graph_coverage" in compact:
        compact["call_graph_coverage"] = _compact_call_graph_coverage(
            compact.get("call_graph_coverage")
        )

    if compact.get("kind") == "repobrief.call_callers":
        if "target_symbol" in compact:
            compact["target_symbol"] = _compact_symbol(compact.get("target_symbol"))
        candidates = compact.get("target_candidates")
        if isinstance(candidates, list):
            compact["target_candidates"] = [
                symbol
                for candidate in candidates
                if (symbol := _compact_symbol(candidate)) is not None
            ]
        compact["callers"] = _compact_callers(compact.get("callers"))
        unresolved = compact.get("unresolved_references")
        compact["unresolved_references"] = (
            [
                _compact_unresolved_call_site(site, keep_caller_identity=True)
                for site in unresolved
                if isinstance(site, dict)
            ]
            if isinstance(unresolved, list)
            else []
        )
    else:
        if "caller_symbol" in compact:
            compact["caller_symbol"] = _compact_symbol(compact.get("caller_symbol"))
        candidates = compact.get("caller_candidates")
        if isinstance(candidates, list):
            compact["caller_candidates"] = [
                symbol
                for candidate in candidates
                if (symbol := _compact_symbol(candidate)) is not None
            ]
        compact["callees"] = _compact_callees(compact.get("callees"))
        unresolved = compact.get("unresolved_call_sites")
        compact["unresolved_call_sites"] = (
            [
                _compact_unresolved_call_site(site, keep_caller_identity=False)
                for site in unresolved
                if isinstance(site, dict)
            ]
            if isinstance(unresolved, list)
            else []
        )
    return compact


def project_read_result(
    result: dict[str, Any],
    manifest_path: str | Path,
    *,
    verbose: bool = False,
) -> dict[str, Any]:
    """Project a read-only frontdoor result to its compact default shape.

    ``verbose=True`` returns ``result`` unchanged. ``verbose=False`` leaves
    status, truncation, navigable symbol/range evidence and explicit non-claim
    semantics visible while collapsing repeated inventories and call-graph
    diagnostics that remain available through the verbose view.
    """
    if verbose or not isinstance(result, dict):
        return result
    path = _coerce_manifest_path(manifest_path)
    projected = dict(result)
    projected["projection"] = COMPACT_PROJECTION
    if projected.get("kind") in _CALL_NAVIGATION_KINDS:
        projected = compact_call_navigation(projected)
    if "availability" in projected:
        projected["availability"] = compact_availability(
            projected.get("availability"), path
        )
    if "freshness" in projected:
        availability = projected.get("availability")
        if isinstance(availability, dict) and "freshness" in availability:
            projected["freshness"] = availability["freshness"]
        else:
            projected["freshness"] = compact_freshness(
                projected.get("freshness"), path
            )
    if "mutation_boundary" in projected:
        projected["mutation_boundary"] = compact_mutation_boundary(
            projected.get("mutation_boundary")
        )
    if "does_not_establish" in projected:
        projected["does_not_establish"] = compact_does_not_establish(
            projected.get("does_not_establish")
        )
    return projected
