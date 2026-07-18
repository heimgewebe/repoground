"""Deprecated RepoBrief entry point; use RepoGround ground."""
from __future__ import annotations

import argparse
import warnings
from typing import Optional, Sequence

from .cmd_ground import register_ground_command_groups, run_ground

warnings.warn(
    "RepoBrief is deprecated; use python -m merger.repoground ground",
    DeprecationWarning,
    stacklevel=2,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="repobrief",
        description="Deprecated RepoBrief compatibility command; use RepoGround ground",
    )
    register_ground_command_groups(parser)
    return parser


def main(args: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    parsed_args = parser.parse_args(list(args) if args is not None else None)
    return run_ground(parsed_args)


if __name__ == "__main__":
    raise SystemExit(main())
