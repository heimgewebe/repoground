"""Deprecated module alias for :mod:`merger.repoground.core.delta_context`."""
from __future__ import annotations

import importlib
import sys
import warnings

warnings.warn(
    "merger.repoground.core.repobrief_delta_context is deprecated; import merger.repoground.core.delta_context instead; compatibility review: 2026-10-01",
    DeprecationWarning,
    stacklevel=2,
)
_module = importlib.import_module(".delta_context", __package__)
sys.modules[__name__] = _module
