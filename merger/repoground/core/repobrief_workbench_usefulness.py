"""Deprecated module alias for :mod:`merger.repoground.core.workbench_usefulness`."""
from __future__ import annotations

import importlib
import sys
import warnings

warnings.warn(
    "merger.repoground.core.repobrief_workbench_usefulness is deprecated; import merger.repoground.core.workbench_usefulness instead; compatibility review: 2026-10-01",
    DeprecationWarning,
    stacklevel=2,
)
_module = importlib.import_module(".workbench_usefulness", __package__)
sys.modules[__name__] = _module
