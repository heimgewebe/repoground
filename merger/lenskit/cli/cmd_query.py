import argparse
import sys
import json
from pathlib import Path

from ..retrieval.query_core import execute_query
from ..retrieval.query_range_coverage import build_query_range_coverage_report
from ..retrieval.session import build_agent_query_session
from ..retrieval.output_projection import project_output
from .stale_check import check_stale_index
from .policy_loader import load_and_validate_embedding_policy, EmbeddingPolicyError

def run_query(args: argparse.Namespace) -> int:
    index_path = Path(args.index)
    if not index_path.exists():
        print(f"Error: Index file not found: {index_path}", file=sys.stderr)
        return 1

    # Perform stale index check
    stale_policy = getattr(args, "stale_policy", "fail")
    is_stale = check_stale_index(index_path, stale_policy=stale_policy)
    if is_stale and stale_policy == "fail":
        return 1

    applied_filters = {
        "repo": args.repo,
        "path": args.path,
        "ext": args.ext,
        "layer": args.layer,
        "artifact_type": getattr(args, "artifact_type", None)
    }

    policy_instance = None
    if getattr(args, "embedding_policy", None):
        policy_path = Path(args.embedding_policy)
        try:
            policy_instance = load_and_validate_embedding_policy(policy_path)
        except EmbeddingPolicyError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

    try:
        graph_weights_dict = None
        if getattr(args, "graph_weights", None):
            try:
                graph_weights_dict = json.loads(args.graph_weights)
            except json.JSONDecodeError:
                print("Error: Invalid JSON for --graph-weights", file=sys.stderr)
                return 1

        output_profile = getattr(args, "output_profile", None)
        context_mode = getattr(args, "context_mode", "exact")
        context_window_lines = getattr(args, "context_window_lines", 0)

        if context_mode == "window" and context_window_lines <= 0:
            print("Error: --context-mode window requires --context-window-lines > 0", file=sys.stderr)
            return 1

        if context_window_lines > 0 and context_mode != "window":
            print("Error: --context-window-lines requires --context-mode window", file=sys.stderr)
            return 1

        build_context = (
            getattr(args, "build_context_bundle", False)
            or bool(output_profile)
            or context_mode != "exact"
            or context_window_lines > 0
        )

        result = execute_query(
            index_path=index_path,
            query_text=args.q,
            k=args.k,
            filters=applied_filters,
            embedding_policy=policy_instance,
            explain=getattr(args, "explain", False),
            overmatch_guard=getattr(args, "overmatch_guard", False),
            graph_index_path=Path(args.graph_index) if getattr(args, "graph_index", None) else None,
            graph_weights=graph_weights_dict,
            test_penalty=getattr(args, "test_penalty", 0.75),
            trace=getattr(args, "trace", False),
            build_context=build_context,
            context_mode=context_mode,
            context_window_lines=context_window_lines
        )

        range_coverage_requested = (
            getattr(args, "range_coverage_report", False)
            or bool(getattr(args, "citation_map", None))
        )
        if range_coverage_requested:
            citation_map = getattr(args, "citation_map", None)
            result["range_coverage"] = build_query_range_coverage_report(
                result,
                citation_map_jsonl=Path(citation_map) if citation_map else None,
            )

        if getattr(args, "trace", False) and "query_trace" in result:
            out_dir_str = getattr(args, "trace_out_dir", None)
            out_dir = Path(out_dir_str) if out_dir_str else Path.cwd()

            if out_dir.exists() and not out_dir.is_dir():
                raise RuntimeError(f"--trace-out-dir path exists but is not a directory: {out_dir}")

            if not out_dir.exists():
                out_dir.mkdir(parents=True, exist_ok=True)

            trace_path = out_dir / "query_trace.json"
            trace_path.write_text(json.dumps(result["query_trace"], indent=2), encoding="utf-8")
            print(f"Query trace saved to {trace_path.absolute()}", file=sys.stderr)

            request_contract = {
                "query": args.q,
                "k": args.k,
                "output_profile": getattr(args, "output_profile", None),
                "explain": getattr(args, "explain", False)
            }

            # Pass out_dir and index_path to compute hashes and populate env block
            session = build_agent_query_session(
                request_contract,
                result,
                query_trace_ref="query_trace.json",
                out_dir=out_dir,
                index_path=str(args.index)
            )
            session_path = out_dir / "agent_query_session.json"
            session_path.write_text(json.dumps(session, indent=2), encoding="utf-8")

    except RuntimeError as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        return 1

    if args.emit == "json":
        output_profile = getattr(args, "output_profile", None)
        if output_profile:
            projected = project_output(result, output_profile)
            print(json.dumps(projected, indent=2))
        else:
            print(json.dumps(result, indent=2))
        return 0
    else:
        print(f"Found {result['count']} chunks for '{result['query']}'")
        print("-" * 60)
        for res in result["results"]:
            print(f"[{res['repo_id']}] {res['path']}:{res['range']}")
            print(f"    Type: {res['type']} | Layer: {res['layer']} | Score: {res['score']:.4f}")
        if "explain" in result:
            print("-" * 60)
            print("Explain Diagnostics:")
            print(json.dumps(result["explain"], indent=2))
        if "range_coverage" in result:
            coverage = result["range_coverage"]
            counts = coverage["counts"]
            print("-" * 60)
            print("Range Coverage:")
            print(
                "    total={total} explicit={explicit} canonical={canonical} "
                "derived={derived} unresolved={unresolved} malformed={malformed}".format(
                    total=coverage["total_hits"],
                    explicit=counts["hits_with_explicit_range_ref"],
                    canonical=counts["hits_with_explicit_canonical_md_range_ref"],
                    derived=counts["hits_with_derived_range_ref"],
                    unresolved=counts["unresolved_hits"],
                    malformed=counts["malformed_hits"],
                )
            )
            if coverage["citation_map"]["warnings"]:
                print("    citation_map_warnings:")
                for warning in coverage["citation_map"]["warnings"]:
                    print(f"    - {warning}")

    return 0
