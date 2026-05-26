"""
Agent export gate for bundle-facing export profiles (roadmap PR A5).

This module enforces a small, explicit export gate for agent-facing profiles:
- post_emit_health must be available and pass on the final bundle surface,
- redaction policy must be acceptable for the requested profile,
- output_health.verdict is observation-only and never sufficient evidence.

Design constraints:
- No manifest mutation.
- No global truth verdicts (no safe/unsafe/agent_ready semantics).
- Deterministic machine-readable result shape.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from .clock import now_utc
from .path_security import resolve_secure_path
from .post_emit_health import derive_post_health_path

try:
    import jsonschema
except ImportError:  # optional runtime dependency
    jsonschema = None

KIND = "lenskit.agent_export_gate"
VERSION = "1.0"

_BUNDLE_KIND = "repolens.bundle.manifest"
_POST_HEALTH_KIND = "lenskit.post_emit_health"
_POST_HEALTH_VERSION = "1.0"
_POST_STATUSES = {"pass", "warn", "fail", "blocked"}
# A5-local profile policy derived from repository output_profile vocabulary.
_AGENT_FACING_PROFILES = {"agent_minimal", "agent-portable", "agent-safe"}
_NON_AGENT_PROFILES = {
    "human_review",
    "ui_navigation",
    "lookup_minimal",
    "review_context",
    "lean-readable",
    "lean-evidence",
    "local-search",
    "debug-full",
    "max-private",
    "forensic-strict",
}
_NON_EXPORTABLE_PROFILES = {
    "local-search",
    "debug-full",
    "max-private",
    "forensic-strict",
}
_KNOWN_PROFILES = _AGENT_FACING_PROFILES | _NON_AGENT_PROFILES

_DOES_NOT_MEAN = [
    "repo_understood",
    "answer_safe_without_citations",
    "claims_true",
]


def _now_iso() -> str:
    ts = now_utc()
    if isinstance(ts, str):
        return ts if ts.endswith("Z") else ts + "Z"
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def _resolve_path(path_str: str) -> Path:
    p = Path(path_str)
    if not p.is_absolute():
        p = Path.cwd() / p
    return p.resolve()


def _load_json(path: Path) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    if not path.exists() or not path.is_file():
        return None, "file not found"
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        return None, str(e)
    if not isinstance(data, dict):
        return None, "JSON root must be an object"
    return data, None


def _is_agent_facing(profile: Optional[str]) -> bool:
    if not profile:
        return False
    return profile in _AGENT_FACING_PROFILES


def _find_output_health_verdict(manifest: Dict[str, Any], manifest_dir: Path) -> Optional[str]:
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        return None

    output_entry = None
    for art in artifacts:
        if not isinstance(art, dict):
            continue
        if art.get("role") == "output_health":
            output_entry = art
            break

    if not isinstance(output_entry, dict):
        return None
    rel_path = output_entry.get("path")
    if not isinstance(rel_path, str) or not rel_path:
        return None

    try:
        output_path = resolve_secure_path(manifest_dir, rel_path)
    except ValueError:
        return None

    output_doc, _ = _load_json(output_path)
    if not isinstance(output_doc, dict):
        return None

    verdict = output_doc.get("verdict")
    if isinstance(verdict, str):
        return verdict
    return None


def _validate_post_health_schema(post_doc: Dict[str, Any]) -> Optional[str]:
    if jsonschema is None:
        return None

    schema_path = Path(__file__).parent.parent / "contracts" / "post-emit-health.v1.schema.json"
    if not schema_path.exists():
        return f"post_emit_health schema not found: {schema_path.name}"

    try:
        with schema_path.open("r", encoding="utf-8") as f:
            schema = json.load(f)
        jsonschema.validate(instance=post_doc, schema=schema)
    except jsonschema.ValidationError as e:  # type: ignore[union-attr]
        return f"post_emit_health schema validation failed: {e.message}"
    except (OSError, json.JSONDecodeError) as e:
        return f"could not load post_emit_health schema: {e}"
    return None


def _validate_post_health_binding(
    post_doc: Dict[str, Any],
    *,
    resolved_manifest: Path,
    manifest_run_id: Optional[str],
) -> Optional[str]:
    kind = post_doc.get("kind")
    if kind != _POST_HEALTH_KIND:
        return f"post_emit_health kind mismatch: expected {_POST_HEALTH_KIND!r} got {kind!r}"

    version = post_doc.get("version")
    if version != _POST_HEALTH_VERSION:
        return (
            "post_emit_health version mismatch: "
            f"expected {_POST_HEALTH_VERSION!r} got {version!r}"
        )

    status = post_doc.get("status")
    if not isinstance(status, str) or status not in _POST_STATUSES:
        return f"post_emit_health has invalid status: {status!r}"

    manifest_path_value = post_doc.get("bundle_manifest_path")
    if not isinstance(manifest_path_value, str) or not manifest_path_value.strip():
        return "post_emit_health bundle_manifest_path is missing or empty"

    resolved_post_manifest = _resolve_path(manifest_path_value.strip())
    if resolved_post_manifest != resolved_manifest:
        return "post_emit_health bundle_manifest_path does not match the evaluated manifest"

    post_bundle_run_id = post_doc.get("bundle_run_id")
    if status == "pass":
        if not isinstance(manifest_run_id, str) or not manifest_run_id.strip():
            return "manifest run_id is missing or empty; cannot bind post_emit_health"
        if not isinstance(post_bundle_run_id, str) or not post_bundle_run_id.strip():
            return "post_emit_health bundle_run_id is missing or empty"
        if post_bundle_run_id != manifest_run_id:
            return "post_emit_health bundle_run_id does not match manifest run_id"

    schema_error = _validate_post_health_schema(post_doc)
    if schema_error is not None:
        return schema_error

    return None


def evaluate_agent_export_gate(
    manifest_path: str,
    post_health_path: Optional[str] = None,
    profile: Optional[str] = None,
    require_redaction: bool = True,
) -> Dict[str, Any]:
    """
    Evaluate whether export is permitted for the requested profile.

    Returns a deterministic machine-readable gate report.
    """
    errors: list[str] = []
    warnings: list[str] = []

    resolved_manifest = _resolve_path(manifest_path)

    manifest, manifest_err = _load_json(resolved_manifest)
    if manifest is None:
        return {
            "kind": KIND,
            "version": VERSION,
            "status": "blocked",
            "profile": profile,
            "agent_facing": _is_agent_facing(profile),
            "checked_at": _now_iso(),
            "bundle_manifest_path": str(resolved_manifest),
            "post_emit_health_status": None,
            "output_health_verdict_observed": None,
            "redaction_required": bool(_is_agent_facing(profile)),
            "redaction_enabled": None,
            "errors": [f"cannot read bundle manifest: {manifest_err}"],
            "warnings": [],
            "does_not_mean": list(_DOES_NOT_MEAN),
        }

    if manifest.get("kind") != _BUNDLE_KIND:
        return {
            "kind": KIND,
            "version": VERSION,
            "status": "blocked",
            "profile": profile,
            "agent_facing": _is_agent_facing(profile),
            "checked_at": _now_iso(),
            "bundle_manifest_path": str(resolved_manifest),
            "post_emit_health_status": None,
            "output_health_verdict_observed": None,
            "redaction_required": bool(_is_agent_facing(profile)),
            "redaction_enabled": None,
            "errors": ["manifest is not a repolens.bundle.manifest"],
            "warnings": [],
            "does_not_mean": list(_DOES_NOT_MEAN),
        }

    manifest_dir = resolved_manifest.parent
    manifest_run_id_raw = manifest.get("run_id")
    manifest_run_id = manifest_run_id_raw if isinstance(manifest_run_id_raw, str) else None
    manifest_run_id_valid = isinstance(manifest_run_id, str) and bool(manifest_run_id.strip())

    profile_missing = profile is None
    profile_unknown = isinstance(profile, str) and profile not in _KNOWN_PROFILES
    agent_facing = _is_agent_facing(profile)
    redaction_required = bool(agent_facing)
    profile_non_exportable = isinstance(profile, str) and profile in _NON_EXPORTABLE_PROFILES

    capabilities = manifest.get("capabilities") if isinstance(manifest.get("capabilities"), dict) else {}
    redaction_value = capabilities.get("redaction")
    redaction_enabled = redaction_value if isinstance(redaction_value, bool) else None

    output_health_verdict_observed: Optional[str] = _find_output_health_verdict(manifest, manifest_dir)

    if post_health_path:
        resolved_post_health = _resolve_path(post_health_path)
    else:
        resolved_post_health = derive_post_health_path(resolved_manifest)

    post_doc, post_err = _load_json(resolved_post_health)
    post_emit_health_status: Optional[str] = None
    post_health_valid = False
    if isinstance(post_doc, dict):
        binding_error = _validate_post_health_binding(
            post_doc,
            resolved_manifest=resolved_manifest,
            manifest_run_id=manifest_run_id,
        )
        if binding_error is not None:
            warnings.append(binding_error)
        else:
            post_health_valid = True
            raw_status = post_doc.get("status")
            if isinstance(raw_status, str):
                post_emit_health_status = raw_status
            observed = post_doc.get("output_health_verdict")
            if isinstance(observed, str):
                output_health_verdict_observed = observed
    else:
        if post_err is not None:
            warnings.append(f"post_emit_health unavailable: {post_err}")

    status = "pass"

    if profile_missing:
        status = "blocked"
        errors.append("export gate requires an explicit profile")
    elif profile_unknown:
        status = "blocked"
        errors.append(f"unknown export profile: {profile!r}")
    elif profile_non_exportable:
        status = "blocked"
        errors.append(f"profile is internal and not agent-exportable: {profile!r}")

    if agent_facing:
        if require_redaction is False:
            status = "blocked"
            errors.append("agent-facing export cannot disable redaction requirement")

        if not manifest_run_id_valid:
            status = "blocked"
            errors.append("agent-facing export requires non-empty manifest run_id")

        if not post_health_valid:
            status = "blocked"
            errors.append("agent-facing export requires valid post_emit_health")
        elif post_emit_health_status == "blocked":
            status = "blocked"
            errors.append("post_emit_health status is blocked")
        elif post_emit_health_status == "fail":
            status = "fail"
            errors.append("post_emit_health status is fail")
        elif post_emit_health_status != "pass":
            status = "fail"
            errors.append("agent-facing export requires post_emit_health status pass")

        if redaction_required and redaction_enabled is not True:
            status = "fail" if status != "blocked" else status
            errors.append("agent-facing export requires capabilities.redaction=true")
    elif not profile_non_exportable:
        warnings.append(
            "non-agent-facing profile result does not certify agent-surface export"
        )

    if output_health_verdict_observed == "pass" and (
        post_doc is None or post_emit_health_status != "pass"
    ):
        warnings.append(
            "output_health.verdict=pass observed but not sufficient for export gate"
        )

    return {
        "kind": KIND,
        "version": VERSION,
        "status": status,
        "profile": profile,
        "agent_facing": agent_facing,
        "checked_at": _now_iso(),
        "bundle_manifest_path": str(resolved_manifest),
        "post_emit_health_status": post_emit_health_status,
        "output_health_verdict_observed": output_health_verdict_observed,
        "redaction_required": redaction_required,
        "redaction_enabled": redaction_enabled,
        "errors": errors,
        "warnings": warnings,
        "does_not_mean": list(_DOES_NOT_MEAN),
    }