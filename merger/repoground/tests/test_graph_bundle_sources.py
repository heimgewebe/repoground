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

    assert result.reason == "no eligible full-contact Python sources"
    graph = json.loads(result.graph_path.read_text(encoding="utf-8"))
    entrypoints = json.loads(result.entrypoints_path.read_text(encoding="utf-8"))
    assert graph["nodes"] == []
    assert entrypoints["entrypoints"] == []


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
