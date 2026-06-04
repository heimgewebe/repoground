"""Tests for the bounded repo-sync mutation (fast-forward-only pre-pull).

These use *real* temporary git repositories (bare remote + two clones) rather
than mocks, so the fast-forward / divergence / dirty semantics are exercised by
git itself. One test additionally monkeypatches ``subprocess.run`` to assert the
non-interactive environment without needing a real remote.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from merger.lenskit.service import repo_sync
from merger.lenskit.service.repo_sync import PrePullStatus, pre_pull_repo


# --- git helpers (hermetic identity / config) ------------------------------

def _git_env() -> dict:
    env = dict(os.environ)
    env.update(
        {
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@example.com",
            # Isolate from any host git config (signing, hooks, url rewrites).
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
        }
    )
    return env


def _git(*args: str, cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        env=_git_env(),
    )
    if check and proc.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed in {cwd}: {proc.stderr}")
    return proc


def _commit_file(repo: Path, name: str, content: str, message: str) -> None:
    (repo / name).write_text(content, encoding="utf-8")
    _git("add", name, cwd=repo)
    _git("commit", "-m", message, cwd=repo)


def _head(repo: Path) -> str:
    return _git("rev-parse", "HEAD", cwd=repo).stdout.strip()


@pytest.fixture
def repos(tmp_path: Path):
    """Create a bare remote with one commit and a tracking clone ('local')."""
    remote = tmp_path / "remote.git"
    _git("init", "--bare", "-b", "main", str(remote), cwd=tmp_path)

    source = tmp_path / "source"
    _git("init", "-b", "main", str(source), cwd=tmp_path)
    _commit_file(source, "file.txt", "v1\n", "init")
    _git("remote", "add", "origin", str(remote), cwd=source)
    _git("push", "-u", "origin", "main", cwd=source)

    local = tmp_path / "local"
    _git("clone", "-b", "main", str(remote), str(local), cwd=tmp_path)

    return {"remote": remote, "source": source, "local": local, "tmp": tmp_path}


# --- skip / warn-and-continue cases ----------------------------------------

def test_pre_pull_skips_non_git_repo(tmp_path: Path):
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "readme.txt").write_text("not a repo", encoding="utf-8")

    result = pre_pull_repo(plain)

    assert result.status == PrePullStatus.SKIPPED_NOT_GIT
    assert result.changed is False


def test_pre_pull_skips_repo_without_upstream(tmp_path: Path):
    repo = tmp_path / "norem"
    _git("init", "-b", "main", str(repo), cwd=tmp_path)
    _commit_file(repo, "a.txt", "x\n", "init")

    result = pre_pull_repo(repo)

    assert result.status == PrePullStatus.SKIPPED_NO_UPSTREAM
    assert result.changed is False
    assert result.before_head == _head(repo)


def test_pre_pull_reports_local_ahead(repos):
    local = repos["local"]
    _commit_file(local, "local_only.txt", "ahead\n", "local commit")
    before = _head(local)

    result = pre_pull_repo(local)

    assert result.status == PrePullStatus.LOCAL_AHEAD
    assert result.changed is False
    # No merge happened; HEAD is unchanged.
    assert _head(local) == before


# --- hard-fail cases --------------------------------------------------------

def test_pre_pull_blocks_dirty_tracked_tree(repos):
    local = repos["local"]
    # Modify a *tracked* file without committing.
    (local / "file.txt").write_text("locally modified\n", encoding="utf-8")
    before = _head(local)

    result = pre_pull_repo(local)

    assert result.status == PrePullStatus.DIRTY
    assert result.changed is False
    # The working tree must be left untouched.
    assert (local / "file.txt").read_text(encoding="utf-8") == "locally modified\n"
    assert _head(local) == before


def test_pre_pull_blocks_diverged_branch(repos):
    source, local = repos["source"], repos["local"]
    # Upstream advances.
    _commit_file(source, "remote.txt", "r\n", "remote commit")
    _git("push", "origin", "main", cwd=source)
    # Local advances on its own (no pull) → divergence.
    _commit_file(local, "mine.txt", "m\n", "local commit")
    before = _head(local)

    result = pre_pull_repo(local)

    assert result.status == PrePullStatus.DIVERGED
    assert result.changed is False
    assert _head(local) == before


def test_pre_pull_fetch_failure_fails(repos):
    local = repos["local"]
    # Point origin at a path that does not exist → fetch fails fast (no prompt).
    missing = repos["tmp"] / "does-not-exist.git"
    _git("remote", "set-url", "origin", str(missing), cwd=local)

    result = pre_pull_repo(local)

    assert result.status == PrePullStatus.FETCH_FAILED
    assert result.changed is False


# --- success cases ----------------------------------------------------------

def test_pre_pull_reports_up_to_date(repos):
    local = repos["local"]
    before = _head(local)

    result = pre_pull_repo(local)

    assert result.status == PrePullStatus.UP_TO_DATE
    assert result.changed is False
    assert result.before_head == before
    assert result.after_head == before


def test_pre_pull_fast_forwards_clean_repo(repos):
    source, local = repos["source"], repos["local"]
    before = _head(local)
    # Upstream advances; local is clean and strictly behind.
    _commit_file(source, "file.txt", "v2\n", "second")
    _git("push", "origin", "main", cwd=source)
    expected_head = _head(source)

    result = pre_pull_repo(local)

    assert result.status == PrePullStatus.FAST_FORWARDED
    assert result.changed is True
    assert result.before_head == before
    assert result.after_head == expected_head
    assert _head(local) == expected_head
    # The fast-forwarded content is now present on disk.
    assert (local / "file.txt").read_text(encoding="utf-8") == "v2\n"


def test_pre_pull_allows_untracked_files(repos):
    source, local = repos["source"], repos["local"]
    # An untracked file must NOT block, and must survive a fast-forward.
    (local / "scratch.tmp").write_text("untracked\n", encoding="utf-8")
    _commit_file(source, "file.txt", "v2\n", "second")
    _git("push", "origin", "main", cwd=source)

    result = pre_pull_repo(local)

    assert result.status == PrePullStatus.FAST_FORWARDED
    assert (local / "scratch.tmp").read_text(encoding="utf-8") == "untracked\n"


def test_pre_pull_allows_untracked_files_up_to_date(repos):
    """Untracked-only changes on an up-to-date repo are not 'dirty'."""
    local = repos["local"]
    (local / "scratch.tmp").write_text("untracked\n", encoding="utf-8")

    result = pre_pull_repo(local)

    assert result.status == PrePullStatus.UP_TO_DATE
    assert (local / "scratch.tmp").exists()


# --- non-interactive environment -------------------------------------------

def test_pre_pull_uses_non_interactive_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Every git invocation must carry GIT_TERMINAL_PROMPT=0 and use an arg list."""
    seen_envs = []
    seen_cmds = []
    real_run = subprocess.run

    def fake_run(cmd, *args, **kwargs):
        seen_cmds.append(cmd)
        seen_envs.append(kwargs.get("env") or {})
        # shell=True is forbidden for these git calls.
        assert kwargs.get("shell", False) is False
        assert isinstance(cmd, (list, tuple))
        # Let the real `git --version` through; short-circuit the rest as non-git.
        if list(cmd[:2]) == ["git", "--version"]:
            return real_run(cmd, *args, **kwargs)
        return subprocess.CompletedProcess(cmd, 0, stdout="false\n", stderr="")

    monkeypatch.setattr(repo_sync.subprocess, "run", fake_run)

    result = pre_pull_repo(tmp_path)

    assert result.status == PrePullStatus.SKIPPED_NOT_GIT
    assert seen_envs, "expected at least one git subprocess call"
    for env in seen_envs:
        assert env.get("GIT_TERMINAL_PROMPT") == "0"
    # No forbidden subcommands were ever issued.
    forbidden = {"pull", "reset", "rebase", "stash", "checkout", "switch", "clean"}
    for cmd in seen_cmds:
        assert forbidden.isdisjoint(set(cmd)), f"forbidden git op in {cmd}"
