import argparse
import json
import sys

# Policy levels for `lenskit parity enforce`.  ``content`` requires only
# content parity (suitable for capability-degraded runtimes such as
# constrained iOS/Pythonista hosts that cannot emit every diagnostic
# artifact — see docs/architecture/artifact-capability-matrix.md).
# ``diagnostic`` is the strict default and requires content *and* diagnostic
# parity.
_REQUIRE_LEVELS = ("content", "diagnostic")


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

    enforce_parser = parity_subparsers.add_parser(
        "enforce",
        help="Enforce a parity policy between two bundle manifests (gate, non-zero exit on violation)",
    )
    enforce_parser.add_argument("left_manifest", help="Left bundle manifest path")
    enforce_parser.add_argument("right_manifest", help="Right bundle manifest path")
    enforce_parser.add_argument(
        "--require",
        choices=_REQUIRE_LEVELS,
        default="diagnostic",
        dest="require_level",
        help=(
            "Required parity level: 'content' (content parity only) or "
            "'diagnostic' (content + diagnostic parity, default)"
        ),
    )
    enforce_parser.add_argument(
        "--json",
        action="store_true",
        dest="emit_json",
        help="Emit machine-readable JSON report",
    )
    enforce_parser.add_argument(
        "--include-state",
        action="store_true",
        dest="include_state",
        help="Include internal parity state mapping in JSON output",
    )


def _input_error_payload(e) -> dict:
    return {
        "status": "fail",
        "error_kind": getattr(e, "error_kind", "validation_error"),
        "message": str(e),
    }


def run_parity_compare(args: argparse.Namespace) -> int:
    from merger.lenskit.core.parity_gates import evaluate_parity_gates
    from merger.lenskit.core.parity_state import ParityInputError, build_parity_state

    try:
        built = build_parity_state(args.left_manifest, args.right_manifest)
    except ParityInputError as e:
        payload = _input_error_payload(e)
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


def run_parity_enforce(args: argparse.Namespace) -> int:
    """Enforce a parity policy: exit 0 only when the required level is satisfied.

    Exit codes:
        0 — required parity level satisfied
        1 — required parity level violated
        2 — input/validation error
    """
    from merger.lenskit.core.parity_gates import evaluate_parity_gates
    from merger.lenskit.core.parity_state import ParityInputError, build_parity_state

    require_level = getattr(args, "require_level", "diagnostic")
    emit_json = getattr(args, "emit_json", False)
    include_state = getattr(args, "include_state", False)

    if require_level not in _REQUIRE_LEVELS:
        payload = {
            "status": "fail",
            "error_kind": "invalid_require_level",
            "message": (
                f"Invalid --require value: {require_level!r}. "
                f"Allowed: {', '.join(_REQUIRE_LEVELS)}"
            ),
            "required_level": require_level,
            "allowed": list(_REQUIRE_LEVELS),
        }
        if emit_json:
            print(json.dumps(payload, indent=2))
        else:
            print(payload["message"], file=sys.stderr)
        return 2

    try:
        built = build_parity_state(args.left_manifest, args.right_manifest)
    except ParityInputError as e:
        payload = _input_error_payload(e)
        payload["required_level"] = require_level
        if emit_json:
            print(json.dumps(payload, indent=2))
        else:
            print(f"Parity enforce failed: {e}", file=sys.stderr)
        return 2

    gates = evaluate_parity_gates(built.state)

    if require_level == "content":
        enforced_pass = gates.content_parity_pass
    elif require_level == "diagnostic":
        enforced_pass = gates.content_parity_pass and gates.diagnostic_parity_pass
    else:
        # Defensive guard: validated above; unreachable unless _REQUIRE_LEVELS
        # is extended without adding the corresponding enforce semantics here.
        payload = {
            "status": "fail",
            "error_kind": "unsupported_require_level",
            "message": f"Unsupported --require value: {require_level!r}",
            "required_level": require_level,
            "allowed": list(_REQUIRE_LEVELS),
        }
        if emit_json:
            print(json.dumps(payload, indent=2))
        else:
            print(payload["message"], file=sys.stderr)
        return 2

    payload = {
        "required_level": require_level,
        "enforced_pass": enforced_pass,
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
    if include_state:
        payload["state"] = built.state

    if emit_json:
        print(json.dumps(payload, indent=2))
    else:
        _print_human_enforce(payload)

    return 0 if enforced_pass else 1


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


def _print_human_enforce(payload: dict) -> None:
    print("Parity Enforce")
    print(f"  required_level:          {payload['required_level']}")
    print(f"  enforced_pass:           {payload['enforced_pass']}")
    print(f"  content_parity_pass:     {payload['content_parity_pass']}")
    print(f"  diagnostic_parity_pass:  {payload['diagnostic_parity_pass']}")
    print(f"  left_stem:               {payload['left_stem']}")
    print(f"  right_stem:              {payload['right_stem']}")

    if payload["content_reasons"]:
        print("\nContent reasons:")
        for reason in payload["content_reasons"]:
            print(f"  - {reason}")

    if payload["diagnostic_reasons"]:
        print("\nDiagnostic reasons:")
        for reason in payload["diagnostic_reasons"]:
            print(f"  - {reason}")
