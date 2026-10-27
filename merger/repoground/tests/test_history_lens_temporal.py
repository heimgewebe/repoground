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


def test_incomplete_git_tree_does_not_claim_additions_or_deletions(tmp_path, monkeypatch):
    from merger.repoground.core import history_lens

    repo, commits = create_repo(tmp_path)
    original = history_lens._git_tree

    def incomplete(root, sha):
        tree, _ = original(root, sha)
        # Simulate an unseen suffix; no missing entry is proven absent.
        return tree, True

    monkeypatch.setattr(history_lens, "_git_tree", incomplete)
    output = git_revision_delta(repo, "fixture", commits[0], commits[-1])
    assert output["status"] == "partial"
    assert output["changed_files_observed"] is None
    assert output["file_changes"] == []
    assert output["python_symbol_changes"] == []
    assert "git_tree_incomplete_delta_omitted" in output["gaps"]
    assert "absence_of_changes" in output["does_not_establish"]


def test_executable_mode_only_change_is_reported_without_blob_delta(tmp_path):
    import os

    repo, commits = create_repo(tmp_path)
    script = repo / "script.sh"
    script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    script.chmod(0o644)
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "non-executable script")
    before = git(repo, "rev-parse", "HEAD")

    script.chmod(0o755)
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "make script executable")
    after = git(repo, "rev-parse", "HEAD")
    result = git_revision_delta(repo, "fixture", before, after)
    changes = [entry for entry in result["file_changes"] if entry["path"] == "script.sh"]
    assert result["status"] == "ok"
    assert len(changes) == 1
    change = changes[0]
    assert change["action"] == "modified"
    assert change["before_blob_oid"] == change["after_blob_oid"]
    assert change["before_mode"] == "100644"
    assert change["after_mode"] == "100755"
    assert change["evidence_type"] == "git_tree_mode_comparison"
    assert [entry for entry in result["python_symbol_changes"] if entry["path"] == "script.sh"] == []
    assert git_revision_view(repo, "fixture", after)["artifacts"][-1]["mode"] == "100755"
    assert os.stat(script).st_mode & 0o111


def test_literal_git_filename_does_not_link_glob_match_history(tmp_path):
    repo, commits = create_repo(tmp_path)
    (repo / "a[1].py").write_text("VALUE = 1\n", encoding="utf-8")
    (repo / "a1.py").write_text("VALUE = 1\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "create literal-bracket and glob-matched files")
    literal_created = git(repo, "rev-parse", "HEAD")

    (repo / "a1.py").write_text("VALUE = 2\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "edit only unrelated glob-matched filename")
    unrelated_sha = git(repo, "rev-parse", "HEAD")

    (repo / "module.py").write_text("VALUE = 3\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "another unrelated edit")
    current = git(repo, "rev-parse", "HEAD")

    history = git_path_history(repo, "fixture", current, "a[1].py")
    assert [entry["commit"] for entry in history["history"]] == [literal_created]
    linked = bind_external_history(repo, "fixture", current, [{
        "repo_id": "fixture", "commit": unrelated_sha, "event_kind": "ci",
        "evidence_ref": "ci:unrelated/123",
    }], path="a[1].py")
    assert linked["events"] == []
    assert "event_sha_outside_explicit_history" in linked["gaps"]


def test_git_reader_explicitly_disables_lazy_fetch_and_pathspec_magic(tmp_path, monkeypatch):
    from merger.repoground.core import history_lens

    repo, commits = create_repo(tmp_path)
    original = history_lens.subprocess.run
    observed: list[tuple[str, str]] = []

    def instrumented(*args, **kwargs):
        env = kwargs["env"]
        observed.append((env.get("GIT_NO_LAZY_FETCH"), env.get("GIT_LITERAL_PATHSPECS")))
        return original(*args, **kwargs)

    monkeypatch.setattr(history_lens.subprocess, "run", instrumented)
    git_revision_delta(repo, "fixture", commits[0], commits[-1])
    assert observed
    assert set(observed) == {("1", "1")}


def test_missing_partial_clone_blobs_do_not_trigger_fetch(tmp_path):
    import os

    source_parent = tmp_path / "source"
    source_parent.mkdir()
    source, commits = create_repo(source_parent)
    git(source, "config", "uploadpack.allowFilter", "true")
    clone = tmp_path / "partial"
    subprocess.run([
        "git", "-c", "protocol.file.allow=always", "clone", "--quiet",
        "--filter=blob:none", "--no-checkout", source.as_uri(), str(clone),
    ], check=True, capture_output=True)
    assert clone.is_dir()
    # Confirm the test actually contains promisor objects, rather than an
    # ordinary full clone where this safety guarantee would be untested.
    promisor = list((clone / ".git" / "objects" / "pack").glob("*.promisor"))
    assert promisor
    before = sorted(p.name for p in (clone / ".git" / "objects" / "pack").iterdir())
    # A non-existent remote makes any accidental read-side lazy fetch fail
    # loudly rather than loading new objects from the producer.
    git(clone, "remote", "set-url", "origin", "file:///nonexistent/repoground-promisor")
    result = git_revision_delta(clone, "fixture", commits[0], commits[-1])
    after = sorted(p.name for p in (clone / ".git" / "objects" / "pack").iterdir())
    assert result["status"] == "partial"
    assert before == after
    assert any(item.startswith("python_ast_unavailable:") for item in result["gaps"])
    assert os.path.isdir(clone / ".git" / "objects")


def test_more_than_thousand_python_symbols_is_partial_not_false_removal(tmp_path):
    repo, _ = create_repo(tmp_path)
    symbols = repo / "symbols.py"
    existing = "".join(f"def f{i:04d}():\n    pass\n" for i in range(1001))
    symbols.write_text(existing, encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "1011? no: 1001 actual top-level function names")
    before = git(repo, "rev-parse", "HEAD")

    symbols.write_text("def a():\n    pass\n" + existing, encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "insert earlier-sorting name before 1001 functions")
    after = git(repo, "rev-parse", "HEAD")
    delta = git_revision_delta(repo, "fixture", before, after)
    assert delta["status"] == "partial"
    assert delta["changed_files_observed"] == 1
    assert delta["file_changes"][0]["path"] == "symbols.py"
    assert delta["python_symbol_changes"] == []
    assert "python_ast_unavailable:symbols.py" in delta["gaps"]
    assert delta == git_revision_delta(repo, "fixture", before, after)


def test_deep_python_ast_is_partial_instead_of_crashing_delta(tmp_path):
    repo, _ = create_repo(tmp_path)
    source = repo / "deep.py"
    source.write_text("value = 0\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "simple AST")
    before = git(repo, "rev-parse", "HEAD")
    source.write_text("value = " + " + ".join(["1"] * 1200) + "\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "deep but short AST")
    after = git(repo, "rev-parse", "HEAD")
    result = git_revision_delta(repo, "fixture", before, after)
    assert result["status"] == "partial"
    assert len(result["file_changes"]) == 1
    assert result["file_changes"][0]["path"] == "deep.py"
    assert result["python_symbol_changes"] == []
    assert "python_ast_unavailable:deep.py" in result["gaps"]
