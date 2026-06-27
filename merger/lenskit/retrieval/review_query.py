"""Execution surface for the opt-in deterministic review-intent planner."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .query_core import execute_query, normalize_excluded_paths
from .review_router import plan_review_query


def _collect_unique_path_candidates(
    run_query: Callable[[int], Dict[str, Any]],
    *,
    target_unique_paths: int,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]], Dict[str, Any]]:
    """Collect ranked candidates until enough unique paths exist or results end.

    ``execute_query`` ranks chunks. A single large file can therefore occupy an
    initial chunk window many times. Review fusion ranks repository paths, so a
    fixed chunk overfetch is insufficient. This bounded-by-index loop doubles the
    requested chunk window until either the requested number of unique paths is
    available or the query returns fewer rows than requested, which proves that
    the matching result set is exhausted for this lane variant.
    """
    if target_unique_paths < 1:
        raise ValueError("target_unique_paths must be at least 1")

    fetch_k = target_unique_paths
    attempts = 0
    while True:
        attempts += 1
        output = run_query(fetch_k)
        unique_hits: List[Dict[str, Any]] = []
        seen_paths = set()
        for hit in output["results"]:
            path = hit["path"]
            if path in seen_paths:
                continue
            seen_paths.add(path)
            unique_hits.append(hit)
            if len(unique_hits) >= target_unique_paths:
                break

        exhausted = output["count"] < fetch_k
        if len(unique_hits) >= target_unique_paths or exhausted:
            return output, unique_hits, {
                "fetch_k": fetch_k,
                "attempts": attempts,
                "exhausted": exhausted,
                "returned_chunks": output["count"],
                "unique_paths": len(unique_hits),
            }

        fetch_k *= 2


def _fallback_to_legacy(
    *,
    index_path: Path,
    query_text: str,
    k: int,
    filters: Optional[Dict[str, Optional[str]]],
    explain: bool,
    excluded_paths: List[str],
    plan: Dict[str, Any],
) -> Dict[str, Any]:
    """Run the established query path and mark the review-plan fallback exactly."""
    output = execute_query(
        index_path=index_path,
        query_text=query_text,
        k=k,
        filters=filters,
        explain=explain,
        excluded_paths=excluded_paths,
    )
    executed_mode = output["query_mode"]
    output["engine"] = f"{output['engine']}+review_intent_fallback"
    output["query_mode"] = "review_intent_fallback"
    output["claim_boundaries"]["does_not_prove"].append(
        "Review-intent planning was requested but no executable review lane was produced."
    )
    if explain:
        explain_block = output.setdefault("explain", {})
        explain_block["review_intent_router"] = plan
        explain_block["review_intent_fallback"] = {
            "reason": "no_executable_review_lanes",
            "executed_query_mode": executed_mode,
            "fallback": "legacy",
        }
    return output


def execute_review_query(
    index_path: Path,
    query_text: str,
    k: int = 10,
    filters: Optional[Dict[str, Optional[str]]] = None,
    explain: bool = False,
    *,
    excluded_paths: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Execute an opt-in multi-lane review query."""
    if k < 1:
        raise ValueError("k must be at least 1")

    normalized_excluded_paths = normalize_excluded_paths(excluded_paths)
    active_filters = filters or {}
    plan = plan_review_query(query_text)
    if not plan["lanes"]:
        return _fallback_to_legacy(
            index_path=index_path,
            query_text=query_text,
            k=k,
            filters=filters,
            explain=explain,
            excluded_paths=normalized_excluded_paths,
            plan=plan,
        )

    # Preserve a broad per-lane path pool for fusion. Unlike the former hard
    # 200-chunk cap, this is a target number of unique paths; the collector may
    # inspect more chunks when one file dominates the ranking window.
    candidate_path_target = max(k * 5, 50)
    lane_results = []
    lane_summaries = []

    legacy_output, raw_legacy_hits, legacy_collection = _collect_unique_path_candidates(
        lambda fetch_k: execute_query(
            index_path=index_path,
            query_text=query_text,
            k=fetch_k,
            filters=filters,
            explain=False,
            excluded_paths=normalized_excluded_paths,
        ),
        target_unique_paths=candidate_path_target,
    )
    legacy_hits = []
    for hit in raw_legacy_hits:
        cloned = copy.deepcopy(hit)
        diagnostics = cloned["why"].setdefault("diagnostics", {})
        diagnostics["review_intent"] = {
            "plan_version": plan["version"],
            "lane": "legacy",
            "variant": "legacy_router",
            "lane_rank": len(legacy_hits) + 1,
            "fts_query": legacy_output.get("fts_query", ""),
        }
        legacy_hits.append(cloned)
    lane_results.append(("legacy", legacy_hits))
    lane_summaries.append(
        {
            "name": "legacy",
            "variant_counts": {"legacy_router": legacy_output["count"]},
            "variant_collection": {"legacy_router": legacy_collection},
            "unique_path_candidates": len(legacy_hits),
        }
    )

    for lane in plan["lanes"]:
        lane_hits = []
        seen_lane_paths = set()
        variant_counts: Dict[str, int] = {}
        variant_collection: Dict[str, Dict[str, Any]] = {}
        variants = [("strict", lane["strict_fts_query"])]
        relaxed_query = lane.get("relaxed_fts_query")
        if relaxed_query:
            variants.append(("relaxed", relaxed_query))

        for variant_name, fts_query in variants:
            lane_output, variant_hits, collection = _collect_unique_path_candidates(
                lambda fetch_k, fts_query=fts_query, variant_name=variant_name: execute_query(
                    index_path=index_path,
                    query_text=query_text,
                    k=fetch_k,
                    filters=filters,
                    explain=False,
                    overmatch_guard=True,
                    excluded_paths=normalized_excluded_paths,
                    _prepared_fts_query=fts_query,
                    _prepared_router_output={
                        "mode": "review_intent.v1",
                        "lane": lane["name"],
                        "variant": variant_name,
                    },
                ),
                target_unique_paths=candidate_path_target,
            )
            variant_counts[variant_name] = lane_output["count"]
            variant_collection[variant_name] = collection
            for hit in variant_hits:
                path = hit["path"]
                if path in seen_lane_paths:
                    continue
                seen_lane_paths.add(path)
                cloned = copy.deepcopy(hit)
                diagnostics = cloned["why"].setdefault("diagnostics", {})
                diagnostics["review_intent"] = {
                    "plan_version": plan["version"],
                    "lane": lane["name"],
                    "variant": variant_name,
                    "lane_rank": len(lane_hits) + 1,
                    "fts_query": fts_query,
                }
                lane_hits.append(cloned)
                if len(lane_hits) >= candidate_path_target:
                    break
            if len(lane_hits) >= candidate_path_target:
                break

        lane_results.append((lane["name"], lane_hits))
        lane_summaries.append(
            {
                "name": lane["name"],
                "variant_counts": variant_counts,
                "variant_collection": variant_collection,
                "unique_path_candidates": len(lane_hits),
            }
        )

    selected = []
    selected_paths = set()
    max_lane_length = max((len(hits) for _, hits in lane_results), default=0)
    for lane_rank in range(max_lane_length):
        for lane_name, hits in lane_results:
            if lane_rank >= len(hits):
                continue
            hit = hits[lane_rank]
            if hit["path"] in selected_paths:
                continue
            selected_paths.add(hit["path"])
            global_rank = len(selected) + 1
            hit["final_score"] = 1.0 / global_rank
            rank_features = hit["why"].setdefault("rank_features", {})
            rank_features["review_fusion_rank"] = global_rank
            rank_features["review_lane_rank"] = lane_rank + 1
            diagnostics = hit["why"].setdefault("diagnostics", {})
            review_diag = diagnostics["review_intent"]
            review_diag["selected_from_lane"] = lane_name
            review_diag["fusion_method"] = "round_robin_unique_path"
            selected.append(hit)
            if len(selected) >= k:
                break
        if len(selected) >= k:
            break

    output: Dict[str, Any] = {
        "query": query_text,
        "k": k,
        "engine": "fts5+review_intent_v1",
        "query_mode": "review_intent",
        "applied_filters": active_filters,
        "count": len(selected),
        "results": selected,
    }
    if normalized_excluded_paths:
        output["applied_exclusions"] = {
            "paths": normalized_excluded_paths,
            "match": "exact_repository_path",
            "application": "before_order_by_and_limit_per_lane",
        }
    if len(selected) < (k / 2.0):
        output["warnings"] = ["Low result coverage"]

    evidence_basis = ["query", "applied_filters", "index"]
    if any("range_ref" in hit or "derived_range_ref" in hit for hit in selected):
        evidence_basis.append("result_ranges")
    if normalized_excluded_paths:
        evidence_basis.append("path_exclusions")
    output["claim_boundaries"] = {
        "proves": [
            "These hits were selected deterministically from this index under "
            "the declared opt-in review-intent plan."
        ],
        "does_not_prove": [
            "A returned artifact is not established as relevant or correct.",
            "Role-lane coverage does not prove review completeness.",
            "Absence of a lane hit does not prove repository absence.",
            "Goldset improvement does not prove improvement for unmeasured queries.",
            "This opt-in result does not establish readiness for default promotion.",
            "Snapshot query does not prove live repository state.",
        ],
        "evidence_basis": evidence_basis,
        "requires_live_check": True,
    }

    if explain:
        explain_block: Dict[str, Any] = {
            "filters": {key: value for key, value in active_filters.items() if value},
            "review_intent_router": plan,
            "lanes": lane_summaries,
            "fusion": {
                "method": "round_robin_unique_path",
                "candidate_unique_paths_per_lane": candidate_path_target,
                "lane_order": [name for name, _ in lane_results],
                "selected_paths": [hit["path"] for hit in selected],
            },
        }
        if normalized_excluded_paths:
            explain_block["excluded_paths"] = normalized_excluded_paths
        if selected:
            explain_block["top_k_scoring"] = [
                {"chunk_id": hit["chunk_id"], "score": hit["final_score"]}
                for hit in selected
            ]
        else:
            explain_block["why_zero"] = "no review-intent lane results"
        output["explain"] = explain_block

    return output
