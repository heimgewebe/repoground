"""Small, navigable evidence projection for resolved RepoGround queries.

This is deliberately a read-only view over ``query_existing_index`` output.  A
live source line is emitted only when the citation producer supplied a live
repository address.  All other hits carry a deterministic non-resolution
reason instead of a plausible-looking path or line number.
"""
from __future__ import annotations

import json
from typing import Any


KIND = "repoground.compact_evidence_query"
VERSION = "v1"
REQUIRED_BYTE_REDUCTION_PERCENT = 60.0


def _line(address: dict[str, Any]) -> str | None:
    path = address.get("path")
    start = address.get("start_line")
    end = address.get("end_line")
    if not isinstance(path, str) or not path or not isinstance(start, int) or not isinstance(end, int):
        return None
    if start < 1 or end < start:
        return None
    return f"{path}:{start}" if start == end else f"{path}:{start}-{end}"


def _reason(hit: dict[str, Any]) -> str:
    address = hit.get("live_repo_address")
    if isinstance(address, dict):
        raw = address.get("reason")
        if isinstance(raw, str) and raw:
            return f"live_address_{raw}"
        raw = address.get("status")
        if isinstance(raw, str) and raw:
            return f"live_address_status_{raw}"
    raw = hit.get("range_error_code")
    if isinstance(raw, str) and raw:
        return f"range_{raw}"
    if hit.get("range_status") != "resolved":
        return "range_not_resolved"
    if hit.get("citation_status") != "resolved":
        return "citation_not_resolved"
    return "live_address_not_emitted"


def project_compact_evidence(result: dict[str, Any]) -> dict[str, Any]:
    """Return a deterministic, at-least-60%-smaller navigation projection.

    The complete result remains available from the normal query surface.  This
    profile intentionally omits excerpts and ranking diagnostics; it is a
    navigation aid, not a replacement for canonical content.  It retains the
    evidence identifiers, freshness and fallback state needed to avoid making
    an unresolved or stale result look more useful than it is.
    """
    resolved = result.get("resolved_evidence") if isinstance(result, dict) else None
    raw_hits = resolved.get("hits") if isinstance(resolved, dict) else []
    hits = []
    for ordinal, raw in enumerate(raw_hits if isinstance(raw_hits, list) else [], start=1):
        if not isinstance(raw, dict):
            continue
        address = raw.get("live_repo_address")
        live_line = _line(address) if isinstance(address, dict) and address.get("status") == "available" else None
        item: dict[str, Any] = {
            "rank": ordinal,
            "live_path_line": live_line,
            "range_status": raw.get("range_status"),
            "citation_status": raw.get("citation_status"),
            "freshness": raw.get("freshness"),
        }
        citation_id = raw.get("citation_id")
        if isinstance(citation_id, str):
            item["citation_id"] = citation_id
        if live_line is None:
            item["non_resolution_reason"] = _reason(raw)
        hits.append(item)

    full_bytes = len(json.dumps(result, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    output = {
        "kind": KIND,
        "version": VERSION,
        "query": result.get("query") if isinstance(result, dict) else None,
        "status": result.get("status") if isinstance(result, dict) else "invalid",
        "freshness": result.get("freshness") if isinstance(result, dict) else None,
        "fallback": {
            "query_mode": (
                result.get("query_result", {}).get("query_mode")
                if isinstance(result, dict) and isinstance(result.get("query_result"), dict)
                else None
            ),
            "warnings": (
                result.get("query_result", {}).get("warnings", [])
                if isinstance(result, dict) and isinstance(result.get("query_result"), dict)
                else []
            ),
        },
        "hits": hits,
        "does_not_establish": [
            "live_repository_state_when_no_live_path_line_is_present",
            "claim_truth",
            "retrieval_completeness",
        ],
    }
    compact_bytes = len(json.dumps(output, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    output["byte_reduction_percent"] = round(
        max(0.0, (1.0 - (compact_bytes / max(full_bytes, 1))) * 100.0), 2
    )
    output["compaction_requirement_percent"] = REQUIRED_BYTE_REDUCTION_PERCENT
    output["compaction_pass"] = (
        output["byte_reduction_percent"] >= REQUIRED_BYTE_REDUCTION_PERCENT
    )
    return output
