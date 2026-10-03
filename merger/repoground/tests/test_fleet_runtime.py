from __future__ import annotations

import hashlib
import importlib.machinery
import importlib.util
import json
import os
import shlex
import shutil
import sqlite3
import stat
import subprocess
import sys
import time
from pathlib import Path
from types import ModuleType

import pytest


ROOT = Path(__file__).resolve().parents[3]
PUBLISHER = ROOT / "scripts/ops/repoground-publish-fleet"
CLI_WRAPPER = ROOT / "scripts/ops/repoground-cli-wrapper"
LEGACY_PUBLISHER = ROOT / "scripts/ops/rb-publish-fleet"
INSTALLER = ROOT / "scripts/ops/install_repoground_publish_fleet_runtime.sh"
LEGACY_INSTALLER = ROOT / "scripts/ops/install_rb_publish_fleet_runtime.sh"
SYSTEMKATALOG_INSTALLER = ROOT / "scripts/ops/install_systemkatalog_publish_runtime.sh"
SYSTEMKATALOG_PUBLISH = ROOT / "scripts/ops/repoground-publish-systemkatalog-main"
SYSTEMKATALOG_WATCH = (
    ROOT / "scripts/ops/repoground-publish-systemkatalog-main-if-changed"
)
LEGACY_SYSTEMKATALOG_PUBLISH = ROOT / "scripts/ops/repobrief-publish-systemkatalog-main"
LEGACY_SYSTEMKATALOG_WATCH = (
    ROOT / "scripts/ops/repobrief-publish-systemkatalog-main-if-changed"
)
UNIT_DIR = ROOT / "ops/systemd/repoground-fleet"
LEGACY_PUBLICATION_POLICY_WRAPPER = '''#!/usr/bin/env python3
"""Deprecated RepoBrief publication-policy entry point.

Use ``repoground-publication-policy``. This delegate remains during RepoGround
3.x so existing automation continues to execute the same implementation.
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path


def main() -> None:
    target = Path(__file__).with_name("repoground-publication-policy")
    print(
        "rb-publication-policy is deprecated; use repoground-publication-policy",
        file=sys.stderr,
    )
    runpy.run_path(str(target), run_name="__main__")


if __name__ == "__main__":
    main()
'''


def load_publisher() -> ModuleType:
    module_name = "repoground_publish_fleet_test"
    loader = importlib.machinery.SourceFileLoader(module_name, str(PUBLISHER))
    spec = importlib.util.spec_from_loader(module_name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    loader.exec_module(module)
    return module


def _is_advertised_branch_fetch(argv: list[str], branch: str) -> bool:
    return argv[-4:] == [
        "fetch",
        "--no-tags",
        "origin",
        f"+refs/heads/{branch}:refs/remotes/origin/{branch}",
    ]


def test_remote_head_explicitly_fetches_remote_advertised_nonstandard_default_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    repo = tmp_path / "preview"
    sha = "b2ba42acc074410e44f03bb2d0943c2c7fc1ef59"
    calls: list[list[str]] = []
    advertised_fetched = False

    def fake_run(
        argv: list[str],
        cwd: Path | None = None,
        check: bool = True,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal advertised_fetched
        calls.append(argv)
        if argv[-4:] == ["ls-remote", "--symref", "origin", "HEAD"]:
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout=f"ref: refs/heads/gh-pages\tHEAD\n{sha}\tHEAD\n",
            )
        if _is_advertised_branch_fetch(argv, "gh-pages"):
            advertised_fetched = True
            return subprocess.CompletedProcess(argv, 0, stdout="")
        if argv[-3:] == ["rev-parse", "--verify", "refs/remotes/origin/gh-pages"]:
            return subprocess.CompletedProcess(
                argv,
                0 if advertised_fetched else 1,
                stdout=f"{sha}\n" if advertised_fetched else "",
            )
        raise AssertionError(f"unexpected command: {argv}")

    monkeypatch.setattr(module, "run", fake_run)

    assert module.remote_head(repo) == ("origin/gh-pages", "gh-pages", sha)
    assert advertised_fetched is True
    assert len(calls) == 3
    assert not any(argv[-3:] == ["fetch", "origin", "--prune"] for argv in calls)
    assert not any("set-head" in argv for argv in calls)


def test_parse_github_remote_requires_exact_github_host() -> None:
    module = load_publisher()
    expected = ("heimgewebe", "metarepo")

    for remote in (
        "git@github.com:heimgewebe/metarepo.git",
        "org-236528253@github.com:heimgewebe/metarepo.git",
        "https://github.com/heimgewebe/metarepo",
        "ssh://git@github.com/heimgewebe/metarepo.git",
        "ssh://git@github.com:22/heimgewebe/metarepo.git",
        "https://github.com:443/heimgewebe/metarepo.git",
    ):
        assert module.parse_github_remote(remote) == expected

    for remote in (
        "git@notgithub.com:heimgewebe/metarepo.git",
        "https://notgithub.com/heimgewebe/metarepo",
        "ssh://git@github.com.evil.example/heimgewebe/metarepo.git",
        "github.com/heimgewebe/metarepo",
        "ssh://git@github.com:0/heimgewebe/metarepo.git",
        "ssh://git@github.com:65536/heimgewebe/metarepo.git",
    ):
        assert module.parse_github_remote(remote) is None


def test_github_ssh_remote_explicit_port_is_bounded() -> None:
    module = load_publisher()

    assert (
        module.github_ssh_remote_explicit_port(
            "ssh://git@github.com:443/heimgewebe/member.git"
        )
        == 443
    )
    assert (
        module.github_ssh_remote_explicit_port(
            "ssh://git@github.com:22/heimgewebe/member.git"
        )
        == 22
    )
    for remote in (
        "ssh://git@github.com/heimgewebe/member.git",
        "git@github.com:heimgewebe/member.git",
        "https://github.com/heimgewebe/member.git",
        "ssh://git@attacker.invalid:443/heimgewebe/member.git",
        "ssh://git@github.com:0/heimgewebe/member.git",
    ):
        assert module.github_ssh_remote_explicit_port(remote) is None


def test_authenticated_membership_transport_requires_https_or_explicit_ssh_user() -> None:
    module = load_publisher()

    for remote in (
        "https://github.com/heimgewebe/metarepo.git",
        "ssh://git@github.com/heimgewebe/metarepo.git",
        "ssh://git@github.com:22/heimgewebe/metarepo.git",
        "git@github.com:heimgewebe/metarepo.git",
        "org-236528253@github.com:heimgewebe/metarepo.git",
    ):
        assert module.github_remote_uses_authenticated_transport(remote) is True

    for remote in (
        "http://github.com/heimgewebe/metarepo.git",
        "git://github.com/heimgewebe/metarepo.git",
        "ssh://github.com/heimgewebe/metarepo.git",
        "github.com:heimgewebe/metarepo.git",
    ):
        assert module.parse_github_remote(remote) == ("heimgewebe", "metarepo")
        assert module.github_remote_uses_authenticated_transport(remote) is False


def test_remote_head_rejects_remote_head_that_moves_after_fetch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    repo = tmp_path / "moving"
    advertised_sha = "a" * 40
    fetched_sha = "b" * 40

    def fake_run(
        argv: list[str],
        cwd: Path | None = None,
        check: bool = True,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        if argv[-4:] == ["ls-remote", "--symref", "origin", "HEAD"]:
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout=(
                    "ref: refs/heads/trunk\tHEAD\n"
                    f"{advertised_sha}\tHEAD\n"
                ),
            )
        if _is_advertised_branch_fetch(argv, "trunk"):
            return subprocess.CompletedProcess(argv, 0, stdout="")
        if argv[-3:] == ["rev-parse", "--verify", "refs/remotes/origin/trunk"]:
            return subprocess.CompletedProcess(argv, 0, stdout=f"{fetched_sha}\n")
        raise AssertionError(f"unexpected command: {argv}")

    monkeypatch.setattr(module, "run", fake_run)

    with pytest.raises(RuntimeError, match="moved during resolution"):
        module.remote_head(repo)



def test_remote_head_for_entry_rejects_checkout_local_transport_override(
    tmp_path: Path,
) -> None:
    module = load_publisher()
    repo, _ = initialize_repository(tmp_path, "member-unsafe-transport")
    remote = "git@github.com:heimgewebe/member.git"
    git(repo, "remote", "add", "origin", remote)
    git(repo, "config", "core.sshCommand", "/bin/false")
    entry = module.RepoEntry(
        key="heimgewebe/member",
        owner="heimgewebe",
        repo="member",
        path=repo,
        remote=remote,
    )

    with pytest.raises(RuntimeError, match="unsafe local Git transport configuration"):
        module.remote_head_for_entry(entry)


def test_remote_head_for_entry_allows_separate_pushurl(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_publisher()
    repo, sha = initialize_repository(tmp_path, "member-pushurl")
    remote = "git@github.com:heimgewebe/member.git"
    git(repo, "remote", "add", "origin", remote)
    git(
        repo,
        "remote",
        "set-url",
        "--add",
        "--push",
        "origin",
        "git@github.com:heimgewebe/member-write.git",
    )
    entry = module.RepoEntry(
        key="heimgewebe/member",
        owner="heimgewebe",
        repo="member",
        path=repo,
        remote=remote,
    )

    def fake_remote_head(
        repo_path: Path,
        *,
        remote: str = "origin",
        env: dict[str, str] | None = None,
    ) -> tuple[str, str, str]:
        assert repo_path == repo
        assert remote == entry.remote
        assert isinstance(env, dict)
        return "origin/main", "main", sha

    monkeypatch.setattr(module, "remote_head", fake_remote_head)

    assert module.remote_head_for_entry(entry) == ("origin/main", "main", sha)


def test_remote_head_for_entry_allows_origin_prune(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_publisher()
    repo, sha = initialize_repository(tmp_path, "member-prune")
    remote = "git@github.com:heimgewebe/member.git"
    git(repo, "remote", "add", "origin", remote)
    git(repo, "config", "remote.origin.prune", "true")
    entry = module.RepoEntry(
        key="heimgewebe/member",
        owner="heimgewebe",
        repo="member",
        path=repo,
        remote=remote,
    )

    assert module._fleet_member_local_config_is_transport_override(
        "remote.origin.prune"
    ) is False
    assert module._fleet_member_local_config_is_transport_override(
        "remote.origin.uploadpack"
    ) is True

    def fake_remote_head(
        repo_path: Path,
        *,
        remote: str = "origin",
        env: dict[str, str] | None = None,
    ) -> tuple[str, str, str]:
        assert repo_path == repo
        assert remote == entry.remote
        assert isinstance(env, dict)
        return "origin/main", "main", sha

    monkeypatch.setattr(module, "remote_head", fake_remote_head)

    assert module.remote_head_for_entry(entry) == ("origin/main", "main", sha)


def test_remote_head_for_entry_allows_secondary_fetch_urls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_publisher()
    repo, sha = initialize_repository(tmp_path, "member-secondary-fetch")
    remote = "https://github.com/heimgewebe/member.git"
    git(repo, "remote", "add", "origin", remote)
    git(
        repo,
        "remote",
        "set-url",
        "--add",
        "origin",
        "https://github.com/heimgewebe/member-mirror.git",
    )
    entry = module.RepoEntry(
        key="heimgewebe/member",
        owner="heimgewebe",
        repo="member",
        path=repo,
        remote=remote,
    )
    observed: dict[str, object] = {}

    def fake_remote_head(
        repo_path: Path,
        *,
        remote: str = "origin",
        env: dict[str, str] | None = None,
    ) -> tuple[str, str, str]:
        observed["repo_path"] = repo_path
        observed["remote"] = remote
        observed["env"] = env
        return "origin/main", "main", sha

    monkeypatch.setattr(module, "remote_head", fake_remote_head)

    assert module.remote_head_for_entry(entry) == ("origin/main", "main", sha)
    assert observed["repo_path"] == repo
    assert observed["remote"] == remote
    assert isinstance(observed["env"], dict)


def test_remote_head_for_entry_rejects_origin_change_since_discovery(
    tmp_path: Path,
) -> None:
    module = load_publisher()
    repo, _ = initialize_repository(tmp_path, "member-origin-change")
    discovered = "git@github.com:heimgewebe/member.git"
    git(repo, "remote", "add", "origin", discovered)
    entry = module.RepoEntry(
        key="heimgewebe/member",
        owner="heimgewebe",
        repo="member",
        path=repo,
        remote=discovered,
    )
    git(repo, "remote", "set-url", "origin", "https://github.com/heimgewebe/member.git")

    with pytest.raises(RuntimeError, match="origin changed since discovery"):
        module.remote_head_for_entry(entry)


def test_remote_head_for_entry_uses_exact_validated_origin_url(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_publisher()
    repo, sha = initialize_repository(tmp_path, "member-bound-origin")
    remote = "git@github.com:heimgewebe/member.git"
    git(repo, "remote", "add", "origin", remote)
    entry = module.RepoEntry(
        key="heimgewebe/member",
        owner="heimgewebe",
        repo="member",
        path=repo,
        remote=remote,
    )
    observed: dict[str, object] = {}

    def fake_remote_head(
        repo_path: Path,
        *,
        remote: str = "origin",
        env: dict[str, str] | None = None,
    ) -> tuple[str, str, str]:
        observed["repo_path"] = repo_path
        observed["remote"] = remote
        observed["env"] = env
        return "origin/main", "main", sha

    monkeypatch.setattr(module, "remote_head", fake_remote_head)

    assert module.remote_head_for_entry(entry) == ("origin/main", "main", sha)
    assert observed["repo_path"] == repo
    assert observed["remote"] == remote
    env = observed["env"]
    assert isinstance(env, dict)
    assert env["GIT_CONFIG_GLOBAL"] == os.devnull
    assert env["GIT_CONFIG_SYSTEM"] == os.devnull


def test_fleet_credential_config_key_allowed_matches_valid_https_github_scopes() -> None:
    module = load_publisher()

    for key in (
        "credential.https://github.com:443.helper",
        "credential.https://bot@github.com.helper",
        "credential.https://bot@github.com:443.username",
        "credential.https://bot@github.com:443/owner/repo.usehttppath",
    ):
        assert module._fleet_credential_config_key_allowed(key) is True

    for key in (
        "credential.https://github.com:0.helper",
        "credential.https://github.com:65536.helper",
        "credential.https://bot:secret@github.com.helper",
        "credential.http://github.com:443.helper",
        "credential.https://github.com.evil.example:443.helper",
    ):
        assert module._fleet_credential_config_key_allowed(key) is False


def test_fleet_tls_config_key_allowed_preserves_only_bounded_github_tls() -> None:
    module = load_publisher()

    for key in (
        "http.pinnedPubkey",
        "http.sslCAInfo",
        "http.sslCAPath",
        "http.sslCert",
        "http.sslCertPasswordProtected",
        "http.sslKey",
        "http.https://github.com.pinnedPubkey",
        "http.https://github.com.sslCert",
        "http.https://github.com.sslCertPasswordProtected",
        "http.https://github.com.sslKey",
        "http.https://github.com:443.pinnedPubkey",
        "http.https://bot@github.com/owner/repo.sslCert",
    ):
        assert module._fleet_tls_config_key_allowed(key) is True

    for key in (
        "http.https://github.com.evil.example.pinnedPubkey",
        "http.https://github.com:0.sslCert",
        "http.https://github.com:65536.sslKey",
        "http.http://github.com.pinnedPubkey",
        "http.pinnedPubkeyExtra",
        "http.sslVerify",
    ):
        assert module._fleet_tls_config_key_allowed(key) is False


def test_fleet_github_authorization_extra_header_is_value_bounded() -> None:
    module = load_publisher()
    key = "http.https://github.com/.extraHeader"

    for allowed_key in (
        key,
        "http.https://github.com:443/.extraHeader",
        "http.https://bot@github.com/owner/repo.extraHeader",
    ):
        assert module._fleet_github_extra_header_key_allowed(allowed_key) is True

    for forbidden_key in (
        "http.extraHeader",
        "http.http://github.com/.extraHeader",
        "http.https://github.com.evil.example/.extraHeader",
        "http.https://github.com:0/.extraHeader",
        "http.https://github.com:65536/.extraHeader",
    ):
        assert module._fleet_github_extra_header_key_allowed(forbidden_key) is False

    for value in (
        "",
        "Authorization: Bearer placeholder-token",
        "authorization:\tBasic cGxhY2Vob2xkZXI=",
    ):
        assert module._fleet_github_authorization_header_value_allowed(value) is True
        assert module._fleet_https_config_entry_allowed(key, value) is True

    for value in (
        "Authorization:",
        " Host: attacker.invalid",
        "Host: attacker.invalid",
        "Proxy-Authorization: Basic cGxhY2Vob2xkZXI=",
        "Authorization: Bearer token\nHost: attacker.invalid",
        "Authorization: Bearer token\x01",
    ):
        assert module._fleet_github_authorization_header_value_allowed(value) is False
        assert module._fleet_https_config_entry_allowed(key, value) is False


def test_fleet_proxy_config_key_allowed_preserves_only_bounded_github_proxies() -> None:
    module = load_publisher()

    for key in (
        "http.proxy",
        "http.proxyAuthMethod",
        "http.proxySSLCAInfo",
        "http.proxySSLCert",
        "http.proxySSLCertPasswordProtected",
        "http.proxySSLKey",
        "http.https://github.com.proxy",
        "http.https://github.com.proxyAuthMethod",
        "http.https://github.com.proxySSLCAInfo",
        "http.https://github.com.proxySSLCert",
        "http.https://github.com.proxySSLCertPasswordProtected",
        "http.https://github.com.proxySSLKey",
        "http.https://github.com:443.proxy",
        "http.https://github.com:443.proxyAuthMethod",
        "http.https://bot@github.com/owner/repo.proxy",
        "http.https://bot@github.com/owner/repo.proxyAuthMethod",
        "http.https://bot@github.com/owner/repo.proxySSLKey",
    ):
        assert module._fleet_proxy_config_key_allowed(key) is True

    for key in (
        "http.https://github.com.evil.example.proxy",
        "http.https://github.com.evil.example.proxyAuthMethod",
        "http.https://github.com.evil.example.proxySSLCAInfo",
        "http.https://github.com.evil.example.proxySSLKey",
        "http.https://github.com:0.proxy",
        "http.https://github.com:65536.proxyAuthMethod",
        "http.http://github.com.proxy",
        "http.proxyAuthMethodExtra",
        "http.proxySSLCAPath",
        "http.proxySSLVerify",
        "http.proxySSLCertExtra",
        "http.sslVerify",
    ):
        assert module._fleet_proxy_config_key_allowed(key) is False


def test_fleet_repo_git_env_preserves_github_credentials_without_transport_overrides(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_publisher()
    repo, _sha = initialize_repository(tmp_path, "credential-member")

    home = tmp_path / "home"
    home.mkdir()
    helper = tmp_path / "credential-helper"
    helper.write_text(
        "#!/bin/sh\n"
        "cat >/dev/null\n"
        "printf 'username=probe-user\\npassword=probe-pass\\n'\n",
        encoding="utf-8",
    )
    helper.chmod(0o700)
    included = tmp_path / "member-credentials.inc"
    included.write_text(
        "[credential \"https://github.com\"]\n"
        "    helper =\n"
        f"    helper = !{helper}\n"
        "[credential \"https://github.com:443\"]\n"
        f"    helper = !{helper}\n"
        "[credential \"https://bot@github.com\"]\n"
        f"    helper = !{helper}\n"
        "[credential \"https://bot@github.com:443\"]\n"
        "    username = bot\n",
        encoding="utf-8",
    )
    git_dir = (repo / ".git").resolve()
    (home / ".gitconfig").write_text(
        f"[includeIf \"gitdir:{git_dir}\"]\n"
        f"    path = {included}\n"
        "[http]\n"
        "    sslCAInfo = /tmp/global-ca.pem\n"
        "    sslCAPath = /tmp/global-ca-dir\n"
        "    pinnedPubkey = sha256//global-github-pin\n"
        "    sslCert = /tmp/global-client.pem\n"
        "    sslCertPasswordProtected = true\n"
        "    sslKey = /tmp/global-client.key\n"
        "    proxy = http://127.0.0.1:18081\n"
        "    proxyAuthMethod = basic\n"
        "    proxySSLCAInfo = /tmp/global-proxy-ca.pem\n"
        "    proxySSLCert = /tmp/global-proxy-client.pem\n"
        "    proxySSLCertPasswordProtected = true\n"
        "    proxySSLKey = /tmp/global-proxy-client.key\n"
        "[http \"https://github.com/\"]\n"
        "    extraHeader =\n"
        "    extraHeader = Authorization: Bearer placeholder-global-token\n"
        "    extraHeader = Host: attacker.invalid\n"
        "[http \"https://github.com\"]\n"
        "    proxy = http://127.0.0.1:18082\n"
        "    proxyAuthMethod = ntlm\n"
        "    proxySSLCAInfo = /tmp/github-proxy-ca.pem\n"
        "[url \"ssh://attacker.invalid/\"]\n"
        "    insteadOf = https://github.com/\n"
        "[core]\n"
        "    sshCommand = /bin/false\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(home))
    for name in module._AUTHORITY_GIT_FORBIDDEN_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("GIT_CONFIG_COUNT", raising=False)
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:18443")
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:18080")
    monkeypatch.setenv("ALL_PROXY", "socks5h://127.0.0.1:11080")
    monkeypatch.setenv("NO_PROXY", "localhost,github.example.invalid")
    monkeypatch.setenv("CURL_CA_BUNDLE", "/tmp/curl-ca.pem")
    monkeypatch.setenv("SSL_CERT_DIR", "/tmp/custom-ca-dir")
    monkeypatch.setenv("SSL_CERT_FILE", "/tmp/custom-ca.pem")
    monkeypatch.setenv("GIT_SSL_CAINFO", "/tmp/git-ca.pem")
    monkeypatch.setenv("GIT_SSL_CAPATH", "/tmp/git-ca-dir")
    monkeypatch.setenv("GIT_SSL_CERT", "/tmp/git-client.pem")
    monkeypatch.setenv("GIT_SSL_CERT_PASSWORD_PROTECTED", "true")
    monkeypatch.setenv("GIT_SSL_KEY", "/tmp/git-client.key")
    monkeypatch.setenv("GIT_SSL_NO_VERIFY", "1")

    authority_env = module._authority_git_env()
    authority_helper = subprocess.run(
        ["/usr/bin/git", "config", "--get-all", "credential.https://github.com.helper"],
        env=authority_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert authority_helper.returncode == 1
    assert "HTTPS_PROXY" not in authority_env
    assert "http_proxy" not in authority_env
    assert "ALL_PROXY" not in authority_env
    assert authority_env["NO_PROXY"] == "localhost,github.example.invalid"
    assert "CURL_CA_BUNDLE" not in authority_env
    assert "SSL_CERT_DIR" not in authority_env
    assert "SSL_CERT_FILE" not in authority_env
    assert "GIT_SSL_CAINFO" not in authority_env
    assert "GIT_SSL_CAPATH" not in authority_env
    assert "GIT_SSL_CERT" not in authority_env
    assert "GIT_SSL_CERT_PASSWORD_PROTECTED" not in authority_env
    assert "GIT_SSL_KEY" not in authority_env
    assert "GIT_SSL_NO_VERIFY" not in authority_env

    safe_global_config = tmp_path / "sanitized-member-global.gitconfig"
    env = module._fleet_repo_git_env(
        repo,
        safe_global_config=safe_global_config,
    )
    assert env["GIT_CONFIG_GLOBAL"] == str(safe_global_config)
    assert env["GIT_CONFIG_SYSTEM"] == os.devnull
    assert "GIT_CONFIG_COUNT" not in env
    assert env["HTTPS_PROXY"] == "http://127.0.0.1:18443"
    assert env["http_proxy"] == "http://127.0.0.1:18080"
    assert env["ALL_PROXY"] == "socks5h://127.0.0.1:11080"
    assert env["NO_PROXY"] == "localhost,github.example.invalid"
    assert env["CURL_CA_BUNDLE"] == "/tmp/curl-ca.pem"
    assert env["SSL_CERT_DIR"] == "/tmp/custom-ca-dir"
    assert env["SSL_CERT_FILE"] == "/tmp/custom-ca.pem"
    assert env["GIT_SSL_CAINFO"] == "/tmp/git-ca.pem"
    assert env["GIT_SSL_CAPATH"] == "/tmp/git-ca-dir"
    assert env["GIT_SSL_CERT"] == "/tmp/git-client.pem"
    assert env["GIT_SSL_CERT_PASSWORD_PROTECTED"] == "true"
    assert env["GIT_SSL_KEY"] == "/tmp/git-client.key"
    assert "GIT_SSL_NO_VERIFY" not in env
    sanitized_cp = subprocess.run(
        [
            "/usr/bin/git",
            "config",
            "--file",
            str(safe_global_config),
            "--null",
            "--get-regexp",
            r"^(credential|http)\.",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert sanitized_cp.returncode == 0, sanitized_cp.stderr
    injected = []
    for record in [item for item in sanitized_cp.stdout.split("\0") if item]:
        key, separator, value = record.partition("\n")
        assert separator
        injected.append((key, value))
    assert any(
        key == "credential.https://github.com.helper"
        and value == f"!{helper}"
        for key, value in injected
    )
    assert any(
        key == "credential.https://github.com:443.helper"
        and value == f"!{helper}"
        for key, value in injected
    )
    assert any(
        key == "credential.https://bot@github.com.helper"
        and value == f"!{helper}"
        for key, value in injected
    )
    assert any(
        key == "credential.https://bot@github.com:443.username"
        and value == "bot"
        for key, value in injected
    )
    assert any(
        key.lower() == "http.sslcainfo"
        and value == "/tmp/global-ca.pem"
        for key, value in injected
    )
    assert any(
        key.lower() == "http.sslcapath"
        and value == "/tmp/global-ca-dir"
        for key, value in injected
    )
    assert ("http.pinnedpubkey", "sha256//global-github-pin") in [
        (key.lower(), value) for key, value in injected
    ]
    assert ("http.sslcert", "/tmp/global-client.pem") in [
        (key.lower(), value) for key, value in injected
    ]
    assert ("http.sslcertpasswordprotected", "true") in [
        (key.lower(), value) for key, value in injected
    ]
    assert ("http.sslkey", "/tmp/global-client.key") in [
        (key.lower(), value) for key, value in injected
    ]
    assert ("http.proxy", "http://127.0.0.1:18081") in [
        (key.lower(), value) for key, value in injected
    ]
    assert ("http.https://github.com.proxy", "http://127.0.0.1:18082") in [
        (key.lower(), value) for key, value in injected
    ]
    assert ("http.proxyauthmethod", "basic") in [
        (key.lower(), value) for key, value in injected
    ]
    assert ("http.https://github.com.proxyauthmethod", "ntlm") in [
        (key.lower(), value) for key, value in injected
    ]
    assert ("http.proxysslcainfo", "/tmp/global-proxy-ca.pem") in [
        (key.lower(), value) for key, value in injected
    ]
    assert (
        "http.https://github.com.proxysslcainfo",
        "/tmp/github-proxy-ca.pem",
    ) in [(key.lower(), value) for key, value in injected]
    assert ("http.proxysslcert", "/tmp/global-proxy-client.pem") in [
        (key.lower(), value) for key, value in injected
    ]
    assert ("http.proxysslcertpasswordprotected", "true") in [
        (key.lower(), value) for key, value in injected
    ]
    assert ("http.proxysslkey", "/tmp/global-proxy-client.key") in [
        (key.lower(), value) for key, value in injected
    ]
    github_extra_headers = [
        value
        for key, value in injected
        if key.lower() == "http.https://github.com/.extraheader"
    ]
    assert github_extra_headers == [
        "",
        "Authorization: Bearer placeholder-global-token",
    ]
    assert "Host: attacker.invalid" not in github_extra_headers

    filled = subprocess.run(
        ["/usr/bin/git", "credential", "fill"],
        input="protocol=https\nhost=github.com\n\n",
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert filled.returncode == 0, filled.stderr
    assert "username=probe-user" in filled.stdout
    assert "password=probe-pass" in filled.stdout

    url_override = subprocess.run(
        ["/usr/bin/git", "config", "--get-regexp", r"^url\."],
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    ssh_override = subprocess.run(
        ["/usr/bin/git", "config", "--get", "core.sshCommand"],
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert url_override.returncode == 1
    assert ssh_override.returncode == 1


def test_fleet_repo_git_env_preserves_local_https_precedence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_publisher()
    repo, _sha = initialize_repository(tmp_path, "member-local-precedence")
    home = tmp_path / "home"
    home.mkdir()
    (home / ".gitconfig").write_text(
        "[credential \"https://github.com\"]\n"
        "    helper = global-helper\n"
        "[http]\n"
        "    proxy = http://127.0.0.1:18081\n"
        "    proxyAuthMethod = basic\n"
        "    proxySSLCAInfo = /tmp/global-proxy-ca.pem\n"
        "    sslCAInfo = /tmp/global-ca.pem\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(home))
    for name in module._AUTHORITY_GIT_FORBIDDEN_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("GIT_CONFIG_COUNT", raising=False)

    git(repo, "config", "http.proxy", "http://127.0.0.1:18084")
    git(repo, "config", "http.proxyAuthMethod", "digest")
    git(repo, "config", "http.proxySSLCAInfo", "/tmp/local-proxy-ca.pem")
    git(repo, "config", "http.sslCAInfo", "/tmp/local-ca.pem")
    git(repo, "config", "credential.https://github.com.helper", "")
    git(repo, "config", "--add", "credential.https://github.com.helper", "local-helper")

    safe_global_config = tmp_path / "precedence-global.gitconfig"
    env = module._fleet_repo_git_env(
        repo,
        safe_global_config=safe_global_config,
    )

    proxy = subprocess.run(
        [
            "/usr/bin/git",
            "-C",
            str(repo),
            "config",
            "--get-urlmatch",
            "http.proxy",
            "https://github.com/heimgewebe/member.git",
        ],
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    proxy_auth_method = subprocess.run(
        [
            "/usr/bin/git",
            "-C",
            str(repo),
            "config",
            "--get-urlmatch",
            "http.proxyAuthMethod",
            "https://github.com/heimgewebe/member.git",
        ],
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    proxy_ca_info = subprocess.run(
        ["/usr/bin/git", "-C", str(repo), "config", "--get", "http.proxySSLCAInfo"],
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    ca_info = subprocess.run(
        ["/usr/bin/git", "-C", str(repo), "config", "--get", "http.sslCAInfo"],
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    helpers = subprocess.run(
        [
            "/usr/bin/git",
            "-C",
            str(repo),
            "config",
            "--get-all",
            "credential.https://github.com.helper",
        ],
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert proxy.returncode == 0, proxy.stderr
    assert proxy.stdout.strip() == "http://127.0.0.1:18084"
    assert proxy_auth_method.returncode == 0, proxy_auth_method.stderr
    assert proxy_auth_method.stdout.strip() == "digest"
    assert proxy_ca_info.returncode == 0, proxy_ca_info.stderr
    assert proxy_ca_info.stdout.strip() == "/tmp/local-proxy-ca.pem"
    assert ca_info.returncode == 0, ca_info.stderr
    assert ca_info.stdout.strip() == "/tmp/local-ca.pem"
    assert helpers.returncode == 0, helpers.stderr
    assert helpers.stdout.splitlines() == ["global-helper", "", "local-helper"]
    assert "GIT_CONFIG_COUNT" not in env


def test_fleet_member_local_config_allows_only_bounded_https_transport() -> None:
    module = load_publisher()

    for key in (
        "http.sslCAInfo",
        "http.sslCAPath",
        "http.proxy",
        "http.proxyAuthMethod",
        "http.proxySSLCAInfo",
        "http.proxySSLCert",
        "http.proxySSLCertPasswordProtected",
        "http.proxySSLKey",
        "http.https://github.com.proxy",
        "http.https://github.com.proxyAuthMethod",
        "http.https://github.com.proxySSLCAInfo",
        "http.https://github.com.proxySSLKey",
        "http.https://github.com.sslCAInfo",
        "http.https://github.com:443.sslCAPath",
    ):
        assert module._fleet_member_local_config_is_transport_override(key) is False

    assert (
        module._fleet_member_local_config_is_transport_override(
            "http.https://github.com/.extraHeader"
        )
        is True
    )
    assert (
        module._fleet_member_local_config_entry_is_transport_override(
            "http.https://github.com/.extraHeader",
            "Authorization: Bearer placeholder-local-token",
        )
        is False
    )

    for key in (
        "http.sslVerify",
        "http.proxySSLVerify",
        "http.proxySSLCAPath",
        "http.https://github.com.evil.example.proxy",
        "http.https://github.com.evil.example.sslCAInfo",
        "http.https://github.com:0.sslCAPath",
    ):
        assert module._fleet_member_local_config_is_transport_override(key) is True


def test_fleet_member_transport_safety_validates_worktree_scope(
    tmp_path: Path,
) -> None:
    module = load_publisher()
    repo, _sha = initialize_repository(tmp_path, "member-worktree-config")
    git(repo, "remote", "add", "origin", "https://github.com/heimgewebe/member.git")
    git(repo, "config", "extensions.worktreeConfig", "true")
    git(repo, "config", "--worktree", "core.sparseCheckout", "true")
    git(repo, "config", "--worktree", "http.sslCAPath", "/tmp/worktree-ca-dir")
    git(repo, "config", "--worktree", "http.proxy", "http://127.0.0.1:18083")
    git(repo, "config", "--worktree", "http.proxyAuthMethod", "negotiate")
    git(repo, "config", "--worktree", "http.proxySSLCAInfo", "/tmp/worktree-proxy-ca.pem")
    git(repo, "config", "--worktree", "http.proxySSLCert", "/tmp/worktree-proxy-client.pem")
    git(repo, "config", "--worktree", "http.proxySSLCertPasswordProtected", "true")
    git(repo, "config", "--worktree", "http.proxySSLKey", "/tmp/worktree-proxy-client.key")
    git(
        repo,
        "config",
        "--worktree",
        "--add",
        "http.https://github.com/.extraHeader",
        "Authorization: Bearer placeholder-worktree-token",
    )

    module.assert_fleet_member_git_transport_safe(
        repo,
        env=module._authority_git_env(),
    )

    git(repo, "config", "--worktree", "core.sshCommand", "/bin/false")
    with pytest.raises(
        RuntimeError,
        match="unsafe worktree Git transport configuration: core.sshcommand",
    ):
        module.assert_fleet_member_git_transport_safe(
            repo,
            env=module._authority_git_env(),
        )


def test_fleet_member_transport_safety_rejects_non_authorization_extra_header(
    tmp_path: Path,
) -> None:
    module = load_publisher()
    repo, _sha = initialize_repository(tmp_path, "member-extra-header")
    git(repo, "remote", "add", "origin", "https://github.com/heimgewebe/member.git")
    key = "http.https://github.com/.extraHeader"
    git(repo, "config", "--add", key, "")
    git(repo, "config", "--add", key, "Authorization: Bearer placeholder-local-token")

    module.assert_fleet_member_git_transport_safe(
        repo,
        env=module._authority_git_env(),
    )

    git(repo, "config", "--add", key, "Host: attacker.invalid")
    with pytest.raises(
        RuntimeError,
        match=r"unsafe local Git transport configuration: .*extraheader",
    ):
        module.assert_fleet_member_git_transport_safe(
            repo,
            env=module._authority_git_env(),
        )


def test_remote_head_for_entry_preserves_checkout_local_https_tls_trust(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_publisher()
    repo, sha = initialize_repository(tmp_path, "member-local-tls")
    remote = "https://github.com/heimgewebe/member.git"
    git(repo, "remote", "add", "origin", remote)
    git(repo, "config", "http.sslCAInfo", "/tmp/local-ca.pem")
    git(repo, "config", "http.sslCAPath", "/tmp/local-ca-dir")
    monkeypatch.setattr(
        module,
        "_global_system_github_https_config",
        lambda _repo_path: [],
    )
    entry = module.RepoEntry(
        key="heimgewebe/member",
        owner="heimgewebe",
        repo="member",
        path=repo,
        remote=remote,
    )
    observed: dict[str, object] = {}

    def fake_remote_head(
        repo_path: Path,
        *,
        remote: str = "origin",
        env: dict[str, str] | None = None,
    ) -> tuple[str, str, str]:
        observed["repo_path"] = repo_path
        observed["remote"] = remote
        observed["env"] = env
        return "origin/main", "main", sha

    monkeypatch.setattr(module, "remote_head", fake_remote_head)

    assert module.remote_head_for_entry(entry) == ("origin/main", "main", sha)
    assert observed["repo_path"] == repo
    assert observed["remote"] == remote
    env = observed["env"]
    assert isinstance(env, dict)

    local_ca_info = subprocess.run(
        ["/usr/bin/git", "-C", str(repo), "config", "--get", "http.sslCAInfo"],
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    local_ca_path = subprocess.run(
        ["/usr/bin/git", "-C", str(repo), "config", "--get", "http.sslCAPath"],
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert local_ca_info.returncode == 0
    assert local_ca_info.stdout.strip() == "/tmp/local-ca.pem"
    assert local_ca_path.returncode == 0
    assert local_ca_path.stdout.strip() == "/tmp/local-ca-dir"


def test_remote_head_for_entry_preserves_checkout_local_https_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_publisher()
    repo, sha = initialize_repository(tmp_path, "member-local-credential")
    remote = "https://github.com/heimgewebe/member.git"
    git(repo, "remote", "add", "origin", remote)
    helper = tmp_path / "local-helper"
    helper.write_text(
        "#!/bin/sh\n"
        "cat >/dev/null\n"
        "printf 'username=local-user\\npassword=local-pass\\n'\n",
        encoding="utf-8",
    )
    helper.chmod(0o700)
    git(repo, "config", "credential.https://github.com.helper", f"!{helper}")
    monkeypatch.setattr(
        module,
        "_global_system_github_https_config",
        lambda _repo_path: [],
    )
    entry = module.RepoEntry(
        key="heimgewebe/member",
        owner="heimgewebe",
        repo="member",
        path=repo,
        remote=remote,
    )
    observed: dict[str, object] = {}

    def fake_remote_head(
        repo_path: Path,
        *,
        remote: str = "origin",
        env: dict[str, str] | None = None,
    ) -> tuple[str, str, str]:
        observed["env"] = env
        return "origin/main", "main", sha

    monkeypatch.setattr(module, "remote_head", fake_remote_head)

    assert module.remote_head_for_entry(entry) == ("origin/main", "main", sha)
    env = observed["env"]
    assert isinstance(env, dict)
    injected = [
        (env[f"GIT_CONFIG_KEY_{i}"], env[f"GIT_CONFIG_VALUE_{i}"])
        for i in range(int(env.get("GIT_CONFIG_COUNT", "0")))
    ]
    assert (
        "credential.https://github.com.helper",
        f"!{helper}",
    ) not in injected
    filled = subprocess.run(
        ["/usr/bin/git", "-C", str(repo), "credential", "fill"],
        input="protocol=https\nhost=github.com\n\n",
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert filled.returncode == 0, filled.stderr
    assert "username=local-user" in filled.stdout
    assert "password=local-pass" in filled.stdout


def test_fleet_repo_git_env_preserves_bounded_credential_helper_lookup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_publisher()
    repo, _sha = initialize_repository(tmp_path, "credential-helper-path")
    home = tmp_path / "home"
    helper_dir = home / ".local" / "bin"
    helper_dir.mkdir(parents=True)
    helper = helper_dir / "git-credential-demo"
    helper.write_text(
        "#!/bin/sh\n"
        "cat >/dev/null\n"
        "printf 'username=path-user\\npassword=path-pass\\n'\n",
        encoding="utf-8",
    )
    helper.chmod(0o700)
    home.mkdir(exist_ok=True)
    (home / ".gitconfig").write_text(
        "[credential \"https://github.com\"]\n"
        "    helper = demo\n",
        encoding="utf-8",
    )
    attacker_bin = tmp_path / "attacker-bin"
    attacker_bin.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("PATH", str(attacker_bin))
    for name in module._AUTHORITY_GIT_FORBIDDEN_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("GIT_CONFIG_COUNT", raising=False)

    env = module._fleet_repo_git_env(
        repo,
        safe_global_config=tmp_path / "credential-helper-global.gitconfig",
    )

    assert env["PATH"] == os.pathsep.join(
        ["/usr/bin", "/bin", "/usr/local/bin", str(helper_dir)]
    )
    assert str(attacker_bin) not in env["PATH"].split(os.pathsep)
    filled = subprocess.run(
        ["/usr/bin/git", "credential", "fill"],
        input="protocol=https\nhost=github.com\n\n",
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert filled.returncode == 0, filled.stderr
    assert "username=path-user" in filled.stdout
    assert "password=path-pass" in filled.stdout


def test_fleet_member_credential_helper_path_rejects_path_injection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_publisher()
    monkeypatch.setenv("HOME", "/tmp/safe:/tmp/attacker")

    with pytest.raises(RuntimeError, match="unsafe for PATH"):
        module._fleet_member_credential_helper_path()


def test_remote_head_for_entry_uses_url_port_for_github_ssh_alternate_route(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_publisher()
    repo, sha = initialize_repository(tmp_path, "member-ssh-url-port")
    remote = "ssh://git@github.com:443/heimgewebe/member.git"
    git(repo, "remote", "add", "origin", remote)

    home = tmp_path / "home"
    ssh_dir = home / ".ssh"
    ssh_dir.mkdir(parents=True)
    (ssh_dir / "config").write_text(
        "Host github.com\n"
        "    HostName ssh.github.com\n",
        encoding="utf-8",
    )
    (ssh_dir / "config").chmod(0o600)
    monkeypatch.setenv("HOME", str(home))

    entry = module.RepoEntry(
        key="heimgewebe/member",
        owner="heimgewebe",
        repo="member",
        path=repo,
        remote=remote,
    )
    observed: dict[str, object] = {}

    def fake_remote_head(
        repo_path: Path,
        *,
        remote: str = "origin",
        env: dict[str, str] | None = None,
    ) -> tuple[str, str, str]:
        observed["repo_path"] = repo_path
        observed["remote"] = remote
        observed["env"] = env
        return "origin/main", "main", sha

    monkeypatch.setattr(module, "remote_head", fake_remote_head)

    assert module.remote_head_for_entry(entry) == ("origin/main", "main", sha)
    assert observed["repo_path"] == repo
    assert observed["remote"] == remote
    env = observed["env"]
    assert isinstance(env, dict)
    command = env["GIT_SSH_COMMAND"]
    assert "HostName=ssh.github.com" in command
    assert "Port=443" in command
    assert "HostKeyAlias=github.com" in command


def test_fleet_repo_ssh_env_preserves_only_bounded_github_auth_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_publisher()
    home = tmp_path / "home"
    ssh_dir = home / ".ssh"
    ssh_dir.mkdir(parents=True)
    (ssh_dir / "config").write_text(
        "Host github.com\n"
        "    HostName ssh.github.com\n"
        "    Port 443\n"
        "    User attacker\n"
        "    IdentityFile ~/.ssh/id_ed25519\n"
        "    CertificateFile ~/.ssh/id_ed25519-cert.pub\n"
        "    IdentitiesOnly yes\n"
        "    IdentityAgent ~/.ssh/agent.sock\n"
        "    ProxyCommand /bin/false\n"
        "    StrictHostKeyChecking no\n"
        "    UserKnownHostsFile /dev/null\n"
        "    LocalCommand /bin/false\n"
        "Host other.example\n"
        "    IdentityFile ~/.ssh/other\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(home))

    env = module._fleet_repo_ssh_env()
    command = env["GIT_SSH_COMMAND"]
    argv = __import__("shlex").split(command)

    assert argv[:3] == ["/usr/bin/ssh", "-F", os.devnull]
    assert str(ssh_dir / "id_ed25519") in argv
    assert f"CertificateFile={ssh_dir / 'id_ed25519-cert.pub'}" in argv
    assert "IdentitiesOnly=yes" in argv
    assert f"IdentityAgent={ssh_dir / 'agent.sock'}" in argv
    assert "ClearAllForwardings=yes" in argv
    assert "PermitLocalCommand=no" in argv
    assert "HostName=ssh.github.com" in argv
    assert "Port=443" in argv
    assert "HostKeyAlias=github.com" in argv
    for forbidden in (
        "attacker.invalid",
        "ProxyCommand",
        "StrictHostKeyChecking=no",
        "UserKnownHostsFile=/dev/null",
        "/bin/false",
        str(ssh_dir / "other"),
    ):
        assert forbidden not in command


def test_fleet_member_ssh_route_honors_url_port_443_with_bounded_hostname(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_publisher()
    home = tmp_path / "home"
    ssh_dir = home / ".ssh"
    ssh_dir.mkdir(parents=True)
    config = ssh_dir / "config"
    config.write_text(
        "Host github.com\n"
        "    HostName ssh.github.com\n",
        encoding="utf-8",
    )
    config.chmod(0o600)
    monkeypatch.setenv("HOME", str(home))

    command_443 = module._fleet_member_ssh_command(remote_port=443)
    assert "HostName=ssh.github.com" in command_443
    assert "Port=443" in command_443
    assert "HostKeyAlias=github.com" in command_443

    command_22 = module._fleet_member_ssh_command(remote_port=22)
    assert "HostName=ssh.github.com" not in command_22
    assert "HostKeyAlias=github.com" not in command_22


@pytest.mark.parametrize(
    ("config_body", "expected_route"),
    [
        (
            "Host github.com\n"
            "    HostName ssh.github.com\n"
            "    Port 443\n",
            True,
        ),
        (
            "Host github.com\n"
            "    HostName attacker.invalid\n"
            "    Port 443\n",
            False,
        ),
        (
            "Host github.com\n"
            "    HostName ssh.github.com\n"
            "    Port 22\n",
            False,
        ),
        (
            "Host other.example\n"
            "    HostName ssh.github.com\n"
            "    Port 443\n",
            False,
        ),
    ],
)
def test_fleet_member_ssh_route_allows_only_github_alternate_443(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    config_body: str,
    expected_route: bool,
) -> None:
    module = load_publisher()
    home = tmp_path / "home"
    ssh_dir = home / ".ssh"
    ssh_dir.mkdir(parents=True)
    config = ssh_dir / "config"
    config.write_text(config_body, encoding="utf-8")
    config.chmod(0o600)
    monkeypatch.setenv("HOME", str(home))

    command = module._fleet_member_ssh_command()

    assert ("HostName=ssh.github.com" in command) is expected_route
    assert ("Port=443" in command) is expected_route
    assert ("HostKeyAlias=github.com" in command) is expected_route


@pytest.mark.parametrize(
    ("config_body", "expected_names"),
    [
        (
            "Match host github.com\n"
            "    IdentityFile ~/.ssh/match-host\n",
            ("match-host",),
        ),
        (
            "Host other.example\n"
            "    IdentityFile ~/.ssh/other\n"
            "Match all\n"
            "    IdentityFile ~/.ssh/match-all\n",
            ("match-all",),
        ),
        (
            "Match host !github.com,*\n"
            "    IdentityFile ~/.ssh/blocked\n",
            (),
        ),
    ],
)
def test_fleet_member_ssh_match_supports_bounded_host_and_all(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    config_body: str,
    expected_names: tuple[str, ...],
) -> None:
    module = load_publisher()
    home = tmp_path / "home"
    ssh_dir = home / ".ssh"
    ssh_dir.mkdir(parents=True)
    config = ssh_dir / "config"
    config.write_text(config_body, encoding="utf-8")
    config.chmod(0o600)
    monkeypatch.setenv("HOME", str(home))

    identities = module._fleet_member_ssh_auth_options().get("identity_files", ())

    assert tuple(Path(value).name for value in identities) == expected_names


def test_fleet_member_ssh_include_expands_nested_auth_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_publisher()
    home = tmp_path / "home"
    ssh_dir = home / ".ssh"
    conf_dir = ssh_dir / "conf.d"
    conf_dir.mkdir(parents=True)
    (ssh_dir / "config").write_text(
        "Include ~/.ssh/conf.d/first\n"
        "Host github.com\n"
        "    IdentitiesOnly yes\n",
        encoding="utf-8",
    )
    (conf_dir / "first").write_text(
        "Include ~/.ssh/conf.d/second\n",
        encoding="utf-8",
    )
    (conf_dir / "second").write_text(
        "Host *\n"
        "    IdentityFile ~/.ssh/include-key\n"
        "    CertificateFile ~/.ssh/include-cert.pub\n"
        "    HostName attacker.invalid\n"
        "    ProxyCommand /bin/false\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(home))

    command = module._fleet_member_ssh_command()

    assert str(ssh_dir / "include-key") in command
    assert f"CertificateFile={ssh_dir / 'include-cert.pub'}" in command
    assert "IdentitiesOnly=yes" in command
    assert "attacker.invalid" not in command
    assert "ProxyCommand" not in command
    assert "/bin/false" not in command


def test_fleet_member_ssh_include_rejects_targets_outside_ssh_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_publisher()
    home = tmp_path / "home"
    ssh_dir = home / ".ssh"
    ssh_dir.mkdir(parents=True)
    outside = tmp_path / "outside.conf"
    outside.write_text(
        "Host github.com\n    IdentityFile ~/.ssh/outside-key\n",
        encoding="utf-8",
    )
    (ssh_dir / "config").write_text(
        f"Include {outside}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(home))

    with pytest.raises(RuntimeError, match="must remain under ~/.ssh"):
        module._fleet_member_ssh_auth_options()


@pytest.mark.parametrize(
    ("host_patterns", "expected_identity"),
    [
        ("GitHub.COM", True),
        ("*", True),
        ("github.*", True),
        ("!github.com *", False),
        ("github.com !github.com", False),
        ("*.github.com", False),
        ("attacker-github.com", False),
        ("github.com.evil.example", False),
    ],
)
def test_fleet_member_ssh_host_patterns_require_exact_github_match(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    host_patterns: str,
    expected_identity: bool,
) -> None:
    module = load_publisher()
    home = tmp_path / "home"
    ssh_dir = home / ".ssh"
    ssh_dir.mkdir(parents=True)
    config = ssh_dir / "config"
    config.write_text(
        f"Host {host_patterns}\n"
        "    IdentityFile ~/.ssh/id_ed25519\n",
        encoding="utf-8",
    )
    config.chmod(0o600)
    monkeypatch.setenv("HOME", str(home))

    options = module._fleet_member_ssh_auth_options()

    identities = options.get("identity_files", ())
    if expected_identity:
        assert identities == (str(ssh_dir / "id_ed25519"),)
    else:
        assert identities == ()


def test_fleet_member_ssh_config_rejects_symlink_and_insecure_permissions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_publisher()
    home = tmp_path / "home"
    ssh_dir = home / ".ssh"
    ssh_dir.mkdir(parents=True)
    target = tmp_path / "shared-config"
    target.write_text(
        "Host github.com\n    IdentityFile ~/.ssh/id_ed25519\n",
        encoding="utf-8",
    )
    config = ssh_dir / "config"
    config.symlink_to(target)
    monkeypatch.setenv("HOME", str(home))

    with pytest.raises(RuntimeError, match="configuration is unavailable"):
        module._fleet_member_ssh_auth_options()

    config.unlink()
    config.write_text(
        "Host github.com\n    IdentityFile ~/.ssh/id_ed25519\n",
        encoding="utf-8",
    )
    config.chmod(0o622)
    with pytest.raises(RuntimeError, match="must not be group/world writable"):
        module._fleet_member_ssh_auth_options()


def test_fleet_member_ssh_config_enforces_actual_read_bound(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_publisher()
    home = tmp_path / "home"
    ssh_dir = home / ".ssh"
    ssh_dir.mkdir(parents=True)
    config = ssh_dir / "config"
    config.write_bytes(b"x" * (module._FLEET_MEMBER_SSH_CONFIG_MAX_BYTES + 1))
    config.chmod(0o600)
    monkeypatch.setenv("HOME", str(home))

    with pytest.raises(RuntimeError, match="exceeds bounded size"):
        module._fleet_member_ssh_auth_options()


def test_remote_head_for_entry_uses_bounded_ssh_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_publisher()
    repo, sha = initialize_repository(tmp_path, "member-ssh-auth")
    remote = "git@github.com:heimgewebe/member.git"
    git(repo, "remote", "add", "origin", remote)
    entry = module.RepoEntry(
        key="heimgewebe/member", owner="heimgewebe", repo="member", path=repo, remote=remote
    )
    ssh_env = module._authority_git_env()
    ssh_env["GIT_SSH_COMMAND"] = "/usr/bin/ssh -F /dev/null -i /tmp/member-key"
    observed: dict[str, object] = {}

    monkeypatch.setattr(
        module,
        "_fleet_repo_ssh_env",
        lambda *, remote=None: ssh_env,
    )

    def fake_remote_head(
        repo_path: Path,
        *,
        remote: str = "origin",
        env: dict[str, str] | None = None,
    ) -> tuple[str, str, str]:
        observed["repo_path"] = repo_path
        observed["remote"] = remote
        observed["env"] = env
        return "origin/main", "main", sha

    monkeypatch.setattr(module, "remote_head", fake_remote_head)

    assert module.remote_head_for_entry(entry) == ("origin/main", "main", sha)
    assert observed["remote"] == remote
    assert observed["env"] is ssh_env


def test_remote_head_for_entry_uses_credential_env_for_https(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_publisher()
    repo, sha = initialize_repository(tmp_path, "member-https-credentials")
    remote = "https://github.com/heimgewebe/member.git"
    git(repo, "remote", "add", "origin", remote)
    entry = module.RepoEntry(
        key="heimgewebe/member",
        owner="heimgewebe",
        repo="member",
        path=repo,
        remote=remote,
    )
    credential_env = module._authority_git_env()
    credential_env["GIT_CONFIG_COUNT"] = "1"
    credential_env["GIT_CONFIG_KEY_0"] = "credential.helper"
    credential_env["GIT_CONFIG_VALUE_0"] = "!/bin/true"
    observed: dict[str, object] = {}

    def fake_fleet_repo_git_env(
        repo_path: Path,
        *,
        safe_global_config: Path | None = None,
    ) -> dict[str, str]:
        assert repo_path == repo
        assert safe_global_config is not None
        return credential_env

    monkeypatch.setattr(module, "_fleet_repo_git_env", fake_fleet_repo_git_env)

    def fake_remote_head(
        repo_path: Path,
        *,
        remote: str = "origin",
        env: dict[str, str] | None = None,
    ) -> tuple[str, str, str]:
        observed["repo_path"] = repo_path
        observed["remote"] = remote
        observed["env"] = env
        return "origin/main", "main", sha

    monkeypatch.setattr(module, "remote_head", fake_remote_head)

    assert module.remote_head_for_entry(entry) == ("origin/main", "main", sha)
    assert observed["remote"] == remote
    assert observed["env"] is credential_env


def test_remote_branch_head_ignores_non_ref_diagnostics_without_shared_ref_update(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_publisher()
    repo = tmp_path / "metarepo"
    sha = "a" * 40
    fetched = False
    calls: list[list[str]] = []

    def fake_run(
        argv: list[str],
        cwd: Path | None = None,
        check: bool = True,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal fetched
        calls.append(argv)
        if argv[-3:] == ["--", "origin", "refs/heads/main"]:
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout=(
                    "Warning: Permanently added github.com to known hosts.\n"
                    f"{sha}\trefs/heads/main\n"
                ),
            )
        if argv[-6:] == [
            "fetch",
            "--no-tags",
            "--no-write-fetch-head",
            "--refmap=",
            "origin",
            "refs/heads/main",
        ]:
            fetched = True
            return subprocess.CompletedProcess(argv, 0, stdout="")
        if argv[-3:] == ["rev-parse", "--verify", f"{sha}^{{commit}}"]:
            return subprocess.CompletedProcess(
                argv,
                0 if fetched else 1,
                stdout=f"{sha}\n" if fetched else "",
            )
        raise AssertionError(f"unexpected command: {argv}")

    monkeypatch.setattr(module, "run", fake_run)

    assert module.remote_branch_head(repo, "main") == ("refs/heads/main", "main", sha)
    assert not any(
        "refs/remotes/origin/main" in argument
        for argv in calls
        for argument in argv
    )


def test_remote_branch_head_rejects_branch_that_moves_during_isolated_fetch_when_old_tip_is_local(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_publisher()
    repo = tmp_path / "metarepo"
    old_sha = "a" * 40
    new_sha = "b" * 40
    advertisements = iter((old_sha, new_sha))

    def fake_run(
        argv: list[str],
        cwd: Path | None = None,
        check: bool = True,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        if argv[-3:] == ["--", "origin", "refs/heads/main"]:
            sha = next(advertisements)
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout=f"{sha}\trefs/heads/main\n",
            )
        if argv[-6:] == [
            "fetch",
            "--no-tags",
            "--no-write-fetch-head",
            "--refmap=",
            "origin",
            "refs/heads/main",
        ]:
            return subprocess.CompletedProcess(argv, 0, stdout="")
        if argv[-3:] == ["rev-parse", "--verify", f"{old_sha}^{{commit}}"]:
            return subprocess.CompletedProcess(argv, 0, stdout=f"{old_sha}\n")
        raise AssertionError(f"unexpected command: {argv}")

    monkeypatch.setattr(module, "run", fake_run)

    with pytest.raises(RuntimeError, match="moved during resolution"):
        module.remote_branch_head(repo, "main")


def test_remote_branch_head_fetch_does_not_update_origin_tracking_ref(
    tmp_path: Path,
) -> None:
    module = load_publisher()
    source, first_sha = initialize_repository(tmp_path, "authority-source")
    remote = tmp_path / "authority-remote.git"
    completed = subprocess.run(
        ["git", "clone", "--quiet", "--bare", str(source), str(remote)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout

    checkout = tmp_path / "authority-checkout"
    completed = subprocess.run(
        ["git", "clone", "--quiet", str(remote), str(checkout)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout
    assert git(checkout, "rev-parse", "refs/remotes/origin/main") == first_sha

    tracked = source / "tracked.txt"
    tracked.write_text("second\n", encoding="utf-8")
    git(source, "add", "tracked.txt")
    git(source, "commit", "-m", "second authority commit")
    second_sha = git(source, "rev-parse", "HEAD")
    assert second_sha != first_sha
    assert (
        subprocess.run(
            ["git", "-C", str(checkout), "cat-file", "-e", f"{second_sha}^{{commit}}"],
            check=False,
        ).returncode
        != 0
    )

    completed = subprocess.run(
        [
            "git",
            "--git-dir",
            str(remote),
            "fetch",
            "--quiet",
            "--no-tags",
            str(source),
            second_sha,
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout
    git(remote, "update-ref", "refs/heads/main", second_sha)

    assert module.remote_branch_head(checkout, "main") == (
        "refs/heads/main",
        "main",
        second_sha,
    )
    assert git(checkout, "rev-parse", "refs/remotes/origin/main") == first_sha
    assert (
        subprocess.run(
            ["git", "-C", str(checkout), "cat-file", "-e", f"{second_sha}^{{commit}}"],
            check=False,
        ).returncode
        == 0
    )


def test_remote_head_falls_back_to_existing_local_origin_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    repo = tmp_path / "demo"
    sha = "a" * 40
    validated_url = "git@github.com:heimgewebe/demo.git"
    calls: list[list[str]] = []
    fetched = False

    def fake_run(
        argv: list[str],
        cwd: Path | None = None,
        check: bool = True,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal fetched
        calls.append(argv)
        if argv[-4:] == ["ls-remote", "--symref", validated_url, "HEAD"]:
            return subprocess.CompletedProcess(argv, 0, stdout=f"{sha}\tHEAD\n")
        if argv[-3:] == ["symbolic-ref", "refs/remotes/origin/HEAD", "--short"]:
            return subprocess.CompletedProcess(argv, 0, stdout="origin/release\n")
        if argv[-3:] == ["--", validated_url, "refs/heads/release"]:
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout=f"{sha}\trefs/heads/release\n",
            )
        if argv[-4:] == [
            "fetch",
            "--no-tags",
            validated_url,
            "+refs/heads/release:refs/remotes/origin/release",
        ]:
            fetched = True
            return subprocess.CompletedProcess(argv, 0, stdout="")
        if argv[-3:] == ["rev-parse", "--verify", "refs/remotes/origin/release"]:
            return subprocess.CompletedProcess(
                argv,
                0 if fetched else 1,
                stdout=f"{sha}\n" if fetched else "",
            )
        raise AssertionError(f"unexpected command: {argv}")

    monkeypatch.setattr(module, "run", fake_run)

    assert module.remote_head(repo, remote=validated_url) == (
        "origin/release",
        "release",
        sha,
    )
    assert fetched is True
    assert not any(
        argv[-3:] == ["fetch", validated_url, "--prune"] for argv in calls
    )
    assert not any("set-head" in argv for argv in calls)

def test_remote_head_rejects_fallback_that_disagrees_with_remote_head_sha(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    repo = tmp_path / "stale-local-head"
    advertised_sha = "a" * 40
    fallback_sha = "b" * 40

    def fake_run(
        argv: list[str],
        cwd: Path | None = None,
        check: bool = True,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        if argv[-4:] == ["ls-remote", "--symref", "origin", "HEAD"]:
            return subprocess.CompletedProcess(argv, 0, stdout=f"{advertised_sha}\tHEAD\n")
        if argv[-3:] == ["symbolic-ref", "refs/remotes/origin/HEAD", "--short"]:
            return subprocess.CompletedProcess(argv, 0, stdout="origin/release\n")
        if argv[-3:] == ["--", "origin", "refs/heads/release"]:
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout=f"{fallback_sha}\trefs/heads/release\n",
            )
        if argv[-3:] in (
            ["--", "origin", "refs/heads/main"],
            ["--", "origin", "refs/heads/master"],
        ):
            return subprocess.CompletedProcess(argv, 2, stdout="")
        raise AssertionError(f"unexpected command: {argv}")

    monkeypatch.setattr(module, "run", fake_run)

    with pytest.raises(RuntimeError, match="remote HEAD disagrees"):
        module.remote_head(repo)

def test_remote_head_remains_fail_closed_without_any_default_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    repo = tmp_path / "empty-default"
    calls: list[list[str]] = []

    def fake_run(
        argv: list[str],
        cwd: Path | None = None,
        check: bool = True,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        if argv[-4:] == ["ls-remote", "--symref", "origin", "HEAD"]:
            return subprocess.CompletedProcess(argv, 0, stdout="")
        if argv[-3:] == ["symbolic-ref", "refs/remotes/origin/HEAD", "--short"]:
            return subprocess.CompletedProcess(argv, 1, stdout="")
        if argv[-3:] in (
            ["--", "origin", "refs/heads/main"],
            ["--", "origin", "refs/heads/master"],
        ):
            return subprocess.CompletedProcess(argv, 2, stdout="")
        raise AssertionError(f"unexpected command: {argv}")

    monkeypatch.setattr(module, "run", fake_run)

    with pytest.raises(RuntimeError, match="no remote default branch"):
        module.remote_head(repo)
    assert not any("set-head" in argv for argv in calls)

def test_remote_head_rejects_non_branch_remote_head_symref(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    repo = tmp_path / "malformed"
    sha = "c" * 40
    calls: list[list[str]] = []

    def fake_run(
        argv: list[str],
        cwd: Path | None = None,
        check: bool = True,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        if argv[-4:] == ["ls-remote", "--symref", "origin", "HEAD"]:
            return subprocess.CompletedProcess(
                argv, 0, stdout=f"ref: refs/tags/v1\tHEAD\n{sha}\tHEAD\n"
            )
        raise AssertionError(f"unexpected command: {argv}")

    monkeypatch.setattr(module, "run", fake_run)

    with pytest.raises(RuntimeError, match="does not advertise a branch"):
        module.remote_head(repo)
    assert calls == [
        ["git", "-C", str(repo), "ls-remote", "--symref", "origin", "HEAD"]
    ]


def test_remote_head_rejects_unsafe_advertised_branch_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    repo = tmp_path / "unsafe"
    sha = "d" * 40

    def fake_run(
        argv: list[str],
        cwd: Path | None = None,
        check: bool = True,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        if argv[-4:] == ["ls-remote", "--symref", "origin", "HEAD"]:
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout=f"ref: refs/heads/feat/../escape\tHEAD\n{sha}\tHEAD\n",
            )
        raise AssertionError(f"unexpected command: {argv}")

    monkeypatch.setattr(module, "run", fake_run)

    with pytest.raises(RuntimeError, match="unsafe branch"):
        module.remote_head(repo)


def test_remote_head_fetches_nested_advertised_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    repo = tmp_path / "nested"
    sha = "e" * 40
    advertised_fetched = False

    def fake_run(
        argv: list[str],
        cwd: Path | None = None,
        check: bool = True,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal advertised_fetched
        if argv[-4:] == ["ls-remote", "--symref", "origin", "HEAD"]:
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout=f"ref: refs/heads/release/1.2\tHEAD\n{sha}\tHEAD\n",
            )
        if _is_advertised_branch_fetch(argv, "release/1.2"):
            advertised_fetched = True
            return subprocess.CompletedProcess(argv, 0, stdout="")
        if argv[-3:] == [
            "rev-parse",
            "--verify",
            "refs/remotes/origin/release/1.2",
        ]:
            return subprocess.CompletedProcess(argv, 0, stdout=f"{sha}\n")
        raise AssertionError(f"unexpected command: {argv}")

    monkeypatch.setattr(module, "run", fake_run)

    assert module.remote_head(repo) == ("origin/release/1.2", "release/1.2", sha)
    assert advertised_fetched is True


def test_repoground_tool_head_reuses_bounded_member_transport(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_publisher()
    repo, sha = initialize_repository(tmp_path, "repoground")
    remote = "git@github.com:heimgewebe/repoground.git"
    git(repo, "remote", "add", "origin", remote)
    monkeypatch.setattr(module, "REPOGROUND_REPO", repo)

    ssh_env = module._authority_git_env()
    ssh_env["GIT_SSH_COMMAND"] = "/usr/bin/ssh -F /dev/null -i /tmp/tool-key"
    observed: dict[str, object] = {}

    def fake_ssh_env(*, remote: str | None = None) -> dict[str, str]:
        observed["ssh_remote"] = remote
        return ssh_env

    def fake_remote_head(
        repo_path: Path,
        *,
        remote: str = "origin",
        env: dict[str, str] | None = None,
    ) -> tuple[str, str, str]:
        observed["repo_path"] = repo_path
        observed["remote"] = remote
        observed["env"] = env
        return "origin/main", "main", sha

    monkeypatch.setattr(module, "_fleet_repo_ssh_env", fake_ssh_env)
    monkeypatch.setattr(module, "remote_head", fake_remote_head)

    assert module._repoground_tool_head() == sha
    assert observed["ssh_remote"] == remote
    assert observed["repo_path"] == repo
    assert observed["remote"] == remote
    assert observed["env"] is ssh_env


def test_ensure_tool_worktree_pins_resolved_generator_sha(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_publisher()
    sha = "a" * 40
    tool_wt = tmp_path / "tool-worktree"
    repository = tmp_path / "repoground"
    observed: dict[str, object] = {}

    monkeypatch.setattr(module, "TOOL_WT", tool_wt)
    monkeypatch.setattr(module, "REPOGROUND_REPO", repository)
    monkeypatch.setattr(module, "_repoground_tool_head", lambda: sha)
    monkeypatch.setattr(module, "generator_inputs_sha", lambda path: "b" * 64)

    def fake_prepare(
        path: Path,
        *,
        expected_repo: Path,
        target: str,
    ) -> None:
        observed["path"] = path
        observed["expected_repo"] = expected_repo
        observed["target"] = target

    def fake_run(
        argv: list[str],
        cwd: Path | None = None,
        check: bool = True,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        assert argv[-3:] == ["rev-parse", "HEAD"] or argv[-2:] == ["rev-parse", "HEAD"]
        assert env == module._authority_git_env()
        return subprocess.CompletedProcess(argv, 0, stdout=f"{sha}\n")

    monkeypatch.setattr(module, "prepare_managed_worktree", fake_prepare)
    monkeypatch.setattr(module, "run", fake_run)

    assert module.ensure_tool_worktree() == (sha, "b" * 64)
    assert observed == {
        "path": tool_wt,
        "expected_repo": repository,
        "target": sha,
    }


def test_publication_config_uses_compact_daily_profile(tmp_path: Path) -> None:
    module = load_publisher()
    default = module.RepoEntry(
        key="heimgewebe/demo",
        owner="heimgewebe",
        repo="demo",
        path=tmp_path / "demo",
        remote="git@github.com:heimgewebe/demo.git",
    )
    vault = module.RepoEntry(
        key="heimgewebe/vault-gewebe",
        owner="heimgewebe",
        repo="vault-gewebe",
        path=tmp_path / "vault-gewebe",
        remote="git@github.com:heimgewebe/vault-gewebe.git",
    )

    assert module.publication_config(default) == module.PublicationConfig(
        profile="fleet-context", language_structure=True
    )
    assert module.publication_config(vault) == module.PublicationConfig(
        profile="agent-portable", language_structure=True
    )
    assert module.publication_config(default).as_dict()["language_structure"] is True


def test_fleet_refresh_command_explicitly_opts_into_language_structure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    publication_root = tmp_path / "publications"
    monkeypatch.setattr(module, "PUB_ROOT", publication_root)
    config = module.PublicationConfig(
        profile="fleet-context", language_structure=True
    )

    command = module.build_refresh_command(
        source_wt=tmp_path / "source",
        out_dir=publication_root / "bundle",
        registry_repository="heimgewebe__demo",
        ref_segment="main",
        config=config,
    )

    assert command[0] == sys.executable
    assert command[1] == "-B"
    assert command[command.index("--profile") + 1] == "fleet-context"
    assert "--language-structure" in command
    assert command[command.index("--publication-root") + 1] == str(publication_root)

    disabled = module.build_refresh_command(
        source_wt=tmp_path / "source",
        out_dir=publication_root / "bundle",
        registry_repository="heimgewebe__demo",
        ref_segment="main",
        config=module.PublicationConfig(profile="fleet-context"),
    )
    assert "--language-structure" not in disabled


def allow_no_active_managed_build_leases(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    def evidence(worktree: Path, build: Path) -> dict[str, object]:
        return {
            "authority": "test-exact-path-lease-evidence",
            "database": "test",
            "checked_at_unix": 1,
            "resource_keys": [
                f"path:{worktree.resolve()}",
                f"path:{build.resolve(strict=False)}",
            ],
            "active_leases": [],
            "does_not_establish": ["non-exact resource keys"],
        }

    monkeypatch.setattr(module, "managed_build_lease_evidence", evidence)


def git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(
            f"git command failed rc={completed.returncode}: {args!r}\n{completed.stdout}"
        )
    return completed.stdout.strip()


def initialize_repository(tmp_path: Path, name: str = "repo") -> tuple[Path, str]:
    repo = tmp_path / name
    repo.mkdir()
    completed = subprocess.run(
        ["git", "-C", str(repo), "init", "--initial-branch=main"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if completed.returncode != 0:
        git(repo, "init")
        git(repo, "checkout", "-b", "main")
    git(repo, "config", "user.name", "RepoBrief Test")
    git(repo, "config", "user.email", "repobrief-test@example.invalid")
    (repo / ".gitignore").write_text(
        "ignored.txt\n__pycache__/\n.pytest_cache/\n.ruff_cache/\n*.pyc\n*.pyo\n*.egg-info/\nbuild/\n",
        encoding="utf-8",
    )
    (repo / "tracked.txt").write_text("clean\n", encoding="utf-8")
    git(repo, "add", ".gitignore", "tracked.txt")
    git(repo, "commit", "-m", "initial")
    return repo, git(repo, "rev-parse", "HEAD")


def test_remote_head_fetches_advertised_branch_from_single_branch_clone(
    tmp_path: Path,
) -> None:
    module = load_publisher()
    remote, _ = initialize_repository(tmp_path, "remote")
    git(remote, "checkout", "-b", "gh-pages")
    (remote / "index.html").write_text("preview\n", encoding="utf-8")
    git(remote, "add", "index.html")
    git(remote, "commit", "-m", "preview")
    preview_sha = git(remote, "rev-parse", "HEAD")
    git(remote, "symbolic-ref", "HEAD", "refs/heads/gh-pages")

    clone = tmp_path / "single-branch"
    completed = subprocess.run(
        [
            "git",
            "clone",
            "--single-branch",
            "--branch",
            "main",
            str(remote),
            str(clone),
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(
            f"single-branch clone failed rc={completed.returncode}\n{completed.stdout}"
        )
    tracking = subprocess.run(
        [
            "git",
            "-C",
            str(clone),
            "rev-parse",
            "--verify",
            "refs/remotes/origin/gh-pages",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert tracking.returncode != 0

    assert module.remote_head(clone) == ("origin/gh-pages", "gh-pages", preview_sha)
    assert (
        git(clone, "rev-parse", "--verify", "refs/remotes/origin/gh-pages")
        == preview_sha
    )


def write_managed_recovery_manifest(
    repo: Path, worktree: Path, head: str, path: Path
) -> Path:
    recovery_ref = (
        "refs/grabowski/checkouts/0123456789abcdef/"
        f"{path.parent.name}/head"
    )
    git(repo, "update-ref", recovery_ref, head)
    common_dir = Path(git(repo, "rev-parse", "--git-common-dir"))
    if not common_dir.is_absolute():
        common_dir = (repo / common_dir).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "archive_id": "test-archive",
                "checkout_path": str(worktree.resolve()),
                "git_common_dir": str(common_dir),
                "head": head,
                "repo": str(repo.resolve()),
                "cleanup": {
                    "requires_dry_run": True,
                    "tool": "grabowski_checkout_cleanup",
                },
                "recovery_refs": [
                    {
                        "ref": recovery_ref,
                        "role": "head",
                        "target": head,
                    }
                ],
                "rollback": {"available": True},
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def write_version(
    group: Path, name: str, payload: bytes, mtime: int
) -> tuple[Path, str]:
    version = group / name
    version.mkdir(parents=True)
    manifest = version / "repo_merge.bundle.manifest.json"
    manifest.write_bytes(payload)
    artifact = version / "repo_merge.md"
    artifact.write_bytes(payload * 2)
    os.utime(version, (mtime, mtime))
    digest = hashlib.sha256(payload).hexdigest()
    return version, digest


def write_historical_generation_symlink(
    candidate: Path,
    *,
    bundled: bool = False,
    target_hash: str = "a" * 64,
    generation_root_name: str = ".repobrief-generations",
) -> tuple[Path, Path]:
    bundle_root = candidate / "bundle" if bundled else candidate
    generation = bundle_root / generation_root_name / "legacy-scope"
    target = generation / target_hash
    target.mkdir(parents=True)
    (target / "payload.txt").write_text("historical payload", encoding="utf-8")
    current = generation / "current"
    current.symlink_to(target_hash, target_is_directory=True)
    return current, target


def isolate_retention_roots(
    module: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> dict[str, Path]:
    roots = {
        "publication": tmp_path / "publication",
        "legacy": tmp_path / "legacy",
        "special": tmp_path / "special",
        "state": tmp_path / "state",
        "log": tmp_path / "log",
    }
    monkeypatch.setattr(module, "PUB_ROOT", roots["publication"])
    monkeypatch.setattr(module, "ARCHIVED_LEGACY_OUT_ROOT", roots["legacy"])
    monkeypatch.setattr(module, "ARCHIVED_SPECIAL_OUT_ROOT", roots["special"])
    monkeypatch.setattr(module, "STATE_ROOT", roots["state"])
    monkeypatch.setattr(module, "LOG_ROOT", roots["log"])
    return roots


def test_publisher_uses_only_canonical_active_environment_and_storage() -> None:
    text = PUBLISHER.read_text(encoding="utf-8")
    former_env_prefix = "R" + "B_"
    former_state = "/home/alex/.local/state/" + "repobrief-publish/fleet"
    former_log = "/home/alex/logs/" + "repobrief-publish"
    former_quarantine = "." + "rb-prune-quarantine"

    assert former_env_prefix not in text
    assert former_state not in text
    assert former_log not in text
    assert former_quarantine not in text
    assert "/home/alex/.local/state/repoground-publish/fleet" in text
    assert "/home/alex/logs/repoground-publish" in text
    assert ".repoground-prune-quarantine" in text
    assert "ARCHIVED_LEGACY_OUT_ROOT" in text
    assert "ARCHIVED_SPECIAL_OUT_ROOT" in text


def test_fingerprint_is_stable_and_covers_all_output_inputs() -> None:
    module = load_publisher()
    config = module.PublicationConfig(profile="full-max")
    first, identity = module.build_fingerprint(
        source_sha="a" * 40,
        generator_inputs_sha="b" * 40,
        publication_repository="heimgewebe__demo",
        config=config,
    )
    repeated, repeated_identity = module.build_fingerprint(
        source_sha="a" * 40,
        generator_inputs_sha="b" * 40,
        publication_repository="heimgewebe__demo",
        config=config,
    )
    source_changed, _ = module.build_fingerprint(
        source_sha="c" * 40,
        generator_inputs_sha="b" * 40,
        publication_repository="heimgewebe__demo",
        config=config,
    )
    tool_changed, _ = module.build_fingerprint(
        source_sha="a" * 40,
        generator_inputs_sha="d" * 40,
        publication_repository="heimgewebe__demo",
        config=config,
    )
    config_changed, _ = module.build_fingerprint(
        source_sha="a" * 40,
        generator_inputs_sha="b" * 40,
        publication_repository="heimgewebe__demo",
        config=module.PublicationConfig(profile="agent-portable"),
    )

    assert first == repeated
    assert identity == repeated_identity
    assert len(first) == 64
    namespace_changed, _ = module.build_fingerprint(
        source_sha="a" * 40,
        generator_inputs_sha="b" * 40,
        publication_repository="other__demo",
        config=config,
    )

    assert (
        len({first, source_changed, tool_changed, config_changed, namespace_changed})
        == 5
    )


def test_generator_inputs_sha_ignores_service_and_test_only_changes(
    tmp_path: Path,
) -> None:
    module = load_publisher()
    repo, _ = initialize_repository(tmp_path, "lenskit")
    tracked = {
        "merger/repoground/__init__.py": "",
        "merger/repoground/cli/__init__.py": "",
        "merger/repoground/cli/ground.py": "entrypoint\n",
        "merger/repoground/cli/cmd_ground.py": "command\n",
        "merger/repoground/core/merge.py": "generator v1\n",
        "merger/repoground/contracts/bundle.json": "{}\n",
        "merger/repoground/retrieval/query.py": "query v1\n",
        "merger/repoground/service/app.py": "service v1\n",
        "merger/repoground/tests/test_only.py": "test v1\n",
    }
    for relative, content in tracked.items():
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "generator baseline")
    baseline = module.generator_inputs_sha(repo)

    (repo / "merger/repoground/service/app.py").write_text(
        "service v2\n", encoding="utf-8"
    )
    (repo / "merger/repoground/tests/test_only.py").write_text(
        "test v2\n", encoding="utf-8"
    )
    git(repo, "add", ".")
    git(repo, "commit", "-m", "non-generator changes")
    assert module.generator_inputs_sha(repo) == baseline

    (repo / "merger/repoground/core/merge.py").write_text(
        "generator v2\n", encoding="utf-8"
    )
    git(repo, "add", ".")
    git(repo, "commit", "-m", "generator change")
    assert module.generator_inputs_sha(repo) != baseline


def test_version_dirs_accepts_only_declared_version_names(tmp_path: Path) -> None:
    module = load_publisher()
    group = tmp_path / "group"
    old = group / "20260714T100000Z"
    new = group / "20260714T110000Z-abcdef123456"
    old.mkdir(parents=True)
    new.mkdir()
    os.utime(old, (100, 100))
    os.utime(new, (200, 200))

    assert module.version_dirs(group) == [new, old]

    (group / "scratch").mkdir()
    with pytest.raises(RuntimeError, match="unexpected retention entries"):
        module.version_dirs(group)


def test_prune_group_is_dry_run_by_default_and_reports_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    roots = isolate_retention_roots(module, tmp_path, monkeypatch)
    group = roots["publication"] / "bundles" / "demo" / "main"
    versions = [
        write_version(group, f"20260714T10000{index}Z", bytes([index + 1]), index)[0]
        for index in range(5)
    ]

    report = module.prune_group(group, keep=3, apply=False, protected=set())

    assert len(report["would_remove"]) == 2
    assert report["would_remove_bytes"] > 0
    assert report["removed"] == []
    assert all(path.exists() for path in versions)
    assert not module.prune_transaction_root().exists()


def test_prune_group_keeps_newest_three_and_protected_older_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    roots = isolate_retention_roots(module, tmp_path, monkeypatch)
    group = roots["publication"] / "bundles" / "demo" / "main"
    versions = [
        write_version(group, f"20260714T10000{index}Z", bytes([index + 1]), index)[0]
        for index in range(6)
    ]
    protected_file = versions[1] / "repo_merge.md"

    report = module.prune_group(
        group,
        keep=3,
        apply=True,
        protected={protected_file.resolve()},
    )

    assert set(module.version_dirs(group)) == {
        versions[5],
        versions[4],
        versions[3],
        versions[1],
    }
    assert str(versions[1]) in report["protected_old"]
    assert report["removed_bytes"] > 0
    transactions = sorted(module.prune_transaction_root().glob("*.json"))
    assert len(transactions) == 2
    assert all(
        json.loads(path.read_text())["state"] == "deleted" for path in transactions
    )


def test_current_prune_keeps_localized_hashes_for_history_protection_and_stable_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    roots = isolate_retention_roots(module, tmp_path, monkeypatch)
    publication_root = roots["publication"]
    group = publication_root / "bundles" / "heimgewebe__demo" / "main"
    versions_and_hashes = [
        write_version(
            group,
            f"20260714T10000{index}Z",
            f"manifest-{index}".encode(),
            index,
        )
        for index in range(5)
    ]
    protected_version, protected_hash = versions_and_hashes[0]
    stable_version, stable_hash = versions_and_hashes[1]
    stable_target = stable_version / "repo_merge.bundle.manifest.json"
    newest_hashes = {digest for _, digest in versions_and_hashes[-3:]}
    stable_manifest = (
        publication_root
        / "external"
        / "repobrief"
        / "heimgewebe__demo"
        / "main"
        / "manifest.json"
    )
    stable_manifest.parent.mkdir(parents=True)
    stable_manifest.write_text(
        json.dumps(
            {
                "bundleManifest": {
                    "path": os.path.relpath(stable_target, stable_manifest.parent)
                }
            }
        ),
        encoding="utf-8",
    )
    localized = publication_root / "external" / "_bundles" / "heimgewebe__demo" / "main"
    unused_hash = "e" * 64
    for digest in newest_hashes | {protected_hash, stable_hash, unused_hash}:
        candidate = localized / digest
        candidate.mkdir(parents=True)
        (candidate / "artifact").write_text(digest, encoding="utf-8")

    report = module.prune_current_group(
        group,
        repository="heimgewebe__demo",
        ref="main",
        keep=3,
        apply=True,
        protected={(protected_version / "repo_merge.md").resolve()},
    )

    assert protected_version.is_dir()
    assert stable_version.is_dir()
    assert (localized / protected_hash).is_dir()
    assert (localized / stable_hash).is_dir()
    assert all((localized / digest).is_dir() for digest in newest_hashes)
    assert str(stable_target) in report["stable_manifest_targets"]
    assert not (localized / unused_hash).exists()
    assert str(localized / unused_hash) in report["localized_removed"]


def test_stable_manifest_target_is_fail_closed_for_missing_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    publication_root = tmp_path / "publication"
    monkeypatch.setattr(module, "PUB_ROOT", publication_root)
    manifest = (
        publication_root
        / "external"
        / "repobrief"
        / "heimgewebe__demo"
        / "main"
        / "manifest.json"
    )
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps({"bundleManifest": {"path": "../../../../missing.json"}}),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="target is unavailable"):
        module.stable_manifest_target(manifest)


def test_global_reachability_uses_only_canonical_owner_qualified_manifests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    publication_root = tmp_path / "publication"
    monkeypatch.setattr(module, "PUB_ROOT", publication_root)

    canonical_target = (
        publication_root
        / "bundles"
        / "heimgewebe__demo"
        / "main"
        / "version"
        / "manifest.json"
    )
    canonical_target.parent.mkdir(parents=True)
    canonical_target.write_text("{}", encoding="utf-8")
    canonical_manifest = (
        publication_root
        / "external"
        / "repobrief"
        / "heimgewebe__demo"
        / "main"
        / "manifest.json"
    )
    canonical_manifest.parent.mkdir(parents=True)
    canonical_manifest.write_text(
        json.dumps(
            {
                "bundleManifest": {
                    "path": os.path.relpath(canonical_target, canonical_manifest.parent)
                }
            }
        ),
        encoding="utf-8",
    )

    frozen_manifest = (
        publication_root / "external" / "repobrief" / "demo" / "main" / "manifest.json"
    )
    frozen_manifest.parent.mkdir(parents=True)
    frozen_manifest.write_text(
        json.dumps({"bundleManifest": {"path": "../../../../missing.json"}}),
        encoding="utf-8",
    )

    assert module.canonical_stable_manifest_paths() == [canonical_manifest]
    assert module.all_stable_manifest_targets() == {canonical_target.resolve()}


def test_managed_worktree_accepts_only_clean_detached_expected_repository(
    tmp_path: Path,
) -> None:
    module = load_publisher()
    repo, sha = initialize_repository(tmp_path)
    worktree = tmp_path / "managed"
    git(repo, "worktree", "add", "--detach", str(worktree), sha)

    module.assert_managed_worktree_clean(worktree, repo)
    module.prepare_managed_worktree(worktree, expected_repo=repo, target=sha)

    assert git(worktree, "rev-parse", "HEAD") == sha
    detached = subprocess.run(
        ["git", "-C", str(worktree), "symbolic-ref", "--quiet", "HEAD"],
        check=False,
    )
    assert detached.returncode != 0


def test_managed_worktree_refuses_dirty_untracked_and_ignored_content(
    tmp_path: Path,
) -> None:
    module = load_publisher()
    repo, sha = initialize_repository(tmp_path)
    worktree = tmp_path / "managed"
    git(repo, "worktree", "add", "--detach", str(worktree), sha)
    tracked = worktree / "tracked.txt"
    tracked.write_text("foreign change\n", encoding="utf-8")
    untracked = worktree / "untracked.txt"
    untracked.write_text("preserve me\n", encoding="utf-8")
    ignored = worktree / "ignored.txt"
    ignored.write_text("preserve me too\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="not clean; refusing reset or cleanup"):
        module.prepare_managed_worktree(worktree, expected_repo=repo, target=sha)

    assert tracked.read_text(encoding="utf-8") == "foreign change\n"
    assert untracked.read_text(encoding="utf-8") == "preserve me\n"
    assert ignored.read_text(encoding="utf-8") == "preserve me too\n"


def test_managed_worktree_cleanup_removes_only_bounded_disposable_artifacts(
    tmp_path: Path,
) -> None:
    module = load_publisher()
    repo, sha = initialize_repository(tmp_path)
    worktree = tmp_path / "managed"
    git(repo, "worktree", "add", "--detach", str(worktree), sha)

    pycache = worktree / "pkg" / "__pycache__"
    pycache.mkdir(parents=True)
    (pycache / "module.cpython-312.pyc").write_bytes(b"cache")
    pytest_cache = worktree / ".pytest_cache"
    pytest_cache.mkdir()
    (pytest_cache / "README.md").write_text("pytest cache\n", encoding="utf-8")
    ruff_cache = worktree / ".ruff_cache"
    ruff_cache.mkdir()
    (ruff_cache / "CACHEDIR.TAG").write_text("ruff cache\n", encoding="utf-8")
    egg_info = worktree / "src" / "demo.egg-info"
    egg_info.mkdir(parents=True)
    (egg_info / "PKG-INFO").write_text("Metadata-Version: 2.4\n", encoding="utf-8")
    loose = worktree / "loose.pyc"
    loose.write_bytes(b"cache")
    build = worktree / "build"
    build.mkdir()

    removed = module.cleanup_managed_disposable_artifacts(worktree, repo)

    assert removed == [
        "build",
        ".pytest_cache",
        ".ruff_cache",
        "loose.pyc",
        "pkg/__pycache__",
        "src/demo.egg-info",
    ]
    assert not pycache.exists()
    assert not pytest_cache.exists()
    assert not ruff_cache.exists()
    assert not egg_info.exists()
    assert not loose.exists()
    assert not build.exists()
    module.assert_managed_worktree_clean(worktree, repo)


def test_managed_worktree_cleanup_rejects_unrelated_and_nonempty_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    repo, sha = initialize_repository(tmp_path)
    worktree = tmp_path / "managed"
    git(repo, "worktree", "add", "--detach", str(worktree), sha)

    unrelated = worktree / "notes.txt"
    unrelated.write_text("preserve\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="not clean; refusing reset or cleanup"):
        module.cleanup_managed_disposable_artifacts(worktree, repo)
    assert unrelated.read_text(encoding="utf-8") == "preserve\n"
    unrelated.unlink()

    build = worktree / "build"
    build.mkdir()
    payload = build / "artifact.bin"
    payload.write_bytes(b"preserve")
    ruff_cache = worktree / ".ruff_cache"
    ruff_cache.mkdir()
    (ruff_cache / "CACHEDIR.TAG").write_text("preserve", encoding="utf-8")
    monkeypatch.setattr(module, "STATE_ROOT", tmp_path / "state")
    with pytest.raises(RuntimeError, match="managed build residue blocked") as excinfo:
        module.cleanup_managed_disposable_artifacts(worktree, repo)
    blocker = json.loads(str(excinfo.value).split(": ", 1)[1])
    assert blocker["classification"] == "unknown"
    assert blocker["automatic_mutation_authorized"] is False
    assert payload.read_bytes() == b"preserve"
    assert (ruff_cache / "CACHEDIR.TAG").read_text(encoding="utf-8") == "preserve"



def test_atomic_write_json_fsyncs_parent_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_publisher()
    path = tmp_path / "receipts" / "fleet-last.json"
    observed_modes: list[int] = []
    real_fsync = module.os.fsync

    def tracking_fsync(descriptor: int) -> None:
        observed_modes.append(module.os.fstat(descriptor).st_mode)
        real_fsync(descriptor)

    monkeypatch.setattr(module.os, "fsync", tracking_fsync)

    module.atomic_write_json(path, {"status": "ok"})

    assert path.is_file()
    assert any(stat.S_ISDIR(mode) for mode in observed_modes)


def test_atomic_create_json_preserves_concurrent_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    path = tmp_path / "private" / "receipt.json"
    original_fsync = module.os.fsync
    calls = 0

    def fsync_with_replacement(descriptor: int) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            original_fsync(descriptor)
            return
        path.unlink()
        path.write_bytes(b"attacker-replacement")
        raise OSError("directory fsync failed after concurrent replacement")

    monkeypatch.setattr(module.os, "fsync", fsync_with_replacement)
    with pytest.raises(OSError, match="directory fsync failed"):
        module.atomic_create_json(path, {"kind": "test"})
    assert path.read_bytes() == b"attacker-replacement"


def test_managed_build_durable_retain_is_exact_bounded_and_non_mutating(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    repo, sha = initialize_repository(tmp_path, "repo")
    source_root = tmp_path / "sources"
    source_root.mkdir()
    worktree = source_root / "heimgewebe__demo__main"
    git(repo, "worktree", "add", "--detach", str(worktree), sha)
    state_root = tmp_path / "state"
    monkeypatch.setattr(module, "SOURCE_ROOT", source_root)
    monkeypatch.setattr(module, "STATE_ROOT", state_root)
    archive_root = tmp_path / "archives"
    archive_root.mkdir()
    monkeypatch.setattr(module, "GRABOWSKI_CHECKOUT_ARCHIVE_ROOT", archive_root)
    monkeypatch.setattr(
        module, "repository_key_for_path", lambda _repo: "heimgewebe/demo"
    )
    allow_no_active_managed_build_leases(module, monkeypatch)
    build = worktree / "build"
    build.mkdir()
    payload = build / "artifact.bin"
    payload.write_bytes(b"historical-unknown")
    entry = module.RepoEntry(
        key="heimgewebe/demo",
        owner="heimgewebe",
        repo="demo",
        path=repo,
        remote="git@github.com:heimgewebe/demo.git",
    )
    review_after = int(time.time()) + 7200
    recovery_manifest = write_managed_recovery_manifest(
        repo,
        worktree,
        sha,
        archive_root / "test-archive" / "manifest.json",
    )

    result = module.record_managed_build_durable_retain(
        entry,
        "main",
        task_id="OPERATOR-ECOSYSTEM-REDUNDANCY-V1-T053",
        reason="Historical bytes lack publisher provenance; retain for bounded review.",
        review_after_unix=review_after,
        recovery_manifest=recovery_manifest,
    )
    replay = module.record_managed_build_durable_retain(
        entry,
        "main",
        task_id="OPERATOR-ECOSYSTEM-REDUNDANCY-V1-T053",
        reason="Historical bytes lack publisher provenance; retain for bounded review.",
        review_after_unix=review_after,
        recovery_manifest=recovery_manifest,
    )

    assert result["idempotent_replay"] is False
    assert replay["idempotent_replay"] is True
    decision_path = module.managed_build_retain_decision_path(worktree)
    assert decision_path.stat().st_mode & 0o777 == 0o600
    decision = json.loads(decision_path.read_text(encoding="utf-8"))
    assert decision["decision"] == "durable-retain"
    assert decision["automatic_mutation_authorized"] is False
    assert decision["task_id"] == "OPERATOR-ECOSYSTEM-REDUNDANCY-V1-T053"

    with pytest.raises(RuntimeError, match="managed build residue blocked") as excinfo:
        module.cleanup_managed_disposable_artifacts(worktree, repo)
    blocker = module.parse_managed_build_blocker(excinfo.value)
    assert blocker is not None
    assert blocker["classification"] == "durable-retain"
    assert blocker["retain_decision"]["sha256"] == module.canonical_sha256(decision)
    assert payload.read_bytes() == b"historical-unknown"

    payload.write_bytes(b"changed-after-decision")
    with pytest.raises(RuntimeError, match="managed build residue blocked") as excinfo:
        module.cleanup_managed_disposable_artifacts(worktree, repo)
    changed = module.parse_managed_build_blocker(excinfo.value)
    assert changed is not None
    assert changed["classification"] == "unknown"
    assert changed["reason"] == (
        "managed build retain decision no longer matches build snapshot"
    )
    assert payload.read_bytes() == b"changed-after-decision"


def test_managed_build_durable_retain_review_due_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    repo, sha = initialize_repository(tmp_path, "repo")
    source_root = tmp_path / "sources"
    source_root.mkdir()
    worktree = source_root / "heimgewebe__demo__main"
    git(repo, "worktree", "add", "--detach", str(worktree), sha)
    monkeypatch.setattr(module, "SOURCE_ROOT", source_root)
    monkeypatch.setattr(module, "STATE_ROOT", tmp_path / "state")
    archive_root = tmp_path / "archives"
    archive_root.mkdir()
    monkeypatch.setattr(module, "GRABOWSKI_CHECKOUT_ARCHIVE_ROOT", archive_root)
    monkeypatch.setattr(
        module, "repository_key_for_path", lambda _repo: "heimgewebe/demo"
    )
    allow_no_active_managed_build_leases(module, monkeypatch)
    build = worktree / "build"
    build.mkdir()
    (build / "artifact.bin").write_bytes(b"retain")
    entry = module.RepoEntry(
        key="heimgewebe/demo",
        owner="heimgewebe",
        repo="demo",
        path=repo,
        remote="git@github.com:heimgewebe/demo.git",
    )
    review_after = int(time.time()) + 3700
    recovery_manifest = write_managed_recovery_manifest(
        repo,
        worktree,
        sha,
        archive_root / "test-archive" / "manifest.json",
    )
    module.record_managed_build_durable_retain(
        entry,
        "main",
        task_id="OPERATOR-ECOSYSTEM-REDUNDANCY-V1-T053",
        reason="Bounded retain decision.",
        review_after_unix=review_after,
        recovery_manifest=recovery_manifest,
    )
    monkeypatch.setattr(module.time, "time", lambda: review_after)

    with pytest.raises(RuntimeError, match="review is due"):
        module.record_managed_build_durable_retain(
            entry,
            "main",
            task_id="OPERATOR-ECOSYSTEM-REDUNDANCY-V1-T053",
            reason="Bounded retain decision.",
            review_after_unix=review_after,
            recovery_manifest=recovery_manifest,
        )

    with pytest.raises(RuntimeError, match="managed build residue blocked") as excinfo:
        module.cleanup_managed_disposable_artifacts(worktree, repo)
    blocker = module.parse_managed_build_blocker(excinfo.value)
    assert blocker is not None
    assert blocker["classification"] == "unknown"
    assert blocker["reason"] == "managed build retain decision review is due"


def test_managed_build_residue_with_exact_stale_provenance_is_quarantined(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    repo, sha = initialize_repository(tmp_path, "repo")
    source_root = tmp_path / "sources"
    source_root.mkdir()
    worktree = source_root / "managed"
    git(repo, "worktree", "add", "--detach", str(worktree), sha)
    state_root = tmp_path / "state"
    monkeypatch.setattr(module, "SOURCE_ROOT", source_root)
    monkeypatch.setattr(module, "STATE_ROOT", state_root)
    monkeypatch.setattr(module, "MANAGED_BUILD_RESIDUE_STALE_SECONDS", 0)
    allow_no_active_managed_build_leases(module, monkeypatch)

    armed = module.arm_managed_build_residue_provenance(worktree, repo)
    assert armed is not None
    build = worktree / "build"
    build.mkdir()
    payload = build / "artifact.bin"
    payload.write_bytes(b"publisher-owned")
    module.finalize_managed_build_residue_provenance(armed, worktree, repo)

    removed = module.cleanup_managed_disposable_artifacts(worktree, repo)

    assert len(removed) == 1
    assert removed[0].startswith("build->quarantine:")
    quarantine = Path(removed[0].split(":", 1)[1])
    assert not build.exists()
    assert (quarantine / "artifact.bin").read_bytes() == b"publisher-owned"
    assert not module.managed_build_residue_record_path(worktree).exists()
    receipts = list((state_root / "managed-build-quarantines").glob("*.json"))
    assert len(receipts) == 1
    receipt = json.loads(receipts[0].read_text(encoding="utf-8"))
    assert receipt["automatic_deletion_authorized"] is False
    assert receipt["classification"] == "managed-stale"
    module.assert_managed_worktree_clean(worktree, repo)


def test_managed_build_residue_fresh_or_changed_stays_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    repo, sha = initialize_repository(tmp_path, "repo")
    source_root = tmp_path / "sources"
    source_root.mkdir()
    worktree = source_root / "managed"
    git(repo, "worktree", "add", "--detach", str(worktree), sha)
    monkeypatch.setattr(module, "SOURCE_ROOT", source_root)
    monkeypatch.setattr(module, "STATE_ROOT", tmp_path / "state")
    monkeypatch.setattr(module, "MANAGED_BUILD_RESIDUE_STALE_SECONDS", 3600)
    allow_no_active_managed_build_leases(module, monkeypatch)

    armed = module.arm_managed_build_residue_provenance(worktree, repo)
    assert armed is not None
    build = worktree / "build"
    build.mkdir()
    payload = build / "artifact.bin"
    payload.write_bytes(b"first")
    module.finalize_managed_build_residue_provenance(armed, worktree, repo)

    with pytest.raises(RuntimeError, match="publisher-owned but not stale"):
        module.cleanup_managed_disposable_artifacts(worktree, repo)
    assert payload.read_bytes() == b"first"

    monkeypatch.setattr(module, "MANAGED_BUILD_RESIDUE_STALE_SECONDS", 0)
    allow_no_active_managed_build_leases(module, monkeypatch)
    payload.write_bytes(b"changed")
    with pytest.raises(RuntimeError, match="changed after publisher observation"):
        module.cleanup_managed_disposable_artifacts(worktree, repo)
    assert payload.read_bytes() == b"changed"


@pytest.mark.parametrize("resource_schema_version", ["2", "3"])
@pytest.mark.parametrize("lease_target", ["worktree", "build"])
def test_exact_active_managed_build_lease_blocks_quarantine(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    lease_target: str,
    resource_schema_version: str,
) -> None:
    module = load_publisher()
    repo, sha = initialize_repository(tmp_path, "repo")
    source_root = tmp_path / "sources"
    source_root.mkdir()
    worktree = source_root / "managed"
    git(repo, "worktree", "add", "--detach", str(worktree), sha)
    state_root = tmp_path / "state"
    monkeypatch.setattr(module, "SOURCE_ROOT", source_root)
    monkeypatch.setattr(module, "STATE_ROOT", state_root)
    monkeypatch.setattr(module, "MANAGED_BUILD_RESIDUE_STALE_SECONDS", 0)
    build = worktree / "build"
    armed = module.arm_managed_build_residue_provenance(worktree, repo)
    assert armed is not None
    build.mkdir()
    payload = build / "artifact.bin"
    payload.write_bytes(b"leased")
    module.finalize_managed_build_residue_provenance(armed, worktree, repo)

    database = tmp_path / "resources.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE leases(
                resource_key TEXT PRIMARY KEY,
                owner_id TEXT NOT NULL,
                purpose TEXT NOT NULL,
                acquired_at_unix INTEGER NOT NULL,
                updated_at_unix INTEGER NOT NULL,
                expires_at_unix INTEGER NOT NULL,
                metadata_sha256 TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                reclaimed_from_owner TEXT
            );
            """
        )
        connection.execute(
            "INSERT INTO metadata(key, value) VALUES('schema_version', ?)",
            (resource_schema_version,),
        )
        target = worktree if lease_target == "worktree" else build
        now = int(time.time())
        connection.execute(
            "INSERT INTO leases VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                f"path:{target.resolve()}",
                "operator:foreign-active-work",
                "test active lease",
                now,
                now,
                now + 3600,
                "0" * 64,
                "{}",
                None,
            ),
        )
    monkeypatch.setattr(module, "GRABOWSKI_RESOURCE_DB", database)

    with pytest.raises(RuntimeError, match="managed build residue blocked") as excinfo:
        module.cleanup_managed_disposable_artifacts(worktree, repo)

    blocker = module.parse_managed_build_blocker(excinfo.value)
    assert blocker is not None
    assert blocker["classification"] == "active-legitimate"
    assert blocker["reason"] == "exact active Grabowski path lease"
    assert blocker["lease_evidence"]["authority"] == (
        f"grabowski-resources-sqlite-v{resource_schema_version}"
    )
    leases = blocker["lease_evidence"]["active_leases"]
    assert leases == [
        {
            "resource_key": f"path:{target.resolve()}",
            "owner_id": "operator:foreign-active-work",
            "expires_at_unix": now + 3600,
            "updated_at_unix": now,
        }
    ]
    assert payload.read_bytes() == b"leased"
    assert not (source_root / module.MANAGED_BUILD_QUARANTINE_DIR_NAME).exists()


def test_managed_build_lease_evidence_rejects_unknown_resource_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    worktree = tmp_path / "managed"
    build = worktree / "build"
    build.mkdir(parents=True)
    database = tmp_path / "resources.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE leases(
                resource_key TEXT PRIMARY KEY,
                owner_id TEXT NOT NULL,
                expires_at_unix INTEGER NOT NULL,
                updated_at_unix INTEGER NOT NULL
            );
            """
        )
        connection.execute(
            "INSERT INTO metadata(key, value) VALUES('schema_version', '4')"
        )
    monkeypatch.setattr(module, "GRABOWSKI_RESOURCE_DB", database)

    with pytest.raises(RuntimeError, match="canonical Grabowski lease schema is incompatible"):
        module.managed_build_lease_evidence(worktree, build)


def test_managed_build_quarantine_rolls_back_when_receipt_write_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    repo, sha = initialize_repository(tmp_path, "repo")
    source_root = tmp_path / "sources"
    source_root.mkdir()
    worktree = source_root / "managed"
    git(repo, "worktree", "add", "--detach", str(worktree), sha)
    monkeypatch.setattr(module, "SOURCE_ROOT", source_root)
    monkeypatch.setattr(module, "STATE_ROOT", tmp_path / "state")
    monkeypatch.setattr(module, "MANAGED_BUILD_RESIDUE_STALE_SECONDS", 0)
    allow_no_active_managed_build_leases(module, monkeypatch)
    armed = module.arm_managed_build_residue_provenance(worktree, repo)
    assert armed is not None
    build = worktree / "build"
    build.mkdir()
    payload = build / "artifact.bin"
    payload.write_bytes(b"rollback")
    module.finalize_managed_build_residue_provenance(armed, worktree, repo)

    real_atomic_write = module.atomic_write_json

    def fail_receipt(path: Path, value: dict[str, object]) -> None:
        if path.parent.name == "managed-build-quarantines":
            raise OSError("simulated receipt failure")
        real_atomic_write(path, value)

    monkeypatch.setattr(module, "atomic_write_json", fail_receipt)
    with pytest.raises(OSError, match="simulated receipt failure"):
        module.cleanup_managed_disposable_artifacts(worktree, repo)
    assert payload.read_bytes() == b"rollback"
    restored = json.loads(
        module.managed_build_residue_record_path(worktree).read_text(encoding="utf-8")
    )
    assert restored["status"] == "observed"


def test_interrupted_managed_build_quarantine_is_reconciled_next_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    repo, sha = initialize_repository(tmp_path, "repo")
    source_root = tmp_path / "sources"
    source_root.mkdir()
    worktree = source_root / "managed"
    git(repo, "worktree", "add", "--detach", str(worktree), sha)
    state_root = tmp_path / "state"
    monkeypatch.setattr(module, "SOURCE_ROOT", source_root)
    monkeypatch.setattr(module, "STATE_ROOT", state_root)
    monkeypatch.setattr(module, "MANAGED_BUILD_RESIDUE_STALE_SECONDS", 0)
    allow_no_active_managed_build_leases(module, monkeypatch)
    armed = module.arm_managed_build_residue_provenance(worktree, repo)
    assert armed is not None
    build = worktree / "build"
    build.mkdir()
    (build / "artifact.bin").write_bytes(b"interrupted")
    module.finalize_managed_build_residue_provenance(armed, worktree, repo)
    classification = module.classify_managed_build_residue(build, worktree, repo)
    transaction_id = "a" * 32
    quarantine_root = module.managed_build_residue_quarantine_root(worktree)
    transaction_root = quarantine_root / transaction_id
    transaction_root.mkdir(mode=0o700)
    worktree_quarantine = transaction_root / worktree.name
    worktree_quarantine.mkdir(mode=0o700)
    quarantine = worktree_quarantine / "build"
    record_path = classification["record_path"]
    planned = dict(classification["record"])
    planned.update(
        {
            "status": "quarantine-planned",
            "transaction_id": transaction_id,
            "quarantine": str(quarantine),
            "quarantine_planned_at_unix": 1,
            "lease_evidence": classification["lease_evidence"],
        }
    )
    module.atomic_write_json(record_path, planned)
    planned_receipt = module.managed_build_quarantine_receipt(
        transaction_id=transaction_id,
        status="planned",
        build=build,
        quarantine=quarantine,
        record_path=record_path,
        snapshot=classification["snapshot"],
        classification="managed-stale",
        lease_evidence=classification["lease_evidence"],
    )
    receipt_path = module.managed_build_quarantine_receipt_path(transaction_id)
    module.atomic_write_json(receipt_path, planned_receipt)
    os.replace(build, quarantine)

    removed = module.cleanup_managed_disposable_artifacts(worktree, repo)

    assert removed == [f"build->quarantine:{quarantine}"]
    assert not build.exists()
    assert (quarantine / "artifact.bin").read_bytes() == b"interrupted"
    assert not record_path.exists()
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["status"] == "quarantined"
    assert receipt["reconciled_after_interruption"] is True


def test_planned_quarantine_without_move_resumes_safely(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    repo, sha = initialize_repository(tmp_path, "repo")
    source_root = tmp_path / "sources"
    source_root.mkdir()
    worktree = source_root / "managed"
    git(repo, "worktree", "add", "--detach", str(worktree), sha)
    state_root = tmp_path / "state"
    monkeypatch.setattr(module, "SOURCE_ROOT", source_root)
    monkeypatch.setattr(module, "STATE_ROOT", state_root)
    monkeypatch.setattr(module, "MANAGED_BUILD_RESIDUE_STALE_SECONDS", 0)
    allow_no_active_managed_build_leases(module, monkeypatch)
    armed = module.arm_managed_build_residue_provenance(worktree, repo)
    assert armed is not None
    build = worktree / "build"
    build.mkdir()
    (build / "artifact.bin").write_bytes(b"not-moved")
    module.finalize_managed_build_residue_provenance(armed, worktree, repo)
    classification = module.classify_managed_build_residue(build, worktree, repo)
    transaction_id = "b" * 32
    quarantine_root = module.managed_build_residue_quarantine_root(worktree)
    transaction_root = quarantine_root / transaction_id
    transaction_root.mkdir(mode=0o700)
    worktree_quarantine = transaction_root / worktree.name
    worktree_quarantine.mkdir(mode=0o700)
    quarantine = worktree_quarantine / "build"
    record_path = classification["record_path"]
    planned = dict(classification["record"])
    planned.update(
        {
            "status": "quarantine-planned",
            "transaction_id": transaction_id,
            "quarantine": str(quarantine),
            "quarantine_planned_at_unix": 1,
            "lease_evidence": classification["lease_evidence"],
        }
    )
    module.atomic_write_json(record_path, planned)

    removed = module.cleanup_managed_disposable_artifacts(worktree, repo)

    assert len(removed) == 1
    assert removed[0].startswith("build->quarantine:")
    assert not build.exists()
    first_receipt = json.loads(
        module.managed_build_quarantine_receipt_path(transaction_id).read_text(
            encoding="utf-8"
        )
    )
    assert first_receipt["status"] == "not-moved"
    completed = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in (state_root / "managed-build-quarantines").glob("*.json")
    ]
    assert sorted(receipt["status"] for receipt in completed) == [
        "not-moved",
        "quarantined",
    ]


def test_managed_build_provenance_record_symlink_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    repo, sha = initialize_repository(tmp_path, "repo")
    source_root = tmp_path / "sources"
    source_root.mkdir()
    worktree = source_root / "managed"
    git(repo, "worktree", "add", "--detach", str(worktree), sha)
    monkeypatch.setattr(module, "SOURCE_ROOT", source_root)
    monkeypatch.setattr(module, "STATE_ROOT", tmp_path / "state")
    build = worktree / "build"
    build.mkdir()
    (build / "artifact.bin").write_bytes(b"preserve")
    record = module.managed_build_residue_record_path(worktree)
    record.parent.mkdir(parents=True)
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    record.symlink_to(outside)

    with pytest.raises(RuntimeError, match="managed build residue blocked"):
        module.cleanup_managed_disposable_artifacts(worktree, repo)
    assert (build / "artifact.bin").read_bytes() == b"preserve"


def test_managed_build_quarantine_root_symlink_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    repo, sha = initialize_repository(tmp_path, "repo")
    source_root = tmp_path / "sources"
    source_root.mkdir()
    worktree = source_root / "managed"
    git(repo, "worktree", "add", "--detach", str(worktree), sha)
    monkeypatch.setattr(module, "SOURCE_ROOT", source_root)
    monkeypatch.setattr(module, "STATE_ROOT", tmp_path / "state")
    monkeypatch.setattr(module, "MANAGED_BUILD_RESIDUE_STALE_SECONDS", 0)
    allow_no_active_managed_build_leases(module, monkeypatch)
    armed = module.arm_managed_build_residue_provenance(worktree, repo)
    assert armed is not None
    build = worktree / "build"
    build.mkdir()
    payload = build / "artifact.bin"
    payload.write_bytes(b"preserve")
    module.finalize_managed_build_residue_provenance(armed, worktree, repo)
    outside = tmp_path / "outside-quarantine"
    outside.mkdir()
    (source_root / module.MANAGED_BUILD_QUARANTINE_DIR_NAME).symlink_to(
        outside, target_is_directory=True
    )

    with pytest.raises(RuntimeError, match="quarantine root is not"):
        module.cleanup_managed_disposable_artifacts(worktree, repo)
    assert payload.read_bytes() == b"preserve"
    assert list(outside.iterdir()) == []


def test_managed_build_residue_armed_record_is_not_remediated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    repo, sha = initialize_repository(tmp_path, "repo")
    source_root = tmp_path / "sources"
    source_root.mkdir()
    worktree = source_root / "managed"
    git(repo, "worktree", "add", "--detach", str(worktree), sha)
    monkeypatch.setattr(module, "SOURCE_ROOT", source_root)
    monkeypatch.setattr(module, "STATE_ROOT", tmp_path / "state")
    monkeypatch.setattr(module, "MANAGED_BUILD_RESIDUE_STALE_SECONDS", 0)
    allow_no_active_managed_build_leases(module, monkeypatch)

    armed = module.arm_managed_build_residue_provenance(worktree, repo)
    assert armed is not None
    build = worktree / "build"
    build.mkdir()
    payload = build / "artifact.bin"
    payload.write_bytes(b"unfinished-generator")

    with pytest.raises(RuntimeError, match="managed build residue blocked") as excinfo:
        module.cleanup_managed_disposable_artifacts(worktree, repo)
    blocker = json.loads(str(excinfo.value).split(": ", 1)[1])
    assert blocker["classification"] == "unknown"
    assert "does not match worktree identity" in blocker["reason"]
    assert payload.read_bytes() == b"unfinished-generator"


def test_managed_build_tree_symlink_is_quarantined_without_following_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    repo, sha = initialize_repository(tmp_path, "repo")
    source_root = tmp_path / "sources"
    source_root.mkdir()
    worktree = source_root / "managed"
    git(repo, "worktree", "add", "--detach", str(worktree), sha)
    monkeypatch.setattr(module, "SOURCE_ROOT", source_root)
    monkeypatch.setattr(module, "STATE_ROOT", tmp_path / "state")
    monkeypatch.setattr(module, "MANAGED_BUILD_RESIDUE_STALE_SECONDS", 0)
    allow_no_active_managed_build_leases(module, monkeypatch)

    armed = module.arm_managed_build_residue_provenance(worktree, repo)
    assert armed is not None
    outside = tmp_path / "outside.txt"
    outside.write_text("preserve", encoding="utf-8")
    build = worktree / "build"
    build.mkdir()
    (build / "outside-link").symlink_to(outside)
    module.finalize_managed_build_residue_provenance(armed, worktree, repo)

    removed = module.cleanup_managed_disposable_artifacts(worktree, repo)

    quarantine = Path(removed[0].split(":", 1)[1])
    link = quarantine / "outside-link"
    assert link.is_symlink()
    assert link.readlink() == outside
    assert outside.read_text(encoding="utf-8") == "preserve"


def test_managed_worktree_idle_detects_open_file_descriptor(
    tmp_path: Path
) -> None:
    module = load_publisher()
    repo, sha = initialize_repository(tmp_path, "repo")
    worktree = tmp_path / "managed"
    git(repo, "worktree", "add", "--detach", str(worktree), sha)
    pycache = worktree / "pkg" / "__pycache__"
    pycache.mkdir(parents=True)
    payload = pycache / "module.pyc"
    payload.write_bytes(b"cache")
    environment = dict(os.environ)
    environment["REPOGROUND_TEST_OPEN_PATH"] = str(payload)
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import os,time; handle=open(os.environ['REPOGROUND_TEST_OPEN_PATH'],'rb'); time.sleep(30)",
        ],
        cwd=tmp_path,
        env=environment,
    )
    try:
        import time

        for _ in range(100):
            references = module.active_process_cwds(worktree)
            if any(pid == process.pid and "fd=" in evidence for pid, evidence in references):
                break
            time.sleep(0.01)
        with pytest.raises(RuntimeError, match="active use"):
            module.cleanup_managed_disposable_artifacts(worktree, repo)
        assert payload.read_bytes() == b"cache"
    finally:
        process.terminate()
        process.wait(timeout=5)


def test_managed_worktree_idle_detects_source_path_in_argv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    repo, sha = initialize_repository(tmp_path, "repo")
    worktree = tmp_path / "managed"
    git(repo, "worktree", "add", "--detach", str(worktree), sha)
    pycache = worktree / "pkg" / "__pycache__"
    pycache.mkdir(parents=True)
    (pycache / "module.pyc").write_bytes(b"cache")
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)", str(worktree)],
        cwd=tmp_path,
    )
    try:
        for _ in range(100):
            if any(pid == process.pid for pid, _ in module.active_process_cwds(worktree)):
                break
            import time
            time.sleep(0.01)
        with pytest.raises(RuntimeError, match="active use"):
            module.cleanup_managed_disposable_artifacts(worktree, repo)
        assert pycache.is_dir()
    finally:
        process.terminate()
        process.wait(timeout=5)


def test_managed_worktree_cleanup_rejects_symlink_inside_disposable_tree(
    tmp_path: Path,
) -> None:
    module = load_publisher()
    repo, sha = initialize_repository(tmp_path)
    worktree = tmp_path / "managed"
    git(repo, "worktree", "add", "--detach", str(worktree), sha)

    outside = tmp_path / "outside.txt"
    outside.write_text("preserve\n", encoding="utf-8")
    pycache = worktree / "pkg" / "__pycache__"
    pycache.mkdir(parents=True)
    (pycache / "escape.pyc").symlink_to(outside)

    with pytest.raises(RuntimeError, match="unsafe file entry"):
        module.cleanup_managed_disposable_artifacts(worktree, repo)
    assert outside.read_text(encoding="utf-8") == "preserve\n"
    assert pycache.is_dir()



def test_managed_worktree_cleanup_validates_all_roots_before_any_removal(
    tmp_path: Path,
) -> None:
    module = load_publisher()
    repo, sha = initialize_repository(tmp_path)
    worktree = tmp_path / "managed"
    git(repo, "worktree", "add", "--detach", str(worktree), sha)

    safe_cache = worktree / ".pytest_cache"
    safe_cache.mkdir()
    (safe_cache / "README.md").write_text("preserve until batch is valid\n", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("preserve\n", encoding="utf-8")
    unsafe_cache = worktree / "pkg" / "__pycache__"
    unsafe_cache.mkdir(parents=True)
    (unsafe_cache / "escape.pyc").symlink_to(outside)

    with pytest.raises(RuntimeError, match="unsafe file entry"):
        module.cleanup_managed_disposable_artifacts(worktree, repo)

    assert safe_cache.is_dir()
    assert (safe_cache / "README.md").is_file()
    assert outside.read_text(encoding="utf-8") == "preserve\n"


def test_managed_worktree_cleanup_refuses_active_process_cwd(tmp_path: Path) -> None:
    module = load_publisher()
    repo, sha = initialize_repository(tmp_path)
    worktree = tmp_path / "managed"
    git(repo, "worktree", "add", "--detach", str(worktree), sha)
    pycache = worktree / "pkg" / "__pycache__"
    pycache.mkdir(parents=True)
    (pycache / "module.pyc").write_bytes(b"cache")

    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        cwd=worktree,
    )
    try:
        with pytest.raises(RuntimeError, match="managed worktree is in active use"):
            module.cleanup_managed_disposable_artifacts(worktree, repo)
        assert pycache.exists()
    finally:
        process.terminate()
        process.wait(timeout=10)

    assert module.cleanup_managed_disposable_artifacts(worktree, repo) == [
        "pkg/__pycache__"
    ]


def test_generation_environment_redirects_runtime_artifacts(tmp_path: Path) -> None:
    module = load_publisher()
    runtime = tmp_path / "runtime"

    env = module.generation_environment(runtime)

    assert env["PYTHONDONTWRITEBYTECODE"] == "1"
    assert env.get("PYTHONNOUSERSITE") == os.environ.get("PYTHONNOUSERSITE")
    assert Path(env["PYTHONPYCACHEPREFIX"]) == runtime / "pycache"
    assert Path(env["XDG_CACHE_HOME"]) == runtime / "xdg-cache"
    assert Path(env["PIP_CACHE_DIR"]) == runtime / "pip-cache"
    assert Path(env["TMPDIR"]) == runtime / "tmp"
    for key in ("PYTHONPYCACHEPREFIX", "XDG_CACHE_HOME", "PIP_CACHE_DIR", "TMPDIR"):
        assert Path(env[key]).is_dir()


def test_generator_repository_is_prioritized_without_reordering_other_entries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_publisher()
    entries = [
        module.RepoEntry(
            key=key,
            owner=key.split("/", 1)[0],
            repo=key.split("/", 1)[1],
            path=Path("/tmp") / key.split("/", 1)[1],
            remote=f"git@github.com:{key}.git",
        )
        for key in (
            "heimgewebe/alpha",
            "heimgewebe/beta",
            "heimgewebe/repoground",
            "heimgewebe/zeta",
        )
    ]
    monkeypatch.setattr(
        module, "generator_repository_key", lambda: "heimgewebe/repoground"
    )

    prioritized = module.prioritize_generator_repository(entries)

    assert [entry.key for entry in prioritized] == [
        "heimgewebe/repoground",
        "heimgewebe/alpha",
        "heimgewebe/beta",
        "heimgewebe/zeta",
    ]


def test_generator_repository_priority_is_applied_before_publication_loop() -> None:
    source = PUBLISHER.read_text(encoding="utf-8")
    inventory_return = source.index("if args.inventory:")
    lock = source.index("\n    lock = acquire_lock()", inventory_return)
    membership = source.index(
        "fleet_membership = load_authoritative_fleet_membership()",
        lock,
    )
    priority = source.index("entries, scheduling = prioritize_fleet_publication(entries)")
    loop = source.index("for entry in entries:", priority)

    assert inventory_return < lock < membership < priority < loop


def test_fleet_fairness_converges_42_repository_backlog_with_limit_8(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    monkeypatch.setattr(module, "STATE_ROOT", tmp_path / "state")
    module.STATE_ROOT.mkdir(parents=True)
    generator_key = "heimgewebe/repoground"
    monkeypatch.setattr(module, "generator_repository_key", lambda: generator_key)
    keys = [generator_key] + [f"heimgewebe/repo-{index:02d}" for index in range(41)]
    entries = [
        module.RepoEntry(
            key=key,
            owner=key.split("/", 1)[0],
            repo=key.split("/", 1)[1],
            path=tmp_path / key.split("/", 1)[1],
            remote=f"git@github.com:{key}.git",
        )
        for key in keys
    ]

    def record_publication(entry: object, sequence: int) -> None:
        repository = module.publication_repository(entry)
        path = module.STATE_ROOT / f"{repository}__main.state.json"
        path.write_text(
            json.dumps(
                {
                    "schema": module.STATE_SCHEMA,
                    "repo_id": repository,
                    "ref": "main",
                    "created_at": f"2026-07-22T{sequence // 3600:02d}:"
                    f"{(sequence // 60) % 60:02d}:{sequence % 60:02d}Z",
                }
            )
            + "\n",
            encoding="utf-8",
        )

    for index, entry in enumerate(entries):
        record_publication(entry, index)

    changed = set(keys)
    publication_counts = {key: 0 for key in keys}
    newly_changed_key: str | None = None
    completed_rounds = 0
    for round_index in range(1, 8):
        ordered, scheduling = module.prioritize_fleet_publication(
            entries, now_epoch=1784773200.0
        )
        assert scheduling["policy"] == module.SCHEDULING_POLICY
        assert scheduling["ordered_repositories"][0] == generator_key
        batch = [entry for entry in ordered if entry.key in changed][:8]
        assert len(batch) <= 8
        for entry in batch:
            changed.remove(entry.key)
            if entry.key == newly_changed_key and publication_counts[entry.key] == 1:
                assert all(count >= 1 for count in publication_counts.values())
            publication_counts[entry.key] += 1
            record_publication(
                entry, 3600 + round_index * 60 + publication_counts[entry.key]
            )
        if round_index == 1:
            newly_changed_key = batch[1].key
            changed.add(newly_changed_key)
        completed_rounds = round_index
        if not changed:
            break

    assert completed_rounds <= 6
    assert not changed
    assert all(count >= 1 for count in publication_counts.values())
    assert newly_changed_key is not None
    assert publication_counts[newly_changed_key] == 2

    _ordered, final_scheduling = module.prioritize_fleet_publication(
        entries, now_epoch=1784773200.0
    )
    evidence = final_scheduling["entries"][newly_changed_key]
    assert evidence["rank"] >= 1
    assert evidence["debt_basis"] == "age_since_last_successful_publication"
    assert isinstance(evidence["publication_debt_seconds"], int)


def test_publication_limit_precedes_source_materialization() -> None:
    source = PUBLISHER.read_text(encoding="utf-8")
    main = source[source.index("def main("):]
    changed = main.index("changed += 1")
    limit = main.index("if args.limit and published >= args.limit", changed)
    publish_call = main.index("publish(", limit)

    assert changed < limit < publish_call
    assert "preflight_existing_source_worktree(" not in source

def test_managed_worktree_refuses_attached_foreign_or_non_worktree_paths(
    tmp_path: Path,
) -> None:
    module = load_publisher()
    repo, sha = initialize_repository(tmp_path, "repo-a")
    attached = tmp_path / "attached"
    git(repo, "worktree", "add", "-b", "managed-branch", str(attached), sha)
    with pytest.raises(RuntimeError, match="attached to a branch"):
        module.assert_managed_worktree_clean(attached, repo)

    foreign_repo, foreign_sha = initialize_repository(tmp_path, "repo-b")
    foreign = tmp_path / "foreign"
    git(foreign_repo, "worktree", "add", "--detach", str(foreign), foreign_sha)
    with pytest.raises(RuntimeError, match="belongs to another repository"):
        module.assert_managed_worktree_clean(foreign, repo)

    ordinary = tmp_path / "ordinary"
    ordinary.mkdir()
    sentinel = ordinary / "sentinel.txt"
    sentinel.write_text("must survive\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="not the expected worktree root"):
        module.prepare_managed_worktree(ordinary, expected_repo=repo, target=sha)
    assert sentinel.read_text(encoding="utf-8") == "must survive\n"


def test_remove_tree_is_confined_to_managed_root_and_rejects_symlinks(
    tmp_path: Path,
) -> None:
    module = load_publisher()
    root = tmp_path / "root"
    removable = root / "group" / "version"
    removable.mkdir(parents=True)
    (removable / "artifact").write_text("data", encoding="utf-8")
    module.remove_tree(removable, apply=True, root=root)
    assert not removable.exists()

    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(RuntimeError, match="outside managed root"):
        module.remove_tree(outside, apply=True, root=root)
    assert outside.is_dir()

    symlink_target = tmp_path / "symlink-target"
    symlink_target.mkdir()
    link = root / "link"
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(symlink_target, target_is_directory=True)
    with pytest.raises(RuntimeError, match="non-directory or symlink"):
        module.remove_tree(link, apply=True, root=root)
    assert symlink_target.is_dir()


def test_retention_bounds_are_fail_closed() -> None:
    module = load_publisher()
    assert module.validate_retention(1) == 1
    assert module.validate_retention(3) == 3
    assert module.validate_retention(10) == 10
    with pytest.raises(ValueError):
        module.validate_retention(0)
    with pytest.raises(ValueError):
        module.validate_retention(11)


def test_unscoped_force_is_rejected_before_repository_discovery() -> None:
    completed = subprocess.run(
        [sys.executable, str(PUBLISHER), "--force"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert completed.returncode == 2
    assert "--force is disabled" in completed.stderr


def test_targeted_force_requires_repo_and_reason() -> None:
    completed = subprocess.run(
        [sys.executable, str(PUBLISHER), "--force-republish"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert completed.returncode == 2
    assert "requires at least one --repo and a non-empty --reason" in completed.stderr


def test_runtime_has_one_hourly_changed_only_timer_and_no_force_fallback() -> None:
    service = (UNIT_DIR / "repoground-publish-fleet-watch.service").read_text(
        encoding="utf-8"
    )
    timer = (UNIT_DIR / "repoground-publish-fleet-watch.timer").read_text(
        encoding="utf-8"
    )

    assert "ExecStart=/home/alex/.local/bin/repoground-publish-fleet" in service
    assert "RepoGround fleet bundles" in service
    assert "--if-changed" in service
    assert "--retention 3" in service
    assert "--force" not in service
    assert "OnCalendar=hourly" in timer
    assert "OnBootSec=" not in timer
    assert "OnUnitActiveSec=" not in timer
    assert "RandomizedDelaySec=10min" in timer
    assert "Persistent=true" in timer
    assert sorted(path.name for path in UNIT_DIR.iterdir()) == [
        "repoground-publish-fleet-watch.service",
        "repoground-publish-fleet-watch.timer",
    ]


def _run_installer(
    tmp_path: Path,
    *arguments: str,
) -> subprocess.CompletedProcess[str]:
    home = tmp_path / "home"
    fake_bin = tmp_path / "bin"
    home.mkdir(exist_ok=True)
    fake_bin.mkdir(exist_ok=True)
    systemctl = fake_bin / "systemctl"
    systemctl.write_text(
        "#!/bin/sh\nprintf '%s\n' \"$*\" >> \"$HOME/systemctl.log\"\n",
        encoding="utf-8",
    )
    systemctl.chmod(0o755)
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PATH"] = str(fake_bin) + os.pathsep + env["PATH"]
    return subprocess.run(
        [str(INSTALLER), *arguments],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        check=False,
    )


def _activate_managed_runtime(home: Path, commit: str = "a" * 40) -> Path:
    managed_root = home / ".local/share/repoground-runtime" / commit
    managed_python = managed_root / ".venv/bin/python"
    managed_python.parent.mkdir(parents=True)
    managed_python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    managed_python.chmod(0o755)
    (managed_root.parent / "current").symlink_to(
        managed_root,
        target_is_directory=True,
    )
    return managed_root


def test_fleet_wrapper_uses_managed_runtime_python(tmp_path: Path) -> None:
    home = tmp_path / "home"
    managed_base = home / ".local/share/repoground-runtime"
    managed_root = managed_base / ("a" * 40)
    managed_python = managed_root / ".venv/bin/python"
    managed_python.parent.mkdir(parents=True)
    marker = tmp_path / "managed-python.args"
    managed_python.write_text(
        "#!/bin/sh\n"
        f"printf '%s\\n' \"$@\" > {shlex.quote(str(marker))}\n",
        encoding="utf-8",
    )
    managed_python.chmod(0o755)
    managed_base.mkdir(parents=True, exist_ok=True)
    (managed_base / "current").symlink_to(managed_root, target_is_directory=True)

    implementation = home / ".local/libexec/repoground/repoground-publish-fleet.py"
    implementation.parent.mkdir(parents=True)
    implementation.write_text("# implementation marker\n", encoding="utf-8")

    fleet_command = tmp_path / "repoground-publish-fleet"
    shutil.copy2(CLI_WRAPPER, fleet_command)

    env = os.environ.copy()
    env["HOME"] = str(home)
    completed = subprocess.run(
        ["bash", str(fleet_command), "--inventory"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        env=env,
    )

    assert completed.returncode == 0, completed.stderr
    assert marker.read_text(encoding="utf-8").splitlines() == [
        "-I",
        str(implementation),
        "--inventory",
    ]


def test_runtime_installer_enable_fails_before_mutation_without_managed_runtime(
    tmp_path: Path,
) -> None:
    completed = _run_installer(tmp_path, "--enable")
    home = tmp_path / "home"

    assert completed.returncode == 1
    assert "managed runtime activation is unavailable" in completed.stderr
    assert not (home / "systemctl.log").exists()
    assert not (home / ".local/bin/repoground-publish-fleet").exists()


def test_runtime_installer_enable_accepts_valid_managed_runtime(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    managed_root = _activate_managed_runtime(home)
    managed_python = managed_root / ".venv/bin/python"
    marker = tmp_path / "managed-inventory.args"
    managed_python.write_text(
        "#!/bin/sh\n"
        f"printf '%s\\n' \"$@\" > {shlex.quote(str(marker))}\n"
        "exit 0\n",
        encoding="utf-8",
    )
    managed_python.chmod(0o755)

    completed = _run_installer(tmp_path, "--enable")

    assert completed.returncode == 0, completed.stderr
    assert "PASS enabled" in completed.stdout
    assert marker.read_text(encoding="utf-8").splitlines()[-2:] == [
        "--inventory",
        "--inventory-allow-missing-local-members",
    ]
    assert "enable --now repoground-publish-fleet-watch.timer" in (
        home / "systemctl.log"
    ).read_text(encoding="utf-8")



def test_runtime_installer_enable_fails_before_mutation_when_inventory_preflight_fails(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    managed_root = _activate_managed_runtime(home)
    managed_python = managed_root / ".venv/bin/python"
    managed_python.write_text("#!/bin/sh\nexit 7\n", encoding="utf-8")
    managed_python.chmod(0o755)

    completed = _run_installer(tmp_path, "--enable")

    assert completed.returncode == 1
    assert "authoritative fleet inventory preflight failed" in completed.stderr
    assert not (home / "systemctl.log").exists()
    assert not (home / ".local/bin/repoground-publish-fleet").exists()


def test_installer_atomically_migrates_state_and_starts_canonical_logs(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    old_state = home / ".local/state/repobrief-publish/fleet"
    old_log = home / "logs/repobrief-publish"
    old_state.mkdir(parents=True)
    old_log.mkdir(parents=True)
    (old_state / "marker.json").write_text("{}\n", encoding="utf-8")
    (old_log / "historical.log").write_text("old\n", encoding="utf-8")

    completed = _run_installer(tmp_path)

    new_state = home / ".local/state/repoground-publish/fleet"
    new_log = home / "logs/repoground-publish"
    assert completed.returncode == 0, completed.stderr
    assert not old_state.exists()
    assert (new_state / "marker.json").read_text(encoding="utf-8") == "{}\n"
    assert new_log.is_dir()
    assert (old_log / "historical.log").read_text(encoding="utf-8") == "old\n"
    installed_wrapper = home / ".local/bin/repoground-publish-fleet"
    installed_impl = (
        home / ".local/libexec/repoground/repoground-publish-fleet.py"
    )
    assert installed_wrapper.read_bytes() == CLI_WRAPPER.read_bytes()
    assert installed_wrapper.stat().st_mode & 0o111
    assert installed_impl.read_bytes() == PUBLISHER.read_bytes()
    assert "PASS paused" in completed.stdout


def test_installer_refuses_dual_state_truth(tmp_path: Path) -> None:
    home = tmp_path / "home"
    old_state = home / ".local/state/repobrief-publish/fleet"
    new_state = home / ".local/state/repoground-publish/fleet"
    old_state.mkdir(parents=True)
    new_state.mkdir(parents=True)
    (old_state / "old").write_text("old", encoding="utf-8")
    (new_state / "new").write_text("new", encoding="utf-8")

    completed = _run_installer(tmp_path)

    assert completed.returncode == 1
    assert "refusing dual truth" in completed.stderr
    assert (old_state / "old").is_file()
    assert (new_state / "new").is_file()


def test_installer_defaults_to_paused_and_removes_duplicate_generators() -> None:
    text = INSTALLER.read_text(encoding="utf-8")

    assert "ENABLE=0" in text
    assert 'if [[ ${1:-} == "--enable" ]]' in text
    assert "rb-publish-fleet-daily.timer" in text
    assert "repobrief-publish-systemkatalog-main-watch.timer" in text
    assert "systemkatalog-repobrief-localize.path" in text
    assert "disable --now" in text
    assert "INSTALL-REPOGROUND-PUBLISH-FLEET-RUNTIME: PASS paused" in text


def test_systemkatalog_entrypoints_delegate_to_bounded_fleet_runtime() -> None:
    publish = SYSTEMKATALOG_PUBLISH.read_text(encoding="utf-8")
    assert "/home/alex/.local/bin/repoground-publish-fleet" in publish
    assert "--if-changed" in publish
    assert "--retention 3" in publish
    assert "--repo heimgewebe/systemkatalog" in publish
    assert "--force" not in publish

    watch = SYSTEMKATALOG_WATCH.read_text(encoding="utf-8")
    assert "is a compatibility alias" in watch
    assert 'exec "$(dirname "$0")/repoground-publish-systemkatalog-main"' in watch
    assert "repoground-publish-fleet" not in watch
    assert "--repo" not in watch

    assert not LEGACY_SYSTEMKATALOG_PUBLISH.exists()
    assert not LEGACY_SYSTEMKATALOG_WATCH.exists()

    compatibility = SYSTEMKATALOG_INSTALLER.read_text(encoding="utf-8")
    assert "install_repoground_publish_fleet_runtime.sh" in compatibility
    assert "systemkatalog-publish" not in compatibility


def test_legacy_fleet_and_installer_entrypoints_are_removed() -> None:
    assert not LEGACY_PUBLISHER.exists()
    assert not LEGACY_INSTALLER.exists()


def test_special_history_pruning_keeps_referenced_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    roots = isolate_retention_roots(module, tmp_path, monkeypatch)
    special_root = roots["special"]
    group = special_root / "systemkatalog-main"
    versions = [
        write_version(group, f"20260714T10000{index}Z", bytes([index + 1]), index)[0]
        for index in range(6)
    ]

    reports = module.prune_all_special(
        keep=3,
        apply=True,
        protected={(versions[1] / "repo_merge.md").resolve()},
    )

    assert len(reports) == 1
    assert set(module.version_dirs(group)) == {
        versions[5],
        versions[4],
        versions[3],
        versions[1],
    }
    assert str(versions[1]) in reports[0]["protected_old"]


def test_state_identity_does_not_trust_legacy_source_only_marker(
    tmp_path: Path,
) -> None:
    module = load_publisher()
    module.STATE_ROOT = tmp_path
    entry = module.RepoEntry(
        key="heimgewebe/demo",
        owner="heimgewebe",
        repo="demo",
        path=tmp_path / "demo",
        remote="git@github.com:heimgewebe/demo.git",
    )

    path = module.state_path(entry, "main")

    assert path == tmp_path / "heimgewebe__demo__main.state.json"
    assert not path.name.endswith(".last-sha")


def test_state_and_active_publication_targets_protect_old_versions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    roots = isolate_retention_roots(module, tmp_path, monkeypatch)
    group = roots["publication"] / "bundles" / "heimgewebe__demo" / "main"
    versions = [
        write_version(group, f"20260714T10000{index}Z", bytes([index + 1]), index)[0]
        for index in range(7)
    ]
    module.atomic_write_json(
        roots["state"] / "heimgewebe__demo__main.state.json",
        {
            "schema": module.STATE_SCHEMA,
            "publication_dir": str(versions[0]),
        },
    )
    active = module.create_active_publication_lease(
        repository="heimgewebe__demo",
        ref="main",
        fingerprint="a" * 64,
        publication_dir=versions[1],
    )

    report = module.prune_group(group, keep=3, apply=True, protected=set())

    assert versions[0].is_dir()
    assert versions[1].is_dir()
    assert not versions[2].exists()
    assert {str(versions[0]), str(versions[1])}.issubset(set(report["protected_old"]))
    module.clear_active_publication_lease(active)


def test_transaction_rechecks_protection_after_quarantine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    roots = isolate_retention_roots(module, tmp_path, monkeypatch)
    group = roots["publication"] / "bundles" / "demo" / "main"
    candidate, _ = write_version(group, "20260714T100000Z", b"payload", 1)
    snapshot = module.tree_snapshot(candidate)
    calls = 0

    def changing_protection(explicit: set[Path]) -> set[Path]:
        nonlocal calls
        calls += 1
        return {candidate.resolve()} if calls >= 3 else set(explicit)

    monkeypatch.setattr(module, "dynamic_protected_paths", changing_protection)
    result = module.transactional_prune(
        candidate,
        root=group,
        expected_snapshot=snapshot,
        removed_bytes=module.tree_bytes(candidate),
        protected=set(),
    )

    assert result["state"] == "retained_newly_protected"
    assert candidate.is_dir()
    transaction = next(module.prune_transaction_root().glob("*.json"))
    assert json.loads(transaction.read_text())["state"] == "restored_newly_protected"


def test_transaction_refuses_candidate_changed_after_planning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    roots = isolate_retention_roots(module, tmp_path, monkeypatch)
    group = roots["publication"] / "bundles" / "demo" / "main"
    candidate, _ = write_version(group, "20260714T100000Z", b"payload", 1)
    snapshot = module.tree_snapshot(candidate)
    (candidate / "repo_merge.md").write_text("changed", encoding="utf-8")

    with pytest.raises(RuntimeError, match="changed after planning"):
        module.transactional_prune(
            candidate,
            root=group,
            expected_snapshot=snapshot,
            removed_bytes=1,
            protected=set(),
        )

    assert candidate.is_dir()
    assert not module.prune_transaction_root().exists()


def test_transactional_delete_is_journaled_and_confined(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    roots = isolate_retention_roots(module, tmp_path, monkeypatch)
    group = roots["publication"] / "bundles" / "demo" / "main"
    candidate, _ = write_version(group, "20260714T100000Z", b"payload", 1)
    snapshot = module.tree_snapshot(candidate)

    result = module.transactional_prune(
        candidate,
        root=group,
        expected_snapshot=snapshot,
        removed_bytes=module.tree_bytes(candidate),
        protected=set(),
    )

    assert result["state"] == "deleted"
    assert not candidate.exists()
    transaction = next(module.prune_transaction_root().glob("*.json"))
    payload = json.loads(transaction.read_text())
    assert payload["state"] == "deleted"
    assert payload["source"] == str(candidate.resolve(strict=False))
    quarantine_path = Path(payload["quarantine"])
    assert quarantine_path.parent.parent.name == module.QUARANTINE_DIR_NAME
    assert module.PERSISTED_V1_QUARANTINE_DIR_NAME not in quarantine_path.parts

    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(RuntimeError, match="escapes managed roots"):
        module.transactional_prune(
            outside,
            root=outside.parent,
            expected_snapshot=module.tree_snapshot(outside),
            removed_bytes=0,
            protected=set(),
        )


def test_reconciliation_accepts_terminal_persisted_v1_quarantine_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    roots = isolate_retention_roots(module, tmp_path, monkeypatch)
    group = roots["publication"] / "bundles" / "demo" / "main"
    group.mkdir(parents=True)
    source = group / "20260714T100000Z"
    transaction_id = "a" * 32
    quarantine = (
        group
        / module.PERSISTED_V1_QUARANTINE_DIR_NAME
        / transaction_id
        / source.name
    )
    transaction = module.prune_transaction_root() / f"{transaction_id}.json"
    module.atomic_write_json(
        transaction,
        {
            "schema": module.PRUNE_TRANSACTION_SCHEMA,
            "transaction_id": transaction_id,
            "state": "deleted",
            "source": str(source.resolve(strict=False)),
            "quarantine": str(quarantine.resolve(strict=False)),
            "root": str(group.resolve()),
            "snapshot": {"device": 1, "inode": 2, "tree_sha256": "a" * 64},
            "removed_bytes": 1,
        },
    )

    reports = module.reconcile_prune_transactions(protected=set(), apply=True)

    assert reports == [{"transaction": str(transaction), "state": "deleted"}]
    assert json.loads(transaction.read_text(encoding="utf-8"))["quarantine"] == str(
        quarantine.resolve(strict=False)
    )


def test_reconciliation_finishes_persisted_v1_quarantine_after_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    roots = isolate_retention_roots(module, tmp_path, monkeypatch)
    group = roots["publication"] / "bundles" / "demo" / "main"
    source, _ = write_version(group, "20260714T100000Z", b"payload", 1)
    snapshot = module.tree_snapshot(source)
    removed_bytes = module.tree_bytes(source)
    transaction_id = "9" * 32
    quarantine = (
        group
        / module.PERSISTED_V1_QUARANTINE_DIR_NAME
        / transaction_id
        / source.name
    )
    quarantine.parent.mkdir(parents=True)
    os.replace(source, quarantine)
    transaction = module.prune_transaction_root() / f"{transaction_id}.json"
    module.atomic_write_json(
        transaction,
        {
            "schema": module.PRUNE_TRANSACTION_SCHEMA,
            "transaction_id": transaction_id,
            "state": "quarantined",
            "source": str(source.resolve(strict=False)),
            "quarantine": str(quarantine.resolve(strict=False)),
            "root": str(group.resolve()),
            "snapshot": snapshot,
            "removed_bytes": removed_bytes,
        },
    )

    assert module.version_dirs(group) == []
    reports = module.reconcile_prune_transactions(protected=set(), apply=True)

    assert reports[0]["applied"] == "delete"
    assert not source.exists()
    assert not quarantine.exists()
    assert not (group / module.PERSISTED_V1_QUARANTINE_DIR_NAME).exists()
    assert json.loads(transaction.read_text(encoding="utf-8"))["state"] == "deleted"


def test_reconciliation_restores_planned_move_that_became_protected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    roots = isolate_retention_roots(module, tmp_path, monkeypatch)
    group = roots["publication"] / "bundles" / "demo" / "main"
    source, _ = write_version(group, "20260714T100000Z", b"payload", 1)
    snapshot = module.tree_snapshot(source)
    transaction_id = "b" * 32
    quarantine = group / module.QUARANTINE_DIR_NAME / transaction_id / source.name
    quarantine.parent.mkdir(parents=True)
    os.replace(source, quarantine)
    module.atomic_write_json(
        module.prune_transaction_root() / f"{transaction_id}.json",
        {
            "schema": module.PRUNE_TRANSACTION_SCHEMA,
            "transaction_id": transaction_id,
            "state": "planned",
            "source": str(source.resolve(strict=False)),
            "quarantine": str(quarantine.resolve(strict=False)),
            "root": str(group.resolve()),
            "snapshot": snapshot,
            "removed_bytes": 1,
        },
    )

    reports = module.reconcile_prune_transactions(protected={source}, apply=True)

    assert reports[0]["applied"] == "restore"
    assert source.is_dir()
    assert not quarantine.exists()
    transaction = module.prune_transaction_root() / f"{transaction_id}.json"
    assert json.loads(transaction.read_text())["state"] == "restored"


def test_reconciliation_records_completed_delete_after_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    roots = isolate_retention_roots(module, tmp_path, monkeypatch)
    group = roots["publication"] / "bundles" / "demo" / "main"
    group.mkdir(parents=True)
    source = group / "20260714T100000Z"
    quarantine = group / module.QUARANTINE_DIR_NAME / ("c" * 32) / source.name
    module.atomic_write_json(
        module.prune_transaction_root() / f"{'c' * 32}.json",
        {
            "schema": module.PRUNE_TRANSACTION_SCHEMA,
            "transaction_id": "c" * 32,
            "state": "quarantined",
            "source": str(source.resolve(strict=False)),
            "quarantine": str(quarantine.resolve(strict=False)),
            "root": str(group.resolve()),
            "snapshot": {"device": 1, "inode": 2, "tree_sha256": "d" * 64},
            "removed_bytes": 1,
        },
    )

    reports = module.reconcile_prune_transactions(protected=set(), apply=True)

    assert reports[0]["applied"] == "record_deleted"
    transaction = module.prune_transaction_root() / f"{'c' * 32}.json"
    assert json.loads(transaction.read_text())["state"] == "deleted"


@pytest.mark.parametrize("bundled", [False, True])
@pytest.mark.parametrize(
    "generation_root_name",
    [".repoground-generations", ".repobrief-generations"],
)
def test_transactional_prune_accepts_only_bounded_generation_current_symlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    bundled: bool,
    generation_root_name: str,
) -> None:
    module = load_publisher()
    roots = isolate_retention_roots(module, tmp_path, monkeypatch)
    group = roots["publication"] / "bundles" / "demo" / "main"
    candidate, _ = write_version(group, "20260714T100000Z", b"payload", 1)
    current, _ = write_historical_generation_symlink(
        candidate,
        bundled=bundled,
        generation_root_name=generation_root_name,
    )

    snapshot = module.tree_snapshot(candidate)
    removed_bytes = module.tree_bytes(candidate)
    result = module.transactional_prune(
        candidate,
        root=group,
        expected_snapshot=snapshot,
        removed_bytes=removed_bytes,
        protected=set(),
    )

    assert result["state"] == "deleted"
    assert result["removed_bytes"] == removed_bytes
    assert not candidate.exists()
    assert not current.exists()


@pytest.mark.parametrize("scan_name", ["tree_bytes", "tree_snapshot"])
def test_tree_scan_reuses_initial_current_symlink_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scan_name: str,
) -> None:
    module = load_publisher()
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    current, _ = write_historical_generation_symlink(
        candidate,
        generation_root_name=module.CANONICAL_GENERATION_ROOT_NAME,
    )
    original_lstat = Path.lstat
    current_lstat_calls = 0

    def counted_lstat(path: Path) -> os.stat_result:
        nonlocal current_lstat_calls
        if path == current:
            current_lstat_calls += 1
        return original_lstat(path)

    monkeypatch.setattr(Path, "lstat", counted_lstat)

    getattr(module, scan_name)(candidate)

    assert current_lstat_calls == 2


def test_reused_current_symlink_metadata_keeps_final_identity_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_publisher()
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    current, _ = write_historical_generation_symlink(
        candidate,
        generation_root_name=module.CANONICAL_GENERATION_ROOT_NAME,
    )
    initial_metadata = current.lstat()
    changed_values = list(initial_metadata)
    changed_values[1] = initial_metadata.st_ino + 1
    changed_metadata = os.stat_result(changed_values)
    original_lstat = Path.lstat

    def changed_lstat(path: Path) -> os.stat_result:
        if path == current:
            return changed_metadata
        return original_lstat(path)

    monkeypatch.setattr(Path, "lstat", changed_lstat)

    with pytest.raises(RuntimeError, match="symlink changed during validation"):
        module._bounded_generation_current_symlink(
            current,
            root=candidate,
            metadata=initial_metadata,
        )


def test_historical_current_symlink_rejects_unsafe_targets_and_locations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    roots = isolate_retention_roots(module, tmp_path, monkeypatch)
    group = roots["publication"] / "bundles" / "demo" / "main"

    absolute, _ = write_version(group, "20260714T100001Z", b"absolute", 1)
    absolute_generation = absolute / ".repobrief-generations" / "legacy-scope"
    absolute_generation.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (absolute_generation / "current").symlink_to(
        outside, target_is_directory=True
    )

    escaping, _ = write_version(group, "20260714T100002Z", b"escaping", 2)
    escaping_generation = escaping / ".repobrief-generations" / "legacy-scope"
    escaping_generation.mkdir(parents=True)
    (escaping_generation / "current").symlink_to(
        f"../{'b' * 64}", target_is_directory=True
    )

    chained, _ = write_version(group, "20260714T100003Z", b"chained", 3)
    chained_generation = chained / ".repobrief-generations" / "legacy-scope"
    chained_generation.mkdir(parents=True)
    real_target = chained_generation / ("c" * 64 + "-real")
    real_target.mkdir()
    (chained_generation / ("c" * 64)).symlink_to(
        real_target.name, target_is_directory=True
    )
    (chained_generation / "current").symlink_to(
        "c" * 64, target_is_directory=True
    )

    misplaced, _ = write_version(group, "20260714T100004Z", b"misplaced", 4)
    misplaced_target = misplaced / ("d" * 64)
    misplaced_target.mkdir()
    (misplaced / "current").symlink_to(
        misplaced_target.name, target_is_directory=True
    )

    dangling, _ = write_version(group, "20260714T100005Z", b"dangling", 5)
    dangling_generation = dangling / ".repobrief-generations" / "legacy-scope"
    dangling_generation.mkdir(parents=True)
    (dangling_generation / "current").symlink_to(
        "e" * 64, target_is_directory=True
    )

    wrong_name, _ = write_version(group, "20260714T100006Z", b"wrong-name", 6)
    wrong_name_generation = (
        wrong_name / ".repobrief-generations" / "legacy-scope"
    )
    wrong_name_target = wrong_name_generation / ("f" * 64)
    wrong_name_target.mkdir(parents=True)
    (wrong_name_generation / "latest").symlink_to(
        wrong_name_target.name, target_is_directory=True
    )

    for candidate in (absolute, escaping, chained, misplaced, dangling, wrong_name):
        with pytest.raises(RuntimeError, match="contains .*symlink"):
            module.tree_bytes(candidate)
        with pytest.raises(RuntimeError, match="contains .*symlink"):
            module.tree_snapshot(candidate)
        assert candidate.is_dir()
    assert outside.is_dir()


def test_transaction_rejects_historical_current_target_swap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    roots = isolate_retention_roots(module, tmp_path, monkeypatch)
    group = roots["publication"] / "bundles" / "demo" / "main"
    candidate, _ = write_version(group, "20260714T100000Z", b"payload", 1)
    current, _ = write_historical_generation_symlink(candidate)
    replacement = current.parent / ("b" * 64)
    replacement.mkdir()
    (replacement / "payload.txt").write_text("replacement", encoding="utf-8")
    snapshot = module.tree_snapshot(candidate)
    removed_bytes = module.tree_bytes(candidate)

    current.unlink()
    current.symlink_to(replacement.name, target_is_directory=True)

    with pytest.raises(RuntimeError, match="changed after planning"):
        module.transactional_prune(
            candidate,
            root=group,
            expected_snapshot=snapshot,
            removed_bytes=removed_bytes,
            protected=set(),
        )

    assert candidate.is_dir()
    assert current.readlink() == Path("b" * 64)
    assert not module.prune_transaction_root().exists()


def test_transaction_rejects_substituted_historical_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    roots = isolate_retention_roots(module, tmp_path, monkeypatch)
    group = roots["publication"] / "bundles" / "demo" / "main"
    candidate, _ = write_version(group, "20260714T100000Z", b"payload", 1)
    current, _ = write_historical_generation_symlink(candidate)
    generation = current.parent
    snapshot = module.tree_snapshot(candidate)
    removed_bytes = module.tree_bytes(candidate)
    substitute = tmp_path / "substitute-generation"
    substitute.mkdir()
    substitute_target = substitute / ("a" * 64)
    substitute_target.mkdir()
    (substitute / "current").symlink_to(
        substitute_target.name, target_is_directory=True
    )

    shutil.rmtree(generation)
    generation.symlink_to(substitute, target_is_directory=True)

    with pytest.raises(RuntimeError, match="contains a symlink"):
        module.transactional_prune(
            candidate,
            root=group,
            expected_snapshot=snapshot,
            removed_bytes=removed_bytes,
            protected=set(),
        )

    assert candidate.is_dir()
    assert generation.is_symlink()
    assert substitute.is_dir()
    assert not module.prune_transaction_root().exists()


def test_retention_rejects_special_file_and_leaves_candidate_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    roots = isolate_retention_roots(module, tmp_path, monkeypatch)
    group = roots["publication"] / "bundles" / "demo" / "main"
    candidate, _ = write_version(group, "20260714T100000Z", b"payload", 1)
    fifo = candidate / "special.fifo"
    os.mkfifo(fifo)

    with pytest.raises(RuntimeError, match="non-regular file"):
        module.tree_bytes(candidate)
    with pytest.raises(RuntimeError, match="non-regular file"):
        module.tree_snapshot(candidate)

    assert candidate.is_dir()
    assert fifo.exists()
    assert not module.prune_transaction_root().exists()


def test_tree_snapshot_and_localized_groups_reject_ambiguous_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    roots = isolate_retention_roots(module, tmp_path, monkeypatch)
    group = roots["publication"] / "bundles" / "demo" / "main"
    candidate, _ = write_version(group, "20260714T100000Z", b"payload", 1)
    target = tmp_path / "target"
    target.mkdir()
    (candidate / "link").symlink_to(target, target_is_directory=True)
    with pytest.raises(RuntimeError, match="contains a symlink"):
        module.tree_snapshot(candidate)

    localized = roots["publication"] / "external" / "_bundles" / "demo" / "main"
    (localized / ("a" * 64)).mkdir(parents=True)
    (localized / "not-a-hash").mkdir()
    with pytest.raises(RuntimeError, match="unexpected localized bundle entries"):
        module.localized_hash_dirs(localized)


def test_legacy_layout_discovery_supports_both_known_shapes_and_rejects_mixing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    roots = isolate_retention_roots(module, tmp_path, monkeypatch)
    modern = roots["legacy"] / "heimgewebe__demo" / "main"
    direct = roots["legacy"] / "cabinet-main"
    write_version(modern, "20260714T100000Z", b"modern", 1)
    write_version(direct, "20260714T100000Z", b"direct", 1)

    assert module.legacy_version_groups() == [direct, modern]

    (direct / "main").mkdir()
    with pytest.raises(RuntimeError, match="mixed legacy layouts"):
        module.legacy_version_groups()


def test_reconciliation_rejects_forged_quarantine_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    roots = isolate_retention_roots(module, tmp_path, monkeypatch)
    group = roots["publication"] / "bundles" / "demo" / "main"
    forged, _ = write_version(group, "20260714T100000Z", b"forged", 1)
    transaction_id = "d" * 32
    source = group / "20260714T100001Z"
    module.atomic_write_json(
        module.prune_transaction_root() / f"{transaction_id}.json",
        {
            "schema": module.PRUNE_TRANSACTION_SCHEMA,
            "transaction_id": transaction_id,
            "state": "quarantined",
            "source": str(source.resolve(strict=False)),
            "quarantine": str(forged.resolve()),
            "root": str(group.resolve()),
            "snapshot": module.tree_snapshot(forged),
            "removed_bytes": module.tree_bytes(forged),
        },
    )

    with pytest.raises(RuntimeError, match="quarantine path mismatch"):
        module.reconcile_prune_transactions(protected=set(), apply=True)

    assert forged.is_dir()


@pytest.mark.parametrize(
    "directory_name_attribute",
    ["QUARANTINE_DIR_NAME", "PERSISTED_V1_QUARANTINE_DIR_NAME"],
)
def test_unjournaled_quarantine_entry_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    directory_name_attribute: str,
) -> None:
    module = load_publisher()
    roots = isolate_retention_roots(module, tmp_path, monkeypatch)
    group = roots["publication"] / "bundles" / "demo" / "main"
    write_version(group, "20260714T100000Z", b"payload", 1)
    directory_name = getattr(module, directory_name_attribute)
    orphan = group / directory_name / ("e" * 32) / "20260714T090000Z"
    orphan.mkdir(parents=True)

    with pytest.raises(RuntimeError, match="unexpected retention quarantine entries"):
        module.version_dirs(group)


def test_transaction_journal_rejects_unexpected_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    isolate_retention_roots(module, tmp_path, monkeypatch)
    transaction_root = module.prune_transaction_root()
    transaction_root.mkdir(parents=True)
    (transaction_root / "notes.txt").write_text("not a journal", encoding="utf-8")

    with pytest.raises(RuntimeError, match="unexpected retention transaction entries"):
        module.reconcile_prune_transactions(protected=set(), apply=False)


def test_regression_canonical_inputs_only() -> None:
    module = load_publisher()
    assert "merger/repoground/cli/ground.py" in module.GENERATOR_INPUT_PATHS
    assert "merger/repoground/cli/cmd_ground.py" in module.GENERATOR_INPUT_PATHS
    assert not any("lenskit" in path for path in module.GENERATOR_INPUT_PATHS)
    assert not any("repobrief" in path for path in module.GENERATOR_INPUT_PATHS)


def test_discover_uses_literal_origin_when_global_insteadof_rewrites(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    repos_root = tmp_path / "repos"
    repos_root.mkdir()
    monkeypatch.setattr(module, "REPOS_ROOT", repos_root)

    repo, _ = initialize_repository(repos_root, "member")
    literal = "https://github.com/heimgewebe/member.git"
    git(repo, "remote", "add", "origin", literal)

    home = tmp_path / "home"
    home.mkdir()
    (home / ".gitconfig").write_text(
        "[url \"ssh://git@github.com/\"]\n"
        "    insteadOf = https://github.com/\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(home))

    assert git(repo, "remote", "get-url", "origin") == (
        "ssh://git@github.com/heimgewebe/member.git"
    )

    entries = module.discover()
    assert len(entries) == 1
    assert entries[0].key == "heimgewebe/member"
    assert entries[0].remote == literal


def test_regression_discover_canonicalizes_retired_lenskit_alias(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    repos_root = tmp_path / "repos"
    repos_root.mkdir()
    monkeypatch.setattr(module, "REPOS_ROOT", repos_root)

    repoground, _ = initialize_repository(repos_root, "repoground")
    git(
        repoground,
        "remote",
        "add",
        "origin",
        "git@github.com:heimgewebe/repoground.git",
    )
    lenskit, _ = initialize_repository(repos_root, "lenskit")
    git(
        lenskit,
        "remote",
        "add",
        "origin",
        "git@github.com:heimgewebe/lenskit.git",
    )

    entries = {entry.key: entry for entry in module.discover()}
    assert set(entries) == {"heimgewebe/repoground"}
    assert entries["heimgewebe/repoground"].path == repoground
    assert entries["heimgewebe/repoground"].repo == "repoground"


def test_regression_discover_does_not_promote_retired_alias_without_canonical_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    repos_root = tmp_path / "repos"
    repos_root.mkdir()
    monkeypatch.setattr(module, "REPOS_ROOT", repos_root)

    lenskit, _ = initialize_repository(repos_root, "lenskit")
    git(
        lenskit,
        "remote",
        "add",
        "origin",
        "git@github.com:heimgewebe/lenskit.git",
    )

    entries = module.discover()
    assert entries == []

def test_publication_state_separates_generator_commit_and_input_hash(
    tmp_path: Path,
) -> None:
    module = load_publisher()
    state_file = tmp_path / "heimgewebe__demo__main.state.json"
    publication_dir = tmp_path / "publication"
    publication_dir.mkdir()
    manifest = publication_dir / "demo_merge.bundle.manifest.json"
    manifest.write_text("{}\n", encoding="utf-8")
    source_sha = "a" * 40
    generator_inputs_sha = "b" * 64
    tool_sha = "d" * 40
    identity = {
        "source_sha": source_sha,
        "generator_inputs_sha": generator_inputs_sha,
    }

    module.write_state(
        state_file,
        fingerprint="c" * 64,
        identity=identity,
        tool_sha=tool_sha,
        repository="heimgewebe__demo",
        ref="main",
        publication_dir=publication_dir,
        manifest_path=str(manifest),
        publication_created_at="2026-07-14T10:00:00Z",
        previous_state=None,
        remote_sha=source_sha,
        remote_ref="origin/main",
        published_now=True,
    )

    data = json.loads(state_file.read_text(encoding="utf-8"))
    assert data["schema"] == module.STATE_SCHEMA
    assert data["repo_id"] == "heimgewebe__demo"
    assert data["stem"] == "heimgewebe__demo__main"
    assert data["created_at"] == "2026-07-14T10:00:00Z"
    assert data["created_at_basis"] == "external_manifest_generated_at"
    assert data["source_commit"] == source_sha
    assert data["generator_commit"] == tool_sha
    assert data["generator_commit_status"] == "recorded"
    assert data["generator_inputs_sha"] == generator_inputs_sha
    assert data["manifest_path"] == str(manifest)
    freshness = data["provenance"]["freshness"]
    assert freshness["status"] == "fresh_at_publication"
    assert freshness["remote_commit"] == source_sha
    assert freshness["live_recheck_required"] is True


def test_legacy_state_migration_uses_manifest_without_rebinding_generator(
    tmp_path: Path,
) -> None:
    module = load_publisher()
    publication_dir = tmp_path / "publication"
    publication_dir.mkdir()
    manifest = publication_dir / "demo_merge.bundle.manifest.json"
    manifest.write_text(
        json.dumps({"created_at": "2026-07-01T12:00:00Z"}) + "\n",
        encoding="utf-8",
    )
    source_sha = "a" * 40
    generator_inputs_sha = "b" * 64
    previous = {
        "schema": module.STATE_SCHEMA,
        "fingerprint": "c" * 64,
        "identity": {
            "source_sha": source_sha,
            "generator_inputs_sha": generator_inputs_sha,
        },
        "publication_dir": str(publication_dir),
        "updated_at": "2026-07-01T12:01:00Z",
    }
    state_file = tmp_path / "state.json"

    module.write_state(
        state_file,
        fingerprint="c" * 64,
        identity=previous["identity"],
        tool_sha="d" * 40,
        repository="heimgewebe__demo",
        ref="main",
        publication_dir=None,
        manifest_path=None,
        publication_created_at=None,
        previous_state=previous,
        remote_sha=source_sha,
        remote_ref="origin/main",
        published_now=False,
    )

    migrated = json.loads(state_file.read_text(encoding="utf-8"))
    assert migrated["created_at"] == "2026-07-01T12:00:00Z"
    assert migrated["created_at_basis"] == "bundle_manifest_created_at"
    assert migrated["manifest_path"] == str(manifest)
    assert migrated["generator_commit"] is None
    assert migrated["generator_commit_status"] == "unavailable_legacy_state"
    assert migrated["generator_inputs_sha"] == generator_inputs_sha
    assert migrated["provenance"]["freshness"]["status"] == "fresh"


def test_regression_canonical_unit_names_and_installer_cutover_order() -> None:
    units = sorted(path.name for path in UNIT_DIR.iterdir())
    assert units == [
        "repoground-publish-fleet-watch.service",
        "repoground-publish-fleet-watch.timer",
    ]

    installer = INSTALLER.read_text(encoding="utf-8")
    assert "rb-publish-fleet-watch.timer" in installer
    assert "rb-publish-fleet-watch.service" in installer
    assert "systemctl --user disable --now" in installer
    assert 'for unit in "${OLD_TIMERS[@]}" "${OLD_UNITS[@]}"' in installer
    assert 'rm -f -- "$UNIT_DIR/$unit"' in installer
    assert 'systemctl --user reset-failed "$unit"' in installer
    install_position = installer.index("ops/systemd/repoground-fleet")
    reload_position = installer.index("systemctl --user daemon-reload")
    enable_position = installer.index(
        "systemctl --user enable --now repoground-publish-fleet-watch.timer"
    )
    assert install_position < reload_position < enable_position


def test_dirty_managed_worktree_is_typed_and_preserved(tmp_path: Path) -> None:
    module = load_publisher()
    repo, sha = initialize_repository(tmp_path)
    worktree = tmp_path / "managed"
    git(repo, "worktree", "add", "--detach", str(worktree), sha)
    tracked = worktree / "tracked.txt"
    tracked.write_text("operator-owned change\n", encoding="utf-8")

    with pytest.raises(module.ManagedWorktreeDirtyError) as caught:
        module.assert_managed_worktree_clean(worktree, repo)

    assert tracked.read_text(encoding="utf-8") == "operator-owned change\n"
    receipt = caught.value.receipt()
    assert receipt["reason"] == "managed_worktree_dirty"
    assert receipt["automatic_reset_authorized"] is False
    assert receipt["status_count"] == 1
    assert receipt["status_sample"] == [{"code": " M", "path": "tracked.txt"}]
    assert receipt["status_truncated"] is False


def test_legacy_dirty_source_no_longer_gates_revision_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    roots = isolate_retention_roots(module, tmp_path, monkeypatch)
    source_root = tmp_path / "sources"
    source_root.mkdir()
    monkeypatch.setattr(module, "SOURCE_ROOT", source_root)
    monkeypatch.setattr(module, "FLEET_LOG", roots["log"] / "fleet.log")

    repo, source_sha = initialize_repository(tmp_path, "demo")
    entry = module.RepoEntry(
        key="heimgewebe/demo",
        owner="heimgewebe",
        repo="demo",
        path=repo,
        remote="git@github.com:heimgewebe/demo.git",
    )
    legacy = module.source_worktree_path(entry, "main")
    git(repo, "worktree", "add", "--detach", str(legacy), source_sha)
    tracked = legacy / "tracked.txt"
    tracked.write_text("historical operator change\n", encoding="utf-8")

    source = module.ensure_source_worktree(entry, "main", source_sha)

    assert source == module.revision_source_worktree_path(entry, "main", source_sha)
    assert source != legacy
    assert git(source, "rev-parse", "HEAD") == source_sha
    assert git(source, "status", "--porcelain") == ""
    assert tracked.read_text(encoding="utf-8") == "historical operator change\n"
    assert git(legacy, "status", "--porcelain") == "M tracked.txt"
    assert not (roots["state"] / "managed-source-recoveries").exists()


def test_dirty_revision_source_is_preserved_and_replaced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    roots = isolate_retention_roots(module, tmp_path, monkeypatch)
    source_root = tmp_path / "sources"
    source_root.mkdir()
    monkeypatch.setattr(module, "SOURCE_ROOT", source_root)
    monkeypatch.setattr(module, "FLEET_LOG", roots["log"] / "fleet.log")

    repo, source_sha = initialize_repository(tmp_path, "demo")
    entry = module.RepoEntry(
        key="heimgewebe/demo",
        owner="heimgewebe",
        repo="demo",
        path=repo,
        remote="git@github.com:heimgewebe/demo.git",
    )
    primary = module.revision_source_worktree_path(entry, "main", source_sha)
    git(repo, "worktree", "add", "--detach", str(primary), source_sha)
    tracked = primary / "tracked.txt"
    tracked.write_text("operator-owned source change\n", encoding="utf-8")

    replacement = module.ensure_source_worktree(entry, "main", source_sha)

    assert replacement != primary
    assert replacement.name.startswith(primary.name + "--recovery-")
    assert tracked.read_text(encoding="utf-8") == "operator-owned source change\n"
    assert git(primary, "status", "--porcelain") == "M tracked.txt"
    assert git(replacement, "rev-parse", "HEAD") == source_sha
    assert git(replacement, "status", "--porcelain") == ""
    receipts = list((roots["state"] / "managed-source-recoveries").glob("*.json"))
    assert len(receipts) == 1
    receipt = json.loads(receipts[0].read_text(encoding="utf-8"))
    assert receipt["schema"] == module.SOURCE_RECOVERY_SCHEMA
    assert receipt["repository"] == "heimgewebe/demo"
    assert receipt["source_commit"] == source_sha
    assert receipt["preserved_worktree"] == str(primary)
    assert receipt["replacement_worktree"] == str(replacement)
    assert receipt["preserved_source_mutated"] is False
    assert receipt["automatic_reset_authorized"] is False
    assert receipt["reason"]["kind"] == "managed_worktree_dirty"

def test_source_recovery_receipt_failure_rolls_back_clean_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    roots = isolate_retention_roots(module, tmp_path, monkeypatch)
    source_root = tmp_path / "sources"
    source_root.mkdir()
    monkeypatch.setattr(module, "SOURCE_ROOT", source_root)
    monkeypatch.setattr(module, "FLEET_LOG", roots["log"] / "fleet.log")

    repo, source_sha = initialize_repository(tmp_path, "demo")
    entry = module.RepoEntry(
        key="heimgewebe/demo",
        owner="heimgewebe",
        repo="demo",
        path=repo,
        remote="git@github.com:heimgewebe/demo.git",
    )
    primary = module.revision_source_worktree_path(entry, "main", source_sha)
    git(repo, "worktree", "add", "--detach", str(primary), source_sha)
    tracked = primary / "tracked.txt"
    tracked.write_text("preserve after receipt failure\n", encoding="utf-8")

    def fail_receipt(**_kwargs: object) -> Path:
        raise OSError("receipt store unavailable")

    monkeypatch.setattr(module, "record_source_recovery", fail_receipt)

    with pytest.raises(OSError, match="receipt store unavailable"):
        module.ensure_source_worktree(entry, "main", source_sha)

    assert tracked.read_text(encoding="utf-8") == "preserve after receipt failure\n"
    assert git(primary, "status", "--porcelain") == "M tracked.txt"
    assert sorted(path.name for path in source_root.iterdir()) == [primary.name]
    assert not (roots["state"] / "managed-source-recoveries").exists()


def test_unrelated_source_prepare_failure_remains_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    source_root = tmp_path / "sources"
    source_root.mkdir()
    monkeypatch.setattr(module, "SOURCE_ROOT", source_root)
    repo, source_sha = initialize_repository(tmp_path, "demo")
    entry = module.RepoEntry(
        key="heimgewebe/demo",
        owner="heimgewebe",
        repo="demo",
        path=repo,
        remote="git@github.com:heimgewebe/demo.git",
    )

    def fail_prepare(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("unrelated worktree failure")

    monkeypatch.setattr(module, "prepare_managed_worktree", fail_prepare)

    with pytest.raises(RuntimeError, match="unrelated worktree failure"):
        module.ensure_source_worktree(entry, "main", source_sha)
    assert list(source_root.iterdir()) == []


def test_unknown_build_residue_is_preserved_and_bypassed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    roots = isolate_retention_roots(module, tmp_path, monkeypatch)
    source_root = tmp_path / "sources"
    source_root.mkdir()
    monkeypatch.setattr(module, "SOURCE_ROOT", source_root)
    monkeypatch.setattr(module, "FLEET_LOG", roots["log"] / "fleet.log")
    allow_no_active_managed_build_leases(module, monkeypatch)

    repo, source_sha = initialize_repository(tmp_path, "demo")
    entry = module.RepoEntry(
        key="heimgewebe/demo",
        owner="heimgewebe",
        repo="demo",
        path=repo,
        remote="git@github.com:heimgewebe/demo.git",
    )
    primary = module.revision_source_worktree_path(entry, "main", source_sha)
    git(repo, "worktree", "add", "--detach", str(primary), source_sha)
    build = primary / "build"
    build.mkdir()
    artifact = build / "operator-artifact.txt"
    artifact.write_text("retain me\n", encoding="utf-8")

    replacement = module.ensure_source_worktree(entry, "main", source_sha)

    assert replacement != primary
    assert artifact.read_text(encoding="utf-8") == "retain me\n"
    assert git(primary, "rev-parse", "HEAD") == source_sha
    assert git(replacement, "rev-parse", "HEAD") == source_sha
    assert git(replacement, "status", "--porcelain") == ""
    receipts = list((roots["state"] / "managed-source-recoveries").glob("*.json"))
    assert len(receipts) == 1
    receipt = json.loads(receipts[0].read_text(encoding="utf-8"))
    assert receipt["reason"]["kind"] == "managed_build_residue"
    assert receipt["reason"]["receipt"]["classification"] == "unknown"
    assert receipt["preserved_source_mutated"] is False


def test_source_revision_prune_removes_only_clean_idle_unleased_worktrees(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    source_root = tmp_path / "sources"
    source_root.mkdir()
    monkeypatch.setattr(module, "SOURCE_ROOT", source_root)
    allow_no_active_managed_build_leases(module, monkeypatch)

    repo, source_sha = initialize_repository(tmp_path, "demo")
    entry = module.RepoEntry(
        key="heimgewebe/demo",
        owner="heimgewebe",
        repo="demo",
        path=repo,
        remote="git@github.com:heimgewebe/demo.git",
    )
    current = module.revision_source_worktree_path(entry, "main", source_sha)
    clean_old = module.revision_source_worktree_path(
        entry, "main", source_sha, recovery_id="a" * 12
    )
    dirty_old = module.revision_source_worktree_path(
        entry, "main", source_sha, recovery_id="b" * 12
    )
    foreign_prefix_match = module.source_worktree_path(entry, "main").with_name(
        module.source_worktree_path(entry, "main").name + "--operator"
    )
    another_ref = module.revision_source_worktree_path(
        entry, "main--feature", source_sha
    )
    for worktree in (
        current,
        clean_old,
        dirty_old,
        foreign_prefix_match,
        another_ref,
    ):
        git(repo, "worktree", "add", "--detach", str(worktree), source_sha)
    (dirty_old / "tracked.txt").write_text("operator change\n", encoding="utf-8")

    report = module.prune_obsolete_revision_source_worktrees(entry, "main", current)

    assert current.is_dir()
    assert not clean_old.exists()
    assert dirty_old.is_dir()
    assert foreign_prefix_match.is_dir()
    assert another_ref.is_dir()
    assert str(clean_old) in report["removed"]
    preserved = {row["path"]: row["reason"] for row in report["preserved"]}
    assert str(dirty_old) in preserved
    assert preserved[str(foreign_prefix_match)] == "source_identity_not_revision_bound"
    assert preserved[str(another_ref)] == "source_identity_not_revision_bound"
    assert (dirty_old / "tracked.txt").read_text(encoding="utf-8") == "operator change\n"


def test_dirty_generator_worktree_remains_a_hard_preflight_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    roots = isolate_retention_roots(module, tmp_path, monkeypatch)
    monkeypatch.setattr(module, "LOCK_PATH", tmp_path / "fleet.lock")
    monkeypatch.setattr(module, "FLEET_LOG", roots["log"] / "fleet.log")
    entry = module.RepoEntry(
        key="heimgewebe/demo",
        owner="heimgewebe",
        repo="demo",
        path=tmp_path / "demo",
        remote="git@github.com:heimgewebe/demo.git",
    )
    monkeypatch.setattr(module, "discover", lambda: [entry])
    dirty_tool = tmp_path / "tool-worktree"

    def dirty_generator() -> tuple[str, str]:
        raise module.ManagedWorktreeDirtyError(dirty_tool, [(" M", "generator.py")])

    monkeypatch.setattr(module, "ensure_tool_worktree", dirty_generator)

    assert module.main(["--repo", "heimgewebe/demo"]) == 1
    receipt = json.loads((roots["log"] / "fleet-last.json").read_text(encoding="utf-8"))
    assert receipt["status"] == "error"
    assert receipt["phase"] == "generator_preflight"
    assert receipt["failed"] == 1
    assert "managed worktree is not clean" in receipt["error"]
    assert "deferred" not in receipt


def test_managed_build_blocker_is_structured_in_fleet_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    roots = isolate_retention_roots(module, tmp_path, monkeypatch)
    monkeypatch.setattr(module, "LOCK_PATH", tmp_path / "fleet.lock")
    monkeypatch.setattr(module, "FLEET_LOG", roots["log"] / "fleet.log")
    entry = module.RepoEntry(
        key="heimgewebe/demo",
        owner="heimgewebe",
        repo="demo",
        path=tmp_path / "demo",
        remote="git@github.com:heimgewebe/demo.git",
    )
    monkeypatch.setattr(module, "discover", lambda: [entry])
    monkeypatch.setattr(
        module,
        "prioritize_fleet_publication",
        lambda entries: (entries, {"policy": "test"}),
    )
    monkeypatch.setattr(
        module,
        "reconcile_prune_transactions",
        lambda *, protected, apply: {"status": "ok"},
    )
    monkeypatch.setattr(module, "ensure_tool_worktree", lambda: ("b" * 40, "c" * 64))
    monkeypatch.setattr(
        module, "remote_head_for_entry", lambda entry: ("origin/main", "main", "a" * 40)
    )
    monkeypatch.setattr(
        module,
        "publication_config",
        lambda entry: module.PublicationConfig(profile="full-max"),
    )

    def block(entry: object, ref_segment: str) -> list[str]:
        raise module.managed_build_blocker(
            tmp_path / "sources" / "demo" / "build",
            classification="unknown",
            reason="no exact publisher provenance",
        )

    monkeypatch.setattr(module, "publish", lambda *args, **kwargs: block(entry, "main"))

    assert module.main(["--repo", "heimgewebe/demo"]) == 1
    receipt = json.loads((roots["log"] / "fleet-last.json").read_text(encoding="utf-8"))
    detail = receipt["details"][0]
    assert detail["status"] == "failed"
    assert detail["managed_build_residue"] == {
        "schema": module.MANAGED_BUILD_RESIDUE_SCHEMA,
        "classification": "unknown",
        "path": str(tmp_path / "sources" / "demo" / "build"),
        "reason": "no exact publisher provenance",
        "automatic_mutation_authorized": False,
    }


def test_durable_retain_blocker_is_nonfatal_but_visible_in_fleet_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    roots = isolate_retention_roots(module, tmp_path, monkeypatch)
    monkeypatch.setattr(module, "LOCK_PATH", tmp_path / "fleet.lock")
    monkeypatch.setattr(module, "FLEET_LOG", roots["log"] / "fleet.log")
    entry = module.RepoEntry(
        key="heimgewebe/demo",
        owner="heimgewebe",
        repo="demo",
        path=tmp_path / "demo",
        remote="git@github.com:heimgewebe/demo.git",
    )
    monkeypatch.setattr(module, "discover", lambda: [entry])
    monkeypatch.setattr(
        module,
        "prioritize_fleet_publication",
        lambda entries: (entries, {"policy": "test"}),
    )
    monkeypatch.setattr(
        module,
        "reconcile_prune_transactions",
        lambda *, protected, apply: {"status": "ok"},
    )
    monkeypatch.setattr(module, "ensure_tool_worktree", lambda: ("b" * 40, "c" * 64))
    monkeypatch.setattr(
        module, "remote_head_for_entry", lambda entry: ("origin/main", "main", "a" * 40)
    )
    monkeypatch.setattr(
        module,
        "publication_config",
        lambda entry: module.PublicationConfig(profile="full-max"),
    )

    def retain(entry: object, ref_segment: str) -> list[str]:
        raise module.managed_build_blocker(
            tmp_path / "sources" / "demo" / "build",
            classification="durable-retain",
            reason="exact manager retain decision is active",
            retain_decision={
                "task_id": "OPERATOR-ECOSYSTEM-REDUNDANCY-V1-T053",
                "review_after_unix": 9999999999,
                "automatic_mutation_authorized": False,
            },
        )

    monkeypatch.setattr(module, "publish", lambda *args, **kwargs: retain(entry, "main"))

    assert module.main(["--repo", "heimgewebe/demo"]) == 0
    receipt = json.loads((roots["log"] / "fleet-last.json").read_text(encoding="utf-8"))
    detail = receipt["details"][0]
    assert receipt["status"] == "warn"
    assert receipt["retained"] == 1
    assert receipt["failed"] == 0
    assert detail["status"] == "retained"
    assert detail["managed_build_residue"]["classification"] == "durable-retain"


def test_missing_generator_inputs_fail_before_publication_and_write_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    roots = isolate_retention_roots(module, tmp_path, monkeypatch)
    monkeypatch.setattr(module, "LOCK_PATH", tmp_path / "fleet.lock")
    monkeypatch.setattr(module, "FLEET_LOG", roots["log"] / "fleet.log")
    entry = module.RepoEntry(
        key="heimgewebe/demo",
        owner="heimgewebe",
        repo="demo",
        path=tmp_path / "demo",
        remote="git@github.com:heimgewebe/demo.git",
    )
    monkeypatch.setattr(module, "discover", lambda: [entry])
    monkeypatch.setattr(
        module,
        "ensure_tool_worktree",
        lambda: (_ for _ in ()).throw(
            RuntimeError("missing required generator inputs: ['cmd_ground.py']")
        ),
    )
    monkeypatch.setattr(
        module,
        "publish",
        lambda *args, **kwargs: pytest.fail("publication must not start"),
    )

    assert module.main(["--repo", "heimgewebe/demo"]) == 1
    receipt = json.loads((roots["log"] / "fleet-last.json").read_text(encoding="utf-8"))
    assert receipt["status"] == "error"
    assert receipt["phase"] == "generator_preflight"
    assert "missing required generator inputs" in receipt["error"]
    assert not roots["publication"].exists()


def test_idempotent_second_run_does_not_publish_or_create_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    roots = isolate_retention_roots(module, tmp_path, monkeypatch)
    monkeypatch.setattr(module, "LOCK_PATH", tmp_path / "fleet.lock")
    monkeypatch.setattr(module, "FLEET_LOG", roots["log"] / "fleet.log")
    monkeypatch.setattr(
        module,
        "reconcile_prune_transactions",
        lambda *, protected, apply: {"status": "ok"},
    )
    publication_root = roots["publication"]
    entry = module.RepoEntry(
        key="heimgewebe/demo",
        owner="heimgewebe",
        repo="demo",
        path=tmp_path / "demo",
        remote="git@github.com:heimgewebe/demo.git",
    )
    source_sha = "a" * 40
    tool_sha = "d" * 40
    generator_inputs_sha = "b" * 64
    publish_calls: list[Path] = []

    def mock_publish(*args, **kwargs):
        out_dir = (
            publication_root
            / "bundles"
            / "heimgewebe__demo"
            / "main"
            / "20260714T100000Z"
        )
        out_dir.mkdir(parents=True, exist_ok=False)
        manifest = out_dir / "demo_merge.bundle.manifest.json"
        manifest.write_text("{}\n", encoding="utf-8")
        publish_calls.append(out_dir)
        data = {
            "publication": {
                "published": [
                    {"generatedAt": "2026-07-14T10:00:00Z"},
                    {"generatedAt": "2026-07-14T10:00:00Z"},
                ]
            }
        }
        return (
            data,
            out_dir,
            tmp_path / "fake-lease.json",
            str(manifest),
            "2026-07-14T10:00:00Z",
            tmp_path / "fake-source-worktree",
        )

    monkeypatch.setattr(module, "publish", mock_publish)
    monkeypatch.setattr(
        module,
        "ensure_tool_worktree",
        lambda: (tool_sha, generator_inputs_sha),
    )
    monkeypatch.setattr(
        module,
        "remote_head_for_entry",
        lambda entry: ("origin/main", "main", source_sha),
    )
    monkeypatch.setattr(module, "clear_active_publication_lease", lambda path: None)
    monkeypatch.setattr(
        module,
        "prune_obsolete_revision_source_worktrees",
        lambda *args, **kwargs: {"removed": [], "preserved": []},
    )
    monkeypatch.setattr(module, "prune_current_group", lambda *args, **kwargs: {})
    monkeypatch.setattr(module, "discover", lambda: [entry])

    argv = ["--repo", "heimgewebe/demo"]
    assert module.main(argv) == 0
    state_file = roots["state"] / "heimgewebe__demo__main.state.json"
    first = json.loads(state_file.read_text(encoding="utf-8"))
    version_parent = publication_root / "bundles" / "heimgewebe__demo" / "main"
    assert [path.name for path in version_parent.iterdir()] == ["20260714T100000Z"]
    assert len(publish_calls) == 1

    assert module.main(argv) == 0
    second = json.loads(state_file.read_text(encoding="utf-8"))
    assert len(publish_calls) == 1
    assert [path.name for path in version_parent.iterdir()] == ["20260714T100000Z"]
    assert second["created_at"] == first["created_at"]
    assert second["generator_commit"] == first["generator_commit"] == tool_sha
    assert second["generator_inputs_sha"] == generator_inputs_sha
    assert second["manifest_path"] == first["manifest_path"]
    assert second["publication_dir"] == first["publication_dir"]
    assert second["provenance"]["freshness"]["status"] == "fresh"
    assert second["provenance"]["freshness"]["live_recheck_required"] is False

def _fake_systemctl_environment(tmp_path: Path, home: Path) -> tuple[dict[str, str], Path]:
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    log = tmp_path / "systemctl.log"
    systemctl = fake_bin / "systemctl"
    systemctl.write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' \"$*\" >> \"$SYSTEMCTL_LOG\"\n",
        encoding="utf-8",
    )
    systemctl.chmod(0o755)
    environment = os.environ.copy()
    environment.update(
        {
            "HOME": str(home),
            "PATH": f"{fake_bin}:{environment['PATH']}",
            "SYSTEMCTL_LOG": str(log),
        }
    )
    return environment, log


def test_runtime_installer_migrates_publication_policy_state_and_removes_wrapper(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    old_root = home / ".local/state/repobrief-publication-policy"
    new_root = home / ".local/state/repoground-publication-policy"
    old_root.mkdir(parents=True)
    record = old_root / "records/example.json"
    record.parent.mkdir()
    original = b'{"schema":"repobrief.publication-record.v1","lenskit_version":"3.0.0"}\n'
    record.write_bytes(original)

    bin_dir = home / ".local/bin"
    bin_dir.mkdir(parents=True)
    legacy = bin_dir / "rb-publication-policy"
    legacy.write_text(LEGACY_PUBLICATION_POLICY_WRAPPER, encoding="utf-8")
    legacy.chmod(0o755)
    environment, _ = _fake_systemctl_environment(tmp_path, home)

    completed = subprocess.run(
        [str(INSTALLER)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        env=environment,
    )

    assert completed.returncode == 0, completed.stderr
    assert not old_root.exists()
    assert (new_root / "records/example.json").read_bytes() == original
    assert new_root.stat().st_mode & 0o777 == 0o700
    assert (bin_dir / "repoground-publication-policy").is_file()
    assert not legacy.exists()


def test_runtime_installer_rejects_dual_publication_policy_state_roots(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    (home / ".local/state/repobrief-publication-policy").mkdir(parents=True)
    (home / ".local/state/repoground-publication-policy").mkdir(parents=True)
    environment, systemctl_log = _fake_systemctl_environment(tmp_path, home)

    completed = subprocess.run(
        [str(INSTALLER)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        env=environment,
    )

    assert completed.returncode == 1
    assert "refusing dual truth" in completed.stderr
    assert not systemctl_log.exists()


def test_runtime_installer_rejects_unknown_legacy_publication_command(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    legacy = home / ".local/bin/rb-publication-policy"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("#!/bin/sh\necho unrelated\n", encoding="utf-8")
    legacy.chmod(0o755)
    environment, systemctl_log = _fake_systemctl_environment(tmp_path, home)

    completed = subprocess.run(
        [str(INSTALLER)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        env=environment,
    )

    assert completed.returncode == 1
    assert "unknown file at legacy publication-policy command path" in completed.stderr
    assert legacy.is_file()
    assert not systemctl_log.exists()

def test_runtime_installer_rejects_legacy_publication_marker_spoof(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    legacy = home / ".local/bin/rb-publication-policy"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(
        "#!/bin/sh\n"
        "# rb-publication-policy is deprecated; use repoground-publication-policy\n"
        "echo unrelated\n",
        encoding="utf-8",
    )
    legacy.chmod(0o755)
    environment, systemctl_log = _fake_systemctl_environment(tmp_path, home)

    completed = subprocess.run(
        [str(INSTALLER)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        env=environment,
    )

    assert completed.returncode == 1
    assert "unknown file at legacy publication-policy command path" in completed.stderr
    assert legacy.is_file()
    assert not systemctl_log.exists()


def test_fleet_membership_authority_ref_is_not_environment_overridable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REPOGROUND_FLEET_MEMBERSHIP_REF", "attacker-branch")
    module = load_publisher()

    assert module.FLEET_MEMBERSHIP_REF == "main"


@pytest.mark.parametrize(
    "raw",
    [
        "repos:\n  - name: repoground\nrepos:\n  - name: heim-pc\n",
        (
            "repos:\n"
            "  - name: repoground\n"
            "    owner: heimgewebe\n"
            "    owner: attacker\n"
        ),
        (
            "repos:\n"
            "  - <<: &trusted {owner: heimgewebe}\n"
            "    <<: &attacker {owner: attacker}\n"
            "    name: demo\n"
        ),
        (
            "repos:\n"
            "  - <<: [{owner: heimgewebe}, {owner: attacker}]\n"
            "    name: demo\n"
        ),
    ],
)
def test_fleet_membership_yaml_rejects_duplicate_mapping_keys(raw: str) -> None:
    module = load_publisher()

    with pytest.raises(RuntimeError, match="fleet membership YAML is invalid"):
        module._load_fleet_membership_yaml(raw)


def test_fleet_membership_yaml_preserves_merge_key_overrides() -> None:
    module = load_publisher()
    document = module._load_fleet_membership_yaml(
        "defaults: &defaults\n"
        "  owner: heimgewebe\n"
        "repos:\n"
        "  - <<: *defaults\n"
        "    owner: other\n"
        "    name: demo\n"
    )

    assert isinstance(document, dict)
    assert document["repos"][0] == {"owner": "other", "name": "demo"}


def test_fleet_membership_keys_follow_authoritative_semantics() -> None:
    module = load_publisher()
    document = {
        "static": {
            "include": [
                {
                    "name": "commonthing",
                    "url": "https://github.com/heimgewebe/commonthing",
                    "status": "related",
                },
                {
                    "name": "explicit-warm",
                    "url": "https://github.com/heimgewebe/explicit-warm",
                    "fleet": True,
                },
            ]
        },
        "repos": [
            {"name": "repoground"},
            "heimgewebe/wgx",
            {"name": "retired", "fleet": False},
        ],
    }

    assert module._fleet_membership_keys(document) == (
        "heimgewebe/repoground",
        "heimgewebe/wgx",
        "heimgewebe/explicit-warm",
    )


def test_fleet_membership_keys_reject_unknown_root_fields() -> None:
    module = load_publisher()

    with pytest.raises(RuntimeError, match="root has unknown fields.*statci"):
        module._fleet_membership_keys(
            {
                "repos": [{"name": "repoground"}],
                "statci": {
                    "include": [
                        {
                            "name": "wgx",
                            "fleet": True,
                        }
                    ]
                },
            }
        )


def test_fleet_membership_keys_reject_unknown_entry_fields() -> None:
    module = load_publisher()

    with pytest.raises(RuntimeError, match="unknown fields.*fleat"):
        module._fleet_membership_keys(
            {
                "repos": [
                    {
                        "name": "repoground",
                        "fleat": False,
                    }
                ]
            }
        )



def test_fleet_membership_keys_reject_unknown_static_fields() -> None:
    module = load_publisher()

    with pytest.raises(RuntimeError, match="static has unknown fields.*incldue"):
        module._fleet_membership_keys(
            {
                "repos": [{"name": "repoground"}],
                "static": {
                    "incldue": [
                        {
                            "name": "wgx",
                            "fleet": True,
                        }
                    ]
                },
            }
        )


@pytest.mark.parametrize("fleet_value", ["false", 0, 1, None, [], {}])
def test_fleet_membership_keys_reject_non_boolean_fleet_flags(
    fleet_value: object,
) -> None:
    module = load_publisher()
    with pytest.raises(RuntimeError, match="fleet must be a boolean"):
        module._fleet_membership_keys(
            {
                "repos": [
                    {
                        "name": "repoground",
                        "fleet": fleet_value,
                    }
                ]
            }
        )


@pytest.mark.parametrize("static_value", [None, [], "invalid", 1, True])
def test_fleet_membership_keys_reject_malformed_static_sections(
    static_value: object,
) -> None:
    module = load_publisher()
    with pytest.raises(RuntimeError, match="static must be an object"):
        module._fleet_membership_keys(
            {
                "repos": [{"name": "repoground"}],
                "static": static_value,
            }
        )


def test_fleet_membership_keys_reject_null_static_include() -> None:
    module = load_publisher()
    with pytest.raises(RuntimeError, match=r"static\.include must be a list"):
        module._fleet_membership_keys(
            {
                "repos": [{"name": "repoground"}],
                "static": {"include": None},
            }
        )


def test_fleet_membership_keys_reject_conflicting_name_repo_fields() -> None:
    module = load_publisher()

    with pytest.raises(RuntimeError, match="name/repo must match"):
        module._fleet_membership_keys(
            {
                "repos": [
                    {
                        "name": "repoground",
                        "repo": "wgx",
                    }
                ]
            }
        )


@pytest.mark.parametrize(
    ("entry", "message"),
    [
        (
            {"name": "repoground", "url": "https://github.com/heimgewebe/wgx"},
            "URL conflicts with declared repository",
        ),
        (
            {
                "name": "repoground",
                "owner": "other",
                "url": "https://github.com/heimgewebe/repoground",
            },
            "URL conflicts with declared repository",
        ),
        (
            {"name": "heimgewebe/repoground", "owner": "other"},
            "owner conflicts with qualified repository",
        ),
    ],
)
def test_fleet_membership_keys_reject_conflicting_identity_fields(
    entry: dict[str, object],
    message: str,
) -> None:
    module = load_publisher()
    with pytest.raises(RuntimeError, match=message):
        module._fleet_membership_keys({"repos": [entry]})


def test_fleet_membership_keys_accept_url_only_identity() -> None:
    module = load_publisher()
    assert module._fleet_membership_keys(
        {"repos": [{"url": "https://github.com/other/demo"}]}
    ) == ("other/demo",)


def test_fleet_membership_keys_accept_matching_name_repo_fields() -> None:
    module = load_publisher()

    assert module._fleet_membership_keys(
        {
            "repos": [
                {
                    "name": "repoground",
                    "repo": "repoground",
                }
            ]
        }
    ) == ("heimgewebe/repoground",)


@pytest.mark.parametrize("owner_value", [False, 0, None, [], {}, "", "   "])
def test_fleet_membership_keys_reject_malformed_owner_values(
    owner_value: object,
) -> None:
    module = load_publisher()
    with pytest.raises(RuntimeError, match="owner must be a non-empty string"):
        module._fleet_membership_keys(
            {
                "repos": [
                    {
                        "name": "repoground",
                        "owner": owner_value,
                    }
                ]
            }
        )


def test_fleet_membership_keys_reject_duplicates() -> None:
    module = load_publisher()
    with pytest.raises(RuntimeError, match="duplicate fleet membership"):
        module._fleet_membership_keys(
            {
                "repos": [
                    {"name": "repoground"},
                    "heimgewebe/repoground",
                ]
            }
        )


def test_authoritative_fleet_membership_reads_remote_main_not_dirty_worktree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_publisher()
    remote, _ = initialize_repository(tmp_path, "metarepo-remote")
    (remote / "fleet").mkdir()
    authoritative = (
        "---\n"
        "static:\n"
        "  include:\n"
        "    - name: commonthing\n"
        "      status: related\n"
        "repos:\n"
        "  - name: repoground\n"
        "  - name: heim-pc\n"
    )
    (remote / "fleet" / "repos.yml").write_text(authoritative, encoding="utf-8")
    git(remote, "add", "fleet/repos.yml")
    git(remote, "commit", "-m", "authoritative fleet")
    remote_head = git(remote, "rev-parse", "HEAD")

    checkout = tmp_path / "metarepo-checkout"
    completed = subprocess.run(
        ["git", "clone", "--quiet", str(remote), str(checkout)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout
    (checkout / "fleet" / "repos.yml").write_text(
        "repos:\n  - name: wrong-local-value\n",
        encoding="utf-8",
    )
    assert git(checkout, "status", "--porcelain")

    monkeypatch.setattr(module, "METAREPO_REPO", checkout)
    original_run = module.run

    def run_with_authority_origin(
        argv: list[str],
        cwd: Path | None = None,
        check: bool = True,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        if argv[-3:] == ["remote", "get-url", "origin"]:
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout="org-236528253@github.com:heimgewebe/metarepo.git\n",
            )
        return original_run(argv, cwd=cwd, check=check, env=env)

    monkeypatch.setattr(module, "run", run_with_authority_origin)
    original_isolated = module.read_remote_branch_blob_isolated

    def read_fixture_remote(
        origin_url: str,
        branch: str,
        path: str,
        *,
        env: dict[str, str],
        max_bytes: int,
    ) -> tuple[str, str, bytes]:
        assert origin_url == module.FLEET_MEMBERSHIP_REMOTE
        return original_isolated(
            str(remote),
            branch,
            path,
            env=env,
            max_bytes=max_bytes,
        )

    monkeypatch.setattr(
        module,
        "read_remote_branch_blob_isolated",
        read_fixture_remote,
    )
    membership = module.load_authoritative_fleet_membership()

    assert membership.keys == (
        "heimgewebe/repoground",
        "heimgewebe/heim-pc",
    )
    assert membership.source_commit == remote_head
    assert membership.source_ref == "refs/heads/main"
    assert membership.receipt()["source_ref"] == "refs/heads/main"
    assert membership.content_sha256 == hashlib.sha256(
        authoritative.encode("utf-8")
    ).hexdigest()


def test_authoritative_fleet_membership_preserves_crlf_blob_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_publisher()
    remote, _ = initialize_repository(tmp_path, "metarepo-crlf")
    (remote / "fleet").mkdir()
    authoritative = (
        b"---\r\n"
        b"repos:\r\n"
        b"  - name: repoground\r\n"
        b"  - name: heim-pc\r\n"
    )
    (remote / "fleet" / "repos.yml").write_bytes(authoritative)
    git(remote, "add", "fleet/repos.yml")
    git(remote, "commit", "-m", "authoritative fleet crlf")

    checkout = tmp_path / "metarepo-crlf-checkout"
    completed = subprocess.run(
        ["git", "clone", "--quiet", str(remote), str(checkout)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout

    monkeypatch.setattr(module, "METAREPO_REPO", checkout)
    original_run = module.run

    def run_with_authority_origin(
        argv: list[str],
        cwd: Path | None = None,
        check: bool = True,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        if argv[-3:] == ["remote", "get-url", "origin"]:
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout="org-236528253@github.com:heimgewebe/metarepo.git\n",
            )
        return original_run(argv, cwd=cwd, check=check, env=env)

    monkeypatch.setattr(module, "run", run_with_authority_origin)
    original_isolated = module.read_remote_branch_blob_isolated

    def read_fixture_remote(
        origin_url: str,
        branch: str,
        path: str,
        *,
        env: dict[str, str],
        max_bytes: int,
    ) -> tuple[str, str, bytes]:
        assert origin_url == module.FLEET_MEMBERSHIP_REMOTE
        return original_isolated(
            str(remote),
            branch,
            path,
            env=env,
            max_bytes=max_bytes,
        )

    monkeypatch.setattr(
        module,
        "read_remote_branch_blob_isolated",
        read_fixture_remote,
    )
    membership = module.load_authoritative_fleet_membership()

    assert membership.keys == (
        "heimgewebe/repoground",
        "heimgewebe/heim-pc",
    )
    assert membership.content_sha256 == hashlib.sha256(authoritative).hexdigest()


def test_authoritative_fleet_membership_rejects_wrong_origin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_publisher()
    checkout, _ = initialize_repository(tmp_path, "metarepo")
    git(
        checkout,
        "remote",
        "add",
        "origin",
        "git@notgithub.com:heimgewebe/metarepo.git",
    )

    monkeypatch.setattr(module, "METAREPO_REPO", checkout)

    with pytest.raises(RuntimeError, match="origin mismatch"):
        module.load_authoritative_fleet_membership()


def test_authoritative_fleet_membership_rejects_unauthenticated_transport(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_publisher()
    checkout, _ = initialize_repository(tmp_path, "metarepo")
    git(
        checkout,
        "remote",
        "add",
        "origin",
        "http://github.com/heimgewebe/metarepo.git",
    )

    monkeypatch.setattr(module, "METAREPO_REPO", checkout)

    with pytest.raises(RuntimeError, match="must use HTTPS or SSH"):
        module.load_authoritative_fleet_membership()


def test_select_authoritative_fleet_entries_reports_missing_and_excluded(
    tmp_path: Path,
) -> None:
    module = load_publisher()
    entries = [
        module.RepoEntry(
            key="heimgewebe/repoground",
            owner="heimgewebe",
            repo="repoground",
            path=tmp_path / "repoground",
            remote="git@github.com:heimgewebe/repoground.git",
        ),
        module.RepoEntry(
            key="heimgewebe/old-local",
            owner="heimgewebe",
            repo="old-local",
            path=tmp_path / "old-local",
            remote="git@github.com:heimgewebe/old-local.git",
        ),
    ]
    membership = module.FleetMembership(
        keys=("heimgewebe/repoground", "heimgewebe/heim-pc"),
        source_commit="a" * 40,
        source_ref="origin/main",
        source_path="fleet/repos.yml",
        content_sha256="b" * 64,
    )

    selected, missing, excluded = module.select_authoritative_fleet_entries(
        entries,
        membership,
    )

    assert [entry.key for entry in selected] == ["heimgewebe/repoground"]
    assert missing == ["heimgewebe/heim-pc"]
    assert excluded == 1


def test_targeted_inventory_bypasses_fleet_membership_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = load_publisher()
    entry = module.RepoEntry(
        key="heimgewebe/nonfleet",
        owner="heimgewebe",
        repo="nonfleet",
        path=tmp_path / "nonfleet",
        remote="git@github.com:heimgewebe/nonfleet.git",
    )
    monkeypatch.setattr(module, "discover", lambda: [entry])

    def forbidden_membership() -> module.FleetMembership:
        raise AssertionError("targeted --repo must not require Fleet membership")

    monkeypatch.setattr(
        module,
        "load_authoritative_fleet_membership",
        forbidden_membership,
    )

    assert module.main(["--inventory", "--repo", "heimgewebe/nonfleet"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["repos"][0]["key"] == "heimgewebe/nonfleet"
    assert payload["membership"]["authority_required"] is False


def test_fleet_inventory_marks_missing_authoritative_member_as_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = load_publisher()
    entry = module.RepoEntry(
        key="heimgewebe/repoground",
        owner="heimgewebe",
        repo="repoground",
        path=tmp_path / "repoground",
        remote="git@github.com:heimgewebe/repoground.git",
    )
    membership = module.FleetMembership(
        keys=("heimgewebe/repoground", "heimgewebe/heim-pc"),
        source_commit="a" * 40,
        source_ref="origin/main",
        source_path="fleet/repos.yml",
        content_sha256="b" * 64,
    )
    monkeypatch.setattr(module, "discover", lambda: [entry])
    monkeypatch.setattr(
        module,
        "load_authoritative_fleet_membership",
        lambda: membership,
    )

    assert module.main(["--inventory"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "warn"
    assert payload["count"] == 2
    assert payload["membership"]["missing_local_members"] == [
        "heimgewebe/heim-pc"
    ]
    assert payload["membership"]["excluded_local_nonmember_count"] == 0

    assert (
        module.main(
            ["--inventory", "--inventory-allow-missing-local-members"]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "warn"
    assert payload["membership"]["missing_local_members"] == [
        "heimgewebe/heim-pc"
    ]


def test_busy_fleet_does_not_run_membership_preflight_or_replace_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = load_publisher()
    lock_path = tmp_path / "fleet.lock"
    log_root = tmp_path / "logs"
    monkeypatch.setattr(module, "LOCK_PATH", lock_path)
    monkeypatch.setattr(module, "LOG_ROOT", log_root)
    monkeypatch.setattr(module, "STATE_ROOT", tmp_path / "state")
    monkeypatch.setattr(module, "discover", lambda: [])

    def forbidden_membership() -> module.FleetMembership:
        raise AssertionError("busy invocation must not run membership preflight")

    monkeypatch.setattr(
        module,
        "load_authoritative_fleet_membership",
        forbidden_membership,
    )

    held_lock = module.acquire_lock()
    assert held_lock is not None
    try:
        assert module.main([]) == 0
    finally:
        held_lock.close()

    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "status": "busy",
        "reason": "fleet publisher already running",
    }
    assert not (log_root / "fleet-last.json").exists()


def test_fleet_membership_preflight_failure_persists_fleet_last(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = load_publisher()
    log_root = tmp_path / "logs"
    monkeypatch.setattr(module, "LOCK_PATH", tmp_path / "fleet.lock")
    monkeypatch.setattr(module, "LOG_ROOT", log_root)
    monkeypatch.setattr(module, "STATE_ROOT", tmp_path / "state")
    monkeypatch.setattr(module, "discover", lambda: [])

    def unavailable_membership() -> module.FleetMembership:
        raise RuntimeError("membership unavailable")

    monkeypatch.setattr(
        module,
        "load_authoritative_fleet_membership",
        unavailable_membership,
    )

    assert module.main([]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["phase"] == "fleet_membership"

    persisted = json.loads((log_root / "fleet-last.json").read_text(encoding="utf-8"))
    assert persisted == payload
