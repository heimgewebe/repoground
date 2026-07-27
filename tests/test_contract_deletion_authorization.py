from __future__ import annotations

import json
import subprocess
from pathlib import Path
from urllib.error import URLError
from urllib.parse import parse_qs, urlsplit

import pytest

import scripts.ci.check_contract_deletion_authorization as authorization
from scripts.ci.check_contract_deletion_authorization import (
    authorization_present,
    fetch_paginated_json,
    main,
    resolve_associated_pr,
)

MARKER = (
    "/authorize-contract-removal pr=1110 "
    "base=8ec3c7d2a5d04b3df63d52c5cf5eb16b725e418c "
    "head=0123456789abcdef0123456789abcdef01234567 "
    "paths_sha256=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
)
COMMIT = "0123456789abcdef0123456789abcdef01234567"
BASE = "8ec3c7d2a5d04b3df63d52c5cf5eb16b725e418c"


def trusted_comment(*, body: str = MARKER) -> dict[str, object]:
    return {
        "author_association": "MEMBER",
        "body": body,
        "user": {"login": "alexdermohr", "type": "User"},
    }


def _guard_shell_script() -> str:
    workflow = Path(".github/workflows/contracts-validate.yml").read_text(
        encoding="utf-8"
    )
    marker = "      - name: Enforce guard policy\n        run: |\n"
    start = workflow.index(marker) + len(marker)
    lines: list[str] = []
    for line in workflow[start:].splitlines():
        if line and not line.startswith("          "):
            break
        lines.append(line[10:] if line else "")
    return "\n".join(lines) + "\n"


def test_guard_embedded_shell_is_valid_bash() -> None:
    result = subprocess.run(
        ["bash", "-n"],
        input=_guard_shell_script(),
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_authorization_requires_exact_trusted_human_marker() -> None:
    assert authorization_present([trusted_comment()], marker=MARKER)


@pytest.mark.parametrize(
    "comment",
    [
        {
            "author_association": "CONTRIBUTOR",
            "body": MARKER,
            "user": {"login": "someone-else", "type": "User"},
        },
        {
            "author_association": "MEMBER",
            "body": MARKER,
            "user": {"login": "automation[bot]", "type": "Bot"},
        },
        trusted_comment(body=MARKER.replace("pr=1110", "pr=1111")),
        trusted_comment(body=f"approved: {MARKER}"),
    ],
)
def test_authorization_rejects_nonexact_or_untrusted_evidence(
    comment: dict[str, object],
) -> None:
    assert not authorization_present([comment], marker=MARKER)


def test_authorization_rejects_non_array_payload() -> None:
    with pytest.raises(ValueError, match="JSON array"):
        authorization_present({}, marker=MARKER)


def test_resolve_associated_pr_accepts_open_pr_head_commit() -> None:
    payload = [
        {
            "number": 1110,
            "head": {"sha": COMMIT},
            "base": {"sha": BASE},
            "merge_commit_sha": None,
        }
    ]
    assert resolve_associated_pr(payload, commit_sha=COMMIT) == (1110, COMMIT, BASE)


def test_resolve_associated_pr_accepts_merged_commit() -> None:
    merge_commit = "f" * 40
    payload = [
        {
            "number": 1110,
            "head": {"sha": COMMIT},
            "base": {"sha": BASE},
            "merge_commit_sha": merge_commit,
        }
    ]
    assert resolve_associated_pr(payload, commit_sha=merge_commit) == (
        1110,
        COMMIT,
        BASE,
    )


def test_resolve_associated_pr_fails_closed_for_ambiguity() -> None:
    payload = [
        {
            "number": number,
            "head": {"sha": COMMIT},
            "base": {"sha": BASE},
            "merge_commit_sha": None,
        }
        for number in (1110, 1111)
    ]
    with pytest.raises(ValueError, match="exactly one"):
        resolve_associated_pr(payload, commit_sha=COMMIT)


def test_cli_fails_closed_for_invalid_json(tmp_path, capsys) -> None:
    comments = tmp_path / "comments.json"
    comments.write_text("not-json", encoding="utf-8")
    result = main(
        [
            "verify-comments",
            "--comments",
            str(comments),
            "--marker",
            MARKER,
        ]
    )
    assert result == 2
    assert "invalid authorization evidence" in capsys.readouterr().err


def test_cli_accepts_exact_comment(tmp_path) -> None:
    comments = tmp_path / "comments.json"
    comments.write_text(json.dumps([trusted_comment()]), encoding="utf-8")
    assert (
        main(
            [
                "verify-comments",
                "--comments",
                str(comments),
                "--marker",
                MARKER,
            ]
        )
        == 0
    )


class _FakeResponse:
    def __init__(self, payload: object) -> None:
        self.raw = json.dumps(payload).encode("utf-8")

    def read(self, limit: int = -1) -> bytes:
        return self.raw if limit < 0 else self.raw[:limit]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        return False


def _paginated_opener(pages: dict[int, object]):
    def opener(request, *, timeout: int):
        assert timeout == authorization.HTTP_TIMEOUT_SECONDS
        query = parse_qs(urlsplit(request.full_url).query)
        assert query["per_page"] == [str(authorization.PAGE_SIZE)]
        page = int(query["page"][0])
        return _FakeResponse(pages.get(page, []))

    return opener


def test_paginated_fetch_reads_authorization_on_second_page() -> None:
    first_page = [{"body": f"discussion-{index}"} for index in range(100)]
    comments = fetch_paginated_json(
        "https://api.github.com/repos/heimgewebe/repoground/issues/1110/comments",
        token="secret",
        opener=_paginated_opener({1: first_page, 2: [trusted_comment()]}),
    )
    assert len(comments) == 101
    assert authorization_present(comments, marker=MARKER)


def test_paginated_fetch_accepts_exact_cap_only_after_empty_sentinel() -> None:
    comments = fetch_paginated_json(
        "https://api.github.com/repos/heimgewebe/repoground/issues/1110/comments",
        token="secret",
        max_pages=1,
        opener=_paginated_opener({1: [{} for _ in range(100)], 2: []}),
    )
    assert len(comments) == 100


def test_paginated_fetch_fails_closed_beyond_cap() -> None:
    with pytest.raises(ValueError, match="exceeds the 1-page limit"):
        fetch_paginated_json(
            "https://api.github.com/repos/heimgewebe/repoground/issues/1110/comments",
            token="secret",
            max_pages=1,
            opener=_paginated_opener({1: [{} for _ in range(100)], 2: [{}]}),
        )


def test_paginated_fetch_rejects_non_github_api_url() -> None:
    with pytest.raises(ValueError, match="https://api.github.com"):
        fetch_paginated_json(
            "https://example.invalid/comments",
            token="secret",
            opener=_paginated_opener({}),
        )


def test_paginated_fetch_fails_closed_on_request_error() -> None:
    def failing_opener(request, *, timeout: int):
        raise URLError("offline")

    with pytest.raises(ValueError, match="page 1 could not be read"):
        fetch_paginated_json(
            "https://api.github.com/repos/heimgewebe/repoground/issues/1110/comments",
            token="secret",
            opener=failing_opener,
        )


def test_cli_accepts_authorization_from_second_comment_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "secret")
    monkeypatch.setattr(
        authorization,
        "urlopen",
        _paginated_opener(
            {
                1: [{"body": f"discussion-{index}"} for index in range(100)],
                2: [trusted_comment()],
            }
        ),
    )
    assert (
        main(
            [
                "verify-comments",
                "--comments-url",
                "https://api.github.com/repos/heimgewebe/repoground/issues/1110/comments",
                "--marker",
                MARKER,
            ]
        )
        == 0
    )


def test_cli_resolves_associated_pr_from_second_page(
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "secret")
    target = {
        "number": 1110,
        "head": {"sha": COMMIT},
        "base": {"sha": BASE},
        "merge_commit_sha": None,
    }
    monkeypatch.setattr(
        authorization,
        "urlopen",
        _paginated_opener({1: [{} for _ in range(100)], 2: [target]}),
    )
    assert (
        main(
            [
                "resolve-push-pr",
                "--pull-requests-url",
                "https://api.github.com/repos/heimgewebe/repoground/commits/commit/pulls",
                "--commit-sha",
                COMMIT,
            ]
        )
        == 0
    )
    assert capsys.readouterr().out.strip() == f"1110 {COMMIT} {BASE}"



def test_paginated_fetch_rejects_oversized_item_page() -> None:
    with pytest.raises(ValueError, match="page 1 exceeds the item limit"):
        fetch_paginated_json(
            "https://api.github.com/repos/heimgewebe/repoground/issues/1110/comments",
            token="secret",
            opener=_paginated_opener({1: [{} for _ in range(101)]}),
        )


def test_cli_url_source_requires_github_token(
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert (
        main(
            [
                "verify-comments",
                "--comments-url",
                "https://api.github.com/repos/heimgewebe/repoground/issues/1110/comments",
                "--marker",
                MARKER,
            ]
        )
        == 2
    )
    assert "GitHub token is missing" in capsys.readouterr().err
