"""Deprecated rLens launcher; use RepoGround serve."""
from __future__ import annotations

import warnings

from . import serve as _serve

warnings.warn(
    "rLens is deprecated; use python -m merger.repoground serve",
    DeprecationWarning,
    stacklevel=2,
)

init_service = _serve.init_service
uvicorn = _serve.uvicorn


def main() -> None:
    _serve.init_service = init_service
    _serve.uvicorn = uvicorn
    _serve.main()


if __name__ == "__main__":
    main()
