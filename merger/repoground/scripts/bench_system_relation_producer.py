"""Revision-bound scale check for the static system-relation producer."""
from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import time
import tracemalloc
from pathlib import Path
from typing import Any

from merger.repoground.core.system_relation_producer import (
    collect_system_relation_evidence,
)


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _p95(samples: list[float]) -> float:
    ordered = sorted(samples)
    index = max(0, min(len(ordered) - 1, round(len(ordered) * 0.95) - 1))
    return ordered[index]


def run_benchmark(
    repository_root: Path,
    *,
    repository_identity: str,
    repository_commit: str,
    repetitions: int,
    max_runtime_ms: float,
    max_peak_bytes: int,
    max_artifact_bytes: int,
) -> dict[str, Any]:
    if repetitions < 1:
        raise ValueError("repetitions must be >= 1")

    elapsed_ms: list[float] = []
    peak_bytes: list[int] = []
    artifact_bytes: list[int] = []
    result_digests: set[str] = set()
    evidence_digests: set[str] = set()
    representative: dict[str, Any] | None = None

    for _ in range(repetitions):
        tracemalloc.start()
        started = time.perf_counter_ns()
        try:
            result = collect_system_relation_evidence(
                repository_root,
                repository_identity=repository_identity,
                repository_commit=repository_commit,
            )
            elapsed = (time.perf_counter_ns() - started) / 1_000_000
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        payload = _canonical_bytes(result)
        elapsed_ms.append(elapsed)
        peak_bytes.append(peak)
        artifact_bytes.append(len(payload))
        result_digests.add(hashlib.sha256(payload).hexdigest())
        evidence_digests.add(result["evidence_sha256"])
        representative = result

    if len(result_digests) != 1 or len(evidence_digests) != 1:
        raise RuntimeError("system-relation producer output was nondeterministic")
    assert representative is not None

    runtime_p95_ms = _p95(elapsed_ms)
    peak_max_bytes = max(peak_bytes)
    artifact_max_bytes = max(artifact_bytes)
    gates = {
        "runtime_p95_ms": {
            "observed": runtime_p95_ms,
            "maximum": max_runtime_ms,
            "passed": runtime_p95_ms <= max_runtime_ms,
        },
        "python_peak_bytes": {
            "observed": peak_max_bytes,
            "maximum": max_peak_bytes,
            "passed": peak_max_bytes <= max_peak_bytes,
        },
        "artifact_bytes": {
            "observed": artifact_max_bytes,
            "maximum": max_artifact_bytes,
            "passed": artifact_max_bytes <= max_artifact_bytes,
        },
        "deterministic_output": {
            "observed_unique_result_digests": len(result_digests),
            "maximum": 1,
            "passed": len(result_digests) == 1,
        },
    }
    return {
        "kind": "repoground.system_relation_producer_benchmark",
        "version": "1.0",
        "repository": {
            "identity": repository_identity,
            "commit": repository_commit,
        },
        "repetitions": repetitions,
        "timing_ms": {
            "median": statistics.median(elapsed_ms),
            "p95": runtime_p95_ms,
            "minimum": min(elapsed_ms),
            "maximum": max(elapsed_ms),
        },
        "python_peak_bytes": peak_max_bytes,
        "artifact_bytes": artifact_max_bytes,
        "result_sha256": next(iter(result_digests)),
        "evidence_sha256": next(iter(evidence_digests)),
        "producer_scan": representative["scan"],
        "record_count": len(representative["evidence"]["records"]),
        "omission_count": len(representative["omissions"]),
        "relation_kinds": representative["overlay"]["relation_kinds"],
        "gates": gates,
        "passed": all(gate["passed"] for gate in gates.values()),
        "memory_scope": (
            "Python allocations in the benchmark process measured with tracemalloc; "
            "short-lived Git child-process RSS is not included."
        ),
        "activation_policy": (
            "This benchmark establishes bounded producer cost only. It does not "
            "authorize broader or default agent-context activation without a paired "
            "agent-utility benefit proof."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--identity", default="heimgewebe/repoground")
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--max-runtime-ms", type=float, default=5000.0)
    parser.add_argument("--max-peak-bytes", type=int, default=64 * 1024 * 1024)
    parser.add_argument("--max-artifact-bytes", type=int, default=2 * 1024 * 1024)
    args = parser.parse_args()

    report = run_benchmark(
        args.repo,
        repository_identity=args.identity,
        repository_commit=args.commit,
        repetitions=args.repetitions,
        max_runtime_ms=args.max_runtime_ms,
        max_peak_bytes=args.max_peak_bytes,
        max_artifact_bytes=args.max_artifact_bytes,
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
