"""Compatibility helpers for PyYAML on constrained or older runtimes."""
from __future__ import annotations


def ensure_pyyaml_collections_abc_compat() -> None:
    """Provide legacy ``collections`` ABC aliases used by older PyYAML builds.

    Some PyYAML versions still reference names such as ``collections.Hashable``
    while modern Python exposes them under ``collections.abc``. Pythonista/iOS
    can combine a newer standard library with an older PyYAML build, so YAML
    loading installs these harmless aliases before calling ``yaml.safe_load``.
    """
    import collections
    import collections.abc

    for name in ("Hashable", "Mapping", "MutableMapping", "Sequence"):
        if not hasattr(collections, name) and hasattr(collections.abc, name):
            setattr(collections, name, getattr(collections.abc, name))
