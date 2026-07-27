#!/usr/bin/env python3
"""Synchronize documented RepoGround MCP read tools with the live registry."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from merger.repoground.cli.mcp_stdio import tool_registry  # noqa: E402

START_MARKER = "<!-- repoground-mcp-tools:start -->"
END_MARKER = "<!-- repoground-mcp-tools:end -->"
DOC_PATHS = (
    REPO_ROOT / "docs/architecture/repoground-mcp-boundary.md",
    REPO_ROOT / "docs/usage/repoground-mcp-stdio.md",
)


def render_tool_block() -> str:
    lines = [START_MARKER]
    for tool in tool_registry(False):
        name = tool["name"]
        description = " ".join(str(tool.get("description") or "").split())
        lines.append(f"- `{name}`: {description}")
    lines.append(END_MARKER)
    return "\n".join(lines)


def replace_tool_block(text: str) -> str:
    start = text.find(START_MARKER)
    end = text.find(END_MARKER)
    if start < 0 or end < 0 or end < start:
        raise ValueError("document is missing the RepoGround MCP tool markers")
    end += len(END_MARKER)
    return text[:start] + render_tool_block() + text[end:]


def sync_document(path: Path, *, check: bool) -> bool:
    before = path.read_text(encoding="utf-8")
    after = replace_tool_block(before)
    if before == after:
        return True
    if check:
        return False
    path.write_text(after, encoding="utf-8")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    stale = [path for path in DOC_PATHS if not sync_document(path, check=args.check)]
    if stale:
        for path in stale:
            print(
                f"RepoGround MCP tool documentation is stale: {path}", file=sys.stderr
            )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
