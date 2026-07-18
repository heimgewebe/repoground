"""Deterministic navigation-utility comparison for RepoGround workbench reads."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from merger.repoground.core.readonly_adapter import RepoGroundReadonlyAdapter

KIND = "repobrief.workbench_usefulness_eval"
VERSION = "2.1"
GOLDSET_KIND = "repobrief.workbench_usefulness_goldset"
GOLDSET_VERSION = "1.0"
DOES_NOT_ESTABLISH = (
    "agent_quality_improvement",
    "answer_correctness",
    "repository_understanding",
    "patch_correctness",
    "test_sufficiency",
    "review_completeness",
    "merge_readiness",
    "general_retrieval_quality",
    "default_workbench_promotion",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_json_object(path: str | Path, *, label: str) -> tuple[Path, dict[str, Any]]:
    resolved = Path(path).expanduser().resolve()
    try:
        value = json.loads(resolved.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"{label} does not exist: {resolved}") from exc
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not valid UTF-8 JSON: {resolved}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return resolved, value


def _mean(values: Iterable[float]) -> float:
    materialized = list(values)
    return sum(materialized) / len(materialized) if materialized else 0.0


def _recall(expected: list[str], observed: list[str]) -> tuple[float, list[str]]:
    if not expected:
        return 1.0, []
    normalized = [item.casefold() for item in observed]
    missing = [
        item
        for item in expected
        if not any(item.casefold() in candidate for candidate in normalized)
    ]
    return (len(expected) - len(missing)) / len(expected), missing


def _mrr(expected: list[str], ranked: list[str]) -> float:
    if not expected:
        return 1.0
    expected_folded = [item.casefold() for item in expected]
    for ordinal, candidate in enumerate(ranked, start=1):
        folded = candidate.casefold()
        if any(item in folded for item in expected_folded):
            return 1.0 / ordinal
    return 0.0


def _query_paths(response: dict[str, Any]) -> list[str]:
    query = response.get("query")
    if not isinstance(query, dict):
        return []
    result = query.get("query_result")
    rows = result.get("results") if isinstance(result, dict) else None
    paths: list[str] = []
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict) and isinstance(row.get("path"), str):
                paths.append(row["path"])
    projection = query.get("source_citation_projection")
    items = projection.get("items") if isinstance(projection, dict) else None
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict) and isinstance(item.get("path"), str):
                paths.append(item["path"])
    return list(dict.fromkeys(paths))


def _symbol_observations(response: dict[str, Any]) -> tuple[list[str], list[str]]:
    search = response.get("symbol_search")
    hits = search.get("hits") if isinstance(search, dict) else None
    names: list[str] = []
    paths: list[str] = []
    if isinstance(hits, list):
        for hit in hits:
            if not isinstance(hit, dict):
                continue
            for field in ("name", "qualified_name"):
                value = hit.get(field)
                if isinstance(value, str):
                    names.append(value)
            if isinstance(hit.get("path"), str):
                paths.append(hit["path"])
    return list(dict.fromkeys(names)), list(dict.fromkeys(paths))


def _guardrails_visible(response: dict[str, Any]) -> bool:
    nonclaims = response.get("does_not_establish")
    boundary = response.get("mutation_boundary")
    return (
        isinstance(nonclaims, list)
        and len(nonclaims) >= 3
        and isinstance(boundary, dict)
        and boundary.get("writes") == []
        and boundary.get("read_paths_do_not_refresh") is True
        and boundary.get("does_not_create_snapshots") is True
    )


def _baseline_guardrails_visible(text: str) -> bool:
    normalized = text.casefold()
    required_marker_groups = (
        ("repo_understood", "repo understanding"),
        ("test_sufficiency", "test sufficiency"),
        ("merge_readiness", "merge readiness"),
        ("does not prove",),
    )
    return all(
        any(marker in normalized for marker in alternatives)
        for alternatives in required_marker_groups
    )


def _source_identity(manifest_path: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    provenance = manifest.get("snapshot_provenance")
    repositories = provenance.get("repositories") if isinstance(provenance, dict) else None
    sources: list[dict[str, Any]] = []
    if isinstance(repositories, list):
        for repository in repositories:
            if not isinstance(repository, dict):
                continue
            sources.append(
                {
                    "name": repository.get("name"),
                    "repo_remote": repository.get("repo_remote"),
                    "git_commit": repository.get("git_commit"),
                    "git_dirty": repository.get("git_dirty"),
                    "provenance_status": repository.get("provenance_status"),
                }
            )
    return {
        "bundle_manifest_name": manifest_path.name,
        "bundle_manifest_sha256": _sha256(manifest_path),
        "bundle_run_id": manifest.get("run_id"),
        "bundle_created_at": manifest.get("created_at"),
        "repositories": sources,
    }


def _validate_goldset(goldset: dict[str, Any]) -> list[dict[str, Any]]:
    if (
        goldset.get("kind") != GOLDSET_KIND
        or goldset.get("version") != GOLDSET_VERSION
    ):
        raise ValueError(
            f"goldset must be {GOLDSET_KIND} version {GOLDSET_VERSION}"
        )
    questions = goldset.get("questions")
    if not isinstance(questions, list) or len(questions) < 5:
        raise ValueError("goldset must contain at least five questions")
    seen: set[str] = set()
    validated: list[dict[str, Any]] = []
    for raw in questions:
        if not isinstance(raw, dict):
            raise ValueError("goldset question must be an object")
        question_id = raw.get("id")
        query = raw.get("query")
        expected_paths = raw.get("expected_paths")
        expected_symbols = raw.get("expected_symbols")
        if not isinstance(question_id, str) or not question_id:
            raise ValueError("goldset question id must be a non-empty string")
        if question_id in seen:
            raise ValueError(f"duplicate goldset question id: {question_id}")
        if not isinstance(query, str) or not query:
            raise ValueError(f"question {question_id} query must be non-empty")
        if not isinstance(expected_paths, list) or not expected_paths:
            raise ValueError(f"question {question_id} expected_paths must be non-empty")
        if not isinstance(expected_symbols, list) or not expected_symbols:
            raise ValueError(f"question {question_id} expected_symbols must be non-empty")
        if not all(isinstance(item, str) and item for item in expected_paths):
            raise ValueError(f"question {question_id} expected_paths are invalid")
        if not all(isinstance(item, str) and item for item in expected_symbols):
            raise ValueError(f"question {question_id} expected_symbols are invalid")
        seen.add(question_id)
        validated.append(raw)
    return validated


def evaluate_workbench_usefulness(
    adapter_config: str | Path,
    *,
    snapshot_id: str,
    goldset_path: str | Path,
    k: int = 10,
) -> dict[str, Any]:
    if not isinstance(k, int) or isinstance(k, bool) or k < 1 or k > 50:
        raise ValueError("k must be an integer between 1 and 50")
    adapter = RepoGroundReadonlyAdapter.from_config(adapter_config)
    gold_path, goldset = _read_json_object(goldset_path, label="workbench goldset")
    questions = _validate_goldset(goldset)
    manifest_path = adapter.manifest_for(snapshot_id)

    baseline_artifact = adapter.workbench_artifact_get(
        snapshot_id,
        "agent_reading_pack",
    )
    if baseline_artifact.get("status") != "available":
        raise ValueError("agent_reading_pack is required for the baseline lane")
    baseline_text = str(baseline_artifact.get("content_text") or "")
    baseline_lines = baseline_text.splitlines()
    baseline_guardrails_visible = _baseline_guardrails_visible(baseline_text)

    rows: list[dict[str, Any]] = []
    for question in questions:
        expected_paths = [str(item) for item in question["expected_paths"]]
        expected_symbols = [str(item) for item in question["expected_symbols"]]
        baseline_path_recall, baseline_missing_paths = _recall(
            expected_paths,
            baseline_lines,
        )
        baseline_symbol_recall, baseline_missing_symbols = _recall(
            expected_symbols,
            baseline_lines,
        )

        query_response = adapter.query_existing_index(
            snapshot_id,
            question["query"],
            k=k,
            filters=question.get("filters"),
            resolve_evidence=True,
            project_sources=True,
        )
        symbol_response = adapter.symbol_search(
            snapshot_id,
            question.get("symbol_query") or question["query"],
            k=k,
            kind=question.get("symbol_kind"),
            path=question.get("symbol_path_filter"),
        )
        query_paths = _query_paths(query_response)
        symbol_names, symbol_paths = _symbol_observations(symbol_response)
        workbench_paths = list(dict.fromkeys(query_paths + symbol_paths))
        workbench_path_recall, workbench_missing_paths = _recall(
            expected_paths,
            workbench_paths,
        )
        workbench_symbol_recall, workbench_missing_symbols = _recall(
            expected_symbols,
            symbol_names,
        )
        query_guardrails_visible = _guardrails_visible(query_response)
        symbol_guardrails_visible = _guardrails_visible(symbol_response)
        workbench_guardrails_visible = (
            query_guardrails_visible and symbol_guardrails_visible
        )
        explicit_missing_evidence = {
            "paths": workbench_missing_paths,
            "symbols": workbench_missing_symbols,
        }
        structured_answer_context_compliant = (
            query_response.get("status") == "available"
            and symbol_response.get("status") == "available"
            and not workbench_missing_paths
            and not workbench_missing_symbols
            and workbench_guardrails_visible
            and isinstance(query_paths, list)
            and isinstance(symbol_names, list)
        )
        baseline_target_recall = _mean(
            [baseline_path_recall, baseline_symbol_recall]
        )
        workbench_target_recall = _mean(
            [workbench_path_recall, workbench_symbol_recall]
        )
        rows.append(
            {
                "id": question["id"],
                "query": question["query"],
                "expected_paths": expected_paths,
                "expected_symbols": expected_symbols,
                "baseline": {
                    "path_recall": baseline_path_recall,
                    "symbol_recall": baseline_symbol_recall,
                    "target_recall": baseline_target_recall,
                    "missing_paths": baseline_missing_paths,
                    "missing_symbols": baseline_missing_symbols,
                    "mrr": _mrr(expected_paths + expected_symbols, baseline_lines),
                    "guardrails_visible": baseline_guardrails_visible,
                    "missing_evidence_explicit": True,
                },
                "workbench": {
                    "query_status": query_response.get("status"),
                    "symbol_status": symbol_response.get("status"),
                    "observed_paths": workbench_paths,
                    "observed_symbols": symbol_names,
                    "path_recall": workbench_path_recall,
                    "symbol_recall": workbench_symbol_recall,
                    "target_recall": workbench_target_recall,
                    "missing_paths": workbench_missing_paths,
                    "missing_symbols": workbench_missing_symbols,
                    "path_mrr_at_k": _mrr(expected_paths, workbench_paths),
                    "symbol_mrr_at_k": _mrr(expected_symbols, symbol_names),
                    "guardrails_visible": workbench_guardrails_visible,
                    "query_guardrails_visible": query_guardrails_visible,
                    "symbol_guardrails_visible": symbol_guardrails_visible,
                    "missing_evidence_explicit": True,
                    "explicit_missing_evidence": explicit_missing_evidence,
                    "structured_answer_context": {
                        "evidence_paths": workbench_paths,
                        "evidence_symbols": symbol_names,
                        "missing_evidence": explicit_missing_evidence,
                        "does_not_establish": list(DOES_NOT_ESTABLISH),
                        "compliant": structured_answer_context_compliant,
                    },
                },
            }
        )

    baseline_metrics = {
        "question_count": len(rows),
        "path_recall": _mean(row["baseline"]["path_recall"] for row in rows),
        "symbol_recall": _mean(
            row["baseline"]["symbol_recall"] for row in rows
        ),
        "target_recall": _mean(row["baseline"]["target_recall"] for row in rows),
        "question_success_rate": _mean(
            1.0 if row["baseline"]["target_recall"] == 1.0 else 0.0
            for row in rows
        ),
        "source_bytes_exposed": len(baseline_text.encode("utf-8")),
        "guardrail_visibility_rate": 1.0 if baseline_guardrails_visible else 0.0,
        "missing_evidence_visibility_rate": 1.0,
    }
    workbench_metrics = {
        "question_count": len(rows),
        "path_recall": _mean(row["workbench"]["path_recall"] for row in rows),
        "symbol_recall": _mean(
            row["workbench"]["symbol_recall"] for row in rows
        ),
        "target_recall": _mean(
            row["workbench"]["target_recall"] for row in rows
        ),
        "question_success_rate": _mean(
            1.0 if row["workbench"]["target_recall"] == 1.0 else 0.0
            for row in rows
        ),
        "path_mrr_at_k": _mean(
            row["workbench"]["path_mrr_at_k"] for row in rows
        ),
        "symbol_mrr_at_k": _mean(
            row["workbench"]["symbol_mrr_at_k"] for row in rows
        ),
        "query_availability_rate": _mean(
            1.0 if row["workbench"]["query_status"] == "available" else 0.0
            for row in rows
        ),
        "symbol_availability_rate": _mean(
            1.0 if row["workbench"]["symbol_status"] == "available" else 0.0
            for row in rows
        ),
        "guardrail_visibility_rate": _mean(
            1.0 if row["workbench"]["guardrails_visible"] else 0.0
            for row in rows
        ),
        "missing_evidence_visibility_rate": _mean(
            1.0 if row["workbench"]["missing_evidence_explicit"] else 0.0
            for row in rows
        ),
        "structured_answer_context_compliance_rate": _mean(
            1.0
            if row["workbench"]["structured_answer_context"]["compliant"]
            else 0.0
            for row in rows
        ),
    }
    target_advantage = (
        workbench_metrics["target_recall"] - baseline_metrics["target_recall"]
    )
    path_regression = workbench_metrics["path_recall"] < baseline_metrics["path_recall"]
    symbol_regression = (
        workbench_metrics["symbol_recall"] < baseline_metrics["symbol_recall"]
    )
    useful = (
        target_advantage >= 0.20
        and not path_regression
        and not symbol_regression
        and workbench_metrics["query_availability_rate"] == 1.0
        and workbench_metrics["symbol_availability_rate"] == 1.0
        and workbench_metrics["guardrail_visibility_rate"] == 1.0
        and workbench_metrics["missing_evidence_visibility_rate"] == 1.0
        and workbench_metrics["structured_answer_context_compliance_rate"] == 1.0
    )
    dimensions = {
        "evidence_usefulness": {
            "metric": "combined_target_recall_advantage",
            "baseline": baseline_metrics["target_recall"],
            "workbench": workbench_metrics["target_recall"],
            "advantage": target_advantage,
        },
        "navigation_value": {
            "path_recall": workbench_metrics["path_recall"],
            "symbol_recall": workbench_metrics["symbol_recall"],
            "path_mrr_at_k": workbench_metrics["path_mrr_at_k"],
            "symbol_mrr_at_k": workbench_metrics["symbol_mrr_at_k"],
        },
        "false_confidence_risk": {
            "baseline_guardrail_visibility_rate": baseline_metrics[
                "guardrail_visibility_rate"
            ],
            "workbench_guardrail_visibility_rate": workbench_metrics[
                "guardrail_visibility_rate"
            ],
            "guardrail_omission_rate": 1.0
            - workbench_metrics["guardrail_visibility_rate"],
            "behavioral_false_confidence": "not_measured_no_natural_language_answers",
            "interpretation": "guardrail visibility is a proxy, not observed agent belief",
        },
        "missing_evidence_visibility": {
            "baseline_report_visibility_rate": baseline_metrics[
                "missing_evidence_visibility_rate"
            ],
            "workbench_report_visibility_rate": workbench_metrics[
                "missing_evidence_visibility_rate"
            ],
            "interpretation": "the evaluator always reports missing expected paths and symbols explicitly",
        },
        "agent_answer_compliance": {
            "structured_context_compliance_rate": workbench_metrics[
                "structured_answer_context_compliance_rate"
            ],
            "natural_language_answer_compliance": "not_measured_no_agent_answers",
            "interpretation": "the metric checks evidence, missing-evidence and non-claim fields before an answer, not whether an agent follows them",
        },
    }
    return {
        "kind": KIND,
        "version": VERSION,
        "status": "pass" if useful else "fail",
        "scope": "deterministic_navigation_utility",
        "source": _source_identity(manifest_path),
        "goldset": {
            "path": gold_path.name,
            "sha256": _sha256(gold_path),
            "question_count": len(rows),
        },
        "comparison": {
            "baseline_condition": "entire_agent_reading_pack_literal_visibility",
            "workbench_condition": "readonly_index_query_plus_symbol_search",
            "k": k,
            "baseline": baseline_metrics,
            "workbench": workbench_metrics,
            "target_recall_advantage": target_advantage,
            "path_regression": path_regression,
            "symbol_regression": symbol_regression,
        },
        "dimensions": dimensions,
        "decision": {
            "navigation_utility_established_for_goldset": useful,
            "workbench_default_promoted": False,
            "reason": (
                "fixed_goldset_advantage_without_central_recall_regression"
                if useful
                else "acceptance_threshold_not_met"
            ),
            "minimum_target_recall_advantage": 0.20,
            "requires_query_and_symbol_availability": True,
        },
        "questions": rows,
        "false_confidence_measurement": {
            "status": "proxy_only",
            "guardrail_visibility_measured": True,
            "behavioral_agent_belief_measured": False,
            "reason": "the deterministic evaluator measures visible caveats and omissions but does not produce natural-language agent answers",
        },
        "answer_compliance_measurement": {
            "status": "structured_context_only",
            "structured_context_compliance_rate": workbench_metrics[
                "structured_answer_context_compliance_rate"
            ],
            "natural_language_agent_answers_measured": False,
        },
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }
