
import json
from pathlib import Path

from merger.repoground.adapters.security import get_security_config

def test_fs_roots_includes_system(service_client):
    res = service_client.client.get("/api/fs/roots", headers=service_client.headers)
    assert res.status_code == 200
    data = res.json()
    roots = data["roots"]
    ids = [r["id"] for r in roots]
    assert "hub" in ids
    assert "system" in ids

    # Verify system path is resolved home
    sys_root = next(r for r in roots if r["id"] == "system")
    assert sys_root["path"] == str(Path.home().resolve())
    # Guaranteed by contract (docs/service-api.md)
    assert "token" in sys_root

def test_create_atlas_system_root(service_client, tmp_path, monkeypatch):
    # Keep the integration test hermetic: the production "system" preset is
    # the real home directory, which can contain hundreds of thousands of
    # entries and previously made the local full suite stall at this test.
    system_root = (tmp_path / "system-root").resolve()
    (system_root / "project" / "nested").mkdir(parents=True)
    (system_root / "project" / "README.md").write_text("small fixture\n", encoding="utf-8")

    security = get_security_config()
    # Mutate a copied list so pytest's monkeypatch restores the exact previous
    # process-global security object after this test.
    monkeypatch.setattr(security, "allowlist_roots", list(security.allowlist_roots))
    monkeypatch.setattr(security, "sensitive_fs_access", security.sensitive_fs_access)
    monkeypatch.setattr(security, "home_preset_root", security.home_preset_root)
    security.add_allowlist_root(system_root)
    security.set_sensitive_fs_access(True, home_preset_root=system_root)

    payload = {
        "root_kind": "preset",
        "root_value": "system",
        "max_depth": 20,  # Must be capped to 6.
        "max_entries": 300000,  # Must be capped to 200000.
    }
    res = service_client.client.post("/api/atlas", json=payload, headers=service_client.headers)
    assert res.status_code == 200
    data = res.json()
    assert data["root_scanned"] == str(system_root)
    assert data["paths"]["json"]

    effective = data["effective"]
    assert effective["max_depth"] == 6
    assert effective["max_entries"] == 200000
    assert "**/.ssh/**" in effective["exclude_globs"]
    assert "**/.password-store/**" in effective["exclude_globs"]
    assert "**/core" in effective["exclude_globs"]
    assert "**/core.[0-9]*" in effective["exclude_globs"]
    assert "**/*.core" in effective["exclude_globs"]

    # TestClient waits for the background task.  Reading the canonical artifact
    # proves the bounded fixture was actually scanned, not merely accepted.
    artifact_path = service_client.merges_dir / data["paths"]["json"]
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert artifact["status"] == "complete"
    assert artifact["root"] == str(system_root)
    assert artifact["stats"]["total_files"] == 1

def test_export_webmaschine_includes_roots(service_client):
    # First create an atlas to ensure export has something to copy
    # (Though it handles missing atlas gracefully)

    res = service_client.client.post("/api/export/webmaschine", headers=service_client.headers)
    assert res.status_code == 200
    export_path = Path(res.json()["path"])

    assert export_path.exists()
    assert (export_path / "README.md").exists()

    # Check machine.json
    machine_json = export_path / "machine.json"
    assert machine_json.exists()

    import json
    with open(machine_json) as f:
        data = json.load(f)
        assert "roots" in data
        assert str(Path.home().resolve()) in data["roots"]
        assert data["hub"] == str(service_client.hub_path)
