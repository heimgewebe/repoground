import json
import argparse
from pathlib import Path
from merger.repoground.cli.cmd_atlas import run_atlas_analyze
from merger.repoground.atlas.registry import AtlasRegistry

def test_analyze_disk_functional(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    registry_path = tmp_path / "atlas/registry/atlas_registry.sqlite"
    registry_path.parent.mkdir(parents=True)

    root_val = tmp_path / "test_root"
    root_val.mkdir()

    with AtlasRegistry(registry_path) as registry:
        registry.register_machine("mach_1", "mach_1")
        registry.register_root("root_1", "mach_1", "abs_path", root_val.resolve().as_posix())
        registry.create_snapshot("snap_1", "mach_1", "root_1", "12345", "complete")

        # Setup snapshot inventory using expected directory structure
        snapshot_dir = tmp_path / "atlas" / "machines" / "mach_1" / "roots" / "root_1" / "snapshots" / "snap_1"
        snapshot_dir.mkdir(parents=True)
        inv_file = snapshot_dir / "inventory.jsonl"
        dirs_file = snapshot_dir / "dirs.jsonl"

        with inv_file.open("w", encoding="utf-8") as f:
            f.write(json.dumps({"rel_path": "file1.txt", "size_bytes": 100, "mtime": "2023-01-01T12:00:00Z"}) + "\n")
            f.write("\n") # Blank line should be skipped
            f.write("invalid json\n") # Should be skipped gracefully
            f.write(json.dumps({"rel_path": "file2.txt", "size_bytes": 500, "mtime": "2022-01-01T12:00:00Z"}) + "\n")
            f.write(json.dumps({"rel_path": "file3.txt", "size_bytes": "invalid", "mtime": "2024-01-01T12:00:00Z"}) + "\n")

        with dirs_file.open("w", encoding="utf-8") as f:
            f.write(json.dumps({"rel_path": "dir1", "subtree_total_bytes": 600, "subtree_file_count": 2}) + "\n")
            f.write(json.dumps({"rel_path": "dir2", "recursive_bytes": 300, "n_files": 1}) + "\n") # Fallbacks
            f.write(json.dumps({"rel_path": "dir3", "subtree_total_bytes": "null", "subtree_file_count": "none"}) + "\n")

        registry.update_snapshot_artifacts("snap_1", {
            "inventory": inv_file.relative_to(tmp_path / "atlas").as_posix(),
            "dirs": dirs_file.relative_to(tmp_path / "atlas").as_posix()
        })

    args = argparse.Namespace(analyze_command="disk", snapshot_id="snap_1")
    exit_code = run_atlas_analyze(args)
    assert exit_code == 0

    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert report["snapshot_id"] == "snap_1"

    # Ensure disk.json was created
    disk_json_path = snapshot_dir / "disk.json"
    assert disk_json_path.exists()

    with disk_json_path.open("r", encoding="utf-8") as f:
        report = json.load(f)

    assert report["total_files"] == 3
    assert report["total_bytes"] == 600

    # Largest files (should be sorted descending)
    assert len(report["largest_files"]) == 3
    assert report["largest_files"][0]["path"] == "file2.txt"
    assert report["largest_files"][0]["size"] == 500

    # Oldest files (should be sorted ascending by date)
    assert len(report["oldest_files"]) == 3
    assert report["oldest_files"][0]["path"] == "file2.txt"
    assert report["oldest_files"][0]["mtime"] == "2022-01-01T12:00:00Z"

    # Largest dirs (descending size)
    assert len(report["largest_dirs"]) == 3
    assert report["largest_dirs"][0]["path"] == "dir1"
    assert report["largest_dirs"][0]["size"] == 600
    assert report["largest_dirs"][1]["path"] == "dir2"
    assert report["largest_dirs"][1]["size"] == 300

    # Most populated dirs (descending count)
    assert len(report["most_populated_dirs"]) == 3
    assert report["most_populated_dirs"][0]["path"] == "dir1"
    assert report["most_populated_dirs"][0]["count"] == 2
    assert report["most_populated_dirs"][1]["path"] == "dir2"
    assert report["most_populated_dirs"][1]["count"] == 1

    # Ensure disk_ref is set correctly
    with AtlasRegistry(registry_path) as registry:
        snapshot = registry.get_snapshot("snap_1")
        disk_ref = snapshot.get("disk_ref")
        assert disk_ref is not None
        assert disk_ref == disk_json_path.relative_to(tmp_path / "atlas").as_posix()
