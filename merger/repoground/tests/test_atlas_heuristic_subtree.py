import json
from pathlib import Path
from merger.repoground.adapters.atlas import AtlasScanner

def test_fingerprint_deterministic_and_present(tmp_path: Path):
    """
    Test A - Fingerprint vorhanden und deterministisch
    """
    # Create test tree
    (tmp_path / "foo").mkdir()
    (tmp_path / "foo" / "b.txt").write_text("b")
    (tmp_path / "foo" / "a.txt").write_text("a")
    (tmp_path / "foo" / "subdir").mkdir()

    # Scan 1
    dirs_file1 = tmp_path / "dirs1.jsonl"
    scanner1 = AtlasScanner(tmp_path, snapshot_id="snap1")
    scanner1.scan(dirs_inventory_file=dirs_file1)

    with open(dirs_file1, "r") as f:
        lines1 = [json.loads(line) for line in f]
    foo1 = next(item for item in lines1 if item["rel_path"] == "foo")

    assert "direct_children_fingerprint" in foo1
    assert foo1["n_files"] == 2
    assert foo1["n_dirs"] == 1

    # Scan 2: same structure, but recreate it to ensure order independence
    (tmp_path / "foo2").mkdir()
    (tmp_path / "foo2" / "subdir").mkdir()
    (tmp_path / "foo2" / "a.txt").write_text("a")
    (tmp_path / "foo2" / "b.txt").write_text("b")

    dirs_file2 = tmp_path / "dirs2.jsonl"
    scanner2 = AtlasScanner(tmp_path, snapshot_id="snap2")
    scanner2.scan(dirs_inventory_file=dirs_file2)

    with open(dirs_file2, "r") as f:
        lines2 = [json.loads(line) for line in f]
    foo2 = next(item for item in lines2 if item["rel_path"] == "foo2")

    # Since they have identical children names and types, fingerprint must match
    assert foo1["direct_children_fingerprint"] == foo2["direct_children_fingerprint"]


def test_heuristic_subtree_matches_unchanged(tmp_path: Path):
    """
    Test B - heuristic_subtree_matches erhöht sich nur für unveränderte Verzeichnisse.
    """
    (tmp_path / "bar").mkdir()
    (tmp_path / "bar" / "1.txt").write_text("1")

    # Scan 1
    dirs_file1 = tmp_path / "dirs1.jsonl"
    scanner1 = AtlasScanner(tmp_path, snapshot_id="snap1")
    scanner1.scan(dirs_inventory_file=dirs_file1)

    # Scan 2 with incremental_dirs_inventory
    scanner2 = AtlasScanner(
        tmp_path,
        snapshot_id="snap2",
        incremental_dirs_inventory=dirs_file1,
        previous_scan_config_hash="hash1",
        current_scan_config_hash="hash1"
    )
    res2 = scanner2.scan()

    # The root "." and "bar" are both unchanged.
    # Total dirs = 2. So matches = 2.
    assert res2["stats"]["incremental"]["heuristic_subtree_matches"] == 2


def test_heuristic_subtree_change_in_child_set(tmp_path: Path):
    """
    Test C - Änderung im Child-Set -> heuristic_subtree_matches darf für dieses Verzeichnis nicht erhöhen.
    """
    (tmp_path / "baz").mkdir()
    f1 = tmp_path / "baz" / "1.txt"
    f1.write_text("1")

    # Scan 1
    dirs_file1 = tmp_path / "dirs1.jsonl"
    scanner1 = AtlasScanner(tmp_path, snapshot_id="snap1")
    scanner1.scan(dirs_inventory_file=dirs_file1)

    # Change the child set
    (tmp_path / "baz" / "2.txt").write_text("2")

    # Scan 2
    scanner2 = AtlasScanner(
        tmp_path,
        snapshot_id="snap2",
        incremental_dirs_inventory=dirs_file1,
        previous_scan_config_hash="hash1",
        current_scan_config_hash="hash1"
    )
    res2 = scanner2.scan()

    # "." directory has same direct children ("baz" dir), but its mtime might have changed?
    # Actually POSIX directory mtime changes when children are added/removed.
    # So both "." and "baz" might have changed mtime, but definitely "baz" has changed fingerprint and count.
    # Let's ensure matches is 1 (for ".").
    assert res2["stats"]["incremental"]["heuristic_subtree_matches"] == 1


def test_heuristic_subtree_config_changed(tmp_path: Path):
    """
    Test D - config_changed -> heuristic_subtree_matches muss 0 bleiben.
    """
    (tmp_path / "qux").mkdir()
    (tmp_path / "qux" / "1.txt").write_text("1")

    # Scan 1
    dirs_file1 = tmp_path / "dirs1.jsonl"
    scanner1 = AtlasScanner(tmp_path, snapshot_id="snap1")
    scanner1.scan(dirs_inventory_file=dirs_file1)

    # Scan 2 with different config hashes
    scanner2 = AtlasScanner(
        tmp_path,
        snapshot_id="snap2",
        incremental_dirs_inventory=dirs_file1,
        previous_scan_config_hash="hash1",
        current_scan_config_hash="hash2"  # changed!
    )
    res2 = scanner2.scan()

    # Must be 0 because config changed
    assert res2["stats"]["incremental"]["heuristic_subtree_matches"] == 0

def test_heuristic_subtree_delimiter_collision(tmp_path: Path):
    """
    Test E - Beweist, dass das Fingerprint-Encoding nicht durch Trennzeichen in Dateinamen
    (wie '|') verwirrt wird (delimiter collision).
    """
    import platform
    if platform.system() == "Windows":
        # Windows doesn't allow '|' in filenames easily
        return

    # Scenario 1: two files: "a" and "b|c"
    dir1 = tmp_path / "dir1"
    dir1.mkdir()
    (dir1 / "a").write_text("a")
    (dir1 / "b|c").write_text("b|c")

    # Scenario 2: two files: "a|b" and "c"
    dir2 = tmp_path / "dir2"
    dir2.mkdir()
    (dir2 / "a|b").write_text("a|b")
    (dir2 / "c").write_text("c")

    # If the fingerprint used simple '|' joining, both might yield "F:a|F:b|c" vs "F:a|b|F:c"
    # which when joined with '|' becomes "F:a|F:b|c" and "F:a|b|F:c" (actually different strings).
    # Wait, a better collision for "|"-joined is:
    # "a" and "b|F:c" -> "F:a|F:b|F:c"
    # "a|F:b" and "c" -> "F:a|F:b|F:c"
    # Let's test EXACTLY this collision!
    dir3 = tmp_path / "dir3"
    dir3.mkdir()
    (dir3 / "a").write_text("1")
    (dir3 / "b|F:c").write_text("2")

    dir4 = tmp_path / "dir4"
    dir4.mkdir()
    (dir4 / "a|F:b").write_text("1")
    (dir4 / "c").write_text("2")

    dirs_file1 = tmp_path / "dirs1.jsonl"
    scanner1 = AtlasScanner(tmp_path, snapshot_id="snap1")
    scanner1.scan(dirs_inventory_file=dirs_file1)

    with open(dirs_file1, "r") as f:
        lines = [json.loads(line) for line in f]

    fp3 = next(item["direct_children_fingerprint"] for item in lines if item["rel_path"] == "dir3")
    fp4 = next(item["direct_children_fingerprint"] for item in lines if item["rel_path"] == "dir4")

    # They MUST NOT match, because they are structurally different sets of files.
    # The JSON serialization prevents the injection attack.
    assert fp3 != fp4
