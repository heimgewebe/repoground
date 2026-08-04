"""Benchmark cold, bounded-parallel, warm and small-delta call-graph builds."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import statistics
import tempfile
import time
import tracemalloc
from pathlib import Path
from typing import Any, Callable

from merger.repoground.architecture.call_graph import (
    CALL_GRAPH_PRODUCER_VERSION,
    DEFAULT_CALL_GRAPH_MAX_IN_FLIGHT_BYTES,
    DEFAULT_CALL_GRAPH_MAX_WORKERS,
    CallGraphBuildCache,
    extract_python_calls,
)
from merger.repoground.architecture.symbol_index import EXCLUDED_DIRS

BuildResult = tuple[dict[str, Any], dict[str, Any]]


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _timing_summary(samples: list[float]) -> dict[str, float | int]:
    ordered = sorted(samples)
    p95_index = max(0, min(len(ordered) - 1, round(len(ordered) * 0.95) - 1))
    return {
        "repetitions": len(ordered),
        "median_ms": statistics.median(ordered),
        "p95_ms": ordered[p95_index],
        "min_ms": ordered[0],
        "max_ms": ordered[-1],
    }


def _result_payload(
    calls: list[dict[str, Any]],
    skipped_files_count: int,
    skipped_errors: list[str],
) -> dict[str, Any]:
    return {
        "calls": calls,
        "skipped_files_count": skipped_files_count,
        "skipped_errors": skipped_errors,
    }


def _build(
    repo_root: Path,
    *,
    cache: CallGraphBuildCache,
    max_workers: int,
    max_in_flight_bytes: int,
) -> BuildResult:
    report: dict[str, Any] = {}
    calls, skipped_count, skipped_errors = extract_python_calls(
        repo_root,
        cache=cache,
        max_workers=max_workers,
        max_in_flight_bytes=max_in_flight_bytes,
        build_report=report,
    )
    return _result_payload(calls, skipped_count, skipped_errors), report


def _measure(
    fn: Callable[[], BuildResult],
    repetitions: int,
) -> dict[str, Any]:
    elapsed_samples: list[float] = []
    parent_peak_bytes: list[int] = []
    result_digests: set[str] = set()
    representative_report: dict[str, Any] | None = None
    for _ in range(repetitions):
        tracemalloc.start()
        started = time.perf_counter_ns()
        try:
            payload, report = fn()
            elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        elapsed_samples.append(elapsed_ms)
        parent_peak_bytes.append(peak)
        result_digests.add(_sha256_bytes(_canonical_bytes(payload)))
        representative_report = report
    if len(result_digests) != 1:
        raise RuntimeError(
            f"nondeterministic benchmark results: {sorted(result_digests)}"
        )
    return {
        "timing": _timing_summary(elapsed_samples),
        "parent_peak_bytes": max(parent_peak_bytes),
        "result_sha256": next(iter(result_digests)),
        "build_report": representative_report,
        "memory_scope": (
            "Parent-process Python allocations plus the producer's explicit "
            "source-payload budget; child-process RSS is not measured."
        ),
    }


def _copy_python_corpus(source_root: Path, destination_root: Path) -> dict[str, Any]:
    manifest: list[dict[str, Any]] = []
    for root, dirs, files in os.walk(source_root, topdown=True):
        dirs[:] = sorted(
            directory for directory in dirs if directory not in EXCLUDED_DIRS
        )
        for file_name in sorted(files):
            if not file_name.endswith(".py"):
                continue
            source = Path(root) / file_name
            if source.is_symlink() or not source.is_file():
                continue
            relative = source.relative_to(source_root)
            destination = destination_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
            size_bytes = destination.stat().st_size
            manifest.append(
                {
                    "path": relative.as_posix(),
                    "size_bytes": size_bytes,
                    "sha256": _sha256_file(destination),
                }
            )
    if not manifest:
        raise RuntimeError(f"no Python files found under {source_root}")
    return {
        "python_file_count": len(manifest),
        "python_source_bytes": sum(item["size_bytes"] for item in manifest),
        "manifest_sha256": _sha256_bytes(_canonical_bytes(manifest)),
    }


def _largest_python_file(repo_root: Path) -> Path:
    candidates = [path for path in repo_root.rglob("*.py") if path.is_file()]
    if not candidates:
        raise RuntimeError("benchmark corpus has no Python files")
    return max(candidates, key=lambda path: (path.stat().st_size, path.as_posix()))


def _measure_small_delta(
    repo_root: Path,
    *,
    target: Path,
    baseline_sha256: str,
    repetitions: int,
    max_workers: int,
    max_in_flight_bytes: int,
) -> dict[str, Any]:
    elapsed_samples: list[float] = []
    parent_peak_bytes: list[int] = []
    delta_digests: set[str] = set()
    clean_digests: set[str] = set()
    representative_report: dict[str, Any] | None = None
    original = target.read_bytes()
    for repetition in range(repetitions):
        cache = CallGraphBuildCache()
        baseline, _ = _build(
            repo_root,
            cache=cache,
            max_workers=1,
            max_in_flight_bytes=max_in_flight_bytes,
        )
        observed_baseline = _sha256_bytes(_canonical_bytes(baseline))
        if observed_baseline != baseline_sha256:
            raise RuntimeError("small-delta baseline drifted before mutation")
        marker = f"\n# repoground call-graph benchmark delta {repetition}\n".encode()
        target.write_bytes(original + marker)
        try:
            tracemalloc.start()
            started = time.perf_counter_ns()
            try:
                incremental, report = _build(
                    repo_root,
                    cache=cache,
                    max_workers=max_workers,
                    max_in_flight_bytes=max_in_flight_bytes,
                )
                elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
                _, peak = tracemalloc.get_traced_memory()
            finally:
                tracemalloc.stop()
            clean, _ = _build(
                repo_root,
                cache=CallGraphBuildCache(),
                max_workers=1,
                max_in_flight_bytes=max_in_flight_bytes,
            )
        finally:
            target.write_bytes(original)
        incremental_sha = _sha256_bytes(_canonical_bytes(incremental))
        clean_sha = _sha256_bytes(_canonical_bytes(clean))
        if incremental_sha != clean_sha:
            raise RuntimeError("small-delta build differs from a clean serial rebuild")
        elapsed_samples.append(elapsed_ms)
        parent_peak_bytes.append(peak)
        delta_digests.add(incremental_sha)
        clean_digests.add(clean_sha)
        representative_report = report
    return {
        "timing": _timing_summary(elapsed_samples),
        "parent_peak_bytes": max(parent_peak_bytes),
        "result_sha256": sorted(delta_digests),
        "clean_result_sha256": sorted(clean_digests),
        "byte_equivalent_to_clean": delta_digests == clean_digests,
        "build_report": representative_report,
        "mutated_path": target.relative_to(repo_root).as_posix(),
        "mutation": "append one comment in the temporary corpus",
        "memory_scope": (
            "Parent-process Python allocations plus the producer's explicit "
            "source-payload budget; child-process RSS is not measured."
        ),
    }


def _ratio(numerator: float, denominator: float) -> float:
    return numerator / max(denominator, 1e-9)


def benchmark(
    source_root: Path,
    *,
    repetitions: int,
    max_workers: int,
    max_in_flight_bytes: int,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="repoground-call-graph-bench-") as temp:
        corpus_root = Path(temp) / "corpus"
        corpus = _copy_python_corpus(source_root, corpus_root)

        cold_serial = _measure(
            lambda: _build(
                corpus_root,
                cache=CallGraphBuildCache(),
                max_workers=1,
                max_in_flight_bytes=max_in_flight_bytes,
            ),
            repetitions,
        )
        baseline_sha = str(cold_serial["result_sha256"])

        cold_parallel = _measure(
            lambda: _build(
                corpus_root,
                cache=CallGraphBuildCache(),
                max_workers=max_workers,
                max_in_flight_bytes=max_in_flight_bytes,
            ),
            repetitions,
        )

        warm_cache = CallGraphBuildCache()
        warm_seed, warm_seed_report = _build(
            corpus_root,
            cache=warm_cache,
            max_workers=1,
            max_in_flight_bytes=max_in_flight_bytes,
        )
        if _sha256_bytes(_canonical_bytes(warm_seed)) != baseline_sha:
            raise RuntimeError("warm-cache seed differs from cold serial result")
        warm = _measure(
            lambda: _build(
                corpus_root,
                cache=warm_cache,
                max_workers=max_workers,
                max_in_flight_bytes=max_in_flight_bytes,
            ),
            repetitions,
        )
        warm["seed_build_report"] = warm_seed_report

        small_delta = _measure_small_delta(
            corpus_root,
            target=_largest_python_file(corpus_root),
            baseline_sha256=baseline_sha,
            repetitions=repetitions,
            max_workers=max_workers,
            max_in_flight_bytes=max_in_flight_bytes,
        )

    serial_median = float(cold_serial["timing"]["median_ms"])
    parallel_median = float(cold_parallel["timing"]["median_ms"])
    warm_median = float(warm["timing"]["median_ms"])
    delta_median = float(small_delta["timing"]["median_ms"])
    parallel_equivalent = cold_parallel["result_sha256"] == baseline_sha
    warm_equivalent = warm["result_sha256"] == baseline_sha
    delta_equivalent = bool(small_delta["byte_equivalent_to_clean"])
    parallel_report = cold_parallel.get("build_report") or {}
    parallel_speedup = _ratio(serial_median, parallel_median)
    warm_speedup = _ratio(serial_median, warm_median)
    delta_speedup = _ratio(serial_median, delta_median)

    parallel_retained = bool(
        parallel_equivalent
        and not parallel_report.get("parallel_fallback")
        and int(parallel_report.get("parallel_files", 0)) > 0
        and parallel_speedup >= 1.0
    )
    cache_retained = bool(
        warm_equivalent
        and delta_equivalent
        and warm_speedup >= 1.0
        and delta_speedup >= 1.0
    )
    regressions = []
    if parallel_speedup < 1.0:
        regressions.append("cold_parallel_slower_than_cold_serial")
    if warm_speedup < 1.0:
        regressions.append("warm_cache_slower_than_cold_serial")
    if delta_speedup < 1.0:
        regressions.append("small_delta_slower_than_cold_serial")

    return {
        "schema_version": 1,
        "kind": "repoground_call_graph_incremental_parallel_measurement",
        "producer_version": CALL_GRAPH_PRODUCER_VERSION,
        "observed_at_unix": int(time.time()),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "cpu_count": os.cpu_count(),
        },
        "configuration": {
            "repetitions": repetitions,
            "max_workers": max_workers,
            "max_in_flight_bytes": max_in_flight_bytes,
        },
        "corpus": corpus,
        "cold_serial": cold_serial,
        "cold_parallel": cold_parallel,
        "warm_unchanged": warm,
        "small_delta": small_delta,
        "equivalence": {
            "cold_parallel": parallel_equivalent,
            "warm_unchanged": warm_equivalent,
            "small_delta_clean_rebuild": delta_equivalent,
        },
        "speedup": {
            "cold_parallel_vs_serial_median": parallel_speedup,
            "warm_unchanged_vs_cold_serial_median": warm_speedup,
            "small_delta_vs_cold_serial_median": delta_speedup,
        },
        "decision": {
            "parallel_optimization_retained": parallel_retained,
            "cache_optimization_retained": cache_retained,
            "regressions": regressions,
            "status": "pass" if parallel_retained and cache_retained else "review",
        },
        "does_not_establish": [
            "faster_all_repositories",
            "child_process_peak_rss",
            "semantic_correctness_beyond_equivalence_to_the_serial_producer",
            "production_capacity_or_slo_compliance",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", type=Path)
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument(
        "--max-workers",
        type=int,
        default=DEFAULT_CALL_GRAPH_MAX_WORKERS,
    )
    parser.add_argument(
        "--max-in-flight-bytes",
        type=int,
        default=DEFAULT_CALL_GRAPH_MAX_IN_FLIGHT_BYTES,
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.repetitions < 1:
        parser.error("--repetitions must be positive")
    if args.max_workers < 1:
        parser.error("--max-workers must be positive")
    if args.max_in_flight_bytes < 1:
        parser.error("--max-in-flight-bytes must be positive")

    result = benchmark(
        args.repo.resolve(),
        repetitions=args.repetitions,
        max_workers=args.max_workers,
        max_in_flight_bytes=args.max_in_flight_bytes,
    )
    rendered = json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result["decision"]["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
