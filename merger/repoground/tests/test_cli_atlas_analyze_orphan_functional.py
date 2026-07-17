import json
import argparse
from pathlib import Path
from merger.repoground.cli.cmd_atlas import run_atlas_analyze
from merger.repoground.atlas.registry import AtlasRegistry

def test_analyze_orphans_functional(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    registry_path = tmp_path / "atlas/registry/atlas_registry.sqlite"
    registry_path.parent.mkdir(parents=True)

    root_val = tmp_path / "test_root"
    root_val.mkdir()

    # Add files to live root
    (root_val / "file1.txt").write_text("live and in snapshot")
    (root_val / "file2_orphan.txt").write_text("live only")

    with AtlasRegistry(registry_path) as registry:
        registry.register_machine("mach_1", "mach_1")
        registry.register_root("root_1", "mach_1", "abs_path", root_val.resolve().as_posix())
        registry.create_snapshot("snap_1", "mach_1", "root_1", "12345", "complete")

        # Setup snapshot inventory using expected directory structure
        snapshot_dir = tmp_path / "atlas" / "machines" / "mach_1" / "roots" / "root_1" / "snapshots" / "snap_1"
        snapshot_dir.mkdir(parents=True)
        inv_file = snapshot_dir / "inventory.jsonl"

        # Snapshot contains file1.txt and file3_dead.txt
        with inv_file.open("w", encoding="utf-8") as f:
            f.write(json.dumps({"rel_path": "file1.txt"}) + "\n")
            f.write(json.dumps({"rel_path": "file3_dead.txt"}) + "\n")

        registry.update_snapshot_artifacts("snap_1", {"inventory": inv_file.relative_to(tmp_path / "atlas").as_posix()})

    args = argparse.Namespace(analyze_command="orphans", snapshot_id="snap_1")
    exit_code = run_atlas_analyze(args)
    assert exit_code == 0

    captured = capsys.readouterr()
    report = json.loads(captured.out)

    assert report["snapshot_id"] == "snap_1"
    assert report["orphan_count"] == 1
    assert report["dead_file_count"] == 1
    assert "file2_orphan.txt" in report["orphans"]
    assert "file3_dead.txt" in report["dead_files"]
