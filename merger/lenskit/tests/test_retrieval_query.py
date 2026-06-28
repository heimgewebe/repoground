import json
import sqlite3
import pytest
from merger.lenskit.retrieval import index_db
from merger.lenskit.retrieval import query_core

@pytest.fixture
def mini_index(tmp_path):
    # Setup paths
    dump_path = tmp_path / "dump.json"
    chunk_path = tmp_path / "chunks.jsonl"
    db_path = tmp_path / "index.sqlite"

    # Write chunks
    chunk_data = [
        {"chunk_id": "c1", "repo_id": "r1", "path": "src/main.py", "content": "def main(): print('hello world')", "start_line": 1, "end_line": 1, "layer": "core", "artifact_type": "code", "content_sha256": "h1"},
        {"chunk_id": "c2", "repo_id": "r1", "path": "tests/test_main.py", "content": "def test_main(): assert True", "start_line": 1, "end_line": 1, "layer": "test", "artifact_type": "code", "content_sha256": "h2"},
        {"chunk_id": "c3", "repo_id": "r1", "path": "docs/readme.md", "content": "# Readme\nThis is a doc.", "start_line": 1, "end_line": 2, "layer": "docs", "artifact_type": "doc", "content_sha256": "h3"},
    ]
    with chunk_path.open("w", encoding="utf-8") as f:
        for c in chunk_data:
            f.write(json.dumps(c) + "\n")

    dump_path.write_text(json.dumps({"dummy": "data"}), encoding="utf-8")

    index_db.build_index(dump_path, chunk_path, db_path)

    return db_path

def test_query_metadata_filter(mini_index):
    # Filter by layer
    res = query_core.execute_query(mini_index, query_text="", k=10, filters={"layer": "core"})
    assert res["count"] == 1
    assert res["results"][0]["chunk_id"] == "c1"

    # Filter by path substring
    res = query_core.execute_query(mini_index, query_text="", k=10, filters={"path": "test"})
    assert res["count"] == 1
    assert res["results"][0]["chunk_id"] == "c2"

    # Filter by extension
    res = query_core.execute_query(mini_index, query_text="", k=10, filters={"ext": "md"})
    assert res["count"] == 1
    assert res["results"][0]["chunk_id"] == "c3"

def test_query_fts_simple(mini_index):
    # FTS Search
    res = query_core.execute_query(mini_index, query_text="hello", k=10)
    assert res["count"] == 1
    assert res["results"][0]["chunk_id"] == "c1"

    # FTS Search no match
    res = query_core.execute_query(mini_index, query_text="zebra", k=10)
    assert res["count"] == 0

def test_query_fts_combined_filter(mini_index):
    # Match text but filter out by layer
    res = query_core.execute_query(mini_index, query_text="def", k=10, filters={"layer": "test"})
    # "def" is in both c1 (core) and c2 (test), should only find c2
    assert res["count"] == 1
    assert res["results"][0]["chunk_id"] == "c2"

def test_query_json_structure(mini_index):
    import jsonschema
    from pathlib import Path

    res = query_core.execute_query(mini_index, query_text="main", k=5, filters={"layer": "core"})
    assert "query" in res
    assert "k" in res
    assert "results" in res
    assert "engine" in res
    assert res["engine"] == "fts5"
    assert len(res["results"]) == 1

    schema_path = Path(__file__).parent.parent / "contracts" / "query-result.v1.schema.json"
    with schema_path.open("r", encoding="utf-8") as f:
        schema = json.load(f)
    jsonschema.validate(instance=res, schema=schema)

    hit = res["results"][0]
    assert "chunk_id" in hit
    assert "range" in hit
    assert "score" in hit
    assert "why" in hit
    assert "matched_terms" in hit["why"]
    assert "filter_pass" in hit["why"]
    assert "rank_features" in hit["why"]
    assert hit["why"]["matched_terms"] == ["main"]
    assert hit["why"]["filter_pass"] == ["layer"]
    assert "bm25" in hit["why"]["rank_features"]

    # Explicit range_ref should only exist if explicitly stored (it's not here)
    assert "range_ref" not in hit

    # Because `mini_index` uses chunks without genuine byte ranges, the DB defaults to start_byte=0, end_byte=0.
    # Since end_byte is not > start_byte, the query_core logic correctly refuses to emit derived_range_ref.
    assert "derived_range_ref" not in hit

    res2 = query_core.execute_query(mini_index, query_text="test_main", k=5)
    assert len(res2["results"]) == 1
    assert "range_ref" not in res2["results"][0]
    assert "derived_range_ref" not in res2["results"][0]

    res3 = query_core.execute_query(mini_index, query_text="Readme", k=5)
    assert len(res3["results"]) == 1
    assert "range_ref" not in res3["results"][0]
    assert "derived_range_ref" not in res3["results"][0]

def test_query_schema_allows_low_result_coverage_warning(mini_index):
    import jsonschema
    from pathlib import Path

    res = query_core.execute_query(mini_index, query_text="hello", k=5)

    assert "warnings" in res
    assert "Low result coverage" in res["warnings"]

    schema_path = Path(__file__).parent.parent / "contracts" / "query-result.v1.schema.json"
    with schema_path.open("r", encoding="utf-8") as f:
        schema = json.load(f)
    jsonschema.validate(instance=res, schema=schema)

def test_citation_resolve_prefers_v2(tmp_path):
    from merger.lenskit.retrieval import index_db
    import json

    db_path = tmp_path / "index.sqlite"
    dump_path = tmp_path / "dump.json"
    chunk_path = tmp_path / "chunks.jsonl"

    full_hash = "1" * 64
    range_hash = "2" * 64

    ref_obj = {
        "range_ref_version": "2",
        "artifact_role": "canonical_md",
        "repo_id": "r1",
        "artifact_path": "merged.md",
        "artifact_byte_start": 0,
        "artifact_byte_end": 10,
        "artifact_line_start": 1,
        "artifact_line_end": 1,
        "source_file_path": "src/main.py",
        "source_line_start": 1,
        "source_line_end": 1,
        "content_sha256": full_hash,
        "range_content_sha256": range_hash,
        "file_path": "merged.md",
        "start_byte": 0,
        "end_byte": 10,
        "start_line": 1,
        "end_line": 1,
    }

    chunk_data = [
        {
            "chunk_id": "c1", "repo_id": "r1", "path": "src/main.py", "content": "def main(): print('hello')",
            "start_line": 1, "end_line": 1, "layer": "core", "artifact_type": "code", "content_sha256": "h1",
            "content_range_ref": ref_obj,
            "start_byte": 0, "end_byte": 10, "source_file": "src/main.py"
        }
    ]
    with chunk_path.open("w", encoding="utf-8") as f:
        for c in chunk_data:
            f.write(json.dumps(c) + "\n")

    dump_path.write_text(json.dumps({"dummy": "data"}))
    index_db.build_index(dump_path, chunk_path, db_path)

    res = query_core.execute_query(db_path, query_text="hello", k=1)
    hit = res["results"][0]

    assert "range_ref" in hit
    assert hit["range_ref"]["range_ref_version"] == "2"
    assert hit["range_ref"]["artifact_path"] == "merged.md"
    assert hit["range_ref"]["source_file_path"] == "src/main.py"
    assert hit["range_ref"]["content_sha256"] == full_hash
    assert hit["range_ref"]["range_content_sha256"] == range_hash

def test_query_semantic_markers(mini_index):
    policy = {
        "model_name": "test-model",
        "provider": "api",
        "fallback_behavior": "ignore",
        "similarity_metric": "cosine",
        "dimensions": 128
    }

    res = query_core.execute_query(mini_index, query_text="def", k=2, embedding_policy=policy)

    assert res["engine"] == "fts5+semantic_requested"
    assert res["count"] == 2 # Should find c1 and c2

    # Check diagnostic markers
    hit = res["results"][0]
    assert "diagnostics" in hit["why"]
    semantic_diag = hit["why"]["diagnostics"]["semantic"]
    assert semantic_diag["enabled"] is False
    assert semantic_diag["fallback_behavior"] == "ignore"
    assert "not implemented" in semantic_diag["error"]
    assert semantic_diag["candidate_k"] == 50  # Overfetch logic triggers
    assert semantic_diag["provider"] == "api"
    assert semantic_diag["model_name"] == "test-model"

def test_query_explain(mini_index):
    res = query_core.execute_query(mini_index, query_text="hello", k=10, explain=True)
    assert "explain" in res
    explain = res["explain"]
    assert "fts_query" in explain
    assert explain["fts_query"] == "hello"
    assert "top_k_scoring" in explain
    assert len(explain["top_k_scoring"]) == 1
    assert explain["top_k_scoring"][0]["chunk_id"] == "c1"

def test_query_explain_zero_hits(mini_index):
    res = query_core.execute_query(mini_index, query_text="zebra", k=10, filters={"layer": "core"}, explain=True)
    assert "explain" in res
    explain = res["explain"]
    assert "fts_query" in explain
    assert explain["filters"]["layer"] == "core"
    assert "why_zero" in explain
    assert explain["why_zero"] == query_core.WHY_ZERO_TOKENS

def test_query_semantic_fallback_fail(mini_index):
    policy = {
        "model_name": "test-model",
        "provider": "api",
        "fallback_behavior": "fail",
        "similarity_metric": "cosine",
        "dimensions": 128
    }

    with pytest.raises(RuntimeError) as excinfo:
        query_core.execute_query(mini_index, query_text="def", k=2, embedding_policy=policy)

    assert "Semantic re-ranking provider 'api' is not yet implemented (fallback_behavior=fail)" in str(excinfo.value)


def _make_mock_conn(err_msg: str):
    class MockConn:
        row_factory = None
        def execute(self, sql, params=()):
            raise sqlite3.Error(err_msg)
        def close(self):
            pass
    return MockConn()

def test_query_no_fts_module_handling(mini_index, monkeypatch):
    monkeypatch.setattr(query_core.sqlite3, "connect", lambda x: _make_mock_conn("no such module: fts5"))

    with pytest.raises(RuntimeError) as excinfo:
        query_core.execute_query(mini_index, query_text="foo", k=10)

    assert "SQLite FTS5 extension missing" in str(excinfo.value)

def test_query_no_fts_table_handling(mini_index, monkeypatch):
    monkeypatch.setattr(query_core.sqlite3, "connect", lambda x: _make_mock_conn("no such table: chunks_fts"))

    with pytest.raises(RuntimeError) as excinfo:
        query_core.execute_query(mini_index, query_text="foo", k=10)

    assert "FTS table missing; likely old or corrupt index" in str(excinfo.value)

def test_query_no_bm25_function_handling(mini_index, monkeypatch):
    monkeypatch.setattr(query_core.sqlite3, "connect", lambda x: _make_mock_conn("no such function: bm25"))

    with pytest.raises(RuntimeError) as excinfo:
        query_core.execute_query(mini_index, query_text="foo", k=10)

    assert "SQLite FTS5 auxiliary function 'bm25' missing" in str(excinfo.value)

def test_query_unable_to_use_bm25_handling(mini_index, monkeypatch):
    monkeypatch.setattr(query_core.sqlite3, "connect", lambda x: _make_mock_conn("unable to use function bm25"))

    with pytest.raises(RuntimeError) as excinfo:
        query_core.execute_query(mini_index, query_text="foo", k=10)

    assert "SQLite FTS5 auxiliary function 'bm25' missing" in str(excinfo.value)

def test_explain_json_stable_order(mini_index):
    """
    Golden Test: Ensure Explain JSON output has a stable prefix order (fts_query, filters) and required keys present.
    Dictionaries in Python 3.7+ maintain insertion order. We enforce the required schema fields
    to ensure the output matches expected 'Golden' prefix ordering.
    """
    res = query_core.execute_query(
        index_path=mini_index,
        query_text="hello",
        k=5,
        filters={"layer": "core"},
        explain=True
    )

    assert "explain" in res
    explain = res["explain"]

    actual_keys = list(explain.keys())

    assert actual_keys[:2] == ["fts_query", "filters"], f"Prefix order mismatch: {actual_keys[:2]} != ['fts_query', 'filters']"
    assert "top_k_scoring" in actual_keys, "Missing 'top_k_scoring'"

    # For zero results
    res_zero = query_core.execute_query(
        index_path=mini_index,
        query_text="zebra",
        k=5,
        filters={"layer": "core"},
        explain=True
    )

    explain_zero = res_zero["explain"]
    actual_zero_keys = list(explain_zero.keys())

    assert actual_zero_keys[:2] == ["fts_query", "filters"], f"Prefix order mismatch: {actual_zero_keys[:2]} != ['fts_query', 'filters']"
    assert "why_zero" in actual_zero_keys, "Missing 'why_zero'"

def test_cmd_query_json_emit(mini_index, capsys):
    from merger.lenskit.cli import cmd_query
    import argparse

    args = argparse.Namespace(
        index=str(mini_index),
        q="hello",
        k=10,
        repo=None, path=None, ext=None, layer=None, artifact_type=None,
        emit="json",
        stale_policy="ignore",
        embedding_policy=None,
        explain=True,
        graph_index=None,
        graph_weights=None,
        test_penalty=0.75
    )
    ret = cmd_query.run_query(args)
    assert ret == 0
    captured = capsys.readouterr()
    assert captured.err == "", f"Expected empty stderr, got: {captured.err}"
    parsed = json.loads(captured.out)
    assert isinstance(parsed, dict)
    assert "results" in parsed
    assert "explain" in parsed

def test_query_semantic_reranking(mini_index, monkeypatch):
    # Create a mock semantic model that produces deterministic vectors
    class MockSemanticModel:
        def encode(self, texts):
            # If input is string, make it list-like for uniform processing
            is_single = isinstance(texts, str)
            if is_single:
                texts = [texts]

            embeddings = []
            for t in texts:
                t = t.lower()
                # Determine mock vectors based on content to force order
                if "test_main" in t:
                    embeddings.append([1.0, 0.0])
                elif "print" in t:
                    embeddings.append([0.0, 1.0])
                elif t == "def":
                    # query returns [1.0, 0.0], matching test_main best
                    embeddings.append([1.0, 0.0])
                else:
                    embeddings.append([0.5, 0.5])

            return embeddings[0] if is_single else embeddings

    def mock_get_semantic_model(name):
        return MockSemanticModel()

    monkeypatch.setattr("merger.lenskit.retrieval.query_core._get_semantic_model", mock_get_semantic_model)

    policy = {
        "model_name": "mock-model",
        "provider": "local",
        "fallback_behavior": "fail",
        "similarity_metric": "cosine",
        "dimensions": 2
    }

    # Baseline: both matches have 'def'. The SQLite query will return them in DB order.
    res_base = query_core.execute_query(mini_index, query_text="def", k=2, explain=True)
    assert res_base["count"] == 2
    base_order = [h["path"] for h in res_base["results"]]

    # We query "def", which matches both chunks lexically.
    # The mock semantic model encodes "def" as [1.0, 0.0].
    # It encodes the content of "tests/test_main.py" (containing "test_main") as [1.0, 0.0].
    # It encodes the content of "src/main.py" (containing "print") as [0.0, 1.0].
    # This forces the semantic similarity to be 1.0 for test_main and 0.0 for main,
    # effectively reranking test_main to the top regardless of baseline DB tie-breaking.

    res_sem = query_core.execute_query(mini_index, query_text="def", k=2, embedding_policy=policy, explain=True)

    assert res_sem["count"] == 2
    sem_order = [h["path"] for h in res_sem["results"]]
    top_hit = res_sem["results"][0]
    second_hit = res_sem["results"][1]

    # Explicitly assert that the semantic reranking altered the order compared to baseline.
    assert base_order != sem_order, "Semantic reranking failed to change the baseline FTS DB order."

    # Assert deterministic ranking outcome
    assert top_hit["path"] == "tests/test_main.py"
    assert second_hit["path"] == "src/main.py"

    # Assert presence of required metrics in explain/why block
    assert "semantic_score" in top_hit["why"]["rank_features"]
    assert "original_bm25" in top_hit["why"]["rank_features"]

    # Assert semantic score logic is correctly calculated by the mock fallback
    assert top_hit["why"]["rank_features"]["semantic_score"] > second_hit["why"]["rank_features"]["semantic_score"]


def test_query_explain_graph_fields_match_scoring(mini_index, tmp_path, monkeypatch):
    graph_index_path = tmp_path / "graph_index.json"
    graph_index = {
        "distances": {"file:tests/test_main.py": 0, "file:src/main.py": 1}
    }
    graph_index_path.write_text(json.dumps(graph_index), encoding="utf-8")

    def mock_load(path, expected_sha256=None):
        return {"status": "ok", "graph": graph_index}

    monkeypatch.setattr(query_core, "load_graph_index", mock_load)

    res = query_core.execute_query(mini_index, query_text="def", k=2, explain=True, graph_index_path=graph_index_path)


    assert "results" in res
    assert len(res["results"]) > 0

    hit = [r for r in res["results"] if r["path"] == "tests/test_main.py"][0]

    assert "diagnostics" in hit["why"] and "graph" in hit["why"]["diagnostics"]
    ge = hit["why"]["diagnostics"]["graph"]

    assert ge["graph_used"] is True
    assert ge["graph_status"] == "ok"
    assert ge["node_id"] == "file:tests/test_main.py"
    assert ge["distance"] == 0

    # Contract proof
    import jsonschema
    from pathlib import Path
    schema_path = Path(__file__).parent.parent / "contracts" / "query-result.v1.schema.json"
    with schema_path.open("r", encoding="utf-8") as f2:
        schema = json.load(f2)
    jsonschema.validate(instance=res, schema=schema)

    # Check that score pre calculation aligns with graph_bonus
    # final_score = (bm25_norm * w_b) + graph_bonus (and test penalty applied if it's test)
    rf = hit["why"]["rank_features"]

    w_b = 0.65
    raw_graph_bonus = (0.20 * 1.0) + (0.15 * 1.0) # distance 0 => prox 1.0, entry 1.0
    cap = 0.20 + 0.15
    graph_bonus = min(raw_graph_bonus, cap)

    assert ge["graph_bonus"] == graph_bonus

    expected_score_pre = (w_b * rf["bm25_norm"]) + graph_bonus
    expected_final_score = expected_score_pre * 0.75 # test_penalty is 0.75

    # allow minor float drift
    assert abs(hit["final_score"] - expected_final_score) < 1e-5

def test_graph_bonus_is_bounded(mini_index, tmp_path, monkeypatch):
    graph_index_path = tmp_path / "graph_index.json"
    graph_index = {
        "distances": {"file:src/main.py": 0}
    }
    graph_index_path.write_text(json.dumps(graph_index), encoding="utf-8")

    def mock_load(path, expected_sha256=None):
        return {"status": "ok", "graph": graph_index}

    monkeypatch.setattr(query_core, "load_graph_index", mock_load)

    # Change weights so raw_graph_bonus exceeds cap naturally if cap is independent,
    # but the cap is currently w_g + w_e. We'll verify it doesn't exceed cap.
    weights = {"w_bm25": 0.5, "w_graph": 2.0, "w_entry": 1.0}

    res = query_core.execute_query(mini_index, query_text="def", k=2, explain=True, graph_index_path=graph_index_path, graph_weights=weights)

    hits = [r for r in res["results"] if r["path"] == "src/main.py"]
    assert len(hits) == 1, "Expected exactly 1 hit for src/main.py"
    hit = hits[0]
    ge = hit["why"]["diagnostics"]["graph"]

    # cap = w_graph + w_entry = 3.0
    # At dist=0, prox=1, boost=1 => raw = 3.0. Bounded to 3.0.
    assert abs(ge["graph_bonus"] - 3.0) < 1e-5

    # What if distance > 0?
    graph_index["distances"]["file:src/main.py"] = 1
    res2 = query_core.execute_query(mini_index, query_text="def", k=2, explain=True, graph_index_path=graph_index_path, graph_weights=weights)
    hit2 = [r for r in res2["results"] if r["path"] == "src/main.py"][0]
    ge2 = hit2["why"]["diagnostics"]["graph"]
    # At dist=1 => prox=0.5, boost=0 => raw = 2.0 * 0.5 = 1.0
    assert abs(ge2["graph_bonus"] - 1.0) < 1e-5


def test_graph_staleness_marker(mini_index, tmp_path, monkeypatch):
    graph_index_path = tmp_path / "graph_index.json"
    graph_index = {
        "distances": {"file:src/main.py": 0}
    }
    graph_index_path.write_text(json.dumps(graph_index), encoding="utf-8")

    captured = {}

    def mock_load(path, expected_sha256=None):
        captured["expected_sha256"] = expected_sha256
        return {"status": "stale_or_mismatched", "graph": graph_index}

    monkeypatch.setattr(query_core, "load_graph_index", mock_load)

    # Test legacy fallback query using monkeypatched db_conn inside _read_expected_graph_sha256 implicitly by modifying the DB
    import sqlite3
    conn = sqlite3.connect(mini_index)
    conn.execute("DELETE FROM index_meta WHERE key='canonical_dump_index_sha256'")
    conn.execute("INSERT INTO index_meta (key, value) VALUES ('dump_sha256', 'legacy_sha')")
    conn.commit()
    conn.close()

    res = query_core.execute_query(mini_index, query_text="def", k=2, explain=True, graph_index_path=graph_index_path)


    hits = [r for r in res["results"] if r["path"] == "src/main.py"]
    assert len(hits) == 1, "Expected exactly 1 hit for src/main.py"
    hit = hits[0]
    ge = hit["why"]["diagnostics"]["graph"]

    assert ge["graph_used"] is False
    assert ge["graph_status"] == "stale_or_mismatched"
    assert ge["distance"] == -1
    assert ge["graph_bonus"] == 0.0
    assert "graph_index" not in res["claim_boundaries"]["evidence_basis"]

    # Direct proof that _read_expected_graph_sha256 extracted the legacy fallback and passed it to the mock
    assert captured.get("expected_sha256") == "legacy_sha"

def test_query_trace_contains_runtime_markers(mini_index):
    policy = {
        "model_name": "test-model",
        "provider": "api",
        "fallback_behavior": "ignore",
        "similarity_metric": "cosine",
        "dimensions": 128
    }

    res = query_core.execute_query(mini_index, query_text="hello", k=10, embedding_policy=policy, trace=True)
    assert "query_trace" in res

    trace = res["query_trace"]
    assert "timings" in trace
    assert "start" in trace["timings"]
    assert "end" in trace["timings"]
    assert "parse_validate_start" in trace["timings"]
    assert "parse_validate_end" in trace["timings"]
    assert "candidate_retrieval_start" in trace["timings"]
    assert "candidate_retrieval_end" in trace["timings"]
    assert "rerank_start" in trace["timings"] if policy else True
    assert "rerank_end" in trace["timings"] if policy else True

    assert "semantic_status" in trace
    assert trace["semantic_status"] == "unsupported_provider"

    assert "fallback_markers" in trace
    assert "semantic_fallback_unsupported_provider" in trace["fallback_markers"]

    assert "candidate_count" in trace
    assert "chosen_hits" in trace
    assert len(trace["chosen_hits"]) > 0

def test_query_json_structure_trace(mini_index):
    import jsonschema
    from pathlib import Path

    res = query_core.execute_query(mini_index, query_text="main", k=5, filters={"layer": "core"}, trace=True)
    assert "query_trace" in res

    # Ensure no rerank markers are present when semantic reranking / graph index are missing
    trace = res["query_trace"]
    assert "rerank_start" not in trace["timings"]
    assert "rerank_end" not in trace["timings"]

    schema_path = Path(__file__).parent.parent / "contracts" / "query-result.v1.schema.json"
    with schema_path.open("r", encoding="utf-8") as f:
        schema = json.load(f)
    jsonschema.validate(instance=res, schema=schema)

def test_graph_staleness_e2e_hash_mismatch(mini_index, tmp_path):
    """
    Proves that a real graph index loaded with an invalid canonical dump SHA
    produces the 'stale_or_mismatched' status through the entire query pipeline
    without using any mocks or monkeypatches.

    This explicitly proves causality: the mismatch of actual vs expected SHA
    triggers the stale status, not an invalid schema or missing file.
    """
    import json
    import sqlite3

    import re
    # We need to know the expected SHA that query_core will read from the DB
    conn = sqlite3.connect(mini_index)
    cursor = conn.execute("SELECT value FROM index_meta WHERE key='canonical_dump_index_sha256'")
    row = cursor.fetchone()
    conn.close()

    # Causality hardening: We must guarantee the DB actually holds a valid 64-hex SHA
    # before we prove that a mismatch causes the stale status. Otherwise, a missing row
    # could cause a silent fallback passing the test for the wrong reasons.
    assert row is not None, "canonical_dump_index_sha256 must exist in index_meta for this E2E mismatch test"
    expected_sha = row[0]
    assert re.fullmatch(r"[a-f0-9]{64}", expected_sha), "Expected DB SHA must match pattern ^[a-f0-9]{64}$"


    # 1. Erzeuge echten Graph-Index
    graph_index_path = tmp_path / "graph_index.json"

    # 2. Erzeuge absichtlich falschen expected_sha
    actual_sha_in_graph = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef"

    # 3. Explicitly prove causality requirements
    assert len(actual_sha_in_graph) == 64, "Actual SHA must pass schema pattern ^[a-f0-9]{64}$"
    assert actual_sha_in_graph != expected_sha, "Sanity check failed: Hashes accidentally matched"

    graph_index = {
        "kind": "lenskit.architecture.graph_index",
        "version": "1.0",
        "run_id": "test_stale_run",
        "canonical_dump_index_sha256": actual_sha_in_graph,
        "distances": {"file:src/main.py": 0},
        "metrics": {"entrypoint_count": 1, "nodes_reachable": 1, "unreachable_nodes": 0}
    }
    graph_index_path.write_text(json.dumps(graph_index), encoding="utf-8")

    # 4. Führe echte Query-Pipeline aus
    from merger.lenskit.retrieval import query_core
    res = query_core.execute_query(mini_index, query_text="def", k=2, explain=True, graph_index_path=graph_index_path)

    # 5. Assertions
    hits = [r for r in res["results"] if r["path"] == "src/main.py"]
    assert len(hits) == 1, "Expected exactly 1 hit for src/main.py"
    hit = hits[0]

    diagnostics = hit["why"]["diagnostics"]["graph"]
    graph_status = diagnostics["graph_status"]

    # Proves the state didn't fall back to other errors
    assert graph_status != "invalid_schema"
    assert graph_status != "not_found"
    assert graph_status != "unreadable"
    assert graph_status != "invalid_json"

    # Proves the exact causality
    assert graph_status == "stale_or_mismatched", f"Expected stale_or_mismatched but got {graph_status}"

    # Pipeline-Check confirmation implicitly given:
    # No monkeypatch was used on query_core or load_graph_index in this test.
    # The actual graph_index JSON was written to disk and loaded natively.


def test_query_ignores_stale_graph_runtime_path(mini_index, tmp_path):
    """
    Proves that a hash-mismatched graph remains diagnostic only and cannot
    contribute distance, bonus, penalty, or graph evidence to ranking.
    """
    import json
    import sqlite3
    import re

    conn = sqlite3.connect(mini_index)
    cursor = conn.execute("SELECT value FROM index_meta WHERE key='canonical_dump_index_sha256'")
    row = cursor.fetchone()
    conn.close()

    # Causality hardening: The test premise requires a valid canonical DB SHA
    assert row is not None, "canonical_dump_index_sha256 must exist in index_meta for this E2E mismatch test"
    expected_sha = row[0]
    assert re.fullmatch(r"[a-f0-9]{64}", expected_sha), "Expected DB SHA must match pattern ^[a-f0-9]{64}$"


    graph_index_path = tmp_path / "graph_index.json"
    actual_sha_in_graph = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef"

    # Pre-condition checks: Causality guarantees
    assert actual_sha_in_graph != expected_sha
    assert len(actual_sha_in_graph) == 64

    graph_index = {
        "kind": "lenskit.architecture.graph_index",
        "version": "1.0",
        "run_id": "test_stale_run",
        "canonical_dump_index_sha256": actual_sha_in_graph,
        "distances": {"file:src/main.py": 0},
        "metrics": {"entrypoint_count": 1, "nodes_reachable": 1, "unreachable_nodes": 0}
    }
    graph_index_path.write_text(json.dumps(graph_index), encoding="utf-8")

    from merger.lenskit.retrieval import query_core
    res = query_core.execute_query(mini_index, query_text="def", k=2, explain=True, graph_index_path=graph_index_path)

    hits = [r for r in res["results"] if r["path"] == "src/main.py"]
    assert len(hits) == 1, "Expected exactly 1 hit for src/main.py"
    hit = hits[0]

    diagnostics = hit["why"]["diagnostics"]["graph"]

    assert diagnostics["graph_status"] == "stale_or_mismatched"
    assert diagnostics["graph_used"] is False
    assert diagnostics["distance"] == -1
    assert diagnostics["graph_bonus"] == 0.0
    assert "graph_index" not in res["claim_boundaries"]["evidence_basis"]
    assert res["claim_boundaries"]["requires_live_check"] is True


# ---------------------------------------------------------------------------
# Claim Boundaries
# ---------------------------------------------------------------------------

def test_claim_boundaries_present(mini_index):
    import jsonschema
    from pathlib import Path

    res = query_core.execute_query(mini_index, query_text="hello", k=5)
    assert "claim_boundaries" in res
    cb = res["claim_boundaries"]
    assert isinstance(cb["proves"], list)
    assert isinstance(cb["does_not_prove"], list)
    assert isinstance(cb["evidence_basis"], list)
    assert isinstance(cb["requires_live_check"], bool)

    schema_path = Path(__file__).parent.parent / "contracts" / "query-result.v1.schema.json"
    with schema_path.open("r", encoding="utf-8") as f:
        schema = json.load(f)
    jsonschema.validate(instance=res, schema=schema)


def test_claim_boundaries_content(mini_index):
    res = query_core.execute_query(mini_index, query_text="hello", k=5)
    cb = res["claim_boundaries"]

    absence_stmt = "Absence of a hit does not prove absence in the repository."
    ranking_stmt = "Ranking does not prove semantic importance."
    snapshot_stmt = "Snapshot query does not prove live repository state."

    assert any(absence_stmt in s for s in cb["does_not_prove"]), "Missing absence disclaimer"
    assert any(ranking_stmt in s for s in cb["does_not_prove"]), "Missing ranking disclaimer"
    assert any(snapshot_stmt in s for s in cb["does_not_prove"]), "Missing snapshot disclaimer"

    assert cb["requires_live_check"] is True
    assert "query" in cb["evidence_basis"]
    assert "applied_filters" in cb["evidence_basis"]
    assert "index" in cb["evidence_basis"]


def test_claim_boundaries_fts_query_evidence(mini_index):
    res = query_core.execute_query(mini_index, query_text="hello", k=5)
    cb = res["claim_boundaries"]
    assert "fts_query" in cb["evidence_basis"], "FTS query should appear in evidence_basis when fts_query is active"


def test_claim_boundaries_no_fts_evidence_for_metadata_only(mini_index):
    res = query_core.execute_query(mini_index, query_text="", k=5, filters={"layer": "core"})
    cb = res["claim_boundaries"]
    assert "fts_query" not in cb["evidence_basis"], "fts_query should not appear in evidence_basis for metadata-only queries"


def test_claim_boundaries_result_ranges_evidence_when_present(tmp_path):
    from merger.lenskit.retrieval import index_db

    db_path = tmp_path / "index.sqlite"
    dump_path = tmp_path / "dump.json"
    chunk_path = tmp_path / "chunks.jsonl"

    ref_obj = {
        "artifact_role": "canonical_md",
        "repo_id": "r1",
        "file_path": "merged.md",
        "start_byte": 0,
        "end_byte": 10,
        "start_line": 1,
        "end_line": 1,
        "content_sha256": "h1"
    }

    chunk_data = [
        {
            "chunk_id": "c1", "repo_id": "r1", "path": "src/main.py", "content": "def main(): print('hello')",
            "start_line": 1, "end_line": 1, "layer": "core", "artifact_type": "code", "content_sha256": "h1",
            "content_range_ref": ref_obj,
            "start_byte": 0, "end_byte": 10, "source_file": "src/main.py"
        }
    ]
    with chunk_path.open("w", encoding="utf-8") as f:
        for c in chunk_data:
            f.write(json.dumps(c) + "\n")
    dump_path.write_text(json.dumps({"dummy": "data"}), encoding="utf-8")
    index_db.build_index(dump_path, chunk_path, db_path)

    res = query_core.execute_query(db_path, query_text="hello", k=1)
    assert "result_ranges" in res["claim_boundaries"]["evidence_basis"]


def test_claim_boundaries_result_ranges_evidence_absent_when_no_range_refs(mini_index):
    res = query_core.execute_query(mini_index, query_text="hello", k=5)
    assert "result_ranges" not in res["claim_boundaries"]["evidence_basis"]

    zero = query_core.execute_query(mini_index, query_text="zebra", k=5)
    assert zero["count"] == 0
    assert "result_ranges" not in zero["claim_boundaries"]["evidence_basis"]


def test_claim_boundaries_graph_index_evidence_when_graph_used(mini_index, tmp_path, monkeypatch):
    graph_index_path = tmp_path / "graph_index.json"
    graph_index = {
        "distances": {
            "file:tests/test_main.py": 0,
            "file:src/main.py": 1
        }
    }
    graph_index_path.write_text(json.dumps(graph_index), encoding="utf-8")

    def mock_load(path, expected_sha256=None):
        return {"status": "ok", "graph": graph_index}

    monkeypatch.setattr(query_core, "load_graph_index", mock_load)

    res = query_core.execute_query(
        mini_index,
        query_text="def",
        k=2,
        explain=True,
        graph_index_path=graph_index_path,
    )

    assert "graph_index" in res["claim_boundaries"]["evidence_basis"]


def test_claim_boundaries_no_graph_index_evidence_when_graph_not_used(mini_index, tmp_path, monkeypatch):
    graph_index_path = tmp_path / "graph_index.json"
    graph_index_path.write_text("{}", encoding="utf-8")

    def mock_load(path, expected_sha256=None):
        return {"status": "invalid_schema", "graph": None}

    monkeypatch.setattr(query_core, "load_graph_index", mock_load)

    res = query_core.execute_query(
        mini_index,
        query_text="def",
        k=2,
        explain=True,
        graph_index_path=graph_index_path,
    )

    assert "graph_index" not in res["claim_boundaries"]["evidence_basis"]


def test_claim_boundaries_schema_rejects_unknown_evidence(mini_index):
    import jsonschema
    from pathlib import Path

    schema_path = Path(__file__).parent.parent / "contracts" / "query-result.v1.schema.json"
    with schema_path.open("r", encoding="utf-8") as f:
        schema = json.load(f)

    invalid = {
        "query": "x", "k": 1, "engine": "fts5", "query_mode": "fts",
        "applied_filters": {}, "count": 0, "results": [],
        "claim_boundaries": {
            "proves": [],
            "does_not_prove": [],
            "evidence_basis": ["not_a_valid_source"],
            "requires_live_check": False
        }
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=invalid, schema=schema)


def test_claim_boundaries_schema_rejects_extra_field(mini_index):
    import jsonschema
    from pathlib import Path

    schema_path = Path(__file__).parent.parent / "contracts" / "query-result.v1.schema.json"
    with schema_path.open("r", encoding="utf-8") as f:
        schema = json.load(f)

    invalid = {
        "query": "x", "k": 1, "engine": "fts5", "query_mode": "fts",
        "applied_filters": {}, "count": 0, "results": [],
        "claim_boundaries": {
            "proves": [],
            "does_not_prove": [],
            "evidence_basis": ["query"],
            "requires_live_check": False,
            "unexpected_extra_field": True
        }
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=invalid, schema=schema)


def test_claim_boundaries_schema_rejects_missing_required_subfield(mini_index):
    import jsonschema
    from pathlib import Path

    schema_path = Path(__file__).parent.parent / "contracts" / "query-result.v1.schema.json"
    with schema_path.open("r", encoding="utf-8") as f:
        schema = json.load(f)

    invalid = {
        "query": "x", "k": 1, "engine": "fts5", "query_mode": "fts",
        "applied_filters": {}, "count": 0, "results": [],
        "claim_boundaries": {
            "proves": [],
            "does_not_prove": []
        }
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=invalid, schema=schema)
