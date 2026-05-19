import json
import pytest
from pathlib import Path

from merger.lenskit.cli.cmd_atlas import _run_analyze_orphans
from merger.lenskit.atlas.registry import AtlasRegistry

@pytest.fixture
def orphan_snapshot_setup(tmp_path, monkeypatch):
    """Sets up a mock registry and inventory with various orphan/dead file scenarios."""
    registry_path = tmp_path / "atlas" / "registry" / "atlas_registry.sqlite"
    atlas_base = tmp_path / "atlas"

    # Mock resolve_atlas_base_dir to return our tmp_path base
    def mock_resolve_base(reg_path=None):
        return atlas_base

    import merger.lenskit.atlas.paths
    monkeypatch.setattr(merger.lenskit.atlas.paths, "resolve_atlas_base_dir", mock_resolve_base)

    with AtlasRegistry(registry_path) as registry:
        live_root = tmp_path / "live_root"
        live_root.mkdir()

        registry.register_machine("test-machine", "test-host")
        registry.register_root("test-root", "test-machine", "abs_path", str(live_root))

        snap_id = "snap_test_123"
        registry.create_snapshot(snap_id, "test-machine", "test-root", "config123", "complete")

        # Create inventory file
        inv_path = atlas_base / "machines" / "test-machine" / "roots" / "test-root" / "snapshots" / snap_id / "inventory.jsonl"
        inv_path.parent.mkdir(parents=True, exist_ok=True)

        # File A: Exists in both snapshot and live
        # File B: Exists in snapshot, missing in live (dead)
        # File C: Missing in snapshot, exists in live (orphan)

        file_a = live_root / "file_a.txt"
        file_c = live_root / "file_c.txt"
        file_a.write_text("hello world")
        file_c.write_text("new file")

        entries = [
            {"rel_path": "file_a.txt", "size_bytes": 11},
            {"rel_path": "file_b.txt", "size_bytes": 20},  # dead file
        ]

        with inv_path.open("w", encoding="utf-8") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")

        # Register artifact
        registry.update_snapshot_artifacts(
            snap_id,
            {"inventory": inv_path.relative_to(atlas_base).as_posix()}
        )

    return registry_path, snap_id


def test_analyze_orphans_differentiates_groups(orphan_snapshot_setup, capsys, monkeypatch):
    registry_path, snap_id = orphan_snapshot_setup


    original_resolve = Path.resolve
    def mock_resolve(self, *args, **kwargs):
        if str(self) == "atlas/registry/atlas_registry.sqlite":
            return registry_path
        return original_resolve(self, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", mock_resolve)

    exit_code = _run_analyze_orphans(snap_id)
    assert exit_code == 0

    captured = capsys.readouterr()
    report = json.loads(captured.out)

    assert report["snapshot_id"] == snap_id

    assert report["orphan_count"] == 1
    assert report["dead_file_count"] == 1
    assert report["orphans"] == ["file_c.txt"]
    assert report["dead_files"] == ["file_b.txt"]

    # Check persistence
    atlas_base = registry_path.parent.parent
    orphans_path = atlas_base / "machines" / "test-machine" / "roots" / "test-root" / "snapshots" / snap_id / "orphans.json"

    assert orphans_path.exists()

    with orphans_path.open() as f:
        data = json.load(f)

    assert "orphans" in data
    assert "dead_files" in data

    with AtlasRegistry(registry_path) as registry:
        snap = registry.get_snapshot(snap_id)

    assert snap["orphans_ref"] is not None
    assert snap["orphans_ref"].endswith("orphans.json")
