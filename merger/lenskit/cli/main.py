import argparse
import sys
import logging
from typing import List, Optional
from . import cmd_index
from . import cmd_query
from . import cmd_eval

def main(args: Optional[List[str]] = None) -> int:
    if args is None:
        args = sys.argv[1:]

    logging.basicConfig(level=logging.WARNING, format='%(levelname)s: %(message)s')

    parser = argparse.ArgumentParser(
        prog="lenskit",
        description="lenskit: Repo Understanding & Retrieval System"
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Citation command
    from .cmd_citation import register_citation_commands
    register_citation_commands(subparsers)

    # Agent reading pack command
    from .cmd_agent_pack import register_agent_pack_commands
    register_agent_pack_commands(subparsers)

    # Federation command
    from .cmd_federation import register_federation_commands
    register_federation_commands(subparsers)

    # Parity command
    from .cmd_parity import register_parity_commands
    register_parity_commands(subparsers)

    # rLens client command
    from .cmd_rlens_client import register_rlens_client_commands
    register_rlens_client_commands(subparsers)

    # Index command
    index_parser = subparsers.add_parser("index", help="Build or verify retrieval index")
    index_parser.add_argument("--dump", required=True, help="Path to dump_index.json")
    index_parser.add_argument("--chunk-index", required=True, help="Path to chunk_index.jsonl")
    index_parser.add_argument("--out", help="Output path for SQLite index")
    index_parser.add_argument("--rebuild", action="store_true", help="Force rebuild of index")
    index_parser.add_argument("--verify", action="store_true", help="Verify existing index freshness")

    # Query command
    query_parser = subparsers.add_parser("query", help="Query the retrieval index")
    query_parser.add_argument("--index", required=True, help="Path to SQLite index")
    query_parser.add_argument("--q", default="", help="Search query text")
    query_parser.add_argument("--k", type=int, default=10, help="Max results")
    query_parser.add_argument("--repo", help="Filter by repo_id")
    query_parser.add_argument("--path", help="Filter by path substring")
    query_parser.add_argument("--ext", help="Filter by file extension")
    query_parser.add_argument("--layer", help="Filter by layer")
    query_parser.add_argument("--artifact-type", help="Filter by artifact_type")
    query_parser.add_argument("--emit", choices=["text", "json"], default="text", help="Output format")
    query_parser.add_argument("--stale-policy", choices=["warn", "fail", "ignore"], default="fail", help="Policy for handling stale indices")
    query_parser.add_argument("--embedding-policy", help="Path to embedding-policy.v1 JSON policy instance (requests semantic pipeline; currently candidate overfetch only)")
    query_parser.add_argument("--explain", action="store_true", help="Include diagnostic explain block in query results")
    query_parser.add_argument("--overmatch-guard", action="store_true", help="Disable synonym OR-expansion in router")
    query_parser.add_argument("--graph-index", help="Path to graph_index.json to enable graph-aware reranking")
    query_parser.add_argument("--graph-weights", help='JSON string of graph weights (e.g. \'{"w_bm25": 0.65}\')')
    query_parser.add_argument("--test-penalty", type=float, default=0.75, help="Score penalty multiplier for test files")
    query_parser.add_argument("--build-context-bundle", action="store_true", help="Explicitly build context bundle")
    query_parser.add_argument("--output-profile", choices=["human_review", "agent_minimal", "ui_navigation", "lookup_minimal", "review_context"], help="Projection profile for the query result")
    query_parser.add_argument("--context-mode", choices=["exact", "block", "window", "file"], default="exact", help="Context expansion mode")
    query_parser.add_argument("--context-window-lines", type=int, default=0, help="Number of lines to expand in window mode")
    query_parser.add_argument("--trace", action="store_true", help="Generate query_trace.json and agent_query_session.json (defaults to current directory, override with --trace-out-dir)")
    query_parser.add_argument("--trace-out-dir", help="Output directory for trace and session artifacts")

    # Eval command
    eval_parser = subparsers.add_parser("eval", help="Evaluate retrieval quality against Gold Queries")
    eval_parser.add_argument("--index", required=True, help="Path to SQLite index")
    eval_parser.add_argument("--queries", default="docs/retrieval/queries.md", help="Path to queries markdown file")
    eval_parser.add_argument("--k", type=int, default=10, help="Max results for recall calculation")
    eval_parser.add_argument("--emit", choices=["text", "json"], default="text", help="Output format")
    eval_parser.add_argument("--stale-policy", choices=["warn", "fail", "ignore"], default="fail", help="Policy for handling stale indices")
    eval_parser.add_argument("--embedding-policy", help="Path to embedding-policy.v1 JSON policy instance (requests semantic pipeline; currently candidate overfetch only)")
    eval_parser.add_argument("--graph-index", help="Path to graph_index.json to enable graph-aware reranking")
    eval_parser.add_argument("--graph-weights", help='JSON string of graph weights (e.g. \'{"w_bm25": 0.65}\')')

    # Range command
    range_parser = subparsers.add_parser("range", help="Range operations")
    range_subparsers = range_parser.add_subparsers(dest="range_cmd", required=True, help="Range commands")
    range_get_parser = range_subparsers.add_parser("get", help="Get a deterministic byte range from an artifact")
    range_get_parser.add_argument("--manifest", required=True, help="Path to bundle manifest or dump index")
    range_get_parser.add_argument("--ref", required=True, help="Path to range_ref JSON file")
    range_get_parser.add_argument("--format", choices=["raw", "json"], default="json", help="Output format")

    # PR-Explain command
    pr_explain_parser = subparsers.add_parser("pr-explain", help="Explain PR context")
    pr_explain_parser.add_argument("--delta", required=True, help="Path to delta.json file")

    # Verify command (placeholder)
    subparsers.add_parser("verify", help="Verify artifacts or bundles")

    # Artifact lookup command
    artifact_parser = subparsers.add_parser("artifact", help="Look up a stored query artifact by ID")
    artifact_parser.add_argument("--id", required=True, help="Artifact ID (e.g. qart-<hex>)")
    artifact_parser.add_argument(
        "--artifact-type",
        choices=["query_trace", "context_bundle", "agent_query_session"],
        dest="artifact_type",
        required=True,
        help="Expected artifact type. Returns status=not_found if ID exists but type mismatches.",
    )
    artifact_parser.add_argument("--hub", help="Hub root path (used to locate .rlens-service store)")

    # Architecture command
    architecture_parser = subparsers.add_parser("architecture", help="Extract architecture views")
    architecture_parser.add_argument("--repo", default=".", help="Path to repository root")
    architecture_group = architecture_parser.add_mutually_exclusive_group(required=True)
    architecture_group.add_argument("--entrypoints", action="store_true", help="Extract entrypoints")
    architecture_group.add_argument("--import-graph", action="store_true", help="Extract Python import graph")
    architecture_group.add_argument("--graph-index", action="store_true", help="Compile graph index from entrypoints and import graph")
    architecture_parser.add_argument("--graph-in", help="Path to architecture.graph.json")
    architecture_parser.add_argument("--entrypoints-in", help="Path to entrypoints.json")

    # Atlas command
    # NOTE: These Atlas CLI definitions are duplicated in cli/rlens.py.
    # Keep them in sync to prevent drift.
    atlas_parser = subparsers.add_parser("atlas", help="Atlas filesystem crawler")
    atlas_subparsers = atlas_parser.add_subparsers(dest="atlas_cmd", required=True, help="Atlas commands")
    atlas_scan_parser = atlas_subparsers.add_parser("scan", help="Scan a filesystem path")
    atlas_scan_parser.add_argument("path", help="The root path to scan")
    atlas_scan_parser.add_argument("--exclude", help="Comma-separated list of glob patterns to exclude")
    atlas_scan_parser.add_argument("--no-default-excludes", action="store_true", help="Do not use default system excludes")
    atlas_scan_parser.add_argument("--max-file-size", type=int, help="Maximum file size in MB to include in scan (default 50)")
    atlas_scan_parser.add_argument("--no-max-file-size", action="store_true", help="Remove file size limits for the scan")
    atlas_scan_parser.add_argument("--depth", type=int, default=6, help="Maximum depth to scan")
    atlas_scan_parser.add_argument("--limit", type=int, default=200000, help="Maximum number of entries to scan")
    atlas_scan_parser.add_argument("--mode", choices=["inventory", "topology", "content", "workspace"], default="inventory", help="The scan mode to execute")
    atlas_scan_parser.add_argument("--machine-id", help="Explicit machine ID for the registry (defaults to ATLAS_MACHINE_ID env var or hostname)")
    atlas_scan_parser.add_argument("--hostname", help="Explicit hostname for the registry (defaults to system hostname)")
    atlas_scan_parser.add_argument("--root-id", help="Explicit root ID for the registry")
    atlas_scan_parser.add_argument("--root-label", help="Explicit root label for the registry")
    atlas_scan_parser.add_argument("--incremental", action="store_true", help="Perform an incremental scan based on the latest snapshot")

    atlas_subparsers.add_parser("machine-health", help="List registered machines with health status and last seen info")
    atlas_subparsers.add_parser("machines", help="List registered machines")
    atlas_roots_parser = atlas_subparsers.add_parser("roots", help="List registered roots")
    atlas_roots_parser.add_argument("--group-by-label", action="store_true", help="Group output by root_label (human-readable text format)")
    atlas_subparsers.add_parser("snapshots", help="List registered snapshots")

    atlas_diff_parser = atlas_subparsers.add_parser("diff", help="Compute delta between two snapshots")
    atlas_diff_parser.add_argument("from_snapshot", help="The from snapshot ID or machine:root_path")
    atlas_diff_parser.add_argument("to_snapshot", help="The to snapshot ID or machine:root_path")

    atlas_history_parser = atlas_subparsers.add_parser("history", help="Show file history across snapshots")
    atlas_history_parser.add_argument("machine_id", help="The machine ID")
    atlas_history_parser.add_argument("root_id", help="The root ID")
    atlas_history_parser.add_argument("rel_path", help="The canonical relative path of the file")

    atlas_search_parser = atlas_subparsers.add_parser("search", help="Search the atlas registry")
    atlas_search_parser.add_argument("--query", help="General search query")
    atlas_search_parser.add_argument("--machine-id", help="Filter by machine ID")
    atlas_search_parser.add_argument("--root-id", help="Filter by root ID")
    atlas_search_parser.add_argument("--snapshot-id", help="Filter by snapshot ID")
    atlas_search_parser.add_argument("--path", help="Filter by path pattern")
    atlas_search_parser.add_argument("--name", help="Filter by name pattern")
    atlas_search_parser.add_argument("--ext", help="Filter by extension")
    atlas_search_parser.add_argument("--min-size", type=int, help="Filter by minimum size in bytes")
    atlas_search_parser.add_argument("--max-size", type=int, help="Filter by maximum size in bytes")
    atlas_search_parser.add_argument("--date-after", help="Filter by modified date after (ISO format)")
    atlas_search_parser.add_argument("--date-before", help="Filter by modified date before (ISO format)")
    atlas_search_parser.add_argument("--content-query", help="Filter by file content (full text search within matched text files)")

    atlas_analyze_parser = atlas_subparsers.add_parser("analyze", help="Run analysis on a snapshot")
    atlas_analyze_subparsers = atlas_analyze_parser.add_subparsers(dest="analyze_command", required=True)
    atlas_analyze_dups_parser = atlas_analyze_subparsers.add_parser("duplicates", help="Analyze duplicates in a snapshot")
    atlas_analyze_dups_parser.add_argument("snapshot_id", help="The snapshot ID to analyze")

    atlas_analyze_orphans_parser = atlas_analyze_subparsers.add_parser("orphans", help="Analyze orphans in a snapshot")
    atlas_analyze_orphans_parser.add_argument("snapshot_id", help="The snapshot ID to analyze")

    atlas_analyze_disk_parser = atlas_analyze_subparsers.add_parser("disk", help="Analyze disk hotspots and old/large files in a snapshot")
    atlas_analyze_disk_parser.add_argument("snapshot_id", help="The snapshot ID to analyze")

    atlas_analyze_backup_gap_parser = atlas_analyze_subparsers.add_parser("backup-gap", help="Compare two snapshots (source and backup) to find missing, outdated, and extraneous files")
    atlas_analyze_backup_gap_parser.add_argument("source_snapshot", help="The source snapshot ID or reference (machine:path)")
    atlas_analyze_backup_gap_parser.add_argument("backup_snapshot", help="The backup snapshot ID or reference (machine:path)")

    atlas_analyze_growth_parser = atlas_analyze_subparsers.add_parser("growth", help="Analyze cross-root growth and report epistemic boundaries")
    atlas_analyze_growth_parser.add_argument("source_snapshot", help="The source snapshot ID or reference (machine:path)")
    atlas_analyze_growth_parser.add_argument("target_snapshot", help="The target snapshot ID or reference (machine:path)")

    parsed_args = parser.parse_args(args)

    if parsed_args.command is None:
        parser.print_help()
        return 0

    if parsed_args.command == "index":
        return cmd_index.run_index(parsed_args)
    elif parsed_args.command == "query":
        return cmd_query.run_query(parsed_args)
    elif parsed_args.command == "eval":
        return cmd_eval.run_eval(parsed_args)
    elif parsed_args.command == "range":
        if parsed_args.range_cmd == "get":
            return cmd_range_get(parsed_args)
        else:
            parser.parse_args(["range", "--help"])
            return 0
    elif parsed_args.command == "pr-explain":
        from . import pr_explain
        return pr_explain.run_pr_explain(parsed_args)
    elif parsed_args.command == "verify":
        print("Verify command placeholder. Use pr-schau-verify for now.")
        return 1
    elif parsed_args.command == "architecture":
        from . import cmd_architecture
        return cmd_architecture.run_architecture_cmd(parsed_args)
    elif parsed_args.command == "atlas":
        from . import cmd_atlas
        if parsed_args.atlas_cmd == "scan":
            return cmd_atlas.run_atlas_scan(parsed_args)
        elif parsed_args.atlas_cmd == "machines":
            return cmd_atlas.run_atlas_machines(parsed_args)
        elif parsed_args.atlas_cmd == "machine-health":
            return cmd_atlas.run_atlas_machine_health(parsed_args)
        elif parsed_args.atlas_cmd == "roots":
            return cmd_atlas.run_atlas_roots(parsed_args)
        elif parsed_args.atlas_cmd == "snapshots":
            return cmd_atlas.run_atlas_snapshots(parsed_args)
        elif parsed_args.atlas_cmd == "diff":
            return cmd_atlas.run_atlas_diff(parsed_args)
        elif parsed_args.atlas_cmd == "history":
            return cmd_atlas.run_atlas_history(parsed_args)
        elif parsed_args.atlas_cmd == "search":
            return cmd_atlas.run_atlas_search(parsed_args)
        elif parsed_args.atlas_cmd == "analyze":
            return cmd_atlas.run_atlas_analyze(parsed_args)
        else:
            parser.parse_args(["atlas", "--help"])
            return 0
    elif parsed_args.command == "citation":
        from .cmd_citation import run_citation_produce, run_citation_validate
        if parsed_args.citation_cmd == "validate":
            return run_citation_validate(parsed_args)
        elif parsed_args.citation_cmd == "produce":
            return run_citation_produce(parsed_args)
        else:
            parser.parse_args(["citation", "--help"])
            return 0
    elif parsed_args.command == "agent-pack":
        from .cmd_agent_pack import run_agent_pack_produce
        if parsed_args.agent_pack_cmd == "produce":
            return run_agent_pack_produce(parsed_args)
        else:
            parser.parse_args(["agent-pack", "--help"])
            return 0
    elif parsed_args.command == "federation":
        from .cmd_federation import handle_federation_command
        return handle_federation_command(parsed_args)
    elif parsed_args.command == "parity":
        from .cmd_parity import run_parity_compare
        if parsed_args.parity_cmd == "compare":
            return run_parity_compare(parsed_args)
        raise RuntimeError(
            f"Unexpected parity command dispatch: {parsed_args.parity_cmd!r}"
        )
    elif parsed_args.command == "artifact":
        from . import cmd_artifact
        return cmd_artifact.run_artifact_lookup(parsed_args)
    elif parsed_args.command == "rlens-client":
        from .cmd_rlens_client import run_rlens_client
        return run_rlens_client(parsed_args)

    return 0


def cmd_range_get(args: argparse.Namespace) -> int:
    import sys
    import json
    from pathlib import Path
    from merger.lenskit.core.range_resolver import resolve_range_ref

    manifest_path = Path(args.manifest)
    ref_path = Path(args.ref)

    try:
        if not ref_path.exists():
            raise FileNotFoundError(f"range_ref file not found: {ref_path}")

        with ref_path.open("r", encoding="utf-8") as f:
            ref = json.load(f)

        result = resolve_range_ref(manifest_path, ref)

        if args.format == "json":
            print(json.dumps(result, indent=2))
        else:
            print(result["text"], end="")

        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
