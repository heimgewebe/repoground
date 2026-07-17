"""Deprecated repoLens entry point; use RepoGround build."""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

warnings.warn(
    "repoLens is deprecated; use python -m merger.repoground build",
    DeprecationWarning,
    stacklevel=2,
)

from build import *  # noqa: F401,F403,E402
from build import main  # noqa: E402

if __name__ == "__main__":
    main()
