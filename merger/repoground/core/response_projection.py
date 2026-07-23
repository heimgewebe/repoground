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


def project_read_result(
    result: dict[str, Any],
    manifest_path: str | Path,
    *,
    verbose: bool = False,
) -> dict[str, Any]:
    """Project a read-only frontdoor result to its compact default shape.

    ``verbose=True`` returns ``result`` unchanged. ``verbose=False`` leaves
    hits, status, error detail, truncation and explicit non-claim semantics
    untouched while collapsing repeated availability and mutation inventories.
    """
    if verbose or not isinstance(result, dict):
        return result
    path = _coerce_manifest_path(manifest_path)
    projected = dict(result)
    projected["projection"] = COMPACT_PROJECTION
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
