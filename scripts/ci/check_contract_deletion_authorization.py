#!/usr/bin/env python3
"""Resolve and verify exact GitHub authorization for protected deletions."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable
from urllib.error import URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

TRUSTED_ASSOCIATIONS = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})
GITHUB_API_HOST = "api.github.com"
PAGE_SIZE = 100
DEFAULT_MAX_PAGES = 20
MAX_PAGE_BYTES = 8 * 1024 * 1024
HTTP_TIMEOUT_SECONDS = 20


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


def _github_page_url(url: str, *, page: int) -> str:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc != GITHUB_API_HOST:
        raise ValueError("GitHub API URL must use https://api.github.com")
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key not in {"page", "per_page"}
    ]
    query.extend((("per_page", str(PAGE_SIZE)), ("page", str(page))))
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment)
    )


def fetch_paginated_json(
    url: str,
    *,
    token: str,
    max_pages: int = DEFAULT_MAX_PAGES,
    opener: Callable[..., Any] | None = None,
) -> list[Any]:
    """Fetch every GitHub API page, failing closed at explicit bounds."""
    if not token:
        raise ValueError("GitHub token is missing")
    if not 1 <= max_pages <= 100:
        raise ValueError("max_pages must be between 1 and 100")
    open_request = opener or urlopen
    collected: list[Any] = []

    for page in range(1, max_pages + 2):
        request = Request(
            _github_page_url(url, page=page),
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with open_request(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
                raw = response.read(MAX_PAGE_BYTES + 1)
        except (OSError, URLError) as exc:
            raise ValueError(f"GitHub API page {page} could not be read") from exc
        if len(raw) > MAX_PAGE_BYTES:
            raise ValueError(f"GitHub API page {page} exceeds the byte limit")
        try:
            payload = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"GitHub API page {page} is not valid JSON") from exc
        if not isinstance(payload, list):
            raise ValueError(f"GitHub API page {page} must be a JSON array")
        if len(payload) > PAGE_SIZE:
            raise ValueError(f"GitHub API page {page} exceeds the item limit")

        if page > max_pages:
            if payload:
                raise ValueError(
                    f"GitHub API pagination exceeds the {max_pages}-page limit"
                )
            break

        collected.extend(payload)
        if len(payload) < PAGE_SIZE:
            break

    return collected


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_evidence(
    *,
    path: Path | None,
    url: str | None,
    max_pages: int,
) -> Any:
    if path is not None:
        return _load_json(path)
    if url is None:
        raise ValueError("evidence source is missing")
    return fetch_paginated_json(
        url,
        token=os.environ.get("GITHUB_TOKEN", ""),
        max_pages=max_pages,
    )


def _add_evidence_source(
    parser: argparse.ArgumentParser,
    *,
    path_option: str,
    url_option: str,
) -> None:
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(path_option, type=Path)
    source.add_argument(url_option)
    parser.add_argument("--max-pages", type=int, default=DEFAULT_MAX_PAGES)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    verify = subparsers.add_parser("verify-comments")
    _add_evidence_source(
        verify,
        path_option="--comments",
        url_option="--comments-url",
    )
    verify.add_argument("--marker", required=True)

    resolve = subparsers.add_parser("resolve-push-pr")
    _add_evidence_source(
        resolve,
        path_option="--pull-requests",
        url_option="--pull-requests-url",
    )
    resolve.add_argument("--commit-sha", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "verify-comments":
            comments = _load_evidence(
                path=args.comments,
                url=args.comments_url,
                max_pages=args.max_pages,
            )
            if not authorization_present(comments, marker=args.marker):
                print(
                    "no exact trusted-human authorization comment found",
                    file=sys.stderr,
                )
                return 1
            print("exact trusted-human authorization comment verified")
            return 0

        pull_requests = _load_evidence(
            path=args.pull_requests,
            url=args.pull_requests_url,
            max_pages=args.max_pages,
        )
        number, head_sha, base_sha = resolve_associated_pr(
            pull_requests,
            commit_sha=args.commit_sha,
        )
        print(number, head_sha, base_sha)
        return 0
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"invalid authorization evidence: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
