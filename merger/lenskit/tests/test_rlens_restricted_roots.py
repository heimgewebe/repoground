"""
Tests for the restricted root policy (Gate 4b).
"""
import pytest
from fastapi.testclient import TestClient
from pathlib import Path
import tempfile

import merger.lenskit.service.app as service_app
from merger.lenskit.adapters.security import (
    get_security_config,
    SecurityConfig,
    AccessDeniedError,
)
from merger.lenskit.adapters.filesystem import list_allowed_roots


@pytest.fixture(autouse=True)
def reset_security_config():
    sec = get_security_config()
    sec.root_policy = "default"
    sec.allowlist_roots = []
    sec.token = None
    yield


def _make_client_and_hub(root_policy="default", token="test-token",
                         hub_dir=None, allowed_roots=None):
    if hub_dir is None:
        hub_dir = Path(tempfile.mkdtemp())
        (hub_dir / "repo1").mkdir(exist_ok=True)
    sec = get_security_config()
    sec.root_policy = "default"
    sec.allowlist_roots = []
    sec.token = None
    # Set env so FS token generation works (used by /api/fs/roots)
    import os
    old_token = os.environ.get("RLENS_TOKEN")
    os.environ["RLENS_TOKEN"] = token
    try:
        service_app.init_service(
            hub_path=hub_dir, token=token, host="127.0.0.1",
            root_policy=root_policy, allowed_roots=allowed_roots,
        )
        with TestClient(service_app.app) as client:
            yield client, str(hub_dir.resolve())
    finally:
        if old_token is None:
            os.environ.pop("RLENS_TOKEN", None)
        else:
            os.environ["RLENS_TOKEN"] = old_token


class TestRestrictedRootPolicy:
    def test_restricted_rejects_home(self):
        sec = SecurityConfig()
        sec.set_root_policy("restricted")
        with pytest.raises(ValueError, match="forbidden"):
            sec.add_allowlist_root(Path.home())

    def test_restricted_rejects_root(self):
        sec = SecurityConfig()
        sec.set_root_policy("restricted")
        with pytest.raises(ValueError, match="forbidden"):
            sec.add_allowlist_root(Path("/"))

    def test_restricted_rejects_etc(self):
        sec = SecurityConfig()
        sec.set_root_policy("restricted")
        with pytest.raises(ValueError, match="forbidden"):
            sec.add_allowlist_root(Path("/etc"))

    def test_restricted_rejects_var(self):
        sec = SecurityConfig()
        sec.set_root_policy("restricted")
        with pytest.raises(ValueError, match="forbidden"):
            sec.add_allowlist_root(Path("/var"))

    def test_restricted_rejects_proc(self):
        sec = SecurityConfig()
        sec.set_root_policy("restricted")
        with pytest.raises(ValueError, match="forbidden"):
            sec.add_allowlist_root(Path("/proc"))

    def test_restricted_rejects_sys(self):
        sec = SecurityConfig()
        sec.set_root_policy("restricted")
        with pytest.raises(ValueError, match="forbidden"):
            sec.add_allowlist_root(Path("/sys"))

    def test_restricted_rejects_dev(self):
        sec = SecurityConfig()
        sec.set_root_policy("restricted")
        with pytest.raises(ValueError, match="forbidden"):
            sec.add_allowlist_root(Path("/dev"))

    def test_restricted_rejects_run(self):
        sec = SecurityConfig()
        sec.set_root_policy("restricted")
        with pytest.raises(ValueError, match="forbidden"):
            sec.add_allowlist_root(Path("/run"))

    def test_restricted_rejects_tmp(self):
        sec = SecurityConfig()
        sec.set_root_policy("restricted")
        with pytest.raises(ValueError, match="forbidden"):
            sec.add_allowlist_root(Path("/tmp"))

    def test_restricted_rejects_ssh_in_path(self):
        sec = SecurityConfig()
        sec.set_root_policy("restricted")
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / ".ssh"
            p.mkdir(exist_ok=True)
            with pytest.raises(ValueError, match="forbidden component"):
                sec.add_allowlist_root(p)

    def test_restricted_rejects_gnupg_in_path(self):
        sec = SecurityConfig()
        sec.set_root_policy("restricted")
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / ".gnupg"
            p.mkdir(exist_ok=True)
            with pytest.raises(ValueError, match="forbidden component"):
                sec.add_allowlist_root(p)

    def test_restricted_rejects_env_in_path(self):
        sec = SecurityConfig()
        sec.set_root_policy("restricted")
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / ".env"
            p.mkdir(exist_ok=True)
            with pytest.raises(ValueError, match="forbidden component"):
                sec.add_allowlist_root(p)

    def test_restricted_rejects_pem_suffix(self):
        sec = SecurityConfig()
        sec.set_root_policy("restricted")
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "cert.pem"
            p.touch(exist_ok=True)
            with pytest.raises(ValueError, match="forbidden suffix"):
                sec.add_allowlist_root(p)

    def test_restricted_rejects_key_suffix(self):
        sec = SecurityConfig()
        sec.set_root_policy("restricted")
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "private.key"
            p.touch(exist_ok=True)
            with pytest.raises(ValueError, match="forbidden suffix"):
                sec.add_allowlist_root(p)

    def test_restricted_accepts_safe_root(self):
        sec = SecurityConfig()
        sec.set_root_policy("restricted")
        with tempfile.TemporaryDirectory() as tmp:
            safe = Path(tmp) / "safe_root"
            safe.mkdir(parents=True, exist_ok=True)
            sec.add_allowlist_root(safe)
            assert safe.resolve() in sec.allowlist_roots

    def test_restricted_prevents_home_prefix(self):
        sec = SecurityConfig()
        sec.set_root_policy("restricted")
        with pytest.raises(ValueError, match="forbidden"):
            sec.add_allowlist_root(Path("/home/user"))

    def test_restricted_fail_closed_no_roots(self):
        sec = SecurityConfig()
        sec.set_root_policy("restricted")
        with pytest.raises(AccessDeniedError, match="No allowed roots"):
            sec.validate_path(Path("/any/path"))


class TestListAllowedRootsRestricted:
    def test_restricted_no_system_root(self):
        sec = get_security_config()
        sec.set_root_policy("restricted")
        with tempfile.TemporaryDirectory() as tmp:
            hub = Path(tmp) / "hub"
            hub.mkdir()
            sec.add_allowlist_root(hub)
            roots = list_allowed_roots(hub, merges_dir=None)
            assert "system" not in [r["id"] for r in roots]

    def test_restricted_no_home_root(self):
        sec = get_security_config()
        sec.set_root_policy("restricted")
        with tempfile.TemporaryDirectory() as tmp:
            hub = Path(tmp) / "hub"
            hub.mkdir()
            sec.add_allowlist_root(hub)
            roots = list_allowed_roots(hub, merges_dir=None)
            assert str(Path.home().resolve()) not in [r["path"] for r in roots]

    def test_restricted_returns_explicit_roots(self):
        sec = get_security_config()
        sec.set_root_policy("restricted")
        with tempfile.TemporaryDirectory() as tmp:
            hub = Path(tmp) / "hub"
            hub.mkdir()
            merges = Path(tmp) / "merges"
            merges.mkdir()
            sec.add_allowlist_root(hub)
            sec.add_allowlist_root(merges)
            roots = list_allowed_roots(hub, merges)
            ids = [r["id"] for r in roots]
            assert "hub" in ids
            assert "merges" in ids
            assert len(roots) == 2

    def test_restricted_returns_only_hub(self):
        sec = get_security_config()
        sec.set_root_policy("restricted")
        with tempfile.TemporaryDirectory() as tmp:
            hub = Path(tmp) / "hub"
            hub.mkdir()
            sec.add_allowlist_root(hub)
            roots = list_allowed_roots(hub, merges_dir=None)
            assert [r["id"] for r in roots] == ["hub"]


class TestDefaultRootPolicy:
    def test_default_still_has_system_root(self):
        sec = get_security_config()
        sec.set_root_policy("default")
        with tempfile.TemporaryDirectory() as tmp:
            hub = Path(tmp) / "hub"
            hub.mkdir()
            sec.add_allowlist_root(hub)
            sec.add_allowlist_root(Path.home().resolve())
            roots = list_allowed_roots(hub, merges_dir=None)
            assert "system" in [r["id"] for r in roots]

    def test_default_does_not_reject_home(self):
        sec = SecurityConfig()
        sec.set_root_policy("default")
        sec.add_allowlist_root(Path.home())
        assert Path.home().resolve() in sec.allowlist_roots


class TestRestrictedAPIIntegration:
    def test_restricted_mode_no_explicit_roots(self):
        with tempfile.TemporaryDirectory() as tmp:
            hub = Path(tmp) / "hub"
            hub.mkdir()
            for gen in _make_client_and_hub(
                root_policy="restricted", hub_dir=hub, allowed_roots=None,
            ):
                client, hub_path = gen
                headers = {"Authorization": "Bearer test-token"}
                resp = client.get("/api/fs/roots", headers=headers)
                assert resp.status_code == 200, resp.text
                ids = [r["id"] for r in resp.json().get("roots", [])]
                assert "hub" in ids
                assert "system" not in ids

    def test_restricted_roots_require_auth(self):
        sec = get_security_config()
        sec.set_root_policy("restricted")
        sec.token = "test-token"
        with tempfile.TemporaryDirectory() as tmp:
            hub = Path(tmp) / "hub"
            hub.mkdir()
            sec.add_allowlist_root(hub)
            with TestClient(service_app.app) as client:
                resp = client.get("/api/fs/roots")
                assert resp.status_code in (401, 403)

    def test_restricted_explicit_allowed_roots_via_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            hub = Path(tmp) / "hub"
            hub.mkdir()
            allowed_repos = Path(tmp) / "repos"
            allowed_repos.mkdir()
            for gen in _make_client_and_hub(
                root_policy="restricted", hub_dir=hub,
                allowed_roots=[str(allowed_repos)],
            ):
                client, hub_path = gen
                headers = {"Authorization": "Bearer test-token"}
                resp = client.get("/api/fs/roots", headers=headers)
                assert resp.status_code == 200, resp.text
                data = resp.json()
                ids = [r["id"] for r in data.get("roots", [])]
                paths = [r["path"] for r in data.get("roots", [])]
                assert "hub" in ids
                assert "system" not in ids
                assert "/" not in paths

    def test_default_mode_backward_compatible(self):
        with tempfile.TemporaryDirectory() as tmp:
            hub = Path(tmp) / "hub"
            hub.mkdir()
            for gen in _make_client_and_hub(root_policy="default", hub_dir=hub):
                client, hub_path = gen
                headers = {"Authorization": "Bearer test-token"}
                resp = client.get("/api/fs/roots", headers=headers)
                assert resp.status_code == 200, resp.text
                ids = [r["id"] for r in resp.json().get("roots", [])]
                assert "hub" in ids
                assert "system" in ids


class TestRestrictedEdgeCases:
    def test_restricted_safe_path_below_home(self):
        sec = SecurityConfig()
        sec.set_root_policy("restricted")
        with tempfile.TemporaryDirectory() as tmp:
            safe = Path(tmp) / "safe_workspace"
            safe.mkdir(parents=True, exist_ok=True)
            sec.add_allowlist_root(safe)
            assert sec.validate_path(safe / "subdir") is not None

    def test_restricted_validates_path_within_allowlist(self):
        sec = SecurityConfig()
        sec.set_root_policy("restricted")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sec.add_allowlist_root(root)
            sub = root / "subdir"
            sub.mkdir(exist_ok=True)
            assert sec.validate_path(sub) == sub.resolve()

    def test_restricted_rejects_outside_allowlist(self):
        sec = SecurityConfig()
        sec.set_root_policy("restricted")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "allowed"
            root.mkdir(exist_ok=True)
            sec.add_allowlist_root(root)
            outside = Path(tmp) / "outside"
            outside.mkdir(exist_ok=True)
            with pytest.raises(AccessDeniedError):
                sec.validate_path(outside)