import argparse
import json
import sys


def register_context_quality_commands(subparsers) -> None:
    cq_parser = subparsers.add_parser(
        "context-quality",
        help="Context quality diagnostic projection (not understanding, not answer safety)",
    )
    cq_subparsers = cq_parser.add_subparsers(
        dest="context_quality_cmd", required=True, help="Context quality commands"
    )

    inspect_parser = cq_subparsers.add_parser(
        "inspect",
        help="Project existing context-quality signals for a bundle (diagnostic only)",
    )
    inspect_parser.add_argument(
        "manifest", help="Path to the bundle manifest JSON"
    )
    inspect_parser.add_argument(
        "--json",
        action="store_true",
        dest="emit_json",
        help="Emit the machine-readable JSON report to stdout",
    )
    inspect_parser.add_argument(
        "--emit-artifact",
        action="store_true",
        dest="emit_artifact",
        help="Persist the report as <stem>.context_quality.json (unregistered; manifest is never mutated)",
    )
    inspect_parser.add_argument(
        "--output",
        dest="output_path",
        default=None,
        help="Explicit output path for the persisted artifact (implies --emit-artifact)",
    )


# degraded is a usable/expected state for minimal bundles, so it is not an error
# exit. Only blocked (cannot project at all) returns a non-zero code.
_EXIT_CODES = {"complete": 0, "degraded": 0, "blocked": 2}


def run_context_quality_inspect(args: argparse.Namespace) -> int:
    from merger.lenskit.core.context_quality import (
        compute_context_quality,
        write_context_quality,
    )

    manifest_path = args.manifest
    output_path = getattr(args, "output_path", None)
    emit_artifact = getattr(args, "emit_artifact", False) or output_path is not None

    written_path = None
    try:
        if emit_artifact:
            written_path, report = write_context_quality(manifest_path, output_path)
        else:
            report = compute_context_quality(manifest_path)
    except Exception as e:  # noqa: BLE001 - surface unexpected failures cleanly
        print(f"Error: unexpected failure during context-quality projection: {e}", file=sys.stderr)
        return 2

    if args.emit_json:
        print(json.dumps(report, indent=2))
    else:
        _print_human_report(report, written_path)

    return _EXIT_CODES.get(report["projection_status"], 1)


def _print_human_report(report: dict, written_path=None) -> None:
    print(f"Context Quality (diagnostic projection): {report['projection_status'].upper()}")
    print(f"  bundle_manifest_path:    {report['bundle_manifest_path']}")
    print(f"  bundle_run_id:           {report.get('bundle_run_id')}")
    print(f"  run_id:                  {report['run_id']}")
    print(f"  authority:               {report['authority']}")
    print(f"  risk_class:              {report['risk_class']}")

    signals = report.get("signals") or {}

    manifest_sig = signals.get("manifest") or {}
    key_roles = manifest_sig.get("key_roles") or {}
    present = [role for role, ok in key_roles.items() if ok]
    print(f"  manifest.key_roles:      {', '.join(present) or '—'}")

    for name in ("output_health", "post_emit_health", "retrieval_eval", "agent_export_gate", "evidence"):
        sig = signals.get(name) or {}
        avail = sig.get("available")
        extra = ""
        if name == "output_health" and avail:
            extra = f" verdict_observed={sig.get('verdict_observed')} (observation only)"
        elif name == "post_emit_health" and avail:
            extra = f" status_observed={sig.get('status_observed')} evidence_level={sig.get('evidence_level')}"
        elif name == "agent_export_gate" and avail:
            extra = f" status_observed={sig.get('status_observed')} (observation only)"
        elif name == "evidence" and avail:
            extra = f" evidence_level={sig.get('evidence_level')}"
        print(f"  signal.{name}: available={avail}{extra}")

    print(
        "  NOTE: diagnostic projection only — NOT repository understanding, "
        "NOT answer safety, NOT retrieval completeness, NOT claim truth."
    )
    print(f"  agent_use_constraints:   {', '.join(report.get('agent_use_constraints') or [])}")
    print(f"  does_not_mean:           {', '.join(report.get('does_not_mean') or [])}")

    if written_path is not None:
        print(f"  written_artifact:        {written_path}")
        print("  NOTE: written artifact is unregistered; manifest not mutated.")

    if report.get("warnings"):
        print(f"\nWarnings ({len(report['warnings'])}):")
        for w in report["warnings"]:
            print(f"  [warn] {w}")

    if report.get("errors"):
        print(f"\nErrors ({len(report['errors'])}):")
        for e in report["errors"]:
            print(f"  [error] {e}")
