import argparse
import json
import sys
import uuid
from pathlib import Path

from ..architecture.entrypoints import generate_entrypoints_document
from ..architecture.import_graph import generate_import_graph_document


def run_architecture_cmd(args: argparse.Namespace) -> int:
    """Execute the architecture CLI command."""

    if args.entrypoints:
        repo_root = Path(args.repo).expanduser().resolve()
        if not repo_root.is_dir():
            print(f"Error: Path '{args.repo}' is not a directory.", file=sys.stderr)
            return 1
        run_id = f"cmd_run_{uuid.uuid4().hex[:8]}"
        canonical_sha256 = "0" * 64
        doc = generate_entrypoints_document(repo_root, run_id, canonical_sha256)
        print(json.dumps(doc, indent=2))
        return 0

    if args.import_graph:
        repo_root = Path(args.repo).expanduser().resolve()
        if not repo_root.is_dir():
            print(f"Error: Path '{args.repo}' is not a directory.", file=sys.stderr)
            return 1
        run_id = f"cmd_run_{uuid.uuid4().hex[:8]}"
        canonical_sha256 = "0" * 64
        doc = generate_import_graph_document(repo_root, run_id, canonical_sha256)
        print(json.dumps(doc, indent=2))
        return 0

    if getattr(args, "graph_index", False):
        if not getattr(args, "graph_in", None) or not getattr(
            args, "entrypoints_in", None
        ):
            print(
                "Error: --graph-index requires --graph-in and --entrypoints-in",
                file=sys.stderr,
            )
            return 1

        from ..architecture.graph_index import (
            GraphIndexCompilationError,
            compile_graph_index,
        )

        try:
            index = compile_graph_index(
                Path(args.graph_in),
                Path(args.entrypoints_in),
            )
        except GraphIndexCompilationError as exc:
            print(json.dumps(exc.as_dict(), sort_keys=True), file=sys.stderr)
            return 2
        print(json.dumps(index, indent=2))
        return 0

    print(
        "Error: You must specify an architecture view to extract "
        "(e.g., --entrypoints, --import-graph).",
        file=sys.stderr,
    )
    return 1
