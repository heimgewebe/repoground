import argparse
import json
import sys


def register_citation_commands(subparsers) -> None:
    citation_parser = subparsers.add_parser("citation", help="Citation operations")
    citation_subparsers = citation_parser.add_subparsers(
        dest="citation_cmd", required=True, help="Citation commands"
    )

    validate_parser = citation_subparsers.add_parser(
        "validate", help="Validate citation readiness of a bundle manifest"
    )
    validate_parser.add_argument(
        "bundle_manifest", help="Path to bundle manifest JSON"
    )
    validate_parser.add_argument(
        "--json",
        action="store_true",
        dest="emit_json",
        help="Emit machine-readable JSON report to stdout",
    )


def run_citation_validate(args: argparse.Namespace) -> int:
    from merger.lenskit.core.citation_validate import validate_bundle

    manifest_path = args.bundle_manifest

    try:
        report = validate_bundle(manifest_path)
    except Exception as e:
        print(f"Error: unexpected failure during validation: {e}", file=sys.stderr)
        return 2

    if args.emit_json:
        print(json.dumps(report, indent=2))
    else:
        _print_human_report(report)

    if report["status"] == "ok":
        return 0
    if report.get("error_kind") == "path_read_error":
        return 2
    return 1


def _print_human_report(report: dict) -> None:
    status = report["status"].upper()
    print(f"Citation Readiness: {status}")
    print(f"  bundle_manifest_path:    {report['bundle_manifest_path']}")
    print(f"  bundle_run_id:           {report['bundle_run_id']}")
    print(f"  validation_run_id:       {report['validation_run_id']}")
    print(f"  canonical_md_sha256:     {report['canonical_md_sha256']}")
    print(f"  chunk_index_sha256:      {report['chunk_index_sha256']}")
    print(f"  canonical_md_actual_sha256: {report['canonical_md_actual_sha256']}")
    print(f"  chunk_index_actual_sha256:  {report['chunk_index_actual_sha256']}")
    print(f"  chunks:                  {report['chunk_count']}")
    print(f"  canonical_range_count:   {report['canonical_range_count']}")
    print(f"  source_range_count:      {report['source_range_count']}")
    print(f"  content_range_ref_count: {report['content_range_ref_count']}")
    print(f"  citation_id_count:       {report['citation_id_count']}")
    print(f"  duplicates:              {report['citation_id_duplicate_count']}")
    print(f"  hash_ok_count:           {report['canonical_range_hash_ok_count']}")

    if report["sample_citation_ids"]:
        print("  sample_citation_ids:")
        for cid in report["sample_citation_ids"]:
            print(f"    {cid}")

    if report["warnings"]:
        print(f"\nWarnings ({len(report['warnings'])}):")
        for w in report["warnings"]:
            print(f"  [warn] {w}")

    if report["errors"]:
        print(f"\nErrors ({len(report['errors'])}):")
        for e in report["errors"]:
            print(f"  [error] {e}")
