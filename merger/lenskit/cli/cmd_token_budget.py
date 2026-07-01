import argparse
import json
import sys
from pathlib import Path


class TokenBudgetCliError(Exception):
    """User-facing CLI input/output error."""


def register_token_budget_commands(subparsers) -> None:
    parser = subparsers.add_parser("token-budget", help="Token budget diagnostics")
    sub = parser.add_subparsers(dest="token_budget_cmd", required=True)

    report = sub.add_parser("report", help="Estimate bundle artifact token budget from manifest bytes")
    report.add_argument("--bundle-manifest", required=True, help="Path to bundle-manifest.v1 JSON")
    report.add_argument("--context-budget", type=int, default=128000, help="Context budget in tokens used for share/overflow diagnostics")
    report.add_argument("--bytes-per-token", type=float, default=4.0, help="Byte divisor used for rough token estimate")
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
        raise TokenBudgetCliError(f"Could not write to {out}: {exc}") from exc


def _exit_for_status(status: str, *, strict: bool = False) -> int:
    if status == "pass":
        return 0
    if status == "warn":
        return 1 if strict else 0
    if status == "fail":
        return 1
    return 2


def run_token_budget_report(args: argparse.Namespace) -> int:
    from merger.lenskit.core.token_budget_report import (
        build_token_budget_report_from_bundle_manifest,
    )

    try:
        report = build_token_budget_report_from_bundle_manifest(
            Path(args.bundle_manifest),
            context_budget_tokens=args.context_budget,
            bytes_per_token=args.bytes_per_token,
        )
        _write_json_or_stdout(report, Path(args.out) if args.out else None)
        return _exit_for_status(str(report.get("status", "unknown")), strict=args.strict)
    except TokenBudgetCliError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Error: unexpected failure: {exc}", file=sys.stderr)
        return 2


def run_token_budget(args: argparse.Namespace) -> int:
    if args.token_budget_cmd == "report":
        return run_token_budget_report(args)
    return 2
