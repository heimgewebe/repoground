"""Deprecated module alias for the canonical RepoGround service client."""
from __future__ import annotations

import importlib
import sys
import warnings

warnings.warn(
    "merger.repoground.cli.cmd_rlens_client is deprecated; import merger.repoground.cli.cmd_service_client instead; compatibility review: 2026-09-01",
    DeprecationWarning,
    stacklevel=2,
)
_module = importlib.import_module(".cmd_service_client", __package__)
sys.modules[__name__] = _module
