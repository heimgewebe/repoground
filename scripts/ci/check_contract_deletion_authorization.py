#!/usr/bin/env python3
"""Resolve and verify exact GitHub authorization for protected deletions."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

TRUSTED_ASSOCIATIONS = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})


def authorization_present(comments: Any, *, marker: str) -> bool:
    """Return true only for one exact marker from a trusted human collaborator."""
    if not isinstance(comments, list):
        raise ValueError("GitHub comments payload must be a JSON array")
    if not marker:
        raise ValueError("marker must be non-empty")

    for comment in comments:
        if not isinstance(comment, dict):
            continue
        user = comment.get("user")
        body = comment.get("body")
        association = comment.get("author_association")
        if not isinstance(user, dict) or not isinstance(body, str):
            continue
        if user.get("type") != "User":
            continue
        if association not in TRUSTED_ASSOCIATIONS:
            continue
        if body.strip() == marker:
            return True
    return False


def _candidate_for_pull_request(
    pull_request: Any,
    *,
    commit_sha: str,
) -> tuple[int, str, str] | None:
    if not isinstance(pull_request, dict):
        return None
    number = pull_request.get("number")
    head = pull_request.get("head")
    base = pull_request.get("base")
    if not isinstance(number, int) or number < 1:
        return None
    if not isinstance(head, dict) or not isinstance(base, dict):
        return None

    head_sha = head.get("sha")
    base_sha = base.get("sha")
    if not isinstance(head_sha, str) or len(head_sha) != 40:
        return None
    if not isinstance(base_sha, str) or len(base_sha) != 40:
        return None
    if head_sha != commit_sha and pull_request.get("merge_commit_sha") != commit_sha:
        return None
    return number, head_sha, base_sha


def resolve_associated_pr(
    pull_requests: Any,
    *,
    commit_sha: str,
) -> tuple[int, str, str]:
    """Resolve one PR whose head or merge commit is the observed push commit."""
    if not isinstance(pull_requests, list):
        raise ValueError("associated pull requests payload must be a JSON array")
    if len(commit_sha) != 40:
        raise ValueError("commit SHA must contain 40 characters")

    candidates = {
        candidate
        for pull_request in pull_requests
        if (
            candidate := _candidate_for_pull_request(
                pull_request,
                commit_sha=commit_sha,
            )
        )
        is not None
    }
    if len(candidates) != 1:
        raise ValueError(
            "expected exactly one associated pull request for commit, "
            f"found {len(candidates)}"
        )
    return next(iter(candidates))


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    verify = subparsers.add_parser("verify-comments")
    verify.add_argument("--comments", type=Path, required=True)
    verify.add_argument("--marker", required=True)

    resolve = subparsers.add_parser("resolve-push-pr")
    resolve.add_argument("--pull-requests", type=Path, required=True)
    resolve.add_argument("--commit-sha", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "verify-comments":
            if not authorization_present(_load_json(args.comments), marker=args.marker):
                print(
                    "no exact trusted-human authorization comment found",
                    file=sys.stderr,
                )
                return 1
            print("exact trusted-human authorization comment verified")
            return 0

        number, head_sha, base_sha = resolve_associated_pr(
            _load_json(args.pull_requests),
            commit_sha=args.commit_sha,
        )
        print(number, head_sha, base_sha)
        return 0
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"invalid authorization evidence: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
