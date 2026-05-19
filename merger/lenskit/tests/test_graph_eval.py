import json
import pytest
from merger.lenskit.cli import cmd_eval
from merger.lenskit.retrieval import index_db
import argparse

@pytest.fixture
def eval_env(tmp_path):
    dump_path = tmp_path / "dump.json"
    chunk_path = tmp_path / "chunks.jsonl"
    db_path = tmp_path / "index.sqlite"
    queries_path = tmp_path / "queries.md"
    graph_index_path = tmp_path / "graph_index.json"

    chunk_data = [
        {"chunk_id": "c1", "repo_id": "r1", "path": "src/entry.py", "content": "def main(): print('hello index from entry')", "start_line": 1, "end_line": 1, "layer": "core", "artifact_type": "code", "content_sha256": "h1"},
        {"chunk_id": "c2", "repo_id": "r1", "path": "src/util.py", "content": "def util(): print('hello index from util')", "start_line": 1, "end_line": 1, "layer": "core", "artifact_type": "code", "content_sha256": "h2"}
    ]
    with chunk_path.open("w", encoding="utf-8") as f:
        for c in chunk_data:
            f.write(json.dumps(c) + "\n")

    dump_path.write_text(json.dumps({"run_id": "test", "canonical_dump_index_sha256": "0"}), encoding="utf-8")
    index_db.build_index(dump_path, chunk_path, db_path)

    queries_path.write_text("1. **\"index\"**\n   * *Expected:* `src/entry.py`\n")

    graph_index = {
        "kind": "lenskit.architecture.graph_index",
        "version": "1.0",
        "run_id": "test",
        "canonical_dump_index_sha256": "0"*64,
        "distances": {"file:src/entry.py": 0, "file:src/util.py": 1},
        "metrics": {"entrypoint_count": 1, "nodes_reachable": 2, "unreachable_nodes": 0}
    }
    graph_index_path.write_text(json.dumps(graph_index), encoding="utf-8")

    return {
        "db": db_path,
        "queries": queries_path,
        "graph_index": graph_index_path
    }

def test_eval_wiring(eval_env, capsys):
    args = argparse.Namespace(
        index=str(eval_env["db"]),
        queries=str(eval_env["queries"]),
        k=10,
        emit="json",
        stale_policy="ignore",
        embedding_policy=None,
        graph_index=str(eval_env["graph_index"]),
        graph_weights=None
    )

    ret = cmd_eval.run_eval(args)
    assert ret == 0
    captured = capsys.readouterr()
    output = json.loads(captured.out)

    # We expect recall to be 100%
    assert output["metrics"]["recall@10"] == 100.0

def test_invalid_graph_index_raises(eval_env, capsys):
    bad_graph = eval_env["graph_index"].parent / "bad_graph.json"
    bad_graph.write_text("{bad json")

    args = argparse.Namespace(
        index=str(eval_env["db"]),
        queries=str(eval_env["queries"]),
        k=10,
        emit="json",
        stale_policy="ignore",
        embedding_policy=None,
        graph_index=str(bad_graph),
        graph_weights=None
    )

    ret = cmd_eval.run_eval(args)
    assert ret == 0
    captured = capsys.readouterr()
    output = json.loads(captured.out)
    assert output["details"][0]["why"]["diagnostics"]["graph"]["graph_used"] is False
    assert output["details"][0]["why"]["diagnostics"]["graph"]["graph_status"] == "invalid_json"

def test_missing_graph_index_raises(eval_env, capsys):
    missing_graph = eval_env["graph_index"].parent / "does_not_exist.json"

    args = argparse.Namespace(
        index=str(eval_env["db"]),
        queries=str(eval_env["queries"]),
        k=10,
        emit="json",
        stale_policy="ignore",
        embedding_policy=None,
        graph_index=str(missing_graph),
        graph_weights=None
    )

    ret = cmd_eval.run_eval(args)
    # Eval core logs the explicit exception as a Semantic Run Error but continues processing returning a valid metrics JSON.
    assert ret == 0
    captured = capsys.readouterr()
    output = json.loads(captured.out)
    assert "Explicitly provided graph index file does not exist" in output["details"][0]["error"]

def test_eval_graph_delta_reporting(eval_env, capsys):
    args = argparse.Namespace(
        index=str(eval_env["db"]),
        queries=str(eval_env["queries"]),
        k=10,
        emit="json",
        stale_policy="ignore",
        embedding_policy=None,
        graph_index=str(eval_env["graph_index"]),
        graph_weights=None
    )

    ret = cmd_eval.run_eval(args)
    assert ret == 0
    captured = capsys.readouterr()
    output = json.loads(captured.out)

    assert "graph_MRR" in output["metrics"]
    assert "delta_mrr" in output["metrics"]

    # In compare mode, baseline is checked
    detail = output["details"][0]
    assert "baseline" in detail
    assert "graph" in detail

    assert detail["baseline"]["explain"]["top_k_scoring"]

    # Ensure graph is used in semantic run and not baseline run
    sem_hit_why = detail["why"]
    assert "graph" in sem_hit_why["diagnostics"]
    assert sem_hit_why["diagnostics"]["graph"]["graph_used"] is True
