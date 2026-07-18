"""Canonical CLI for compact, resolved RepoGround evidence navigation."""
from __future__ import annotations

import argparse
import json
import sys

from merger.repoground.core.bundle_access import query_existing_index
from merger.repoground.core.compact_evidence import project_compact_evidence


def register_evidence_query_commands(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "evidence-query",
        help="Query a bundle and print compact live-path evidence or explicit non-resolution reasons",
    )
    parser.add_argument("--bundle-manifest", required=True)
    parser.add_argument("--q", required=True)
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument("--output-profile", choices=["compact_evidence"], default="compact_evidence")
    parser.set_defaults(handler=run_evidence_query)


def run_evidence_query(args: argparse.Namespace) -> int:
    try:
        result = query_existing_index(
            args.bundle_manifest, args.q, k=args.k, resolve_evidence=True, project_sources=True
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        result = {
            "query": args.q,
            "status": "invalid",
            "error": str(exc),
            "resolved_evidence": {"hits": []},
        }
        print(json.dumps(project_compact_evidence(result), indent=2, sort_keys=True))
        print(f"evidence-query: {exc}", file=sys.stderr)
        return 1
    compact = project_compact_evidence(result)
    print(json.dumps(compact, indent=2, sort_keys=True))
    if result.get("status") != "available":
        return 1
    if not compact["compaction_pass"]:
        print(
            "evidence-query: compact response did not meet the 60% byte-reduction requirement",
            file=sys.stderr,
        )
        return 2
    return 0
