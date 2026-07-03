import argparse
import json

import pytest

from merger.lenskit.architecture import graph_source_validation
from merger.lenskit.architecture.graph_index import GraphIndexCompilationError, compile_graph_index
from merger.lenskit.cli import cmd_architecture
from merger.lenskit.tests.graph_compiler_fixtures import entrypoints_document, graph_document


def write_sources(tmp_path, graph=None, entrypoints=None):
    graph_path = tmp_path / "graph.json"
    entrypoints_path = tmp_path / "entrypoints.json"
    graph_path.write_text(json.dumps(graph or graph_document()), encoding="utf-8")
    entrypoints_path.write_text(json.dumps(entrypoints or entrypoints_document()), encoding="utf-8")
    return graph_path, entrypoints_path


def test_invalid_graph_schema(tmp_path):
    graph = graph_document()
    graph.pop("coverage")
    with pytest.raises(GraphIndexCompilationError) as caught:
        compile_graph_index(*write_sources(tmp_path, graph=graph))
    assert (caught.value.code, caught.value.source) == ("invalid_schema", "architecture_graph")


def test_invalid_entrypoints_schema(tmp_path):
    entrypoints = entrypoints_document()
    entrypoints["entrypoints"][0].pop("evidence_level")
    with pytest.raises(GraphIndexCompilationError) as caught:
        compile_graph_index(*write_sources(tmp_path, entrypoints=entrypoints))
    assert (caught.value.code, caught.value.source) == ("invalid_schema", "entrypoints")


def test_compiler_requires_jsonschema(tmp_path, monkeypatch):
    paths = write_sources(tmp_path)
    monkeypatch.setattr(graph_source_validation, "jsonschema", None)
    with pytest.raises(GraphIndexCompilationError) as caught:
        compile_graph_index(*paths)
    assert caught.value.code == "validation_unavailable"


@pytest.mark.parametrize("target", ["graph", "entrypoints"])
def test_run_id_must_be_nonempty(tmp_path, target):
    graph = graph_document()
    entrypoints = entrypoints_document()
    (graph if target == "graph" else entrypoints)["run_id"] = ""
    with pytest.raises(GraphIndexCompilationError) as caught:
        compile_graph_index(*write_sources(tmp_path, graph, entrypoints))
    assert caught.value.code == "invalid_provenance"


def test_source_provenance_must_match(tmp_path):
    with pytest.raises(GraphIndexCompilationError) as caught:
        compile_graph_index(*write_sources(tmp_path, entrypoints=entrypoints_document(run_id="other")))
    assert caught.value.code == "provenance_mismatch"

    with pytest.raises(GraphIndexCompilationError) as caught:
        compile_graph_index(*write_sources(tmp_path, entrypoints=entrypoints_document(canonical_sha="1" * 64)))
    assert caught.value.code == "provenance_mismatch"


def test_expected_bundle_provenance_must_match(tmp_path):
    paths = write_sources(tmp_path)
    with pytest.raises(GraphIndexCompilationError) as caught:
        compile_graph_index(*paths, expected_run_id="other")
    assert caught.value.code == "bundle_provenance_mismatch"

    with pytest.raises(GraphIndexCompilationError) as caught:
        compile_graph_index(*paths, expected_canonical_sha256="1" * 64)
    assert caught.value.code == "bundle_provenance_mismatch"


def test_error_has_stable_machine_shape():
    error = GraphIndexCompilationError("provenance_mismatch", "mismatch", source="provenance", errors=["a", "b"])
    assert error.as_dict() == {
        "code": "provenance_mismatch",
        "message": "mismatch",
        "source": "provenance",
        "errors": ["a", "b"],
    }


def test_cli_reports_structured_failure(tmp_path, capsys):
    graph = graph_document()
    graph.pop("coverage")
    graph_path, entrypoints_path = write_sources(tmp_path, graph=graph)
    args = argparse.Namespace(
        entrypoints=False,
        import_graph=False,
        graph_index=True,
        graph_in=str(graph_path),
        entrypoints_in=str(entrypoints_path),
        repo=str(tmp_path),
    )
    assert cmd_architecture.run_architecture_cmd(args) == 2
    captured = capsys.readouterr()
    payload = json.loads(captured.err)
    assert payload["code"] == "invalid_schema"
    assert payload["source"] == "architecture_graph"
    assert "Traceback" not in captured.err
