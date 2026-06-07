"""rLens Source Acquisition v1 — remote snapshot materialization.

This module adds an explicitly *non-mutating* way to acquire the content rLens
scans. It complements ``repo_sync.py`` (the bounded fast-forward-only pre-pull),
it does not replace it.

Source modes (see ``docs/blueprints/rlens-source-acquisition-blueprint.md``):

* ``local_current``   — scan the current local working tree; no git mutation.
* ``local_ff``        — the existing bounded pre-pull, then scan the local tree.
* ``remote_snapshot`` — scan an isolated materialization of a remote commit.

Hard guarantees for ``remote_snapshot``:

* Never mutates the local user repo (no fetch into it, no merge, no checkout,
  no switch, no reset, no upstream change).
* Uses a job-bound cache/temp directory under the validated ``merges_dir``.
* No ``shell=True``; every git command is an explicit argument list.
* ``GIT_TERMINAL_PROMPT=0`` for all git calls; auth-required fetches fail fast.
* Git subprocess output is decoded ``encoding="utf-8", errors="surrogateescape"``.
* Remote URLs, stderr and messages are credential-redacted before they are
  returned, logged or written to a report.
* Snapshot extraction is hardened against path traversal and escaping
  symlink/hardlink members.
"""
from __future__ import annotations

import io
import logging
import os
import re
import shutil
import subprocess
import tarfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 60

# Job-bound snapshot root, created under the (already validated) merges_dir.
SNAPSHOT_DIR_NAME = ".rlens-source-snapshots"

# Report warning codes (v1 known limits).
WARN_SUBMODULES_NOT_EXPANDED = "submodules_not_expanded"
WARN_LFS_NOT_SMUDGED = "lfs_not_smudged"


class SourceStatus:
    """String-constant status vocabulary (no enums)."""

    SNAPSHOT_CREATED = "snapshot_created"
    PLANNED = "planned"
    SKIPPED = "skipped"
    MISSING_REMOTE = "missing_remote"
    MISSING_REF = "missing_ref"
    FETCH_FAILED = "fetch_failed"
    ARCHIVE_FAILED = "archive_failed"
    EXTRACT_FAILED = "extract_failed"
    ERROR = "error"
    # Used only by resolve_remote_ref to signal a successful resolution.
    RESOLVED = "resolved"


# Mask credentials git can echo in remote URLs:
# https://user:token@host and https://token@host forms.
_CREDENTIAL_RE = re.compile(r"([A-Za-z][A-Za-z0-9+.-]*://)[^/\s@]+@")

_HEX_SHA_RE = re.compile(r"^[0-9a-fA-F]{7,64}$")


def _redact(text: Optional[str]) -> Optional[str]:
    """Strip embedded credentials before text is stored/logged/returned."""
    if not text:
        return text
    return _CREDENTIAL_RE.sub(r"\1[REDACTED]@", text)


def _git_env() -> dict:
    """Environment for git subprocesses: never prompt, never hang interactively."""
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def _run_git(
    args: Sequence[str],
    *,
    repo_path: Optional[Path] = None,
    git_dir: Optional[Path] = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess:
    """Run a git command as an explicit arg list (never ``shell=True``).

    Timeouts and OS-level launch errors are converted into a non-zero
    ``CompletedProcess`` so callers branch on ``returncode`` uniformly.
    """
    cmd: List[str] = ["git"]
    if git_dir is not None:
        cmd += ["--git-dir", str(git_dir)]
    if repo_path is not None:
        cmd += ["-C", str(repo_path)]
    cmd += list(args)
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="surrogateescape",
            timeout=timeout,
            env=_git_env(),
            check=False,
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, 124, stdout="", stderr=f"git timed out after {timeout}s")
    except OSError as exc:  # e.g. git binary missing
        return subprocess.CompletedProcess(cmd, 127, stdout="", stderr=str(exc))


def _run_git_binary(
    args: Sequence[str],
    *,
    git_dir: Optional[Path] = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> "subprocess.CompletedProcess[bytes]":
    """Run a git command that emits binary stdout (e.g. ``archive``).

    stderr is decoded with surrogateescape for safe redaction; stdout stays bytes.
    """
    cmd: List[str] = ["git"]
    if git_dir is not None:
        cmd += ["--git-dir", str(git_dir)]
    cmd += list(args)
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            timeout=timeout,
            env=_git_env(),
            check=False,
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, 124, stdout=b"", stderr=f"git timed out after {timeout}s".encode())
    except OSError as exc:
        return subprocess.CompletedProcess(cmd, 127, stdout=b"", stderr=str(exc).encode())
    return proc


@dataclass
class RemoteRefResolution:
    repo: str
    repo_path: str
    policy: str
    requested_remote_ref: Optional[str]
    resolved_ref: Optional[str]
    resolved_commit: Optional[str]
    status: str
    message: str
    stderr: Optional[str] = None
    remote_url_redacted: Optional[str] = None
    remote_name: str = "origin"


@dataclass
class RemoteSnapshotResult:
    repo: str
    original_path: str
    snapshot_path: Optional[str]
    source_mode: str
    status: str
    remote_ref_policy: str
    requested_remote_ref: Optional[str]
    resolved_ref: Optional[str]
    resolved_commit: Optional[str]
    remote_url_redacted: Optional[str]
    local_repo_mutated: bool = False
    message: str = ""
    stderr: Optional[str] = None
    warnings: List[str] = field(default_factory=list)


def resolve_effective_source_mode(req) -> str:
    """Map a JobRequest onto the effective source mode.

    Explicit ``repo_source_mode`` wins. Otherwise derive from the legacy flags:
    ``pre_pull and not plan_only`` → ``local_ff``; else ``local_current``.
    """
    explicit = getattr(req, "repo_source_mode", None)
    plan_only = bool(getattr(req, "plan_only", False))
    if explicit == "remote_snapshot":
        # remote_snapshot never mutates the local repo; plan_only becomes a dry-plan.
        return "remote_snapshot"
    if explicit == "local_current":
        return "local_current"
    if explicit == "local_ff":
        # plan_only must never mutate local repos, so a fast-forward is suppressed.
        return "local_current" if plan_only else "local_ff"
    pre_pull = bool(getattr(req, "pre_pull", True))
    if pre_pull and not plan_only:
        return "local_ff"
    return "local_current"



def _read_remote_url(repo_path: Path, remote_name: str, timeout: int) -> "tuple[Optional[str], subprocess.CompletedProcess]":
    proc = _run_git(["config", "--get", f"remote.{remote_name}.url"], repo_path=repo_path, timeout=timeout)
    url = proc.stdout.strip() if proc.returncode == 0 else None
    return (url or None), proc


def _parse_remote_tracking_ref(ref: str, *, default_remote: str = "origin") -> Optional[tuple[str, str]]:
    """Normalize a ref spelling onto (remote_name, full_ref), or None if it is a SHA/unknown."""
    r = ref.strip()
    if not r or _HEX_SHA_RE.match(r):
        return None

    if r.startswith("refs/remotes/"):
        parts = r[len("refs/remotes/"):].split("/", 1)
        if len(parts) == 2:
            return parts[0], f"refs/heads/{parts[1]}"
    if r.startswith("refs/heads/"):
        return default_remote, r
    if r.startswith("refs/tags/"):
        return default_remote, r
    if "/" in r:
        parts = r.split("/", 1)
        return parts[0], f"refs/heads/{parts[1]}"

    return default_remote, f"refs/heads/{r}"


def _ls_remote_commit(remote_url: str, ref: str, timeout: int) -> "tuple[Optional[str], subprocess.CompletedProcess]":
    """Return the commit a remote ref points at via ls-remote (no fetch)."""
    if ref.startswith("refs/tags/"):
        proc = _run_git(["ls-remote", remote_url, ref, f"{ref}^{{}}"], timeout=timeout)
        sha = None
        fallback_sha = None
        if proc.returncode == 0 and proc.stdout.strip():
            for line in proc.stdout.splitlines():
                parts = line.strip().split()
                if len(parts) >= 2:
                    if parts[1] == f"{ref}^{{}}":
                        sha = parts[0]
                        break
                    if parts[1] == ref:
                        fallback_sha = parts[0]
            if not sha:
                sha = fallback_sha
        return sha, proc
    else:
        proc = _run_git(["ls-remote", remote_url, ref], timeout=timeout)
        sha = None
        if proc.returncode == 0 and proc.stdout.strip():
            sha = proc.stdout.split()[0].strip() or None
        return sha, proc


def resolve_remote_ref(
    repo_path: Path,
    *,
    remote_ref: Optional[str],
    remote_ref_policy: str,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> RemoteRefResolution:
    """Resolve which remote ref/commit a remote_snapshot job should materialize.

    Performs read-only remote queries (``config``, ``ls-remote``, local ``@{u}`` /
    branch reads). Never fetches into, mutates, or switches the local repo.
    """
    repo_path = Path(repo_path)
    repo_name = repo_path.name
    path_str = str(repo_path)

    def make(status: str, message: str, *, resolved_ref=None, resolved_commit=None,
             stderr=None, remote_url=None, remote_name="origin") -> RemoteRefResolution:
        return RemoteRefResolution(
            repo=repo_name,
            repo_path=path_str,
            policy=remote_ref_policy,
            requested_remote_ref=remote_ref,
            resolved_ref=resolved_ref,
            resolved_commit=resolved_commit,
            status=status,
            message=message,
            stderr=_redact(stderr),
            remote_url_redacted=_redact(remote_url),
            remote_name=remote_name,
        )

    version = _run_git(["--version"], timeout=timeout_seconds)
    if version.returncode != 0:
        return make(SourceStatus.ERROR, "git is not available (git --version failed)",
                    stderr=version.stderr)

    inside = _run_git(["rev-parse", "--is-inside-work-tree"], repo_path=repo_path, timeout=timeout_seconds)
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        return make(SourceStatus.ERROR, f"{repo_name} is not a git work tree", stderr=inside.stderr)

    full_ref = None

    if remote_ref:
        parsed = _parse_remote_tracking_ref(remote_ref)
        if parsed is None:
            remote_url, _ = _read_remote_url(repo_path, "origin", timeout_seconds)
            if not remote_url:
                return make(SourceStatus.MISSING_REMOTE, f"{repo_name} has no 'origin' remote configured", remote_url=remote_url)
            return make(SourceStatus.RESOLVED, f"using explicit commit SHA; availability will be verified during fetch/materialization",
                        resolved_ref=remote_ref,
                        resolved_commit=remote_ref if _HEX_SHA_RE.match(remote_ref.strip()) else None,
                        remote_url=remote_url, remote_name="origin")

        remote_name, full_ref = parsed
        remote_url, url_proc = _read_remote_url(repo_path, remote_name, timeout_seconds)
        if not remote_url:
            return make(SourceStatus.MISSING_REMOTE, f"{repo_name} has no '{remote_name}' remote configured", stderr=url_proc.stderr)

        sha, ls = _ls_remote_commit(remote_url, full_ref, timeout_seconds)
        if not sha:
            return make(SourceStatus.MISSING_REF, f"explicit remote_ref '{remote_ref}' not found on {remote_name}", stderr=ls.stderr, remote_url=remote_url, remote_name=remote_name)

        if full_ref.startswith("refs/heads/"):
            resolved_display = f"{remote_name}/{full_ref[len('refs/heads/'):]}"
        else:
            resolved_display = full_ref

        return make(SourceStatus.RESOLVED, f"resolved explicit ref to {resolved_display}",
                    resolved_ref=resolved_display, resolved_commit=sha, remote_url=remote_url, remote_name=remote_name)

    elif remote_ref_policy == "upstream":
        up = _run_git(["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
                      repo_path=repo_path, timeout=timeout_seconds)
        if up.returncode != 0 or not up.stdout.strip():
            remote_url, _ = _read_remote_url(repo_path, "origin", timeout_seconds)
            return make(SourceStatus.MISSING_REF,
                        f"{repo_name} has no upstream tracking branch (policy=upstream)",
                        stderr=up.stderr, remote_url=remote_url)

        parsed = _parse_remote_tracking_ref(up.stdout.strip())
        if not parsed:
            remote_url, _ = _read_remote_url(repo_path, "origin", timeout_seconds)
            return make(SourceStatus.MISSING_REF,
                        f"{repo_name} upstream '{up.stdout.strip()}' is not an origin branch",
                        remote_url=remote_url)

        remote_name, full_ref = parsed
        remote_url, url_proc = _read_remote_url(repo_path, remote_name, timeout_seconds)
        if not remote_url:
            return make(SourceStatus.MISSING_REMOTE, f"{repo_name} has no '{remote_name}' remote configured", stderr=url_proc.stderr)

    elif remote_ref_policy == "same_branch":
        cur = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], repo_path=repo_path, timeout=timeout_seconds)
        branch = cur.stdout.strip() if cur.returncode == 0 else ""
        remote_url, url_proc = _read_remote_url(repo_path, "origin", timeout_seconds)
        if not branch or branch == "HEAD":
            return make(SourceStatus.MISSING_REF,
                        f"{repo_name} is detached or has no current branch (policy=same_branch)",
                        stderr=cur.stderr, remote_url=remote_url)
        if not remote_url:
            return make(SourceStatus.MISSING_REMOTE, f"{repo_name} has no 'origin' remote configured", stderr=url_proc.stderr)

        remote_name = "origin"
        full_ref = f"refs/heads/{branch}"

    elif remote_ref_policy == "default_branch":
        remote_name = "origin"
        remote_url, url_proc = _read_remote_url(repo_path, "origin", timeout_seconds)
        if not remote_url:
            return make(SourceStatus.MISSING_REMOTE, f"{repo_name} has no 'origin' remote configured", stderr=url_proc.stderr)

        full_ref = _resolve_default_branch(remote_url, timeout_seconds)
        if not full_ref:
            return make(SourceStatus.MISSING_REF,
                        f"could not determine origin default branch for {repo_name}",
                        remote_url=remote_url)
    else:
        remote_url, _ = _read_remote_url(repo_path, "origin", timeout_seconds)
        return make(SourceStatus.ERROR, f"unknown remote_ref_policy '{remote_ref_policy}'",
                    remote_url=remote_url)

    sha, ls = _ls_remote_commit(remote_url, full_ref, timeout_seconds)
    if not sha:
        display = f"{remote_name}/{full_ref[len('refs/heads/'):]}" if full_ref.startswith("refs/heads/") else full_ref
        return make(SourceStatus.MISSING_REF,
                    f"{display} not found on remote for {repo_name}",
                    stderr=ls.stderr, remote_url=remote_url, remote_name=remote_name)

    display = f"{remote_name}/{full_ref[len('refs/heads/'):]}" if full_ref.startswith("refs/heads/") else full_ref
    return make(SourceStatus.RESOLVED, f"resolved to {display}",
                resolved_ref=display, resolved_commit=sha, remote_url=remote_url, remote_name=remote_name)



def _resolve_default_branch(remote_url: str, timeout: int) -> Optional[str]:
    """Prefer origin/HEAD via ls-remote --symref; fall back to 'main' if present."""
    sym = _run_git(["ls-remote", "--symref", remote_url, "HEAD"], timeout=timeout)
    if sym.returncode == 0 and sym.stdout:
        for line in sym.stdout.splitlines():
            line = line.strip()
            if line.startswith("ref:") and line.endswith("HEAD"):
                middle = line[len("ref:"):].strip().split()[0]
                parsed = _parse_remote_tracking_ref(middle)
                if parsed:
                    return parsed[1]
    main_sha, _ = _ls_remote_commit(remote_url, "refs/heads/main", timeout)
    if main_sha:
        return "refs/heads/main"
    return None


def materialize_remote_snapshot(
    repo_path: Path,
    *,
    remote_ref: Optional[str],
    remote_ref_policy: str,
    cache_root: Path,
    job_id: str,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> RemoteSnapshotResult:
    """Materialize an isolated snapshot of a remote commit and return its path.

    Never mutates the local repo. Builds a bare cache git dir under a job-bound
    directory inside ``cache_root`` and extracts ``git archive`` output safely.
    """
    repo_path = Path(repo_path)
    repo_name = repo_path.name
    original_path = str(repo_path)

    def make(status: str, message: str, *, resolution: Optional[RemoteRefResolution] = None,
             snapshot_path=None, stderr=None, warnings=None) -> RemoteSnapshotResult:
        return RemoteSnapshotResult(
            repo=repo_name,
            original_path=original_path,
            snapshot_path=snapshot_path,
            source_mode="remote_snapshot",
            status=status,
            remote_ref_policy=remote_ref_policy,
            requested_remote_ref=remote_ref,
            resolved_ref=resolution.resolved_ref if resolution else None,
            resolved_commit=resolution.resolved_commit if resolution else None,
            remote_url_redacted=resolution.remote_url_redacted if resolution else None,
            local_repo_mutated=False,
            message=message,
            stderr=_redact(stderr) if stderr else (resolution.stderr if resolution else None),
            warnings=warnings or [],
        )

    resolution = resolve_remote_ref(
        repo_path,
        remote_ref=remote_ref,
        remote_ref_policy=remote_ref_policy,
        timeout_seconds=timeout_seconds,
    )
    if resolution.status != SourceStatus.RESOLVED:
        # Map resolution failure onto a snapshot status verbatim.
        return make(resolution.status, resolution.message, resolution=resolution)

    # The snapshot tree dir is named after the repo so the scanner labels the
    # bundle with the original repo name (scan_repo derives the name from path).
    base = Path(cache_root) / SNAPSHOT_DIR_NAME / job_id
    cache_git_dir = base / f"{repo_name}.git"
    snapshot_dir = base / repo_name
    try:
        cache_git_dir.mkdir(parents=True, exist_ok=True)
        base_resolved = base.resolve()
        snapshot_parent_resolved = snapshot_dir.parent.resolve()

        if snapshot_parent_resolved != base_resolved:
            return make(SourceStatus.ERROR, f"snapshot directory parent escaped job cache for {repo_name}", resolution=resolution)

        if snapshot_dir.exists() or snapshot_dir.is_symlink():
            if snapshot_dir.is_symlink():
                return make(SourceStatus.ERROR, f"snapshot directory is a symlink for {repo_name}", resolution=resolution)
            if not snapshot_dir.is_dir():
                return make(SourceStatus.ERROR, f"snapshot path exists but is not a directory for {repo_name}", resolution=resolution)
            snapshot_resolved = snapshot_dir.resolve()
            if snapshot_resolved != (base_resolved / repo_name):
                return make(SourceStatus.ERROR, f"snapshot directory escaped job cache for {repo_name}", resolution=resolution)
            shutil.rmtree(snapshot_dir)

        snapshot_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return make(SourceStatus.ERROR, f"could not create snapshot dirs for {repo_name}",
                    resolution=resolution, stderr=str(exc))

    # Bare cache repo (isolated from the user's repo).
    init = _run_git(["init", "--bare", str(cache_git_dir)], timeout=timeout_seconds)
    if init.returncode != 0:
        return make(SourceStatus.ERROR, f"git init --bare failed for {repo_name}",
                    resolution=resolution, stderr=init.stderr)


    remote_name = resolution.remote_name
    remote_url, url_proc = _read_remote_url(repo_path, remote_name, timeout_seconds)
    if not remote_url:
        return make(SourceStatus.MISSING_REMOTE, f"{repo_name} has no '{remote_name}' remote configured",
                    resolution=resolution, stderr=url_proc.stderr)

    fetch = _run_git(
        [
            "fetch",
            "--prune",
            remote_url,
            f"+refs/heads/*:refs/remotes/{remote_name}/*",
            "+refs/tags/*:refs/tags/*"
        ],
        git_dir=cache_git_dir,
        timeout=timeout_seconds,
    )
    if fetch.returncode != 0:
        return make(SourceStatus.FETCH_FAILED, f"git fetch failed for {repo_name} snapshot",
                    resolution=resolution, stderr=fetch.stderr)

    rev_target = resolution.resolved_commit or resolution.resolved_ref or ""
    if resolution.resolved_ref and resolution.resolved_ref.startswith(f"{remote_name}/"):
        rev_target = f"refs/remotes/{resolution.resolved_ref}"
    elif resolution.resolved_ref and resolution.resolved_ref.startswith("refs/tags/"):
        rev_target = resolution.resolved_ref

    rev = _run_git(["rev-parse", "--verify", f"{rev_target}^{{commit}}"], git_dir=cache_git_dir, timeout=timeout_seconds)

    direct_fetch_stderr = None
    if rev.returncode != 0 and resolution.resolved_ref and _HEX_SHA_RE.match(resolution.resolved_ref):
        direct_fetch = _run_git(
            ["fetch", "--prune", remote_url, resolution.resolved_ref],
            git_dir=cache_git_dir,
            timeout=timeout_seconds,
        )
        if direct_fetch.returncode == 0:
            rev = _run_git(["rev-parse", "--verify", f"{rev_target}^{{commit}}"], git_dir=cache_git_dir, timeout=timeout_seconds)
        else:
            direct_fetch_stderr = direct_fetch.stderr

    if rev.returncode != 0:
        stderr_to_use = direct_fetch_stderr or rev.stderr
        return make(SourceStatus.MISSING_REF,
                    f"could not resolve {resolution.resolved_ref} to a commit in {repo_name} cache",
                    resolution=resolution, stderr=stderr_to_use)
    commit = rev.stdout.strip()
    resolution.resolved_commit = commit

    archive = _run_git_binary(["archive", "--format=tar", commit], git_dir=cache_git_dir, timeout=timeout_seconds)
    if archive.returncode != 0:
        stderr_txt = archive.stderr.decode("utf-8", errors="surrogateescape") if isinstance(archive.stderr, bytes) else archive.stderr
        return make(SourceStatus.ARCHIVE_FAILED, f"git archive failed for {repo_name}",
                    resolution=resolution, stderr=stderr_txt)

    try:
        safe_extract_tar(archive.stdout, snapshot_dir)
    except SnapshotExtractionError as exc:
        return make(SourceStatus.EXTRACT_FAILED, f"unsafe tar member while extracting {repo_name} snapshot: {exc}",
                    resolution=resolution, stderr=str(exc))
    except (tarfile.TarError, OSError) as exc:
        return make(SourceStatus.EXTRACT_FAILED, f"failed to extract {repo_name} snapshot",
                    resolution=resolution, stderr=str(exc))

    warnings = _detect_snapshot_warnings(snapshot_dir)
    return make(
        SourceStatus.SNAPSHOT_CREATED,
        f"materialized {resolution.resolved_ref} ({commit[:12]}) for {repo_name}",
        resolution=resolution,
        snapshot_path=str(snapshot_dir),
        warnings=warnings,
    )


class SnapshotExtractionError(Exception):
    """Raised when a tar member would escape the snapshot directory."""


def safe_extract_tar(data: bytes, dest: Path) -> None:
    """Extract a tar byte stream into ``dest``, rejecting any escaping member.

    Defences:
    * no absolute member paths;
    * no ``..`` traversal (final resolved path must stay under ``dest``);
    * symlink/hardlink members whose target resolves outside ``dest`` are rejected.
    """
    dest = Path(dest).resolve()
    dest.mkdir(parents=True, exist_ok=True)

    def _within(target: Path) -> bool:
        try:
            resolved = target.resolve()
        except OSError:
            return False
        return resolved == dest or dest in resolved.parents

    with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as tar:
        for member in tar.getmembers():
            name = member.name
            if name.startswith("/") or os.path.isabs(name):
                raise SnapshotExtractionError(f"absolute path member: {name!r}")
            member_target = (dest / name)
            # Resolve without following the (not-yet-created) member itself.
            if not _within(dest / name):
                raise SnapshotExtractionError(f"path traversal member: {name!r}")

            if member.issym() or member.islnk():
                link = member.linkname
                if os.path.isabs(link):
                    raise SnapshotExtractionError(f"absolute link target: {name!r} -> {link!r}")
                # Hardlink targets are archive-relative; symlink targets are
                # relative to the member's own directory.
                if member.islnk():
                    link_resolved = dest / link
                else:
                    link_resolved = member_target.parent / link
                if not _within(link_resolved):
                    raise SnapshotExtractionError(f"escaping link: {name!r} -> {link!r}")

        # Re-open for extraction (getmembers consumed the stream once).
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as tar:
        for member in tar.getmembers():
            tar.extract(member, path=dest)


def _detect_snapshot_warnings(snapshot_dir: Path) -> List[str]:
    """Report v1 known limits: unexpanded submodules and un-smudged LFS content."""
    warnings: List[str] = []
    gitmodules = snapshot_dir / ".gitmodules"
    if gitmodules.is_file():
        warnings.append(WARN_SUBMODULES_NOT_EXPANDED)

    if _has_lfs_markers(snapshot_dir):
        warnings.append(WARN_LFS_NOT_SMUDGED)
    return warnings


def _has_lfs_markers(snapshot_dir: Path) -> bool:
    """True if .gitattributes declares an LFS filter or an LFS pointer is found."""
    gitattributes = snapshot_dir / ".gitattributes"
    try:
        if gitattributes.is_file():
            text = gitattributes.read_text(encoding="utf-8", errors="surrogateescape")
            if "filter=lfs" in text:
                return True
    except OSError:
        logger.debug("Could not read .gitattributes for LFS detection.", exc_info=True)

    # Bounded scan for the canonical LFS pointer signature in small files.
    pointer_sig = "version https://git-lfs.github.com/spec"
    scanned = 0
    for path in snapshot_dir.rglob("*"):
        if scanned >= 2000:
            break
        if not path.is_file() or path.is_symlink():
            continue
        try:
            if path.stat().st_size > 1024:
                continue
            with path.open("r", encoding="utf-8", errors="surrogateescape") as fh:
                head = fh.read(64)
        except OSError:
            continue
        scanned += 1
        if head.startswith(pointer_sig):
            return True
    return False
