"""
Integration example: Using retrieval_eval_diagnostics in the eval pipeline.

This module shows how to integrate the diagnostics calibrator with existing
evaluation results to generate diagnostic reports.

NOTE: The calibrator does not modify retrieval behavior, metrics, or the gold set.
It only explains why misses occurred.
"""

from pathlib import Path
from typing import Dict, List, Any, Optional
from .eval_diagnostics import ReturnEvalDiagnosticsCalibrator


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
    calibrator = ReturnEvalDiagnosticsCalibrator(
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
        "results": [
            {
                "query_index": 0,
                "query": "...",
                "expected": ["path1", "path2"],
                "is_relevant": false,  # Miss if false
                "observed_top_k_count": 0,  # Number of results found
                ...
            }
        ]
    }
    """
    misses = []
    results = eval_results.get("results", [])

    for result in results:
        # Only process misses (is_relevant=false)
        if result.get("is_relevant", False):
            continue

        query_index = result.get("query_index", 0)
        query_text = result.get("query", "")
        expected = result.get("expected", [])
        found_count = result.get("observed_top_k_count", 0)
        top_k = result.get("top_k", 10)

        # For each expected target, create a miss record
        for expected_target in expected:
            # Try to determine if target was in results
            found_in_results = False
            rank_in_results = None

            # Check if target was found (substring match in results)
            top_results = result.get("top_results", [])
            for idx, res_path in enumerate(top_results):
                if expected_target in res_path or res_path in expected_target:
                    found_in_results = True
                    rank_in_results = idx + 1
                    break

            miss = {
                "query_id": f"q{query_index}",
                "query_text": query_text,
                "expected_target": expected_target,
                "found_in_results": found_in_results,
                "rank_in_results": rank_in_results,
                "top_k": top_k,
                "query_had_zero_hits": found_count == 0,
            }
            misses.append(miss)

    return misses
