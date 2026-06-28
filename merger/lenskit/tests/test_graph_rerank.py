import json
from pathlib import Path
import pytest
from merger.lenskit.retrieval import query_core
from merger.lenskit.retrieval import index_db

@pytest.fixture
def mini_index_with_graph(tmp_path):
    dump_path = tmp_path / "dump.json"
    chunk_path = tmp_path / "chunks.jsonl"
    db_path = tmp_path / "index.sqlite"
    graph_index_path = tmp_path / "graph_index.json"

    chunk_data = [
        {"chunk_id": "c1", "repo_id": "r1", "path": "src/entry.py", "content": "def main(): print('hello from entry')", "start_line": 1, "end_line": 1, "layer": "core", "artifact_type": "code", "content_sha256": "h1"},
        {"chunk_id": "c2", "repo_id": "r1", "path": "src/util.py", "content": "def util(): print('hello from util')", "start_line": 1, "end_line": 1, "layer": "core", "artifact_type": "code", "content_sha256": "h2"},
        {"chunk_id": "c3", "repo_id": "r1", "path": "src/deep.py", "content": "def deep(): print('hello from deep')", "start_line": 1, "end_line": 1, "layer": "core", "artifact_type": "code", "content_sha256": "h3"},
        {"chunk_id": "c4", "repo_id": "r1", "path": "tests/test_entry.py", "content": "def test_entry(): print('hello test')", "start_line": 1, "end_line": 1, "layer": "test", "artifact_type": "code", "content_sha256": "h4"},
    ]
    with chunk_path.open("w", encoding="utf-8") as f:
        for c in chunk_data:
            f.write(json.dumps(c) + "\n")

    dump_path.write_text(json.dumps({"dummy": "data"}), encoding="utf-8")

    index_db.build_index(dump_path, chunk_path, db_path)

    import hashlib
    with open(dump_path, "rb") as df:
        db_hash = hashlib.sha256(df.read()).hexdigest()

    graph_index = {
        "kind": "lenskit.architecture.graph_index",
        "version": "1.0",
        "run_id": "test_run",
        "canonical_dump_index_sha256": db_hash,
        "distances": {
            "file:src/entry.py": 0,
            "file:src/util.py": 1,
            "file:src/deep.py": 2,
            "file:tests/test_entry.py": -1
        },
        "metrics": {
            "entrypoint_count": 1,
            "nodes_reachable": 3,
            "unreachable_nodes": 1
        }
    }
    graph_index_path.write_text(json.dumps(graph_index), encoding="utf-8")

    return db_path, graph_index_path

def test_graph_rerank(mini_index_with_graph):
    db_path, graph_index_path = mini_index_with_graph

    query_core.execute_query(db_path, query_text="hello", k=10, explain=True)

    res_graph = query_core.execute_query(db_path, query_text="hello", k=10, explain=True, graph_index_path=graph_index_path, test_penalty=0.5)

    assert "ranker" in res_graph["explain"]

    graph_order = [r["path"] for r in res_graph["results"]]

    assert graph_order[0] == "src/entry.py"
    assert graph_order[1] == "src/util.py"
    assert graph_order[2] == "src/deep.py"
    assert graph_order[3] == "tests/test_entry.py"

    assert "near_entry" in res_graph["results"][0]["why_list"]
    assert "entrypoint_boost" in res_graph["results"][0]["why_list"]
    assert "not_test" in res_graph["results"][0]["why_list"]

    assert "near_entry" in res_graph["results"][1]["why_list"]
    assert "entrypoint_boost" not in res_graph["results"][1]["why_list"]

    assert res_graph["results"][3]["layer"] == "test"
    # why_list is only appended to the result object if it is non-empty. For test layer entries without other bonuses, it can be absent.
    assert "not_test" not in res_graph["results"][3].get("why_list", [])

def test_graph_fallback(mini_index_with_graph):
    db_path, graph_index_path = mini_index_with_graph

    with pytest.raises(RuntimeError, match="Explicitly provided graph index file does not exist"):
        query_core.execute_query(db_path, query_text="hello", k=10, explain=True, graph_index_path=Path("nonexistent.json"))

    res = query_core.execute_query(db_path, query_text="hello", k=10, explain=True, graph_index_path=None)
    assert "ranker" not in res["explain"]
    assert "why_list" not in res.get("results", [{}])[0] if res.get("results") else True


def test_stale_graph_is_diagnostic_only(mini_index_with_graph, tmp_path):
    db_path, graph_index_path = mini_index_with_graph
    baseline = query_core.execute_query(db_path, query_text="hello", k=10, explain=True)
    stale_graph = json.loads(graph_index_path.read_text(encoding="utf-8"))
    stale_graph["canonical_dump_index_sha256"] = "f" * 64
    stale_path = tmp_path / "stale_graph_index.json"
    stale_path.write_text(json.dumps(stale_graph), encoding="utf-8")
    observed = query_core.execute_query(
        db_path,
        query_text="hello",
        k=10,
        explain=True,
        graph_index_path=stale_path,
        test_penalty=0.1,
    )
    assert [(h["path"], h["score"], h["final_score"]) for h in observed["results"]] == [
        (h["path"], h["score"], h["final_score"]) for h in baseline["results"]
    ]
    assert "ranker" not in observed["explain"]
    for hit in observed["results"]:
        graph = hit["why"]["diagnostics"]["graph"]
        assert graph["graph_status"] == "stale_or_mismatched"
        assert graph["graph_used"] is False
        assert graph["distance"] == -1
        assert graph["graph_bonus"] == 0.0
        assert "entrypoint_boost" not in hit.get("why_list", [])
        assert "near_entry" not in hit.get("why_list", [])
        assert "not_test" not in hit.get("why_list", [])
