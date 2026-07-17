import pytest
import json
import argparse
from pathlib import Path
from merger.repoground.cli import cmd_query

@pytest.fixture
def mini_index(tmp_path, monkeypatch):
    from merger.repoground.retrieval import index_db

    # Change to a temp dir so written files don't clutter the repo root
    monkeypatch.chdir(tmp_path)

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

def test_agent_session_trace_contains_refs(mini_index, tmp_path):
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
        output_profile="agent_minimal",
        context_window_lines=0,
        context_mode="exact",
        build_context_bundle=False,
        overmatch_guard=False,
        trace=True
    )

    ret = cmd_query.run_query(args)
    assert ret == 0

    trace_path = tmp_path / "query_trace.json"
    session_path = tmp_path / "agent_query_session.json"

    assert trace_path.exists()
    assert session_path.exists()

    session = json.loads(session_path.read_text(encoding="utf-8"))

    assert "refs" in session
    assert session["refs"]["query_trace_ref"] == "query_trace.json"
    assert "r1" in session.get("resolved_bundles", [])
    assert session["refs"].get("context_bundle_ref") is None
    assert "diagnostics_ref" in session["refs"]
    assert session["refs"]["diagnostics_ref"] is None

    # Verify new integrity and environment fields
    assert "environment" in session
    assert "lenskit_version" in session["environment"]
    assert "index_path" in session["environment"]
    assert "timestamp_utc" in session["environment"]

    assert "integrity" in session["refs"]
    assert "query_trace_sha256" in session["refs"]["integrity"]

    # Hash check
    import hashlib
    expected_hash = hashlib.sha256(trace_path.read_bytes()).hexdigest()
    assert session["refs"]["integrity"]["query_trace_sha256"] == expected_hash

    # Verify the structure using the schema
    try:
        import jsonschema
        schema_path = Path(__file__).parent.parent / "contracts" / "agent-query-session.v1.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        jsonschema.validate(instance=session, schema=schema)
    except ImportError:
        pytest.skip("jsonschema is not installed; skipping agent session schema validation")

def test_agent_session_trace_out_dir(mini_index, tmp_path):
    out_dir = tmp_path / "custom_out"
    out_dir.mkdir()

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
        output_profile="agent_minimal",
        context_window_lines=0,
        context_mode="exact",
        build_context_bundle=False,
        overmatch_guard=False,
        trace=True,
        trace_out_dir=str(out_dir)
    )

    ret = cmd_query.run_query(args)
    assert ret == 0

    trace_path = out_dir / "query_trace.json"
    session_path = out_dir / "agent_query_session.json"

    assert trace_path.exists()
    assert session_path.exists()

    session = json.loads(session_path.read_text(encoding="utf-8"))

    import hashlib
    expected_hash = hashlib.sha256(trace_path.read_bytes()).hexdigest()
    assert session["refs"]["integrity"]["query_trace_sha256"] == expected_hash

def test_agent_session_trace_out_dir_is_file(mini_index, tmp_path, capsys):
    # Create a file where the directory should be
    bad_dir = tmp_path / "not_a_dir"
    bad_dir.write_text("i am a file")

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
        output_profile="agent_minimal",
        context_window_lines=0,
        context_mode="exact",
        build_context_bundle=False,
        overmatch_guard=False,
        trace=True,
        trace_out_dir=str(bad_dir)
    )

    ret = cmd_query.run_query(args)
    # The CLI catches RuntimeError and prints to stderr, returning 1
    assert ret == 1

    captured = capsys.readouterr()
    assert "--trace-out-dir" in captured.err
    assert "not a directory" in captured.err
