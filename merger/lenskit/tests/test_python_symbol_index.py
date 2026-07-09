import json
from pathlib import Path

import jsonschema

from merger.lenskit.architecture.symbol_index import (
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


def test_python_symbol_index_skips_operator_and_cache_directories(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "real.py").write_text("def real_symbol():\n    return None\n", encoding="utf-8")
    hidden = tmp_path / ".grabowski" / "worktrees" / "copy"
    hidden.mkdir(parents=True)
    (hidden / "shadow.py").write_text("def shadow_symbol():\n    return None\n", encoding="utf-8")
    cache = tmp_path / ".pytest_cache"
    cache.mkdir()
    (cache / "cached.py").write_text("def cached_symbol():\n    return None\n", encoding="utf-8")

    symbols, skipped_count, skipped_errors = extract_python_symbols(tmp_path)

    assert skipped_count == 0
    assert skipped_errors == []
    assert [item["qualified_name"] for item in symbols] == ["real_symbol"]
    assert {item["path"] for item in symbols} == {"pkg/real.py"}


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
