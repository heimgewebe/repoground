#!/usr/bin/env python3
"""Start RepoGround MCP stdio from an absolute RepoGround checkout path."""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
repo_root_text = str(REPO_ROOT)
if repo_root_text not in sys.path:
    sys.path.insert(0, repo_root_text)

from merger.repoground.cli.mcp_stdio import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
