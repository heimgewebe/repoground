import argparse
import sys
import json
from pathlib import Path

from ..retrieval.eval_core import do_eval, parse_gold_queries
from .stale_check import check_stale_index
from .policy_loader import load_and_validate_embedding_policy, EmbeddingPolicyError

def run_eval(args: argparse.Namespace) -> int:
    index_path = Path(args.index)
    if not index_path.exists():
        print(f"Error: Index file not found: {index_path}", file=sys.stderr)
        return 1

    # Perform stale index check
    stale_policy = getattr(args, "stale_policy", "fail")
    is_stale = check_stale_index(index_path, stale_policy=stale_policy)
    if is_stale and stale_policy == "fail":
        return 1

    queries_path = Path(args.queries) if args.queries else Path("docs/retrieval/queries.md")
    is_json_mode = (args.emit == "json")

    policy_instance = None
    if getattr(args, "embedding_policy", None):
        policy_path = Path(args.embedding_policy)
        try:
            policy_instance = load_and_validate_embedding_policy(policy_path)
        except EmbeddingPolicyError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

    graph_weights_dict = None
    if getattr(args, "graph_weights", None):
        try:
            graph_weights_dict = json.loads(args.graph_weights)
        except json.JSONDecodeError:
            print("Error: Invalid JSON for --graph-weights", file=sys.stderr)
            return 1

    try:
        out = do_eval(
            index_path,
            queries_path,
            args.k,
            is_json_mode,
            is_stale,
            policy_instance,
            graph_index_path=Path(args.graph_index) if getattr(args, "graph_index", None) else None,
            graph_weights=graph_weights_dict
        )
    except RuntimeError as e:
        print(f"Error during eval: {e}", file=sys.stderr)
        return 1

    if out is None:
        return 1

    if is_json_mode:
        print(json.dumps(out, indent=2))

    # Evaluate against accept_criteria if present in a JSON queries file
    if queries_path.suffix == ".json":
        try:
            # We parse the gold queries a second time here. This avoids breaking the existing
            # do_eval API while keeping gate threshold logic strictly in the CLI wrapper.
            gold_queries = parse_gold_queries(queries_path)

            # Determine the global required recall across all queries' accept_criteria.
            # We enforce exactly one threshold (global recall@k). If multiple distinct thresholds
            # are found, we fail, as per explicit gate semantics.
            thresholds = set()
            for q in gold_queries:
                ac = q.get("accept_criteria", {})
                if f"recall_at_{args.k}" in ac:
                    raw_val = ac[f"recall_at_{args.k}"]
                    try:
                        val = float(raw_val)
                    except (ValueError, TypeError):
                        print(f"Error: Invalid recall_at_{args.k} threshold '{raw_val}'; must be a numeric ratio between 0.0 and 1.0.", file=sys.stderr)
                        return 1

                    if val < 0.0 or val > 1.0:
                        print(f"Error: Invalid recall_at_{args.k} threshold ({val}). accept_criteria must use a ratio between 0.0 and 1.0.", file=sys.stderr)
                        return 1
                    thresholds.add(val)

            if len(thresholds) > 1:
                print(f"Error: Multiple conflicting recall_at_{args.k} thresholds found in queries. Gate requires exactly one global threshold.", file=sys.stderr)
                return 1

            if len(thresholds) == 1:
                required_recall = thresholds.pop()
                actual_recall = out["metrics"].get(f"recall@{args.k}", 0.0)

                # The criteria is strictly a ratio (0.0 to 1.0) but metrics is a percentage (0.0 to 100.0), so normalize
                target_percent = required_recall * 100.0

                if actual_recall < target_percent:
                    print(f"Error: Recall@{args.k} ({actual_recall:.1f}%) did not meet the global required threshold ({target_percent:.1f}%).", file=sys.stderr)
                    return 1
        except Exception as e:
            print(f"Error evaluating accept criteria: {e}", file=sys.stderr)
            return 1

    return 0
