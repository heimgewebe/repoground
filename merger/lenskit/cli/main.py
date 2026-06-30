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

    # Bundle health command (post-emit validator)
    from .cmd_bundle_health import register_bundle_health_commands
    register_bundle_health_commands(subparsers)

    # Bundle surface command (real-dump surface self-check)
    from .cmd_bundle_surface import register_bundle_surface_commands
    register_bundle_surface_commands(subparsers)

    # Context quality command (diagnostic projection)
    from .cmd_context_quality import register_context_quality_commands
    register_context_quality_commands(subparsers)

    # Federation command
    from .cmd_federation import register_federation_commands
    register_federation_commands(subparsers)

    # Parity command
    from .cmd_parity import register_parity_commands
    register_parity_commands(subparsers)

    # Governance command (Track C: authority / inference-boundary contract lint)
    from .cmd_governance import register_governance_commands
    register_governance_commands(subparsers)

    # Doc-freshness command (diagnostic: docs-vs-code drift)
    from .cmd_doc_freshness import register_doc_freshness_commands
    register_doc_freshness_commands(subparsers)

    # Agent entry manifest command
    from .cmd_agent_entry import register_agent_entry_commands
    register_agent_entry_commands(subparsers)

    # Export safety command
    from .cmd_export_safety import register_export_safety_commands
    register_export_safety_commands(subparsers)

    # Agent consumption command
    from .cmd_agent_consumption import register_agent_consumption_commands
    register_agent_consumption_commands(subparsers)

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

    # Verify command (PR-Schau bundle verifier)
    verify_parser = subparsers.add_parser("verify", help="Verify a PR-Schau bundle (schema, integrity, no-truncate guard)")
    verify_parser.add_argument("bundle", help="Path to a PR-Schau bundle (index file or directory)")
    verify_parser.add_argument("--level", choices=["basic", "full"], default="full", help="Verification level")

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
    from .cmd_atlas import register_atlas_commands
    register_atlas_commands(subparsers)

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
        from . import pr_schau_verify
        return pr_schau_verify.run_verify(parsed_args.bundle, parsed_args.level)
    elif parsed_args.command == "architecture":
        from . import cmd_architecture
        return cmd_architecture.run_architecture_cmd(parsed_args)
    elif parsed_args.command == "atlas":
        from .cmd_atlas import handle_atlas_command
        return handle_atlas_command(parsed_args)
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
    elif parsed_args.command == "bundle-health":
        from .cmd_bundle_health import run_bundle_health_export_gate, run_bundle_health_post
        if parsed_args.bundle_health_cmd == "post":
            return run_bundle_health_post(parsed_args)
        if parsed_args.bundle_health_cmd == "export-gate":
            return run_bundle_health_export_gate(parsed_args)
        else:
            parser.parse_args(["bundle-health", "--help"])
            return 0
    elif parsed_args.command == "bundle-surface":
        from .cmd_bundle_surface import run_bundle_surface_validate
        if parsed_args.bundle_surface_cmd == "validate":
            return run_bundle_surface_validate(parsed_args)
        else:
            parser.parse_args(["bundle-surface", "--help"])
            return 0
    elif parsed_args.command == "context-quality":
        from .cmd_context_quality import run_context_quality_inspect
        if parsed_args.context_quality_cmd == "inspect":
            return run_context_quality_inspect(parsed_args)
        else:
            parser.parse_args(["context-quality", "--help"])
            return 0
    elif parsed_args.command == "federation":
        from .cmd_federation import handle_federation_command
        return handle_federation_command(parsed_args)
    elif parsed_args.command == "parity":
        from .cmd_parity import run_parity_compare, run_parity_enforce
        if parsed_args.parity_cmd == "compare":
            return run_parity_compare(parsed_args)
        elif parsed_args.parity_cmd == "enforce":
            return run_parity_enforce(parsed_args)
        raise RuntimeError(
            f"Unexpected parity command dispatch: {parsed_args.parity_cmd!r}"
        )
    elif parsed_args.command == "governance":
        from .cmd_governance import (
            run_governance_ast_lint,
            run_governance_forensic_preflight,
            run_governance_lint,
        )
        if parsed_args.governance_cmd == "lint":
            return run_governance_lint(parsed_args)
        elif parsed_args.governance_cmd == "ast-lint":
            return run_governance_ast_lint(parsed_args)
        elif parsed_args.governance_cmd == "forensic-preflight":
            return run_governance_forensic_preflight(parsed_args)
        else:
            parser.parse_args(["governance", "--help"])
            return 0
    elif parsed_args.command == "doc-freshness":
        from .cmd_doc_freshness import (
            run_doc_freshness_inspect,
            run_doc_freshness_update,
        )
        if parsed_args.doc_freshness_cmd == "inspect":
            return run_doc_freshness_inspect(parsed_args)
        elif parsed_args.doc_freshness_cmd == "update":
            return run_doc_freshness_update(parsed_args)
        else:
            parser.parse_args(["doc-freshness", "--help"])
            return 0
    elif parsed_args.command == "agent-entry":
        from .cmd_agent_entry import run_agent_entry
        return run_agent_entry(parsed_args)
    elif parsed_args.command == "export-safety":
        from .cmd_export_safety import run_export_safety
        return run_export_safety(parsed_args)
    elif parsed_args.command == "agent-consumption":
        from .cmd_agent_consumption import run_agent_consumption
        return run_agent_consumption(parsed_args)
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
