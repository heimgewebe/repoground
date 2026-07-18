"""Explicit write-side CLI for incremental retrieval snapshots.

The status command only reads the committed pointer/status files.  It never
creates, refreshes, verifies, or otherwise builds a snapshot.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from typing import Any, Callable, Mapping

from merger.repoground.retrieval.incremental_snapshot import (
    IncrementalRetrievalSnapshot,
    SnapshotConfig,
    run_polling_watcher,
)


def register_incremental_snapshot_commands(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "retrieval-snapshot",
        help="Explicit write operations and read-only status for incremental retrieval snapshots",
    )
    commands = parser.add_subparsers(dest="retrieval_snapshot_cmd", required=True)
    for name, help_text in (("build", "Build or incrementally publish a retrieval snapshot"),
                            ("full-verify", "Build explicitly and compare with a full chunk build")):
        command = commands.add_parser(name, help=help_text)
        _add_snapshot_options(command, source_required=True)
    status = commands.add_parser("status", help="Read the committed snapshot and watcher status; never builds")
    status.add_argument("--storage", required=True, help="Snapshot storage root")
    watch = commands.add_parser("watch", help="Run an optional, foreground stdlib polling watcher")
    _add_snapshot_options(watch, source_required=True)
    watch.add_argument("--poll-seconds", type=float, default=1.0)
    watch.add_argument("--debounce-seconds", type=float, default=0.25)
    watch.add_argument("--queue-limit", type=int, default=128)
    watch.add_argument("--base-backoff-seconds", type=float, default=1.0)
    watch.add_argument("--max-backoff-seconds", type=float, default=60.0)
    watch.add_argument("--run-seconds", type=float, help="Optional bounded foreground run, mainly for automation")
    measure = commands.add_parser("measure", help="Measure full, incremental and no-op builds on a disposable copy")
    _add_snapshot_options(measure, source_required=True)
    measure.add_argument("--report", required=True, help="Destination JSON report")
    measure.add_argument("--change-file", help="Repository-relative UTF-8 file to change; auto-selects one if omitted")


def _add_snapshot_options(parser: argparse.ArgumentParser, *, source_required: bool) -> None:
    parser.add_argument("--source", required=source_required, help="Repository source root")
    parser.add_argument("--storage", required=True, help="Snapshot storage root")
    parser.add_argument("--repo-id", default="local")
    parser.add_argument("--max-size", type=int, default=8192)
    parser.add_argument("--max-lines", type=int, default=400)
    parser.add_argument("--min-size", type=int, default=2048)
    parser.add_argument("--min-lines", type=int, default=200)
    parser.add_argument("--include-extension", action="append", default=[], help="Restrict to extension, e.g. .py (repeatable)")


def _snapshot(args: argparse.Namespace) -> IncrementalRetrievalSnapshot:
    config = SnapshotConfig(
        repo_id=args.repo_id, max_size=args.max_size, max_lines=args.max_lines,
        min_size=args.min_size, min_lines=args.min_lines,
        include_extensions=tuple(args.include_extension),
    )
    return IncrementalRetrievalSnapshot(Path(args.source), Path(args.storage), config)


def _print(value: Mapping[str, Any]) -> None:
    print(json.dumps(value, sort_keys=True, indent=2))


def _read_json(path: Path) -> Mapping[str, Any] | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _io_bytes() -> Mapping[str, int] | None:
    path = Path("/proc/self/io")
    if not path.exists():
        return None
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, raw = line.split(":", 1)
        if key in {"read_bytes", "write_bytes"}:
            values[key] = int(raw.strip())
    return values


def _timed(operation: Callable[[], Any], storage: Path) -> tuple[Any, Mapping[str, Any]]:
    before_io = _io_bytes()
    before_output = _tree_bytes(storage)
    cpu_start, wall_start = time.process_time(), time.perf_counter()
    result = operation()
    timing: dict[str, Any] = {
        "wall_seconds": time.perf_counter() - wall_start,
        "cpu_seconds": time.process_time() - cpu_start,
        "output_tree_bytes_delta": _tree_bytes(storage) - before_output,
    }
    after_io = _io_bytes()
    if before_io is not None and after_io is not None:
        timing["io_bytes"] = {key: after_io[key] - before_io[key] for key in before_io}
        timing["io_method"] = "linux_proc_self_io"
    else:
        timing["io_method"] = "output_tree_bytes_delta_only"
    return result, timing


def _tree_bytes(root: Path) -> int:
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file()) if root.exists() else 0


def _hash_tree(root: Path, *, exclude: Path | None = None) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink() or ".git" in path.relative_to(root).parts:
            continue
        if exclude is not None and path.resolve() == exclude.resolve():
            continue
        digest.update(path.relative_to(root).as_posix().encode() + b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def _git_commit(source: Path) -> str | None:
    try:
        return subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def run_incremental_snapshot(args: argparse.Namespace) -> int:
    try:
        if args.retrieval_snapshot_cmd == "status":
            storage = Path(args.storage)
            pointer = _read_json(storage / "current.json")
            generation = None
            if pointer is not None:
                generation = _read_json(storage / "generations" / pointer["generation_id"] / "snapshot.json")
            _print({"pointer": pointer, "snapshot": generation, "watcher": _read_json(storage / "watcher-status.json")})
            return 0
        snapshot = _snapshot(args)
        if args.retrieval_snapshot_cmd == "build":
            _print(snapshot.build().receipt)
            return 0
        if args.retrieval_snapshot_cmd == "full-verify":
            _print(snapshot.full_verify())
            return 0
        if args.retrieval_snapshot_cmd == "watch":
            until = time.monotonic() + args.run_seconds if args.run_seconds is not None else None
            return run_polling_watcher(snapshot, poll_seconds=args.poll_seconds, debounce_seconds=args.debounce_seconds,
                                       queue_limit=args.queue_limit, base_backoff_seconds=args.base_backoff_seconds,
                                       max_backoff_seconds=args.max_backoff_seconds, stop_after=until)
        if args.retrieval_snapshot_cmd == "measure":
            _run_measurement(args, snapshot)
            return 0
    except Exception as exc:
        print(f"retrieval-snapshot {args.retrieval_snapshot_cmd}: {exc}", file=os.sys.stderr)
        return 1
    raise RuntimeError(f"unexpected retrieval snapshot command: {args.retrieval_snapshot_cmd}")


def _run_measurement(args: argparse.Namespace, configured: IncrementalRetrievalSnapshot) -> None:
    source = configured.source_root
    report_path = Path(args.report).resolve()
    try:
        report_relative = report_path.relative_to(source)
    except ValueError:
        report_relative = None
    with tempfile.TemporaryDirectory(prefix="repoground-incremental-measure-") as temporary:
        worktree = Path(temporary) / "source"
        ignored = shutil.ignore_patterns(".git", ".pytest_cache", "__pycache__", ".mypy_cache", ".ruff_cache")
        shutil.copytree(source, worktree, ignore=ignored)
        if report_relative is not None:
            (worktree / report_relative).unlink(missing_ok=True)
        storage = Path(temporary) / "storage"
        snapshot = IncrementalRetrievalSnapshot(worktree, storage, configured.config)
        first, full = _timed(snapshot.build, storage)
        change = Path(args.change_file) if args.change_file else next(
            path.relative_to(worktree) for path in sorted(worktree.rglob("*.py")) if path.is_file()
        )
        target = worktree / change
        target.write_text(target.read_text(encoding="utf-8") + "\n# repoground measurement mutation\n", encoding="utf-8")
        incremental, changed = _timed(snapshot.build, storage)
        noop, no_op = _timed(snapshot.build, storage)
        report = {
            "schema": "repoground.incremental-retrieval-measurement.v1",
            "repository": {
                "source": ".",
                "absolute_source_path_persisted": False,
                "commit": _git_commit(source),
                "input_tree_sha256": _hash_tree(source, exclude=report_path),
                "excluded_output": str(report_relative) if report_relative else None,
            },
            "configuration": {"sha256": configured.config.fingerprint(), "value": dict(configured.config.__dict__)},
            "input": {"measurement_copy_sha256_before_change": first.receipt["content_fingerprint"], "changed_path": change.as_posix(), "measurement_copy_sha256_after_change": incremental.receipt["content_fingerprint"]},
            "runs": {"full_build": full, "incremental_change": changed, "no_op": no_op},
            "results": {"full_generation": first.generation_id, "incremental_generation": incremental.generation_id, "no_op_generation": noop.generation_id, "no_op": noop.no_op,
                        "incremental_files": incremental.receipt["files"], "freshness_latency_seconds": changed["wall_seconds"]},
            "boundaries": "Runs use a disposable copy of this repository; /proc/self/io reports process IO when available and otherwise output-tree bytes are only an approximation.",
        }
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        _print(report)
