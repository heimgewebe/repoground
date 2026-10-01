from __future__ import annotations

import hashlib
import shlex
import importlib.machinery
import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest


ROOT = Path(__file__).resolve().parents[3]
PUBLISHER = ROOT / "scripts/ops/repoground-publish-fleet"


def load_publisher() -> ModuleType:
    module_name = "repoground_publish_fleet_replace_ref_test"
    loader = importlib.machinery.SourceFileLoader(module_name, str(PUBLISHER))
    spec = importlib.util.spec_from_loader(module_name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    loader.exec_module(module)
    return module


def git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout
    return completed.stdout.strip()


def initialize_repository(tmp_path: Path, name: str) -> Path:
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
    git(repo, "config", "user.name", "RepoGround Test")
    git(repo, "config", "user.email", "repoground-test@example.invalid")
    (repo / ".gitignore").write_text(".pytest_cache/\n__pycache__/\n", encoding="utf-8")
    (repo / "tracked.txt").write_text("base\n", encoding="utf-8")
    git(repo, "add", ".gitignore", "tracked.txt")
    git(repo, "commit", "-m", "initial")
    return repo


def test_authoritative_fleet_membership_ignores_local_replace_refs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_publisher()
    remote = initialize_repository(tmp_path, "metarepo-replace")
    (remote / "fleet").mkdir()
    authoritative = "repos:\n  - name: repoground\n"
    (remote / "fleet" / "repos.yml").write_text(authoritative, encoding="utf-8")
    git(remote, "add", "fleet/repos.yml")
    git(remote, "commit", "-m", "authoritative fleet")
    remote_head = git(remote, "rev-parse", "HEAD")

    checkout = tmp_path / "metarepo-replace-checkout"
    completed = subprocess.run(
        ["git", "clone", "--quiet", str(remote), str(checkout)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout
    git(checkout, "config", "user.name", "RepoGround Test")
    git(checkout, "config", "user.email", "repoground-test@example.invalid")

    (checkout / "fleet" / "repos.yml").write_text(
        "repos:\n  - name: attacker-controlled\n",
        encoding="utf-8",
    )
    git(checkout, "add", "fleet/repos.yml")
    git(checkout, "commit", "-m", "local replacement commit")
    replacement_sha = git(checkout, "rev-parse", "HEAD")
    assert replacement_sha != remote_head
    git(checkout, "replace", remote_head, replacement_sha)

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
    membership = module.load_authoritative_fleet_membership()

    assert membership.keys == ("heimgewebe/repoground",)
    assert membership.source_commit == remote_head
    assert membership.content_sha256 == hashlib.sha256(
        authoritative.encode("utf-8")
    ).hexdigest()


def test_authoritative_fleet_membership_rejects_checkout_local_ssh_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_publisher()
    authoritative = initialize_repository(tmp_path, "metarepo-authoritative")
    checkout = tmp_path / "metarepo-authoritative-checkout"
    completed = subprocess.run(
        ["git", "clone", "--quiet", str(authoritative), str(checkout)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout

    attacker = initialize_repository(tmp_path, "metarepo-attacker")
    (attacker / "fleet").mkdir()
    (attacker / "fleet" / "repos.yml").write_text(
        "repos:\n  - name: attacker-controlled\n",
        encoding="utf-8",
    )
    git(attacker, "add", "fleet/repos.yml")
    git(attacker, "commit", "-m", "attacker fleet")
    attacker_head = git(attacker, "rev-parse", "HEAD")

    fake_ssh = tmp_path / "fake-ssh"
    fake_ssh.write_text(
        "#!/bin/sh\nexec git-upload-pack "
        + shlex.quote(str(attacker))
        + "\n",
        encoding="utf-8",
    )
    fake_ssh.chmod(0o700)
    git(
        checkout,
        "remote",
        "set-url",
        "origin",
        "org-236528253@github.com:heimgewebe/metarepo.git",
    )
    git(checkout, "config", "core.sshCommand", str(fake_ssh))

    redirected = subprocess.run(
        [
            "git",
            "-C",
            str(checkout),
            "ls-remote",
            "--exit-code",
            "--refs",
            "--",
            "origin",
            "refs/heads/main",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert redirected.returncode == 0, redirected.stdout
    assert redirected.stdout.split()[0] == attacker_head

    monkeypatch.setattr(module, "METAREPO_REPO", checkout)
    with pytest.raises(
        RuntimeError,
        match="unsafe local Git transport configuration: core.sshcommand",
    ):
        module.load_authoritative_fleet_membership()


def test_authority_git_transport_guard_rejects_environment_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_publisher()
    repo = initialize_repository(tmp_path, "metarepo-env")
    for name in module._AUTHORITY_GIT_FORBIDDEN_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("GIT_CONFIG_COUNT", raising=False)
    monkeypatch.setenv("GIT_SSH_COMMAND", "ssh -F /tmp/attacker-config")

    with pytest.raises(
        RuntimeError,
        match="repository/transport overrides: GIT_SSH_COMMAND",
    ):
        module.assert_authority_git_transport_safe(repo)


@pytest.mark.parametrize(
    "key",
    [
        "core.sshCommand",
        "url.ssh://attacker.invalid/.insteadOf",
        "url.ssh://attacker.invalid/.pushInsteadOf",
        "remote.origin.uploadpack",
        "remote.origin.proxy",
        "http.proxy",
        "http.sslVerify",
        "include.path",
        "extensions.worktreeConfig",
    ],
)
def test_authority_git_transport_guard_classifies_local_overrides(key: str) -> None:
    module = load_publisher()
    assert module._authority_git_local_config_is_transport_override(key)
