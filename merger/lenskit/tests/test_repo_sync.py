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
from merger.lenskit.service.repo_sync import (
    PrePullStatus,
    pre_pull_repo,
    plan_pre_pull_repo,
    apply_pre_pull_plan,
    plan_pre_pull_repos,
    HARD_FAIL_STATUSES,
)


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


# --- two-phase plan / apply ------------------------------------------------

def test_plan_pre_pull_repo_returns_planned_fast_forward_without_merging(repos):
    source, local = repos["source"], repos["local"]
    before = _head(local)
    _commit_file(source, "file.txt", "v2\n", "second")
    _git("push", "origin", "main", cwd=source)

    plan = plan_pre_pull_repo(local)

    assert plan.status == PrePullStatus.PLANNED_FAST_FORWARD
    assert plan.needs_apply is True
    assert plan.before_head == before
    # The plan phase must NOT mutate the working tree (no merge yet).
    assert _head(local) == before
    assert (local / "file.txt").read_text(encoding="utf-8") == "v1\n"


def test_apply_pre_pull_plan_fast_forwards(repos):
    source, local = repos["source"], repos["local"]
    before = _head(local)
    _commit_file(source, "file.txt", "v2\n", "second")
    _git("push", "origin", "main", cwd=source)
    expected = _head(source)

    plan = plan_pre_pull_repo(local)
    result = apply_pre_pull_plan(plan)

    assert result.status == PrePullStatus.FAST_FORWARDED
    assert result.changed is True
    assert result.before_head == before
    assert result.after_head == expected
    assert _head(local) == expected


def test_apply_pre_pull_plan_detects_head_race(repos):
    source, local = repos["source"], repos["local"]
    _commit_file(source, "file.txt", "v2\n", "second")
    _git("push", "origin", "main", cwd=source)

    plan = plan_pre_pull_repo(local)
    assert plan.status == PrePullStatus.PLANNED_FAST_FORWARD

    # HEAD moves locally between plan and apply (concurrent commit) → race.
    _commit_file(local, "local.txt", "race\n", "local race commit")
    raced_head = _head(local)

    result = apply_pre_pull_plan(plan)

    assert result.status == PrePullStatus.HEAD_CHANGED
    assert result.changed is False
    # The planned fast-forward was refused; local HEAD is the racing commit, untouched.
    assert _head(local) == raced_head


def test_plan_pre_pull_dirty_returns_hard_fail_without_mutation(repos):
    local = repos["local"]
    (local / "file.txt").write_text("dirty\n", encoding="utf-8")
    before = _head(local)

    plan = plan_pre_pull_repo(local)

    assert plan.status == PrePullStatus.DIRTY
    assert plan.needs_apply is False
    assert _head(local) == before
    assert (local / "file.txt").read_text(encoding="utf-8") == "dirty\n"


def test_pre_pull_repo_single_repo_still_fast_forwards(repos):
    """The single-repo convenience wrapper still plans+applies in one call."""
    source, local = repos["source"], repos["local"]
    _commit_file(source, "file.txt", "v2\n", "second")
    _git("push", "origin", "main", cwd=source)
    expected = _head(source)

    result = pre_pull_repo(local)

    assert result.status == PrePullStatus.FAST_FORWARDED
    assert _head(local) == expected


def test_batch_plan_no_apply_when_any_repo_hard_fails(repos, tmp_path: Path):
    """Planning a batch never mutates: a hard-failing repo leaves the others unapplied."""
    source = repos["source"]
    remote = repos["remote"]
    ff_repo = repos["local"]  # will be strictly behind → PLANNED_FAST_FORWARD

    # A second clone that we make dirty (hard-fail).
    dirty_repo = tmp_path / "dirty"
    _git("clone", "-b", "main", str(remote), str(dirty_repo), cwd=tmp_path)
    (dirty_repo / "file.txt").write_text("dirty\n", encoding="utf-8")

    # Advance upstream so ff_repo is behind.
    _commit_file(source, "file.txt", "v2\n", "second")
    _git("push", "origin", "main", cwd=source)
    ff_before = _head(ff_repo)

    plans = plan_pre_pull_repos([ff_repo, dirty_repo])
    statuses = {p.repo: p.status for p in plans}

    assert statuses[ff_repo.name] == PrePullStatus.PLANNED_FAST_FORWARD
    assert statuses[dirty_repo.name] == PrePullStatus.DIRTY
    # Critically: planning the batch did NOT fast-forward ff_repo. The caller is
    # responsible for refusing apply when any plan hard-fails; here we prove the
    # plan phase itself is side-effect-free.
    assert _head(ff_repo) == ff_before


def test_untracked_files_do_not_block_plan_or_apply(repos):
    source, local = repos["source"], repos["local"]
    (local / "scratch.tmp").write_text("untracked\n", encoding="utf-8")
    _commit_file(source, "file.txt", "v2\n", "second")
    _git("push", "origin", "main", cwd=source)

    plan = plan_pre_pull_repo(local)
    assert plan.status == PrePullStatus.PLANNED_FAST_FORWARD
    result = apply_pre_pull_plan(plan)
    assert result.status == PrePullStatus.FAST_FORWARDED
    assert (local / "scratch.tmp").read_text(encoding="utf-8") == "untracked\n"


# --- credential redaction --------------------------------------------------

def test_redact_user_colon_token_at_host():
    url = "https://user:secret@example.com/repo.git"
    assert repo_sync._redact(url) == "https://[REDACTED]@example.com/repo.git"


def test_redact_token_only_at_host():
    url = "https://secret@example.com/repo.git"
    assert repo_sync._redact(url) == "https://[REDACTED]@example.com/repo.git"


def test_redact_no_credential_unchanged():
    url = "https://example.com/repo.git"
    assert repo_sync._redact(url) == url


def test_redact_none_passthrough():
    assert repo_sync._redact(None) is None


# --- untracked-overwrite detection -----------------------------------------

def test_plan_hard_fails_when_untracked_would_be_overwritten(repos):
    """Plan phase detects collision: untracked file shares path with upstream addition."""
    source, local = repos["source"], repos["local"]
    before = _head(local)

    # Commit a NEW file in source so it is not yet in local.
    _commit_file(source, "new_remote.txt", "upstream content\n", "add new_remote.txt")
    _git("push", "origin", "main", cwd=source)

    # Place an untracked file at the same path in local before planning.
    (local / "new_remote.txt").write_text("local untracked\n", encoding="utf-8")

    plan = plan_pre_pull_repo(local)

    assert plan.status == PrePullStatus.UNTRACKED_WOULD_BE_OVERWRITTEN
    assert plan.status in HARD_FAIL_STATUSES
    assert plan.needs_apply is False
    assert "new_remote.txt" in plan.message
    assert "refusing pre-pull" in plan.message
    # Working tree must be untouched.
    assert _head(local) == before
    assert (local / "new_remote.txt").read_text(encoding="utf-8") == "local untracked\n"


def test_untracked_non_colliding_still_allowed(repos):
    """Harmless untracked files with paths NOT in upstream remain non-blocking."""
    source, local = repos["source"], repos["local"]

    _commit_file(source, "new_remote.txt", "upstream content\n", "add new_remote.txt")
    _git("push", "origin", "main", cwd=source)

    # Different name — no collision.
    (local / "scratch.tmp").write_text("harmless\n", encoding="utf-8")

    plan = plan_pre_pull_repo(local)

    assert plan.status == PrePullStatus.PLANNED_FAST_FORWARD
    assert plan.needs_apply is True


def test_batch_plan_hard_fails_on_untracked_overwrite_prevents_other_apply(repos, tmp_path: Path):
    """Multi-repo batch: untracked-overwrite hard-fail in one repo leaves the other unapplied."""
    source = repos["source"]
    remote = repos["remote"]
    ff_repo = repos["local"]  # will be strictly behind

    # A second clone where an untracked file would collide.
    collision_repo = tmp_path / "collision"
    _git("clone", "-b", "main", str(remote), str(collision_repo), cwd=tmp_path)

    # Commit new file to source, push.
    _commit_file(source, "new_remote.txt", "upstream\n", "add new_remote.txt")
    _git("push", "origin", "main", cwd=source)
    ff_before = _head(ff_repo)

    # Place untracked collision file only in collision_repo.
    (collision_repo / "new_remote.txt").write_text("local untracked\n", encoding="utf-8")

    plans = plan_pre_pull_repos([ff_repo, collision_repo])
    statuses = {p.repo: p.status for p in plans}

    assert statuses[ff_repo.name] == PrePullStatus.PLANNED_FAST_FORWARD
    assert statuses[collision_repo.name] == PrePullStatus.UNTRACKED_WOULD_BE_OVERWRITTEN
    # Plan phase is side-effect-free: ff_repo was not fast-forwarded.
    assert _head(ff_repo) == ff_before
    # Untracked file in collision_repo is preserved.
    assert (collision_repo / "new_remote.txt").read_text(encoding="utf-8") == "local untracked\n"


def test_plan_hard_fails_untracked_collision_with_special_path_chars(repos):
    """Paths with spaces/unicode must be matched correctly (NUL-terminated -z output)."""
    source, local = repos["source"], repos["local"]
    before = _head(local)
    special = "böse datei.txt"

    _commit_file(source, special, "upstream content\n", "add special path")
    _git("push", "origin", "main", cwd=source)

    (local / special).write_text("local untracked\n", encoding="utf-8")

    plan = plan_pre_pull_repo(local)

    assert plan.status == PrePullStatus.UNTRACKED_WOULD_BE_OVERWRITTEN
    assert plan.needs_apply is False
    # The *raw* (unquoted) path appears in the message — only true when -z disables
    # git's path quoting. Without -z the message would carry the quoted octal form.
    assert special in plan.message
    assert _head(local) == before
    assert (local / special).read_text(encoding="utf-8") == "local untracked\n"


def test_plan_hard_fails_when_ignored_untracked_would_be_overwritten(repos):
    """Ignored untracked files are still protected (no --exclude-standard)."""
    source, local = repos["source"], repos["local"]
    before = _head(local)

    # Locally ignore 'ignored.txt' via .git/info/exclude (no commit → local stays
    # strictly behind), then create it as an ignored untracked file.
    (local / ".git" / "info" / "exclude").write_text("ignored.txt\n", encoding="utf-8")
    (local / "ignored.txt").write_text("precious local\n", encoding="utf-8")

    # Upstream introduces 'ignored.txt' as a tracked file.
    _commit_file(source, "ignored.txt", "upstream content\n", "add ignored.txt")
    _git("push", "origin", "main", cwd=source)

    plan = plan_pre_pull_repo(local)

    assert plan.status == PrePullStatus.UNTRACKED_WOULD_BE_OVERWRITTEN
    assert plan.needs_apply is False
    assert "ignored.txt" in plan.message
    assert _head(local) == before
    assert (local / "ignored.txt").read_text(encoding="utf-8") == "precious local\n"


def test_plan_hard_fails_on_untracked_file_directory_collision(repos):
    """An untracked file collides with an upstream path nested under that name."""
    source, local = repos["source"], repos["local"]
    before = _head(local)

    # Upstream adds tracked 'collision/file.txt' (a directory named 'collision').
    (source / "collision").mkdir()
    (source / "collision" / "file.txt").write_text("upstream\n", encoding="utf-8")
    _git("add", "collision/file.txt", cwd=source)
    _git("commit", "-m", "add collision/file.txt", cwd=source)
    _git("push", "origin", "main", cwd=source)

    # Local has an untracked FILE literally named 'collision'.
    (local / "collision").write_text("local untracked file\n", encoding="utf-8")

    plan = plan_pre_pull_repo(local)

    assert plan.status == PrePullStatus.UNTRACKED_WOULD_BE_OVERWRITTEN
    assert plan.needs_apply is False
    assert _head(local) == before
    assert (local / "collision").read_text(encoding="utf-8") == "local untracked file\n"


def test_plan_hard_fails_when_untracked_safety_check_fails(repos, monkeypatch: pytest.MonkeyPatch):
    """If the safety check (diff/ls-files) errors, refuse with ERROR — never fast-forward."""
    source, local = repos["source"], repos["local"]
    before = _head(local)
    _commit_file(source, "file.txt", "v2\n", "second")
    _git("push", "origin", "main", cwd=source)

    real_run_git = repo_sync._run_git

    def failing_run_git(args, *a, **kw):
        # Force exactly the untracked-overwrite safety check to fail; let the rest
        # of the plan (version/status/fetch/ancestry) run for real.
        if "diff" in args and "--name-only" in args:
            return subprocess.CompletedProcess(
                list(args), 128, stdout="", stderr="fatal: simulated diff failure\n"
            )
        return real_run_git(args, *a, **kw)

    monkeypatch.setattr(repo_sync, "_run_git", failing_run_git)

    plan = plan_pre_pull_repo(local)

    assert plan.status == PrePullStatus.ERROR
    assert plan.status in HARD_FAIL_STATUSES
    assert plan.needs_apply is False
    assert "untracked overwrite safety check failed" in plan.message
    # HEAD untouched; we never reached PLANNED_FAST_FORWARD.
    assert _head(local) == before


def test_no_forbidden_git_operations(repos, monkeypatch: pytest.MonkeyPatch):
    """Across a real plan+apply fast-forward, no forbidden git op is ever issued."""
    source, local = repos["source"], repos["local"]
    _commit_file(source, "file.txt", "v2\n", "second")
    _git("push", "origin", "main", cwd=source)

    seen_cmds = []
    real_run = subprocess.run

    def recording_run(cmd, *args, **kwargs):
        seen_cmds.append(list(cmd))
        assert kwargs.get("shell", False) is False
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(repo_sync.subprocess, "run", recording_run)

    result = pre_pull_repo(local)
    assert result.status == PrePullStatus.FAST_FORWARDED

    forbidden = {"pull", "reset", "rebase", "stash", "checkout", "switch", "clean"}
    for cmd in seen_cmds:
        assert forbidden.isdisjoint(set(cmd)), f"forbidden git op in {cmd}"
    # The only mutation is exactly one fast-forward-only merge.
    merges = [c for c in seen_cmds if "merge" in c]
    assert all("--ff-only" in c for c in merges), f"non-ff merge issued: {merges}"
    assert len(merges) == 1
