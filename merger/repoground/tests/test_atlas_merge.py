from merger.repoground.adapters.atlas import AtlasScanner

def test_atlas_merge_single_folder(tmp_path):
    target_dir = tmp_path / "myfolder"
    target_dir.mkdir()

    (target_dir / "a.txt").write_text("Content A", encoding="utf-8")
    (target_dir / "b.md").write_text("Content B", encoding="utf-8")
    (target_dir / "c.bin").write_bytes(b"\x89\x00\x01\x02") # Binary
    (target_dir / "sub").mkdir() # Subdir should be ignored
    (target_dir / "sub" / "d.txt").write_text("Content D", encoding="utf-8")

    output_file = tmp_path / "merged.txt"

    scanner = AtlasScanner(tmp_path)
    result = scanner.merge_folder("myfolder", output_file)

    assert output_file.exists()
    content = output_file.read_text(encoding="utf-8")

    # Check structure
    assert "===== FILE: myfolder/a.txt =====" in content
    assert "Content A" in content
    assert "===== FILE: myfolder/b.md =====" in content
    assert "Content B" in content

    # Check binary skip
    assert "===== SKIPPED FILES =====" in content
    assert "myfolder/c.bin (binary/non-text)" in content

    # Check non-recursive (subdir ignored)
    assert "myfolder/sub/d.txt" not in content

    # Result dict
    assert "myfolder/a.txt" in result["merged"]
    assert "myfolder/b.md" in result["merged"]
    # merged is list of strings (paths)
    assert "myfolder/c.bin" not in result["merged"]

def test_atlas_merge_recursive_and_limits(tmp_path):
    target_dir = tmp_path / "rec"
    target_dir.mkdir()
    (target_dir / "root.txt").write_text("Root")
    (target_dir / "sub").mkdir()
    (target_dir / "sub/deep.txt").write_text("Deep")

    output_file = tmp_path / "rec_merged.txt"
    scanner = AtlasScanner(tmp_path)

    # Test recursive
    scanner.merge_folder("rec", output_file, recursive=True)
    content = output_file.read_text(encoding="utf-8")

    assert "rec/root.txt" in content
    assert "rec/sub/deep.txt" in content
    assert "Recursive: True" in content

    # Test Max Files Limit
    output_limit = tmp_path / "limit_merged.txt"
    result_limit = scanner.merge_folder("rec", output_limit, recursive=True, max_files=1)
    content_limit = output_limit.read_text(encoding="utf-8")

    assert "MERGE TRUNCATED: max_files reached" in content_limit
    assert result_limit["truncated"] == "max_files"
