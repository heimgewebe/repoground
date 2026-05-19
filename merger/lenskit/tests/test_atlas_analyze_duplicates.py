import json
import pytest
from pathlib import Path

from merger.lenskit.cli.cmd_atlas import _run_analyze_duplicates
from merger.lenskit.atlas.registry import AtlasRegistry

@pytest.fixture
def duplicate_snapshot_setup(tmp_path, monkeypatch):
    """Sets up a mock registry and inventory with various duplicate scenarios."""
    registry_path = tmp_path / "atlas" / "registry" / "atlas_registry.sqlite"
    atlas_base = tmp_path / "atlas"

    # Mock resolve_atlas_base_dir to return our tmp_path base
    def mock_resolve_base(reg_path=None):
        return atlas_base

    import merger.lenskit.atlas.paths
    monkeypatch.setattr(merger.lenskit.atlas.paths, "resolve_atlas_base_dir", mock_resolve_base)

    with AtlasRegistry(registry_path) as registry:
        registry.register_machine("test-machine", "test-host")
        registry.register_root("test-root", "test-machine", "abs_path", str(tmp_path))

        snap_id = "snap_test_123"
        registry.create_snapshot(snap_id, "test-machine", "test-root", "config123", "complete")

        # Create inventory file
        inv_path = atlas_base / "machines" / "test-machine" / "roots" / "test-root" / "snapshots" / snap_id / "inventory.jsonl"
        inv_path.parent.mkdir(parents=True, exist_ok=True)

        # Create fake files so live hashing works
        file_a = tmp_path / "file_a.txt"
        file_b = tmp_path / "file_b.txt"
        file_a.write_text("hello world")
        file_b.write_text("hello world")

        file_c = tmp_path / "file_c.txt"
        file_c.write_text("different")

        # A file completely outside of the tmp_path root to test path escape protection
        outside_file = tmp_path.parent / "outside_escape.txt"
        outside_file.write_text("hello world")

        entries = [
            # Group 1: Confirmed via existing checksum
            {"rel_path": "path/1.txt", "size_bytes": 100, "checksum": "sha256:abc"},
            {"rel_path": "path/2.txt", "size_bytes": 100, "checksum": "sha256:abc"},

            # Group 2: Heuristic via quick_hash
            {"rel_path": "path/3.txt", "size_bytes": 200, "quick_hash": "quick123"},
            {"rel_path": "path/4.txt", "size_bytes": 200, "quick_hash": "quick123"},

            # Group 3: Live hashed (size 11, "hello world")
            {"rel_path": "file_a.txt", "size_bytes": 11},
            {"rel_path": "file_b.txt", "size_bytes": 11},
            # Malicious traversal attempt pointing outside the root
            {"rel_path": "../outside_escape.txt", "size_bytes": 11},

            # Non-duplicate
            {"rel_path": "file_c.txt", "size_bytes": 9},
        ]

        with inv_path.open("w", encoding="utf-8") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")

        # Register artifact
        registry.update_snapshot_artifacts(snap_id, {"inventory": str(inv_path.relative_to(atlas_base))})

    return registry_path, snap_id


def test_analyze_duplicates_differentiates_groups(duplicate_snapshot_setup, capsys, monkeypatch):
    registry_path, snap_id = duplicate_snapshot_setup

    # We need to run the inner function and capture stdout

    # Monkeypatch the module-level registry path resolution instead of the global Path class
    # cmd_atlas relies on Path("atlas/registry/atlas_registry.sqlite").resolve()
    # To intercept this without replacing `Path` entirely, we can mock `Path.resolve` just for this string

    original_resolve = Path.resolve
    def mock_resolve(self, *args, **kwargs):
        if str(self) == "atlas/registry/atlas_registry.sqlite":
            return registry_path
        return original_resolve(self, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", mock_resolve)

    exit_code = _run_analyze_duplicates(snap_id)
    assert exit_code == 0

    captured = capsys.readouterr()
    report = json.loads(captured.out)

    assert report["snapshot_id"] == snap_id
    assert report["duplicate_groups_count"] == 3

    duplicates = report["duplicates"]

    # Find specific groups
    group_100 = next(g for g in duplicates if g["size_bytes"] == 100)
    assert group_100["checksum_verified"] is True
    assert group_100["checksum"] == "sha256:abc"
    assert "quick_hash" not in group_100
    assert len(group_100["members"]) == 2

    group_200 = next(g for g in duplicates if g["size_bytes"] == 200)
    assert group_200["checksum_verified"] is False
    assert group_200["quick_hash"] == "quick123"
    assert "checksum" not in group_200
    assert len(group_200["members"]) == 2

    group_11 = next(g for g in duplicates if g["size_bytes"] == 11)
    assert group_11["checksum_verified"] is True
    assert group_11["checksum"].startswith("sha256:")
    assert "quick_hash" not in group_11
    assert len(group_11["members"]) == 2

    # Check persistence
    atlas_base = registry_path.parent.parent
    duplicates_path = atlas_base / "machines" / "test-machine" / "roots" / "test-root" / "snapshots" / snap_id / "duplicates.json"

    assert duplicates_path.exists()

    with duplicates_path.open() as f:
        data = json.load(f)

    assert "duplicates" in data

    with AtlasRegistry(registry_path) as registry:
        snap = registry.get_snapshot(snap_id)

    assert snap["duplicates_ref"] is not None
    assert snap["duplicates_ref"].endswith("duplicates.json")
