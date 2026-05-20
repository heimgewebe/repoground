import argparse
import json


def register_agent_pack_commands(subparsers) -> None:
    pack_parser = subparsers.add_parser(
        "agent-pack", help="Agent reading pack operations"
    )
    pack_subparsers = pack_parser.add_subparsers(
        dest="agent_pack_cmd", required=True, help="Agent reading pack commands"
    )

    produce_parser = pack_subparsers.add_parser(
        "produce", help="Produce <stem>.agent_reading_pack.md from a bundle manifest"
    )
    produce_parser.add_argument("bundle_manifest", help="Path to bundle manifest JSON")
    produce_parser.add_argument(
        "--output",
        dest="output_path",
        default=None,
        help="Output path for agent_reading_pack.md (default: adjacent to manifest)",
    )
    produce_parser.add_argument(
        "--json",
        action="store_true",
        dest="emit_json",
        help="Emit machine-readable JSON report to stdout",
    )


def run_agent_pack_produce(args: argparse.Namespace) -> int:
    from merger.lenskit.core.agent_reading_pack import produce_agent_reading_pack

    report = produce_agent_reading_pack(args.bundle_manifest, getattr(args, "output_path", None))

    if args.emit_json:
        print(json.dumps(report, indent=2))
    else:
        _print_produce_report(report)

    if report["status"] == "ok":
        return 0
    if report.get("error_kind") == "path_read_error":
        return 2
    return 1


def _print_produce_report(report: dict) -> None:
    print(f"Agent Reading Pack: {report['status'].upper()}")
    print(f"  bundle_manifest_path:  {report['bundle_manifest_path']}")
    print(f"  bundle_run_id:         {report['bundle_run_id']}")
    print(f"  production_run_id:      {report['production_run_id']}")
    print(f"  output_path:           {report['output_path']}")
    print(f"  output_sha256:         {report['output_sha256']}")
    print(f"  output_bytes:          {report['output_bytes']}")
    print(f"  artifact_role_count:   {report['artifact_role_count']}")
    print(f"  top_file_count:        {report['top_file_count']}")
    print(f"  indexed_chunk_count:   {report['indexed_chunk_count']}")
    print(f"  health_verdict:        {report['health_verdict']}")

    if report.get("warnings"):
        print(f"\nWarnings ({len(report['warnings'])}):")
        for w in report["warnings"]:
            print(f"  [warn] {w}")

    if report.get("errors"):
        print(f"\nErrors ({len(report['errors'])}):")
        for e in report["errors"]:
            print(f"  [error] {e}")
