"""Deprecated RepoBrief MCP entry point; use RepoGround MCP."""
from __future__ import annotations
import warnings
from .mcp_stdio import *  # noqa: F401,F403
from .mcp_stdio import main

warnings.warn(
    "RepoBrief MCP is deprecated; use python -m merger.repoground mcp",
    DeprecationWarning,
    stacklevel=2,
)

if __name__ == "__main__":
    raise SystemExit(main())
