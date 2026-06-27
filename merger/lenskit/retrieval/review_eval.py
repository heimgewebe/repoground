"""
Review Retrieval Metric Baseline + Miss Diagnostics adapter.

This module connects the review goldset (`docs/retrieval/review_queries.v1.json`)
to the existing evaluation and diagnostics infrastructure. The default mode
measures the established lexical pipeline. With ``review_intent=True`` it
explicitly selects the opt-in deterministic review pipeline and records that
execution condition. It remains a diagnostic measuring instrument, not a
quality or correctness verdict.

Reuse, not reinvention:
- Metrics (recall@k, MRR, zero_hit_ratio, per-category recall/MRR) come from
  `eval_core.do_eval`.
- Per-expected-target miss classification reuses the existing taxonomy in
  `eval_diagnostics.RetrievalEvalDiagnosticsCalibrator` (the eight
  `DiagnosticsRecord.PRIMARY_DIAGNOSES` terms). No second taxonomy is introduced.

Boundaries (see DOES_NOT_ESTABLISH):
- A hit does not prove answer correctness.
- A miss does not prove code absence.
- recall@k does not prove ranking sufficiency or review completeness.
"""

import json
import re
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional, Tuple

from .eval_core import do_eval
from .eval_diagnostics import DiagnosticsRecord, RetrievalEvalDiagnosticsCalibrator
from .query_core import normalize_excluded_paths

# Inference boundaries for the review-retrieval baseline. These mirror the
# discipline already encoded in eval_core.claim_boundaries.does_not_prove and
# eval_diagnostics.DOES_NOT_PROVE: the baseline is a diagnostic measurement, never
# a truth/completeness/sufficiency verdict.
DOES_NOT_ESTABLISH: Tuple[str, ...] = (
    "This baseline measures current lexical retrieval behavior for the review goldset.",
    "The report is diagnostic and does not establish review completeness.",
    "A hit does not prove answer correctness.",
    "A miss does not prove code absence.",
    "recall@k does not prove ranking sufficiency.",
)

GOLDSET_SELF_REFERENCE_REASON = "goldset_self_reference"

# Path-shape heuristics mirror the static goldset guard
# (merger/lenskit/tests/test_review_retrieval_goldset.py) so target-kind labeling
# stays consistent with how the goldset itself is validated.
_REPO_PATH_PREFIXES = (".github/", "docs/", "merger/", "scripts/", "tools/")
_REPO_PATH_SUFFIXES = (".py", ".json", ".md", ".sh", ".yml", ".yaml", ".toml", ".txt")
_ROOT_PATH_PATTERNS = {"Makefile", "README.md", "pyproject.toml", "package.json"}

_RECALL_KEY_RE = re.compile(r"^recall@(\d+)$")


def _is_repo_path_pattern(pattern: str) -> bool:
    return (
        pattern.startswith(_REPO_PATH_PREFIXES)
        or "/" in pattern
        or pattern.endswith(_REPO_PATH_SUFFIXES)
        or pattern in _ROOT_PATH_PATTERNS
    )


def _resolve_goldset_exclusion(
    goldset_path: Path,
    repo_root: Optional[Path],
) -> Tuple[List[str], List[Dict[str, str]]]:
    """Resolve the goldset path only when an explicit repository root is supplied."""
    if repo_root is None:
        return [], []

    resolved_root = Path(repo_root).resolve()
    if not resolved_root.is_dir():
        raise ValueError(f"repo_root must be an existing directory: {repo_root}")

    supplied_goldset = Path(goldset_path)
    resolved_goldset = (
        supplied_goldset.resolve()
        if supplied_goldset.is_absolute()
        else (resolved_root / supplied_goldset).resolve()
    )
    try:
        relative_goldset = resolved_goldset.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError("goldset_path must resolve inside repo_root") from exc

    normalized_path = normalize_excluded_paths([relative_goldset.as_posix()])[0]
    return [normalized_path], [
        {
            "path": normalized_path,
            "reason": GOLDSET_SELF_REFERENCE_REASON,
        }
    ]


def _normalize_path_exclusion_records(
    records: Optional[List[Dict[str, str]]],
) -> List[Dict[str, str]]:
    normalized: Dict[Tuple[str, str], Dict[str, str]] = {}
    for record in records or []:
        if not isinstance(record, dict):
            raise ValueError("path exclusion records must be objects")
        path = normalize_excluded_paths([record.get("path")])[0]
        reason = record.get("reason")
        if not isinstance(reason, str) or not reason:
            raise ValueError("path exclusion records require a non-empty reason")
        normalized[(path, reason)] = {"path": path, "reason": reason}
    return [normalized[key] for key in sorted(normalized)]


def classify_target_kind(target: str) -> str:
    """Classify an expected target's shape for diagnostic reporting.

    Returns one of: "test_path", "path", "symbol_or_text", "unknown".

    Path-like targets are recognized, but symbolic targets (e.g. function names)
    are never treated as file errors.
    """
    if not isinstance(target, str) or not target.strip():
        return "unknown"
    if not _is_repo_path_pattern(target):
        return "symbol_or_text"
    basename = PurePosixPath(target.rstrip("/")).name
    if "/tests/" in target or basename.startswith("test_"):
        return "test_path"
    return "path"


def normalize_review_queries(raw: Any) -> List[Dict[str, Any]]:
    """Normalize the review goldset into stable query records.

    Accepts either a top-level list (the committed shape) or a
    ``{"queries": [...]}`` envelope. Several expected-target field names are
    tolerated (`expected_patterns`, `expected`, `expected_targets`) and multiple
    expected patterns per query are preserved. A deterministic ``query_id`` is
    assigned by 1-based position so reports are reproducible.
    """
    if isinstance(raw, dict):
        queries = raw.get("queries")
    elif isinstance(raw, list):
        queries = raw
    else:
        queries = None

    if not isinstance(queries, list):
        raise ValueError(
            "review goldset must be a list of queries or a {'queries': [...]} object"
        )

    normalized: List[Dict[str, Any]] = []
    for idx, item in enumerate(queries, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"review query #{idx} must be an object")

        expected = (
            item.get("expected_patterns")
            or item.get("expected")
            or item.get("expected_targets")
            or []
        )
        if not isinstance(expected, list):
            expected = [expected]

        normalized.append(
            {
                "query_id": f"RQ-{idx:02d}",
                "query": item.get("query") or item.get("query_text") or "",
                "category": item.get("category") or "uncategorized",
                "expected_targets": [str(target) for target in expected],
                "filters": item.get("filters") or {},
                "accept_criteria": item.get("accept_criteria") or {},
            }
        )
    return normalized


def load_review_queries(path: Path) -> List[Dict[str, Any]]:
    """Load and normalize the review goldset from a JSON file."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Review goldset not found: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    return normalize_review_queries(raw)


def _infer_k(metrics: Dict[str, Any], fallback: int) -> int:
    """Infer the configured eval k from a ``recall@N`` metric key."""
    if isinstance(metrics, dict):
        for key in metrics:
            if isinstance(key, str):
                match = _RECALL_KEY_RE.match(key)
                if match:
                    return int(match.group(1))
    return fallback


def _find_target_rank(
    target: str, top_results: List[str]
) -> Tuple[bool, Optional[int], Optional[str]]:
    """Locate the first ranked result matching ``target`` (substring semantics).

    Mirrors the relevance match used by eval_core.evaluate_single_run. Returns
    (found, rank_1_indexed, matched_result).
    """
    # Keep substring semantics aligned with eval_core.evaluate_single_run.
    # Matcher calibration is a later slice; this adapter must not change retrieval semantics.
    for rank_idx, result_path in enumerate(top_results):
        if isinstance(result_path, str) and (
            target in result_path or result_path in target
        ):
            return True, rank_idx + 1, result_path
    return False, None, None


def build_review_retrieval_baseline(
    eval_results: Dict[str, Any],
    *,
    k: Optional[int] = None,
    calibrator: Optional[RetrievalEvalDiagnosticsCalibrator] = None,
    goldset_path: Optional[Path] = None,
    path_exclusions: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """Build the review retrieval baseline from ``eval_core.do_eval`` output.

    The returned dict carries reproducible metrics, per-expected-target hit
    reporting, miss diagnostics reconciled with the existing taxonomy, and
    explicit inference boundaries. Retrieval metrics are taken verbatim from the
    eval output; this function adds review-specific aggregation and per-target
    reporting only.
    """
    metrics_in = eval_results.get("metrics", {}) or {}
    details = eval_results.get("details", []) or []
    resolved_k = k if k is not None else _infer_k(metrics_in, fallback=10)
    recall_key = f"recall@{resolved_k}"
    normalized_path_exclusions = _normalize_path_exclusion_records(path_exclusions)
    if normalized_path_exclusions:
        observed_excluded_paths = normalize_excluded_paths(
            (eval_results.get("measurement_conditions") or {}).get("excluded_paths")
        )
        declared_excluded_paths = [
            record["path"] for record in normalized_path_exclusions
        ]
        if observed_excluded_paths != declared_excluded_paths:
            raise ValueError(
                "baseline exclusion provenance does not match eval conditions"
            )

    if calibrator is None:
        calibrator = RetrievalEvalDiagnosticsCalibrator()

    taxonomy_summary: Dict[str, int] = {
        diagnosis: 0 for diagnosis in sorted(DiagnosticsRecord.PRIMARY_DIAGNOSES)
    }

    query_records: List[Dict[str, Any]] = []
    miss_diagnostics: List[Dict[str, Any]] = []
    expected_target_total = 0
    expected_target_hits = 0

    for idx, detail in enumerate(details, start=1):
        query_id = f"RQ-{idx:02d}"
        query_text = detail.get("query", "")
        category = detail.get("category") or "uncategorized"
        expected = detail.get("expected", []) or []
        top_results = detail.get("top_results", []) or []
        found_count = detail.get("found_count", 0)
        query_had_zero_hits = found_count == 0 or len(top_results) == 0

        target_records: List[Dict[str, Any]] = []
        for raw_target in expected:
            target = str(raw_target)
            expected_target_total += 1
            found, rank, matched = _find_target_rank(target, top_results)
            in_top_k = found and rank is not None and rank <= resolved_k
            if in_top_k:
                expected_target_hits += 1

            # Diagnose every target through the existing taxonomy. Hits resolve to
            # "target_in_top_k"; misses fall into the existing miss categories.
            record = calibrator.diagnose_miss(
                query_id=query_id,
                query_text=query_text,
                expected_target=target,
                found_in_results=found,
                rank_in_results=rank,
                top_k=resolved_k,
                query_had_zero_hits=query_had_zero_hits,
            )
            diagnosis = record.primary_diagnosis
            if diagnosis not in DiagnosticsRecord.PRIMARY_DIAGNOSES:
                diagnosis = "diagnostic_inconclusive"
            taxonomy_summary[diagnosis] = taxonomy_summary.get(diagnosis, 0) + 1

            target_records.append(
                {
                    "target": target,
                    "target_kind": classify_target_kind(target),
                    "found": in_top_k,
                    "rank": rank if in_top_k else None,
                    "matched_result": matched if in_top_k else None,
                    "diagnosis": diagnosis,
                }
            )
            if not in_top_k:
                diagnostic_record = record.to_dict()
                diagnostic_record["primary_diagnosis"] = diagnosis
                miss_diagnostics.append(diagnostic_record)

        query_records.append(
            {
                "query_id": query_id,
                "query": query_text,
                "category": category,
                "top_k": resolved_k,
                "query_had_zero_hits": query_had_zero_hits,
                "expected_targets": target_records,
            }
        )

    categories: Dict[str, Dict[str, Any]] = {}
    for cat, stats in (metrics_in.get("categories", {}) or {}).items():
        total = stats.get("total_queries", 0)
        hits = stats.get("base_hits", stats.get("hits", 0))
        categories[cat] = {
            "total_queries": total,
            "hits": hits,
            "misses": total - hits,
            recall_key: stats.get(recall_key, 0.0),
            "MRR": stats.get("MRR", 0.0),
        }

    total_queries = metrics_in.get("total_queries", len(details))

    baseline = {
        "version": "1.0",
        "authority": "diagnostic_signal",
        "risk_class": "diagnostic",
        "goldset": {
            "path": str(goldset_path) if goldset_path is not None else None,
            "total_queries": total_queries,
        },
        "k": resolved_k,
        "metrics": {
            "total_queries": total_queries,
            recall_key: metrics_in.get(recall_key, 0.0),
            "MRR": metrics_in.get("MRR", 0.0),
            "zero_hit_ratio": metrics_in.get("zero_hit_ratio", 0.0),
            "expected_target_total": expected_target_total,
            "expected_target_hits": expected_target_hits,
            "expected_target_misses": expected_target_total - expected_target_hits,
        },
        "categories": categories,
        "queries": query_records,
        "miss_taxonomy_summary": taxonomy_summary,
        "miss_diagnostics": miss_diagnostics,
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }
    eval_conditions = eval_results.get("measurement_conditions") or {}
    review_condition = eval_conditions.get("review_intent")
    if normalized_path_exclusions or review_condition:
        baseline["measurement_conditions"] = {}
    if normalized_path_exclusions:
        baseline["measurement_conditions"].update({
            "path_exclusions": normalized_path_exclusions,
            "match": "exact_repository_path",
            "application": (
                "before_order_by_and_limit_per_lane"
                if review_condition
                else "before_order_by_and_limit"
            ),
            "ranking_algorithm_changed": bool(
                review_condition and review_condition.get("ranking_algorithm_changed")
            ),
            "does_not_establish": [
                "Excluded paths are outside this measurement run only.",
                "An excluded path is not established as irrelevant.",
                "Changed metrics do not establish a ranking improvement.",
            ],
        })
    if review_condition:
        baseline["measurement_conditions"]["review_intent"] = dict(
            review_condition
        )
        baseline["does_not_establish"].extend([
            "Review-intent metrics do not establish improvement for unmeasured query classes.",
            "This opt-in baseline does not establish readiness for default promotion.",
        ])
    return baseline


def run_review_retrieval_baseline(
    index_path: Path,
    goldset_path: Path,
    k: int = 10,
    *,
    chunk_index_path: Optional[Path] = None,
    canonical_path: Optional[Path] = None,
    citation_path: Optional[Path] = None,
    is_stale: bool = False,
    repo_root: Optional[Path] = None,
    review_intent: bool = False,
) -> Optional[Dict[str, Any]]:
    """Reproduction helper: run the eval and build the review baseline.

    This is a library-only convenience wrapper around ``eval_core.do_eval`` plus
    the diagnostics calibrator. The default path remains the established lexical
    evaluation; ``review_intent=True`` selects the opt-in deterministic review
    pipeline. Returns ``None`` if the underlying eval cannot parse the goldset
    (matching ``do_eval`` semantics).
    """
    excluded_paths, path_exclusions = _resolve_goldset_exclusion(
        Path(goldset_path), repo_root
    )
    eval_results = do_eval(
        Path(index_path),
        Path(goldset_path),
        k,
        is_json_mode=True,
        is_stale=is_stale,
        excluded_paths=excluded_paths,
        review_intent=review_intent,
    )
    if eval_results is None:
        return None

    calibrator = RetrievalEvalDiagnosticsCalibrator(
        index_path=Path(chunk_index_path) if chunk_index_path is not None else None,
        canonical_path=Path(canonical_path) if canonical_path is not None else None,
        citation_path=Path(citation_path) if citation_path is not None else None,
    )
    return build_review_retrieval_baseline(
        eval_results,
        k=k,
        calibrator=calibrator,
        goldset_path=goldset_path,
        path_exclusions=path_exclusions,
    )
