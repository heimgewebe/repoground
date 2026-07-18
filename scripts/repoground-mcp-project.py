#!/usr/bin/env python3
"""Start the project-local RepoGround MCP server with canonical defaults."""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from merger.repoground.cli.mcp_stdio import main  # noqa: E402


def _argv() -> list[str]:
    bundle_root = Path(
        os.environ.get(
            "REPOGROUND_BUNDLE_ROOT",
            "~/.local/share/repoground/bundles",
        )
    ).expanduser()
    argv = [
        "--bundle-root",
        str(bundle_root),
        "--repo-root",
        str(REPO_ROOT),
    ]
    if os.environ.get("REPOGROUND_MCP_ENABLE_SNAPSHOT_CREATE") == "1":
        argv.append("--enable-snapshot-create")
    return argv


if __name__ == "__main__":
    raise SystemExit(main(_argv()))
