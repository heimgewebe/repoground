"""Reproducible quality/cost evaluation for Rust/Bash structure adapters."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import re
import statistics
import subprocess
import time
import tracemalloc
from collections import Counter, defaultdict
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from merger.repoground.core.bounded_artifact_read import (
    read_stable_regular_file_bytes,
)
from merger.repoground.core.language_structure import build_language_structure_document

KIND = "repoground.language_structure_benchmark"
VERSION = "1.0"
GOLDSET_KIND = "repoground.language_structure_goldset"
GOLDSET_VERSION = "1.0"
CASE_CLASSES = frozenset({"positive", "ambiguous", "dynamic", "null"})
_REVISION_RE = re.compile(r"^[a-f0-9]{40}(?:[a-f0-9]{24})?$")
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_MAX_GOLDSET_BYTES = 4 * 1024 * 1024
_MAX_BENEFIT_BYTES = 1024 * 1024
_EXPECTED_RECORD_FIELDS = frozenset(
    {
        "language",
        "relation",
        "symbol",
        "target_symbol",
        "path",
        "start_line",
        "end_line",
        "start_character",
        "end_character",
    }
)


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _finite_rate(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    converted = float(value)
    if not math.isfinite(converted) or not 0.0 <= converted <= 1.0:
        return None
    return converted


def _finite_nonnegative(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    converted = float(value)
    if not math.isfinite(converted) or converted < 0.0:
        return None
    return converted


def _nonnegative_integer(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _valid_revision(value: Any) -> bool:
    return isinstance(value, str) and _REVISION_RE.fullmatch(value) is not None


def _read_json_object(path: Path, *, max_bytes: int, label: str) -> dict[str, Any]:
    raw, _identity, failure, detail = read_stable_regular_file_bytes(
        path, max_bytes=max_bytes
    )
    if failure is not None or raw is None:
        suffix = f": {detail}" if detail else ""
        raise ValueError(f"{label} read failed: {failure or 'unreadable'}{suffix}")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"{label} is not bounded valid UTF-8 JSON: {type(exc).__name__}"
        ) from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _validate_expected_records(
    case_id: str, language: str, expected: Any
) -> list[dict[str, Any]]:
    if not isinstance(expected, list) or not all(
        isinstance(item, dict) for item in expected
    ):
        raise ValueError(f"case {case_id}: expected_records must contain objects")
    if any(
        not _EXPECTED_RECORD_FIELDS <= set(item)
        or item.get("language") != language
        or any(
            isinstance(item.get(field), bool) or not isinstance(item.get(field), int)
            for field in (
                "start_line",
                "end_line",
                "start_character",
                "end_character",
            )
        )
        for item in expected
    ):
        raise ValueError(f"case {case_id}: expected record/range contract invalid")
    return expected


def _validate_goldset_case(
    raw_case: Any, *, seen_ids: set[str]
) -> tuple[str, str, str]:
    if not isinstance(raw_case, dict):
        raise ValueError("goldset case must be an object")
    case_id = raw_case.get("id")
    language = raw_case.get("language")
    case_class = raw_case.get("case_class")
    if not isinstance(case_id, str) or not case_id or case_id in seen_ids:
        raise ValueError("goldset case ids must be non-empty and unique")
    if language not in {"bash", "rust"}:
        raise ValueError(f"case {case_id}: language must be bash or rust")
    if case_class not in CASE_CLASSES:
        raise ValueError(f"case {case_id}: unsupported case_class")
    if not isinstance(raw_case.get("fixture_root"), str):
        raise ValueError(f"case {case_id}: fixture_root must be a string")
    expected = _validate_expected_records(
        case_id, language, raw_case.get("expected_records")
    )
    reasons = raw_case.get("expected_degradation_reasons")
    if not isinstance(reasons, list) or not all(
        isinstance(item, str) and item for item in reasons
    ):
        raise ValueError(
            f"case {case_id}: expected_degradation_reasons must contain strings"
        )
    if case_class == "null" and expected:
        raise ValueError(f"case {case_id}: true-null cases cannot expect records")
    return case_id, str(language), str(case_class)


def load_language_goldset(path: str | Path) -> dict[str, Any]:
    value = _read_json_object(Path(path), max_bytes=_MAX_GOLDSET_BYTES, label="goldset")
    if value.get("kind") != GOLDSET_KIND or value.get("version") != GOLDSET_VERSION:
        raise ValueError("unsupported language structure goldset contract")
    cases = value.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("goldset cases must be a non-empty list")
    ids: set[str] = set()
    classes: set[str] = set()
    languages: set[str] = set()
    classes_by_language: dict[str, set[str]] = defaultdict(set)
    for raw_case in cases:
        case_id, language, case_class = _validate_goldset_case(raw_case, seen_ids=ids)
        ids.add(case_id)
        classes.add(case_class)
        languages.add(language)
        classes_by_language[language].add(case_class)
    if classes != CASE_CLASSES:
        raise ValueError(
            "goldset must cover positive, ambiguous, dynamic and true-null cases"
        )
    if languages != {"bash", "rust"}:
        raise ValueError("goldset must cover Bash and Rust")
    if any(classes_by_language[language] != CASE_CLASSES for language in languages):
        raise ValueError(
            "each language must cover positive, ambiguous, dynamic and true-null cases"
        )
    return value


def _record_key(item: Mapping[str, Any], *, exact_range: bool) -> tuple[Any, ...]:
    source = item.get("source") if isinstance(item.get("source"), Mapping) else {}
    range_value = (
        source.get("range") if isinstance(source.get("range"), Mapping) else {}
    )
    key: tuple[Any, ...] = (
        item.get("language"),
        item.get("relation"),
        item.get("symbol"),
        item.get("target_symbol"),
        source.get("path"),
    )
    if not exact_range:
        return key
    return (
        *key,
        range_value.get("start_line"),
        range_value.get("end_line"),
        range_value.get("start_character"),
        range_value.get("end_character"),
    )


def _expected_key(item: Mapping[str, Any], *, exact_range: bool) -> tuple[Any, ...]:
    key: tuple[Any, ...] = (
        item.get("language"),
        item.get("relation"),
        item.get("symbol"),
        item.get("target_symbol"),
        item.get("path"),
    )
    if not exact_range:
        return key
    return (
        *key,
        item.get("start_line"),
        item.get("end_line", item.get("start_line")),
        item.get("start_character"),
        item.get("end_character"),
    )


def _counts(
    actual: Counter[tuple[Any, ...]], expected: Counter[tuple[Any, ...]]
) -> dict[str, int]:
    true_positive = sum((actual & expected).values())
    actual_count = sum(actual.values())
    expected_count = sum(expected.values())
    return {
        "true_positive": true_positive,
        "false_positive": actual_count - true_positive,
        "false_negative": expected_count - true_positive,
        "actual": actual_count,
        "expected": expected_count,
    }


def _rates(counts: Mapping[str, int]) -> dict[str, float]:
    actual = int(counts["actual"])
    expected = int(counts["expected"])
    matched = int(counts["true_positive"])
    precision = matched / actual if actual else (1.0 if not expected else 0.0)
    recall = matched / expected if expected else 1.0
    return {"precision": round(precision, 6), "recall": round(recall, 6)}


def _metric(
    actual: Counter[tuple[Any, ...]], expected: Counter[tuple[Any, ...]]
) -> dict[str, Any]:
    counts = _counts(actual, expected)
    return {**counts, **_rates(counts)}


def _metric_contract_valid(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    counts = {
        field: _nonnegative_integer(value.get(field))
        for field in (
            "true_positive",
            "false_positive",
            "false_negative",
            "actual",
            "expected",
        )
    }
    precision = _finite_rate(value.get("precision"))
    recall = _finite_rate(value.get("recall"))
    if any(item is None for item in (*counts.values(), precision, recall)):
        return False
    typed_counts = {field: int(item) for field, item in counts.items()}
    expected_rates = _rates(typed_counts)
    return (
        typed_counts["actual"]
        == typed_counts["true_positive"] + typed_counts["false_positive"]
        and typed_counts["expected"]
        == typed_counts["true_positive"] + typed_counts["false_negative"]
        and abs(float(precision) - expected_rates["precision"]) <= 0.000001
        and abs(float(recall) - expected_rates["recall"]) <= 0.000001
    )


def _true_null_observation(actual_items: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Count every emitted record; duplicate false positives remain observable."""
    return {
        "pass": not actual_items,
        "false_positive_records": len(actual_items),
    }


def _add_counts(target: dict[str, int], source: Mapping[str, Any]) -> None:
    for key in (
        "true_positive",
        "false_positive",
        "false_negative",
        "actual",
        "expected",
    ):
        target[key] += int(source[key])


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round((len(ordered) - 1) * 0.95))]


def _git_output(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
        env={
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_TERMINAL_PROMPT": "0",
        },
    )
    if completed.returncode != 0:
        raise ValueError(f"git binding check failed: {completed.stderr.strip()[:200]}")
    return completed.stdout.strip()


def _bind_source_revision(
    root: Path, *, source_revision: str, fixture_paths: list[str]
) -> None:
    if not _valid_revision(source_revision):
        raise ValueError(
            "source_revision must be a lowercase 40- or 64-character revision"
        )
    if _git_output(root, "rev-parse", "HEAD") != source_revision:
        raise ValueError("source_revision does not equal repository HEAD")
    status = _git_output(root, "status", "--porcelain")
    if status:
        raise ValueError("benchmark repository is dirty or contains untracked state")
    fixture_status = _git_output(root, "status", "--porcelain", "--", *fixture_paths)
    if fixture_status:
        raise ValueError("goldset fixture paths are dirty or untracked")


def _keep_optional(reason: str, **extra: Any) -> dict[str, Any]:
    return {
        "status": "keep_optional",
        "broad_activation_eligible": False,
        "default_promoted": False,
        "reason": reason,
        **extra,
    }


def _promotion_case_results_valid(value: Any, *, case_count: int) -> bool:
    if not isinstance(value, list) or len(value) != case_count:
        return False
    seen_ids: set[str] = set()
    for item in value:
        if not isinstance(item, Mapping):
            return False
        case_id = item.get("id")
        metrics = item.get("metrics")
        costs = item.get("costs")
        case_class = item.get("case_class")
        true_null_pass = item.get("true_null_pass")
        if (
            not isinstance(case_id, str)
            or not case_id
            or case_id in seen_ids
            or item.get("language") not in {"bash", "rust"}
            or case_class not in CASE_CLASSES
            or not isinstance(item.get("size_class"), str)
            or not isinstance(item.get("semantic_deterministic"), bool)
            or _nonnegative_integer(item.get("symbol_hits")) is None
            or _nonnegative_integer(item.get("false_positive_records")) is None
            or not isinstance(metrics, Mapping)
            or set(metrics) != {"symbol", "relations", "ranges"}
            or not all(_metric_contract_valid(metrics[lane]) for lane in metrics)
            or not isinstance(costs, Mapping)
            or _finite_nonnegative(costs.get("latency_ms")) is None
            or _nonnegative_integer(costs.get("peak_memory_bytes")) is None
            or _nonnegative_integer(costs.get("index_size_bytes")) is None
            or (
                not isinstance(true_null_pass, bool)
                if case_class == "null"
                else true_null_pass is not None
            )
        ):
            return False
        seen_ids.add(case_id)
    return True


def _promotion_report_binding(
    report: Mapping[str, Any],
) -> tuple[str, str, int] | None:
    source_revision = report.get("source_revision")
    goldset_sha256 = report.get("goldset_sha256")
    case_count = _nonnegative_integer(report.get("case_count"))
    case_results = report.get("case_results")
    fixture_binding = report.get("fixture_binding")
    valid = (
        report.get("kind") == KIND
        and report.get("version") == VERSION
        and _valid_revision(source_revision)
        and isinstance(goldset_sha256, str)
        and _SHA256_RE.fullmatch(goldset_sha256) is not None
        and case_count is not None
        and case_count >= 1
        and _promotion_case_results_valid(case_results, case_count=case_count)
        and isinstance(fixture_binding, Mapping)
        and isinstance(fixture_binding.get("repository_root"), str)
        and bool(fixture_binding.get("repository_root"))
        and fixture_binding.get("git_head_equals_source_revision") is True
        and fixture_binding.get("repository_worktree_clean") is True
        and fixture_binding.get("fixture_paths_clean") is True
        and fixture_binding.get("network_used") is False
    )
    if not valid:
        return None
    return str(source_revision), goldset_sha256, case_count


def decide_language_adapter_promotion(
    report: Mapping[str, Any], *, agent_benefit: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Fail closed until verified component-delta agent evidence exists."""
    try:
        if _promotion_report_binding(report) is None:
            return _keep_optional("benchmark_revision_binding_invalid")
        if not isinstance(agent_benefit, Mapping):
            return _keep_optional("revision_bound_agent_benefit_missing")
        return _keep_optional("verified_component_delta_agent_benefit_missing")
    except (KeyError, TypeError, ValueError, OverflowError):
        return _keep_optional("promotion_input_malformed")


def _case_fixture_root(root: Path, raw_case: Any) -> tuple[Mapping[str, Any], Path]:
    if not isinstance(raw_case, Mapping):
        raise ValueError("goldset case must be an object")
    fixture = raw_case.get("fixture_root")
    if not isinstance(fixture, str):
        raise ValueError("fixture_root must be a string")
    fixture_root = (root / fixture).resolve()
    try:
        fixture_root.relative_to(root)
    except ValueError as exc:
        raise ValueError("fixture_root escapes repository") from exc
    if not fixture_root.is_dir():
        raise ValueError(f"fixture_root missing: {fixture}")
    return raw_case, fixture_root


def evaluate_language_structure_goldset(
    goldset: Mapping[str, Any],
    *,
    repo_root: str | Path,
    source_revision: str,
    agent_benefit: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Measure semantic quality separately from environment-dependent resource cost."""
    root = Path(repo_root).resolve()
    cases = goldset.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("goldset cases must be a non-empty list")
    fixture_paths = [
        str(case.get("fixture_root"))
        for case in cases
        if isinstance(case, Mapping) and isinstance(case.get("fixture_root"), str)
    ]
    if len(fixture_paths) != len(cases):
        raise ValueError("every goldset case requires fixture_root")
    _bind_source_revision(
        root, source_revision=source_revision, fixture_paths=fixture_paths
    )
    goldset_sha256 = _sha256(goldset)
    latencies: list[float] = []
    peaks: list[int] = []
    sizes: list[int] = []
    case_results: list[dict[str, Any]] = []
    deterministic = True
    all_expected_degradations_present = True
    no_unexpected_degradations = True
    totals: dict[str, dict[str, int]] = defaultdict(
        lambda: {
            "true_positive": 0,
            "false_positive": 0,
            "false_negative": 0,
            "actual": 0,
            "expected": 0,
        }
    )
    language_totals: dict[str, dict[str, dict[str, int]]] = defaultdict(
        lambda: defaultdict(
            lambda: {
                "true_positive": 0,
                "false_positive": 0,
                "false_negative": 0,
                "actual": 0,
                "expected": 0,
            }
        )
    )
    language_costs: dict[str, dict[str, list[Any]]] = defaultdict(
        lambda: {"latencies": [], "peaks": [], "sizes": []}
    )
    true_null_cases = 0
    true_null_passes = 0
    true_null_false_positives = 0

    for raw_case in cases:
        raw_case, fixture_root = _case_fixture_root(root, raw_case)
        kwargs = {
            "repository_commit": source_revision,
            "bundle_manifest": "goldset.bundle.manifest.json",
            "canonical_dump_index_sha256": goldset_sha256,
            "run_id": str(raw_case.get("id")),
        }
        tracemalloc.start()
        started = time.perf_counter()
        document = build_language_structure_document(fixture_root, **kwargs)
        latency = (time.perf_counter() - started) * 1000.0
        _current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        repeated = build_language_structure_document(fixture_root, **kwargs)
        semantic_keys = (
            "status",
            "source",
            "languages",
            "records",
            "degradations",
            "promotion",
        )
        semantic = {key: document.get(key) for key in semantic_keys}
        repeated_semantic = {key: repeated.get(key) for key in semantic_keys}
        case_deterministic = semantic == repeated_semantic
        deterministic = deterministic and case_deterministic
        payload_size = len(_canonical_bytes(document))
        latencies.append(latency)
        peaks.append(peak)
        sizes.append(payload_size)

        expected_items = raw_case.get("expected_records")
        if not isinstance(expected_items, list):
            raise ValueError("expected_records must be a list")
        actual_items = [
            item for item in document.get("records", []) if isinstance(item, Mapping)
        ]
        actual_symbol = Counter(
            _record_key(item, exact_range=False)
            for item in actual_items
            if item.get("relation") == "definition"
        )
        expected_symbol = Counter(
            _expected_key(item, exact_range=False)
            for item in expected_items
            if item.get("relation") == "definition"
        )
        actual_relations = Counter(
            _record_key(item, exact_range=False)
            for item in actual_items
            if item.get("relation") != "definition"
        )
        expected_relations = Counter(
            _expected_key(item, exact_range=False)
            for item in expected_items
            if item.get("relation") != "definition"
        )
        actual_ranges = Counter(
            _record_key(item, exact_range=True) for item in actual_items
        )
        expected_ranges = Counter(
            _expected_key(item, exact_range=True) for item in expected_items
        )
        metrics = {
            "symbol": _metric(actual_symbol, expected_symbol),
            "relations": _metric(actual_relations, expected_relations),
            "ranges": _metric(actual_ranges, expected_ranges),
        }
        language = str(raw_case.get("language"))
        language_costs[language]["latencies"].append(latency)
        language_costs[language]["peaks"].append(peak)
        language_costs[language]["sizes"].append(payload_size)
        for lane, metric in metrics.items():
            _add_counts(totals[lane], metric)
            _add_counts(language_totals[language][lane], metric)

        expected_reasons = set(raw_case.get("expected_degradation_reasons") or [])
        observed_reasons = {
            str(item.get("reason"))
            for item in document.get("degradations", [])
            if isinstance(item, Mapping)
        }
        missing_reasons = sorted(expected_reasons - observed_reasons)
        unexpected_reasons = sorted(observed_reasons - expected_reasons)
        all_expected_degradations_present = (
            all_expected_degradations_present and not missing_reasons
        )
        no_unexpected_degradations = (
            no_unexpected_degradations and not unexpected_reasons
        )
        false_positive_records = (
            metrics["symbol"]["false_positive"] + metrics["relations"]["false_positive"]
        )
        is_true_null = raw_case.get("case_class") == "null"
        true_null_observation = _true_null_observation(actual_items)
        true_null_pass = is_true_null and true_null_observation["pass"]
        if is_true_null:
            true_null_cases += 1
            true_null_passes += int(true_null_pass)
            true_null_false_positives += int(
                true_null_observation["false_positive_records"]
            )
        case_results.append(
            {
                "id": raw_case.get("id"),
                "language": language,
                "size_class": raw_case.get("size_class"),
                "case_class": raw_case.get("case_class"),
                "metrics": metrics,
                "symbol_hits": metrics["symbol"]["true_positive"],
                "false_positive_records": false_positive_records,
                "true_null_pass": true_null_pass if is_true_null else None,
                "semantic_deterministic": case_deterministic,
                "degradations": {
                    "expected": sorted(expected_reasons),
                    "observed": sorted(observed_reasons),
                    "missing": missing_reasons,
                    "unexpected": unexpected_reasons,
                },
                "costs": {
                    "latency_ms": round(latency, 6),
                    "peak_memory_bytes": peak,
                    "index_size_bytes": payload_size,
                },
            }
        )

    def summarized(raw: Mapping[str, Mapping[str, int]]) -> dict[str, Any]:
        return {
            lane: {**counts, **_rates(counts)} for lane, counts in sorted(raw.items())
        }

    per_language = {
        language: summarized(lanes)
        for language, lanes in sorted(language_totals.items())
    }

    def summarized_costs(
        latency_values: list[float], peak_values: list[int], size_values: list[int]
    ) -> dict[str, Any]:
        return {
            "latency_ms_median": round(statistics.median(latency_values), 6),
            "latency_ms_p95": round(_p95(latency_values), 6),
            "peak_memory_bytes_max": max(peak_values, default=0),
            "index_size_bytes_total": sum(size_values),
            "index_size_bytes_max": max(size_values, default=0),
        }

    per_language_costs = {
        language: summarized_costs(
            list(values["latencies"]),
            list(values["peaks"]),
            list(values["sizes"]),
        )
        for language, values in sorted(language_costs.items())
    }
    logical_cpu_count = os.cpu_count()
    if not isinstance(logical_cpu_count, int) or logical_cpu_count < 1:
        logical_cpu_count = None
    report: dict[str, Any] = {
        "kind": KIND,
        "version": VERSION,
        "goldset_id": goldset.get("id"),
        "goldset_sha256": goldset_sha256,
        "source_revision": source_revision,
        "fixture_binding": {
            "repository_root": str(root),
            "git_head_equals_source_revision": True,
            "repository_worktree_clean": True,
            "fixture_paths_clean": True,
            "network_used": False,
        },
        "case_count": len(cases),
        "case_results": case_results,
        "metrics": {
            "per_language": per_language,
            "aggregate": summarized(totals),
            "separation": [
                "symbol_hits_and_precision_recall",
                "relation_precision_recall",
                "range_exact_precision_recall",
            ],
        },
        "true_nulls": {
            "case_count": true_null_cases,
            "pass_count": true_null_passes,
            "false_positive_records": true_null_false_positives,
        },
        "degradation_expectations": {
            "all_expected_present": all_expected_degradations_present,
            "no_unexpected": no_unexpected_degradations,
            "exact_match": (
                all_expected_degradations_present and no_unexpected_degradations
            ),
        },
        "costs": {
            "latency_ms_median": round(statistics.median(latencies), 6)
            if latencies
            else 0.0,
            "latency_ms_p95": round(_p95(latencies), 6),
            "peak_memory_bytes_max": max(peaks, default=0),
            "index_size_bytes_total": sum(sizes),
            "index_size_bytes_max": max(sizes, default=0),
            "per_language": per_language_costs,
            "runtime_environment": {
                "python_implementation": platform.python_implementation().lower()
                or "unknown",
                "python_version": platform.python_version() or "unknown",
                "platform_system": platform.system().lower() or "unknown",
                "platform_machine": platform.machine().lower() or "unknown",
                "logical_cpu_count": logical_cpu_count,
            },
            "runtime_measurements_are_environment_observations": True,
        },
        "determinism": {
            "semantic_projection_repeated_equal": deterministic,
            "runtime_metrics_excluded_from_determinism_claim": True,
        },
        "does_not_establish": [
            "complete_rust_semantics",
            "complete_bash_semantics",
            "runtime_behavior",
            "cross_machine_latency_equivalence",
            "agent_benefit_without_verified_component_delta_evaluation",
            "default_activation",
        ],
    }
    report["promotion"] = decide_language_adapter_promotion(
        report, agent_benefit=agent_benefit
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the local offline T021 language-structure goldset"
    )
    parser.add_argument("--goldset", required=True)
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument(
        "--agent-benefit",
        help=(
            "legacy external benefit input; retained for compatibility but cannot "
            "authorize promotion until the verified component-delta harness exists"
        ),
    )
    args = parser.parse_args(argv)
    goldset = load_language_goldset(args.goldset)
    agent_benefit = None
    if args.agent_benefit:
        raw, _identity, failure, detail = read_stable_regular_file_bytes(
            Path(args.agent_benefit), max_bytes=_MAX_BENEFIT_BYTES
        )
        if failure is not None or raw is None:
            suffix = f": {detail}" if detail else ""
            raise ValueError(
                f"agent benefit read failed: {failure or 'unreadable'}{suffix}"
            )
        agent_benefit = json.loads(raw.decode("utf-8"))
    report = evaluate_language_structure_goldset(
        goldset,
        repo_root=args.repo_root,
        source_revision=args.source_revision,
        agent_benefit=agent_benefit,
    )
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "decide_language_adapter_promotion",
    "evaluate_language_structure_goldset",
    "load_language_goldset",
    "main",
]
