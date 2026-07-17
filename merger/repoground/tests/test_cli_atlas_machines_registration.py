import pytest
import sys
import subprocess
import os
import argparse
import socket
from pathlib import Path

from merger.repoground.cli.cmd_atlas import run_atlas_scan, run_atlas_roots
from merger.repoground.atlas.registry import AtlasRegistry
import json

def test_atlas_scan_explicit_machine_and_hostname(tmp_path: Path, monkeypatch):
    # Change current working directory to tmp_path to isolate registry creation
    monkeypatch.chdir(tmp_path)

    # Set up arguments for run_atlas_scan
    scan_root = tmp_path / "scan_target"
    scan_root.mkdir()
    (scan_root / "test_file.txt").write_text("hello")

    args = argparse.Namespace(
        path=str(scan_root),
        exclude=None,
        no_default_excludes=False,
        max_file_size=None,
        no_max_file_size=False,
        depth=100,
        limit=200000,
        mode="inventory",
        incremental=False,
        machine_id="test-machine-id-123",
        hostname="test-hostname-123"
    )

    # Run the scan
    exit_code = run_atlas_scan(args)
    assert exit_code == 0

    # Verify the registry
    registry_path = Path("atlas/registry/atlas_registry.sqlite").resolve()
    assert registry_path.exists()

    with AtlasRegistry(registry_path) as registry:
        machine = registry.get_machine("test-machine-id-123")
        assert machine is not None
        assert machine["machine_id"] == "test-machine-id-123"
        assert machine["hostname"] == "test-hostname-123"

def test_atlas_scan_default_machine_and_hostname(tmp_path: Path, monkeypatch):
    # Change current working directory to tmp_path to isolate registry creation
    monkeypatch.chdir(tmp_path)

    # clear env var
    monkeypatch.delenv("ATLAS_MACHINE_ID", raising=False)

    scan_root = tmp_path / "scan_target"
    scan_root.mkdir()

    args = argparse.Namespace(
        path=str(scan_root),
        exclude=None,
        no_default_excludes=False,
        max_file_size=None,
        no_max_file_size=False,
        depth=100,
        limit=200000,
        mode="inventory",
        incremental=False,
        machine_id=None,
        hostname=None
    )

    # Run the scan
    exit_code = run_atlas_scan(args)
    assert exit_code == 0

    expected_hostname = socket.gethostname().strip().lower()

    registry_path = Path("atlas/registry/atlas_registry.sqlite").resolve()
    with AtlasRegistry(registry_path) as registry:
        machine = registry.get_machine(expected_hostname)
        assert machine is not None
        assert machine["machine_id"] == expected_hostname
        assert machine["hostname"] == expected_hostname

def test_atlas_scan_machine_registration_conflict(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    scan_root = tmp_path / "scan_target"
    scan_root.mkdir()

    # Preregister m1 with host-a
    registry_path = Path("atlas/registry/atlas_registry.sqlite").resolve()
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    with AtlasRegistry(registry_path) as registry:
        registry.register_machine("m1", "host-a")

    args = argparse.Namespace(
        path=str(scan_root),
        exclude=None,
        no_default_excludes=False,
        max_file_size=None,
        no_max_file_size=False,
        depth=100,
        limit=200000,
        mode="inventory",
        incremental=False,
        machine_id="m1",
        hostname="host-b"
    )

    exit_code = run_atlas_scan(args)
    assert exit_code == 1

    captured = capsys.readouterr()
    assert "already registered with a different hostname" in captured.err

def test_atlas_scan_machine_registration_case_insensitivity(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    scan_root = tmp_path / "scan_target"
    scan_root.mkdir()

    registry_path = Path("atlas/registry/atlas_registry.sqlite").resolve()
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    with AtlasRegistry(registry_path) as registry:
        registry.register_machine("m1", "host-a")

    args = argparse.Namespace(
        path=str(scan_root),
        exclude=None,
        no_default_excludes=False,
        max_file_size=None,
        no_max_file_size=False,
        depth=100,
        limit=200000,
        mode="inventory",
        incremental=False,
        machine_id="M1",
        hostname="HOST-A"
    )

    # Should succeed because it normalizes to m1 and host-a, which match the existing record
    exit_code = run_atlas_scan(args)
    assert exit_code == 0

def test_atlas_scan_env_var_fallback(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    scan_root = tmp_path / "scan_target"
    scan_root.mkdir()

    monkeypatch.setenv("ATLAS_MACHINE_ID", "env-machine-123")

    args = argparse.Namespace(
        path=str(scan_root),
        exclude=None,
        no_default_excludes=False,
        max_file_size=None,
        no_max_file_size=False,
        depth=100,
        limit=200000,
        mode="inventory",
        incremental=False,
        machine_id=None,
        hostname=None
    )

    exit_code = run_atlas_scan(args)
    assert exit_code == 0

    expected_hostname = socket.gethostname().strip().lower()

    registry_path = Path("atlas/registry/atlas_registry.sqlite").resolve()
    with AtlasRegistry(registry_path) as registry:
        machine = registry.get_machine("env-machine-123")
        assert machine is not None
        assert machine["machine_id"] == "env-machine-123"
        assert machine["hostname"] == expected_hostname


def test_atlas_scan_explicit_overrides_env_var(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    scan_root = tmp_path / "scan_target"
    scan_root.mkdir()

    monkeypatch.setenv("ATLAS_MACHINE_ID", "env-machine-123")

    args = argparse.Namespace(
        path=str(scan_root),
        exclude=None,
        no_default_excludes=False,
        max_file_size=None,
        no_max_file_size=False,
        depth=100,
        limit=200000,
        mode="inventory",
        incremental=False,
        machine_id="explicit-machine-456",
        hostname=None
    )

    exit_code = run_atlas_scan(args)
    assert exit_code == 0

    expected_hostname = socket.gethostname().strip().lower()

    registry_path = Path("atlas/registry/atlas_registry.sqlite").resolve()
    with AtlasRegistry(registry_path) as registry:
        machine = registry.get_machine("explicit-machine-456")
        assert machine is not None
        assert machine["machine_id"] == "explicit-machine-456"
        assert machine["hostname"] == expected_hostname

        env_machine = registry.get_machine("env-machine-123")
        assert env_machine is None


def test_atlas_scan_empty_hostname_fails(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    scan_root = tmp_path / "scan_target"
    scan_root.mkdir()

    args = argparse.Namespace(
        path=str(scan_root),
        exclude=None,
        no_default_excludes=False,
        max_file_size=None,
        no_max_file_size=False,
        depth=100,
        limit=200000,
        mode="inventory",
        incremental=False,
        machine_id="m1",
        hostname="   "
    )

    exit_code = run_atlas_scan(args)
    assert exit_code == 1

    captured = capsys.readouterr()
    assert "Hostname cannot be empty" in captured.err


def test_atlas_scan_empty_machine_id_fails(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    scan_root = tmp_path / "scan_target"
    scan_root.mkdir()

    args = argparse.Namespace(
        path=str(scan_root),
        exclude=None,
        no_default_excludes=False,
        max_file_size=None,
        no_max_file_size=False,
        depth=100,
        limit=200000,
        mode="inventory",
        incremental=False,
        machine_id="",
        hostname="valid-hostname"
    )

    exit_code = run_atlas_scan(args)
    assert exit_code == 1

    captured = capsys.readouterr()
    assert "Invalid machine_id format" in captured.err

def test_atlas_scan_empty_hostname_string_fails_without_fallback(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    scan_root = tmp_path / "scan_target"
    scan_root.mkdir()

    args = argparse.Namespace(
        path=str(scan_root),
        exclude=None,
        no_default_excludes=False,
        max_file_size=None,
        no_max_file_size=False,
        depth=100,
        limit=200000,
        mode="inventory",
        incremental=False,
        machine_id="valid-machine",
        hostname=""
    )

    exit_code = run_atlas_scan(args)
    assert exit_code == 1

    captured = capsys.readouterr()
    assert "Hostname cannot be empty" in captured.err



def test_atlas_scan_legacy_machine_id_propagation(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    scan_root = tmp_path / "scan_target"
    scan_root.mkdir()

    # Pre-insert legacy uppercase machine_id directly
    registry_path = Path("atlas/registry/atlas_registry.sqlite").resolve()
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    with AtlasRegistry(registry_path) as registry:
        cur = registry.conn.cursor()
        cur.execute(
            "INSERT INTO machines (machine_id, hostname, labels, last_seen_at) VALUES (?, ?, ?, ?)",
            ("LEGACY-PROP-1", "host-prop", None, "2026-03-21T18:26:22Z")
        )
        registry.conn.commit()

    args = argparse.Namespace(
        path=str(scan_root),
        exclude=None,
        no_default_excludes=False,
        max_file_size=None,
        no_max_file_size=False,
        depth=100,
        limit=200000,
        mode="inventory",
        incremental=False,
        machine_id="legacy-prop-1",
        hostname="host-prop"
    )

    exit_code = run_atlas_scan(args)
    assert exit_code == 0

    with AtlasRegistry(registry_path) as registry:
        # Machine should still only exist as uppercase
        assert registry.get_machine("legacy-prop-1") is None
        assert registry.get_machine("LEGACY-PROP-1") is not None

        # Verify the root was registered under the uppercase ID
        roots = registry.list_roots()
        prop_root = next((r for r in roots if r["machine_id"] == "LEGACY-PROP-1"), None)
        assert prop_root is not None

        # Verify the snapshot was created under the uppercase ID
        snapshots = registry.list_snapshots()
        prop_snap = next((s for s in snapshots if s["machine_id"] == "LEGACY-PROP-1"), None)
        assert prop_snap is not None

def test_atlas_scan_explicit_root_identity(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    scan_root = tmp_path / "scan_target"
    scan_root.mkdir()

    args = argparse.Namespace(
        path=str(scan_root),
        exclude=None,
        no_default_excludes=False,
        max_file_size=None,
        no_max_file_size=False,
        depth=100,
        limit=200000,
        mode="inventory",
        incremental=False,
        machine_id="test-machine",
        hostname="test-host",
        root_id="explicit-root",
        root_label="explicit-label"
    )

    exit_code = run_atlas_scan(args)
    assert exit_code == 0

    registry_path = Path("atlas/registry/atlas_registry.sqlite").resolve()
    with AtlasRegistry(registry_path) as registry:
        root = registry.get_root("explicit-root")
        assert root is not None
        assert root["machine_id"] == "test-machine"
        assert root["label"] == "explicit-label"
        assert root["root_value"] == str(scan_root.resolve())

def test_atlas_scan_empty_explicit_root_id_fails(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    scan_root = tmp_path / "scan_target"
    scan_root.mkdir()

    args = argparse.Namespace(
        path=str(scan_root),
        exclude=None,
        no_default_excludes=False,
        max_file_size=None,
        no_max_file_size=False,
        depth=100,
        limit=200000,
        mode="inventory",
        incremental=False,
        machine_id="test-machine",
        hostname="test-host",
        root_id="   ",
        root_label="explicit-label"
    )

    exit_code = run_atlas_scan(args)
    assert exit_code == 1

    captured = capsys.readouterr()
    assert "Error: root-id cannot be explicitly empty." in captured.err

def test_atlas_scan_explicit_root_identity_cli(tmp_path: Path):
    scan_root = tmp_path / "cli_scan_target"
    scan_root.mkdir()

    repo_root = Path(__file__).parent.parent.parent.parent.resolve()
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{repo_root}{os.pathsep}{existing_pythonpath}" if existing_pythonpath else str(repo_root)

    # We must explicitly set ATLAS_MACHINE_ID to bypass any system hostname inference
    # problems in the runner environment if we don't pass --machine-id, or we can just pass it.

    cmd = [
        sys.executable,
        "-m", "merger.repoground.cli.main",
        "atlas", "scan",
        str(scan_root),
        "--machine-id", "test-machine",
        "--hostname", "test-host",
        "--root-id", "  explicit-cli-root  ",
        "--root-label", " explicit-cli-label "
    ]

    result = subprocess.run(cmd, env=env, cwd=str(tmp_path), capture_output=True, text=True)
    assert result.returncode == 0, f"CLI command failed. stderr: {result.stderr}"

    registry_path = tmp_path / "atlas" / "registry" / "atlas_registry.sqlite"
    assert registry_path.exists()

    with AtlasRegistry(registry_path) as registry:
        root = registry.get_root("explicit-cli-root")
        assert root is not None, "Explicit root ID was not stripped or not registered"
        assert root["machine_id"] == "test-machine"
        assert root["label"] == "explicit-cli-label"
        assert root["root_value"] == str(scan_root.resolve())

def test_atlas_scan_explicit_root_identity_cli_empty_id(tmp_path: Path):
    scan_root = tmp_path / "cli_scan_target"
    scan_root.mkdir()

    repo_root = Path(__file__).parent.parent.parent.parent.resolve()
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{repo_root}{os.pathsep}{existing_pythonpath}" if existing_pythonpath else str(repo_root)

    cmd = [
        sys.executable,
        "-m", "merger.repoground.cli.main",
        "atlas", "scan",
        str(scan_root),
        "--machine-id", "test-machine",
        "--hostname", "test-host",
        "--root-id", "   "
    ]

    result = subprocess.run(cmd, env=env, cwd=str(tmp_path), capture_output=True, text=True)
    assert result.returncode == 1, "CLI should have failed with empty explicit root-id"
    assert "Error: root-id cannot be explicitly empty." in result.stderr

def test_atlas_scan_empty_explicit_root_label_fails(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    scan_root = tmp_path / "scan_target"
    scan_root.mkdir()

    args = argparse.Namespace(
        path=str(scan_root),
        exclude=None,
        no_default_excludes=False,
        max_file_size=None,
        no_max_file_size=False,
        depth=100,
        limit=200000,
        mode="inventory",
        incremental=False,
        machine_id="test-machine",
        hostname="test-host",
        root_id="explicit-root",
        root_label="   "
    )

    exit_code = run_atlas_scan(args)
    assert exit_code == 1

    captured = capsys.readouterr()
    assert "Error: root-label cannot be explicitly empty." in captured.err

def test_atlas_scan_explicit_root_identity_cli_empty_label(tmp_path: Path):
    scan_root = tmp_path / "cli_scan_target"
    scan_root.mkdir()

    repo_root = Path(__file__).parent.parent.parent.parent.resolve()
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{repo_root}{os.pathsep}{existing_pythonpath}" if existing_pythonpath else str(repo_root)

    cmd = [
        sys.executable,
        "-m", "merger.repoground.cli.main",
        "atlas", "scan",
        str(scan_root),
        "--machine-id", "test-machine",
        "--hostname", "test-host",
        "--root-id", "explicit-cli-root",
        "--root-label", "   "
    ]

    result = subprocess.run(cmd, env=env, cwd=str(tmp_path), capture_output=True, text=True)
    assert result.returncode == 1, "CLI should have failed with empty explicit root-label"
    assert "Error: root-label cannot be explicitly empty." in result.stderr


@pytest.mark.parametrize("invalid_id", [
    "invalid/path",
    "invalid\\path",
    "..",
    ".",
    "invalid path",
    "path*with*star"
])
def test_atlas_scan_explicit_root_identity_invalid_chars_fails(tmp_path: Path, monkeypatch, capsys, invalid_id):
    monkeypatch.chdir(tmp_path)
    scan_root = tmp_path / "scan_target"
    scan_root.mkdir()

    args = argparse.Namespace(
        path=str(scan_root),
        exclude=None,
        no_default_excludes=False,
        max_file_size=None,
        no_max_file_size=False,
        depth=100,
        limit=200000,
        mode="inventory",
        incremental=False,
        machine_id="test-machine",
        hostname="test-host",
        root_id=invalid_id,
        root_label="explicit-label"
    )

    exit_code = run_atlas_scan(args)
    assert exit_code == 1

    captured = capsys.readouterr()
    assert f"Error: explicit root-id '{invalid_id.strip()}' is invalid." in captured.err

def test_atlas_scan_root_identity_cross_machine_overwrite_fails(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    scan_root = tmp_path / "scan_target"
    scan_root.mkdir()

    scan_root_2 = tmp_path / "scan_target_2"
    scan_root_2.mkdir()

    # Machine 1 creates root
    args1 = argparse.Namespace(
        path=str(scan_root),
        exclude=None,
        no_default_excludes=False,
        max_file_size=None,
        no_max_file_size=False,
        depth=100,
        limit=200000,
        mode="inventory",
        incremental=False,
        machine_id="machine-1",
        hostname="host-1",
        root_id="shared-root-id",
        root_label=None
    )

    exit_code1 = run_atlas_scan(args1)
    assert exit_code1 == 0

    # Machine 2 tries to reuse same root_id explicitly
    args2 = argparse.Namespace(
        path=str(scan_root_2),
        exclude=None,
        no_default_excludes=False,
        max_file_size=None,
        no_max_file_size=False,
        depth=100,
        limit=200000,
        mode="inventory",
        incremental=False,
        machine_id="machine-2",
        hostname="host-2",
        root_id="shared-root-id",
        root_label=None
    )

    exit_code2 = run_atlas_scan(args2)
    assert exit_code2 == 1

    captured = capsys.readouterr()
    assert "is already registered to a different machine" in captured.err
    assert "Cannot silently overwrite" in captured.err

    registry_path = Path("atlas/registry/atlas_registry.sqlite").resolve()
    with AtlasRegistry(registry_path) as registry:
        root = registry.get_root("shared-root-id")
        # Ensure it wasn't overwritten
        assert root["machine_id"] == "machine-1"

def test_atlas_scan_default_root_label_generation(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    scan_root = tmp_path / "My Documents"
    scan_root.mkdir()

    args = argparse.Namespace(
        path=str(scan_root),
        exclude=None,
        no_default_excludes=False,
        max_file_size=None,
        no_max_file_size=False,
        depth=100,
        limit=200000,
        mode="inventory",
        incremental=False,
        machine_id="test-machine",
        hostname="test-host",
        root_id=None,
        root_label=None
    )

    exit_code = run_atlas_scan(args)
    assert exit_code == 0

    registry_path = Path("atlas/registry/atlas_registry.sqlite").resolve()
    with AtlasRegistry(registry_path) as registry:
        roots = registry.list_roots()
        assert len(roots) == 1
        assert roots[0]["label"] == "my-documents"

def test_atlas_scan_explicit_root_label_stripped(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    scan_root = tmp_path / "scan_target"
    scan_root.mkdir()

    args = argparse.Namespace(
        path=str(scan_root),
        exclude=None,
        no_default_excludes=False,
        max_file_size=None,
        no_max_file_size=False,
        depth=100,
        limit=200000,
        mode="inventory",
        incremental=False,
        machine_id="test-machine",
        hostname="test-host",
        root_id=None,
        root_label="   explicit-docs  "
    )

    exit_code = run_atlas_scan(args)
    assert exit_code == 0

    registry_path = Path("atlas/registry/atlas_registry.sqlite").resolve()
    with AtlasRegistry(registry_path) as registry:
        roots = registry.list_roots()
        assert len(roots) == 1
        assert roots[0]["label"] == "explicit-docs"

def test_atlas_scan_multiple_roots_same_label(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    scan_root1 = tmp_path / "My Documents"
    scan_root1.mkdir()

    args1 = argparse.Namespace(
        path=str(scan_root1),
        exclude=None,
        no_default_excludes=False,
        max_file_size=None,
        no_max_file_size=False,
        depth=100,
        limit=200000,
        mode="inventory",
        incremental=False,
        machine_id="machine-1",
        hostname="host-1",
        root_id=None,
        root_label=None
    )

    exit_code1 = run_atlas_scan(args1)
    assert exit_code1 == 0

    scan_root2 = tmp_path / "Other Host" / "My Documents"
    scan_root2.parent.mkdir()
    scan_root2.mkdir()

    args2 = argparse.Namespace(
        path=str(scan_root2),
        exclude=None,
        no_default_excludes=False,
        max_file_size=None,
        no_max_file_size=False,
        depth=100,
        limit=200000,
        mode="inventory",
        incremental=False,
        machine_id="machine-2",
        hostname="host-2",
        root_id=None,
        root_label="my-documents"
    )

    exit_code2 = run_atlas_scan(args2)
    assert exit_code2 == 0

    registry_path = Path("atlas/registry/atlas_registry.sqlite").resolve()
    with AtlasRegistry(registry_path) as registry:
        roots = registry.list_roots()
        assert len(roots) == 2

        labels = [r["label"] for r in roots]
        assert labels == ["my-documents", "my-documents"]

def test_atlas_cli_roots_grouping(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    # Preregister
    registry_path = Path("atlas/registry/atlas_registry.sqlite").resolve()
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    with AtlasRegistry(registry_path) as registry:
        registry.register_machine("m1", "h1")
        registry.register_machine("m2", "h2")
        registry.register_root("m1_docs", "m1", "abs_path", "/path/1", label="documents")
        registry.register_root("m2_docs", "m2", "abs_path", "/path/2", label="documents")
        registry.register_root("m1_pics", "m1", "abs_path", "/path/3", label="pictures")

    # Test Default JSON Output
    args_default = argparse.Namespace(group_by_label=False)
    exit_code = run_atlas_roots(args_default)
    assert exit_code == 0
    captured = capsys.readouterr()
    output_json = captured.out

    # Verify it parses as JSON and contains the roots
    roots_list = json.loads(output_json)
    assert len(roots_list) == 3
    labels = [r.get("label") for r in roots_list]
    assert "documents" in labels
    assert "pictures" in labels

    # Test Grouped Output
    args_grouped = argparse.Namespace(group_by_label=True)
    exit_code = run_atlas_roots(args_grouped)
    assert exit_code == 0
    captured = capsys.readouterr()
    output_text = captured.out

    assert "documents:" in output_text
    assert "  - machine: m1 | id: m1_docs -> /path/1" in output_text
    assert "  - machine: m2 | id: m2_docs -> /path/2" in output_text
    assert "pictures:" in output_text
    assert "  - machine: m1 | id: m1_pics -> /path/3" in output_text


def test_atlas_scan_root_path_fallback(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    scan_root = tmp_path / "dummy"
    scan_root.mkdir()

    # Simple object to bypass Path.name issues
    class MockPath:
        def __init__(self, p):
            self.p = p
            self.name = ""
            self.drive = "C:"
            self.anchor = "C:\\"
        def __str__(self):
            return str(self.p)
        def exists(self):
            return self.p.exists()
        def is_dir(self):
            return self.p.is_dir()
        def is_file(self):
            return self.p.is_file()
        def is_symlink(self):
            return self.p.is_symlink()
        def resolve(self):
            return self.p.resolve()
        def stat(self):
            return self.p.stat()
        def iterdir(self):
            return self.p.iterdir()
        def __fspath__(self):
            return str(self.p)

    def mock_path(p):
        return MockPath(Path(p))

    monkeypatch.setattr("merger.repoground.cli.cmd_atlas.Path", mock_path)

    args = argparse.Namespace(
        path=str(scan_root),
        exclude=None,
        no_default_excludes=False,
        max_file_size=None,
        no_max_file_size=False,
        depth=100,
        limit=200000,
        mode="inventory",
        incremental=False,
        machine_id="test-machine",
        hostname="test-host",
        root_id=None,
        root_label=None
    )

    exit_code = run_atlas_scan(args)
    assert exit_code == 0

    registry_path = Path("atlas/registry/atlas_registry.sqlite").resolve()
    with AtlasRegistry(registry_path) as registry:
        roots = registry.list_roots()
        assert len(roots) == 1
        assert roots[0]["label"] == "c"

def test_atlas_cli_roots_grouping_semantic_collision(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    registry_path = Path("atlas/registry/atlas_registry.sqlite").resolve()
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    with AtlasRegistry(registry_path) as registry:
        registry.register_machine("m1", "h1")
        # Root 1: label=None
        registry.register_root("m1_none", "m1", "abs_path", "/path/none", label=None)
        # Root 2: label="unlabeled"
        registry.register_root("m1_unlabeled", "m1", "abs_path", "/path/unlabeled", label="unlabeled")

    args_grouped = argparse.Namespace(group_by_label=True)
    exit_code = run_atlas_roots(args_grouped)
    assert exit_code == 0

    captured = capsys.readouterr()
    output_text = captured.out

    # They should be separated in output
    assert "(none):" in output_text
    assert "  - machine: m1 | id: m1_none -> /path/none" in output_text
    assert "unlabeled:" in output_text
    assert "  - machine: m1 | id: m1_unlabeled -> /path/unlabeled" in output_text