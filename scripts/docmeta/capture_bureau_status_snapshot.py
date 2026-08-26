#!/usr/bin/env python3
"""Capture a fresh read-only Bureau snapshot for RepoGround status-truth checks."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.docmeta.status_truth_followups import (
    BUREAU_CANDIDATE_PROJECTION_SOURCE,
    BUREAU_SNAPSHOT_KIND,
    BUREAU_SNAPSHOT_SCHEMA_VERSION,
)


def _unwrap(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("Bureau command did not return a JSON object")
    result = value.get("result")
    if isinstance(result, dict):
        return result
    return value


def _run_json(command: list[str]) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return _unwrap(json.loads(completed.stdout))


def _candidate_projection_metadata(
    candidates: dict[str, Any],
    summary: dict[str, Any],
) -> tuple[bool, str, int]:
    coverage_complete = candidates.get("coverage_complete") is True
    projection_source = candidates.get("projection_source")
    projection_records = summary.get("projection_records")
    if not coverage_complete:
        raise ValueError("Bureau candidate projection coverage is incomplete")
    if projection_source != BUREAU_CANDIDATE_PROJECTION_SOURCE:
        raise ValueError("Bureau candidate projection is not the authoritative complete event scan")
    if (
        isinstance(projection_records, bool)
        or not isinstance(projection_records, int)
        or projection_records < 0
    ):
        raise ValueError("Bureau candidate projection lacks an event-count revision")
    return coverage_complete, projection_source, projection_records


def build_snapshot(
    projection: dict[str, Any],
    candidates: dict[str, Any],
    *,
    observed_at: str | None = None,
) -> dict[str, Any]:
    state_store = projection.get("state_store")
    state_store = state_store if isinstance(state_store, dict) else {}
    authority = projection.get("task_authority")
    authority = authority if isinstance(authority, dict) else {}
    if state_store.get("available") is not True or authority.get("status") != "state-store":
        raise ValueError("Bureau StateStore task authority is unavailable")
    task_root = authority.get("task_spec_root_sha256")
    if not isinstance(task_root, str) or len(task_root) != 64:
        raise ValueError("Bureau task authority lacks task_spec_root_sha256")

    task_records: dict[str, dict[str, Any]] = {}
    for item in projection.get("tasks", []):
        if not isinstance(item, dict) or not isinstance(item.get("task_id"), str):
            continue
        task_id = item["task_id"]
        task_records[task_id] = {
            "canonical_id": task_id,
            "state": item.get("effective_state"),
        }

    summary = candidates.get("summary")
    summary = summary if isinstance(summary, dict) else {}
    (
        coverage_complete,
        projection_source,
        projection_records,
    ) = _candidate_projection_metadata(candidates, summary)
    candidate_records: dict[str, dict[str, Any]] = {}
    for item in summary.get("latest_candidates", []):
        if not isinstance(item, dict):
            continue
        record = item.get("record")
        record = record if isinstance(record, dict) else {}
        candidate_id = record.get("candidate_id")
        if not isinstance(candidate_id, str) or not candidate_id.startswith("candidate-"):
            continue
        candidate_records[candidate_id] = {
            "canonical_id": candidate_id,
            "status": record.get("status"),
        }

    timestamp = observed_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "kind": BUREAU_SNAPSHOT_KIND,
        "schema_version": BUREAU_SNAPSHOT_SCHEMA_VERSION,
        "available": True,
        "observed_at": timestamp,
        "source": {
            "authority": "bureau-state-store",
            "task_authority": "state-store",
            "task_spec_root_sha256": task_root,
            "candidate_coverage_complete": coverage_complete,
            "candidate_projection_source": projection_source,
            "candidate_projection_records": projection_records,
        },
        "tasks": task_records,
        "candidates": candidate_records,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bureau-root", type=Path, required=True)
    parser.add_argument("--bureau-command", default="bureau")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--candidate-limit", type=int, default=500)
    args = parser.parse_args(argv)

    base = [args.bureau_command, "--root", str(args.bureau_root), "--json"]
    projection = _run_json([*base, "status-projection", "--skip-github"])
    candidates = _run_json(
        [
            *base,
            "live-list",
            "--kind",
            "candidate_task",
            "--limit",
            str(args.candidate_limit),
        ]
    )
    snapshot = build_snapshot(projection, candidates)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(snapshot, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
