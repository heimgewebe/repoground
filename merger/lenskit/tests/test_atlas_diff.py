import json
import os
import tempfile
import pytest
from pathlib import Path
from typing import Optional, Dict, Any
from merger.lenskit.atlas.registry import AtlasRegistry
from merger.lenskit.atlas.diff import (
    compute_snapshot_delta,
    _compare_file_sets,
    _load_inventory_index,
    compute_snapshot_comparison
)
from merger.lenskit.atlas.paths import resolve_artifact_ref

@pytest.fixture
def temp_workspace(tmp_path):
    # Setup mock atlas structure
    registry_db = tmp_path / "atlas" / "registry" / "atlas_registry.sqlite"
    return tmp_path, registry_db

@pytest.fixture
def populated_registry(temp_workspace):
    tmp_path, registry_db = temp_workspace

    with AtlasRegistry(registry_db) as reg:
        reg.register_machine("m1", "host")
        reg.register_root("r1", "m1", "abs_path", "/var/www")

        # In Atlas, artifacts are stored relative to atlas_base (which is two levels up from registry.db_path)
        atlas_base = registry_db.parent.parent
        atlas_base.mkdir(parents=True, exist_ok=True)

        # Write mock inventory 1
        inv1_path = atlas_base / "artifacts" / "inv1.jsonl"
        inv1_path.parent.mkdir(parents=True, exist_ok=True)

        with open(inv1_path, "w", encoding="utf-8") as f:
            f.write(json.dumps({"snapshot_id": "s1", "rel_path": "a.txt", "size_bytes": 100, "mtime": "2023-01-01T00:00:00Z", "is_symlink": False}) + "\n")
            f.write(json.dumps({"snapshot_id": "s1", "rel_path": "b.txt", "size_bytes": 200, "mtime": "2023-01-01T00:00:00Z", "is_symlink": False}) + "\n")

        reg.create_snapshot("s1", "m1", "r1", "hash1", "complete")

        # We explicitly store the relative path to prove Canonical Resolution against registry_db works
        # regardless of current working directory.
        inv1_rel = inv1_path.relative_to(atlas_base).as_posix()
        reg.update_snapshot_artifacts("s1", {"inventory": inv1_rel})

        # Write mock inventory 2
        inv2_path = atlas_base / "artifacts" / "inv2.jsonl"
        with open(inv2_path, "w", encoding="utf-8") as f:
            f.write(json.dumps({"snapshot_id": "s2", "rel_path": "a.txt", "size_bytes": 100, "mtime": "2023-01-01T00:00:00Z", "is_symlink": False}) + "\n")
            f.write(json.dumps({"snapshot_id": "s2", "rel_path": "b.txt", "size_bytes": 250, "mtime": "2023-01-02T00:00:00Z", "is_symlink": False}) + "\n")
            f.write(json.dumps({"snapshot_id": "s2", "rel_path": "c.txt", "size_bytes": 300, "mtime": "2023-01-02T00:00:00Z", "is_symlink": False}) + "\n")

        # Re-write s1 with d.txt to test removals
        with open(inv1_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"snapshot_id": "s1", "rel_path": "d.txt", "size_bytes": 400, "mtime": "2023-01-01T00:00:00Z", "is_symlink": False}) + "\n")

        reg.create_snapshot("s2", "m1", "r1", "hash2", "complete")
        inv2_rel = inv2_path.relative_to(atlas_base).as_posix()
        reg.update_snapshot_artifacts("s2", {"inventory": inv2_rel})

        yield reg

def test_compute_snapshot_delta(populated_registry):
    # Prove CWD independence by executing from a random temporary directory
    old_cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as td:
        os.chdir(td)
        try:
            delta = compute_snapshot_delta(populated_registry, "s1", "s2")

            assert len(delta["new_files"]) == 1
            assert delta["new_files"][0] == "c.txt"

            assert len(delta["removed_files"]) == 1
            assert delta["removed_files"][0] == "d.txt"

            assert len(delta["changed_files"]) == 1
            assert delta["changed_files"][0] == "b.txt"

            # Check delta in registry
            reg_deltas = populated_registry.list_deltas()
            assert len(reg_deltas) == 1
            assert reg_deltas[0]["delta_id"] == delta["delta_id"]
        finally:
            os.chdir(old_cwd)


def test_compute_delta_errors(populated_registry):
    with pytest.raises(ValueError, match="Snapshot not found"):
        compute_snapshot_delta(populated_registry, "s1", "nonexistent")

    populated_registry.create_snapshot("s_partial", "m1", "r1", "hashx", "running")
    with pytest.raises(ValueError, match="status='complete'"):
        compute_snapshot_delta(populated_registry, "s1", "s_partial")

    populated_registry.register_root("r2", "m1", "abs_path", "/var/lib")
    populated_registry.create_snapshot("s3", "m1", "r2", "hash3", "complete")

    with pytest.raises(ValueError, match="Snapshots must belong to the same machine and root"):
        compute_snapshot_delta(populated_registry, "s1", "s3")



def test_cross_machine_delta(temp_workspace, populated_registry):
    _, registry_db = temp_workspace

    populated_registry.register_machine("m2", "otherhost")
    populated_registry.register_root("r2", "m2", "abs_path", "/var/backup")

    atlas_base = registry_db.parent.parent
    inv3_path = atlas_base / "artifacts" / "inv3.jsonl"
    inv3_path.parent.mkdir(parents=True, exist_ok=True)
    with open(inv3_path, "w", encoding="utf-8") as f:
        f.write(json.dumps({"snapshot_id": "s3", "rel_path": "a.txt", "size_bytes": 100, "mtime": "2023-01-01T00:00:00Z", "is_symlink": False}) + "\n")
        f.write(json.dumps({"snapshot_id": "s3", "rel_path": "new.txt", "size_bytes": 50, "mtime": "2023-01-01T00:00:00Z", "is_symlink": False}) + "\n")
        # Inject problematic lines to verify robustness of parser
        f.write("\n")
        f.write("invalid json\n")
        f.write(json.dumps({"size_bytes": 999}) + "\n")
        f.write(json.dumps({"rel_path": "", "size_bytes": 1}) + "\n")
        f.write(json.dumps({"rel_path": None, "size_bytes": 1}) + "\n")
        f.write(json.dumps({"rel_path": 12345, "size_bytes": 1}) + "\n")
        f.write(json.dumps(123) + "\n")
        f.write(json.dumps([]) + "\n")
        f.write(json.dumps("abc") + "\n")

    populated_registry.create_snapshot("s3", "m2", "r2", "hash3", "complete")

    # Store relative path to test canonical resolution independent of CWD
    inv3_rel = inv3_path.relative_to(atlas_base).as_posix()
    populated_registry.update_snapshot_artifacts("s3", {"inventory": inv3_rel})

    old_cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as td:
        os.chdir(td)
        try:
            delta = compute_snapshot_comparison(populated_registry, "s1", "s3")

            assert delta["mode"] == "cross-root-comparison"
            assert delta["is_cross_root"] is True
            assert delta["from_machine_id"] == "m1"
            assert delta["to_machine_id"] == "m2"
            assert delta["from_root_id"] == "r1"
            assert delta["to_root_id"] == "r2"
            assert delta["summary"]["new_count"] == 1
            assert delta["new_files"][0] == "new.txt"
            assert delta["summary"]["removed_count"] == 2 # b.txt, d.txt
            assert delta["summary"]["changed_count"] == 0 # a.txt is identical
        finally:
            os.chdir(old_cwd)

def test_resolve_snapshot_ref(populated_registry):
    from merger.lenskit.cli.cmd_atlas import _resolve_snapshot_ref

    # Normal ref
    assert _resolve_snapshot_ref("s1", populated_registry) == "s1"

    with populated_registry.conn:
        populated_registry.conn.execute("UPDATE snapshots SET created_at = '2023-01-01T00:00:00Z' WHERE snapshot_id = 's1'")
        populated_registry.conn.execute("UPDATE snapshots SET created_at = '2023-01-02T00:00:00Z' WHERE snapshot_id = 's2'")

    resolved_id = _resolve_snapshot_ref("m1:/var/www", populated_registry)
    assert resolved_id == "s2" # The newer one

    # Test Tie-breaking logic (same created_at)
    with populated_registry.conn:
        populated_registry.conn.execute("UPDATE snapshots SET created_at = '2023-01-02T00:00:00Z' WHERE snapshot_id = 's1'")

    # Both s1 and s2 have exactly '2023-01-02T00:00:00Z'.
    # secondary sort is by snapshot_id descending. 's2' > 's1', so 's2' should win.
    resolved_id_tied = _resolve_snapshot_ref("m1:/var/www", populated_registry)
    assert resolved_id_tied == "s2"

    # Not found paths
    with pytest.raises(ValueError, match="No root found"):
        _resolve_snapshot_ref("m1:/nowhere", populated_registry)

    # Empty complete snapshots check
    populated_registry.register_root("r_empty", "m1", "abs_path", "/var/empty")
    populated_registry.create_snapshot("s_empty", "m1", "r_empty", "h", "running")
    with pytest.raises(ValueError, match="No complete snapshots found"):
        _resolve_snapshot_ref("m1:/var/empty", populated_registry)

    # Trivial path variants
    resolved_slash = _resolve_snapshot_ref("m1:/var/www/", populated_registry)
    assert resolved_slash == "s2"

    resolved_dot = _resolve_snapshot_ref("m1:/var/www/.", populated_registry)
    assert resolved_dot == "s2"

    # Ambiguous paths match error behavior (including cross-validation of trailing slashes/dots)
    populated_registry.register_root("r_ambig", "m1", "abs_path", "/var/www/")
    with pytest.raises(ValueError, match="Ambiguous root reference"):
        _resolve_snapshot_ref("m1:/var/www", populated_registry)

    with pytest.raises(ValueError, match="Ambiguous root reference"):
        _resolve_snapshot_ref("m1:/var/www/", populated_registry)

    with pytest.raises(ValueError, match="Ambiguous root reference"):
        _resolve_snapshot_ref("m1:/var/www/.", populated_registry)

def test_cli_diff_routing(temp_workspace, populated_registry, capsys):
    tmp_path, registry_db = temp_workspace
    import argparse
    from merger.lenskit.cli.cmd_atlas import run_atlas_diff

    old_cwd = os.getcwd()
    os.chdir(tmp_path)

    try:
        # 1. same-root delta
        args = argparse.Namespace(from_snapshot="s1", to_snapshot="s2")
        ret = run_atlas_diff(args)
        assert ret == 0
        captured = capsys.readouterr()
        assert "Mode: same-root-delta" in captured.out
        assert "Warning: This is a cross-root delta" not in captured.out

        # 2. cross-root comparison
        populated_registry.register_machine("m2", "other")
        populated_registry.register_root("r2", "m2", "abs_path", "/var/backup")

        atlas_base = registry_db.parent.parent
        inv3_path = atlas_base / "artifacts" / "inv3.jsonl"
        inv3_path.parent.mkdir(parents=True, exist_ok=True)
        with open(inv3_path, "w", encoding="utf-8") as f:
            f.write(json.dumps({"snapshot_id": "s3", "rel_path": "a.txt", "size_bytes": 100, "mtime": "2023-01-01T00:00:00Z", "is_symlink": False}) + "\n")
            f.write(json.dumps({"size_bytes": 999}) + "\n")

        populated_registry.create_snapshot("s3", "m2", "r2", "hash3", "complete")
        inv3_rel = inv3_path.relative_to(atlas_base).as_posix()
        populated_registry.update_snapshot_artifacts("s3", {"inventory": inv3_rel})

        args = argparse.Namespace(from_snapshot="s1", to_snapshot="s3")
        ret = run_atlas_diff(args)
        assert ret == 0
        captured = capsys.readouterr()
        assert "Mode: cross-root-comparison" in captured.out
        assert "From: m1:/var/www (s1)" in captured.out
        assert "To:   m2:/var/backup (s3)" in captured.out

        # 3. cross-root comparison using machine:path resolution explicitly
        args = argparse.Namespace(from_snapshot="m1:/var/www", to_snapshot="m2:/var/backup")
        ret = run_atlas_diff(args)
        assert ret == 0
        captured = capsys.readouterr()
        assert "Mode: cross-root-comparison" in captured.out
        # Test explicitly asserts that the resolved snapshot IDs are correctly embedded in the output
        assert "From: m1:/var/www (s2)" in captured.out
        assert "To:   m2:/var/backup (s3)" in captured.out

    finally:
        os.chdir(old_cwd)

# --- Unit Tests for _compare_file_sets and _load_inventory_index ---

def test_compare_file_sets_empty():
    from_files = {}
    to_files = {}
    new, removed, changed = _compare_file_sets(from_files, to_files)
    assert new == []
    assert removed == []
    assert changed == []

def test_compare_file_sets_identical():
    files = {
        "file1.txt": {"size_bytes": 100, "mtime": "2023-01-01T00:00:00Z", "is_symlink": False},
        "dir/file2.txt": {"size_bytes": 200, "mtime": "2023-01-01T00:00:00Z", "is_symlink": False}
    }
    new, removed, changed = _compare_file_sets(files, files)
    assert new == []
    assert removed == []
    assert changed == []

def test_compare_file_sets_added_removed():
    from_files = {
        "removed.txt": {"size_bytes": 100, "mtime": "2023-01-01T00:00:00Z", "is_symlink": False},
        "stay.txt": {"size_bytes": 50, "mtime": "2023-01-01T00:00:00Z", "is_symlink": False}
    }
    to_files = {
        "new.txt": {"size_bytes": 150, "mtime": "2023-01-02T00:00:00Z", "is_symlink": False},
        "stay.txt": {"size_bytes": 50, "mtime": "2023-01-01T00:00:00Z", "is_symlink": False}
    }
    new, removed, changed = _compare_file_sets(from_files, to_files)
    assert new == ["new.txt"]
    assert removed == ["removed.txt"]
    assert changed == []

def test_compare_file_sets_changed():
    from_files = {
        "size_change.txt": {"size_bytes": 100, "mtime": "2023-01-01T00:00:00Z", "is_symlink": False},
        "mtime_change.txt": {"size_bytes": 100, "mtime": "2023-01-01T00:00:00Z", "is_symlink": False},
        "symlink_change.txt": {"size_bytes": 100, "mtime": "2023-01-01T00:00:00Z", "is_symlink": False}
    }
    to_files = {
        "size_change.txt": {"size_bytes": 101, "mtime": "2023-01-01T00:00:00Z", "is_symlink": False},
        "mtime_change.txt": {"size_bytes": 100, "mtime": "2023-01-01T00:00:01Z", "is_symlink": False},
        "symlink_change.txt": {"size_bytes": 100, "mtime": "2023-01-01T00:00:00Z", "is_symlink": True}
    }
    new, removed, changed = _compare_file_sets(from_files, to_files)
    assert new == []
    assert removed == []
    # Verify deterministic sorting of changed_files
    assert changed == ["mtime_change.txt", "size_change.txt", "symlink_change.txt"]

def test_compare_file_sets_sorting():
    """Verify that new, removed, and changed lists are all deterministically sorted."""
    from_files = {
        "r2.txt": {}, "r1.txt": {},
        "c2.txt": {"size_bytes": 10}, "c1.txt": {"size_bytes": 10}
    }
    to_files = {
        "n2.txt": {}, "n1.txt": {},
        "c2.txt": {"size_bytes": 20}, "c1.txt": {"size_bytes": 20}
    }
    new, removed, changed = _compare_file_sets(from_files, to_files)
    assert new == ["n1.txt", "n2.txt"]
    assert removed == ["r1.txt", "r2.txt"]
    assert changed == ["c1.txt", "c2.txt"]

def test_compare_file_sets_missing_fields():
    """
    Verify behavior when comparison fields are missing.
    The implementation uses .get(), so missing fields are treated as None.
    """
    from_files = {
        "both_missing.txt": {"mtime": "X"},
        "one_missing.txt": {"size_bytes": 100}
    }
    to_files = {
        "both_missing.txt": {"mtime": "X"},
        "one_missing.txt": {}
    }
    new, removed, changed = _compare_file_sets(from_files, to_files)
    assert "both_missing.txt" not in changed
    assert "one_missing.txt" in changed

def test_load_inventory_index_basic(tmp_path):
    inv_path = tmp_path / "inventory.jsonl"
    data = [
        {"rel_path": "file1.txt", "size_bytes": 10},
        {"rel_path": "file2.txt", "size_bytes": 20}
    ]
    with open(inv_path, "w", encoding="utf-8") as f:
        for item in data:
            f.write(json.dumps(item) + "\n")

    index = _load_inventory_index(inv_path)
    assert len(index) == 2
    assert index["file1.txt"]["size_bytes"] == 10

def test_load_inventory_index_malformed_and_types(tmp_path):
    """Verify handling of malformed JSON and incorrect top-level types."""
    inv_path = tmp_path / "inventory.jsonl"
    with open(inv_path, "w", encoding="utf-8") as f:
        f.write('{"rel_path": "valid.txt"}\n')
        f.write('malformed json\n')
        f.write('[]\n')
        f.write('123\n')
        f.write('{"missing_rel_path": true}\n')
        f.write('{"rel_path": 123}\n')

    index = _load_inventory_index(inv_path)
    assert list(index.keys()) == ["valid.txt"]

def test_load_inventory_index_duplicate_rel_path_last_wins(tmp_path):
    """Verify that for duplicate rel_path entries, the last one in the file wins."""
    inv_path = tmp_path / "inventory.jsonl"
    with open(inv_path, "w", encoding="utf-8") as f:
        f.write('{"rel_path": "dup.txt", "val": 1}\n')
        f.write('{"rel_path": "dup.txt", "val": 2}\n')

    index = _load_inventory_index(inv_path)
    assert len(index) == 1
    assert index["dup.txt"]["val"] == 2

def test_load_inventory_index_whitespace_only_line(tmp_path):
    """Verify that lines containing only whitespace are silently ignored."""
    inv_path = tmp_path / "inventory.jsonl"
    with open(inv_path, "w", encoding="utf-8") as f:
        f.write('{"rel_path": "file1.txt"}\n')
        f.write('   \n')
        f.write('\t\n')
        f.write('{"rel_path": "file2.txt"}\n')

    index = _load_inventory_index(inv_path)
    assert sorted(index.keys()) == ["file1.txt", "file2.txt"]

def test_compute_snapshot_comparison_public_entry_point(tmp_path):
    """
    Lean integration test for compute_snapshot_comparison.
    Ensures component collaboration via the public entry point using a mock registry
    and canonical inventory paths.
    """
    atlas_base = tmp_path / "atlas"
    registry_db = atlas_base / "registry" / "atlas.db"
    registry_db.parent.mkdir(parents=True)

    class MockRegistry:
        def __init__(self, db_path: Path):
            self.db_path = db_path
        def get_snapshot(self, snap_id: str) -> Optional[Dict[str, Any]]:
            if snap_id == "s1":
                return {
                    "machine_id": "m1", "root_id": "r1", "status": "complete",
                    "inventory_ref": "machines/m1/roots/r1/snapshots/s1/inv.jsonl"
                }
            if snap_id == "s2":
                return {
                    "machine_id": "m2", "root_id": "r2", "status": "complete",
                    "inventory_ref": "machines/m2/roots/r2/snapshots/s2/inv.jsonl"
                }
            return None
        def get_root(self, root_id: str) -> Optional[Dict[str, Any]]:
            return {"root_id": root_id, "root_value": f"/path/to/{root_id}"}

    registry = MockRegistry(registry_db)

    inv1_path = resolve_artifact_ref(atlas_base, "machines/m1/roots/r1/snapshots/s1/inv.jsonl")
    inv1_path.parent.mkdir(parents=True)
    with open(inv1_path, "w", encoding="utf-8") as f:
        f.write(json.dumps({"rel_path": "shared.txt", "size_bytes": 10}) + "\n")
        f.write(json.dumps({"rel_path": "removed.txt", "size_bytes": 10}) + "\n")

    inv2_path = resolve_artifact_ref(atlas_base, "machines/m2/roots/r2/snapshots/s2/inv.jsonl")
    inv2_path.parent.mkdir(parents=True)
    with open(inv2_path, "w", encoding="utf-8") as f:
        f.write(json.dumps({"rel_path": "shared.txt", "size_bytes": 20}) + "\n")
        f.write(json.dumps({"rel_path": "new.txt", "size_bytes": 10}) + "\n")

    result = compute_snapshot_comparison(registry, "s1", "s2")

    assert result["mode"] == "cross-root-comparison"
    assert result["summary"]["new_count"] == 1
    assert result["new_files"] == ["new.txt"]
    assert result["removed_files"] == ["removed.txt"]
    assert result["changed_files"] == ["shared.txt"]
