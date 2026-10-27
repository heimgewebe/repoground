"""Read-only, commit-addressed history tests using real Git commits in a disposable repo."""
from pathlib import Path
import subprocess

import pytest

from merger.repoground.core.history_lens import (
    bind_external_history,
    git_path_history,
    git_revision_delta,
    git_revision_view,
)


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


def create_repo(tmp_path: Path) -> tuple[Path, list[str]]:
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "user.name", "RepoGround fixture")
    git(root, "config", "user.email", "fixture@localhost")
    commits = []
    (root / "module.py").write_text("def first():\n    return 1\n", encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-qm", "real first Git commit")
    commits.append(git(root, "rev-parse", "HEAD"))

    (root / "module.py").write_text("def first():\n    return 1\n\ndef second():\n    return 2\n", encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-qm", "real second Git commit")
    commits.append(git(root, "rev-parse", "HEAD"))

    (root / "module.py").write_text("def third():\n    return 3\n", encoding="utf-8")
    (root / "contracts").mkdir()
    (root / "contracts" / "rule.schema.json").write_text('{"type":"object"}\n', encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-qm", "real third Git commit")
    commits.append(git(root, "rev-parse", "HEAD"))
    return root, commits


def test_three_real_git_commits_and_determinism(tmp_path):
    repo, commits = create_repo(tmp_path)
    a, b, c = commits
    before = git_revision_view(repo, "fixture", a)
    middle = git_revision_view(repo, "fixture", b)
    after = git_revision_view(repo, "fixture", c)
    assert (before["source_commit"], middle["source_commit"], after["source_commit"]) == (a, b, c)
    assert [x["path"] for x in after["artifacts"]] == ["contracts/rule.schema.json", "module.py"]
    delta = git_revision_delta(repo, "fixture", a, c)
    assert delta == git_revision_delta(repo, "fixture", a, c)
    assert delta["status"] == "ok"
    assert [(x["path"], x["action"]) for x in delta["file_changes"]] == [
        ("contracts/rule.schema.json", "added"), ("module.py", "modified")
    ]
    assert delta["file_changes"][0]["artifact_type"] == "contract"
    assert delta["python_symbol_changes"][0]["added"] == ["third"]
    assert delta["python_symbol_changes"][0]["removed"] == ["first"]
    assert delta["observation_time"] is None
    assert not (repo / "snapshot.json").exists()


def test_history_events_only_bound_to_explicit_git_path(tmp_path):
    repo, commits = create_repo(tmp_path)
    a, b, c = commits
    history = git_path_history(repo, "fixture", c, "module.py")
    assert [x["commit"] for x in history["history"]] == [c, b, a]
    records = [
        {"repo_id": "fixture", "commit": c, "event_kind": "ci",
         "evidence_ref": "https://github.com/heimgewebe/repo/actions/runs/42",
         "event_time": "2026-10-27T10:00:00Z"},
        {"repo_id": "fixture", "commit": a, "event_kind": "pr", "evidence_ref": "github:pull/3"},
        {"repo_id": "elsewhere", "commit": c, "event_kind": "pr", "evidence_ref": "github:pull/4"},
        {"repo_id": "fixture", "commit": "f" * 40, "event_kind": "ci", "evidence_ref": "ci:run/5"},
        {"repo_id": "fixture", "commit": c, "event_kind": "ci", "evidence_ref": "https://github.com/?token=secret"},
    ]
    bound = bind_external_history(repo, "fixture", c, records, path="module.py")
    assert bound["status"] == "partial"
    assert {(x["event_kind"], x["relation"]) for x in bound["events"]} == {
        ("ci", "exact_commit"), ("pr", "same_path_history")
    }
    assert all("token" not in str(x) for x in bound["events"])
    assert "event_repo_mismatch" in bound["gaps"]
    assert "event_sha_outside_explicit_history" in bound["gaps"]
    assert "event_evidence_ref_rejected" in bound["gaps"]
    assert bind_external_history(repo, "fixture", c, [], path="module.py")["status"] == "unavailable"


@pytest.mark.parametrize("bad", ["HEAD", "0" * 40, "../secrets", "a" * 7])
def test_unknown_and_unacceptable_commits_fail_closed(tmp_path, bad):
    repo, commits = create_repo(tmp_path)
    with pytest.raises(ValueError):
        git_revision_view(repo, "fixture", bad)
    with pytest.raises(ValueError):
        git_revision_delta(repo, "fixture", bad, commits[-1])


def test_path_traversal_rejected_and_non_regular_entries_not_followed(tmp_path):
    repo, commits = create_repo(tmp_path)
    with pytest.raises(ValueError, match="safe relative"):
        git_path_history(repo, "fixture", commits[-1], "../something")
    external = tmp_path / "private.txt"
    external.write_text("NEVER_EXPOSE_ME", encoding="utf-8")
    (repo / "linked-secret").symlink_to(external)
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "symlink is only a git object")
    result = git_revision_view(repo, "fixture", git(repo, "rev-parse", "HEAD"))
    assert result["status"] == "partial"
    assert "linked-secret" not in [x["path"] for x in result["artifacts"]]
    assert "NEVER_EXPOSE_ME" not in str(result)
