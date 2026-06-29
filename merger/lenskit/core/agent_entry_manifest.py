from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Iterator


_DOES_NOT_ESTABLISH = (
    "repo_understood",
    "answer_safe_without_citations",
    "claims_true",
    "forensic_ready",
    "all_relevant_context_used",
)

_READ_FIRST_PRIORITY = (
    "agent_reading_pack",
    "post_emit_health",
    "canonical_md",
)

# V1 agent-entry expected surfaces. Broader bundle inventory roles
# (chunk indexes, sqlite index, retrieval eval, derived/dump indexes)
# are surfaced when present but are not reported as unavailable in v1.
_SELF_ROLE = "agent_entry_manifest"
_MANIFEST_SUFFIX = ".bundle.manifest.json"
_OUTPUT_SUFFIX = ".agent_entry_manifest.json"

_EXPECTED_SURFACES = (
    "canonical_md",
    "agent_reading_pack",
    "post_emit_health",
    "claim_evidence_map_json",
    "citation_map_jsonl",
    "bundle_surface_validation",
    "output_health",
    "export_safety_report",
)


def _as_dict(value: Any) -> Dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    return None


def _as_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    return []


def _str_or_none(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    return None


def _artifact_role(artifact: Dict[str, Any]) -> str | None:
    return _str_or_none(artifact.get("role"))


def _artifact_path(artifact: Dict[str, Any]) -> str | None:
    return _str_or_none(artifact.get("path"))


def _artifact_sha256(artifact: Dict[str, Any]) -> str | None:
    return _str_or_none(artifact.get("sha256"))


def _artifact_authority(artifact: Dict[str, Any]) -> str | None:
    return _str_or_none(artifact.get("authority"))


def _artifact_canonicality(artifact: Dict[str, Any]) -> str | None:
    return _str_or_none(artifact.get("canonicality"))


def _links(bundle_manifest: Dict[str, Any]) -> Dict[str, Any]:
    links = _as_dict(bundle_manifest.get("links"))
    return links or {}


def _linked_sidecar_surfaces(bundle_manifest: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
    links = _links(bundle_manifest)
    
    post_emit_path = _str_or_none(links.get("post_emit_health_path"))
    if post_emit_path:
        yield {
            "role": "post_emit_health",
            "path": post_emit_path,
            "sha256": None,
            "authority": "diagnostic_signal",
            "canonicality": "diagnostic",
            "risk_class": "diagnostic",
            "required_for": [],
            "recommended_for": [],
        }
        
    surface_path = _str_or_none(links.get("bundle_surface_validation_path"))
    if surface_path:
        yield {
            "role": "bundle_surface_validation",
            "path": surface_path,
            "sha256": None,
            "authority": "diagnostic_signal",
            "canonicality": "diagnostic",
            "risk_class": "diagnostic",
            "required_for": [],
            "recommended_for": [],
        }


def build_agent_entry_manifest(
    bundle_manifest: Dict[str, Any],
    *,
    created_at: Optional[str] = None,
) -> Dict[str, Any]:
    # Determine bundle run id
    bundle_run_id = (
        _str_or_none(bundle_manifest.get("run_id"))
        or _str_or_none(bundle_manifest.get("bundle_run_id"))
        or _str_or_none(bundle_manifest.get("id"))
    )
    if not bundle_run_id:
        raise ValueError("bundle_run_id missing")

    # Determine created at
    if created_at is not None:
        final_created_at = created_at
    else:
        manifest_created_at = _str_or_none(bundle_manifest.get("created_at"))
        final_created_at = manifest_created_at if manifest_created_at else "unknown"

    artifacts = _as_list(bundle_manifest.get("artifacts"))

    canonical_source: Dict[str, Any] | None = None
    available_surfaces: List[Dict[str, Any]] = []
    available_roles: set[str] = set()

    for artifact_raw in artifacts:
        artifact = _as_dict(artifact_raw)
        if not artifact:
            continue

        role = _artifact_role(artifact)
        if role == _SELF_ROLE:
            # Agent Entry Manifest is intentionally self-excluding. A manifest
            # cannot truthfully carry its own freshly computed sha256 inside its
            # own body without a circular hash. Re-runs over final manifests
            # therefore stay deterministic and do not list a stale self-entry.
            continue
        path = _artifact_path(artifact)

        if role == "canonical_md" and not path:
            raise ValueError("canonical_md path missing")

        if not role or not path:
            continue

        authority = _artifact_authority(artifact)
        canonicality = _artifact_canonicality(artifact)

        if role == "canonical_md":
            authority = authority or "canonical_content"
            canonicality = canonicality or "content_source"
        else:
            authority = authority or "unknown"
            canonicality = canonicality or "unknown"
        sha256 = _artifact_sha256(artifact)
        risk_class = _str_or_none(artifact.get("risk_class"))

        surface_ref: Dict[str, Any] = {
            "role": role,
            "path": path,
            "sha256": sha256,
            "authority": authority,
            "canonicality": canonicality,
            "risk_class": risk_class,
            "required_for": [],
            "recommended_for": [],
        }

        available_surfaces.append(surface_ref)
        available_roles.add(role)

        if role == "canonical_md":
            if canonical_source is not None:
                raise ValueError("multiple canonical_md artifacts")
            canonical_source = {
                "role": role,
                "path": path,
                "sha256": sha256,
                "authority": authority,
                "canonicality": canonicality,
            }

    for linked_surface in _linked_sidecar_surfaces(bundle_manifest):
        if linked_surface["role"] not in available_roles:
            available_surfaces.append(linked_surface)
            available_roles.add(linked_surface["role"])

    if not canonical_source:
        raise ValueError("canonical_md artifact missing")

    if canonical_source["authority"] != "canonical_content":
        raise ValueError("canonical_md authority must be canonical_content")

    if canonical_source["canonicality"] != "content_source":
        raise ValueError("canonical_md canonicality must be content_source")

    surfaces_by_role = {
        surface["role"]: surface
        for surface in available_surfaces
        if isinstance(surface.get("role"), str)
    }

    read_first = [
        surfaces_by_role[role]
        for role in _READ_FIRST_PRIORITY
        if role in surfaces_by_role
    ]

    unavailable_surfaces = [
        {
            "role": expected_role,
            "reason": "not_present_in_bundle_manifest",
            "required_for": [],
            "recommended_for": [],
        }
        for expected_role in _EXPECTED_SURFACES
        if expected_role not in available_roles
    ]

    task_profiles_ref = {
        "kind": "lenskit.required_reading_protocol",
        "version": "1.0",
        "source": "merger.lenskit.core.required_reading",
    }

    return {
        "kind": "lenskit.agent_entry_manifest",
        "version": "1.0",
        "bundle_run_id": bundle_run_id,
        "created_at": final_created_at,
        "authority": "navigation_index",
        "canonicality": "derived",
        "risk_class": "navigation",
        "canonical_source": canonical_source,
        "read_first": read_first,
        "task_profiles_ref": task_profiles_ref,
        "available_surfaces": available_surfaces,
        "unavailable_surfaces": unavailable_surfaces,
        "does_not_establish": list(_DOES_NOT_ESTABLISH),
    }

def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_bytes_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            delete=False,
            dir=str(path.parent),
            prefix=f".{path.name}.",
            suffix=".tmp",
        ) as tmp_file:
            tmp_file.write(data)
            tmp_file.flush()
            os.fsync(tmp_file.fileno())
            tmp_path = Path(tmp_file.name)
        os.replace(tmp_path, path)
    finally:
        if tmp_path is not None and tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def _default_output_path(manifest_path: Path) -> Path | None:
    if manifest_path.name.endswith(_MANIFEST_SUFFIX):
        stem = manifest_path.name[: -len(_MANIFEST_SUFFIX)]
        return manifest_path.parent / f"{stem}{_OUTPUT_SUFFIX}"
    return None


def produce_agent_entry_manifest(
    manifest_path_str: str,
    output_path_str: str | None = None,
) -> Dict[str, Any]:
    """Produce ``<stem>.agent_entry_manifest.json`` from a bundle manifest.

    The produced file is navigation-only. It is deliberately self-excluding:
    when run over a final manifest that already registers an
    ``agent_entry_manifest`` artifact, that existing self-entry is skipped in
    the generated payload to avoid circular hash claims.
    """
    manifest_path = Path(manifest_path_str)
    if not manifest_path.is_absolute():
        manifest_path = Path.cwd() / manifest_path
    manifest_path = manifest_path.resolve()

    output_path: Path | None
    if output_path_str:
        candidate = Path(output_path_str)
        output_path = candidate if candidate.is_absolute() else Path.cwd() / candidate
        output_path = output_path.resolve()
    else:
        output_path = _default_output_path(manifest_path)

    if not manifest_path.is_file():
        return {
            "status": "fail",
            "error_kind": "path_read_error",
            "bundle_manifest_path": str(manifest_path),
            "output_path": str(output_path) if output_path is not None else None,
            "errors": [f"Manifest not found or not a file: {manifest_path}"],
            "warnings": [],
        }
    if output_path is None:
        return {
            "status": "fail",
            "error_kind": "output_path_error",
            "bundle_manifest_path": str(manifest_path),
            "output_path": None,
            "errors": [
                f"Cannot derive output path: manifest filename {manifest_path.name!r} "
                f"does not end with {_MANIFEST_SUFFIX!r}."
            ],
            "warnings": [],
        }
    if output_path == manifest_path:
        return {
            "status": "fail",
            "error_kind": "output_path_error",
            "bundle_manifest_path": str(manifest_path),
            "output_path": str(output_path),
            "errors": ["Output path collides with bundle manifest input."],
            "warnings": [],
        }

    try:
        bundle_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return {
            "status": "fail",
            "error_kind": "path_read_error",
            "bundle_manifest_path": str(manifest_path),
            "output_path": str(output_path),
            "errors": [f"Cannot load manifest: {exc}"],
            "warnings": [],
        }

    try:
        payload = build_agent_entry_manifest(bundle_manifest)
    except Exception as exc:
        return {
            "status": "fail",
            "error_kind": "manifest_error",
            "bundle_manifest_path": str(manifest_path),
            "output_path": str(output_path),
            "errors": [str(exc)],
            "warnings": [],
        }

    body = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    try:
        _write_bytes_atomic(output_path, body)
    except OSError as exc:
        return {
            "status": "fail",
            "error_kind": "path_write_error",
            "bundle_manifest_path": str(manifest_path),
            "output_path": str(output_path),
            "errors": [f"Cannot write output: {exc}"],
            "warnings": [],
        }

    return {
        "status": "ok",
        "error_kind": "ok",
        "bundle_manifest_path": str(manifest_path),
        "bundle_run_id": payload.get("bundle_run_id"),
        "output_path": str(output_path),
        "output_sha256": _sha256_bytes(body),
        "output_bytes": len(body),
        "available_surface_count": len(payload.get("available_surfaces", [])),
        "unavailable_surface_count": len(payload.get("unavailable_surfaces", [])),
        "errors": [],
        "warnings": [],
    }
