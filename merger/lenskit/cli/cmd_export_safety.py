import argparse
import json
import sys
from pathlib import Path


class ExportSafetyCliError(Exception):
    """User-facing CLI input/output error."""


def register_export_safety_commands(subparsers) -> None:
    parser = subparsers.add_parser("export-safety", help="Export safety report operations")
    sub = parser.add_subparsers(dest="export_safety_cmd", required=True)

    report = sub.add_parser("report", help="Build an export_safety_report from a bundle manifest")
    report.add_argument("--bundle-manifest", required=True, help="Path to bundle-manifest.v1 JSON")
    report.add_argument("--profile", required=True, help="Export profile, e.g. local-private or agent-portable")
    report.add_argument("--agent-facing", action="store_true", help="Force agent-facing policy semantics")
    report.add_argument("--public-facing", action="store_true", help="Force public-facing policy semantics")
    report.add_argument("--strict", action="store_true", help="Treat warn status as exit code 1")
    report.add_argument("--out", "--output", dest="out", help="Output path; stdout when omitted")


def _write_json_or_stdout(payload: dict, out: Path | None) -> None:
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if out is None:
        sys.stdout.write(text)
        return
    try:
        out.write_text(text, encoding="utf-8")
    except OSError as exc:
        raise ExportSafetyCliError(f"Could not write to {out}: {exc}") from exc


def _exit_for_status(status: str, *, strict: bool = False) -> int:
    if status == "pass":
        return 0
    if status == "warn":
        return 1 if strict else 0
    if status == "fail":
        return 1
    return 2


def run_export_safety_report(args: argparse.Namespace) -> int:
    from merger.lenskit.core.export_safety_report import (
        build_export_safety_report_from_bundle_manifest,
    )

    try:
        report = build_export_safety_report_from_bundle_manifest(
            Path(args.bundle_manifest),
            profile=args.profile,
            agent_facing=True if args.agent_facing else None,
            public_facing=True if args.public_facing else None,
        )
        _write_json_or_stdout(report, Path(args.out) if args.out else None)
        return _exit_for_status(str(report.get("status", "unknown")), strict=args.strict)
    except ExportSafetyCliError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Error: unexpected failure: {exc}", file=sys.stderr)
        return 2


def run_export_safety(args: argparse.Namespace) -> int:
    if args.export_safety_cmd == "report":
        return run_export_safety_report(args)
    return 2
