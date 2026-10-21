from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from merger.repoground.core.bundle_access import (
    query_existing_index,
    resolve_required_reading_for_bundle,
    snapshot_status,
)
from merger.repoground.core.citation_projection import source_authority_projection
from merger.repoground.core.manifest_snapshot import (
    active_manifest_snapshot,
    resolve_manifest_path,
)
from merger.repoground.core.language_structure import (
    compose_language_structure_evidence,
)
from merger.repoground.core.language_structure_access import (
    load_language_structure_artifact,
)

# Bilingual (EN/DE) function-word stoplist. These words carry no retrieval
# signal but, because the FTS router AND-joins every term, a single one that is
# absent from a chunk zeroes an otherwise good match. Removing them for the
# relaxed OR retry is safe: the set holds only unambiguous function words, never
# code identifiers or content terms.
_RETRIEVAL_STOPWORDS = frozenset(
    {
        # English
        "how",
        "does",
        "do",
        "did",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "the",
        "a",
        "an",
        "of",
        "to",
        "into",
        "in",
        "on",
        "for",
        "and",
        "or",
        "with",
        "what",
        "which",
        "where",
        "when",
        "why",
        "who",
        "that",
        "this",
        "these",
        "those",
        "its",
        "it",
        "as",
        "at",
        "by",
        # German
        "wie",
        "was",
        "welche",
        "welcher",
        "welches",
        "wo",
        "wann",
        "warum",
        "wer",
        "ist",
        "sind",
        "war",
        "den",
        "dem",
        "der",
        "die",
        "das",
        "ein",
        "eine",
        "einen",
        "und",
        "oder",
        "mit",
        "fuer",
        "von",
        "zu",
        "im",
        "auf",
        "ob",
        "des",
        "als",
    }
)


def _content_tokens(query: str) -> list[str]:
    """Deterministic, order-preserving content tokens for relaxed retrieval."""
    tokens: list[str] = []
    seen: set[str] = set()
    normalized_query = unicodedata.normalize("NFC", query)
    for token in re.findall(r"\b\w+\b", normalized_query.lower()):
        # Retain the original identifier and additionally expose its snake_case
        # parts.  FTS tokenizers differ in their underscore handling; the OR
        # fallback must be deterministic across both behaviours.
        candidates = [token]
        if "_" in token:
            candidates.extend(part for part in token.split("_") if part)
        for candidate in candidates:
            if candidate in _RETRIEVAL_STOPWORDS or candidate in seen:
                continue
            seen.add(candidate)
            tokens.append(candidate)
    return tokens


def _or_fts_query(tokens: list[str]) -> str:
    """Build a safe FTS5 OR query; quoting keeps terms literal (no operators)."""
    return " OR ".join(f'"{token}"' for token in tokens)


def _run_query(
    manifest_path: Path, query: str, k: int, prepared_fts_query: str | None = None
) -> dict[str, Any]:
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
_RETRIEVAL_INFRASTRUCTURE_STATUSES = {"available", "missing", "invalid", "unknown"}
_RANGE_STATUSES = {
    "resolved",
    "missing",
    "drifted",
    "invalid",
    "degraded",
    "not_applicable",
}
_AVAILABILITY_STATUS_MAP = {
    "pass": "available",
    "warn": "partial",
    "fail": "missing",
    "available": "available",
    "partial": "partial",
    "missing": "missing",
    "unknown": "unknown",
}
MAX_EXCERPT_CHARS_PER_HIT = 1600


def _utf8_size(value: str) -> int:
    return len(value.encode("utf-8"))


def _utf8_prefix(value: str, *, max_bytes: int, max_characters: int) -> str:
    """Return a Unicode-safe prefix bounded independently by bytes and characters."""
    if max_bytes <= 0 or max_characters <= 0:
        return ""
    result: list[str] = []
    used = 0
    for character in value[:max_characters]:
        width = _utf8_size(character)
        if used + width > max_bytes:
            break
        result.append(character)
        used += width
    return "".join(result)


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
            caveats.append(
                {
                    "kind": "unknown_freshness"
                    if status == "unknown"
                    else "stale_snapshot",
                    "detail": f"Snapshot freshness status is {status}.",
                }
            )
        return {"status": status, "caveats": caveats}
    return {
        "status": "unknown",
        "caveats": [
            {
                "kind": "unknown_freshness",
                "detail": "Snapshot freshness metadata was unavailable.",
            }
        ],
    }


def _availability_block(snapshot: dict[str, Any]) -> dict[str, Any]:
    model = snapshot.get("availability_model")
    if isinstance(model, dict):
        raw_status = model.get("status")
        status = _AVAILABILITY_STATUS_MAP.get(raw_status, "unknown")
        status = _as_status(status, _AVAILABILITY_STATUSES, "unknown")
        caveats = []
        if status in {"partial", "missing", "unknown"}:
            caveats.append(
                {
                    "kind": "missing_artifact"
                    if status in {"partial", "missing"}
                    else "degraded_validation",
                    "detail": (
                        f"Snapshot availability status is {status}"
                        + (
                            f" (source status: {raw_status})."
                            if raw_status != status
                            else "."
                        )
                    ),
                }
            )
        return {"status": status, "caveats": caveats}
    return {
        "status": "unknown",
        "caveats": [
            {
                "kind": "degraded_validation",
                "detail": "Snapshot availability metadata was unavailable.",
            }
        ],
    }


def _retrieval_infrastructure_block(query_result: dict[str, Any]) -> dict[str, Any]:
    """Report whether the search backend itself resolved, separately from the bundle.

    `_availability_block` describes the snapshot; it cannot see whether the FTS
    index this pack queries actually exists. Keeping the two apart is what makes
    "the index is absent" distinguishable from "the index was searched and held
    nothing" — reporting the former as the latter tells the agent to rephrase a
    query that no wording could ever answer.
    """
    status = query_result.get("status")
    if status == "available":
        return {
            "status": "available",
            "index_resolved": True,
            "error_code": None,
            "detail": None,
        }
    error_code = query_result.get("error_code")
    detail = str(query_result.get("error") or "Query backend unavailable.")
    return {
        "status": _as_status(status, _RETRIEVAL_INFRASTRUCTURE_STATUSES, "unknown"),
        "index_resolved": False,
        "error_code": error_code,
        "detail": detail,
    }


def _snapshot_ref(
    snapshot: dict[str, Any], manifest_path: Path, freshness: dict[str, Any]
) -> dict[str, Any]:
    bound_snapshot = active_manifest_snapshot(manifest_path)
    manifest_sha = (
        bound_snapshot.binding.sha256
        if bound_snapshot is not None
        else _sha256_file(manifest_path)
    )
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
        result["git_commit"] = (
            snapshot.get("git_commit")
            if isinstance(snapshot.get("git_commit"), str)
            else None
        )
    return result


def _fts_query_of(query_result: dict[str, Any]) -> str | None:
    inner = query_result.get("query_result") if isinstance(query_result, dict) else None
    fts = inner.get("fts_query") if isinstance(inner, dict) else None
    return fts if isinstance(fts, str) and fts else None


def _retrieval_hits(query_result: dict[str, Any]) -> list[dict[str, Any]]:
    raw = query_result.get("query_result") if isinstance(query_result, dict) else None
    hits = raw.get("results") if isinstance(raw, dict) else []
    projection = (
        query_result.get("source_citation_projection")
        if isinstance(query_result, dict)
        else None
    )
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
            "artifact_role": str(
                hit.get("artifact_role") or hit.get("artifact_type") or "sqlite_index"
            ),
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


def _source_projection_fields(hit: dict[str, Any]) -> dict[str, Any]:
    fields = _source_address_fields(hit)
    fields["source_authority"] = source_authority_projection(
        hit.get("source_authority")
    )
    return fields


def _resolved_ranges(
    query_result: dict[str, Any],
    max_context_tokens: int,
    *,
    max_context_chars: int | None = None,
) -> tuple[list[dict[str, Any]], int, bool]:
    """Compatibility wrapper; the second result is now exact UTF-8 bytes used."""
    ranges, used_bytes, _used_characters, truncated, _omissions = (
        _resolved_ranges_with_budget(
            query_result,
            max_context_tokens,
            max_context_bytes=max_context_chars,
        )
    )
    return ranges, used_bytes, truncated


def _resolved_ranges_with_budget(
    query_result: dict[str, Any],
    max_context_tokens: int,
    *,
    max_context_bytes: int | None = None,
) -> tuple[list[dict[str, Any]], int, int, bool, list[dict[str, Any]]]:
    resolved = (
        query_result.get("resolved_evidence")
        if isinstance(query_result, dict)
        else None
    )
    hits = resolved.get("hits") if isinstance(resolved, dict) else []
    budget_bytes = (
        max_context_tokens * 4
        if max_context_bytes is None
        else max(0, int(max_context_bytes))
    )
    candidates: list[tuple[int, dict[str, Any], str]] = []
    seen: set[str] = set()
    truncated = False
    omissions: list[dict[str, Any]] = []

    for idx, hit in enumerate(hits if isinstance(hits, list) else []):
        if not isinstance(hit, dict):
            continue
        range_value = hit.get("range") if isinstance(hit.get("range"), dict) else {}
        text = range_value.get("text") if isinstance(range_value, dict) else None
        excerpt = text if isinstance(text, str) else hit.get("text_excerpt")
        if not isinstance(excerpt, str) or not excerpt.strip():
            truncated = True
            omissions.append(
                {
                    "lane": "canonical_md",
                    "reason": "missing_text_excerpt",
                    "ref": str(hit.get("chunk_id") or f"range-{idx + 1}"),
                }
            )
            continue
        range_ref = (
            hit.get("range_ref")
            if isinstance(hit.get("range_ref"), dict)
            else {"ref": str(hit.get("chunk_id") or f"range-{idx + 1}")}
        )
        source_path = hit.get("source_path") or hit.get("path") or ""
        key = json.dumps(
            {
                "source_path": source_path,
                "source_line_range": hit.get("source_line_range"),
                "range_ref": range_ref,
            },
            sort_keys=True,
            ensure_ascii=False,
        )
        if key in seen:
            truncated = True
            omissions.append(
                {
                    "lane": "canonical_md",
                    "reason": "duplicate_range",
                    "ref": str(range_ref.get("ref") or f"range-{idx + 1}"),
                }
            )
            continue
        seen.add(key)
        diagnostic = int(
            isinstance(source_path, str)
            and (
                source_path.startswith("docs/diagnostics/")
                or source_path.startswith("docs/proofs/")
            )
        )
        candidates.append((diagnostic, hit, excerpt))

    candidates.sort(key=lambda item: item[0])
    used_bytes = 0
    used_characters = 0
    result: list[dict[str, Any]] = []
    for position, (_diagnostic, hit, excerpt) in enumerate(candidates):
        remaining = budget_bytes - used_bytes
        if remaining <= 0:
            truncated = True
            omissions.extend(
                {
                    "lane": "canonical_md",
                    "reason": "hard_byte_budget_exceeded",
                    "ref": str(
                        candidate_hit.get("range_ref", {}).get("ref")
                        if isinstance(candidate_hit.get("range_ref"), dict)
                        else candidate_hit.get("chunk_id")
                        or f"range-{candidate_position + 1}"
                    ),
                    "remaining_bytes": 0,
                }
                for candidate_position, (_lane, candidate_hit, _text) in enumerate(
                    candidates[position:], start=position
                )
            )
            break
        remaining_hits = len(candidates) - position
        fair_share = max(1, remaining // max(1, remaining_hits))
        # Reserve enough of the remaining bytes for the first UTF-8 code
        # point when possible; keep earlier BM25 hits ahead of later ones.
        bounded_excerpt = _utf8_prefix(
            excerpt,
            max_bytes=min(remaining, max(fair_share, _utf8_size(excerpt[0]))),
            max_characters=MAX_EXCERPT_CHARS_PER_HIT,
        )
        if len(bounded_excerpt) < len(excerpt):
            truncated = True
            omissions.append(
                {
                    "lane": "canonical_md",
                    "reason": "excerpt_truncated",
                    "ref": str(
                        hit.get("range_ref", {}).get("ref")
                        if isinstance(hit.get("range_ref"), dict)
                        else hit.get("chunk_id") or f"range-{position + 1}"
                    ),
                    "original_bytes": _utf8_size(excerpt),
                    "selected_bytes": _utf8_size(bounded_excerpt),
                }
            )
        if not bounded_excerpt:
            truncated = True
            omissions.append(
                {
                    "lane": "canonical_md",
                    "reason": "hard_byte_budget_exceeded",
                    "ref": str(hit.get("chunk_id") or f"range-{position + 1}"),
                    "remaining_bytes": remaining,
                }
            )
            continue
        excerpt_bytes = _utf8_size(bounded_excerpt)
        used_bytes += excerpt_bytes
        used_characters += len(bounded_excerpt)
        status = _as_status(hit.get("range_status"), _RANGE_STATUSES, "degraded")
        range_ref = (
            hit.get("range_ref")
            if isinstance(hit.get("range_ref"), dict)
            else {"ref": str(hit.get("chunk_id") or f"range-{position + 1}")}
        )
        item: dict[str, Any] = {
            "artifact_role": str(hit.get("artifact_role") or "canonical_md"),
            "status": status,
            "range_ref": range_ref,
            "text_excerpt": bounded_excerpt,
            "text_excerpt_bytes": excerpt_bytes,
            "text_excerpt_characters": len(bounded_excerpt),
            "text_excerpt_truncated": len(bounded_excerpt) < len(excerpt),
        }
        range_value = hit.get("range") if isinstance(hit.get("range"), dict) else {}
        content_sha = range_value.get("content_sha256") or range_value.get("sha256")
        if isinstance(content_sha, str) and len(content_sha) == 64:
            item["content_sha256"] = content_sha
        item.update(_source_projection_fields(hit))
        result.append(item)
    return result, used_bytes, used_characters, truncated, omissions


def _language_range_projection(record: dict[str, Any]) -> dict[str, Any] | None:
    source = record.get("source")
    if not isinstance(source, dict):
        return None
    path = source.get("path")
    range_value = source.get("range")
    if not isinstance(path, str) or not path or not isinstance(range_value, dict):
        return None
    start = range_value.get("start_line")
    end = range_value.get("end_line")
    if not isinstance(start, int) or not isinstance(end, int):
        return None
    evidence = (
        record.get("evidence") if isinstance(record.get("evidence"), dict) else {}
    )
    confidence = evidence.get("confidence")
    score = (
        float(confidence)
        if isinstance(confidence, (int, float)) and not isinstance(confidence, bool)
        else 0.0
    )
    record_id = str(record.get("id") or f"{path}:{start}:{end}")
    adapter = record.get("adapter") if isinstance(record.get("adapter"), dict) else {}
    provenance = (
        record.get("provenance") if isinstance(record.get("provenance"), dict) else {}
    )
    uncertainty = [
        str(item) for item in record.get("uncertainty", []) if isinstance(item, str)
    ]
    return {
        "hit": {
            "artifact_role": "language_structure_json",
            "ref": record_id,
            "score": score,
            "purpose": "optional Rust/Bash structure navigation candidate",
            "language": record.get("language"),
            "adapter": dict(adapter),
            "repository_commit": provenance.get("repository_commit"),
            "bundle_manifest": provenance.get("bundle_manifest"),
            "bundle_manifest_sha256": provenance.get("bundle_manifest_sha256"),
            "evidence_level": evidence.get("level"),
            "confidence": score,
            "uncertainty": uncertainty,
            "source_range": dict(range_value),
        },
        "range": {
            "artifact_role": "language_structure_json",
            "status": "resolved",
            "source_authority": source_authority_projection(None),
            "range_ref": {
                "ref": record_id,
                "path": path,
                "range": dict(range_value),
                "language": record.get("language"),
                "relation": record.get("relation"),
                "symbol": record.get("symbol"),
                "target_symbol": record.get("target_symbol"),
                "adapter": record.get("adapter"),
                "evidence": evidence,
                "provenance": record.get("provenance"),
                "uncertainty": record.get("uncertainty"),
            },
            "source_path": path,
            "source_line_range": {
                "start_line": start,
                "end_line": end,
                "display": f"{start}-{end}",
            },
        },
    }


def _language_structure_for_query(
    manifest_path: Path,
    *,
    query: str,
    k: int,
    max_bytes: int,
    preloaded: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response = preloaded or load_language_structure_artifact(manifest_path)
    if response.get("status") != "available":
        return {
            "status": response.get("status", "missing"),
            "reason": response.get("reason"),
            "retrieval_hits": [],
            "resolved_ranges": [],
            "structured_evidence": None,
            "used_bytes": 0,
            "used_unicode_characters": 0,
            "omissions": [],
            "truncated": False,
        }
    document = response.get("content_json")
    if not isinstance(document, dict):
        return {
            "status": "blocked",
            "reason": "language_structure_content_unavailable",
            "retrieval_hits": [],
            "resolved_ranges": [],
            "structured_evidence": None,
            "used_bytes": 0,
            "used_unicode_characters": 0,
            "omissions": [],
            "truncated": False,
        }
    terms = _content_tokens(query)
    max_items = max(10, min(50, k * 2))
    composed = compose_language_structure_evidence(
        document,
        terms=terms,
        max_bytes=max_bytes,
        max_items=max_items,
        bundle_manifest_sha256=(
            response.get("manifest_sha256")
            if isinstance(response.get("manifest_sha256"), str)
            else None
        ),
    )
    evidence = (
        composed.get("evidence") if isinstance(composed.get("evidence"), dict) else {}
    )
    records = [item for item in evidence.get("records", []) if isinstance(item, dict)]
    degradations = [
        item for item in evidence.get("degradations", []) if isinstance(item, dict)
    ]
    hits: list[dict[str, Any]] = []
    ranges: list[dict[str, Any]] = []
    for record in records:
        projected = _language_range_projection(record)
        if projected is None:
            continue
        hits.append(projected["hit"])
        ranges.append(projected["range"])
    budget = composed.get("budget") if isinstance(composed.get("budget"), dict) else {}
    selection = (
        composed.get("selection") if isinstance(composed.get("selection"), dict) else {}
    )
    omitted = budget.get("omitted") if isinstance(budget.get("omitted"), dict) else {}
    truncated = bool(
        selection.get("source_truncated")
        or int(omitted.get("records", 0) or 0) > 0
        or int(omitted.get("degradations", 0) or 0) > 0
    )
    structured = composed if records or degradations else None
    return {
        "status": "available",
        "reason": None,
        "retrieval_hits": hits,
        "resolved_ranges": ranges,
        "structured_evidence": structured,
        "used_bytes": int(budget.get("used_bytes", 0) or 0) if structured else 0,
        "used_unicode_characters": (
            int(budget.get("used_unicode_characters", 0) or 0) if structured else 0
        ),
        "omissions": list(budget.get("omissions", [])),
        "truncated": truncated,
        "has_degradations": bool(degradations),
    }


def _required_reading_block(resolution: dict[str, Any]) -> dict[str, Any]:
    rr = resolution.get("required_reading") if isinstance(resolution, dict) else {}
    if not isinstance(rr, dict):
        rr = {}
    return {
        "task_profile": str(
            resolution.get("task_profile")
            or rr.get("task_profile")
            or "basic_repo_question"
        ),
        "required": list(rr.get("required") or []),
        "recommended": list(rr.get("recommended") or []),
        "missing_required": list(rr.get("missing_required") or []),
        "missing_recommended": list(rr.get("missing_recommended") or []),
        "status": str(rr.get("status") or resolution.get("status") or "not_applicable"),
    }


def _context_budget(
    max_context_tokens: int, max_context_bytes: int | None
) -> tuple[int, int]:
    if (
        isinstance(max_context_tokens, bool)
        or not isinstance(max_context_tokens, int)
        or max_context_tokens <= 0
    ):
        raise ValueError("max_context_tokens must be a positive integer")
    if max_context_bytes is not None and (
        isinstance(max_context_bytes, bool)
        or not isinstance(max_context_bytes, int)
        or max_context_bytes <= 0
    ):
        raise ValueError("max_context_bytes must be a positive integer when set")
    token_ceiling = max_context_tokens * 4
    return token_ceiling, min(
        token_ceiling,
        max_context_bytes if max_context_bytes is not None else token_ceiling,
    )


def _language_context_reserve(
    language_response: Mapping[str, Any],
    *,
    query: str,
    k: int,
    total_context_bytes: int,
) -> int:
    if language_response.get("status") != "available":
        return 0
    language_document = language_response.get("content_json")
    if not isinstance(language_document, dict):
        return 0
    preview = compose_language_structure_evidence(
        language_document,
        terms=_content_tokens(query),
        max_bytes=total_context_bytes,
        max_items=max(10, min(50, k * 2)),
        bundle_manifest_sha256=(
            language_response.get("manifest_sha256")
            if isinstance(language_response.get("manifest_sha256"), str)
            else None
        ),
    )
    budget = preview.get("budget") if isinstance(preview, Mapping) else None
    used_bytes = budget.get("used_bytes") if isinstance(budget, Mapping) else 0
    if isinstance(used_bytes, bool) or not isinstance(used_bytes, int):
        return 0
    # Reserve no more than one third for optional structure, but reserve the
    # exact preview size when it is smaller. This prevents false text-lane
    # "budget exceeded" omissions while keeping canonical excerpts competitive.
    return min(max(0, used_bytes), 4096, total_context_bytes // 3)


def _source_candidates_from_index(
    response: dict[str, Any], query_terms: set[str]
) -> list[tuple[int, str, dict[str, Any], dict[str, Any]]]:
    """Return only source-addressed, evidence-resolved chunks from one index read."""
    raw = response.get("query_result")
    resolved = response.get("resolved_evidence")
    rows = raw.get("results") if isinstance(raw, dict) else None
    hits = resolved.get("hits") if isinstance(resolved, dict) else None
    if not isinstance(rows, list) or not isinstance(hits, list):
        return []
    projection = response.get("source_citation_projection")
    items = projection.get("items") if isinstance(projection, dict) else None
    citations_by_ref: dict[str, str] = {}
    ambiguous_refs: set[str] = set()
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        ref = item.get("chunk_id")
        citation = item.get("citation_id")
        if (
            not isinstance(ref, str)
            or not isinstance(citation, str)
            or not citation.startswith("cit_")
        ):
            continue
        previous = citations_by_ref.setdefault(ref, citation)
        if previous != citation:
            ambiguous_refs.add(ref)
    evidence_by_ref = {
        hit["chunk_id"]: hit
        for hit in hits
        if isinstance(hit, dict)
        and isinstance(hit.get("chunk_id"), str)
        and hit.get("chunk_id") not in ambiguous_refs
        and hit.get("range_status") == "resolved"
        and isinstance(hit.get("citation_id"), str)
        and hit["citation_id"].startswith("cit_")
        and citations_by_ref.get(hit["chunk_id"]) == hit["citation_id"]
    }
    candidates = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        source = row.get("source_path") or row.get("path")
        evidence = evidence_by_ref.get(row.get("chunk_id"))
        if (
            not isinstance(source, str)
            or not source
            or evidence is None
            or evidence.get("source_path") != source
        ):
            continue
        filename_tokens = set(
            re.findall(
                r"\b\w+\b",
                unicodedata.normalize("NFC", source)
                .lower()
                .replace("/", " ")
                .replace("-", " ")
                .replace("_", " ")
                .replace(".", " "),
            )
        )
        candidates.append((len(filename_tokens & query_terms), source, row, evidence))
    return candidates


_NAVIGATION_LOCATORS = frozenset(
    {
        "find",
        "finde",
        "finden",
        "locate",
        "where",
        "wo",
        "which",
        "welche",
        "welcher",
        "welches",
        "suche",
        "zeige",
    }
)
_NAVIGATION_OBJECTS = frozenset(
    {
        "implementation",
        "implementierung",
        "implemented",
        "implementiert",
        "entrypoint",
        "context",
        "filename",
        "dateiname",
        "file",
        "files",
        "datei",
        "dateien",
        "path",
        "pfad",
        "source",
        "sourcecode",
        "quellcode",
        "defined",
        "definiert",
        "defines",
        "module",
        "modules",
        "modul",
        "modulen",
        "paths",
        "pfade",
        "pfaden",
        "handled",
        "handler",
        "test",
    }
)


_SOURCE_LOCATION_NOUNS = frozenset(
    {
        "module",
        "modules",
        "modul",
        "modulen",
        "file",
        "files",
        "datei",
        "dateien",
        "path",
        "paths",
        "pfad",
        "pfade",
        "pfaden",
        "source",
        "quellcode",
        "filename",
        "dateiname",
    }
)
_SOURCE_LOCATION_QUESTION_WORDS = frozenset(
    {"which", "what", "welche", "welcher", "welches", "welchem", "welchen"}
)
_FIND_EXPLANATION_OPENERS = frozenset(
    {
        "why",
        "how",
        "what",
        "when",
        "whether",
        "if",
        "warum",
        "wieso",
        "wie",
        "was",
        "wann",
        "ob",
    }
)
_WHERE_EXPLANATION_VERBS = frozenset(
    {
        "do",
        "does",
        "did",
        "fail",
        "fails",
        "crashes",
        "fehlschlägt",
        "schlägt",
        "scheitert",
        "tritt",
        "passiert",
    }
)
_WHERE_EXPLANATION_PARTICIPLES = frozenset(
    {"failing", "crashing", "breaking", "hanging"}
)
_FIND_EXPLANATION_NOUNS = frozenset({"reason", "cause", "grund", "ursache"})


def _where_is_source_location(words: list[str]) -> bool:
    """Ignore emphasis but not question verbs that request an explanation."""
    following = words[1:]
    if following[:1] in (["exactly"], ["genau"]):
        following = following[1:]
    if (
        following
        and following[0] in {"is", "are", "was", "were"}
        and following[-1] in _WHERE_EXPLANATION_PARTICIPLES
    ):
        return False
    return not following or not (set(following) & _WHERE_EXPLANATION_VERBS)


def _find_source_location_complement(
    words: list[str], *, require_locative: bool
) -> bool:
    """Use file-location grammar, never an explanatory complement."""
    if words[:1] in (["exactly"], ["genau"]):
        words = words[1:]
    if not words or set(words[:5]) & _FIND_EXPLANATION_NOUNS:
        return False
    if (
        len(words) > 2
        and words[0] == "in"
        and words[1] in _SOURCE_LOCATION_QUESTION_WORDS
    ):
        words = words[1:]
    if words[0] in _SOURCE_LOCATION_QUESTION_WORDS:
        return len(words) > 1 and words[1] in _SOURCE_LOCATION_NOUNS
    if require_locative or words[0] in {"where", "wo"}:
        return words[0] in {"where", "wo"} and _where_is_source_location(words)
    return words[0] not in _FIND_EXPLANATION_OPENERS


def _navigation_path_intent(query: str) -> bool:
    """Only explicit source-location requests may bias indexed OR ranking."""
    words = re.findall(r"\b\w+\b", unicodedata.normalize("NFC", query).lower())
    if not words or not set(words) & _NAVIGATION_OBJECTS:
        return False
    # Source-pair noun phrases are requests for matching implementation and
    # test files, unlike explanatory questions containing the same nouns.
    nouns = set(words)
    if (
        "?" not in query
        and {"implementation", "corresponding", "test"} <= nouns
        and not nouns & (_FIND_EXPLANATION_OPENERS | {"does", "is", "has", "have"})
    ):
        return True
    # "find" inside a why/how question is content, not a source locator.
    if words[0] in {"please", "bitte"}:
        words = words[1:]
    if (
        len(words) > 2
        and words[0] == "in"
        and words[1] in _SOURCE_LOCATION_QUESTION_WORDS
    ):
        words = words[1:]
    if not words:
        return False
    if words[0] in {"find", "finde", "finden", "locate", "suche", "zeige"}:
        complement = words[1:]
        while complement and complement[0] in {
            "mir",
            "mich",
            "me",
            "sie",
            "bitte",
            "mal",
            "du",
            "exactly",
            "genau",
        }:
            complement = complement[1:]
        is_find_out = complement[:1] in (["out"], ["heraus"])
        return _find_source_location_complement(
            complement[1:] if is_find_out else complement,
            require_locative=is_find_out,
        )
    if words[0] in _SOURCE_LOCATION_QUESTION_WORDS:
        return len(words) > 1 and words[1] in _SOURCE_LOCATION_NOUNS
    if words[0] in {"where", "wo"}:
        return _where_is_source_location(words)
    return words[0] in _NAVIGATION_LOCATORS


def _relaxed_path_index_reads(
    manifest_path: Path, *, query: str, fts_query: str, k: int
) -> list[dict[str, Any]]:
    """Two bounded read-only path hints, still constrained by the original FTS."""
    generic = {
        "find",
        "heraus",
        "genau",
        "exactly",
        "configured",
        "implementation",
        "implementierung",
        "corresponding",
        "associated",
        "generated",
        "begrenztes",
        "änderungsumfeld",
        "actual",
        "real",
        "source",
        "files",
        "script",
        "scripts",
        "package",
        "query",
        "where",
        "context",
    }
    anchors = [
        term
        for term in _content_tokens(query)
        if (
            5 <= len(term) <= 32
            and term not in generic
            and term not in _NAVIGATION_LOCATORS
            and (term == "entrypoint" or term not in _NAVIGATION_OBJECTS)
        )
    ][:2]
    results = []
    for anchor in anchors:
        indexed = query_existing_index(
            manifest_path,
            query,
            k=min(100, max(1, k * 4)),
            filters={"path": anchor},
            resolve_evidence=True,
            project_sources=True,
            prepared_fts_query=fts_query,
        )
        if indexed.get("status") == "available":
            results.append(indexed)
    return results


def _prefer_diverse_relaxed_sources(
    query_result: dict[str, Any],
    *,
    query: str,
    k: int,
    path_results: list[dict[str, Any]],
) -> dict[str, Any]:
    """Take at most k distinct sources with existing verifiable citations."""
    candidates = []
    projected = []
    for result in (query_result, *path_results):
        candidates.extend(
            _source_candidates_from_index(result, set(_content_tokens(query)))
        )
        citations = result.get("source_citation_projection")
        if isinstance(citations, dict) and isinstance(citations.get("items"), list):
            projected.extend(
                item for item in citations["items"] if isinstance(item, dict)
            )

    # Ordinary answers retain original FTS/BM25 order; explicit navigation
    # alone may prioritize filename matches after the first original hit.
    navigation = _navigation_path_intent(query)
    ordered = (
        candidates[:1] + sorted(candidates[1:], key=lambda row: -row[0])
        if navigation
        else candidates
    )
    selected = []
    seen = set()
    for _overlap, source, row, evidence in ordered:
        # BM25 ranks chunks, not files. Diversity applies only to navigation.
        identity = source if navigation else row.get("chunk_id")
        if identity in seen:
            continue
        seen.add(identity)
        selected.append((row, evidence))
        if len(selected) == k:
            break
    projection_by_identity = {
        (item.get("chunk_id"), item.get("citation_id")): item
        for item in projected
        if isinstance(item.get("chunk_id"), str)
        and isinstance(item.get("citation_id"), str)
    }
    return {
        "query_result": {"results": [row for row, _ in selected]},
        "resolved_evidence": {"hits": [hit for _, hit in selected]},
        "source_citation_projection": {
            "items": [
                projection_by_identity[(row["chunk_id"], hit["citation_id"])]
                for row, hit in selected
            ]
        },
    }


def _balanced_relaxed_ranges(
    selected: dict[str, Any],
    max_context_tokens: int,
    max_context_bytes: int,
) -> tuple[list[dict[str, Any]], int, int, bool, list[dict[str, Any]]]:
    """Share remaining bytes, not a fixed per-hit slice that may round to zero."""
    # The common allocator already bounds UTF-8 excerpts, preserves citations,
    # reports omissions, and reallocates unused bytes to later verified hits.
    return _resolved_ranges_with_budget(
        selected, max_context_tokens, max_context_bytes=max_context_bytes
    )


def _manifest_content_digest(manifest_path: Path) -> str | None:
    """Verify the source manifest across separately resolved index reads."""
    try:
        return hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    except OSError:
        return None


def _query_context(
    manifest_path: Path,
    *,
    query: str,
    k: int,
    max_context_tokens: int,
    max_context_bytes: int,
) -> dict[str, Any]:
    query_result = _run_query(manifest_path, query, k)
    retrieval_hits = _retrieval_hits(query_result)
    ranges, used_bytes, used_characters, truncated, omissions = (
        _resolved_ranges_with_budget(
            query_result,
            max_context_tokens,
            max_context_bytes=max_context_bytes,
        )
    )
    state: dict[str, Any] = {
        "query_result": query_result,
        "retrieval_hits": retrieval_hits,
        "resolved_ranges": ranges,
        "used_bytes": used_bytes,
        "used_characters": used_characters,
        "truncated": truncated,
        "omissions": omissions,
        "fts_query": _fts_query_of(query_result),
        "strategy": "exact_and",
        "relaxed": False,
    }
    if ranges or query_result.get("status") != "available":
        return state
    tokens = _content_tokens(query)
    if len(tokens) < 2:
        return state
    or_query = _or_fts_query(tokens)
    # Overfetch verified chunks only as needed; preserve the wider existing
    # search window for explicit navigation with multiple requested sources.
    navigation = _navigation_path_intent(query)
    candidate_k = min(100, max(1, k * 3, 24 if navigation and k > 1 else k))
    manifest_digest_before = (
        _manifest_content_digest(manifest_path) if navigation else None
    )
    relaxed_result = _run_query(
        manifest_path, query, candidate_k, prepared_fts_query=or_query
    )
    # With k=1, a verified first OR candidate already fills the answer.
    # Further path reads cannot alter it but would revalidate the full index.
    verified_candidates = _source_candidates_from_index(relaxed_result, set(tokens))
    need_path_hints = navigation and (k > 1 or not verified_candidates)
    path_results = (
        _relaxed_path_index_reads(manifest_path, query=query, fts_query=or_query, k=k)
        if need_path_hints
        else []
    )
    # The path may name a different manifest after an atomic replacement.
    # Hash only a small manifest, not the entire SQLite index, on navigation.
    manifest_content_unchanged = not path_results or (
        manifest_digest_before is not None
        and manifest_digest_before == _manifest_content_digest(manifest_path)
    )
    # Separate index queries can observe different SQLite bytes after a swap.
    # Only combine evidence from the same hashed artifact and bound manifest.
    artifact = relaxed_result.get("index_artifact")
    stable_path_results = [
        indexed
        for indexed in path_results
        if manifest_content_unchanged
        and isinstance(artifact, dict)
        and isinstance(artifact.get("sha256"), str)
        and re.fullmatch(r"[0-9a-f]{64}", artifact["sha256"])
        and isinstance(relaxed_result.get("bundle_manifest"), str)
        and indexed.get("index_artifact") == artifact
        and indexed.get("bundle_manifest") == relaxed_result["bundle_manifest"]
    ]
    rejected_path_identity = len(stable_path_results) != len(path_results)
    path_results = stable_path_results
    path_warnings = [
        warning
        for indexed in path_results
        for warning in (indexed.get("warnings") or [])
        if isinstance(warning, dict)
    ]
    selected_result = _prefer_diverse_relaxed_sources(
        relaxed_result, query=query, k=k, path_results=path_results
    )
    # Check every consulted index result, including filtered path hints.
    # Uncitable candidates never become answer evidence, but must be reported.
    invalid_candidates = (
        [
            {
                "lane": "canonical_md",
                "reason": (
                    "bundle_manifest_identity_unverified"
                    if not manifest_content_unchanged
                    else "index_artifact_mismatch"
                ),
                "ref": "filtered_path_index",
            }
        ]
        if rejected_path_identity
        else []
    )
    for indexed in (relaxed_result, *path_results):
        verified_ids = {
            row.get("chunk_id")
            for _overlap, _source, row, _evidence in _source_candidates_from_index(
                indexed, set(tokens)
            )
        }
        raw_rows = indexed.get("query_result")
        raw_rows = raw_rows.get("results") if isinstance(raw_rows, dict) else []
        invalid_candidates.extend(
            {
                "lane": "canonical_md",
                "reason": "unverified_index_evidence",
                "ref": row["chunk_id"],
            }
            for row in (raw_rows if isinstance(raw_rows, list) else [])
            if isinstance(row, dict)
            and isinstance(row.get("chunk_id"), str)
            and row["chunk_id"] not in verified_ids
        )
    invalid_candidates = list(
        {
            (item["lane"], item["reason"], item["ref"]): item
            for item in invalid_candidates
        }.values()
    )
    relaxed = _balanced_relaxed_ranges(
        selected_result, max_context_tokens, max_context_bytes
    )
    if not relaxed[0]:
        state["omissions"].extend(invalid_candidates)
        return state
    (
        state["resolved_ranges"],
        state["used_bytes"],
        state["used_characters"],
        state["truncated"],
        state["omissions"],
    ) = relaxed
    state["omissions"].extend(invalid_candidates)
    emitted = {
        (item.get("source_path"), item.get("citation_id"))
        for item in relaxed[0]
        if isinstance(item.get("citation_id"), str)
    }
    selected_hits = [
        hit
        for hit in selected_result["resolved_evidence"]["hits"]
        if (hit.get("source_path"), hit.get("citation_id")) in emitted
    ]
    emitted_ids = {hit["chunk_id"] for hit in selected_hits}
    emitted_response = {
        **relaxed_result,
        "warnings": list(
            {
                json.dumps(warning, sort_keys=True): warning
                for warning in list(relaxed_result.get("warnings") or [])
                + path_warnings
            }.values()
        ),
        "query_result": {
            **(relaxed_result.get("query_result") or {}),
            **selected_result["query_result"],
            "fts_query": or_query,
            "results": [
                row
                for row in selected_result["query_result"]["results"]
                if row.get("chunk_id") in emitted_ids
            ],
        },
        "resolved_evidence": {
            **(relaxed_result.get("resolved_evidence") or {}),
            "hits": selected_hits,
        },
        "source_citation_projection": {
            **(relaxed_result.get("source_citation_projection") or {}),
            "items": [
                item
                for item in selected_result["source_citation_projection"]["items"]
                if item.get("chunk_id") in emitted_ids
                and (
                    item.get("citation_id")
                    in {citation for _source, citation in emitted}
                )
            ],
        },
    }
    state.update(
        {
            "query_result": emitted_response,
            "retrieval_hits": _retrieval_hits(emitted_response),
            "fts_query": or_query,
            "strategy": "or_relaxed",
            "relaxed": True,
        }
    )
    return state


def _retrieval_availability(
    availability: Mapping[str, Any], retrieval_infrastructure: Mapping[str, Any]
) -> dict[str, Any]:
    if retrieval_infrastructure["index_resolved"]:
        return dict(availability)
    return {
        "status": "missing",
        "caveats": list(availability.get("caveats") or [])
        + [
            {
                "kind": "missing_artifact",
                "detail": retrieval_infrastructure["detail"],
            }
        ],
    }


def _retrieval_caveats(
    freshness: Mapping[str, Any],
    availability: Mapping[str, Any],
    *,
    state: Mapping[str, Any],
    retrieval_infrastructure: Mapping[str, Any],
    query: str,
    additional_evidence_present: bool,
) -> list[dict[str, Any]]:
    caveats = list(freshness.get("caveats") or []) + list(
        availability.get("caveats") or []
    )
    if state["truncated"]:
        caveats.append(
            {
                "kind": "other",
                "detail": "Context evidence was truncated to respect the hard UTF-8 byte budget.",
            }
        )
    if any(
        item.get("reason") == "unverified_index_evidence" for item in state["omissions"]
    ):
        caveats.append(
            {
                "kind": "degraded_validation",
                "detail": "Some OR retrieval candidates lacked verified citations and were excluded.",
            }
        )
    if any(
        item.get("reason")
        in {"index_artifact_mismatch", "bundle_manifest_identity_unverified"}
        for item in state["omissions"]
    ):
        caveats.append(
            {
                "kind": "degraded_validation",
                "detail": (
                    "Filtered source candidates from a different or unverified index "
                    "artifact or bundle manifest were excluded."
                ),
            }
        )
    if state["relaxed"]:
        caveats.append(
            {
                "kind": "other",
                "detail": (
                    "No exact (AND) retrieval match; results are relaxed OR-matches ranked by "
                    "relevance and may be less precise. Rephrase with specific code identifiers "
                    "for a tighter match."
                ),
            }
        )
    elif (
        not state["resolved_ranges"]
        and not additional_evidence_present
        and retrieval_infrastructure["index_resolved"]
    ):
        caveats.append(
            {
                "kind": "other",
                "detail": (
                    "No evidence matched the query. RepoGround retrieval is keyword/identifier-based "
                    f"(executed FTS: {state['fts_query'] or query!r}). Rephrase with concrete code "
                    "identifiers or terms."
                ),
            }
        )
    return caveats


def _final_retrieval_metadata(
    query: str,
    state: Mapping[str, Any],
    *,
    text_match_count: int,
    structure_match_count: int,
) -> dict[str, Any]:
    if text_match_count:
        strategy = str(state["strategy"])
        if structure_match_count:
            strategy += "_with_structure"
    elif structure_match_count:
        strategy = "structure_only"
    else:
        strategy = "none"
    return {
        "raw_query": query,
        "fts_query": state["fts_query"],
        "strategy": strategy,
        "match_count": len(state["resolved_ranges"]),
    }


def _merge_language_context(
    state: dict[str, Any],
    caveats: list[dict[str, Any]],
    language_context: Mapping[str, Any],
) -> dict[str, Any]:
    structured_evidence: dict[str, Any] = {}
    if language_context.get("structured_evidence") is not None:
        structured_evidence["language_structure"] = language_context[
            "structured_evidence"
        ]
        state["retrieval_hits"].extend(language_context["retrieval_hits"])
        state["resolved_ranges"].extend(language_context["resolved_ranges"])
        state["used_bytes"] += int(language_context.get("used_bytes", 0) or 0)
        state["used_characters"] += int(
            language_context.get("used_unicode_characters", 0) or 0
        )
        state["omissions"].extend(language_context.get("omissions", []))
        caveats.append(
            {
                "kind": "other",
                "detail": (
                    "Optional Rust/Bash structure evidence is derived navigation evidence; "
                    "its adapter, confidence, range and uncertainty fields must remain visible."
                ),
            }
        )
        if language_context.get("has_degradations"):
            caveats.append(
                {
                    "kind": "degraded_validation",
                    "detail": (
                        "Relevant language-structure evidence contains explicit adapter degradation "
                        "or unresolved-case records; do not promote it to runtime truth."
                    ),
                }
            )
    elif language_context.get("status") == "blocked":
        caveats.append(
            {
                "kind": "degraded_validation",
                "detail": (
                    "Optional language-structure evidence was rejected: "
                    + str(language_context.get("reason") or "untrusted sidecar")
                ),
            }
        )
    if language_context.get("truncated"):
        state["truncated"] = True
        if language_context.get("structured_evidence") is None:
            state["omissions"].extend(language_context.get("omissions", []))
        caveats.append(
            {
                "kind": "other",
                "detail": "Relevant language-structure evidence was omitted by the shared context budget.",
            }
        )
    return structured_evidence


def build_ask_context_pack(
    bundle_manifest: str | Path,
    *,
    query: str,
    task_profile: str = "basic_repo_question",
    max_context_tokens: int = 8000,
    max_context_bytes: int | None = None,
    max_answer_tokens: int = 1200,
    k: int = 5,
) -> dict[str, Any]:
    """Build a read-only RepoGround ask context pack from existing artifacts.

    The function does not create or refresh snapshots. It delegates retrieval to the
    existing read-only index query and reports token budget as a constraint, not as a
    quality or correctness proof.
    """
    token_derived_byte_ceiling, total_context_bytes = _context_budget(
        max_context_tokens, max_context_bytes
    )
    manifest_path = resolve_manifest_path(bundle_manifest)
    snapshot = snapshot_status(manifest_path)
    freshness = _freshness_block(snapshot)
    availability = _availability_block(snapshot)
    required_reading = _required_reading_block(
        resolve_required_reading_for_bundle(manifest_path, task_profile)
    )
    language_response = load_language_structure_artifact(manifest_path)
    language_reserve = _language_context_reserve(
        language_response,
        query=query,
        k=k,
        total_context_bytes=total_context_bytes,
    )
    text_context_bytes = max(0, total_context_bytes - language_reserve)
    state = _query_context(
        manifest_path,
        query=query,
        k=k,
        max_context_tokens=max_context_tokens,
        max_context_bytes=text_context_bytes,
    )
    text_match_count = len(state["resolved_ranges"])

    retrieval_infrastructure = _retrieval_infrastructure_block(state["query_result"])
    availability = _retrieval_availability(availability, retrieval_infrastructure)
    language_context = _language_structure_for_query(
        manifest_path,
        query=query,
        k=k,
        max_bytes=max(0, total_context_bytes - state["used_bytes"]),
        preloaded=language_response,
    )
    language_caveats: list[dict[str, Any]] = []
    structured_evidence = _merge_language_context(
        state, language_caveats, language_context
    )
    structure_match_count = len(state["resolved_ranges"]) - text_match_count
    retrieval = _final_retrieval_metadata(
        query,
        state,
        text_match_count=text_match_count,
        structure_match_count=structure_match_count,
    )
    caveats = _retrieval_caveats(
        freshness,
        availability,
        state=state,
        retrieval_infrastructure=retrieval_infrastructure,
        query=query,
        additional_evidence_present=bool(structured_evidence),
    )
    caveats.extend(language_caveats)

    citation_obligations = [
        "Cite every strong repository claim with resolved RepoGround evidence where available.",
        "Surface freshness, availability and non-claim caveats in the answer.",
    ]
    result = {
        "kind": KIND,
        "version": VERSION,
        "request_id": hashlib.sha256(
            f"{manifest_path}\0{task_profile}\0{query}".encode("utf-8")
        ).hexdigest()[:16],
        "snapshot_ref": _snapshot_ref(snapshot, manifest_path, freshness),
        "freshness": freshness,
        "availability": availability,
        "required_reading": required_reading,
        "retrieval": retrieval,
        "retrieval_infrastructure": retrieval_infrastructure,
        "retrieval_hits": state["retrieval_hits"],
        "resolved_ranges": state["resolved_ranges"],
        "answer_scaffold": {
            "citation_obligations": citation_obligations,
            "caveats_to_surface": caveats,
            "non_claims_to_surface": list(DOES_NOT_ESTABLISH),
        },
        "budget": {
            "max_context_tokens": max_context_tokens,
            "token_derived_byte_ceiling": token_derived_byte_ceiling,
            "max_context_bytes": total_context_bytes,
            "max_answer_tokens": max_answer_tokens,
            "context_bytes_used": state["used_bytes"],
            "context_unicode_characters_used": state["used_characters"],
            "approx_context_chars_used": state["used_characters"],
            "byte_budget_is_hard": True,
            "unit": "utf8_bytes",
            "accounting": (
                "sum(UTF-8 bytes of emitted canonical_md text_excerpt values) + "
                "canonical JSON UTF-8 bytes of emitted language_structure.evidence; "
                "address and envelope metadata are outside the evidence payload budget"
            ),
            "omissions": state["omissions"],
            "truncated": state["truncated"],
            "does_not_establish_quality": True,
        },
        "forbidden_operations": list(FORBIDDEN_OPERATIONS),
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }
    if structured_evidence:
        result["structured_evidence"] = structured_evidence
    return result


def _render_source_authority_text_scalar(value: str) -> str:
    """Render one authority scalar without raw terminal/Unicode controls."""
    rendered = json.dumps(value, ensure_ascii=False)
    parts: list[str] = []
    for character in rendered:
        if unicodedata.category(character) in {"Cc", "Cf", "Zl", "Zp"}:
            codepoint = ord(character)
            escape = (
                f"\\u{codepoint:04x}" if codepoint <= 0xFFFF else f"\\U{codepoint:08x}"
            )
            parts.append(escape)
        else:
            parts.append(character)
    return "".join(parts)


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
        source_authority = item.get("source_authority")
        if isinstance(source_authority, dict):
            lines.append(
                f"  source_authority: {source_authority.get('classification')}"
            )
            for field in (
                "status",
                "canonicality",
                "role",
                "temporal_scope",
                "observed_at",
                "last_reviewed",
            ):
                value = source_authority.get(field)
                if isinstance(value, str) and value:
                    rendered_value = _render_source_authority_text_scalar(value)
                    lines.append(f"  source_authority.{field}: {rendered_value}")
            for caveat in source_authority.get("does_not_establish", []):
                if isinstance(caveat, str):
                    rendered_caveat = _render_source_authority_text_scalar(caveat)
                    lines.append(f"  does_not_establish: {rendered_caveat}")
        if excerpt:
            lines.append(f"  excerpt: {excerpt[:240].replace(chr(10), ' ')}")
    lines.append("")
    lines.append("Non-claims:")
    for item in pack.get("does_not_establish", []):
        lines.append(f"- {item}")
    return "\n".join(lines) + "\n"
