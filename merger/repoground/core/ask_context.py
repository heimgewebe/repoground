from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from merger.repoground.core.bundle_access import (
    query_existing_index,
    resolve_required_reading_for_bundle,
    snapshot_status,
)

# Bilingual (EN/DE) function-word stoplist. These words carry no retrieval
# signal but, because the FTS router AND-joins every term, a single one that is
# absent from a chunk zeroes an otherwise good match. Removing them for the
# relaxed OR retry is safe: the set holds only unambiguous function words, never
# code identifiers or content terms.
_RETRIEVAL_STOPWORDS = frozenset({
    # English
    "how", "does", "do", "did", "is", "are", "was", "were", "be", "been",
    "the", "a", "an", "of", "to", "into", "in", "on", "for", "and", "or",
    "with", "what", "which", "where", "when", "why", "who", "that", "this",
    "these", "those", "its", "it", "as", "at", "by",
    # German
    "wie", "was", "welche", "welcher", "welches", "wo", "wann", "warum", "wer",
    "ist", "sind", "war", "den", "dem", "der", "die", "das", "ein", "eine",
    "einen", "und", "oder", "mit", "fuer", "von", "zu", "im", "auf", "ob",
    "des", "als",
})


def _content_tokens(query: str) -> list[str]:
    """Deterministic, order-preserving content tokens for relaxed retrieval."""
    tokens: list[str] = []
    seen: set[str] = set()
    for token in re.findall(r"[a-z0-9_]+", query.lower()):
        if token in _RETRIEVAL_STOPWORDS or token in seen:
            continue
        seen.add(token)
        tokens.append(token)
    return tokens


def _or_fts_query(tokens: list[str]) -> str:
    """Build a safe FTS5 OR query; quoting keeps terms literal (no operators)."""
    return " OR ".join(f'"{token}"' for token in tokens)


def _run_query(manifest_path: Path, query: str, k: int, prepared_fts_query: str | None = None) -> dict[str, Any]:
    return query_existing_index(
        manifest_path,
        query,
        k=k,
        filters={},
        resolve_evidence=True,
        project_sources=True,
        prepared_fts_query=prepared_fts_query,
    )

KIND = "repobrief.ask_context_pack"
VERSION = "1.0"
FORBIDDEN_OPERATIONS = [
    "implicit_refresh",
    "git_mutation",
    "snapshot_creation_on_read",
    "patch_application",
    "pull_request_mutation",
    "shell_execution",
    "merge_authorization",
]
DOES_NOT_ESTABLISH = [
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
_FRESHNESS_STATUSES = {"fresh", "stale", "unknown", "not_comparable", "not_applicable"}
_AVAILABILITY_STATUSES = {"available", "partial", "missing", "unknown"}
_RANGE_STATUSES = {"resolved", "missing", "drifted", "invalid", "degraded", "not_applicable"}


def _sha256_file(path: Path) -> str | None:
    try:
        h = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _as_status(value: Any, allowed: set[str], default: str) -> str:
    if isinstance(value, str) and value in allowed:
        return value
    return default


def _freshness_block(snapshot: dict[str, Any]) -> dict[str, Any]:
    raw = snapshot.get("freshness")
    if isinstance(raw, dict):
        status = _as_status(raw.get("status"), _FRESHNESS_STATUSES, "unknown")
        caveats = []
        if status in {"stale", "unknown", "not_comparable"}:
            caveats.append({
                "kind": "unknown_freshness" if status == "unknown" else "stale_snapshot",
                "detail": f"Snapshot freshness status is {status}.",
            })
        return {"status": status, "caveats": caveats}
    return {
        "status": "unknown",
        "caveats": [{"kind": "unknown_freshness", "detail": "Snapshot freshness metadata was unavailable."}],
    }


def _availability_block(snapshot: dict[str, Any]) -> dict[str, Any]:
    model = snapshot.get("availability_model")
    if isinstance(model, dict):
        status = _as_status(model.get("status"), _AVAILABILITY_STATUSES, "unknown")
        caveats = []
        if status in {"partial", "missing", "unknown"}:
            caveats.append({
                "kind": "missing_artifact" if status in {"partial", "missing"} else "degraded_validation",
                "detail": f"Snapshot availability status is {status}.",
            })
        return {"status": status, "caveats": caveats}
    return {
        "status": "unknown",
        "caveats": [{"kind": "degraded_validation", "detail": "Snapshot availability metadata was unavailable."}],
    }


def _snapshot_ref(snapshot: dict[str, Any], manifest_path: Path, freshness: dict[str, Any]) -> dict[str, Any]:
    manifest_sha = _sha256_file(manifest_path)
    result: dict[str, Any] = {
        "stem": manifest_path.name.replace(".bundle.manifest.json", ""),
        "manifest_path": str(manifest_path),
        "freshness_policy": "allow_stale_with_caveat",
        "freshness_status": freshness["status"],
    }
    if manifest_sha:
        result["manifest_sha256"] = manifest_sha
    run_id = snapshot.get("bundle_run_id")
    if isinstance(run_id, str) and run_id:
        result["git_commit"] = snapshot.get("git_commit") if isinstance(snapshot.get("git_commit"), str) else None
    return result


def _fts_query_of(query_result: dict[str, Any]) -> str | None:
    inner = query_result.get("query_result") if isinstance(query_result, dict) else None
    fts = inner.get("fts_query") if isinstance(inner, dict) else None
    return fts if isinstance(fts, str) and fts else None


def _retrieval_hits(query_result: dict[str, Any]) -> list[dict[str, Any]]:
    raw = query_result.get("query_result") if isinstance(query_result, dict) else None
    hits = raw.get("results") if isinstance(raw, dict) else []
    projection = query_result.get("source_citation_projection") if isinstance(query_result, dict) else None
    projected_items = projection.get("items") if isinstance(projection, dict) else []
    citations_by_ref = {
        str(item.get("chunk_id")): item.get("citation_id")
        for item in (projected_items if isinstance(projected_items, list) else [])
        if isinstance(item, dict) and item.get("chunk_id") is not None
    }
    result = []
    for idx, hit in enumerate(hits if isinstance(hits, list) else []):
        if not isinstance(hit, dict):
            continue
        ref = str(hit.get("chunk_id") or hit.get("id") or f"hit-{idx + 1}")
        item = {
            "artifact_role": str(hit.get("artifact_role") or hit.get("artifact_type") or "sqlite_index"),
            "ref": ref,
            "score": float(hit.get("score") or hit.get("bm25_score") or 0.0),
            "purpose": "retrieval candidate for ask context",
        }
        citation_id = citations_by_ref.get(ref)
        if isinstance(citation_id, str) and citation_id.startswith("cit_"):
            item["citation_id"] = citation_id
        result.append(item)
    return result


def _source_address_fields(hit: dict[str, Any]) -> dict[str, Any]:
    """Original repository address for a hit, so navigation tasks need not parse
    it out of the excerpt. The canonical_md range_ref stays the authority; these
    are source-address conveniences.
    """
    fields: dict[str, Any] = {}
    source_path = hit.get("source_path") or hit.get("path")
    if isinstance(source_path, str) and source_path:
        fields["source_path"] = source_path
    source_line_range = hit.get("source_line_range")
    if isinstance(source_line_range, dict):
        projected = {
            key: source_line_range[key]
            for key in ("start_line", "end_line", "display")
            if key in source_line_range
        }
        if projected:
            fields["source_line_range"] = projected
    citation_id = hit.get("citation_id")
    if isinstance(citation_id, str) and citation_id.startswith("cit_"):
        fields["citation_id"] = citation_id
    return fields


def _resolved_ranges(query_result: dict[str, Any], max_context_tokens: int) -> tuple[list[dict[str, Any]], int, bool]:
    resolved = query_result.get("resolved_evidence") if isinstance(query_result, dict) else None
    hits = resolved.get("hits") if isinstance(resolved, dict) else []
    budget_chars = max_context_tokens * 4
    used_chars = 0
    truncated = False
    result = []
    for idx, hit in enumerate(hits if isinstance(hits, list) else []):
        if not isinstance(hit, dict):
            continue
        range_value = hit.get("range") if isinstance(hit.get("range"), dict) else {}
        text = range_value.get("text") if isinstance(range_value, dict) else None
        excerpt = text if isinstance(text, str) else hit.get("text_excerpt")
        if isinstance(excerpt, str):
            remaining = max(0, budget_chars - used_chars)
            if len(excerpt) > remaining:
                excerpt = excerpt[:remaining]
                truncated = True
            used_chars += len(excerpt)
        status = _as_status(hit.get("range_status"), _RANGE_STATUSES, "degraded")
        range_ref = hit.get("range_ref") if isinstance(hit.get("range_ref"), dict) else {"ref": str(hit.get("chunk_id") or f"range-{idx + 1}")}
        item: dict[str, Any] = {
            "artifact_role": str(hit.get("artifact_role") or "canonical_md"),
            "status": status,
            "range_ref": range_ref,
        }
        if isinstance(excerpt, str):
            item["text_excerpt"] = excerpt
        content_sha = None
        if isinstance(range_value, dict):
            content_sha = range_value.get("content_sha256") or range_value.get("sha256")
        if isinstance(content_sha, str) and len(content_sha) == 64:
            item["content_sha256"] = content_sha
        item.update(_source_address_fields(hit))
        result.append(item)
    return result, used_chars, truncated


def _required_reading_block(resolution: dict[str, Any]) -> dict[str, Any]:
    rr = resolution.get("required_reading") if isinstance(resolution, dict) else {}
    if not isinstance(rr, dict):
        rr = {}
    return {
        "task_profile": str(resolution.get("task_profile") or rr.get("task_profile") or "basic_repo_question"),
        "required": list(rr.get("required") or []),
        "recommended": list(rr.get("recommended") or []),
        "missing_required": list(rr.get("missing_required") or []),
        "missing_recommended": list(rr.get("missing_recommended") or []),
        "status": str(rr.get("status") or resolution.get("status") or "not_applicable"),
    }


def build_ask_context_pack(
    bundle_manifest: str | Path,
    *,
    query: str,
    task_profile: str = "basic_repo_question",
    max_context_tokens: int = 8000,
    max_answer_tokens: int = 1200,
    k: int = 5,
) -> dict[str, Any]:
    """Build a read-only RepoGround ask context pack from existing artifacts.

    The function does not create or refresh snapshots. It delegates retrieval to the
    existing read-only index query and reports token budget as a constraint, not as a
    quality or correctness proof.
    """
    manifest_path = Path(bundle_manifest).expanduser().resolve()
    snapshot = snapshot_status(manifest_path)
    freshness = _freshness_block(snapshot)
    availability = _availability_block(snapshot)
    required_reading = _required_reading_block(resolve_required_reading_for_bundle(manifest_path, task_profile))
    query_result = _run_query(manifest_path, query, k)
    retrieval_hits = _retrieval_hits(query_result)
    resolved_ranges, used_chars, truncated = _resolved_ranges(query_result, max_context_tokens)
    executed_fts = _fts_query_of(query_result)
    strategy = "exact_and"
    relaxed = False

    # Recall fallback: the FTS router AND-joins every term, so one word absent
    # from a chunk zeroes an otherwise good match (common for natural-language
    # questions). When the exact match is empty, retry once with a relaxed OR
    # over content tokens. Adopt only if it recovers ranges, and label it so the
    # agent treats these as lower-precision candidates rather than exact hits.
    if not resolved_ranges and query_result.get("status") == "available":
        tokens = _content_tokens(query)
        if len(tokens) >= 2:
            or_query = _or_fts_query(tokens)
            relaxed_result = _run_query(manifest_path, query, k, prepared_fts_query=or_query)
            relaxed_ranges, relaxed_chars, relaxed_truncated = _resolved_ranges(relaxed_result, max_context_tokens)
            if relaxed_ranges:
                query_result = relaxed_result
                retrieval_hits = _retrieval_hits(relaxed_result)
                resolved_ranges, used_chars, truncated = relaxed_ranges, relaxed_chars, relaxed_truncated
                executed_fts = or_query
                strategy = "or_relaxed"
                relaxed = True

    retrieval = {
        "raw_query": query,
        "fts_query": executed_fts,
        "strategy": strategy if resolved_ranges else "none",
        "match_count": len(resolved_ranges),
    }

    caveats = list(freshness.get("caveats") or []) + list(availability.get("caveats") or [])
    if query_result.get("status") != "available":
        caveats.append({"kind": "missing_artifact", "detail": str(query_result.get("error") or "Query evidence unavailable.")})
    if truncated:
        caveats.append({"kind": "other", "detail": "Context excerpts were truncated to respect max_context_tokens."})
    if relaxed:
        caveats.append({
            "kind": "other",
            "detail": (
                "No exact (AND) retrieval match; results are relaxed OR-matches ranked by "
                "relevance and may be less precise. Rephrase with specific code identifiers "
                "for a tighter match."
            ),
        })
    elif not resolved_ranges:
        caveats.append({
            "kind": "other",
            "detail": (
                "No evidence matched the query. RepoGround retrieval is keyword/identifier-based "
                f"(executed FTS: {executed_fts or query!r}). Rephrase with concrete code "
                "identifiers or terms."
            ),
        })
    citation_obligations = [
        "Cite every strong repository claim with resolved RepoGround evidence where available.",
        "Surface freshness, availability and non-claim caveats in the answer.",
    ]
    return {
        "kind": KIND,
        "version": VERSION,
        "request_id": hashlib.sha256(f"{manifest_path}\0{task_profile}\0{query}".encode("utf-8")).hexdigest()[:16],
        "snapshot_ref": _snapshot_ref(snapshot, manifest_path, freshness),
        "freshness": freshness,
        "availability": availability,
        "required_reading": required_reading,
        "retrieval": retrieval,
        "retrieval_hits": retrieval_hits,
        "resolved_ranges": resolved_ranges,
        "answer_scaffold": {
            "citation_obligations": citation_obligations,
            "caveats_to_surface": caveats,
            "non_claims_to_surface": list(DOES_NOT_ESTABLISH),
        },
        "budget": {
            "max_context_tokens": max_context_tokens,
            "max_answer_tokens": max_answer_tokens,
            "approx_context_chars_used": used_chars,
            "truncated": truncated,
            "does_not_establish_quality": True,
        },
        "forbidden_operations": list(FORBIDDEN_OPERATIONS),
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }


def render_ask_context_pack_text(pack: dict[str, Any]) -> str:
    lines = [
        "RepoGround Ask Context Pack",
        f"status: required_reading={pack.get('required_reading', {}).get('status')} freshness={pack.get('freshness', {}).get('status')} availability={pack.get('availability', {}).get('status')}",
        f"snapshot: {pack.get('snapshot_ref', {}).get('manifest_path')}",
        "",
        "Citation obligations:",
    ]
    for item in pack.get("answer_scaffold", {}).get("citation_obligations", []):
        lines.append(f"- {item}")
    lines.append("")
    lines.append("Resolved ranges:")
    for item in pack.get("resolved_ranges", []):
        excerpt = item.get("text_excerpt")
        ref = item.get("range_ref")
        lines.append(f"- {item.get('artifact_role')} {item.get('status')} {ref}")
        if excerpt:
            lines.append(f"  excerpt: {excerpt[:240].replace(chr(10), ' ')}")
    lines.append("")
    lines.append("Non-claims:")
    for item in pack.get("does_not_establish", []):
        lines.append(f"- {item}")
    return "\n".join(lines) + "\n"
