from pathlib import Path
import json
from merger.repoground.adapters.atlas import AtlasScanner

def test_is_excluded_handles_backslashes():
    # Use simpler pattern to test normalization logic specifically
    # Exclude "secret/file.txt"
    scanner = AtlasScanner(Path("."), exclude_globs=["secret/file.txt"])

    # Test path with backslash - should be normalized to match "secret/file.txt"
    assert scanner._is_excluded("secret\\file.txt") is True

    # Control case
    assert scanner._is_excluded("secret/file.txt") is True

    # Should not match
    assert scanner._is_excluded("public\\file.txt") is False

def test_is_excluded_handles_mixed_slashes_glob():
    # Test normalization with standard glob
    scanner = AtlasScanner(Path("."), exclude_globs=["**/node_modules/**"])

    assert scanner._is_excluded("project\\node_modules/package.json") is True

def test_is_excluded_rejects_absolute_and_traversal_strings():
    # Guardrail tests for string inputs to enforce relative semantics
    # Glob pattern doesn't matter much here, checking guardrail logic
    scanner = AtlasScanner(Path("."), exclude_globs=["**/*.txt"])

    # Absolute POSIX path
    assert scanner._is_excluded("/etc/passwd") is True

    # Parent traversal
    assert scanner._is_excluded("../secret/file.txt") is True
    assert scanner._is_excluded("subdir/../file.txt") is True

    # Windows drive letter (absolute)
    assert scanner._is_excluded("C:\\secret\\file.txt") is True
    assert scanner._is_excluded("D:/data/file.txt") is True

    # UNC path (absolute)
    assert scanner._is_excluded("\\\\server\\share\\file.txt") is True
    assert scanner._is_excluded("//server/share/file.txt") is True

def test_scan_integration_excludes(tmp_path):
    # Setup temp directory structure
    (tmp_path / "public").mkdir()
    (tmp_path / "public" / "ok.txt").touch()

    (tmp_path / "secret").mkdir()
    (tmp_path / "secret" / "hidden.txt").touch()

    # Initialize scanner excluding "secret" folder
    # Using relative path pattern
    scanner = AtlasScanner(tmp_path, snapshot_id="dummy_snap", exclude_globs=["secret/**"])

    inventory_file = tmp_path / "inventory.jsonl"
    scanner.scan(inventory_file=inventory_file)

    # Read inventory
    paths = []
    decoded_entries = 0
    with inventory_file.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                paths.append(entry["rel_path"])
                decoded_entries += 1
            except json.JSONDecodeError:
                continue

    # Assert that we actually processed something to avoid false positives
    assert decoded_entries > 0, "Inventory produced no valid JSON entries; test may be skipping content."

    # Verification
    # "public/ok.txt" should be present
    assert "public/ok.txt" in paths
    # "secret/hidden.txt" should be excluded
    assert "secret/hidden.txt" not in paths
