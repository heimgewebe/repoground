"""Deprecated repoLens helper alias; use build_utils."""
from __future__ import annotations
import warnings
warnings.warn("repolens_utils is deprecated; use build_utils", DeprecationWarning, stacklevel=2)
from build_utils import *  # noqa: F401,F403
