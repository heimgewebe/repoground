"""Fail-closed historic RepoGround source custody for pinned root inventory consumers.

These tests never create or remove real Git worktrees. All publisher effects
are substituted by a disposable temporary directory and mocked runners.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import runpy
from types import SimpleNamespace
from unittest import mock

import pytest


PUBLISHER = Path(__file__).resolve().parents[1] / "scripts/ops/repoground-publish-fleet"
HISTORICAL_HEAD = "d6d4b3c4337d8bd51758d10d83975c9d61fd18d7"


@pytest.fixture
def publisher():
    return runpy.run_path(str(PUBLISHER))


def _entry(tmp_path):
    return SimpleNamespace(owner="heimgewebe", repo="heim-pc", key="heimgewebe/heim-pc", path=tmp_path / "odb")


def test_historical_source_pin_uses_fixed_reviewed_git_revision(publisher):
    pins = publisher["HISTORICAL_SOURCE_PINS"]
    paths = pins[("heimgewebe/heim-pc", "main")][HISTORICAL_HEAD]
    assert paths == {
        "scripts/nixos_critical_user_data_inventory.py": "5f3b9aa1e2ad49da932ac699023f7f020e562d1d6ec0584a8c9dafb6ffaef572",
        "scripts/nixos_critical_data_inventory.py": "f71996ac1b3722a0785465e9504c2cfd23878d1b85597ddaff7a5bebf0a49d84",
        "nixos/production/critical-user-data-contract-v1.json": "d979b42a8a030ca37b5a3c57ac192c81324d72bf3ac292adbda427eeec2c8097",
        "nixos/production/critical-user-home-data-contract-v1.json": "385cf944e6a28c94a4593eeb1e6e5c87141cb26a4dc8a6cc96b783e21a623347",
        "nixos/production/recovery-contract-v1.json": "fcd9856f9038652469605b97818bb6904bf34bb54843b4e322e797dc3533a5b6",
    }


def test_pin_is_not_removed_while_unpinned_worktree_can_be_pruned(tmp_path, publisher):
    entry = _entry(tmp_path)
    root = tmp_path / "sources"
    root.mkdir()
    pinned = root / f"heimgewebe__heim-pc__main--{HISTORICAL_HEAD}"
    old = root / ("heimgewebe__heim-pc__main--" + "b" * 40)
    current = root / ("heimgewebe__heim-pc__main--" + "c" * 40)
    for candidate in (pinned, old, current):
        candidate.mkdir()
    pruned = []
    def fake_run(argv, **kwargs):
        pruned.append(Path(argv[-1]))
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    function = publisher["prune_obsolete_revision_source_worktrees"]
    with mock.patch.dict(function.__globals__, {
        "SOURCE_ROOT": root,
        "HISTORICAL_SOURCE_PINS": {("heimgewebe/heim-pc", "main"): {HISTORICAL_HEAD: {}}},
        "_verify_historical_pinned_source": mock.Mock(return_value=None),
        "assert_managed_worktree_clean": mock.Mock(),
        "assert_managed_worktree_idle": mock.Mock(),
        "managed_build_lease_evidence": mock.Mock(return_value={"active_leases": []}),
        "run": fake_run,
    }):
        report = function(entry, "main", current)
    assert old in pruned
    assert pinned not in pruned
    assert pinned not in report["removed"]
    assert {"path": str(pinned), "reason": "reviewed_historical_source_pin"} in report["preserved"]


def test_historical_pin_detects_byte_mismatch_without_any_mutation(tmp_path, publisher):
    source = tmp_path / "historical"
    (source / "data").mkdir(parents=True)
    (source / "data/contract.json").write_bytes(b"altered")
    checker = publisher["_verify_historical_pinned_source"]
    with mock.patch.dict(checker.__globals__, {
        "run": mock.Mock(return_value=SimpleNamespace(
            returncode=0, stdout=HISTORICAL_HEAD + "\n", stderr=""
        )),
        "assert_managed_worktree_clean": mock.Mock(),
    }):
        with pytest.raises(RuntimeError, match="digest"):
            checker(source, _entry(tmp_path).path, HISTORICAL_HEAD, {
                "data/contract.json": sha256(b"approved").hexdigest()
            })


def test_historical_pin_rejects_symlinked_payload(tmp_path, publisher):
    source = tmp_path / "historical"
    (source / "data").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.write_bytes(b"approved")
    (source / "data/contract.json").symlink_to(outside)
    checker = publisher["_verify_historical_pinned_source"]
    with mock.patch.dict(checker.__globals__, {
        "run": mock.Mock(return_value=SimpleNamespace(
            returncode=0, stdout=HISTORICAL_HEAD + "\n", stderr=""
        )),
        "assert_managed_worktree_clean": mock.Mock(),
    }):
        with pytest.raises(RuntimeError, match="symlink|unsafe"):
            checker(source, _entry(tmp_path).path, HISTORICAL_HEAD, {
                "data/contract.json": sha256(b"approved").hexdigest()
            })


def test_managed_historical_source_is_exactly_materialized_and_reverified(tmp_path, publisher):
    """The published fixed consumer path must be verified first as staging."""
    entry = _entry(tmp_path)
    ensure = publisher["ensure_historical_source_pins"]
    source_root = tmp_path / "source-root"
    source_root.mkdir()
    fixed = source_root / f"heimgewebe__heim-pc__main--{HISTORICAL_HEAD}"
    calls = []
    def prepare(path, *, expected_repo, target):
        assert expected_repo == entry.path
        assert target == HISTORICAL_HEAD
        assert path != fixed
        path.mkdir()
        calls.append(("prepare", path))
    def verify(path, repository, sha, digests):
        assert repository == entry.path and sha == HISTORICAL_HEAD
        calls.append(("verify", path))
    def run(argv, **kwargs):
        assert argv[-3] == "move"
        staged, destination = Path(argv[-2]), Path(argv[-1])
        assert destination == fixed and ("verify", staged) in calls
        staged.rename(destination)
        calls.append(("move", destination))
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    with mock.patch.dict(ensure.__globals__, {
        "SOURCE_ROOT": source_root,
        "HISTORICAL_SOURCE_PINS": {
            ("heimgewebe/heim-pc", "main"): {HISTORICAL_HEAD: {"a": "e" * 64}}
        },
        "prepare_managed_worktree": prepare,
        "_verify_historical_pinned_source": verify,
        "_managed_worktree_git_env": lambda *args, **kwargs: {"GIT_NO_REPLACE_OBJECTS": "1"},
        "run": run,
        "ensure_source_worktree": mock.Mock(
            side_effect=AssertionError("direct fixed-path checkout forbidden")
        ),
    }):
        assert ensure(entry, "main") == [fixed]
    assert calls[0][0] == "prepare"
    assert [action for action, _ in calls] == ["prepare", "verify", "move", "verify"]
    assert fixed.is_dir()


def test_missing_historical_pin_denies_gc_before_any_worktree_remove(tmp_path, publisher):
    entry = _entry(tmp_path)
    root = tmp_path / "sources"
    root.mkdir()
    obsolete = root / ("heimgewebe__heim-pc__main--" + "b" * 40)
    obsolete.mkdir()
    current = root / ("heimgewebe__heim-pc__main--" + "c" * 40)
    current.mkdir()
    prune = publisher["prune_obsolete_revision_source_worktrees"]
    runner = mock.Mock()
    with mock.patch.dict(prune.__globals__, {
        "SOURCE_ROOT": root,
        "HISTORICAL_SOURCE_PINS": {("heimgewebe/heim-pc", "main"): {HISTORICAL_HEAD: {"a": "e" * 64}}},
        "run": runner,
    }):
        with pytest.raises(RuntimeError, match="missing"):
            prune(entry, "main", current)
    runner.assert_not_called()


def test_dirty_existing_historical_pin_is_denied_before_recovery_create(tmp_path, publisher):
    entry = _entry(tmp_path)
    root = tmp_path / "source-root"
    pinned = root / f"heimgewebe__heim-pc__main--{HISTORICAL_HEAD}"
    pinned.mkdir(parents=True)
    ensure = publisher["ensure_historical_source_pins"]
    materialize = mock.Mock()
    with mock.patch.dict(ensure.__globals__, {
        "SOURCE_ROOT": root,
        "HISTORICAL_SOURCE_PINS": {("heimgewebe/heim-pc", "main"): {HISTORICAL_HEAD: {"a": "e" * 64}}},
        "_verify_historical_pinned_source": mock.Mock(side_effect=RuntimeError("historical pinned source payload digest mismatch")),
        "ensure_source_worktree": materialize,
    }):
        with pytest.raises(RuntimeError, match="digest"):
            ensure(entry, "main")
    materialize.assert_not_called()


def test_historical_recovery_alias_cannot_claim_fixed_consumer_path(tmp_path, publisher):
    """Never adopt a colliding/preexisting staged recovery identity."""
    entry = _entry(tmp_path)
    root = tmp_path / "source-root"
    root.mkdir()
    collision = root / f"heimgewebe__heim-pc__main--{HISTORICAL_HEAD}--recovery-123456789abc"
    collision.mkdir()
    ensure = publisher["ensure_historical_source_pins"]
    validator = mock.Mock()
    with mock.patch.dict(ensure.__globals__, {
        "SOURCE_ROOT": root,
        "HISTORICAL_SOURCE_PINS": {
            ("heimgewebe/heim-pc", "main"): {HISTORICAL_HEAD: {"a": "e" * 64}}
        },
        "_verify_historical_pinned_source": validator,
        "prepare_managed_worktree": mock.Mock(
            side_effect=AssertionError("preexisting staging path must not be reset")
        ),
    }), mock.patch.object(
        ensure.__globals__["uuid"], "uuid4",
        return_value=SimpleNamespace(hex="123456789abc" + "0" * 20),
    ):
        with pytest.raises(RuntimeError, match="staging identity already exists"):
            ensure(entry, "main")
    validator.assert_not_called()
    assert collision.is_dir()


def test_exact_payload_verification_accepts_only_same_head_and_bytes(tmp_path, publisher):
    source = tmp_path / "historical"
    (source / "data").mkdir(parents=True)
    (source / "data/contract.json").write_bytes(b"approved")
    checker = publisher["_verify_historical_pinned_source"]
    with mock.patch.dict(checker.__globals__, {
        "SOURCE_ROOT": tmp_path,
        "run": mock.Mock(return_value=SimpleNamespace(
            returncode=0, stdout=HISTORICAL_HEAD + "\n", stderr=""
        )),
        "assert_managed_worktree_clean": mock.Mock(),
    }):
        checker(source, _entry(tmp_path).path, HISTORICAL_HEAD, {
            "data/contract.json": sha256(b"approved").hexdigest()
        })
        with mock.patch.dict(checker.__globals__, {
            "run": mock.Mock(return_value=SimpleNamespace(
                returncode=0, stdout="a" * 40 + "\n", stderr=""
            )),
        }):
            with pytest.raises(RuntimeError, match="revision drifted"):
                checker(source, _entry(tmp_path).path, HISTORICAL_HEAD, {
                    "data/contract.json": sha256(b"approved").hexdigest()
                })

def test_historical_git_no_replace_env_protects_actual_tree(tmp_path, publisher):
    """Real disposable Git: replacement refs must not change a pinned worktree."""
    import os
    import subprocess
    repo = tmp_path / "repo"
    repo.mkdir()
    def git(*args, env=None, working=repo):
        value = subprocess.run(
            ["git", "-C", str(working), *args], env=env,
            capture_output=True, text=True, timeout=15
        )
        assert value.returncode == 0, (args, value.stdout, value.stderr)
        return value.stdout.strip()
    git("init", "-q")
    git("config", "user.name", "source-pin-test")
    git("config", "user.email", "source-pin-test@example.invalid")
    for name in ("scanner.py", "aggregate.py", "critical.json", "home.json", "recovery.json"):
        (repo / name).write_bytes(b"approved\n")
    (repo / "other.txt").write_bytes(b"source-A\n")
    git("add", ".")
    git("commit", "-qm", "A")
    commit_a = git("rev-parse", "HEAD")
    (repo / "other.txt").write_bytes(b"source-B\n")
    git("add", ".")
    git("commit", "-qm", "B")
    commit_b = git("rev-parse", "HEAD")
    git("replace", commit_a, commit_b)
    unsafe = tmp_path / "replaced"
    safe = tmp_path / "original"
    unsafe_env = {key: value for key, value in os.environ.items() if key != "GIT_NO_REPLACE_OBJECTS"}
    trusted_env = publisher["_authority_git_env"]()
    git("worktree", "add", "--detach", "-q", str(unsafe), commit_a, env=unsafe_env)
    git("worktree", "add", "--detach", "-q", str(safe), commit_a, env=trusted_env)
    assert git("rev-parse", "HEAD", working=unsafe, env=unsafe_env) == commit_a
    assert git("rev-parse", "HEAD", working=safe, env=trusted_env) == commit_a
    assert not git("status", "--porcelain", working=unsafe, env=unsafe_env)
    assert not git("status", "--porcelain", working=safe, env=trusted_env)
    assert (unsafe / "other.txt").read_bytes() == b"source-B\n"
    assert (safe / "other.txt").read_bytes() == b"source-A\n"


def test_historical_pin_failed_stage_is_removed_only_when_clean(tmp_path, publisher):
    """Rejected source never appears at the fixed consumer path."""
    entry = _entry(tmp_path)
    root = tmp_path / "source-root"
    root.mkdir()
    fixed = root / f"heimgewebe__heim-pc__main--{HISTORICAL_HEAD}"
    ensure = publisher["ensure_historical_source_pins"]
    removed = []
    def prepare(path, *, expected_repo, target):
        assert path != fixed and target == HISTORICAL_HEAD
        path.mkdir()
    def run(argv, **kwargs):
        assert argv[-2] == "remove"
        path = Path(argv[-1])
        assert path != fixed
        path.rmdir()
        removed.append(path)
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    with mock.patch.dict(ensure.__globals__, {
        "SOURCE_ROOT": root,
        "HISTORICAL_SOURCE_PINS": {
            ("heimgewebe/heim-pc", "main"): {HISTORICAL_HEAD: {"a": "e" * 64}}
        },
        "prepare_managed_worktree": prepare,
        "_verify_historical_pinned_source": mock.Mock(
            side_effect=RuntimeError("historical pinned source payload digest mismatch")
        ),
        "assert_managed_worktree_clean": mock.Mock(),
        "assert_managed_worktree_idle": mock.Mock(),
        "run": run,
    }):
        with pytest.raises(RuntimeError, match="digest mismatch"):
            ensure(entry, "main")
    assert not fixed.exists()
    assert len(removed) == 1
    assert not removed[0].exists()


def test_pinned_source_detects_name_replacement_after_fd_hash(tmp_path, publisher):
    """Second path lookup must detect a swapped file, not just validate the old fd."""
    source = tmp_path / "historical"
    parent = source / "data"
    parent.mkdir(parents=True)
    name = parent / "contract.json"
    name.write_bytes(b"approved")
    checker = publisher["_verify_historical_pinned_source"]
    original_read = checker.__globals__["os"].read
    substituted = {"value": False}
    def swap_after_read(fd, length):
        payload = original_read(fd, length)
        if payload and not substituted["value"]:
            name.rename(parent / "old-approved")
            name.write_bytes(b"poisoned")
            substituted["value"] = True
        return payload
    with mock.patch.dict(checker.__globals__, {
        "SOURCE_ROOT": tmp_path,
        "run": mock.Mock(return_value=SimpleNamespace(
            returncode=0, stdout=HISTORICAL_HEAD + "\n", stderr=""
        )),
        "assert_managed_worktree_clean": mock.Mock(),
    }), mock.patch.object(checker.__globals__["os"], "read", side_effect=swap_after_read):
        with pytest.raises(RuntimeError, match="(pathname|changed|unsafe)"):
            checker(source, _entry(tmp_path).path, HISTORICAL_HEAD, {
                "data/contract.json": sha256(b"approved").hexdigest()
            })
    assert substituted["value"]
def test_actual_git_staged_source_publishes_exact_commit_and_is_idempotent(tmp_path, publisher):
    """Real Git worktree promotion is tested only inside a disposable temporary ODB."""
    import subprocess

    entry = _entry(tmp_path)
    entry.path.mkdir()
    def git(repo, *args):
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True, text=True, timeout=20,
        )
        assert result.returncode == 0, (args, result.stdout, result.stderr)
        return result.stdout.strip()

    git(entry.path, "init", "-q")
    git(entry.path, "config", "user.name", "source-pin-integration-test")
    git(entry.path, "config", "user.email", "source-pin-test@example.invalid")
    approved = {}
    for relative in (
        "scripts/nixos_critical_user_data_inventory.py",
        "scripts/nixos_critical_data_inventory.py",
        "nixos/production/critical-user-data-contract-v1.json",
        "nixos/production/critical-user-home-data-contract-v1.json",
        "nixos/production/recovery-contract-v1.json",
    ):
        file_path = entry.path / relative
        file_path.parent.mkdir(parents=True, exist_ok=True)
        payload = ("reviewed:" + relative + "\n").encode()
        file_path.write_bytes(payload)
        approved[relative] = sha256(payload).hexdigest()
    (entry.path / "non_pinned.txt").write_text("trusted historical source\n")
    git(entry.path, "add", ".")
    git(entry.path, "commit", "-qm", "historical A")
    head = git(entry.path, "rev-parse", "HEAD")
    root = tmp_path / "published_sources"
    root.mkdir()
    ensure = publisher["ensure_historical_source_pins"]
    with mock.patch.dict(ensure.__globals__, {
        "SOURCE_ROOT": root,
        "HISTORICAL_SOURCE_PINS": {("heimgewebe/heim-pc", "main"): {head: approved}},
    }):
        first = ensure(entry, "main")
        second = ensure(entry, "main")
    fixed = root / f"heimgewebe__heim-pc__main--{head}"
    assert first == second == [fixed]
    assert fixed.is_dir()
    assert git(fixed, "rev-parse", "HEAD") == head
    assert not git(fixed, "status", "--porcelain")
    assert (fixed / "non_pinned.txt").read_text() == "trusted historical source\n"
    assert not list(root.glob(f"*{head}--recovery-*"))
