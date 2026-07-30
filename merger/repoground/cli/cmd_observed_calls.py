"""CLI surface for the Observed Call Overlay v1 (S2).

``observed-calls produce`` is the only RepoGround entry point that executes
target code. It is never reached by bundle generation: the static pipeline
stays non-executing, and an overlay exists only because an operator explicitly
asked for one named command to be traced.

``observed-calls callers`` and ``observed-calls callees`` read that overlay
back. They are deliberately separate from ``get_callers``/``get_callees``: a
consumer that wants observed evidence has to ask for it by name, and what it
gets is labelled S2 throughout.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def register_observed_calls_commands(subparsers) -> None:
    parser = subparsers.add_parser(
        "observed-calls",
        help="Produce and read run-bound observed call evidence (S2)",
    )
    observed_subparsers = parser.add_subparsers(
        dest="observed_calls_cmd", required=True, help="Observed call commands"
    )

    produce_parser = observed_subparsers.add_parser(
        "produce",
        help="Trace one command and emit its Observed Call Overlay v1 (S2)",
    )
    produce_parser.add_argument(
        "--repo-root", default=".", help="Repository to observe"
    )
    produce_parser.add_argument(
        "--run-id", required=True, help="Bundle run identity to bind the overlay to"
    )
    produce_parser.add_argument(
        "--canonical-dump-index-sha256",
        required=True,
        help="sha256 of the dump_index_json artifact this overlay is read next to",
    )
    produce_parser.add_argument(
        "--output", dest="output_path", required=True, help="Output path for the overlay"
    )
    produce_parser.add_argument(
        "--observation-run-id",
        default=None,
        help="Explicit observation identity (default: derived from the run fingerprint)",
    )
    # Named ``traced_command``: the subparser dispatcher already owns ``command``.
    produce_parser.add_argument(
        "traced_command",
        nargs=argparse.REMAINDER,
        help="Command to trace, after '--' (for example: -- -m pytest tests/)",
    )

    for name, subject in (
        ("callers", "What was observed calling this symbol"),
        ("callees", "What this symbol was observed to call"),
    ):
        read_parser = observed_subparsers.add_parser(name, help=subject)
        read_parser.add_argument("overlay", help="Path to the observed call overlay JSON")
        read_parser.add_argument("name", help="Symbol name to look up")
        read_parser.add_argument(
            "--path", default=None, help="Restrict to paths containing this substring"
        )
        read_parser.add_argument(
            "--k", type=int, default=25, help="Maximum number of relations to return"
        )
        read_parser.add_argument(
            "--call-graph",
            default=None,
            help="Static python_call_graph JSON to compare against (adds static_correspondence)",
        )


def run_observed_calls_produce(args: argparse.Namespace) -> int:
    from merger.repoground.architecture.observed_call_overlay import (
        generate_observed_call_overlay_document,
    )
    from merger.repoground.core.observed_call_overlay_validation import (
        validate_observed_call_overlay,
    )

    command = [item for item in args.traced_command if item != "--"]
    if not command:
        print("error: no command to trace was given after '--'", file=sys.stderr)
        return 2
    try:
        document = generate_observed_call_overlay_document(
            Path(args.repo_root),
            args.run_id,
            args.canonical_dump_index_sha256,
            command,
            observation_run_id=args.observation_run_id,
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    failure = validate_observed_call_overlay(document)
    if failure is not None:
        print(
            "error: produced overlay is invalid: "
            f"{failure['error_code']}: {failure['error']}",
            file=sys.stderr,
        )
        return 1
    out_path = Path(args.output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        f"observed overlay written: {out_path} "
        f"relations={document['relation_count']} "
        f"observed_calls={document['observed_call_total']} "
        f"exit_status={document['execution_outcome']['exit_status']}"
    )
    return 0


def run_observed_calls_read(args: argparse.Namespace, direction: str) -> int:
    from merger.repoground.core.observed_call_navigation import (
        get_observed_callees,
        get_observed_callers,
    )

    reader = get_observed_callers if direction == "callers" else get_observed_callees
    result = reader(
        args.overlay,
        args.name,
        args.path,
        args.k,
        call_graph=args.call_graph,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["status"] == "available" else 1
