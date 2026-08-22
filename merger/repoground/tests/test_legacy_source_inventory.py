from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/ops/repoground-legacy-source-inventory"


def _git(cwd: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=True,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "RepoGround Test",
            "GIT_AUTHOR_EMAIL": "repoground@example.invalid",
            "GIT_COMMITTER_NAME": "RepoGround Test",
            "GIT_COMMITTER_EMAIL": "repoground@example.invalid",
            "GIT_OPTIONAL_LOCKS": "0",
        },
    )
    return completed.stdout.strip()


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True)
    _git(path, "init", "-q")
    (path / "tracked.txt").write_text("base\n", encoding="utf-8")
    _git(path, "add", "tracked.txt")
    _git(path, "commit", "-qm", "base")


def _run(
    legacy_root: Path,
    canonical_root: Path,
    proc_root: Path,
    *,
    env: dict[str, str] | None = None,
) -> dict:
    proc_root.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        [
            str(SCRIPT),
            "--root",
            str(legacy_root),
            "--canonical-root",
            str(canonical_root),
            "--proc-root",
            str(proc_root),
        ],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return json.loads(completed.stdout)


@pytest.fixture
def roots(tmp_path: Path) -> tuple[Path, Path, Path]:
    legacy = tmp_path / ".repobrief-sources"
    canonical = tmp_path / "repos"
    proc = tmp_path / "proc"
    legacy.mkdir()
    canonical.mkdir()
    proc.mkdir()
    return legacy, canonical, proc


def test_inventory_is_deterministic_and_advisory(
    roots: tuple[Path, Path, Path],
) -> None:
    legacy, canonical, proc = roots
    _init_repo(legacy / "owner__zeta__main")
    _init_repo(legacy / "owner__alpha__main")

    first = _run(legacy, canonical, proc)
    second = _run(legacy, canonical, proc)

    assert first == second
    assert [item["name"] for item in first["entries"]] == [
        "owner__alpha__main",
        "owner__zeta__main",
    ]
    assert first["authority"] == "advisory-only"
    assert first["lease_check_required"] is True
    assert "lease_clearance" in first["does_not_establish"]
    assert "deletion_authority" in first["does_not_establish"]


def test_clean_independent_repo_is_only_a_preflight_candidate(
    roots: tuple[Path, Path, Path],
) -> None:
    legacy, canonical, proc = roots
    _init_repo(legacy / "owner__sample__main")

    payload = _run(legacy, canonical, proc)
    item = payload["entries"][0]

    assert item["git_state"] == "clean"
    assert item["shared_common_dir"] is False
    assert item["canonical_checkout"]["exists"] is False
    assert item["preflight_candidate"] is True
    assert item["lease_check_required"] is True
    assert item["authority"] == "advisory-only"
    assert "deletion_authority" in item["does_not_establish"]
    assert "safe_to_delete" not in item


def test_dirty_repo_is_blocked(roots: tuple[Path, Path, Path]) -> None:
    legacy, canonical, proc = roots
    repo = legacy / "owner__sample__main"
    _init_repo(repo)
    (repo / "tracked.txt").write_text("dirty\n", encoding="utf-8")

    payload = _run(legacy, canonical, proc)
    item = payload["entries"][0]

    assert item["git_state"] == "dirty"
    assert item["preflight_candidate"] is False


def test_linked_worktree_and_shared_canonical_common_dir_are_blocked(
    roots: tuple[Path, Path, Path],
) -> None:
    legacy, canonical, proc = roots
    source = canonical / "sample"
    _init_repo(source)
    linked = legacy / "owner__sample__main"
    _git(source, "worktree", "add", "--detach", str(linked), "HEAD")

    payload = _run(legacy, canonical, proc)
    item = payload["entries"][0]

    assert item["shared_common_dir"] is True
    assert item["canonical_checkout"]["exists"] is True
    assert item["canonical_checkout"]["shares_git_common_dir"] is True
    assert item["preflight_candidate"] is False


def test_non_git_directory_fails_closed(
    roots: tuple[Path, Path, Path],
) -> None:
    legacy, canonical, proc = roots
    (legacy / "owner__notes__main").mkdir()

    payload = _run(legacy, canonical, proc)
    item = payload["entries"][0]

    assert item["git_repository"] is False
    assert item["git_state"] == "unknown"
    assert item["preflight_candidate"] is False
    assert item["errors"]


def test_process_cwd_conflict_blocks_candidate(
    roots: tuple[Path, Path, Path],
) -> None:
    legacy, canonical, proc = roots
    repo = legacy / "owner__sample__main"
    _init_repo(repo)
    pid = proc / "123"
    pid.mkdir()
    (pid / "cwd").symlink_to(repo)

    payload = _run(legacy, canonical, proc)
    item = payload["entries"][0]

    assert item["process_cwd_conflicts"] == [
        {"pid": 123, "cwd": str(repo.resolve())}
    ]
    assert item["preflight_candidate"] is False


def test_incomplete_process_scan_fails_closed(
    roots: tuple[Path, Path, Path],
) -> None:
    legacy, canonical, proc = roots
    _init_repo(legacy / "owner__sample__main")
    for pid in range(1, 33):
        pid_dir = proc / str(pid)
        pid_dir.mkdir()
        # A directory in place of /proc/<pid>/cwd deterministically makes
        # readlink fail and fills the bounded per-PID diagnostic sample.
        (pid_dir / "cwd").mkdir()

    completed = subprocess.run(
        [
            str(SCRIPT),
            "--root",
            str(legacy),
            "--canonical-root",
            str(canonical),
            "--proc-root",
            str(proc),
            "--max-proc-entries",
            "20",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)
    process_scan = payload["process_scan"]
    item = payload["entries"][0]

    assert process_scan["complete"] is False
    assert process_scan["error_count"] == 21
    assert process_scan["errors"][0] == "process_limit_exceeded:32>20"
    assert len(process_scan["errors"]) == 16
    assert process_scan["errors_truncated"] is True
    assert process_scan["errors_omitted_count"] == 5
    assert item["process_scan_complete"] is False
    assert item["preflight_candidate"] is False
    assert "process_scan_incomplete" in item["errors"]


def test_large_diagnostics_are_bounded_without_losing_evidence(
    roots: tuple[Path, Path, Path], tmp_path: Path
) -> None:
    legacy, canonical, proc = roots
    entry = legacy / "owner__sample__main"
    entry.mkdir()
    for pid in range(1, 201):
        (proc / str(pid)).mkdir()
        # A directory in place of /proc/<pid>/cwd deterministically makes
        # readlink fail, simulating an unreadable proc cwd entry.
        (proc / str(pid) / "cwd").mkdir()

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_git = fake_bin / "git"
    fake_git.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "args = sys.argv[1:]\n"
        "if args[-2:] == ['rev-parse', '--is-inside-work-tree']:\n"
        "    print('true')\n"
        "elif args[-2:] == ['rev-parse', 'HEAD']:\n"
        "    print('deadbeef')\n"
        "elif args[-2:] == ['rev-parse', '--git-common-dir']:\n"
        "    print('/synthetic/common')\n"
        "elif args[-3:] == ['worktree', 'list', '--porcelain']:\n"
        "    for index in range(128):\n"
        "        print(f'worktree /synthetic/worktree-{index:03d}')\n"
        "else:\n"
        "    raise SystemExit(0)\n",
        encoding="utf-8",
    )
    fake_git.chmod(0o755)
    fake_env = {**os.environ, "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}"}

    first = _run(legacy, canonical, proc, env=fake_env)
    second = _run(legacy, canonical, proc, env=fake_env)
    item = first["entries"][0]
    process_scan = first["process_scan"]

    assert first == second
    assert item["worktree_path_count"] == 128
    assert item["worktree_paths"] == [
        f"/synthetic/worktree-{index:03d}" for index in range(16)
    ]
    assert item["worktree_paths_truncated"] is True
    assert item["worktree_paths_omitted_count"] == 112
    assert item["shared_common_dir"] is True
    assert item["preflight_candidate"] is False
    assert process_scan["error_count"] == 200
    assert len(process_scan["errors"]) == 16
    assert process_scan["errors"] == sorted(process_scan["errors"])
    assert process_scan["errors_truncated"] is True
    assert process_scan["errors_omitted_count"] == 184
    assert len(json.dumps(first, separators=(",", ":"), sort_keys=True)) < 20_000
