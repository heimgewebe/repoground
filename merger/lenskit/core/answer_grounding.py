from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from merger.lenskit.core.range_resolver import resolve_range_ref

KIND = "repobrief.answer_grounding_verdict"
VERSION = "1.0"
NON_CLAIMS = [
    "actual_reading_proven",
    "answer_correct",
    "repo_understood",
    "all_relevant_context_used",
    "claims_true",
    "test_sufficiency",
    "regression_absence",
    "runtime_behavior",
    "forensic_ready",
    "merge_readiness",
    "security_correctness",
]


def _sha256_json(data: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _snapshot_ref(declaration: Mapping[str, Any], manifest_path: Path) -> dict[str, Any]:
    raw = declaration.get("snapshot_ref")
    if isinstance(raw, Mapping):
        result = dict(raw)
    else:
        result = {"stem": manifest_path.stem, "manifest_path": str(manifest_path)}
    result.setdefault("stem", manifest_path.stem)
    result.setdefault("manifest_path", str(manifest_path))
    return result


def _declaration_ref(declaration: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "answer_id": str(declaration.get("answer_id") or "unknown-answer"),
        "question_hash": str(declaration.get("question_hash") or "0" * 64),
        "answer_hash": str(declaration.get("answer_hash") or "0" * 64),
        "declaration_sha256": _sha256_json(declaration),
    }


def _diagnostic(code: str, severity: str, detail: str, ref: str | None = None) -> dict[str, Any]:
    item = {"code": code, "severity": severity, "detail": detail}
    if ref:
        item["ref"] = ref
    return item


def _evidence_check(
    ref: str,
    status: str,
    severity: str,
    detail: str,
    *,
    artifact_role: str | None = None,
    authority: str = "canonical_snapshot",
) -> dict[str, Any]:
    item = {
        "ref": ref,
        "status": status,
        "severity": severity,
        "authority": authority,
        "detail": detail,
    }
    if artifact_role:
        item["artifact_role"] = artifact_role
    return item


def _required_reading_check(
    artifact_role: str,
    status: str,
    severity: str,
    detail: str,
) -> dict[str, Any]:
    return {
        "artifact_role": artifact_role,
        "status": status,
        "severity": severity,
        "detail": detail,
    }


def _load_citation_map(path: Path | None) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    if path is None:
        return {}, []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return {}, [_diagnostic("missing_required_artifact", "fail", f"Citation map does not exist: {path}")]
    except OSError as exc:
        return {}, [_diagnostic("degraded_dependency", "warn", f"Citation map could not be read: {exc}")]

    entries: dict[str, dict[str, Any]] = {}
    diagnostics: list[dict[str, Any]] = []
    for lineno, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError as exc:
            diagnostics.append(
                _diagnostic(
                    "degraded_dependency",
                    "warn",
                    f"Citation map JSONL line {lineno} is invalid JSON: {exc.msg}",
                )
            )
            continue
        if not isinstance(data, dict):
            diagnostics.append(
                _diagnostic("degraded_dependency", "warn", f"Citation map line {lineno} is not an object")
            )
            continue
        citation_id = data.get("citation_id")
        if isinstance(citation_id, str) and citation_id:
            entries[citation_id] = data
    return entries, diagnostics


def _range_ref_from_citation(entry: Mapping[str, Any]) -> dict[str, Any] | None:
    existing = entry.get("range_ref")
    if isinstance(existing, dict):
        return dict(existing)
    canonical_range = entry.get("canonical_range")
    if not isinstance(canonical_range, Mapping):
        return None
    return {
        "artifact_role": "canonical_md",
        "repo_id": entry.get("repo_id") or "unknown-repo",
        "file_path": canonical_range.get("file_path"),
        "start_byte": canonical_range.get("start_byte"),
        "end_byte": canonical_range.get("end_byte"),
        "start_line": canonical_range.get("start_line"),
        "end_line": canonical_range.get("end_line"),
        "content_sha256": canonical_range.get("content_sha256"),
    }


def _resolve_range(manifest_path: Path, range_ref: Mapping[str, Any]) -> tuple[bool, str, str]:
    try:
        result = resolve_range_ref(manifest_path, dict(range_ref))
    except Exception as exc:  # range_resolver exposes several precise exceptions
        detail = str(exc)
        if "hash mismatch" in detail.lower():
            return False, "drifted", detail
        return False, "invalid", detail
    return True, "resolved", f"Range resolved ({result.get('bytes', 'unknown')} bytes)."


def verify_answer_grounding(
    declaration: Mapping[str, Any],
    *,
    bundle_manifest: str | Path,
    citation_map: str | Path | None = None,
    required_artifacts: Sequence[str] = (),
    recommended_artifacts: Sequence[str] = (),
) -> dict[str, Any]:
    """Verify declared answer grounding against existing RepoBrief artifacts.

    This is deliberately read-only: it only reads explicitly supplied files and delegates
    range extraction to the existing range resolver. It performs no Git, shell, refresh,
    snapshot creation, patch, PR, test or merge operation.
    """
    manifest_path = Path(bundle_manifest).expanduser().resolve()
    citation_map_path = Path(citation_map).expanduser().resolve() if citation_map is not None else None

    citation_checks: list[dict[str, Any]] = []
    range_checks: list[dict[str, Any]] = []
    required_checks: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    freshness_caveats = list(declaration.get("freshness_caveats") or [])
    availability_caveats: list[dict[str, Any]] = []

    if not manifest_path.exists():
        diagnostics.append(
            _diagnostic("missing_required_artifact", "fail", f"Bundle manifest does not exist: {manifest_path}")
        )

    citation_entries, citation_map_diagnostics = _load_citation_map(citation_map_path)
    diagnostics.extend(citation_map_diagnostics)

    used_citations = declaration.get("used_citations") or []
    if not isinstance(used_citations, list):
        used_citations = []
        diagnostics.append(_diagnostic("degraded_dependency", "warn", "used_citations is not an array"))

    for item in used_citations:
        citation_id = item.get("citation_id") if isinstance(item, Mapping) else None
        citation_ref = str(citation_id or "<missing-citation-id>")
        if not citation_id or citation_id not in citation_entries:
            citation_checks.append(
                _evidence_check(
                    citation_ref,
                    "missing",
                    "fail",
                    "Declared citation ID was not found in the supplied citation map.",
                    artifact_role="citation_map_jsonl",
                )
            )
            diagnostics.append(
                _diagnostic("citation_not_found", "fail", "Declared citation ID was not found.", citation_ref)
            )
            continue
        entry = citation_entries[citation_id]
        citation_checks.append(
            _evidence_check(
                citation_ref,
                "resolved",
                "info",
                "Declared citation ID exists in the supplied citation map.",
                artifact_role="citation_map_jsonl",
            )
        )
        citation_range_ref = _range_ref_from_citation(entry)
        if citation_range_ref:
            ok, status, detail = _resolve_range(manifest_path, citation_range_ref)
            severity = "info" if ok else "fail"
            citation_checks.append(
                _evidence_check(
                    f"{citation_ref}:canonical_range",
                    status,
                    severity,
                    detail,
                    artifact_role="canonical_md",
                )
            )
            if not ok:
                diagnostics.append(
                    _diagnostic(
                        "content_hash_mismatch" if status == "drifted" else "range_not_resolved",
                        "fail",
                        detail,
                        citation_ref,
                    )
                )

    used_ranges = declaration.get("used_ranges") or []
    if not isinstance(used_ranges, list):
        used_ranges = []
        diagnostics.append(_diagnostic("degraded_dependency", "warn", "used_ranges is not an array"))

    for idx, item in enumerate(used_ranges, start=1):
        if not isinstance(item, Mapping) or not isinstance(item.get("range_ref"), Mapping):
            ref = f"declared-range-{idx}"
            range_checks.append(_evidence_check(ref, "invalid", "fail", "Declared range is missing range_ref."))
            diagnostics.append(_diagnostic("range_not_resolved", "fail", "Declared range is missing range_ref.", ref))
            continue
        ref = item.get("claim_ref") or f"declared-range-{idx}"
        ok, status, detail = _resolve_range(manifest_path, item["range_ref"])
        severity = "info" if ok else "fail"
        range_checks.append(
            _evidence_check(
                str(ref),
                status,
                severity,
                detail,
                artifact_role=str(item.get("artifact_role") or item["range_ref"].get("artifact_role") or "canonical_md"),
            )
        )
        if not ok:
            diagnostics.append(
                _diagnostic(
                    "content_hash_mismatch" if status == "drifted" else "range_not_resolved",
                    "fail",
                    detail,
                    str(ref),
                )
            )

    declared_roles = set(declaration.get("declared_artifacts") or [])
    # Grounding declarations may not carry declared_artifacts yet; infer roles from evidence.
    declared_roles.update(
        str(r.get("artifact_role"))
        for r in used_ranges
        if isinstance(r, Mapping) and r.get("artifact_role")
    )
    if used_citations:
        declared_roles.add("citation_map_jsonl")

    for role in required_artifacts:
        if role in declared_roles:
            required_checks.append(_required_reading_check(role, "declared", "info", "Required artifact was declared."))
        else:
            required_checks.append(_required_reading_check(role, "missing_required", "fail", "Required artifact was not declared."))
            diagnostics.append(_diagnostic("missing_required_artifact", "fail", f"Required artifact was not declared: {role}", role))
    for role in recommended_artifacts:
        if role in declared_roles:
            required_checks.append(_required_reading_check(role, "declared", "info", "Recommended artifact was declared."))
        else:
            required_checks.append(_required_reading_check(role, "missing_recommended", "warn", "Recommended artifact was not declared."))
            diagnostics.append(_diagnostic("missing_recommended_artifact", "warn", f"Recommended artifact was not declared: {role}", role))

    declared_non_claims = set(declaration.get("does_not_establish") or [])
    missing_non_claims = [claim for claim in NON_CLAIMS if claim not in declared_non_claims]
    for claim in missing_non_claims:
        diagnostics.append(_diagnostic("missing_non_claim", "fail", f"Declaration is missing non-claim: {claim}", claim))

    if any(d.get("severity") == "fail" for d in diagnostics):
        status = "fail"
    elif any(d.get("code") == "degraded_dependency" for d in diagnostics):
        status = "degraded"
    elif any(d.get("severity") == "warn" for d in diagnostics):
        status = "warn"
    elif not used_citations and not used_ranges and not required_artifacts:
        status = "not_applicable"
        diagnostics.append(_diagnostic("not_applicable", "info", "No citations, ranges or required artifacts were declared for verification."))
    else:
        status = "pass"

    return {
        "kind": KIND,
        "version": VERSION,
        "status": status,
        "checked_declaration": _declaration_ref(declaration),
        "snapshot_ref": _snapshot_ref(declaration, manifest_path),
        "citation_checks": citation_checks,
        "range_checks": range_checks,
        "required_reading_checks": required_checks,
        "diagnostics": diagnostics,
        "freshness_caveats": freshness_caveats,
        "availability_caveats": availability_caveats,
        "does_not_establish": list(NON_CLAIMS),
    }
