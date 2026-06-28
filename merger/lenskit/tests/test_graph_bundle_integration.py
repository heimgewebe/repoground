import hashlib
import json

import pytest

from merger.lenskit.architecture.graph_index import GraphIndexCompilationError
from merger.lenskit.core.constants import ArtifactRole
from merger.lenskit.core.merge import build_derived_artifacts


def _source_documents(run_id: str, sha256: str):
    graph = {
        "kind": "lenskit.architecture.graph",
        "version": "1.0",
        "run_id": run_id,
        "canonical_dump_index_sha256": sha256,
        "nodes": [
            {
                "node_id": "file:main.py",
                "kind": "file",
                "path": "main.py",
                "repo": "repo1",
                "is_test": False,
            }
        ],
        "edges": [],
        "coverage": {
            "files_seen": 1,
            "files_parsed": 1,
            "edge_counts_by_type": {},
            "unknown_layer_share": 1.0,
        },
    }
    entrypoints = {
        "kind": "lenskit.entrypoints",
        "version": "1.0",
        "run_id": run_id,
        "canonical_dump_index_sha256": sha256,
        "entrypoints": [
            {
                "id": "path:main.py",
                "type": "cli",
                "path": "main.py",
                "evidence_level": "S1",
            }
        ],
    }
    return graph, entrypoints


def _setup(tmp_path, *, source_run_id="test_run"):
    hub = tmp_path / "hub"
    (hub / "docs" / "retrieval").mkdir(parents=True)
    (hub / "docs" / "retrieval" / "queries.md").write_text(
        '1. **"test"**\n   *Expected:* `main.py`\n', encoding="utf-8"
    )
    base = tmp_path / "dummy_base"
    dump_index = base.with_suffix(".dump_index.json")
    dump_index.write_text('{"run_id":"test_run"}', encoding="utf-8")
    dump_sha = hashlib.sha256(dump_index.read_bytes()).hexdigest()
    chunk_index = base.with_suffix(".chunk_index.jsonl")
    chunk_index.write_text("", encoding="utf-8")
    graph, entrypoints = _source_documents(source_run_id, dump_sha)
    base.with_suffix(".architecture_graph.json").write_text(
        json.dumps(graph), encoding="utf-8"
    )
    base.with_suffix(".entrypoints.json").write_text(
        json.dumps(entrypoints), encoding="utf-8"
    )

    def base_name_func(part_suffix=""):
        return base

    args = {
        "dump_index_path": dump_index,
        "chunk_path": chunk_index,
        "base_name_func": base_name_func,
        "run_id": "test_run",
        "hub_path": hub,
        "generator_info": {"version": "test", "config_sha256": "0" * 64},
        "repo_names": ["repo1"],
        "debug": False,
    }
    return base, dump_sha, args


def test_graph_bundle_integration_positive(tmp_path):
    base, dump_sha, args = _setup(tmp_path)
    derived_paths = build_derived_artifacts(**args)

    graph_path = base.with_suffix(".graph_index.json")
    assert graph_path in derived_paths
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    assert graph["run_id"] == "test_run"
    assert graph["canonical_dump_index_sha256"] == dump_sha
    assert graph["distances"]["file:main.py"] == 0

    derived = json.loads(
        base.with_suffix(".derived_index.json").read_text(encoding="utf-8")
    )
    assert derived["artifacts"][ArtifactRole.GRAPH_INDEX_JSON.value]["path"] == graph_path.name


def test_graph_bundle_fails_closed_on_provenance_mismatch(tmp_path):
    base, _, args = _setup(tmp_path, source_run_id="other-run")

    with pytest.raises(GraphIndexCompilationError) as caught:
        build_derived_artifacts(**args)

    assert caught.value.code == "bundle_provenance_mismatch"
    assert not base.with_suffix(".graph_index.json").exists()


@pytest.mark.parametrize(
    ("missing_suffix", "expected_source"),
    [
        (".architecture_graph.json", "architecture_graph"),
        (".entrypoints.json", "entrypoints"),
    ],
)
def test_graph_bundle_fails_closed_with_partial_sources(
    tmp_path,
    missing_suffix,
    expected_source,
):
    base, _, args = _setup(tmp_path)
    base.with_suffix(missing_suffix).unlink()

    with pytest.raises(GraphIndexCompilationError) as caught:
        build_derived_artifacts(**args)

    assert caught.value.code == "source_not_found"
    assert caught.value.source == expected_source
    assert not base.with_suffix(".graph_index.json").exists()


def test_graph_bundle_fallback_without_sources(tmp_path):
    base, _, args = _setup(tmp_path)
    base.with_suffix(".architecture_graph.json").unlink()
    base.with_suffix(".entrypoints.json").unlink()

    derived_paths = build_derived_artifacts(**args)

    graph_path = base.with_suffix(".graph_index.json")
    assert graph_path not in derived_paths
    assert not graph_path.exists()
    derived = json.loads(
        base.with_suffix(".derived_index.json").read_text(encoding="utf-8")
    )
    assert ArtifactRole.GRAPH_INDEX_JSON.value not in derived["artifacts"]
