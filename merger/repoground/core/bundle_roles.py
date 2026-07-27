"""Selected-manifest and artifact-role projections for read-only bundle access.

This module owns no repository discovery policy. Repository-to-bundle selection
stays in :mod:`bundle_catalog`; once selected, manifest bytes are read through
the request-scoped, bounded manifest snapshot contract before roles are
resolved or projected.
"""

from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from merger.repoground.core.bounded_artifact_read import (
    read_stable_regular_file_bytes,
)
from merger.repoground.core.manifest_snapshot import (
    MAX_MANIFEST_BYTES,
    active_manifest_snapshot,
    resolve_manifest_path,
)

DOES_NOT_ESTABLISH = (
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

_LINKED_ROLES = {
    "post_emit_health_path": "post_emit_health",
    "bundle_surface_validation_path": "bundle_surface_validation",
    "export_safety_report_path": "export_safety_report",
}


def read_json_object(path: Path) -> dict[str, Any]:
    """Return one bounded, stable object without narrowing legacy shapes.

    Request-scoped current manifests keep their strict selected-generation
    binding. Historical read-only callers also accept pre-schema fixtures and
    legacy bundle manifests, so the unbound fallback validates only stable
    UTF-8 JSON object bytes and leaves shape checks to the owning consumer.
    """
    snapshot = active_manifest_snapshot(path)
    if snapshot is not None:
        return snapshot.json_object()

    raw, _metadata, failure, detail = read_stable_regular_file_bytes(
        path,
        max_bytes=MAX_MANIFEST_BYTES,
    )
    if failure == "file_missing":
        raise ValueError(f"bundle manifest does not exist: {path}")
    if failure == "too_large":
        raise ValueError(f"bundle manifest exceeds the bounded read limit: {path}")
    if failure is not None or raw is None:
        suffix = f": {detail}" if detail else ""
        raise ValueError(f"bundle manifest is unavailable: {path}{suffix}")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"bundle manifest is not valid JSON: {path}") from exc
    if not isinstance(data, dict):
        raise ValueError("bundle manifest must be a JSON object")
    return data


def artifact_list(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    artifacts = manifest.get("artifacts", [])
    if not isinstance(artifacts, list):
        raise ValueError("bundle manifest artifacts must be an array")
    return [artifact for artifact in artifacts if isinstance(artifact, dict)]


def safe_artifact_path(root: Path, raw_path: Any) -> Path | None:
    """Resolve one manifest path beneath its bundle root, failing closed."""
    if not isinstance(raw_path, str) or not raw_path:
        return None
    try:
        root_resolved = root.resolve(strict=True)
        candidate = (root_resolved / raw_path).resolve(strict=False)
        candidate.relative_to(root_resolved)
    except (OSError, RuntimeError, ValueError):
        return None
    return candidate


def artifact_record(
    bundle_manifest: Path,
    artifact: Mapping[str, Any],
) -> dict[str, Any]:
    root = bundle_manifest.parent
    artifact_path = safe_artifact_path(root, artifact.get("path"))
    try:
        file_exists = bool(artifact_path and artifact_path.exists())
    except OSError:
        file_exists = False
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


def resolve_unique_artifact(
    manifest_path: Path,
    manifest: Mapping[str, Any],
    role: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str | None]:
    """Resolve exactly one registered role without silently choosing duplicates."""
    matches = [
        artifact
        for artifact in artifact_list(manifest)
        if artifact.get("role") == role
    ]
    if not matches:
        return None, None, "missing"
    if len(matches) != 1:
        return None, None, "role_ambiguous"
    payload = matches[0]
    projected = artifact_record(manifest_path, payload)
    if projected["absolute_path"] is None:
        return payload, projected, "path_invalid"
    return payload, projected, None


def read_only_mutation_boundary() -> dict[str, Any]:
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


def available_roles(bundle_manifest: str | Path) -> list[str]:
    manifest_path = resolve_manifest_path(bundle_manifest)
    manifest = read_json_object(manifest_path)
    roles: set[str] = {"bundle_manifest"}
    for artifact in artifact_list(manifest):
        role = artifact.get("role")
        if isinstance(role, str) and role:
            roles.add(role)
    links = manifest.get("links")
    if isinstance(links, dict):
        for key, role in _LINKED_ROLES.items():
            if links.get(key):
                roles.add(role)
    return sorted(roles)


def resolve_required_reading_for_bundle(
    bundle_manifest: str | Path,
    task_profile: str,
) -> dict[str, Any]:
    from merger.repoground.core.required_reading import (
        default_required_reading_protocol,
        resolve_required_reading,
    )

    manifest_path = resolve_manifest_path(bundle_manifest)
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
        "mutation_boundary": read_only_mutation_boundary(),
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }


def snapshot_status(
    bundle_manifest: str | Path,
    *,
    manifest_data: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Project snapshot status without refreshing bundle state."""
    requested_manifest_path = Path(bundle_manifest).expanduser()
    if manifest_data is None:
        manifest_path = resolve_manifest_path(requested_manifest_path)
        manifest = read_json_object(manifest_path)
    else:
        if not isinstance(manifest_data, Mapping):
            raise ValueError("manifest_data must be a mapping")
        # Preserve the lexical selected generation. Following a later symlink
        # replacement here would mix caller-verified bytes with another root.
        manifest_path = Path(
            os.path.abspath(os.fspath(requested_manifest_path))
        )
        manifest = deepcopy(dict(manifest_data))

    artifacts = [
        artifact_record(manifest_path, artifact)
        for artifact in artifact_list(manifest)
    ]
    roles = sorted(
        str(artifact["role"])
        for artifact in artifacts
        if isinstance(artifact.get("role"), str)
    )
    capabilities = (
        manifest.get("capabilities")
        if isinstance(manifest.get("capabilities"), dict)
        else {}
    )
    from merger.repoground.core.availability import snapshot_availability_model

    availability_model = snapshot_availability_model(
        manifest_path,
        manifest,
        resolve_manifest_path=manifest_data is None,
    )
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
        "mutation_boundary": read_only_mutation_boundary(),
        "does_not_establish": list(DOES_NOT_ESTABLISH),
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
    manifest_path = resolve_manifest_path(bundle_manifest)
    manifest = read_json_object(manifest_path)
    matches = [
        artifact
        for artifact in artifact_list(manifest)
        if artifact.get("role") == role
    ]
    artifact = artifact_record(manifest_path, matches[0]) if matches else None
    return {
        "kind": "repobrief.artifact_ref",
        "version": "v1",
        "status": "available" if artifact is not None else "missing",
        "bundle_manifest": str(manifest_path),
        "role": role,
        "artifact": artifact,
        "mutation_boundary": read_only_mutation_boundary(),
        "does_not_establish": list(DOES_NOT_ESTABLISH),
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
        "mutation_boundary": read_only_mutation_boundary(),
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }
