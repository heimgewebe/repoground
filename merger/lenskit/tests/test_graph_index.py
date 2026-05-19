import json
from merger.lenskit.architecture.graph_index import compile_graph_index

def test_compile_graph_index(tmp_path):
    graph = {
        "run_id": "test",
        "canonical_dump_index_sha256": "0"*64,
        "nodes": [
            {"node_id": "ep1", "path": "main.py"},
            {"node_id": "util", "path": "util.py"},
            {"node_id": "unreach", "path": "unreach.py"}
        ],
        "edges": [
            {"src": "ep1", "dst": "util"}
        ]
    }

    entrypoints = {
        "entrypoints": [
            {"path": "main.py"}
        ]
    }

    graph_path = tmp_path / "graph.json"
    graph_path.write_text(json.dumps(graph))

    eps_path = tmp_path / "entrypoints.json"
    eps_path.write_text(json.dumps(entrypoints))

    idx = compile_graph_index(graph_path, eps_path)

    assert idx["metrics"]["entrypoint_count"] == 1
    assert idx["distances"]["ep1"] == 0
    assert idx["distances"]["util"] == 1
    assert idx["distances"]["unreach"] == -1

    # Assert alias keys injection is working correctly
    assert idx["distances"]["file:main.py"] == 0
    assert idx["distances"]["file:util.py"] == 1
    assert idx["distances"]["file:unreach.py"] == -1

from merger.lenskit.architecture.graph_index import load_graph_index

def test_graph_schema_validation(tmp_path):
    graph_path = tmp_path / "bad_graph.json"
    # Missing required 'kind' and 'version'
    graph_path.write_text('{"distances": {}}', encoding="utf-8")

    res = load_graph_index(graph_path)
    assert res["status"] == "invalid_schema"
    assert res["graph"] is None

def test_graph_loader_normalizes_and_rejects_invalid(tmp_path):
    graph_path = tmp_path / "bad_json.json"
    graph_path.write_text("{bad json", encoding="utf-8")

    res = load_graph_index(graph_path)
    assert res["status"] == "invalid_json"
    assert res["graph"] is None

    # Missing file
    res = load_graph_index(tmp_path / "missing.json")
    assert res["status"] == "not_found"

    # valid file
    valid_path = tmp_path / "valid.json"
    valid_data = {
        "kind": "lenskit.architecture.graph_index",
        "version": "1.0",
        "run_id": "test",
        "canonical_dump_index_sha256": "0"*64,
        "distances": {"file:main.py": 0},
        "metrics": {"entrypoint_count": 1, "nodes_reachable": 1, "unreachable_nodes": 0}
    }
    valid_path.write_text(json.dumps(valid_data), encoding="utf-8")
    res = load_graph_index(valid_path)
    assert res["status"] == "ok"
    assert res["graph"] is not None
