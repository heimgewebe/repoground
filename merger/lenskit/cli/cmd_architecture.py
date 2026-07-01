import argparse
import json
import sys
import uuid
from pathlib import Path

from ..architecture.entrypoints import generate_entrypoints_document
from ..architecture.import_graph import generate_import_graph_document


def _load_source_roots(args: argparse.Namespace) -> tuple[str, ...]:
    roots: list[str] = []
    raw_roots = getattr(args, "source_roots", None)
    if raw_roots:
        roots.extend(root.strip() for root in raw_roots.split(",") if root.strip())

    source_roots_file = getattr(args, "source_roots_file", None)
    if source_roots_file:
        path = Path(source_roots_file).expanduser().resolve()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ValueError(f"failed to read --source-roots-file: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError("--source-roots-file must contain a JSON object")
        if payload.get("kind") != "lenskit.architecture.source_roots":
            raise ValueError("--source-roots-file has invalid kind")
        if payload.get("version") != "1.0":
            raise ValueError("--source-roots-file has invalid version")
        file_roots = payload.get("roots")
        if not isinstance(file_roots, list) or not all(isinstance(root, str) for root in file_roots):
            raise ValueError("--source-roots-file roots must be a string array")
        roots.extend(file_roots)

    return tuple(roots)


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
        try:
            source_roots = _load_source_roots(args)
            doc = generate_import_graph_document(
                repo_root,
                run_id,
                canonical_sha256,
                source_roots=source_roots,
            )
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 2
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
