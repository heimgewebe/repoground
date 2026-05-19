import os
import sys
import pytest
from pathlib import Path
from unittest.mock import MagicMock

pytestmark = pytest.mark.skipif(os.name != "posix", reason="root policy tests assume POSIX paths")

# --- Mocking for init_service Behavioral Test ---
class MockBaseModel:
    def __init__(self, **kwargs):
        for k, v in kwargs.items(): setattr(self, k, v)
    @classmethod
    def model_rebuild(cls, **kwargs): pass
    @classmethod
    def update_forward_refs(cls, **kwargs): pass

def setup_mocks():
    # Only mock if dependencies are missing (e.g. in minimal CI)
    try:
        import fastapi  # noqa: F401  # presence check
        import pydantic  # noqa: F401  # presence check
    except ImportError:
        m_fastapi = MagicMock()
        sys.modules["fastapi"] = m_fastapi
        sys.modules["fastapi.staticfiles"] = MagicMock()
        sys.modules["fastapi.responses"] = MagicMock()
        sys.modules["fastapi.middleware.cors"] = MagicMock()
        m_pydantic = MagicMock()
        m_pydantic.BaseModel = MockBaseModel
        m_pydantic.Field = lambda *args, **kwargs: MagicMock()
        sys.modules["pydantic"] = m_pydantic
        sys.modules["starlette"] = MagicMock()
        sys.modules["starlette.concurrency"] = MagicMock()

    # Mock heavy service components if not present
    # BUT DO NOT mock merger.lenskit.adapters.security
    sys.modules.setdefault("merger.lenskit.service.jobstore", MagicMock())
    sys.modules.setdefault("merger.lenskit.service.runner", MagicMock())
    sys.modules.setdefault("merger.lenskit.service.logging_provider", MagicMock())
    sys.modules.setdefault("merger.lenskit.service.auth", MagicMock())
    sys.modules.setdefault("merger.lenskit.adapters.atlas", MagicMock())
    sys.modules.setdefault("merger.lenskit.adapters.metarepo", MagicMock())
    sys.modules.setdefault("merger.lenskit.adapters.sources", MagicMock())
    sys.modules.setdefault("merger.lenskit.adapters.diagnostics", MagicMock())
    sys.modules.setdefault("merger.lenskit.core.merge", MagicMock())

setup_mocks()
# Ensure repo root is in path
sys.path.insert(0, os.getcwd())

from merger.lenskit.service.app import init_service
from merger.lenskit.adapters.security import get_security_config

def test_security_config_allowlist_invariant(tmp_path):
    """
    Unit Test: Verify that SecurityConfig enforces boundaries correctly.
    """
    from merger.lenskit.adapters.security import SecurityConfig, AccessDeniedError
    sec = SecurityConfig()
    hub = (tmp_path / "hub").resolve()
    hub.mkdir(parents=True, exist_ok=True)
    repo_dir = hub / "repo"
    repo_dir.mkdir()

    sec.add_allowlist_root(hub)

    # Path inside hub should be allowed
    sec.validate_path(repo_dir)

    # Path outside should be denied
    with pytest.raises(AccessDeniedError):
        sec.validate_path(Path("/etc"))

def _reset_allowlist(sec):
    if not hasattr(sec, "allowlist_roots"):
        pytest.skip("SecurityConfig has no allowlist_roots; cannot assert root policy")
    roots = sec.allowlist_roots
    try:
        roots.clear()
        return
    except Exception:
        pass
    # fallback: replace with empty list
    sec.allowlist_roots = []

def test_init_service_loopback_with_token_allows_root(monkeypatch, tmp_path):
    """
    Behavioral: Loopback + Token -> Root IS allowlisted.
    """
    hub = tmp_path / "hub"
    hub.mkdir()
    sec = get_security_config()
    _reset_allowlist(sec)

    init_service(hub, host="127.0.0.1", token="secret")

    root_path = Path("/").resolve()
    assert root_path in sec.allowlist_roots

def test_init_service_loopback_without_token_refuses_root(monkeypatch, tmp_path):
    """
    Behavioral: Loopback without Token -> Root is NOT allowlisted.
    """
    hub = tmp_path / "hub"
    hub.mkdir()
    sec = get_security_config()
    _reset_allowlist(sec)

    # Ensure no tokens in env
    monkeypatch.delenv("RLENS_TOKEN", raising=False)
    monkeypatch.delenv("RLENS_FS_TOKEN_SECRET", raising=False)

    init_service(hub, host="127.0.0.1", token=None)

    root_path = Path("/").resolve()
    assert root_path not in sec.allowlist_roots

def test_init_service_non_loopback_with_token_refuses_root(monkeypatch, tmp_path):
    """
    Behavioral: Non-loopback + Token -> Root is NOT allowlisted.
    """
    hub = tmp_path / "hub"
    hub.mkdir()
    sec = get_security_config()
    _reset_allowlist(sec)

    init_service(hub, host="192.168.1.1", token="secret")

    root_path = Path("/").resolve()
    assert root_path not in sec.allowlist_roots

def test_static_source_check_app_py():
    app_path = Path("merger/lenskit/service/app.py")
    content = app_path.read_text(encoding="utf-8")

    # Legacy flags should be gone
    assert "RLENS_ALLOW_FS_ROOT" not in content
    assert "RLENS_OPERATOR_MODE" not in content

    # Core Logic Markers should be present
    assert "_is_loopback_host(host)" in content
    assert "has_token" in content
    assert "is_loopback and has_token" in content
    assert "add_allowlist_root(" in content

def test_static_source_check_rlens_cli():
    cli_path = Path("merger/lenskit/cli/rlens.py")
    content = cli_path.read_text(encoding="utf-8")

    # Flags should be gone
    assert "RLENS_ALLOW_FS_ROOT" not in content
    assert "RLENS_OPERATOR_MODE" not in content

    # Notice for non-loopback should be present
    assert "Root browsing will be refused by policy (non-loopback host)" in content

def test_static_source_check_adr():
    adr_path = Path("docs/adr/001-secure-fs-navigation.md")
    content = adr_path.read_text(encoding="utf-8")

    assert "Loopback-Scoped Root Access" in content
    assert "enabled by default only when the service is bound to a loopback interface" in content
    assert "optionally including system root on loopback + auth" in content
