import json
import pytest
import argparse
from merger.repoground.atlas.diff import _compare_file_sets
from merger.repoground.cli.cmd_atlas import run_atlas_analyze

def test_compare_file_sets_semantics_for_backup_gap():
    """
    Strict semantic test proving that the file comparison logic
    maps correctly to the backup gap domains.
    """

    # Source (from) files
    source_files = {
        "doc/only_in_source.md": {"size_bytes": 100, "mtime": "2024-01-01", "is_symlink": False},
        "doc/both_unchanged.md": {"size_bytes": 200, "mtime": "2024-01-01", "is_symlink": False},
        "doc/both_changed.md": {"size_bytes": 300, "mtime": "2024-01-01", "is_symlink": False},
    }

    # Backup (to) files
    backup_files = {
        "doc/only_in_backup.md": {"size_bytes": 50, "mtime": "2024-01-01", "is_symlink": False},
        "doc/both_unchanged.md": {"size_bytes": 200, "mtime": "2024-01-01", "is_symlink": False},
        "doc/both_changed.md": {"size_bytes": 400, "mtime": "2024-01-02", "is_symlink": False}, # Changed size and mtime
    }

    new_files, removed_files, changed_files = _compare_file_sets(source_files, backup_files)

    # Prove the mapping:
    # 1. missing_in_backup -> removed_files
    # "only_in_source.md" should be missing in backup (removed from the perspective of source -> backup)
    assert removed_files == ["doc/only_in_source.md"]

    # 2. outdated_in_backup -> changed_files
    # "both_changed.md" should be outdated
    assert changed_files == ["doc/both_changed.md"]

    # 3. extraneous_in_backup -> new_files
    # "only_in_backup.md" should be extraneous
    assert new_files == ["doc/only_in_backup.md"]

@pytest.fixture
def backup_gap_registry_setup(tmp_path):
    from merger.repoground.atlas.registry import AtlasRegistry

    registry_db = tmp_path / "atlas" / "registry" / "atlas_registry.sqlite"
    registry_db.parent.mkdir(parents=True, exist_ok=True)

    atlas_base = registry_db.parent.parent

    reg = AtlasRegistry(registry_db)
    reg.register_machine("m1", "host1")
    reg.register_root("r1", "m1", "abs_path", "/var/source")

    reg.register_machine("m2", "host2")
    reg.register_root("r2", "m2", "abs_path", "/var/backup")

    # Source Inventory
    inv_source_path = atlas_base / "artifacts" / "inv_source.jsonl"
    inv_source_path.parent.mkdir(parents=True, exist_ok=True)
    with open(inv_source_path, "w", encoding="utf-8") as f:
        f.write(json.dumps({"snapshot_id": "s_source", "rel_path": "missing.txt", "size_bytes": 100, "mtime": "2023-01-01T00:00:00Z", "is_symlink": False}) + "\n")
        f.write(json.dumps({"snapshot_id": "s_source", "rel_path": "outdated.txt", "size_bytes": 200, "mtime": "2023-01-02T00:00:00Z", "is_symlink": False}) + "\n")
        f.write(json.dumps({"snapshot_id": "s_source", "rel_path": "unchanged.txt", "size_bytes": 300, "mtime": "2023-01-01T00:00:00Z", "is_symlink": False}) + "\n")

    # Backup Inventory
    inv_backup_path = atlas_base / "artifacts" / "inv_backup.jsonl"
    with open(inv_backup_path, "w", encoding="utf-8") as f:
        f.write(json.dumps({"snapshot_id": "s_backup", "rel_path": "outdated.txt", "size_bytes": 150, "mtime": "2023-01-01T00:00:00Z", "is_symlink": False}) + "\n")
        f.write(json.dumps({"snapshot_id": "s_backup", "rel_path": "unchanged.txt", "size_bytes": 300, "mtime": "2023-01-01T00:00:00Z", "is_symlink": False}) + "\n")
        f.write(json.dumps({"snapshot_id": "s_backup", "rel_path": "extraneous.txt", "size_bytes": 50, "mtime": "2023-01-01T00:00:00Z", "is_symlink": False}) + "\n")

    reg.create_snapshot("s_source", "m1", "r1", "hash1", "complete")
    inv_source_rel = inv_source_path.relative_to(atlas_base).as_posix()
    reg.update_snapshot_artifacts("s_source", {"inventory": inv_source_rel})

    reg.create_snapshot("s_backup", "m2", "r2", "hash2", "complete")
    inv_backup_rel = inv_backup_path.relative_to(atlas_base).as_posix()
    reg.update_snapshot_artifacts("s_backup", {"inventory": inv_backup_rel})

    reg.close()
    return tmp_path

def test_run_atlas_analyze_backup_gap_handler(backup_gap_registry_setup, capsys, monkeypatch):
    """
    Test the analyze handler path for backup-gap,
    ensuring it produces the expected JSON report with correct mappings.
    This is a handler-near integration test with snapshot-ID resolution,
    not a full subprocess/parser test.
    """
    tmp_path = backup_gap_registry_setup

    # Establish realistic test environment mapping standard path layouts
    monkeypatch.chdir(tmp_path)

    args = argparse.Namespace(
        analyze_command="backup-gap",
        source_snapshot="s_source",
        backup_snapshot="s_backup"
    )

    ret = run_atlas_analyze(args)
    assert ret == 0

    captured = capsys.readouterr()
    report = json.loads(captured.out)

    assert report["source_snapshot"] == "s_source"
    assert report["backup_snapshot"] == "s_backup"

    assert report["summary"]["missing_count"] == 1
    assert report["summary"]["outdated_count"] == 1
    assert report["summary"]["extraneous_count"] == 1

    assert "missing.txt" in report["missing"]
    assert "outdated.txt" in report["outdated"]
    assert "extraneous.txt" in report["extraneous"]
