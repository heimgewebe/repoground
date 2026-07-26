from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from merger.repoground.core.bundle_catalog import BundleCatalogError


REPO_ROOT = Path(__file__).resolve().parents[3]
LAUNCHER_PATH = REPO_ROOT / "scripts" / "repoground-mcp-project.py"


def _load_launcher():
    spec = importlib.util.spec_from_file_location(
        "repoground_mcp_project_test_module", LAUNCHER_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_launcher_source_does_not_contain_legacy_local_bundle_default():
    text = LAUNCHER_PATH.read_text(encoding="utf-8")

    assert "~/.local/share/repoground/bundles" not in text
    assert "manifest-publications" in text


def test_canonical_publication_root_finds_ancestor_catalog(tmp_path, monkeypatch):
    module = _load_launcher()
    repo_root = tmp_path / ".repoground-worktrees" / "frontdoor"
    repo_root.mkdir(parents=True)
    publication_root = tmp_path / "manifest-publications" / "bundles"
    publication_root.mkdir(parents=True)
    monkeypatch.setattr(module, "REPO_ROOT", repo_root)
    monkeypatch.delenv("REPOGROUND_BUNDLE_ROOT", raising=False)
    monkeypatch.delenv("REPOGROUND_PUBLICATION_ROOT", raising=False)

    assert module._canonical_publication_root() == publication_root.resolve()


def test_explicit_bundle_root_override_has_priority(tmp_path, monkeypatch):
    module = _load_launcher()
    override = tmp_path / "explicit-bundles"
    monkeypatch.setenv("REPOGROUND_BUNDLE_ROOT", str(override))
    monkeypatch.setenv("REPOGROUND_PUBLICATION_ROOT", str(tmp_path / "lower-priority"))

    assert module._canonical_publication_root() == override.resolve()


def test_selected_bundle_uses_repo_identity_and_healthy_catalog(tmp_path, monkeypatch):
    module = _load_launcher()
    publication_root = tmp_path / "publications"
    manifest = publication_root / "selected.bundle.manifest.json"
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    seen = {}

    monkeypatch.setattr(module, "REPO_ROOT", repo_root)
    monkeypatch.setattr(module, "_canonical_publication_root", lambda: publication_root)
    monkeypatch.setattr(
        module, "checkout_repo_identity", lambda _root: "heimgewebe/repoground"
    )

    def select(root, *, repo, require_healthy):
        seen.update(
            {
                "root": root,
                "repo": repo,
                "require_healthy": require_healthy,
            }
        )
        return {
            "status": "available",
            "selected": {"manifest_path": str(manifest)},
        }

    monkeypatch.setattr(module, "select_bundle_manifest", select)
    monkeypatch.delenv("REPOGROUND_REPO_ID", raising=False)

    assert module._selected_bundle_manifest() == manifest
    assert seen == {
        "root": publication_root,
        "repo": "heimgewebe/repoground",
        "require_healthy": True,
    }


def test_selected_bundle_fails_closed_when_catalog_is_ambiguous(tmp_path, monkeypatch):
    module = _load_launcher()
    publication_root = tmp_path / "publications"
    monkeypatch.setattr(module, "_canonical_publication_root", lambda: publication_root)
    monkeypatch.setattr(
        module, "checkout_repo_identity", lambda _root: "heimgewebe/repoground"
    )
    monkeypatch.setattr(
        module,
        "select_bundle_manifest",
        lambda *_args, **_kwargs: {
            "status": "ambiguous",
            "reason": "newest_bundle_identity_ambiguous",
            "selected": None,
        },
    )
    monkeypatch.delenv("REPOGROUND_REPO_ID", raising=False)

    with pytest.raises(BundleCatalogError, match="newest_bundle_identity_ambiguous"):
        module._selected_bundle_manifest()
