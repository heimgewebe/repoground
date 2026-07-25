# -*- coding: utf-8 -*-
"""Output-option and report-delivery helpers for the Pythonista CLI."""

from typing import Any, Callable, Optional, Tuple


def resolve_scan_options(
    args: Any,
    *,
    parse_human_size: Callable[[str], int],
    normalize_ext_list: Callable[[str], Any],
) -> Tuple[int, Any, Optional[str]]:
    max_bytes = parse_human_size(str(args.max_bytes))
    if max_bytes < 0:
        max_bytes = 0
    ext_list = normalize_ext_list(args.extensions) if args.extensions else None
    return max_bytes, ext_list, args.path_filter


def resolve_output_options(
    args: Any,
    *,
    parse_human_size: Callable[[str], int],
    extras_config_type: Any,
    log: Callable[[str], None] = print,
) -> Tuple[int, Any]:
    split_size = 0
    if args.split_size:
        split_size = parse_human_size(args.split_size)
        log(f"Splitting at {split_size} bytes")

    extras_config, warnings = extras_config_type.from_csv(args.extras)
    for warning in warnings:
        log(f"Warning: {warning}")
    if args.json_sidecar:
        extras_config.json_sidecar = True
    return split_size, extras_config


def extract_delta_meta(
    *,
    extras_config: Any,
    summaries: Any,
    merges_dir: Any,
    load_extractor_module: Callable[[], Any],
    debug: bool,
    log: Callable[[str], None] = print,
) -> Any:
    if not (extras_config.delta_reports and summaries and len(summaries) == 1):
        return None

    repo_name = summaries[0]["name"]
    try:
        module = load_extractor_module()
        if not (
            module
            and hasattr(module, "find_latest_diff_for_repo")
            and hasattr(module, "extract_delta_meta_from_diff_file")
        ):
            return None
        diff_path = module.find_latest_diff_for_repo(merges_dir, repo_name)
        if not diff_path:
            return None
        delta_meta = module.extract_delta_meta_from_diff_file(diff_path)
        if delta_meta and debug:
            log(f"Delta metadata extracted from {diff_path.name}")
        return delta_meta
    except Exception as exc:
        if debug:
            log(f"Warning: Could not extract delta metadata: {exc}")
        return None


def write_cli_reports(
    *,
    write_reports_v2: Callable[..., Any],
    merges_dir: Any,
    hub: Any,
    summaries: Any,
    args: Any,
    max_bytes: int,
    split_size: int,
    path_filter: Optional[str],
    ext_list: Any,
    extras_config: Any,
    delta_meta: Any,
    log: Callable[[str], None] = print,
) -> Any:
    artifacts = write_reports_v2(
        merges_dir,
        hub,
        summaries,
        args.level,
        args.mode,
        max_bytes,
        bool(args.plan_only),
        args.code_only,
        split_size,
        debug=args.debug,
        path_filter=path_filter,
        ext_filter=ext_list,
        extras=extras_config,
        delta_meta=delta_meta,
        meta_density=args.meta_density,
        output_mode=args.output_mode,
        redact_secrets=args.redact_secrets,
        generator_info={"name": "repoground", "platform": "cli"},
    )

    out_paths = artifacts.get_all_paths()
    log(f"Generated {len(out_paths)} report(s):")
    for path in out_paths:
        log(f"  - {path}")
    return artifacts
