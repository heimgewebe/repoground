import sys
import subprocess
import json
import os
from pathlib import Path

def test_cli_atlas_analyze_backup_gap(tmp_path, monkeypatch):
    """
    Tests the user-facing contract of providing explicit 'snapshot_id' references.
    This serves as the foundational functional CLI test for Snapshot-ID resolution.
    """
    # Setup registry and environments
    registry_path = tmp_path / "atlas/registry/atlas_registry.sqlite"
    atlas_base = tmp_path / "atlas"
    atlas_base.mkdir(parents=True)

    # We will invoke the CLI script via subprocess but set CWD

    # Let's write a mock registry and snapshot artifacts
    # We can use the AtlasRegistry directly to set up state, then use CLI to query it.
    from merger.repoground.atlas.registry import AtlasRegistry

    with AtlasRegistry(registry_path) as reg:
        reg.register_machine("machine-a", "host-a")
        reg.register_root("root-src", "machine-a", "abs_path", "/src")
        reg.register_root("root-backup", "machine-a", "abs_path", "/backup")

        snap1 = "snap_src_1"
        snap2 = "snap_backup_1"

        reg.create_snapshot(snap1, "machine-a", "root-src", "hash1", "complete")
        reg.create_snapshot(snap2, "machine-a", "root-backup", "hash2", "complete")

        # Write dummy inventory files
        inv_src_path = atlas_base / "inv_src.jsonl"
        with open(inv_src_path, "w", encoding="utf-8") as f:
            f.write(json.dumps({"rel_path": "file1.txt", "size_bytes": 100, "mtime": "2024-01-01"}) + "\n")
            f.write(json.dumps({"rel_path": "file2.txt", "size_bytes": 200, "mtime": "2024-01-01"}) + "\n")
            f.write(json.dumps({"rel_path": "file4.txt", "size_bytes": 400, "mtime": "2024-01-02"}) + "\n")

        inv_backup_path = atlas_base / "inv_backup.jsonl"
        with open(inv_backup_path, "w", encoding="utf-8") as f:
            f.write(json.dumps({"rel_path": "file1.txt", "size_bytes": 100, "mtime": "2024-01-01"}) + "\n")
            f.write(json.dumps({"rel_path": "file3.txt", "size_bytes": 300, "mtime": "2024-01-01"}) + "\n")
            f.write(json.dumps({"rel_path": "file4.txt", "size_bytes": 400, "mtime": "2024-01-01"}) + "\n")

        reg.update_snapshot_artifacts(snap1, {"inventory": "inv_src.jsonl"})
        reg.update_snapshot_artifacts(snap2, {"inventory": "inv_backup.jsonl"})

    monkeypatch.chdir(tmp_path)

    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    env = os.environ.copy()
    existing_pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{repo_root}{os.pathsep}{existing_pp}" if existing_pp else str(repo_root)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "merger.repoground.cli.main",
            "atlas",
            "analyze",
            "backup-gap",
            "snap_src_1",
            "snap_backup_1"
        ],
        capture_output=True,
        text=True,
        env=env
    )

    assert result.returncode == 0, f"Command failed: {result.stderr}"

    # Parse output
    output_json = json.loads(result.stdout.strip())

    # Validation semantics
    assert output_json["source_snapshot"] == "snap_src_1"
    assert output_json["backup_snapshot"] == "snap_backup_1"
    assert output_json["summary"]["missing_count"] == 1
    assert output_json["summary"]["outdated_count"] == 1
    assert output_json["summary"]["extraneous_count"] == 1

    assert output_json["missing"] == ["file2.txt"]
    assert output_json["outdated"] == ["file4.txt"]
    assert output_json["extraneous"] == ["file3.txt"]

def test_cli_atlas_analyze_backup_gap_machine_path_resolution(tmp_path, monkeypatch):
    """
    Tests the user-facing contract of providing 'machine:path' references
    instead of explicit snapshot IDs.
    """
    registry_path = tmp_path / "atlas/registry/atlas_registry.sqlite"
    atlas_base = tmp_path / "atlas"
    atlas_base.mkdir(parents=True)

    from merger.repoground.atlas.registry import AtlasRegistry
    with AtlasRegistry(registry_path) as reg:
        reg.register_machine("machine-a", "host-a")
        reg.register_root("root-src", "machine-a", "abs_path", "/src")
        reg.register_root("root-backup", "machine-a", "abs_path", "/backup")

        # We use explicit created_at to ensure deterministic resolution in _resolve_snapshot_ref
        reg.create_snapshot("snap_src_1", "machine-a", "root-src", "hash1", "complete")
        # In a real environment, creating sets created_at inside SQLite.
        # `_resolve_snapshot_ref` sorts by created_at DESC, returning the latest.
        # We have one snapshot per root, so it will trivially resolve to these.
        reg.create_snapshot("snap_backup_1", "machine-a", "root-backup", "hash2", "complete")

        # Write dummy inventory files
        inv_src_path = atlas_base / "inv_src.jsonl"
        with open(inv_src_path, "w", encoding="utf-8") as f:
            f.write(json.dumps({"rel_path": "file1.txt", "size_bytes": 100, "mtime": "2024-01-01"}) + "\n")
            f.write(json.dumps({"rel_path": "file2.txt", "size_bytes": 200, "mtime": "2024-01-01"}) + "\n")
            f.write(json.dumps({"rel_path": "file4.txt", "size_bytes": 400, "mtime": "2024-01-02"}) + "\n")

        inv_backup_path = atlas_base / "inv_backup.jsonl"
        with open(inv_backup_path, "w", encoding="utf-8") as f:
            f.write(json.dumps({"rel_path": "file1.txt", "size_bytes": 100, "mtime": "2024-01-01"}) + "\n")
            f.write(json.dumps({"rel_path": "file3.txt", "size_bytes": 300, "mtime": "2024-01-01"}) + "\n")
            f.write(json.dumps({"rel_path": "file4.txt", "size_bytes": 400, "mtime": "2024-01-01"}) + "\n")

        reg.update_snapshot_artifacts("snap_src_1", {"inventory": "inv_src.jsonl"})
        reg.update_snapshot_artifacts("snap_backup_1", {"inventory": "inv_backup.jsonl"})

    monkeypatch.chdir(tmp_path)

    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    env = os.environ.copy()
    existing_pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{repo_root}{os.pathsep}{existing_pp}" if existing_pp else str(repo_root)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "merger.repoground.cli.main",
            "atlas",
            "analyze",
            "backup-gap",
            "machine-a:/src",     # Explicit machine:path routing
            "machine-a:/backup"   # Explicit machine:path routing
        ],
        capture_output=True,
        text=True,
        env=env
    )

    assert result.returncode == 0, f"Command failed: {result.stderr}"

    output_json = json.loads(result.stdout.strip())

    assert output_json["source_snapshot"] == "snap_src_1"
    assert output_json["backup_snapshot"] == "snap_backup_1"
    assert output_json["summary"]["missing_count"] == 1
    assert output_json["summary"]["outdated_count"] == 1
    assert output_json["summary"]["extraneous_count"] == 1

    assert output_json["missing"] == ["file2.txt"]
    assert output_json["outdated"] == ["file4.txt"]
    assert output_json["extraneous"] == ["file3.txt"]

def test_cli_atlas_analyze_backup_gap_label_resolution(tmp_path, monkeypatch):
    """
    Tests the user-facing contract of providing 'machine_id:label:root_label' references
    instead of explicit snapshot IDs.
    """
    registry_path = tmp_path / "atlas/registry/atlas_registry.sqlite"
    atlas_base = tmp_path / "atlas"
    atlas_base.mkdir(parents=True)

    from merger.repoground.atlas.registry import AtlasRegistry
    with AtlasRegistry(registry_path) as reg:
        reg.register_machine("machine-a", "host-a")
        reg.register_machine("machine-b", "host-b")
        reg.register_root("root-src", "machine-a", "abs_path", "/src", label="src-label")
        reg.register_root("root-backup", "machine-b", "abs_path", "/backup", label="backup-label")

        reg.create_snapshot("snap_src_1", "machine-a", "root-src", "hash1", "complete")
        reg.create_snapshot("snap_backup_1", "machine-b", "root-backup", "hash2", "complete")

        inv_src_path = atlas_base / "inv_src.jsonl"
        with open(inv_src_path, "w", encoding="utf-8") as f:
            f.write(json.dumps({"rel_path": "file1.txt", "size_bytes": 100, "mtime": "2024-01-01"}) + "\n")
            f.write(json.dumps({"rel_path": "file2.txt", "size_bytes": 200, "mtime": "2024-01-01"}) + "\n")
            f.write(json.dumps({"rel_path": "file4.txt", "size_bytes": 400, "mtime": "2024-01-02"}) + "\n")

        inv_backup_path = atlas_base / "inv_backup.jsonl"
        with open(inv_backup_path, "w", encoding="utf-8") as f:
            f.write(json.dumps({"rel_path": "file1.txt", "size_bytes": 100, "mtime": "2024-01-01"}) + "\n")
            f.write(json.dumps({"rel_path": "file3.txt", "size_bytes": 300, "mtime": "2024-01-01"}) + "\n")
            f.write(json.dumps({"rel_path": "file4.txt", "size_bytes": 400, "mtime": "2024-01-01"}) + "\n")

        reg.update_snapshot_artifacts("snap_src_1", {"inventory": "inv_src.jsonl"})
        reg.update_snapshot_artifacts("snap_backup_1", {"inventory": "inv_backup.jsonl"})

    monkeypatch.chdir(tmp_path)

    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    env = os.environ.copy()
    existing_pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{repo_root}{os.pathsep}{existing_pp}" if existing_pp else str(repo_root)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "merger.repoground.cli.main",
            "atlas",
            "analyze",
            "backup-gap",
            "machine-a:label:src-label",     # Explicit machine:label routing
            "machine-b:label:backup-label"   # Explicit machine:label routing
        ],
        capture_output=True,
        text=True,
        env=env
    )

    assert result.returncode == 0, f"Command failed: {result.stderr}"

    output_json = json.loads(result.stdout.strip())

    assert output_json["source_snapshot"] == "snap_src_1"
    assert output_json["backup_snapshot"] == "snap_backup_1"
    assert output_json["summary"]["missing_count"] == 1
    assert output_json["summary"]["outdated_count"] == 1
    assert output_json["summary"]["extraneous_count"] == 1

    assert output_json["missing"] == ["file2.txt"]
    assert output_json["outdated"] == ["file4.txt"]
    assert output_json["extraneous"] == ["file3.txt"]
