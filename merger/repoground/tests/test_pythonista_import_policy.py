import pytest
from pathlib import Path
import re

# Define the target directory relative to this test file
# Location: merger/repoground/tests/test_pythonista_import_policy.py
# Target:   merger/repoground/frontends/pythonista/
PYTHONISTA_DIR = Path(__file__).resolve().parents[2] / "repoground" / "frontends" / "pythonista"

# Regex to find "from ." or "from .xyz"
# We strictly forbid relative imports to ensure Pythonista compatibility
RELATIVE_IMPORT_PATTERN = re.compile(r"^\s*from\s+\.", re.MULTILINE)

def test_pythonista_has_no_relative_imports():
    """
    Enforces the 'Option 1' Architecture Policy:
    Files in 'frontends/pythonista' must use absolute imports (flat layout),
    relying on sys.path manipulation in the entry point rather than relative package imports.
    """
    if not PYTHONISTA_DIR.exists():
        pytest.skip(f"Pythonista directory not found at {PYTHONISTA_DIR}")

    offenders = []

    # Scan all .py files in the directory recursively to ensure no subdirectories sneak in relative imports
    for p in PYTHONISTA_DIR.rglob("*.py"):
        # We enforce flat script layout for Pythonista compatibility.
        # Even __init__.py should avoid relative imports if it's meant to run in this specific environment,
        # though standard package rules might argue otherwise. Here, flat script wins.

        try:
            content = p.read_text(encoding="utf-8")
        except Exception as e:
            print(f"Warning: Could not read {p}: {e}")
            continue

        if RELATIVE_IMPORT_PATTERN.search(content):
            # Report relative path for better context in recursive scan
            rel_path = p.relative_to(PYTHONISTA_DIR)
            offenders.append(str(rel_path))

    assert not offenders, (
        f"Relative imports found in Pythonista frontend files: {offenders}. "
        "POLICY: The Pythonista frontend uses a 'flat script' layout to ensure standalone execution on iOS. "
        "Relative imports (from . import ...) are forbidden. "
        "Use absolute imports (e.g. 'from build_utils import ...') and ensure sys.path is managed in entry points."
    )
