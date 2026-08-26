#!/usr/bin/env python3
"""Run the repository-only status-truth gate without pretending Bureau live access."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.docmeta.check_status_truth import DEFAULT_STATUS_PATH, scan

DEFERRED_CODE = "STATUS_TRUTH_BUREAU_UNAVAILABLE"


def defer_external_bureau_resolution(report: dict[str, Any]) -> dict[str, Any]:
    findings = report.get("findings")
    findings = findings if isinstance(findings, list) else []
    deferred = [
        item
        for item in findings
        if isinstance(item, dict) and item.get("code") == DEFERRED_CODE
    ]
    retained = [item for item in findings if item not in deferred]

    result = dict(report)
    result["findings"] = retained
    summary = dict(result.get("summary") or {})
    summary["finding_count"] = len(retained)
    summary["deferred_bureau_reference_count"] = len(deferred)
    result["summary"] = summary
    result["status"] = "pass" if not retained else "fail"

    resolution = dict(result.get("bureau_reference_resolution") or {})
    if deferred:
        resolution.update(
            {
                "status": "deferred_external",
                "reason": (
                    "GitHub-hosted repository CI has no authoritative Bureau StateStore; "
                    "strict live resolution belongs to the operator-side snapshot check"
                ),
            }
        )
    result["bureau_reference_resolution"] = resolution

    boundaries = list(result.get("does_not_establish") or [])
    boundary = (
        "live Bureau task/candidate state when repository CI has no StateStore snapshot"
    )
    if boundary not in boundaries:
        boundaries.append(boundary)
    result["does_not_establish"] = boundaries
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--status-path", type=Path, default=DEFAULT_STATUS_PATH)
    parser.add_argument("--format", choices=("human", "json"), default="human")
    args = parser.parse_args(argv)

    report = defer_external_bureau_resolution(scan(args.root, args.status_path))
    if args.format == "json":
        print(json.dumps(report, indent=2, sort_keys=True))
    elif report["findings"]:
        for finding in report["findings"]:
            print(f"{finding['path']}: {finding['code']}: {finding['detail']}")
    else:
        summary = report["summary"]
        print(
            "Status truth CI check: pass "
            f"({summary['task_count']} tasks, "
            f"{summary.get('deferred_bureau_reference_count', 0)} external Bureau refs deferred)"
        )
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
