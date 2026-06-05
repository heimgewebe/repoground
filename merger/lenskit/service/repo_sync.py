"""Bounded repo-sync mutation: fast-forward-only pre-pull preflight.

This module implements a *narrow*, locally authorized repo preparation step that
runs before an rLens scan/merge. It is classified in ``docs/service-api.md`` as a
``bounded repo-sync mutation``: it may update a local working tree, but only via a
clean, fast-forward-only merge of the already-configured upstream tracking branch.

Hard guarantees (see ``docs/service-api.md`` — Mutation Boundary Classification):

* No ``shell=True`` — every git invocation is an explicit argument list.
* No ``git pull`` — fetch and fast-forward-only merge are separate, inspectable steps.
* No ``reset`` / ``rebase`` / ``stash`` / ``checkout`` / ``switch`` / ``clean``.
* Never discards local changes and never deletes untracked files.
* Never switches branches and never resolves conflicts automatically.
* Never prompts for credentials (``GIT_TERMINAL_PROMPT=0``); auth-required fetches
  fail fast rather than hanging interactively.

A dirty (tracked) working tree, a diverged branch, or a failed fetch/merge is a
hard failure. A non-git path, a missing upstream, or a locally-ahead branch is a
warn-and-continue case.
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 60


class PrePullStatus:
    """Terminal status vocabulary for a single repo pre-pull attempt."""

    # Warn-and-continue (the repo simply cannot/need-not be fast-forwarded)
    SKIPPED_NOT_GIT = "skipped_not_git"
    SKIPPED_NO_UPSTREAM = "skipped_no_upstream"
    LOCAL_AHEAD = "local_ahead"

    # Plan-phase only: a fast-forward is possible but has NOT been applied yet.
    # Never a final success — it must be turned into FAST_FORWARDED by the apply
    # phase (or HEAD_CHANGED / MERGE_FAILED if the apply is no longer safe).
    PLANNED_FAST_FORWARD = "planned_fast_forward"

    # Success (scan proceeds)
    UP_TO_DATE = "up_to_date"
    FAST_FORWARDED = "fast_forwarded"

    # Hard failure (job must stop before scanning stale/ambiguous state)
    DIRTY = "dirty"
    DIVERGED = "diverged"
    FETCH_FAILED = "fetch_failed"
    MERGE_FAILED = "merge_failed"
    # HEAD moved between plan and apply (a concurrent local commit/checkout):
    # the planned fast-forward is no longer valid, so we refuse rather than guess.
    HEAD_CHANGED = "head_changed"
    # Untracked files in the working tree share a path with files the upstream
    # fast-forward would write. git merge --ff-only would abort with an error,
    # but only in the apply phase — detecting this in the plan phase prevents
    # any repo from being partially fast-forwarded in a multi-repo batch.
    UNTRACKED_WOULD_BE_OVERWRITTEN = "untracked_would_be_overwritten"
    ERROR = "error"


# Statuses that must abort the job. Scanning would otherwise either lose local
# work (dirty/diverged) or silently dump a stale tree (fetch/merge failure).
# HEAD_CHANGED aborts because a concurrent local change invalidated the plan.
HARD_FAIL_STATUSES = frozenset(
    {
        PrePullStatus.DIRTY,
        PrePullStatus.DIVERGED,
        PrePullStatus.FETCH_FAILED,
        PrePullStatus.MERGE_FAILED,
        PrePullStatus.HEAD_CHANGED,
        PrePullStatus.UNTRACKED_WOULD_BE_OVERWRITTEN,
        PrePullStatus.ERROR,
    }
)

# Statuses that are surfaced as warnings but do not block the scan.
WARN_STATUSES = frozenset(
    {
        PrePullStatus.SKIPPED_NOT_GIT,
        PrePullStatus.SKIPPED_NO_UPSTREAM,
        PrePullStatus.LOCAL_AHEAD,
    }
)

# Statuses that represent a clean, completed pre-pull.
SUCCESS_STATUSES = frozenset(
    {
        PrePullStatus.UP_TO_DATE,
        PrePullStatus.FAST_FORWARDED,
    }
)

# Plan statuses whose plans still need an apply phase to reach a final status.
PLAN_APPLY_STATUSES = frozenset(
    {
        PrePullStatus.PLANNED_FAST_FORWARD,
    }
)

# When the *running rLens code repo itself* reaches one of these states, the
# operator must be reminded to restart the service: a live Python process does
# not reload modules just because files on disk changed. Only an *actual*
# fast-forward (files changed) warrants the reminder — not up_to_date/local_ahead.
SELF_REPO_NOTICE_STATUSES = frozenset(
    {
        PrePullStatus.FAST_FORWARDED,
    }
)


@dataclass
class PrePullResult:
    """Structured, report-producing outcome of a single repo pre-pull."""

    repo: str
    path: str
    status: str
    changed: bool = False
    before_head: Optional[str] = None
    after_head: Optional[str] = None
    upstream: Optional[str] = None
    message: str = ""
    stderr: Optional[str] = None


@dataclass
class PrePullPlan:
    """Outcome of the *plan* phase (read + fetch + analyze, no working-tree merge).

    A plan with ``needs_apply=True`` (status ``PLANNED_FAST_FORWARD``) describes a
    fast-forward that is safe *now* but has not been executed. The apply phase
    re-verifies HEAD before merging. Plans with hard-fail/warn/up-to-date statuses
    are terminal and carry through unchanged.
    """

    repo: str
    path: str
    status: str
    changed: bool = False
    before_head: Optional[str] = None
    after_head: Optional[str] = None
    upstream: Optional[str] = None
    message: str = ""
    stderr: Optional[str] = None
    needs_apply: bool = False


# Mask credentials that git can echo in remote URLs.
# Handles both https://user:token@host and https://token@host forms.
_CREDENTIAL_RE = re.compile(r"(https?://)(?:[^/\s:@]+:)?[^/\s@]+@")


def _redact(text: Optional[str]) -> Optional[str]:
    """Strip embedded credentials from git stderr before it is stored/logged."""
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
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess:
    """Run a single git command as an explicit arg list (never ``shell=True``).

    Timeouts and OS-level launch errors are converted into a non-zero
    ``CompletedProcess`` so callers can branch on ``returncode`` uniformly
    instead of handling exceptions at every call site.
    """
    cmd: List[str] = ["git"]
    if repo_path is not None:
        cmd += ["-C", str(repo_path)]
    cmd += list(args)
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=_git_env(),
            check=False,
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, 124, stdout="", stderr=f"git timed out after {timeout}s")
    except OSError as exc:  # e.g. git binary missing
        return subprocess.CompletedProcess(cmd, 127, stdout="", stderr=str(exc))


def is_self_repo(repo_path: Path) -> bool:
    """True if ``repo_path`` contains the running rLens code or the process CWD.

    Used only to attach a restart reminder — never to gate or skip the pre-pull.
    """
    try:
        resolved = repo_path.resolve()
    except OSError:
        return False

    candidates: List[Path] = []
    try:
        candidates.append(Path(__file__).resolve())
    except OSError:
        # Best-effort only: if the module path cannot be resolved in this runtime
        # context, skip this candidate and continue self-repo detection.
        logger.debug("Unable to resolve __file__ for self-repo detection.", exc_info=True)
    try:
        candidates.append(Path.cwd().resolve())
    except OSError:
        # Best-effort only: if resolving CWD fails, skip this candidate and continue
        # evaluating other paths for self-repo detection.
        logger.debug("Unable to resolve cwd for self-repo detection.", exc_info=True)

    for candidate in candidates:
        if candidate == resolved or resolved in candidate.parents:
            return True
    return False


def _split_git_z(stdout: str) -> List[str]:
    """Split NUL-separated git output (``-z``) into a list, dropping empties.

    Using ``-z`` (and this splitter) avoids git's path quoting/escaping for paths
    with spaces, unicode, or special characters, which ``--name-only`` without
    ``-z`` would otherwise mangle.
    """
    if not stdout:
        return []
    return [part for part in stdout.split("\0") if part]


def _path_collides(a: str, b: str) -> bool:
    """True if two repo-relative paths conflict as file-vs-file or file-vs-dir.

    A fast-forward that writes ``b`` overwrites a local untracked ``a`` when the
    paths are equal, or when one is a directory prefix of the other (e.g. local
    untracked ``foo`` vs upstream ``foo/bar``, or vice versa).
    """
    return a == b or a.startswith(b + "/") or b.startswith(a + "/")


def plan_pre_pull_repo(repo_path: Path, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS) -> PrePullPlan:
    """Plan phase: read + fetch + fast-forward analysis. Never merges/mutates HEAD.

    Returns a :class:`PrePullPlan`. A ``PLANNED_FAST_FORWARD`` plan (``needs_apply``)
    means a clean fast-forward is possible; call :func:`apply_pre_pull_plan` to
    execute it. All other statuses are terminal. Never raises for ordinary git
    states. See module docstring for the (deliberately narrow) git operations used.
    """
    repo_path = Path(repo_path)
    repo_name = repo_path.name
    path_str = str(repo_path)

    def make(status: str, message: str = "", **kwargs) -> PrePullPlan:
        return PrePullPlan(repo=repo_name, path=path_str, status=status, message=message, **kwargs)

    # 1. Is git available at all?
    version = _run_git(["--version"], timeout=timeout_seconds)
    if version.returncode != 0:
        return make(
            PrePullStatus.ERROR,
            "git is not available (git --version failed)",
            stderr=_redact(version.stderr),
        )

    # 2. Is the path a git work tree? If not, skip (warn-and-continue).
    inside = _run_git(["rev-parse", "--is-inside-work-tree"], repo_path=repo_path, timeout=timeout_seconds)
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        return make(
            PrePullStatus.SKIPPED_NOT_GIT,
            f"{repo_name} is not a git work tree; skipping pre-pull",
        )

    # 3. Record current HEAD (may be unborn on a fresh repo → tolerated).
    head = _run_git(["rev-parse", "HEAD"], repo_path=repo_path, timeout=timeout_seconds)
    before_head = head.stdout.strip() if head.returncode == 0 else None

    # 4. Refuse to touch a dirty *tracked* tree. Untracked files do not block.
    status = _run_git(
        ["status", "--porcelain=v1", "--untracked-files=no"],
        repo_path=repo_path,
        timeout=timeout_seconds,
    )
    if status.returncode != 0:
        return make(
            PrePullStatus.ERROR,
            f"git status failed for {repo_name}",
            before_head=before_head,
            stderr=_redact(status.stderr),
        )
    if status.stdout.strip():
        return make(
            PrePullStatus.DIRTY,
            f"{repo_name} has uncommitted tracked changes; refusing pre-pull",
            before_head=before_head,
        )

    # 5. Does the current branch track an upstream? If not, skip.
    upstream_proc = _run_git(
        ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
        repo_path=repo_path,
        timeout=timeout_seconds,
    )
    if upstream_proc.returncode != 0:
        return make(
            PrePullStatus.SKIPPED_NO_UPSTREAM,
            f"{repo_name} has no upstream tracking branch; skipping pre-pull",
            before_head=before_head,
        )
    upstream = upstream_proc.stdout.strip()

    # 6. Fetch (prune). Non-interactive; auth failures fail fast.
    fetch = _run_git(["fetch", "--prune"], repo_path=repo_path, timeout=timeout_seconds)
    if fetch.returncode != 0:
        return make(
            PrePullStatus.FETCH_FAILED,
            f"git fetch failed for {repo_name}",
            before_head=before_head,
            upstream=upstream,
            stderr=_redact(fetch.stderr),
        )

    # 7. Fast-forward analysis via ancestry checks (no merge commits possible).
    head_anc = _run_git(
        ["merge-base", "--is-ancestor", "HEAD", "@{u}"],
        repo_path=repo_path,
        timeout=timeout_seconds,
    )
    up_anc = _run_git(
        ["merge-base", "--is-ancestor", "@{u}", "HEAD"],
        repo_path=repo_path,
        timeout=timeout_seconds,
    )
    # is-ancestor returns 0 (yes) / 1 (no); anything else is an error.
    if head_anc.returncode not in (0, 1) or up_anc.returncode not in (0, 1):
        bad = head_anc if head_anc.returncode not in (0, 1) else up_anc
        return make(
            PrePullStatus.ERROR,
            f"ancestry check failed for {repo_name}",
            before_head=before_head,
            upstream=upstream,
            stderr=_redact(bad.stderr),
        )

    head_is_ancestor = head_anc.returncode == 0
    upstream_is_ancestor = up_anc.returncode == 0

    if head_is_ancestor and upstream_is_ancestor:
        # HEAD == upstream
        return make(
            PrePullStatus.UP_TO_DATE,
            f"{repo_name} is already up to date with {upstream}",
            before_head=before_head,
            after_head=before_head,
            upstream=upstream,
        )

    if upstream_is_ancestor and not head_is_ancestor:
        # Local commits not on upstream; nothing to fast-forward.
        return make(
            PrePullStatus.LOCAL_AHEAD,
            f"{repo_name} is ahead of {upstream}; no fast-forward needed",
            before_head=before_head,
            after_head=before_head,
            upstream=upstream,
        )

    if not head_is_ancestor and not upstream_is_ancestor:
        # Both sides have unique commits.
        return make(
            PrePullStatus.DIVERGED,
            f"{repo_name} has diverged from {upstream}; refusing pre-pull (not a fast-forward)",
            before_head=before_head,
            upstream=upstream,
        )

    # head_is_ancestor and not upstream_is_ancestor → strictly behind → a clean
    # fast-forward is *potentially* possible. Before committing to the plan,
    # check whether any untracked file in the working tree would be overwritten
    # by the fast-forward. git merge --ff-only would reject these in the apply
    # phase, but catching them here prevents any other repo from being applied
    # first in a multi-repo batch.
    #
    # NUL-terminated (`-z`) output avoids path quoting for spaces/unicode. We do
    # NOT pass `--exclude-standard`: ignored untracked files are still local data
    # that a bounded fast-forward must never clobber, so they participate in the
    # collision check too.
    upstream_files_proc = _run_git(
        ["diff", "--name-only", "-z", f"HEAD..{upstream}"],
        repo_path=repo_path,
        timeout=timeout_seconds,
    )
    untracked_proc = _run_git(
        ["ls-files", "--others", "-z"],
        repo_path=repo_path,
        timeout=timeout_seconds,
    )
    # A failed safety check must NOT degrade to a fast-forward: if we cannot
    # prove the working tree is safe, we refuse (hard fail) rather than guess.
    if upstream_files_proc.returncode != 0 or untracked_proc.returncode != 0:
        bad = upstream_files_proc if upstream_files_proc.returncode != 0 else untracked_proc
        return make(
            PrePullStatus.ERROR,
            f"untracked overwrite safety check failed for {repo_name}; refusing pre-pull",
            before_head=before_head,
            upstream=upstream,
            stderr=_redact(bad.stderr),
        )

    upstream_files = set(_split_git_z(upstream_files_proc.stdout))
    untracked_files = set(_split_git_z(untracked_proc.stdout))
    collisions = sorted(
        untracked
        for untracked in untracked_files
        if any(_path_collides(untracked, upstream_path) for upstream_path in upstream_files)
    )
    if collisions:
        shown = collisions[:10]
        suffix = f" (and {len(collisions) - 10} more)" if len(collisions) > 10 else ""
        paths_str = ", ".join(shown) + suffix
        return make(
            PrePullStatus.UNTRACKED_WOULD_BE_OVERWRITTEN,
            f"{repo_name} has untracked files that would be overwritten by fast-forward: "
            f"{paths_str}; refusing pre-pull",
            before_head=before_head,
            upstream=upstream,
        )

    return make(
        PrePullStatus.PLANNED_FAST_FORWARD,
        f"{repo_name} can fast-forward to {upstream}",
        before_head=before_head,
        upstream=upstream,
        needs_apply=True,
    )


def _plan_to_result(plan: PrePullPlan) -> PrePullResult:
    """Project a terminal (non-apply) plan onto a PrePullResult unchanged."""
    return PrePullResult(
        repo=plan.repo,
        path=plan.path,
        status=plan.status,
        changed=plan.changed,
        before_head=plan.before_head,
        after_head=plan.after_head,
        upstream=plan.upstream,
        message=plan.message,
        stderr=plan.stderr,
    )


def apply_pre_pull_plan(plan: PrePullPlan, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS) -> PrePullResult:
    """Apply phase: execute a planned fast-forward (the only mutation in this module).

    Plans that do not need applying carry through unchanged. For a planned
    fast-forward, HEAD is re-verified against ``plan.before_head`` (race guard)
    before a single ``merge --ff-only`` is run.
    """
    if plan.status not in PLAN_APPLY_STATUSES or not plan.needs_apply:
        # up_to_date / local_ahead / skipped / warn / hard-fail plans: nothing to do.
        return _plan_to_result(plan)

    repo_path = Path(plan.path)
    repo_name = plan.repo

    def make(status: str, message: str = "", **kwargs) -> PrePullResult:
        kwargs.setdefault("before_head", plan.before_head)
        kwargs.setdefault("upstream", plan.upstream)
        return PrePullResult(repo=repo_name, path=str(repo_path), status=status, message=message, **kwargs)

    # Race guard: HEAD must still be exactly what we planned against. A concurrent
    # local commit/checkout invalidates the fast-forward, so we refuse it.
    head = _run_git(["rev-parse", "HEAD"], repo_path=repo_path, timeout=timeout_seconds)
    current_head = head.stdout.strip() if head.returncode == 0 else None
    if head.returncode != 0:
        return make(
            PrePullStatus.ERROR,
            f"could not re-read HEAD for {repo_name} before apply",
            stderr=_redact(head.stderr),
        )
    if current_head != plan.before_head:
        return make(
            PrePullStatus.HEAD_CHANGED,
            f"{repo_name} HEAD changed between plan and apply "
            f"({plan.before_head} -> {current_head}); refusing fast-forward",
            after_head=current_head,
        )

    merge = _run_git(["merge", "--ff-only", "@{u}"], repo_path=repo_path, timeout=timeout_seconds)
    if merge.returncode != 0:
        return make(
            PrePullStatus.MERGE_FAILED,
            f"fast-forward merge failed for {repo_name}",
            stderr=_redact(merge.stderr),
        )

    after = _run_git(["rev-parse", "HEAD"], repo_path=repo_path, timeout=timeout_seconds)
    after_head = after.stdout.strip() if after.returncode == 0 else None
    return make(
        PrePullStatus.FAST_FORWARDED,
        f"{repo_name} fast-forwarded to {plan.upstream}",
        changed=True,
        after_head=after_head,
    )


def pre_pull_repo(repo_path: Path, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS) -> PrePullResult:
    """Plan + apply a fast-forward-only update of a single local git repo.

    Convenience wrapper preserving the original single-repo entry point. For
    multi-repo jobs prefer :func:`plan_pre_pull_repos` + :func:`apply_pre_pull_plans`
    so that no repo is fast-forwarded when another repo's plan hard-fails.
    """
    plan = plan_pre_pull_repo(repo_path, timeout_seconds)
    if plan.status in HARD_FAIL_STATUSES:
        return _plan_to_result(plan)
    if plan.needs_apply:
        return apply_pre_pull_plan(plan, timeout_seconds)
    return _plan_to_result(plan)


def plan_pre_pull_repos(sources: Sequence[Path], timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS) -> List[PrePullPlan]:
    """Plan (read + fetch + analyze) every source. No working tree is mutated."""
    return [plan_pre_pull_repo(Path(src), timeout_seconds) for src in sources]


def apply_pre_pull_plans(plans: Sequence[PrePullPlan], timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS) -> List[PrePullResult]:
    """Apply every plan. Callers MUST ensure no plan is a hard-fail before calling.

    Applying is all-or-nothing only at the plan-decision level: callers must not
    call this when any plan hard-failed. This function does not provide rollback
    after an earlier apply succeeds; a later apply failure is returned as a hard
    failure to the caller.
    """
    return [apply_pre_pull_plan(plan, timeout_seconds) for plan in plans]
