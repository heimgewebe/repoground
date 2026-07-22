import json
from pathlib import Path

import jsonschema
import pytest

from merger.repoground.architecture.import_graph import (
    SourceRootError,
    generate_import_graph_document,
)
from merger.repoground.cli.main import main


def _without_generated_at(document):
    comparable = dict(document)
    comparable.pop("generated_at", None)
    return comparable


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


def test_empty_source_roots_preserve_default_graph():
    repo_root = Path(__file__).parent / "fixtures" / "architecture_import_graph"

    default = generate_import_graph_document(repo_root, "run", "0" * 64)
    explicit_empty = generate_import_graph_document(
        repo_root,
        "run",
        "0" * 64,
        source_roots=(),
    )

    assert _without_generated_at(default) == _without_generated_at(explicit_empty)


def test_explicit_source_root_resolves_unique_local_module(tmp_path):
    target = tmp_path / "src" / "acme" / "service.py"
    target.parent.mkdir(parents=True)
    target.write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "consumer.py").write_text(
        "from acme.service import VALUE\n",
        encoding="utf-8",
    )

    doc = generate_import_graph_document(
        tmp_path,
        "run",
        "0" * 64,
        source_roots=("src",),
    )
    edges = {(edge["src"], edge["dst"]) for edge in doc["edges"]}

    assert ("file:consumer.py", "file:src/acme/service.py") in edges


def test_source_root_order_does_not_resolve_competing_modules(tmp_path):
    for root in ("left", "right"):
        target = tmp_path / root / "mod.py"
        target.parent.mkdir()
        target.write_text(f"ROOT = {root!r}\n", encoding="utf-8")
    (tmp_path / "consumer.py").write_text("import mod\n", encoding="utf-8")

    left_first = generate_import_graph_document(
        tmp_path,
        "run",
        "0" * 64,
        source_roots=("left", "right"),
    )
    right_first = generate_import_graph_document(
        tmp_path,
        "run",
        "0" * 64,
        source_roots=("right", "left"),
    )
    edges = {(edge["src"], edge["dst"]) for edge in left_first["edges"]}

    assert _without_generated_at(left_first) == _without_generated_at(right_first)
    assert ("file:consumer.py", "module:mod") in edges
    assert ("file:consumer.py", "file:left/mod.py") not in edges
    assert ("file:consumer.py", "file:right/mod.py") not in edges


@pytest.mark.parametrize(
    "source_root",
    ["", ".", "./src", "../src", "src/../pkg", "/src", "src\\pkg", "src//pkg", "src/"],
)
def test_noncanonical_source_roots_fail_closed(tmp_path, source_root):
    with pytest.raises(SourceRootError):
        generate_import_graph_document(
            tmp_path,
            "run",
            "0" * 64,
            source_roots=(source_root,),
        )


def test_duplicate_and_missing_source_roots_fail_closed(tmp_path):
    (tmp_path / "src").mkdir()

    with pytest.raises(SourceRootError, match="duplicate source root"):
        generate_import_graph_document(
            tmp_path,
            "run",
            "0" * 64,
            source_roots=("src", "src"),
        )
    with pytest.raises(SourceRootError, match="not an existing directory"):
        generate_import_graph_document(
            tmp_path,
            "run",
            "0" * 64,
            source_roots=("missing",),
        )


def test_source_root_symlink_must_remain_inside_repository(tmp_path):
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    (tmp_path / "escape").symlink_to(outside, target_is_directory=True)

    with pytest.raises(SourceRootError, match="escapes repository"):
        generate_import_graph_document(
            tmp_path,
            "run",
            "0" * 64,
            source_roots=("escape",),
        )


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


def test_graph_includes_bounded_cross_language_file_inventory(tmp_path):
    files = {
        ".github/workflows/ci.yml": "name: ci\n",
        "apps/api/migrations/001.sql": "select 1;\n",
        "apps/api/src/lib.rs": "pub fn run() {}\n",
        "apps/web/src/Component.svelte": "<div />\n",
        "apps/web/src/Component.test.ts": "test('x', () => {})\n",
        "docs/guide.md": "# Guide\n",
        "config/settings.toml": "enabled = true\n",
        "build/legacy.py": "import os\n",
        ".cache/ignored.ts": "export const ignored = true\n",
        "vendor.bin": "ignored\n",
    }
    for relative, content in files.items():
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    doc = generate_import_graph_document(tmp_path, "run", "0" * 64)
    nodes = {item["path"]: item for item in doc["nodes"] if item["kind"] == "file"}

    assert nodes[".github/workflows/ci.yml"]["language"] == "yaml"
    assert nodes["apps/api/migrations/001.sql"]["language"] == "sql"
    assert nodes["apps/api/src/lib.rs"]["language"] == "rust"
    assert nodes["apps/web/src/Component.svelte"]["language"] == "svelte"
    assert nodes["apps/web/src/Component.test.ts"]["language"] == "typescript"
    assert nodes["apps/web/src/Component.test.ts"]["is_test"] is True
    assert nodes["docs/guide.md"]["language"] == "markdown"
    assert nodes["config/settings.toml"]["language"] == "toml"
    assert nodes["build/legacy.py"]["language"] == "python"
    assert ".cache/ignored.ts" not in nodes
    assert "vendor.bin" not in nodes
    non_python_ids = {
        f"file:{path}"
        for path, node in nodes.items()
        if node.get("language") != "python"
    }
    assert not any(
        edge["src"] in non_python_ids or edge["dst"] in non_python_ids
        for edge in doc["edges"]
    )


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
