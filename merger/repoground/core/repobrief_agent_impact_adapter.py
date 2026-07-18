"""Deprecated module alias for :mod:`merger.repoground.core.agent_impact_adapter`."""
from __future__ import annotations

import importlib
import sys
import warnings

warnings.warn(
    "merger.repoground.core.repobrief_agent_impact_adapter is deprecated; import merger.repoground.core.agent_impact_adapter instead; compatibility review: 2026-10-01",
    DeprecationWarning,
    stacklevel=2,
)
_module = importlib.import_module(".agent_impact_adapter", __package__)
sys.modules[__name__] = _module
