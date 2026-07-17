#!/usr/bin/env python3
from __future__ import annotations
import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
warnings.warn(
    "repobrief-mcp-stdio.py is deprecated; use repoground-mcp-stdio.py",
    FutureWarning,
    stacklevel=1,
)
from merger.repoground.cli.mcp_stdio import main
raise SystemExit(main())
