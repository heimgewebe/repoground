import pytest
import json
import argparse
from merger.repoground.cli import cmd_query

@pytest.fixture
def mini_index(tmp_path):
    from merger.repoground.retrieval import index_db

    # Setup paths
    dump_path = tmp_path / "dump.json"
    chunk_path = tmp_path / "chunks.jsonl"
    db_path = tmp_path / "index.sqlite"

    # Write chunks
    chunk_data = [
        {"chunk_id": "c1", "repo_id": "r1", "path": "src/main.py", "content": "def main(): print('hello world')", "start_line": 1, "end_line": 1, "layer": "core", "artifact_type": "code", "content_sha256": "h1"},
    ]
    with chunk_path.open("w", encoding="utf-8") as f:
        for c in chunk_data:
            f.write(json.dumps(c) + "\n")

    dump_data = {
        "version": "1.0",
        "repos": {"r1": {"chunks_file": "chunks.jsonl"}},
        "manifest": {"chunk_index_jsonl": {"sha256": "dummy"}}
    }
    dump_path.write_text(json.dumps(dump_data), encoding="utf-8")

    index_db.build_index(dump_path, chunk_path, db_path)
    return db_path

def test_cli_query_lookup_minimal(mini_index, capsys):
    args = argparse.Namespace(
        index=str(mini_index),
        q="hello",
        k=1,
        repo=None, path=None, ext=None, layer=None, artifact_type=None,
        emit="json",
        stale_policy="ignore",
        embedding_policy=None,
        explain=True,
        graph_index=None,
        graph_weights=None,
        test_penalty=0.75,
        output_profile="lookup_minimal",

        context_window_lines=1,
        context_mode="window",
        build_context_bundle=False,
        overmatch_guard=False,
        trace=False
    )

    ret = cmd_query.run_query(args)
    assert ret == 0

    captured = capsys.readouterr()
    data = json.loads(captured.out)

    assert "hits" in data
    assert len(data["hits"]) > 0
    for hit in data["hits"]:
        assert "explain" not in hit
        assert "graph_context" not in hit
        assert "surrounding_context" not in hit

def test_cli_query_review_context(mini_index, capsys):
    args = argparse.Namespace(
        index=str(mini_index),
        q="hello",
        k=1,
        repo=None, path=None, ext=None, layer=None, artifact_type=None,
        emit="json",
        stale_policy="ignore",
        embedding_policy=None,
        explain=True,
        graph_index=None,
        graph_weights=None,
        test_penalty=0.75,
        output_profile="review_context",

        context_window_lines=1,
        context_mode="window",
        build_context_bundle=False,
        overmatch_guard=False,
        trace=False
    )

    ret = cmd_query.run_query(args)
    assert ret == 0

    captured = capsys.readouterr()
    data = json.loads(captured.out)

    assert "hits" in data
    assert len(data["hits"]) > 0
    for hit in data["hits"]:
        assert "explain" in hit
        assert "graph_context" not in hit
        # Context mode window 1 expands lines, so surrounding_context shouldn't be None.
        assert "surrounding_context" in hit
        assert hit["surrounding_context"] is not None
