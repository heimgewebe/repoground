# -*- coding: utf-8 -*-
"""Argument-parser contract for the Pythonista/desktop build entrypoint."""

import argparse
from typing import Optional, Sequence


def build_parser(
    *,
    default_level: str,
    default_mode: str,
    default_max_file_bytes: int,
    default_split_size: str,
    default_extras: str,
) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="RepoGround build")
    parser.add_argument("paths", nargs="*", help="Repositories to merge")
    parser.add_argument("--hub", help="RepoGround hub base directory")
    parser.add_argument(
        "--level",
        choices=["overview", "summary", "dev", "max"],
        default=default_level,
    )
    parser.add_argument(
        "--mode",
        choices=["gesamt", "pro-repo"],
        default=default_mode,
    )
    parser.add_argument(
        "--max-bytes",
        type=str,
        default=str(default_max_file_bytes),
        help="Max bytes per file (e.g. 5MB, 500K, or 0 for unlimited)",
    )
    parser.add_argument(
        "--split-size",
        help="Split output into chunks (e.g. 50MB, 1GB)",
        default=default_split_size,
    )
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument(
        "--code-only",
        action="store_true",
        help="Include only code/test/config/contract categories",
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug output")
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Force headless (no Pythonista UI/editor)",
    )
    pre_pull_group = parser.add_mutually_exclusive_group()
    pre_pull_group.add_argument(
        "--pre-pull",
        dest="pre_pull",
        action="store_true",
        default=None,
        help="Fast-forward-only update before scanning (default: enabled unless --plan-only)",
    )
    pre_pull_group.add_argument(
        "--no-pre-pull",
        dest="pre_pull",
        action="store_false",
        help="Disable the fast-forward-only pre-pull; scan the current on-disk state as-is",
    )
    parser.add_argument(
        "--extras",
        help=(
            "Comma-separated list of extras "
            "(health,organism_index,fleet_panorama,delta_reports,augment_sidecar,"
            "json_sidecar,heatmap,language_structure; alias: ai_heatmap) or 'none'"
        ),
        default=default_extras,
    )
    parser.add_argument(
        "--extensions",
        help="Comma-separated list of extensions (e.g. .md,.py) to include",
        default=None,
    )
    parser.add_argument(
        "--path-filter",
        help="Path substring to include (e.g. docs/)",
        default=None,
    )
    parser.add_argument(
        "--json-sidecar",
        action="store_true",
        help="Generate JSON sidecar file alongside markdown report",
    )
    parser.add_argument(
        "--meta-density",
        choices=["min", "standard", "full", "auto"],
        default="auto",
        help="Control metadata verbosity",
    )
    parser.add_argument(
        "--output-mode",
        choices=["archive", "retrieval", "dual"],
        default="dual",
        help="Output mode: archive (MD only), retrieval (Chunk Index), or dual (both)",
    )
    parser.add_argument(
        "--redact-secrets",
        action="store_true",
        help="Enable heuristic secret redaction",
    )
    parser.add_argument(
        "--source-mode",
        choices=["local-current", "local-ff", "remote-snapshot"],
        default=None,
        help=(
            "RepoGround service source acquisition mode "
            "(local-current / local-ff / remote-snapshot)"
        ),
    )
    parser.add_argument(
        "--remote-ref",
        default=None,
        help="Explicit remote ref for remote-snapshot (e.g. origin/main or a commit SHA)",
    )
    parser.add_argument(
        "--remote-ref-policy",
        choices=["upstream", "same-branch", "default-branch"],
        default=None,
        help=(
            "remote-snapshot ref policy when --remote-ref is absent (default: upstream). "
            "Non-default policies require --source-mode remote-snapshot."
        ),
    )
    return parser


def parse_args(
    argv: Optional[Sequence[str]],
    *,
    default_level: str,
    default_mode: str,
    default_max_file_bytes: int,
    default_split_size: str,
    default_extras: str,
):
    parser = build_parser(
        default_level=default_level,
        default_mode=default_mode,
        default_max_file_bytes=default_max_file_bytes,
        default_split_size=default_split_size,
        default_extras=default_extras,
    )
    return parser.parse_args(argv)
