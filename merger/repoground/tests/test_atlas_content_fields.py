import json
from pathlib import Path
from unittest.mock import patch

from merger.repoground.adapters.atlas import AtlasScanner, count_lines

def test_detect_mime_type_with_enable_content_stats(tmp_path: Path):
    """
    Test that mime_type is correctly identified and recorded when enable_content_stats is True.
    """
    test_dir = tmp_path / "test_mime"
    test_dir.mkdir()

    # Create various types of files

    # 1. Plain text file with extension
    text_file = test_dir / "text_file.txt"
    text_file.write_text("Hello World!")

    # 2. PDF file with correct magic bytes but no extension
    pdf_file = test_dir / "pdf_no_ext"
    with pdf_file.open("wb") as f:
        f.write(b"%PDF-1.4\n...")

    # 3. Binary file without recognized magic bytes
    bin_file = test_dir / "random.dat"
    with bin_file.open("wb") as f:
        f.write(b"\x00\x01\x02\x03\x04\x05")

    # 4. Unknown text file (no extension, text content)
    unknown_text = test_dir / "unknown_text"
    unknown_text.write_text("This is just some text content.")

    inv_file = tmp_path / "inventory.jsonl"

    scanner = AtlasScanner(
        root=test_dir,
        snapshot_id="test_snap",
        enable_content_stats=True
    )
    scanner.scan(inventory_file=inv_file)

    assert inv_file.exists()

    # Parse inventory
    results = {}
    with inv_file.open("r", encoding="utf-8") as f:
        for line in f:
            entry = json.loads(line)
            results[entry["name"]] = entry

    assert results["text_file.txt"]["mime_type"] == "text/plain"
    assert results["pdf_no_ext"]["mime_type"] == "application/pdf"
    assert results["random.dat"]["mime_type"] == "application/octet-stream"
    assert results["unknown_text"]["mime_type"] == "text/plain"

    # Check encodings for text files
    assert results["text_file.txt"].get("encoding") == "utf-8"
    assert results["unknown_text"].get("encoding") == "utf-8"
    # PDF is recognized as application/pdf and should NOT get an encoding field,
    # even though it contains b"%PDF-1.4\n..." without null bytes.
    assert "encoding" not in results["pdf_no_ext"]
    assert "encoding" not in results["random.dat"]


def test_count_lines_with_enable_content_stats(tmp_path: Path):
    """
    Test that line_count is correctly computed for text files, including non-utf-8 encodings.
    """
    test_dir = tmp_path / "test_lines"
    test_dir.mkdir()

    file1 = test_dir / "file1.txt"
    file1.write_text("Line 1\nLine 2\nLine 3\n")

    file2 = test_dir / "file2.txt"
    file2.write_text("Single line")

    file3 = test_dir / "empty.txt"
    file3.write_text("")

    file4 = test_dir / "utf16.txt"
    file4.write_bytes("Line 1\nLine 2\nLine 3\n".encode("utf-16"))

    inv_file = tmp_path / "inventory.jsonl"

    scanner = AtlasScanner(
        root=test_dir,
        snapshot_id="test_snap",
        enable_content_stats=True
    )
    scanner.scan(inventory_file=inv_file)

    results = {}
    with inv_file.open("r", encoding="utf-8") as f:
        for line in f:
            entry = json.loads(line)
            results[entry["name"]] = entry.get("line_count")

    assert results["file1.txt"] == 3
    assert results["file2.txt"] == 1
    assert results["empty.txt"] == 0
    assert results["utf16.txt"] == 3

def test_count_lines_skips_huge_files(tmp_path: Path):
    """
    Test that count_lines skips files larger than 20MB.
    """
    huge_file = tmp_path / "huge.txt"
    huge_file.write_text("Hello\nWorld")

    # Simulate a file size > 20MB without writing 20MB to disk
    result = count_lines(huge_file, size=21 * 1024 * 1024)
    assert result is None

def test_detect_encoding_with_enable_content_stats(tmp_path: Path):
    """
    Test that encoding is correctly identified for different file encodings.
    """
    test_dir = tmp_path / "test_encoding"
    test_dir.mkdir()

    # UTF-8
    utf8_file = test_dir / "utf8.txt"
    utf8_file.write_text("Hello World!")

    # UTF-16
    utf16_file = test_dir / "utf16.txt"
    utf16_file.write_bytes("Hello World!".encode("utf-16"))

    # ISO-8859-1 (Latin-1)
    iso_file = test_dir / "iso.txt"
    iso_file.write_bytes("Héllö".encode("iso-8859-1"))

    inv_file = tmp_path / "inventory.jsonl"

    scanner = AtlasScanner(
        root=test_dir,
        snapshot_id="test_snap",
        enable_content_stats=True
    )
    scanner.scan(inventory_file=inv_file)

    assert inv_file.exists()

    # Parse inventory
    results = {}
    with inv_file.open("r", encoding="utf-8") as f:
        for line in f:
            entry = json.loads(line)
            results[entry["name"]] = entry.get("encoding")

    assert results["utf8.txt"] == "utf-8"
    assert results["utf16.txt"] == "utf-16"
    assert results["iso.txt"] in ["iso-8859-1", "windows-1252"]

def test_no_mime_type_when_content_stats_disabled(tmp_path: Path):
    """
    Test that mime_type is omitted when enable_content_stats is False.
    """
    test_dir = tmp_path / "test_no_mime"
    test_dir.mkdir()

    text_file = test_dir / "file.txt"
    text_file.write_text("Hello")

    inv_file = tmp_path / "inventory.jsonl"

    scanner = AtlasScanner(
        root=test_dir,
        snapshot_id="test_snap",
        enable_content_stats=False
    )
    scanner.scan(inventory_file=inv_file)

    with inv_file.open("r", encoding="utf-8") as f:
        entry = json.loads(f.readline())
        assert "mime_type" not in entry
        assert "encoding" not in entry
        assert "line_count" not in entry

def test_incremental_mime_reuse(tmp_path: Path):
    """
    Test that mime_type is reused during incremental scans.
    """
    test_dir = tmp_path / "test_incremental"
    test_dir.mkdir()

    text_file = test_dir / "file.txt"
    text_file.write_text("Data")

    inv_file1 = tmp_path / "inventory1.jsonl"
    scanner1 = AtlasScanner(root=test_dir, snapshot_id="snap1", enable_content_stats=True)
    scanner1.scan(inventory_file=inv_file1)

    # Scan again with incremental reuse
    inv_file2 = tmp_path / "inventory2.jsonl"
    scanner2 = AtlasScanner(
        root=test_dir,
        snapshot_id="snap2",
        enable_content_stats=True,
        incremental_inventory=inv_file1,
        previous_scan_config_hash="hash1",
        current_scan_config_hash="hash1"
    )
    scanner2.scan(inventory_file=inv_file2)

    with inv_file2.open("r", encoding="utf-8") as f:
        entry = json.loads(f.readline())
        assert entry["mime_type"] == "text/plain"
        assert entry["encoding"] == "utf-8"
        assert entry["line_count"] == 1

    # Assert reuse stats
    assert scanner2.stats["incremental"]["reused_files_count"] == 1

def test_mime_type_not_calculated_when_stats_disabled(tmp_path: Path):
    """
    Test that detect_mime_type is not even called when enable_content_stats=False,
    saving unnecessary computation.
    """
    test_dir = tmp_path / "test_no_calc"
    test_dir.mkdir()
    (test_dir / "file.txt").write_text("Hello")

    scanner = AtlasScanner(
        root=test_dir,
        snapshot_id="test_snap",
        enable_content_stats=False
    )

    with patch("merger.repoground.adapters.atlas.detect_mime_type") as mock_detect:
        scanner.scan(inventory_file=tmp_path / "inv.jsonl")

    # Assert that the function was never called
    mock_detect.assert_not_called()

def test_no_mime_type_incremental_when_stats_disabled(tmp_path: Path):
    """
    Test that even if incremental inventory has mime_type, it is not emitted if enable_content_stats=False.
    """
    test_dir = tmp_path / "test_incremental_disabled"
    test_dir.mkdir()

    text_file = test_dir / "file.txt"
    text_file.write_text("Data")

    # Force a previous inventory that HAS content stats
    inv_file1 = tmp_path / "inventory1.jsonl"
    scanner1 = AtlasScanner(root=test_dir, snapshot_id="snap1", enable_content_stats=True)
    scanner1.scan(inventory_file=inv_file1)

    with inv_file1.open("r", encoding="utf-8") as f:
        entry = json.loads(f.readline())
        assert "mime_type" in entry

    # Scan again with incremental reuse, but content stats DISABLED
    inv_file2 = tmp_path / "inventory2.jsonl"
    scanner2 = AtlasScanner(
        root=test_dir,
        snapshot_id="snap2",
        enable_content_stats=False,
        incremental_inventory=inv_file1,
        previous_scan_config_hash="hash1",
        current_scan_config_hash="hash1"
    )
    scanner2.scan(inventory_file=inv_file2)

    with inv_file2.open("r", encoding="utf-8") as f:
        entry = json.loads(f.readline())
        assert "mime_type" not in entry
        assert "encoding" not in entry
        assert "line_count" not in entry

    # The file itself should be counted as reused in terms of base file metadata
    assert scanner2.stats["incremental"]["reused_files_count"] == 1

def test_atlas_is_huge_serialization(tmp_path: Path):
    """
    Test that is_huge is correctly serialized into the inventory
    if the file exceeds max_file_size.
    """
    test_dir = tmp_path / "test_is_huge"
    test_dir.mkdir()

    # Small file
    small_file = test_dir / "small.txt"
    small_file.write_text("Hello")  # 5 bytes

    # Huge file (for our scanner max_size = 10)
    huge_file = test_dir / "huge.txt"
    huge_file.write_text("This is definitely larger than ten bytes.")  # 41 bytes

    inv_file = tmp_path / "inventory.jsonl"

    scanner = AtlasScanner(
        root=test_dir,
        snapshot_id="test_snap",
        enable_content_stats=True,
        max_file_size=10
    )
    scanner.scan(inventory_file=inv_file)

    results = {}
    with inv_file.open("r", encoding="utf-8") as f:
        for line in f:
            entry = json.loads(line)
            results[entry["name"]] = entry

    assert results["huge.txt"].get("is_huge") is True
    assert "is_huge" not in results["small.txt"]
