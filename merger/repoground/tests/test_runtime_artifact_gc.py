import json
import os
from pathlib import Path

import pytest

from merger.repoground.service.query_artifact_store import QueryArtifactStore
from merger.repoground.service.runtime_artifact_gc import (
    RuntimeArtifactGCError,
    build_retention_plan,
)
from merger.repoground.service.runtime_artifact_retention import (
    MANUAL_GC_DEFAULT_PROFILE,
    RUNTIME_ARTIFACT_TYPES,
    runtime_artifact_gc_profile,
    runtime_artifact_retention_policy,
)


def _entry(
    artifact_id: str,
    artifact_type: str,
    created_at: str,
    *,
    artifact_refs=None,
    payload_size: int = 0,
):
    data = {"payload": "x" * payload_size}
    if artifact_type == "agent_query_session":
        data["artifact_refs"] = artifact_refs or {}
    return {
        "id": artifact_id,
        "artifact_type": artifact_type,
        "data": data,
        "provenance": {"source_query": "q", "timestamp": created_at, "run_id": "run-1"},
        "created_at": created_at,
        "retention_policy": "unbounded_currently",
    }


def _protection(*, active=(), pins=(), external=(), reference_state="complete"):
    return {
        "schema_version": 1,
        "reference_state": reference_state,
        "active_session_ids": list(active),
        "pinned_artifact_ids": list(pins),
        "external_references": list(external),
    }


def _tiny_budgets():
    return {
        artifact_type: {
            "max_age_seconds": 10,
            "max_count": 1,
            "max_bytes": 450,
        }
        for artifact_type in RUNTIME_ARTIFACT_TYPES
    }


def _write_store(storage_dir: Path, entries) -> QueryArtifactStore:
    storage_dir.mkdir(parents=True, exist_ok=True)
    (storage_dir / "query_artifacts.json").write_text(json.dumps(entries, indent=2), encoding="utf-8")
    return QueryArtifactStore(storage_dir)


def test_policy_exposes_manual_budget_profile_without_automatic_delete():
    policy = runtime_artifact_retention_policy()
    manual = policy["manual_gc"]

    assert policy["default_retention_policy"] == "unbounded_currently"
    assert policy["ttl"]["enabled"] is False
    assert policy["gc"]["automatic_delete"] is False
    assert manual["enabled"] is True
    assert manual["automatic_delete"] is False
    assert manual["mode"] == "explicit_plan_hash_bound_apply"
    assert manual["default_profile"] == MANUAL_GC_DEFAULT_PROFILE
    assert manual["unknown_reference_state_blocks"] is True
    assert set(manual["profiles"][MANUAL_GC_DEFAULT_PROFILE]) == set(RUNTIME_ARTIFACT_TYPES)
    for budget in runtime_artifact_gc_profile().values():
        assert set(budget) == {"max_age_seconds", "max_count", "max_bytes"}
        assert all(value > 0 for value in budget.values())


def test_plan_is_deterministic_and_records_age_count_and_bytes_reasons():
    entries = [
        _entry("qart-a", "query_trace", "2025-01-01T00:00:00Z", payload_size=300),
        _entry("qart-b", "query_trace", "2025-01-02T00:00:00Z", payload_size=300),
        _entry("qart-c", "query_trace", "2025-01-03T00:00:00Z", payload_size=300),
    ]
    kwargs = dict(
        entries=entries,
        store_sha256="a" * 64,
        protection=_protection(),
        as_of="2026-01-01T00:00:00Z",
        profile_id="test",
        budgets=_tiny_budgets(),
    )

    first = build_retention_plan(**kwargs)
    second = build_retention_plan(**kwargs)

    assert first == second
    assert first["plan_sha256"] == second["plan_sha256"]
    assert first["automatic_delete"] is False
    assert first["requires_explicit_apply"] is True
    assert first["expected_release"]["objects"] == 3
    all_reasons = {reason for candidate in first["candidates"] for reason in candidate["reasons"]}
    assert "age_budget" in all_reasons
    assert "count_budget" in all_reasons or "bytes_budget" in all_reasons


def test_active_session_protects_itself_and_referenced_artifacts():
    entries = [
        _entry("qart-trace", "query_trace", "2020-01-01T00:00:00Z"),
        _entry("qart-bundle", "context_bundle", "2020-01-01T00:00:00Z"),
        _entry(
            "qart-session",
            "agent_query_session",
            "2020-01-01T00:00:00Z",
            artifact_refs={
                "query_trace_id": "qart-trace",
                "context_bundle_id": "qart-bundle",
            },
        ),
    ]
    plan = build_retention_plan(
        entries=entries,
        store_sha256="b" * 64,
        protection=_protection(active=("qart-session",)),
        as_of="2026-01-01T00:00:00Z",
        profile_id="test",
        budgets=_tiny_budgets(),
    )

    assert plan["candidates"] == []
    protected = {row["artifact_id"]: row["reasons"] for row in plan["protected"]}
    assert "active_session" in protected["qart-session"]
    assert any(reason.startswith("active_session_ref:qart-session") for reason in protected["qart-trace"])
    assert any(reason.startswith("active_session_ref:qart-session") for reason in protected["qart-bundle"])


def test_pin_and_nonterminal_external_reference_are_protected():
    entries = [
        _entry("qart-pin", "query_trace", "2020-01-01T00:00:00Z"),
        _entry("qart-pr", "context_bundle", "2020-01-01T00:00:00Z"),
    ]
    plan = build_retention_plan(
        entries=entries,
        store_sha256="c" * 64,
        protection=_protection(
            pins=("qart-pin",),
            external=(
                {
                    "artifact_id": "qart-pr",
                    "kind": "pull_request",
                    "state": "nonterminal",
                    "reference": "heimgewebe/repoground#123",
                },
            ),
        ),
        as_of="2026-01-01T00:00:00Z",
        profile_id="test",
        budgets=_tiny_budgets(),
    )

    assert plan["candidates"] == []
    protected = {row["artifact_id"] for row in plan["protected"]}
    assert protected == {"qart-pin", "qart-pr"}


def test_unknown_reference_state_blocks_plan():
    with pytest.raises(RuntimeArtifactGCError) as excinfo:
        build_retention_plan(
            entries=[_entry("qart-a", "query_trace", "2020-01-01T00:00:00Z")],
            store_sha256="d" * 64,
            protection=_protection(reference_state="unknown"),
            as_of="2026-01-01T00:00:00Z",
            profile_id="test",
            budgets=_tiny_budgets(),
        )
    assert excinfo.value.code == "reference_state_unknown"


def test_unknown_created_at_is_protected_not_deleted():
    entry = _entry("qart-a", "query_trace", "2020-01-01T00:00:00Z")
    entry["created_at"] = "not-a-date"
    plan = build_retention_plan(
        entries=[entry],
        store_sha256="e" * 64,
        protection=_protection(),
        as_of="2026-01-01T00:00:00Z",
        profile_id="test",
        budgets=_tiny_budgets(),
    )
    assert plan["candidates"] == []
    assert plan["protected"] == [{"artifact_id": "qart-a", "reasons": ["created_at_unknown"]}]


def test_store_apply_rejects_tampered_plan_hash(tmp_path):
    store = _write_store(
        tmp_path,
        [_entry("qart-a", "query_trace", "2020-01-01T00:00:00Z")],
    )
    plan = store.retention_plan(
        protection=_protection(),
        as_of="2026-01-01T00:00:00Z",
    )
    plan["expected_release"]["objects"] += 1

    with pytest.raises(RuntimeArtifactGCError) as excinfo:
        store.apply_retention(plan=plan, protection=_protection())
    assert excinfo.value.code == "plan_hash_mismatch"


def test_store_apply_rejects_changed_snapshot(tmp_path):
    store = _write_store(
        tmp_path,
        [_entry("qart-old", "query_trace", "2020-01-01T00:00:00Z")],
    )
    plan = store.retention_plan(
        protection=_protection(),
        as_of="2026-01-01T00:00:00Z",
    )
    other = QueryArtifactStore(tmp_path)
    other.store(
        "query_trace",
        {"new": True},
        {"source_query": "q", "timestamp": "2026-01-01T00:00:00Z"},
    )

    with pytest.raises(RuntimeArtifactGCError) as excinfo:
        store.apply_retention(plan=plan, protection=_protection())
    assert excinfo.value.code == "store_snapshot_changed"


def test_new_pin_between_plan_and_apply_skips_candidate_and_receipt_is_idempotent(tmp_path):
    store = _write_store(
        tmp_path,
        [_entry("qart-old", "query_trace", "2020-01-01T00:00:00Z")],
    )
    plan = store.retention_plan(
        protection=_protection(),
        as_of="2026-01-01T00:00:00Z",
    )

    receipt = store.apply_retention(
        plan=plan,
        protection=_protection(pins=("qart-old",)),
    )
    assert receipt["status"] == "applied"
    assert receipt["deleted"]["objects"] == 0
    assert receipt["skipped_newly_protected"] == ["qart-old"]
    assert store.get("qart-old") is not None

    replay = store.apply_retention(
        plan=plan,
        protection=_protection(pins=("qart-old",)),
    )
    assert replay["receipt_sha256"] == receipt["receipt_sha256"]
    assert replay["idempotent_replay"] is True


def test_apply_deletes_candidate_and_other_store_instance_observes_change(tmp_path):
    store = _write_store(
        tmp_path,
        [_entry("qart-old", "query_trace", "2020-01-01T00:00:00Z")],
    )
    stale_reader = QueryArtifactStore(tmp_path)
    plan = store.retention_plan(
        protection=_protection(),
        as_of="2026-01-01T00:00:00Z",
    )

    receipt = store.apply_retention(plan=plan, protection=_protection())

    assert receipt["deleted"]["objects"] == 1
    assert receipt["deleted"]["bytes"] > 0
    assert receipt["integrity_readback"]["post_store_sha256"]
    assert store.get("qart-old") is None
    assert stale_reader.get("qart-old") is None

    replay = store.apply_retention(plan=plan, protection=_protection())
    assert replay["idempotent_replay"] is True
    assert replay["receipt_sha256"] == receipt["receipt_sha256"]


def test_apply_recovers_receipt_when_effect_completed_before_receipt(tmp_path):
    store = _write_store(
        tmp_path,
        [_entry("qart-old", "query_trace", "2020-01-01T00:00:00Z")],
    )
    plan = store.retention_plan(
        protection=_protection(),
        as_of="2026-01-01T00:00:00Z",
    )
    receipt = store.apply_retention(plan=plan, protection=_protection())
    receipt_path = tmp_path / "retention-receipts" / f"{plan['plan_sha256']}.json"
    receipt_path.unlink()

    recovered = store.apply_retention(plan=plan, protection=_protection())

    assert recovered["receipt_sha256"] == receipt["receipt_sha256"]
    assert recovered["recovered_after_effect"] is True
    assert receipt_path.exists()


def test_symlink_store_is_rejected_fail_closed(tmp_path):
    outside = tmp_path / "outside.json"
    outside.write_text("[]", encoding="utf-8")
    storage = tmp_path / "store"
    storage.mkdir()
    (storage / "query_artifacts.json").symlink_to(outside)
    store = QueryArtifactStore(storage)

    with pytest.raises(RuntimeArtifactGCError) as excinfo:
        store.retention_plan(
            protection=_protection(),
            as_of="2026-01-01T00:00:00Z",
        )
    assert excinfo.value.code == "unsafe_store_entry"


def test_stale_writer_reloads_disk_before_store_and_does_not_resurrect_gc_entries(tmp_path):
    store = _write_store(
        tmp_path,
        [_entry("qart-old", "query_trace", "2020-01-01T00:00:00Z")],
    )
    stale_writer = QueryArtifactStore(tmp_path)
    plan = store.retention_plan(
        protection=_protection(),
        as_of="2026-01-01T00:00:00Z",
    )
    store.apply_retention(plan=plan, protection=_protection())

    new_id = stale_writer.store(
        "query_trace",
        {"new": True},
        {"source_query": "q", "timestamp": "2026-01-01T00:00:00Z"},
    )

    assert stale_writer.get("qart-old") is None
    assert stale_writer.get(new_id) is not None
    ids = {
        entry["id"]
        for entry in json.loads((tmp_path / "query_artifacts.json").read_text(encoding="utf-8"))
    }
    assert "qart-old" not in ids
    assert new_id in ids


def test_pending_gc_transaction_blocks_normal_store_until_receipt_recovery(tmp_path):
    store = _write_store(
        tmp_path,
        [_entry("qart-old", "query_trace", "2020-01-01T00:00:00Z")],
    )
    plan = store.retention_plan(
        protection=_protection(),
        as_of="2026-01-01T00:00:00Z",
    )
    store.apply_retention(plan=plan, protection=_protection())
    receipt_path = tmp_path / "retention-receipts" / f"{plan['plan_sha256']}.json"
    receipt_path.unlink()

    writer = QueryArtifactStore(tmp_path)
    with pytest.raises(RuntimeArtifactGCError) as excinfo:
        writer.store(
            "query_trace",
            {"blocked": True},
            {"source_query": "q", "timestamp": "2026-01-01T00:00:00Z"},
        )
    assert excinfo.value.code == "retention_transaction_pending"

    recovered = store.apply_retention(plan=plan, protection=_protection())
    assert recovered["recovered_after_effect"] is True
    writer.store(
        "query_trace",
        {"after_recovery": True},
        {"source_query": "q", "timestamp": "2026-01-01T00:00:00Z"},
    )

def test_gc_rejects_foreign_owned_storage_directory(monkeypatch, tmp_path):
    from merger.repoground.service import runtime_artifact_gc_store as gc_store

    original_lstat = gc_store.lstat_path

    def foreign_storage_lstat(path):
        metadata = original_lstat(path)
        if Path(path) != tmp_path:
            return metadata
        values = list(metadata)
        values[4] = os.geteuid() + 1
        return os.stat_result(values)

    monkeypatch.setattr(gc_store, "lstat_path", foreign_storage_lstat)

    with pytest.raises(RuntimeArtifactGCError) as excinfo:
        gc_store.RuntimeArtifactGCStore(tmp_path)
    assert excinfo.value.code == "foreign_store_owner"

def test_symlink_receipt_cannot_mask_pending_transaction(tmp_path):
    store = _write_store(
        tmp_path,
        [_entry("qart-old", "query_trace", "2020-01-01T00:00:00Z")],
    )
    plan = store.retention_plan(
        protection=_protection(),
        as_of="2026-01-01T00:00:00Z",
    )
    store.apply_retention(plan=plan, protection=_protection())

    receipt_path = tmp_path / "retention-receipts" / f"{plan['plan_sha256']}.json"
    outside = tmp_path / "outside-receipt.json"
    outside.write_bytes(receipt_path.read_bytes())
    receipt_path.unlink()
    receipt_path.symlink_to(outside)

    writer = QueryArtifactStore(tmp_path)
    with pytest.raises(RuntimeArtifactGCError) as excinfo:
        writer.store(
            "query_trace",
            {"must_not_write": True},
            {"source_query": "q", "timestamp": "2026-01-01T00:00:00Z"},
        )

    assert excinfo.value.code == "unsafe_store_entry"
    persisted = json.loads((tmp_path / "query_artifacts.json").read_text(encoding="utf-8"))
    assert persisted == []
