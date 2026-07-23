from __future__ import annotations

import datetime
from pathlib import Path
from typing import Any, Mapping

from merger.repoground.core.snapshot_profiles import ARTIFACT_ORDER, PROFILE_ARTIFACT_RULES, REQ_EXCLUDED, REQ_NA, REQ_RECOMMENDED, REQ_REQUIRED
from merger.repoground.architecture.graph_index import load_graph_index
from merger.repoground.core.graph_degradation import (
    GRAPH_AVAILABILITY_STATUS_VALUES,
    GRAPH_DOES_NOT_ESTABLISH,
    graph_availability_degradation,
)

KIND = "repobrief.snapshot_availability"
VERSION = "v1"
AVAILABILITY_VALUES = ("available", "missing", "missing_required", "not_applicable", "profile_excluded", "degraded", "blocked_by_missing_dependency", "blocked_by_missing_provenance", "blocked_by_missing_source", "invalid")
FRESHNESS_VALUES = ("fresh", "stale", "unknown", "not_comparable")
DOES_NOT_ESTABLISH = ("truth", "correctness", "completeness", "runtime_behavior", "test_sufficiency", "regression_absence", "repo_understood", "claims_true", "forensic_ready", "freshness_against_remote", "merge_readiness")
GRAPH_AVAILABILITY_VALUES = GRAPH_AVAILABILITY_STATUS_VALUES
LINKED_SIDECAR_ROLES = {"post_emit_health_path": "post_emit_health", "bundle_surface_validation_path": "bundle_surface_validation", "surface_validation_path": "bundle_surface_validation", "export_safety_report_path": "export_safety_report"}


def _parse_created_at(value: Any) -> datetime.datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed.astimezone(datetime.timezone.utc)


def _safe_path(root: Path, raw_path: Any) -> Path | None:
    if not isinstance(raw_path, str) or not raw_path:
        return None
    candidate = (root / raw_path).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    return candidate


def _artifact_records(manifest_path: Path, manifest: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    root = manifest_path.parent
    records = {"bundle_manifest": [{"path": manifest_path.name, "file_exists": manifest_path.is_file(), "path_valid": True}]}
    artifacts = manifest.get("artifacts", [])
    if isinstance(artifacts, list):
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                continue
            role = artifact.get("role")
            if not isinstance(role, str) or not role:
                continue
            candidate = _safe_path(root, artifact.get("path"))
            records.setdefault(role, []).append({"path": artifact.get("path"), "file_exists": bool(candidate and candidate.is_file()), "path_valid": candidate is not None})
    links = manifest.get("links")
    if isinstance(links, dict):
        for key, role in LINKED_SIDECAR_ROLES.items():
            if role in records:
                continue
            candidate = _safe_path(root, links.get(key))
            if candidate is not None:
                records.setdefault(role, []).append({"path": links.get(key), "file_exists": candidate.is_file(), "path_valid": True, "from_link": key})
    return records


def _requirement_for(profile: str | None, role: str) -> str:
    if profile in PROFILE_ARTIFACT_RULES and role in PROFILE_ARTIFACT_RULES[profile]:
        return PROFILE_ARTIFACT_RULES[profile][role]
    if role == "bundle_manifest":
        return REQ_REQUIRED
    return "optional"


def _availability_for(requirement: str, records: list[dict[str, Any]]) -> tuple[str, str]:
    listed = bool(records)
    file_backed = any(record.get("file_exists") is True for record in records)
    invalid_path = any(record.get("path_valid") is False for record in records)
    if requirement == REQ_NA:
        return "not_applicable", "role is not applicable for this profile"
    if requirement == REQ_EXCLUDED:
        if listed:
            return "invalid", "profile-excluded role is present"
        return "profile_excluded", "role is excluded by this profile"
    if file_backed:
        return "available", "artifact is listed and file-backed"
    if listed and invalid_path:
        return "invalid", "artifact path is invalid or escapes the bundle root"
    if listed:
        return "blocked_by_missing_source", "artifact is listed but the file is missing"
    if requirement == REQ_REQUIRED:
        return "missing_required", "required artifact is absent"
    return "missing", "artifact is absent"



def _first_record(records: dict[str, list[dict[str, Any]]], role: str) -> dict[str, Any] | None:
    role_records = records.get(role, [])
    return role_records[0] if role_records else None


def _graph_record_state(record: dict[str, Any] | None) -> tuple[str, str]:
    if record is None:
        return "absent", "artifact is not listed"
    if record.get("path_valid") is False:
        return "invalid", "artifact path is invalid or escapes the bundle root"
    if record.get("file_exists") is not True:
        return "missing", "artifact is listed but the file is missing"
    return "present", "artifact is listed and file-backed"



def _complete_graph_availability(base: dict[str, Any], *, status: str, reason: str, load_status: str | None = None) -> dict[str, Any]:
    degradation = graph_availability_degradation(status, load_status=load_status, reason=reason)
    base.update({
        "status": status,
        "reason": reason,
        "retrieval_eligible": degradation["retrieval_eligible"],
        "degradation": degradation,
    })
    return base


def graph_availability_model(manifest_path: str | Path, manifest: Mapping[str, Any], *, profile: str | None = None) -> dict[str, Any]:
    """Report graph availability without promoting graph evidence to truth.

    This is a read-only snapshot projection. It may surface whether graph
    artifacts are present, stale, missing or profile-excluded, but it does not
    build graphs, refresh snapshots, or allow stale graphs to influence
    retrieval.
    """

    path = Path(manifest_path).expanduser().resolve()
    capabilities = manifest.get("capabilities") if isinstance(manifest.get("capabilities"), dict) else {}
    effective_profile = profile if profile is not None else capabilities.get("repobrief_profile")
    if not isinstance(effective_profile, str) or effective_profile not in PROFILE_ARTIFACT_RULES:
        effective_profile = None

    records = _artifact_records(path, manifest)
    graph_record = _first_record(records, "architecture_graph_json")
    index_record = _first_record(records, "graph_index_json")
    graph_state, graph_reason = _graph_record_state(graph_record)
    index_state, index_reason = _graph_record_state(index_record)

    base: dict[str, Any] = {
        "kind": "repobrief.graph_availability",
        "version": "v1",
        "profile": effective_profile,
        "availability_values": list(GRAPH_AVAILABILITY_VALUES),
        "architecture_graph": {
            "state": graph_state,
            "reason": graph_reason,
            "path": graph_record.get("path") if graph_record else None,
        },
        "graph_index": {
            "state": index_state,
            "reason": index_reason,
            "path": index_record.get("path") if index_record else None,
            "load_status": None,
        },
        "retrieval_eligible": False,
        "stale_graph_must_not_influence_retrieval": True,
        "does_not_establish": list(GRAPH_DOES_NOT_ESTABLISH),
    }

    if effective_profile == "public-share":
        return _complete_graph_availability(base, status="profile_excluded", reason="graph surfaces are excluded for public-share profile")

    if graph_record is None and index_record is None:
        return _complete_graph_availability(base, status="not_generated", reason="graph artifacts are not listed in the bundle manifest")

    if graph_state == "invalid" or index_state == "invalid":
        return _complete_graph_availability(base, status="invalid", reason="one or more graph artifact paths are invalid")

    if graph_state == "missing" or index_state == "missing":
        return _complete_graph_availability(base, status="blocked_by_missing_source", reason="one or more listed graph artifacts are missing on disk")

    if index_record is None:
        return _complete_graph_availability(base, status="not_generated", reason="graph index artifact is not listed")

    expected_sha = None
    links = manifest.get("links")
    if isinstance(links, dict) and isinstance(links.get("canonical_dump_index_sha256"), str):
        expected_sha = links["canonical_dump_index_sha256"]
    if not expected_sha:
        return _complete_graph_availability(base, status="blocked_by_missing_provenance", reason="canonical dump index sha256 is unavailable for graph staleness check")

    load_status = load_graph_index(path.parent, str(index_record.get("path")), expected_sha)
    graph_status = load_status.get("status")
    base["graph_index"]["load_status"] = graph_status
    if graph_status == "ok":
        _complete_graph_availability(base, status="available", reason="graph index is file-backed, schema-valid and provenance-coherent", load_status=graph_status)
    elif graph_status == "stale_or_mismatched":
        _complete_graph_availability(base, status="stale", reason="graph index canonical dump hash does not match this snapshot", load_status=graph_status)
    elif graph_status in {"not_found", "unreadable"}:
        _complete_graph_availability(base, status="blocked_by_missing_source", reason=f"graph index load status is {graph_status}", load_status=graph_status)
    elif graph_status == "validation_unavailable":
        _complete_graph_availability(base, status="validation_unavailable", reason="graph index validation is unavailable in this runtime", load_status=graph_status)
    else:
        _complete_graph_availability(base, status="invalid", reason=f"graph index load status is {graph_status}", load_status=graph_status)
    return base


def _commit_identity_from_present_repos(
    present_repos: list[Mapping[str, Any]],
) -> dict[str, Any] | None:
    repositories: list[dict[str, str]] = []
    for repo in present_repos:
        git_commit = repo.get("git_commit")
        if not isinstance(git_commit, str) or not git_commit:
            continue
        identity = {"git_commit": git_commit}
        name = repo.get("repo") or repo.get("name") or repo.get("path")
        if isinstance(name, str) and name:
            identity["repo"] = name
        repositories.append(identity)
    return {"repositories": repositories} if repositories else None


def snapshot_freshness_model(manifest: Mapping[str, Any], *, max_age_seconds: int | None = None, as_of: datetime.datetime | None = None) -> dict[str, Any]:
    created_at_raw = manifest.get("created_at")
    created_at = _parse_created_at(created_at_raw)
    snapshot_provenance = manifest.get("snapshot_provenance")
    repos = snapshot_provenance.get("repositories") if isinstance(snapshot_provenance, dict) else None
    repos = repos if isinstance(repos, list) else []
    present_repos = [repo for repo in repos if isinstance(repo, dict) and repo.get("provenance_status") == "present" and isinstance(repo.get("git_commit"), str) and repo.get("git_commit")]
    commit_identity = _commit_identity_from_present_repos(present_repos)
    result: dict[str, Any] = {"status": "unknown", "created_at": created_at_raw if isinstance(created_at_raw, str) else None, "age_seconds": None, "max_age_seconds": max_age_seconds, "as_of": None, "basis": "unknown", "snapshot_provenance_recorded": isinstance(snapshot_provenance, dict), "repository_count": len(repos), "present_repository_count": len(present_repos), "commit_identity": commit_identity, "reason": None}
    if created_at is None:
        result["reason"] = "missing_or_invalid_created_at"
        return result
    if not isinstance(snapshot_provenance, dict):
        result["reason"] = "blocked_by_missing_provenance"
        return result
    if not repos:
        result["reason"] = "blocked_by_missing_source"
        return result
    if not present_repos:
        result["reason"] = "blocked_by_missing_provenance"
        return result
    result["basis"] = "git_commit"
    if max_age_seconds is None:
        result["status"] = "not_comparable"
        result["reason"] = "no_max_age_seconds"
        return result
    as_of = as_of or datetime.datetime.now(datetime.timezone.utc)
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=datetime.timezone.utc)
    as_of = as_of.astimezone(datetime.timezone.utc)
    result["as_of"] = as_of.strftime("%Y-%m-%dT%H:%M:%SZ")
    age = (as_of - created_at).total_seconds()
    if age < 0:
        result["reason"] = "created_at_in_future"
        return result
    result["age_seconds"] = int(age)
    if age > max_age_seconds:
        result["status"] = "stale"
        result["reason"] = "age_exceeds_max_age_seconds"
    else:
        result["status"] = "fresh"
        result["reason"] = "within_max_age_seconds"
    return result


def snapshot_availability_model(manifest_path: str | Path, manifest: Mapping[str, Any], *, profile: str | None = None, max_age_seconds: int | None = None, as_of: datetime.datetime | None = None) -> dict[str, Any]:
    path = Path(manifest_path).expanduser().resolve()
    capabilities = manifest.get("capabilities") if isinstance(manifest.get("capabilities"), dict) else {}
    effective_profile = profile if profile is not None else capabilities.get("repobrief_profile")
    if not isinstance(effective_profile, str) or effective_profile not in PROFILE_ARTIFACT_RULES:
        effective_profile = None
    records = _artifact_records(path, manifest)
    roles = sorted(set(ARTIFACT_ORDER) | set(records))
    artifacts = []
    for role in roles:
        requirement = _requirement_for(effective_profile, role)
        availability, reason = _availability_for(requirement, records.get(role, []))
        artifacts.append({"role": role, "requirement": requirement, "availability": availability, "reason": reason, "file_exists": any(record.get("file_exists") is True for record in records.get(role, []))})
    availability_counts: dict[str, int] = {value: 0 for value in AVAILABILITY_VALUES}
    for artifact in artifacts:
        availability_counts[artifact["availability"]] += 1
    if availability_counts["invalid"] or availability_counts["missing_required"]:
        status = "fail"
    elif availability_counts["blocked_by_missing_source"] or availability_counts["blocked_by_missing_provenance"] or availability_counts["degraded"]:
        status = "warn"
    elif any(artifact["availability"] == "missing" and artifact["requirement"] == REQ_RECOMMENDED for artifact in artifacts):
        status = "warn"
    else:
        status = "pass"
    return {"kind": KIND, "version": VERSION, "status": status, "profile": effective_profile, "bundle_manifest": str(path), "availability_values": list(AVAILABILITY_VALUES), "freshness_values": list(FRESHNESS_VALUES), "availability_counts": availability_counts, "artifacts": artifacts, "freshness": snapshot_freshness_model(manifest, max_age_seconds=max_age_seconds, as_of=as_of), "graph_availability": graph_availability_model(path, manifest, profile=effective_profile), "does_not_establish": list(DOES_NOT_ESTABLISH)}
