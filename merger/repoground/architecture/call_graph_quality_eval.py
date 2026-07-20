"""Evaluate the fixed Python call-graph quality and navigation goldset."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

from merger.repoground.core.agent_impact_eval import evaluate_agent_impact_goldset

from .call_graph import extract_python_calls


GOLDSET_KIND = "lenskit.python_call_graph_quality_goldset"
GOLDSET_VERSION = "1.0"
VALID_STATUSES = frozenset({"resolved", "candidate", "ambiguous", "unresolved"})
VALID_EVIDENCE_LEVELS = frozenset({"S0", "S1"})
VALID_RELATION_TYPES = frozenset({"calls", "constructs"})
REPO_ROOT = Path(__file__).resolve().parents[3]


class PythonCallGraphGoldsetError(ValueError):
    """The Python call-graph quality goldset is structurally invalid."""


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 0.0


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise PythonCallGraphGoldsetError(message)


def _non_empty_string(value: Any, label: str) -> str:
    _expect(
        isinstance(value, str) and bool(value),
        f"{label} must be a non-empty string",
    )
    return str(value)


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    _expect(isinstance(value, Mapping), f"{label} must be an object")
    return value


def _non_empty_list(value: Any, label: str) -> list[Any]:
    _expect(
        isinstance(value, list) and bool(value),
        f"{label} must be a non-empty list",
    )
    return list(value)


def _unique_strings(value: Any, label: str) -> list[str]:
    values = _non_empty_list(value, label)
    _expect(
        all(isinstance(item, str) and item for item in values),
        f"{label} must contain non-empty strings",
    )
    _expect(len(set(values)) == len(values), f"{label} must be unique")
    return [str(item) for item in values]


def _positive_integer(value: Any, label: str) -> int:
    _expect(
        not isinstance(value, bool) and isinstance(value, int) and value >= 1,
        f"{label} must be a positive integer",
    )
    return int(value)


def _number_between_zero_and_one(value: Any, label: str) -> float:
    _expect(
        not isinstance(value, bool) and isinstance(value, (int, float)),
        f"{label} must be numeric",
    )
    number = float(value)
    _expect(0.0 <= number <= 1.0, f"{label} must be between 0 and 1")
    return number


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PythonCallGraphGoldsetError(
            f"cannot load Python call-graph goldset: {path}"
        ) from exc
    _expect(isinstance(payload, dict), "goldset must be a JSON object")
    return dict(payload)


def _validate_thresholds(raw: Any) -> dict[str, Any]:
    thresholds = dict(_mapping(raw, "thresholds"))
    required = {
        "minimum_s1_precision",
        "minimum_target_recall",
        "minimum_context_path_reduction",
        "no_case_regression",
    }
    missing = required - set(thresholds)
    _expect(
        not missing,
        f"thresholds missing {', '.join(sorted(missing))}",
    )
    for key in (
        "minimum_s1_precision",
        "minimum_target_recall",
        "minimum_context_path_reduction",
    ):
        thresholds[key] = _number_between_zero_and_one(thresholds[key], key)
    _expect(
        thresholds["no_case_regression"] is True,
        "no_case_regression must be true",
    )
    return thresholds


def _validate_caller(case: Mapping[str, Any], case_id: str) -> None:
    _expect(
        "caller_qualified_name" in case,
        f"{case_id}.caller_qualified_name must be explicit",
    )
    caller = case["caller_qualified_name"]
    _expect(
        caller is None or (isinstance(caller, str) and bool(caller)),
        f"{case_id}.caller_qualified_name must be null or non-empty",
    )


def _validate_expected_target(
    case_id: str,
    status: str,
    evidence: str,
    target_id: Any,
) -> None:
    if status == "resolved":
        _non_empty_string(target_id, f"{case_id}.expected_target_id")
        _expect(evidence == "S1", f"{case_id}: resolved cases must expect S1")
    else:
        _expect(
            target_id is None,
            f"{case_id}: non-resolved cases must not expect a target",
        )


def _validated_case(
    raw_case: Any,
    known_ids: set[str],
) -> tuple[str, str]:
    case = _mapping(raw_case, "case")
    case_id = _non_empty_string(case.get("id"), "case id")
    _expect(case_id not in known_ids, f"duplicate case id: {case_id}")
    category = _non_empty_string(case.get("category"), f"{case_id}.category")
    _non_empty_string(case.get("path"), f"{case_id}.path")
    _non_empty_string(
        case.get("callee_expression"),
        f"{case_id}.callee_expression",
    )
    _validate_caller(case, case_id)
    status = str(case.get("expected_status"))
    evidence = str(case.get("expected_evidence_level"))
    relation = str(case.get("expected_relation_type"))
    _expect(status in VALID_STATUSES, f"{case_id}.expected_status is invalid")
    _expect(
        evidence in VALID_EVIDENCE_LEVELS,
        f"{case_id}.expected_evidence_level is invalid",
    )
    _expect(
        relation in VALID_RELATION_TYPES,
        f"{case_id}.expected_relation_type is invalid",
    )
    _non_empty_string(case.get("expected_reason"), f"{case_id}.expected_reason")
    _validate_expected_target(
        case_id,
        status,
        evidence,
        case.get("expected_target_id"),
    )
    return case_id, category


def _validate_cases(payload: Mapping[str, Any]) -> set[str]:
    cases = _non_empty_list(payload.get("cases"), "cases")
    case_ids: set[str] = set()
    observed_categories: set[str] = set()
    for raw_case in cases:
        case_id, category = _validated_case(raw_case, case_ids)
        case_ids.add(case_id)
        observed_categories.add(category)
    required_categories = set(
        _unique_strings(payload.get("required_categories"), "required_categories")
    )
    missing = required_categories - observed_categories
    _expect(
        not missing,
        "goldset missing required categories: " + ", ".join(sorted(missing)),
    )
    return case_ids


def _validated_agent_task(
    raw_task: Any,
    known_task_ids: set[str],
    case_ids: set[str],
) -> str:
    task = _mapping(raw_task, "agent task")
    task_id = _non_empty_string(task.get("id"), "agent task id")
    _expect(
        task_id not in known_task_ids,
        f"duplicate agent task id: {task_id}",
    )
    selected = _unique_strings(task.get("case_ids"), f"{task_id}.case_ids")
    unknown = set(selected) - case_ids
    _expect(
        not unknown,
        f"{task_id} references unknown cases: "
        + ", ".join(sorted(unknown)),
    )
    _unique_strings(task.get("baseline_paths"), f"{task_id}.baseline_paths")
    _positive_integer(
        task.get("baseline_tool_calls"),
        f"{task_id}.baseline_tool_calls",
    )
    return task_id


def _validate_agent_tasks(
    payload: Mapping[str, Any],
    case_ids: set[str],
) -> None:
    tasks = _non_empty_list(payload.get("agent_tasks"), "agent_tasks")
    task_ids: set[str] = set()
    for raw_task in tasks:
        task_id = _validated_agent_task(raw_task, task_ids, case_ids)
        task_ids.add(task_id)


def _validate_boundaries(payload: Mapping[str, Any]) -> None:
    _unique_strings(payload.get("does_not_establish"), "does_not_establish")


def load_python_call_graph_goldset(path: Path) -> dict[str, Any]:
    payload = _read_json_object(path)
    _expect(payload.get("kind") == GOLDSET_KIND, "unexpected goldset kind")
    _expect(
        payload.get("version") == GOLDSET_VERSION,
        "unsupported goldset version",
    )
    _non_empty_string(payload.get("fixture_root"), "fixture_root")
    thresholds = _validate_thresholds(payload.get("thresholds"))
    case_ids = _validate_cases(payload)
    _validate_agent_tasks(payload, case_ids)
    _validate_boundaries(payload)
    payload["thresholds"] = thresholds
    return payload


def _target_path(target_id: str | None) -> str | None:
    if not target_id or not target_id.startswith("py:"):
        return None
    for marker in (":async_function:", ":function:", ":class:"):
        prefix, separator, _ = target_id.partition(marker)
        if separator:
            return prefix.removeprefix("py:").replace(":", "/")
    return None


def _fixture_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    files = (candidate for candidate in root.rglob("*") if candidate.is_file())
    for path in sorted(files):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        payload = path.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


def _case_match(call: Mapping[str, Any], case: Mapping[str, Any]) -> bool:
    return (
        call.get("path") == case["path"]
        and call.get("callee_expression") == case["callee_expression"]
        and call.get("caller_qualified_name") == case["caller_qualified_name"]
    )


def _selector_error(case: Mapping[str, Any], match_count: int) -> dict[str, Any]:
    return {
        "id": case["id"],
        "category": case["category"],
        "path": case["path"],
        "callee_expression": case["callee_expression"],
        "caller_qualified_name": case["caller_qualified_name"],
        "selector_match_count": match_count,
        "expected_status": case["expected_status"],
        "actual_status": None,
        "expected_target_id": case.get("expected_target_id"),
        "actual_target_ids": [],
        "counts_as_true_positive": False,
        "counts_as_false_positive": False,
        "counts_as_false_negative": case["expected_status"] == "resolved",
        "outcome": "selector_error",
        "passed": False,
    }


def _target_ids_match(
    target_ids: list[str],
    expected_target: str | None,
) -> bool:
    if expected_target is None:
        return target_ids == []
    return target_ids == [expected_target]


def _classification(
    expected_s1: bool,
    actual_s1: bool,
    target_match: bool,
) -> tuple[str, bool, bool, bool]:
    correct_s1 = expected_s1 and actual_s1 and target_match
    false_positive = actual_s1 and not correct_s1
    false_negative = expected_s1 and not correct_s1
    if correct_s1:
        outcome = "true_positive"
    elif expected_s1 and actual_s1:
        outcome = "wrong_target"
    elif false_positive:
        outcome = "false_positive"
    elif false_negative:
        outcome = "false_negative"
    else:
        outcome = "non_s1_expected"
    return outcome, correct_s1, false_positive, false_negative


def _matched_case_result(
    call: Mapping[str, Any],
    case: Mapping[str, Any],
) -> dict[str, Any]:
    expected_target = case.get("expected_target_id")
    target_ids = list(call.get("resolved_target_ids", []))
    target_match = _target_ids_match(target_ids, expected_target)
    fields_match = (
        call.get("resolution_status") == case["expected_status"]
        and call.get("resolution_reason") == case["expected_reason"]
        and call.get("evidence_level") == case["expected_evidence_level"]
        and call.get("relation_type") == case["expected_relation_type"]
    )
    expected_s1 = case["expected_status"] == "resolved"
    actual_s1 = (
        call.get("resolution_status") == "resolved"
        and call.get("evidence_level") == "S1"
    )
    outcome, true_positive, false_positive, false_negative = _classification(
        expected_s1,
        actual_s1,
        target_match,
    )
    return {
        "id": case["id"],
        "category": case["category"],
        "path": case["path"],
        "callee_expression": case["callee_expression"],
        "caller_qualified_name": case["caller_qualified_name"],
        "selector_match_count": 1,
        "expected_status": case["expected_status"],
        "actual_status": call.get("resolution_status"),
        "expected_reason": case["expected_reason"],
        "actual_reason": call.get("resolution_reason"),
        "expected_evidence_level": case["expected_evidence_level"],
        "actual_evidence_level": call.get("evidence_level"),
        "expected_relation_type": case["expected_relation_type"],
        "actual_relation_type": call.get("relation_type"),
        "expected_target_id": expected_target,
        "actual_target_ids": target_ids,
        "source_range_ref": call.get("range_ref"),
        "counts_as_true_positive": true_positive,
        "counts_as_false_positive": false_positive,
        "counts_as_false_negative": false_negative,
        "outcome": outcome,
        "passed": fields_match and target_match,
    }


def _evaluate_case(
    calls: Sequence[Mapping[str, Any]],
    case: Mapping[str, Any],
) -> dict[str, Any]:
    matches = [call for call in calls if _case_match(call, case)]
    if len(matches) != 1:
        return _selector_error(case, len(matches))
    return _matched_case_result(matches[0], case)


def _impact_paths(
    task: Mapping[str, Any],
    case_results: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    paths: set[str] = set()
    for case_id in task["case_ids"]:
        case = case_results[case_id]
        paths.add(str(case["path"]))
        target_path = _target_path(case.get("expected_target_id"))
        if target_path:
            paths.add(target_path)
    return sorted(paths)


def _navigation_goldset(
    tasks: Sequence[Mapping[str, Any]],
    by_id: Mapping[str, Mapping[str, Any]],
    minimum_reduction: float,
) -> dict[str, Any]:
    return {
        "id": "python-call-graph-navigation-tasks-v1",
        "minimum_target_recall_advantage": 1.0,
        "minimum_context_path_reduction_at_equal_or_better_recall": (
            minimum_reduction
        ),
        "cases": [
            {
                "id": task["id"],
                "expected_paths": _impact_paths(task, by_id),
            }
            for task in tasks
        ],
    }


def _navigation_observations(
    tasks: Sequence[Mapping[str, Any]],
    by_id: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        str(task["id"]): {
            "baseline_paths": list(task["baseline_paths"]),
            "impact_context": {
                "target": {"paths": _impact_paths(task, by_id)},
                "gaps": [],
                "source_statuses": [],
            },
        }
        for task in tasks
    }


def _navigation_outcome(
    task: Mapping[str, Any],
    utility_case: Mapping[str, Any],
    by_id: Mapping[str, Mapping[str, Any]],
    minimum_reduction: float,
) -> dict[str, Any]:
    selected_cases_pass = all(
        by_id[case_id]["passed"] for case_id in task["case_ids"]
    )
    passed = (
        selected_cases_pass
        and utility_case["impact_recall"] >= utility_case["baseline_recall"]
        and utility_case["context_path_reduction_ratio"] >= minimum_reduction
    )
    return {
        **utility_case,
        "execution_mode": "deterministic_fixed_navigation_task",
        "case_ids": list(task["case_ids"]),
        "baseline_tool_calls": int(task["baseline_tool_calls"]),
        "graph_tool_calls": 1,
        "outcome": "pass" if passed else "fail",
    }


def _evaluate_navigation_tasks(
    goldset: Mapping[str, Any],
    case_results: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, int]]:
    by_id = {case["id"]: case for case in case_results}
    tasks = list(goldset["agent_tasks"])
    minimum_reduction = goldset["thresholds"]["minimum_context_path_reduction"]
    utility = evaluate_agent_impact_goldset(
        _navigation_goldset(tasks, by_id, minimum_reduction),
        _navigation_observations(tasks, by_id),
    )
    utility_by_id = {item["id"]: item for item in utility["cases"]}
    outcomes = [
        _navigation_outcome(
            task,
            utility_by_id[task["id"]],
            by_id,
            minimum_reduction,
        )
        for task in tasks
    ]
    tool_counts = {
        "baseline": sum(item["baseline_tool_calls"] for item in outcomes),
        "graph": sum(item["graph_tool_calls"] for item in outcomes),
    }
    return utility, outcomes, tool_counts


def _quality_counts(case_results: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    return {
        "true_positives": sum(
            case["counts_as_true_positive"] for case in case_results
        ),
        "false_positives": sum(
            case["counts_as_false_positive"] for case in case_results
        ),
        "false_negatives": sum(
            case["counts_as_false_negative"] for case in case_results
        ),
        "unresolved": sum(
            case["actual_status"] != "resolved" for case in case_results
        ),
    }


def _false_positive_classes(
    case_results: Sequence[Mapping[str, Any]],
) -> dict[str, int]:
    counts = Counter(
        str(case.get("actual_reason") or "unknown")
        for case in case_results
        if case["counts_as_false_positive"]
    )
    return dict(sorted(counts.items()))


def _benchmark_metrics(
    case_results: Sequence[Mapping[str, Any]],
    call_bytes: bytes,
    build_time_ms: float,
    navigation: Mapping[str, Any],
    tool_counts: Mapping[str, int],
) -> dict[str, Any]:
    counts = _quality_counts(case_results)
    true_positives = counts["true_positives"]
    false_positives = counts["false_positives"]
    false_negatives = counts["false_negatives"]
    return {
        "s1_precision": _ratio(
            true_positives,
            true_positives + false_positives,
        ),
        "target_recall": _ratio(
            true_positives,
            true_positives + false_negatives,
        ),
        "true_positive_count": true_positives,
        "false_positive_count": false_positives,
        "false_negative_count": false_negatives,
        "false_positive_classes": _false_positive_classes(case_results),
        "unresolved_count": counts["unresolved"],
        "unresolved_share": _ratio(counts["unresolved"], len(case_results)),
        "serialized_call_bytes": len(call_bytes),
        "build_time_ms": build_time_ms,
        "baseline_tool_calls": tool_counts["baseline"],
        "graph_tool_calls": tool_counts["graph"],
        "tool_call_reduction": _ratio(
            tool_counts["baseline"] - tool_counts["graph"],
            tool_counts["baseline"],
        ),
        "navigation_utility": navigation["metrics"],
    }


def _threshold_checks(
    metrics: Mapping[str, Any],
    thresholds: Mapping[str, Any],
    case_results: Sequence[Mapping[str, Any]],
    agent_outcomes: Sequence[Mapping[str, Any]],
) -> dict[str, bool]:
    navigation_metrics = metrics["navigation_utility"]
    return {
        "minimum_s1_precision": (
            metrics["s1_precision"] >= thresholds["minimum_s1_precision"]
        ),
        "minimum_target_recall": (
            metrics["target_recall"] >= thresholds["minimum_target_recall"]
        ),
        "minimum_context_path_reduction": (
            navigation_metrics["context_path_reduction_ratio"]
            >= thresholds["minimum_context_path_reduction"]
        ),
        "no_case_regression": (
            all(case["passed"] for case in case_results)
            and all(item["outcome"] == "pass" for item in agent_outcomes)
            and navigation_metrics["no_case_regression"]
        ),
    }


def _decision(checks: Mapping[str, bool]) -> dict[str, Any]:
    eligible = all(checks.values())
    reason = (
        "quality thresholds met; a separate reviewed Bureau decision is required"
        if eligible
        else "quality thresholds failed; default promotion remains prohibited"
    )
    return {
        "threshold_checks": dict(checks),
        "thresholds_met": eligible,
        "eligible_for_review": eligible,
        "default_promoted": False,
        "decision_authority": "Bureau",
        "reason": reason,
    }


def evaluate_python_call_graph_fixture(
    fixture_root: Path,
    goldset: Mapping[str, Any],
) -> dict[str, Any]:
    fixture_root = fixture_root.resolve()
    started = time.perf_counter_ns()
    calls, skipped_files_count, skipped_errors = extract_python_calls(fixture_root)
    build_time_ms = round((time.perf_counter_ns() - started) / 1_000_000, 3)
    case_results = [_evaluate_case(calls, case) for case in goldset["cases"]]
    call_bytes = _canonical_bytes(calls)
    navigation, agent_outcomes, tool_counts = _evaluate_navigation_tasks(
        goldset,
        case_results,
    )
    metrics = _benchmark_metrics(
        case_results,
        call_bytes,
        build_time_ms,
        navigation,
        tool_counts,
    )
    checks = _threshold_checks(
        metrics,
        goldset["thresholds"],
        case_results,
        agent_outcomes,
    )
    return {
        "kind": "lenskit.python_call_graph_quality_benchmark",
        "version": "1.0",
        "scope": "fixed_python_goldset_and_deterministic_navigation_tasks",
        "evidence": {
            "goldset_sha256": _sha256(_canonical_bytes(goldset)),
            "fixture_sha256": _fixture_sha256(fixture_root),
            "call_records_sha256": _sha256(call_bytes),
        },
        "coverage": {
            "case_count": len(case_results),
            "category_count": len({case["category"] for case in case_results}),
            "call_record_count": len(calls),
            "skipped_files_count": skipped_files_count,
            "skipped_errors": skipped_errors,
        },
        "thresholds": dict(goldset["thresholds"]),
        "metrics": metrics,
        "cases": case_results,
        "agent_task_outcomes": agent_outcomes,
        "decision": _decision(checks),
        "does_not_establish": list(goldset["does_not_establish"]),
    }


def evaluate_python_call_graph_goldset(
    goldset_path: Path,
    *,
    repository_root: Path = REPO_ROOT,
) -> dict[str, Any]:
    goldset = load_python_call_graph_goldset(goldset_path)
    fixture_root = Path(goldset["fixture_root"])
    if not fixture_root.is_absolute():
        fixture_root = repository_root / fixture_root
    return evaluate_python_call_graph_fixture(fixture_root, goldset)


def stable_report_projection(report: Mapping[str, Any]) -> dict[str, Any]:
    """Return the deterministic report surface, excluding measured wall time."""

    projection = json.loads(json.dumps(report))
    projection["metrics"].pop("build_time_ms", None)
    return projection


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--goldset",
        type=Path,
        default=REPO_ROOT / "docs/retrieval/python_call_graph_goldset.v1.json",
    )
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--out", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = evaluate_python_call_graph_goldset(
        args.goldset,
        repository_root=args.repo_root,
    )
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0 if report["decision"]["thresholds_met"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
