"""Deterministic RepoBrief token-budget context compiler.

The compiler reads existing bundle artifacts only. It does not create snapshots,
refresh indexes, import target code, or write bundle artifacts. It ranks bounded
context candidates from resolved evidence, symbol navigation and required
reading, then selects as many as fit into a caller-supplied token budget.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Mapping

from merger.lenskit.core.graph_degradation import graph_gap_from_availability
from merger.lenskit.core.repobrief_access import (
    query_existing_index,
    resolve_required_reading_for_bundle,
    search_symbol_index,
    snapshot_status,
)

KIND = "repobrief.context_compiler"
VERSION = "v1"
MAX_CONTEXT_BUDGET_TOKENS = 1_000_000
MAX_SIGNAL_HITS = 50
DEFAULT_BYTES_PER_TOKEN = 4.0

DOES_NOT_ESTABLISH = (
    "exact_token_count",
    "model_context_fit",
    "best_possible_context",
    "all_relevant_context_used",
    "answer_correctness",
    "repo_understood",
    "claims_true",
    "runtime_behavior",
    "test_sufficiency",
    "review_completeness",
    "merge_readiness",
    "agent_quality_improvement",
)


def _read_only_mutation_boundary() -> dict[str, Any]:
    return {
        "writes": [],
        "does_not_mutate": [
            "git",
            "pull_requests",
            "patches",
            "source_working_tree",
            "brief_bundle_artifacts",
            "latest_complete_registry",
        ],
        "read_paths_do_not_refresh": True,
    }


def _invalid_result(
    manifest_path: Path,
    *,
    error: str,
    error_code: str,
    task: str,
    task_profile: str,
    context_budget_tokens: Any,
) -> dict[str, Any]:
    return {
        "kind": KIND,
        "version": VERSION,
        "status": "invalid",
        "bundle_manifest": str(manifest_path),
        "task": task,
        "task_profile": task_profile,
        "context_budget_tokens": context_budget_tokens,
        "error": error,
        "error_code": error_code,
        "selected_context": [],
        "omitted_context": [],
        "gaps": [],
        "mutation_boundary": _read_only_mutation_boundary(),
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }


def _estimate_tokens_from_bytes(byte_count: Any, bytes_per_token: float) -> int:
    if isinstance(byte_count, bool) or not isinstance(byte_count, int) or byte_count <= 0:
        return 1
    return max(1, int(math.ceil(byte_count / bytes_per_token)))


def _estimate_tokens_from_text(text: Any, bytes_per_token: float) -> int:
    if not isinstance(text, str) or not text:
        return 1
    return max(1, int(math.ceil(len(text.encode("utf-8")) / bytes_per_token)))


def _compact_match_text(value: str) -> str:
    return "".join(ch for ch in value.casefold() if ch.isalnum())


def _artifact_by_role(status: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    artifacts = status.get("artifacts")
    if not isinstance(artifacts, list):
        return result
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        role = artifact.get("role")
        if isinstance(role, str) and role not in result:
            result[role] = artifact
    return result


def _candidate(
    *,
    candidate_id: str,
    source: str,
    priority: int,
    estimated_tokens: int,
    selection_reason: str,
    payload: dict[str, Any],
    citations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "id": candidate_id,
        "source": source,
        "priority": priority,
        "estimated_tokens": estimated_tokens,
        "selection_reason": selection_reason,
        "citations": citations or [],
        **payload,
    }


def _retrieval_candidates(
    manifest_path: Path,
    *,
    query: str,
    signal_k: int,
    bytes_per_token: float,
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    if not query.strip():
        return [], {"status": "skipped", "reason": "query_empty"}, []
    result = query_existing_index(
        manifest_path,
        query,
        k=signal_k,
        resolve_evidence=True,
        project_sources=True,
    )
    gaps: list[dict[str, Any]] = []
    if result.get("status") != "available":
        gaps.append({
            "source": "resolved_evidence",
            "status": result.get("status"),
            "error_code": result.get("error_code"),
            "reason": result.get("error") or "resolved evidence query unavailable",
        })
        return [], {"status": result.get("status"), "error_code": result.get("error_code")}, gaps

    projection = result.get("source_citation_projection")
    items = projection.get("items") if isinstance(projection, dict) else []
    candidates: list[dict[str, Any]] = []
    for ordinal, item in enumerate(items if isinstance(items, list) else []):
        if not isinstance(item, dict):
            continue
        text = item.get("text_excerpt")
        citation_id = item.get("citation_id") if isinstance(item.get("citation_id"), str) else None
        source_range = item.get("source_range") if isinstance(item.get("source_range"), dict) else None
        citation_range = item.get("citation_range") if isinstance(item.get("citation_range"), dict) else None
        citations = []
        if citation_id or source_range or citation_range:
            citations.append({
                "citation_id": citation_id,
                "source_range": source_range,
                "citation_range": citation_range,
                "range_status": item.get("range_status"),
                "citation_status": item.get("citation_status"),
                "live_repo_address": item.get("live_repo_address"),
            })
        token_estimate = _estimate_tokens_from_text(text, bytes_per_token)
        candidates.append(
            _candidate(
                candidate_id=f"resolved-evidence:{ordinal}",
                source="resolved_evidence",
                priority=10 + ordinal,
                estimated_tokens=token_estimate,
                selection_reason="query_match_with_resolved_range",
                citations=citations,
                payload={
                    "title": item.get("path") or item.get("chunk_id") or f"resolved evidence {ordinal}",
                    "artifact_role": "canonical_md",
                    "path": item.get("path"),
                    "chunk_id": item.get("chunk_id"),
                    "text_excerpt": text,
                    "text_truncated": item.get("text_truncated"),
                    "source_range": source_range,
                    "canonical_authority": item.get("canonical_authority"),
                },
            )
        )
    if not candidates:
        gaps.append({"source": "resolved_evidence", "status": "empty", "reason": "query returned no resolved source candidates"})
    signal = {
        "status": "available",
        "hit_count": len(candidates),
        "query_status": result.get("status"),
        "citation_projection_status": projection.get("status") if isinstance(projection, dict) else None,
    }
    return candidates, signal, gaps


def _symbol_candidates(
    manifest_path: Path,
    *,
    query: str,
    signal_k: int,
    bytes_per_token: float,
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    if not query.strip():
        return [], {"status": "skipped", "reason": "query_empty"}, []
    result = search_symbol_index(manifest_path, query, k=signal_k)
    if result.get("status") == "available" and result.get("hit_count") == 0:
        compact_query = _compact_match_text(query)
        if compact_query and compact_query != query.strip().casefold():
            compact_result = search_symbol_index(manifest_path, compact_query, k=signal_k)
            if compact_result.get("status") == "available" and compact_result.get("hit_count", 0) > 0:
                result = compact_result
    gaps: list[dict[str, Any]] = []
    if result.get("status") != "available":
        gaps.append({
            "source": "python_symbol_index_json",
            "status": result.get("status"),
            "error_code": result.get("error_code"),
            "reason": result.get("error") or "symbol index unavailable",
        })
        return [], {"status": result.get("status"), "error_code": result.get("error_code")}, gaps
    candidates: list[dict[str, Any]] = []
    for ordinal, hit in enumerate(result.get("hits") if isinstance(result.get("hits"), list) else []):
        if not isinstance(hit, dict):
            continue
        label = " ".join(
            str(hit.get(part, ""))
            for part in ("kind", "qualified_name", "path", "range_ref")
        )
        source_range = hit.get("source_range") if isinstance(hit.get("source_range"), dict) else None
        range_ref = hit.get("range_ref") if isinstance(hit.get("range_ref"), str) else None
        citations = [{"range_ref": range_ref, "source_range": source_range}] if range_ref or source_range else []
        candidates.append(
            _candidate(
                candidate_id=f"symbol:{ordinal}",
                source="python_symbol_index_json",
                priority=20 + ordinal,
                estimated_tokens=_estimate_tokens_from_text(label, bytes_per_token),
                selection_reason="symbol_name_or_path_match",
                citations=citations,
                payload={
                    "title": hit.get("qualified_name") or hit.get("name"),
                    "symbol": hit,
                    "path": hit.get("path"),
                    "source_range": source_range,
                },
            )
        )
    if not candidates:
        gaps.append({"source": "python_symbol_index_json", "status": "empty", "reason": "symbol search returned no candidates"})
    return candidates, {"status": "available", "hit_count": len(candidates)}, gaps



def _relation_path_value(value: Any) -> str | None:
    if isinstance(value, dict) and isinstance(value.get("path"), str):
        return value["path"]
    if isinstance(value, str):
        return value
    return None


def _relation_candidates(
    status: Mapping[str, Any],
    *,
    query: str,
    signal_k: int,
    bytes_per_token: float,
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    artifacts = _artifact_by_role(status)
    artifact = artifacts.get("relation_cards_jsonl")
    if not isinstance(artifact, dict) or not artifact.get("absolute_path"):
        return [], {"status": "missing", "error_code": "relation_cards_jsonl_missing"}, [{
            "source": "relation_cards_jsonl",
            "status": "missing",
            "error_code": "relation_cards_jsonl_missing",
            "reason": "relation_cards_jsonl artifact is not present in the bundle manifest",
        }]
    path = Path(str(artifact["absolute_path"]))
    if not path.is_file():
        return [], {"status": "missing", "error_code": "relation_cards_jsonl_file_missing"}, [{
            "source": "relation_cards_jsonl",
            "status": "missing",
            "error_code": "relation_cards_jsonl_file_missing",
            "reason": "relation_cards_jsonl artifact file does not exist",
        }]
    q = query.strip().casefold()
    candidates: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    try:
        rows = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        return [], {"status": "invalid", "error_code": "relation_cards_jsonl_unreadable"}, [{
            "source": "relation_cards_jsonl",
            "status": "invalid",
            "error_code": "relation_cards_jsonl_unreadable",
            "reason": str(exc),
        }]
    for row_number, line in enumerate(rows, start=1):
        if not line.strip():
            continue
        try:
            card = json.loads(line)
        except ValueError as exc:
            errors.append({"row": row_number, "error": str(exc)})
            continue
        if not isinstance(card, dict):
            errors.append({"row": row_number, "error": "row_not_object"})
            continue
        source_path = _relation_path_value(card.get("source"))
        target_path = _relation_path_value(card.get("target"))
        evidence = card.get("evidence") if isinstance(card.get("evidence"), dict) else {}
        haystack = " ".join(
            str(value)
            for value in (
                card.get("relation"),
                source_path,
                target_path,
                evidence.get("source_path"),
                evidence.get("start_line"),
                evidence.get("end_line"),
            )
        ).casefold()
        if q and q not in haystack:
            compact_query = _compact_match_text(q)
            compact_haystack = _compact_match_text(haystack)
            if not compact_query or compact_query not in compact_haystack:
                continue
        label = f"{source_path or '?'} -> {target_path or '?'} {card.get('relation') or ''}"
        candidates.append(
            _candidate(
                candidate_id=f"relation:{row_number}",
                source="relation_cards_jsonl",
                priority=25 + row_number,
                estimated_tokens=_estimate_tokens_from_text(label, bytes_per_token),
                selection_reason="relation_card_match",
                citations=[{
                    "artifact_role": "relation_cards_jsonl",
                    "source_path": source_path,
                    "target_path": target_path,
                    "evidence": evidence,
                    "evidence_level": card.get("evidence_level"),
                }],
                payload={
                    "title": label,
                    "artifact_role": "relation_cards_jsonl",
                    "path": source_path,
                    "relation": card.get("relation"),
                    "source_path": source_path,
                    "target_path": target_path,
                    "evidence": evidence,
                },
            )
        )
        if len(candidates) >= signal_k:
            break
    gaps: list[dict[str, Any]] = []
    if errors:
        gaps.append({"source": "relation_cards_jsonl", "status": "invalid_rows", "row_errors": errors[:10]})
    if not candidates:
        gaps.append({"source": "relation_cards_jsonl", "status": "empty", "reason": "relation card search returned no candidates"})
    signal_status = "warn" if errors else "available"
    return candidates, {"status": signal_status, "hit_count": len(candidates), "invalid_row_count": len(errors)}, gaps

def _required_reading_candidates(
    status: Mapping[str, Any],
    required_reading: Mapping[str, Any],
    *,
    bytes_per_token: float,
) -> list[dict[str, Any]]:
    artifacts = _artifact_by_role(status)
    candidates: list[dict[str, Any]] = []
    for group, base_priority, reason in (
        ("available_required", 30, "required_reading_role"),
        ("available_recommended", 60, "recommended_reading_role"),
    ):
        roles = required_reading.get(group)
        if not isinstance(roles, list):
            continue
        for ordinal, role in enumerate(str(role) for role in roles):
            artifact = artifacts.get(role)
            if role == "bundle_manifest":
                artifact = {
                    "role": "bundle_manifest",
                    "path": Path(str(status.get("bundle_manifest", "bundle_manifest"))).name,
                    "absolute_path": status.get("bundle_manifest"),
                    "bytes": None,
                    "authority": "navigation_index",
                    "canonicality": "derived",
                }
            if not isinstance(artifact, dict):
                continue
            candidates.append(
                _candidate(
                    candidate_id=f"artifact:{role}",
                    source="required_reading",
                    priority=base_priority + ordinal,
                    estimated_tokens=_estimate_tokens_from_bytes(artifact.get("bytes"), bytes_per_token),
                    selection_reason=reason,
                    citations=[{
                        "artifact_role": role,
                        "path": artifact.get("path"),
                        "authority": artifact.get("authority"),
                        "canonicality": artifact.get("canonicality"),
                    }],
                    payload={
                        "title": role,
                        "artifact_role": role,
                        "path": artifact.get("path"),
                        "absolute_path": artifact.get("absolute_path"),
                        "authority": artifact.get("authority"),
                        "canonicality": artifact.get("canonicality"),
                    },
                )
            )
    return candidates


def _dedupe_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[Any, Any, Any]] = set()
    result: list[dict[str, Any]] = []
    for candidate in sorted(candidates, key=lambda c: (c["priority"], c["estimated_tokens"], c["id"])):
        key = (candidate.get("source"), candidate.get("path"), candidate.get("title"))
        if key in seen:
            continue
        seen.add(key)
        result.append(candidate)
    return result


def _select_candidates(candidates: list[dict[str, Any]], budget: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    selected: list[dict[str, Any]] = []
    omitted: list[dict[str, Any]] = []
    used = 0
    for candidate in candidates:
        estimate = candidate["estimated_tokens"]
        if used + estimate <= budget:
            selected_item = {**candidate, "selection_status": "selected", "budget_before_tokens": used, "budget_after_tokens": used + estimate}
            selected.append(selected_item)
            used += estimate
        else:
            omitted.append({
                **candidate,
                "selection_status": "omitted",
                "omission_reason": "estimated_tokens_exceed_remaining_budget",
                "budget_remaining_tokens": max(budget - used, 0),
            })
    return selected, omitted


def compile_context_plan(
    bundle_manifest: str | Path,
    *,
    task: str,
    task_profile: str = "basic_repo_question",
    context_budget_tokens: int = 8_000,
    query: str | None = None,
    signal_k: int = 10,
    bytes_per_token: float = DEFAULT_BYTES_PER_TOKEN,
) -> dict[str, Any]:
    manifest_path = Path(bundle_manifest).expanduser().resolve()
    if not isinstance(task, str) or not task.strip():
        return _invalid_result(manifest_path, error="task must be a non-empty string", error_code="task_invalid", task=str(task), task_profile=task_profile, context_budget_tokens=context_budget_tokens)
    if not isinstance(task_profile, str) or not task_profile.strip():
        return _invalid_result(manifest_path, error="task_profile must be a non-empty string", error_code="task_profile_invalid", task=task, task_profile=str(task_profile), context_budget_tokens=context_budget_tokens)
    if not isinstance(context_budget_tokens, int) or isinstance(context_budget_tokens, bool) or context_budget_tokens < 1 or context_budget_tokens > MAX_CONTEXT_BUDGET_TOKENS:
        return _invalid_result(manifest_path, error=f"context_budget_tokens must be an integer between 1 and {MAX_CONTEXT_BUDGET_TOKENS}", error_code="context_budget_out_of_bounds", task=task, task_profile=task_profile, context_budget_tokens=context_budget_tokens)
    if not isinstance(signal_k, int) or isinstance(signal_k, bool) or signal_k < 1 or signal_k > MAX_SIGNAL_HITS:
        return _invalid_result(manifest_path, error=f"signal_k must be an integer between 1 and {MAX_SIGNAL_HITS}", error_code="signal_k_out_of_bounds", task=task, task_profile=task_profile, context_budget_tokens=context_budget_tokens)
    if not isinstance(bytes_per_token, (int, float)) or isinstance(bytes_per_token, bool) or bytes_per_token <= 0:
        return _invalid_result(manifest_path, error="bytes_per_token must be a number greater than 0", error_code="bytes_per_token_invalid", task=task, task_profile=task_profile, context_budget_tokens=context_budget_tokens)
    bytes_per_token = float(bytes_per_token)

    effective_query = query if isinstance(query, str) and query.strip() else task
    try:
        status = snapshot_status(manifest_path)
        required_resolution = resolve_required_reading_for_bundle(manifest_path, task_profile)
    except ValueError as exc:
        return _invalid_result(manifest_path, error=str(exc), error_code="bundle_manifest_invalid", task=task, task_profile=task_profile, context_budget_tokens=context_budget_tokens)

    required = required_resolution.get("required_reading") if isinstance(required_resolution.get("required_reading"), dict) else {}
    gaps: list[dict[str, Any]] = []
    if required.get("status") in {"fail", "not_applicable"}:
        gaps.append({
            "source": "required_reading",
            "status": required.get("status"),
            "missing_required": required.get("missing_required"),
            "reason": "required reading is not fully available",
        })
    elif required.get("missing_recommended"):
        gaps.append({
            "source": "required_reading",
            "status": "warn",
            "missing_recommended": required.get("missing_recommended"),
            "reason": "recommended reading is not fully available",
        })

    availability = status.get("availability_model") if isinstance(status.get("availability_model"), dict) else {}
    freshness = availability.get("freshness") if isinstance(availability, dict) else None
    graph_availability = availability.get("graph_availability") if isinstance(availability, dict) else None
    if isinstance(freshness, dict) and freshness.get("status") not in {"fresh", "not_comparable"}:
        gaps.append({"source": "freshness", "status": freshness.get("status"), "reason": freshness.get("reason")})
    if isinstance(graph_availability, dict) and graph_availability.get("status") != "available":
        gaps.append(graph_gap_from_availability("graph_availability", graph_availability))

    retrieval_candidates, retrieval_signal, retrieval_gaps = _retrieval_candidates(
        manifest_path,
        query=effective_query,
        signal_k=signal_k,
        bytes_per_token=bytes_per_token,
    )
    symbol_candidates, symbol_signal, symbol_gaps = _symbol_candidates(
        manifest_path,
        query=effective_query,
        signal_k=signal_k,
        bytes_per_token=bytes_per_token,
    )
    relation_candidates, relation_signal, relation_gaps = _relation_candidates(
        status,
        query=effective_query,
        signal_k=signal_k,
        bytes_per_token=bytes_per_token,
    )
    gaps.extend(retrieval_gaps)
    gaps.extend(symbol_gaps)
    gaps.extend(relation_gaps)

    required_candidates = _required_reading_candidates(
        status,
        required,
        bytes_per_token=bytes_per_token,
    )
    all_candidates = _dedupe_candidates(retrieval_candidates + symbol_candidates + relation_candidates + required_candidates)
    selected, omitted = _select_candidates(all_candidates, context_budget_tokens)

    used_tokens = sum(item["estimated_tokens"] for item in selected)
    candidate_counts: dict[str, int] = {}
    selected_counts: dict[str, int] = {}
    for candidate in all_candidates:
        source = str(candidate.get("source"))
        candidate_counts[source] = candidate_counts.get(source, 0) + 1
    for candidate in selected:
        source = str(candidate.get("source"))
        selected_counts[source] = selected_counts.get(source, 0) + 1

    fallback_roles = [
        item for item in selected + omitted
        if item.get("source") == "required_reading" and item.get("artifact_role") in {"canonical_md", "agent_reading_pack", "bundle_manifest"}
    ]
    status_value = "pass"
    if not selected or required.get("status") in {"fail", "not_applicable"}:
        status_value = "fail"
    elif gaps or omitted:
        status_value = "warn"

    return {
        "kind": KIND,
        "version": VERSION,
        "status": status_value,
        "bundle_manifest": str(manifest_path),
        "bundle_run_id": status.get("bundle_run_id"),
        "task": task,
        "task_profile": task_profile,
        "query": effective_query,
        "budget": {
            "context_budget_tokens": context_budget_tokens,
            "estimated_used_tokens": used_tokens,
            "estimated_remaining_tokens": max(context_budget_tokens - used_tokens, 0),
            "bytes_per_token": bytes_per_token,
            "exact_tokenizer": False,
        },
        "signals": {
            "resolved_evidence": retrieval_signal,
            "python_symbol_index_json": symbol_signal,
            "relation_cards_jsonl": relation_signal,
            "required_reading": {
                "status": required.get("status"),
                "required": required.get("required"),
                "recommended": required.get("recommended"),
                "missing_required": required.get("missing_required"),
                "missing_recommended": required.get("missing_recommended"),
            },
            "availability": {
                "status": availability.get("status") if isinstance(availability, dict) else None,
                "freshness": freshness,
                "graph_availability": graph_availability,
            },
        },
        "candidate_count": len(all_candidates),
        "selected_count": len(selected),
        "omitted_count": len(omitted),
        "candidate_counts_by_source": candidate_counts,
        "selected_counts_by_source": selected_counts,
        "selected_context": selected,
        "omitted_context": omitted,
        "fallback_context": {
            "available": bool(fallback_roles),
            "roles": fallback_roles,
            "reason": "required reading canonical/front-door roles remain available as fallback when retrieval, graph or symbol signals are missing",
        },
        "gaps": gaps,
        "selection_trace": {
            "ordering": "priority_then_estimated_tokens_then_id",
            "priority_bands": [
                {"source": "resolved_evidence", "priority": "10-19"},
                {"source": "python_symbol_index_json", "priority": "20-29"},
                {"source": "relation_cards_jsonl", "priority": "25+"},
                {"source": "required_reading", "priority": "30+ required, 60+ recommended"},
            ],
            "omission_reasons": sorted({item.get("omission_reason") for item in omitted if item.get("omission_reason")}),
        },
        "mutation_boundary": _read_only_mutation_boundary(),
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }
