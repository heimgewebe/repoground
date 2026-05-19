import sqlite3
from merger.lenskit.retrieval import query_core

def test_query_ignores_missing_source_file_column(tmp_path):
    """
    Simulates querying an older index that does not have the 'source_file' column.
    Ensures query_core safely ignores the missing column and does not crash or emit
    a fake derived_range_ref.
    """
    db_path = tmp_path / "old_index.sqlite"
    conn = sqlite3.connect(str(db_path))

    # Old schema without 'source_file'
    conn.execute("""
        CREATE TABLE chunks (
            chunk_id TEXT PRIMARY KEY,
            repo_id TEXT,
            path TEXT,
            start_line INTEGER,
            end_line INTEGER,
            start_byte INTEGER,
            end_byte INTEGER,
            content_sha256 TEXT,
            layer TEXT,
            artifact_type TEXT,
            content_range_ref TEXT
        )
    """)
    conn.execute("""
        CREATE VIRTUAL TABLE chunks_fts USING fts5(
            chunk_id UNINDEXED,
            content,
            path_tokens
        )
    """)

    # Insert old data
    conn.execute("""
        INSERT INTO chunks (chunk_id, repo_id, path, start_line, end_line, start_byte, end_byte, content_sha256, layer, artifact_type, content_range_ref)
        VALUES ('c1', 'r1', 'src/main.py', 1, 1, 0, 10, 'h1', 'core', 'code', NULL)
    """)
    conn.execute("INSERT INTO chunks_fts (chunk_id, content) VALUES ('c1', 'def main(): pass')")
    conn.commit()
    conn.close()

    # Execute query
    res = query_core.execute_query(db_path, query_text="def", k=1)

    assert res["count"] == 1
    hit = res["results"][0]

    # Should safely complete without range_refs
    assert "range_ref" not in hit
    assert "derived_range_ref" not in hit
