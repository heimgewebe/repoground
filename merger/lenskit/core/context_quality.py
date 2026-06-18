"""
Context Quality Signals projector for Lenskit bundles (roadmap PR B1).

Computes a machine-readable diagnostic PROJECTION of signals that already exist
in and around a bundle (manifest role availability, output_health checks,
post_emit_health status / achieved evidence level, retrieval-eval metrics, and an
optional agent export-gate result) and writes it as
``<stem>.context_quality.json``.

Design contract (deliberately small and additive):
- This artifact is a projection, never a new truth layer. It is not a truth
  source, not an understanding verdict, not a retrieval-completeness proof, not
  an answer-safety gate, not a global score, and not a claim judgment.
- ``authority`` is always ``diagnostic_signal`` and ``risk_class`` is always
  ``diagnostic``.
- The headline field is ``projection_status`` (``complete | degraded | blocked``),
  which describes PROJECTION completeness only -- never context quality, never
  repository understanding, never answer safety. There is intentionally no global
  ``status`` verdict.
- ``compute_context_quality`` performs no writes. ``write_context_quality``
  writes ``<stem>.context_quality.json`` next to the manifest unless an explicit
  output path is given, and never mutates or registers anything in the manifest.
- Missing optional inputs produce unavailable/degraded signal entries, never a
  crash. Invalid optional JSON produces a warning, never a fabricated value.
- Signals are projected as observations only. output_health verdicts are never
  used to infer post-emit validity; post_emit_health is never used to infer
  answer safety; retrieval metrics are never treated as completeness; the export
  gate is never reinterpreted as claim truth. The retrieval-eval miss_taxonomy is
  surfaced verbatim as an existing diagnostic classification, never as proof of
  repository absence, semantic (ir)relevance, retrieval completeness, or claim
  truth.
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .clock import now_utc
from .path_security import resolve_secure_path
from .post_emit_health import derive_post_health_path

logger = logging.getLogger(__name__)

KIND = "lenskit.context_quality"
VERSION = "1.0"

_BUNDLE_KIND = "repolens.bundle.manifest"
_MANIFEST_SUFFIX = ".bundle.manifest.json"
_CONTEXT_QUALITY_SUFFIX = ".context_quality.json"

AUTHORITY = "diagnostic_signal"
RISK_CLASS = "diagnostic"

# What this projection deliberately does NOT establish (never claim verdicts).
DOES_NOT_MEAN = (
    "repo_understood",
    "retrieval_complete",
    "answer_safe_without_citations",
    "claims_true",
)

# How an agent must treat this projection (usage constraints, not verdicts).
AGENT_USE_CONSTRAINTS = (
    "verify_content_against_canonical_md",
    "cite_canonical_ranges_for_claims",
    "do_not_treat_context_quality_as_repo_understanding",
    "do_not_treat_retrieval_metrics_as_completeness_proof",
    "do_not_treat_export_gate_as_claim_truth",
)

# Manifest roles whose presence we surface as a key-role availability map.
_KEY_ROLES = (
    "canonical_md",
    "agent_reading_pack",
    "chunk_index_jsonl",
    "citation_map_jsonl",
    "output_health",
    "retrieval_eval_json",
    "sqlite_index",
)

# Evidence-level vocabulary from docs/architecture/artifact-evidence-levels.md.
# Values outside this set received from optional inputs are filtered to null/dropped.
_KNOWN_EVIDENCE_LEVELS = frozenset({
    "readable",
    "navigable",
    "citable",
    "range_strict",
    "searchable",
    "diagnostic_full",
    "forensic_strict",
})

# Cap on how many miss cases we surface in the projection. The full taxonomy
# lives in retrieval_eval_json; the context-quality projection only carries a
# small navigational sample so it stays compact.
_MISS_TAXONOMY_CASE_SAMPLE_LIMIT = 5


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
        return None, str(e)
    if not isinstance(data, dict):
        return None, "JSON root must be an object"
    return data, None


def _num_or_none(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    return value if isinstance(value, (int, float)) else None


def _int_or_none(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    return value if isinstance(value, int) else None


def _str_or_none(value: Any) -> Optional[str]:
    return value if isinstance(value, str) else None


def _bool_or_none(value: Any) -> Optional[bool]:
    return value if isinstance(value, bool) else None


def _string_list(value: Any) -> List[str]:
    """Return only the string items of a JSON list; [] for any non-list value.

    Defensive against untrusted/older JSON: a truthy non-list scalar (e.g. ``True``,
    ``404``, ``"broken"``) or a dict must never raise or iterate unexpectedly.
    """
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def derive_context_quality_path(manifest_path: Path) -> Path:
    """Derive ``<stem>.context_quality.json`` adjacent to the manifest."""
    name = manifest_path.name
    if name.endswith(_MANIFEST_SUFFIX):
        stem = name[: -len(_MANIFEST_SUFFIX)]
    else:
        stem = manifest_path.stem
    return manifest_path.parent / (stem + _CONTEXT_QUALITY_SUFFIX)


def _resolve_signal_path(
    explicit_path: Optional[str],
    by_role: Optional[Dict[str, Dict[str, Any]]],
    role: str,
    manifest_dir: Path,
) -> Tuple[Optional[Path], Optional[str], Optional[str]]:
    """
    Resolve where a signal artifact lives.

    Returns ``(path, source, note)``. ``source`` is ``explicit_path`` or
    ``manifest_role`` when a candidate was found, else ``None``. ``note`` carries
    a non-fatal explanation (e.g. a rejected manifest path) for the caller to warn
    about. Manifest-declared paths are resolved securely relative to the manifest
    directory.
    """
    if explicit_path:
        return _resolve_path(explicit_path), "explicit_path", None
    if by_role is not None:
        entry = by_role.get(role)
        if isinstance(entry, dict) and isinstance(entry.get("path"), str) and entry["path"]:
            try:
                return resolve_secure_path(manifest_dir, entry["path"]), "manifest_role", None
            except ValueError as e:
                return None, "manifest_role", f"path rejected: {e}"
    return None, None, None


# ---------------------------------------------------------------------------
# Per-signal projectors
# ---------------------------------------------------------------------------

def _project_output_health(
    explicit_path: Optional[str],
    by_role: Dict[str, Dict[str, Any]],
    manifest_dir: Path,
    warnings: List[str],
) -> Dict[str, Any]:
    path, source, note = _resolve_signal_path(explicit_path, by_role, "output_health", manifest_dir)
    if path is None:
        if note:
            warnings.append(f"output_health unavailable: {note}")
            return {"available": False, "source": source, "reason": note}
        return {
            "available": False,
            "source": None,
            "reason": "not declared in manifest and no explicit path given",
        }

    doc, err = _load_json(path)
    if doc is None:
        warnings.append(f"output_health unavailable: {err}")
        return {"available": False, "source": source, "reason": err}

    checks = doc.get("checks") if isinstance(doc.get("checks"), dict) else {}
    return {
        "available": True,
        "source": source,
        "verdict_observed": _str_or_none(doc.get("verdict")),
        "checks": {
            "canonical_md_hash_ok": _bool_or_none(checks.get("canonical_md_hash_ok")),
            "chunk_index_hash_ok": _bool_or_none(checks.get("chunk_index_hash_ok")),
            "sqlite_row_count_matches_chunk_count": _bool_or_none(
                checks.get("sqlite_row_count_matches_chunk_count")
            ),
            "fts_content_non_empty": _bool_or_none(checks.get("fts_content_non_empty")),
            "range_ref_resolution_status": _str_or_none(checks.get("range_ref_resolution_status")),
            "redaction_status_explicit": _bool_or_none(checks.get("redaction_status_explicit")),
            "redact_secrets_enabled": _bool_or_none(checks.get("redact_secrets_enabled")),
        },
    }


def _project_post_emit_health(
    explicit_path: Optional[str],
    resolved_manifest: Path,
    warnings: List[str],
) -> Dict[str, Any]:
    # post_emit_health is not a manifest-declared role; it lives as the sidecar
    # <stem>.bundle_health.post.json next to the manifest (or at an explicit path).
    if explicit_path:
        path: Optional[Path] = _resolve_path(explicit_path)
        source = "explicit_path"
    else:
        path = derive_post_health_path(resolved_manifest)
        source = "derived_sidecar"

    if path is None or not path.exists():
        if source == "explicit_path":
            warnings.append("post_emit_health unavailable: file not found")
            return {"available": False, "source": source, "reason": "file not found"}
        return {
            "available": False,
            "source": None,
            "reason": "no post_emit_health sidecar present",
        }

    doc, err = _load_json(path)
    if doc is None:
        warnings.append(f"post_emit_health unavailable: {err}")
        return {"available": False, "source": source, "reason": err}

    return {
        "available": True,
        "source": source,
        "status_observed": _str_or_none(doc.get("status")),
        "evidence_level": _str_or_none(doc.get("evidence_level")),
        "evidence_levels_reached": _string_list(doc.get("evidence_levels_reached")),
        "does_not_mean": _string_list(doc.get("does_not_mean")),
    }


def _project_miss_taxonomy(raw: Any) -> Dict[str, Any]:
    """
    Mechanically project the existing retrieval-eval ``miss_taxonomy`` diagnostic.

    The already-computed aggregate counts and the ``does_not_prove`` boundary are
    copied verbatim, plus a small capped navigational sample of cases. This invents
    no new aggregation, no score, and no verdict. When the retrieval-eval document
    predates or omits ``miss_taxonomy`` the projection is marked unavailable WITHOUT
    a warning, so older eval files never degrade or fail the projection.

    Defensive against untrusted/older JSON: list-typed fields (``does_not_prove``,
    ``cases``, ``case.miss_types``) are read only when they are actually lists, so a
    truthy non-list value never raises. Cases are validated as dicts BEFORE the
    sample limit is applied, so leading malformed entries cannot starve later valid
    cases out of the sample.
    """
    if raw is None:
        return {"available": False, "reason": "missing_from_retrieval_eval"}
    if not isinstance(raw, dict):
        return {"available": False, "reason": "invalid_miss_taxonomy_shape"}

    aggregate = raw.get("aggregate")
    aggregate = aggregate if isinstance(aggregate, dict) else None

    raw_cases = raw.get("cases")
    cases = raw_cases if isinstance(raw_cases, list) else []
    cases_sample: List[Dict[str, Any]] = []
    for case in cases:
        if not isinstance(case, dict):
            continue
        if len(cases_sample) >= _MISS_TAXONOMY_CASE_SAMPLE_LIMIT:
            break
        cases_sample.append({
            "query_index": _int_or_none(case.get("query_index")),
            "query": _str_or_none(case.get("query")),
            "primary_miss_type": _str_or_none(case.get("primary_miss_type")),
            "miss_types": _string_list(case.get("miss_types")),
        })

    return {
        "available": True,
        "aggregate": aggregate,
        "cases_sample": cases_sample,
        "does_not_prove": _string_list(raw.get("does_not_prove")),
    }


def _project_retrieval_eval(
    explicit_path: Optional[str],
    by_role: Dict[str, Dict[str, Any]],
    manifest_dir: Path,
    warnings: List[str],
) -> Dict[str, Any]:
    path, source, note = _resolve_signal_path(
        explicit_path, by_role, "retrieval_eval_json", manifest_dir
    )
    if path is None:
        if note:
            warnings.append(f"retrieval_eval unavailable: {note}")
            return {"available": False, "source": source, "reason": note}
        return {
            "available": False,
            "source": None,
            "reason": "not declared in manifest and no explicit path given",
        }

    doc, err = _load_json(path)
    if doc is None:
        warnings.append(f"retrieval_eval unavailable: {err}")
        return {"available": False, "source": source, "reason": err}

    metrics = doc.get("metrics") if isinstance(doc.get("metrics"), dict) else {}
    projected_metrics = {
        "recall@10": _num_or_none(metrics.get("recall@10")),
        "MRR": _num_or_none(metrics.get("MRR")),
        "total_queries": _int_or_none(metrics.get("total_queries")),
        "hits": _int_or_none(metrics.get("hits")),
        "zero_hit_ratio": _num_or_none(metrics.get("zero_hit_ratio")),
        "stale_flag": _bool_or_none(metrics.get("stale_flag")),
    }

    categories: Optional[List[Dict[str, Any]]] = None
    raw_categories = metrics.get("categories")
    if isinstance(raw_categories, dict):
        categories = []
        for name, cat in raw_categories.items():
            if not isinstance(cat, dict):
                continue
            categories.append(
                {
                    "category": str(name),
                    "total_queries": _int_or_none(cat.get("total_queries")),
                    "hits": _int_or_none(cat.get("hits")),
                    "MRR": _num_or_none(cat.get("MRR")),
                    "recall@10": _num_or_none(cat.get("recall@10")),
                }
            )

    return {
        "available": True,
        "source": source,
        "metrics": projected_metrics,
        "categories": categories,
        "miss_taxonomy": _project_miss_taxonomy(doc.get("miss_taxonomy")),
    }


def _project_agent_export_gate(
    explicit_path: Optional[str],
    warnings: List[str],
) -> Dict[str, Any]:
    # The export gate is computed on demand and is neither a manifest role nor a
    # standard sidecar, so it is only projected when an explicit path is provided.
    if not explicit_path:
        return {
            "available": False,
            "source": None,
            "reason": "no agent_export_gate path given",
        }

    path = _resolve_path(explicit_path)
    doc, err = _load_json(path)
    if doc is None:
        warnings.append(f"agent_export_gate unavailable: {err}")
        return {"available": False, "source": "explicit_path", "reason": err}

    return {
        "available": True,
        "source": "explicit_path",
        "status_observed": _str_or_none(doc.get("status")),
        "profile_observed": _str_or_none(doc.get("profile")),
        "agent_facing_observed": _bool_or_none(doc.get("agent_facing")),
    }


def _project_evidence(post_emit_signal: Dict[str, Any], warnings: List[str]) -> Dict[str, Any]:
    # Evidence reuses the existing evidence-level vocabulary surfaced by
    # post_emit_health. It never invents new levels and never aggregates a score.
    # Unknown values from an optional (possibly corrupted) sidecar are filtered
    # to null/dropped with a warning to keep this report schema-valid.
    if post_emit_signal.get("available"):
        raw_level = post_emit_signal.get("evidence_level")
        if raw_level is not None and raw_level not in _KNOWN_EVIDENCE_LEVELS:
            warnings.append(
                f"post_emit_health evidence_level {raw_level!r} is not in known vocabulary; set to null"
            )
            raw_level = None

        raw_reached = _string_list(post_emit_signal.get("evidence_levels_reached"))
        known_reached = [lvl for lvl in raw_reached if lvl in _KNOWN_EVIDENCE_LEVELS]
        dropped = [lvl for lvl in raw_reached if lvl not in _KNOWN_EVIDENCE_LEVELS]
        if dropped:
            warnings.append(
                f"post_emit_health evidence_levels_reached contained unknown values (dropped): {dropped!r}"
            )

        return {
            "available": True,
            "source": "post_emit_health",
            "evidence_level": raw_level,
            "evidence_levels_reached": known_reached,
        }
    return {
        "available": False,
        "source": None,
        "evidence_level": None,
        "evidence_levels_reached": [],
    }


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------

def _blocked_signals() -> Dict[str, Any]:
    return {
        "manifest": {
            "available": False,
            "kind": None,
            "version": None,
            "run_id": None,
            "roles_present": [],
            "key_roles": {role: False for role in _KEY_ROLES},
        },
        "output_health": {"available": False, "source": None, "reason": "manifest blocked"},
        "post_emit_health": {"available": False, "source": None, "reason": "manifest blocked"},
        "retrieval_eval": {"available": False, "source": None, "reason": "manifest blocked"},
        "agent_export_gate": {"available": False, "source": None, "reason": "manifest blocked"},
        "evidence": {
            "available": False,
            "source": None,
            "evidence_level": None,
            "evidence_levels_reached": [],
        },
    }


def _assemble(
    *,
    projection_status: str,
    run_id: str,
    bundle_run_id: Any,
    manifest_path_str: str,
    signals: Dict[str, Any],
    warnings: List[str],
    errors: List[str],
) -> Dict[str, Any]:
    return {
        "kind": KIND,
        "version": VERSION,
        "run_id": run_id,
        "checked_at": _now_iso(),
        "bundle_manifest_path": manifest_path_str,
        "bundle_run_id": bundle_run_id if isinstance(bundle_run_id, str) else None,
        "projection_status": projection_status,
        "authority": AUTHORITY,
        "risk_class": RISK_CLASS,
        "signals": signals,
        "agent_use_constraints": list(AGENT_USE_CONSTRAINTS),
        "does_not_mean": list(DOES_NOT_MEAN),
        "warnings": warnings,
        "errors": errors,
    }


def _blocked_report(
    run_id: str,
    resolved_manifest: Path,
    error_msg: str,
    bundle_run_id: Any,
) -> Dict[str, Any]:
    return _assemble(
        projection_status="blocked",
        run_id=run_id,
        bundle_run_id=bundle_run_id,
        manifest_path_str=str(resolved_manifest),
        signals=_blocked_signals(),
        warnings=[],
        errors=[error_msg],
    )


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

def compute_context_quality(
    manifest_path: str,
    *,
    output_health_path: Optional[str] = None,
    post_emit_health_path: Optional[str] = None,
    retrieval_eval_path: Optional[str] = None,
    agent_export_gate_path: Optional[str] = None,
    run_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Project the available context-quality signals for a bundle. Pure: no writes.

    Returns a dict conforming to ``context-quality.v1.schema.json``. When the
    manifest cannot be read or is not a ``repolens.bundle.manifest``, returns a
    schema-valid report with ``projection_status == "blocked"``.
    """
    run_id = run_id or str(uuid.uuid4())
    resolved_manifest = _resolve_path(manifest_path)

    manifest, load_err = _load_json(resolved_manifest)
    if manifest is None:
        return _blocked_report(
            run_id, resolved_manifest, f"cannot read bundle manifest: {load_err}", bundle_run_id=None
        )

    bundle_run_id = manifest.get("run_id")
    if manifest.get("kind") != _BUNDLE_KIND:
        return _blocked_report(
            run_id,
            resolved_manifest,
            "manifest is not a repolens.bundle.manifest; cannot project context quality",
            bundle_run_id=bundle_run_id,
        )

    manifest_dir = resolved_manifest.parent
    warnings: List[str] = []
    errors: List[str] = []

    # ── manifest signal: role availability projection ────────────────────────
    by_role: Dict[str, Dict[str, Any]] = {}
    roles_present: List[str] = []
    artifacts = manifest.get("artifacts")
    if isinstance(artifacts, list):
        for art in artifacts:
            if isinstance(art, dict) and isinstance(art.get("role"), str):
                by_role.setdefault(art["role"], art)
                roles_present.append(art["role"])
    else:
        warnings.append("manifest 'artifacts' is not a list; role availability unknown")

    key_roles = {role: (role in by_role) for role in _KEY_ROLES}
    if not key_roles["canonical_md"]:
        warnings.append("canonical_md role not declared in manifest")

    manifest_signal = {
        "available": True,
        "kind": _str_or_none(manifest.get("kind")),
        "version": _str_or_none(manifest.get("version")),
        "run_id": _str_or_none(bundle_run_id),
        "roles_present": sorted(set(roles_present)),
        "key_roles": key_roles,
    }

    # ── projected diagnostic signals (observations only) ─────────────────────
    output_health_signal = _project_output_health(
        output_health_path, by_role, manifest_dir, warnings
    )
    post_emit_signal = _project_post_emit_health(
        post_emit_health_path, resolved_manifest, warnings
    )
    retrieval_signal = _project_retrieval_eval(
        retrieval_eval_path, by_role, manifest_dir, warnings
    )
    export_gate_signal = _project_agent_export_gate(agent_export_gate_path, warnings)
    evidence_signal = _project_evidence(post_emit_signal, warnings)

    signals = {
        "manifest": manifest_signal,
        "output_health": output_health_signal,
        "post_emit_health": post_emit_signal,
        "retrieval_eval": retrieval_signal,
        "agent_export_gate": export_gate_signal,
        "evidence": evidence_signal,
    }

    # ── projection_status: completeness of the projection, nothing more ──────
    all_available = all(
        signals[name].get("available") is True
        for name in (
            "manifest",
            "output_health",
            "post_emit_health",
            "retrieval_eval",
            "agent_export_gate",
        )
    )
    if all_available and not warnings and not errors:
        projection_status = "complete"
    else:
        projection_status = "degraded"

    return _assemble(
        projection_status=projection_status,
        run_id=run_id,
        bundle_run_id=bundle_run_id,
        manifest_path_str=str(resolved_manifest),
        signals=signals,
        warnings=warnings,
        errors=errors,
    )


def write_context_quality(
    manifest_path: str,
    output_path: Optional[str] = None,
    **kwargs: Any,
) -> Tuple[Path, Dict[str, Any]]:
    """
    Compute the context-quality projection and persist it as
    ``<stem>.context_quality.json`` (or ``output_path`` if given).

    The written artifact is intentionally NOT registered in the bundle manifest,
    and the manifest is never mutated. Returns ``(written_path, report)``.
    """
    report = compute_context_quality(manifest_path, **kwargs)
    resolved_manifest = _resolve_path(manifest_path)
    if output_path:
        out = Path(output_path)
        out = out if out.is_absolute() else Path.cwd() / out
    else:
        out = derive_context_quality_path(resolved_manifest)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    logger.debug(
        "context_quality written to %s (projection_status=%s)",
        out,
        report["projection_status"],
    )
    return out, report
