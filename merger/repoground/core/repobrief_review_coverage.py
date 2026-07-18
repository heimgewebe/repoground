"""Deprecated module alias for :mod:`merger.repoground.core.review_coverage`."""
from __future__ import annotations

import importlib
import sys
import warnings

warnings.warn(
    "merger.repoground.core.repobrief_review_coverage is deprecated; import merger.repoground.core.review_coverage instead; compatibility review: 2026-10-01",
    DeprecationWarning,
    stacklevel=2,
)
_module = importlib.import_module(".review_coverage", __package__)
sys.modules[__name__] = _module
