"""Tests for compatibility with older PyYAML builds."""
from __future__ import annotations

import collections
import collections.abc

from merger.repoground.core.yaml_compat import ensure_pyyaml_collections_abc_compat


_ALIASES = ("Hashable", "Mapping", "MutableMapping", "Sequence")


def _delete_pyyaml_collections_aliases(monkeypatch):
    for name in _ALIASES:
        # Register even an initially missing attribute for automatic teardown.
        monkeypatch.setattr(
            collections, name, getattr(collections.abc, name), raising=False
        )
        monkeypatch.delattr(collections, name, raising=False)


def test_ensure_pyyaml_collections_abc_compat_installs_missing_aliases(monkeypatch):
    _delete_pyyaml_collections_aliases(monkeypatch)

    ensure_pyyaml_collections_abc_compat()

    for name in _ALIASES:
        assert getattr(collections, name) is getattr(collections.abc, name)


def test_augment_yaml_load_installs_compat_before_safe_load(monkeypatch, tmp_path):
    from merger.repoground.core import merge

    repo = tmp_path / "sample"
    repo.mkdir()
    (repo / "sample_augment.yml").write_text("augment: {}\n", encoding="utf-8")

    _delete_pyyaml_collections_aliases(monkeypatch)

    def fake_safe_load(text):
        assert text == "augment: {}\n"
        assert collections.Hashable is collections.abc.Hashable
        return {"augment": {}}

    monkeypatch.setattr(merge.yaml, "safe_load", fake_safe_load)
    rendered = merge._render_augment_block([repo])

    assert "Augment Intelligence" in rendered
