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
