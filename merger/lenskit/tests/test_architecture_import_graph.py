import json
from pathlib import Path

import jsonschema
import pytest

from merger.lenskit.architecture.import_graph import generate_import_graph_document
from merger.lenskit.cli.main import main


def test_import_graph_generator():
    repo_root = Path(__file__).parent / "fixtures" / "architecture_import_graph"
    run_id = "test_run_123"
    canonical_sha256 = "0" * 64

    doc = generate_import_graph_document(repo_root, run_id, canonical_sha256)

    schema_path = (
        Path(__file__).parent.parent
        / "contracts"
        / "architecture.graph.v1.schema.json"
    )
    with schema_path.open(encoding="utf-8") as handle:
        schema = json.load(handle)

    jsonschema.validate(instance=doc, schema=schema)

    expected_path = repo_root / "expected.graph.json"
    with expected_path.open(encoding="utf-8") as handle:
        expected = json.load(handle)

    doc["generated_at"] = "2024-01-01T00:00:00Z"
    expected["run_id"] = run_id

    assert doc == expected


def test_ambiguous_local_module_name_remains_external(tmp_path):
    (tmp_path / "foo.py").write_text("VALUE = 1\n", encoding="utf-8")
    package = tmp_path / "foo"
    package.mkdir()
    (package / "__init__.py").write_text("VALUE = 2\n", encoding="utf-8")
    (tmp_path / "consumer.py").write_text("import foo\n", encoding="utf-8")

    doc = generate_import_graph_document(tmp_path, "run", "0" * 64)
    edges = {(edge["src"], edge["dst"]) for edge in doc["edges"]}

    assert ("file:consumer.py", "module:foo") in edges
    assert ("file:consumer.py", "file:foo.py") not in edges
    assert ("file:consumer.py", "file:foo/__init__.py") not in edges


def test_test_directory_layer_precedes_nested_core_segment(tmp_path):
    target = tmp_path / "tests" / "core" / "service.py"
    target.parent.mkdir(parents=True)
    target.write_text("VALUE = 1\n", encoding="utf-8")

    doc = generate_import_graph_document(tmp_path, "run", "0" * 64)
    node = next(item for item in doc["nodes"] if item["path"] == "tests/core/service.py")

    assert node["layer"] == "test"


def test_cli_architecture_mutually_exclusive(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main(["architecture", "--entrypoints", "--import-graph"])

    assert exc_info.value.code != 0
    captured = capsys.readouterr()
    assert "not allowed with argument" in captured.err
