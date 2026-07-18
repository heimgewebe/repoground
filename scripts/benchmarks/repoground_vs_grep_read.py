#!/usr/bin/env python3
"""Measure RepoGround retrieval against bounded local text search and reads.

Ripgrep is preferred when installed.  A deterministic UTF-8 Python substring
search is used otherwise, and every case records the selected search engine.
No network, installation or repository mutation is performed.  A report is
always written when argument validation succeeds, including when acceptance
gates fail, so a failed run remains inspectable and reproducible.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

# Permit direct execution from any checkout directory without installation.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

COMPACTION_REQUIRED_PERCENT = 60.0
TOKEN_PROXY_BYTES_PER_TOKEN = 4
READ_LIMIT_BYTES = 4096


def _execute_review_query(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Late import keeps this script directly executable without installation."""
    from merger.repoground.retrieval.review_query import execute_review_query

    return execute_review_query(*args, **kwargs)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def _tree_sha256(root: Path) -> str:
    """Hash the local source input without including VCS metadata or symlinks."""
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if ".git" in path.parts or not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(relative + b"\0")
        digest.update(_sha256(path).encode("ascii") + b"\n")
    return digest.hexdigest()


def _tokens(question: str) -> list[str]:
    return list(dict.fromkeys(re.findall(r"[A-Za-z0-9_]{3,}", question.lower())))


def _expected_targets(paths: list[str], expected: list[str]) -> dict[str, Any]:
    found = [pattern for pattern in expected if any(pattern in path for path in paths)]
    missing = [pattern for pattern in expected if pattern not in found]
    return {"expected": expected, "found": found, "missing": missing}


def _source_freshness(paths: list[str], root: Path, index_mtime_ns: int | None) -> dict[str, Any]:
    missing: list[str] = []
    newer_than_index: list[str] = []
    for relative in paths:
        candidate = root / relative
        if not candidate.is_file():
            missing.append(relative)
        elif index_mtime_ns is not None and candidate.stat().st_mtime_ns > index_mtime_ns:
            newer_than_index.append(relative)
    if missing:
        status = "unavailable"
    elif newer_than_index:
        status = "stale"
    else:
        status = "fresh"
    return {
        "status": status,
        "checked_path_count": len(paths),
        "missing_paths": missing,
        "newer_than_index_paths": newer_than_index,
    }


def _compact_repoground_response(result: dict[str, Any], freshness: dict[str, Any]) -> dict[str, Any]:
    """Keep navigation evidence, source freshness and fallback details only."""
    hits = []
    for hit in result.get("results", []):
        hits.append({
            "chunk_id": hit.get("chunk_id"),
            "path": hit.get("path"),
            "start_line": hit.get("start_line"),
            "end_line": hit.get("end_line"),
            "content_sha256": hit.get("content_sha256"),
            "range_ref": hit.get("content_range_ref") or hit.get("range_ref"),
        })
    return {
        "query": result.get("query"),
        "k": result.get("k"),
        "status": "available",
        "hits": hits,
        "freshness": freshness,
        "fallback": {
            "query_mode": result.get("query_mode"),
            "warnings": result.get("warnings", []),
        },
    }


def _python_matching_paths(root: Path, token: str) -> list[Path]:
    """Return deterministic text-file matches when ripgrep is unavailable."""
    needle = token.casefold()
    matches: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(root)
        if ".git" in relative.parts:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        if needle in content.casefold():
            matches.append(path)
    return matches


def _grep_read(root: Path, question: str, k: int) -> tuple[dict[str, Any], int, int]:
    paths: list[str] = []
    process_calls = 0
    ripgrep = shutil.which("rg")
    search_engine = "ripgrep" if ripgrep else "python_utf8_substring"
    for token in _tokens(question):
        if ripgrep:
            process_calls += 1
            run = subprocess.run(
                [ripgrep, "-l", "-i", "--glob", "!.git", "--", token, str(root)],
                text=True,
                capture_output=True,
                check=False,
            )
            candidates = [Path(raw) for raw in run.stdout.splitlines()]
        else:
            candidates = _python_matching_paths(root, token)
        for path in candidates:
            try:
                relative = path.relative_to(root).as_posix()
            except ValueError:
                continue
            if relative not in paths:
                paths.append(relative)
            if len(paths) >= k:
                break
        if len(paths) >= k:
            break
    reads = []
    for relative in paths:
        with (root / relative).open("rb") as handle:
            reads.append({"path": relative, "bytes_read": len(handle.read(READ_LIMIT_BYTES))})
    result = {
        "query": question,
        "k": k,
        "status": "available",
        "search_engine": search_engine,
        "paths": paths,
        "reads": reads,
    }
    return result, process_calls, len(reads)


def _measurement(condition: str, result: dict[str, Any], *, runtime_ns: int, process_calls: int,
                 source_read_calls: int, paths: list[str], expected: list[str], freshness: dict[str, Any],
                 compact: dict[str, Any] | None = None) -> dict[str, Any]:
    response_bytes = len(json.dumps(result, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    target_state = _expected_targets(paths, expected)
    useful_displayed = bool(paths)
    false_confidence = useful_displayed and (
        bool(target_state["missing"]) or freshness["status"] != "fresh"
    )
    item: dict[str, Any] = {
        "condition": condition,
        "runtime_ms": round(runtime_ns / 1_000_000, 3),
        "tool_calls": 1,
        "process_calls": process_calls,
        "source_read_calls": source_read_calls,
        "response_bytes": response_bytes,
        "token_proxy": math.ceil(response_bytes / TOKEN_PROXY_BYTES_PER_TOKEN),
        "paths": paths,
        "expected_targets": target_state,
        "source_index_freshness": freshness,
        "useful_displayed": useful_displayed,
        "false_confidence": false_confidence,
    }
    if result.get("search_engine"):
        item["search_engine"] = result["search_engine"]
    if compact is not None:
        compact_bytes = len(json.dumps(compact, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        reduction = (1 - compact_bytes / max(response_bytes, 1)) * 100
        item["compaction"] = {
            "compact_response_bytes": compact_bytes,
            "byte_reduction_percent": round(max(0.0, reduction), 2),
            "required_percent": COMPACTION_REQUIRED_PERCENT,
            "pass": reduction >= COMPACTION_REQUIRED_PERCENT,
            "preserved": ["chunk_id", "path", "line_range", "content_sha256", "range_ref", "freshness", "fallback"],
        }
    return item


def _aggregate(cases: list[dict[str, Any]], condition: str) -> dict[str, Any]:
    rows = [case[condition] for case in cases]
    freshness = Counter(row["source_index_freshness"]["status"] for row in rows)
    total: dict[str, Any] = {
        "case_count": len(rows),
        "runtime_ms": round(sum(row["runtime_ms"] for row in rows), 3),
        "tool_calls": sum(row["tool_calls"] for row in rows),
        "process_calls": sum(row["process_calls"] for row in rows),
        "source_read_calls": sum(row["source_read_calls"] for row in rows),
        "response_bytes": sum(row["response_bytes"] for row in rows),
        "token_proxy": sum(row["token_proxy"] for row in rows),
        "expected_targets_missing": sum(len(row["expected_targets"]["missing"]) for row in rows),
        "false_confidence_cases": sum(bool(row["false_confidence"]) for row in rows),
        "source_index_freshness": dict(sorted(freshness.items())),
    }
    if condition == "repoground":
        compactions = [row["compaction"] for row in rows]
        full_bytes = total["response_bytes"]
        compact_bytes = sum(row["compact_response_bytes"] for row in compactions)
        reduction = (1 - compact_bytes / max(full_bytes, 1)) * 100
        total["compaction"] = {
            "compact_response_bytes": compact_bytes,
            "byte_reduction_percent": round(max(0.0, reduction), 2),
            "required_percent": COMPACTION_REQUIRED_PERCENT,
            "all_cases_pass": all(row["pass"] for row in compactions),
            "aggregate_pass": reduction >= COMPACTION_REQUIRED_PERCENT,
        }
    return total


def _category_decisions(cases: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for case in cases:
        category = str(case.get("category") or "uncategorized")
        grouped.setdefault(category, []).append(case)
    decisions: dict[str, dict[str, Any]] = {}
    for category, rows in sorted(grouped.items()):
        repoground_rows = [row["repoground"] for row in rows]
        grep_rows = [row["grep_read"] for row in rows]
        repoground_missing = sum(len(row["expected_targets"]["missing"]) for row in repoground_rows)
        grep_missing = sum(len(row["expected_targets"]["missing"]) for row in grep_rows)
        repoground_false_confidence = sum(bool(row["false_confidence"]) for row in repoground_rows)
        grep_false_confidence = sum(bool(row["false_confidence"]) for row in grep_rows)
        unsafe_freshness = sum(
            row["source_index_freshness"]["status"] != "fresh" for row in repoground_rows
        )
        compaction_pass = all(row["compaction"]["pass"] for row in repoground_rows)
        measurable_benefit = repoground_missing < grep_missing
        no_quality_regression = (
            repoground_false_confidence <= grep_false_confidence and unsafe_freshness == 0
        )
        evidence_safe = repoground_false_confidence == 0
        recommended = measurable_benefit and no_quality_regression and evidence_safe and compaction_pass
        decisions[category] = {
            "case_count": len(rows),
            "repoground_expected_targets_missing": repoground_missing,
            "grep_read_expected_targets_missing": grep_missing,
            "repoground_false_confidence_cases": repoground_false_confidence,
            "grep_read_false_confidence_cases": grep_false_confidence,
            "repoground_unsafe_freshness_cases": unsafe_freshness,
            "compaction_pass": compaction_pass,
            "measurable_benefit": measurable_benefit,
            "no_quality_regression": no_quality_regression,
            "evidence_safe": evidence_safe,
            "recommended": recommended,
        }
    return decisions


def run(index: Path, repo_root: Path, questions_path: Path, k: int) -> dict[str, Any]:
    questions = json.loads(questions_path.read_text(encoding="utf-8"))
    if not isinstance(questions, list) or not 20 <= len(questions) <= 30:
        raise ValueError("questions must contain 20 to 30 fixed cases")
    if k < 1:
        raise ValueError("k must be at least 1")
    root = repo_root.resolve()
    index = index.resolve()
    index_mtime_ns = index.stat().st_mtime_ns
    cases = []
    for ordinal, case in enumerate(questions, start=1):
        query = case["query"]
        expected = case["expected_patterns"]
        started = time.perf_counter_ns()
        rg_result = _execute_review_query(index, query, k=k)
        rg_runtime = time.perf_counter_ns() - started
        rg_paths = [hit["path"] for hit in rg_result["results"]]
        rg_freshness = _source_freshness(rg_paths, root, index_mtime_ns)
        rg_compact = _compact_repoground_response(rg_result, rg_freshness)

        started = time.perf_counter_ns()
        grep_result, process_calls, read_calls = _grep_read(root, query, k)
        grep_runtime = time.perf_counter_ns() - started
        grep_paths = grep_result["paths"]
        # rg/read deliberately does not consume the index; its source freshness
        # is therefore recorded independently rather than pretending index use.
        grep_freshness = _source_freshness(grep_paths, root, None)
        cases.append({
            "ordinal": ordinal,
            "query": query,
            "category": case.get("category"),
            "k": k,
            "repoground": _measurement("repoground", rg_result, runtime_ns=rg_runtime, process_calls=0,
                                         source_read_calls=0, paths=rg_paths, expected=expected,
                                         freshness=rg_freshness, compact=rg_compact),
            "grep_read": _measurement("grep_read", grep_result, runtime_ns=grep_runtime,
                                        process_calls=process_calls, source_read_calls=read_calls,
                                        paths=grep_paths, expected=expected, freshness=grep_freshness),
        })
    aggregates = {name: _aggregate(cases, name) for name in ("repoground", "grep_read")}
    compaction = aggregates["repoground"]["compaction"]
    category_decisions = _category_decisions(cases)
    recommended_categories = [
        category for category, decision in category_decisions.items() if decision["recommended"]
    ]
    failure_reasons: list[str] = []
    if not (compaction["all_cases_pass"] and compaction["aggregate_pass"]):
        failure_reasons.append("compaction_below_60_percent")
    if any(not decision["no_quality_regression"] for decision in category_decisions.values()):
        failure_reasons.append("quality_or_freshness_regression")
    if failure_reasons:
        status = "fail"
        inconclusive_reasons: list[str] = []
    elif recommended_categories:
        status = "pass"
        inconclusive_reasons = []
    else:
        status = "inconclusive"
        inconclusive_reasons = ["no_named_category_with_safe_reproducible_benefit"]
    return {
        "kind": "repoground_vs_grep_read_benchmark",
        "version": "v2",
        "status": status,
        "acceptance": {
            "same_question_set": True,
            "same_k": k,
            "compaction_required_percent": COMPACTION_REQUIRED_PERCENT,
            "failure_reasons": failure_reasons,
            "inconclusive_reasons": inconclusive_reasons,
            "recommended_categories": recommended_categories,
            "preference_recommendation": "repoground" if recommended_categories else None,
        },
        "category_decisions": category_decisions,
        "configuration": {"k": k, "read_limit_bytes": READ_LIMIT_BYTES, "token_proxy_bytes_per_token": TOKEN_PROXY_BYTES_PER_TOKEN},
        "inputs": {
            "benchmark_script_sha256": _sha256(Path(__file__)),
            "index_sha256": _sha256(index),
            "questions_sha256": _sha256(questions_path),
            "repo_tree_sha256": _tree_sha256(root),
            "index_path": index.name,
            "repo_root": ".",
            "absolute_paths_persisted": False,
        },
        "environment": {"python": sys.version.split()[0], "platform": platform.platform(), "pid": os.getpid()},
        "cases": cases,
        "aggregates": aggregates,
        "does_not_establish": ["repository_understanding", "answer_correctness", "unmeasured_query_quality"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", required=True, type=Path)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--questions", type=Path, default=Path("docs/retrieval/review_queries.v1.json"))
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    report = run(args.index, args.repo_root, args.questions, args.k)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 1 if report["status"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
