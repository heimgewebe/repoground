"""Deprecated module alias for :mod:`merger.repoground.core.mcp_resources`."""
from __future__ import annotations

import importlib
import sys
import warnings

warnings.warn(
    "merger.repoground.core.repobrief_mcp_resources is deprecated; import merger.repoground.core.mcp_resources instead; compatibility review: 2026-10-01",
    DeprecationWarning,
    stacklevel=2,
)
_module = importlib.import_module(".mcp_resources", __package__)
sys.modules[__name__] = _module
