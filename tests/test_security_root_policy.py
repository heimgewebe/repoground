import json
import logging
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

        # In a dependency-minimal environment, mock the service's heavy
        # imports as a group. When FastAPI/Pydantic are available, import the
        # real modules: process-global MagicMocks would contaminate later tests
        # in the same pytest session.
        # BUT DO NOT mock merger.repoground.adapters.security.
        sys.modules.setdefault("merger.repoground.service.jobstore", MagicMock())
        sys.modules.setdefault("merger.repoground.service.runner", MagicMock())
        sys.modules.setdefault("merger.repoground.service.logging_provider", MagicMock())
        sys.modules.setdefault("merger.repoground.service.auth", MagicMock())
        sys.modules.setdefault("merger.repoground.adapters.atlas", MagicMock())
        sys.modules.setdefault("merger.repoground.adapters.metarepo", MagicMock())
        sys.modules.setdefault("merger.repoground.adapters.sources", MagicMock())
        sys.modules.setdefault("merger.repoground.adapters.diagnostics", MagicMock())
        sys.modules.setdefault("merger.repoground.core.merge", MagicMock())

setup_mocks()
# Ensure repo root is in path
sys.path.insert(0, os.getcwd())

from merger.repoground.service.app import app, init_service, resolve_atlas_root
from merger.repoground.service.models import AtlasRequest
from merger.repoground.adapters.security import get_security_config, AccessDeniedError
from merger.repoground.adapters.filesystem import list_allowed_roots, resolve_fs_path
from fastapi import HTTPException
from fastapi.testclient import TestClient

def test_security_config_allowlist_invariant(tmp_path):
    """
    Unit Test: Verify that SecurityConfig enforces boundaries correctly.
    """
    from merger.repoground.adapters.security import SecurityConfig, AccessDeniedError
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

def test_sensitive_home_preset_must_already_be_allowlisted(tmp_path):
    from merger.repoground.adapters.security import SecurityConfig

    sec = SecurityConfig()
    untrusted_home = (tmp_path / "untrusted-home").resolve()

    with pytest.raises(
        ValueError,
        match="Home preset root must be allowlisted before activation",
    ):
        sec.set_sensitive_fs_access(True, home_preset_root=untrusted_home)

    assert sec.sensitive_fs_access is False
    assert sec.home_preset_root is None


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
    home_path = Path.home().resolve()
    assert root_path in sec.allowlist_roots
    assert home_path in sec.allowlist_roots
    assert sec.sensitive_fs_access is True

def test_init_service_home_resolution_failure_degrades_to_root_only(
    monkeypatch, tmp_path, caplog
):
    """An unavailable Home preset must not abort authenticated root access."""
    hub = tmp_path / "hub"
    hub.mkdir()
    sec = get_security_config()
    _reset_allowlist(sec)

    def fail_home():
        raise RuntimeError("synthetic home lookup failure")

    monkeypatch.setattr(Path, "home", fail_home)
    with caplog.at_level(logging.WARNING):
        init_service(hub, host="127.0.0.1", token="secret")

    assert Path("/").resolve() in sec.allowlist_roots
    assert sec.sensitive_fs_access is True
    assert sec.home_preset_root is None
    assert {entry["id"] for entry in list_allowed_roots(hub, None)} == {"hub"}
    assert "Home preset unavailable" in caplog.text
    assert "root only" in caplog.text

    with pytest.raises(HTTPException) as exc_info:
        resolve_fs_path(hub=hub, merges_dir=None, root_id="system", rel_path="")

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == (
        "Home preset is unavailable in this service configuration"
    )

    with pytest.raises(HTTPException) as atlas_exc:
        resolve_atlas_root(
            AtlasRequest(root_kind="preset", root_value="system"),
            hub,
            None,
        )
    assert atlas_exc.value.status_code == 503

    root_request = AtlasRequest(root_kind="abs_path", root_value=str(Path("/")))
    assert resolve_atlas_root(root_request, hub, None).scan_root == Path("/").resolve()

    with TestClient(app) as client:
        response = client.get(
            "/api/fs/list",
            params={"root": "system", "rel": ""},
            headers={"Authorization": "Bearer secret"},
        )
    assert response.status_code == 503
    assert response.json() == {
        "detail": "Home preset is unavailable in this service configuration"
    }

    with TestClient(app) as client:
        export_response = client.post(
            "/api/export/webmaschine",
            headers={"Authorization": "Bearer secret"},
        )
    assert export_response.status_code == 200
    machine_path = Path(export_response.json()["path"]) / "machine.json"
    machine = json.loads(machine_path.read_text(encoding="utf-8"))
    assert machine["roots"] == []


def test_list_allowed_roots_preserves_explicit_roots_on_home_io_failure(
    monkeypatch, tmp_path
):
    """An optional cached Home failure must not hide Hub or Merges roots."""
    hub = tmp_path / "hub"
    merges = tmp_path / "merges"
    fake_home = tmp_path / "service-home"
    hub.mkdir()
    merges.mkdir()
    fake_home.mkdir()

    monkeypatch.setattr(Path, "home", lambda: fake_home)
    init_service(hub, host="127.0.0.1", token="secret")
    sec = get_security_config()
    original_validate = sec.validate_path

    def fail_cached_home(path):
        if path == sec.home_preset_root:
            raise OSError("synthetic cached Home I/O failure")
        return original_validate(path)

    monkeypatch.setattr(sec, "validate_path", fail_cached_home)

    roots = list_allowed_roots(hub, merges)
    assert roots == [
        {"id": "hub", "path": str(hub.resolve())},
        {"id": "merges", "path": str(merges.resolve())},
    ]


def test_init_service_home_registration_failure_degrades_to_root_only(
    monkeypatch, tmp_path
):
    """A rejected Home registration must not leave a stale preset path active."""
    hub = tmp_path / "hub"
    fake_home = tmp_path / "service-home"
    hub.mkdir()
    fake_home.mkdir()
    sec = get_security_config()
    _reset_allowlist(sec)
    original_add_root = sec.add_allowlist_root

    monkeypatch.setattr(Path, "home", lambda: fake_home)

    def reject_home(path):
        if path == fake_home.resolve():
            raise ValueError("synthetic Home registration failure")
        original_add_root(path)

    monkeypatch.setattr(sec, "add_allowlist_root", reject_home)
    init_service(hub, host="127.0.0.1", token="secret")

    assert Path("/").resolve() in sec.allowlist_roots
    assert fake_home.resolve() not in sec.allowlist_roots
    assert sec.sensitive_fs_access is True
    assert sec.home_preset_root is None
    assert {entry["id"] for entry in list_allowed_roots(hub, None)} == {"hub"}


def test_init_service_root_registration_failure_is_explicit_and_fail_closed(
    monkeypatch, tmp_path
):
    """A failed reinit must revoke every earlier sensitive grant."""
    previous_hub = tmp_path / "previous-hub"
    hub = tmp_path / "hub"
    previous_hub.mkdir()
    hub.mkdir()
    sec = get_security_config()
    _reset_allowlist(sec)
    root = Path("/").resolve()
    home = Path.home().resolve()

    init_service(previous_hub, host="127.0.0.1", token="secret")
    assert sec.sensitive_fs_access is True
    assert sec.home_preset_root == home

    original_add_root = sec.add_allowlist_root

    def reject_root(path):
        if path == root:
            raise ValueError("synthetic root registration failure")
        original_add_root(path)

    monkeypatch.setattr(sec, "add_allowlist_root", reject_root)

    with pytest.raises(
        RuntimeError,
        match="Authenticated filesystem-root access could not be initialized",
    ):
        init_service(hub, host="127.0.0.1", token="secret")

    assert sec.sensitive_fs_access is False
    assert sec.home_preset_root is None
    assert root not in sec.allowlist_roots
    assert home not in sec.allowlist_roots
    assert previous_hub.resolve() not in sec.allowlist_roots
    assert sec.allowlist_roots == [hub.resolve()]


def test_home_preset_uses_startup_resolved_path_without_recomputing(
    monkeypatch, tmp_path
):
    """Later Home lookup failures must not invalidate a successful startup grant."""
    hub = tmp_path / "hub"
    fake_home = tmp_path / "service-home"
    hub.mkdir()
    fake_home.mkdir()

    monkeypatch.setattr(Path, "home", lambda: fake_home)
    init_service(hub, host="127.0.0.1", token="secret")
    sec = get_security_config()
    assert sec.home_preset_root == fake_home.resolve()

    def fail_home():
        raise RuntimeError("Home must not be recomputed after startup")

    monkeypatch.setattr(Path, "home", fail_home)

    roots = list_allowed_roots(hub, None)
    system = next(entry for entry in roots if entry["id"] == "system")
    assert system["path"] == str(fake_home.resolve())
    trusted = resolve_fs_path(
        hub=hub,
        merges_dir=None,
        root_id="system",
        rel_path="",
    )
    assert trusted.path == fake_home.resolve()


def test_init_service_loopback_without_token_refuses_root(monkeypatch, tmp_path):
    """
    Behavioral: Loopback without Token -> Root is NOT allowlisted.
    """
    hub = tmp_path / "hub"
    hub.mkdir()
    sec = get_security_config()
    _reset_allowlist(sec)

    # Ensure no tokens in env
    monkeypatch.delenv("REPOGROUND_TOKEN", raising=False)
    monkeypatch.delenv("REPOGROUND_FS_TOKEN_SECRET", raising=False)

    init_service(hub, host="127.0.0.1", token=None)

    root_path = Path("/").resolve()
    home_path = Path.home().resolve()
    assert root_path not in sec.allowlist_roots
    assert home_path not in sec.allowlist_roots
    assert sec.sensitive_fs_access is False

    roots = list_allowed_roots(hub, None)
    assert {entry["id"] for entry in roots} == {"hub"}
    with pytest.raises(AccessDeniedError):
        resolve_fs_path(hub=hub, merges_dir=None, root_id="system", rel_path="")

def test_system_alias_requires_capability_not_only_path_allowlist(tmp_path):
    hub = tmp_path / "hub"
    hub.mkdir()
    init_service(hub, host="127.0.0.1", token=None)
    sec = get_security_config()

    # Simulate an explicitly configured root that happens to include Home.
    # That must not silently mint the broader `system` capability.
    sec.add_allowlist_root(Path.home().resolve())

    roots = list_allowed_roots(hub, None)
    assert "system" not in {entry["id"] for entry in roots}
    with pytest.raises(AccessDeniedError):
        resolve_fs_path(hub=hub, merges_dir=None, root_id="system", rel_path="")


def test_atlas_abs_path_cannot_bypass_sensitive_root_policy(tmp_path):
    hub = tmp_path / "hub"
    hub.mkdir()
    init_service(hub, host="127.0.0.1", token=None)

    request = AtlasRequest(root_kind="abs_path", root_value=str(Path.home().resolve()))

    with pytest.raises(AccessDeniedError):
        resolve_atlas_root(request, hub, None)


def test_atlas_abs_path_rejects_symlink_escape_from_hub(tmp_path):
    hub = tmp_path / "hub"
    outside = tmp_path / "outside"
    hub.mkdir()
    outside.mkdir()
    escape = hub / "escape"
    escape.symlink_to(outside, target_is_directory=True)
    init_service(hub, host="127.0.0.1", token=None)

    request = AtlasRequest(root_kind="abs_path", root_value=str(escape))

    with pytest.raises(AccessDeniedError):
        resolve_atlas_root(request, hub, None)


def test_atlas_abs_path_allows_symlink_that_stays_inside_hub(tmp_path):
    hub = tmp_path / "hub"
    target = hub / "target"
    target.mkdir(parents=True)
    alias = hub / "alias"
    alias.symlink_to(target, target_is_directory=True)
    init_service(hub, host="127.0.0.1", token=None)

    request = AtlasRequest(root_kind="abs_path", root_value=str(alias))
    resolved = resolve_atlas_root(request, hub, None)

    assert resolved.scan_root == target.resolve()


def test_atlas_abs_path_rejects_parent_components_before_resolution(tmp_path):
    hub = tmp_path / "hub"
    outside = tmp_path / "outside"
    hub.mkdir()
    outside.mkdir()
    init_service(hub, host="127.0.0.1", token=None)

    request = AtlasRequest(
        root_kind="abs_path",
        root_value=str(hub / ".." / outside.name),
    )

    with pytest.raises(HTTPException) as exc_info:
        resolve_atlas_root(request, hub, None)

    assert exc_info.value.status_code == 400
    assert "Path traversal not allowed" in exc_info.value.detail


def test_fs_roots_api_omits_system_without_auth(tmp_path, monkeypatch):
    hub = tmp_path / "hub"
    hub.mkdir()
    monkeypatch.setenv("REPOGROUND_FS_TOKEN_SECRET", "synthetic-fs-signing-secret")
    init_service(hub, host="127.0.0.1", token=None)

    with TestClient(app) as client:
        response = client.get("/api/fs/roots")

    assert response.status_code == 200
    roots = response.json()["roots"]
    assert {entry["id"] for entry in roots} == {"hub"}
    assert all(entry["token"] for entry in roots)


def test_atlas_api_rejects_home_abs_path_without_auth(tmp_path):
    hub = tmp_path / "hub"
    hub.mkdir()
    init_service(hub, host="127.0.0.1", token=None)

    with TestClient(app) as client:
        response = client.post(
            "/api/atlas",
            json={
                "root_kind": "abs_path",
                "root_value": str(Path.home().resolve()),
            },
        )

    assert response.status_code == 403


def test_atlas_abs_path_within_hub_remains_available_without_auth(tmp_path):
    hub = tmp_path / "hub"
    child = hub / "project"
    child.mkdir(parents=True)
    init_service(hub, host="127.0.0.1", token=None)

    request = AtlasRequest(root_kind="abs_path", root_value=str(child))
    resolved = resolve_atlas_root(request, hub, None)

    assert resolved.scan_root == child.resolve()


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
    home_path = Path.home().resolve()
    assert root_path not in sec.allowlist_roots
    assert home_path not in sec.allowlist_roots

def test_init_service_replaces_previous_allowlist_configuration(tmp_path):
    """Reinitialization must revoke roots belonging to the previous hub."""
    first_hub = tmp_path / "first-hub"
    second_hub = tmp_path / "second-hub"
    first_hub.mkdir()
    second_hub.mkdir()
    sec = get_security_config()
    _reset_allowlist(sec)

    init_service(first_hub, host="127.0.0.1", token=None)
    assert first_hub.resolve() in sec.allowlist_roots

    init_service(second_hub, host="127.0.0.1", token=None)
    assert first_hub.resolve() not in sec.allowlist_roots
    assert second_hub.resolve() in sec.allowlist_roots


def test_init_service_removes_stale_root_when_auth_is_disabled(tmp_path):
    """A prior authenticated init must not leave root enabled after auth is removed."""
    hub = tmp_path / "hub"
    hub.mkdir()
    sec = get_security_config()
    _reset_allowlist(sec)

    init_service(hub, host="127.0.0.1", token="secret")
    assert Path("/").resolve() in sec.allowlist_roots

    init_service(hub, host="127.0.0.1", token=None)
    assert Path("/").resolve() not in sec.allowlist_roots
    assert Path.home().resolve() not in sec.allowlist_roots
    assert sec.home_preset_root is None
    assert hub.resolve() in sec.allowlist_roots


def test_init_service_removes_stale_root_when_binding_becomes_non_loopback(tmp_path):
    """Changing to a non-loopback bind must revoke an earlier root grant."""
    hub = tmp_path / "hub"
    hub.mkdir()
    sec = get_security_config()
    _reset_allowlist(sec)

    init_service(hub, host="127.0.0.1", token="secret")
    assert Path("/").resolve() in sec.allowlist_roots

    init_service(hub, host="192.168.1.1", token="secret")
    assert Path("/").resolve() not in sec.allowlist_roots


def test_init_service_fs_token_secret_without_bearer_refuses_root(monkeypatch, tmp_path):
    """
    Regression: REPOGROUND_FS_TOKEN_SECRET signs FS download tokens but does NOT
    enable bearer auth. On its own it must not widen the jail to system root,
    otherwise root browsing would be reachable with auth effectively disabled.
    Invariant: root allowlisted <=> verify_token is actually enforced.
    """
    hub = tmp_path / "hub"
    hub.mkdir()
    sec = get_security_config()
    _reset_allowlist(sec)
    sec.set_token(None)

    monkeypatch.delenv("REPOGROUND_TOKEN", raising=False)
    monkeypatch.setenv("REPOGROUND_FS_TOKEN_SECRET", "fs-signing-secret")

    init_service(hub, host="127.0.0.1", token=None)

    root_path = Path("/").resolve()
    assert root_path not in sec.allowlist_roots
    assert Path.home().resolve() not in sec.allowlist_roots
    # Auth is not active (no bearer token), so sensitive roots remain refused.
    assert not sec.token

def test_static_source_check_app_py():
    app_path = Path("merger/repoground/service/app.py")
    content = app_path.read_text(encoding="utf-8")

    # Legacy flags should be gone
    assert "REPOGROUND_ALLOW_FS_ROOT" not in content
    assert "REPOGROUND_OPERATOR_MODE" not in content

    # Core Logic Markers should be present
    assert "_is_loopback_host(host)" in content
    assert "has_token" in content
    assert "is_loopback and has_token" in content
    assert "add_allowlist_root(" in content

def test_static_source_check_service_cli():
    cli_path = Path("merger/repoground/cli/serve.py")
    content = cli_path.read_text(encoding="utf-8")

    # Flags should be gone
    assert "REPOGROUND_ALLOW_FS_ROOT" not in content
    assert "REPOGROUND_OPERATOR_MODE" not in content

    # Notice for non-loopback should be present
    assert "Home and root browsing will be refused by policy (non-loopback host)" in content
    assert "Home and root browsing are disabled without bearer authentication" in content

def test_static_source_check_adr():
    adr_path = Path("docs/adr/001-secure-fs-navigation.md")
    content = adr_path.read_text(encoding="utf-8")

    assert "Loopback- and Auth-Scoped Sensitive Access" in content
    assert "home directory (`system`) or the filesystem root (`/`)" in content
    assert "only the explicitly configured Hub and merges directory are allowlisted" in content
    assert "does not activate bearer authentication" in content
    assert "cannot authorize sensitive filesystem browsing" in content
    assert "other local processes or users" in content
