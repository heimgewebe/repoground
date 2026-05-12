import json
import logging
import sqlite3
import pytest
from unittest.mock import patch, MagicMock
from merger.lenskit.retrieval import index_db

@pytest.fixture
def mini_artifacts(tmp_path):
    # Setup paths
    dump_path = tmp_path / "dump.json"
    chunk_path = tmp_path / "chunks.jsonl"

    # Write chunks
    chunk_data = [
        {"chunk_id": "c1", "repo_id": "r1", "path": "src/main.py", "content": "def main(): pass", "start_line": 1, "end_line": 1, "layer": "core"},
        {"chunk_id": "c2", "repo_id": "r1", "path": "tests/test_main.py", "content": "def test_main(): assert True", "start_line": 1, "end_line": 1, "layer": "test"},
    ]
    with chunk_path.open("w") as f:
        for c in chunk_data:
            f.write(json.dumps(c) + "\n")

    # Write dump
    dump_data = {"dummy": "data"}
    dump_path.write_text(json.dumps(dump_data))

    return dump_path, chunk_path

def test_index_build_counts(mini_artifacts, tmp_path):
    dump_path, chunk_path = mini_artifacts
    db_path = tmp_path / "index.sqlite"

    index_db.build_index(dump_path, chunk_path, db_path)

    assert db_path.exists()

    conn = sqlite3.connect(str(db_path))
    c = conn.cursor()

    # Check chunks table count
    count = c.execute("SELECT count(*) FROM chunks").fetchone()[0]
    assert count == 2

    # Check FTS table count
    fts_count = c.execute("SELECT count(*) FROM chunks_fts").fetchone()[0]
    assert fts_count == 2

    conn.close()

def test_index_metadata_integrity(mini_artifacts, tmp_path):
    dump_path, chunk_path = mini_artifacts
    db_path = tmp_path / "index.sqlite"

    index_db.build_index(dump_path, chunk_path, db_path)

    conn = sqlite3.connect(str(db_path))
    c = conn.cursor()

    row = c.execute("SELECT value FROM index_meta WHERE key='schema_version'").fetchone()
    assert row[0] == index_db.INDEX_SCHEMA_VERSION

    conn.close()

def test_stale_index_detection(mini_artifacts, tmp_path):
    dump_path, chunk_path = mini_artifacts
    db_path = tmp_path / "index.sqlite"

    # Build initial
    index_db.build_index(dump_path, chunk_path, db_path)
    assert index_db.verify_index(db_path, dump_path, chunk_path) is True

    # Mutate dump file
    dump_path.write_text("modified content")

    # Check stale
    assert index_db.verify_index(db_path, dump_path, chunk_path) is False

def test_index_ingest_diagnostics(tmp_path, caplog):
    dump_path = tmp_path / "dump.json"
    chunk_path = tmp_path / "chunks.jsonl"
    db_path = tmp_path / "index.sqlite"

    dump_path.write_text("{}")

    # Create messy JSONL: 1 good, 1 invalid JSON, 1 missing chunk_id, 1 empty
    with chunk_path.open("w") as f:
        f.write('{"chunk_id": "ok1"}\n')
        f.write('BROKEN_JSON\n')
        f.write('{"repo": "missing_id"}\n')
        f.write('\n')

    with caplog.at_level(logging.WARNING, logger="merger.lenskit.retrieval.index_db"):
        index_db.build_index(dump_path, chunk_path, db_path)

    assert "Index ingest had issues" in caplog.text
    assert "invalid_json=1" in caplog.text
    assert "missing_id=1" in caplog.text

    conn = sqlite3.connect(str(db_path))
    c = conn.cursor()

    # Verify metadata stats
    meta = dict(c.execute("SELECT key, value FROM index_meta").fetchall())
    assert meta["ingest.total_lines"] == "4"
    assert meta["ingest.invalid_json_lines"] == "1"
    assert meta["ingest.missing_chunk_id_lines"] == "1"
    assert meta["ingest.empty_lines"] == "1"
    assert meta["ingest.ingested_chunks_count"] == "1"

    conn.close()


def test_build_index_closes_connection_on_error(tmp_path):
    """Regression: connection must be closed even when create_schema raises."""
    dump_path = tmp_path / "dump.json"
    chunk_path = tmp_path / "chunks.jsonl"
    db_path = tmp_path / "index.sqlite"

    dump_path.write_text("{}")
    chunk_path.write_text("")

    mock_conn = MagicMock(spec=sqlite3.Connection)
    mock_conn.close = MagicMock()

    with patch("merger.lenskit.retrieval.index_db.sqlite3") as mock_sqlite3:
        mock_sqlite3.connect.return_value = mock_conn
        # Simulate failure during schema creation
        mock_conn.cursor.side_effect = RuntimeError("injected schema failure")

        with pytest.raises(RuntimeError, match="injected schema failure"):
            index_db.build_index(dump_path, chunk_path, db_path)

    mock_conn.close.assert_called_once()


# ---------------------------------------------------------------------------
# FTS content hydration from content_range_ref (PR 1)
# ---------------------------------------------------------------------------

def _make_range_ref_env(tmp_path):
    """
    Build a minimal but valid environment for content_range_ref resolution:
    - canonical_md file with known content
    - dump_index.json with contract == "dump-index" pointing to it
    Returns (dump_path, canonical_md_path, ref_dict, expected_text)
    """
    import hashlib

    canonical_md = tmp_path / "canonical.md"
    # Use a unique token so we can later verify the FTS hit
    content = "# Section\n\nhydrateduniquetokenxq7z is the search term.\n"
    canonical_bytes = content.encode("utf-8")
    canonical_md.write_bytes(canonical_bytes)

    start_byte = 0
    end_byte = len(canonical_bytes)
    sha = hashlib.sha256(canonical_bytes[start_byte:end_byte]).hexdigest()

    ref = {
        "artifact_role": "canonical_md",
        "repo_id": "testrepo",
        "file_path": canonical_md.name,
        "start_byte": start_byte,
        "end_byte": end_byte,
        "start_line": 1,
        "end_line": 3,
        "content_sha256": sha,
    }

    dump_path = tmp_path / "dump.json"
    dump_path.write_text(json.dumps({
        "contract": "dump-index",
        "contract_version": "v1",
        "run_id": "test-run",
        "artifacts": {
            "canonical_md": {
                "role": "canonical_md",
                "path": canonical_md.name,
            }
        }
    }))

    return dump_path, canonical_md, ref, content


def test_fts_content_hydrated_from_range_ref(tmp_path):
    """Chunk without inline content but with content_range_ref must have FTS content populated."""
    dump_path, canonical_md, ref, expected_text = _make_range_ref_env(tmp_path)

    chunk_path = tmp_path / "chunks.jsonl"
    with chunk_path.open("w") as f:
        f.write(json.dumps({
            "chunk_id": "c_ref",
            "repo_id": "testrepo",
            "path": "docs/section.md",
            "layer": "core",
            "content_range_ref": ref,
            # intentionally NO "content" key
        }) + "\n")

    db_path = tmp_path / "index.sqlite"
    index_db.build_index(dump_path, chunk_path, db_path)

    conn = sqlite3.connect(str(db_path))
    try:
        # FTS content must not be empty
        row = conn.execute(
            "SELECT content FROM chunks_fts WHERE chunk_id = 'c_ref'"
        ).fetchone()
        assert row is not None, "No FTS row found for chunk c_ref"
        assert row[0] == expected_text, (
            f"FTS content mismatch. Got: {row[0]!r}"
        )

        # A term that only appears in the resolved content must produce an FTS hit
        hits = conn.execute(
            "SELECT chunk_id FROM chunks_fts WHERE chunks_fts MATCH 'hydrateduniquetokenxq7z'"
        ).fetchall()
        assert any(h[0] == "c_ref" for h in hits), (
            "FTS query for term in resolved range content returned no hits"
        )

        # Hydration stat is recorded in index_meta
        meta = dict(conn.execute("SELECT key, value FROM index_meta").fetchall())
        assert meta.get("ingest.fts_hydrated_from_range_ref") == "1"
    finally:
        conn.close()


def test_fts_content_hydrated_from_canonical_range_without_jsonschema(tmp_path, monkeypatch):
    """canonical_range hydration must not depend on jsonschema at index-build time."""
    dump_path, canonical_md, ref, expected_text = _make_range_ref_env(tmp_path)

    chunk_path = tmp_path / "chunks.jsonl"
    with chunk_path.open("w") as f:
        f.write(json.dumps({
            "chunk_id": "c_can",
            "repo_id": "testrepo",
            "path": "docs/section.md",
            "layer": "core",
            "canonical_range": ref,
            "content_range_ref": ref,
        }) + "\n")

    monkeypatch.setattr("merger.lenskit.core.range_resolver.jsonschema", None)

    db_path = tmp_path / "index.sqlite"
    index_db.build_index(dump_path, chunk_path, db_path)

    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT content FROM chunks_fts WHERE chunk_id = 'c_can'"
        ).fetchone()
        assert row is not None
        assert row[0] == expected_text

        meta = dict(conn.execute("SELECT key, value FROM index_meta").fetchall())
        assert meta.get("ingest.fts_hydrated_from_canonical_range") == "1"
        assert meta.get("ingest.fts_hydrated_from_range_ref") == "0"
    finally:
        conn.close()


def test_fts_content_hydration_hash_mismatch_raises(tmp_path):
    """A wrong content_sha256 in content_range_ref must cause a controlled failure."""
    dump_path, canonical_md, ref, _ = _make_range_ref_env(tmp_path)

    # Tamper the hash
    bad_ref = dict(ref)
    bad_ref["content_sha256"] = "a" * 64

    chunk_path = tmp_path / "chunks.jsonl"
    with chunk_path.open("w") as f:
        f.write(json.dumps({
            "chunk_id": "c_bad_hash",
            "repo_id": "testrepo",
            "path": "docs/section.md",
            "layer": "core",
            "content_range_ref": bad_ref,
        }) + "\n")

    db_path = tmp_path / "index.sqlite"
    with pytest.raises(RuntimeError, match="FTS hydration failed"):
        index_db.build_index(dump_path, chunk_path, db_path)
    assert not db_path.exists()


def test_fts_content_hydration_invalid_json_ref_raises(tmp_path):
    """A malformed JSON string in content_range_ref must fail index build."""
    dump_path = tmp_path / "dump.json"
    dump_path.write_text(json.dumps({
        "contract": "dump-index",
        "contract_version": "v1",
        "run_id": "test-run",
        "artifacts": {
            "canonical_md": {
                "role": "canonical_md",
                "path": "canonical.md",
            }
        }
    }))

    chunk_path = tmp_path / "chunks.jsonl"
    with chunk_path.open("w") as f:
        f.write(json.dumps({
            "chunk_id": "c_bad_json_ref",
            "repo_id": "testrepo",
            "path": "docs/section.md",
            "layer": "core",
            "content_range_ref": "{not-valid-json",
        }) + "\n")

    db_path = tmp_path / "index.sqlite"
    with pytest.raises(RuntimeError, match="invalid content_range_ref JSON"):
        index_db.build_index(dump_path, chunk_path, db_path)
    assert not db_path.exists()


def test_fts_content_hydration_missing_artifact_raises(tmp_path):
    """A content_range_ref pointing to a missing artifact file must fail index build."""
    dump_path, canonical_md, ref, _ = _make_range_ref_env(tmp_path)
    canonical_md.unlink()

    chunk_path = tmp_path / "chunks.jsonl"
    with chunk_path.open("w") as f:
        f.write(json.dumps({
            "chunk_id": "c_missing_artifact",
            "repo_id": "testrepo",
            "path": "docs/section.md",
            "layer": "core",
            "content_range_ref": ref,
        }) + "\n")

    db_path = tmp_path / "index.sqlite"
    with pytest.raises(RuntimeError, match="FTS hydration failed"):
        index_db.build_index(dump_path, chunk_path, db_path)
    assert not db_path.exists()


def test_fts_content_hydration_supports_list_artifacts_and_normalized_file_path(tmp_path):
    """Resolver accepts dump_index artifacts as list and tolerates ./ path differences."""
    import hashlib

    canonical_md = tmp_path / "canonical.md"
    content = b"hydrateduniquetokenxq7z from list artifacts\n"
    canonical_md.write_bytes(content)
    sha = hashlib.sha256(content).hexdigest()

    dump_path = tmp_path / "dump.json"
    dump_path.write_text(json.dumps({
        "contract": "dump-index",
        "contract_version": "v1",
        "run_id": "test-run",
        "artifacts": [
            {
                "role": "canonical_md",
                "path": "canonical.md",
            }
        ],
    }))

    ref = {
        "artifact_role": "canonical_md",
        "repo_id": "testrepo",
        "file_path": "./canonical.md",
        "start_byte": 0,
        "end_byte": len(content),
        "start_line": 1,
        "end_line": 1,
        "content_sha256": sha,
    }

    chunk_path = tmp_path / "chunks.jsonl"
    chunk_path.write_text(json.dumps({
        "chunk_id": "c_list_artifacts",
        "repo_id": "testrepo",
        "path": "docs/section.md",
        "layer": "core",
        "canonical_range": ref,
    }) + "\n")

    db_path = tmp_path / "index.sqlite"
    index_db.build_index(dump_path, chunk_path, db_path)

    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT content FROM chunks_fts WHERE chunk_id = 'c_list_artifacts'"
        ).fetchone()
        assert row is not None
        assert row[0] == content.decode("utf-8")
    finally:
        conn.close()


def test_fts_content_hydration_empty_range_raises(tmp_path):
    """A range where start_byte == end_byte must be rejected as semantically empty."""
    import hashlib

    canonical_md = tmp_path / "canonical.md"
    content = b"non-empty content line\n"
    canonical_md.write_bytes(content)

    # Construct a zero-length range (start == end)
    empty_sha = hashlib.sha256(b"").hexdigest()
    ref = {
        "artifact_role": "canonical_md",
        "repo_id": "testrepo",
        "file_path": canonical_md.name,
        "start_byte": 5,
        "end_byte": 5,
        "start_line": 1,
        "end_line": 1,
        "content_sha256": empty_sha,
    }

    dump_path = tmp_path / "dump.json"
    dump_path.write_text(json.dumps({
        "contract": "dump-index",
        "contract_version": "v1",
        "run_id": "test-run",
        "artifacts": {
            "canonical_md": {
                "role": "canonical_md",
                "path": canonical_md.name,
            }
        },
    }))

    chunk_path = tmp_path / "chunks.jsonl"
    chunk_path.write_text(json.dumps({
        "chunk_id": "c_empty_range",
        "repo_id": "testrepo",
        "path": "docs/section.md",
        "layer": "core",
        "canonical_range": ref,
    }) + "\n")

    db_path = tmp_path / "index.sqlite"
    with pytest.raises(RuntimeError, match="out of bounds"):
        index_db.build_index(dump_path, chunk_path, db_path)
    assert not db_path.exists()
