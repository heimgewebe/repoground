# -*- coding: utf-8 -*-
"""Headless build orchestration with dependencies supplied by the entry module."""

import sys
import uuid
from pathlib import Path
from typing import Any, Optional, Sequence


def _exit_usage(message: str) -> None:
    print(f"Error: {message}", file=sys.stderr)
    raise SystemExit(2)


def _validate_cli_request(api: Any, args: Any) -> tuple:
    source_mode = getattr(args, "source_mode", None)
    pre_pull = getattr(args, "pre_pull", None)
    plan_only = bool(getattr(args, "plan_only", False))
    remote_ref = getattr(args, "remote_ref", None)
    remote_ref_policy = getattr(args, "remote_ref_policy", None)

    if api.is_ios_runtime():
        if pre_pull is True:
            _exit_usage(api.git_subprocess_unavailable_message("--pre-pull"))
        if source_mode == "local-ff":
            _exit_usage(
                api.git_subprocess_unavailable_message("--source-mode local-ff")
            )
        if source_mode == "remote-snapshot":
            _exit_usage(
                api.git_subprocess_unavailable_message("--source-mode remote-snapshot")
            )

    if plan_only and pre_pull is True:
        _exit_usage(
            "--plan-only and --pre-pull are mutually exclusive "
            "(plan_only never mutates local repos)."
        )
    if source_mode == "local-current" and pre_pull is True:
        _exit_usage(
            "--source-mode local-current does not fast-forward; remove --pre-pull."
        )
    if source_mode == "local-ff" and pre_pull is False:
        _exit_usage(
            "--source-mode local-ff implies a fast-forward pre-pull; "
            "remove --no-pre-pull."
        )
    if source_mode == "remote-snapshot" and pre_pull is True:
        _exit_usage(
            "--source-mode remote-snapshot never mutates the local repo; "
            "remove --pre-pull."
        )

    if api.validate_source_mode_request is not None:
        canonical_mode = source_mode.replace("-", "_") if source_mode else None
        canonical_policy = (
            remote_ref_policy.replace("-", "_") if remote_ref_policy else None
        )
        try:
            api.validate_source_mode_request(
                repo_source_mode=canonical_mode,
                pre_pull=pre_pull,
                plan_only=plan_only,
                remote_ref=remote_ref,
                remote_ref_policy=canonical_policy,
            )
        except api.SourceModeConflictError as exc:
            _exit_usage(str(exc))

    return source_mode, pre_pull, plan_only, remote_ref, remote_ref_policy


def _resolve_sources(api: Any, args: Any, hub: Path) -> list:
    sources = []
    if args.paths:
        for value in args.paths:
            path = Path(value)
            if not path.exists():
                path = hub / value
            if path.exists() and path.is_dir():
                sources.append(path)
            else:
                print(f"Warning: {path} not found.")
    else:
        for repo_name in api.find_repos_in_hub(hub):
            sources.append(hub / repo_name)

    if not sources:
        cwd = Path.cwd()
        print(f"No sources in hub ({hub}). Scanning current directory: {cwd}")
        sources.append(cwd)
    return sources


def _materialize_remote_sources(
    api: Any,
    *,
    sources: list,
    hub: Path,
    plan_only: bool,
    remote_ref: Optional[str],
    remote_ref_policy: str,
) -> Optional[list]:
    if api.materialize_remote_snapshot is None or api.resolve_remote_ref is None:
        print(
            "Error: remote_snapshot requested but source_acquisition module is unavailable.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    merges_dir = api.get_merges_dir(hub)
    job_id = "headless-" + uuid.uuid4().hex[:12]
    if plan_only:
        ok = True
        for source in sources:
            resolution = api.resolve_remote_ref(
                source,
                remote_ref=remote_ref,
                remote_ref_policy=remote_ref_policy,
            )
            if resolution.status == api.SourceStatus.RESOLVED:
                commit_short = (resolution.resolved_commit or "")[:12]
                print(
                    f"remote_snapshot plan {resolution.repo}: would scan "
                    f"{resolution.resolved_ref} ({commit_short})"
                )
            else:
                ok = False
                print(
                    f"Error: remote_snapshot plan {resolution.repo}: "
                    f"{resolution.status} - {resolution.message}",
                    file=sys.stderr,
                )
        if not ok:
            raise SystemExit(1)
        print(
            "remote_snapshot plan_only: ref resolution complete; "
            "skipping scan and bundle write."
        )
        return None

    snapshot_sources = []
    for source in sources:
        result = api.materialize_remote_snapshot(
            source,
            remote_ref=remote_ref,
            remote_ref_policy=remote_ref_policy,
            cache_root=merges_dir,
            job_id=job_id,
        )
        if (
            result.status != api.SourceStatus.SNAPSHOT_CREATED
            or not result.snapshot_path
        ):
            print(
                f"Error: remote_snapshot {result.repo}: "
                f"{result.status} - {result.message}",
                file=sys.stderr,
            )
            raise SystemExit(1)
        for warning in result.warnings:
            print(f"Warning: {result.repo}: {warning}")
        commit_short = (result.resolved_commit or "")[:12]
        print(
            f"remote_snapshot {result.repo}: scanning {result.resolved_ref} "
            f"({commit_short}); local repo not mutated"
        )
        snapshot_sources.append(Path(result.snapshot_path))
    return snapshot_sources


def run_main_cli(api: Any, argv: Optional[Sequence[str]] = None) -> None:
    """Run the historical CLI contract through explicit module boundaries."""
    args = api.parse_cli_args(
        argv,
        default_level=api.DEFAULT_LEVEL,
        default_mode=api.DEFAULT_MODE,
        default_max_file_bytes=api.DEFAULT_MAX_FILE_BYTES,
        default_split_size=api.DEFAULT_SPLIT_SIZE,
        default_extras=api.DEFAULT_EXTRAS,
    )
    _, pre_pull, plan_only, remote_ref, remote_ref_policy_arg = _validate_cli_request(
        api, args
    )

    try:
        hub = api.detect_hub_dir(api.SCRIPT_PATH, args.hub)
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)

    sources = _resolve_sources(api, args, hub)
    print(f"Hub: {hub}")
    print(f"Sources: {[source.name for source in sources]}")

    effective_source_mode = api.resolve_effective_headless_source_mode(args)
    remote_ref_policy = (remote_ref_policy_arg or "upstream").replace("-", "_")

    if effective_source_mode == "remote_snapshot":
        resolved_sources = _materialize_remote_sources(
            api,
            sources=sources,
            hub=hub,
            plan_only=plan_only,
            remote_ref=remote_ref,
            remote_ref_policy=remote_ref_policy,
        )
        if resolved_sources is None:
            return
        sources = resolved_sources
    elif effective_source_mode == "local_ff":
        try:
            api.run_pre_pull_two_phase(sources, log=print)
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)
            raise SystemExit(1)
    elif plan_only and pre_pull is not False:
        print("Pre-pull skipped because plan_only=True.")

    max_bytes, ext_list, path_filter = api.resolve_scan_options(
        args,
        parse_human_size=api.parse_human_size,
        normalize_ext_list=api._normalize_ext_list,
    )

    summaries = []
    for source in sources:
        print(f"Scanning {source.name}...")
        summary = api.scan_repo(
            source,
            ext_list,
            path_filter,
            max_bytes,
            calculate_md5=True,
            include_hidden=True,
        )
        summaries.append(summary)

    split_size, extras_config = api.resolve_output_options(
        args,
        parse_human_size=api.parse_human_size,
        extras_config_type=api.ExtrasConfig,
        log=print,
    )
    merges_dir = api.get_merges_dir(hub)
    delta_meta = api.extract_delta_meta(
        extras_config=extras_config,
        summaries=summaries,
        merges_dir=merges_dir,
        load_extractor_module=api._load_repoground_extractor_module,
        debug=args.debug,
        log=print,
    )
    api.write_cli_reports(
        write_reports_v2=api.write_reports_v2,
        merges_dir=merges_dir,
        hub=hub,
        summaries=summaries,
        args=args,
        max_bytes=max_bytes,
        split_size=split_size,
        path_filter=path_filter,
        ext_list=ext_list,
        extras_config=extras_config,
        delta_meta=delta_meta,
        log=print,
    )
