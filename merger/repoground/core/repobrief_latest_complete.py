"""Deprecated module alias for :mod:`merger.repoground.core.latest_complete`."""
from __future__ import annotations

import importlib
import sys
import warnings

warnings.warn(
    "merger.repoground.core.repobrief_latest_complete is deprecated; import merger.repoground.core.latest_complete instead; compatibility review: 2026-10-01",
    DeprecationWarning,
    stacklevel=2,
)
_module = importlib.import_module(".latest_complete", __package__)
sys.modules[__name__] = _module
