"""Fixed per-language benchmark for SCIP adapter navigation records."""
from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from merger.repoground.core._scip_adapter_common import (
    BENCHMARK_DOES_NOT_ESTABLISH,
    BENCHMARK_KIND,
    BENCHMARK_VERSION,
    KIND,
    VERSION,
    _sequence,
    _text,
)


def benchmark_identity(record: Mapping[str, Any]) -> dict[str, Any]:
    """Return the stable, goldset-facing identity of one adapter record."""
    source = record["source"]
    source_range = source["range"]
    return {
        "record_type": record["record_type"],
        "relation": record["relation"],
        "symbol": record["symbol"],
        "target_symbol": record.get("target_symbol"),
        "path": source["path"],
        "start_line": source_range["start_line"],
    }


def _metric(numerator: int, denominator: int) -> float:
    return 1.0 if denominator == 0 else numerator / denominator


def _identity_key(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _threshold(value: Any, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be numeric")
    result = float(value)
    if result < 0.0 or result > 1.0:
        raise ValueError(f"{field} must be between 0 and 1")
    return result


def _artifact_status(artifact: Mapping[str, Any]) -> str:
    status = artifact.get("status")
    if status not in {"available", "degraded"}:
        raise ValueError("artifact status must be available or degraded")
    return status


def _actual_benchmark_sets(
    artifact: Mapping[str, Any],
) -> dict[str, set[str]]:
    actual_by_language: dict[str, set[str]] = {}
    for record in _sequence(artifact.get("records")):
        if not isinstance(record, Mapping):
            raise ValueError("artifact record is not an object")
        language = _text(record.get("language"))
        if language is None:
            raise ValueError("artifact record language is missing")
        actual_by_language.setdefault(language.casefold(), set()).add(
            _identity_key(benchmark_identity(record))
        )
    return actual_by_language


def _expected_benchmark_sets(
    expected_by_language: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, set[str]]:
    if not expected_by_language:
        raise ValueError("goldset must contain at least one language")
    expected_sets: dict[str, set[str]] = {}
    for raw_language, expected in expected_by_language.items():
        language = _text(raw_language)
        if language is None:
            raise ValueError("goldset language is invalid")
        normalized_language = language.casefold()
        if normalized_language in expected_sets:
            raise ValueError("goldset languages must be unique after case folding")
        if not isinstance(expected, Sequence) or isinstance(expected, (str, bytes)):
            raise ValueError("goldset language entries must be a sequence")
        if not expected:
            raise ValueError("goldset language entries must not be empty")
        identities: set[str] = set()
        for item in expected:
            if not isinstance(item, Mapping):
                raise ValueError("goldset identity must be an object")
            identities.add(_identity_key(item))
        expected_sets[normalized_language] = identities
    return expected_sets


def _unbenchmarked_result(actual: set[str]) -> dict[str, Any]:
    return {
        "status": "unbenchmarked",
        "true_positive": 0,
        "false_positive": len(actual),
        "false_negative": 0,
        "precision": 0.0 if actual else 1.0,
        "recall": 0.0,
        "passed": False,
    }


def _language_result(
    actual: set[str],
    expected: set[str],
    *,
    precision_threshold: float,
    recall_threshold: float,
) -> dict[str, Any]:
    true_positive = len(actual & expected)
    false_positive = len(actual - expected)
    false_negative = len(expected - actual)
    precision = _metric(true_positive, true_positive + false_positive)
    recall = _metric(true_positive, true_positive + false_negative)
    passed = precision >= precision_threshold and recall >= recall_threshold
    return {
        "status": "pass" if passed else "fail",
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "precision": precision,
        "recall": recall,
        "passed": passed,
    }


def _evaluate_languages(
    actual_by_language: Mapping[str, set[str]],
    expected_sets: Mapping[str, set[str]],
    *,
    precision_threshold: float,
    recall_threshold: float,
) -> tuple[dict[str, Any], list[str], list[str], list[str]]:
    per_language: dict[str, Any] = {}
    eligible: list[str] = []
    unbenchmarked: list[str] = []
    failed: list[str] = []
    for language in sorted(set(actual_by_language) | set(expected_sets)):
        actual = actual_by_language.get(language, set())
        expected = expected_sets.get(language)
        if expected is None:
            unbenchmarked.append(language)
            per_language[language] = _unbenchmarked_result(actual)
            continue
        result = _language_result(
            actual,
            expected,
            precision_threshold=precision_threshold,
            recall_threshold=recall_threshold,
        )
        per_language[language] = result
        (eligible if result["passed"] else failed).append(language)
    return per_language, eligible, unbenchmarked, failed


def _benchmark_status(
    artifact_status: str,
    failed: list[str],
    unbenchmarked: list[str],
) -> str:
    if failed:
        return "fail"
    if artifact_status == "degraded" or unbenchmarked:
        return "warn"
    return "pass"


def evaluate_scip_adapter(
    artifact: Mapping[str, Any],
    expected_by_language: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    minimum_precision: float = 0.97,
    minimum_recall: float = 0.95,
) -> dict[str, Any]:
    """Evaluate fixed per-language navigation identities without promoting them."""
    if artifact.get("kind") != KIND or artifact.get("version") != VERSION:
        raise ValueError("artifact is not a SCIP symbol-relations v1 artifact")
    if not isinstance(expected_by_language, Mapping):
        raise TypeError("expected_by_language must be a mapping")
    artifact_status = _artifact_status(artifact)
    precision_threshold = _threshold(minimum_precision, field="minimum_precision")
    recall_threshold = _threshold(minimum_recall, field="minimum_recall")
    per_language, eligible, unbenchmarked, failed = _evaluate_languages(
        _actual_benchmark_sets(artifact),
        _expected_benchmark_sets(expected_by_language),
        precision_threshold=precision_threshold,
        recall_threshold=recall_threshold,
    )
    status = _benchmark_status(artifact_status, failed, unbenchmarked)
    source = artifact.get("source")
    source = source if isinstance(source, Mapping) else {}
    return {
        "kind": BENCHMARK_KIND,
        "version": BENCHMARK_VERSION,
        "status": status,
        "artifact_status": artifact_status,
        "artifact_source": {
            "index_sha256": source.get("index_sha256"),
            "repository_commit": source.get("repository_commit"),
        },
        "thresholds": {
            "minimum_precision": precision_threshold,
            "minimum_recall": recall_threshold,
        },
        "per_language": per_language,
        "eligible_languages": eligible,
        "unbenchmarked_languages": unbenchmarked,
        "failed_languages": failed,
        "consumer_enablement": {
            "eligible_for_review": status == "pass" and bool(eligible),
            "default_promoted": False,
        },
        "does_not_establish": list(BENCHMARK_DOES_NOT_ESTABLISH),
    }
