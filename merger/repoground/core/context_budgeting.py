"""Deterministic relevance-aware budgeting for RepoGround context candidates.

The selector is deliberately independent from retrieval production. It consumes
already bounded, evidence-bearing candidates and allocates a hard byte and token
budget using explicit relevance, change-proximity, authority and diversity
signals. Scores are navigation diagnostics only and never establish truth,
completeness, correctness or merge readiness.
"""

from __future__ import annotations

import math
from pathlib import PurePosixPath
from typing import Any, Mapping, Sequence

DEFAULT_WEIGHTS = {
    "relevance": 0.45,
    "change_proximity": 0.25,
    "evidence_authority": 0.20,
    "coverage_diversity": 0.10,
}

_SOURCE_BASE_PRIORITY = {
    "changed_path": 5,
    "resolved_evidence": 10,
    "python_symbol_index_json": 20,
    "relation_cards_jsonl": 25,
    "required_reading": 30,
}


def normalize_changed_paths(changed_paths: Sequence[str] | None) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in changed_paths or ():
        if not isinstance(raw, str):
            raise ValueError("changed_paths entries must be strings")
        normalized = raw.strip().replace("\\", "/").lstrip("./")
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _candidate_path(candidate: Mapping[str, Any]) -> str | None:
    for key in ("path", "source_path", "target_path"):
        value = candidate.get(key)
        if isinstance(value, str) and value:
            return value.replace("\\", "/").lstrip("./")
    return None


def _change_proximity(
    path: str | None, changed_paths: Sequence[str]
) -> tuple[float, str]:
    if not path or not changed_paths:
        return 0.0, "no_changed_path_match"
    candidate = PurePosixPath(path)
    best = 0.0
    reason = "no_changed_path_match"
    for changed in changed_paths:
        changed_path = PurePosixPath(changed)
        if candidate == changed_path:
            return 1.0, "exact_changed_path"
        if candidate in changed_path.parents or changed_path in candidate.parents:
            if best < 0.75:
                best, reason = 0.75, "changed_path_ancestor_or_descendant"
            continue
        common = 0
        for left, right in zip(candidate.parts, changed_path.parts):
            if left != right:
                break
            common += 1
        if common and best < 0.35:
            best, reason = 0.35, "shared_changed_path_prefix"
    return best, reason


def _flatten_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value.casefold()]
    if isinstance(value, Mapping):
        result: list[str] = []
        for key, item in value.items():
            if key in {
                "declared_authority",
                "canonicality",
                "trust_class",
                "authority",
            }:
                result.extend(_flatten_strings(item))
            elif isinstance(item, Mapping):
                result.extend(_flatten_strings(item))
        return result
    return []


def _authority_score(candidate: Mapping[str, Any]) -> tuple[float, str]:
    values = _flatten_strings(candidate.get("trust")) + _flatten_strings(candidate)
    joined = " ".join(values)
    if any(
        token in joined
        for token in ("canonical_content", "content_source", "canonical")
    ):
        return 1.0, "canonical_content"
    if "raw_repository_content" in joined:
        return 0.9, "raw_repository_content"
    if any(token in joined for token in ("navigation_index", "manifest_projection")):
        return 0.7, "navigation_or_manifest_index"
    if any(
        token in joined
        for token in ("derived", "static_analysis", "generated_artifact")
    ):
        return 0.55, "derived_navigation"
    return 0.4, "authority_unspecified"


def _relevance_score(candidate: Mapping[str, Any]) -> tuple[float, int]:
    source = str(candidate.get("source") or "")
    priority = candidate.get("priority")
    priority_value = (
        priority
        if isinstance(priority, int) and not isinstance(priority, bool)
        else 100
    )
    base = _SOURCE_BASE_PRIORITY.get(source, 50)
    ordinal = max(priority_value - base, 0)
    if source == "changed_path":
        return 1.0, ordinal
    if source == "required_reading":
        return max(0.2, 0.55 / (1.0 + ordinal)), ordinal
    return max(0.1, 1.0 / (1.0 + ordinal)), ordinal


def _diversity_keys(candidate: Mapping[str, Any]) -> tuple[str, str]:
    source = str(candidate.get("source") or "unknown")
    path = _candidate_path(candidate)
    if not path:
        return source, "<no-path>"
    parts = PurePosixPath(path).parts
    group = "/".join(parts[:2]) if len(parts) >= 2 else path
    return source, group


def _estimated_bytes(candidate: Mapping[str, Any], bytes_per_token: float) -> int:
    explicit = candidate.get("estimated_bytes")
    if isinstance(explicit, int) and not isinstance(explicit, bool) and explicit > 0:
        return explicit
    tokens = candidate.get("estimated_tokens")
    token_count = (
        tokens
        if isinstance(tokens, int) and not isinstance(tokens, bool) and tokens > 0
        else 1
    )
    return max(1, int(math.ceil(token_count * bytes_per_token)))


def _validate_weights(weights: Mapping[str, float] | None) -> dict[str, float]:
    result = dict(DEFAULT_WEIGHTS)
    if weights is not None:
        unknown = sorted(set(weights) - set(DEFAULT_WEIGHTS))
        if unknown:
            raise ValueError("unknown context ranking weights: " + ", ".join(unknown))
        for key, value in weights.items():
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or value < 0
            ):
                raise ValueError(
                    f"context ranking weight {key} must be a non-negative number"
                )
            result[key] = float(value)
    total = sum(result.values())
    if total <= 0:
        raise ValueError("at least one context ranking weight must be positive")
    return {key: value / total for key, value in result.items()}


def _annotate_candidate(
    candidate: Mapping[str, Any],
    *,
    changed_paths: Sequence[str],
    bytes_per_token: float,
) -> dict[str, Any]:
    item = dict(candidate)
    path = _candidate_path(item)
    relevance, query_rank = _relevance_score(item)
    change_proximity, change_reason = _change_proximity(path, changed_paths)
    authority, authority_reason = _authority_score(item)
    source_key, path_key = _diversity_keys(item)
    item["estimated_bytes"] = _estimated_bytes(item, bytes_per_token)
    item["ranking_evidence"] = {
        "query_rank": query_rank,
        "relevance": round(relevance, 6),
        "change_proximity": round(change_proximity, 6),
        "change_proximity_reason": change_reason,
        "evidence_authority": round(authority, 6),
        "evidence_authority_reason": authority_reason,
        "diversity_source_key": source_key,
        "diversity_path_key": path_key,
    }
    return item


def select_relevance_budgeted_context(
    candidates: Sequence[Mapping[str, Any]],
    *,
    token_budget: int,
    byte_budget: int,
    bytes_per_token: float,
    changed_paths: Sequence[str] | None = None,
    weights: Mapping[str, float] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Select candidates under both hard budgets with deterministic evidence.

    Candidate generation may remain source-specific, but the final selector has
    no per-lane quota. Every candidate competes in one pool and changed-path
    candidates are scored explicitly rather than being silently hidden behind a
    source cap.
    """
    normalized_changed_paths = normalize_changed_paths(changed_paths)
    normalized_weights = _validate_weights(weights)
    remaining = [
        _annotate_candidate(
            candidate,
            changed_paths=normalized_changed_paths,
            bytes_per_token=bytes_per_token,
        )
        for candidate in candidates
    ]
    selected: list[dict[str, Any]] = []
    omitted: list[dict[str, Any]] = []
    used_tokens = 0
    used_bytes = 0
    selected_sources: set[str] = set()
    selected_path_groups: set[str] = set()

    while remaining:
        scored: list[tuple[float, int, int, str, dict[str, Any], float]] = []
        for item in remaining:
            evidence = item["ranking_evidence"]
            source_key = evidence["diversity_source_key"]
            path_key = evidence["diversity_path_key"]
            source_novelty = 1.0 if source_key not in selected_sources else 0.0
            path_novelty = 1.0 if path_key not in selected_path_groups else 0.0
            diversity = (source_novelty + path_novelty) / 2.0
            score = (
                normalized_weights["relevance"] * evidence["relevance"]
                + normalized_weights["change_proximity"] * evidence["change_proximity"]
                + normalized_weights["evidence_authority"]
                * evidence["evidence_authority"]
                + normalized_weights["coverage_diversity"] * diversity
            )
            tokens = item.get("estimated_tokens")
            token_count = (
                tokens
                if isinstance(tokens, int)
                and not isinstance(tokens, bool)
                and tokens > 0
                else 1
            )
            scored.append(
                (
                    -round(score, 12),
                    item["estimated_bytes"],
                    token_count,
                    str(item.get("id") or ""),
                    item,
                    diversity,
                )
            )
        scored.sort(key=lambda row: row[:4])
        _negative_score, estimated_bytes, token_count, _identifier, item, diversity = (
            scored[0]
        )
        remaining.remove(item)
        score = -_negative_score
        evidence = dict(item["ranking_evidence"])
        evidence["coverage_diversity"] = round(diversity, 6)
        evidence["selection_score"] = round(score, 6)
        item["ranking_evidence"] = evidence
        fits_tokens = used_tokens + token_count <= token_budget
        fits_bytes = used_bytes + estimated_bytes <= byte_budget
        if fits_tokens and fits_bytes:
            item.update(
                {
                    "selection_status": "selected",
                    "budget_before_tokens": used_tokens,
                    "budget_after_tokens": used_tokens + token_count,
                    "budget_before_bytes": used_bytes,
                    "budget_after_bytes": used_bytes + estimated_bytes,
                }
            )
            selected.append(item)
            used_tokens += token_count
            used_bytes += estimated_bytes
            selected_sources.add(evidence["diversity_source_key"])
            selected_path_groups.add(evidence["diversity_path_key"])
            continue

        if not fits_tokens:
            omission_reason = "estimated_tokens_exceed_remaining_budget"
        else:
            omission_reason = "estimated_bytes_exceed_remaining_budget"
        item.update(
            {
                "omission_constraints": {
                    "token_budget_exceeded": not fits_tokens,
                    "byte_budget_exceeded": not fits_bytes,
                },
                "selection_status": "omitted",
                "omission_reason": omission_reason,
                "budget_remaining_tokens": max(token_budget - used_tokens, 0),
                "budget_remaining_bytes": max(byte_budget - used_bytes, 0),
                "required_tokens": token_count,
                "required_bytes": estimated_bytes,
            }
        )
        omitted.append(item)

    trace = {
        "algorithm": "dynamic_weighted_greedy_v1",
        "one_shared_candidate_pool": True,
        "per_lane_selection_caps": False,
        "weights": normalized_weights,
        "changed_paths": normalized_changed_paths,
        "hard_budgets": {
            "tokens": token_budget,
            "bytes": byte_budget,
            "used_tokens": used_tokens,
            "used_bytes": used_bytes,
        },
        "tie_break": "selection_score_desc_then_estimated_bytes_then_estimated_tokens_then_id",
        "does_not_establish": [
            "semantic_truth",
            "retrieval_completeness",
            "repository_understanding",
            "test_sufficiency",
            "merge_readiness",
        ],
    }
    return selected, omitted, trace
