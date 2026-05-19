import json
from merger.lenskit.architecture.graph_index import compile_graph_index
from merger.lenskit.retrieval import query_core
from merger.lenskit.retrieval import index_db

def test_graph_e2e_compile_and_query(tmp_path):
    graph = {
        "run_id": "test_e2e",
        "nodes": [
            {"node_id": "file:main.py", "path": "main.py"},
            {"node_id": "file:util.py", "path": "util.py"},
            {"node_id": "file:far.py", "path": "far.py"}
        ],
        "edges": [
            {"src": "file:main.py", "dst": "file:util.py"}
        ]
    }

    entrypoints = {
        "entrypoints": [
            {"path": "main.py"}
        ]
    }

    graph_path = tmp_path / "architecture.graph.json"
    graph_path.write_text(json.dumps(graph))

    eps_path = tmp_path / "entrypoints.json"
    eps_path.write_text(json.dumps(entrypoints))

    graph_index = compile_graph_index(graph_path, eps_path)

    gi_path = tmp_path / "graph_index.json"
    gi_path.write_text(json.dumps(graph_index))

    dump_path = tmp_path / "dump.json"
    chunk_path = tmp_path / "chunks.jsonl"
    db_path = tmp_path / "index.sqlite"

    chunk_data = [
        {"chunk_id": "c1", "repo_id": "r1", "path": "main.py", "content": "func", "start_line": 1, "end_line": 1, "layer": "core", "artifact_type": "code"},
        {"chunk_id": "c2", "repo_id": "r1", "path": "util.py", "content": "func", "start_line": 1, "end_line": 1, "layer": "core", "artifact_type": "code"},
        {"chunk_id": "c3", "repo_id": "r1", "path": "far.py", "content": "func", "start_line": 1, "end_line": 1, "layer": "core", "artifact_type": "code"}
    ]
    with chunk_path.open("w") as f:
        for c in chunk_data:
            f.write(json.dumps(c) + "\n")

    dump_path.write_text(json.dumps({"dummy": "data"}))
    index_db.build_index(dump_path, chunk_path, db_path)

    import hashlib
    with open(dump_path, "rb") as df:
         db_hash = hashlib.sha256(df.read()).hexdigest()
    graph_index["canonical_dump_index_sha256"] = db_hash
    gi_path.write_text(json.dumps(graph_index))

    res = query_core.execute_query(db_path, query_text="func", k=10, explain=True, graph_index_path=gi_path)

    order = [r["path"] for r in res["results"]]

    assert order[0] == "main.py"
    assert order[1] == "util.py"
    assert order[2] == "far.py"

    assert "near_entry" in res["results"][0]["why_list"]
    assert "entrypoint_boost" in res["results"][0]["why_list"]
