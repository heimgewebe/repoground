import sqlite3
import pytest

def test_sqlite_fts5_bm25_capability():
    """
    Smoke test to verify that the underlying SQLite installation supports FTS5 and the BM25 function.
    This is critical for retrieval features.
    """
    conn = sqlite3.connect(":memory:")
    try:
        c = conn.cursor()

        # 1. Check for FTS5 module availability
        try:
            c.execute("CREATE VIRTUAL TABLE t USING fts5(content)")
        except sqlite3.Error as e:
            if "no such module: fts5" in str(e):
                pytest.skip("SQLite FTS5 module not available")
            raise

        # 2. Insert dummy data
        c.execute("INSERT INTO t(content) VALUES ('hello world')")

        # 3. Check for BM25 function availability
        try:
            c.execute("SELECT bm25(t) FROM t WHERE t MATCH 'hello'")
            result = c.fetchone()[0]
        except sqlite3.Error as e:
            if "no such function: bm25" in str(e):
                pytest.skip("SQLite BM25 function not available")
            raise

        # 4. Verify result type
        assert isinstance(result, (int, float)), f"Expected numeric BM25 score, got {type(result)}"

    finally:
        conn.close()
