from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from .clock import now_utc
from .claim_evidence_diagnostics import (
    claim_absence_reason_detail,
    claim_absence_reason_from_manifest,
)
from .path_security import resolve_secure_path
from .post_emit_health import derive_post_health_path

try:
    import jsonschema
except ImportError:  # optional runtime dependency
    jsonschema = None

KIND = "lenskit.forensic_preflight"
VERSION = "1.0"
_BUNDLE_KIND = "repolens.bundle.manifest"
_SHA256_LEN = 64


def _now_iso() -> str:
    ts = now_utc()
    if isinstance(ts, str):
        return ts if ts.endswith("Z") else ts + "Z"
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def _check(name: str, status: str, detail: str) -> Dict[str, str]:
    return {"name": name, "status": status, "detail": detail}


def _resolve(path: str) -> Path:
    p = Path(path)
    if not p.is_absolute():
        p = Path.cwd() / p
    return p.resolve()


def _sha256_file(path: Path) -> Optional[str]:
    h = hashlib.sha256()
    try:
        with path.open("rb") as f:
            for buf in iter(lambda: f.read(65536), b""):
                h.update(buf)
    except OSError:
        return None
    return h.hexdigest()


def _load_json(path: Path) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    if not path.exists() or not path.is_file():
        return None, "file not found"
    try:
        with path.open("r", encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, json.JSONDecodeError, UnicodeError) as e:
        return None, str(e)
    if not isinstance(doc, dict):
        return None, "JSON root must be an object"
    return doc, None


def _find_artifact(artifacts: list[Any], role: str) -> Optional[Dict[str, Any]]:
    for art in artifacts:
        if isinstance(art, dict) and art.get("role") == role:
            return art
    return None


def _check_artifact_hash(
    artifacts: list[Any],
    manifest_dir: Path,
    role: str,
    *,
    check_name: str,
) -> Tuple[Dict[str, str], Optional[Dict[str, Any]], Optional[Path], Optional[str], Optional[str]]:
    art = _find_artifact(artifacts, role)
    if art is None:
        return _check(check_name, "blocked", f"{role} missing in manifest"), None, None, None, None

    raw_path = art.get("path")
    if not isinstance(raw_path, str) or not raw_path:
        return _check(check_name, "blocked", f"{role} path missing"), art, None, None, None

    try:
        path = resolve_secure_path(manifest_dir, raw_path)
    except ValueError as e:
        return _check(check_name, "fail", f"{role} path rejected: {e}"), art, None, None, str(e)

    expected = art.get("sha256")
    if not isinstance(expected, str) or len(expected) != _SHA256_LEN:
        return _check(check_name, "fail", f"{role} sha256 missing/invalid"), art, path, None, None

    actual = _sha256_file(path)
    if actual is None:
        return _check(check_name, "blocked", f"{role} artifact file missing/unreadable"), art, path, None, None

    if actual != expected:
        return _check(check_name, "fail", f"{role} sha256 mismatch"), art, path, actual, expected
    return _check(check_name, "pass", f"{role} hash verified"), art, path, actual, expected


def _validate_claim_map_schema(claim_map_doc: Dict[str, Any]) -> Tuple[str, str]:
    if jsonschema is None:
        return "blocked", "claim-evidence-map schema validation unavailable: jsonschema not installed"

    schema_path = Path(__file__).parent.parent / "contracts" / "claim-evidence-map.v1.schema.json"
    doc, err = _load_json(schema_path)
    if doc is None:
        return "blocked", f"claim-evidence-map schema unavailable: {err}"
    try:
        jsonschema.validate(instance=claim_map_doc, schema=doc)
    except jsonschema.ValidationError as e:  # type: ignore[union-attr]
        return "fail", f"claim_evidence_map schema invalid: {e.message}"
    return "pass", "claim_evidence_map schema valid"


def _post_health_binding_status(
    post_doc: Dict[str, Any],
    *,
    resolved_manifest: Path,
    manifest_run_id: Any,
) -> Tuple[str, str]:
    post_manifest_path = post_doc.get("bundle_manifest_path")
    if not isinstance(post_manifest_path, str) or not post_manifest_path:
        return "blocked", "post_emit_health missing bundle_manifest_path binding"

    resolved_post_manifest = _resolve(post_manifest_path)
    if resolved_post_manifest != resolved_manifest:
        return (
            "fail",
            "post_emit_health bundle_manifest_path does not match requested manifest",
        )

    if isinstance(manifest_run_id, str):
        post_bundle_run_id = post_doc.get("bundle_run_id")
        if not isinstance(post_bundle_run_id, str) or not post_bundle_run_id:
            return "blocked", "post_emit_health missing bundle_run_id binding"
        if post_bundle_run_id != manifest_run_id:
            return "fail", "post_emit_health bundle_run_id does not match manifest run_id"

    return "pass", "post_emit_health bound to requested manifest"


def compute_forensic_preflight(
    manifest_path: str,
    *,
    post_health_path: Optional[str] = None,
    run_id: Optional[str] = None,
) -> Dict[str, Any]:
    checks: list[Dict[str, str]] = []
    errors: list[str] = []
    warnings: list[str] = []

    run_id = run_id or str(uuid.uuid4())
    resolved_manifest = _resolve(manifest_path)
    manifest, manifest_err = _load_json(resolved_manifest)
    if manifest is None:
        return {
            "kind": KIND,
            "version": VERSION,
            "run_id": run_id,
            "checked_at": _now_iso(),
            "bundle_manifest_path": str(resolved_manifest),
            "status": "blocked",
            "checks": [_check("manifest_present", "blocked", f"cannot read manifest: {manifest_err}")],
            "errors": [f"cannot read manifest: {manifest_err}"],
            "warnings": [],
            "does_not_mean": ["claims_true", "repo_understood"],
        }

    if manifest.get("kind") != _BUNDLE_KIND:
        return {
            "kind": KIND,
            "version": VERSION,
            "run_id": run_id,
            "checked_at": _now_iso(),
            "bundle_manifest_path": str(resolved_manifest),
            "status": "blocked",
            "checks": [_check("manifest_present", "blocked", "manifest is not a bundle manifest")],
            "errors": ["manifest is not a repolens.bundle.manifest"],
            "warnings": [],
            "does_not_mean": ["claims_true", "repo_understood"],
        }

    checks.append(_check("manifest_present", "pass", "bundle manifest loaded"))
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        return {
            "kind": KIND,
            "version": VERSION,
            "run_id": run_id,
            "checked_at": _now_iso(),
            "bundle_manifest_path": str(resolved_manifest),
            "status": "blocked",
            "checks": checks + [_check("manifest_artifacts_list", "blocked", "manifest artifacts missing")],
            "errors": ["manifest artifacts list missing"],
            "warnings": [],
            "does_not_mean": ["claims_true", "repo_understood"],
        }

    manifest_dir = resolved_manifest.parent
    for role, check_name in (
        ("canonical_md", "canonical_md_hash_ok"),
        ("chunk_index_jsonl", "chunk_index_hash_ok"),
        ("citation_map_jsonl", "citation_map_hash_ok"),
    ):
        c, _, _, _, _ = _check_artifact_hash(artifacts, manifest_dir, role, check_name=check_name)
        checks.append(c)
        if c["status"] == "fail":
            errors.append(c["detail"])
        elif c["status"] == "blocked":
            errors.append(c["detail"])

    claim_present = _find_artifact(artifacts, "claim_evidence_map_json")
    if claim_present is None:
        claim_absence_reason = claim_absence_reason_from_manifest(manifest)
        reason_detail = claim_absence_reason_detail(claim_absence_reason)
        reason_suffix = (
            f" reason={claim_absence_reason} ({reason_detail})"
            if claim_absence_reason is not None
            else ""
        )
        missing_detail = "claim_evidence_map_json missing" + reason_suffix
        checks.append(_check("claim_evidence_map_present", "blocked", missing_detail))
        checks.append(_check("claim_evidence_map_hash_ok", "blocked", missing_detail))
        checks.append(_check("claim_evidence_map_schema_valid", "blocked", missing_detail))
        errors.append(missing_detail)
    else:
        checks.append(_check("claim_evidence_map_present", "pass", "claim_evidence_map_json present"))
        c, _, claim_path, _, _ = _check_artifact_hash(
            artifacts,
            manifest_dir,
            "claim_evidence_map_json",
            check_name="claim_evidence_map_hash_ok",
        )
        checks.append(c)
        if c["status"] in {"fail", "blocked"}:
            errors.append(c["detail"])
            checks.append(
                _check(
                    "claim_evidence_map_schema_valid",
                    "skipped",
                    "schema check skipped because claim_evidence_map hash is unverified",
                )
            )
        else:
            claim_doc, claim_err = _load_json(claim_path) if claim_path is not None else (None, "path missing")
            if claim_doc is None:
                checks.append(
                    _check("claim_evidence_map_schema_valid", "fail", f"cannot read claim_evidence_map: {claim_err}")
                )
                errors.append(f"cannot read claim_evidence_map: {claim_err}")
            else:
                schema_status, schema_detail = _validate_claim_map_schema(claim_doc)
                checks.append(_check("claim_evidence_map_schema_valid", schema_status, schema_detail))
                if schema_status == "fail":
                    errors.append(schema_detail)
                elif schema_status == "blocked":
                    errors.append(schema_detail)
                elif schema_status == "warn":
                    warnings.append(schema_detail)

    resolved_post = _resolve(post_health_path) if post_health_path else derive_post_health_path(resolved_manifest)
    post_doc, post_err = _load_json(resolved_post)
    if post_doc is None:
        checks.append(_check("post_emit_health_present", "blocked", f"post_emit_health missing: {post_err}"))
        checks.append(_check("post_emit_health_pass", "blocked", "post_emit_health missing"))
        checks.append(_check("post_emit_health_bound_to_manifest", "blocked", "post_emit_health missing"))
        checks.append(_check("range_citation_strict", "blocked", "cannot verify without post_emit_health"))
        checks.append(_check("no_required_checks_skipped", "blocked", "cannot verify without post_emit_health"))
        errors.append(f"post_emit_health missing: {post_err}")
    else:
        checks.append(_check("post_emit_health_present", "pass", "post_emit_health loaded"))
        binding_status, binding_detail = _post_health_binding_status(
            post_doc,
            resolved_manifest=resolved_manifest,
            manifest_run_id=manifest.get("run_id"),
        )
        checks.append(_check("post_emit_health_bound_to_manifest", binding_status, binding_detail))
        if binding_status in {"blocked", "fail"}:
            errors.append(binding_detail)
            checks.append(
                _check(
                    "post_emit_health_pass",
                    "blocked",
                    "cannot trust post_emit_health status because binding is missing or mismatched",
                )
            )
            checks.append(
                _check(
                    "range_citation_strict",
                    "blocked",
                    "cannot verify because post_emit_health binding is missing or mismatched",
                )
            )
            checks.append(
                _check(
                    "no_required_checks_skipped",
                    "blocked",
                    "cannot verify because post_emit_health binding is missing or mismatched",
                )
            )
        else:
            post_status = post_doc.get("status")
            if post_status == "pass":
                checks.append(_check("post_emit_health_pass", "pass", "post_emit_health status=pass"))
            elif post_status == "warn":
                checks.append(_check("post_emit_health_pass", "warn", "post_emit_health status=warn"))
                warnings.append("post_emit_health status=warn")
            elif post_status in {"blocked", "fail"}:
                checks.append(_check("post_emit_health_pass", "blocked", f"post_emit_health status={post_status}"))
                errors.append(f"post_emit_health status={post_status}")
            else:
                checks.append(
                    _check(
                        "post_emit_health_pass",
                        "fail",
                        f"post_emit_health status invalid: {post_status!r}",
                    )
                )
                errors.append(f"post_emit_health status invalid: {post_status!r}")

            reached = post_doc.get("evidence_levels_reached")
            range_status = post_doc.get("range_ref_resolution_status")
            if isinstance(reached, list) and "range_strict" in reached and range_status == "ok":
                checks.append(_check("range_citation_strict", "pass", "range_strict evidence reached"))
            elif post_status == "pass":
                checks.append(
                    _check(
                        "range_citation_strict",
                        "blocked",
                        "range_strict evidence not reached in post_emit_health",
                    )
                )
                errors.append("range_strict evidence not reached in post_emit_health")
            else:
                checks.append(
                    _check(
                        "range_citation_strict",
                        "blocked",
                        "range_strict evidence unavailable because post_emit_health is not pass",
                    )
                )

            required_checks = {
                "manifest_schema_valid",
                "artifact_paths_exist",
                "artifact_hashes_match",
                "canonical_md_present",
                "agent_pack_present",
                "claim_evidence_map_present",
                "claim_evidence_map_hash_ok",
                "claim_evidence_map_schema_valid",
                "range_ref_resolution",
            }
            post_checks = post_doc.get("checks")
            if not isinstance(post_checks, list):
                checks.append(_check("no_required_checks_skipped", "blocked", "post_emit_health checks missing"))
                errors.append("post_emit_health checks missing")
            else:
                status_by_name = {}
                for item in post_checks:
                    if isinstance(item, dict) and isinstance(item.get("name"), str):
                        status_by_name[item["name"]] = item.get("status")

                missing = sorted(name for name in required_checks if name not in status_by_name)
                skipped = sorted(name for name in required_checks if status_by_name.get(name) == "skipped")
                if missing:
                    checks.append(
                        _check(
                            "no_required_checks_skipped",
                            "blocked",
                            f"required post_emit checks missing: {', '.join(missing)}",
                        )
                    )
                    errors.append(f"required post_emit checks missing: {', '.join(missing)}")
                elif skipped:
                    checks.append(
                        _check(
                            "no_required_checks_skipped",
                            "blocked",
                            f"required post_emit checks skipped: {', '.join(skipped)}",
                        )
                    )
                    errors.append(f"required post_emit checks skipped: {', '.join(skipped)}")
                else:
                    checks.append(_check("no_required_checks_skipped", "pass", "no required post_emit checks skipped"))

    capabilities = manifest.get("capabilities")
    redaction = capabilities.get("redaction") if isinstance(capabilities, dict) else None
    if isinstance(redaction, bool):
        checks.append(_check("redaction_policy_explicit", "pass", f"redaction explicitly set to {redaction}"))
    else:
        checks.append(_check("redaction_policy_explicit", "blocked", "redaction capability not explicitly set"))
        errors.append("redaction capability not explicitly set")

    statuses = {check["status"] for check in checks}
    if "fail" in statuses:
        status = "fail"
    elif "blocked" in statuses:
        status = "blocked"
    elif "warn" in statuses or warnings:
        status = "warn"
    else:
        status = "pass"

    return {
        "kind": KIND,
        "version": VERSION,
        "run_id": run_id,
        "checked_at": _now_iso(),
        "bundle_manifest_path": str(resolved_manifest),
        "post_emit_health_path": str(resolved_post),
        "status": status,
        "checks": checks,
        "errors": errors,
        "warnings": warnings,
        "does_not_mean": [
            "claims_true",
            "repo_understood",
            "answer_safe_without_citations",
        ],
    }
