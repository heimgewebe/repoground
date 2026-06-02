"""CLI for the real-dump bundle surface self-check.

    lenskit bundle-surface validate --manifest <bundle.manifest.json> \
        [--require claim-evidence-map] [--json] [--emit-artifact] [--output P]

Exit codes (consistent with ``lenskit bundle-health``):
    0 = pass / warn
    1 = fail
    2 = blocked
"""

import argparse
import json
import sys


def register_bundle_surface_commands(subparsers) -> None:
    bs_parser = subparsers.add_parser(
        "bundle-surface", help="Bundle surface self-check (claim-map / provenance coherence)"
    )
    bs_subparsers = bs_parser.add_subparsers(
        dest="bundle_surface_cmd", required=True, help="Bundle surface commands"
    )

    validate_parser = bs_subparsers.add_parser(
        "validate",
        help="Validate the coherence of a final emitted bundle surface",
    )
    validate_parser.add_argument(
        "--manifest", required=True, help="Path to the bundle manifest JSON"
    )
    validate_parser.add_argument(
        "--require",
        choices=["claim-evidence-map"],
        default=None,
        help="Require a coherent claim_evidence_map surface (present, or absent "
        "with a machine-readable reason)",
    )
    validate_parser.add_argument(
        "--json",
        action="store_true",
        dest="emit_json",
        help="Emit the machine-readable JSON report to stdout",
    )
    validate_parser.add_argument(
        "--emit-artifact",
        action="store_true",
        dest="emit_artifact",
        help="Persist the report as <stem>.bundle_surface_validation.json (unregistered)",
    )
    validate_parser.add_argument(
        "--output",
        dest="output_path",
        default=None,
        help="Explicit output path for the persisted artifact (implies --emit-artifact)",
    )


_EXIT_CODES = {"pass": 0, "warn": 0, "fail": 1, "blocked": 2}


def run_bundle_surface_validate(args: argparse.Namespace) -> int:
    from merger.lenskit.core.bundle_surface_validate import (
        validate_bundle_surface,
        write_bundle_surface_validation,
    )

    require_claim = getattr(args, "require", None) == "claim-evidence-map"
    output_path = getattr(args, "output_path", None)
    emit_artifact = getattr(args, "emit_artifact", False) or output_path is not None

    written_path = None
    try:
        if emit_artifact:
            written_path, report = write_bundle_surface_validation(
                args.manifest,
                output_path,
                require_claim_evidence_map=require_claim,
            )
        else:
            report = validate_bundle_surface(
                args.manifest, require_claim_evidence_map=require_claim
            )
    except Exception as e:  # noqa: BLE001 - surface unexpected failures cleanly
        print(f"Error: unexpected failure during bundle surface validation: {e}", file=sys.stderr)
        return 2

    if args.emit_json:
        print(json.dumps(report, indent=2))
    else:
        _print_human_report(report, written_path)

    return _EXIT_CODES.get(report["status"], 1)


def _print_human_report(report: dict, written_path=None) -> None:
    print(f"Bundle Surface Validation: {report['status'].upper()}")
    print(f"  bundle_manifest_path:        {report['bundle_manifest_path']}")
    print(f"  bundle_run_id:               {report.get('bundle_run_id')}")
    print(f"  require_claim_evidence_map:  {report.get('require_claim_evidence_map')}")
    print("  checks:")
    for c in report.get("checks", []):
        print(f"    [{c['status']}] {c['name']}: {c.get('detail', '')}")
    print(f"  does_not_mean:               {', '.join(report.get('does_not_mean') or [])}")
    if written_path is not None:
        print(f"  written_artifact:            {written_path}")
        print("  NOTE: written artifact is unregistered; manifest not mutated.")
