"""
Post-emit Bundle Health validator for Lenskit bundles (roadmap PR A4).

Validates the FINAL emitted bundle surface *after* every derived artifact is
present — in particular the ``agent_reading_pack``, which the in-pipeline
``output_health`` (pre-emit) cannot see because the pack is produced *after*
``output_health`` is written (see ``core/merge.py``: output_health is anchored to
``dump_index`` and emitted before the manifest is finalized; the pack is emitted
last). This module closes that gap.

Design contract:
- Independent from ``output_health``: ``output_health.verdict`` is recorded as an
  OBSERVATION only and NEVER causes a post-emit pass. A green pre-emit health does
  not imply a green post-emit status.
- No self-hash circularity: the post-emit report is a separate file
  (``<stem>.bundle_health.post.json``) that is intentionally NOT registered in the
  bundle manifest, so it never verifies its own hash and never mutates manifest
  truth.
- Redaction status is REPORTED but NOT enforced (enforcement is roadmap PR A5).
- The achieved evidence level is reported using the existing control-plane
  vocabulary (``docs/architecture/artifact-evidence-levels.md``). It is NOT a
  global understanding verdict.

Status model (precedence ``blocked`` > ``fail`` > ``warn`` > ``pass``):
- ``blocked`` — certification could not complete: a required certification surface
  is absent (manifest unreadable / not a bundle manifest / no artifact list, or a
  required role such as ``canonical_md`` / ``agent_reading_pack`` is not declared).
- ``fail``    — certification completed but found defects: a manifest-declared
  artifact file is missing, a hash mismatch, an invalid manifest schema, a
  range-ref resolution failure, or the pack mis-declares itself as canonical.
- ``warn``    — usable but degraded (e.g. jsonschema unavailable for strict checks).
- ``pass``    — all required checks satisfied.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .check_view import compact_check_projection
from .clock import now_utc
from .claim_evidence_diagnostics import (
    claim_absence_reason_detail,
    claim_absence_reason_from_manifest,
)
from .constants import ArtifactRole
from .output_health import _is_jsonschema_unavailable_error
from .path_security import resolve_secure_path
from .rooted_filesystem import (
    RootedFilesystemError,
    atomic_write_bytes,
    read_regular_bytes,
)

from .dependency_diagnostics import jsonschema_dependency
from .health_degradation import HEALTH_STATUS_MODEL, degradation_item, degradation_summary

try:
    import jsonschema
except ImportError:  # optional runtime dependency
    jsonschema = None

logger = logging.getLogger(__name__)

KIND = "lenskit.post_emit_health"
VERSION = "1.0"


class PostEmitHealthBindingError(RuntimeError):
    """Raised when final manifest binding cannot be persisted safely."""

_MANIFEST_SUFFIX = ".bundle.manifest.json"
_POST_HEALTH_SUFFIX = ".bundle_health.post.json"
_BUNDLE_KIND = "repolens.bundle.manifest"
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")

# Minimum disclaimers the artifact must always carry. These are NOT claim
# verdicts; they declare what a post-emit pass deliberately does NOT establish.
DOES_NOT_MEAN = (
    "repo_understood",
    "answer_safe_without_citations",
)

# The artifact must explicitly state the pre-/post-health independence.
INDEPENDENCE_NOTE = (
    "output_health.verdict=pass does not imply post_emit_health.status=pass"
)

# Existing evidence-level vocabulary (docs/architecture/artifact-evidence-levels.md).
_EVIDENCE_ORDER = (
    "readable",
    "navigable",
    "citable",
    "range_strict",
    "searchable",
    "diagnostic_full",
    "forensic_strict",
)
# The strict linear chain used to pick a single conservative headline level.
_CORE_LADDER = ("readable", "navigable", "citable", "range_strict")

_CANONICAL_MD = ArtifactRole.CANONICAL_MD.value
_CHUNK_INDEX = ArtifactRole.CHUNK_INDEX_JSONL.value
_CITATION_MAP = ArtifactRole.CITATION_MAP_JSONL.value
_CLAIM_EVIDENCE_MAP = ArtifactRole.CLAIM_EVIDENCE_MAP_JSON.value
_SQLITE_INDEX = ArtifactRole.SQLITE_INDEX.value
_OUTPUT_HEALTH = ArtifactRole.OUTPUT_HEALTH.value
_AGENT_PACK = ArtifactRole.AGENT_READING_PACK.value
_DEBUG_ROLES = frozenset(
    {
        ArtifactRole.DUMP_INDEX_JSON.value,
        ArtifactRole.DERIVED_MANIFEST_JSON.value,
        ArtifactRole.INDEX_SIDECAR_JSON.value,
        ArtifactRole.ARCHITECTURE_SUMMARY.value,
    }
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sha256_file(path: Path) -> Optional[str]:
    h = hashlib.sha256()
    try:
        with path.open("rb") as f:
            for buf in iter(lambda: f.read(65536), b""):
                h.update(buf)
        return h.hexdigest()
    except OSError:
        return None


def _now_iso() -> str:
    ts = now_utc()
    if isinstance(ts, str):
        return ts if ts.endswith("Z") else ts + "Z"
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def _check(
    name: str,
    status: str,
    detail: Optional[str] = None,
    validation: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    out: Dict[str, Any] = {"name": name, "status": status}
    if detail:
        out["detail"] = detail
    if validation is not None:
        out["validation"] = validation
    return out


def _validation(mode: str, engine: str, reason: str) -> Dict[str, str]:
    return {"mode": mode, "engine": engine, "reason": reason}


def _schema_skip_reason(message: str) -> str:
    if "schema not found" in message:
        return "schema_missing"
    if "jsonschema unavailable" in message:
        return "dependency_unavailable"
    return "unsupported_runtime"


def _resolve_manifest_path(manifest_path_str: str) -> Path:
    p = Path(manifest_path_str)
    if not p.is_absolute():
        p = Path.cwd() / p
    return p.resolve()


def derive_post_health_path(manifest_path: Path) -> Path:
    """Derive ``<stem>.bundle_health.post.json`` adjacent to the manifest."""
    name = manifest_path.name
    if name.endswith(_MANIFEST_SUFFIX):
        stem = name[: -len(_MANIFEST_SUFFIX)]
    else:
        stem = manifest_path.stem
    return manifest_path.parent / (stem + _POST_HEALTH_SUFFIX)


def _range_ref_status(
    manifest_path: Path, chunk_index_path: Optional[Path]
) -> Tuple[str, str, Dict[str, str]]:
    """
    Resolve one range reference from the chunk index against the final bundle
    manifest. Prefers the current ``canonical_range`` field and falls back to the
    legacy ``content_range_ref``. Returns (status, message, validation) where
    status is one of: ``ok``, ``fail``, ``environment_error``, ``no_range_ref``,
    ``unavailable``.
    """
    not_applicable = _validation(
        "skipped_unavailable", "range_resolver", "check_not_applicable"
    )
    if chunk_index_path is None or not chunk_index_path.exists():
        return "unavailable", "chunk_index not available for range_ref check", not_applicable

    sample_ref: Optional[Dict[str, Any]] = None
    try:
        with chunk_index_path.open("r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(chunk, dict):
                    continue
                raw = chunk.get("canonical_range")
                if raw is None:
                    raw = chunk.get("content_range_ref")
                if raw is None:
                    continue
                if isinstance(raw, str):
                    try:
                        raw = json.loads(raw)
                    except json.JSONDecodeError as e:
                        return (
                            "fail",
                            f"invalid range reference JSON string: {e}",
                            _validation(
                                "structural_precheck",
                                "range_resolver",
                                "malformed_range_ref",
                            ),
                        )
                if not isinstance(raw, dict):
                    return (
                        "fail",
                        "range reference must be an object",
                        _validation(
                            "structural_precheck",
                            "range_resolver",
                            "malformed_range_ref",
                        ),
                    )
                sample_ref = raw
                break
    except (OSError, UnicodeError) as e:
        return "unavailable", f"could not read chunk_index: {e}", not_applicable

    if sample_ref is None:
        return "no_range_ref", "no range reference found; range_ref check skipped", not_applicable

    try:
        from .range_resolver import resolve_range_ref

        resolve_range_ref(manifest_path, sample_ref)
        return (
            "ok",
            "range reference resolved against bundle manifest",
            _validation("jsonschema", "range_resolver", "available"),
        )
    except Exception as e:  # noqa: BLE001 - classify below
        if _is_jsonschema_unavailable_error(e):
            return (
                "environment_error",
                "range_ref validation skipped: jsonschema unavailable",
                _validation(
                    "skipped_unavailable", "range_resolver", "dependency_unavailable"
                ),
            )
        if "schema file not found" in str(e).lower():
            return (
                "fail",
                f"range_ref resolution failed: {e}",
                _validation("skipped_unavailable", "range_resolver", "schema_missing"),
            )
        return (
            "fail",
            f"range_ref resolution failed: {e}",
            _validation("jsonschema", "range_resolver", "available"),
        )


def _compute_evidence(
    valid_roles: set[str],
    range_ref_status: str,
    jsonschema_available: bool,
    sqlite_ok: Optional[bool],
    output_health_valid: bool,
) -> Tuple[Optional[str], List[str]]:
    """
    Report achieved evidence levels using the existing vocabulary. Each level
    encodes its own prerequisites, so this never overstates what was reached.
    ``forensic_strict`` is evaluated by dedicated forensic preflight, not here.
    """
    reached: set[str] = set()

    readable = _CANONICAL_MD in valid_roles
    if readable:
        reached.add("readable")

    navigable = readable and _AGENT_PACK in valid_roles and _CHUNK_INDEX in valid_roles
    if navigable:
        reached.add("navigable")

    citable = navigable and _CITATION_MAP in valid_roles
    if citable:
        reached.add("citable")

    if citable and range_ref_status == "ok" and jsonschema_available:
        reached.add("range_strict")

    if navigable and _SQLITE_INDEX in valid_roles and bool(sqlite_ok):
        reached.add("searchable")

    if navigable and output_health_valid and _DEBUG_ROLES.issubset(valid_roles):
        reached.add("diagnostic_full")

    headline: Optional[str] = None
    for lvl in _CORE_LADDER:
        if lvl in reached:
            headline = lvl
        else:
            break

    ordered = [lvl for lvl in _EVIDENCE_ORDER if lvl in reached]
    return headline, ordered


def _validate_claim_evidence_map_schema(doc: Dict[str, Any]) -> Tuple[str, str]:
    """Returns (status, message): pass | fail | environment_error."""
    if jsonschema is None:
        return "environment_error", "claim_evidence_map schema validation skipped: jsonschema unavailable"

    schema_path = Path(__file__).parent.parent / "contracts" / "claim-evidence-map.v1.schema.json"
    if not schema_path.exists():
        return "environment_error", f"claim_evidence_map schema not found: {schema_path.name}"

    try:
        with schema_path.open("r", encoding="utf-8") as f:
            schema = json.load(f)
        jsonschema.validate(instance=doc, schema=schema)
        return "pass", "claim_evidence_map validates against claim-evidence-map.v1"
    except jsonschema.ValidationError as e:  # type: ignore[union-attr]
        return "fail", f"claim_evidence_map schema validation failed: {e.message}"
    except (OSError, json.JSONDecodeError) as e:
        return "environment_error", f"could not load claim_evidence_map schema: {e}"


def _post_emit_degradation(checks: List[Dict[str, Any]], *, jsonschema_available: bool) -> Dict[str, Any]:
    items: List[Dict[str, Any]] = []
    if not jsonschema_available:
        items.append(degradation_item("jsonschema_unavailable", "degraded", "jsonschema dependency unavailable for strict validation"))
        items.append(degradation_item("environment_degraded", "degraded", "runtime cannot execute every strict validation check"))
    for check in checks:
        name = str(check.get("name", ""))
        status = str(check.get("status", ""))
        validation = check.get("validation")
        if status != "skipped" or not isinstance(validation, dict):
            continue
        if validation.get("mode") != "skipped_unavailable":
            continue
        reason = str(validation.get("reason", check.get("detail", "skipped")))
        item_status = "not_applicable" if reason == "check_not_applicable" else "degraded"
        if name == "range_ref_resolution":
            items.append(degradation_item("range_strict_unavailable", item_status, reason, check=name))
        elif name == "claim_evidence_map_schema_valid":
            items.append(degradation_item("claim_evidence_validation_skipped", item_status, reason, check=name))
        if name in {"manifest_schema_valid", "range_ref_resolution", "claim_evidence_map_schema_valid"}:
            items.append(degradation_item("schema_validation_skipped", item_status, reason, check=name))
    return degradation_summary(items)


def _assemble(
    *,
    status: str,
    run_id: str,
    bundle_run_id: Any,
    manifest_path_str: str,
    checks: List[Dict[str, Any]],
    errors: List[str],
    warnings: List[str],
    evidence_level: Optional[str] = None,
    evidence_levels_reached: Optional[List[str]] = None,
    output_health_verdict: Optional[str] = None,
    redaction_status: Optional[Dict[str, Any]] = None,
    noise_hygiene: Optional[Dict[str, Any]] = None,
    artifact_count_checked: int = 0,
    hash_mismatch_count: int = 0,
    missing_artifact_count: int = 0,
    range_ref_resolution_status: Optional[str] = None,
    jsonschema_available: bool = False,
    agent_pack: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    health_degradation = _post_emit_degradation(
        checks, jsonschema_available=jsonschema_available
    )
    return {
        "kind": KIND,
        "health_status_model": list(HEALTH_STATUS_MODEL),
        "degradation": health_degradation,
        "version": VERSION,
        "dependencies": jsonschema_dependency(
            available=jsonschema_available,
            required_for=[
                "manifest_schema",
                "range_ref_schema",
                "claim_evidence_map_schema",
            ],
        ),
        "run_id": run_id,
        "bundle_run_id": bundle_run_id,
        "checked_at": _now_iso(),
        "bundle_manifest_path": manifest_path_str,
        "status": status,
        "checks": checks,
        "errors": errors,
        "warnings": warnings,
        "does_not_mean": list(DOES_NOT_MEAN),
        "independence_note": INDEPENDENCE_NOTE,
        "evidence_level": evidence_level,
        "evidence_levels_reached": evidence_levels_reached or [],
        "output_health_verdict": output_health_verdict,
        "redaction_status": redaction_status,
        "noise_hygiene": noise_hygiene,
        "artifact_count_checked": artifact_count_checked,
        "hash_mismatch_count": hash_mismatch_count,
        "missing_artifact_count": missing_artifact_count,
        "range_ref_resolution_status": range_ref_resolution_status,
        "agent_pack": agent_pack,
    }


def _validate_manifest_schema(manifest: Dict[str, Any]) -> Tuple[str, str]:
    """Returns (status, message): pass | fail | environment_error."""
    schema_path = Path(__file__).parent.parent / "contracts" / "bundle-manifest.v1.schema.json"
    if jsonschema is None:
        return "environment_error", "manifest schema validation skipped: jsonschema unavailable"
    if not schema_path.exists():
        return "environment_error", f"bundle manifest schema not found: {schema_path.name}"
    try:
        with schema_path.open("r", encoding="utf-8") as f:
            schema = json.load(f)
        jsonschema.validate(instance=manifest, schema=schema)
        return "pass", "manifest validates against bundle-manifest.v1"
    except jsonschema.ValidationError as e:  # type: ignore[union-attr]
        return "fail", f"manifest schema validation failed: {e.message}"
    except (OSError, json.JSONDecodeError) as e:
        return "environment_error", f"could not load bundle manifest schema: {e}"


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

def compute_post_emit_health(
    manifest_path_str: str,
    *,
    agent_pack_required: bool = True,
    run_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Validate the final emitted bundle surface. Pure: performs no writes.

    Returns a dict conforming to ``post-emit-health.v1.schema.json``.
    """
    run_id = run_id or str(uuid.uuid4())
    manifest_path = _resolve_manifest_path(manifest_path_str)
    manifest_path_str = str(manifest_path)
    manifest_dir = manifest_path.parent

    # ── blocked: cannot even enumerate the surface ───────────────────────────
    if not manifest_path.exists() or not manifest_path.is_file():
        return _assemble(
            status="blocked",
            run_id=run_id,
            bundle_run_id=None,
            manifest_path_str=manifest_path_str,
            checks=[_check("manifest_present", "blocked", "bundle manifest not found")],
            errors=["bundle manifest not found or not a file"],
            warnings=[],
            jsonschema_available=jsonschema is not None,
        )

    try:
        with manifest_path.open("r", encoding="utf-8") as f:
            manifest = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        return _assemble(
            status="blocked",
            run_id=run_id,
            bundle_run_id=None,
            manifest_path_str=manifest_path_str,
            checks=[_check("manifest_present", "blocked", f"cannot read manifest: {e}")],
            errors=[f"cannot read bundle manifest: {e}"],
            warnings=[],
            jsonschema_available=jsonschema is not None,
        )

    bundle_run_id = manifest.get("run_id") if isinstance(manifest, dict) else None

    if not isinstance(manifest, dict) or manifest.get("kind") != _BUNDLE_KIND:
        return _assemble(
            status="blocked",
            run_id=run_id,
            bundle_run_id=bundle_run_id,
            manifest_path_str=manifest_path_str,
            checks=[_check("manifest_present", "blocked", "not a repolens.bundle.manifest")],
            errors=["manifest is not a repolens.bundle.manifest; cannot certify bundle surface"],
            warnings=[],
            jsonschema_available=jsonschema is not None,
        )

    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        return _assemble(
            status="blocked",
            run_id=run_id,
            bundle_run_id=bundle_run_id,
            manifest_path_str=manifest_path_str,
            checks=[_check("manifest_present", "blocked", "manifest 'artifacts' is not a list")],
            errors=["manifest 'artifacts' is not a list; no inspectable artifact surface"],
            warnings=[],
            jsonschema_available=jsonschema is not None,
        )

    checks: List[Dict[str, Any]] = [_check("manifest_present", "pass")]
    errors: List[str] = []
    warnings: List[str] = []
    blocking: List[str] = []

    # ── manifest schema ──────────────────────────────────────────────────────
    schema_status, schema_msg = _validate_manifest_schema(manifest)
    if schema_status == "pass":
        checks.append(
            _check(
                "manifest_schema_valid",
                "pass",
                validation=_validation("jsonschema", "jsonschema", "available"),
            )
        )
    elif schema_status == "fail":
        checks.append(
            _check(
                "manifest_schema_valid",
                "fail",
                detail=schema_msg,
                validation=_validation("jsonschema", "jsonschema", "available"),
            )
        )
        errors.append(schema_msg)
    else:  # environment_error
        checks.append(
            _check(
                "manifest_schema_valid",
                "skipped",
                detail=schema_msg,
                validation=_validation(
                    "skipped_unavailable", "jsonschema", _schema_skip_reason(schema_msg)
                ),
            )
        )
        warnings.append(schema_msg)

    # ── per-artifact existence + hash ────────────────────────────────────────
    artifact_count_checked = 0
    missing_artifact_count = 0
    hash_mismatch_count = 0
    valid_roles: set[str] = set()
    by_role: Dict[str, Dict[str, Any]] = {}

    for index, art in enumerate(artifacts):
        if not isinstance(art, dict):
            errors.append(f"artifact at index {index} is not an object")
            continue
        artifact_count_checked += 1
        role = art.get("role") if isinstance(art.get("role"), str) else f"<index {index}>"
        if isinstance(art.get("role"), str):
            by_role.setdefault(art["role"], art)
        raw_path = art.get("path")
        expected_sha = art.get("sha256")

        if not isinstance(raw_path, str) or not raw_path:
            errors.append(f"artifact '{role}' has no path")
            continue
        try:
            target = resolve_secure_path(manifest_dir, raw_path)
        except ValueError as e:
            errors.append(f"artifact '{role}' path rejected: {e}")
            continue

        if not target.exists() or not target.is_file():
            missing_artifact_count += 1
            errors.append(f"artifact '{role}' is declared in the manifest but the file is missing: {raw_path}")
            continue

        actual = _sha256_file(target)
        if actual is None:
            errors.append(f"artifact '{role}' could not be read for hashing: {raw_path}")
            continue
        if isinstance(expected_sha, str) and _SHA256_RE.fullmatch(expected_sha):
            if actual != expected_sha:
                hash_mismatch_count += 1
                errors.append(
                    f"artifact '{role}' hash mismatch: manifest={expected_sha} actual={actual}"
                )
                continue
            valid_roles.add(art["role"]) if isinstance(art.get("role"), str) else None
        else:
            warnings.append(f"artifact '{role}' has no usable sha256 in manifest; integrity unverified")

    checks.append(
        _check(
            "artifact_paths_exist",
            "fail" if missing_artifact_count else "pass",
            f"{missing_artifact_count} of {artifact_count_checked} declared artifact file(s) missing",
        )
    )
    checks.append(
        _check(
            "artifact_hashes_match",
            "fail" if hash_mismatch_count else "pass",
            f"{hash_mismatch_count} hash mismatch(es) across {artifact_count_checked} artifact(s)",
        )
    )

    # ── canonical_md must be declared (truth-source surface) ─────────────────
    if _CANONICAL_MD not in by_role:
        blocking.append("canonical_md is not declared in the manifest; cannot certify a truth source")
        checks.append(_check("canonical_md_present", "blocked", "canonical_md absent from manifest"))
    else:
        checks.append(_check("canonical_md_present", "pass"))

    # ── agent_reading_pack: the defining post-emission certification surface ──
    pack_entry = by_role.get(_AGENT_PACK)
    pack_present = pack_entry is not None
    pack_authority = pack_entry.get("authority") if isinstance(pack_entry, dict) else None
    pack_canonicality = pack_entry.get("canonicality") if isinstance(pack_entry, dict) else None
    pack_hash_ok: Optional[bool] = _AGENT_PACK in valid_roles if pack_present else None
    pack_self_role_ok: Optional[bool] = None

    if not pack_present:
        if agent_pack_required:
            blocking.append("agent_reading_pack is not declared in the manifest; agent surface cannot be certified")
            checks.append(_check("agent_pack_present", "blocked", "agent_reading_pack absent from manifest"))
        else:
            checks.append(_check("agent_pack_present", "skipped", "agent_reading_pack not required for this run"))
    else:
        checks.append(_check("agent_pack_present", "pass"))
        # The pack is navigation, never content/canonical truth. A mis-declared
        # self-role is a defect (a navigation artifact claiming to be the source
        # of truth). This is the manifest-level form of "the pack does not list
        # itself as a canonical/content source incorrectly".
        mis_declared = (
            pack_authority == "canonical_content" or pack_canonicality == "content_source"
        )
        if mis_declared:
            pack_self_role_ok = False
            errors.append(
                "agent_reading_pack mis-declares itself as a canonical/content source "
                f"(authority={pack_authority!r}, canonicality={pack_canonicality!r})"
            )
            checks.append(_check("agent_pack_self_role", "fail", "pack declared as canonical/content"))
        else:
            pack_self_role_ok = True
            checks.append(_check("agent_pack_self_role", "pass", "pack declared as navigation/derived"))

    agent_pack = {
        "present": pack_present,
        "required": bool(agent_pack_required),
        "hash_ok": pack_hash_ok,
        "authority_declared": pack_authority,
        "canonicality_declared": pack_canonicality,
        "self_role_ok": pack_self_role_ok,
    }

    # ── range-ref / citation resolution (checkable where relevant) ───────────
    chunk_entry = by_role.get(_CHUNK_INDEX)
    chunk_index_path: Optional[Path] = None
    if isinstance(chunk_entry, dict) and isinstance(chunk_entry.get("path"), str):
        try:
            chunk_index_path = resolve_secure_path(manifest_dir, chunk_entry["path"])
        except ValueError:
            chunk_index_path = None

    rr_status, rr_msg, rr_validation = _range_ref_status(
        manifest_path, chunk_index_path
    )
    if rr_status == "ok":
        checks.append(
            _check(
                "range_ref_resolution",
                "pass",
                detail=rr_msg,
                validation=rr_validation,
            )
        )
    elif rr_status == "fail":
        checks.append(
            _check(
                "range_ref_resolution",
                "fail",
                detail=rr_msg,
                validation=rr_validation,
            )
        )
        errors.append(rr_msg)
    elif rr_status == "environment_error":
        checks.append(
            _check(
                "range_ref_resolution",
                "skipped",
                detail=rr_msg,
                validation=rr_validation,
            )
        )
        warnings.append(rr_msg)
    else:  # no_range_ref / unavailable — nothing to certify, non-blocking
        checks.append(
            _check(
                "range_ref_resolution",
                "skipped",
                detail=rr_msg,
                validation=rr_validation,
            )
        )

    # ── claim_evidence_map: optional globally, required for forensic_strict preflight ──
    claim_entry = by_role.get(_CLAIM_EVIDENCE_MAP)
    if claim_entry is None:
        claim_absence_reason = claim_absence_reason_from_manifest(manifest)
        reason_detail = claim_absence_reason_detail(claim_absence_reason)
        reason_suffix = (
            f" reason={claim_absence_reason} ({reason_detail})"
            if claim_absence_reason is not None
            else ""
        )
        checks.append(
            _check(
                "claim_evidence_map_present",
                "skipped",
                "claim_evidence_map_json absent; forensic_strict preflight would block"
                + reason_suffix,
            )
        )
        checks.append(
            _check(
                "claim_evidence_map_hash_ok",
                "skipped",
                "claim_evidence_map_json absent" + reason_suffix,
            )
        )
        checks.append(
            _check(
                "claim_evidence_map_schema_valid",
                "skipped",
                detail="claim_evidence_map_json absent" + reason_suffix,
                validation=_validation(
                    "skipped_unavailable", "jsonschema", "check_not_applicable"
                ),
            )
        )
    else:
        checks.append(_check("claim_evidence_map_present", "pass"))
        claim_hash_ok = _CLAIM_EVIDENCE_MAP in valid_roles
        if not claim_hash_ok:
            checks.append(
                _check(
                    "claim_evidence_map_hash_ok",
                    "fail",
                    "claim_evidence_map_json is declared but hash is missing/invalid",
                )
            )
            checks.append(
                _check(
                    "claim_evidence_map_schema_valid",
                    "skipped",
                    detail="schema validation skipped because claim_evidence_map_json hash is unverified",
                    validation=_validation(
                        "skipped_unavailable", "jsonschema", "check_not_applicable"
                    ),
                )
            )
            errors.append("claim_evidence_map_json is declared but hash is missing/invalid")
        else:
            checks.append(_check("claim_evidence_map_hash_ok", "pass"))
            claim_path_raw = claim_entry.get("path")
            if not isinstance(claim_path_raw, str) or not claim_path_raw:
                checks.append(_check("claim_evidence_map_schema_valid", "fail", "claim_evidence_map_json path missing"))
                errors.append("claim_evidence_map_json path missing")
            else:
                try:
                    claim_path = resolve_secure_path(manifest_dir, claim_path_raw)
                    with claim_path.open("r", encoding="utf-8") as f:
                        claim_doc = json.load(f)
                    if not isinstance(claim_doc, dict):
                        raise ValueError("claim_evidence_map_json root must be an object")
                except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as e:
                    checks.append(_check("claim_evidence_map_schema_valid", "fail", f"cannot parse claim_evidence_map_json: {e}"))
                    errors.append(f"cannot parse claim_evidence_map_json: {e}")
                else:
                    claim_schema_status, claim_schema_msg = _validate_claim_evidence_map_schema(claim_doc)
                    if claim_schema_status == "pass":
                        checks.append(
                            _check(
                                "claim_evidence_map_schema_valid",
                                "pass",
                                validation=_validation(
                                    "jsonschema", "jsonschema", "available"
                                ),
                            )
                        )
                    elif claim_schema_status == "fail":
                        checks.append(
                            _check(
                                "claim_evidence_map_schema_valid",
                                "fail",
                                detail=claim_schema_msg,
                                validation=_validation(
                                    "jsonschema", "jsonschema", "available"
                                ),
                            )
                        )
                        errors.append(claim_schema_msg)
                    else:
                        checks.append(
                            _check(
                                "claim_evidence_map_schema_valid",
                                "skipped",
                                detail=claim_schema_msg,
                                validation=_validation(
                                    "skipped_unavailable",
                                    "jsonschema",
                                    _schema_skip_reason(claim_schema_msg),
                                ),
                            )
                        )
                        warnings.append(claim_schema_msg)

    # ── redaction: reported, never enforced (enforcement is PR A5) ───────────
    capabilities = manifest.get("capabilities") if isinstance(manifest.get("capabilities"), dict) else {}
    redact_value = capabilities.get("redaction")
    redaction_status = {
        "available": isinstance(redact_value, bool),
        "redact_secrets_enabled": redact_value if isinstance(redact_value, bool) else None,
        "enforced": False,
    }
    checks.append(
        _check(
            "redaction_status_reported",
            "pass",
            f"redaction={redact_value!r} (reported only; not enforced in post_emit_health)",
        )
    )

    # ── output_health: OBSERVATION ONLY (never gates post-emit status) ───────
    # Coverage is based on a *validated* artifact, not a bare manifest declaration:
    # a declared-but-missing/hash-mismatched output_health is not trusted and must
    # not boost evidence (e.g. diagnostic_full) or supply a verdict.
    output_health_verdict: Optional[str] = None
    output_health_declared = _OUTPUT_HEALTH in by_role
    output_health_valid = _OUTPUT_HEALTH in valid_roles
    sqlite_ok: Optional[bool] = None
    noise_hygiene: Dict[str, Any] = {"available": False, "excluded_noise_count": None, "source": None}

    oh_entry = by_role.get(_OUTPUT_HEALTH)
    if output_health_valid and isinstance(oh_entry, dict) and isinstance(oh_entry.get("path"), str):
        try:
            oh_path = resolve_secure_path(manifest_dir, oh_entry["path"])
        except ValueError:
            oh_path = None
        if oh_path is not None and oh_path.exists():
            try:
                with oh_path.open("r", encoding="utf-8") as f:
                    oh_doc = json.load(f)
            except (OSError, json.JSONDecodeError):
                oh_doc = None
            if isinstance(oh_doc, dict):
                v = oh_doc.get("verdict")
                output_health_verdict = v if isinstance(v, str) else None
                raw_checks = oh_doc.get("checks")
                oh_checks = compact_check_projection(oh_doc) if isinstance(raw_checks, dict) else {}
                rc_match = oh_checks.get("sqlite_row_count_matches_chunk_count")
                fts_ok = oh_checks.get("fts_content_non_empty")
                if rc_match is not None or fts_ok is not None:
                    sqlite_ok = bool(rc_match) and bool(fts_ok)
                # Noise-hygiene signals are surfaced only where already available
                # (e.g. a future A2 excluded_noise diagnostic). Never synthesized.
                excluded = oh_checks.get("excluded_noise")
                if excluded is None:
                    excluded = oh_doc.get("excluded_noise")
                hygiene = oh_checks.get("noise_hygiene")
                if not isinstance(hygiene, dict):
                    hygiene = oh_doc.get("noise_hygiene")
                hygiene_available = isinstance(hygiene, dict) and hygiene.get("available") is True
                excluded_count: Optional[int] = None
                legacy_available = False
                if isinstance(excluded, list):
                    excluded_count = len(excluded)
                    legacy_available = True
                elif isinstance(excluded, dict) and hygiene_available:
                    raw_count = excluded.get("count")
                    excluded_count = raw_count if isinstance(raw_count, int) else None
                if excluded_count is None and hygiene_available:
                    raw_count = hygiene.get("excluded_noise_count")
                    excluded_count = raw_count if isinstance(raw_count, int) else None
                if excluded_count is not None and (hygiene_available or legacy_available):
                    noise_hygiene = {
                        "available": True,
                        "excluded_noise_count": excluded_count,
                        "source": "output_health",
                    }

    if output_health_valid:
        oh_obs_status, oh_obs_detail = "pass", (
            f"output_health.verdict={output_health_verdict!r} (observation only; "
            "does not imply post_emit_health.status=pass)"
        )
    elif output_health_declared:
        oh_obs_status, oh_obs_detail = "skipped", (
            "output_health is declared but not hash-validated; verdict not trusted"
        )
    else:
        oh_obs_status, oh_obs_detail = "skipped", "output_health not declared in manifest"
    checks.append(_check("output_health_observed", oh_obs_status, oh_obs_detail))

    # ── evidence level (existing vocabulary; not an understanding verdict) ────
    evidence_level, evidence_levels_reached = _compute_evidence(
        valid_roles,
        rr_status,
        jsonschema_available=jsonschema is not None,
        sqlite_ok=sqlite_ok,
        output_health_valid=output_health_valid,
    )
    checks.append(
        _check(
            "evidence_level_reported",
            "pass",
            f"achieved evidence_level={evidence_level!r}",
        )
    )

    # ── status (blocked > fail > warn > pass) ────────────────────────────────
    if blocking:
        status = "blocked"
        # surface blocking reasons in errors for visibility without losing the
        # blocked headline
        errors = list(errors) + blocking
    elif errors:
        status = "fail"
    elif warnings:
        status = "warn"
    else:
        status = "pass"

    return _assemble(
        status=status,
        run_id=run_id,
        bundle_run_id=bundle_run_id,
        manifest_path_str=manifest_path_str,
        checks=checks,
        errors=errors,
        warnings=warnings,
        evidence_level=evidence_level,
        evidence_levels_reached=evidence_levels_reached,
        output_health_verdict=output_health_verdict,
        redaction_status=redaction_status,
        noise_hygiene=noise_hygiene,
        artifact_count_checked=artifact_count_checked,
        hash_mismatch_count=hash_mismatch_count,
        missing_artifact_count=missing_artifact_count,
        range_ref_resolution_status=rr_status,
        jsonschema_available=jsonschema is not None,
        agent_pack=agent_pack,
    )


def _read_binding_input(path: Path, *, label: str) -> bytes:
    try:
        return read_regular_bytes(path)
    except (RootedFilesystemError, OSError) as exc:
        raise PostEmitHealthBindingError(f"cannot read {label}: {exc}") from exc


def _parse_post_emit_health_binding_input(payload: bytes) -> Dict[str, Any]:
    try:
        post_health = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PostEmitHealthBindingError(
            "post_emit_health must be valid UTF-8 JSON before final binding"
        ) from exc
    if not isinstance(post_health, dict):
        raise PostEmitHealthBindingError(
            "post_emit_health JSON root must be an object before final binding"
        )
    if post_health.get("kind") != KIND or post_health.get("version") != VERSION:
        raise PostEmitHealthBindingError(
            "post_emit_health kind/version mismatch before final binding"
        )
    return post_health


def _assert_final_manifest_hash(path: Path, expected_sha256: str) -> None:
    current = _read_binding_input(path, label="final bundle manifest")
    if hashlib.sha256(current).hexdigest() != expected_sha256:
        raise PostEmitHealthBindingError(
            "final bundle manifest changed while post_emit_health was being bound"
        )


def bind_post_emit_health_to_final_manifest(
    manifest_path_str: str,
    post_health_path_str: str,
) -> str:
    """Atomically bind an existing health report to final manifest bytes.

    The report is intentionally not a manifest artifact, so this additive hash
    does not create a self-hash cycle. Existing validation metadata is preserved.
    """
    manifest_path = _resolve_manifest_path(manifest_path_str)
    post_health_path = Path(post_health_path_str)
    if not post_health_path.is_absolute():
        post_health_path = Path.cwd() / post_health_path

    manifest_bytes = _read_binding_input(
        manifest_path, label="final bundle manifest"
    )
    post_health = _parse_post_emit_health_binding_input(
        _read_binding_input(post_health_path, label="post_emit_health")
    )
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    post_health["bundle_manifest_sha256"] = manifest_sha256
    rendered = (json.dumps(post_health, indent=2) + "\n").encode("utf-8")

    # Reject changes that occurred while parsing before making the sidecar visible.
    _assert_final_manifest_hash(manifest_path, manifest_sha256)
    try:
        atomic_write_bytes(post_health_path, rendered)
    except (RootedFilesystemError, OSError) as exc:
        raise PostEmitHealthBindingError(
            f"cannot persist final manifest binding safely: {exc}"
        ) from exc
    # Close the remaining write-to-observation race before publication continues.
    _assert_final_manifest_hash(manifest_path, manifest_sha256)
    return manifest_sha256


def write_post_emit_health(
    manifest_path_str: str,
    output_path_str: Optional[str] = None,
    *,
    agent_pack_required: bool = True,
    run_id: Optional[str] = None,
) -> Tuple[Path, Dict[str, Any]]:
    """
    Compute the post-emit health report and persist it as
    ``<stem>.bundle_health.post.json`` (or ``output_path_str`` if given).

    The written artifact is intentionally NOT registered in the bundle manifest:
    persistence does not mutate manifest truth, and the report never verifies its
    own hash. Returns ``(written_path, report)``.
    """
    report = compute_post_emit_health(
        manifest_path_str, agent_pack_required=agent_pack_required, run_id=run_id
    )
    manifest_path = _resolve_manifest_path(manifest_path_str)
    if output_path_str:
        out = Path(output_path_str)
        out = out if out.is_absolute() else Path.cwd() / out
    else:
        out = derive_post_health_path(manifest_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    logger.debug("post_emit_health written to %s (status=%s)", out, report["status"])
    return out, report
