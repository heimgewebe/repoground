# -*- coding: utf-8 -*-
"""Portable source-mode and pre-pull decisions for the Pythonista frontend."""

import sys
from pathlib import Path
from typing import Any, Callable, Iterable, Optional


def is_ios_runtime() -> bool:
    """True under Pythonista/iOS, where subprocesses are unavailable."""
    return sys.platform == "ios"


def git_subprocesses_supported() -> bool:
    """False on Pythonista/iOS; true on supported desktop/server runtimes."""
    return not is_ios_runtime()


def git_subprocess_unavailable_message(feature: str) -> str:
    return (
        f"{feature} requires git subprocesses and is not supported in Pythonista/iOS. "
        "Disable this option or run RepoGround build on desktop/server."
    )


def resolve_headless_source_mode(args: Any) -> str:
    """Map parsed arguments to the canonical source-mode identifier."""
    source_mode = getattr(args, "source_mode", None)
    plan_only = bool(getattr(args, "plan_only", False))
    if source_mode == "remote-snapshot":
        return "remote_snapshot"
    if source_mode == "local-current":
        return "local_current"
    if source_mode == "local-ff":
        return "local_current" if plan_only else "local_ff"
    requested = getattr(args, "pre_pull", None)
    if requested is None:
        requested = not plan_only
    return "local_ff" if (requested and not plan_only) else "local_current"


def resolve_pre_pull_switch_value(pre_pull_switch: Any) -> bool:
    """Read a Pythonista switch, preserving the documented default-true value."""
    return True if pre_pull_switch is None else bool(pre_pull_switch.value)


def resolve_effective_pre_pull(
    pre_pull: Any,
    plan_only: Any,
    *,
    log: Optional[Callable[[str], None]] = None,
    notify: Optional[Callable[[str], None]] = None,
) -> bool:
    """Apply plan-only and iOS capability gates to the pre-pull request."""
    effective = bool(pre_pull and not plan_only)
    if effective and not git_subprocesses_supported():
        hint = (
            "Pre-pull disabled on iOS: git subprocesses are not supported in "
            "Pythonista. Scanning the local working tree as-is."
        )
        if log is not None:
            log(hint)
        if notify is not None:
            notify("Pre-pull disabled on iOS (no git subprocess)")
        return False
    return effective


def resolve_effective_headless_source_mode(
    args: Any,
    *,
    log: Optional[Callable[[str], None]] = print,
) -> str:
    """Apply the iOS fallback to an otherwise canonical headless source mode."""
    mode = resolve_headless_source_mode(args)
    if mode == "local_ff" and not git_subprocesses_supported():
        if log is not None:
            log(
                "Implicit local_ff/default fast-forward disabled on iOS: git subprocesses "
                "are not supported in Pythonista; scanning the local working tree as-is."
            )
        mode = "local_current"
    return mode


def run_pre_pull_two_phase(
    sources: Iterable[Path],
    *,
    plan_pre_pull_repos: Any,
    apply_pre_pull_plans: Any,
    is_self_repo: Any,
    pre_pull_status: Any,
    hard_fail_statuses: Any,
    warn_statuses: Any,
    log: Callable[[str], None] = print,
    warn: Optional[Callable[[str], None]] = None,
) -> Any:
    """Plan every repository before applying any fast-forward.

    Runtime integrations are injected explicitly. This keeps the module portable
    and makes the mutation boundary visible to callers and tests.
    """
    if warn is None:

        def warn(message: str) -> None:
            print(message, file=sys.stderr)

    if plan_pre_pull_repos is None or apply_pre_pull_plans is None:
        raise RuntimeError("Pre-pull requested but repo_sync module is unavailable.")

    log(
        "Pre-pull enabled: planning updates for all repositories (fast-forward only)..."
    )
    plans = plan_pre_pull_repos(sources)

    hard_failures = []
    for plan in plans:
        log(f"Pre-pull plan {plan.repo}: {plan.status} - {plan.message}")
        if plan.stderr:
            log(f"Pre-pull plan {plan.repo} detail: {plan.stderr.strip()}")
        if plan.status in warn_statuses:
            warn(f"Warning: {plan.repo}: {plan.status} - {plan.message}")
        if plan.status in hard_fail_statuses:
            hard_failures.append(plan)

    if hard_failures:
        detail = "; ".join(
            f"{plan.repo}: {plan.status} - {plan.message}" for plan in hard_failures
        )
        raise ValueError(
            "Pre-pull plan failed (no repo HEADs or working trees were fast-forwarded): "
            + detail
        )

    log("Pre-pull plan OK: applying fast-forwards...")
    results = apply_pre_pull_plans(plans)
    for result in results:
        log(f"Pre-pull apply {result.repo}: {result.status} - {result.message}")
        if result.stderr:
            log(f"Pre-pull apply {result.repo} detail: {result.stderr.strip()}")
        if result.status in hard_fail_statuses:
            raise ValueError(
                f"Pre-pull apply failed for {result.repo}: {result.status} - {result.message}"
            )
        if (
            pre_pull_status is not None
            and result.status == pre_pull_status.FAST_FORWARDED
            and is_self_repo(Path(result.path))
        ):
            warn(
                f"Warning: pre_pull fast-forwarded the running code repository '{result.repo}'. "
                "Please restart any active service after completion."
            )
    return results
