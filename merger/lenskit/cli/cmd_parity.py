import argparse
import json
import sys


def register_parity_commands(subparsers) -> None:
    parity_parser = subparsers.add_parser("parity", help="Parity operations")
    parity_subparsers = parity_parser.add_subparsers(
        dest="parity_cmd", required=True, help="Parity commands"
    )

    compare_parser = parity_subparsers.add_parser(
        "compare", help="Compare two real bundle manifests via parity gates"
    )
    compare_parser.add_argument("left_manifest", help="Left bundle manifest path")
    compare_parser.add_argument("right_manifest", help="Right bundle manifest path")
    compare_parser.add_argument(
        "--json",
        action="store_true",
        dest="emit_json",
        help="Emit machine-readable JSON report",
    )
    compare_parser.add_argument(
        "--include-state",
        action="store_true",
        dest="include_state",
        help="Include internal parity state mapping in JSON output",
    )


def run_parity_compare(args: argparse.Namespace) -> int:
    from merger.lenskit.core.parity_gates import evaluate_parity_gates
    from merger.lenskit.core.parity_state import ParityInputError, build_parity_state

    try:
        built = build_parity_state(args.left_manifest, args.right_manifest)
    except ParityInputError as e:
        payload = {
            "status": "fail",
            "error_kind": getattr(e, "error_kind", "validation_error"),
            "message": str(e),
        }
        if args.emit_json:
            print(json.dumps(payload, indent=2))
        else:
            print(f"Parity compare failed: {e}", file=sys.stderr)
        return 2

    gates = evaluate_parity_gates(built.state)

    payload = {
        "content_parity_pass": gates.content_parity_pass,
        "diagnostic_parity_pass": gates.diagnostic_parity_pass,
        "content_reasons": gates.content_reasons,
        "diagnostic_reasons": gates.diagnostic_reasons,
        "compared_artifacts": built.compared_artifacts,
        "left_only_artifacts": built.left_only_artifacts,
        "right_only_artifacts": built.right_only_artifacts,
        "left_stem": built.left_stem,
        "right_stem": built.right_stem,
    }
    if args.include_state:
        payload["state"] = built.state

    if args.emit_json:
        print(json.dumps(payload, indent=2))
    else:
        _print_human(payload)

    if gates.content_parity_pass and gates.diagnostic_parity_pass:
        return 0
    return 1


def _print_human(payload: dict) -> None:
    print("Parity Compare")
    print(f"  left_stem:               {payload['left_stem']}")
    print(f"  right_stem:              {payload['right_stem']}")
    print(f"  content_parity_pass:     {payload['content_parity_pass']}")
    print(f"  diagnostic_parity_pass:  {payload['diagnostic_parity_pass']}")
    print(f"  compared_artifacts:      {', '.join(payload['compared_artifacts'])}")
    print(f"  left_only_artifacts:     {', '.join(payload['left_only_artifacts'])}")
    print(f"  right_only_artifacts:    {', '.join(payload['right_only_artifacts'])}")

    if payload["content_reasons"]:
        print("\nContent reasons:")
        for reason in payload["content_reasons"]:
            print(f"  - {reason}")

    if payload["diagnostic_reasons"]:
        print("\nDiagnostic reasons:")
        for reason in payload["diagnostic_reasons"]:
            print(f"  - {reason}")
