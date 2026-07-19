import pytest
from pathlib import Path
import json
from fastapi.testclient import TestClient

from merger.repoground.service.app import app, init_service, verify_token

@pytest.fixture
def lifecycle_client(tmp_path: Path):
    # Setup test directories
    hub = tmp_path / "hub"
    merges = hub / ".repoground" / "merges"
    merges.mkdir(parents=True)

    # Create test artifacts in reverse chronological order
    # Oldest: Failed
    failed_data = {
        "status": "failed",
        "root": "/test",
        "created_at": "2024-01-01T10:00:00Z",
        "error": "Failed early"
    }
    (merges / "atlas-1000.json").write_text(json.dumps(failed_data), encoding="utf-8")

    # Middle: Complete
    completed_data = {
        "status": "complete",
        "root": "/test",
        "created_at": "2024-01-02T10:00:00Z",
        "stats": {"total_files": 1}
    }
    (merges / "atlas-2000.json").write_text(json.dumps(completed_data), encoding="utf-8")
    (merges / "atlas-2000.md").write_text("# Report", encoding="utf-8")
    (merges / "atlas-2000.inventory.jsonl").write_text('{"rel_path": "file1.txt"}', encoding="utf-8")
    (merges / "atlas-2000.dirs_inventory.jsonl").write_text('{"rel_path": "dir1"}', encoding="utf-8")

    # Newest: Running
    running_data = {
        "status": "running",
        "root": "/test",
        "created_at": "2024-01-03T10:00:00Z"
    }
    (merges / "atlas-3000.json").write_text(json.dumps(running_data), encoding="utf-8")

    # Snapshot middleware to prevent global test suite contamination
    orig_middleware = list(app.user_middleware)
    orig_stack = app.middleware_stack

    # Reset FastAPI middleware stack explicitly BEFORE init_service
    app.middleware_stack = None
    app.user_middleware.clear()

    init_service(hub_path=hub, merges_dir=merges)

    app.dependency_overrides[verify_token] = lambda: True
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        app.user_middleware = orig_middleware
        app.middleware_stack = orig_stack

def test_list_all_artifacts(lifecycle_client: TestClient):
    response = lifecycle_client.get("/api/atlas")
    assert response.status_code == 200

    data = response.json()
    assert len(data) == 3

    # Verify sorting: newest first (atlas-3000 -> 2000 -> 1000)
    assert data[0]["id"] == "atlas-3000"
    assert data[0]["status"] == "running"

    assert data[1]["id"] == "atlas-2000"
    assert data[1]["status"] == "complete"
    assert "dirs_inventory" in data[1]["paths"]
    assert data[1]["paths"]["dirs_inventory"] == "atlas-2000.dirs_inventory.jsonl"

    assert data[2]["id"] == "atlas-1000"
    assert data[2]["status"] == "failed"
    assert data[2]["error"] == "Failed early"

def test_get_latest_artifact_ignores_running_and_failed(lifecycle_client: TestClient):
    response = lifecycle_client.get("/api/atlas/latest")
    assert response.status_code == 200

    data = response.json()

    # Must skip 'atlas-3000' (running) and return 'atlas-2000' (complete)
    assert data["id"] == "atlas-2000"
    assert data["status"] == "complete"
    assert "dirs_inventory" in data["paths"]
    assert data["paths"]["dirs_inventory"] == "atlas-2000.dirs_inventory.jsonl"

def test_download_dirs_inventory(lifecycle_client: TestClient):
    response = lifecycle_client.get("/api/atlas/atlas-2000/download?key=dirs_inventory")
    assert response.status_code == 200
    assert response.text == '{"rel_path": "dir1"}'

    # check that content-disposition exists and matches the expected filename pattern roughly
    # the client just returns the file response, starlette adds disposition if filename provided
    cd = response.headers.get("content-disposition", "")
    assert "atlas-2000.dirs_inventory.jsonl" in cd

def test_get_latest_artifact_404_if_none_completed(tmp_path: Path):
    # Setup hub with NO completed artifacts
    hub = tmp_path / "hub2"
    merges = hub / ".repoground" / "merges"
    merges.mkdir(parents=True)

    running_data = {
        "status": "running",
        "root": "/test",
        "created_at": "2024-01-03T10:00:00Z"
    }
    (merges / "atlas-3000.json").write_text(json.dumps(running_data), encoding="utf-8")

    orig_middleware = list(app.user_middleware)
    orig_stack = app.middleware_stack

    app.middleware_stack = None
    app.user_middleware.clear()

    init_service(hub_path=hub, merges_dir=merges)

    app.dependency_overrides[verify_token] = lambda: True
    try:
        with TestClient(app) as client:
            response = client.get("/api/atlas/latest")
            assert response.status_code == 404
            assert "No complete atlas artifacts found" in response.json()["detail"]
    finally:
        app.dependency_overrides.clear()
        app.user_middleware = orig_middleware
        app.middleware_stack = orig_stack


def test_legacy_completed_status_normalized_in_list(tmp_path: Path):
    """Artifacts with legacy status 'completed' are normalized to 'complete' by list_atlas()."""
    hub = tmp_path / "hub_legacy"
    merges = hub / ".repoground" / "merges"
    merges.mkdir(parents=True)

    # Legacy artifact uses "completed" (old vocabulary)
    legacy_data = {
        "status": "completed",
        "root": "/legacy",
        "created_at": "2023-06-15T08:00:00Z",
        "stats": {"total_files": 42}
    }
    (merges / "atlas-500.json").write_text(json.dumps(legacy_data), encoding="utf-8")

    orig_middleware = list(app.user_middleware)
    orig_stack = app.middleware_stack
    app.middleware_stack = None
    app.user_middleware.clear()

    init_service(hub_path=hub, merges_dir=merges)
    app.dependency_overrides[verify_token] = lambda: True
    try:
        with TestClient(app) as client:
            response = client.get("/api/atlas")
            assert response.status_code == 200
            data = response.json()
            assert len(data) == 1
            # Must be normalized to "complete", not "completed"
            assert data[0]["status"] == "complete"
    finally:
        app.dependency_overrides.clear()
        app.user_middleware = orig_middleware
        app.middleware_stack = orig_stack


def test_legacy_completed_status_found_by_get_latest(tmp_path: Path):
    """get_latest_atlas() recognizes legacy 'completed' artifacts as valid complete scans."""
    hub = tmp_path / "hub_legacy2"
    merges = hub / ".repoground" / "merges"
    merges.mkdir(parents=True)

    # Only a legacy "completed" artifact exists — should be found by get_latest
    legacy_data = {
        "status": "completed",
        "root": "/old-scan",
        "created_at": "2023-01-01T00:00:00Z",
        "stats": {"total_files": 7}
    }
    (merges / "atlas-100.json").write_text(json.dumps(legacy_data), encoding="utf-8")

    orig_middleware = list(app.user_middleware)
    orig_stack = app.middleware_stack
    app.middleware_stack = None
    app.user_middleware.clear()

    init_service(hub_path=hub, merges_dir=merges)
    app.dependency_overrides[verify_token] = lambda: True
    try:
        with TestClient(app) as client:
            response = client.get("/api/atlas/latest")
            assert response.status_code == 200
            data = response.json()
            assert data["id"] == "atlas-100"
            assert data["status"] == "complete"
    finally:
        app.dependency_overrides.clear()
        app.user_middleware = orig_middleware
        app.middleware_stack = orig_stack
