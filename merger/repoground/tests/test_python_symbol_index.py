import json
from pathlib import Path

import jsonschema
import pytest

from merger.repoground.architecture.symbol_index import (
    EXCLUDED_DIRS,
    extract_python_symbols,
    generate_symbol_index_document,
)


def test_python_symbol_index_extracts_deterministic_symbols(tmp_path):
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "__init__.py").write_text("class Root:\n    pass\n", encoding="utf-8")
    (package / "mod.py").write_text(
        "def top():\n"
        "    def inner():\n"
        "        return 1\n"
        "    return inner()\n\n"
        "class Thing:\n"
        "    @property\n"
        "    def value(self):\n"
        "        return 42\n\n"
        "    async def load(self):\n"
        "        return None\n",
        encoding="utf-8",
    )
    (package / "bad.py").write_text("def broken(:\n", encoding="utf-8")

    symbols, skipped_count, skipped_errors = extract_python_symbols(tmp_path)

    assert skipped_count == 1
    assert any("pkg/bad.py" in error for error in skipped_errors)
    assert [(item["path"], item["qualified_name"], item["kind"]) for item in symbols] == [
        ("pkg/__init__.py", "Root", "class"),
        ("pkg/mod.py", "top", "function"),
        ("pkg/mod.py", "top.inner", "function"),
        ("pkg/mod.py", "Thing", "class"),
        ("pkg/mod.py", "Thing.value", "function"),
        ("pkg/mod.py", "Thing.load", "async_function"),
    ]

    top = next(item for item in symbols if item["qualified_name"] == "top")
    assert top["range_ref"] == "file:pkg/mod.py#L1-L4"
    assert top["module"] == "pkg.mod"

    value = next(item for item in symbols if item["qualified_name"] == "Thing.value")
    assert value["decorators"] == ["property"]


def test_python_symbol_index_skips_all_excluded_directories(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "real.py").write_text("def real_symbol():\n    return None\n", encoding="utf-8")

    for excluded_dir in sorted(EXCLUDED_DIRS):
        shadow_dir = tmp_path / excluded_dir / "nested" / "copy"
        shadow_dir.mkdir(parents=True)
        symbol_name = f"shadow_{excluded_dir.replace('.', '_').replace('-', '_')}"
        (shadow_dir / "shadow.py").write_text(f"def {symbol_name}():\n    return None\n", encoding="utf-8")

    symbols, skipped_count, skipped_errors = extract_python_symbols(tmp_path)

    assert skipped_count == 0
    assert skipped_errors == []
    assert [item["qualified_name"] for item in symbols] == ["real_symbol"]
    assert {item["path"] for item in symbols} == {"pkg/real.py"}


def test_python_symbol_index_does_not_skip_dot_directories_by_default(tmp_path):
    scripts = tmp_path / ".github" / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "tool.py").write_text("def github_tool():\n    return None\n", encoding="utf-8")

    symbols, skipped_count, skipped_errors = extract_python_symbols(tmp_path)

    assert skipped_count == 0
    assert skipped_errors == []
    assert [(item["path"], item["qualified_name"]) for item in symbols] == [
        (".github/scripts/tool.py", "github_tool"),
    ]


def test_python_symbol_index_does_not_follow_directory_symlinks(tmp_path, tmp_path_factory):
    target = tmp_path_factory.mktemp("symbol-index-symlink-target")
    (target / "linked.py").write_text("def linked_symbol():\n    return None\n", encoding="utf-8")
    link = tmp_path / "linked_dir"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks are not available on this platform: {exc}")

    (tmp_path / "real.py").write_text("def real_symbol():\n    return None\n", encoding="utf-8")

    symbols, skipped_count, skipped_errors = extract_python_symbols(tmp_path)

    assert skipped_count == 0
    assert skipped_errors == []
    assert [item["qualified_name"] for item in symbols] == ["real_symbol"]


def test_python_symbol_index_document_matches_schema(tmp_path):
    (tmp_path / "tool.py").write_text("async def main():\n    return None\n", encoding="utf-8")
    doc = generate_symbol_index_document(tmp_path, "run-1", "a" * 64)

    schema_path = Path(__file__).parent.parent / "contracts" / "python-symbol-index.v1.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    jsonschema.validate(instance=doc, schema=schema)

    assert doc["kind"] == "lenskit.python_symbol_index"
    assert doc["language"] == "python"
    assert doc["symbols"][0]["qualified_name"] == "main"
    assert "runtime_behavior" in doc["does_not_establish"]
