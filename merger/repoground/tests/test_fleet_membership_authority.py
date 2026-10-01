from __future__ import annotations

import hashlib
import importlib.machinery
import importlib.util
import os
import random
import shlex
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


def bind_isolated_fetch_to_local_remote(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    remote: Path,
) -> None:
    original = module.read_remote_branch_blob_isolated
    git(remote, "config", "uploadpack.allowFilter", "true")

    def read_fixture_remote(
        origin_url: str,
        branch: str,
        path: str,
        *,
        env: dict[str, str],
        max_bytes: int,
    ) -> tuple[str, str, bytes]:
        assert module.parse_github_remote(origin_url) == ("heimgewebe", "metarepo")
        return original(
            remote.as_uri(),
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
    bind_isolated_fetch_to_local_remote(module, monkeypatch, remote)
    membership = module.load_authoritative_fleet_membership()

    assert membership.keys == ("heimgewebe/repoground",)
    assert membership.source_commit == remote_head
    assert membership.content_sha256 == hashlib.sha256(
        authoritative.encode("utf-8")
    ).hexdigest()


def test_authoritative_fleet_membership_ignores_forged_local_object_for_remote_sha(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_publisher()
    remote = initialize_repository(tmp_path, "metarepo-forged-remote")
    (remote / "fleet").mkdir()
    authoritative = "repos:\n  - name: repoground\n"
    (remote / "fleet" / "repos.yml").write_text(authoritative, encoding="utf-8")
    git(remote, "add", "fleet/repos.yml")
    git(remote, "commit", "-m", "authoritative fleet")
    remote_head = git(remote, "rev-parse", "HEAD")

    checkout = tmp_path / "metarepo-forged-checkout"
    completed = subprocess.run(
        [
            "git",
            "clone",
            "--quiet",
            "--no-hardlinks",
            str(remote),
            str(checkout),
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout

    attacker = initialize_repository(tmp_path, "metarepo-forged-attacker")
    (attacker / "fleet").mkdir()
    (attacker / "fleet" / "repos.yml").write_text(
        "repos:\n  - name: attacker-controlled\n",
        encoding="utf-8",
    )
    git(attacker, "add", "fleet/repos.yml")
    git(attacker, "commit", "-m", "attacker fleet")
    attacker_head = git(attacker, "rev-parse", "HEAD")

    attacker_objects = attacker / ".git" / "objects"
    checkout_objects = checkout / ".git" / "objects"
    for source in attacker_objects.glob("[0-9a-f][0-9a-f]/*"):
        relative = source.relative_to(attacker_objects)
        target = checkout_objects / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())

    attacker_commit_object = (
        attacker_objects / attacker_head[:2] / attacker_head[2:]
    )
    assert attacker_commit_object.is_file()
    forged_commit_object = (
        checkout_objects / remote_head[:2] / remote_head[2:]
    )
    forged_commit_object.parent.mkdir(parents=True, exist_ok=True)
    forged_commit_object.write_bytes(attacker_commit_object.read_bytes())

    compromised = git(checkout, "show", f"{remote_head}:fleet/repos.yml")
    assert "attacker-controlled" in compromised

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
    bind_isolated_fetch_to_local_remote(module, monkeypatch, remote)
    membership = module.load_authoritative_fleet_membership()

    assert membership.keys == ("heimgewebe/repoground",)
    assert membership.source_commit == remote_head
    assert membership.content_sha256 == hashlib.sha256(
        authoritative.encode("utf-8")
    ).hexdigest()


def test_isolated_membership_fetch_skips_unrelated_large_blob(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_publisher()
    remote = initialize_repository(tmp_path, "metarepo-partial-fetch")
    git(remote, "config", "uploadpack.allowFilter", "true")
    (remote / "fleet").mkdir()
    authoritative = "repos:\n  - name: repoground\n"
    (remote / "fleet" / "repos.yml").write_text(authoritative, encoding="utf-8")
    (remote / "unrelated.bin").write_bytes(
        random.Random(1337).randbytes(8 * 1024 * 1024)
    )
    git(remote, "add", "fleet/repos.yml", "unrelated.bin")
    git(remote, "commit", "-m", "authoritative fleet with unrelated blob")
    remote_head = git(remote, "rev-parse", "HEAD")

    isolated_root = tmp_path / "preserved-authority"

    class PreservedTemporaryDirectory:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def __enter__(self) -> str:
            isolated_root.mkdir()
            return str(isolated_root)

        def __exit__(
            self,
            exc_type: object,
            exc: object,
            traceback: object,
        ) -> bool:
            return False

    monkeypatch.setattr(
        module.tempfile,
        "TemporaryDirectory",
        PreservedTemporaryDirectory,
    )

    remote_ref, source_sha, encoded = module.read_remote_branch_blob_isolated(
        remote.as_uri(),
        "main",
        "fleet/repos.yml",
        env=module._authority_git_env(),
        max_bytes=module.FLEET_MEMBERSHIP_MAX_BYTES,
    )

    assert remote_ref == "refs/heads/main"
    assert source_sha == remote_head
    assert encoded == authoritative.encode("utf-8")
    object_bytes = sum(
        path.stat().st_size
        for path in (isolated_root / "authority.git" / "objects").rglob("*")
        if path.is_file()
    )
    assert object_bytes < 1024 * 1024


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


def test_authority_git_env_neutralizes_nonlocal_transport_configuration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_publisher()
    home = tmp_path / "home"
    home.mkdir()
    (home / ".gitconfig").write_text(
        "[core]\n"
        "    sshCommand = /tmp/attacker-ssh\n"
        "[url \"ssh://attacker.invalid/\"]\n"
        "    insteadOf = git@github.com:\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("GIT_DIR", "/tmp/attacker-git-dir")
    monkeypatch.setenv("GIT_SSH_COMMAND", "/tmp/attacker-ssh")
    monkeypatch.setenv("HTTPS_PROXY", "http://attacker.invalid:8080")
    monkeypatch.setenv("SSL_CERT_FILE", "/tmp/attacker-ca.pem")
    monkeypatch.setenv("LD_PRELOAD", "/tmp/attacker.so")
    monkeypatch.setenv("PATH", "/tmp/attacker-bin")
    monkeypatch.setenv("SSH_AUTH_SOCK", "/tmp/test-agent.sock")

    raw_env = os.environ.copy()
    raw_env.pop("GIT_DIR", None)
    raw_env.pop("GIT_SSH_COMMAND", None)
    inherited_global = subprocess.run(
        ["/usr/bin/git", "config", "--global", "--name-only", "--list"],
        env=raw_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert inherited_global.returncode == 0, inherited_global.stdout
    assert "core.sshcommand" in inherited_global.stdout.lower()
    assert "insteadof" in inherited_global.stdout.lower()

    env = module._authority_git_env()

    assert env["PATH"] == "/usr/bin:/bin"
    assert env["GIT_CONFIG_GLOBAL"] == os.devnull
    assert env["GIT_CONFIG_SYSTEM"] == os.devnull
    assert env["GIT_CONFIG_NOSYSTEM"] == "1"
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert (
        env["GIT_SSH_COMMAND"]
        == "/usr/bin/ssh -F /dev/null -o BatchMode=yes"
    )
    assert env["GIT_SSH_VARIANT"] == "ssh"
    assert env["SSH_AUTH_SOCK"] == "/tmp/test-agent.sock"
    assert "GIT_DIR" not in env
    assert "HTTPS_PROXY" not in env
    assert "SSL_CERT_FILE" not in env
    assert "LD_PRELOAD" not in env

    effective_global = subprocess.run(
        ["/usr/bin/git", "config", "--global", "--name-only", "--list"],
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert effective_global.returncode == 0, effective_global.stdout
    assert "core.sshcommand" not in effective_global.stdout.lower()
    assert "insteadof" not in effective_global.stdout.lower()


@pytest.mark.parametrize(
    "key",
    [
        "core.sshCommand",
        "core.askPass",
        "ssh.variant",
        "url.ssh://attacker.invalid/.insteadOf",
        "url.ssh://attacker.invalid/.pushInsteadOf",
        "remote.origin.uploadpack",
        "remote.origin.proxy",
        "http.proxy",
        "http.sslVerify",
        "credential.helper",
        "include.path",
        "extensions.worktreeConfig",
    ],
)
def test_authority_git_transport_guard_classifies_local_overrides(key: str) -> None:
    module = load_publisher()
    assert module._authority_git_local_config_is_transport_override(key)
