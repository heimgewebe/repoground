from __future__ import annotations

import hashlib
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
