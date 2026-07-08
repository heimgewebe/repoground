import json

import pytest

from merger.lenskit.service.query_artifact_store import QueryArtifactStore, VALID_ARTIFACT_TYPES
from merger.lenskit.service.runtime_artifact_retention import (
    RETENTION_POLICY_ID,
    RUNTIME_ARTIFACT_TYPES,
    runtime_artifact_metadata_for,
    runtime_artifact_retention_policy,
)


def test_runtime_artifact_retention_policy_is_machine_readable_and_deferred():
    policy = runtime_artifact_retention_policy()

    assert policy["kind"] == "lenskit.runtime_artifact_retention_policy"
    assert policy["policy_id"] == RETENTION_POLICY_ID
    assert policy["status"] == "explicitly_deferred"
    assert policy["default_retention_policy"] == "unbounded_currently"
    assert policy["ttl"] == {
        "enabled": False,
        "default_ttl_seconds": None,
        "rationale": "No TTL is active for query runtime artifacts in this version.",
    }
    assert policy["gc"]["enabled"] is False
    assert policy["gc"]["automatic_delete"] is False
    assert policy["gc"]["requires_explicit_future_policy"] is True
    assert policy["no_surprise_delete"] == {
        "existing_artifacts_deleted_by_this_policy": False,
        "store_write_path_deletes_existing_entries": False,
        "lookup_deletes_expired_entries": False,
    }
    assert policy["backward_compatibility"] == {
        "legacy_entries_backfilled_on_read": True,
        "legacy_entries_rewritten_on_read": False,
        "migration_required": False,
    }
    assert set(policy["applies_to"]) == set(RUNTIME_ARTIFACT_TYPES)
    assert "automatic_deletion" in policy["does_not_establish"]


def test_runtime_artifact_metadata_covers_all_store_types_without_gc_or_ttl():
    policy = runtime_artifact_retention_policy()

    assert set(VALID_ARTIFACT_TYPES) == set(RUNTIME_ARTIFACT_TYPES)
    assert set(policy["artifact_types"]) == set(VALID_ARTIFACT_TYPES)
    for artifact_type in VALID_ARTIFACT_TYPES:
        meta = runtime_artifact_metadata_for(artifact_type)
        assert meta == policy["artifact_types"][artifact_type]
        assert meta["retention_policy"] == "unbounded_currently"
        assert meta["lifecycle_status"] == "active"
        assert meta["expires_at"] is None
        assert meta["ttl_enabled"] is False
        assert meta["ttl_seconds"] is None
        assert meta["gc_enabled"] is False
        assert meta["deletion_mode"] == "not_supported_by_policy"


def test_runtime_artifact_metadata_rejects_unknown_type():
    with pytest.raises(ValueError):
        runtime_artifact_metadata_for("unknown")


def test_query_artifact_store_entries_use_retention_policy_without_deletion(tmp_path):
    store = QueryArtifactStore(tmp_path)
    artifact_id = store.store(
        "query_trace",
        {"trace": "payload"},
        {"source_query": "q", "timestamp": "2026-07-08T00:00:00+00:00"},
        run_id="run-1",
    )

    entry = store.get(artifact_id)
    assert entry is not None
    assert entry["retention_policy"] == "unbounded_currently"
    assert entry["ttl_enabled"] is False
    assert entry["ttl_seconds"] is None
    assert entry["gc_enabled"] is False
    assert entry["gc_mode"] == "not_implemented"
    assert entry["deletion_mode"] == "not_supported_by_policy"
    assert entry["expires_at"] is None

    stored = json.loads((tmp_path / "query_artifacts.json").read_text(encoding="utf-8"))
    assert len(stored) == 1
    assert stored[0]["id"] == artifact_id


def test_query_artifact_store_diagnostics_exposes_policy_id_without_mutation(tmp_path):
    store = QueryArtifactStore(tmp_path)
    artifact_id = store.store(
        "context_bundle",
        {"hits": []},
        {"source_query": "q", "timestamp": "2026-07-08T00:00:00+00:00"},
    )
    before = (tmp_path / "query_artifacts.json").read_text(encoding="utf-8")

    diagnostics = store.diagnostics()
    after = (tmp_path / "query_artifacts.json").read_text(encoding="utf-8")

    assert before == after
    assert diagnostics["total_artifacts"] == 1
    assert diagnostics["by_artifact_type"] == {"context_bundle": 1}
    assert diagnostics["retention_policy"] == "unbounded_currently"
    assert diagnostics["retention_policy_id"] == RETENTION_POLICY_ID
    assert diagnostics["retention_policy_status"] == "explicitly_deferred"
    assert diagnostics["gc_enabled"] is False
    assert diagnostics["ttl_enabled"] is False
    assert store.get(artifact_id) is not None


def test_legacy_entry_is_backfilled_on_read_but_not_rewritten(tmp_path):
    store_file = tmp_path / "query_artifacts.json"
    store_file.write_text(
        json.dumps([
            {
                "id": "qart-legacy",
                "artifact_type": "agent_query_session",
                "data": {"session": "legacy"},
                "provenance": {"source_query": "q", "timestamp": "2026-07-08T00:00:00+00:00"},
                "created_at": "2026-07-08T00:00:00+00:00",
            }
        ]),
        encoding="utf-8",
    )
    before = store_file.read_text(encoding="utf-8")
    store = QueryArtifactStore(tmp_path)

    entry = store.get("qart-legacy")
    after = store_file.read_text(encoding="utf-8")

    assert entry["retention_policy"] == "unbounded_currently"
    assert entry["ttl_enabled"] is False
    assert entry["gc_enabled"] is False
    assert before == after
