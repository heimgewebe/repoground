# -*- coding: utf-8 -*-
import sys
from pathlib import Path

def normalize_path(p: str) -> str:
    """
    Normalize a path for consistent comparisons.
    Similar to WebUI's normalizePath function.

    Rules:
    - Remove leading "./"
    - Remove trailing "/" (except for root)
    - Keep "/" as separator
    - Empty string becomes "."
    """
    if not isinstance(p, str):
        return "."

    p = p.strip()

    # Handle absolute root
    if p == "/":
        return "/"

    # Remove leading "./"
    if p.startswith("./"):
        p = p[2:]

    # Remove trailing "/" (but not if it's just "/")
    if len(p) > 1 and p.endswith("/"):
        p = p[:-1]

    # Empty becomes "."
    if p == "":
        return "."

    return p


def normalize_repo_id(s: str) -> str:
    """
    Normalize repository identifiers for robust matching.
    Handles common drift forms:
      - leading './'
      - trailing '/'
      - backslashes
      - accidental path inputs (hub/foo -> foo)
      - case drift (pragmatic on iOS)
    """
    s = str(s).strip().replace("\\", "/")
    # Drop leading "./" repeatedly
    while s.startswith("./"):
        s = s[2:]
    # Drop trailing slashes
    s = s.rstrip("/")
    # If a path slipped in, keep last segment
    if "/" in s:
        s = s.split("/")[-1]
    # Pragmatic: collapse case drift
    s = s.lower()
    return s


def safe_script_path() -> Path:
    """
    Versucht, den Pfad dieses Skripts robust zu bestimmen.

    Reihenfolge:
    1. __file__ (Standard-Python)
    2. sys.argv[0] (z. B. in Shortcuts / eingebetteten Umgebungen)
    3. aktuelle Arbeitsdirectory (Last Resort)
    """
    try:
        return Path(__file__).resolve()
    except NameError:
        # Pythonista / Shortcuts oder exotischer Kontext
        argv0 = None
        try:
            if getattr(sys, "argv", None):
                argv0 = sys.argv[0] or None
        except Exception:
            argv0 = None

        if argv0:
            try:
                return Path(argv0).resolve()
            except Exception as e:
                sys.stderr.write(f"Warning: Failed to resolve argv0 path: {e}\n")

        # Fallback: aktuelle Arbeitsdirectory
        return Path.cwd().resolve()
