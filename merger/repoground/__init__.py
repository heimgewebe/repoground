"""Canonical RepoGround implementation package."""
from __future__ import annotations

from pathlib import Path

PRODUCT_NAME = "RepoGround"


def _release_version() -> str:
    version_file = Path(__file__).resolve().parents[2] / "RELEASE_VERSION"
    try:
        return version_file.read_text(encoding="utf-8").strip()
    except OSError:
        return "3.0.0"


__version__ = _release_version()

__all__ = ["PRODUCT_NAME", "__version__"]
