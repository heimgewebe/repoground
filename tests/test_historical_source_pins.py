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
def publisher(tmp_path):
    namespace = runpy.run_path(str(PUBLISHER))
    # Test receipts must never escape pytest's disposable state root.
    namespace["ensure_historical_source_pins"].__globals__["STATE_ROOT"] = (
        tmp_path / "private-publisher-state"
    )
    return namespace


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
        "_verify_historical_pinned_git_tree": mock.Mock(return_value="f" * 40),
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
        "SOURCE_ROOT": tmp_path,
        "run": mock.Mock(return_value=SimpleNamespace(
            returncode=0, stdout=HISTORICAL_HEAD + "\n", stderr=""
        )),
        "assert_managed_worktree_clean": mock.Mock(),
        "_verify_historical_pinned_git_tree": mock.Mock(return_value="f" * 40),
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
        "SOURCE_ROOT": tmp_path,
        "run": mock.Mock(return_value=SimpleNamespace(
            returncode=0, stdout=HISTORICAL_HEAD + "\n", stderr=""
        )),
        "assert_managed_worktree_clean": mock.Mock(),
        "_verify_historical_pinned_git_tree": mock.Mock(return_value="f" * 40),
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
    assert [action for action, _ in calls] == ["prepare", "verify", "verify", "move", "verify"]
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
        with pytest.raises(RuntimeError, match="requires owner reconciliation"):
            ensure(entry, "main")
    materialize.assert_not_called()
    assert pinned.is_dir()  # Do not move any unregistered foreign directory.


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
        "_verify_historical_pinned_git_tree": mock.Mock(return_value="f" * 40),
    }):
        checker(source, _entry(tmp_path).path, HISTORICAL_HEAD, {
            "data/contract.json": sha256(b"approved").hexdigest()
        })
        with mock.patch.dict(checker.__globals__, {
            "_verify_historical_pinned_git_tree": mock.Mock(
                side_effect=RuntimeError("historical pinned source revision drifted")
            ),
        }):
            with pytest.raises(RuntimeError, match="revision drifted"):
                checker(source, _entry(tmp_path).path, HISTORICAL_HEAD, {
                    "data/contract.json": sha256(b"approved").hexdigest()
                })


def test_replacement_protection_is_scoped_to_source_identity(publisher):
    # General Fleet Git transport has an audited no-extra-GIT_* contract.
    assert "GIT_NO_REPLACE_OBJECTS" not in publisher["_authority_git_env"]()
    assert publisher["_pinned_source_git_env"]()["GIT_NO_REPLACE_OBJECTS"] == "1"


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
    trusted_env = publisher["_pinned_source_git_env"]()
    git("worktree", "add", "--detach", "-q", str(unsafe), commit_a, env=unsafe_env)
    git("worktree", "add", "--detach", "-q", str(safe), commit_a, env=trusted_env)
    assert git("rev-parse", "HEAD", working=unsafe, env=unsafe_env) == commit_a
    assert git("rev-parse", "HEAD", working=safe, env=trusted_env) == commit_a
    assert not git("status", "--porcelain", working=unsafe, env=unsafe_env)
    assert not git("status", "--porcelain", working=safe, env=trusted_env)
    assert (unsafe / "other.txt").read_bytes() == b"source-B\n"
    assert (safe / "other.txt").read_bytes() == b"source-A\n"


def test_historical_pin_failed_stage_is_retained_for_owner_cleanup(tmp_path, publisher):
    """A rejected stage must never be deleted by a raceable git remove pathname."""
    entry = _entry(tmp_path)
    root = tmp_path / "source-root"
    root.mkdir()
    fixed = root / f"heimgewebe__heim-pc__main--{HISTORICAL_HEAD}"
    ensure = publisher["ensure_historical_source_pins"]
    created = []

    def prepare(path, *, expected_repo, target):
        assert path != fixed and target == HISTORICAL_HEAD
        path.mkdir()
        (path / "valuable-untracked.txt").write_bytes(b"preserve even on failure")
        created.append(path)

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
        "run": mock.Mock(side_effect=AssertionError("never recursively remove a rejected stage")),
    }):
        with pytest.raises(RuntimeError, match="staging retained for owner cleanup"):
            ensure(entry, "main")
    assert not fixed.exists()
    assert len(created) == 1
    assert created[0].is_dir()
    assert (created[0] / "valuable-untracked.txt").read_bytes() == (
        b"preserve even on failure"
    )

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
        "_verify_historical_pinned_git_tree": mock.Mock(return_value="f" * 40),
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
        "HISTORICAL_SOURCE_PIN_TREES": {
            head: git(entry.path, "rev-parse", "HEAD^{tree}")
        },
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

def test_historical_pin_rejects_cross_root_swap_between_two_approved_files(
    tmp_path, publisher
):
    """Approved files from two separate trees must never combine as one pin."""
    root = tmp_path / "sources"
    root.mkdir()
    source = root / "original"
    replacement = tmp_path / "replacement"
    for directory in (source, replacement):
        (directory / "data").mkdir(parents=True)
    (source / "data/a").write_bytes(b"approved-a")
    (source / "data/b").write_bytes(b"poisoned-b")
    (replacement / "data/a").write_bytes(b"poisoned-a")
    (replacement / "data/b").write_bytes(b"approved-b")
    checker = publisher["_verify_historical_pinned_source"]
    read = checker.__globals__["os"].read
    swapped = {"done": False}

    def swap_roots_after_first_file(fd, size):
        chunk = read(fd, size)
        if chunk and not swapped["done"]:
            source.rename(tmp_path / "retained-original")
            replacement.rename(source)
            swapped["done"] = True
        return chunk

    with mock.patch.dict(checker.__globals__, {
        "SOURCE_ROOT": root,
        "run": mock.Mock(return_value=SimpleNamespace(
            returncode=0, stdout=HISTORICAL_HEAD + "\n", stderr=""
        )),
        "assert_managed_worktree_clean": mock.Mock(),
        "_verify_historical_pinned_git_tree": mock.Mock(return_value="f" * 40),
    }), mock.patch.object(
        checker.__globals__["os"], "read", side_effect=swap_roots_after_first_file
    ):
        with pytest.raises(RuntimeError, match="root changed|digest mismatch"):
            checker(source, _entry(tmp_path).path, HISTORICAL_HEAD, {
                "data/a": sha256(b"approved-a").hexdigest(),
                "data/b": sha256(b"approved-b").hexdigest(),
            })
    assert swapped["done"] is True


def test_postmove_invalid_pin_is_quarantined_and_fixed_path_removed(
    tmp_path, publisher
):
    """A failed final verifier must retract only the just-promoted inode."""
    entry = _entry(tmp_path)
    root = tmp_path / "source-root"
    root.mkdir()
    expected = root / f"heimgewebe__heim-pc__main--{HISTORICAL_HEAD}"
    ensure = publisher["ensure_historical_source_pins"]
    recorded = {"stage": None, "moves": [], "checks": []}
    recovery = mock.Mock()

    def prepare(path, *, expected_repo, target):
        assert expected_repo == entry.path and target == HISTORICAL_HEAD
        path.mkdir()
        recorded["stage"] = path

    def verify(path, _repository, _sha, _digests):
        recorded["checks"].append(path)
        if path == expected:
            raise RuntimeError("historical pinned source payload digest mismatch")

    def run(argv, **kwargs):
        assert argv[-3] == "move"
        source, target = Path(argv[-2]), Path(argv[-1])
        assert source.is_dir() and not target.exists()
        source.rename(target)
        recorded["moves"].append((source, target))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    with mock.patch.dict(ensure.__globals__, {
        "SOURCE_ROOT": root,
        "HISTORICAL_SOURCE_PINS": {
            ("heimgewebe/heim-pc", "main"): {
                HISTORICAL_HEAD: {"one": "a" * 64}
            }
        },
        "prepare_managed_worktree": prepare,
        "_verify_historical_pinned_source": verify,
        "_managed_worktree_git_env": lambda *a, **kw: {
            "GIT_NO_REPLACE_OBJECTS": "1"
        },
        "run": run,
        "record_source_recovery": recovery,
        "assert_managed_worktree_identity": mock.Mock(),
    }):
        with pytest.raises(RuntimeError, match="postmove verification refused"):
            ensure(entry, "main")
    assert not expected.exists()
    assert recorded["stage"].is_dir()
    assert len(recorded["moves"]) == 2
    assert recorded["moves"][0][1] == expected
    assert recorded["moves"][1] == (expected, recorded["stage"])
    recovery.assert_called_once()


def test_prune_never_removes_inflight_historical_pin_recovery_stage(
    tmp_path, publisher
):
    """A pinned staging source must survive a concurrent ordinary fleet GC."""
    entry = _entry(tmp_path)
    root = tmp_path / "source-root"
    root.mkdir()
    fixed = root / f"heimgewebe__heim-pc__main--{HISTORICAL_HEAD}"
    stage = root / (
        f"heimgewebe__heim-pc__main--{HISTORICAL_HEAD}"
        "--recovery-123456789abc"
    )
    for path in (fixed, stage):
        path.mkdir()
    current = root / ("heimgewebe__heim-pc__main--" + "c" * 40)
    current.mkdir()
    removed = []
    def fake_run(argv, **kwargs):
        removed.append(Path(argv[-1]))
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    prune = publisher["prune_obsolete_revision_source_worktrees"]
    with mock.patch.dict(prune.__globals__, {
        "SOURCE_ROOT": root,
        "HISTORICAL_SOURCE_PINS": {
            ("heimgewebe/heim-pc", "main"): {HISTORICAL_HEAD: {"f": "e" * 64}}
        },
        "_verify_historical_pinned_source": mock.Mock(),
        "run": fake_run,
    }):
        report = prune(entry, "main", current)
    assert stage not in removed
    assert stage.is_dir()
    assert {
        "path": str(stage),
        "reason": "reviewed_historical_source_stage_requires_owner_closeout",
    } in report["preserved"]


@pytest.mark.parametrize("index_flag", ["--assume-unchanged", "--skip-worktree"])
def test_historical_pin_rejects_hidden_index_flag_and_quarantines_owned_source(
    tmp_path, publisher, index_flag
):
    """Even an apparently clean worktree may contain poisoned unpinned bytes."""
    import subprocess

    entry = _entry(tmp_path)
    entry.path.mkdir()

    def git(path, *args):
        result = subprocess.run(
            ["git", "-C", str(path), *args],
            capture_output=True, text=True, timeout=20,
        )
        assert result.returncode == 0, (args, result.stdout, result.stderr)
        return result.stdout.strip()

    git(entry.path, "init", "-q")
    git(entry.path, "config", "user.name", "source-custody-test")
    git(entry.path, "config", "user.email", "source-custody-test@example.invalid")
    (entry.path / "data").mkdir()
    (entry.path / "data/approved").write_bytes(b"approved")
    (entry.path / "non_pinned.py").write_bytes(b"safe\n")
    git(entry.path, "add", ".")
    git(entry.path, "commit", "-qm", "reviewed")
    head = git(entry.path, "rev-parse", "HEAD")
    source_root = tmp_path / "source-root"
    source_root.mkdir()
    fixed = source_root / f"heimgewebe__heim-pc__main--{head}"
    digests = {"data/approved": sha256(b"approved").hexdigest()}
    ensure = publisher["ensure_historical_source_pins"]
    recovery = mock.Mock()
    with mock.patch.dict(ensure.__globals__, {
        "SOURCE_ROOT": source_root,
        "HISTORICAL_SOURCE_PINS": {
            ("heimgewebe/heim-pc", "main"): {head: digests}
        },
        "HISTORICAL_SOURCE_PIN_TREES": {
            head: git(entry.path, "rev-parse", "HEAD^{tree}")
        },
        "record_source_recovery": recovery,
    }):
        assert ensure(entry, "main") == [fixed]
        git(fixed, "update-index", index_flag, "--", "non_pinned.py")
        (fixed / "non_pinned.py").write_bytes(b"poisoned\n")
        assert git(fixed, "status", "--porcelain") == ""  # Reproduce P1.
        with pytest.raises(RuntimeError, match="invalid; consumer name retracted"):
            ensure(entry, "main")
    assert not fixed.exists()
    quarantines = list(source_root.glob(f"*{head}--recovery-*"))
    assert len(quarantines) == 1
    assert (quarantines[0] / "non_pinned.py").read_bytes() == b"poisoned\n"
    recovery.assert_called_once()


def test_invalid_consumer_symlink_is_unlinked_without_following_target(
    tmp_path, publisher
):
    entry = _entry(tmp_path)
    root = tmp_path / "source-root"
    root.mkdir()
    outside = tmp_path / "unrelated"
    outside.mkdir()
    (outside / "important").write_bytes(b"unchanged")
    fixed = root / f"heimgewebe__heim-pc__main--{HISTORICAL_HEAD}"
    fixed.symlink_to(outside, target_is_directory=True)
    ensure = publisher["ensure_historical_source_pins"]
    with mock.patch.dict(ensure.__globals__, {
        "SOURCE_ROOT": root,
        "HISTORICAL_SOURCE_PINS": {
            ("heimgewebe/heim-pc", "main"): {
                HISTORICAL_HEAD: {"data/approved": "c" * 64}
            }
        },
        "prepare_managed_worktree": mock.Mock(
            side_effect=AssertionError("never adopt a poisoned fixed name")
        ),
    }):
        with pytest.raises(RuntimeError, match="consumer name retracted"):
            ensure(entry, "main")
    assert not fixed.exists() and not fixed.is_symlink()
    assert (outside / "important").read_bytes() == b"unchanged"


def test_postmove_invalid_pin_with_raced_staging_name_is_still_quarantined(
    tmp_path, publisher
):
    """A leftover stage cannot defeat retraction of the promoted inode."""
    entry = _entry(tmp_path)
    root = tmp_path / "source-root"
    root.mkdir()
    fixed = root / f"heimgewebe__heim-pc__main--{HISTORICAL_HEAD}"
    ensure = publisher["ensure_historical_source_pins"]
    state = {"stage": None, "moves": [], "recovery": None}

    def prepare(path, **_kwargs):
        path.mkdir()
        state["stage"] = path

    def verify(path, *_args):
        if path == fixed:
            raise RuntimeError("invalid source after promotion")

    def move(argv, **_kwargs):
        assert argv[-3] == "move"
        origin, target = Path(argv[-2]), Path(argv[-1])
        assert origin.is_dir() and not target.exists()
        origin.rename(target)
        state["moves"].append((origin, target))
        if target == fixed:
            # Simulate a leftover/raced staging directory after Git reports success.
            state["stage"].mkdir()
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def recovery(**kwargs):
        state["recovery"] = kwargs

    with mock.patch.dict(ensure.__globals__, {
        "SOURCE_ROOT": root,
        "HISTORICAL_SOURCE_PINS": {
            ("heimgewebe/heim-pc", "main"): {
                HISTORICAL_HEAD: {"one": "a" * 64}
            }
        },
        "prepare_managed_worktree": prepare,
        "_verify_historical_pinned_source": verify,
        "_managed_worktree_git_env": lambda *_args, **_kw: {
            "GIT_NO_REPLACE_OBJECTS": "1"
        },
        "assert_managed_worktree_identity": mock.Mock(),
        "run": move,
        "record_source_recovery": recovery,
    }):
        with pytest.raises(RuntimeError, match="postmove verification refused"):
            ensure(entry, "main")
    assert not fixed.exists()
    assert state["stage"].is_dir()
    assert len(state["moves"]) == 2
    assert state["moves"][1][0] == fixed
    assert state["moves"][1][1] != state["stage"]
    assert state["moves"][1][1].is_dir()
    assert state["recovery"]["replacement"] == state["moves"][1][1]


def test_historical_pinned_tree_detects_extra_file_planted_after_object_read(
    tmp_path, publisher
):
    """Raw fd enumeration denies untracked imports added after a trusted Git tree read."""
    import os
    import subprocess

    entry = _entry(tmp_path)
    entry.path.mkdir()

    def git(path, *args):
        result = subprocess.run(
            ["git", "-C", str(path), *args],
            capture_output=True, text=True, timeout=20,
        )
        assert result.returncode == 0, (args, result.stdout, result.stderr)
        return result.stdout.strip()

    git(entry.path, "init", "-q")
    git(entry.path, "config", "user.name", "source-identity-test")
    git(entry.path, "config", "user.email", "source-identity@example.invalid")
    (entry.path / "data").mkdir()
    (entry.path / "data/approved").write_bytes(b"approved")
    (entry.path / "safe.py").write_bytes(b"safe\\n")
    git(entry.path, "add", ".")
    git(entry.path, "commit", "-qm", "fixed historical source")
    head = git(entry.path, "rev-parse", "HEAD")
    root = tmp_path / "pinned-source"
    root.mkdir()
    fixed = root / f"heimgewebe__heim-pc__main--{head}"
    ensure = publisher["ensure_historical_source_pins"]
    check_tree = publisher["_verify_historical_pinned_git_tree"]
    digests = {"data/approved": sha256(b"approved").hexdigest()}
    planted = {"value": False}
    real_run = subprocess.run
    injected_name = "untracked-import.py"
    injected_bytes = b"malicious-import\\n"

    def inject_after_tree_read(args, **kwargs):
        result = real_run(args, **kwargs)
        if (
            not planted["value"]
            and "ls-tree" in args
            and result.returncode == 0
        ):
            (fixed / injected_name).write_bytes(injected_bytes)
            planted["value"] = True
        return result

    with mock.patch.dict(ensure.__globals__, {
        "SOURCE_ROOT": root,
        "HISTORICAL_SOURCE_PINS": {
            ("heimgewebe/heim-pc", "main"): {head: digests}
        },
        "HISTORICAL_SOURCE_PIN_TREES": {
            head: git(entry.path, "rev-parse", "HEAD^{tree}")
        },
    }):
        assert ensure(entry, "main") == [fixed]
        fd = os.open(fixed, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            with mock.patch.object(
                check_tree.__globals__["subprocess"], "run",
                side_effect=inject_after_tree_read,
            ):
                with pytest.raises(RuntimeError, match="unexpected file"):
                    check_tree(fd, head, entry.path, fixed)
        finally:
            os.close(fd)
        assert planted["value"]
        with pytest.raises(RuntimeError, match="invalid; consumer name retracted"):
            ensure(entry, "main")
    assert not fixed.exists()
    retained = list(root.glob(f"*{head}--recovery-*"))
    assert len(retained) == 1
    assert (retained[0] / injected_name).read_bytes() == injected_bytes


@pytest.fixture
def disposable_verified_git_tree(tmp_path, publisher):
    """Real linked worktree with a scoped, independent synthetic tree pin."""
    import subprocess

    entry = _entry(tmp_path)
    entry.path.mkdir()

    def git(path, *args):
        result = subprocess.run(
            ["/usr/bin/git", "-C", str(path), *args],
            capture_output=True, text=True, timeout=20,
        )
        assert result.returncode == 0, (args, result.stdout, result.stderr)
        return result.stdout.strip()

    git(entry.path, "init", "-q")
    git(entry.path, "config", "user.name", "historical-tree-security-test")
    git(entry.path, "config", "user.email", "historical-tree@example.invalid")
    (entry.path / "safe.py").write_bytes(b"safe\n")
    git(entry.path, "add", ".")
    git(entry.path, "commit", "-qm", "approved tree")
    head = git(entry.path, "rev-parse", "HEAD")
    tree = git(entry.path, "rev-parse", "HEAD^{tree}")
    source_root = tmp_path / "source-root"
    source_root.mkdir()
    fixed = source_root / f"heimgewebe__heim-pc__main--{head}"
    ensure = publisher["ensure_historical_source_pins"]
    with mock.patch.dict(ensure.__globals__, {
        "SOURCE_ROOT": source_root,
        "HISTORICAL_SOURCE_PINS": {
            ("heimgewebe/heim-pc", "main"): {
                head: {"safe.py": sha256(b"safe\n").hexdigest()}
            }
        },
        "HISTORICAL_SOURCE_PIN_TREES": {head: tree},
    }):
        assert ensure(entry, "main") == [fixed]
        yield SimpleNamespace(
            entry=entry, fixed=fixed, head=head,
            checker=publisher["_verify_historical_pinned_git_tree"],
        )


def test_historical_tree_requires_independently_pinned_oid(
    disposable_verified_git_tree,
):
    import os

    item = disposable_verified_git_tree
    fd = os.open(item.fixed, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        with mock.patch.dict(
            item.checker.__globals__, {"HISTORICAL_SOURCE_PIN_TREES": {}}
        ):
            with pytest.raises(RuntimeError, match="commit or tree identity drifted"):
                item.checker(fd, item.head, item.entry.path, item.fixed)
    finally:
        os.close(fd)


@pytest.mark.parametrize("altered_mode", [0o4644, 0o2644, 0o1644])
def test_historical_tree_rejects_special_permission_bits(
    disposable_verified_git_tree, altered_mode,
):
    import os

    item = disposable_verified_git_tree
    os.chmod(item.fixed / "safe.py", altered_mode)
    fd = os.open(item.fixed, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        with pytest.raises(RuntimeError, match="file mode or identity unsafe"):
            item.checker(fd, item.head, item.entry.path, item.fixed)
    finally:
        os.close(fd)


def test_historical_tree_final_walk_rebinds_hashed_tracked_inodes(
    tmp_path, disposable_verified_git_tree,
):
    """Replace a tracked path after the hash/re-stat, before the last fd walk."""
    import os
    import subprocess

    item = disposable_verified_git_tree
    real_run = subprocess.run
    observed = {"trees": 0, "swapped": False}

    def swap_after_final_object_check(argv, **kwargs):
        result = real_run(argv, **kwargs)
        if (
            "rev-parse" in argv
            and f"{item.head}^{{tree}}" in argv
            and result.returncode == 0
        ):
            observed["trees"] += 1
            if observed["trees"] == 2:
                (item.fixed / "safe.py").rename(tmp_path / "retained-safe.py")
                (item.fixed / "safe.py").write_bytes(b"evil\n")
                observed["swapped"] = True
        return result

    fd = os.open(item.fixed, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        with mock.patch.object(
            item.checker.__globals__["subprocess"], "run",
            side_effect=swap_after_final_object_check,
        ):
            with pytest.raises(RuntimeError, match="tracked file identity drifted"):
                item.checker(fd, item.head, item.entry.path, item.fixed)
    finally:
        os.close(fd)
    assert observed == {"trees": 2, "swapped": True}


def test_historical_tree_reference_matches_reviewed_commit(publisher):
    """The historical tree OID is an independent constant, not HEAD's text."""
    assert publisher["HISTORICAL_SOURCE_PIN_TREES"] == {
        HISTORICAL_HEAD: "fe2c5afd07ad36fe66759a37fe53a703bd38947b"
    }


def test_historical_commit_sha256_pins_against_public_upstream_git(tmp_path, publisher):
    """CI must prove all five production bytes from the *actual* Git object.

    This intentionally fails closed if the public HTTPS source is unavailable;
    contract literals and synthetic Git fixtures alone are not provenance.
    There are no writes outside pytest's disposable object database.
    """
    import os
    import subprocess

    repository = tmp_path / "historical-source-odb"
    environment = {
        "HOME": str(tmp_path),
        "PATH": "/usr/bin:/bin",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_TERMINAL_PROMPT": "0",
    }

    def git(*arguments, timeout=30):
        result = subprocess.run(
            ["/usr/bin/git", *arguments],
            env=environment, capture_output=True, timeout=timeout,
            check=False,
        )
        assert result.returncode == 0, (
            arguments, result.stderr[-1024:].decode("utf-8", errors="replace")
        )
        return result.stdout

    git("init", "-q", str(repository))
    git(
        "-C", str(repository), "fetch", "--no-tags", "--depth=1",
        "https://github.com/heimgewebe/heim-pc.git", HISTORICAL_HEAD,
        timeout=90,
    )
    assert git("-C", str(repository), "rev-parse", "FETCH_HEAD").strip() == (
        HISTORICAL_HEAD.encode("ascii")
    )
    assert git(
        "-C", str(repository), "rev-parse", "FETCH_HEAD^{tree}"
    ).strip().decode("ascii") == publisher["HISTORICAL_SOURCE_PIN_TREES"][HISTORICAL_HEAD]
    digests = publisher["HISTORICAL_SOURCE_PINS"][("heimgewebe/heim-pc", "main")][HISTORICAL_HEAD]
    assert len(digests) == 5
    for relative, expected in sorted(digests.items()):
        actual_bytes = git("-C", str(repository), "show", f"FETCH_HEAD:{relative}")
        assert sha256(actual_bytes).hexdigest() == expected, relative


def test_historical_pinned_payload_rejects_hardlink_before_digest(
    tmp_path, publisher
):
    source = tmp_path / "source"
    payload = source / "data" / "approved"
    payload.parent.mkdir(parents=True)
    payload.write_bytes(b"approved")
    other_link = tmp_path / "shared-payload"
    import os
    os.link(payload, other_link)
    checker = publisher["_verify_historical_pinned_source"]
    with mock.patch.dict(checker.__globals__, {
        "SOURCE_ROOT": tmp_path,
        "assert_managed_worktree_clean": mock.Mock(),
        "_verify_historical_pinned_git_tree": mock.Mock(return_value="f" * 40),
    }):
        with pytest.raises(RuntimeError, match="payload is unsafe"):
            checker(source, _entry(tmp_path).path, HISTORICAL_HEAD, {
                "data/approved": sha256(b"approved").hexdigest()
            })
    assert other_link.read_bytes() == b"approved"


def test_failed_git_promotion_after_rename_retracts_exact_worktree(
    tmp_path, publisher
):
    """Git may exit nonzero after a successful physical rename; never retry."""
    entry = _entry(tmp_path)
    root = tmp_path / "source-root"
    root.mkdir()
    fixed = root / f"heimgewebe__heim-pc__main--{HISTORICAL_HEAD}"
    ensure = publisher["ensure_historical_source_pins"]
    state = {"moves": [], "stage": None}

    def prepare(path, **_kwargs):
        path.mkdir()
        state["stage"] = path

    def move_then_fail(argv, **_kwargs):
        assert argv[-3] == "move"
        source, dest = Path(argv[-2]), Path(argv[-1])
        assert source.is_dir() and not dest.exists()
        source.rename(dest)
        state["moves"].append((source, dest))
        if dest == fixed:
            raise RuntimeError("git returned nonzero after physical rename")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    with mock.patch.dict(ensure.__globals__, {
        "SOURCE_ROOT": root,
        "HISTORICAL_SOURCE_PINS": {
            ("heimgewebe/heim-pc", "main"): {
                HISTORICAL_HEAD: {"one": "a" * 64}
            }
        },
        "prepare_managed_worktree": prepare,
        "_verify_historical_pinned_source": mock.Mock(),
        "_managed_worktree_git_env": lambda *_a, **_kw: {
            "GIT_NO_REPLACE_OBJECTS": "1"
        },
        "assert_managed_worktree_identity": mock.Mock(),
        "run": move_then_fail,
        "record_source_recovery": mock.Mock(),
    }):
        with pytest.raises(RuntimeError, match="postmove verification refused"):
            ensure(entry, "main")
    assert not fixed.exists()
    assert len(state["moves"]) == 2
    assert state["moves"][1] == (fixed, state["stage"])
    assert state["stage"].is_dir()


def test_postmove_raced_symlink_is_retracted_without_unlinking_target(
    tmp_path, publisher
):
    """A swap immediately after Git promotion cannot expose a symlink."""
    entry = _entry(tmp_path)
    root = tmp_path / "source-root"
    root.mkdir()
    fixed = root / f"heimgewebe__heim-pc__main--{HISTORICAL_HEAD}"
    outside = tmp_path / "unrelated"
    outside.mkdir()
    (outside / "important").write_bytes(b"keep")
    displaced = tmp_path / "displaced-managed-stage"
    ensure = publisher["ensure_historical_source_pins"]

    def prepare(path, **_kwargs):
        path.mkdir()

    def move_with_raced_symlink(argv, **_kwargs):
        assert argv[-3] == "move"
        stage, destination = Path(argv[-2]), Path(argv[-1])
        assert destination == fixed and stage.is_dir() and not fixed.exists()
        stage.rename(fixed)
        fixed.rename(displaced)
        fixed.symlink_to(outside, target_is_directory=True)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    with mock.patch.dict(ensure.__globals__, {
        "SOURCE_ROOT": root,
        "HISTORICAL_SOURCE_PINS": {
            ("heimgewebe/heim-pc", "main"): {
                HISTORICAL_HEAD: {"one": "a" * 64}
            }
        },
        "prepare_managed_worktree": prepare,
        "_verify_historical_pinned_source": mock.Mock(),
        "_managed_worktree_git_env": lambda *_a, **_kw: {
            "GIT_NO_REPLACE_OBJECTS": "1"
        },
        "run": move_with_raced_symlink,
    }):
        with pytest.raises(RuntimeError, match="consumer symlink retracted"):
            ensure(entry, "main")
    assert not fixed.exists() and not fixed.is_symlink()
    assert displaced.is_dir()
    assert (outside / "important").read_bytes() == b"keep"

def test_pinned_verifier_does_not_execute_untrusted_local_clean_filter(
    tmp_path, publisher
):
    """Modified tracked bytes are rejected without letting git status run filters."""
    import os
    import subprocess
    import time

    entry = _entry(tmp_path)
    entry.path.mkdir()

    def git(path, *args):
        result = subprocess.run(
            ["/usr/bin/git", "-C", str(path), *args],
            capture_output=True, text=True, timeout=20,
        )
        assert result.returncode == 0, (args, result.stdout, result.stderr)
        return result.stdout.strip()

    git(entry.path, "init", "-q")
    git(entry.path, "config", "user.name", "historical-pin-test")
    git(entry.path, "config", "user.email", "historical-pin@example.invalid")
    (entry.path / "data").mkdir()
    (entry.path / "data/approved").write_bytes(b"approved")
    (entry.path / ".gitattributes").write_text(
        "non_pinned.py filter=attacker\n", encoding="utf-8"
    )
    (entry.path / "non_pinned.py").write_bytes(b"safe\n")
    git(entry.path, "add", ".")
    git(entry.path, "commit", "-qm", "bound commit")
    head = git(entry.path, "rev-parse", "HEAD")
    source_root = tmp_path / "source-root"
    source_root.mkdir()
    fixed = source_root / f"heimgewebe__heim-pc__main--{head}"
    digests = {"data/approved": sha256(b"approved").hexdigest()}
    ensure = publisher["ensure_historical_source_pins"]
    check = publisher["_verify_historical_pinned_source"]
    with mock.patch.dict(ensure.__globals__, {
        "SOURCE_ROOT": source_root,
        "HISTORICAL_SOURCE_PINS": {
            ("heimgewebe/heim-pc", "main"): {head: digests}
        },
        "HISTORICAL_SOURCE_PIN_TREES": {
            head: git(entry.path, "rev-parse", "HEAD^{tree}")
        },
    }):
        assert ensure(entry, "main") == [fixed]
        marker = tmp_path / "filter-executed"
        git(entry.path, "config", "filter.attacker.clean",
            f"/usr/bin/sh -c 'printf ran >> {marker}; cat'")
        # Force Git's status dirty-content comparison.  The on-disk
        # modification preserves the byte count but changes content.
        target = fixed / "non_pinned.py"
        target.write_bytes(b"evil\n")
        future = time.time_ns() + 1_000_000_000
        os.utime(target, ns=(future, future))
        with pytest.raises(RuntimeError, match="tracked file bytes drifted"):
            check(fixed, entry.path, head, digests)
        assert not marker.exists(), "verifier executed repository-local clean filter"


def test_pinned_verifier_rejects_foreign_gitfile_before_any_git_command(
    tmp_path, publisher
):
    """A source Gitfile cannot redirect identity to an unrelated Gitdir."""
    import subprocess

    entry = _entry(tmp_path)
    entry.path.mkdir()

    def git(path, *args):
        result = subprocess.run(
            ["/usr/bin/git", "-C", str(path), *args],
            capture_output=True, text=True, timeout=20,
        )
        assert result.returncode == 0, (args, result.stdout, result.stderr)
        return result.stdout.strip()

    git(entry.path, "init", "-q")
    git(entry.path, "config", "user.name", "historical-pin-test")
    git(entry.path, "config", "user.email", "historical-pin@example.invalid")
    (entry.path / "data").mkdir()
    (entry.path / "data/approved").write_bytes(b"approved")
    git(entry.path, "add", ".")
    git(entry.path, "commit", "-qm", "bound commit")
    head = git(entry.path, "rev-parse", "HEAD")
    source_root = tmp_path / "source-root"
    source_root.mkdir()
    fixed = source_root / f"heimgewebe__heim-pc__main--{head}"
    digests = {"data/approved": sha256(b"approved").hexdigest()}
    ensure = publisher["ensure_historical_source_pins"]
    check = publisher["_verify_historical_pinned_source"]
    with mock.patch.dict(ensure.__globals__, {
        "SOURCE_ROOT": source_root,
        "HISTORICAL_SOURCE_PINS": {
            ("heimgewebe/heim-pc", "main"): {head: digests}
        },
        "HISTORICAL_SOURCE_PIN_TREES": {
            head: git(entry.path, "rev-parse", "HEAD^{tree}")
        },
    }):
        assert ensure(entry, "main") == [fixed]
        (fixed / ".git").write_text(
            "gitdir: " + str(tmp_path / "attacker-gitdir") + "\n",
            encoding="ascii",
        )
        with pytest.raises(RuntimeError, match="foreign Gitdir"):
            check(fixed, entry.path, head, digests)


def test_historical_symlink_quarantine_never_unlinks_raced_foreign_file(
    tmp_path, publisher
):
    """A replacement regular file is retained and cannot be mistaken for a link."""
    entry = _entry(tmp_path)
    root = tmp_path / "source-root"
    root.mkdir()
    outside = tmp_path / "protected"
    outside.mkdir()
    (outside / "important").write_bytes(b"unchanged")
    fixed = root / f"heimgewebe__heim-pc__main--{HISTORICAL_HEAD}"
    fixed.symlink_to(outside, target_is_directory=True)

    recovery = publisher["_quarantine_failed_historical_consumer_path"]
    real_move = publisher["_rename_historical_noreplace"]
    old_link = tmp_path / "saved-original-link"
    foreign = b"valuable foreign file; never unlink or overwrite"

    def swap_between_no_follow_stat_and_move(src_fd, src, dst_fd, dst):
        # This is the same race as the exact-head Codex P1. It runs at
        # the syscall boundary, not before the source preflight.
        assert src == fixed.name and dst == "rejected-symlink"
        fixed.rename(old_link)
        fixed.write_bytes(foreign)
        return real_move(src_fd, src, dst_fd, dst)

    with mock.patch.dict(recovery.__globals__, {
        "SOURCE_ROOT": root,
        "_rename_historical_noreplace": swap_between_no_follow_stat_and_move,
    }):
        with pytest.raises(RuntimeError, match="owner reconciliation required"):
            recovery(
                entry=entry, ref_segment="main", sha=HISTORICAL_HEAD,
                fixed=fixed, failure_type="RuntimeError",
            )

    quarantines = list(root.glob(f"*{HISTORICAL_HEAD}--recovery-*"))
    assert len(quarantines) == 1
    assert (quarantines[0] / "rejected-symlink").read_bytes() == foreign
    assert not fixed.exists() and not fixed.is_symlink()
    assert old_link.is_symlink()
    assert old_link.resolve() == outside
    assert (outside / "important").read_bytes() == b"unchanged"


def test_historical_symlink_recovery_does_not_overwrite_occupied_target(
    tmp_path, publisher
):
    """Kernel-enforced no-replace must leave both entries intact on collision."""
    import os

    source_root = tmp_path / "source-root"
    source_root.mkdir()
    source = source_root / "unsafe-link"
    source.symlink_to(tmp_path / "unrelated")
    recovery = source_root / "recovery"
    recovery.mkdir()
    occupied = recovery / "rejected-symlink"
    occupied.write_bytes(b"unrelated owner data")

    open_directory = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    source_fd = os.open(source_root, open_directory)
    recovery_fd = os.open(recovery, open_directory)
    try:
        with pytest.raises(OSError):
            publisher["_rename_historical_noreplace"](
                source_fd, source.name, recovery_fd, occupied.name
            )
    finally:
        os.close(recovery_fd)
        os.close(source_fd)

    assert source.is_symlink()
    assert occupied.read_bytes() == b"unrelated owner data"


def test_historical_symlink_highlevel_collision_retries_without_clobber(
    tmp_path, publisher,
):
    """A no-replace collision must not strand the fixed consumer symlink."""
    import os

    entry = _entry(tmp_path)
    root = tmp_path / "source-root"
    root.mkdir()
    outside = tmp_path / "target"
    outside.mkdir()
    (outside / "important").write_bytes(b"unmodified")
    fixed = root / f"heimgewebe__heim-pc__main--{HISTORICAL_HEAD}"
    fixed.symlink_to(outside, target_is_directory=True)
    quarantine = publisher["_quarantine_failed_historical_consumer_path"]
    original_move = publisher["_rename_historical_noreplace"]
    attempts = []

    def collide_once(from_fd, name, to_fd, target):
        attempts.append(target)
        if len(attempts) == 1:
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                         0o600, dir_fd=to_fd)
            try:
                os.write(fd, b"foreign bytes")
            finally:
                os.close(fd)
        return original_move(from_fd, name, to_fd, target)

    with mock.patch.dict(quarantine.__globals__, {
        "SOURCE_ROOT": root, "_rename_historical_noreplace": collide_once,
    }):
        retained = quarantine(
            entry=entry, ref_segment="main", sha=HISTORICAL_HEAD,
            fixed=fixed, failure_type="RuntimeError",
        )
    assert len(attempts) == 2
    assert not fixed.exists() and not fixed.is_symlink()
    dirs = list(root.glob(f"*{HISTORICAL_HEAD}--recovery-*"))
    assert len(dirs) == 2 and retained in dirs
    assert (retained / "rejected-symlink").is_symlink()
    assert (retained / "rejected-symlink").resolve() == outside
    assert sum(
        (d / "rejected-symlink").is_file() and
        (d / "rejected-symlink").read_bytes() == b"foreign bytes"
        for d in dirs
    ) == 1
    assert (outside / "important").read_bytes() == b"unmodified"


def test_historical_symlink_collision_exhaustion_preserves_all_bytes(
    tmp_path, publisher,
):
    """Bounded failure cannot delete colliding foreign objects or the original."""
    import os

    entry = _entry(tmp_path)
    root = tmp_path / "source-root"
    root.mkdir()
    outside = tmp_path / "target"
    outside.mkdir()
    (outside / "important").write_bytes(b"unmodified")
    fixed = root / f"heimgewebe__heim-pc__main--{HISTORICAL_HEAD}"
    fixed.symlink_to(outside, target_is_directory=True)
    quarantine = publisher["_quarantine_failed_historical_consumer_path"]
    original_move = publisher["_rename_historical_noreplace"]
    attempts = []

    def collide_always(from_fd, name, to_fd, target):
        attempts.append(target)
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                     0o600, dir_fd=to_fd)
        try:
            os.write(fd, b"foreign")
        finally:
            os.close(fd)
        return original_move(from_fd, name, to_fd, target)

    with mock.patch.dict(quarantine.__globals__, {
        "SOURCE_ROOT": root, "_rename_historical_noreplace": collide_always,
    }):
        with pytest.raises(RuntimeError, match="owner reconciliation required"):
            quarantine(
                entry=entry, ref_segment="main", sha=HISTORICAL_HEAD,
                fixed=fixed, failure_type="RuntimeError",
            )
    assert 2 <= len(attempts) <= 8
    assert fixed.is_symlink() and fixed.resolve() == outside
    dirs = list(root.glob(f"*{HISTORICAL_HEAD}--recovery-*"))
    assert len(dirs) == len(attempts)
    assert all((d / "rejected-symlink").read_bytes() == b"foreign"
               for d in dirs)
    assert (outside / "important").read_bytes() == b"unmodified"
