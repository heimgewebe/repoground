"""RepoGround source acquisition v1 — remote snapshot materialization.

This module adds an explicitly *non-mutating* way to acquire the content RepoGround
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
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 60

# Job-bound snapshot root, created under the (already validated) merges_dir.
SNAPSHOT_DIR_NAME = ".repoground-source-snapshots"
DEFAULT_SNAPSHOT_RETENTION_COUNT = 3
DEFAULT_SNAPSHOT_MAX_AGE_HOURS = 24
DEFAULT_SNAPSHOT_MAX_BYTES = 2 * 1024 * 1024 * 1024

# Report warning codes (v1 known limits).
WARN_SUBMODULES_NOT_EXPANDED = "submodules_not_expanded"
WARN_LFS_NOT_SMUDGED = "lfs_not_smudged"


def _allocated_tree_bytes(path: Path) -> int:
    total = 0
    for root, dirs, files in os.walk(path, followlinks=False):
        root_path = Path(root)
        dirs[:] = [name for name in dirs if not (root_path / name).is_symlink()]
        for name in files:
            candidate = root_path / name
            if candidate.is_symlink():
                continue
            try:
                total += candidate.stat().st_blocks * 512
            except FileNotFoundError:
                continue
    return total


def _snapshot_retention_report(
    root: Path,
    *,
    protected: set[str],
    keep: int,
    max_age_hours: int,
    max_bytes: int,
    apply: bool,
) -> dict:
    return {
        "status": "ok",
        "mode": "apply" if apply else "dry-run",
        "root": str(root),
        "keep": keep,
        "max_age_hours": max_age_hours,
        "max_bytes": max_bytes,
        "protected_job_ids": sorted(protected),
        "retained": [],
        "protected": [],
        "would_remove": [],
        "removed": [],
        "would_remove_bytes": 0,
        "removed_bytes": 0,
    }


def _collect_snapshot_rows(root: Path) -> tuple[list[dict], list[str]]:
    rows: list[dict] = []
    unsafe: list[str] = []
    for child in root.iterdir():
        if child.is_symlink() or not child.is_dir():
            unsafe.append(str(child))
            continue
        try:
            stat_result = child.stat()
        except FileNotFoundError:
            continue
        rows.append(
            {
                "path": child,
                "job_id": child.name,
                "mtime": stat_result.st_mtime,
                "bytes": _allocated_tree_bytes(child),
            }
        )
    return rows, unsafe


def _partition_snapshot_rows(
    rows: list[dict],
    *,
    protected: set[str],
    keep: int,
    current_time: float,
    max_age_hours: int,
) -> tuple[list[dict], list[dict], list[str]]:
    rows.sort(key=lambda row: (row["mtime"], row["job_id"]), reverse=True)
    unprotected = [row for row in rows if row["job_id"] not in protected]
    retained_ids = {row["job_id"] for row in unprotected[:keep]}
    retained: list[dict] = []
    removable: list[dict] = []
    protected_paths: list[str] = []
    max_age_seconds = max_age_hours * 3600

    for row in rows:
        if row["job_id"] in protected:
            protected_paths.append(str(row["path"]))
            retained.append(row)
        elif (
            row["job_id"] not in retained_ids
            or current_time - row["mtime"] > max_age_seconds
        ):
            removable.append(row)
        else:
            retained.append(row)
    return retained, removable, protected_paths


def _enforce_snapshot_size_limit(
    retained: list[dict],
    removable: list[dict],
    *,
    protected: set[str],
    max_bytes: int,
) -> None:
    retained_unprotected = [row for row in retained if row["job_id"] not in protected]
    retained_unprotected.sort(
        key=lambda row: (row["mtime"], row["job_id"]), reverse=True
    )
    retained_bytes = sum(row["bytes"] for row in retained_unprotected)
    while retained_bytes > max_bytes and retained_unprotected:
        oldest = retained_unprotected.pop()
        retained_bytes -= oldest["bytes"]
        retained.remove(oldest)
        removable.append(oldest)


def _remove_snapshot_rows(root: Path, removable: list[dict]) -> list[str]:
    root_resolved = root.resolve()
    removed: list[str] = []
    for row in removable:
        candidate = row["path"]
        if (
            candidate.is_symlink()
            or not candidate.is_dir()
            or candidate.resolve().parent != root_resolved
        ):
            raise RuntimeError(
                f"snapshot cleanup target changed or escaped root: {candidate}"
            )
        shutil.rmtree(candidate)
        removed.append(str(candidate))
    return removed


def prune_source_snapshots(
    cache_root: Path,
    *,
    protected_job_ids: set[str] | None = None,
    keep: int = DEFAULT_SNAPSHOT_RETENTION_COUNT,
    max_age_hours: int = DEFAULT_SNAPSHOT_MAX_AGE_HOURS,
    max_bytes: int = DEFAULT_SNAPSHOT_MAX_BYTES,
    apply: bool = False,
    now: float | None = None,
) -> dict:
    """Plan or apply bounded cleanup of job-scoped remote source snapshots.

    Active job ids are always protected. Any symlink or non-directory child blocks
    the whole cleanup before deletion, rather than guessing what is safe.
    """
    if keep < 0 or max_age_hours < 0 or max_bytes < 0:
        raise ValueError("snapshot retention bounds must be non-negative")

    protected = set(protected_job_ids or set())
    root = Path(cache_root) / SNAPSHOT_DIR_NAME
    report = _snapshot_retention_report(
        root,
        protected=protected,
        keep=keep,
        max_age_hours=max_age_hours,
        max_bytes=max_bytes,
        apply=apply,
    )
    if not root.exists():
        return report
    if root.is_symlink() or not root.is_dir():
        report.update(status="blocked", error="snapshot root is not a real directory")
        return report

    rows, unsafe = _collect_snapshot_rows(root)
    if unsafe:
        report.update(
            status="blocked",
            error="unsafe snapshot children",
            unsafe_children=sorted(unsafe),
        )
        return report

    retained, removable, protected_paths = _partition_snapshot_rows(
        rows,
        protected=protected,
        keep=keep,
        current_time=time.time() if now is None else now,
        max_age_hours=max_age_hours,
    )
    _enforce_snapshot_size_limit(
        retained, removable, protected=protected, max_bytes=max_bytes
    )
    removable.sort(key=lambda row: (row["mtime"], row["job_id"]))
    report["protected"] = protected_paths
    report["retained"] = sorted(str(row["path"]) for row in retained)
    bytes_to_remove = sum(row["bytes"] for row in removable)

    if apply:
        report["removed"] = _remove_snapshot_rows(root, removable)
        report["removed_bytes"] = bytes_to_remove
    else:
        report["would_remove"] = [str(row["path"]) for row in removable]
        report["would_remove_bytes"] = bytes_to_remove
    return report


def remove_source_snapshot(cache_root: Path, job_id: str) -> bool:
    """Remove exactly one job snapshot with path-containment checks."""
    root = Path(cache_root) / SNAPSHOT_DIR_NAME
    target = root / job_id
    if not target.exists():
        return False
    if root.is_symlink() or target.is_symlink() or not target.is_dir():
        raise RuntimeError(f"unsafe source snapshot path: {target}")
    if target.resolve().parent != root.resolve():
        raise RuntimeError(f"source snapshot escaped root: {target}")
    shutil.rmtree(target)
    return True


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

    Defensive: ``JobRequest`` already rejects contradictions at /api/jobs, but
    internal objects, stored jobs, ``model_construct()`` and tests can bypass
    pydantic. So an *explicit* mode is re-run through the same central
    ``validate_source_mode_request`` the API uses — a contradictory state
    (``local_ff`` + ``plan_only``, ``local_current`` + explicit ``pre_pull``,
    an unknown mode, …) raises here rather than being silently smoothed away.
    """
    explicit = getattr(req, "repo_source_mode", None)
    plan_only = bool(getattr(req, "plan_only", False))

    if explicit is None:
        # Legacy: derive purely from pre_pull/plan_only. There is no explicit mode
        # to contradict, so there is nothing for the validator to reject here.
        pre_pull = bool(getattr(req, "pre_pull", True))
        return "local_ff" if pre_pull and not plan_only else "local_current"

    # ``pre_pull`` is only an explicit choice when the object records it as set
    # (pydantic's ``model_fields_set``). On a plain JobRequest with just a
    # ``repo_source_mode``, ``pre_pull`` is the inert default and must not, on its
    # own, turn a bare explicit mode into a conflict. Objects without that marker
    # (test doubles, dict-shaped stored jobs) give no explicit/default signal, so
    # ``pre_pull`` is treated as unset to preserve the API's legacy tolerance.
    fields_set = getattr(req, "model_fields_set", None)
    if fields_set is not None and "pre_pull" in fields_set:
        pre_pull = bool(getattr(req, "pre_pull", False))
    else:
        pre_pull = None

    validate_source_mode_request(
        repo_source_mode=explicit,
        pre_pull=pre_pull,
        plan_only=plan_only,
        remote_ref=getattr(req, "remote_ref", None),
        remote_ref_policy=getattr(req, "remote_ref_policy", None),
    )
    return explicit


class SourceModeConflictError(ValueError):
    """Raised when a source-mode request describes a contradictory state.

    Subclasses ``ValueError`` so a pydantic ``model_validator`` re-raises it as a
    validation error (HTTP 422) and CLI/headless surfaces can map it onto exit 2.
    """


def validate_source_mode_request(
    *,
    repo_source_mode: Optional[str],
    pre_pull: Optional[bool],
    plan_only: bool,
    remote_ref: Optional[str],
    remote_ref_policy: Optional[str],
) -> None:
    """Central source-mode control plane shared by API, CLI, WebUI and headless.

    ``pre_pull`` is tri-state: ``True``/``False`` for an *explicit* choice and
    ``None`` when the caller did not set it (legacy default). Only explicit
    contradictions are rejected so a bare ``repo_source_mode`` still works.

    ``remote_ref`` and a non-default ``remote_ref_policy`` only carry meaning for
    ``remote_snapshot``; on any other mode they would silently do nothing, so they
    are rejected to prevent hash/semantic drift. The default policy (``upstream``
    or ``None``) is inert on local modes and therefore tolerated.

    Raises ``SourceModeConflictError`` on any contradiction; returns ``None`` when
    the request is coherent. Never performs I/O.
    """
    allowed_modes = {None, "local_current", "local_ff", "remote_snapshot"}
    if repo_source_mode not in allowed_modes:
        raise SourceModeConflictError(f"unknown repo_source_mode: {repo_source_mode!r}")

    has_remote_ref = bool(remote_ref and str(remote_ref).strip())
    non_default_policy = remote_ref_policy is not None and remote_ref_policy != "upstream"

    if repo_source_mode == "remote_snapshot":
        if pre_pull is True:
            raise SourceModeConflictError(
                "remote_snapshot never mutates the local repo; pre_pull must not be true. "
                "Use local_ff for a fast-forward pre-pull."
            )
        return

    # Every non-remote mode (local_current, local_ff, or the legacy None default):
    # remote ref selection must not be smuggled in where it has no effect.
    if has_remote_ref:
        raise SourceModeConflictError(
            "remote_ref is only valid with repo_source_mode='remote_snapshot'."
        )
    if non_default_policy:
        raise SourceModeConflictError(
            "a non-default remote_ref_policy is only valid with "
            "repo_source_mode='remote_snapshot'."
        )

    if repo_source_mode == "local_current":
        if pre_pull is True:
            raise SourceModeConflictError(
                "local_current scans the working tree as-is and does not fast-forward; "
                "pre_pull must not be true."
            )
        return

    if repo_source_mode == "local_ff":
        if pre_pull is False:
            raise SourceModeConflictError(
                "local_ff implies a fast-forward pre-pull; pre_pull must not be false."
            )
        if plan_only:
            raise SourceModeConflictError(
                "local_ff cannot be combined with plan_only: local_ff would fast-forward "
                "the local repo, but plan_only must not cause any local mutation. "
                "Use local_current for plan-only, or remote_snapshot for a non-mutating remote check."
            )
        return

    # repo_source_mode is None → legacy behaviour derived from pre_pull/plan_only.
    # Nothing further to validate (remote_ref / non-default policy already rejected).
    return



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
    remote_ref = (remote_ref.strip() or None) if remote_ref else None

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
            return make(SourceStatus.RESOLVED, "using explicit commit SHA; availability will be verified during fetch/materialization",
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
    remote_ref = (remote_ref.strip() or None) if remote_ref else None

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
    # Validate the job-bound snapshot root before any mkdir that could follow a
    # symlink. The service normally creates safe job ids, but this helper also
    # defends itself when called directly from tests/headless clients.
    job_id_text = str(job_id)
    if not job_id_text or job_id_text in {".", ".."} or "/" in job_id_text or "\\" in job_id_text:
        return make(SourceStatus.ERROR, f"invalid snapshot job_id for {repo_name}", resolution=resolution)

    snapshots_root = Path(cache_root) / SNAPSHOT_DIR_NAME
    base = snapshots_root / job_id_text
    cache_git_dir = base / f"{repo_name}.git"
    snapshot_dir = base / repo_name
    try:
        if snapshots_root.is_symlink():
            return make(SourceStatus.ERROR, f"snapshot root is a symlink for {repo_name}", resolution=resolution)
        snapshots_root.mkdir(parents=True, exist_ok=True)
        snapshots_root_resolved = snapshots_root.resolve()

        if base.exists() or base.is_symlink():
            if base.is_symlink():
                return make(SourceStatus.ERROR, f"snapshot job directory is a symlink for {repo_name}", resolution=resolution)
            if not base.is_dir():
                return make(SourceStatus.ERROR, f"snapshot job path exists but is not a directory for {repo_name}", resolution=resolution)
        else:
            base.mkdir(parents=False, exist_ok=False)

        base_resolved = base.resolve()
        if base_resolved.parent != snapshots_root_resolved:
            return make(SourceStatus.ERROR, f"snapshot job directory escaped snapshot root for {repo_name}", resolution=resolution)

        if cache_git_dir.exists() or cache_git_dir.is_symlink():
            if cache_git_dir.is_symlink():
                return make(SourceStatus.ERROR, f"snapshot git cache is a symlink for {repo_name}", resolution=resolution)
            if not cache_git_dir.is_dir():
                return make(SourceStatus.ERROR, f"snapshot git cache path exists but is not a directory for {repo_name}", resolution=resolution)

        cache_git_dir.mkdir(parents=True, exist_ok=True)
        cache_git_resolved = cache_git_dir.resolve()
        if cache_git_resolved.parent != base_resolved:
            return make(SourceStatus.ERROR, f"snapshot git cache escaped job cache for {repo_name}", resolution=resolution)

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
            "--no-write-fetch-head",
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
            ["fetch", "--no-write-fetch-head", "--prune", remote_url, resolution.resolved_ref],
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
    """Extract a tar byte stream into ``dest`` with a hardened, manual writer.

    v1 policy — security before convenience (see the source-acquisition blueprint):

    * Only regular files and ordinary directories are extracted. Symlinks,
      hardlinks, FIFOs, character/block devices and any other special member type
      are rejected outright (a ``git archive --format=tar`` of normal source code
      contains none of these except, possibly, symlinks which v1 deliberately rejects).
    * No absolute member paths and no ``..`` traversal — the destination path of
      every member must stay under ``dest``.
    * No member is written through an existing symlink: every path component of
      every member is checked, so a symlink already present in ``dest`` (or one
      that an earlier member tried to introduce — impossible here, links are
      rejected) can never be followed out of the tree.

    ``tarfile.extract`` is never used: each regular file is streamed and written
    by hand so member metadata can never redirect the write.
    """
    dest = Path(dest).resolve()
    try:
        dest.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise SnapshotExtractionError(
            f"could not create extraction destination {dest}: {exc}"
        ) from exc

    def _normalized_parts(name: str) -> tuple:
        # Reject absolute paths and any traversal; return the safe relative parts.
        if not name or name.startswith("/") or os.path.isabs(name):
            raise SnapshotExtractionError(f"absolute path member: {name!r}")
        # Normalize separators (git archive emits POSIX paths).
        parts = [p for p in name.replace("\\", "/").split("/") if p not in ("", ".")]
        if any(p == ".." for p in parts):
            raise SnapshotExtractionError(f"path traversal member: {name!r}")
        if not parts:
            raise SnapshotExtractionError(f"empty member path: {name!r}")
        # Defensive: the joined, normalized path must remain under dest.
        joined = os.path.normpath(str(dest.joinpath(*parts)))
        joined_path = Path(joined)
        if joined_path != dest and dest not in joined_path.parents:
            raise SnapshotExtractionError(f"path traversal member: {name!r}")
        return tuple(parts)

    def _assert_no_symlink_ancestor(parts: tuple) -> None:
        # None of the on-disk path components leading to (and including, for dirs)
        # the target may be an existing symlink we would otherwise write through.
        cur = dest
        for part in parts:
            cur = cur / part
            if cur.is_symlink():
                raise SnapshotExtractionError(f"symlink in target path: {cur}")

    with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as tar:
        for member in tar.getmembers():
            name = member.name

            if member.issym() or member.islnk():
                raise SnapshotExtractionError(f"link member not allowed: {name!r}")
            if member.isdev() or member.isfifo():
                raise SnapshotExtractionError(f"special member not allowed: {name!r}")
            if not (member.isfile() or member.isdir()):
                raise SnapshotExtractionError(f"unsupported member type: {name!r}")

            parts = _normalized_parts(name)

            if member.isdir():
                _assert_no_symlink_ancestor(parts)
                target = dest.joinpath(*parts)
                if target.is_symlink():
                    raise SnapshotExtractionError(f"symlink in target path: {target}")
                try:
                    target.mkdir(parents=True, exist_ok=True)
                except OSError as exc:
                    raise SnapshotExtractionError(
                        f"could not create directory member {name!r}: {exc}"
                    ) from exc
                continue

            # Regular file: validate the parent chain, create dirs, write by hand.
            _assert_no_symlink_ancestor(parts[:-1])
            parent = dest.joinpath(*parts[:-1]) if len(parts) > 1 else dest
            try:
                parent.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise SnapshotExtractionError(
                    f"could not create parent directory for member {name!r}: {exc}"
                ) from exc
            target = dest.joinpath(*parts)
            if target.is_symlink():
                raise SnapshotExtractionError(f"symlink in target path: {target}")
            extracted = tar.extractfile(member)
            if extracted is None:
                raise SnapshotExtractionError(
                    f"could not extract regular file member: {name!r}"
                )
            # Stream the member in chunks: never read a whole file into memory, so a
            # hostile or oversized archive cannot blow up the resident set.
            try:
                with open(target, "wb") as fh:
                    shutil.copyfileobj(extracted, fh)
            except OSError as exc:
                raise SnapshotExtractionError(
                    f"could not write member {name!r}: {exc}"
                ) from exc
            finally:
                extracted.close()
            # Preserve only the low permission bits; never setuid/setgid/sticky.
            try:
                os.chmod(target, member.mode & 0o777)
            except OSError:
                logger.debug("Could not chmod extracted snapshot file %s", target, exc_info=True)


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
