"""Deprecated module alias for :mod:`merger.repoground.core.availability`."""
from __future__ import annotations

import importlib
import sys
import warnings

warnings.warn(
    "merger.repoground.core.repobrief_availability is deprecated; import merger.repoground.core.availability instead; compatibility review: 2026-10-01",
    DeprecationWarning,
    stacklevel=2,
)
_module = importlib.import_module(".availability", __package__)
sys.modules[__name__] = _module
