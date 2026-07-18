from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from merger.repoground.core.ask_context import DOES_NOT_ESTABLISH, build_ask_context_pack

KIND = "repobrief.ask_eval"
VERSION = "1.0"
MISS_CODES = (
    "missing_expected_path",
    "missing_expected_citation",
    "required_reading_fail",
    "no_resolved_ranges",
    "budget_truncated",
)


def _read_json(path: str | Path) -> dict[str, Any]:
    p = Path(path).expanduser().resolve()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"goldset does not exist: {p}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"goldset is not valid JSON: {p}") from exc
    if not isinstance(data, dict):
        raise ValueError("goldset must be a JSON object")
    return data


def _range_paths(pack: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    for item in pack.get("resolved_ranges", []):
        if not isinstance(item, dict):
            continue
        ref = item.get("range_ref")
        if isinstance(ref, dict):
            path = ref.get("file_path") or ref.get("artifact_path") or ref.get("path")
            if isinstance(path, str) and path:
                paths.append(path)
    return paths


def _citation_ids(pack: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for hit in pack.get("retrieval_hits", []):
        if isinstance(hit, dict) and isinstance(hit.get("citation_id"), str):
            result.append(hit["citation_id"])
    return result


def _recall(expected: list[str], found: list[str]) -> tuple[float, list[str]]:
    if not expected:
        return 1.0, []
    found_set = set(found)
    missing = [item for item in expected if item not in found_set]
    return (len(expected) - len(missing)) / len(expected), missing


def _mrr(expected: list[str], ranked: list[str]) -> float:
    if not expected:
        return 1.0
    expected_set = set(expected)
    for idx, item in enumerate(ranked, start=1):
        if item in expected_set:
            return 1.0 / idx
    return 0.0


def _evaluate_one(bundle_manifest: Path, entry: dict[str, Any], *, k: int, max_context_tokens: int) -> dict[str, Any]:
    query = str(entry.get("query") or entry.get("q") or "")
    task_profile = str(entry.get("task_profile") or "basic_repo_question")
    max_answer_tokens = int(entry.get("max_answer_tokens") or 1200)
    pack = build_ask_context_pack(
        bundle_manifest,
        query=query,
        task_profile=task_profile,
        max_context_tokens=max_context_tokens,
        max_answer_tokens=max_answer_tokens,
        k=k,
    )
    expected_paths = [str(x) for x in entry.get("expected_paths") or []]
    expected_citations = [str(x) for x in entry.get("expected_citation_ids") or []]
    found_paths = _range_paths(pack)
    found_citations = _citation_ids(pack)
    path_recall, missing_paths = _recall(expected_paths, found_paths)
    citation_coverage, missing_citations = _recall(expected_citations, found_citations)
    rr_status = pack.get("required_reading", {}).get("status")
    required_reading_coverage = 0.0 if rr_status == "fail" else 1.0
    miss_taxonomy: dict[str, int] = {code: 0 for code in MISS_CODES}
    miss_taxonomy["missing_expected_path"] = len(missing_paths)
    miss_taxonomy["missing_expected_citation"] = len(missing_citations)
    miss_taxonomy["required_reading_fail"] = 1 if rr_status == "fail" else 0
    miss_taxonomy["no_resolved_ranges"] = 1 if not pack.get("resolved_ranges") else 0
    miss_taxonomy["budget_truncated"] = 1 if pack.get("budget", {}).get("truncated") is True else 0
    status = "pass" if sum(miss_taxonomy.values()) == 0 else "fail"
    return {
        "id": str(entry.get("id") or query),
        "status": status,
        "query": query,
        "task_profile": task_profile,
        "expected_paths": expected_paths,
        "found_paths": found_paths,
        "missing_paths": missing_paths,
        "expected_citation_ids": expected_citations,
        "found_citation_ids": found_citations,
        "missing_citation_ids": missing_citations,
        "metrics": {
            "expected_path_recall": path_recall,
            "citation_coverage": citation_coverage,
            "required_reading_coverage": required_reading_coverage,
            "mrr_at_k": _mrr(expected_paths, found_paths),
        },
        "miss_taxonomy": miss_taxonomy,
        "context_pack": pack,
    }


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _promotion_gate(metrics: dict[str, Any], baseline: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(baseline, dict):
        return {
            "eligible": False,
            "status": "warn",
            "reason": "baseline_metrics_missing",
            "requires_no_central_query_regression": True,
            "requires_documented_measurement_advantage": True,
        }
    baseline_metrics = baseline.get("metrics") if isinstance(baseline.get("metrics"), dict) else baseline
    regression_keys = ["expected_path_recall", "citation_coverage", "required_reading_coverage", "mrr_at_k"]
    regressions = [
        key for key in regression_keys
        if float(metrics.get(key, 0.0)) < float(baseline_metrics.get(key, 0.0))
    ]
    advantage = sum(float(metrics.get(key, 0.0)) - float(baseline_metrics.get(key, 0.0)) for key in regression_keys)
    return {
        "eligible": not regressions and advantage > 0,
        "status": "pass" if not regressions and advantage > 0 else "fail",
        "regressions": regressions,
        "measurement_advantage": advantage,
        "requires_no_central_query_regression": True,
        "requires_documented_measurement_advantage": True,
    }


def evaluate_ask_goldset(
    bundle_manifest: str | Path,
    goldset_path: str | Path,
    *,
    k: int = 5,
    max_context_tokens: int = 8000,
    baseline_path: str | Path | None = None,
) -> dict[str, Any]:
    manifest_path = Path(bundle_manifest).expanduser().resolve()
    goldset = _read_json(goldset_path)
    queries = goldset.get("queries")
    if not isinstance(queries, list) or not all(isinstance(item, dict) for item in queries):
        raise ValueError("goldset queries must be an array of objects")
    results = [_evaluate_one(manifest_path, item, k=k, max_context_tokens=max_context_tokens) for item in queries]
    metrics = {
        "query_count": len(results),
        "expected_path_recall": _mean([r["metrics"]["expected_path_recall"] for r in results]),
        "citation_coverage": _mean([r["metrics"]["citation_coverage"] for r in results]),
        "required_reading_coverage": _mean([r["metrics"]["required_reading_coverage"] for r in results]),
        "mrr_at_k": _mean([r["metrics"]["mrr_at_k"] for r in results]),
        "budget_truncation_rate": _mean([1.0 if r["context_pack"].get("budget", {}).get("truncated") else 0.0 for r in results]),
    }
    miss_taxonomy = {code: sum(r["miss_taxonomy"].get(code, 0) for r in results) for code in MISS_CODES}
    baseline = _read_json(baseline_path) if baseline_path else None
    promotion_gate = _promotion_gate(metrics, baseline)
    status = "pass" if all(r["status"] == "pass" for r in results) else "fail"
    if status == "pass" and promotion_gate["status"] == "warn":
        status = "warn"
    return {
        "kind": KIND,
        "version": VERSION,
        "status": status,
        "bundle_manifest": str(manifest_path),
        "goldset": str(Path(goldset_path).expanduser().resolve()),
        "metrics": metrics,
        "miss_taxonomy": miss_taxonomy,
        "promotion_gate": promotion_gate,
        "results": results,
        "does_not_establish": list(DOES_NOT_ESTABLISH) + ["retrieval_quality_sufficient", "default_promotion_safe"],
    }
