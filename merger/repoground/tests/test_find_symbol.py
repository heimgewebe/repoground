"""find_symbol MCP tool + exact-first ranking in the shared symbol search.

find_symbol is the navigation primitive ("where is X defined?") that content
retrieval (ask_context) does not provide. It reuses the existing
``search_symbol_index`` core, which now ranks exact name matches before
substring matches so a definition lookup surfaces the symbol itself first.
"""
import hashlib
import json
from pathlib import Path

from merger.repoground.core import mcp_tools
from merger.repoground.core.bundle_access import search_symbol_index


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _symbol_bundle(tmp_path: Path) -> Path:
    symbol_index = tmp_path / "demo.python_symbol_index.json"
    symbol_index.write_text(
        json.dumps(
            {
                "kind": "lenskit.python_symbol_index",
                "version": "1.0",
                "run_id": "run-1",
                "canonical_dump_index_sha256": "a" * 64,
                "language": "python",
                "symbol_kinds": ["class", "function", "async_function"],
                "symbols": [
                    # A substring match declared BEFORE the exact match, to prove
                    # exact-first ranking reorders regardless of index position.
                    {
                        "id": "py:pkg:mod.py:function:run_pipeline",
                        "kind": "function",
                        "name": "run_pipeline",
                        "qualified_name": "run_pipeline",
                        "module": "pkg.mod",
                        "path": "pkg/mod.py",
                        "start_line": 3,
                        "end_line": 5,
                        "range_ref": "file:pkg/mod.py#L3-L5",
                    },
                    {
                        "id": "py:pkg:mod.py:function:run",
                        "kind": "function",
                        "name": "run",
                        "qualified_name": "run",
                        "module": "pkg.mod",
                        "path": "pkg/mod.py",
                        "start_line": 8,
                        "end_line": 10,
                        "range_ref": "file:pkg/mod.py#L8-L10",
                    },
                    {
                        "id": "py:pkg:mod.py:class:Runner",
                        "kind": "class",
                        "name": "Runner",
                        "qualified_name": "Runner",
                        "module": "pkg.mod",
                        "path": "pkg/mod.py",
                        "start_line": 13,
                        "end_line": 20,
                        "range_ref": "file:pkg/mod.py#L13-L20",
                    },
                ],
                "skipped_files_count": 0,
                "skipped_errors": [],
                "does_not_establish": ["call_graph_completeness"],
            }
        ),
        encoding="utf-8",
    )
    manifest = tmp_path / "demo.bundle.manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "kind": "repolens.bundle.manifest",
                "run_id": "run-1",
                "artifacts": [
                    {
                        "role": "python_symbol_index_json",
                        "path": symbol_index.name,
                        "content_type": "application/json",
                        "bytes": symbol_index.stat().st_size,
                        "sha256": _sha(symbol_index),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return manifest


def test_exact_match_ranks_before_substring(tmp_path):
    manifest = _symbol_bundle(tmp_path)

    result = search_symbol_index(manifest, "run", k=10)

    assert result["status"] == "available"
    # 'run' matches run (exact), run_pipeline and Runner (substring); the exact
    # match wins the top slot even though it is declared after run_pipeline.
    names = [hit["qualified_name"] for hit in result["hits"]]
    assert names[0] == "run"
    assert set(names) == {"run", "run_pipeline", "Runner"}


def test_find_symbol_tool_locates_definition_with_range(tmp_path):
    manifest = _symbol_bundle(tmp_path)

    payload = mcp_tools.find_symbol(bundle_manifest=str(manifest), name="run")

    assert payload["kind"] == "repobrief.mcp.read_only_frontdoor"
    assert payload["tool"] == "find_symbol"
    assert payload["status"] == "available"
    assert payload["mutation_boundary"]["writes"] == []
    top = payload["result"]["hits"][0]
    assert top["qualified_name"] == "run"
    assert top["path"] == "pkg/mod.py"
    assert top["start_line"] == 8
    assert top["range_ref"] == "file:pkg/mod.py#L8-L10"


def test_find_symbol_tool_filters_by_kind(tmp_path):
    manifest = _symbol_bundle(tmp_path)

    payload = mcp_tools.find_symbol(
        bundle_manifest=str(manifest), name="run", kind="class"
    )

    hits = payload["result"]["hits"]
    assert [hit["qualified_name"] for hit in hits] == ["Runner"]


def test_find_symbol_tool_rejects_empty_name(tmp_path):
    manifest = _symbol_bundle(tmp_path)

    for empty in ("", "   "):
        payload = mcp_tools.find_symbol(bundle_manifest=str(manifest), name=empty)
        assert payload["status"] == "invalid"
        assert payload["result"]["error_code"] == "name_invalid"
        # Fails closed: no symbols are listed for an empty query.
        assert payload["result"]["hits"] == []
        assert payload["result"]["hit_count"] == 0


def test_find_symbol_tool_rejects_unknown_kind(tmp_path):
    manifest = _symbol_bundle(tmp_path)

    payload = mcp_tools.find_symbol(
        bundle_manifest=str(manifest), name="run", kind="macro"
    )

    assert payload["status"] == "invalid"
    assert payload["result"]["error_code"] == "kind_invalid"
    assert payload["result"]["hits"] == []


def test_find_symbol_tool_reports_missing_symbol_index(tmp_path):
    manifest = tmp_path / "empty.bundle.manifest.json"
    manifest.write_text(
        json.dumps({"kind": "repolens.bundle.manifest", "run_id": "x", "artifacts": []}),
        encoding="utf-8",
    )

    payload = mcp_tools.find_symbol(bundle_manifest=str(manifest), name="run")

    assert payload["status"] == "missing"
    assert payload["result"]["error_code"] == "python_symbol_index_json_missing"
