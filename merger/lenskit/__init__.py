"""Deprecated compatibility namespace for RepoGround 3.x.

New code must import :mod:`merger.repoground`.  Legacy submodule imports are
redirected to the canonical module objects instead of loading the same source a
second time.  This preserves class, cache, registry and singleton identity
until the contract review date of 2026-10-01.
"""
from __future__ import annotations

import importlib
import importlib.abc
import importlib.util
import sys
import warnings
from types import ModuleType

_LEGACY_PREFIX = "merger.lenskit."
_CANONICAL_PREFIX = "merger.repoground."

warnings.warn(
    "merger.lenskit is deprecated; import merger.repoground instead; compatibility review: 2026-10-01",
    DeprecationWarning,
    stacklevel=2,
)


class _RepoGroundAliasLoader(importlib.abc.Loader):
    """Return one canonical module under an additional legacy sys.modules key."""

    def __init__(self, canonical_name: str) -> None:
        self.canonical_name = canonical_name
        self._canonical_attrs: dict[str, object] = {}

    def create_module(self, spec: importlib.machinery.ModuleSpec) -> ModuleType:
        module = importlib.import_module(self.canonical_name)
        self._canonical_attrs = {
            "__name__": module.__name__,
            "__spec__": module.__spec__,
            "__loader__": module.__loader__,
            "__package__": module.__package__,
            "__path__": getattr(module, "__path__", None),
        }
        sys.modules[spec.name] = module
        return module

    def exec_module(self, module: ModuleType) -> None:
        # Import machinery temporarily applies the legacy spec to the returned
        # module. Restore the canonical metadata so relative imports, reload and
        # diagnostics continue to operate on merger.repoground.
        module.__name__ = str(self._canonical_attrs["__name__"])
        module.__spec__ = self._canonical_attrs["__spec__"]  # type: ignore[assignment]
        module.__loader__ = self._canonical_attrs["__loader__"]  # type: ignore[assignment]
        module.__package__ = str(self._canonical_attrs["__package__"])
        canonical_path = self._canonical_attrs["__path__"]
        if canonical_path is not None:
            module.__path__ = canonical_path  # type: ignore[attr-defined]


class _RepoGroundAliasFinder(importlib.abc.MetaPathFinder):
    """Map every ``merger.lenskit.*`` import to ``merger.repoground.*``."""

    _repoground_legacy_alias_finder = True

    def find_spec(
        self,
        fullname: str,
        path: object = None,
        target: ModuleType | None = None,
    ) -> importlib.machinery.ModuleSpec | None:
        del path, target
        if not fullname.startswith(_LEGACY_PREFIX):
            return None
        canonical_name = _CANONICAL_PREFIX + fullname[len(_LEGACY_PREFIX) :]
        canonical_spec = importlib.util.find_spec(canonical_name)
        if canonical_spec is None:
            return None
        return importlib.util.spec_from_loader(
            fullname,
            _RepoGroundAliasLoader(canonical_name),
            is_package=canonical_spec.submodule_search_locations is not None,
        )


if not any(
    getattr(finder, "_repoground_legacy_alias_finder", False)
    for finder in sys.meta_path
):
    sys.meta_path.insert(0, _RepoGroundAliasFinder())

# ``__path__`` remains available for tooling that inspects packages directly;
# the meta-path finder above owns actual submodule loading.
_canonical_package = importlib.import_module("merger.repoground")
__path__ = list(getattr(_canonical_package, "__path__", []))
if __spec__ is not None:
    __spec__.submodule_search_locations = __path__
