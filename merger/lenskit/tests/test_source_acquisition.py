"""Tests for rLens Source Acquisition v1 (remote_snapshot).

These use *real* temporary git repositories (bare remote + tracking clone) so the
ref-resolution and snapshot materialization semantics are exercised by git itself.
The central invariant is that remote_snapshot NEVER mutates the local repo: the
local branch, its (missing) upstream, and a dirty working tree all survive intact.
"""
from __future__ import annotations

import io
import os
import subprocess
import tarfile
from pathlib import Path

import pytest

from merger.lenskit.service import source_acquisition as sa
from merger.lenskit.service.source_acquisition import (
    SourceStatus,
    SnapshotExtractionError,
    materialize_remote_snapshot,
    resolve_remote_ref,
    resolve_effective_source_mode,
    safe_extract_tar,
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
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
        }
    )
    return env


def _git(*args: str, cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, env=_git_env())
    if check and proc.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed in {cwd}: {proc.stderr}")
    return proc


def _commit_file(repo: Path, name: str, content: str, message: str) -> None:
    target = repo / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    _git("add", name, cwd=repo)
    _git("commit", "-m", message, cwd=repo)


@pytest.fixture
def remote_and_local(tmp_path: Path):
    """A bare remote with `main` (file.txt=v2) and a clone parked on a no-upstream branch."""
    remote = tmp_path / "remote.git"
    _git("init", "--bare", "-b", "main", str(remote), cwd=tmp_path)

    source = tmp_path / "source"
    _git("init", "-b", "main", str(source), cwd=tmp_path)
    _commit_file(source, "file.txt", "v1\n", "init")
    _commit_file(source, "file.txt", "v2\n", "second")
    _git("remote", "add", "origin", str(remote), cwd=source)
    _git("push", "-u", "origin", "main", cwd=source)

    local = tmp_path / "local"
    _git("clone", "-b", "main", str(remote), str(local), cwd=tmp_path)
    # Park on a branch with NO upstream (the concrete problem case).
    _git("checkout", "-b", "pr-xyz", cwd=local)

    cache = tmp_path / "cache"
    cache.mkdir()
    return {"remote": remote, "local": local, "tmp": tmp_path, "cache": cache}


def _has_no_upstream(local: Path) -> bool:
    proc = _git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}", cwd=local, check=False)
    return proc.returncode != 0


# --- effective mode --------------------------------------------------------

class _Req:
    def __init__(self, **kw):
        self.repo_source_mode = kw.get("repo_source_mode")
        self.remote_ref = kw.get("remote_ref")
        self.remote_ref_policy = kw.get("remote_ref_policy", "upstream")
        self.pre_pull = kw.get("pre_pull", True)
        self.plan_only = kw.get("plan_only", False)


def test_effective_source_mode_legacy_and_explicit():
    assert resolve_effective_source_mode(_Req(pre_pull=True, plan_only=False)) == "local_ff"
    assert resolve_effective_source_mode(_Req(pre_pull=False)) == "local_current"
    assert resolve_effective_source_mode(_Req(pre_pull=True, plan_only=True)) == "local_current"
    assert resolve_effective_source_mode(_Req(repo_source_mode="local_current", pre_pull=True)) == "local_current"
    assert resolve_effective_source_mode(_Req(repo_source_mode="remote_snapshot")) == "remote_snapshot"
    # local_ff + plan_only must not mutate → degrades to local_current.
    assert resolve_effective_source_mode(_Req(repo_source_mode="local_ff", plan_only=True)) == "local_current"


# --- 1. default_branch on a no-upstream local branch -----------------------

def test_remote_snapshot_default_branch_no_upstream(remote_and_local):
    local = remote_and_local["local"]
    assert _has_no_upstream(local), "precondition: local branch has no upstream"
    before_branch = _git("rev-parse", "--abbrev-ref", "HEAD", cwd=local).stdout.strip()

    result = materialize_remote_snapshot(
        local,
        remote_ref=None,
        remote_ref_policy="default_branch",
        cache_root=remote_and_local["cache"],
        job_id="job1",
    )

    assert result.status == SourceStatus.SNAPSHOT_CREATED, result.message
    assert result.resolved_ref == "origin/main"
    assert result.resolved_commit
    assert result.local_repo_mutated is False
    # Snapshot content reflects origin/main (v2).
    snap = Path(result.snapshot_path)
    assert (snap / "file.txt").read_text() == "v2\n"
    assert snap.name == "local"  # named after the repo so the scanner labels it right

    # Local repo is untouched: still on pr-xyz, still no upstream, no merge.
    assert _git("rev-parse", "--abbrev-ref", "HEAD", cwd=local).stdout.strip() == before_branch == "pr-xyz"
    assert _has_no_upstream(local)


# --- 2. same_branch --------------------------------------------------------

def test_remote_snapshot_same_branch(remote_and_local):
    local = remote_and_local["local"]
    # Create origin/foo and a local branch foo (no tracking required by same_branch).
    _git("checkout", "-b", "foo", cwd=local)
    _commit_file(local, "foo.txt", "foo\n", "foo commit")
    _git("push", "origin", "foo", cwd=local)
    # Re-park without upstream by recreating the branch pointer locally.
    _git("checkout", "-B", "foo", cwd=local)

    result = materialize_remote_snapshot(
        local,
        remote_ref=None,
        remote_ref_policy="same_branch",
        cache_root=remote_and_local["cache"],
        job_id="job2",
    )
    assert result.status == SourceStatus.SNAPSHOT_CREATED, result.message
    assert result.resolved_ref == "origin/foo"
    assert (Path(result.snapshot_path) / "foo.txt").read_text() == "foo\n"


# --- 3. explicit remote_ref ------------------------------------------------

def test_remote_snapshot_explicit_ref(remote_and_local):
    local = remote_and_local["local"]
    remote_main_sha = _git("ls-remote", str(remote_and_local["remote"]), "refs/heads/main", cwd=local).stdout.split()[0]

    result = materialize_remote_snapshot(
        local,
        remote_ref="origin/main",
        remote_ref_policy="upstream",  # ignored because explicit ref wins
        cache_root=remote_and_local["cache"],
        job_id="job3",
    )
    assert result.status == SourceStatus.SNAPSHOT_CREATED, result.message
    assert result.resolved_commit == remote_main_sha
    assert (Path(result.snapshot_path) / "file.txt").read_text() == "v2\n"


# --- 4. dirty local tree is ignored / preserved ----------------------------

def test_remote_snapshot_dirty_local_tree_ignored(remote_and_local):
    local = remote_and_local["local"]
    (local / "file.txt").write_text("LOCAL DIRTY EDIT\n", encoding="utf-8")

    result = materialize_remote_snapshot(
        local,
        remote_ref=None,
        remote_ref_policy="default_branch",
        cache_root=remote_and_local["cache"],
        job_id="job4",
    )
    assert result.status == SourceStatus.SNAPSHOT_CREATED, result.message
    # Snapshot is the committed remote content, not the dirty local edit.
    assert (Path(result.snapshot_path) / "file.txt").read_text() == "v2\n"
    # Local dirty state is preserved (no checkout/reset/clean happened).
    assert (local / "file.txt").read_text() == "LOCAL DIRTY EDIT\n"
    assert result.local_repo_mutated is False


# --- 5. missing remote -----------------------------------------------------

def test_remote_snapshot_missing_remote_fails_cleanly(tmp_path):
    repo = tmp_path / "no-remote"
    _git("init", "-b", "main", str(repo), cwd=tmp_path)
    _commit_file(repo, "a.txt", "a\n", "init")

    result = materialize_remote_snapshot(
        repo,
        remote_ref=None,
        remote_ref_policy="default_branch",
        cache_root=tmp_path / "cache",
        job_id="job5",
    )
    assert result.status == SourceStatus.MISSING_REMOTE
    assert result.snapshot_path is None
    assert result.local_repo_mutated is False


# --- 6. missing ref (upstream policy without upstream) ----------------------

def test_remote_snapshot_missing_ref_fails_cleanly(remote_and_local):
    local = remote_and_local["local"]
    assert _has_no_upstream(local)
    result = materialize_remote_snapshot(
        local,
        remote_ref=None,
        remote_ref_policy="upstream",
        cache_root=remote_and_local["cache"],
        job_id="job6",
    )
    assert result.status == SourceStatus.MISSING_REF
    assert result.snapshot_path is None


# --- 7. credential redaction -----------------------------------------------

def test_remote_snapshot_redacts_remote_url_credentials(tmp_path):
    repo = tmp_path / "cred"
    _git("init", "-b", "main", str(repo), cwd=tmp_path)
    _commit_file(repo, "a.txt", "a\n", "init")
    secret = "s3cr3t-token"
    _git("remote", "add", "origin", f"https://user:{secret}@example.invalid/repo.git", cwd=repo)

    resolution = resolve_remote_ref(
        repo, remote_ref=None, remote_ref_policy="default_branch", timeout_seconds=10
    )
    # The unreachable host means resolution fails, but the redaction must hold.
    assert resolution.remote_url_redacted is not None
    assert secret not in resolution.remote_url_redacted
    assert "[REDACTED]" in resolution.remote_url_redacted
    assert secret not in (resolution.stderr or "")
    assert secret not in (resolution.message or "")


# --- 8. safe tar extraction ------------------------------------------------

def _tar_with_member(name: str, *, linkname: str = None, typeflag=tarfile.REGTYPE) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        info = tarfile.TarInfo(name=name)
        if linkname is not None:
            info.type = typeflag
            info.linkname = linkname
        else:
            data = b"hello"
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
            buf2 = buf.getvalue()
            return buf2
        tar.addfile(info)
    return buf.getvalue()


def test_safe_tar_extraction_rejects_path_traversal(tmp_path):
    dest = tmp_path / "out"
    # 1. ../ traversal
    with pytest.raises(SnapshotExtractionError):
        safe_extract_tar(_tar_with_member("../evil.txt"), dest)
    # 2. absolute path
    with pytest.raises(SnapshotExtractionError):
        safe_extract_tar(_tar_with_member("/etc/evil.txt"), dest)
    # 3. escaping symlink
    with pytest.raises(SnapshotExtractionError):
        safe_extract_tar(_tar_with_member("link", linkname="../../escape", typeflag=tarfile.SYMTYPE), dest)
    # 4. a well-formed member extracts fine
    safe_extract_tar(_tar_with_member("good/inner.txt"), dest)
    assert (dest / "good" / "inner.txt").read_text() == "hello"


# --- 9. submodule warning --------------------------------------------------

def test_remote_snapshot_warns_on_gitmodules(remote_and_local):
    local = remote_and_local["local"]
    # Commit a .gitmodules on origin/main.
    _git("checkout", "main", cwd=local)
    _commit_file(local, ".gitmodules", '[submodule "x"]\n\tpath = x\n\turl = ./x\n', "add gitmodules")
    _git("push", "origin", "main", cwd=local)
    _git("checkout", "-b", "pr-2", cwd=local)

    result = materialize_remote_snapshot(
        local, remote_ref=None, remote_ref_policy="default_branch",
        cache_root=remote_and_local["cache"], job_id="job9",
    )
    assert result.status == SourceStatus.SNAPSHOT_CREATED, result.message
    assert sa.WARN_SUBMODULES_NOT_EXPANDED in result.warnings


# --- 10. LFS warning -------------------------------------------------------

def test_remote_snapshot_warns_on_lfs_attributes_or_pointer(remote_and_local):
    local = remote_and_local["local"]
    _git("checkout", "main", cwd=local)
    _commit_file(local, ".gitattributes", "*.bin filter=lfs diff=lfs merge=lfs -text\n", "add lfs attrs")
    _git("push", "origin", "main", cwd=local)
    _git("checkout", "-b", "pr-3", cwd=local)

    result = materialize_remote_snapshot(
        local, remote_ref=None, remote_ref_policy="default_branch",
        cache_root=remote_and_local["cache"], job_id="job10",
    )
    assert result.status == SourceStatus.SNAPSHOT_CREATED, result.message
    assert sa.WARN_LFS_NOT_SMUDGED in result.warnings
