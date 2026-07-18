"""Benchmark linear, process-local and persisted call-navigation strategies."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import statistics
import tempfile
import time
import tracemalloc
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Sequence

from merger.repoground.architecture.call_graph import extract_python_calls
from merger.repoground.core import mcp_tools
from merger.repoground.core.bundle_identity import (
    CANONICAL_BUNDLE_KIND,
    CANONICAL_BUNDLE_VERSION,
)
from merger.repoground.core.call_navigation_index import (
    CallNavigationIndex,
    linear_calls_for_symbol,
    linear_reference_calls,
    linear_target_related_calls,
)
from merger.repoground.core.bundle_access import _clear_call_navigation_caches

DEFAULT_SYNTHETIC_CALL_COUNT = 50_000


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _distribution(fn: Callable[[], Any], repetitions: int) -> dict[str, Any]:
    samples = []
    for _ in range(repetitions):
        started = time.perf_counter_ns()
        fn()
        samples.append((time.perf_counter_ns() - started) / 1_000_000)
    ordered = sorted(samples)
    p95_index = max(0, min(len(ordered) - 1, int(len(ordered) * 0.95) - 1))
    return {
        "repetitions": repetitions,
        "median_ms": statistics.median(ordered),
        "p95_ms": ordered[p95_index],
        "min_ms": ordered[0],
        "max_ms": ordered[-1],
    }


def _timed_memory(fn: Callable[[], Any]) -> tuple[Any, float, int, int]:
    tracemalloc.start()
    started = time.perf_counter_ns()
    try:
        value = fn()
        elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
        retained, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return value, elapsed_ms, retained, peak


def _synthetic_symbol(
    symbol_id: str,
    *,
    name: str,
    path: str,
    start_line: int = 1,
    end_line: int = 100_000,
) -> dict[str, Any]:
    return {
        "id": symbol_id,
        "kind": "function",
        "name": name,
        "qualified_name": name,
        "module": path.removesuffix(".py").replace("/", "."),
        "path": path,
        "start_line": start_line,
        "end_line": end_line,
        "range_ref": f"file:{path}#L{start_line}-L{end_line}",
        "decorators": [],
    }


def synthetic_corpus(
    call_count: int,
    *,
    target_count: int = 500,
    caller_count: int = 1_000,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    calls = []
    for position in range(call_count):
        target = position % target_count
        caller = position % caller_count
        status_slot = position % 10
        if status_slot < 8:
            status = "resolved"
            evidence = "S1"
        elif status_slot == 8:
            status = "candidate"
            evidence = "S0"
        else:
            status = "unresolved"
            evidence = "S0"
        target_id = f"py:pkg:targets/t{target}.py:function:target_{target}"
        caller_id = f"py:pkg:callers/c{caller}.py:function:caller_{caller}"
        line = position // caller_count + 2
        expression = (
            f"registry.handlers.target_{target}"
            if position % 7 == 0
            else f"target_{target}"
        )
        calls.append(
            {
                "path": f"pkg/callers/c{caller}.py",
                "start_line": line,
                "start_col": position % 17,
                "end_line": line,
                "end_col": position % 17 + len(expression) + 2,
                "range_ref": f"file:pkg/callers/c{caller}.py#L{line}-L{line}",
                "callee_expression": expression,
                "simple_name": f"target_{target}",
                "caller_scope": "symbol",
                "caller_symbol_id": caller_id,
                "caller_qualified_name": f"caller_{caller}",
                "caller_kind": "function",
                "caller_start_line": 1,
                "caller_end_line": 100_000,
                "relation_type": "calls",
                "evidence_level": evidence,
                "resolution_status": status,
                "resolution_reason": f"synthetic_{status}",
                "resolved_target_ids": [target_id] if status == "resolved" else [],
                "candidate_target_ids": [target_id] if status == "candidate" else [],
            }
        )
    symbols = [
        _synthetic_symbol(
            f"py:pkg:targets/t{target}.py:function:target_{target}",
            name=f"target_{target}",
            path=f"pkg/targets/t{target}.py",
        )
        for target in range(target_count)
    ]
    symbols.extend(
        _synthetic_symbol(
            f"py:pkg:callers/c{caller}.py:function:caller_{caller}",
            name=f"caller_{caller}",
            path=f"pkg/callers/c{caller}.py",
        )
        for caller in range(caller_count)
    )
    return calls, symbols


def _query_set(calls: Sequence[dict[str, Any]], limit: int = 20) -> dict[str, Any]:
    name_counts = Counter(
        str(call.get("simple_name", "")).casefold()
        for call in calls
        if call.get("simple_name")
    )
    references = [
        name
        for name, _ in sorted(
            name_counts.items(), key=lambda item: (-item[1], item[0])
        )[:limit]
    ]

    targets: dict[tuple[str, str], None] = {}
    callers: dict[tuple[Any, ...], dict[str, Any]] = {}
    for call in calls:
        simple_name = str(call.get("simple_name", "")).casefold()
        for target_id in [
            *call.get("resolved_target_ids", []),
            *call.get("candidate_target_ids", []),
        ]:
            targets.setdefault((str(target_id), simple_name), None)
        caller_id = call.get("caller_symbol_id")
        if isinstance(caller_id, str):
            identity = (
                caller_id,
                call.get("path"),
                call.get("caller_qualified_name"),
                call.get("caller_kind"),
                call.get("caller_start_line"),
                call.get("caller_end_line"),
            )
            callers.setdefault(
                identity,
                {
                    "id": caller_id,
                    "path": call.get("path"),
                    "qualified_name": call.get("caller_qualified_name"),
                    "kind": call.get("caller_kind"),
                    "start_line": call.get("caller_start_line"),
                    "end_line": call.get("caller_end_line"),
                },
            )
    return {
        "references": references,
        "targets": [list(item) for item in sorted(targets)[:limit]],
        "callers": [callers[key] for key in sorted(callers)[:limit]],
    }


def _linear_result(
    calls: Sequence[dict[str, Any]], queries: dict[str, Any]
) -> dict[str, Any]:
    return {
        "references": [
            linear_reference_calls(calls, query) for query in queries["references"]
        ],
        "targets": [
            linear_target_related_calls(calls, target_id, query)
            for target_id, query in queries["targets"]
        ],
        "callers": [
            linear_calls_for_symbol(calls, symbol) for symbol in queries["callers"]
        ],
    }


def _indexed_result(
    index: CallNavigationIndex, queries: dict[str, Any]
) -> dict[str, Any]:
    return {
        "references": [index.reference_calls(query) for query in queries["references"]],
        "targets": [
            index.target_related_calls(target_id, query)
            for target_id, query in queries["targets"]
        ],
        "callers": [index.calls_for_symbol(symbol) for symbol in queries["callers"]],
    }


def benchmark_tier(
    calls: Sequence[dict[str, Any]],
    *,
    label: str,
    query_repetitions: int,
    cold_repetitions: int,
) -> dict[str, Any]:
    call_bytes = _canonical_bytes(list(calls))
    source_sha = _sha256(call_bytes)
    queries = _query_set(calls)

    index, build_ms, index_retained_bytes, index_peak_bytes = _timed_memory(
        lambda: CallNavigationIndex.build(calls)
    )
    projection = index.persisted_projection(source_sha)
    sidecar_bytes = _canonical_bytes(projection)
    restored = CallNavigationIndex.from_persisted_projection(
        calls, json.loads(sidecar_bytes), source_sha
    )

    linear_bytes = _canonical_bytes(_linear_result(calls, queries))
    indexed_bytes = _canonical_bytes(_indexed_result(index, queries))
    restored_bytes = _canonical_bytes(_indexed_result(restored, queries))
    equivalent = linear_bytes == indexed_bytes == restored_bytes

    linear_query = _distribution(
        lambda: _linear_result(calls, queries), query_repetitions
    )
    indexed_query = _distribution(
        lambda: _indexed_result(index, queries), query_repetitions
    )
    restored_query = _distribution(
        lambda: _indexed_result(restored, queries), query_repetitions
    )

    def cold_linear() -> None:
        json.loads(call_bytes)

    def cold_memory() -> None:
        parsed = json.loads(call_bytes)
        CallNavigationIndex.build(parsed)

    def cold_persisted() -> None:
        parsed_calls = json.loads(call_bytes)
        parsed_projection = json.loads(sidecar_bytes)
        CallNavigationIndex.from_persisted_projection(
            parsed_calls, parsed_projection, source_sha
        )

    return {
        "label": label,
        "call_count": len(calls),
        "query_counts": {key: len(value) for key, value in queries.items()},
        "call_json_bytes": len(call_bytes),
        "source_calls_sha256": source_sha,
        "equivalence": {
            "status": "pass" if equivalent else "fail",
            "byte_equivalent": equivalent,
            "result_sha256": _sha256(linear_bytes),
        },
        "linear_scan": {
            "bundle_bytes": len(call_bytes),
            "cold_load": _distribution(cold_linear, cold_repetitions),
            "warm_query_batch": linear_query,
        },
        "process_local_index": {
            "bundle_bytes": len(call_bytes),
            "build_ms": build_ms,
            "build_retained_bytes": index_retained_bytes,
            "build_peak_bytes": index_peak_bytes,
            "cold_load_and_build": _distribution(cold_memory, cold_repetitions),
            "warm_query_batch": indexed_query,
        },
        "persisted_sidecar": {
            "bundle_bytes": len(call_bytes) + len(sidecar_bytes),
            "sidecar_bytes": len(sidecar_bytes),
            "bundle_overhead_ratio": len(sidecar_bytes) / max(1, len(call_bytes)),
            "source_hash_bound": True,
            "cold_load_and_restore": _distribution(cold_persisted, cold_repetitions),
            "warm_query_batch": restored_query,
        },
        "speedup": {
            "process_local_vs_linear_warm_median": linear_query["median_ms"]
            / max(indexed_query["median_ms"], 1e-9),
            "persisted_vs_linear_warm_median": linear_query["median_ms"]
            / max(restored_query["median_ms"], 1e-9),
        },
    }


def _count(
    calls: Sequence[dict[str, Any]], field: str, keys: Sequence[str]
) -> dict[str, int]:
    result = {key: 0 for key in keys}
    for call in calls:
        result[str(call[field])] += 1
    return result


def _write_synthetic_bundle(
    root: Path,
    calls: Sequence[dict[str, Any]],
    symbols: Sequence[dict[str, Any]],
) -> Path:
    run_id = "call-navigation-benchmark"
    canonical_sha = "a" * 64
    call_graph = root / "benchmark.python_call_graph.json"
    symbol_index = root / "benchmark.python_symbol_index.json"
    call_payload = {
        "kind": "lenskit.python_call_graph",
        "version": "1.0",
        "run_id": run_id,
        "canonical_dump_index_sha256": canonical_sha,
        "language": "python",
        "evidence_model": {
            "S0": "unresolved or ambiguous static candidate",
            "S1": "one uniquely resolved local target",
        },
        "resolution_statuses": ["resolved", "candidate", "ambiguous", "unresolved"],
        "relation_types": ["calls", "constructs"],
        "call_count": len(calls),
        "resolution_counts": _count(
            calls,
            "resolution_status",
            ("resolved", "candidate", "ambiguous", "unresolved"),
        ),
        "evidence_counts": _count(calls, "evidence_level", ("S0", "S1")),
        "relation_counts": _count(calls, "relation_type", ("calls", "constructs")),
        "calls": list(calls),
        "skipped_files_count": 0,
        "skipped_errors": [],
        "skipped_errors_total_count": 0,
        "skipped_errors_truncated": False,
        "does_not_establish": [
            "complete_call_graph",
            "runtime_reachability",
            "dynamic_dispatch_resolution",
            "dependency_completeness",
            "transitive_import_resolution",
            "import_success",
            "test_sufficiency",
            "review_completeness",
            "merge_readiness",
        ],
    }
    symbol_payload = {
        "kind": "lenskit.python_symbol_index",
        "version": "1.0",
        "run_id": run_id,
        "canonical_dump_index_sha256": canonical_sha,
        "language": "python",
        "symbol_kinds": ["class", "function", "async_function"],
        "symbols": list(symbols),
        "skipped_files_count": 0,
        "skipped_errors": [],
        "does_not_establish": ["call_graph_completeness"],
    }
    call_graph.write_bytes(_canonical_bytes(call_payload))
    symbol_index.write_bytes(_canonical_bytes(symbol_payload))
    manifest = root / "benchmark.bundle.manifest.json"
    manifest.write_bytes(
        _canonical_bytes(
            {
                "kind": CANONICAL_BUNDLE_KIND,
                "version": CANONICAL_BUNDLE_VERSION,
                "run_id": run_id,
                "artifacts": [
                    {
                        "role": "python_symbol_index_json",
                        "path": symbol_index.name,
                        "content_type": "application/json",
                        "bytes": symbol_index.stat().st_size,
                        "sha256": _sha256(symbol_index.read_bytes()),
                    },
                    {
                        "role": "python_call_graph_json",
                        "path": call_graph.name,
                        "content_type": "application/json",
                        "bytes": call_graph.stat().st_size,
                        "sha256": _sha256(call_graph.read_bytes()),
                    },
                ],
            }
        )
    )
    return manifest


def benchmark_mcp(
    calls: Sequence[dict[str, Any]],
    symbols: Sequence[dict[str, Any]],
    *,
    cold_repetitions: int,
    warm_repetitions: int,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="lenskit-call-navigation-bench-") as raw:
        manifest = _write_synthetic_bundle(Path(raw), calls, symbols)

        def batch() -> dict[str, Any]:
            return {
                "references": mcp_tools.find_references(
                    bundle_manifest=manifest, name="target_7", k=25
                ),
                "callers": mcp_tools.get_callers(
                    bundle_manifest=manifest,
                    name="target_7",
                    path="pkg/targets/t7.py",
                    k=25,
                ),
                "callees": mcp_tools.get_callees(
                    bundle_manifest=manifest,
                    name="caller_7",
                    path="pkg/callers/c7.py",
                    k=25,
                ),
            }

        def cold_batch() -> None:
            _clear_call_navigation_caches()
            batch()

        _clear_call_navigation_caches()
        cold_result, cold_first_ms, cold_retained_bytes, cold_peak_bytes = (
            _timed_memory(batch)
        )
        warm_result = batch()
        byte_equivalent = _canonical_bytes(cold_result) == _canonical_bytes(warm_result)
        cold_distribution = _distribution(cold_batch, cold_repetitions)
        _clear_call_navigation_caches()
        batch()
        warm_distribution = _distribution(batch, warm_repetitions)
        _clear_call_navigation_caches()
        return {
            "call_count": len(calls),
            "cold_first_ms": cold_first_ms,
            "cold_first_retained_bytes": cold_retained_bytes,
            "cold_first_peak_bytes": cold_peak_bytes,
            "cold_batch": cold_distribution,
            "warm_repeated_batch": warm_distribution,
            "cold_warm_byte_equivalent": byte_equivalent,
            "result_sha256": _sha256(_canonical_bytes(cold_result)),
        }


def _machine_context() -> dict[str, Any]:
    return {
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "logical_cpu_count": os.cpu_count(),
    }


def run_benchmark(
    repo: str | Path,
    *,
    synthetic_call_count: int = DEFAULT_SYNTHETIC_CALL_COUNT,
    query_repetitions: int = 7,
    cold_repetitions: int = 3,
    mcp_repetitions: int = 10,
    include_real_repo: bool = True,
) -> dict[str, Any]:
    repo_path = Path(repo).expanduser().resolve()
    synthetic_calls, synthetic_symbols = synthetic_corpus(synthetic_call_count)
    tiers = [
        benchmark_tier(
            synthetic_calls,
            label=f"synthetic_{synthetic_call_count}",
            query_repetitions=query_repetitions,
            cold_repetitions=cold_repetitions,
        )
    ]
    skipped_files_count = None
    skipped_errors: list[str] = []
    if include_real_repo:
        real_calls, skipped_files_count, skipped_errors = extract_python_calls(
            repo_path
        )
        tiers.append(
            benchmark_tier(
                real_calls,
                label="representative_real_repo",
                query_repetitions=query_repetitions,
                cold_repetitions=cold_repetitions,
            )
        )
    equivalence_pass = all(tier["equivalence"]["byte_equivalent"] for tier in tiers)
    report = {
        "kind": "repobrief.call_navigation_scale_benchmark",
        "version": "1.0",
        "status": "pass" if equivalence_pass else "fail",
        "machine_context": _machine_context(),
        "configuration": {
            "synthetic_call_count": synthetic_call_count,
            "fixed_acceptance_tier": synthetic_call_count
            == DEFAULT_SYNTHETIC_CALL_COUNT,
            "query_repetitions": query_repetitions,
            "cold_repetitions": cold_repetitions,
            "mcp_repetitions": mcp_repetitions,
            "representative_repo": "current_repository" if include_real_repo else None,
        },
        "representative_repo_parse": {
            "skipped_files_count": skipped_files_count,
            "skipped_errors": skipped_errors[:20],
        },
        "tiers": tiers,
        "mcp": benchmark_mcp(
            synthetic_calls,
            synthetic_symbols,
            cold_repetitions=cold_repetitions,
            warm_repetitions=mcp_repetitions,
        ),
        "decision": {
            "selected": "process_local_in_memory_index",
            "rejected": {
                "linear_scan": "repeated O(call_count) scans and repeated artifact validation",
                "persisted_sidecar": "adds a second bundle artifact and measurable byte overhead without better warm queries",
            },
            "cache_bound": "manifest hash plus artifact identity, declared hash and byte count",
            "cache_max_entries": 2,
        },
        "does_not_establish": [
            "performance_on_all_machines",
            "performance_on_all_repositories",
            "runtime_call_graph_completeness",
            "dynamic_dispatch_resolution",
            "default_promotion_without_equivalence_gates",
        ],
    }
    if not report["mcp"]["cold_warm_byte_equivalent"]:
        report["status"] = "fail"
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--output")
    parser.add_argument(
        "--synthetic-call-count", type=int, default=DEFAULT_SYNTHETIC_CALL_COUNT
    )
    parser.add_argument("--query-repetitions", type=int, default=7)
    parser.add_argument("--cold-repetitions", type=int, default=3)
    parser.add_argument("--mcp-repetitions", type=int, default=10)
    parser.add_argument("--skip-real-repo", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if (
        min(
            args.synthetic_call_count,
            args.query_repetitions,
            args.cold_repetitions,
            args.mcp_repetitions,
        )
        < 1
    ):
        raise SystemExit("benchmark counts must be positive")
    report = run_benchmark(
        args.repo,
        synthetic_call_count=args.synthetic_call_count,
        query_repetitions=args.query_repetitions,
        cold_repetitions=args.cold_repetitions,
        mcp_repetitions=args.mcp_repetitions,
        include_real_repo=not args.skip_real_repo,
    )
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).expanduser().resolve().write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
