from __future__ import annotations

import json

import pytest

from scripts.ci.check_contract_deletion_authorization import (
    authorization_present,
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
