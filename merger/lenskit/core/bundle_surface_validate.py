"""Real-dump bundle surface self-check.

This validator closes the gap that produced the original report: a real
single-repo dump whose ``docs/doc-freshness-registry.yml`` exists, yet whose
emitted bundle silently lacked ``claim_evidence_map_json`` *and* carried no
machine-readable absence reason, while ``output_health`` still read ``pass`` and
the agent reading pack still announced the claim map as missing. The pre-emit
``output_health`` cannot catch this (it runs before the pack and never inspects
the claim-map surface), and a stale runtime can drop the claim map without any
of the existing gates objecting.

``validate_bundle_surface`` inspects the **final** emitted surface and asserts
its internal coherence:

- claim-evidence-map surface: the map is present XOR a machine-readable absence
  reason is set — never silently absent;
- agent reading pack consistency: a present claim map MUST be summarized in the
  pack (with its artifact line), never announced as absent, and the legacy
  "not yet produced" placeholder is treated as drift;
- agent reading pack front door: the emitted pack MUST expose the v1.1 version
  sentinel, required navigation sections, and change-impact caution markers;
- post-emit health: a persisted ``post_emit_health`` sidecar exists (so
  ``output_health=pass`` cannot be mistaken for forensic-readiness) AND its
  ``status`` is propagated — a present-but-failed post_emit_health drags the
  surface down rather than passing on mere presence;
- surface link coherence: recorded ``links`` pointers resolve to real sidecars;
- generator provenance: ``name`` / ``version`` / ``config_sha256`` are present
  and the ``runtime`` block is available so runtime/service drift is diagnosable.

It is read-only and performs no writes. It is **not** a truth/forensic verdict:
a ``pass`` means the emitted surface is internally coherent, not that any claim
is true. ``forensic_strict`` promotion remains a separate decision.

Status model (precedence ``fail`` > ``blocked`` > ``warn`` > ``pass``):
- ``blocked`` — a required surface is a *declared* gap (e.g. claim map absent
  with a valid absence reason while it is required); the run is not certifiable
  but the gap is honest and machine-readable.
- ``fail``    — an active surface *defect* (claim map absent with no reason while
  required, a present-map/announced-absent contradiction, a stale pack
  placeholder, or missing generator provenance fields).
- ``warn``    — usable but degraded (e.g. post-emit health not persisted, or the
  ``generator.runtime`` block missing so drift is not diagnosable).
- ``pass``    — the emitted surface is internally coherent.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple, TypedDict, Union

from .claim_evidence_diagnostics import (
    claim_absence_reason_detail,
    claim_absence_reason_from_manifest,
)
from .clock import now_utc
from .constants import ArtifactRole
from .path_security import resolve_secure_path
from .post_emit_health import derive_post_health_path

KIND = "lenskit.bundle_surface_validation"
VERSION = "1.0"
_BUNDLE_KIND = "repolens.bundle.manifest"

ValidationMode = Literal["jsonschema", "minimal_fallback", "structural_precheck"]
ValidationReason = Literal[
    "available",
    "dependency_missing",
    "dependency_unavailable",
    "check_not_applicable",
    "surface_coherence_check",
]
CheckStatus = Literal["pass", "warn", "fail", "blocked", "skipped"]


class Validation(TypedDict):
    mode: ValidationMode
    engine: str
    reason: ValidationReason


# Check models newly emitted producer checks. The JSON schema keeps
# check.validation optional for backwards compatibility with older reports.
class Check(TypedDict):
    name: str
    status: CheckStatus
    detail: str
    validation: Validation


_ENGINE_NAME = "bundle_surface_validate"

_CLAIM_MAP_ROLE = ArtifactRole.CLAIM_EVIDENCE_MAP_JSON.value
_AGENT_PACK_ROLE = ArtifactRole.AGENT_READING_PACK.value
_OUTPUT_HEALTH_ROLE = ArtifactRole.OUTPUT_HEALTH.value

_CARD_SURFACE_ROLES = {
    ArtifactRole.LENS_CARDS_JSONL.value: {
        "contract": {"id": "lens-card", "version": "v1"},
        "authority": "navigation_index",
        "canonicality": "derived",
        "risk_class": "navigation",
    },
    ArtifactRole.CONCEPT_CARDS_JSONL.value: {
        "contract": {"id": "concept-card", "version": "v1"},
        "authority": "navigation_index",
        "canonicality": "derived",
        "risk_class": "navigation",
    },
    ArtifactRole.RELATION_CARDS_JSONL.value: {
        "contract": {"id": "relation-card", "version": "v1"},
        "authority": "navigation_index",
        "canonicality": "derived",
        "risk_class": "navigation",
    },
    ArtifactRole.PR_DELTA_CARDS_JSONL.value: {
        "contract": {"id": "pr-delta-card", "version": "v1"},
        "authority": "diagnostic_signal",
        "canonicality": "diagnostic",
        "risk_class": "diagnostic",
    },
}

# Pack markers (see core/agent_reading_pack.py). The surface validator keeps
# these explicit because it guards the emitted runtime artifact, not merely the
# producer's in-process version constant.
_AGENT_PACK_V1_1_SENTINEL_PREFIX = "<!-- ARTIFACT:agent_reading_pack VERSION:v1.1 "
_AGENT_PACK_V1_1_FRONT_DOOR_MARKERS = (
    "## REQUIRED_READING_BY_TASK",
    "## WHEN_CANONICAL_MD_ONLY_IS_INSUFFICIENT",
    "## SIDECAR_USAGE_RULES",
    "## ANSWER_COMPLIANCE_CHECKLIST",
    "## DO_NOT_CLAIM",
    "`change_impact`",
    "relation or path proximity alone does not prove change impact",
)
_PACK_SUMMARY_HEADER = "## CLAIM_EVIDENCE_MAP_SUMMARY"
_PACK_ABSENT_PLACEHOLDER = "_No verified `claim_evidence_map_json` artifact present._"
# Legacy placeholder emitted by stale builds that predate the claim-map wiring.
_PACK_LEGACY_PLACEHOLDER = "claim_evidence_map is not yet produced"

# Status precedence — highest severity wins. An active defect (fail) outranks a
# declared, honest gap (blocked).
_PRECEDENCE = {"pass": 0, "warn": 1, "blocked": 2, "fail": 3}


def _now_iso() -> str:
    ts = now_utc()
    if isinstance(ts, str):
        return ts if ts.endswith("Z") else ts + "Z"
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def _surface_validation(
    reason: ValidationReason = "surface_coherence_check",
) -> Validation:
    return {"mode": "structural_precheck", "engine": _ENGINE_NAME, "reason": reason}


def _surface_check(
    name: str,
    status: CheckStatus,
    detail: str,
    reason: ValidationReason = "surface_coherence_check",
) -> Check:
    return {
        "name": name,
        "status": status,
        "detail": detail,
        "validation": _surface_validation(reason),
    }


def _rollup(checks: List[Check]) -> str:
    worst = "pass"
    for c in checks:
        if _PRECEDENCE.get(c["status"], 0) > _PRECEDENCE[worst]:
            worst = c["status"]
    return worst


def _assemble(
    *,
    status: str,
    run_id: str,
    bundle_run_id: Any,
    manifest_path_str: str,
    require_claim_evidence_map: bool,
    checks: List[Dict[str, str]],
) -> Dict[str, Any]:
    return {
        "kind": KIND,
        "version": VERSION,
        "run_id": run_id,
        "bundle_run_id": bundle_run_id,
        "checked_at": _now_iso(),
        "bundle_manifest_path": manifest_path_str,
        "require_claim_evidence_map": bool(require_claim_evidence_map),
        "status": status,
        "checks": checks,
        "does_not_mean": ["claims_true", "repo_understood", "forensic_ready"],
    }


def _by_role(artifacts: List[Any]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for art in artifacts:
        if isinstance(art, dict) and isinstance(art.get("role"), str):
            out.setdefault(art["role"], art)
    return out


def _read_pack_text(
    manifest_dir: Path, pack_entry: Optional[Dict[str, Any]]
) -> Optional[str]:
    if not isinstance(pack_entry, dict):
        return None
    raw_path = pack_entry.get("path")
    if not isinstance(raw_path, str) or not raw_path:
        return None
    try:
        path = resolve_secure_path(manifest_dir, raw_path)
    except ValueError:
        return None
    if not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None



def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _card_surface_checks(
    *,
    by_role: Dict[str, Dict[str, Any]],
    manifest_dir: Path,
) -> List[Check]:
    """Validate optional Card JSONL surfaces when they are present.

    Absence is allowed because Card artifacts are optional/profile-dependent.
    Presence, however, must be coherent: manifest metadata, file existence,
    byte/hash accounting and JSONL parseability must all hold.
    """
    checks: List[Check] = []
    present = [role for role in _CARD_SURFACE_ROLES if role in by_role]
    if not present:
        return [
            _surface_check(
                "card_surface_artifacts",
                "skipped",
                "no bundle-registered card artifacts present; optional surface absent",
            )
        ]

    problems: List[str] = []
    parsed_counts: Dict[str, int] = {}
    for role in present:
        entry = by_role[role]
        expected = _CARD_SURFACE_ROLES[role]
        for key in ("content_type", "authority", "canonicality", "risk_class"):
            expected_value = (
                "application/x-ndjson" if key == "content_type" else expected[key]
            )
            actual = entry.get(key)
            if actual != expected_value:
                problems.append(
                    f"{role}: {key}={actual!r}, expected {expected_value!r}"
                )
        if entry.get("contract") != expected["contract"]:
            problems.append(
                f"{role}: contract={entry.get('contract')!r}, "
                f"expected {expected['contract']!r}"
            )
        if entry.get("regenerable") is not True:
            problems.append(f"{role}: regenerable is not true")
        if entry.get("staleness_sensitive") is not True:
            problems.append(f"{role}: staleness_sensitive is not true")

        raw_path = entry.get("path")
        if not isinstance(raw_path, str) or not raw_path:
            problems.append(f"{role}: path missing or invalid")
            continue
        try:
            path = resolve_secure_path(manifest_dir, raw_path)
        except ValueError as exc:
            problems.append(f"{role}: path rejected: {exc}")
            continue
        if not path.is_file():
            problems.append(f"{role}: file does not exist at {raw_path}")
            continue
        try:
            size = path.stat().st_size
            sha = _sha256_file(path)
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            problems.append(f"{role}: file unreadable: {type(exc).__name__}: {exc}")
            continue
        if entry.get("bytes") != size:
            problems.append(
                f"{role}: bytes={entry.get('bytes')!r}, actual={size}"
            )
        if entry.get("sha256") != sha:
            expected_sha = entry.get("sha256")
            problems.append(
                f"{role}: sha256 mismatch manifest={str(expected_sha)[:12]} "
                f"actual={sha[:12]}"
            )
        rows = [line for line in text.splitlines() if line.strip()]
        if not rows:
            problems.append(f"{role}: JSONL is empty")
            continue
        count = 0
        for line_no, line in enumerate(rows, start=1):
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                problems.append(f"{role}: invalid JSONL at line {line_no}: {exc.msg}")
                break
            if not isinstance(item, dict):
                problems.append(f"{role}: JSONL line {line_no} is not an object")
                break
            count += 1
        parsed_counts[role] = count

    if problems:
        return [
            _surface_check(
                "card_surface_artifacts",
                "fail",
                "; ".join(problems),
            )
        ]
    detail = ", ".join(f"{role}={parsed_counts[role]}" for role in present)
    checks.append(
        _surface_check(
            "card_surface_artifacts",
            "pass",
            "card artifact metadata, files, hashes and JSONL parseability coherent: "
            + detail,
        )
    )
    return checks


def _card_agent_pack_index_check(
    *,
    by_role: Dict[str, Dict[str, Any]],
    pack_present_in_manifest: bool,
    pack_text: Optional[str],
) -> Check:
    present = [role for role in _CARD_SURFACE_ROLES if role in by_role]
    if not present:
        return _surface_check(
            "card_agent_reading_pack_index",
            "skipped",
            "no card artifacts present; no card index linkage required",
        )
    if not pack_present_in_manifest:
        return _surface_check(
            "card_agent_reading_pack_index",
            "fail",
            "card artifacts present but agent_reading_pack is not declared",
        )
    if pack_text is None:
        return _surface_check(
            "card_agent_reading_pack_index",
            "warn",
            "card artifacts present but agent_reading_pack is not readable",
        )
    missing = [role for role in present if role not in pack_text]
    if missing:
        return _surface_check(
            "card_agent_reading_pack_index",
            "fail",
            "agent_reading_pack does not reference present card artifact role(s): "
            + ", ".join(missing),
        )
    return _surface_check(
        "card_agent_reading_pack_index",
        "pass",
        "agent_reading_pack references all present card artifact roles: "
        + ", ".join(present),
    )


def _pack_front_door_v1_1_surface_check(
    *,
    pack_present_in_manifest: bool,
    pack_text: Optional[str],
) -> Check:
    if not pack_present_in_manifest:
        return _surface_check(
            "agent_reading_pack_front_door_v1_1",
            "fail",
            "agent_reading_pack not declared in manifest; navigation surface absent",
        )
    if pack_text is None:
        return _surface_check(
            "agent_reading_pack_front_door_v1_1",
            "fail",
            "agent_reading_pack declared but not readable; navigation surface "
            "stale/incomplete",
        )

    missing = []
    if not pack_text.startswith(_AGENT_PACK_V1_1_SENTINEL_PREFIX):
        missing.append("ARTIFACT:agent_reading_pack VERSION:v1.1 sentinel")
    missing.extend(
        marker
        for marker in _AGENT_PACK_V1_1_FRONT_DOOR_MARKERS
        if marker not in pack_text
    )
    if missing:
        return _surface_check(
            "agent_reading_pack_front_door_v1_1",
            "fail",
            "agent_reading_pack missing v1.1 front-door marker(s): "
            + ", ".join(missing)
            + "; navigation surface stale/incomplete",
        )
    return _surface_check(
        "agent_reading_pack_front_door_v1_1",
        "pass",
        "agent_reading_pack exposes the complete v1.1 front-door navigation surface",
    )


def _claim_surface_check(
    *,
    claim_present: bool,
    absence_reason: Optional[str],
    require: bool,
) -> Check:
    """The headline check: map present XOR machine-readable absence reason."""
    if claim_present and absence_reason is not None:
        return _surface_check(
            "claim_evidence_map_surface",
            "fail",
            "contradictory surface: claim_evidence_map_json present but "
            f"claim_evidence_map_absence_reason={absence_reason} is also set",
        )
    if claim_present:
        return _surface_check(
            "claim_evidence_map_surface",
            "pass",
            "claim_evidence_map_json present and consistent",
        )
    # absent
    if absence_reason is not None:
        detail = (
            f"claim_evidence_map_json absent; machine-readable reason="
            f"{absence_reason} ({claim_absence_reason_detail(absence_reason)})"
        )
        if require:
            return _surface_check(
                "claim_evidence_map_surface",
                "blocked",
                detail + "; required for this bundle",
            )
        return _surface_check("claim_evidence_map_surface", "pass", detail)
    # absent and no reason — the silent contradiction this gate exists to catch.
    detail = (
        "claim_evidence_map_json missing and no claim_evidence_map_absence_reason set "
        "(silent absence)"
    )
    if require:
        return _surface_check(
            "claim_evidence_map_surface", "fail", detail + "; required for this bundle"
        )
    return _surface_check("claim_evidence_map_surface", "warn", detail)


def _pack_consistency_surface_check(
    *,
    pack_present_in_manifest: bool,
    pack_text: Optional[str],
    claim_present: bool,
    absence_reason: Optional[str],
) -> Check:
    if not pack_present_in_manifest:
        return _surface_check(
            "agent_reading_pack_consistency",
            "skipped",
            "agent_reading_pack not declared in manifest",
        )
    if pack_text is None:
        return _surface_check(
            "agent_reading_pack_consistency",
            "warn",
            "agent_reading_pack declared but not readable for consistency check",
        )
    if _PACK_LEGACY_PLACEHOLDER in pack_text:
        return _surface_check(
            "agent_reading_pack_consistency",
            "fail",
            "agent_reading_pack contains the legacy 'claim_evidence_map is not yet "
            "produced' placeholder (stale generator build)",
        )
    has_summary_artifact = (
        _PACK_SUMMARY_HEADER in pack_text and "- artifact:" in pack_text
    )
    has_absent_placeholder = _PACK_ABSENT_PLACEHOLDER in pack_text
    if claim_present:
        # A present claim map MUST be visible in the pack as a summary with an
        # artifact line. Anything else — the absent placeholder, or no summary at
        # all — is drift between the manifest and the navigation surface.
        if not has_summary_artifact:
            reason = (
                "announces it as absent"
                if has_absent_placeholder
                else "does not summarize it (no CLAIM_EVIDENCE_MAP_SUMMARY artifact line)"
            )
            return _surface_check(
                "agent_reading_pack_consistency",
                "fail",
                f"claim_evidence_map_json present in manifest but agent_reading_pack {reason}",
            )
        return _surface_check(
            "agent_reading_pack_consistency",
            "pass",
            "agent_reading_pack summarizes the present claim_evidence_map",
        )
    # claim map absent: a placeholder is expected; if a reason is set the pack
    # should surface it rather than carry a bare blanket gap.
    if has_summary_artifact:
        return _surface_check(
            "agent_reading_pack_consistency",
            "fail",
            "claim_evidence_map_json absent from manifest but agent_reading_pack "
            "advertises a CLAIM_EVIDENCE_MAP_SUMMARY artifact line",
        )
    if absence_reason is not None and "reason=" not in pack_text:
        return _surface_check(
            "agent_reading_pack_consistency",
            "warn",
            "claim_evidence_map absent with reason "
            f"{absence_reason} but agent_reading_pack does not surface the reason",
        )
    return _surface_check(
        "agent_reading_pack_consistency",
        "pass",
        "agent_reading_pack consistent with absent claim_evidence_map",
    )


# post_emit_health.status → surface-check status. A present-but-failed
# post_emit_health must NOT pass: persistence ("is present") is separated from
# the verdict ("says green"). Unknown/invalid status is treated conservatively.
_POST_STATUS_TO_CHECK: Dict[str, CheckStatus] = {
    "pass": "pass",
    "warn": "warn",
    "fail": "fail",
    "blocked": "blocked",
}


def _post_emit_health_checks(*, manifest_path: Path, require: bool) -> List[Check]:
    """Emit persistence and, when readable, propagated post_emit_health status checks."""
    sidecar = derive_post_health_path(manifest_path)
    if not sidecar.is_file():
        detail = (
            f"post_emit_health sidecar not persisted at {sidecar.name}; "
            "output_health alone (pre-emit) is not a forensic-ready signal"
        )
        persisted = "warn" if require else "skipped"
        return [_surface_check("post_emit_health_persisted", persisted, detail)]

    try:
        doc = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return [
            _surface_check(
                "post_emit_health_persisted",
                "warn",
                f"post_emit_health sidecar present at {sidecar.name} but unreadable",
            )
        ]

    persisted_check = _surface_check(
        "post_emit_health_persisted",
        "pass",
        f"post_emit_health persisted at {sidecar.name}",
    )
    post_status = doc.get("status") if isinstance(doc, dict) else None
    if not isinstance(post_status, str) or post_status not in _POST_STATUS_TO_CHECK:
        status_check = _surface_check(
            "post_emit_health_status",
            "warn",
            f"post_emit_health persisted but status is missing/invalid ({post_status!r})",
        )
    else:
        # Propagate the verdict: a present post_emit_health that itself failed
        # must drag the surface down, not pass on mere existence.
        status_check = _surface_check(
            "post_emit_health_status",
            _POST_STATUS_TO_CHECK[post_status],
            f"post_emit_health.status={post_status}",
        )
    return [persisted_check, status_check]


def _links_coherence_surface_check(
    manifest: Dict[str, Any], manifest_dir: Path
) -> Check:
    """Validate that the machine-readable surface links resolve to real sidecars.

    When the generator records ``post_emit_health_path`` /
    ``bundle_surface_validation_path`` in ``links``, those must point at existing
    files — a dangling link is incoherent machine-readable truth. Absent links
    (a pre-emit validation pass, where links are not set yet, or a legacy
    manifest) are skipped, not failed. The link/sidecar *status* equality is
    guaranteed by construction at emit time and is intentionally not re-derived
    here (a self-check must not re-validate its own verdict)."""
    links = manifest.get("links") if isinstance(manifest.get("links"), dict) else {}
    referenced = {
        "post_emit_health_path": links.get("post_emit_health_path"),
        "bundle_surface_validation_path": links.get("bundle_surface_validation_path"),
    }
    if all(v is None for v in referenced.values()):
        return _surface_check(
            "surface_links_coherent",
            "skipped",
            "no surface links recorded (pre-emit run or legacy manifest)",
        )
    problems: List[str] = []
    for key, raw in referenced.items():
        if raw is None:
            continue
        if not isinstance(raw, str) or not raw:
            problems.append(f"{key} is not a usable path")
            continue
        try:
            target = resolve_secure_path(manifest_dir, raw)
        except ValueError as e:
            problems.append(f"{key} rejected: {e}")
            continue
        if not target.is_file():
            problems.append(f"{key} '{raw}' does not resolve to an existing file")
    if problems:
        return _surface_check("surface_links_coherent", "fail", "; ".join(problems))
    return _surface_check(
        "surface_links_coherent",
        "pass",
        "recorded surface links resolve to existing sidecars",
    )


def _generator_provenance_surface_check(generator: Any) -> Check:
    if not isinstance(generator, dict):
        return _surface_check(
            "generator_provenance", "fail", "generator block missing or not an object"
        )
    missing = [k for k in ("name", "version", "config_sha256") if not generator.get(k)]
    if missing:
        return _surface_check(
            "generator_provenance",
            "fail",
            f"generator block missing required field(s): {', '.join(missing)}",
        )
    runtime = generator.get("runtime")
    if not isinstance(runtime, dict) or not runtime.get("module"):
        return _surface_check(
            "generator_provenance",
            "warn",
            "generator.runtime block missing; runtime/service drift is not "
            "diagnosable from this bundle",
        )
    commit = runtime.get("git_commit")
    return _surface_check(
        "generator_provenance",
        "pass",
        f"generator provenance complete (module={runtime.get('module')}, "
        f"git_commit={commit})",
    )


def validate_bundle_surface(
    manifest_path: Union[str, Path],
    *,
    require_claim_evidence_map: bool = False,
    run_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Validate the coherence of a final emitted bundle surface.

    Pure: performs no writes. Returns a dict conforming to
    ``bundle-surface-validation.v1`` (``kind`` ==
    ``lenskit.bundle_surface_validation``).
    """
    run_id = run_id or str(uuid.uuid4())
    mp = Path(manifest_path)
    if not mp.is_absolute():
        mp = Path.cwd() / mp
    mp = mp.resolve()
    manifest_path_str = str(mp)

    # ── blocked: cannot even enumerate the surface ───────────────────────────
    if not mp.is_file():
        return _assemble(
            status="blocked",
            run_id=run_id,
            bundle_run_id=None,
            manifest_path_str=manifest_path_str,
            require_claim_evidence_map=require_claim_evidence_map,
            checks=[
                _surface_check(
                    "manifest_present", "blocked", "bundle manifest not found"
                )
            ],
        )
    try:
        manifest = json.loads(mp.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as e:
        return _assemble(
            status="blocked",
            run_id=run_id,
            bundle_run_id=None,
            manifest_path_str=manifest_path_str,
            require_claim_evidence_map=require_claim_evidence_map,
            checks=[
                _surface_check(
                    "manifest_present", "blocked", f"cannot read manifest: {e}"
                )
            ],
        )

    bundle_run_id = manifest.get("run_id") if isinstance(manifest, dict) else None
    if not isinstance(manifest, dict) or manifest.get("kind") != _BUNDLE_KIND:
        return _assemble(
            status="blocked",
            run_id=run_id,
            bundle_run_id=bundle_run_id,
            manifest_path_str=manifest_path_str,
            require_claim_evidence_map=require_claim_evidence_map,
            checks=[
                _surface_check(
                    "manifest_present", "blocked", "not a repolens.bundle.manifest"
                )
            ],
        )
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        return _assemble(
            status="blocked",
            run_id=run_id,
            bundle_run_id=bundle_run_id,
            manifest_path_str=manifest_path_str,
            require_claim_evidence_map=require_claim_evidence_map,
            checks=[
                _surface_check(
                    "manifest_present", "blocked", "manifest 'artifacts' is not a list"
                )
            ],
        )

    checks: List[Check] = [
        _surface_check("manifest_present", "pass", "bundle manifest loaded")
    ]
    by_role = _by_role(artifacts)
    claim_present = _CLAIM_MAP_ROLE in by_role
    absence_reason = claim_absence_reason_from_manifest(manifest)

    # ── claim-evidence-map surface (headline) ────────────────────────────────
    checks.append(
        _claim_surface_check(
            claim_present=claim_present,
            absence_reason=absence_reason,
            require=require_claim_evidence_map,
        )
    )

    # ── agent reading pack consistency ───────────────────────────────────────
    pack_entry = by_role.get(_AGENT_PACK_ROLE)
    pack_text = _read_pack_text(mp.parent, pack_entry)
    checks.append(
        _pack_consistency_surface_check(
            pack_present_in_manifest=pack_entry is not None,
            pack_text=pack_text,
            claim_present=claim_present,
            absence_reason=absence_reason,
        )
    )
    checks.append(
        _pack_front_door_v1_1_surface_check(
            pack_present_in_manifest=pack_entry is not None,
            pack_text=pack_text,
        )
    )


    # ── card artifact surfaces (optional, strict when present) ───────────────
    checks.extend(_card_surface_checks(by_role=by_role, manifest_dir=mp.parent))
    checks.append(
        _card_agent_pack_index_check(
            by_role=by_role,
            pack_present_in_manifest=pack_entry is not None,
            pack_text=pack_text,
        )
    )

    # ── post-emit health: persistence AND propagated status ──────────────────
    checks.extend(
        _post_emit_health_checks(manifest_path=mp, require=require_claim_evidence_map)
    )

    # ── surface link coherence (recorded links must resolve) ─────────────────
    checks.append(_links_coherence_surface_check(manifest, mp.parent))

    # ── output_health is not a forensic-ready signal (made explicit) ─────────
    if _OUTPUT_HEALTH_ROLE in by_role:
        checks.append(
            _surface_check(
                "output_health_not_forensic_ready",
                "pass",
                "output_health is a pre-emit signal; it does not inspect the "
                "claim-map/post-emit surface and never implies forensic-readiness",
                reason="check_not_applicable",
            )
        )

    # ── generator provenance (runtime drift diagnosability) ──────────────────
    checks.append(_generator_provenance_surface_check(manifest.get("generator")))

    return _assemble(
        status=_rollup(checks),
        run_id=run_id,
        bundle_run_id=bundle_run_id,
        manifest_path_str=manifest_path_str,
        require_claim_evidence_map=require_claim_evidence_map,
        checks=checks,
    )


def write_bundle_surface_validation(
    manifest_path: Union[str, Path],
    output_path: Optional[Union[str, Path]] = None,
    *,
    require_claim_evidence_map: bool = False,
    run_id: Optional[str] = None,
) -> Tuple[Path, Dict[str, Any]]:
    """Compute and persist the surface validation as ``<stem>.bundle_surface_validation.json``.

    The sidecar is intentionally **not** registered as a manifest artifact: a
    self-check must never verify its own hash. Returns ``(written_path, report)``.
    """
    report = validate_bundle_surface(
        manifest_path,
        require_claim_evidence_map=require_claim_evidence_map,
        run_id=run_id,
    )
    mp = Path(manifest_path)
    if not mp.is_absolute():
        mp = Path.cwd() / mp
    mp = mp.resolve()
    if output_path is not None:
        out = Path(output_path)
        out = out if out.is_absolute() else Path.cwd() / out
    else:
        out = derive_surface_validation_path(mp)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return out, report


_MANIFEST_SUFFIX = ".bundle.manifest.json"
_SURFACE_SUFFIX = ".bundle_surface_validation.json"


def derive_surface_validation_path(manifest_path: Path) -> Path:
    """Derive ``<stem>.bundle_surface_validation.json`` adjacent to the manifest."""
    name = manifest_path.name
    if name.endswith(_MANIFEST_SUFFIX):
        stem = name[: -len(_MANIFEST_SUFFIX)]
    else:
        stem = manifest_path.stem
    return manifest_path.parent / (stem + _SURFACE_SUFFIX)
