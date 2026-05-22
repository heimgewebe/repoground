import json
import pytest
from pathlib import Path
from merger.lenskit.retrieval import index_db, query_core
import jsonschema

@pytest.fixture
def mini_index(tmp_path):
    dump_path = tmp_path / "dump.json"
    chunk_path = tmp_path / "chunks.jsonl"
    db_path = tmp_path / "index.sqlite"

    chunk_data = [
        {
            "chunk_id": "c1", "repo_id": "r1", "path": "src/main.py",
            "content": "def main():\n    print('hello world')\n    return 0",
            "start_line": 10, "end_line": 12, "layer": "core", "artifact_type": "code", "content_sha256": "h1"
        },
        {
            "chunk_id": "c2", "repo_id": "r1", "path": "src/main.py",
            "content": "def helper():\n    pass",
            "start_line": 15, "end_line": 16, "layer": "core", "artifact_type": "code", "content_sha256": "h2"
        },
    ]
    with chunk_path.open("w", encoding="utf-8") as f:
        for c in chunk_data:
            f.write(json.dumps(c) + "\n")

    dump_path.write_text(json.dumps({"dummy": "data"}), encoding="utf-8")
    index_db.build_index(dump_path, chunk_path, db_path)
    return db_path


def test_context_bundle_contains_evidence_and_context(mini_index):
    res = query_core.execute_query(
        mini_index,
        query_text="hello",
        k=5,
        build_context=True,
        context_mode="exact"
    )

    assert "context_bundle" in res
    bundle = res["context_bundle"]
    assert bundle["query"] == "hello"
    assert len(bundle["hits"]) == 1

    hit = bundle["hits"][0]
    assert hit["hit_identity"] == "c1"
    assert "hello world" in hit["resolved_code_snippet"]
    assert hit["surrounding_context"] is None

    # Contract validation of the explicit bundle schema
    bundle_schema_path = Path(__file__).parent.parent / "contracts" / "query-context-bundle.v1.schema.json"
    bundle_schema = json.loads(bundle_schema_path.read_text(encoding="utf-8"))
    jsonschema.validate(instance=bundle, schema=bundle_schema)

    # Contract validation of the base result schema
    contracts_dir = Path(__file__).parent.parent / "contracts"
    base_schema_path = contracts_dir / "query-result.v1.schema.json"
    base_schema = json.loads(base_schema_path.read_text(encoding="utf-8"))

    # Need a custom registry mapping the local file so remote fetches aren't attempted
    from referencing import Registry, Resource
    registry = Registry().with_resource(
        "query-context-bundle.v1.schema.json",
        Resource.from_contents(bundle_schema)
    )

    jsonschema.validate(instance=res, schema=base_schema, registry=registry)


def test_context_bundle_preserves_provenance(tmp_path):
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
            "chunk_id": "c1", "repo_id": "r1", "path": "src/main.py", "content": "hello provenance",
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

    res = query_core.execute_query(db_path, query_text="provenance", k=1, build_context=True)
    bundle = res["context_bundle"]
    hit = bundle["hits"][0]

    assert hit["provenance_type"] == "explicit"
    assert "range_ref" in hit
    assert hit["range_ref"] == ref_obj
    assert "merged.md" in hit["bundle_source_references"]


def test_context_expansion_exact_vs_block_vs_window(mini_index):
    # exact
    res_exact = query_core.execute_query(mini_index, query_text="hello", build_context=True, context_mode="exact")
    assert res_exact["context_bundle"]["hits"][0]["surrounding_context"] is None

    # block (currently a deterministic pass-through yielding None)
    res_block = query_core.execute_query(mini_index, query_text="hello", build_context=True, context_mode="block")
    assert res_block["context_bundle"]["hits"][0]["surrounding_context"] is None

    # window
    res_win = query_core.execute_query(mini_index, query_text="hello", build_context=True, context_mode="window", context_window_lines=5)
    win_ctx = res_win["context_bundle"]["hits"][0]["surrounding_context"]
    assert win_ctx is not None
    assert "def helper" in win_ctx  # c2 should be pulled in by the window (lines 15-16 are within 12+5=17)

    # file
    res_file = query_core.execute_query(mini_index, query_text="hello", build_context=True, context_mode="file")
    file_ctx = res_file["context_bundle"]["hits"][0]["surrounding_context"]
    assert file_ctx is not None
    assert "def main" in file_ctx
    assert "def helper" in file_ctx


def test_ui_payload_excludes_internal_fields(mini_index, capsys):
    from merger.lenskit.cli import cmd_query
    import argparse

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
        output_profile="ui_navigation",
        context_mode="exact",
        context_window_lines=0
    )

    ret = cmd_query.run_query(args)
    assert ret == 0
    captured = capsys.readouterr()
    output = json.loads(captured.out)

    # ui_navigation preserves all context bundle fields and outputs the bundle projection directly
    assert "query" in output
    assert "hits" in output
    assert isinstance(output["hits"], list)

    # Base query-result wrapper should not be present in the projected bundle output
    assert "engine" not in output
    assert "count" not in output

    assert "explain" in output["hits"][0]

    # Explicitly check that no internal hit fields (like _raw_content) leaked
    hit = output["hits"][0]
    assert "_raw_content" not in hit

    # Also check the raw JSON output to ensure it doesn't appear anywhere
    assert "_raw_content" not in captured.out


def test_agent_minimal_profile_contract(mini_index, capsys):
    from merger.lenskit.cli import cmd_query
    import argparse

    args = argparse.Namespace(
        index=str(mini_index),
        q="hello",
        k=1,
        repo=None, path=None, ext=None, layer=None, artifact_type=None,
        emit="json",
        stale_policy="ignore",
        embedding_policy=None,
        explain=True, # Will be stripped
        graph_index=None,
        graph_weights=None,
        test_penalty=0.75,
        output_profile="agent_minimal",
        context_mode="exact",
        context_window_lines=0
    )

    ret = cmd_query.run_query(args)
    assert ret == 0
    captured = capsys.readouterr()
    output = json.loads(captured.out)

    assert "hits" in output
    hit = output["hits"][0]

    # Agent minimal strips explain & graph_context & surrounding_context (if null)
    assert "explain" not in hit
    assert "graph_context" not in hit
    assert "surrounding_context" not in hit

    # Essential provenance is preserved
    assert hit["provenance_type"] in ["explicit", "derived"]

def test_context_bundle_extracts_snippet_correctly(mini_index):
    # Testing that snippet is correctly extracted during hit building
    res = query_core.execute_query(mini_index, query_text="hello", build_context=True)
    hit = res["context_bundle"]["hits"][0]

    # Ensuring snippet exists (representing the raw extracted content)
    assert isinstance(hit["resolved_code_snippet"], str)
    assert "hello world" in hit["resolved_code_snippet"]

def test_cli_explicit_bundle_flag(mini_index, capsys):
    from merger.lenskit.cli import cmd_query
    import argparse

    args = argparse.Namespace(
        index=str(mini_index),
        q="hello",
        k=1,
        repo=None, path=None, ext=None, layer=None, artifact_type=None,
        emit="json",
        stale_policy="ignore",
        embedding_policy=None,
        explain=False,
        graph_index=None,
        graph_weights=None,
        test_penalty=0.75,
        output_profile=None,
        context_mode="exact",
        context_window_lines=0,
        build_context_bundle=True
    )

    ret = cmd_query.run_query(args)
    assert ret == 0
    captured = capsys.readouterr()
    output = json.loads(captured.out)

    # When emit is json and no output_profile is set, we expect the base query result structure,
    # but the context_bundle should be included because build_context_bundle=True.
    assert "engine" in output
    assert "context_bundle" in output
    assert output["context_bundle"]["hits"][0]["surrounding_context"] is None


def test_cli_backward_compatibility(mini_index, capsys):
    from merger.lenskit.cli import cmd_query
    import argparse

    # Use window mode implicitly to trigger bundle creation
    args = argparse.Namespace(
        index=str(mini_index),
        q="hello",
        k=1,
        repo=None, path=None, ext=None, layer=None, artifact_type=None,
        emit="json",
        stale_policy="ignore",
        embedding_policy=None,
        explain=False,
        graph_index=None,
        graph_weights=None,
        test_penalty=0.75,
        output_profile=None,
        context_mode="window",
        context_window_lines=5,
        build_context_bundle=False
    )

    ret = cmd_query.run_query(args)
    assert ret == 0
    captured = capsys.readouterr()
    output = json.loads(captured.out)

    assert "engine" in output
    assert "context_bundle" in output
    # Validate window mode context was fetched
    assert output["context_bundle"]["hits"][0]["surrounding_context"] is not None


def test_cli_rejects_window_lines_without_window_mode(mini_index, capsys):
    from merger.lenskit.cli import cmd_query
    import argparse

    args = argparse.Namespace(
        index=str(mini_index),
        q="hello",
        k=1,
        repo=None, path=None, ext=None, layer=None, artifact_type=None,
        emit="json",
        stale_policy="ignore",
        embedding_policy=None,
        explain=False,
        graph_index=None,
        graph_weights=None,
        test_penalty=0.75,
        output_profile=None,
        context_mode="exact",
        context_window_lines=5
    )

    ret = cmd_query.run_query(args)
    assert ret == 1
    captured = capsys.readouterr()
    assert "--context-window-lines requires --context-mode window" in captured.err


# --- PR B3: surface-local context_risk hardening ---

_EXPECTED_CONTEXT_RISK = {
    "retrieval_based_subset": True,
    "missing_relevant_context_possible": True,
    "may_answer_from_this_directly": False,
    "claims_resolve_to": {
        "content": "canonical_md",
        "metadata": "bundle_manifest",
        "schema": "schema",
        "runtime": "query_trace",
    },
    "does_not_prove": [
        "Absence of a hit does not prove absence in the repository.",
        "These retrieved snippets do not prove complete or sufficient context.",
        "Ranking does not prove semantic importance.",
        "This bundle is an agent context projection, not canonical repository content.",
    ],
}


def test_context_bundle_declares_context_risk(mini_index):
    # The producer emits a surface-local context_risk block, and the resulting
    # bundle still validates against the (additively extended) bundle schema.
    res = query_core.execute_query(
        mini_index, query_text="hello", k=5, build_context=True, context_mode="exact"
    )
    bundle = res["context_bundle"]

    assert bundle["context_risk"] == _EXPECTED_CONTEXT_RISK
    # The safety-critical semantics specifically:
    assert bundle["context_risk"]["may_answer_from_this_directly"] is False
    assert bundle["context_risk"]["claims_resolve_to"]["content"] == "canonical_md"

    bundle_schema_path = (
        Path(__file__).parent.parent / "contracts" / "query-context-bundle.v1.schema.json"
    )
    bundle_schema = json.loads(bundle_schema_path.read_text(encoding="utf-8"))
    jsonschema.validate(instance=bundle, schema=bundle_schema)


def test_context_bundle_v1_backwards_compatible():
    # A legacy bundle WITHOUT context_risk must still validate: the field is optional,
    # so adding it is a non-breaking, additive change for existing consumers/bundles.
    bundle_schema_path = (
        Path(__file__).parent.parent / "contracts" / "query-context-bundle.v1.schema.json"
    )
    bundle_schema = json.loads(bundle_schema_path.read_text(encoding="utf-8"))

    legacy_bundle = {"query": "hello", "hits": []}
    jsonschema.validate(instance=legacy_bundle, schema=bundle_schema)


def test_context_risk_block_is_deterministic(mini_index):
    # The block is a constant: two independent runs produce an identical context_risk.
    res_a = query_core.execute_query(mini_index, query_text="hello", k=5, build_context=True)
    res_b = query_core.execute_query(mini_index, query_text="hello", k=5, build_context=True)
    assert res_a["context_bundle"]["context_risk"] == res_b["context_bundle"]["context_risk"]


def test_context_risk_survives_agent_minimal_projection(mini_index):
    # The concrete harm B3 closes: agent_minimal returns the bare bundle, dropping the
    # query-result-level claim_boundaries. The bundle-level context_risk must survive
    # the projection so the agent still sees the projection/resolve boundary.
    from merger.lenskit.retrieval.output_projection import project_output

    res = query_core.execute_query(mini_index, query_text="hello", k=5, build_context=True)
    projected = project_output(res, "agent_minimal")

    # project_output returns either the bare bundle (direct form) or a wrapper.
    bundle = projected["context_bundle"] if "context_bundle" in projected else projected

    assert "context_risk" in bundle
    assert bundle["context_risk"] == _EXPECTED_CONTEXT_RISK
    # agent_minimal still strips per-hit explain (sanity: we projected the right profile).
    assert all("explain" not in hit for hit in bundle["hits"])
