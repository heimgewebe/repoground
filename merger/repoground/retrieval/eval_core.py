import re
import sys
import json
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

from .query_core import execute_query, normalize_excluded_paths
from .review_query import execute_review_query

WHY_FAIL_QUERY_EXECUTION = "query execution failed"
WHY_FAIL_MISSING_EXPLAIN = "missing explain from query execution"


def classify_miss(query_case: Dict[str, Any], expected_paths: List[str], is_relevant: bool, found_count: int, top_results: List[str]) -> Tuple[List[str], Optional[str]]:
    """
    Classify a retrieval miss mechanically.
    
        Returns:
            (miss_types: List[str], primary_miss_type: Optional[str])
    
    Miss types are conservative and diagnostic only:
    - Do not prove repository absence
    - Do not prove claim truth/falsity
    - Classify based on available mechanical signals only
    """
    explain = query_case.get("explain", {}) if isinstance(query_case, dict) else {}
    why = query_case.get("why", {}) if isinstance(query_case, dict) else {}
    has_query_execution_error = bool(query_case.get("error")) or explain.get("why_fail") == WHY_FAIL_QUERY_EXECUTION or why.get("why_fail") == WHY_FAIL_QUERY_EXECUTION
    if has_query_execution_error:
        return ["query_execution_error"], "query_execution_error"

    if is_relevant:
        return [], None
    
    miss_types = []
    
    # Zero results: query returned nothing
    if found_count == 0:
        miss_types.append("zero_results")
    # Expected paths provided but not in results: expected not in top-k
    elif expected_paths and top_results:
        # Check if any expected path substring is in top results
        found_expected = False
        for result_path in top_results:
            for exp_pattern in expected_paths:
                if exp_pattern in result_path:
                    found_expected = True
                    break
            if found_expected:
                break
        
        if not found_expected:
            miss_types.append("expected_not_in_top_k")
    # Missing metadata for classification
    elif not expected_paths:
        miss_types.append("path_or_symbol_metadata_missing")
    
    # Fallback: ensure at least one miss type is always returned for miss cases
    if not miss_types:
        miss_types.append("unknown")
    
    primary_miss_type = miss_types[0]
    
    return miss_types, primary_miss_type


def build_miss_taxonomy(results_detail: List[Dict[str, Any]], is_stale: bool) -> Dict[str, Any]:
    """
    Build the miss taxonomy from evaluation results.
    
    This is a diagnostic classification layer that explains why retrievals failed.
    It does NOT prove repository absence or claim semantic truth.
    """
    taxonomy = {
        "version": "1.0",
        "authority": "diagnostic_signal",
        "risk_class": "diagnostic",
        "classification_basis": [
            "retrieval_eval_expectations",
            "returned_hit_paths",
            "query_metadata"
        ],
        "does_not_prove": [
            "absence_of_retrieval_hit_does_not_prove_absence_in_repository",
            "miss_type_does_not_prove_claim_truth_or_falsehood",
            "ranking_position_does_not_prove_semantic_importance",
            "retrieval_eval_does_not_prove_retrieval_completeness",
            "taxonomy_is_diagnostic_not_authoritative"
        ],
        "aggregate": {
            "total_cases_classified": 0,
            "total_misses": 0,
            "by_type": {
                "zero_results": 0,
                "expected_not_in_top_k": 0,
                "expected_rank_below_k": 0,
                "expected_path_not_indexed": 0,
                "expected_symbol_not_indexed": 0,
                "path_or_symbol_metadata_missing": 0,
                "possible_query_vocabulary_gap": 0,
                "possible_filter_scope_gap": 0,
                "noise_or_fixture_hit": 0,
                "stale_eval_input": 0,
                "query_execution_error": 0,
                "unknown": 0
            }
        },
        "cases": []
    }
    
    for query_index, detail in enumerate(results_detail):
        is_relevant = detail.get("is_relevant", False)
        found_count = detail.get("found_count", 0)
        top_results = detail.get("top_results", [])
        expected = detail.get("expected", [])
        query_text = detail.get("query", "")
        explain = detail.get("explain", {}) if isinstance(detail, dict) else {}
        why = detail.get("why", {}) if isinstance(detail, dict) else {}
        is_query_execution_error = bool(detail.get("error")) or explain.get("why_fail") == WHY_FAIL_QUERY_EXECUTION or why.get("why_fail") == WHY_FAIL_QUERY_EXECUTION
        
        miss_types, primary_miss_type = classify_miss(detail, expected, is_relevant, found_count, top_results)
        
        taxonomy["aggregate"]["total_cases_classified"] += 1
        
        # Only record misses in cases
        if not is_relevant or is_query_execution_error:
            taxonomy["aggregate"]["total_misses"] += 1

            if is_stale and "stale_eval_input" not in miss_types:
                miss_types.append("stale_eval_input")
                if primary_miss_type is None:
                    primary_miss_type = "stale_eval_input"
            
            # Update aggregate counts
            for miss_type in miss_types:
                if miss_type in taxonomy["aggregate"]["by_type"]:
                    taxonomy["aggregate"]["by_type"][miss_type] += 1
            
            case_entry = {
                "query_index": query_index,
                "query": query_text,
                "expected": expected,
                "is_relevant": is_relevant,
                "observed_top_k_count": found_count,
                "miss_types": miss_types,
                "primary_miss_type": primary_miss_type or "unknown",
                "classification_basis": taxonomy["classification_basis"].copy()
            }
            
            # Add optional notes if staleness is a factor
            if is_stale:
                case_entry["notes"] = ["eval marked stale; may affect classification"]
            
            taxonomy["cases"].append(case_entry)
    
    return taxonomy

RE_MD_QUERY_TITLE = re.compile(r"^\d+\.\s+\*\*\"(.+?)\"\*\*")
RE_CLEAN_MD_LINE = re.compile(r"^[\s*+\-]+")
RE_EXPECTED_LABEL = re.compile(r"^\*?Expected:?\*?", re.IGNORECASE)
RE_CODE_TICKS = re.compile(r"`([^`]+)`")
RE_CATEGORY_LABEL = re.compile(r"^\*?Category:?\*?\s*(.+)$", re.IGNORECASE)
RE_FILTER_LABEL = re.compile(r"^\*?Filter:?\*?", re.IGNORECASE)
RE_FILTER_KV = re.compile(r"(?:`|)?([\w.-]+)=([\w/.-]+)(?:`|)?")

def parse_gold_queries(md_path: Path) -> List[Dict[str, Any]]:
    if not md_path.exists():
        raise FileNotFoundError(f"Queries file not found: {md_path}")

    content = md_path.read_text(encoding="utf-8")

    if md_path.suffix == ".json":
        try:
            data = json.loads(content)
            queries = []
            for item in data:
                queries.append({
                    "query": item.get("query", ""),
                    "category": item.get("category"),
                    "expected_paths": item.get("expected_patterns", []),
                    "filters": item.get("filters", {}),
                    "accept_criteria": item.get("accept_criteria", {})
                })
            return queries
        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse JSON queries file: {e}")

    queries = []
    current_query = None

    lines = content.splitlines()
    for line in lines:
        line = line.strip()
        if not line:
            continue

        m_title = RE_MD_QUERY_TITLE.match(line)
        if m_title:
            if current_query:
                queries.append(current_query)
            current_query = {
                "query": m_title.group(1),
                "category": None,
                "expected_paths": [],
                "filters": {},
                "accept_criteria": {}
            }
            continue

        if not current_query:
            continue

        clean_line = RE_CLEAN_MD_LINE.sub("", line).strip()

        if RE_EXPECTED_LABEL.match(clean_line):
            expected_terms = RE_CODE_TICKS.findall(line)
            current_query["expected_paths"].extend(expected_terms)

        m_category = RE_CATEGORY_LABEL.match(clean_line)
        if m_category:
            current_query["category"] = m_category.group(1).strip()
            continue

        if RE_FILTER_LABEL.match(clean_line):
            parts = clean_line.split(":", 1)
            if len(parts) > 1:
                rest = parts[1]
                matches = RE_FILTER_KV.findall(rest)
                for k, v in matches:
                    current_query["filters"][k] = v

    if current_query:
        queries.append(current_query)

    return queries

def evaluate_single_run(
    q_text: str,
    filters: Dict[str, str],
    expected: List[str],
    index_path: Path,
    k: int,
    embedding_policy: Optional[Dict[str, Any]],
    graph_index_path: Optional[Path],
    graph_weights: Optional[Dict[str, float]],
    *,
    excluded_paths: Optional[List[str]] = None,
    review_intent: bool = False,
) -> Tuple[bool, str, Optional[Dict[str, Any]], List[str], int, float, Dict[str, Any]]:
    if review_intent:
        if embedding_policy is not None or graph_index_path is not None:
            raise ValueError(
                "review_intent evaluation does not support semantic or graph comparison"
            )
        res = execute_review_query(
            index_path=index_path,
            query_text=q_text,
            k=k,
            filters=filters,
            explain=True,
            excluded_paths=excluded_paths,
        )
    else:
        res = execute_query(
            index_path=index_path,
            query_text=q_text,
            k=k,
            filters=filters,
            embedding_policy=embedding_policy,
            explain=True,
            graph_index_path=graph_index_path,
            graph_weights=graph_weights,
            excluded_paths=excluded_paths,
        )

    is_relevant = False
    top_match = "-"
    hit_why = None
    found_paths = [r["path"] for r in res["results"]]
    rr = 0.0

    for idx, r in enumerate(res["results"]):
        hit_path = r["path"]
        for exp in expected:
            if exp in hit_path:
                if not is_relevant:
                    is_relevant = True
                    top_match = hit_path
                    hit_why = r.get("why")
                    rr = 1.0 / (idx + 1)
                break
        if is_relevant:
            break

    return is_relevant, top_match, hit_why, found_paths, res["count"], rr, res


def do_eval(
    index_path: Path,
    queries_path: Path,
    k: int,
    is_json_mode: bool = False,
    is_stale: bool = False,
    embedding_policy: Optional[Dict[str, Any]] = None,
    graph_index_path: Optional[Path] = None,
    graph_weights: Optional[Dict[str, float]] = None,
    *,
    excluded_paths: Optional[List[str]] = None,
    review_intent: bool = False,
) -> Optional[Dict[str, Any]]:
    """
    Executes a benchmark evaluation of the retrieval system against gold queries.

    When `embedding_policy` is provided (Compare Mode):
    - The system runs each query twice: once as a pure lexical baseline, and once utilizing the semantic reranker.
    - If the semantic pipeline raises an exception (even if `fallback_behavior="fail"`),
      the exception is trapped and isolated.
    - The evaluation script will NOT abort. The lexical baseline data remains preserved,
      and the semantic error string is explicitly logged within the `semantic.error` block of the JSON output.
    """
    normalized_excluded_paths = normalize_excluded_paths(excluded_paths)
    if review_intent and (
        embedding_policy is not None or graph_index_path is not None
    ):
        raise ValueError(
            "review_intent evaluation does not support semantic or graph comparison"
        )

    try:
        gold_queries = parse_gold_queries(queries_path)
    except Exception as e:
        print(f"Error parsing queries file: {e}", file=sys.stderr)
        return None

    if not gold_queries:
        print("No queries found in input file.", file=sys.stderr)
        return None

    compare_mode = (embedding_policy is not None) or (graph_index_path is not None)
    if embedding_policy is not None and graph_index_path is not None:
        compare_type = "sem_graph"
        compare_label = "Sem+Graph"
    elif embedding_policy is not None:
        compare_type = "semantic"
        compare_label = "Semantic"
    elif graph_index_path is not None:
        compare_type = "graph"
        compare_label = "Graph"
    else:
        compare_type = "none"
        compare_label = "None"

    if not is_json_mode:
        print(f"Running Eval on {len(gold_queries)} queries against {index_path.name}...")
        print("-" * 80 if compare_mode else "-" * 60)
        if compare_mode:
            print(f"{'Query':<35} | {'Base (RR / Match)':<25} | {compare_label + ' (RR / Match)':<25}")
        else:
            print(f"{'Query':<40} | {'Found':<5} | {'Rel?':<4} | {'Top-1 Match':<30}")
        print("-" * 80 if compare_mode else "-" * 60)

    base_hits_at_k = 0
    base_mrr_sum = 0.0
    sem_hits_at_k = 0
    sem_mrr_sum = 0.0
    zero_hit_count = 0
    total_queries = len(gold_queries)
    results_detail = []
    category_stats: Dict[str, Dict[str, Any]] = {}
    graph_index_used = False
    review_intent_executed_queries = 0
    review_intent_fallback_queries = 0
    review_intent_error_queries = 0

    for q in gold_queries:
        q_text = q["query"]
        category = q.get("category")
        filters = q["filters"]
        expected = q["expected_paths"]

        cat_key = category if category else "uncategorized"
        if cat_key not in category_stats:
            category_stats[cat_key] = {"total_queries": 0, "base_hits": 0, "base_mrr_sum": 0.0, "sem_hits": 0, "sem_mrr_sum": 0.0}
        category_stats[cat_key]["total_queries"] += 1

        try:
            # Baseline run (no embedding policy)
            b_rel, b_match, b_why, b_paths, b_count, b_rr, b_res = evaluate_single_run(
                q_text,
                filters,
                expected,
                index_path,
                k,
                None,
                None,
                graph_weights,
                excluded_paths=normalized_excluded_paths,
                review_intent=review_intent,
            )
            if review_intent:
                if b_res.get("query_mode") == "review_intent":
                    review_intent_executed_queries += 1
                else:
                    review_intent_fallback_queries += 1

            s_rel, s_match, s_why, s_paths, s_count, s_rr, s_res = False, "-", None, [], 0, 0.0, {}
            sem_error_str = None
            if compare_mode:
                try:
                    # Semantic run
                    s_rel, s_match, s_why, s_paths, s_count, s_rr, s_res = evaluate_single_run(
                        q_text,
                        filters,
                        expected,
                        index_path,
                        k,
                        embedding_policy,
                        graph_index_path,
                        graph_weights,
                        excluded_paths=normalized_excluded_paths,
                        review_intent=review_intent,
                    )
                    if "graph_index" in s_res.get("claim_boundaries", {}).get("evidence_basis", []):
                        graph_index_used = True
                except Exception as e:
                    # We catch a broad Exception here intentionally. This guarantees that absolutely any
                    # catastrophic failure in the semantic path (e.g. OOM, bad schema, model crash)
                    # is perfectly isolated, ensuring the valid Baseline metrics remain intact for evaluation.
                    sem_error_str = str(e)
                    s_res = {"explain": {"filters": filters, "why_fail": WHY_FAIL_QUERY_EXECUTION}}

            if b_count == 0 and (not compare_mode or s_count == 0):
                zero_hit_count += 1

            if b_rel:
                base_hits_at_k += 1
                category_stats[cat_key]["base_hits"] += 1
            base_mrr_sum += b_rr
            category_stats[cat_key]["base_mrr_sum"] += b_rr

            if compare_mode:
                if s_rel:
                    sem_hits_at_k += 1
                    category_stats[cat_key]["sem_hits"] += 1
                sem_mrr_sum += s_rr
                category_stats[cat_key]["sem_mrr_sum"] += s_rr

            if not is_json_mode:
                disp_q = (q_text[:32] + "..") if len(q_text) > 32 else q_text
                if compare_mode:
                    b_disp_match = (b_match[:15] + "..") if len(b_match) > 15 else b_match
                    s_disp_match = (s_match[:15] + "..") if len(s_match) > 15 else s_match
                    b_str = f"{b_rr:.2f} / {b_disp_match}" if b_rel else "0.00 / ❌"
                    if sem_error_str:
                        s_str = "ERR / ❌"
                    else:
                        s_str = f"{s_rr:.2f} / {s_disp_match}" if s_rel else "0.00 / ❌"
                    print(f"{disp_q:<35} | {b_str:<25} | {s_str:<25}")
                else:
                    rel_mark = "✅" if b_rel else "❌"
                    disp_match = (b_match[:27] + "..") if len(b_match) > 27 else b_match
                    print(f"{disp_q:<40} | {b_count:<5} | {rel_mark:<4} | {disp_match:<30}")

            detail = {
                "query": q_text,
                "category": cat_key,
                "filters": filters,
                "expected": expected,
                "is_relevant": b_rel,
                "hit_path": b_match if b_rel else None,
                "found_count": b_count,
                "top_results": b_paths,
                "rr": b_rr,
                "query_mode": b_res.get("query_mode"),
                "explain": b_res.get("explain", {"filters": filters, "why_fail": WHY_FAIL_MISSING_EXPLAIN})
            }
            if b_why is not None:
                detail["why"] = b_why

            if compare_mode:
                detail["baseline"] = {
                    "is_relevant": b_rel,
                    "hit_path": b_match if b_rel else None,
                    "found_count": b_count,
                    "top_results": b_paths,
                    "rr": b_rr,
                    "explain": b_res.get("explain", {"filters": filters, "why_fail": WHY_FAIL_MISSING_EXPLAIN})
                }
                detail[compare_type] = {
                    "is_relevant": s_rel,
                    "hit_path": s_match if s_rel else None,
                    "found_count": s_count,
                    "top_results": s_paths,
                    "rr": s_rr,
                    "explain": s_res.get("explain", {"filters": filters, "why_fail": WHY_FAIL_MISSING_EXPLAIN})
                }
                if sem_error_str:
                    detail[compare_type]["error"] = sem_error_str
                detail["delta_rr"] = s_rr - b_rr
                # Overwrite backwards-compatible base fields with semantic ones if we're evaluating semantic overall
                detail["is_relevant"] = s_rel
                detail["hit_path"] = s_match if s_rel else None
                detail["found_count"] = s_count
                detail["top_results"] = s_paths
                detail["rr"] = s_rr
                detail["explain"] = s_res.get("explain", {"filters": filters, "why_fail": WHY_FAIL_MISSING_EXPLAIN})
                if s_why is not None:
                    detail["why"] = s_why
                if sem_error_str:
                    detail["error"] = f"Semantic Run Error: {sem_error_str}"

            results_detail.append(detail)

        except RuntimeError as e:
            if review_intent:
                review_intent_error_queries += 1
            if "Invalid graph index JSON" in str(e) or "Explicitly provided graph index file does not exist" in str(e):
                raise e
            if not is_json_mode:
                disp_q = (q_text[:32] + "..") if len(q_text) > 32 else q_text
                if compare_mode:
                    print(f"{disp_q:<35} | {'ERR':<25} | {'ERR':<25}", file=sys.stderr)
                else:
                    print(f"{disp_q:<40} | {'ERR':<5} | ❌   | error: {str(e)[:23]}", file=sys.stderr)

            results_detail.append({
                "query": q_text,
                "category": cat_key,
                "filters": filters,
                "expected": expected,
                "is_relevant": False,
                "hit_path": None,
                "found_count": 0,
                "top_results": [],
                "error": str(e),
                "why": {"why_fail": WHY_FAIL_QUERY_EXECUTION},
                "explain": {"filters": filters, "why_fail": WHY_FAIL_QUERY_EXECUTION}
            })

        except Exception as e:
            if review_intent:
                review_intent_error_queries += 1
            if not is_json_mode:
                disp_q = (q_text[:32] + "..") if len(q_text) > 32 else q_text
                if compare_mode:
                    print(f"{disp_q:<35} | {'ERR':<25} | {'ERR':<25}", file=sys.stderr)
                else:
                    print(f"{disp_q:<40} | {'ERR':<5} | ❌   | error: {str(e)[:23]}", file=sys.stderr)

            results_detail.append({
                "query": q_text,
                "category": cat_key,
                "filters": filters,
                "expected": expected,
                "is_relevant": False,
                "hit_path": None,
                "found_count": 0,
                "top_results": [],
                "error": str(e),
                "explain": {
                    "filters": filters,
                    "why_fail": WHY_FAIL_QUERY_EXECUTION
                }
            })

    base_recall_at_k = (base_hits_at_k / total_queries) * 100.0 if total_queries > 0 else 0.0
    base_mrr = base_mrr_sum / total_queries if total_queries > 0 else 0.0

    sem_recall_at_k = (sem_hits_at_k / total_queries) * 100.0 if total_queries > 0 else 0.0
    sem_mrr = sem_mrr_sum / total_queries if total_queries > 0 else 0.0

    zero_hit_ratio = zero_hit_count / total_queries if total_queries > 0 else 0.0

    for cat_data in category_stats.values():
        c_total = cat_data["total_queries"]
        cat_data[f"recall@{k}"] = (cat_data["base_hits"] / c_total) * 100.0 if c_total > 0 else 0.0
        cat_data["MRR"] = cat_data["base_mrr_sum"] / c_total if c_total > 0 else 0.0

        if compare_mode:
            cat_data[f"{compare_type}_recall@{k}"] = (cat_data["sem_hits"] / c_total) * 100.0 if c_total > 0 else 0.0
            cat_data[f"{compare_type}_MRR"] = cat_data["sem_mrr_sum"] / c_total if c_total > 0 else 0.0

    if not is_json_mode:
        print("-" * 80 if compare_mode else "-" * 60)
        if compare_mode:
            print(f"Base Recall@{k}: {base_recall_at_k:.1f}% ({base_hits_at_k}/{total_queries}) | Base MRR: {base_mrr:.3f}")
            print(f"{compare_label[:4]:<4} Recall@{k}: {sem_recall_at_k:.1f}% ({sem_hits_at_k}/{total_queries}) | {compare_label[:4]:<4} MRR: {sem_mrr:.3f}")
            print(f"Delta Recall@{k}: {(sem_recall_at_k - base_recall_at_k):+.1f}% | Delta MRR: {(sem_mrr - base_mrr):+.3f}")
            print(f"0-Hits Ratio: {zero_hit_ratio:.2f} ({zero_hit_count}/{total_queries})")
            for cat, stats in category_stats.items():
                print(f"  {cat} Base Recall@{k}: {stats[f'recall@{k}']:.1f}% | Base MRR: {stats['MRR']:.3f}")
                print(f"  {cat} {compare_label[:4]:<4} Recall@{k}: {stats.get(f'{compare_type}_recall@{k}', 0):.1f}% | {compare_label[:4]:<4} MRR: {stats.get(f'{compare_type}_MRR', 0):.3f}")
        else:
            print(f"Recall@{k}: {base_recall_at_k:.1f}% ({base_hits_at_k}/{total_queries}) | MRR: {base_mrr:.3f}")
            print(f"0-Hits Ratio: {zero_hit_ratio:.2f} ({zero_hit_count}/{total_queries})")
            for cat, stats in category_stats.items():
                print(f"  {cat} Recall@{k}: {stats[f'recall@{k}']:.1f}% | MRR: {stats['MRR']:.3f}")
        print("-" * 80 if compare_mode else "-" * 60)

    evidence_basis = ["eval_queries", "expected_targets", "query_results", "index", "retrieval_metrics"]
    if graph_index_used:
        evidence_basis.append("graph_index")
    if normalized_excluded_paths:
        evidence_basis.append("path_exclusions")

    # Build the miss taxonomy for diagnostic purposes
    miss_taxonomy = build_miss_taxonomy(results_detail, is_stale)

    out = {
        "metrics": {
            f"recall@{k}": sem_recall_at_k if compare_mode else base_recall_at_k,
            f"baseline_recall@{k}": base_recall_at_k,
            "MRR": sem_mrr if compare_mode else base_mrr,
            "baseline_MRR": base_mrr,
            "total_queries": total_queries,
            "hits": sem_hits_at_k if compare_mode else base_hits_at_k,
            "baseline_hits": base_hits_at_k,
            "stale_flag": is_stale,
            "zero_hit_ratio": zero_hit_ratio,
            "categories": category_stats
        },
        "details": results_detail,
        "claim_boundaries": {
            "proves": [
                "These metrics were computed for this eval set against this index and query pipeline."
            ],
            "does_not_prove": [
                "Recall on this eval set does not prove general retrieval quality.",
                "Zero-hit ratio does not prove absence of relevant repository content.",
                "MRR does not prove semantic correctness.",
                "Eval results do not prove live repository state."
            ],
            "evidence_basis": evidence_basis,
            "requires_live_check": True
        },
        "miss_taxonomy": miss_taxonomy
    }
    if normalized_excluded_paths or review_intent:
        out["measurement_conditions"] = {}
    if normalized_excluded_paths:
        out["measurement_conditions"].update({
            "excluded_paths": normalized_excluded_paths,
            "match": "exact_repository_path",
            "application": (
                "before_order_by_and_limit_per_lane"
                if review_intent
                else "before_order_by_and_limit"
            ),
            "ranking_algorithm_changed": review_intent,
        })
        out["claim_boundaries"]["does_not_prove"].append(
            "Path exclusions change this measurement scope; they do not establish a ranking improvement."
        )
        out["claim_boundaries"]["does_not_prove"].append(
            "An excluded path is not established as irrelevant."
        )
    if review_intent:
        out["measurement_conditions"]["review_intent"] = {
            "enabled": True,
            "requested": True,
            "plan_version": "review_intent.v1",
            "fusion": "round_robin_unique_path",
            "default_promoted": False,
            "executed_queries": review_intent_executed_queries,
            "fallback_queries": review_intent_fallback_queries,
            "error_queries": review_intent_error_queries,
            "fallback_mode": "legacy",
            "ranking_algorithm_changed": review_intent_executed_queries > 0,
        }
        out["claim_boundaries"]["does_not_prove"].extend([
            "Review-intent metrics do not establish improvement for unmeasured query classes.",
            "This opt-in evaluation does not establish readiness for default promotion.",
        ])

    if compare_mode:
        out["metrics"][f"{compare_type}_recall@{k}"] = sem_recall_at_k
        out["metrics"][f"{compare_type}_MRR"] = sem_mrr
        out["metrics"][f"{compare_type}_hits"] = sem_hits_at_k
        out["metrics"]["delta_recall"] = sem_recall_at_k - base_recall_at_k
        out["metrics"]["delta_mrr"] = sem_mrr - base_mrr

        # Backwards compatibility specifically for semantic eval callers.
        # These additional semantic_* metrics in non-semantic compare modes serve purely for backward compatibility.
        if compare_type != "semantic":
            out["metrics"][f"semantic_recall@{k}"] = sem_recall_at_k
            out["metrics"]["semantic_MRR"] = sem_mrr

    return out
