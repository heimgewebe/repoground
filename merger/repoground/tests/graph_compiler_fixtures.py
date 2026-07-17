def graph_document(run_id="run", canonical_sha="0" * 64):
    return {
        "kind": "lenskit.architecture.graph",
        "version": "1.0",
        "run_id": run_id,
        "canonical_dump_index_sha256": canonical_sha,
        "granularity": "file",
        "nodes": [
            {
                "node_id": "file:main.py",
                "kind": "file",
                "path": "main.py",
                "repo": "repo",
                "language": "python",
                "layer": "unknown",
                "is_test": False,
            },
            {
                "node_id": "file:util.py",
                "kind": "file",
                "path": "util.py",
                "repo": "repo",
                "language": "python",
                "layer": "unknown",
                "is_test": False,
            },
            {
                "node_id": "file:unreach.py",
                "kind": "file",
                "path": "unreach.py",
                "repo": "repo",
                "language": "python",
                "layer": "unknown",
                "is_test": False,
            },
        ],
        "edges": [
            {
                "src": "file:main.py",
                "dst": "file:util.py",
                "edge_type": "import",
                "evidence_level": "S1",
                "evidence": {"source_path": "main.py", "start_line": 1},
            }
        ],
        "coverage": {
            "files_seen": 3,
            "files_parsed": 3,
            "edge_counts_by_type": {"import": 1},
            "unknown_layer_share": 1.0,
        },
    }


def entrypoints_document(run_id="run", canonical_sha="0" * 64):
    return {
        "kind": "lenskit.entrypoints",
        "version": "1.0",
        "run_id": run_id,
        "canonical_dump_index_sha256": canonical_sha,
        "entrypoints": [
            {
                "id": "main.py:module_main",
                "type": "module_main",
                "path": "main.py",
                "evidence_level": "S0",
                "evidence": {"rule": "fixture"},
            }
        ],
    }
