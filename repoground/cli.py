"""Short RepoGround CLI facade.

All command dispatch is owned by :mod:`merger.repoground`; this module exists
only so ``python -m repoground`` and installed console entry points share the
same implementation.
"""
from __future__ import annotations

from collections.abc import Sequence

from merger.repoground.__main__ import main as _canonical_main


def main(argv: Sequence[str] | None = None) -> int:
    return _canonical_main(argv)


__all__ = ["main"]
