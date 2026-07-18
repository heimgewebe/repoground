"""Deprecated module alias for :mod:`merger.repoground.cli.cmd_ground`."""
from __future__ import annotations

import importlib
import sys
import warnings

warnings.warn(
    "merger.repoground.cli.cmd_repobrief is deprecated; import merger.repoground.cli.cmd_ground instead; compatibility review: 2026-09-01",
    DeprecationWarning,
    stacklevel=2,
)
_module = importlib.import_module(".cmd_ground", __package__)
sys.modules[__name__] = _module
