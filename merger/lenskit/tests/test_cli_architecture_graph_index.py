import argparse
import json

from merger.lenskit.cli.cmd_architecture import run_architecture_cmd


def test_graph_index_cli_emits_structured_error_and_exit_2(tmp_path, capsys):
    sha256 = "a" * 64
    graph_path = tmp_path / "graph.json"
    entrypoints_path = tmp_path / "entrypoints.json"
    graph_path.write_text(
        json.dumps(
            {
                "kind": "lenskit.architecture.graph",
                "version": "1.0",
                "run_id": "graph-run",
                "canonical_dump_index_sha256": sha256,
                "nodes": [],
                "edges": [],
                "coverage": {
                    "files_seen": 0,
                    "files_parsed": 0,
                    "edge_counts_by_type": {},
                    "unknown_layer_share": 1.0,
                },
            }
        ),
        encoding="utf-8",
    )
    entrypoints_path.write_text(
        json.dumps(
            {
                "kind": "lenskit.entrypoints",
                "version": "1.0",
                "run_id": "entrypoint-run",
                "canonical_dump_index_sha256": sha256,
                "entrypoints": [],
            }
        ),
        encoding="utf-8",
    )

    exit_code = run_architecture_cmd(
        argparse.Namespace(
            entrypoints=False,
            import_graph=False,
            graph_index=True,
            graph_in=str(graph_path),
            entrypoints_in=str(entrypoints_path),
            repo=str(tmp_path),
        )
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    diagnostic = json.loads(captured.err)
    assert diagnostic["code"] == "provenance_mismatch"
    assert diagnostic["source"] == "provenance"
    assert diagnostic["message"] == "source run_id values differ"
