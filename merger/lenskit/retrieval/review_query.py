"""Execution surface for the opt-in deterministic review-intent planner."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Dict, List, Optional

from .query_core import execute_query, normalize_excluded_paths
from .review_router import plan_review_query


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
    if not query_text:
        return execute_query(
            index_path=index_path,
            query_text=query_text,
            k=k,
            filters=filters,
            explain=explain,
            excluded_paths=normalized_excluded_paths,
        )

    plan = plan_review_query(query_text)
    if not plan["lanes"]:
        return execute_query(
            index_path=index_path,
            query_text=query_text,
            k=k,
            filters=filters,
            explain=explain,
            excluded_paths=normalized_excluded_paths,
        )

    candidate_k = min(max(k * 5, 50), 200)
    lane_results = []
    lane_summaries = []

    legacy_output = execute_query(
        index_path=index_path,
        query_text=query_text,
        k=candidate_k,
        filters=filters,
        explain=False,
        excluded_paths=normalized_excluded_paths,
    )
    legacy_hits = []
    seen_legacy_paths = set()
    for hit in legacy_output["results"]:
        path = hit["path"]
        if path in seen_legacy_paths:
            continue
        seen_legacy_paths.add(path)
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
            "unique_path_candidates": len(legacy_hits),
        }
    )

    for lane in plan["lanes"]:
        lane_hits = []
        seen_lane_paths = set()
        variant_counts: Dict[str, int] = {}
        variants = [("strict", lane["strict_fts_query"])]
        relaxed_query = lane.get("relaxed_fts_query")
        if relaxed_query:
            variants.append(("relaxed", relaxed_query))

        for variant_name, fts_query in variants:
            lane_output = execute_query(
                index_path=index_path,
                query_text=query_text,
                k=candidate_k,
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
            )
            variant_counts[variant_name] = lane_output["count"]
            for hit in lane_output["results"]:
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
                if len(lane_hits) >= candidate_k:
                    break
            if len(lane_hits) >= candidate_k:
                break

        lane_results.append((lane["name"], lane_hits))
        lane_summaries.append(
            {
                "name": lane["name"],
                "variant_counts": variant_counts,
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
                "candidate_k_per_lane": candidate_k,
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
