#!/usr/bin/env python3
import sys
from pathlib import Path


FORBIDDEN_STUBS_PATH = Path("merger/repoground/tests/stubs")


def check_no_test_stubs() -> None:
    """Reject the test-stub path that can shadow installed dependencies."""
    repo_root = Path(__file__).resolve().parent.parent
    stubs_path = repo_root / FORBIDDEN_STUBS_PATH

    # Path.exists() is false for a dangling symlink. The symlink itself is still
    # forbidden because replacing its target could silently reactivate shadowing.
    if stubs_path.exists() or stubs_path.is_symlink():
        print(f"ERROR: Forbidden path found: {stubs_path}")
        print("FAIL: Test stubs can shadow installed dependencies.")
        print("Please remove this path and use the real dependencies instead.")
        sys.exit(1)

    print("OK: No forbidden 'tests/stubs' directory found.")
    sys.exit(0)


if __name__ == "__main__":
    check_no_test_stubs()
