import pytest
import subprocess
import os
import json
import sys
from pathlib import Path
from merger.repoground.atlas.registry import AtlasRegistry

def test_cli_machine_health_json_output(tmp_path, monkeypatch):
    """
    Test explicitly the CLI path for 'atlas machine-health'.
    This verifies that the command parses correctly, dispatches,
    executes against the DB, and outputs valid, expected JSON structure.
    """
    # Create an isolated registry directory
    registry_dir = tmp_path / "atlas" / "registry"
    registry_dir.mkdir(parents=True)
    registry_db = registry_dir / "atlas_registry.sqlite"

    # 1. Setup minimal test data
    with AtlasRegistry(registry_db) as reg:
        reg.register_machine("m-empty", "host-empty")

        reg.register_machine("m-running", "host-running")
        reg.register_root("r2", "m-running", "abs_path", "/foo")
        reg.create_snapshot("snap1", "m-running", "r2", "hash1", "running")

        reg.register_machine("m-complete", "host-complete")
        reg.register_root("r3", "m-complete", "abs_path", "/bar")
        reg.create_snapshot("snap2", "m-complete", "r3", "hash2", "running")
        reg.update_snapshot_status("snap2", "complete")

    # Change into the parent of the `atlas` directory so the cli naturally finds `atlas/registry/...`
    monkeypatch.chdir(tmp_path)

    # 2. Invoke the CLI tool via subprocess
    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    env = os.environ.copy()
    existing_pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{repo_root}{os.pathsep}{existing_pp}" if existing_pp else str(repo_root)

    cmd = [sys.executable, "-m", "merger.repoground.cli.main", "atlas", "machine-health"]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=tmp_path, env=env)

    # 3. Assertions on the result
    assert result.returncode == 0, f"Command failed with stderr: {result.stderr}"

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        pytest.fail(f"CLI output was not valid JSON:\n{result.stdout}")

    # Output should be ordered by machine_id (m-complete, m-empty, m-running)
    assert len(data) == 3

    # Explicitly verify the deterministic ordering
    returned_ids = [d["machine_id"] for d in data]
    assert returned_ids == ["m-complete", "m-empty", "m-running"]

    # Validate m-complete
    m_complete = next(d for d in data if d["machine_id"] == "m-complete")
    assert m_complete["hostname"] == "host-complete"
    assert m_complete["total_complete_snapshots"] == 1
    assert m_complete["has_snapshots"] is True
    assert "last_seen_at" in m_complete

    # Validate m-empty
    m_empty = next(d for d in data if d["machine_id"] == "m-empty")
    assert m_empty["hostname"] == "host-empty"
    assert m_empty["total_complete_snapshots"] == 0
    assert m_empty["has_snapshots"] is False

    # Validate m-running (should NOT count as complete snapshot)
    m_running = next(d for d in data if d["machine_id"] == "m-running")
    assert m_running["hostname"] == "host-running"
    assert m_running["total_complete_snapshots"] == 0
    assert m_running["has_snapshots"] is False
