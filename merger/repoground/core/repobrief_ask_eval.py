"""Deprecated module alias for :mod:`merger.repoground.core.ask_evaluation`."""
from __future__ import annotations

import importlib
import sys
import warnings

warnings.warn(
    "merger.repoground.core.repobrief_ask_eval is deprecated; import merger.repoground.core.ask_evaluation instead; compatibility review: 2026-10-01",
    DeprecationWarning,
    stacklevel=2,
)
_module = importlib.import_module(".ask_evaluation", __package__)
sys.modules[__name__] = _module
