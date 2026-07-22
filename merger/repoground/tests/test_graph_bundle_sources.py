import json

import pytest

from merger.repoground.architecture import bundle_sources
from merger.repoground.architecture.bundle_sources import (
    BundleGraphSourceError,
    ensure_bundle_graph_sources,
)


SHA = "a" * 64


def _repo(tmp_path, name="repo1"):
    root = tmp_path / name
    root.mkdir()
    (root / "main.py").write_text(
        "import os\n\nif __name__ == '__main__':\n    print(os.name)\n",
        encoding="utf-8",
    )
    (root / "excluded.py").write_text(
        "if __name__ == '__main__':\n    print('excluded')\n",
        encoding="utf-8",
    )
    return {"root": root, "name": name}


def _chunk_index(tmp_path, repo="repo1", records=None):
    path = tmp_path / f"{repo}.chunk_index.jsonl"
    if records is None:
        records = [
            {
                "repo": repo,
                "path": "main.py",
                "source_status": "full",
                "truncated": False,
                "source_range": {"status": "declared"},
            }
        ]
    path.write_text(
        "".join(json.dumps(record) + "\n" for record in records),
        encoding="utf-8",
    )
    return path


def _ensure(tmp_path, *, summaries=None, chunk_index=None):
    return ensure_bundle_graph_sources(
        base_path=tmp_path / "bundle",
        chunk_index_path=chunk_index or _chunk_index(tmp_path),
        repo_summaries=summaries or [_repo(tmp_path)],
        run_id="run-1",
        canonical_dump_index_sha256=SHA,
        generated_at="2026-06-28T12:00:00Z",
    )


def test_produces_sources_from_full_contact_retrieval_paths(tmp_path):
    result = _ensure(tmp_path)

    assert result.status == "produced"
    assert result.reason is None
    graph = json.loads(result.graph_path.read_text(encoding="utf-8"))
    entrypoints = json.loads(result.entrypoints_path.read_text(encoding="utf-8"))
    assert graph["run_id"] == entrypoints["run_id"] == "run-1"
    assert graph["canonical_dump_index_sha256"] == SHA
    assert entrypoints["canonical_dump_index_sha256"] == SHA
    assert graph["generated_at"] == "2026-06-28T12:00:00Z"
    file_nodes = [node for node in graph["nodes"] if node["kind"] == "file"]
    assert {node["path"] for node in file_nodes} == {"main.py"}
    assert {node["repo"] for node in file_nodes} == {"repo1"}
    assert [item["path"] for item in entrypoints["entrypoints"]] == ["main.py"]


def test_produces_cross_language_inventory_from_full_contact_retrieval_paths(tmp_path):
    repo = _repo(tmp_path)
    root = repo["root"]
    sources = {
        "apps/web/Component.svelte": "<div />\n",
        "apps/web/Component.test.ts": "test('x', () => {})\n",
        "apps/api/migrations/001.sql": "select 1;\n",
        ".github/workflows/ci.yml": "name: ci\n",
        "derived.graph.json": "{}\n",
    }
    for relative, content in sources.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    records = [
        {
            "repo": "repo1",
            "path": path,
            "source_status": "full",
            "truncated": False,
            "source_range": {"status": "declared"},
        }
        for path in ["main.py", *sources]
    ]
    result = _ensure(
        tmp_path,
        summaries=[repo],
        chunk_index=_chunk_index(tmp_path, records=records),
    )

    graph = json.loads(result.graph_path.read_text(encoding="utf-8"))
    entrypoints = json.loads(result.entrypoints_path.read_text(encoding="utf-8"))
    file_nodes = {
        node["path"]: node
        for node in graph["nodes"]
        if node["kind"] == "file"
    }

    assert set(file_nodes) == {
        ".github/workflows/ci.yml",
        "apps/api/migrations/001.sql",
        "apps/web/Component.svelte",
        "apps/web/Component.test.ts",
        "main.py",
    }
    assert file_nodes["apps/web/Component.test.ts"]["is_test"] is True
    assert file_nodes["apps/web/Component.svelte"]["language"] == "svelte"
    assert file_nodes["apps/api/migrations/001.sql"]["language"] == "sql"
    assert file_nodes[".github/workflows/ci.yml"]["language"] == "yaml"
    non_python_ids = {
        node["node_id"]
        for node in file_nodes.values()
        if node["language"] != "python"
    }
    assert not any(
        edge["src"] in non_python_ids or edge["dst"] in non_python_ids
        for edge in graph["edges"]
    )
    assert [item["path"] for item in entrypoints["entrypoints"]] == ["main.py"]


def test_excludes_truncated_or_unverifiable_chunk_sources(tmp_path):
    repo = _repo(tmp_path)
    chunk_index = _chunk_index(
        tmp_path,
        records=[
            {
                "repo": "repo1",
                "path": "main.py",
                "source_status": "truncated",
                "truncated": True,
                "source_range": {"status": "unavailable"},
            },
            {
                "repo": "repo1",
                "path": "excluded.py",
                "source_status": "full",
                "truncated": False,
            },
        ],
    )

    result = _ensure(tmp_path, summaries=[repo], chunk_index=chunk_index)

    assert result.reason == "no eligible full-contact graph sources"
    graph = json.loads(result.graph_path.read_text(encoding="utf-8"))
    entrypoints = json.loads(result.entrypoints_path.read_text(encoding="utf-8"))
    assert graph["nodes"] == []
    assert entrypoints["entrypoints"] == []


def test_redacted_cross_language_sources_do_not_bypass_source_range_boundary(tmp_path):
    repo = _repo(tmp_path)
    workflow = repo["root"] / ".github/workflows/ci.yml"
    workflow.parent.mkdir(parents=True, exist_ok=True)
    workflow.write_text("name: ci\n", encoding="utf-8")
    chunk_index = _chunk_index(
        tmp_path,
        records=[
            {
                "repo": "repo1",
                "path": ".github/workflows/ci.yml",
                "source_status": "full",
                "truncated": False,
                "source_range": {"status": "unavailable"},
            }
        ],
    )

    result = _ensure(tmp_path, summaries=[repo], chunk_index=chunk_index)

    graph = json.loads(result.graph_path.read_text(encoding="utf-8"))
    assert result.reason == "no eligible full-contact graph sources"
    assert not any(
        node.get("path") == ".github/workflows/ci.yml"
        for node in graph["nodes"]
    )


def test_skips_automatic_production_for_multi_repo(tmp_path):
    summaries = [_repo(tmp_path, "repo1"), _repo(tmp_path, "repo2")]

    result = _ensure(tmp_path, summaries=summaries)

    assert result.status == "skipped"
    assert result.reason == "multi-repo graph identity is out of scope"
    assert not result.graph_path.exists()
    assert not result.entrypoints_path.exists()


def test_preserves_partial_pair_for_fail_closed_compiler(tmp_path):
    base = tmp_path / "bundle"
    graph_path = base.with_suffix(".architecture_graph.json")
    graph_path.write_text("{}", encoding="utf-8")

    result = _ensure(tmp_path)

    assert result.status == "partial"
    assert graph_path.read_text(encoding="utf-8") == "{}"
    assert not result.entrypoints_path.exists()


def test_invalid_chunk_index_fails_closed(tmp_path):
    chunk_index = tmp_path / "bad.chunk_index.jsonl"
    chunk_index.write_text("{bad\n", encoding="utf-8")

    with pytest.raises(BundleGraphSourceError, match="invalid chunk index JSON"):
        _ensure(tmp_path, chunk_index=chunk_index)

    assert not (tmp_path / "bundle.architecture_graph.json").exists()
    assert not (tmp_path / "bundle.entrypoints.json").exists()


def test_write_failure_removes_partial_pair(tmp_path, monkeypatch):
    original = bundle_sources._write_json_atomic
    calls = 0

    def fail_second_write(path, payload):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated write failure")
        original(path, payload)

    monkeypatch.setattr(bundle_sources, "_write_json_atomic", fail_second_write)

    with pytest.raises(BundleGraphSourceError, match="failed to produce"):
        _ensure(tmp_path)

    assert not (tmp_path / "bundle.architecture_graph.json").exists()
    assert not (tmp_path / "bundle.entrypoints.json").exists()
