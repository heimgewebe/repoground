import hashlib
import json

from merger.lenskit.architecture.graph_index import compile_graph_index
from merger.lenskit.retrieval import index_db, query_core


def test_graph_e2e_compile_and_query(tmp_path):
    source_sha = "0" * 64
    graph = {
        "kind": "lenskit.architecture.graph",
        "version": "1.0",
        "run_id": "test_e2e",
        "canonical_dump_index_sha256": source_sha,
        "nodes": [
            {
                "node_id": "file:main.py",
                "kind": "file",
                "path": "main.py",
                "repo": "r1",
                "is_test": False,
            },
            {
                "node_id": "file:util.py",
                "kind": "file",
                "path": "util.py",
                "repo": "r1",
                "is_test": False,
            },
            {
                "node_id": "file:far.py",
                "kind": "file",
                "path": "far.py",
                "repo": "r1",
                "is_test": False,
            },
        ],
        "edges": [
            {
                "src": "file:main.py",
                "dst": "file:util.py",
                "edge_type": "import",
                "evidence_level": "S1",
                "evidence": {"source_path": "main.py"},
            }
        ],
        "coverage": {
            "files_seen": 3,
            "files_parsed": 3,
            "edge_counts_by_type": {"import": 1},
            "unknown_layer_share": 1.0,
        },
    }
    entrypoints = {
        "kind": "lenskit.entrypoints",
        "version": "1.0",
        "run_id": "test_e2e",
        "canonical_dump_index_sha256": source_sha,
        "entrypoints": [
            {
                "id": "path:main.py",
                "type": "cli",
                "path": "main.py",
                "evidence_level": "S1",
            }
        ],
    }

    graph_path = tmp_path / "architecture.graph.json"
    graph_path.write_text(json.dumps(graph), encoding="utf-8")
    entrypoints_path = tmp_path / "entrypoints.json"
    entrypoints_path.write_text(json.dumps(entrypoints), encoding="utf-8")
    graph_index = compile_graph_index(graph_path, entrypoints_path)

    graph_index_path = tmp_path / "graph_index.json"
    dump_path = tmp_path / "dump.json"
    chunk_path = tmp_path / "chunks.jsonl"
    db_path = tmp_path / "index.sqlite"

    chunks = [
        {
            "chunk_id": "c1",
            "repo_id": "r1",
            "path": "main.py",
            "content": "func",
            "start_line": 1,
            "end_line": 1,
            "layer": "core",
            "artifact_type": "code",
        },
        {
            "chunk_id": "c2",
            "repo_id": "r1",
            "path": "util.py",
            "content": "func",
            "start_line": 1,
            "end_line": 1,
            "layer": "core",
            "artifact_type": "code",
        },
        {
            "chunk_id": "c3",
            "repo_id": "r1",
            "path": "far.py",
            "content": "func",
            "start_line": 1,
            "end_line": 1,
            "layer": "core",
            "artifact_type": "code",
        },
    ]
    with chunk_path.open("w", encoding="utf-8") as handle:
        for chunk in chunks:
            handle.write(json.dumps(chunk) + "\n")

    dump_path.write_text(json.dumps({"dummy": "data"}), encoding="utf-8")
    index_db.build_index(dump_path, chunk_path, db_path)
    graph_index["canonical_dump_index_sha256"] = hashlib.sha256(
        dump_path.read_bytes()
    ).hexdigest()
    graph_index_path.write_text(json.dumps(graph_index), encoding="utf-8")

    result = query_core.execute_query(
        db_path,
        query_text="func",
        k=10,
        explain=True,
        graph_index_path=graph_index_path,
    )

    assert [item["path"] for item in result["results"]] == [
        "main.py",
        "util.py",
        "far.py",
    ]
    assert "near_entry" in result["results"][0]["why_list"]
    assert "entrypoint_boost" in result["results"][0]["why_list"]
