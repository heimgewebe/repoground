"""Direct CLI for the read-only RepoGround agent impact adapter.

Usage:
    python -m merger.repoground.cli.agent_impact \
      --config adapter.json --snapshot-id demo --target-path src/demo.py
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence

from merger.repoground.core.agent_impact_adapter import (
    RepoGroundAgentImpactAdapter,
)
from merger.repoground.core.readonly_adapter import (
    RepoGroundReadonlyAdapterError,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a read-only RepoGround agent impact/edit context.",
    )
    parser.add_argument("--config", required=True)
    parser.add_argument("--snapshot-id", required=True)
    parser.add_argument("--target-path")
    parser.add_argument("--target-symbol")
    parser.add_argument(
        "--changed-path",
        action="append",
        default=[],
        dest="changed_paths",
    )
    parser.add_argument("--mode", choices=("impact", "edit"), default="impact")
    parser.add_argument("--max-items", type=int, default=25)
    parser.add_argument(
        "--no-query-context",
        action="store_false",
        dest="include_query_context",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        adapter = RepoGroundAgentImpactAdapter.from_config(args.config)
        result = adapter.agent_impact_context(
            args.snapshot_id,
            target_path=args.target_path,
            target_symbol=args.target_symbol,
            changed_paths=args.changed_paths,
            mode=args.mode,
            max_items=args.max_items,
            include_query_context=args.include_query_context,
        )
    except (OSError, RepoGroundReadonlyAdapterError, ValueError) as exc:
        result = {
            "kind": "repobrief.agent_impact_cli_error",
            "version": "1.0",
            "status": "invalid",
            "error": str(exc),
            "error_code": "agent_impact_cli_invalid",
        }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if result.get("status") not in {"invalid", "blocked"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
