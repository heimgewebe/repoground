import subprocess
import os
import sys
from pathlib import Path

def test_cli_rejects_same_machine_rebinding(tmp_path, monkeypatch):
    """
    Tests that the CLI handles a same-machine root rebinding attempt cleanly,
    returning exit code 1 and printing an error to stderr (not a raw traceback).
    """
    repo_root = Path(__file__).resolve().parent.parent.parent.parent

    # Create two different target directories
    dir1 = tmp_path / "target1"
    dir1.mkdir()
    dir2 = tmp_path / "target2"
    dir2.mkdir()

    # Move CLI into the temporary workspace so the registry is created there
    monkeypatch.chdir(tmp_path)

    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{repo_root}{os.pathsep}{existing_pythonpath}"
    env["ATLAS_MACHINE_ID"] = "test-machine"

    # 1. First scan to register the root
    cmd1 = [
        sys.executable,
        "-m", "merger.repoground.cli.main",
        "atlas", "scan",
        str(dir1),
        "--root-id", "my_shared_root"
    ]
    res1 = subprocess.run(cmd1, capture_output=True, text=True, env=env)
    assert res1.returncode == 0

    # 2. Second scan attempting to bind the same root_id to a different path
    cmd2 = [
        sys.executable,
        "-m", "merger.repoground.cli.main",
        "atlas", "scan",
        str(dir2),
        "--root-id", "my_shared_root"
    ]
    res2 = subprocess.run(cmd2, capture_output=True, text=True, env=env)

    # It must fail cleanly
    assert res2.returncode == 1
    # Check that the stderr contains the expected error message and no raw traceback
    assert "Error during root registration:" in res2.stderr
    assert "Cannot silently rebind" in res2.stderr
    assert "Traceback" not in res2.stderr

def test_cli_generates_safe_default_root_id(tmp_path, monkeypatch):
    """
    Tests that the CLI handles scan_root.name with spaces and generates a safe
    default root_id that passes registry validation.
    """
    repo_root = Path(__file__).resolve().parent.parent.parent.parent

    # Create target directory with spaces and unicode
    dir_unsafe = tmp_path / "My Documents"
    dir_unsafe.mkdir()

    monkeypatch.chdir(tmp_path)

    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{repo_root}{os.pathsep}{existing_pythonpath}"
    env["ATLAS_MACHINE_ID"] = "test-machine"

    # Scan without explicit --root-id
    cmd = [
        sys.executable,
        "-m", "merger.repoground.cli.main",
        "atlas", "scan",
        str(dir_unsafe)
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, env=env)

    # It must succeed without raising a ValueError from register_root
    assert res.returncode == 0
    assert "Error during root registration" not in res.stderr

    # Explicitly verify the registered root_id in the SQLite registry
    import sqlite3
    import re
    db_path = tmp_path / "atlas" / "registry" / "atlas_registry.sqlite"
    assert db_path.exists()

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT root_id FROM roots")
    roots = cur.fetchall()
    conn.close()

    assert len(roots) == 1
    root_id = roots[0][0]

    # It must contain no spaces and be filesystem-safe
    assert " " not in root_id
    assert "My-Documents" in root_id
    assert re.match(r"^[A-Za-z0-9._-]+$", root_id)
