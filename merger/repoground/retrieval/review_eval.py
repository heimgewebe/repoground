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

import hashlib
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
CANONICAL_REVIEW_GOLDSET = Path("docs/retrieval/review_queries.v1.json")
GOLDSET_CONTRACT_PATH = (
    Path(__file__).resolve().parents[1]
    / "contracts"
    / "review-retrieval-goldset.v1.schema.json"
)


class SnapshotRetrievalMeasurementError(RuntimeError):
    """Fail-closed error for an invalid canonical snapshot benchmark."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


# Path-shape heuristics mirror the static goldset guard
# (merger/repoground/tests/test_review_retrieval_goldset.py) so target-kind labeling
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


def _percentage(hits: int, total: int) -> float:
    return round((hits / total) * 100.0, 6) if total else 0.0


def build_review_retrieval_baseline(
    eval_results: Dict[str, Any],
    *,
    k: Optional[int] = None,
    calibrator: Optional[RetrievalEvalDiagnosticsCalibrator] = None,
    goldset_path: Optional[Path] = None,
    path_exclusions: Optional[List[Dict[str, str]]] = None,
    review_queries: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Build review-specific aggregates from ``eval_core.do_eval`` output.

    Question recall and expected-target recall are deliberately separate. A
    question counts as a hit when any expected target is retrieved; target
    recall counts each expected path or symbol independently.
    """
    metrics_in = eval_results.get("metrics", {}) or {}
    details = eval_results.get("details", []) or []
    resolved_k = k if k is not None else _infer_k(metrics_in, fallback=10)
    recall_key = f"recall@{resolved_k}"
    question_recall_key = f"question_recall@{resolved_k}"
    target_recall_key = f"expected_target_recall@{resolved_k}"
    criterion_key = f"recall_at_{resolved_k}"
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

    normalized_queries = review_queries
    if normalized_queries is None and goldset_path is not None and Path(goldset_path).is_file():
        normalized_queries = load_review_queries(Path(goldset_path))
    if normalized_queries is not None and len(normalized_queries) != len(details):
        raise ValueError("review goldset query count does not match eval details")

    if calibrator is None:
        calibrator = RetrievalEvalDiagnosticsCalibrator()

    taxonomy_summary: Dict[str, int] = {
        diagnosis: 0 for diagnosis in sorted(DiagnosticsRecord.PRIMARY_DIAGNOSES)
    }
    query_records: List[Dict[str, Any]] = []
    miss_diagnostics: List[Dict[str, Any]] = []
    expected_target_total = 0
    expected_target_hits = 0
    acceptance_passed = 0
    acceptance_failed = 0
    acceptance_evaluated = 0
    category_targets: Dict[str, Dict[str, int]] = {}

    for idx, detail in enumerate(details, start=1):
        query_id = f"RQ-{idx:02d}"
        query_text = detail.get("query", "")
        category = detail.get("category") or "uncategorized"
        expected = detail.get("expected", []) or []
        top_results = detail.get("top_results", []) or []
        found_count = detail.get("found_count", 0)
        query_had_zero_hits = found_count == 0 or len(top_results) == 0
        query_spec = normalized_queries[idx - 1] if normalized_queries is not None else None
        if query_spec is not None:
            if query_spec.get("query") != query_text:
                raise ValueError(f"review goldset query #{idx} does not match eval detail")
            if list(query_spec.get("expected_targets", [])) != list(expected):
                raise ValueError(f"review goldset targets #{idx} do not match eval detail")

        target_records: List[Dict[str, Any]] = []
        query_target_hits = 0
        cat_targets = category_targets.setdefault(category, {"total": 0, "hits": 0})
        for raw_target in expected:
            target = str(raw_target)
            expected_target_total += 1
            cat_targets["total"] += 1
            found, rank, matched = _find_target_rank(target, top_results)
            in_top_k = found and rank is not None and rank <= resolved_k
            if in_top_k:
                expected_target_hits += 1
                query_target_hits += 1
                cat_targets["hits"] += 1

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
            target_records.append({
                "target": target,
                "target_kind": classify_target_kind(target),
                "found": in_top_k,
                "rank": rank if in_top_k else None,
                "matched_result": matched if in_top_k else None,
                "diagnosis": diagnosis,
            })
            if not in_top_k:
                diagnostic_record = record.to_dict()
                diagnostic_record["primary_diagnosis"] = diagnosis
                miss_diagnostics.append(diagnostic_record)

        query_target_total = len(expected)
        observed_ratio = (query_target_hits / query_target_total) if query_target_total else 0.0
        acceptance = None
        if query_spec is not None:
            raw_threshold = (query_spec.get("accept_criteria") or {}).get(criterion_key)
            if isinstance(raw_threshold, (int, float)):
                passed = observed_ratio >= float(raw_threshold)
                acceptance_evaluated += 1
                acceptance_passed += int(passed)
                acceptance_failed += int(not passed)
                acceptance = {
                    "criterion": criterion_key,
                    "required_ratio": float(raw_threshold),
                    "observed_ratio": round(observed_ratio, 6),
                    "status": "pass" if passed else "fail",
                }

        query_record = {
            "query_id": query_id,
            "query": query_text,
            "category": category,
            "top_k": resolved_k,
            "query_had_zero_hits": query_had_zero_hits,
            "question_hit": bool(detail.get("is_relevant", False)),
            "reciprocal_rank": float(detail.get("rr", 0.0) or 0.0),
            "expected_target_total": query_target_total,
            "expected_target_hits": query_target_hits,
            "expected_target_misses": query_target_total - query_target_hits,
            target_recall_key: _percentage(query_target_hits, query_target_total),
            "expected_targets": target_records,
        }
        if acceptance is not None:
            query_record["acceptance"] = acceptance
        query_records.append(query_record)

    categories: Dict[str, Dict[str, Any]] = {}
    for cat, stats in (metrics_in.get("categories", {}) or {}).items():
        total = int(stats.get("total_queries", 0) or 0)
        hits = int(stats.get("base_hits", stats.get("hits", 0)) or 0)
        target_stats = category_targets.get(cat, {"total": 0, "hits": 0})
        categories[cat] = {
            "total_queries": total,
            "hits": hits,
            "misses": total - hits,
            recall_key: stats.get(recall_key, 0.0),
            question_recall_key: stats.get(recall_key, 0.0),
            "MRR": stats.get("MRR", 0.0),
            "expected_target_total": target_stats["total"],
            "expected_target_hits": target_stats["hits"],
            "expected_target_misses": target_stats["total"] - target_stats["hits"],
            target_recall_key: _percentage(target_stats["hits"], target_stats["total"]),
        }

    total_queries = int(metrics_in.get("total_queries", len(details)) or 0)
    question_hits_raw = metrics_in.get("hits")
    if question_hits_raw is None:
        question_hits = round(
            total_queries * float(metrics_in.get(recall_key, 0.0) or 0.0) / 100.0
        )
    else:
        question_hits = int(question_hits_raw or 0)
    baseline = {
        "version": "1.1",
        "authority": "diagnostic_signal",
        "risk_class": "diagnostic",
        "goldset": {
            "path": str(goldset_path) if goldset_path is not None else None,
            "total_queries": total_queries,
        },
        "k": resolved_k,
        "metrics": {
            "total_queries": total_queries,
            "question_hits": question_hits,
            "question_misses": total_queries - question_hits,
            recall_key: metrics_in.get(recall_key, 0.0),
            question_recall_key: metrics_in.get(recall_key, 0.0),
            "MRR": metrics_in.get("MRR", 0.0),
            "zero_hit_ratio": metrics_in.get("zero_hit_ratio", 0.0),
            "expected_target_total": expected_target_total,
            "expected_target_hits": expected_target_hits,
            "expected_target_misses": expected_target_total - expected_target_hits,
            target_recall_key: _percentage(expected_target_hits, expected_target_total),
        },
        "categories": categories,
        "queries": query_records,
        "acceptance": {
            "criterion": criterion_key,
            "evaluated_queries": acceptance_evaluated,
            "passed_queries": acceptance_passed,
            "failed_queries": acceptance_failed,
            "status": (
                "not_evaluated"
                if acceptance_evaluated == 0
                else "pass" if acceptance_failed == 0 else "fail"
            ),
            "does_not_allow_default_promotion": True,
        },
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
        baseline["measurement_conditions"]["review_intent"] = dict(review_condition)
        baseline["does_not_establish"].extend([
            "Review-intent metrics do not establish improvement for unmeasured query classes.",
            "This opt-in baseline does not establish readiness for default promotion.",
        ])
    return baseline


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_canonical_goldset(path: Path) -> List[Dict[str, Any]]:
    try:
        import jsonschema
    except ImportError as exc:
        raise SnapshotRetrievalMeasurementError(
            "canonical_validation_unavailable",
            "jsonschema is required when the canonical review goldset is present",
        ) from exc
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        schema = json.loads(GOLDSET_CONTRACT_PATH.read_text(encoding="utf-8"))
        jsonschema.Draft7Validator.check_schema(schema)
        jsonschema.validate(instance=raw, schema=schema)
        return normalize_review_queries(raw)
    except (OSError, ValueError, json.JSONDecodeError, jsonschema.SchemaError, jsonschema.ValidationError) as exc:
        raise SnapshotRetrievalMeasurementError(
            "canonical_goldset_invalid", str(exc)
        ) from exc


def _enrich_snapshot_report(
    report: Dict[str, Any],
    baseline: Dict[str, Any],
    *,
    benchmark: Dict[str, Any],
) -> Dict[str, Any]:
    metrics = report.setdefault("metrics", {})
    baseline_metrics = baseline["metrics"]
    for key in (
        "question_hits",
        "question_misses",
        f"question_recall@{baseline['k']}",
        "expected_target_total",
        "expected_target_hits",
        "expected_target_misses",
        f"expected_target_recall@{baseline['k']}",
    ):
        metrics[key] = baseline_metrics[key]
    for category, additions in baseline["categories"].items():
        metrics.setdefault("categories", {}).setdefault(category, {}).update({
            key: value
            for key, value in additions.items()
            if key.startswith("expected_target_") or key.startswith("question_recall@")
        })
    for detail, query_record in zip(report.get("details", []), baseline["queries"]):
        detail.update({
            "question_hit": query_record["question_hit"],
            "expected_target_total": query_record["expected_target_total"],
            "expected_target_hits": query_record["expected_target_hits"],
            "expected_target_misses": query_record["expected_target_misses"],
            f"expected_target_recall@{baseline['k']}": query_record[f"expected_target_recall@{baseline['k']}"],
            "expected_targets": query_record["expected_targets"],
        })
        if "acceptance" in query_record:
            detail["acceptance"] = query_record["acceptance"]
    report["benchmark"] = benchmark
    report["review_measurement"] = {
        "version": baseline["version"],
        "metrics": baseline_metrics,
        "categories": baseline["categories"],
        "acceptance": baseline["acceptance"],
        "miss_taxonomy_summary": baseline["miss_taxonomy_summary"],
        "miss_diagnostics": baseline["miss_diagnostics"],
        "does_not_establish": baseline["does_not_establish"],
    }
    report["claim_boundaries"]["does_not_prove"].extend([
        "Question recall and expected-target recall do not establish review completeness.",
        "This snapshot measurement does not authorize default retrieval promotion.",
    ])
    return report


def run_snapshot_retrieval_evaluation(
    index_path: Path,
    *,
    repo_root: Optional[Path],
    generic_queries_path: Optional[Path],
    k: int = 10,
    chunk_index_path: Optional[Path] = None,
    canonical_path: Optional[Path] = None,
    citation_path: Optional[Path] = None,
) -> Optional[Dict[str, Any]]:
    """Run the truthful snapshot benchmark without silently changing ranking.

    A valid repository-local review goldset is canonical. If it exists but is
    invalid, evaluation fails closed rather than falling back to the generic
    sample. If no canonical goldset exists, the generic sample remains available
    but is explicitly noncanonical and cannot support promotion.
    """
    resolved_root = Path(repo_root).resolve() if repo_root is not None else None
    canonical_goldset = (
        resolved_root / CANONICAL_REVIEW_GOLDSET
        if resolved_root is not None
        else None
    )
    if canonical_goldset is not None and canonical_goldset.is_file():
        review_queries = _validate_canonical_goldset(canonical_goldset)
        excluded_paths, path_exclusions = _resolve_goldset_exclusion(
            canonical_goldset, resolved_root
        )
        try:
            report = do_eval(
                Path(index_path),
                canonical_goldset,
                k,
                is_json_mode=True,
                excluded_paths=excluded_paths,
                review_intent=False,
            )
        except Exception as exc:
            raise SnapshotRetrievalMeasurementError(
                "canonical_measurement_failed", str(exc)
            ) from exc
        if report is None:
            raise SnapshotRetrievalMeasurementError(
                "canonical_measurement_failed", "evaluation returned no report"
            )
        calibrator = RetrievalEvalDiagnosticsCalibrator(
            index_path=Path(chunk_index_path) if chunk_index_path is not None else None,
            canonical_path=Path(canonical_path) if canonical_path is not None else None,
            citation_path=Path(citation_path) if citation_path is not None else None,
        )
        baseline = build_review_retrieval_baseline(
            report,
            k=k,
            calibrator=calibrator,
            goldset_path=CANONICAL_REVIEW_GOLDSET,
            path_exclusions=path_exclusions,
            review_queries=review_queries,
        )
        acceptance_status = baseline["acceptance"]["status"]
        reasons = ["default_promotion_requires_separate_comparative_decision"]
        if acceptance_status != "pass":
            reasons.append("canonical_acceptance_not_met")
        benchmark = {
            "kind": "repository_review_goldset",
            "scope": "repository_specific",
            "canonical": True,
            "query_source": CANONICAL_REVIEW_GOLDSET.as_posix(),
            "query_source_sha256": _sha256(canonical_goldset),
            "contract": {"id": "review-retrieval-goldset", "version": "v1"},
            "validation_status": "pass",
            "evaluation_mode": "default_lexical",
            "default_promotion_allowed": False,
            "promotion_status": "blocked",
            "promotion_block_reasons": reasons,
            "does_not_establish": [
                "The canonical benchmark measures only the committed review questions.",
                "Passing thresholds would not establish review completeness.",
                "Snapshot diagnostics do not authorize a retrieval implementation change.",
            ],
        }
        return _enrich_snapshot_report(report, baseline, benchmark=benchmark)

    if generic_queries_path is None or not Path(generic_queries_path).is_file():
        return None
    generic_path = Path(generic_queries_path)
    report = do_eval(Path(index_path), generic_path, k, is_json_mode=True)
    if report is None:
        return None
    report["benchmark"] = {
        "kind": "generic_example",
        "scope": "generic_diagnostic_sample",
        "canonical": False,
        "query_source": generic_path.name,
        "query_source_sha256": _sha256(generic_path),
        "validation_status": "not_applicable",
        "evaluation_mode": "default_lexical",
        "default_promotion_allowed": False,
        "promotion_status": "blocked",
        "promotion_block_reasons": [
            "repository_specific_goldset_missing",
            "generic_example_is_not_promotion_evidence",
        ],
        "does_not_establish": [
            "This generic example is diagnostic only.",
            "It does not measure repository-specific review quality.",
            "It cannot mask or replace a repository-specific canonical benchmark.",
        ],
    }
    report["claim_boundaries"]["does_not_prove"].append(
        "The generic example does not establish repository-specific retrieval quality."
    )
    return report

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
