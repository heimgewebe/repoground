import os
import json
from datetime import datetime, timezone
from pathlib import Path
from merger.repoground.adapters.atlas import AtlasScanner

def test_incremental_scan_reuses_unchanged_files(tmp_path: Path):
    # Setup test directory
    root_dir = tmp_path / "test_root"
    root_dir.mkdir()

    file1 = root_dir / "file1.txt"
    file1.write_text("Hello World!")

    file2 = root_dir / "file2.txt"
    file2.write_text("Unchanged content")

    inventory_file1 = tmp_path / "inventory1.jsonl"

    # Run baseline scan
    scanner1 = AtlasScanner(
        root=root_dir,
        snapshot_id="snap1",
        enable_content_stats=True
    )
    result1 = scanner1.scan(inventory_file=inventory_file1)
    stats1 = result1["stats"]

    assert stats1["incremental"]["reused_files_count"] == 0
    assert stats1["total_files"] == 2

    # Modify one file, leave the other
    file1.write_text("Hello Incremental World!")

    # Explicitly set a newer mtime to ensure the heuristic correctly catches it
    old_mtime = file1.stat().st_mtime
    os.utime(file1, (old_mtime + 10.0, old_mtime + 10.0))

    new_mtime = file1.stat().st_mtime
    assert new_mtime > old_mtime, "mtime must be strictly newer for heuristic test"

    # Add a new file
    file3 = root_dir / "file3.txt"
    file3.write_text("New file")

    # Run incremental scan
    inventory_file2 = tmp_path / "inventory2.jsonl"
    scanner2 = AtlasScanner(
        root=root_dir,
        snapshot_id="snap2",
        enable_content_stats=True,
        incremental_inventory=inventory_file1
    )
    result2 = scanner2.scan(inventory_file=inventory_file2)
    stats2 = result2["stats"]

    assert stats2["total_files"] == 3

    # file2 should be reused
    assert stats2["incremental"]["reused_files_count"] == 1

    # file1 was modified, file3 is new -> so 2 files analysed, 1 skipped.
    assert stats2["incremental"]["skipped_analysis_count"] == 1

    # Verify the new inventory file
    inv_data = {}
    with inventory_file2.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip(): continue
            item = json.loads(line)
            inv_data[item["rel_path"]] = item

    assert "file1.txt" in inv_data
    assert "file2.txt" in inv_data
    assert "file3.txt" in inv_data

    # Ensure inode and device are captured
    assert "inode" in inv_data["file1.txt"]
    assert "device" in inv_data["file1.txt"]

def test_incremental_scan_dict_input(tmp_path: Path):
    root_dir = tmp_path / "test_root_dict"
    root_dir.mkdir()

    file1 = root_dir / "dict_file.txt"
    file1.write_text("Some dict content")

    # Manually construct fake prior inventory dict
    stat = file1.stat()
    mtime_iso = datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat().replace('+00:00', 'Z')
    fake_inv = {
        "dict_file.txt": {
            "rel_path": "dict_file.txt",
            "size_bytes": stat.st_size,
            "mtime": mtime_iso,
            "is_text": True
        }
    }

    inventory_file = tmp_path / "inventory_dict.jsonl"
    scanner = AtlasScanner(
        root=root_dir,
        snapshot_id="snap_dict",
        enable_content_stats=True,
        incremental_inventory=fake_inv
    )
    result = scanner.scan(inventory_file=inventory_file)

    # The file exactly matches our fake dictionary entry
    assert result["stats"]["incremental"]["reused_files_count"] == 1

def test_incremental_scan_handles_malformed_jsonl(tmp_path: Path):
    root_dir = tmp_path / "test_root_malformed"
    root_dir.mkdir()

    # Create the valid file we expect to be reused
    file_valid = root_dir / "valid_file.txt"
    file_valid.write_text("Valid content")

    # Get current stats to spoof the JSONL entry
    stat = file_valid.stat()
    mtime_iso = datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat().replace('+00:00', 'Z')

    # Create a malformed incremental_inventory.jsonl
    inventory_file = tmp_path / "malformed_inventory.jsonl"
    with inventory_file.open("w", encoding="utf-8") as f:
        # Line 1: Completely broken JSON
        f.write("{ broken json line \n")

        # Line 2: Valid JSON, missing rel_path
        f.write('{"name": "missing_rel_path.txt", "size_bytes": 100}\n')

        # Line 3: Valid JSON with rel_path (the one we want reused)
        valid_entry = {
            "rel_path": "valid_file.txt",
            "size_bytes": stat.st_size,
            "mtime": mtime_iso,
            "is_text": True
        }
        f.write(json.dumps(valid_entry) + "\n")

        # Line 4: Wrong type for rel_path
        f.write('{"rel_path": 123, "size_bytes": 100}\n')

    # Run the scanner
    out_inventory_file = tmp_path / "out_inventory.jsonl"
    scanner = AtlasScanner(
        root=root_dir,
        snapshot_id="snap_malformed",
        enable_content_stats=True,
        incremental_inventory=inventory_file
    )

    result = scanner.scan(inventory_file=out_inventory_file)
    stats = result["stats"]

    # The scanner should not have crashed.
    # It should have successfully parsed the valid entry and reused the file.
    assert stats["total_files"] == 1
    assert stats["incremental"]["reused_files_count"] == 1

    # Verify the internal dictionary state of the scanner
    assert "valid_file.txt" in scanner.incremental_inventory
    assert len(scanner.incremental_inventory) == 1

def test_incremental_scan_config_hash_invalidation(tmp_path: Path):
    root_dir = tmp_path / "test_root_config"
    root_dir.mkdir()

    file1 = root_dir / "config_file.txt"
    file1.write_text("Hello Config Hash!")

    inventory_file1 = tmp_path / "inventory_cfg1.jsonl"

    # Scan 1 with config_hash_A
    scanner1 = AtlasScanner(
        root=root_dir,
        snapshot_id="snap1",
        enable_content_stats=True,
        current_scan_config_hash="hash_A"
    )
    res1 = scanner1.scan(inventory_file=inventory_file1)

    assert res1["stats"]["total_files"] == 1

    # Read the inventory to verify `is_text` is present
    with inventory_file1.open("r", encoding="utf-8") as f:
        inv1_data = json.loads(f.read().strip())
    assert inv1_data["is_text"] is True

    inventory_file2 = tmp_path / "inventory_cfg2.jsonl"

    # Scan 2 with config_hash_B
    scanner2 = AtlasScanner(
        root=root_dir,
        snapshot_id="snap2",
        enable_content_stats=True,
        incremental_inventory=inventory_file1,
        previous_scan_config_hash="hash_A",
        current_scan_config_hash="hash_B"
    )
    res2 = scanner2.scan(inventory_file=inventory_file2)
    stats2 = res2["stats"]

    # Because config hash changed, `is_text` cache must be invalidated.
    # Therefore skipped_analysis_count should be 0 despite file being reused.
    assert stats2["incremental"]["reused_files_count"] == 1
    assert stats2["incremental"]["skipped_analysis_count"] == 0

def test_incremental_scan_quick_hash_reuse(tmp_path: Path):
    root_dir = tmp_path / "test_root_quick_hash"
    root_dir.mkdir()

    file1 = root_dir / "hash_file.txt"
    file1.write_text("Hello Quick Hash!")

    inventory_file1 = tmp_path / "inventory_hash1.jsonl"

    # Scan 1 to establish baseline and quick_hash
    scanner1 = AtlasScanner(
        root=root_dir,
        snapshot_id="snap1",
        enable_content_stats=True
    )
    scanner1.scan(inventory_file=inventory_file1)

    with inventory_file1.open("r", encoding="utf-8") as f:
        inv1_data = json.loads(f.read().strip())

    assert "quick_hash" in inv1_data

    # Touch the file to bump mtime, keeping size and content identical
    old_mtime = file1.stat().st_mtime
    new_mtime = old_mtime + 10.0
    os.utime(file1, (new_mtime, new_mtime))

    assert file1.stat().st_mtime > old_mtime

    inventory_file2 = tmp_path / "inventory_hash2.jsonl"

    # Scan 2: Should use quick_hash because mtime changed but size matched
    scanner2 = AtlasScanner(
        root=root_dir,
        snapshot_id="snap2",
        enable_content_stats=True,
        incremental_inventory=inventory_file1
    )
    res2 = scanner2.scan(inventory_file=inventory_file2)
    stats2 = res2["stats"]

    # It should correctly identify it as reused and skip analysis
    assert stats2["incremental"]["reused_files_count"] == 1
    assert stats2["incremental"]["skipped_analysis_count"] == 1

    with inventory_file2.open("r", encoding="utf-8") as f:
        inv2_data = json.loads(f.read().strip())

    # Check that quick_hash persists and matches
    assert "quick_hash" in inv2_data
    assert inv1_data["quick_hash"] == inv2_data["quick_hash"]

def test_incremental_scan_directory_aggregates_rollup(tmp_path: Path):
    root_dir = tmp_path / "test_root_rollup"
    root_dir.mkdir()

    # Create structure:
    # root/
    #   file_a.txt (size 10)
    #   child_dir/
    #     file_b.txt (size 20)
    #     grandchild_dir/
    #       file_c.txt (size 30)

    file_a = root_dir / "file_a.txt"
    file_a.write_bytes(b"0123456789")

    child_dir = root_dir / "child_dir"
    child_dir.mkdir()
    file_b = child_dir / "file_b.txt"
    file_b.write_bytes(b"01234567890123456789")

    grandchild_dir = child_dir / "grandchild_dir"
    grandchild_dir.mkdir()
    file_c = grandchild_dir / "file_c.txt"
    file_c.write_bytes(b"012345678901234567890123456789")

    # Give file_c an explicitly newer mtime than the rest to verify propagation
    base_mtime = file_a.stat().st_mtime
    os.utime(file_c, (base_mtime + 100.0, base_mtime + 100.0))
    expected_max_mtime = datetime.fromtimestamp(file_c.stat().st_mtime, timezone.utc).isoformat().replace('+00:00', 'Z')

    dirs_file = tmp_path / "dirs.jsonl"
    scanner = AtlasScanner(
        root=root_dir,
        snapshot_id="snap_rollup"
    )
    scanner.scan(dirs_inventory_file=dirs_file)

    dirs_data = {}
    with dirs_file.open("r", encoding="utf-8") as f:
        for line in f:
            item = json.loads(line)
            dirs_data[item["rel_path"]] = item

    # Verify Grandchild
    gc = dirs_data["child_dir/grandchild_dir"]
    assert gc["n_files"] == 1
    assert gc["subtree_file_count"] == 1
    assert gc["subtree_dir_count"] == 0
    assert gc["subtree_total_bytes"] == 30
    assert gc["max_descendant_mtime"] == expected_max_mtime

    # Verify Child
    cd = dirs_data["child_dir"]
    assert cd["n_files"] == 1
    assert cd["n_dirs"] == 1
    assert cd["subtree_file_count"] == 2
    assert cd["subtree_dir_count"] == 1
    assert cd["subtree_total_bytes"] == 50
    assert cd["max_descendant_mtime"] == expected_max_mtime

    # Verify Root
    rd = dirs_data["."]
    assert rd["n_files"] == 1
    assert rd["n_dirs"] == 1
    assert rd["subtree_file_count"] == 3
    assert rd["subtree_dir_count"] == 2
    assert rd["subtree_total_bytes"] == 60
    assert rd["max_descendant_mtime"] == expected_max_mtime

    # Verify that recursive_hash is properly populated
    assert "recursive_hash" in gc
    assert "recursive_hash" in cd
    assert "recursive_hash" in rd

    # We shouldn't export these internal state tracking variables
    assert "direct_file_signatures" not in gc
    assert "child_dir_hashes" not in gc

def test_recursive_hash_determinism_and_bubbling(tmp_path: Path):
    from merger.repoground.adapters.atlas import AtlasScanner
    import json

    root_dir = tmp_path / "test_root_recursive_hash"
    root_dir.mkdir()

    # Create structure:
    # root/
    #   file_a.txt
    #   child_dir/
    #     file_b.txt

    file_a = root_dir / "file_a.txt"
    file_a.write_bytes(b"A_CONTENT")

    child_dir = root_dir / "child_dir"
    child_dir.mkdir()
    file_b = child_dir / "file_b.txt"
    file_b.write_bytes(b"B_CONTENT")

    file_b_stat = file_b.stat()

    # Scan 1
    dirs_file1 = tmp_path / "dirs1.jsonl"
    scanner1 = AtlasScanner(root=root_dir, snapshot_id="snap1")
    scanner1.scan(dirs_inventory_file=dirs_file1)

    dirs_data1 = {}
    with dirs_file1.open("r", encoding="utf-8") as f:
        for line in f:
            item = json.loads(line)
            dirs_data1[item["rel_path"]] = item

    hash_root1 = dirs_data1["."]["recursive_hash"]
    hash_child1 = dirs_data1["child_dir"]["recursive_hash"]

    # Scan 2 without any changes -> Hashes must be identical
    dirs_file2 = tmp_path / "dirs2.jsonl"
    scanner2 = AtlasScanner(root=root_dir, snapshot_id="snap2")
    scanner2.scan(dirs_inventory_file=dirs_file2)

    dirs_data2 = {}
    with dirs_file2.open("r", encoding="utf-8") as f:
        for line in f:
            item = json.loads(line)
            dirs_data2[item["rel_path"]] = item

    assert dirs_data2["."]["recursive_hash"] == hash_root1
    assert dirs_data2["child_dir"]["recursive_hash"] == hash_child1

    # Modify deep descendant
    file_b.write_bytes(b"B_CONTENT_MODIFIED")

    # Scan 3 -> Hashes must bubble up and change
    dirs_file3 = tmp_path / "dirs3.jsonl"
    scanner3 = AtlasScanner(root=root_dir, snapshot_id="snap3")
    scanner3.scan(dirs_inventory_file=dirs_file3)

    dirs_data3 = {}
    with dirs_file3.open("r", encoding="utf-8") as f:
        for line in f:
            item = json.loads(line)
            dirs_data3[item["rel_path"]] = item

    hash_root3 = dirs_data3["."]["recursive_hash"]
    hash_child3 = dirs_data3["child_dir"]["recursive_hash"]

    # Root hash must change because child changed
    assert hash_child3 != hash_child1
    assert hash_root3 != hash_root1

    # Revert the change to see if it produces the same original hash
    file_b.write_bytes(b"B_CONTENT")

    # We must reset mtime to the original, because mtime is part of the hash
    import os
    os.utime(file_b, (file_b_stat.st_atime, file_b_stat.st_mtime))

    # Scan 4 -> Revert
    dirs_file4 = tmp_path / "dirs4.jsonl"
    scanner4 = AtlasScanner(root=root_dir, snapshot_id="snap4")
    scanner4.scan(dirs_inventory_file=dirs_file4)

    dirs_data4 = {}
    with dirs_file4.open("r", encoding="utf-8") as f:
        for line in f:
            item = json.loads(line)
            dirs_data4[item["rel_path"]] = item

    assert dirs_data4["."]["recursive_hash"] == hash_root1

    # -----------------------------------------------------
    # Test "silent content change"
    # (same size, same mtime, but different content -> quick_hash catches it)
    # -----------------------------------------------------

    # Overwrite with DIFFERENT content of the EXACT SAME length
    file_b.write_bytes(b"B_CONTENX")

    # Reset atime/mtime to the original ones
    os.utime(file_b, (file_b_stat.st_atime, file_b_stat.st_mtime))

    # Scan 5 -> Silent change
    dirs_file5 = tmp_path / "dirs5.jsonl"
    scanner5 = AtlasScanner(root=root_dir, snapshot_id="snap5")
    scanner5.scan(dirs_inventory_file=dirs_file5)

    dirs_data5 = {}
    with dirs_file5.open("r", encoding="utf-8") as f:
        for line in f:
            item = json.loads(line)
            dirs_data5[item["rel_path"]] = item

    hash_root5 = dirs_data5["."]["recursive_hash"]
    hash_child5 = dirs_data5["child_dir"]["recursive_hash"]

    # The hash should be DIFFERENT from the original (hash_root1)
    # Because quick_hash captures the altered byte "X".
    assert hash_child5 != hash_child1
    assert hash_root5 != hash_root1

def test_incremental_scan_huge_file_behavior(tmp_path: Path):
    root_dir = tmp_path / "test_root_huge"
    root_dir.mkdir()

    # Create a small file
    small_file = root_dir / "small.txt"
    small_file.write_text("Hello Small!")

    # Create a file that is "huge" by our test standard (e.g. > 100 bytes)
    huge_file = root_dir / "huge.txt"
    huge_file.write_bytes(b"0" * 150)

    inventory_file1 = tmp_path / "inventory_huge1.jsonl"

    # Scan 1: Set max_file_size to 100 bytes
    scanner1 = AtlasScanner(
        root=root_dir,
        snapshot_id="snap1",
        enable_content_stats=True,
        max_file_size=100
    )
    scanner1.scan(inventory_file=inventory_file1)

    inv1_data = {}
    with inventory_file1.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip(): continue
            item = json.loads(line)
            inv1_data[item["rel_path"]] = item

    # Both files must be in the inventory
    assert "small.txt" in inv1_data
    assert "huge.txt" in inv1_data

    # Small file should have content fields and quick_hash
    assert "quick_hash" in inv1_data["small.txt"]
    assert "is_text" in inv1_data["small.txt"]

    # Huge file should NOT have content fields or quick_hash
    assert "quick_hash" not in inv1_data["huge.txt"]
    assert "is_text" not in inv1_data["huge.txt"]
    assert "mime_type" not in inv1_data["huge.txt"]

    # Scan 2: Modify the small file to become huge.
    small_file.write_bytes(b"1" * 150)
    # Ensure mtime updates for incremental check
    old_mtime = small_file.stat().st_mtime
    os.utime(small_file, (old_mtime + 10.0, old_mtime + 10.0))

    inventory_file2 = tmp_path / "inventory_huge2.jsonl"
    scanner2 = AtlasScanner(
        root=root_dir,
        snapshot_id="snap2",
        enable_content_stats=True,
        max_file_size=100,
        incremental_inventory=inventory_file1
    )
    scanner2.scan(inventory_file=inventory_file2)

    inv2_data = {}
    with inventory_file2.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip(): continue
            item = json.loads(line)
            inv2_data[item["rel_path"]] = item

    # The formerly small file is now huge. It should not inherit the old quick_hash.
    assert "quick_hash" not in inv2_data["small.txt"], "quick_hash was improperly reused for a file that became huge"
    assert "is_text" not in inv2_data["small.txt"], "is_text was improperly reused for a file that became huge"

def test_incremental_scan_huge_file_config_change_reuse(tmp_path: Path):
    root_dir = tmp_path / "test_root_huge_config"
    root_dir.mkdir()

    # Create a file that is small initially
    test_file = root_dir / "test.txt"
    test_file.write_bytes(b"0" * 50)

    inventory_file1 = tmp_path / "inventory_cfg1.jsonl"

    # Scan 1: max_file_size is large enough (100)
    scanner1 = AtlasScanner(
        root=root_dir,
        snapshot_id="snap1",
        enable_content_stats=True,
        max_file_size=100
    )
    scanner1.scan(inventory_file=inventory_file1)

    inv1_data = {}
    with inventory_file1.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip(): continue
            item = json.loads(line)
            inv1_data[item["rel_path"]] = item

    # The file should have quick_hash
    assert "quick_hash" in inv1_data["test.txt"]

    # Scan 2: File is completely UNCHANGED (same size, same mtime).
    # But configuration changes so that max_file_size = 10, meaning the 50-byte file is now HUGE.
    inventory_file2 = tmp_path / "inventory_cfg2.jsonl"
    scanner2 = AtlasScanner(
        root=root_dir,
        snapshot_id="snap2",
        enable_content_stats=True,
        max_file_size=10,
        incremental_inventory=inventory_file1
    )
    scanner2.scan(inventory_file=inventory_file2)

    inv2_data = {}
    with inventory_file2.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip(): continue
            item = json.loads(line)
            inv2_data[item["rel_path"]] = item

    # The file is now huge. It should not have quick_hash inherited from the previous scan!
    assert "quick_hash" not in inv2_data["test.txt"]
