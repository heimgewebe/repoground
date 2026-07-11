from pathlib import Path
import shutil
import sys
import tempfile

import pytest


def pytest_collection_modifyitems(config, items):
    """Skip browser-marked tests when pytest-playwright is not installed.

    The `browser` marker (see pytest.ini) covers WebUI tests that need the
    playwright `page` fixture. Without this hook, a runtime that lacks
    pytest-playwright (for example the core development lock without the
    separate browser lock)
    reports hard fixture errors instead of skips.
    """
    if config.pluginmanager.hasplugin("playwright"):
        return
    skip_browser = pytest.mark.skip(
        reason=(
            "pytest-playwright not installed "
            "(see requirements/repobrief-browser.lock.txt)"
        )
    )
    for item in items:
        if "browser" in item.keywords:
            item.add_marker(skip_browser)


@pytest.fixture
def no_jsonschema(monkeypatch):
    """Simulate an environment where importing jsonschema fails."""
    monkeypatch.setitem(sys.modules, "jsonschema", None)


@pytest.fixture
def service_client():
    # Split imports to handle missing fastapi dependency gracefully (skip)
    # but allow broken service code to fail tests (no try/except)
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        pytest.skip("FastAPI not installed (required for service tests)")

    # Canonical imports - if this fails, the test should fail (broken code)
    from merger.lenskit.service.app import app, init_service, state

    # Fastapi doesn't allow adding middleware after app has started, and init_service does this.
    # To cleanly test without polluting app.py, we reset the middleware stack for the fixture.
    app.middleware_stack = None

    # Setup
    temp_dir = tempfile.mkdtemp()
    hub_path = Path(temp_dir) / "hub"
    hub_path.mkdir()
    merges_dir = hub_path / "merges"
    merges_dir.mkdir()

    # Create a dummy repo for scanning
    (hub_path / "repo-test").mkdir()
    (hub_path / "repo-test" / "README.md").write_text("Test Content")

    token = "test-token-123"

    # Ensure FS token secret is available for tests
    import os
    os.environ["RLENS_TOKEN"] = token

    # Initialize service with explicit token and merges_dir
    init_service(hub_path, token=token, merges_dir=merges_dir)

    client = TestClient(app)
    auth_headers = {"Authorization": f"Bearer {token}"}

    # Expose useful objects
    class Context:
        def __init__(self):
            self.client = client
            self.headers = auth_headers
            self.store = state.job_store
            self.hub_path = hub_path
            self.merges_dir = merges_dir
            self.runner = state.runner

    ctx = Context()

    yield ctx

    # Teardown
    shutil.rmtree(temp_dir, ignore_errors=True)
