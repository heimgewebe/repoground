"""Existing RepoGround CLI entry point for deterministic, read-only change evidence."""
from __future__ import annotations

import argparse
import json

from merger.repoground.core.agent_evidence_pack import (
    USE_CASES,
    build_evidence_pack,
    render_evidence_markdown,
)


def register_agent_evidence_commands(subparsers: argparse._SubParsersAction) -> None:
    command = subparsers.add_parser(
        "agent-evidence",
        help="Read-only, revision-bound Git change and RepoGround bundle evidence",
    )
    command.add_argument("--repo-root", required=True, help="Exact existing local Git checkout root")
    command.add_argument("--base", required=True, help="Exact 40-character base commit SHA")
    command.add_argument("--target", required=True, help="Exact 40-character target commit SHA")
    command.add_argument("--bundle-manifest", help="Optional already published bundle manifest")
    command.add_argument("--use-case", choices=USE_CASES, default="explain-change")
    command.add_argument("--budget-tokens", type=int, default=1200)
    command.add_argument("--expected-diff-sha256", help="Optional caller-bound SHA-256 of Git diff")
    command.add_argument("--emit", choices=("json", "markdown"), default="markdown")


def run_agent_evidence(args: argparse.Namespace) -> int:
    pack = build_evidence_pack(
        repo_root=args.repo_root,
        base_revision=args.base,
        target_revision=args.target,
        bundle_manifest=args.bundle_manifest,
        use_case=args.use_case,
        context_budget_tokens=args.budget_tokens,
        expected_diff_sha256=args.expected_diff_sha256,
    )
    if args.emit == "json":
        print(json.dumps(pack, ensure_ascii=False, sort_keys=True, indent=2))
    else:
        print(render_evidence_markdown(pack), end="")
    return 2 if pack["status"] == "invalid" else 0
