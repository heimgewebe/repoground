"""Deprecated module alias for :mod:`merger.repoground.core.live_freshness`."""
from __future__ import annotations

import importlib
import sys
import warnings

warnings.warn(
    "merger.repoground.core.repobrief_live_freshness is deprecated; import merger.repoground.core.live_freshness instead; compatibility review: 2026-10-01",
    DeprecationWarning,
    stacklevel=2,
)
_module = importlib.import_module(".live_freshness", __package__)
sys.modules[__name__] = _module
