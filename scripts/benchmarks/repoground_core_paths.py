#!/usr/bin/env python3
"""Measure runtime and allocation cost of central RepoGround core paths.

The benchmark drives the real production entry points over a deterministic
synthetic repository so that two runs on the same host are comparable:

  * ``bundle_write_archive``   – ``write_reports_v2`` in archive output mode
  * ``bundle_write_dual``      – ``write_reports_v2`` in dual mode (chunks, sidecars)
  * ``retrieval_index_build``  – ``index_db.build_index`` over the produced bundle
  * ``retrieval_query``        – ``query_core.execute_query`` against that index
  * ``service_app_import``     – cold subprocess import of the service application
  * ``atlas_scan``             – optional Atlas observation subsystem scan

Wall time is reported as the minimum and median of repeated samples; the
minimum is the stable figure because host noise can only add time.  Peak
allocation is measured with ``tracemalloc`` in one separate, unsampled run so
that the tracing overhead never contaminates the timing samples.

No acceptance gate is applied.  Timing on shared hosts is not reproducible
across machines, so this script records evidence and leaves comparison to the
reader; only execution failures are reported as a failing status.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path
from typing import Any, Callable

# Permit direct execution from any checkout directory without installation.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_SAMPLES = 5
FIXTURE_PYTHON_FILES = 60
FIXTURE_MARKDOWN_FILES = 20
FIXTURE_FUNCTIONS_PER_FILE = 12

DOES_NOT_ESTABLISH = [
    "cross-host comparability of absolute timings",
    "absence of regressions on unmeasured paths",
    "production workload representativeness",
    "memory use outside the Python allocator",
]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def _git_commit() -> str | None:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return None
    return completed.stdout.strip() or None


def _git_dirty() -> bool | None:
    completed = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return None
    return bool(completed.stdout.strip())


def build_fixture_repository(root: Path) -> Path:
    """Write a deterministic source tree; identical bytes across runs and hosts."""

    repo_root = root / "benchfixture"
    (repo_root / "src").mkdir(parents=True)
    (repo_root / "docs").mkdir(parents=True)
    for index in range(FIXTURE_PYTHON_FILES):
        lines = [
            '"""Deterministic benchmark module."""',
            "",
            "from __future__ import annotations",
            "",
        ]
        for function in range(FIXTURE_FUNCTIONS_PER_FILE):
            lines.extend(
                [
                    f"def module_{index:03d}_function_{function:02d}(value: int) -> int:",
                    '    """Return a deterministic transform of ``value``."""',
                    f"    total = value * {function + 1}",
                    f"    if total > {index + 1}:",
                    f"        total -= {index + 1}",
                    "    return total",
                    "",
                ]
            )
        (repo_root / "src" / f"module_{index:03d}.py").write_text(
            "\n".join(lines), encoding="utf-8"
        )
    for index in range(FIXTURE_MARKDOWN_FILES):
        body = [f"# Benchmark document {index:03d}", ""]
        for paragraph in range(8):
            body.append(
                f"Section {paragraph} of document {index:03d} describes deterministic "
                "benchmark content used to exercise chunking and retrieval."
            )
            body.append("")
        (repo_root / "docs" / f"document_{index:03d}.md").write_text(
            "\n".join(body), encoding="utf-8"
        )
    (repo_root / "README.md").write_text(
        "# Benchmark fixture\n\nDeterministic RepoGround core-path benchmark input.\n",
        encoding="utf-8",
    )
    return repo_root


class _WorkspaceSequence:
    """Hand out a fresh output directory per invocation.

    ``write_reports_v2`` derives artifact names from a minute-resolution
    timestamp, so repeated samples must not share an output directory.
    """

    def __init__(self, root: Path, name: str) -> None:
        self._root = root / name
        self._counter = 0

    def next(self) -> Path:
        self._counter += 1
        workspace = self._root / f"run{self._counter:03d}"
        workspace.mkdir(parents=True, exist_ok=True)
        return workspace


def _measure(
    operation: Callable[[], Any],
    *,
    samples: int,
    setup: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """Time ``operation`` repeatedly, then measure peak allocation once."""

    durations: list[float] = []
    for _ in range(samples):
        if setup is not None:
            setup()
        started = time.perf_counter()
        operation()
        durations.append(time.perf_counter() - started)

    if setup is not None:
        setup()
    tracemalloc.start()
    try:
        operation()
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    return {
        "samples": samples,
        "wall_seconds_min": round(min(durations), 6),
        "wall_seconds_median": round(statistics.median(durations), 6),
        "wall_seconds_max": round(max(durations), 6),
        "peak_traced_bytes": int(peak),
        "peak_traced_measured_separately": True,
    }


def _bundle_cases(
    root: Path, repo_root: Path, samples: int
) -> tuple[dict[str, Any], Path | None, Path | None]:
    from merger.repoground.core.merge import ExtrasConfig, scan_repo, write_reports_v2

    generator_info = {
        "name": "repoground-core-path-benchmark",
        "platform": "benchmark",
        "version": "0",
    }
    summary = scan_repo(repo_root, calculate_md5=True)
    cases: dict[str, Any] = {}

    def _write(merges_dir: Path, output_mode: str, json_sidecar: bool) -> Any:
        return write_reports_v2(
            merges_dir=merges_dir,
            hub=root,
            repo_summaries=[summary],
            detail="max",
            mode="gesamt",
            max_bytes=0,
            plan_only=False,
            output_mode=output_mode,
            extras=ExtrasConfig(json_sidecar=json_sidecar),
            redact_secrets=False,
            generator_info=dict(generator_info),
            publish_generation=False,
        )

    archive_workspaces = _WorkspaceSequence(root, "merges_archive")
    cases["bundle_write_archive"] = _measure(
        lambda: _write(archive_workspaces.next(), "archive", False),
        samples=samples,
    )

    dual_workspaces = _WorkspaceSequence(root, "merges_dual")
    produced: dict[str, Any] = {}

    def _run_dual() -> None:
        produced["value"] = _write(dual_workspaces.next(), "dual", True)

    cases["bundle_write_dual"] = _measure(_run_dual, samples=samples)
    artifacts = produced["value"]
    return cases, artifacts.dump_index, artifacts.chunk_index


def _retrieval_cases(
    root: Path, dump_index: Path | None, chunk_index: Path | None, samples: int
) -> dict[str, Any]:
    if dump_index is None or chunk_index is None:
        return {
            "retrieval_index_build": {"skipped": "bundle produced no retrieval artifacts"},
            "retrieval_query": {"skipped": "bundle produced no retrieval artifacts"},
        }

    from merger.repoground.retrieval.index_db import build_index
    from merger.repoground.retrieval.query_core import execute_query

    db_path = root / "index" / "bench.sqlite"
    db_path.parent.mkdir(parents=True, exist_ok=True)

    def _drop_index() -> None:
        if db_path.exists():
            db_path.unlink()

    cases = {
        "retrieval_index_build": _measure(
            lambda: build_index(dump_index, chunk_index, db_path),
            samples=samples,
            setup=_drop_index,
        )
    }
    build_index(dump_index, chunk_index, db_path)
    cases["retrieval_query"] = _measure(
        lambda: execute_query(db_path, "deterministic transform value", k=10),
        samples=samples,
    )
    return cases


def _service_case(samples: int) -> dict[str, Any]:
    """Measure cold service-application import in a separate interpreter."""

    program = (
        "import time, tracemalloc, json, sys\n"
        "tracemalloc.start()\n"
        "started = time.perf_counter()\n"
        "import merger.repoground.service.app  # noqa: F401\n"
        "elapsed = time.perf_counter() - started\n"
        "peak = tracemalloc.get_traced_memory()[1]\n"
        "tracemalloc.stop()\n"
        "print(json.dumps({'wall_seconds': elapsed, 'peak_traced_bytes': peak}))\n"
    )
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(REPO_ROOT), environment.get("PYTHONPATH", "")]
    ).rstrip(os.pathsep)

    durations: list[float] = []
    peaks: list[int] = []
    for _ in range(samples):
        completed = subprocess.run(
            [sys.executable, "-c", program],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )
        if completed.returncode != 0:
            return {
                "skipped": "service application import failed",
                "detail": completed.stderr.strip()[-500:],
            }
        payload = json.loads(completed.stdout.strip().splitlines()[-1])
        durations.append(float(payload["wall_seconds"]))
        peaks.append(int(payload["peak_traced_bytes"]))

    return {
        "samples": samples,
        "wall_seconds_min": round(min(durations), 6),
        "wall_seconds_median": round(statistics.median(durations), 6),
        "wall_seconds_max": round(max(durations), 6),
        "peak_traced_bytes": min(peaks),
        "peak_traced_measured_separately": False,
        "isolation": "subprocess",
    }


def _atlas_case(root: Path, repo_root: Path, samples: int) -> dict[str, Any]:
    """Atlas is an optional observation subsystem; absence is recorded, not failed."""

    try:
        from merger.repoground.adapters.atlas import AtlasScanner
    except Exception as exc:  # pragma: no cover - optional subsystem
        return {"skipped": "atlas adapter unavailable", "detail": str(exc)[:200]}

    inventory = root / "atlas" / "inventory.jsonl"
    inventory.parent.mkdir(parents=True, exist_ok=True)

    def _scan() -> None:
        AtlasScanner(
            repo_root,
            max_depth=6,
            snapshot_id="benchmark-fixed-snapshot",
        ).scan(inventory_file=inventory)

    return _measure(_scan, samples=samples) | {"optional_subsystem": True}


def run(samples: int, include_atlas: bool) -> dict[str, Any]:
    cases: dict[str, Any] = {}
    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="repoground-corebench-") as raw_root:
        root = Path(raw_root)
        repo_root = build_fixture_repository(root)
        try:
            bundle_cases, dump_index, chunk_index = _bundle_cases(root, repo_root, samples)
            cases.update(bundle_cases)
            cases.update(_retrieval_cases(root, dump_index, chunk_index, samples))
        except Exception as exc:
            failures.append(f"bundle_or_retrieval: {type(exc).__name__}: {exc}")
        cases["service_app_import"] = _service_case(samples)
        if include_atlas:
            try:
                cases["atlas_scan"] = _atlas_case(root, repo_root, samples)
            except Exception as exc:
                failures.append(f"atlas: {type(exc).__name__}: {exc}")
        else:
            cases["atlas_scan"] = {"skipped": "not requested (optional subsystem)"}

    return {
        "kind": "repoground.core_path_benchmark",
        "version": "1.0",
        "status": "fail" if failures else "pass",
        "failures": failures,
        "binding": {
            "commit": _git_commit(),
            "worktree_dirty": _git_dirty(),
            "benchmark_script_sha256": _sha256(Path(__file__)),
        },
        "configuration": {
            "samples": samples,
            "fixture_python_files": FIXTURE_PYTHON_FILES,
            "fixture_markdown_files": FIXTURE_MARKDOWN_FILES,
            "fixture_functions_per_file": FIXTURE_FUNCTIONS_PER_FILE,
            "reported_statistic": "wall_seconds_min is the comparison figure",
            "timing_gate": "none",
        },
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "processor": platform.processor(),
        },
        "cases": cases,
        "does_not_establish": DOES_NOT_ESTABLISH,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=DEFAULT_SAMPLES)
    parser.add_argument("--include-atlas", action="store_true")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    if args.samples < 1:
        parser.error("--samples must be at least 1")
    report = run(args.samples, args.include_atlas)
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 1 if report["status"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
