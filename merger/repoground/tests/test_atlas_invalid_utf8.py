import os
import json
import pytest
from pathlib import Path
from merger.repoground.adapters.atlas import AtlasScanner

def test_atlas_invalid_utf8_filename(tmp_path: Path):
    """
    Regression test to ensure AtlasScanner does not crash when encountering
    filenames with invalid UTF-8 byte sequences (which Python decodes using
    surrogateescape on Unix).
    """
    # Create a file with invalid UTF-8 bytes in its name
    # \xff is an invalid UTF-8 start byte
    bad_name_bytes = b"invalid_\xff_name.txt"

    try:
        # Create the file using bytes path
        bad_path_bytes = os.path.join(os.fsencode(tmp_path), bad_name_bytes)
        with open(bad_path_bytes, 'wb') as f:
            f.write(b"content")
    except OSError:
        # If the filesystem does not support this (e.g. Windows), skip the test
        pytest.skip("Filesystem does not support invalid UTF-8 bytes in filenames")

    # Run AtlasScanner
    scanner = AtlasScanner(tmp_path, snapshot_id="dummy_snap")

    inventory_file = tmp_path / "inventory.jsonl"
    dirs_inventory_file = tmp_path / "dirs_inventory.jsonl"

    # A) Verify scan() does NOT raise UnicodeEncodeError
    try:
        scanner.scan(inventory_file=inventory_file, dirs_inventory_file=dirs_inventory_file)
    except UnicodeEncodeError as e:
        pytest.fail(f"Scanner crashed with UnicodeEncodeError: {e}")

    # B) Verify inventory files exist
    assert inventory_file.exists(), "Inventory file was not created"
    assert dirs_inventory_file.exists(), "Dirs inventory file was not created"

    # C) Verify inventory files are valid UTF-8
    try:
        content = inventory_file.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        pytest.fail("Inventory file is not valid UTF-8")

    try:
        dirs_inventory_file.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        pytest.fail("Dirs inventory file is not valid UTF-8")

    # D) Verify inventory contains the file and it has escaped unicode sequences
    lines = content.strip().split("\n")

    # Find the entry for the file with the invalid name
    target_entry = None
    parsed_names = []

    for line in lines:
        if not line.strip():
            continue
        entry = json.loads(line)
        parsed_names.append(entry["name"])
        if entry["name"].startswith("invalid_") and entry["name"].endswith("_name.txt"):
            target_entry = entry
            break

    assert target_entry is not None, f"Target file with invalid utf-8 was not found in the inventory. Found names: {parsed_names[:20]}"

    # Check that the filename string contains escaped unicode sequences.
    # When python parses the JSON \uXXXX string, it restores the surrogate character.
    # The original \xff byte becomes \udcff due to surrogateescape.
    assert "invalid_\udcff_name.txt" in target_entry["name"]

    # If we read the raw text of the JSONL file, we should see the explicit escape sequence
    assert "\\udcff" in content, "Expected JSON serialization to escape the specific surrogate character using surrogateescape (\\udcff)"
