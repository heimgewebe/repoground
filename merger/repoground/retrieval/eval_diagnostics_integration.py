"""
Integration example: Using retrieval_eval_diagnostics in the eval pipeline.

This module shows how to integrate the diagnostics calibrator with existing
evaluation results to generate diagnostic reports.

NOTE: The calibrator does not modify retrieval behavior, metrics, or the gold set.
It only explains why misses occurred.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import re
from .eval_diagnostics import RetrievalEvalDiagnosticsCalibrator


def _require_eval_detail(value: Any, *, index: int) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(
            f"Expected retrieval_eval['details'][{index}] to be an object."
        )
    return value


def _require_detail_string_list(
    value: Any,
    *,
    index: int,
    field: str,
) -> List[str]:
    path = f"retrieval_eval['details'][{index}]['{field}']"
    if not isinstance(value, list):
        raise ValueError(f"Expected {path} to be a list of strings.")
    for item_index, item in enumerate(value):
        if not isinstance(item, str):
            raise ValueError(f"Expected {path}[{item_index}] to be a string.")
        if not item.strip():
            raise ValueError(
                f"Expected {path}[{item_index}] to be a non-empty string."
            )
    return value


def _validate_eval_detail_fields(
    detail: Dict[str, Any],
    *,
    index: int,
) -> Tuple[str, List[str], bool, int, List[str]]:
    prefix = f"retrieval_eval['details'][{index}]"

    query_text = detail.get("query", "")
    if not isinstance(query_text, str):
        raise ValueError(f"Expected {prefix}['query'] to be a string.")

    expected = _require_detail_string_list(
        detail.get("expected", []),
        index=index,
        field="expected",
    )

    is_relevant = detail.get("is_relevant", False)
    if not isinstance(is_relevant, bool):
        raise ValueError(f"Expected {prefix}['is_relevant'] to be a boolean.")

    found_count = detail.get("found_count", 0)
    if isinstance(found_count, bool) or not isinstance(found_count, int):
        raise ValueError(f"Expected {prefix}['found_count'] to be an integer.")
    if found_count < 0:
        raise ValueError(f"Expected {prefix}['found_count'] to be non-negative.")

    top_results = _require_detail_string_list(
        detail.get("top_results", []),
        index=index,
        field="top_results",
    )

    return query_text, expected, is_relevant, found_count, top_results


def _query_execution_error(
    detail: Dict[str, Any],
    *,
    index: int,
) -> Optional[str]:
    prefix = f"retrieval_eval['details'][{index}]"
    error = detail.get("error")
    if error is not None:
        if not isinstance(error, str) or not error.strip():
            raise ValueError(f"Expected {prefix}['error'] to be a non-empty string.")

    why_fail_candidates = [
        (f"{prefix}['why_fail']", detail.get("why_fail")),
    ]
    for section_name in ("why", "explain"):
        section = detail.get(section_name)
        if isinstance(section, dict):
            why_fail_candidates.append(
                (
                    f"{prefix}['{section_name}']['why_fail']",
                    section.get("why_fail"),
                )
            )

    for marker_path, why_fail in why_fail_candidates:
        if why_fail is not None and not isinstance(why_fail, str):
            raise ValueError(f"Expected {marker_path} to be a string.")

    has_query_execution_failure = any(
        why_fail == "query execution failed"
        for _, why_fail in why_fail_candidates
    )
    if has_query_execution_failure:
        return error or "query execution failed"
    return None


def integrate_diagnostics_with_eval_results(
    eval_results: Dict[str, Any],
    index_path: Optional[Path] = None,
    canonical_path: Optional[Path] = None,
    citation_path: Optional[Path] = None,
    output_path: Optional[Path] = None,
    report_timestamp: Optional[str] = None,
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
        report_timestamp: Optional stable source/run timestamp to include in metadata.

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
    diagnostics_report = calibrator.generate_report(
        misses, timestamp=report_timestamp
    )

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
                "is_relevant": false,
                "found_count": 0,  # Number of results found
                ...
            }
        ]
    }
    """
    misses: List[Dict[str, Any]] = []
    if "details" not in eval_results:
        if "results" in eval_results:
            raise ValueError(
                "Expected retrieval_eval field 'details', found unsupported legacy key 'results'."
            )
        raise ValueError("Expected retrieval_eval field 'details'.")

    details = eval_results.get("details", [])
    if not isinstance(details, list):
        raise ValueError("Expected retrieval_eval['details'] to be a list.")

    configured_top_k = _infer_top_k_from_metrics(eval_results.get("metrics", {}))

    for detail_idx, detail in enumerate(details):
        detail = _require_eval_detail(detail, index=detail_idx)
        (
            query_text,
            expected,
            _is_relevant,
            found_count,
            top_results,
        ) = _validate_eval_detail_fields(detail, index=detail_idx)

        query_error = _query_execution_error(detail, index=detail_idx)

        # Prefer configured eval k from metrics (e.g., recall@10), because top_results
        # may be shorter than k for low-hit queries.
        top_k = (
            configured_top_k
            if configured_top_k is not None
            else (len(top_results) if len(top_results) > 0 else None)
        )

        # For each expected target, create a miss record
        for expected_target in expected:
            if query_error is not None:
                misses.append(
                    {
                        "query_id": f"q{detail_idx}",
                        "query_text": query_text,
                        "expected_target": expected_target,
                        "found_in_results": False,
                        "rank_in_results": None,
                        "top_k": top_k,
                        "query_had_zero_hits": True,
                        "query_error": query_error,
                    }
                )
                continue

            # Try to determine if target was in results
            found_in_results = False
            rank_in_results = None

            # Check if target was found (substring match in results)
            for rank_idx, res_path in enumerate(top_results):
                if expected_target in res_path:
                    found_in_results = True
                    rank_in_results = rank_idx + 1
                    break

            # Query-level is_relevant cannot identify which target matched. A target
            # observed within the effective k is not a miss; an over-fetched target
            # below k remains diagnostic input with its observed rank preserved.
            if rank_in_results is not None and (
                top_k is None or rank_in_results <= top_k
            ):
                continue

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
                candidate = int(match.group(1))
            except ValueError:
                continue
            if candidate > 0:
                candidates.append(candidate)

    return max(candidates) if candidates else None
