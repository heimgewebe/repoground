"""CLI surface for the read-only RepoGround doctor."""
from __future__ import annotations

import argparse
import json
from typing import Any

from merger.repoground.core.doctor import build_doctor_report


def register_doctor_command(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "doctor",
        help="Inspect local RepoGround readiness without repair or refresh",
    )
    parser.add_argument(
        "--repo-root",
        default=".",
        help="Explicit local repository checkout used for provenance/freshness checks",
    )
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument(
        "--bundle-root",
        help="Existing RepoGround publication catalog root",
    )
    selection.add_argument(
        "--manifest",
        help="Exact existing RepoGround bundle manifest",
    )
    parser.add_argument(
        "--mcp-config",
        help="MCP client configuration to validate (default: <repo-root>/.mcp.json)",
    )
    parser.add_argument(
        "--mcp-starter",
        help="Project MCP starter to validate (default: <repo-root>/scripts/repoground-mcp-project.py)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="emit_json",
        help="Emit the complete machine-readable doctor report",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Return exit 1 for degraded required readiness (blocked is always exit 2)",
    )


def _human_report(report: dict[str, Any]) -> str:
    lines = [f"RepoGround doctor: {report['status']}"]
    for check in report.get("checks", []):
        optional = " [optional]" if check.get("optional") else ""
        lines.append(
            f"- {check.get('id')}: {check.get('status')}{optional} — {check.get('cause')}"
        )
        impact = check.get("impact")
        if impact:
            lines.append(f"  impact: {impact}")
        next_action = check.get("next_action")
        if next_action and next_action != "No action required.":
            lines.append(f"  next: {next_action}")
    lines.append(
        "Read-only: no install, refresh, Git mutation, service mutation, secret read or network sync."
    )
    return "\n".join(lines)


def run_doctor(args: argparse.Namespace) -> int:
    report = build_doctor_report(
        repo_root=args.repo_root,
        bundle_root=args.bundle_root,
        manifest=args.manifest,
        mcp_config=args.mcp_config,
        mcp_starter=args.mcp_starter,
    )
    if args.emit_json:
        print(
            json.dumps(
                report,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            )
        )
    else:
        print(_human_report(report))

    if report["status"] == "blocked":
        return 2
    if report["status"] == "degraded" and args.strict:
        return 1
    return 0
