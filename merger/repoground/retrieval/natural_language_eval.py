"""Paired multilingual natural-language retrieval evaluation for T019."""

from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable, Mapping

DOES_NOT_ESTABLISH = [
    "semantic_truth",
    "retrieval_completeness",
    "repository_understanding",
    "answer_correctness",
    "test_sufficiency",
    "merge_readiness",
]


def load_goldset(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("natural-language goldset must be a JSON object")
    return value


def _validate_goldset_case(
    case: object,
    *,
    index: int,
    required_categories: set[str],
    ids: set[str],
    observed_categories: set[str],
    observed_languages: set[str],
) -> list[str]:
    label = f"cases[{index}]"
    if not isinstance(case, Mapping):
        return [f"{label} must be an object"]
    errors: list[str] = []
    case_id = case.get("id")
    if not isinstance(case_id, str) or not case_id:
        errors.append(f"{label}.id is required")
    elif case_id in ids:
        errors.append(f"duplicate case id: {case_id}")
    else:
        ids.add(case_id)
    query = case.get("query")
    if not isinstance(query, str) or not query.strip():
        errors.append(f"{label}.query is required")
    language = case.get("language")
    if not isinstance(language, str) or not language:
        errors.append(f"{label}.language is required")
    else:
        observed_languages.add(language)
    category = case.get("category")
    if category not in required_categories:
        errors.append(f"{label}.category is invalid")
    else:
        observed_categories.add(str(category))
    expected = case.get("expected_paths")
    valid_expected = isinstance(expected, list) and all(
        isinstance(item, str) and item for item in expected
    )
    if not valid_expected:
        errors.append(f"{label}.expected_paths must contain strings")
    elif category == "true_miss" and expected:
        errors.append(f"{label} true_miss must have no expected paths")
    elif category != "true_miss" and not expected:
        errors.append(f"{label} non-miss case requires expected paths")
    return errors


def validate_goldset(goldset: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if goldset.get("kind") != "repoground.natural_language_retrieval_goldset":
        errors.append("goldset kind is invalid")
    if goldset.get("version") != "1.0":
        errors.append("goldset version is invalid")
    cases = goldset.get("cases")
    if not isinstance(cases, list) or not cases:
        return errors + ["goldset cases must be a non-empty array"]
    required_categories = {
        "exact_identifier",
        "paraphrase",
        "synonym",
        "compound",
        "true_miss",
    }
    observed_categories: set[str] = set()
    observed_languages: set[str] = set()
    ids: set[str] = set()
    for index, case in enumerate(cases):
        errors.extend(
            _validate_goldset_case(
                case,
                index=index,
                required_categories=required_categories,
                ids=ids,
                observed_categories=observed_categories,
                observed_languages=observed_languages,
            )
        )
    missing_categories = sorted(required_categories - observed_categories)
    if missing_categories:
        errors.append("missing categories: " + ", ".join(missing_categories))
    if len(observed_languages) < 2:
        errors.append("goldset must contain at least two languages")
    return errors


def _match_rank(paths: list[str], expected: list[str]) -> int | None:
    for rank, path in enumerate(paths, start=1):
        if any(path == target or path.endswith(target) for target in expected):
            return rank
    return None


def _route_metrics(
    cases: list[Mapping[str, Any]],
    runner: Callable[[str, int], Mapping[str, Any]],
    k: int,
) -> dict[str, Any]:
    target_total = 0
    target_hits = 0
    reciprocal_ranks: list[float] = []
    latencies: list[float] = []
    context_bytes = 0
    tool_calls = 0
    misses: Counter[str] = Counter()
    per_case: list[dict[str, Any]] = []
    by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_language: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for case in cases:
        output = dict(runner(str(case["query"]), k))
        paths = [str(path) for path in output.get("paths") or []][:k]
        expected = list(case["expected_paths"])
        latency = float(output.get("latency_ms") or 0.0)
        latencies.append(latency)
        context_bytes += int(output.get("context_bytes") or 0)
        tool_calls += int(output.get("tool_calls") or 0)
        error = output.get("error")
        rank = _match_rank(paths, expected) if expected else None
        if error:
            misses["route_error"] += 1
        if expected:
            target_total += 1
            if rank is None:
                misses["target_exists_not_in_top_k"] += 1
                reciprocal_ranks.append(0.0)
            else:
                target_hits += 1
                reciprocal_ranks.append(1.0 / rank)
        elif paths:
            misses["false_positive_on_true_miss"] += 1
        record = {
            "id": case["id"],
            "category": case["category"],
            "language": case["language"],
            "rank": rank,
            "returned_paths": paths,
            "error": error,
        }
        per_case.append(record)
        by_category[str(case["category"])].append(record)
        by_language[str(case["language"])].append(record)
    recall = target_hits / target_total if target_total else 0.0
    mrr = statistics.fmean(reciprocal_ranks) if reciprocal_ranks else 0.0
    return {
        "recall_at_k": round(recall, 6),
        "mrr": round(mrr, 6),
        "target_hits": target_hits,
        "target_total": target_total,
        "miss_taxonomy": dict(sorted(misses.items())),
        "latency_ms": {
            "median": round(statistics.median(latencies), 6) if latencies else 0.0,
            "maximum": round(max(latencies), 6) if latencies else 0.0,
        },
        "context_bytes": context_bytes,
        "tool_calls": tool_calls,
        "categories": {
            key: {
                "case_count": len(records),
                "hits": sum(item["rank"] is not None for item in records),
            }
            for key, records in sorted(by_category.items())
        },
        "languages": {
            key: {
                "case_count": len(records),
                "hits": sum(item["rank"] is not None for item in records),
            }
            for key, records in sorted(by_language.items())
        },
        "cases": per_case,
    }


def evaluate_paired_routes(
    goldset: Mapping[str, Any],
    *,
    baseline_runner: Callable[[str, int], Mapping[str, Any]],
    candidate_runner: Callable[[str, int], Mapping[str, Any]],
    k: int = 10,
    max_latency_ratio: float = 2.0,
    max_context_bytes_ratio: float = 1.25,
    max_tool_calls_ratio: float = 1.0,
    bindings: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    errors = validate_goldset(goldset)
    if errors:
        raise ValueError("invalid natural-language goldset: " + "; ".join(errors))
    if not isinstance(k, int) or isinstance(k, bool) or k < 1:
        raise ValueError("k must be a positive integer")
    cases = list(goldset["cases"])
    baseline = _route_metrics(cases, baseline_runner, k)
    candidate = _route_metrics(cases, candidate_runner, k)
    baseline_latency = max(baseline["latency_ms"]["median"], 0.001)
    baseline_bytes = max(baseline["context_bytes"], 1)
    baseline_calls = max(baseline["tool_calls"], 1)
    gates = [
        {
            "name": "recall_non_regression",
            "passed": candidate["recall_at_k"] >= baseline["recall_at_k"],
        },
        {"name": "mrr_non_regression", "passed": candidate["mrr"] >= baseline["mrr"]},
        {
            "name": "no_new_failure_class",
            "passed": set(candidate["miss_taxonomy"]) <= set(baseline["miss_taxonomy"]),
        },
        {
            "name": "latency_bound",
            "passed": candidate["latency_ms"]["median"]
            <= baseline_latency * max_latency_ratio,
        },
        {
            "name": "context_bytes_bound",
            "passed": candidate["context_bytes"]
            <= baseline_bytes * max_context_bytes_ratio,
        },
        {
            "name": "tool_calls_bound",
            "passed": candidate["tool_calls"] <= baseline_calls * max_tool_calls_ratio,
        },
    ]
    passed = all(item["passed"] for item in gates)
    return {
        "kind": "repoground.natural_language_retrieval_evaluation",
        "version": "1.0",
        "status": "passed" if passed else "blocked",
        "k": k,
        "goldset_id": goldset.get("id"),
        "baseline": baseline,
        "candidate": candidate,
        "gates": gates,
        "bindings": dict(bindings or {}),
        "default_promotion_allowed": False,
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }
