import pytest
from fastapi.testclient import TestClient
from fastapi import HTTPException

# Import app logic
from merger.repoground.service.app import app, init_service, state, download_artifact
from merger.repoground.service.models import JobRequest, Artifact
from merger.repoground.adapters.security import get_security_config

client = TestClient(app)

@pytest.fixture
def secure_env(tmp_path):
    """
    Sets up a secure environment with:
    - hub_dir (allowed)
    - allowed_merges (allowed)
    - forbidden_dir (NOT allowed)

    Teardown ensures global state is reset to prevent test pollution.
    """
    hub = tmp_path / "hub"
    hub.mkdir()

    allowed_merges = tmp_path / "allowed_merges"
    allowed_merges.mkdir()

    forbidden = tmp_path / "forbidden"
    forbidden.mkdir()
    (forbidden / "secret.md").write_text("SECRET DATA\n")

    # Initialize service, allowlisting ONLY hub and allowed_merges
    # forbidden is NOT included
    # Explicitly UNSET token to avoid implicit root allowlisting on loopback
    import os
    old_token = os.environ.get("RLENS_TOKEN")
    if "RLENS_TOKEN" in os.environ:
        del os.environ["RLENS_TOKEN"]

    try:
        # Now init service without token in env
        init_service(hub_path=hub, merges_dir=allowed_merges, token=None)

        yield {
            "hub": hub,
            "allowed": allowed_merges,
            "forbidden": forbidden
        }
    finally:
        # Teardown: Reset global state
        state.hub = None
        state.merges_dir = None
        state.job_store = None
        state.runner = None
        state.log_provider = None

        # Restore token if it was set, else ensure it's unset
        os.environ.pop("RLENS_TOKEN", None)
        if old_token is not None:
            os.environ["RLENS_TOKEN"] = old_token

        # Reset Security Config allowlist
        sec = get_security_config()
        roots = getattr(sec, "allowlist_roots", None)
        if hasattr(roots, "clear"):
            roots.clear()
        else:
            sec.allowlist_roots = []
        sec.token = None

def test_download_custom_merges_dir_success(secure_env):
    """
    Test that downloading from an allowed custom merges_dir works.
    """
    # Create file in allowed dir
    target_file = secure_env["allowed"] / "report.md"
    target_file.write_text("Valid Content\n")

    # Mock Artifact with custom merges_dir
    req = JobRequest(repos=["r1"], merges_dir=str(secure_env["allowed"]))
    art = Artifact(
        id="art-ok",
        job_id="job-ok",
        hub=str(secure_env["hub"]),
        repos=["r1"],
        created_at="2023-01-01T00:00:00",
        paths={"md": target_file.name},
        params=req
    )
    state.job_store.add_artifact(art)

    # Act: Direct call
    response = download_artifact(id="art-ok")

    # Assert
    assert str(response.path) == str(target_file)

def test_download_custom_merges_dir_forbidden_http(secure_env):
    """
    Integration Test: Verify via HTTP Client that forbidden dir returns 403.
    """
    # Mock Artifact with FORBIDDEN merges_dir
    req = JobRequest(repos=["r1"], merges_dir=str(secure_env["forbidden"]))
    art_id = "art-bad-http"
    art = Artifact(
        id=art_id,
        job_id="job-bad",
        hub=str(secure_env["hub"]),
        repos=["r1"],
        created_at="2023-01-01T00:00:00",
        paths={"md": "secret.md"},
        params=req
    )
    state.job_store.add_artifact(art)

    # Act: HTTP Request
    # Note: `client` uses the app instance which uses the global `state` we initialized
    response = client.get(f"/api/artifacts/{art_id}/download?key=md")

    # Assert
    assert response.status_code == 403
    assert "Access denied" in response.json()["detail"]

def test_download_symlink_bypass_blocked(secure_env):
    """
    Test that a symlink INSIDE an allowed directory pointing OUTSIDE is blocked (403).
    """
    # Create symlink: allowed/link.md -> forbidden/secret.md
    link_path = secure_env["allowed"] / "link.md"
    target_path = secure_env["forbidden"] / "secret.md"

    try:
        link_path.symlink_to(target_path)
    except OSError:
        pytest.skip("Symlinks not supported on this platform")

    # Mock Artifact: points to valid dir, but file is a symlink
    req = JobRequest(repos=["r1"], merges_dir=str(secure_env["allowed"]))
    art = Artifact(
        id="art-link",
        job_id="job-link",
        hub=str(secure_env["hub"]),
        repos=["r1"],
        created_at="2023-01-01T00:00:00",
        paths={"md": link_path.name},
        params=req
    )
    state.job_store.add_artifact(art)

    # Act & Assert
    with pytest.raises(HTTPException) as exc:
        download_artifact(id="art-link")

    # Should be 403 because validate_path resolves the symlink and sees it's in forbidden root
    assert exc.value.status_code == 403
    assert "Access denied" in exc.value.detail
