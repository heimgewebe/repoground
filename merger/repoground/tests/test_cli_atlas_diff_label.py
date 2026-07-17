import sys
import subprocess
import os
import json
import pytest
from pathlib import Path
from merger.repoground.cli.cmd_atlas import _resolve_snapshot_ref, parse_snapshot_ref, SnapshotRefKind

class MockRegistry:
    def __init__(self, roots, complete_snapshots):
        self._roots = roots
        self._complete_snapshots = complete_snapshots

    def list_roots(self):
        return self._roots

    def list_complete_snapshots(self, root_id):
        return [s for s in self._complete_snapshots if s["root_id"] == root_id]

@pytest.fixture
def mock_registry():
    roots = [
        {"root_id": "r1", "machine_id": "m1", "root_value": "/path1", "label": "docs"},
        {"root_id": "r2", "machine_id": "m2", "root_value": "/path2", "label": "docs"},
        {"root_id": "r3", "machine_id": "m1", "root_value": "/path3", "label": "images"},
        {"root_id": "r4", "machine_id": "m3", "root_value": "/path4", "label": "multi"},
        {"root_id": "r5", "machine_id": "m3", "root_value": "/path5", "label": "multi"},
        {"root_id": "r6", "machine_id": "m4", "root_value": "/path6", "label": "nodata"},
        {"root_id": "r7", "machine_id": "m5", "root_value": "/path/with:colon", "label": "weird"},
    ]
    snapshots = [
        {"snapshot_id": "s1", "root_id": "r1", "created_at": "2023-01-01T00:00:00Z"},
        {"snapshot_id": "s2", "root_id": "r1", "created_at": "2023-01-02T00:00:00Z"},
        {"snapshot_id": "s3", "root_id": "r2", "created_at": "2023-01-01T00:00:00Z"},
        {"snapshot_id": "s4", "root_id": "r3", "created_at": "2023-01-01T00:00:00Z"},
        {"snapshot_id": "s7", "root_id": "r7", "created_at": "2023-01-01T00:00:00Z"},
    ]
    return MockRegistry(roots, snapshots)


# --- A. Parser tests ---
def test_parse_snapshot_id_directly():
    parsed = parse_snapshot_ref("s123")
    assert parsed.kind == SnapshotRefKind.SNAPSHOT_ID
    assert parsed.value == "s123"

def test_parse_machine_path():
    parsed = parse_snapshot_ref("m1:/path3")
    assert parsed.kind == SnapshotRefKind.MACHINE_PATH
    assert parsed.machine_id == "m1"
    assert parsed.value == "/path3"

def test_parse_machine_label():
    parsed = parse_snapshot_ref("m1:label:docs")
    assert parsed.kind == SnapshotRefKind.MACHINE_LABEL
    assert parsed.machine_id == "m1"
    assert parsed.value == "docs"

def test_parse_machine_label_with_colon():
    parsed = parse_snapshot_ref("m1:label:docs:2024")
    assert parsed.kind == SnapshotRefKind.MACHINE_LABEL
    assert parsed.machine_id == "m1"
    assert parsed.value == "docs:2024"

def test_parse_whitespace_handling():
    # Spaces inside fields are trimmed
    parsed = parse_snapshot_ref(" m1 :label: docs ")
    assert parsed.kind == SnapshotRefKind.MACHINE_LABEL
    assert parsed.machine_id == "m1"
    assert parsed.value == "docs"

    parsed3 = parse_snapshot_ref("m1: label :docs")
    assert parsed3.kind == SnapshotRefKind.MACHINE_LABEL
    assert parsed3.machine_id == "m1"
    assert parsed3.value == "docs"

    parsed4 = parse_snapshot_ref("m1:  label: docs")
    assert parsed4.kind == SnapshotRefKind.MACHINE_LABEL
    assert parsed4.machine_id == "m1"
    assert parsed4.value == "docs"

    parsed2 = parse_snapshot_ref(" m1 : /path ")
    assert parsed2.kind == SnapshotRefKind.MACHINE_PATH
    assert parsed2.machine_id == "m1"
    # root_value path is not stripped by the parser to maintain trailing spaces if needed
    assert parsed2.value == " /path "

def test_parse_error_cases():
    with pytest.raises(ValueError, match="with a non-empty machine_id"):
        parse_snapshot_ref(":label:docs")
    with pytest.raises(ValueError, match="with a non-empty root_label"):
        parse_snapshot_ref("m1:label")
    with pytest.raises(ValueError, match="with a non-empty root_label"):
        parse_snapshot_ref("m1:label:")
    with pytest.raises(ValueError, match="with a non-empty machine_id"):
        parse_snapshot_ref(" :/path")
    with pytest.raises(ValueError, match="with a non-empty path"):
        parse_snapshot_ref("m1:")
    with pytest.raises(ValueError, match="cannot be empty"):
        parse_snapshot_ref("   ")


# --- B. Resolver/E2E tests ---
def test_resolve_by_label_success(mock_registry):
    # Should find r1, and then the latest snapshot (s2)
    snap_id = _resolve_snapshot_ref("m1:label:docs", mock_registry)
    assert snap_id == "s2"

    # Should find r2, and snapshot s3
    snap_id = _resolve_snapshot_ref("m2:label:docs", mock_registry)
    assert snap_id == "s3"

def test_resolve_by_label_not_found(mock_registry):
    with pytest.raises(ValueError, match="No root found for machine 'm1' with label 'missing'"):
        _resolve_snapshot_ref("m1:label:missing", mock_registry)

def test_resolve_by_label_ambiguous(mock_registry):
    with pytest.raises(ValueError, match="Multiple roots found for machine 'm3' with label 'multi'; use machine:path or snapshot_id for explicit disambiguation"):
        _resolve_snapshot_ref("m3:label:multi", mock_registry)

def test_resolve_by_label_no_snapshots(mock_registry):
    with pytest.raises(ValueError, match="No complete snapshot found for machine 'm4' and label 'nodata'"):
        _resolve_snapshot_ref("m4:label:nodata", mock_registry)

def test_resolve_by_path_fallback(mock_registry):
    # Tests the existing machine:path functionality is unmodified
    snap_id = _resolve_snapshot_ref("m1:/path3", mock_registry)
    assert snap_id == "s4"

def test_resolve_snapshot_id_directly(mock_registry):
    # Should just return the exact string if no colon is present
    snap_id = _resolve_snapshot_ref("s123", mock_registry)
    assert snap_id == "s123"

def test_resolve_path_with_colon(mock_registry):
    # Ensure a path with a colon works in the old machine:path branch
    snap_id = _resolve_snapshot_ref("m5:/path/with:colon", mock_registry)
    assert snap_id == "s7"

def test_resolve_by_label_with_colon(mock_registry):
    # This proves that `m1:label:weird:label` is parsed as root_label = `weird:label`
    # We will register a mock root for this
    mock_registry._roots.append({"root_id": "r8", "machine_id": "m1", "root_value": "/weird", "label": "weird:label"})
    mock_registry._complete_snapshots.append({"snapshot_id": "s8", "root_id": "r8", "created_at": "2023-01-01T00:00:00Z"})

    snap_id = _resolve_snapshot_ref("m1:label:weird:label", mock_registry)
    assert snap_id == "s8"

def test_cli_atlas_diff_label_e2e(tmp_path, monkeypatch):
    registry_dir = tmp_path / "atlas" / "registry"
    registry_dir.mkdir(parents=True)
    registry_path = registry_dir / "atlas_registry.sqlite"

    monkeypatch.chdir(tmp_path)

    from merger.repoground.atlas.registry import AtlasRegistry
    from merger.repoground.atlas.paths import resolve_snapshot_dir
    with AtlasRegistry(registry_path) as reg:
        reg.register_machine("m1", "host1")
        reg.register_machine("m2", "host2")
        reg.register_machine("m3", "host3")

        reg.register_root("root_m1", "m1", "abs_path", "/data1", label="docs")
        reg.register_root("root_m2", "m2", "abs_path", "/data2", label="docs")
        reg.register_root("root_m3_a", "m3", "abs_path", "/data3a", label="ambiguous")
        reg.register_root("root_m3_b", "m3", "abs_path", "/data3b", label="ambiguous")

        reg.create_snapshot("snap1", "m1", "root_m1", "hash", "complete")
        reg.create_snapshot("snap2", "m2", "root_m2", "hash", "complete")
        reg.create_snapshot("snap3", "m3", "root_m3_a", "hash", "complete")
        atlas_base = tmp_path / "atlas"

        # Additional setup for colon in label E2E test
        reg.register_root("root_m1_c", "m1", "abs_path", "/data1c", label="docs:2024")
        reg.register_root("root_m2_c", "m2", "abs_path", "/data2c", label="docs:2024")
        reg.create_snapshot("snap_c1", "m1", "root_m1_c", "hash", "complete")
        reg.create_snapshot("snap_c2", "m2", "root_m2_c", "hash", "complete")

        snap_c1_dir = resolve_snapshot_dir(atlas_base, "m1", "root_m1_c", "snap_c1")
        snap_c1_dir.mkdir(parents=True)
        inv_c1 = snap_c1_dir / "inventory.jsonl"
        with open(inv_c1, "w") as f:
            f.write(json.dumps({"rel_path": "file_colon.txt", "size_bytes": 50, "mtime": 1000}) + "\n")
        inv_c1_rel = inv_c1.relative_to(atlas_base).as_posix()
        reg.update_snapshot_artifacts("snap_c1", {"inventory": inv_c1_rel})

        snap_c2_dir = resolve_snapshot_dir(atlas_base, "m2", "root_m2_c", "snap_c2")
        snap_c2_dir.mkdir(parents=True)
        inv_c2 = snap_c2_dir / "inventory.jsonl"
        with open(inv_c2, "w") as f:
            f.write(json.dumps({"rel_path": "file_colon.txt", "size_bytes": 50, "mtime": 1000}) + "\n")
        inv_c2_rel = inv_c2.relative_to(atlas_base).as_posix()
        reg.update_snapshot_artifacts("snap_c2", {"inventory": inv_c2_rel})

        atlas_base = tmp_path / "atlas"

        # We need mock inventories because the cross-root diff tries to load them
        snap1_dir = resolve_snapshot_dir(atlas_base, "m1", "root_m1", "snap1")
        snap1_dir.mkdir(parents=True)
        inv1 = snap1_dir / "inventory.jsonl"
        with open(inv1, "w") as f:
            f.write(json.dumps({"rel_path": "file1.txt", "size_bytes": 100, "mtime": 1000}) + "\n")

        # Artifacts in the registry must be exactly relative to the atlas base directory.
        # The cross-root comparison resolver relies on this exact relative path geometry.
        inv1_rel = inv1.relative_to(atlas_base).as_posix()
        reg.update_snapshot_artifacts("snap1", {"inventory": inv1_rel})

        snap2_dir = resolve_snapshot_dir(atlas_base, "m2", "root_m2", "snap2")
        snap2_dir.mkdir(parents=True)
        inv2 = snap2_dir / "inventory.jsonl"
        with open(inv2, "w") as f:
            f.write(json.dumps({"rel_path": "file1.txt", "size_bytes": 100, "mtime": 1000}) + "\n")

        inv2_rel = inv2.relative_to(atlas_base).as_posix()
        reg.update_snapshot_artifacts("snap2", {"inventory": inv2_rel})

    env = os.environ.copy()
    # test file lives at <repo>/merger/repoground/tests/...
    # subprocess PYTHONPATH must include <repo>, not <repo>/merger/repoground.
    repo_root = Path(__file__).resolve().parents[3]
    env["PYTHONPATH"] = str(repo_root) + os.pathsep + env.get("PYTHONPATH", "")

    # 1. Success case
    cmd = [sys.executable, "-m", "merger.repoground.cli.main", "atlas", "diff", "m1:label:docs", "m2:label:docs"]
    res = subprocess.run(cmd, env=env, capture_output=True, text=True)
    assert res.returncode == 0
    assert "Comparison:" in res.stdout
    assert "From: m1:/data1 (snap1)" in res.stdout
    assert "To:   m2:/data2 (snap2)" in res.stdout
    assert "Mode: cross-root-comparison" in res.stdout
    assert "Summary:" in res.stdout
    assert "New files:" in res.stdout

    # 2. Unknown label
    cmd = [sys.executable, "-m", "merger.repoground.cli.main", "atlas", "diff", "m1:label:unknown", "m2:label:docs"]
    res = subprocess.run(cmd, env=env, capture_output=True, text=True)
    assert res.returncode == 1
    assert "No root found for machine 'm1' with label 'unknown'" in res.stderr

    # 3. Ambiguous label
    cmd = [sys.executable, "-m", "merger.repoground.cli.main", "atlas", "diff", "m3:label:ambiguous", "m1:label:docs"]
    res = subprocess.run(cmd, env=env, capture_output=True, text=True)
    assert res.returncode == 1
    assert "Multiple roots found for machine 'm3' with label 'ambiguous'" in res.stderr

    # 4. Success case with colon in label
    cmd = [sys.executable, "-m", "merger.repoground.cli.main", "atlas", "diff", "m1:label:docs:2024", "m2:label:docs:2024"]
    res = subprocess.run(cmd, env=env, capture_output=True, text=True)
    assert res.returncode == 0
    assert "From: m1:/data1c (snap_c1)" in res.stdout
    assert "To:   m2:/data2c (snap_c2)" in res.stdout
    assert "Summary:" in res.stdout
    assert "New files:" in res.stdout

def test_resolve_by_label_malformed(mock_registry):
    with pytest.raises(ValueError, match="expected syntax 'machine_id:label:<root_label>' with a non-empty root_label"):
        _resolve_snapshot_ref("m1:label", mock_registry)

    with pytest.raises(ValueError, match="expected syntax 'machine_id:label:<root_label>' with a non-empty root_label"):
        _resolve_snapshot_ref("m1:label:", mock_registry)

    with pytest.raises(ValueError, match="expected syntax 'machine_id:label:<root_label>' with a non-empty root_label"):
        _resolve_snapshot_ref("m1:label:   ", mock_registry)

