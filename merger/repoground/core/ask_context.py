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
        bounded_excerpt = _utf8_prefix(
            excerpt,
            max_bytes=fair_share,
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
        item.update(_source_address_fields(hit))
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
    relaxed_result = _run_query(manifest_path, query, k, prepared_fts_query=or_query)
    relaxed = _resolved_ranges_with_budget(
        relaxed_result,
        max_context_tokens,
        max_context_bytes=max_context_bytes,
    )
    if not relaxed[0]:
        return state
    (
        state["resolved_ranges"],
        state["used_bytes"],
        state["used_characters"],
        state["truncated"],
        state["omissions"],
    ) = relaxed
    state.update(
        {
            "query_result": relaxed_result,
            "retrieval_hits": _retrieval_hits(relaxed_result),
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
) -> list[dict[str, Any]]:
    caveats = list(freshness.get("caveats") or []) + list(
        availability.get("caveats") or []
    )
    if state["truncated"]:
        caveats.append(
            {
                "kind": "other",
                "detail": "Context excerpts were truncated to respect the hard UTF-8 byte budget.",
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
    elif not state["resolved_ranges"] and retrieval_infrastructure["index_resolved"]:
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

    retrieval = {
        "raw_query": query,
        "fts_query": state["fts_query"],
        "strategy": state["strategy"] if state["resolved_ranges"] else "none",
        "match_count": len(state["resolved_ranges"]),
    }

    retrieval_infrastructure = _retrieval_infrastructure_block(state["query_result"])
    availability = _retrieval_availability(availability, retrieval_infrastructure)
    caveats = _retrieval_caveats(
        freshness,
        availability,
        state=state,
        retrieval_infrastructure=retrieval_infrastructure,
        query=query,
    )
    language_context = _language_structure_for_query(
        manifest_path,
        query=query,
        k=k,
        max_bytes=max(0, total_context_bytes - state["used_bytes"]),
        preloaded=language_response,
    )
    structured_evidence = _merge_language_context(state, caveats, language_context)

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
