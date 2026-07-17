"""RepoGround public Python convenience surface.

The canonical implementation lives in :mod:`merger.repoground`.  This package
contains no second engine or dispatcher; it only provides the short
``python -m repoground`` entry point and stable product metadata.
"""

from __future__ import annotations

from pathlib import Path

PRODUCT_NAME = "RepoGround"
ENGINE_MODULE = "merger.repoground"


def _release_version() -> str:
    version_file = Path(__file__).resolve().parent.parent / "RELEASE_VERSION"
    try:
        return version_file.read_text(encoding="utf-8").strip()
    except OSError:
        return "3.0.0"


__version__ = _release_version()

__all__ = ["ENGINE_MODULE", "PRODUCT_NAME", "__version__"]
