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
# Timeout per benchmark invocation in seconds.  Prevents runaway runners from
# blocking CI indefinitely.
_BENCHMARK_TIMEOUT_SECONDS = 300


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


def _git_object_exists_at(root: Path, revision: str) -> bool:
    completed = subprocess.run(
        ["git", "cat-file", "-e", revision],
        cwd=root,
        check=False,
        capture_output=True,
    )
    return completed.returncode == 0


def _git_dirty(root: Path) -> bool | None:
    completed = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    return bool(completed.stdout.strip()) if completed.returncode == 0 else None


def _git_blob_sha256(commit: str, path: str, root: Path) -> str | None:
    """Compute SHA-256 of a blob at ``commit:path`` for content binding."""
    try:
        completed = subprocess.run(
            ["git", "show", f"{commit}:{path}"],
            cwd=root,
            check=True,
            capture_output=True,
        )
        return hashlib.sha256(completed.stdout).hexdigest()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


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
    try:
        completed = subprocess.run(
            command,
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            timeout=_BENCHMARK_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"benchmark timed out after {_BENCHMARK_TIMEOUT_SECONDS}s in {root}: {exc}"
        ) from exc
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
        # Normalize: flatten skip reasons to sorted unique strings
        flat_reasons: list[str] = []
        for row in rows:
            val = row["skipped"]
            if isinstance(val, list):
                flat_reasons.extend(str(r) for r in val)
            else:
                flat_reasons.append(str(val))
        return {
            "skipped": sorted(set(flat_reasons)),
            "rounds": len(rows),
            "samples_per_round": [
                int(row["samples"]) if "samples" in row else "unknown"
                for row in rows
            ],
        }
    if any("skipped" in row for row in rows):
        # Partial skip: structured contract failure.  All or nothing.
        return {
            "skipped": ["partial_skip_not_allowed"],
            "rounds": len(rows),
            "status": "fail",
        }
    for field in MEASURED_FIELDS:
        if any(field not in row for row in rows):
            return {
                "skipped": [f"missing_field_{field}"],
                "rounds": len(rows),
                "status": "fail",
            }
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
    # Structural failures must never be reclassified as ordinary skips.
    if before.get("status") == "fail" or after.get("status") == "fail":
        return {
            "status": "fail",
            "reason": "structural measurement failure",
            "before": before,
            "after": after,
        }
    if "skipped" in before or "skipped" in after:
        contract_fields = ("skipped", "rounds", "samples_per_round")
        before_contract = {field: before.get(field) for field in contract_fields}
        after_contract = {field: after.get(field) for field in contract_fields}
        if before_contract != after_contract:
            return {
                "status": "fail",
                "reason": "skip contract differs",
                "before": before,
                "after": after,
            }
        return {"status": "skip", "before": before, "after": after}
    # Fail-closed: both sides must have required measurement fields
    for side_label, side_data in [("before", before), ("after", after)]:
        for field in MEASURED_FIELDS:
            if field not in side_data or side_data[field] is None:
                return {
                    "status": "fail",
                    "reason": f"{side_label} missing measurement field {field}",
                    "before": before,
                    "after": after,
                }
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


def _validate_before_content_binding(
    before_root: Path,
    before_commit: str,
    before_tree: str,
    benchmark_script_path: str,
) -> dict[str, Any]:
    """Verify that the 'before' checkout content matches the claimed commit.

    Fail-closed: before_root must be an authoritative Git checkout of the
    claimed commit/tree identity, clean, with claimed commit available.
    No self-attested CLI copy.
    """
    findings: list[str] = []
    live_commit = _git_value(before_root, "HEAD")
    if live_commit != before_commit:
        findings.append(
            f"before HEAD ({live_commit}) does not match claimed commit ({before_commit})"
        )
    live_tree = _git_value(before_root, "HEAD^{tree}")
    if live_tree is None:
        findings.append("before HEAD^{tree} is unavailable (shallow or broken checkout)")
    # Verify claimed before_tree matches live HEAD^{tree} exactly
    if live_tree is not None and live_tree != before_tree:
        findings.append(
            f"before live tree ({live_tree}) does not match claimed before_tree ({before_tree})"
        )
    # Verify before worktree is clean — dirty must be exactly False, None is error
    dirty = _git_dirty(before_root)
    if dirty is None:
        findings.append("before worktree dirty status could not be determined")
    elif dirty is True:
        findings.append("before worktree is dirty (expected clean)")
    # Verify claimed commit is reachable
    if not _git_object_exists_at(before_root, before_commit):
        findings.append(f"claimed before_commit {before_commit} is not reachable")
    # Verify benchmark script content identity against the claimed commit
    live_script_hash = _sha256(before_root / benchmark_script_path)
    claimed_script_hash = _git_blob_sha256(before_commit, benchmark_script_path, before_root)
    if claimed_script_hash is None:
        findings.append(
            f"benchmark script {benchmark_script_path} not found at claimed commit"
        )
    elif live_script_hash != claimed_script_hash:
        findings.append(
            "before benchmark script content does not match claimed commit blob"
        )
    return {
        "status": "pass" if not findings else "fail",
        "findings": findings,
        "live_commit": live_commit,
        "live_tree": live_tree,
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

    # Fail-closed: validate before content binding against claimed commit
    before_binding_check = _validate_before_content_binding(
        before_root, before_commit, before_tree, str(BENCHMARK_RELATIVE)
    )
    if before_binding_check["status"] == "fail":
        raise RuntimeError(
            f"before content binding failed: {'; '.join(before_binding_check['findings'])}"
        )

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
            "gate_kind": "performance_smoke_gate",
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
            "source": "clean_git_worktree",
            "worktree_dirty": False,
        },
        "content_binding": before_binding_check,
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
        "before_content_binding": before_binding_check,
        "gate": common["configuration"]["timing_gate"],
        "compared_cases": comparisons,
        "failed_cases": failures,
        "bindings": {"before": before["binding"], "after": after["binding"]},
        "does_not_establish": [
            "cross-host comparability",
            "absence of regressions on unmeasured paths",
            "production workload representativeness",
            "memory use outside Python tracemalloc",
            "statistical significance",
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
