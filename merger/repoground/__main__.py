"""Unified RepoGround command surface."""
from __future__ import annotations

import sys
from collections.abc import Callable, Sequence

from . import __version__

_HELP = """usage: repoground <command> [options]

RepoGround turns repositories into navigable, verifiable agent context.

primary commands:
  build     build a repository evidence bundle
  query     query a retrieval index
  search    alias for query
  graph     extract architecture and graph views
  verify    verify a bundle or review surface
  ground    snapshot, ask and evidence-access operations
  serve     run the RepoGround HTTP/Web service
  mcp       run the RepoGround MCP stdio server

All established advanced commands remain available through the same CLI.
"""


def _call_sys_argv(main: Callable[[], object], argv: list[str]) -> int:
    previous = sys.argv[:]
    sys.argv = [previous[0], *argv]
    try:
        result = main()
        return int(result) if isinstance(result, int) else 0
    finally:
        sys.argv = previous


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in {"-h", "--help", "help"}:
        print(_HELP)
        return 0
    if args[0] in {"-V", "--version", "version"}:
        print(f"RepoGround {__version__}")
        return 0

    command, rest = args[0], args[1:]
    if command == "build":
        from .frontends.pythonista.build import main_cli
        return _call_sys_argv(main_cli, rest)
    if command == "serve":
        from .cli.serve import main as serve_main
        return _call_sys_argv(serve_main, rest)
    if command == "mcp":
        from .cli.mcp_stdio import main as mcp_main
        return int(mcp_main(rest))
    if command == "ground":
        from .cli.ground import main as ground_main
        return int(ground_main(rest))

    from .cli.main import main as established_main
    if command == "search":
        command = "query"
    elif command == "graph":
        command = "architecture"
    return int(established_main([command, *rest]))


if __name__ == "__main__":
    raise SystemExit(main())
