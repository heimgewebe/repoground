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
from merger.repoground.core.bundle_catalog import (  # noqa: E402
    BundleCatalogError,
    checkout_repo_identity,
    select_bundle_manifest,
)


def _canonical_publication_root() -> Path:
    configured = os.environ.get("REPOGROUND_BUNDLE_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    search_parents = tuple(REPO_ROOT.parents[:3])
    default_root = REPO_ROOT.parent / "manifest-publications" / "bundles"
    for parent in search_parents:
        candidate = parent / "manifest-publications" / "bundles"
        if candidate.is_dir():
            default_root = candidate
            break
    return (
        Path(os.environ.get("REPOGROUND_PUBLICATION_ROOT", str(default_root)))
        .expanduser()
        .resolve()
    )


def _selected_bundle_manifest() -> Path:
    bundle_root = _canonical_publication_root()
    repo_identity = os.environ.get("REPOGROUND_REPO_ID") or checkout_repo_identity(
        REPO_ROOT
    )
    selection = select_bundle_manifest(
        bundle_root, repo=repo_identity, require_healthy=True
    )
    selected = selection.get("selected")
    manifest = selected.get("manifest_path") if isinstance(selected, dict) else None
    if selection.get("status") != "available" or not isinstance(manifest, str):
        reason = selection.get("reason") or selection.get("status") or "unknown"
        raise BundleCatalogError(
            f"no unique healthy RepoGround bundle for {repo_identity!r} under {bundle_root}: {reason}"
        )
    return Path(manifest)


def _argv() -> list[str]:
    argv = [
        "--bundle-root",
        str(_selected_bundle_manifest()),
        "--repo-root",
        str(REPO_ROOT),
    ]
    if os.environ.get("REPOGROUND_MCP_ENABLE_SNAPSHOT_CREATE") == "1":
        argv.append("--enable-snapshot-create")
    return argv


if __name__ == "__main__":
    try:
        raise SystemExit(main(_argv()))
    except BundleCatalogError as exc:
        print(f"repoground project MCP: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
