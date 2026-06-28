import json

import pytest

from merger.lenskit.architecture import graph_index as graph_index_module
from merger.lenskit.architecture import graph_source_validation
from merger.lenskit.architecture.graph_index import (
    GraphIndexCompilationError,
    compile_graph_index,
    load_graph_index,
)

SHA_A = "a" * 64
SHA_B = "b" * 64


def _graph(run_id="run-1", sha=SHA_A):
    return {
        "kind": "lenskit.architecture.graph",
        "version": "1.0",
        "run_id": run_id,
        "canonical_dump_index_sha256": sha,
        "nodes": [
            {
                "node_id": "main",
                "kind": "file",
                "path": "main.py",
                "repo": "repo",
                "is_test": False,
            },
            {
                "node_id": "util",
                "kind": "file",
                "path": "util.py",
                "repo": "repo",
                "is_test": False,
            },
        ],
        "edges": [
            {
                "src": "main",
                "dst": "util",
                "edge_type": "import",
                "evidence_level": "S1",
                "evidence": {"source_path": "main.py"},
            }
        ],
        "coverage": {
            "files_seen": 2,
            "files_parsed": 2,
            "edge_counts_by_type": {"import": 1},
            "unknown_layer_share": 1.0,
        },
    }


def _entrypoints(run_id="run-1", sha=SHA_A):
    return {
        "kind": "lenskit.entrypoints",
        "version": "1.0",
        "run_id": run_id,
        "canonical_dump_index_sha256": sha,
        "entrypoints": [
            {
                "id": "path:main.py",
                "type": "cli",
                "path": "main.py",
                "evidence_level": "S1",
            }
        ],
    }


def _graph_index(run_id="run-1", sha=SHA_A):
    return {
        "kind": "lenskit.architecture.graph_index",
        "version": "1.0",
        "run_id": run_id,
        "canonical_dump_index_sha256": sha,
        "distances": {},
        "metrics": {
            "entrypoint_count": 0,
            "nodes_reachable": 0,
            "unreachable_nodes": 0,
        },
    }


def _write(tmp_path, graph=None, entrypoints=None):
    graph_path = tmp_path / "graph.json"
    entrypoints_path = tmp_path / "entrypoints.json"
    graph_path.write_text(json.dumps(graph or _graph()), encoding="utf-8")
    entrypoints_path.write_text(
        json.dumps(entrypoints or _entrypoints()), encoding="utf-8"
    )
    return graph_path, entrypoints_path


def test_compile_graph_index_requires_coherent_validated_sources(tmp_path):
    graph_path, entrypoints_path = _write(tmp_path)

    result = compile_graph_index(
        graph_path,
        entrypoints_path,
        expected_run_id="run-1",
        expected_canonical_sha256=SHA_A,
    )

    assert result["run_id"] == "run-1"
    assert result["canonical_dump_index_sha256"] == SHA_A
    assert result["distances"]["main"] == 0
    assert result["distances"]["util"] == 1
    assert result["distances"]["file:main.py"] == 0
    assert result["metrics"] == {
        "entrypoint_count": 1,
        "nodes_reachable": 2,
        "unreachable_nodes": 0,
    }


@pytest.mark.parametrize("source", ["graph", "entrypoints"])
def test_compile_rejects_each_invalid_source_schema(tmp_path, source):
    graph = _graph()
    entrypoints = _entrypoints()
    if source == "graph":
        del graph["coverage"]
        expected_source = "architecture_graph"
    else:
        del entrypoints["entrypoints"][0]["id"]
        expected_source = "entrypoints"
    graph_path, entrypoints_path = _write(tmp_path, graph, entrypoints)

    with pytest.raises(GraphIndexCompilationError) as caught:
        compile_graph_index(graph_path, entrypoints_path)

    error = caught.value
    assert error.code == "invalid_schema"
    assert error.source == expected_source
    assert error.errors
    assert error.as_dict()["errors"] == list(error.errors)


@pytest.mark.parametrize(
    ("graph", "entrypoints"),
    [
        (_graph(run_id="graph-run"), _entrypoints(run_id="entry-run")),
        (_graph(sha=SHA_A), _entrypoints(sha=SHA_B)),
    ],
)
def test_compile_rejects_source_provenance_mismatch(tmp_path, graph, entrypoints):
    graph_path, entrypoints_path = _write(tmp_path, graph, entrypoints)

    with pytest.raises(GraphIndexCompilationError) as caught:
        compile_graph_index(graph_path, entrypoints_path)

    assert caught.value.code == "provenance_mismatch"
    assert caught.value.source == "provenance"


@pytest.mark.parametrize(
    ("expected_run_id", "expected_sha", "code"),
    [
        ("other", SHA_A, "bundle_provenance_mismatch"),
        ("run-1", SHA_B, "bundle_provenance_mismatch"),
        ("", SHA_A, "invalid_expected_provenance"),
        ("run-1", "bad", "invalid_expected_provenance"),
    ],
)
def test_compile_rejects_invalid_expected_provenance(
    tmp_path, expected_run_id, expected_sha, code
):
    graph_path, entrypoints_path = _write(tmp_path)

    with pytest.raises(GraphIndexCompilationError) as caught:
        compile_graph_index(
            graph_path,
            entrypoints_path,
            expected_run_id=expected_run_id,
            expected_canonical_sha256=expected_sha,
        )

    assert caught.value.code == code
    assert caught.value.source == "expected_provenance"


def test_compile_fails_closed_without_jsonschema(tmp_path, monkeypatch):
    graph_path, entrypoints_path = _write(tmp_path)
    monkeypatch.setattr(graph_source_validation, "jsonschema", None)

    with pytest.raises(GraphIndexCompilationError) as caught:
        compile_graph_index(graph_path, entrypoints_path)

    assert caught.value.as_dict() == {
        "code": "validation_unavailable",
        "message": "jsonschema is required for graph index compilation",
        "source": "architecture_graph",
        "errors": [],
    }


def test_schema_diagnostics_are_stable_json_paths(tmp_path):
    entrypoints = _entrypoints()
    entrypoints["entrypoints"][0] = {"path": "main.py", "unexpected": True}
    graph_path, entrypoints_path = _write(tmp_path, _graph(), entrypoints)

    diagnostics = []
    for _ in range(2):
        with pytest.raises(GraphIndexCompilationError) as caught:
            compile_graph_index(graph_path, entrypoints_path)
        diagnostics.append(caught.value.errors)

    assert diagnostics[0] == diagnostics[1]
    assert all(item.startswith("$") for item in diagnostics[0])


def test_graph_loader_keeps_existing_status_contract(tmp_path):
    bad_json = tmp_path / "bad.json"
    bad_json.write_text("{bad", encoding="utf-8")
    assert load_graph_index(tmp_path, "bad.json")["status"] == "invalid_json"
    assert load_graph_index(tmp_path, "missing.json")["status"] == "not_found"

    invalid = tmp_path / "invalid.json"
    invalid.write_text('{"distances": {}}', encoding="utf-8")
    assert load_graph_index(tmp_path, "invalid.json")["status"] == "invalid_schema"


def test_graph_loader_fails_closed_without_jsonschema(tmp_path, monkeypatch):
    graph_path = tmp_path / "graph-index.json"
    graph_path.write_text(json.dumps(_graph_index()), encoding="utf-8")
    monkeypatch.setattr(graph_index_module, "jsonschema", None)

    result = load_graph_index(tmp_path, graph_path.name)

    assert result == {"status": "validation_unavailable", "graph": None}


def test_graph_loader_fails_closed_without_schema_file(tmp_path, monkeypatch):
    graph_path = tmp_path / "graph-index.json"
    graph_path.write_text(json.dumps(_graph_index()), encoding="utf-8")
    monkeypatch.setattr(
        graph_index_module,
        "_GRAPH_INDEX_SCHEMA_PATH",
        tmp_path / "missing.schema.json",
    )

    result = load_graph_index(tmp_path, graph_path.name)

    assert result == {"status": "validation_unavailable", "graph": None}


def test_graph_loader_rejects_absolute_path(tmp_path):
    result = load_graph_index(tmp_path, str(tmp_path / "graph.json"))

    assert result == {"status": "invalid_path", "graph": None}
