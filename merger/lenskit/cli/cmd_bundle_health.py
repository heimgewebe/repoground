import argparse
import json
import sys


def register_bundle_health_commands(subparsers) -> None:
    bh_parser = subparsers.add_parser(
        "bundle-health", help="Bundle health validation (post-emit)"
    )
    bh_subparsers = bh_parser.add_subparsers(
        dest="bundle_health_cmd", required=True, help="Bundle health commands"
    )

    post_parser = bh_subparsers.add_parser(
        "post",
        help="Validate the final emitted bundle surface (post-emit health)",
    )
    post_parser.add_argument(
        "manifest", help="Path to the bundle manifest JSON"
    )
    post_parser.add_argument(
        "--json",
        action="store_true",
        dest="emit_json",
        help="Emit the machine-readable JSON report to stdout",
    )
    post_parser.add_argument(
        "--emit-artifact",
        action="store_true",
        dest="emit_artifact",
        help="Persist the report as <stem>.bundle_health.post.json (unregistered; manifest is never mutated)",
    )
    post_parser.add_argument(
        "--output",
        dest="output_path",
        default=None,
        help="Explicit output path for the persisted artifact (implies --emit-artifact)",
    )
    post_parser.add_argument(
        "--no-require-agent-pack",
        action="store_false",
        dest="agent_pack_required",
        help="Do not treat a missing agent_reading_pack as a blocking absence",
    )

    export_gate_parser = bh_subparsers.add_parser(
        "export-gate",
        help="Evaluate export gate for a requested profile",
    )
    export_gate_parser.add_argument(
        "manifest", help="Path to the bundle manifest JSON"
    )
    export_gate_parser.add_argument(
        "--profile",
        required=False,
        default=None,
        help="Requested export profile (agent-facing profiles enforce hard gating)",
    )
    export_gate_parser.add_argument(
        "--post-health",
        dest="post_health_path",
        default=None,
        help="Optional explicit path to post_emit_health JSON report",
    )
    export_gate_parser.add_argument(
        "--json",
        action="store_true",
        dest="emit_json",
        help="Emit the machine-readable JSON report to stdout",
    )


_EXIT_CODES = {"pass": 0, "warn": 0, "fail": 1, "blocked": 2}


def run_bundle_health_post(args: argparse.Namespace) -> int:
    from merger.lenskit.core.post_emit_health import (
        compute_post_emit_health,
        write_post_emit_health,
    )

    manifest_path = args.manifest
    agent_pack_required = getattr(args, "agent_pack_required", True)
    output_path = getattr(args, "output_path", None)
    emit_artifact = getattr(args, "emit_artifact", False) or output_path is not None

    written_path = None
    try:
        if emit_artifact:
            written_path, report = write_post_emit_health(
                manifest_path,
                output_path,
                agent_pack_required=agent_pack_required,
            )
        else:
            report = compute_post_emit_health(
                manifest_path, agent_pack_required=agent_pack_required
            )
    except Exception as e:  # noqa: BLE001 - surface unexpected failures cleanly
        print(f"Error: unexpected failure during post-emit validation: {e}", file=sys.stderr)
        return 2

    if args.emit_json:
        print(json.dumps(report, indent=2))
    else:
        _print_human_report(report, written_path)

    return _EXIT_CODES.get(report["status"], 1)


def _print_human_report(report: dict, written_path=None) -> None:
    print(f"Post-emit Bundle Health: {report['status'].upper()}")
    print(f"  bundle_manifest_path:    {report['bundle_manifest_path']}")
    print(f"  bundle_run_id:           {report.get('bundle_run_id')}")
    print(f"  run_id:                  {report['run_id']}")
    print(f"  evidence_level:          {report.get('evidence_level')}")
    print(f"  evidence_levels_reached: {', '.join(report.get('evidence_levels_reached') or []) or '—'}")
    print(f"  output_health_verdict:   {report.get('output_health_verdict')} (observation only)")
    print(f"  artifact_count_checked:  {report['artifact_count_checked']}")
    print(f"  missing_artifact_count:  {report['missing_artifact_count']}")
    print(f"  hash_mismatch_count:     {report['hash_mismatch_count']}")
    print(f"  range_ref_resolution:    {report.get('range_ref_resolution_status')}")

    agent_pack = report.get("agent_pack") or {}
    print(f"  agent_pack.present:      {agent_pack.get('present')}")
    print(f"  agent_pack.self_role_ok: {agent_pack.get('self_role_ok')}")
    print(f"  agent_pack.required:     {agent_pack.get('required')}")
    if agent_pack.get("required") is False:
        print("  NOTE: agent_reading_pack not required for this run; this is not an agent-surface certification.")

    redaction = report.get("redaction_status") or {}
    print(f"  redaction (reported):    {redaction.get('redact_secrets_enabled')} (enforced={redaction.get('enforced')})")

    print(f"  {report['independence_note']}")
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


def run_bundle_health_export_gate(args: argparse.Namespace) -> int:
    from merger.lenskit.core.agent_export_gate import evaluate_agent_export_gate

    try:
        report = evaluate_agent_export_gate(
            manifest_path=args.manifest,
            post_health_path=getattr(args, "post_health_path", None),
            profile=getattr(args, "profile", None),
            require_redaction=True,
        )
    except Exception as e:  # noqa: BLE001 - surface unexpected failures cleanly
        print(f"Error: unexpected failure during export gate evaluation: {e}", file=sys.stderr)
        return 2

    if args.emit_json:
        print(json.dumps(report, indent=2))
    else:
        _print_export_gate_human(report)

    return _EXIT_CODES.get(report["status"], 1)


def _print_export_gate_human(report: dict) -> None:
    print(f"Agent Export Gate: {report['status'].upper()}")
    print(f"  profile:                     {report.get('profile')}")
    print(f"  agent_facing:                {report.get('agent_facing')}")
    print(f"  bundle_manifest_path:        {report.get('bundle_manifest_path')}")
    print(f"  post_emit_health_status:     {report.get('post_emit_health_status')}")
    print(f"  redaction_required:          {report.get('redaction_required')}")
    print(f"  redaction_enabled:           {report.get('redaction_enabled')}")
    print(
        "  output_health_verdict:        "
        f"{report.get('output_health_verdict_observed')} (observation only)"
    )
    print(f"  does_not_mean:               {', '.join(report.get('does_not_mean') or [])}")

    if report.get("warnings"):
        print(f"\nWarnings ({len(report['warnings'])}):")
        for w in report["warnings"]:
            print(f"  [warn] {w}")

    if report.get("errors"):
        print(f"\nErrors ({len(report['errors'])}):")
        for e in report["errors"]:
            print(f"  [error] {e}")
