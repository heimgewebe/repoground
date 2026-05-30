import argparse
import json
import sys


def register_governance_commands(subparsers) -> None:
    gov_parser = subparsers.add_parser(
        "governance",
        help="Governance Track C tooling (authority / inference-boundary contract lint)",
    )
    gov_subparsers = gov_parser.add_subparsers(
        dest="governance_cmd", required=True, help="Governance commands"
    )

    lint_parser = gov_subparsers.add_parser(
        "lint",
        help="Anti-hallucination contract lint (C2.4): L3 boundary + L5 truth-language",
    )
    lint_parser.add_argument(
        "--contracts-dir",
        dest="contracts_dir",
        default=None,
        help="Directory of *.schema.json contracts (defaults to the packaged contracts dir)",
    )
    lint_parser.add_argument(
        "--json",
        action="store_true",
        dest="emit_json",
        help="Emit the machine-readable JSON lint report to stdout",
    )

    ast_lint_parser = gov_subparsers.add_parser(
        "ast-lint",
        help=(
            "EXPERIMENTAL marker-gated AST lint (C2.7): L1/L2/L4 authority-flow. "
            "Non-blocking; not wired into CI."
        ),
    )
    ast_lint_parser.add_argument(
        "--path",
        dest="scan_path",
        default=None,
        help=(
            "Root directory or .py file to scan (defaults to the packaged lenskit "
            "package, minus tests/fixtures/contracts)"
        ),
    )
    ast_lint_parser.add_argument(
        "--json",
        action="store_true",
        dest="emit_json",
        help="Emit the machine-readable JSON lint report to stdout",
    )


def run_governance_lint(args: argparse.Namespace) -> int:
    from pathlib import Path

    from merger.lenskit.core.anti_hallucination_lint import lint_contracts_dir

    contracts_dir = getattr(args, "contracts_dir", None)
    contracts_dir = Path(contracts_dir) if contracts_dir else None

    try:
        report = lint_contracts_dir(contracts_dir)
    except (ValueError, OSError) as exc:
        print(f"Error: unable to run contract lint: {exc}", file=sys.stderr)
        return 2

    if getattr(args, "emit_json", False):
        print(json.dumps(report.to_dict(), indent=2))
    else:
        _print_human_report(report)

    return 0 if report.status == "pass" else 1


def run_governance_ast_lint(args: argparse.Namespace) -> int:
    from pathlib import Path

    from merger.lenskit.core.anti_hallucination_ast_lint import (
        AstLintReport,
        lint_default_tree,
        lint_file,
        lint_tree,
    )

    scan_path = getattr(args, "scan_path", None)
    try:
        if scan_path is None:
            report = lint_default_tree()
        else:
            path = Path(scan_path)
            if not path.exists():
                print(f"Error: AST lint path does not exist: {path}", file=sys.stderr)
                return 2
            if path.is_file():
                report = AstLintReport(files_scanned=1)
                report.findings.extend(lint_file(path))
            elif path.is_dir():
                report = lint_tree(path)
            else:
                print(
                    f"Error: AST lint path is neither file nor directory: {path}",
                    file=sys.stderr,
                )
                return 2
    except (ValueError, OSError) as exc:
        print(f"Error: unable to run AST lint: {exc}", file=sys.stderr)
        return 2

    if getattr(args, "emit_json", False):
        print(json.dumps(report.to_dict(), indent=2))
    else:
        _print_ast_human_report(report)

    # Experimental, non-blocking by intent: today's un-annotated tree is clean
    # (status == "pass" → exit 0). Findings only appear once the opt-in markers
    # are adopted, and are surfaced as a "warn" status (exit 1) for local use.
    return 0 if report.status == "pass" else 1


def _print_ast_human_report(report) -> None:
    print(
        "Anti-Hallucination AST Lint (C2.7, EXPERIMENTAL / non-blocking): "
        f"{report.status.upper()}"
    )
    print(f"  files_scanned: {report.files_scanned}")
    print(f"  files_skipped: {report.files_skipped}")
    print(f"  rules_covered: {', '.join(report.to_dict()['rules_covered'])}")
    print(f"  findings:      {report.finding_count}")

    if report.findings:
        print(f"\nFindings ({report.finding_count}):")
        for f in report.findings:
            print(f"  [{f.rule}] {f.file}:{f.line} ({f.symbol})")
            print(f"        {f.message}")

    print(
        "\n  NOTE: marker-gated, opt-in AST lint — a clean run does NOT prove the code "
        "is authority-safe (it only checks *declared* low-authority flows). Experimental "
        "and NOT wired into CI. L3/L5 are contract-static (C2.4); L6 is the export gate "
        "(C5); C4 runtime annotation remains open."
    )


def _print_human_report(report) -> None:
    print(f"Anti-Hallucination Contract Lint (C2.4): {report.status.upper()}")
    print(f"  contracts_scanned: {report.contracts_scanned}")
    print(f"  rules_enforced:    {', '.join(report.to_dict()['rules_enforced'])}")
    print(f"  errors:            {report.error_count}")
    print(f"  deferred:          {report.deferred_count}")

    if report.findings:
        print(f"\nErrors ({report.error_count}):")
        for f in report.findings:
            print(f"  [{f.rule}] {f.contract} @ {f.location}")
            print(f"        {f.message}")

    if report.deferred:
        print(f"\nDeferred (tracked, non-blocking) ({report.deferred_count}):")
        for f in report.deferred:
            print(f"  [{f.rule}] {f.contract} @ {f.location}")
            print(f"        {f.message}")

    print(
        "\n  NOTE: contract-static lint only — a pass does NOT prove contracts are "
        "truthful, complete, or runtime-safe. L1/L2/L4 (AST) and L6 (export gate) "
        "are out of scope for C2.4."
    )
