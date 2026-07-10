import json
from merger.lenskit.adapters import atlas as atlas_module

AtlasScanner = atlas_module.AtlasScanner

def test_atlas_inventory_includes_all_titles(tmp_path):
    # Setup: Create folder structure
    (tmp_path / "subdir").mkdir()
    (tmp_path / "subdir" / "file1.txt").write_text("content", encoding="utf-8")
    # Use a binary file with null byte to ensure detection works
    (tmp_path / "subdir" / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00")
    (tmp_path / "root.md").write_text("# Root", encoding="utf-8")

    # .git should be excluded by default
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("x", encoding="utf-8")

    inventory_file = tmp_path / "atlas.inventory.jsonl"

    scanner = AtlasScanner(tmp_path, snapshot_id="dummy_snap", inventory_strict=False, enable_content_stats=True)
    scanner.scan(inventory_file=inventory_file)

    assert inventory_file.exists()

    lines = inventory_file.read_text(encoding="utf-8").strip().splitlines()
    items = [json.loads(line) for line in lines]

    paths = {item["rel_path"] for item in items}

    # Check inclusions
    assert "subdir/file1.txt" in paths
    assert "subdir/image.png" in paths
    assert "root.md" in paths

    # Check exclusions
    assert ".git/config" not in paths

    # Check fields
    file1 = next(i for i in items if i["rel_path"] == "subdir/file1.txt")
    assert file1["name"] == "file1.txt"
    assert file1["ext"] == ".txt"
    assert file1["is_text"] is True
    assert "size_bytes" in file1
    assert "mtime" in file1

    img = next(i for i in items if i["rel_path"] == "subdir/image.png")
    assert img["is_text"] is False

def test_atlas_inventory_strict_mode(tmp_path):
    # Test strict mode (minimal excludes)
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "pkg.json").write_text("{}", encoding="utf-8")

    inventory_file = tmp_path / "atlas.inventory_strict.jsonl"

    # With inventory_strict=True, node_modules should be included
    # (Default strict excludes are only .git and .venv)
    scanner = AtlasScanner(tmp_path, snapshot_id="dummy_snap", inventory_strict=True)
    scanner.scan(inventory_file=inventory_file)

    lines = inventory_file.read_text(encoding="utf-8").strip().splitlines()
    items = [json.loads(line) for line in lines]
    paths = {item["rel_path"] for item in items}

    assert "node_modules/pkg.json" in paths

def test_atlas_truncation(tmp_path):
    # Test truncation stats
    for i in range(10):
        (tmp_path / f"file{i}.txt").write_text("x")

    scanner = AtlasScanner(tmp_path, max_entries=5)
    result = scanner.scan()

    assert result["stats"]["truncated"]["hit"] is True
    assert result["stats"]["truncated"]["reason"] == "max_entries"
    # Adjusted assertion to match new behavior:
    # "files_seen" is capped at max_entries when truncation occurs.
    assert result["stats"]["truncated"]["files_seen"] == 5

def test_atlas_dirs_inventory(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    (tmp_path / "a/sub").mkdir()

    dirs_file = tmp_path / "dirs.jsonl"
    scanner = AtlasScanner(tmp_path)
    scanner.scan(dirs_inventory_file=dirs_file)

    assert dirs_file.exists()
    lines = dirs_file.read_text(encoding="utf-8").strip().splitlines()
    items = [json.loads(line) for line in lines]
    paths = {item["rel_path"] for item in items}

    assert "a" in paths
    assert "b" in paths
    assert "a/sub" in paths

def test_exclude_pattern_robustness(tmp_path):
    # Test that excluding "myexclude" correctly excludes "myexclude" folder AND "myexclude/file"
    # even if pattern was just "**/myexclude"

    (tmp_path / "keep").mkdir()
    (tmp_path / "keep" / "ok.txt").write_text("ok")

    (tmp_path / "myexclude").mkdir()
    (tmp_path / "myexclude" / "bad.txt").write_text("bad")

    # Explicit custom exclude
    scanner = AtlasScanner(tmp_path, snapshot_id="dummy_snap", exclude_globs=["**/myexclude"])

    inventory_file = tmp_path / "inv.jsonl"
    scanner.scan(inventory_file=inventory_file)

    lines = inventory_file.read_text(encoding="utf-8").strip().splitlines()
    items = [json.loads(line) for line in lines]
    paths = {item["rel_path"] for item in items}

    assert "keep/ok.txt" in paths
    assert "myexclude/bad.txt" not in paths

def test_atlas_inventory_fails_without_snapshot_id(tmp_path):
    import pytest
    (tmp_path / "file1.txt").write_text("content", encoding="utf-8")

    inventory_file = tmp_path / "atlas.inventory.jsonl"

    # Missing snapshot_id
    scanner = AtlasScanner(tmp_path)

    with pytest.raises(ValueError, match="Inventory emission requires a snapshot_id"):
        scanner.scan(inventory_file=inventory_file)

def test_atlas_dirs_inventory_excludes_files(tmp_path):
    (tmp_path / "mixed").mkdir()
    (tmp_path / "mixed" / "ok.txt").write_text("ok")
    (tmp_path / "mixed" / "ignore.me").write_text("ignore")

    dirs_file = tmp_path / "dirs.jsonl"
    scanner = AtlasScanner(tmp_path, exclude_globs=["**/ignore.me"])
    scanner.scan(dirs_inventory_file=dirs_file)

    lines = dirs_file.read_text(encoding="utf-8").strip().splitlines()
    items = [json.loads(line) for line in lines]

    mixed_dir = next(i for i in items if i["rel_path"] == "mixed")
    assert mixed_dir["n_files"] == 1


def test_atlas_reports_apparent_allocated_and_sparse_bytes(tmp_path, monkeypatch):
    root = tmp_path / "source"
    root.mkdir()
    target = root / "sparse.bin"
    with target.open("wb") as handle:
        handle.seek(1024 * 1024 - 1)
        handle.write(b"x")

    monkeypatch.setattr(atlas_module, "allocated_bytes_from_stat", lambda _stat: 4096)
    inventory_file = tmp_path / "sparse.inventory.jsonl"
    result = AtlasScanner(root, snapshot_id="snap_sparse").scan(
        inventory_file=inventory_file
    )

    item = json.loads(inventory_file.read_text(encoding="utf-8").splitlines()[0])
    assert item["size_bytes"] == 1024 * 1024
    assert item["allocated_size_bytes"] == 4096
    assert item["is_sparse"] is True
    assert result["stats"]["total_bytes"] == 1024 * 1024
    assert result["stats"]["total_allocated_bytes"] == 4096
    assert result["stats"]["sparse_files_count"] == 1
    assert result["stats"]["sparse_apparent_bytes"] == 1024 * 1024
    assert result["stats"]["sparse_allocated_bytes"] == 4096


def test_allocated_bytes_falls_back_to_apparent_size_without_st_blocks():
    from types import SimpleNamespace

    assert atlas_module.allocated_bytes_from_stat(SimpleNamespace(st_size=1234)) == 1234


def test_atlas_directory_rollups_include_allocated_bytes(tmp_path, monkeypatch):
    root = tmp_path / "source"
    nested = root / "nested"
    nested.mkdir(parents=True)
    (root / "top.txt").write_bytes(b"a" * 10)
    (nested / "child.txt").write_bytes(b"b" * 20)

    monkeypatch.setattr(atlas_module, "allocated_bytes_from_stat", lambda stat: stat.st_size + 100)
    dirs_file = tmp_path / "dirs.jsonl"
    result = AtlasScanner(root, snapshot_id="snap_rollup").scan(
        dirs_inventory_file=dirs_file
    )

    rows = {
        row["rel_path"]: row
        for row in map(json.loads, dirs_file.read_text(encoding="utf-8").splitlines())
    }
    assert rows["nested"]["subtree_total_bytes"] == 20
    assert rows["nested"]["subtree_allocated_bytes"] == 120
    assert rows["."]["subtree_total_bytes"] == 30
    assert rows["."]["subtree_allocated_bytes"] == 230
    assert result["stats"]["top_dirs"][0] == {
        "path": ".",
        "bytes": 30,
        "allocated_bytes": 230,
    }


def test_generated_inventory_row_validates_against_contract(tmp_path):
    from jsonschema import Draft7Validator
    from pathlib import Path

    root = tmp_path / "source"
    root.mkdir()
    (root / "file.txt").write_text("content", encoding="utf-8")
    inventory_file = tmp_path / "inventory.jsonl"

    AtlasScanner(root, snapshot_id="snap_contract").scan(inventory_file=inventory_file)
    row = json.loads(inventory_file.read_text(encoding="utf-8").splitlines()[0])
    schema_path = Path("merger/lenskit/contracts/atlas-inventory.v1.schema.json")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    Draft7Validator(schema).validate(row)
    assert row["allocated_size_bytes"] >= 0
    assert isinstance(row["is_sparse"], bool)
