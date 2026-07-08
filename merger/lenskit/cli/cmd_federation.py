import argparse
import sys
import json
from pathlib import Path

def register_federation_commands(subparsers) -> None:
    """Registers federation subcommands and arguments."""
    federation_parser = subparsers.add_parser("federation", help="Manage federated cross-repo bundles")
    federation_subparsers = federation_parser.add_subparsers(dest="federation_command", required=True)

    # init
    init_parser = federation_subparsers.add_parser("init", help="Initialize a new federation index")
    init_parser.add_argument("--id", required=True, help="Unique federation ID (e.g., project name)")
    init_parser.add_argument("--out", type=str, default="federation_index.json", help="Path to write the new federation index")

    # add
    add_parser = federation_subparsers.add_parser("add", help="Add a bundle to the federation index")
    add_parser.add_argument("--index", required=True, help="Path to federation index")
    add_parser.add_argument("--repo", required=True, help="Unique repo ID for this bundle")
    add_parser.add_argument("--bundle", required=True, help="Path or URI to the bundle root")

    # inspect
    inspect_parser = federation_subparsers.add_parser("inspect", help="Inspect a federation index")
    inspect_parser.add_argument("--index", required=True, help="Path to federation index")

    # validate
    validate_parser = federation_subparsers.add_parser("validate", help="Validate a federation index")
    validate_parser.add_argument("--index", required=True, help="Path to federation index")

    # query
    query_parser = federation_subparsers.add_parser("query", help="Execute a minimal federated query fan-out across local bundles")
    query_parser.add_argument("--index", help="Path to federation index")
    query_parser.add_argument(
        "--bundle",
        action="append",
        default=[],
        metavar="REPO_ID=PATH",
        help="Inline bundle root or index file. May be repeated instead of --index.",
    )
    query_parser.add_argument(
        "--federation-id",
        default="inline-bundle-set",
        help="Federation ID used for inline --bundle queries.",
    )
    query_parser.add_argument("-q", "--query", required=True, help="Query string")
    query_parser.add_argument("-k", type=int, default=10, help="Number of final results to return (top-k across all bundles)")
    query_parser.add_argument("--repo", type=str, help="Filter by repository ID (currently the only supported filter)")
    query_parser.add_argument("--trace", action="store_true", help="Include diagnostic trace and generate federation_trace.json (and federation_conflicts.json if applicable) in CWD")



def _parse_inline_bundle_specs(bundle_args: list[str]) -> list[dict[str, str]]:
    specs: list[dict[str, str]] = []
    for raw in bundle_args:
        if "=" not in raw:
            raise ValueError("--bundle must use REPO_ID=PATH")
        repo_id, bundle_path = raw.split("=", 1)
        repo_id = repo_id.strip()
        bundle_path = bundle_path.strip()
        if not repo_id or not bundle_path:
            raise ValueError("--bundle requires non-empty REPO_ID and PATH")
        specs.append({"repo_id": repo_id, "bundle_path": bundle_path})
    return specs

def handle_federation_command(args: argparse.Namespace) -> int:
    """Dispatches federation commands to their respective handlers."""
    from merger.lenskit.core.federation import init_federation
    from merger.lenskit.core.federation import add_bundle
    from merger.lenskit.core.federation import inspect_federation
    from merger.lenskit.core.federation import validate_federation

    if args.federation_command == "init":
        out_path = Path(args.out)
        try:
            init_federation(args.id, out_path)
            print(f"Successfully initialized federation index '{args.id}' at {out_path.as_posix()}")
            return 0
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

    elif args.federation_command == "add":
        index_path = Path(args.index)
        try:
            add_bundle(index_path, args.repo, args.bundle)
            print(f"Successfully added bundle '{args.repo}' to federation index at {index_path.as_posix()}")
            return 0
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

    elif args.federation_command == "inspect":
        index_path = Path(args.index)
        try:
            summary = inspect_federation(index_path)
            print(json.dumps(summary, indent=2))
            return 0
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

    elif args.federation_command == "validate":
        index_path = Path(args.index)
        try:
            is_valid = validate_federation(index_path)
            if is_valid:
                print(f"Federation index at {index_path.as_posix()} is valid.")
                return 0
            else:
                print(f"Federation index at {index_path.as_posix()} is invalid.", file=sys.stderr)
                return 1
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

    elif args.federation_command == "query":
        from merger.lenskit.retrieval.federation_query import execute_federated_query
        from merger.lenskit.retrieval.federation_query import execute_federated_query_from_bundles
        index_path = Path(args.index) if args.index else None
        inline_bundles = getattr(args, "bundle", []) or []
        filters = None
        if args.repo:
            filters = {"repo": args.repo}

        try:
            if bool(index_path) == bool(inline_bundles):
                raise ValueError("provide exactly one query source: --index or one or more --bundle REPO_ID=PATH")

            if index_path:
                res = execute_federated_query(
                    index_path,
                    query_text=args.query,
                    k=args.k,
                    filters=filters,
                    trace=args.trace
                )
            else:
                res = execute_federated_query_from_bundles(
                    _parse_inline_bundle_specs(inline_bundles),
                    query_text=args.query,
                    k=args.k,
                    filters=filters,
                    trace=args.trace,
                    federation_id=args.federation_id,
                    base_path=Path.cwd(),
                )
            print(json.dumps(res, indent=2))

            # Write trace if requested
            if args.trace and "federation_trace" in res:
                # Note: The creation of `federation_trace.json` here is an explicit CLI projection
                # of the runtime diagnostics meant for localized debugging. It does not replace
                # a full canonical artifact management lifecycle.
                import datetime
                trace_obj = {
                    "query": args.query,
                    "total_results": res.get("total_candidates_found", res["count"]),
                    "timestamp": datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat(),
                    "bundles": []
                }

                # Fetch original bundles from the persisted index or from inline specs.
                if index_path:
                    with index_path.open("r", encoding="utf-8") as f:
                        fed_data = json.load(f)
                else:
                    fed_data = {
                        "bundles": _parse_inline_bundle_specs(inline_bundles),
                    }

                status_map = res["federation_trace"].get("bundle_status", {})
                error_map = res["federation_trace"].get("bundle_errors", {})
                latency_map = res["federation_trace"].get("bundle_latency_ms", {})

                for b in fed_data.get("bundles", []):
                    repo_id = b["repo_id"]
                    b_obj = {
                        "repo_id": repo_id,
                        "bundle_path": b["bundle_path"],
                        "status": status_map.get(repo_id, "error")
                    }
                    if "last_fingerprint" in b:
                        b_obj["fingerprint"] = b["last_fingerprint"]
                    if repo_id in latency_map:
                        b_obj["latency_ms"] = float(latency_map[repo_id])
                    if repo_id in error_map:
                        b_obj["error_message"] = error_map[repo_id]

                    trace_obj["bundles"].append(b_obj)

                trace_out_path = Path("federation_trace.json")
                with trace_out_path.open("w", encoding="utf-8") as f:
                    json.dump(trace_obj, f, indent=2)

            # Write conflicts if requested
            conflicts = res.get("federation_conflicts")
            if args.trace and conflicts:
                conflicts_out_path = Path("federation_conflicts.json")
                with conflicts_out_path.open("w", encoding="utf-8") as f:
                    json.dump(conflicts, f, indent=2)

            # Write cross-repo links if requested
            cross_repo_links = res.get("cross_repo_links")
            if args.trace and cross_repo_links:
                links_out_path = Path("cross_repo_links.json")
                with links_out_path.open("w", encoding="utf-8") as f:
                    json.dump(cross_repo_links, f, indent=2)

            return 0
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

    return 0
