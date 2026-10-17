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
    entry = _entry(tmp_path)
    ensure = publisher["ensure_historical_source_pins"]
    source_root = tmp_path / "source-root"
    source = source_root / f"heimgewebe__heim-pc__main--{HISTORICAL_HEAD}"
    with mock.patch.dict(ensure.__globals__, {
        "SOURCE_ROOT": source_root,
        "HISTORICAL_SOURCE_PINS": {("heimgewebe/heim-pc", "main"): {HISTORICAL_HEAD: {"a": "e" * 64}}},
        "ensure_source_worktree": mock.Mock(return_value=source),
        "_verify_historical_pinned_source": mock.Mock(),
    }):
        paths = ensure(entry, "main")
        ensure.__globals__["ensure_source_worktree"].assert_called_once_with(
            entry, "main", HISTORICAL_HEAD
        )
        ensure.__globals__["_verify_historical_pinned_source"].assert_called_once_with(
            source, entry.path, HISTORICAL_HEAD, {"a": "e" * 64}
        )
    assert paths == [source]


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
    entry = _entry(tmp_path)
    root = tmp_path / "source-root"
    recovery = root / f"heimgewebe__heim-pc__main--{HISTORICAL_HEAD}--recovery-123456789abc"
    ensure = publisher["ensure_historical_source_pins"]
    validator = mock.Mock()
    with mock.patch.dict(ensure.__globals__, {
        "SOURCE_ROOT": root,
        "HISTORICAL_SOURCE_PINS": {("heimgewebe/heim-pc", "main"): {HISTORICAL_HEAD: {"a": "e" * 64}}},
        "ensure_source_worktree": mock.Mock(return_value=recovery),
        "_verify_historical_pinned_source": validator,
    }):
        with pytest.raises(RuntimeError, match="recovery identity"):
            ensure(entry, "main")
    validator.assert_not_called()


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
