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
    SourceModeConflictError,
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
        # Mirror pydantic's model_fields_set: only the kwargs the caller passed
        # count as explicitly set, so the resolver can tell an explicit pre_pull
        # from the inert default — exactly as it does for a real JobRequest.
        self.model_fields_set = set(kw.keys())


def test_effective_source_mode_legacy_and_explicit():
    # Legacy (repo_source_mode unset): derived purely from pre_pull/plan_only.
    assert resolve_effective_source_mode(_Req(pre_pull=True, plan_only=False)) == "local_ff"
    assert resolve_effective_source_mode(_Req(pre_pull=False)) == "local_current"
    assert resolve_effective_source_mode(_Req(pre_pull=True, plan_only=True)) == "local_current"
    # A bare explicit mode (no explicit pre_pull) is accepted as-is.
    assert resolve_effective_source_mode(_Req(repo_source_mode="local_current")) == "local_current"
    assert resolve_effective_source_mode(_Req(repo_source_mode="local_ff")) == "local_ff"
    assert resolve_effective_source_mode(_Req(repo_source_mode="remote_snapshot")) == "remote_snapshot"


def test_effective_source_mode_rejects_explicit_contradictions():
    # The resolver re-runs the central validator, so an object that bypasses the
    # /api/jobs model_validator (model_construct, stored jobs, test doubles) still
    # cannot smuggle a contradictory explicit state past it.
    # local_ff + plan_only: local_ff would mutate, plan_only forbids mutation.
    with pytest.raises(SourceModeConflictError):
        resolve_effective_source_mode(_Req(repo_source_mode="local_ff", plan_only=True))
    # local_ff + explicit pre_pull=False: local_ff implies the fast-forward pre-pull.
    with pytest.raises(SourceModeConflictError):
        resolve_effective_source_mode(_Req(repo_source_mode="local_ff", pre_pull=False))
    # local_current + explicit pre_pull=True: local_current scans as-is, never pre-pulls.
    with pytest.raises(SourceModeConflictError):
        resolve_effective_source_mode(_Req(repo_source_mode="local_current", pre_pull=True))
    # remote_snapshot + explicit pre_pull=True: remote_snapshot never mutates the local repo.
    with pytest.raises(SourceModeConflictError):
        resolve_effective_source_mode(_Req(repo_source_mode="remote_snapshot", pre_pull=True))
    # Unknown explicit mode must never fall through to a silent local default.
    with pytest.raises(SourceModeConflictError):
        resolve_effective_source_mode(_Req(repo_source_mode="wat"))


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


def test_remote_snapshot_does_not_persist_remote_url_credentials_in_cache(tmp_path, monkeypatch):
    repo = tmp_path / "cred_repo"
    _git("init", "-b", "main", str(repo), cwd=tmp_path)
    _commit_file(repo, "a.txt", "a\n", "init")

    secret = "secret-token-12345"
    fake_url = f"https://user:{secret}@example.invalid/repo.git"

    def mock_read_remote_url(repo_path, remote_name, timeout):
        return fake_url, subprocess.CompletedProcess(["git"], 0, stdout=fake_url)

    monkeypatch.setattr(sa, "_read_remote_url", mock_read_remote_url)

    orig_run_git = sa._run_git
    run_git_calls = []

    def spy_run_git(args, **kwargs):
        run_git_calls.append(list(args))
        if args[0] == "ls-remote":
            return subprocess.CompletedProcess(args, 0, stdout="1234567890abcdef1234567890abcdef12345678\trefs/heads/main\n")
        return orig_run_git(args, **kwargs)

    monkeypatch.setattr(sa, "_run_git", spy_run_git)

    result = materialize_remote_snapshot(
        repo,
        remote_ref="origin/main",
        remote_ref_policy="upstream",
        cache_root=tmp_path / "cache",
        job_id="job-cred-test",
    )

    assert result.status == SourceStatus.FETCH_FAILED
    assert "[REDACTED]" in (result.remote_url_redacted or "")
    assert secret not in (result.remote_url_redacted or "")
    assert secret not in (result.stderr or "")
    assert secret not in (result.message or "")

    fetch_calls = [call_args for call_args in run_git_calls if call_args and call_args[0] == "fetch"]
    assert fetch_calls, "expected at least one direct fetch call"
    for call_args in fetch_calls:
        assert "--no-write-fetch-head" in call_args

    for call_args in run_git_calls:
        if call_args[0] == "remote":
            assert "add" not in call_args
            assert "set-url" not in call_args

    cache_git_dir = tmp_path / "cache" / sa.SNAPSHOT_DIR_NAME / "job-cred-test" / "cred_repo.git"
    config_file = cache_git_dir / "config"
    if config_file.exists():
        content = config_file.read_text(encoding="utf-8")
        assert secret not in content
        assert 'remote "origin"' not in content

    if cache_git_dir.exists():
        secret_bytes = secret.encode("utf-8")
        for path in cache_git_dir.rglob("*"):
            if path.is_file():
                assert secret_bytes not in path.read_bytes(), f"secret leaked into cache file: {path}"

# --- 12. Fix 1: Non-origin upstream ---

def test_remote_snapshot_upstream_policy_uses_tracked_non_origin_remote(tmp_path):
    # Remote A (origin)
    origin_remote = tmp_path / "origin.git"
    _git("init", "--bare", "-b", "main", str(origin_remote), cwd=tmp_path)

    # Remote B (upstream)
    upstream_remote = tmp_path / "upstream.git"
    _git("init", "--bare", "-b", "main", str(upstream_remote), cwd=tmp_path)

    # We need a commit in upstream
    temp = tmp_path / "temp"
    _git("init", "-b", "main", str(temp), cwd=tmp_path)
    _commit_file(temp, "upstream.txt", "hello upstream\n", "init")
    _git("remote", "add", "upstream", str(upstream_remote), cwd=temp)
    _git("push", "upstream", "main", cwd=temp)

    # Local repo
    local = tmp_path / "local"
    _git("init", "-b", "main", str(local), cwd=tmp_path)
    _commit_file(local, "local.txt", "local\n", "init")
    _git("remote", "add", "origin", str(origin_remote), cwd=local)
    _git("remote", "add", "upstream", str(upstream_remote), cwd=local)

    # fetch upstream and set tracking
    _git("fetch", "upstream", cwd=local)
    _git("branch", "-u", "upstream/main", "main", cwd=local)

    result = materialize_remote_snapshot(
        local,
        remote_ref=None,
        remote_ref_policy="upstream",
        cache_root=tmp_path / "cache",
        job_id="job_upstream",
    )

    assert result.status == SourceStatus.SNAPSHOT_CREATED, result.stderr
    assert result.resolved_ref == "upstream/main"
    assert (Path(result.snapshot_path) / "upstream.txt").read_text() == "hello upstream\n"


# --- 13. Fix 2: Tag ref ---

def test_remote_snapshot_explicit_tag_ref(tmp_path):
    remote = tmp_path / "remote.git"
    _git("init", "--bare", "-b", "main", str(remote), cwd=tmp_path)

    temp = tmp_path / "temp"
    _git("init", "-b", "main", str(temp), cwd=tmp_path)
    _commit_file(temp, "tag.txt", "v1\n", "init")
    _git("remote", "add", "origin", str(remote), cwd=temp)
    _git("tag", "v1", cwd=temp)
    _git("push", "origin", "main", "--tags", cwd=temp)

    local = tmp_path / "local"
    _git("init", "-b", "main", str(local), cwd=tmp_path)
    _git("remote", "add", "origin", str(remote), cwd=local)

    result = materialize_remote_snapshot(
        local,
        remote_ref="refs/tags/v1",
        remote_ref_policy="upstream",
        cache_root=tmp_path / "cache",
        job_id="job_tag",
    )
    assert result.status == SourceStatus.SNAPSHOT_CREATED, result.stderr
    assert result.resolved_ref == "refs/tags/v1"
    assert (Path(result.snapshot_path) / "tag.txt").read_text() == "v1\n"


# --- 14. Fix 2: Explicit SHA ---

def test_remote_snapshot_explicit_sha_reachable_only_by_tag(tmp_path):
    remote = tmp_path / "remote.git"
    _git("init", "--bare", "-b", "main", str(remote), cwd=tmp_path)

    temp = tmp_path / "temp"
    _git("init", "-b", "main", str(temp), cwd=tmp_path)
    _git("remote", "add", "origin", str(remote), cwd=temp)
    _commit_file(temp, "file.txt", "1\n", "first")
    sha1 = _git("rev-parse", "HEAD", cwd=temp).stdout.strip()
    _git("tag", "v1", cwd=temp)

    _commit_file(temp, "file.txt", "2\n", "second")
    _git("push", "origin", "main", "--tags", cwd=temp)

    # We ask for sha1 directly
    local = tmp_path / "local"
    _git("init", "-b", "main", str(local), cwd=tmp_path)
    _git("remote", "add", "origin", str(remote), cwd=local)

    result = materialize_remote_snapshot(
        local,
        remote_ref=sha1,
        remote_ref_policy="upstream",
        cache_root=tmp_path / "cache",
        job_id="job_sha",
    )
    assert result.status == SourceStatus.SNAPSHOT_CREATED, result.stderr
    assert result.resolved_commit == sha1
    assert (Path(result.snapshot_path) / "file.txt").read_text() == "1\n"

# --- 15. Fix 3: Redaction ---

def test_redact_credentials_in_non_http_remote_urls():
    assert sa._redact("ftp://user:password@example.com/repo.git") == "ftp://[REDACTED]@example.com/repo.git"
    assert sa._redact("ssh://git@example.com/repo.git") == "ssh://[REDACTED]@example.com/repo.git"
    assert sa._redact("https://token@example.com/repo.git") == "https://[REDACTED]@example.com/repo.git"
    assert sa._redact("https://user:token@example.com/repo.git") == "https://[REDACTED]@example.com/repo.git"
    assert sa._redact("git@github.com:owner/repo.git") == "git@github.com:owner/repo.git"

def test_remote_snapshot_explicit_sha_missing_fails_cleanly(tmp_path):
    remote = tmp_path / "remote.git"
    _git("init", "--bare", "-b", "main", str(remote), cwd=tmp_path)

    temp = tmp_path / "temp"
    _git("init", "-b", "main", str(temp), cwd=tmp_path)
    _git("remote", "add", "origin", str(remote), cwd=temp)
    _commit_file(temp, "file.txt", "1\n", "first")
    _git("push", "origin", "main", cwd=temp)

    local = tmp_path / "local"
    _git("init", "-b", "main", str(local), cwd=tmp_path)
    _git("remote", "add", "origin", str(remote), cwd=local)

    missing_sha = "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2"
    result = materialize_remote_snapshot(
        local,
        remote_ref=missing_sha,
        remote_ref_policy="upstream",
        cache_root=tmp_path / "cache",
        job_id="job_sha_missing",
    )
    assert result.status == SourceStatus.MISSING_REF, result.stderr
    assert result.snapshot_path is None


# --- 16. Fix 1: Symlink snapshot reject ---

def test_remote_snapshot_rejects_symlink_snapshot_dir_before_extract(tmp_path):
    remote = tmp_path / "remote.git"
    _git("init", "--bare", "-b", "main", str(remote), cwd=tmp_path)
    
    temp = tmp_path / "temp"
    _git("init", "-b", "main", str(temp), cwd=tmp_path)
    _commit_file(temp, "file.txt", "1\n", "first")
    _git("remote", "add", "origin", str(remote), cwd=temp)
    _git("push", "origin", "main", cwd=temp)

    local = tmp_path / "local"
    _git("init", "-b", "main", str(local), cwd=tmp_path)
    _git("remote", "add", "origin", str(remote), cwd=local)

    cache = tmp_path / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    
    job_id = "job_symlink"
    snapshot_base = cache / sa.SNAPSHOT_DIR_NAME / job_id
    snapshot_base.mkdir(parents=True, exist_ok=True)
    
    outside = tmp_path / "outside"
    outside.mkdir()
    
    snapshot_dir = snapshot_base / "local"
    os.symlink(str(outside), str(snapshot_dir))

    result = materialize_remote_snapshot(
        local,
        remote_ref=None,
        remote_ref_policy="default_branch",
        cache_root=cache,
        job_id=job_id,
    )
    assert result.status == SourceStatus.ERROR
    assert result.snapshot_path is None
    assert "symlink" in (result.stderr or "") or "symlink" in (result.message or "")


# --- 17. Fix 2: Stale file cleanup ---

def test_remote_snapshot_cleans_existing_snapshot_dir_before_extract(tmp_path):
    remote = tmp_path / "remote.git"
    _git("init", "--bare", "-b", "main", str(remote), cwd=tmp_path)
    
    temp = tmp_path / "temp"
    _git("init", "-b", "main", str(temp), cwd=tmp_path)
    _commit_file(temp, "old.txt", "old\n", "init")
    _commit_file(temp, "file.txt", "A\n", "a")
    _git("remote", "add", "origin", str(remote), cwd=temp)
    _git("push", "origin", "main", cwd=temp)

    local = tmp_path / "local"
    _git("init", "-b", "main", str(local), cwd=tmp_path)
    _git("remote", "add", "origin", str(remote), cwd=local)

    cache = tmp_path / "cache"
    job_id = "job-clean"
    
    # First materialization
    result1 = materialize_remote_snapshot(
        local,
        remote_ref=None,
        remote_ref_policy="default_branch",
        cache_root=cache,
        job_id=job_id,
    )
    assert result1.status == SourceStatus.SNAPSHOT_CREATED
    assert (Path(result1.snapshot_path) / "old.txt").exists()
    
    # Update remote: remove old.txt, change file.txt
    _git("rm", "old.txt", cwd=temp)
    _commit_file(temp, "file.txt", "B\n", "b")
    _git("push", "origin", "main", cwd=temp)
    
    # Second materialization with same job_id
    result2 = materialize_remote_snapshot(
        local,
        remote_ref=None,
        remote_ref_policy="default_branch",
        cache_root=cache,
        job_id=job_id,
    )
    assert result2.status == SourceStatus.SNAPSHOT_CREATED
    assert not (Path(result2.snapshot_path) / "old.txt").exists()
    assert (Path(result2.snapshot_path) / "file.txt").read_text() == "B\n"


# --- 18. Fix 3: Annotated tags ---

def test_remote_snapshot_explicit_annotated_tag_ref_resolves_commit(tmp_path):
    remote = tmp_path / "remote.git"
    _git("init", "--bare", "-b", "main", str(remote), cwd=tmp_path)

    temp = tmp_path / "temp"
    _git("init", "-b", "main", str(temp), cwd=tmp_path)
    _commit_file(temp, "tagged.txt", "annotated\n", "init")
    commit_sha = _git("rev-parse", "HEAD", cwd=temp).stdout.strip()
    
    _git("tag", "-a", "v1", "-m", "version 1", cwd=temp)
    _git("remote", "add", "origin", str(remote), cwd=temp)
    _git("push", "origin", "main", "--tags", cwd=temp)

    local = tmp_path / "local"
    _git("init", "-b", "main", str(local), cwd=tmp_path)
    _git("remote", "add", "origin", str(remote), cwd=local)

    result = materialize_remote_snapshot(
        local,
        remote_ref="refs/tags/v1",
        remote_ref_policy="upstream",
        cache_root=tmp_path / "cache",
        job_id="job_annotated_tag",
    )
    assert result.status == SourceStatus.SNAPSHOT_CREATED, result.stderr
    assert result.resolved_ref == "refs/tags/v1"
    assert result.resolved_commit == commit_sha


# --- 19. Fix 4: Explicit SHA missing remote ---

def test_remote_snapshot_plan_only_explicit_sha_missing_remote_is_not_planned(tmp_path):
    repo = tmp_path / "no-remote"
    _git("init", "-b", "main", str(repo), cwd=tmp_path)
    _commit_file(repo, "a.txt", "a\n", "init")
    sha = _git("rev-parse", "HEAD", cwd=repo).stdout.strip()

    # The issue was that a missing remote with a valid explicit SHA
    # would still return RESOLVED instead of MISSING_REMOTE.
    resolution = resolve_remote_ref(
        repo, remote_ref=sha, remote_ref_policy="upstream", timeout_seconds=10
    )
    assert resolution.status == SourceStatus.MISSING_REMOTE
    assert resolution.status != SourceStatus.RESOLVED
    assert resolution.resolved_commit is None

# --- 20. Optimal hardening: snapshot base/root + blank ref ------------------

def test_remote_snapshot_rejects_symlink_job_snapshot_base_before_extract(tmp_path):
    remote = tmp_path / "remote.git"
    _git("init", "--bare", "-b", "main", str(remote), cwd=tmp_path)

    temp = tmp_path / "temp"
    _git("init", "-b", "main", str(temp), cwd=tmp_path)
    _commit_file(temp, "file.txt", "1\n", "first")
    _git("remote", "add", "origin", str(remote), cwd=temp)
    _git("push", "origin", "main", cwd=temp)

    local = tmp_path / "local"
    _git("init", "-b", "main", str(local), cwd=tmp_path)
    _git("remote", "add", "origin", str(remote), cwd=local)

    cache = tmp_path / "cache"
    snapshots_root = cache / sa.SNAPSHOT_DIR_NAME
    snapshots_root.mkdir(parents=True, exist_ok=True)

    outside = tmp_path / "outside"
    outside.mkdir()

    job_id = "job_base_symlink"
    os.symlink(str(outside), str(snapshots_root / job_id))

    result = materialize_remote_snapshot(
        local,
        remote_ref=None,
        remote_ref_policy="default_branch",
        cache_root=cache,
        job_id=job_id,
    )

    assert result.status == SourceStatus.ERROR
    assert result.snapshot_path is None
    assert "symlink" in (result.message or "")
    assert not (outside / "local.git").exists()
    assert not (outside / "local").exists()


def test_remote_snapshot_rejects_job_id_path_separator(tmp_path):
    remote = tmp_path / "remote.git"
    _git("init", "--bare", "-b", "main", str(remote), cwd=tmp_path)

    temp = tmp_path / "temp"
    _git("init", "-b", "main", str(temp), cwd=tmp_path)
    _commit_file(temp, "file.txt", "1\n", "first")
    _git("remote", "add", "origin", str(remote), cwd=temp)
    _git("push", "origin", "main", cwd=temp)

    local = tmp_path / "local"
    _git("init", "-b", "main", str(local), cwd=tmp_path)
    _git("remote", "add", "origin", str(remote), cwd=local)

    result = materialize_remote_snapshot(
        local,
        remote_ref=None,
        remote_ref_policy="default_branch",
        cache_root=tmp_path / "cache",
        job_id="../escape",
    )

    assert result.status == SourceStatus.ERROR
    assert result.snapshot_path is None
    assert "invalid snapshot job_id" in (result.message or "")


def test_remote_snapshot_blank_remote_ref_uses_policy_not_sha_path(remote_and_local):
    result = materialize_remote_snapshot(
        remote_and_local["local"],
        remote_ref="   ",
        remote_ref_policy="default_branch",
        cache_root=remote_and_local["cache"],
        job_id="job_blank_ref",
    )

    assert result.status == SourceStatus.SNAPSHOT_CREATED, result.stderr
    assert result.requested_remote_ref is None
    assert result.resolved_ref == "origin/main"
    assert result.resolved_commit


def test_safe_extract_tar_rejects_special_device_member(tmp_path):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        info = tarfile.TarInfo(name="devnode")
        info.type = tarfile.CHRTYPE
        info.devmajor = 1
        info.devminor = 3
        tar.addfile(info)

    with pytest.raises(SnapshotExtractionError):
        safe_extract_tar(buf.getvalue(), tmp_path / "out")


# --- 21. Tar extraction hardening (v1: links/special members rejected) ------

def _build_tar(members) -> bytes:
    """Build a tar from a list of (TarInfo, optional payload-bytes)."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for info, payload in members:
            if payload is None:
                tar.addfile(info)
            else:
                info.size = len(payload)
                tar.addfile(info, io.BytesIO(payload))
    return buf.getvalue()


def _reg(name: str, payload: bytes = b"data") -> tuple:
    info = tarfile.TarInfo(name=name)
    info.type = tarfile.REGTYPE
    return info, payload


def _dir(name: str) -> tuple:
    info = tarfile.TarInfo(name=name)
    info.type = tarfile.DIRTYPE
    return info, None


def _sym(name: str, linkname: str) -> tuple:
    info = tarfile.TarInfo(name=name)
    info.type = tarfile.SYMTYPE
    info.linkname = linkname
    return info, None


def _lnk(name: str, linkname: str) -> tuple:
    info = tarfile.TarInfo(name=name)
    info.type = tarfile.LNKTYPE
    info.linkname = linkname
    return info, None


def _fifo(name: str) -> tuple:
    info = tarfile.TarInfo(name=name)
    info.type = tarfile.FIFOTYPE
    return info, None


def _blk(name: str) -> tuple:
    info = tarfile.TarInfo(name=name)
    info.type = tarfile.BLKTYPE
    info.devmajor = 8
    info.devminor = 0
    return info, None


def test_safe_extract_tar_rejects_dot_dot(tmp_path):
    with pytest.raises(SnapshotExtractionError):
        safe_extract_tar(_build_tar([_reg("../evil.txt")]), tmp_path / "out")


def test_safe_extract_tar_rejects_absolute(tmp_path):
    with pytest.raises(SnapshotExtractionError):
        safe_extract_tar(_build_tar([_reg("/etc/evil.txt")]), tmp_path / "out")


def test_safe_extract_tar_rejects_symlink_dir_then_file_under_it(tmp_path):
    # Classic escalation: a symlink "dir" -> somewhere, then a later "dir/file".
    # v1 rejects the symlink member outright, so the file can never be written
    # through it. No file must escape the destination either.
    outside = tmp_path / "outside"
    outside.mkdir()
    dest = tmp_path / "out"
    members = [_sym("dir", str(outside)), _reg("dir/pwned.txt", b"x")]
    with pytest.raises(SnapshotExtractionError):
        safe_extract_tar(_build_tar(members), dest)
    assert not (outside / "pwned.txt").exists()


def test_safe_extract_tar_rejects_relative_symlink(tmp_path):
    with pytest.raises(SnapshotExtractionError):
        safe_extract_tar(_build_tar([_sym("link", "../escape")]), tmp_path / "out")


def test_safe_extract_tar_rejects_hardlink(tmp_path):
    members = [_reg("a.txt", b"a"), _lnk("b.txt", "a.txt")]
    with pytest.raises(SnapshotExtractionError):
        safe_extract_tar(_build_tar(members), tmp_path / "out")


def test_safe_extract_tar_rejects_fifo(tmp_path):
    with pytest.raises(SnapshotExtractionError):
        safe_extract_tar(_build_tar([_fifo("pipe")]), tmp_path / "out")


def test_safe_extract_tar_rejects_block_device(tmp_path):
    with pytest.raises(SnapshotExtractionError):
        safe_extract_tar(_build_tar([_blk("disk")]), tmp_path / "out")


def test_safe_extract_tar_rejects_existing_symlink_parent_in_dest(tmp_path):
    # A symlink already present in the destination must never be followed: the
    # write must be rejected, not redirected outside the tree.
    outside = tmp_path / "outside"
    outside.mkdir()
    dest = tmp_path / "out"
    dest.mkdir()
    os.symlink(str(outside), str(dest / "sub"))
    with pytest.raises(SnapshotExtractionError):
        safe_extract_tar(_build_tar([_reg("sub/file.txt", b"x")]), dest)
    assert not (outside / "file.txt").exists()


def test_safe_extract_tar_extracts_regular_files_and_dirs(tmp_path):
    dest = tmp_path / "out"
    members = [_dir("pkg"), _reg("pkg/mod.py", b"print(1)\n"), _reg("README.md", b"hi\n")]
    safe_extract_tar(_build_tar(members), dest)
    assert (dest / "pkg" / "mod.py").read_text() == "print(1)\n"
    assert (dest / "README.md").read_text() == "hi\n"
    # Nothing escaped the destination.
    assert (dest / "pkg").is_dir() and not (dest / "pkg").is_symlink()


def test_safe_extract_tar_wraps_fs_collision_as_extraction_error(tmp_path):
    # A regular file "a" followed by "a/b.txt" makes the parent mkdir fail. The
    # raw OSError must be wrapped as SnapshotExtractionError so the caller maps it
    # onto a controlled extract_failed, not an uncaught FileExistsError.
    dest = tmp_path / "out"
    members = [_reg("a", b"i am a file"), _reg("a/b.txt", b"x")]
    with pytest.raises(SnapshotExtractionError):
        safe_extract_tar(_build_tar(members), dest)
