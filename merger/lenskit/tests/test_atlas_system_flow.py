import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from merger.lenskit.service.app import app, init_service, state, verify_token

client = TestClient(app)

@pytest.fixture
def mock_state():
    # Setup mock state
    mock_hub = Path("/tmp/mock_hub")
    mock_hub.mkdir(parents=True, exist_ok=True)
    mock_merges = Path("/tmp/mock_merges")
    mock_merges.mkdir(parents=True, exist_ok=True)

    init_service(hub_path=mock_hub, merges_dir=mock_merges, token="test-token")
    app.dependency_overrides[verify_token] = lambda: True

    # Mock Security Config
    with patch("merger.lenskit.service.app.get_security_config") as mock_get_sec:
        mock_sec_instance = MagicMock()
        mock_sec_instance.validate_path.side_effect = lambda p: p # Pass through
        mock_get_sec.return_value = mock_sec_instance

        yield state

    # Cleanup
    app.dependency_overrides.pop(verify_token, None)
    import shutil
    shutil.rmtree(mock_hub, ignore_errors=True)
    shutil.rmtree(mock_merges, ignore_errors=True)

def test_atlas_system_root_mapping(mock_state):
    """
    Verify that root_kind="preset" with root_value="system" maps to Path.home() in the application logic.
    Note: This tests the mapping logic. The actual path security policy is mocked here
    to focus on the 'system' keyword handling.
    """
    # We need to bypass the actual AtlasScanner execution since it scans real files
    with patch("merger.lenskit.service.app.AtlasScanner") as MockScanner:
        with patch("merger.lenskit.service.app.render_atlas_md") as mock_render:
            mock_instance = MockScanner.return_value
            mock_instance.scan.return_value = {"root": str(Path.home()), "tree": {}}
            mock_render.return_value = "Mock MD"

            payload = {
                "root_kind": "preset",
                "root_value": "system",
                "max_depth": 1,
                "max_entries": 100
            }

            response = client.post("/api/atlas", json=payload)

            assert response.status_code == 200
            data = response.json()
            assert data["id"].startswith("atlas-")

            # The API returns the RESOLVED path in root_scanned
            # We expect it to be user home
            expected_home = str(Path.home().resolve())
            assert data["root_scanned"] == expected_home

def test_atlas_missing_root_422(mock_state):
    """
    Verify that missing root_kind or invalid schema returns 422
    """
    payload = {
        "max_depth": 1
    }

    response = client.post("/api/atlas", json=payload)
    # Pydantic validation fails because root_kind is required
    assert response.status_code == 422

def test_atlas_legacy_only_422(mock_state):
    """
    Verify that providing only deprecated legacy fields (e.g. root_id)
    fails validation because root_kind is required.
    """
    payload = {
        "root_id": "system",
        "max_depth": 1
    }

    response = client.post("/api/atlas", json=payload)
    assert response.status_code == 422

def test_atlas_missing_root_value_400(mock_state):
    """
    Verify that missing root_value when root_kind="preset" returns 400
    """
    payload = {
        "root_kind": "preset",
        "max_depth": 1
    }

    response = client.post("/api/atlas", json=payload)
    assert response.status_code == 400
    assert "root_value is required" in response.json()["detail"]

def test_atlas_invalid_preset(mock_state):
    """
    Verify that invalid preset returns 400
    """
    payload = {
        "root_kind": "preset",
        "root_value": "invalid_root",
        "max_depth": 1
    }

    response = client.post("/api/atlas", json=payload)
    assert response.status_code == 400
    assert "Invalid preset" in response.json()["detail"]

def test_atlas_abs_path_success(mock_state):
    """
    Verify that absolute path works when root_kind="abs_path"
    """
    with patch("merger.lenskit.service.app.AtlasScanner") as MockScanner:
        with patch("merger.lenskit.service.app.render_atlas_md") as mock_render:
            mock_instance = MockScanner.return_value
            abs_path = str(Path("/tmp").resolve())
            mock_instance.scan.return_value = {"root": abs_path, "tree": {}}
            mock_render.return_value = "Mock MD"

            payload = {
                "root_kind": "abs_path",
                "root_value": abs_path,
                "max_depth": 1,
                "max_entries": 100
            }

            response = client.post("/api/atlas", json=payload)

            assert response.status_code == 200
            data = response.json()
            assert data["id"].startswith("atlas-")
            assert data["root_scanned"] == abs_path

def test_atlas_abs_path_relative_fails(mock_state):
    """
    Verify that relative paths fail when root_kind="abs_path"
    """
    payload = {
        "root_kind": "abs_path",
        "root_value": "relative/path/here",
        "max_depth": 1
    }

    response = client.post("/api/atlas", json=payload)
    assert response.status_code == 400
    assert "Invalid absolute path" in response.json()["detail"]
