"""Deprecated module alias for :mod:`merger.repoground.core.publication_policy`."""
from __future__ import annotations

import importlib
import sys
import warnings

warnings.warn(
    "merger.repoground.core.repobrief_publication_policy is deprecated; import merger.repoground.core.publication_policy instead; compatibility review: 2026-10-01",
    DeprecationWarning,
    stacklevel=2,
)
_module = importlib.import_module(".publication_policy", __package__)
sys.modules[__name__] = _module
