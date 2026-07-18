"""Deprecated module alias for :mod:`merger.repoground.core.context_compiler`."""
from __future__ import annotations

import importlib
import sys
import warnings

warnings.warn(
    "merger.repoground.core.repobrief_context_compiler is deprecated; import merger.repoground.core.context_compiler instead; compatibility review: 2026-10-01",
    DeprecationWarning,
    stacklevel=2,
)
_module = importlib.import_module(".context_compiler", __package__)
sys.modules[__name__] = _module
