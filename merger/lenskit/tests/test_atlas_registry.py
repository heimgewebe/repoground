import pytest
import sqlite3
from merger.lenskit.atlas.registry import AtlasRegistry

@pytest.fixture
def temp_db_path(tmp_path):
    return tmp_path / "test_registry.sqlite"

@pytest.fixture
def registry(temp_db_path):
    with AtlasRegistry(temp_db_path) as reg:
        yield reg

def test_registry_initialization(temp_db_path, registry):
    assert temp_db_path.exists()
    conn = sqlite3.connect(temp_db_path)
    cur = conn.cursor()

    # Check tables exist
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in cur.fetchall()}
    assert "machines" in tables
    assert "roots" in tables
    assert "snapshots" in tables
    conn.close()

def test_machine_registry(registry):
    # Register new machine
    registry.register_machine("m1", "host-a", ["local", "dev"])

    m = registry.get_machine("m1")
    assert m is not None
    assert m["machine_id"] == "m1"
    assert m["hostname"] == "host-a"
    assert "local" in m["labels"]
    assert m["last_seen_at"] is not None

    # Update existing machine (with matching hostname)
    registry.register_machine("m1", "host-a", ["prod"])
    m2 = registry.get_machine("m1")
    assert m2["hostname"] == "host-a"
    assert "prod" in m2["labels"]

    # Updating with different hostname should fail
    with pytest.raises(ValueError, match="already registered with a different hostname"):
        registry.register_machine("m1", "host-b", ["prod"])

    # Invalid machine_id should fail
    with pytest.raises(ValueError, match="Invalid machine_id format"):
        registry.register_machine("m 1 !", "host-a")

    # Empty hostname should fail
    with pytest.raises(ValueError, match="Hostname cannot be empty"):
        registry.register_machine("m2", "   ")

    # List machines
    registry.register_machine("m2", "host-c")
    machines = registry.list_machines()
    assert len(machines) == 2

def test_root_registry(registry):
    registry.register_machine("m1", "host-a")

    registry.register_root("r1", "m1", "abs_path", "/var/www", "www-root")

    r = registry.get_root("r1")
    assert r is not None
    assert r["root_id"] == "r1"
    assert r["machine_id"] == "m1"
    assert r["root_kind"] == "abs_path"
    assert r["root_value"] == "/var/www"
    assert r["label"] == "www-root"

    # Update existing root
    registry.register_root("r1", "m1", "preset", "/var/www", "new-label")
    r2 = registry.get_root("r1")
    assert r2["root_kind"] == "preset"
    assert r2["root_value"] == "/var/www"
    assert r2["label"] == "new-label"

    # List roots
    registry.register_root("r2", "m1", "abs_path", "/tmp")
    roots = registry.list_roots()
    assert len(roots) == 2

def test_snapshot_registry(registry):
    registry.register_machine("m1", "host-a")
    registry.register_root("r1", "m1", "abs_path", "/var/www")

    registry.create_snapshot("s1", "m1", "r1", "hash123", "running")

    s = registry.get_snapshot("s1")
    assert s is not None
    assert s["snapshot_id"] == "s1"
    assert s["machine_id"] == "m1"
    assert s["root_id"] == "r1"
    assert s["scan_config_hash"] == "hash123"
    assert s["status"] == "running"
    assert s["created_at"] is not None
    assert s["inventory_ref"] is None

    registry.update_snapshot_status("s1", "complete")
    s2 = registry.get_snapshot("s1")
    assert s2["status"] == "complete"

    registry.update_snapshot_artifacts("s1", {"inventory": "inv.jsonl", "topology": "topo.json"})
    s3 = registry.get_snapshot("s1")
    assert s3["inventory_ref"] == "inv.jsonl"
    assert s3["topology_ref"] == "topo.json"
    assert s3["dirs_ref"] is None

    # List snapshots
    # Ensure they have identical created_at to test secondary sorting on ID
    cur = registry.conn.cursor()
    cur.execute("UPDATE snapshots SET created_at = '2026-03-10T00:00:00Z' WHERE snapshot_id = 's1'")
    registry.conn.commit()

    registry.create_snapshot("s2", "m1", "r1", "hash456", "running")
    cur.execute("UPDATE snapshots SET created_at = '2026-03-10T00:00:00Z' WHERE snapshot_id = 's2'")
    registry.conn.commit()

    snapshots = registry.list_snapshots()
    assert len(snapshots) == 2

    # Check ordering by created_at DESC, snapshot_id DESC
    # Since both have the exact same created_at, 's2' must strictly appear before 's1'
    assert snapshots[0]["snapshot_id"] == "s2"
    assert snapshots[1]["snapshot_id"] == "s1"


def test_delta_registry(registry):
    registry.register_machine("m1", "host-a")
    registry.register_root("r1", "m1", "abs_path", "/var/www")

    registry.create_snapshot("s1", "m1", "r1", "hash1", "complete")
    registry.create_snapshot("s2", "m1", "r1", "hash2", "complete")

    registry.register_delta("delta1", "s1", "s2", "delta_ref.json")

    delta = registry.get_delta("delta1")
    assert delta is not None
    assert delta["delta_id"] == "delta1"
    assert delta["from_snapshot_id"] == "s1"
    assert delta["to_snapshot_id"] == "s2"
    assert delta["delta_ref"] == "delta_ref.json"
    assert "created_at" in delta

    registry.create_snapshot("s3", "m1", "r1", "hash3", "complete")
    registry.register_delta("delta2", "s2", "s3", "delta_ref2.json")

    # Check ordering by created_at DESC, delta_id DESC
    cur = registry.conn.cursor()
    cur.execute("UPDATE deltas SET created_at = '2026-03-10T00:00:00Z' WHERE delta_id = 'delta1'")
    cur.execute("UPDATE deltas SET created_at = '2026-03-10T00:00:00Z' WHERE delta_id = 'delta2'")
    registry.conn.commit()

    deltas = registry.list_deltas()
    assert len(deltas) == 2
    assert deltas[0]["delta_id"] == "delta2"
    assert deltas[1]["delta_id"] == "delta1"


def test_machine_registry_legacy_reuse(registry):
    cur = registry.conn.cursor()
    # Force insert a legacy uppercase entry directly into SQLite to bypass current lower() normalization
    cur.execute(
        "INSERT INTO machines (machine_id, hostname, labels, last_seen_at) VALUES (?, ?, ?, ?)",
        ("LEGACY-M1", "HOST-A", None, "2026-03-21T18:26:22Z")
    )
    registry.conn.commit()

    # Re-registering with new lowercase normalized equivalent should reuse the same row
    used_id = registry.register_machine("legacy-m1", "host-a", ["legacy"])
    assert used_id == "LEGACY-M1"

    # Assert get_machine with legacy ID works exactly
    m = registry.get_machine("LEGACY-M1")
    assert m is not None
    assert "legacy" in m["labels"]

    # Ensure no duplicate was created
    machines = registry.list_machines()
    assert len(machines) == 1

def test_machine_registry_ambiguous_legacy_ids(registry):
    cur = registry.conn.cursor()
    cur.execute("INSERT INTO machines (machine_id, hostname) VALUES (?, ?)", ("M1", "host-a"))
    cur.execute("INSERT INTO machines (machine_id, hostname) VALUES (?, ?)", ("m1", "host-a"))
    registry.conn.commit()

    with pytest.raises(ValueError, match="Ambiguous legacy machine IDs found for"):
        registry.register_machine("m1", "host-a")

def test_machine_health(registry):
    registry.register_machine("m1", "host1")
    registry.register_root("r1", "m1", "abs_path", "/foo")

    # Test without snapshots
    health = registry.get_machine_health()
    assert len(health) == 1
    assert health[0]["machine_id"] == "m1"
    assert health[0]["total_complete_snapshots"] == 0
    assert health[0]["has_snapshots"] == False

    # Add a running snapshot
    registry.create_snapshot("s1", "m1", "r1", "hash1", "running")
    health = registry.get_machine_health()
    assert health[0]["total_complete_snapshots"] == 0
    assert health[0]["has_snapshots"] == False

    # Mark as complete
    registry.update_snapshot_status("s1", "complete")
    health = registry.get_machine_health()
    assert health[0]["total_complete_snapshots"] == 1
    assert health[0]["has_snapshots"] == True
    assert health[0]["last_snapshot_at"] is not None

def test_root_registry_validation(registry):
    registry.register_machine("m1", "host-a")
    registry.register_machine("m2", "host-b")

    # Valid root
    registry.register_root("my_root", "m1", "abs_path", "/var/www")
    assert registry.get_root("my_root")["root_value"] == "/var/www"

    # Reject empty root ID
    with pytest.raises(ValueError, match="Root ID cannot be empty."):
        registry.register_root("   ", "m1", "abs_path", "/tmp")

    # Reject invalid characters
    with pytest.raises(ValueError, match="is invalid"):
        registry.register_root("invalid root/id", "m1", "abs_path", "/tmp")

    # Reject strictly . and ..
    with pytest.raises(ValueError, match="cannot be '.' or '..'"):
        registry.register_root(".", "m1", "abs_path", "/tmp")
    with pytest.raises(ValueError, match="cannot be '.' or '..'"):
        registry.register_root("..", "m1", "abs_path", "/tmp")

    # Reject cross-machine overwrite
    with pytest.raises(ValueError, match="is already registered to a different machine"):
        registry.register_root("my_root", "m2", "abs_path", "/var/www")

    # Reject same-machine rebinding to different path
    with pytest.raises(ValueError, match="is already bound to path"):
        registry.register_root("my_root", "m1", "abs_path", "/different/path")

    # Updating with SAME path is allowed (e.g., updating label)
    registry.register_root("my_root", "m1", "abs_path", "/var/www", "new-label")
    assert registry.get_root("my_root")["label"] == "new-label"
