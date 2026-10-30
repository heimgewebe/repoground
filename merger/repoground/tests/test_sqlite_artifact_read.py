"""Boundary checks for file-backed, hash-verified SQLite bundle access."""

from __future__ import annotations

import pytest

from merger.repoground.core.bounded_artifact_read import MAX_REGISTERED_ARTIFACT_BYTES
from merger.repoground.core.sqlite_artifact_read import (
    MAX_SQLITE_ARTIFACT_BYTES,
    SQLITE_HASH_CHUNK_BYTES,
    SqliteArtifactValidationError,
    sqlite_integrity_contract,
)

# Observed from the verified 2026-10-30 Commonworld 50,770-chunk bundle.
COMMONWORLD_SQLITE_INDEX_BYTES = 504_496_128


def test_large_commonworld_sqlite_uses_separate_finite_streaming_budget() -> None:
    assert MAX_REGISTERED_ARTIFACT_BYTES == 256 * 1024 * 1024
    assert MAX_SQLITE_ARTIFACT_BYTES == 1024 * 1024 * 1024
    assert SQLITE_HASH_CHUNK_BYTES == 1024 * 1024
    assert MAX_REGISTERED_ARTIFACT_BYTES < COMMONWORLD_SQLITE_INDEX_BYTES
    assert COMMONWORLD_SQLITE_INDEX_BYTES < MAX_SQLITE_ARTIFACT_BYTES
    declared = {
        "bytes": COMMONWORLD_SQLITE_INDEX_BYTES,
        "sha256": "a" * 64,
    }
    assert sqlite_integrity_contract(declared) == (
        COMMONWORLD_SQLITE_INDEX_BYTES,
        "a" * 64,
    )


def test_sqlite_still_rejects_bytes_over_its_own_hard_limit() -> None:
    with pytest.raises(SqliteArtifactValidationError) as caught:
        sqlite_integrity_contract({
            "bytes": MAX_SQLITE_ARTIFACT_BYTES + 1,
            "sha256": "b" * 64,
        })
    assert caught.value.error_code == "sqlite_index_too_large"


@pytest.mark.parametrize(
    "artifact",
    [
        {"bytes": True, "sha256": "a" * 64},
        {"bytes": -1, "sha256": "a" * 64},
        {"bytes": COMMONWORLD_SQLITE_INDEX_BYTES, "sha256": "not-a-digest"},
        {"bytes": COMMONWORLD_SQLITE_INDEX_BYTES},
        {"sha256": "a" * 64},
    ],
)
def test_sqlite_never_accepts_invalid_manifest_integrity(artifact: dict) -> None:
    with pytest.raises(SqliteArtifactValidationError) as caught:
        sqlite_integrity_contract(artifact)
    assert caught.value.error_code == "sqlite_index_integrity_unavailable"
