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

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

MUTATION_BOUNDARY_REF = "repobrief.mutation_boundary.read_only_frontdoor.v1"
DOES_NOT_ESTABLISH_REF = "repobrief.does_not_establish.default.v1"

# Role availability values that are normal/expected per call; anything
# else (missing_required, invalid, blocked_by_*, degraded, or a "missing"
# recommended artifact) is a gap and stays visible even in compact mode.
_GOOD_ROLE_AVAILABILITY = {"available", "not_applicable", "profile_excluded"}
_RECOMMENDED = "recommended"
_GOOD_GRAPH_STATUS = {"available", "not_generated", "profile_excluded"}


def _coerce_manifest_path(manifest_path: str | Path) -> Path:
    return Path(manifest_path).expanduser().resolve()


def _read_manifest(manifest_path: str | Path) -> dict[str, Any] | None:
    path = _coerce_manifest_path(manifest_path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _commit_entries_from_manifest(manifest: dict[str, Any] | None) -> tuple[tuple[str, str | None], ...]:
    if manifest is None:
        return ()
    provenance = manifest.get("snapshot_provenance")
    repos = provenance.get("repositories") if isinstance(provenance, dict) else None
    if not isinstance(repos, list):
        return ()
    identities: list[tuple[str, str | None]] = []
    for repo in repos:
        if not (
            isinstance(repo, dict)
            and repo.get("provenance_status") == "present"
            and isinstance(repo.get("git_commit"), str)
            and repo.get("git_commit")
        ):
            continue
        name = repo.get("repo") or repo.get("name") or repo.get("path")
        identities.append(
            (
                repo["git_commit"],
                name if isinstance(name, str) and name else None,
            )
        )
    return tuple(identities)


@lru_cache(maxsize=128)
def _cached_commit_entries(
    path_text: str,
    device: int,
    inode: int,
    size: int,
    mtime_ns: int,
) -> tuple[tuple[str, str | None], ...]:
    """Read commit provenance once for one concrete on-disk manifest revision.

    The stat fields are intentionally part of the key: replacing or modifying
    the manifest produces a different cache entry without requiring a global
    manual invalidation protocol. The unused stat arguments encode file
    identity/revision in the cache key; only ``path_text`` is needed to read.
    """
    del device, inode, size, mtime_ns
    return _commit_entries_from_manifest(_read_manifest(Path(path_text)))


def _normalize_commit_identity(value: Any) -> dict[str, Any] | None:
    """Normalize legacy/synthetic commit values to one stable object shape."""
    if isinstance(value, str) and value:
        return {"repositories": [{"git_commit": value}]}
    if not isinstance(value, dict):
        return None
    repositories = value.get("repositories")
    if isinstance(repositories, list):
        normalized = [repo for repo in repositories if isinstance(repo, dict)]
        return {"repositories": normalized} if normalized else None
    git_commit = value.get("git_commit")
    if isinstance(git_commit, str) and git_commit:
        identity: dict[str, Any] = {"git_commit": git_commit}
        repo = value.get("repo")
        if isinstance(repo, str) and repo:
            identity["repo"] = repo
        return {"repositories": [identity]}
    return None


def commit_identity(manifest_path: str | Path) -> dict[str, Any] | None:
    """Return all present repository commit identities recorded by the bundle.

    The shape is stable for single- and multi-repository snapshots. ``None`` is
    returned rather than fabricating an identity when provenance is absent.
    Repeated reads of an unchanged manifest reuse stat-keyed provenance data
    instead of reparsing the full JSON file on every compact frontdoor call.
    """
    path = _coerce_manifest_path(manifest_path)
    try:
        stat = path.stat()
    except OSError:
        return None
    entries = _cached_commit_entries(
        str(path),
        stat.st_dev,
        stat.st_ino,
        stat.st_size,
        stat.st_mtime_ns,
    )
    if not entries:
        return None
    repositories = []
    for git_commit, repo in entries:
        identity: dict[str, Any] = {"git_commit": git_commit}
        if repo is not None:
            identity["repo"] = repo
        repositories.append(identity)
    return {"repositories": repositories}


def compact_freshness(freshness: Any, manifest_path: str | Path) -> dict[str, Any]:
    """Freshness status + stable commit identity; never silence non-fresh detail."""
    status = freshness.get("status") if isinstance(freshness, dict) else None
    status = status if isinstance(status, str) else "unknown"
    identity = None
    if isinstance(freshness, dict):
        identity = _normalize_commit_identity(
            freshness.get("commit_identity")
            or freshness.get("commit")
            or freshness.get("git_commit")
        )
    if identity is None:
        identity = commit_identity(manifest_path)
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
    if status not in _GOOD_GRAPH_STATUS and isinstance(graph_model, dict) and graph_model.get("reason"):
        compact["reason"] = graph_model["reason"]
    return compact


def compact_role_gaps(artifacts: Any) -> list[dict[str, Any]]:
    """Only the roles whose availability is not simply fine.

    Drops the always-repeated full per-role inventory while keeping any explicit
    actionable gap visible by default.
    """
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
        if artifact.get("reason") is not None:
            gap["reason"] = artifact["reason"]
        gaps.append(gap)
    return gaps


def compact_availability(availability_model: Any, manifest_path: str | Path) -> dict[str, Any]:
    if not isinstance(availability_model, dict):
        return {
            "status": "unknown",
            "freshness": compact_freshness(None, manifest_path),
            "graph_availability": {"status": "unknown"},
            "gaps": [],
        }
    compact: dict[str, Any] = {
        "status": availability_model.get("status", "unknown"),
        "freshness": compact_freshness(availability_model.get("freshness"), manifest_path),
        "graph_availability": compact_graph_availability(availability_model.get("graph_availability")),
        "gaps": compact_role_gaps(availability_model.get("artifacts")),
    }
    if availability_model.get("error") is not None:
        compact["error"] = availability_model["error"]
    if availability_model.get("error_code") is not None:
        compact["error_code"] = availability_model["error_code"]
    if availability_model.get("reason") is not None:
        compact["reason"] = availability_model["reason"]
    return compact


def compact_mutation_boundary(boundary: Any) -> dict[str, Any]:
    """Keep the essential read-only safety facts visible in compact mode."""
    source = boundary if isinstance(boundary, dict) else {}
    writes = source.get("writes")
    normalized_writes = list(writes) if isinstance(writes, list) else []
    ref = source.get("ref") or MUTATION_BOUNDARY_REF
    compact: dict[str, Any] = {
        "ref": ref,
        "writes": normalized_writes,
        "read_only": not normalized_writes,
    }
    if isinstance(source.get("read_paths_do_not_refresh"), bool):
        compact["read_paths_do_not_refresh"] = source["read_paths_do_not_refresh"]
    if isinstance(source.get("not_reachable_from_snapshot_create"), bool):
        compact["not_reachable_from_snapshot_create"] = source[
            "not_reachable_from_snapshot_create"
        ]
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
    if "availability" in projected:
        projected["availability"] = compact_availability(projected.get("availability"), path)
    if "freshness" in projected:
        availability = projected.get("availability")
        if isinstance(availability, dict) and "freshness" in availability:
            projected["freshness"] = availability["freshness"]
        else:
            projected["freshness"] = compact_freshness(projected.get("freshness"), path)
    if "mutation_boundary" in projected:
        projected["mutation_boundary"] = compact_mutation_boundary(
            projected.get("mutation_boundary")
        )
    if "does_not_establish" in projected:
        projected["does_not_establish"] = compact_does_not_establish(
            projected.get("does_not_establish")
        )
    return projected
