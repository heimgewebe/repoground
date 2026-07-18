"""Deprecated module alias for :mod:`merger.repoground.core.readonly_adapter`."""
from __future__ import annotations

import importlib
import sys
import warnings

warnings.warn(
    "merger.repoground.core.repobrief_readonly_adapter is deprecated; import merger.repoground.core.readonly_adapter instead; compatibility review: 2026-10-01",
    DeprecationWarning,
    stacklevel=2,
)
_module = importlib.import_module(".readonly_adapter", __package__)
sys.modules[__name__] = _module
