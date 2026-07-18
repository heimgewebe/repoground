from __future__ import annotations

import concurrent.futures
import datetime as dt
import json
import shutil
import subprocess
from pathlib import Path

import pytest

import merger.repoground.core.publication_policy as publication_policy

from merger.repoground.core.publication_policy import (
    PublicationIdentity,
    PublicationPolicyError,
    PublicationPolicyStore,
    RetentionPolicy,
    canonical_sha256,
    parse_time,
    sha256_file,
    tree_snapshot,
)

UTC = dt.timezone.utc


def make_identity(index: int = 1, *, profile: str = "full-max") -> PublicationIdentity:
    return PublicationIdentity(
        repository="heimgewebe__demo",
        lane="main",
        repository_commit=f"{index:040x}",
        profile=profile,
        configuration_sha256=f"{index + 100:064x}",
        lenskit_version="1.0.0",
        bundle_schema="repobrief.bundle.v1",
        generator_inputs_sha256=f"{index + 200:064x}",
    )


def make_store(tmp_path: Path) -> PublicationPolicyStore:
    return PublicationPolicyStore(
        evidence_root=tmp_path / "evidence",
        payload_root=tmp_path / "payloads",
    )


def write_payload(path: Path, content: str) -> Path:
    path.mkdir(parents=True)
    (path / "repo_merge.md").write_text(content, encoding="utf-8")
    manifest = path / "repo_merge.bundle.manifest.json"
    manifest.write_text(json.dumps({"content": content}), encoding="utf-8")
    return manifest


def create_success(
    store: PublicationPolicyStore,
    *,
    index: int,
    completed_at: dt.datetime,
) -> tuple[Path, Path, dict[str, object]]:
    identity = make_identity(index)
    payload = store.payload_root / identity.repository / identity.lane / f"payload-{index}"
    result = store.begin(identity, payload_path=payload, now=completed_at)
    assert result["status"] == "created"
    manifest = write_payload(payload, f"payload-{index}")
    store.complete(Path(str(result["record_path"])), manifest_path=manifest, now=completed_at)
    return Path(str(result["record_path"])), payload, result


def create_prunable_success_set(
    store: PublicationPolicyStore,
    *,
    start_index: int,
    completed_at: dt.datetime,
) -> tuple[Path, Path]:
    created: list[tuple[Path, Path, dict[str, object]]] = []
    for offset in range(4):
        created.append(
            create_success(
                store,
                index=start_index + offset,
                completed_at=completed_at
                - dt.timedelta(minutes=3 - offset),
            )
        )
    oldest_record, oldest_payload, _ = created[0]
    return oldest_record, oldest_payload


def _concurrent_begin(
    evidence_root: str,
    payload_root: str,
    identity_payload: dict[str, str],
    payload_path: str,
    observed_at: str,
) -> str:
    store = PublicationPolicyStore(
        evidence_root=Path(evidence_root), payload_root=Path(payload_root)
    )
    identity = PublicationIdentity(**identity_payload)
    result = store.begin(
        identity,
        payload_path=Path(payload_path),
        now=parse_time(observed_at),
    )
    return str(result["status"])


def test_identity_is_canonical_and_covers_all_required_inputs() -> None:
    baseline = make_identity(1)
    equal = make_identity(1)
    assert baseline.sha256 == equal.sha256

    variants = {
        make_identity(2).sha256,
        make_identity(1, profile="compact").sha256,
        PublicationIdentity(
            **{**baseline.as_dict(), "lenskit_version": "1.0.1"}
        ).sha256,
        PublicationIdentity(
            **{**baseline.as_dict(), "bundle_schema": "repobrief.bundle.v2"}
        ).sha256,
        PublicationIdentity(
            **{
                **baseline.as_dict(),
                "configuration_sha256": "f" * 64,
            }
        ).sha256,
        PublicationIdentity(
            **{
                **baseline.as_dict(),
                "generator_inputs_sha256": "e" * 64,
            }
        ).sha256,
    }
    assert baseline.sha256 not in variants
    assert len(variants) == 6


def test_retention_policy_cannot_weaken_canonical_floors() -> None:
    unsafe = (
        {"recent": 2},
        {"daily": 6},
        {"weekly": 7},
        {"incomplete_ttl_seconds": 48 * 60 * 60 - 1},
    )
    for override in unsafe:
        with pytest.raises(ValueError, match=">="):
            RetentionPolicy(**override)


def test_begin_cannot_weaken_incomplete_ttl_floor(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    identity = make_identity(6)
    payload = store.payload_root / identity.repository / identity.lane / "candidate"

    with pytest.raises(ValueError, match=">="):
        store.begin(
            identity,
            payload_path=payload,
            incomplete_ttl_seconds=48 * 60 * 60 - 1,
        )

    assert not store.evidence_root.exists()
    assert not payload.exists()


def test_store_requires_separate_evidence_and_payload_roots(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="must be disjoint"):
        PublicationPolicyStore(
            evidence_root=tmp_path / "store",
            payload_root=tmp_path / "store" / "payloads",
        )


def test_stream_lock_rejects_symlink(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    lock_path = store.evidence_root / "locks" / "heimgewebe__demo" / "main.lock"
    lock_path.parent.mkdir(parents=True)
    victim = tmp_path / "victim"
    victim.write_text("keep", encoding="utf-8")
    lock_path.symlink_to(victim)

    with pytest.raises(PublicationPolicyError, match="stream lock"):
        with store.stream_lock("heimgewebe__demo", "main"):
            pass

    assert victim.read_text(encoding="utf-8") == "keep"


def test_evidence_write_rejects_symlinked_directory_chain(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    records = store.evidence_root / "records"
    records.mkdir(parents=True)
    (records / "heimgewebe__demo").symlink_to(outside, target_is_directory=True)
    identity = make_identity(7)
    payload = store.payload_root / identity.repository / identity.lane / "candidate"

    with pytest.raises(PublicationPolicyError, match="trusted director"):
        store.begin(
            identity,
            payload_path=payload,
            now=dt.datetime(2026, 7, 15, 12, tzinfo=UTC),
        )

    assert list(outside.iterdir()) == []


def test_completed_identity_is_a_noop_without_duplicate_payload(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    observed_at = dt.datetime(2026, 7, 15, 8, tzinfo=UTC)
    identity = make_identity()
    payload = store.payload_root / "heimgewebe__demo" / "main" / "one"
    first = store.begin(identity, payload_path=payload, now=observed_at)
    manifest = write_payload(payload, "first")
    store.complete(Path(str(first["record_path"])), manifest_path=manifest, now=observed_at)

    second_payload = store.payload_root / "heimgewebe__demo" / "main" / "two"
    second = store.begin(
        identity,
        payload_path=second_payload,
        now=observed_at + dt.timedelta(minutes=1),
    )

    assert second["status"] == "noop"
    assert second["payload_path"] == str(payload.resolve())
    assert not second_payload.exists()
    assert len(store.list_records(identity.repository, identity.lane)) == 1


def test_concurrent_identical_begin_creates_one_record(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    identity = make_identity()
    payload = store.payload_root / "heimgewebe__demo" / "main" / "concurrent"
    observed_at = "2026-07-15T08:00:00Z"

    with concurrent.futures.ProcessPoolExecutor(max_workers=4) as executor:
        statuses = list(
            executor.map(
                _concurrent_begin,
                [str(store.evidence_root)] * 4,
                [str(store.payload_root)] * 4,
                [identity.as_dict()] * 4,
                [str(payload)] * 4,
                [observed_at] * 4,
            )
        )

    assert statuses.count("created") == 1
    assert statuses.count("in_progress") == 3
    assert len(store.list_records(identity.repository, identity.lane)) == 1


def test_retention_selects_recent_daily_weekly_and_explicit_pins(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    base = dt.datetime(2026, 7, 15, 12, tzinfo=UTC)
    records: list[Path] = []

    for index in range(1, 11):
        record, _, _ = create_success(
            store,
            index=index,
            completed_at=base - dt.timedelta(days=index - 1),
        )
        records.append(record)
    for index in range(11, 19):
        record, _, _ = create_success(
            store,
            index=index,
            completed_at=base - dt.timedelta(days=14 + (index - 11) * 7),
        )
        records.append(record)

    store.pin(records[-1], reason="long-term comparison", now=base)
    plan = store.plan_retention(
        "heimgewebe__demo",
        "main",
        policy=RetentionPolicy(recent=3, daily=7, weekly=8),
        now=base,
    )

    reasons = plan["retention_reasons"]
    assert isinstance(reasons, dict)
    assert sum("recent" in values for values in reasons.values()) == 3
    assert sum("daily" in values for values in reasons.values()) == 7
    assert sum("weekly" in values for values in reasons.values()) == 8
    assert any("pin" in values for values in reasons.values())
    assert records[-1].stem in plan["retained"]
    assert plan["entries"]


def test_incomplete_ttl_expires_after_48_hours_unless_pinned(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    now = dt.datetime(2026, 7, 15, 12, tzinfo=UTC)
    old_identity = make_identity(31)
    young_identity = make_identity(32)
    old_payload = store.payload_root / "heimgewebe__demo" / "main" / "old"
    young_payload = store.payload_root / "heimgewebe__demo" / "main" / "young"
    old = store.begin(
        old_identity,
        payload_path=old_payload,
        now=now - dt.timedelta(hours=49),
    )
    young = store.begin(
        young_identity,
        payload_path=young_payload,
        now=now - dt.timedelta(hours=47),
    )
    old_payload.mkdir(parents=True)
    young_payload.mkdir(parents=True)

    plan = store.plan_retention(
        "heimgewebe__demo",
        "main",
        policy=RetentionPolicy(),
        now=now,
    )
    candidates = {entry["generation_id"] for entry in plan["entries"]}
    assert Path(str(old["record_path"])).stem in candidates
    assert Path(str(young["record_path"])).stem not in candidates

    store.pin(Path(str(old["record_path"])), reason="debugging", now=now)
    pinned_plan = store.plan_retention(
        "heimgewebe__demo",
        "main",
        policy=RetentionPolicy(),
        now=now,
    )
    pinned_candidates = {
        entry["generation_id"] for entry in pinned_plan["entries"]
    }
    assert Path(str(old["record_path"])).stem not in pinned_candidates


def test_expired_incomplete_without_payload_is_recorded_without_deletion(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    now = dt.datetime(2026, 7, 15, 12, tzinfo=UTC)
    identity = make_identity(35)
    payload = store.payload_root / identity.repository / identity.lane / "never-created"
    begun = store.begin(
        identity,
        payload_path=payload,
        now=now - dt.timedelta(hours=49),
    )
    record_path = Path(str(begun["record_path"]))

    plan = store.plan_retention(
        identity.repository, identity.lane, now=now
    )
    assert plan["entries"] == [
        {
            "generation_id": record_path.stem,
            "record_relpath": record_path.relative_to(
                store.evidence_root
            ).as_posix(),
            "record_sha256": sha256_file(record_path),
            "payload_relpath": payload.relative_to(
                store.payload_root
            ).as_posix(),
            "payload_missing": True,
            "payload_snapshot": None,
            "reason": "incomplete-ttl-expired-missing-payload",
        }
    ]

    result = store.apply_plan(plan, now=now)

    assert result["results"] == [
        {
            "generation_id": record_path.stem,
            "status": "recorded-missing-payload",
            "payload_bytes": 0,
        }
    ]
    record = json.loads(record_path.read_text(encoding="utf-8"))
    assert record["payload_state"] == "pruned"
    assert record["missing_payload_confirmed"] is True
    assert not payload.exists()


def test_young_incomplete_without_payload_does_not_block_planning(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    now = dt.datetime(2026, 7, 15, 12, tzinfo=UTC)
    identity = make_identity(36)
    begun = store.begin(
        identity,
        payload_path=(
            store.payload_root / identity.repository / identity.lane / "young-missing"
        ),
        now=now - dt.timedelta(hours=47),
    )

    plan = store.plan_retention(
        identity.repository, identity.lane, now=now
    )

    assert plan["entries"] == []
    assert Path(str(begun["record_path"])).is_file()


def test_unknown_record_key_fails_closed(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    now = dt.datetime(2026, 7, 15, 12, tzinfo=UTC)
    record_path, payload, _ = create_success(store, index=39, completed_at=now)
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["unexpected_control"] = True
    record_path.write_text(json.dumps(record), encoding="utf-8")

    with pytest.raises(PublicationPolicyError, match="invalid keys"):
        store.list_records("heimgewebe__demo", "main")

    assert payload.is_dir()


def test_unknown_pin_key_fails_closed(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    now = dt.datetime(2026, 7, 15, 12, tzinfo=UTC)
    record_path, payload, _ = create_success(store, index=38, completed_at=now)
    pin_result = store.pin(record_path, reason="hold", now=now)
    pin_path = Path(str(pin_result["pin_path"]))
    pin = json.loads(pin_path.read_text(encoding="utf-8"))
    pin["unexpected_control"] = True
    pin_path.write_text(json.dumps(pin), encoding="utf-8")

    with pytest.raises(PublicationPolicyError, match="invalid keys"):
        store.plan_retention("heimgewebe__demo", "main", now=now)

    assert payload.is_dir()


def test_unknown_plan_key_fails_before_payload_mutation(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    now = dt.datetime(2026, 7, 15, 12, tzinfo=UTC)
    _, old_payload = create_prunable_success_set(
        store, start_index=40, completed_at=now
    )
    plan = store.plan_retention(
        "heimgewebe__demo", "main", policy=RetentionPolicy(), now=now
    )
    plan["unexpected_control"] = True
    unhashed = dict(plan)
    unhashed.pop("plan_sha256")
    plan["plan_sha256"] = canonical_sha256(unhashed)

    with pytest.raises(PublicationPolicyError, match="invalid keys"):
        store.apply_plan(plan, now=now)

    assert old_payload.is_dir()


def test_unknown_snapshot_key_fails_before_payload_mutation(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    now = dt.datetime(2026, 7, 15, 12, tzinfo=UTC)
    _, old_payload = create_prunable_success_set(
        store, start_index=44, completed_at=now
    )
    plan = store.plan_retention(
        "heimgewebe__demo", "main", policy=RetentionPolicy(), now=now
    )
    entry = plan["entries"][0]
    assert isinstance(entry, dict)
    snapshot = entry["payload_snapshot"]
    assert isinstance(snapshot, dict)
    snapshot["unexpected_control"] = True
    unhashed = dict(plan)
    unhashed.pop("plan_sha256")
    plan["plan_sha256"] = canonical_sha256(unhashed)

    with pytest.raises(PublicationPolicyError, match="invalid keys"):
        store.apply_plan(plan, now=now)

    assert old_payload.is_dir()


def test_malformed_retention_reasons_fail_before_payload_mutation(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    now = dt.datetime(2026, 7, 15, 12, tzinfo=UTC)
    _, old_payload = create_prunable_success_set(
        store, start_index=48, completed_at=now
    )
    plan = store.plan_retention(
        "heimgewebe__demo", "main", policy=RetentionPolicy(), now=now
    )
    plan["retention_reasons"] = {}
    unhashed = dict(plan)
    unhashed.pop("plan_sha256")
    plan["plan_sha256"] = canonical_sha256(unhashed)

    with pytest.raises(PublicationPolicyError, match="reasons do not match"):
        store.apply_plan(plan, now=now)

    assert old_payload.is_dir()


def test_plan_write_rejects_existing_symlink_target(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    now = dt.datetime(2026, 7, 15, 12, tzinfo=UTC)
    plan = store.plan_retention("heimgewebe__demo", "main", now=now)
    victim = tmp_path / "victim.json"
    victim.write_text("keep", encoding="utf-8")
    output = tmp_path / "plan.json"
    output.symlink_to(victim)

    with pytest.raises(PublicationPolicyError, match="owner-controlled regular file"):
        store.write_plan(output, plan)

    assert victim.read_text(encoding="utf-8") == "keep"


def test_apply_prunes_only_payload_and_preserves_durable_evidence(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    base = dt.datetime(2026, 7, 15, 12, tzinfo=UTC)
    first_record, first_payload = create_prunable_success_set(
        store, start_index=41, completed_at=base
    )

    plan = store.plan_retention(
        "heimgewebe__demo",
        "main",
        policy=RetentionPolicy(),
        now=base,
    )
    result = store.apply_plan(plan, now=base)

    assert result["status"] == "applied"
    assert not first_payload.exists()
    assert first_record.is_file()
    record = json.loads(first_record.read_text(encoding="utf-8"))
    assert record["payload_state"] == "pruned"
    assert record["payload_tree_sha256"]
    assert record["manifest_sha256"]
    assert record["prune_transaction_id"]


def test_pin_added_after_plan_prevents_apply(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    base = dt.datetime(2026, 7, 15, 12, tzinfo=UTC)
    old_record, old_payload = create_prunable_success_set(
        store, start_index=51, completed_at=base
    )
    plan = store.plan_retention(
        "heimgewebe__demo",
        "main",
        policy=RetentionPolicy(),
        now=base,
    )
    store.pin(old_record, reason="operator hold", now=base)

    result = store.apply_plan(plan, now=base)

    assert result["results"] == [
        {"generation_id": old_record.stem, "status": "retained-now"}
    ]
    assert old_payload.is_dir()


def test_retained_now_still_requires_original_record_binding(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    base = dt.datetime(2026, 7, 15, 12, tzinfo=UTC)
    old_record, old_payload = create_prunable_success_set(
        store, start_index=58, completed_at=base
    )
    plan = store.plan_retention(
        "heimgewebe__demo", "main", policy=RetentionPolicy(), now=base
    )
    store.pin(old_record, reason="late hold", now=base)
    old_record.write_text(
        old_record.read_text(encoding="utf-8") + " ", encoding="utf-8"
    )

    with pytest.raises(PublicationPolicyError, match="record changed"):
        store.apply_plan(plan, now=base)

    assert old_payload.is_dir()


def test_stale_record_or_payload_plan_fails_closed(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    base = dt.datetime(2026, 7, 15, 12, tzinfo=UTC)
    old_record, old_payload = create_prunable_success_set(
        store, start_index=61, completed_at=base
    )
    plan = store.plan_retention(
        "heimgewebe__demo",
        "main",
        policy=RetentionPolicy(),
        now=base,
    )
    old_record.write_text(old_record.read_text(encoding="utf-8") + " ", encoding="utf-8")

    with pytest.raises(PublicationPolicyError, match="record changed"):
        store.apply_plan(plan, now=base)
    assert old_payload.is_dir()


def test_plan_cannot_redirect_prune_to_unbound_identical_payload(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    base = dt.datetime(2026, 7, 15, 12, tzinfo=UTC)
    old_record, old_payload = create_prunable_success_set(
        store, start_index=66, completed_at=base
    )
    unrelated_payload = store.payload_root / "heimgewebe__demo" / "main" / "unrelated"
    shutil.copytree(old_payload, unrelated_payload)
    plan = store.plan_retention(
        "heimgewebe__demo", "main", policy=RetentionPolicy(), now=base
    )
    entry = plan["entries"][0]
    assert isinstance(entry, dict)
    entry["payload_relpath"] = unrelated_payload.relative_to(
        store.payload_root
    ).as_posix()
    entry["payload_snapshot"] = tree_snapshot(unrelated_payload).as_dict()
    unhashed = dict(plan)
    unhashed.pop("plan_sha256")
    plan["plan_sha256"] = canonical_sha256(unhashed)

    with pytest.raises(PublicationPolicyError, match="not bound to record"):
        store.apply_plan(plan, now=base)

    assert old_record.is_file()
    assert old_payload.is_dir()
    assert unrelated_payload.is_dir()


def test_transaction_cannot_redirect_recovery_to_unbound_payload(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    base = dt.datetime(2026, 7, 15, 12, tzinfo=UTC)
    old_record, old_payload = create_prunable_success_set(
        store, start_index=68, completed_at=base
    )
    transaction_id = "a" * 32
    unrelated_relpath = "heimgewebe__demo/main/unrelated-missing"
    transaction = {
        "schema": "repobrief.publication-prune-transaction.v1",
        "transaction_id": transaction_id,
        "plan_id": "b" * 32,
        "repository": "heimgewebe__demo",
        "lane": "main",
        "generation_id": old_record.stem,
        "record_relpath": old_record.relative_to(store.evidence_root).as_posix(),
        "source_relpath": unrelated_relpath,
        "quarantine_relpath": (
            f".publication-policy-quarantine/{transaction_id}/{old_record.stem}"
        ),
        "snapshot": tree_snapshot(old_payload).as_dict(),
        "reason": "history-policy",
        "state": "planned",
        "updated_at": "2026-07-15T12:00:00Z",
    }
    transaction_dir = store.evidence_root / "transactions"
    transaction_dir.mkdir(parents=True)
    (transaction_dir / f"{transaction_id}.json").write_text(
        json.dumps(transaction), encoding="utf-8"
    )

    with pytest.raises(PublicationPolicyError, match="not bound to record"):
        store.reconcile_transactions(
            "heimgewebe__demo", "main", policy=RetentionPolicy(), now=base
        )

    assert old_payload.is_dir()


def test_crash_after_quarantine_is_reconciled_idempotently(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = make_store(tmp_path)
    base = dt.datetime(2026, 7, 15, 12, tzinfo=UTC)
    old_record, old_payload = create_prunable_success_set(
        store, start_index=71, completed_at=base
    )
    policy = RetentionPolicy()
    plan = store.plan_retention(
        "heimgewebe__demo", "main", policy=policy, now=base
    )

    real_remove_tree = publication_policy.remove_tree
    calls = 0

    def fail_once(path: str | Path, *args: object, **kwargs: object) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("simulated crash")
        real_remove_tree(Path(path), *args, **kwargs)

    monkeypatch.setattr(publication_policy, "remove_tree", fail_once)
    with pytest.raises(RuntimeError, match="simulated crash"):
        store.apply_plan(plan, now=base)
    assert not old_payload.exists()
    assert old_record.is_file()

    monkeypatch.setattr(publication_policy, "remove_tree", real_remove_tree)
    first = store.reconcile_transactions(
        "heimgewebe__demo", "main", policy=policy, now=base
    )
    second = store.reconcile_transactions(
        "heimgewebe__demo", "main", policy=policy, now=base
    )

    assert first["results"][0]["status"] == "deleted"
    assert second["results"] == []
    record = json.loads(old_record.read_text(encoding="utf-8"))
    assert record["payload_state"] == "pruned"


def test_failed_ttl_starts_at_failure_time(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    now = dt.datetime(2026, 7, 15, 12, tzinfo=UTC)
    identity = make_identity(81)
    payload = store.payload_root / "heimgewebe__demo" / "main" / "failed"
    begun = store.begin(
        identity, payload_path=payload, now=now - dt.timedelta(hours=72)
    )
    payload.mkdir(parents=True)
    record = Path(str(begun["record_path"]))
    store.fail(record, reason="generator failed", now=now - dt.timedelta(hours=1))

    young_plan = store.plan_retention(
        identity.repository,
        identity.lane,
        policy=RetentionPolicy(),
        now=now,
    )
    assert young_plan["entries"] == []

    expired_plan = store.plan_retention(
        identity.repository,
        identity.lane,
        policy=RetentionPolicy(),
        now=now + dt.timedelta(hours=48),
    )
    assert [entry["generation_id"] for entry in expired_plan["entries"]] == [
        record.stem
    ]


def test_orphan_pin_fails_closed(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    now = dt.datetime(2026, 7, 15, 12, tzinfo=UTC)
    record, _, _ = create_success(store, index=82, completed_at=now)
    store.pin(record, reason="baseline", now=now)
    record.unlink()

    with pytest.raises(PublicationPolicyError, match="pins reference missing"):
        store.plan_retention(
            "heimgewebe__demo",
            "main",
            policy=RetentionPolicy(),
            now=now,
        )


def test_cli_round_trip_enforces_identity_noop(tmp_path: Path) -> None:
    script = (
        Path(__file__).resolve().parents[3] / "scripts" / "ops" / "repoground-publication-policy"
    )
    evidence = tmp_path / "evidence"
    payload_root = tmp_path / "payloads"
    first_payload = payload_root / "heimgewebe__demo" / "main" / "first"
    second_payload = payload_root / "heimgewebe__demo" / "main" / "second"
    identity_args = [
        "--repository",
        "heimgewebe__demo",
        "--lane",
        "main",
        "--repository-commit",
        "1" * 40,
        "--profile",
        "full-max",
        "--configuration-sha256",
        "2" * 64,
        "--repoground-version",
        "1.0.0",
        "--bundle-schema",
        "repobrief.bundle.v1",
        "--generator-inputs-sha256",
        "3" * 64,
    ]

    def invoke(*arguments: str) -> dict[str, object]:
        completed = subprocess.run(
            [
                str(script),
                "--evidence-root",
                str(evidence),
                "--payload-root",
                str(payload_root),
                *arguments,
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        value = json.loads(completed.stdout)
        assert isinstance(value, dict)
        return value

    begun = invoke("begin", *identity_args, "--payload", str(first_payload))
    assert begun["status"] == "created"
    manifest = write_payload(first_payload, "cli")
    completed = invoke(
        "complete",
        "--record",
        str(begun["record_path"]),
        "--manifest",
        str(manifest),
    )
    assert completed["status"] == "completed"

    repeated = invoke("begin", *identity_args, "--payload", str(second_payload))
    assert repeated["status"] == "noop"
    assert not second_payload.exists()


def test_begin_refuses_preexisting_unbound_payload(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    payload = store.payload_root / "heimgewebe__demo" / "main" / "occupied"
    payload.mkdir(parents=True)

    with pytest.raises(PublicationPolicyError, match="already exists"):
        store.begin(
            make_identity(91),
            payload_path=payload,
            now=dt.datetime(2026, 7, 15, 12, tzinfo=UTC),
        )
    assert store.list_records("heimgewebe__demo", "main") == []


def test_tampered_plan_hash_fails_before_payload_mutation(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    base = dt.datetime(2026, 7, 15, 12, tzinfo=UTC)
    _, old_payload = create_prunable_success_set(
        store, start_index=92, completed_at=base
    )
    plan = store.plan_retention(
        "heimgewebe__demo",
        "main",
        policy=RetentionPolicy(),
        now=base,
    )
    plan["retained"] = []

    with pytest.raises(PublicationPolicyError, match="hash mismatch"):
        store.apply_plan(plan, now=base)
    assert old_payload.is_dir()


def test_payload_changed_after_plan_fails_closed(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    base = dt.datetime(2026, 7, 15, 12, tzinfo=UTC)
    _, old_payload = create_prunable_success_set(
        store, start_index=94, completed_at=base
    )
    plan = store.plan_retention(
        "heimgewebe__demo",
        "main",
        policy=RetentionPolicy(),
        now=base,
    )
    (old_payload / "repo_merge.md").write_text("changed", encoding="utf-8")

    with pytest.raises(PublicationPolicyError, match="payload changed"):
        store.apply_plan(plan, now=base)
    assert old_payload.is_dir()


def test_pin_added_after_quarantine_restores_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = make_store(tmp_path)
    base = dt.datetime(2026, 7, 15, 12, tzinfo=UTC)
    old_record, old_payload = create_prunable_success_set(
        store, start_index=96, completed_at=base
    )
    policy = RetentionPolicy()
    plan = store.plan_retention(
        "heimgewebe__demo", "main", policy=policy, now=base
    )
    real_remove_tree = publication_policy.remove_tree

    def crash_before_delete(path: str | Path, *args: object, **kwargs: object) -> None:
        raise RuntimeError("simulated crash before delete")

    monkeypatch.setattr(publication_policy, "remove_tree", crash_before_delete)
    with pytest.raises(RuntimeError, match="simulated crash"):
        store.apply_plan(plan, now=base)
    assert not old_payload.exists()

    store.pin(old_record, reason="retain after review", now=base)
    monkeypatch.setattr(publication_policy, "remove_tree", real_remove_tree)
    result = store.reconcile_transactions(
        "heimgewebe__demo", "main", policy=policy, now=base
    )

    assert result["results"][0]["status"] == "restored"
    assert old_payload.is_dir()
    record = json.loads(old_record.read_text(encoding="utf-8"))
    assert record["payload_state"] == "present"


def test_repeated_fail_does_not_extend_failed_ttl(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    now = dt.datetime(2026, 7, 15, 12, tzinfo=UTC)
    identity = make_identity(101)
    payload = store.payload_root / identity.repository / identity.lane / "failed-once"
    begun = store.begin(
        identity, payload_path=payload, now=now - dt.timedelta(hours=72)
    )
    payload.mkdir(parents=True)
    record = Path(str(begun["record_path"]))
    first = store.fail(
        record, reason="first failure", now=now - dt.timedelta(hours=49)
    )
    second = store.fail(
        record, reason="later duplicate report", now=now - dt.timedelta(hours=1)
    )

    assert first["status"] == "failed"
    assert second["status"] == "already_failed"
    plan = store.plan_retention(
        identity.repository,
        identity.lane,
        policy=RetentionPolicy(),
        now=now,
    )
    assert [entry["generation_id"] for entry in plan["entries"]] == [record.stem]


def test_pruned_payload_cannot_be_pinned(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    now = dt.datetime(2026, 7, 15, 12, tzinfo=UTC)
    old_record, _ = create_prunable_success_set(
        store, start_index=102, completed_at=now
    )
    plan = store.plan_retention(
        "heimgewebe__demo",
        "main",
        policy=RetentionPolicy(),
        now=now,
    )
    store.apply_plan(plan, now=now)

    with pytest.raises(PublicationPolicyError, match="present payload"):
        store.pin(old_record, reason="too late", now=now)


def test_duplicate_plan_generation_fails_before_mutation(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    now = dt.datetime(2026, 7, 15, 12, tzinfo=UTC)
    _, old_payload = create_prunable_success_set(
        store, start_index=104, completed_at=now
    )
    plan = store.plan_retention(
        "heimgewebe__demo",
        "main",
        policy=RetentionPolicy(),
        now=now,
    )
    entries = plan["entries"]
    assert isinstance(entries, list) and entries
    entries.append(dict(entries[0]))
    unhashed = dict(plan)
    unhashed.pop("plan_sha256")
    plan["plan_sha256"] = canonical_sha256(unhashed)

    with pytest.raises(PublicationPolicyError, match="duplicate retention plan"):
        store.apply_plan(plan, now=now)
    assert old_payload.is_dir()


def test_tree_snapshot_rejects_symlinks(tmp_path: Path) -> None:
    payload = tmp_path / "payload"
    payload.mkdir()
    target = tmp_path / "target"
    target.write_text("data", encoding="utf-8")
    (payload / "link").symlink_to(target)

    with pytest.raises(PublicationPolicyError, match="symlink"):
        tree_snapshot(payload)
