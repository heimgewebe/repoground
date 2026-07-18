from __future__ import annotations

import argparse
import sys
from typing import Optional, Sequence

from .cmd_ground import register_ground_command_groups, run_ground


def build_parser(
    *,
    prog: str = "repoground ground",
    description: str = "RepoGround: evidence-bound snapshot and read-access commands",
) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=prog, description=description)
    register_ground_command_groups(parser)
    return parser


def main(args: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    parsed_args = parser.parse_args(list(args) if args is not None else None)
    return run_ground(parsed_args)


if __name__ == "__main__":
    sys.exit(main())
