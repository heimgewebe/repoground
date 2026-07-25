#!/usr/bin/env python3
"""Compare RepoGround core-path benchmarks across two bound revisions."""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

TIMING_REGRESSION_PCT_MAX = 5.0
PEAK_MEMORY_REGRESSION_PCT_MAX = 5.0
BENCHMARK_RELATIVE = Path("scripts/benchmarks/repoground_core_paths.py")
MEASURED_FIELDS = ("wall_seconds_median", "peak_traced_bytes")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def _git_value(root: Path, expression: str) -> str | None:
    completed = subprocess.run(
        ["git", "rev-parse", expression],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip() if completed.returncode == 0 else None


def _git_dirty(root: Path) -> bool | None:
    completed = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    return bool(completed.stdout.strip()) if completed.returncode == 0 else None


def _percent_change(before: float, after: float) -> float:
    if before == 0:
        return 0.0 if after == 0 else float("inf")
    return ((after - before) / before) * 100.0


def _run_benchmark(root: Path, samples: int, output: Path) -> dict[str, Any]:
    command = [
        sys.executable,
        str(root / BENCHMARK_RELATIVE),
        "--samples",
        str(samples),
        "--out",
        str(output),
    ]
    completed = subprocess.run(
        command,
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"benchmark failed in {root}: {completed.stderr.strip()[-1000:]}"
        )
    payload = json.loads(output.read_text(encoding="utf-8"))
    if payload.get("status") != "pass":
        raise RuntimeError(f"benchmark report is not pass in {root}")
    return payload


def _aggregate_case(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if all("skipped" in row for row in rows):
        reasons = sorted({str(row["skipped"]) for row in rows})
        return {"skipped": reasons, "rounds": len(rows)}
    if any("skipped" in row for row in rows):
        raise RuntimeError("case is measured in only a subset of rounds")
    for field in MEASURED_FIELDS:
        if any(field not in row for row in rows):
            raise RuntimeError(f"measured case lacks {field}")
    return {
        "rounds": len(rows),
        "samples_per_round": [int(row["samples"]) for row in rows],
        "wall_seconds_medians": [float(row["wall_seconds_median"]) for row in rows],
        "wall_seconds_median": round(
            statistics.median(float(row["wall_seconds_median"]) for row in rows), 6
        ),
        "peak_traced_bytes_samples": [int(row["peak_traced_bytes"]) for row in rows],
        "peak_traced_bytes": int(
            statistics.median(int(row["peak_traced_bytes"]) for row in rows)
        ),
    }


def _aggregate_reports(reports: list[dict[str, Any]]) -> dict[str, Any]:
    case_names = sorted({name for report in reports for name in report["cases"]})
    return {
        name: _aggregate_case([report["cases"][name] for report in reports])
        for name in case_names
    }


def _compare_case(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    if "skipped" in before or "skipped" in after:
        if before.get("skipped") != after.get("skipped"):
            return {
                "status": "fail",
                "reason": "skip contract differs",
                "before": before,
                "after": after,
            }
        return {"status": "skip", "before": before, "after": after}
    timing_change = _percent_change(
        float(before["wall_seconds_median"]), float(after["wall_seconds_median"])
    )
    memory_change = _percent_change(
        float(before["peak_traced_bytes"]), float(after["peak_traced_bytes"])
    )
    timing_pass = timing_change <= TIMING_REGRESSION_PCT_MAX
    memory_pass = memory_change <= PEAK_MEMORY_REGRESSION_PCT_MAX
    return {
        "status": "pass" if timing_pass and memory_pass else "fail",
        "before": before,
        "after": after,
        "median_regression_pct": round(timing_change, 3),
        "peak_memory_regression_pct": round(memory_change, 3),
        "timing_pass": timing_pass,
        "memory_pass": memory_pass,
    }


def _validate_reports(
    before_reports: list[dict[str, Any]],
    after_reports: list[dict[str, Any]],
    samples: int,
) -> dict[str, Any]:
    all_reports = before_reports + after_reports
    script_hashes = {report["binding"]["benchmark_script_sha256"] for report in all_reports}
    environments = {
        (
            report["environment"]["python"],
            report["environment"]["platform"],
            report["environment"]["processor"],
        )
        for report in all_reports
    }
    sample_counts = {int(report["configuration"]["samples"]) for report in all_reports}
    findings: list[str] = []
    if len(script_hashes) != 1:
        findings.append("benchmark script hash differs")
    if len(environments) != 1:
        findings.append("benchmark environment differs")
    if sample_counts != {samples}:
        findings.append("sample count differs from requested contract")
    return {
        "status": "pass" if not findings else "fail",
        "findings": findings,
        "benchmark_script_sha256": next(iter(script_hashes)) if len(script_hashes) == 1 else None,
        "environment": list(environments)[0] if len(environments) == 1 else None,
    }


def compare(
    before_root: Path,
    after_root: Path,
    *,
    before_commit: str,
    before_tree: str,
    after_commit: str,
    after_tree: str,
    rounds: int,
    samples: int,
    warmups: int,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    before_script = before_root / BENCHMARK_RELATIVE
    after_script = after_root / BENCHMARK_RELATIVE
    if _sha256(before_script) != _sha256(after_script):
        raise RuntimeError("benchmark scripts are not byte-identical")
    live_after_commit = _git_value(after_root, "HEAD")
    live_after_tree = _git_value(after_root, "HEAD^{tree}")
    if live_after_commit != after_commit or live_after_tree != after_tree:
        raise RuntimeError("after revision binding does not match live checkout")
    if _git_dirty(after_root) is not False:
        raise RuntimeError("after worktree must be clean")

    before_reports: list[dict[str, Any]] = []
    after_reports: list[dict[str, Any]] = []
    execution_order: list[str] = []
    with tempfile.TemporaryDirectory(prefix="repoground-t009-benchmark-") as raw:
        temp = Path(raw)
        for warmup in range(warmups):
            _run_benchmark(before_root, 1, temp / f"warmup-before-{warmup}.json")
            _run_benchmark(after_root, 1, temp / f"warmup-after-{warmup}.json")
        for index in range(rounds):
            order = ("before", "after") if index % 2 == 0 else ("after", "before")
            for label in order:
                execution_order.append(label)
                root = before_root if label == "before" else after_root
                report = _run_benchmark(
                    root, samples, temp / f"round-{index:02d}-{label}.json"
                )
                (before_reports if label == "before" else after_reports).append(report)

    validation = _validate_reports(before_reports, after_reports, samples)
    before_cases = _aggregate_reports(before_reports)
    after_cases = _aggregate_reports(after_reports)
    if set(before_cases) != set(after_cases):
        raise RuntimeError("measured case sets differ")
    comparisons = {
        name: _compare_case(before_cases[name], after_cases[name])
        for name in sorted(before_cases)
    }
    failures = [name for name, row in comparisons.items() if row["status"] == "fail"]
    status = "pass" if validation["status"] == "pass" and not failures else "fail"
    common = {
        "kind": "repoground.core_path_benchmark.aggregate",
        "version": "1.0",
        "configuration": {
            "rounds": rounds,
            "samples_per_round": samples,
            "warmups_per_revision": warmups,
            "primary_timing_metric": "median of per-round wall_seconds_median",
            "primary_memory_metric": "median of per-round peak_traced_bytes",
            "execution_order": execution_order,
            "timing_gate": {
                "median_regression_pct_max": TIMING_REGRESSION_PCT_MAX,
                "peak_memory_regression_pct_max": PEAK_MEMORY_REGRESSION_PCT_MAX,
            },
        },
        "environment": {
            "host": platform.node(),
            "python_executable": sys.executable,
            "validated_benchmark_environment": validation["environment"],
        },
        "benchmark_script_sha256": validation["benchmark_script_sha256"],
    }
    before = common | {
        "side": "before",
        "binding": {
            "commit": before_commit,
            "tree": before_tree,
            "source": "git_archive",
            "worktree_dirty": False,
        },
        "cases": before_cases,
    }
    after = common | {
        "side": "after",
        "binding": {
            "commit": after_commit,
            "tree": after_tree,
            "source": "clean_git_worktree",
            "worktree_dirty": False,
        },
        "cases": after_cases,
    }
    comparison = {
        "kind": "repoground.core_path_benchmark.comparison",
        "version": "1.0",
        "status": status,
        "validation": validation,
        "gate": common["configuration"]["timing_gate"],
        "compared_cases": comparisons,
        "failed_cases": failures,
        "bindings": {"before": before["binding"], "after": after["binding"]},
        "does_not_establish": [
            "cross-host comparability",
            "absence of regressions on unmeasured paths",
            "production workload representativeness",
            "memory use outside Python tracemalloc",
        ],
    }
    return before, after, comparison


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--before-root", type=Path, required=True)
    parser.add_argument("--after-root", type=Path, required=True)
    parser.add_argument("--before-commit", required=True)
    parser.add_argument("--before-tree", required=True)
    parser.add_argument("--after-commit", required=True)
    parser.add_argument("--after-tree", required=True)
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.rounds < 2 or args.samples < 1 or args.warmups < 0:
        parser.error("rounds >= 2, samples >= 1 and warmups >= 0 are required")
    before, after, comparison = compare(
        args.before_root.resolve(),
        args.after_root.resolve(),
        before_commit=args.before_commit,
        before_tree=args.before_tree,
        after_commit=args.after_commit,
        after_tree=args.after_tree,
        rounds=args.rounds,
        samples=args.samples,
        warmups=args.warmups,
    )
    args.out_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "repoground-legacy-t009-performance.before.json": before,
        "repoground-legacy-t009-performance.after.json": after,
        "repoground-legacy-t009-performance.comparison.json": comparison,
    }
    for name, payload in outputs.items():
        (args.out_dir / name).write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    return 0 if comparison["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
