import os
from pathlib import Path

# Define forbidden strings
FORBIDDEN_STRINGS = [
    "repolens-agent.v1",
    'contract_version": "v1"',
    "contract_version': 'v1'",
    'contract_version = "v1"',
    "contract_version = 'v1'",
]

# Paths to ignore (e.g., this test file itself)
IGNORE_FILES = {
    "test_contract_version_guards.py",
}

# Only scan these extensions to avoid binary noise and speed up test
TEXT_EXTENSIONS = {".py", ".md", ".json", ".yml", ".yaml", ".txt"}

def test_no_stale_v1_references():
    """
    Guard ensuring that no stale 'v1' contract references remain in the codebase.
    """
    # Start scanning from merger/repoground
    base_dir = Path(__file__).parent.parent

    found_violations = []

    for root, dirs, files in os.walk(base_dir):
        # Skip __pycache__ and hidden dirs
        dirs[:] = [d for d in dirs if not d.startswith("__") and not d.startswith(".")]

        for fname in files:
            if fname in IGNORE_FILES:
                continue

            path = Path(root) / fname

            # Skip documentation files as they often contain historical v1 references as text
            try:
                p_rel = path.relative_to(base_dir).as_posix()
            except ValueError:
                p_rel = path.as_posix()

            if p_rel.startswith("docs/") or p_rel.startswith("merger/repoground/docs/"):
                continue

            # Check extension
            if path.suffix.lower() not in TEXT_EXTENSIONS:
                continue

            try:
                content = path.read_text(encoding="utf-8", errors="ignore")
                lines = content.splitlines()
                for i, line in enumerate(lines):
                    # Allow dump-index, architecture-summary and derived-index to use v1
                    if any(x in line for x in ("dump-index", "architecture-summary", "derived-index")):
                        continue

                    # Context check for dump-index, derived-index, architecture-summary (multi-line)
                    # If we found forbidden string, check context
                    found_forbidden = False
                    for forbidden in FORBIDDEN_STRINGS:
                        if forbidden in line:
                            found_forbidden = True
                            break

                    if found_forbidden:
                        # Check surrounding lines
                        # Look back 8 lines
                        start = max(0, i - 8)
                        context = "\n".join(lines[start:i+1])
                        if any(x in context for x in ("dump-index", "derived-index", "architecture-summary")):
                            continue

                        found_violations.append(f"{path}: Found '{forbidden}'")
            except Exception as e:
                print(f"Warning: could not read {path}: {e}")

    assert not found_violations, "Found stale v1 contract references:\n" + "\n".join(found_violations)
