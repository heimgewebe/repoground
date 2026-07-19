"""Tests for QueryArtifactStore.diagnostics() — Runtime Artifact Retention Diagnostics v0.

Diagnose-only: this method does not delete, does not enable TTL/GC, and must
not mutate stored artifact payloads or the on-disk store file.
"""
import json
import time

import pytest

from merger.repoground.service.query_artifact_store import QueryArtifactStore
from merger.repoground.service.runtime_artifact_retention import RETENTION_POLICY_ID


_DIAGNOSTIC_FIELDS = {
    "total_artifacts",
    "by_artifact_type",
    "oldest_created_at",
    "newest_created_at",
    "store_file_size_bytes",
    "retention_policy",
    "retention_policy_id",
    "retention_policy_status",
    "gc_enabled",
    "ttl_enabled",
}


@pytest.fixture
def storage_dir(tmp_path):
    return tmp_path / ".repoground-service"


@pytest.fixture
def store(storage_dir):
    return QueryArtifactStore(storage_dir)


def _prov(query="q", timestamp="2024-01-01T00:00:00+00:00"):
    return {"source_query": query, "timestamp": timestamp}


class TestQueryArtifactStoreDiagnosticsEmpty:
    def test_empty_store_reports_zero_total(self, store):
        diag = store.diagnostics()
        assert diag["total_artifacts"] == 0
        assert diag["by_artifact_type"] == {}
        assert diag["oldest_created_at"] is None
        assert diag["newest_created_at"] is None

    def test_empty_store_file_size_is_zero(self, store):
        # No store() call has been made — _save() has not run, file should be absent.
        diag = store.diagnostics()
        assert diag["store_file_size_bytes"] == 0

    def test_empty_store_carries_retention_constants(self, store):
        diag = store.diagnostics()
        assert diag["retention_policy"] == "unbounded_currently"
        assert diag["retention_policy_id"] == RETENTION_POLICY_ID
        assert diag["retention_policy_status"] == "explicitly_deferred"
        assert diag["gc_enabled"] is False
        assert diag["ttl_enabled"] is False

    def test_empty_store_returns_expected_field_set(self, store):
        diag = store.diagnostics()
        assert set(diag.keys()) == _DIAGNOSTIC_FIELDS


class TestQueryArtifactStoreDiagnosticsCounts:
    def test_counts_per_artifact_type(self, store):
        store.store("query_trace", {}, _prov())
        store.store("query_trace", {}, _prov())
        store.store("context_bundle", {"query": "q", "hits": []}, _prov())
        store.store("agent_query_session", {"query": "q"}, _prov())

        diag = store.diagnostics()
        assert diag["total_artifacts"] == 4
        assert diag["by_artifact_type"] == {
            "query_trace": 2,
            "context_bundle": 1,
            "agent_query_session": 1,
        }

    def test_single_artifact_type_count(self, store):
        for _ in range(3):
            store.store("query_trace", {}, _prov())

        diag = store.diagnostics()
        assert diag["total_artifacts"] == 3
        assert diag["by_artifact_type"] == {"query_trace": 3}


class TestQueryArtifactStoreDiagnosticsTimes:
    def test_oldest_and_newest_created_at(self, store):
        store.store("query_trace", {}, _prov())
        time.sleep(0.01)
        store.store("query_trace", {}, _prov())
        time.sleep(0.01)
        store.store("query_trace", {}, _prov())

        diag = store.diagnostics()
        assert diag["oldest_created_at"] is not None
        assert diag["newest_created_at"] is not None
        assert diag["oldest_created_at"] <= diag["newest_created_at"]

        all_entries = store.get_all()
        creations = sorted(e["created_at"] for e in all_entries)
        assert diag["oldest_created_at"] == creations[0]
        assert diag["newest_created_at"] == creations[-1]

    def test_single_artifact_oldest_equals_newest(self, store):
        store.store("query_trace", {}, _prov())
        diag = store.diagnostics()
        assert diag["oldest_created_at"] == diag["newest_created_at"]
        assert diag["oldest_created_at"] is not None


class TestQueryArtifactStoreDiagnosticsFileSize:
    def test_store_file_size_reported_when_file_exists(self, store, storage_dir):
        store.store("query_trace", {"payload": "x" * 256}, _prov())

        diag = store.diagnostics()
        store_file = storage_dir / "query_artifacts.json"
        assert store_file.exists()
        assert diag["store_file_size_bytes"] == store_file.stat().st_size
        assert diag["store_file_size_bytes"] > 0

    def test_store_file_size_grows_with_more_entries(self, store):
        store.store("query_trace", {}, _prov())
        size_after_one = store.diagnostics()["store_file_size_bytes"]
        store.store("query_trace", {"larger": "payload" * 50}, _prov())
        size_after_two = store.diagnostics()["store_file_size_bytes"]
        assert size_after_two > size_after_one


class TestQueryArtifactStoreDiagnosticsReadOnly:
    def test_diagnostics_does_not_modify_store_file_content(self, store, storage_dir):
        store.store("query_trace", {}, _prov())
        store_file = storage_dir / "query_artifacts.json"
        before = store_file.read_bytes()

        for _ in range(3):
            store.diagnostics()

        assert store_file.read_bytes() == before

    def test_diagnostics_does_not_modify_store_file_mtime(self, store, storage_dir):
        store.store("query_trace", {}, _prov())
        store_file = storage_dir / "query_artifacts.json"
        mtime_before = store_file.stat().st_mtime_ns

        time.sleep(0.05)
        for _ in range(3):
            store.diagnostics()

        assert store_file.stat().st_mtime_ns == mtime_before

    def test_diagnostics_does_not_change_get_all_output(self, store):
        store.store("query_trace", {"k": "v"}, _prov())
        store.store("context_bundle", {"query": "q", "hits": []}, _prov())
        before = store.get_all()

        store.diagnostics()

        after = store.get_all()
        assert before == after

    def test_diagnostics_repeated_calls_are_stable(self, store):
        store.store("query_trace", {}, _prov())
        store.store("context_bundle", {"query": "q", "hits": []}, _prov())

        first = store.diagnostics()
        second = store.diagnostics()
        third = store.diagnostics()
        assert first == second == third


class TestQueryArtifactStoreDiagnosticsLegacy:
    def test_legacy_entries_without_lifecycle_fields_do_not_break_diagnostics(
        self, storage_dir
    ):
        """Legacy entries pre-dating the runtime-metadata schema must be counted.

        These entries lack ``authority``, ``canonicality``, ``artifact_shape``,
        ``retention_policy``, ``lifecycle_status``, ``expires_at``, and
        ``claim_boundaries``.  diagnostics() must read them from the cache
        without raising and without persisting any backfill.
        """
        storage_dir.mkdir(parents=True, exist_ok=True)
        store_file = storage_dir / "query_artifacts.json"
        legacy_entries = [
            {
                "id": "qart-legacy-trace",
                "artifact_type": "query_trace",
                "data": {"query_input": "legacy"},
                "provenance": {
                    "source_query": "legacy",
                    "timestamp": "2024-01-01T00:00:00+00:00",
                },
                "created_at": "2024-01-01T00:00:00+00:00",
            },
            {
                "id": "qart-legacy-bundle",
                "artifact_type": "context_bundle",
                "data": {"query": "q", "hits": []},
                "provenance": {
                    "source_query": "q",
                    "timestamp": "2024-02-15T10:00:00+00:00",
                },
                "created_at": "2024-02-15T10:00:00+00:00",
            },
        ]
        store_file.write_text(json.dumps(legacy_entries), encoding="utf-8")
        size_on_disk_before = store_file.stat().st_size
        mtime_before = store_file.stat().st_mtime_ns

        store = QueryArtifactStore(storage_dir)
        diag = store.diagnostics()

        assert diag["total_artifacts"] == 2
        assert diag["by_artifact_type"] == {
            "query_trace": 1,
            "context_bundle": 1,
        }
        assert diag["oldest_created_at"] == "2024-01-01T00:00:00+00:00"
        assert diag["newest_created_at"] == "2024-02-15T10:00:00+00:00"
        assert diag["retention_policy"] == "unbounded_currently"
        assert diag["gc_enabled"] is False
        assert diag["ttl_enabled"] is False

        # Diagnostics must not have rewritten the store to backfill metadata.
        assert store_file.stat().st_size == size_on_disk_before
        assert store_file.stat().st_mtime_ns == mtime_before

    def test_legacy_entry_without_created_at_is_counted_but_skipped_for_age(
        self, storage_dir
    ):
        storage_dir.mkdir(parents=True, exist_ok=True)
        store_file = storage_dir / "query_artifacts.json"
        entries = [
            {
                "id": "qart-no-time",
                "artifact_type": "query_trace",
                "data": {},
                "provenance": {"source_query": "q", "timestamp": "t"},
                # no created_at
            },
        ]
        store_file.write_text(json.dumps(entries), encoding="utf-8")

        store = QueryArtifactStore(storage_dir)
        diag = store.diagnostics()
        assert diag["total_artifacts"] == 1
        assert diag["by_artifact_type"] == {"query_trace": 1}
        assert diag["oldest_created_at"] is None
        assert diag["newest_created_at"] is None

    def test_malformed_created_at_is_counted_but_ignored_for_age(self, storage_dir):
        storage_dir.mkdir(parents=True, exist_ok=True)
        store_file = storage_dir / "query_artifacts.json"
        entries = [
            {
                "id": "qart-valid",
                "artifact_type": "query_trace",
                "data": {},
                "provenance": {"source_query": "q", "timestamp": "t"},
                "created_at": "2024-01-01T00:00:00+00:00",
            },
            {
                "id": "qart-bad-time",
                "artifact_type": "query_trace",
                "data": {},
                "provenance": {"source_query": "q", "timestamp": "t"},
                "created_at": "not-a-date",
            },
        ]
        store_file.write_text(json.dumps(entries), encoding="utf-8")

        store = QueryArtifactStore(storage_dir)
        diag = store.diagnostics()
        assert diag["total_artifacts"] == 2
        assert diag["by_artifact_type"] == {"query_trace": 2}
        assert diag["oldest_created_at"] == "2024-01-01T00:00:00+00:00"
        assert diag["newest_created_at"] == "2024-01-01T00:00:00+00:00"

    def test_age_range_uses_only_valid_offset_aware_timestamps(self, storage_dir):
        storage_dir.mkdir(parents=True, exist_ok=True)
        store_file = storage_dir / "query_artifacts.json"
        entries = [
            {
                "id": "qart-invalid",
                "artifact_type": "query_trace",
                "data": {},
                "provenance": {"source_query": "q", "timestamp": "t"},
                "created_at": "not-a-date",
            },
            {
                "id": "qart-zulu",
                "artifact_type": "context_bundle",
                "data": {},
                "provenance": {"source_query": "q", "timestamp": "t"},
                "created_at": "2024-01-01T00:00:00Z",
            },
            {
                "id": "qart-naive",
                "artifact_type": "query_trace",
                "data": {},
                "provenance": {"source_query": "q", "timestamp": "t"},
                "created_at": "2024-01-01T01:00:00",
            },
            {
                "id": "qart-aware-late",
                "artifact_type": "agent_query_session",
                "data": {},
                "provenance": {"source_query": "q", "timestamp": "t"},
                "created_at": "2024-01-01T03:00:00+02:00",
            },
            {
                "id": "qart-aware-early",
                "artifact_type": "query_trace",
                "data": {},
                "provenance": {"source_query": "q", "timestamp": "t"},
                "created_at": "2023-12-31T23:30:00+00:00",
            },
        ]
        store_file.write_text(json.dumps(entries), encoding="utf-8")

        store = QueryArtifactStore(storage_dir)
        diag = store.diagnostics()
        assert diag["total_artifacts"] == 5
        assert diag["by_artifact_type"] == {
            "query_trace": 3,
            "context_bundle": 1,
            "agent_query_session": 1,
        }
        assert diag["oldest_created_at"] == "2023-12-31T23:30:00+00:00"
        assert diag["newest_created_at"] == "2024-01-01T03:00:00+02:00"

    def test_z_suffix_is_accepted_and_naive_timestamp_is_skipped(self, storage_dir):
        storage_dir.mkdir(parents=True, exist_ok=True)
        store_file = storage_dir / "query_artifacts.json"
        entries = [
            {
                "id": "qart-zulu-only-valid",
                "artifact_type": "query_trace",
                "data": {},
                "provenance": {"source_query": "q", "timestamp": "t"},
                "created_at": "2024-01-01T00:00:00Z",
            },
            {
                "id": "qart-naive-invalid",
                "artifact_type": "query_trace",
                "data": {},
                "provenance": {"source_query": "q", "timestamp": "t"},
                "created_at": "2024-01-02T00:00:00",
            },
        ]
        store_file.write_text(json.dumps(entries), encoding="utf-8")

        store = QueryArtifactStore(storage_dir)
        diag = store.diagnostics()
        assert diag["total_artifacts"] == 2
        assert diag["by_artifact_type"] == {"query_trace": 2}
        assert diag["oldest_created_at"] == "2024-01-01T00:00:00Z"
        assert diag["newest_created_at"] == "2024-01-01T00:00:00Z"

    def test_legacy_entry_without_artifact_type_counts_as_unknown(self, storage_dir):
        """Entry missing artifact_type field should be counted under 'unknown'."""
        storage_dir.mkdir(parents=True, exist_ok=True)
        store_file = storage_dir / "query_artifacts.json"
        entries = [
            {
                "id": "qart-no-type",
                "data": {"query_input": "test"},
                "provenance": {"source_query": "test", "timestamp": "t"},
                "created_at": "2024-01-01T00:00:00+00:00",
                # no artifact_type
            },
        ]
        store_file.write_text(json.dumps(entries), encoding="utf-8")

        store = QueryArtifactStore(storage_dir)
        diag = store.diagnostics()
        assert diag["total_artifacts"] == 1
        assert diag["by_artifact_type"] == {"unknown": 1}

    def test_legacy_entry_with_empty_artifact_type_counts_as_unknown(
        self, storage_dir
    ):
        """Entry with empty artifact_type should be counted under 'unknown'."""
        storage_dir.mkdir(parents=True, exist_ok=True)
        store_file = storage_dir / "query_artifacts.json"
        entries = [
            {
                "id": "qart-empty-type",
                "artifact_type": "",
                "data": {"query_input": "test"},
                "provenance": {"source_query": "test", "timestamp": "t"},
                "created_at": "2024-01-01T00:00:00+00:00",
            },
        ]
        store_file.write_text(json.dumps(entries), encoding="utf-8")

        store = QueryArtifactStore(storage_dir)
        diag = store.diagnostics()
        assert diag["total_artifacts"] == 1
        assert diag["by_artifact_type"] == {"unknown": 1}

    def test_legacy_entry_with_non_string_artifact_type_counts_as_unknown(
        self, storage_dir
    ):
        """Entry with non-string artifact_type should be counted under 'unknown'."""
        storage_dir.mkdir(parents=True, exist_ok=True)
        store_file = storage_dir / "query_artifacts.json"
        entries = [
            {
                "id": "qart-int-type",
                "artifact_type": 123,  # Non-string type
                "data": {"query_input": "test"},
                "provenance": {"source_query": "test", "timestamp": "t"},
                "created_at": "2024-01-01T00:00:00+00:00",
            },
        ]
        store_file.write_text(json.dumps(entries), encoding="utf-8")

        store = QueryArtifactStore(storage_dir)
        diag = store.diagnostics()
        assert diag["total_artifacts"] == 1
        assert diag["by_artifact_type"] == {"unknown": 1}

    def test_mix_of_known_and_unknown_artifact_types(self, storage_dir):
        """Multiple artifacts with mixed known and unknown types counted separately."""
        storage_dir.mkdir(parents=True, exist_ok=True)
        store_file = storage_dir / "query_artifacts.json"
        entries = [
            {
                "id": "qart-trace",
                "artifact_type": "query_trace",
                "data": {},
                "provenance": {"source_query": "q", "timestamp": "t"},
                "created_at": "2024-01-01T00:00:00+00:00",
            },
            {
                "id": "qart-unknown",
                "data": {},
                "provenance": {"source_query": "q", "timestamp": "t"},
                "created_at": "2024-01-01T01:00:00+00:00",
                # no artifact_type
            },
            {
                "id": "qart-bundle",
                "artifact_type": "context_bundle",
                "data": {},
                "provenance": {"source_query": "q", "timestamp": "t"},
                "created_at": "2024-01-01T02:00:00+00:00",
            },
            {
                "id": "qart-bad-type",
                "artifact_type": None,
                "data": {},
                "provenance": {"source_query": "q", "timestamp": "t"},
                "created_at": "2024-01-01T03:00:00+00:00",
            },
        ]
        store_file.write_text(json.dumps(entries), encoding="utf-8")

        store = QueryArtifactStore(storage_dir)
        diag = store.diagnostics()
        assert diag["total_artifacts"] == 4
        assert diag["by_artifact_type"] == {
            "query_trace": 1,
            "context_bundle": 1,
            "unknown": 2,  # 2 entries with missing/None artifact_type
        }
