"""
Integration example: Using retrieval_eval_diagnostics in the eval pipeline.

This module shows how to integrate the diagnostics calibrator with existing
evaluation results to generate diagnostic reports.

NOTE: The calibrator does not modify retrieval behavior, metrics, or the gold set.
It only explains why misses occurred.
"""

from pathlib import Path
from typing import Dict, List, Any, Optional
import re
from .eval_diagnostics import RetrievalEvalDiagnosticsCalibrator


def integrate_diagnostics_with_eval_results(
    eval_results: Dict[str, Any],
    index_path: Optional[Path] = None,
    canonical_path: Optional[Path] = None,
    citation_path: Optional[Path] = None,
    output_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Integrate diagnostics calibrator with existing eval results.

    This function takes the output from a standard retrieval evaluation
    (from eval_core.do_eval) and generates diagnostic classifications
    for all misses without modifying the original evaluation.

    Args:
        eval_results: Results from eval_core.do_eval()
        index_path: Path to chunk_index.jsonl
        canonical_path: Path to canonical_md artifact
        citation_path: Path to citation_map_jsonl
        output_path: Optional path to save diagnostics report

    Returns:
        Dictionary with original eval results and added diagnostics report.
    """
    calibrator = RetrievalEvalDiagnosticsCalibrator(
        index_path=index_path,
        canonical_path=canonical_path,
        citation_path=citation_path,
    )

    # Extract misses from eval results
    misses = _extract_misses_from_eval(eval_results)

    # Generate diagnostic report
    diagnostics_report = calibrator.generate_report(misses)

    # Optionally save report
    if output_path:
        calibrator.save_report(diagnostics_report, output_path)

    # Combine original results with diagnostics
    combined = {
        "eval_results": eval_results,
        "diagnostics_report": diagnostics_report,
        "note": "Diagnostics are diagnostic-only signals and do not modify evaluation metrics.",
    }

    return combined


def _extract_misses_from_eval(eval_results: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Extract misses from standard eval results format.

    Expected structure:
    {
        "metrics": {...},
        "details": [
            {
                "query": "...",
                "expected": ["path1", "path2"],
                "is_relevant": false,  # Miss if false
                "found_count": 0,  # Number of results found
                ...
            }
        ]
    }
    """
    misses: List[Dict[str, Any]] = []
    if "details" not in eval_results:
        if "results" in eval_results:
            raise ValueError("Expected retrieval_eval field 'details', found unsupported legacy key 'results'.")
        raise ValueError("Expected retrieval_eval field 'details'.")

    details = eval_results.get("details", [])
    if not isinstance(details, list):
        raise ValueError("Expected retrieval_eval['details'] to be a list.")

    configured_top_k = _infer_top_k_from_metrics(eval_results.get("metrics", {}))

    for detail_idx, detail in enumerate(details):
        # Only process misses (is_relevant=false)
        if detail.get("is_relevant", False):
            continue

        query_text = detail.get("query", "")
        expected = detail.get("expected", [])
        if not isinstance(expected, list):
            expected = [str(expected)]
        found_count = detail.get("found_count", 0)
        if not isinstance(found_count, int):
            found_count = 0

        top_results = detail.get("top_results", [])
        if not isinstance(top_results, list):
            top_results = []
        # Prefer configured eval k from metrics (e.g., recall@10), because top_results
        # may be shorter than k for low-hit queries.
        top_k = configured_top_k if configured_top_k is not None else (len(top_results) if len(top_results) > 0 else None)

        # For each expected target, create a miss record
        for expected_target in expected:
            if not isinstance(expected_target, str):
                expected_target = str(expected_target)

            # Try to determine if target was in results
            found_in_results = False
            rank_in_results = None

            # Check if target was found (substring match in results)
            for rank_idx, res_path in enumerate(top_results):
                if isinstance(res_path, str) and (expected_target in res_path or res_path in expected_target):
                    found_in_results = True
                    rank_in_results = rank_idx + 1
                    break

            miss = {
                "query_id": f"q{detail_idx}",
                "query_text": query_text,
                "expected_target": expected_target,
                "found_in_results": found_in_results,
                "rank_in_results": rank_in_results,
                "top_k": top_k,
                "query_had_zero_hits": found_count == 0,
            }
            misses.append(miss)

    return misses


def _infer_top_k_from_metrics(metrics: Any) -> Optional[int]:
    """Infer configured eval k from retrieval_eval metrics keys like recall@10."""
    if not isinstance(metrics, dict):
        return None

    pattern = re.compile(r"(?:^|_)recall@(\d+)$")
    candidates: List[int] = []

    for key in metrics.keys():
        if not isinstance(key, str):
            continue
        match = pattern.search(key)
        if match:
            try:
                candidates.append(int(match.group(1)))
            except ValueError:
                continue

    return max(candidates) if candidates else None
