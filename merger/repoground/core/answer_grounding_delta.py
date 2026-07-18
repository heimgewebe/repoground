from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from merger.repoground.core.answer_grounding import NON_CLAIMS
from merger.repoground.core.range_resolver import resolve_range_ref
from merger.repoground.core.bundle_access import snapshot_status

KIND = "repobrief.answer_grounding_delta_verdict"
VERSION = "1.0"
STATUSES = ("valid", "drifted", "missing", "not_comparable")


def _read_citation_map(path: str | Path | None) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    if path is None:
        return {}, [{"code": "citation_map_missing", "severity": "warn", "detail": "No new citation map supplied."}]
    p = Path(path).expanduser().resolve()
    try:
        lines = p.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return {}, [{"code": "citation_map_missing", "severity": "warn", "detail": f"Citation map missing: {p}"}]
    entries: dict[str, dict[str, Any]] = {}
    diagnostics: list[dict[str, Any]] = []
    for lineno, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            diagnostics.append({"code": "citation_map_invalid", "severity": "warn", "detail": f"Invalid JSONL line {lineno}."})
            continue
        if isinstance(data, dict) and isinstance(data.get("citation_id"), str):
            entries[data["citation_id"]] = data
    return entries, diagnostics


def _range_ref_from_citation(entry: Mapping[str, Any]) -> dict[str, Any] | None:
    range_ref = entry.get("range_ref")
    if isinstance(range_ref, dict):
        return dict(range_ref)
    canonical_range = entry.get("canonical_range")
    if isinstance(canonical_range, Mapping):
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
    return None


def _check_range(manifest: Path, range_ref: dict[str, Any]) -> tuple[str, str]:
    try:
        resolve_range_ref(manifest, range_ref)
    except Exception as exc:
        detail = str(exc)
        if "hash mismatch" in detail.lower():
            return "drifted", detail
        return "not_comparable", detail
    return "valid", "Citation range resolved against the newer snapshot."


def _freshness_from_snapshot_ref(snapshot_ref: Mapping[str, Any] | None) -> str:
    if not isinstance(snapshot_ref, Mapping):
        return "unknown"
    value = snapshot_ref.get("freshness_status")
    return str(value) if isinstance(value, str) and value else "unknown"


def check_answer_grounding_delta(
    old_declaration: Mapping[str, Any],
    *,
    new_bundle_manifest: str | Path,
    new_citation_map: str | Path | None = None,
) -> dict[str, Any]:
    """Check old declared citations/ranges against a newer snapshot.

    Read-only: this function reads explicitly supplied existing files only. It does not
    create snapshots, fetch Git state, refresh bundles, or normalize freshness statuses.
    """
    manifest_path = Path(new_bundle_manifest).expanduser().resolve()
    entries, diagnostics = _read_citation_map(new_citation_map)
    citation_checks: list[dict[str, Any]] = []
    range_checks: list[dict[str, Any]] = []

    for item in old_declaration.get("used_citations") or []:
        if not isinstance(item, Mapping):
            continue
        citation_id = item.get("citation_id")
        if not isinstance(citation_id, str) or not citation_id:
            continue
        entry = entries.get(citation_id)
        if entry is None:
            citation_checks.append({
                "citation_id": citation_id,
                "status": "missing",
                "detail": "Citation ID was not present in the newer citation map.",
            })
            continue
        range_ref = _range_ref_from_citation(entry)
        if range_ref is None:
            citation_checks.append({
                "citation_id": citation_id,
                "status": "not_comparable",
                "detail": "New citation entry has no comparable range reference.",
            })
            continue
        status, detail = _check_range(manifest_path, range_ref)
        citation_checks.append({"citation_id": citation_id, "status": status, "detail": detail})

    for idx, item in enumerate(old_declaration.get("used_ranges") or [], start=1):
        if not isinstance(item, Mapping) or not isinstance(item.get("range_ref"), dict):
            range_checks.append({
                "range_id": f"declared-range-{idx}",
                "status": "not_comparable",
                "detail": "Old declaration range is missing range_ref.",
            })
            continue
        status, detail = _check_range(manifest_path, dict(item["range_ref"]))
        range_checks.append({
            "range_id": str(item.get("claim_ref") or f"declared-range-{idx}"),
            "status": status,
            "detail": detail,
        })

    all_statuses = [item["status"] for item in citation_checks + range_checks]
    if "drifted" in all_statuses:
        status = "drifted"
    elif "missing" in all_statuses:
        status = "missing"
    elif "not_comparable" in all_statuses or not all_statuses:
        status = "not_comparable"
    else:
        status = "valid"

    new_status = snapshot_status(manifest_path)
    new_freshness = new_status.get("freshness") if isinstance(new_status, dict) else None
    return {
        "kind": KIND,
        "version": VERSION,
        "status": status,
        "valid_statuses": list(STATUSES),
        "old_snapshot_freshness_status": _freshness_from_snapshot_ref(old_declaration.get("snapshot_ref")),
        "new_snapshot_freshness_status": (
            new_freshness.get("status") if isinstance(new_freshness, dict) else "unknown"
        ),
        "citation_checks": citation_checks,
        "range_checks": range_checks,
        "diagnostics": diagnostics,
        "mutation_boundary": {
            "writes": [],
            "reads_existing_files_only": True,
            "does_not_create_snapshots": True,
            "does_not_fetch_git": True,
            "does_not_refresh_bundles": True,
        },
        "does_not_establish": list(NON_CLAIMS) + [
            "semantic_answer_correctness",
            "new_snapshot_is_fresh",
            "citation_stability_across_all_commits",
        ],
    }
