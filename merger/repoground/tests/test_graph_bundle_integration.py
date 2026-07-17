import builtins
import hashlib
import json
from pathlib import Path

import pytest

from merger.repoground.architecture import bundle_sources
from merger.repoground.architecture.bundle_sources import BundleGraphSourceError
from merger.repoground.architecture.graph_index import GraphIndexCompilationError
from merger.repoground.core.constants import ArtifactRole
from merger.repoground.core.merge import build_derived_artifacts
from merger.repoground.retrieval.review_eval import SnapshotRetrievalMeasurementError


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


def test_graph_bundle_auto_produces_bound_sources_for_single_repo(tmp_path):
    base, dump_sha, args = _setup(tmp_path)
    base.with_suffix(".architecture_graph.json").unlink()
    base.with_suffix(".entrypoints.json").unlink()
    repo_root = tmp_path / "repo1"
    repo_root.mkdir()
    (repo_root / "main.py").write_text(
        "if __name__ == '__main__':\n    print('hello')\n",
        encoding="utf-8",
    )
    args["chunk_path"].write_text(
        json.dumps(
            {
                "repo": "repo1",
                "path": "main.py",
                "source_status": "full",
                "truncated": False,
                "source_range": {"status": "declared"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    args["repo_summaries"] = [{"root": repo_root, "name": "repo1"}]

    derived_paths = build_derived_artifacts(**args)

    graph_source = base.with_suffix(".architecture_graph.json")
    entrypoint_source = base.with_suffix(".entrypoints.json")
    graph_index = base.with_suffix(".graph_index.json")
    assert graph_source in derived_paths
    assert entrypoint_source in derived_paths
    assert graph_index in derived_paths
    graph = json.loads(graph_source.read_text(encoding="utf-8"))
    entrypoints = json.loads(entrypoint_source.read_text(encoding="utf-8"))
    assert graph["run_id"] == entrypoints["run_id"] == "test_run"
    assert graph["canonical_dump_index_sha256"] == dump_sha
    assert entrypoints["canonical_dump_index_sha256"] == dump_sha
    file_nodes = [node for node in graph["nodes"] if node["kind"] == "file"]
    assert [(node["path"], node["repo"]) for node in file_nodes] == [
        ("main.py", "repo1")
    ]
    compiled = json.loads(graph_index.read_text(encoding="utf-8"))
    assert compiled["distances"]["file:main.py"] == 0
    derived = json.loads(
        base.with_suffix(".derived_index.json").read_text(encoding="utf-8")
    )
    assert ArtifactRole.ARCHITECTURE_GRAPH_JSON.value in derived["artifacts"]
    assert ArtifactRole.ENTRYPOINTS_JSON.value in derived["artifacts"]


def test_graph_bundle_propagates_source_production_failure(tmp_path, monkeypatch):
    base, _, args = _setup(tmp_path)

    def fail_production(**kwargs):
        raise BundleGraphSourceError("simulated source production failure")

    monkeypatch.setattr(bundle_sources, "ensure_bundle_graph_sources", fail_production)

    with pytest.raises(BundleGraphSourceError, match="simulated source production"):
        build_derived_artifacts(**args)

    assert not base.with_suffix(".graph_index.json").exists()


def test_derived_snapshot_prefers_repository_review_goldset(tmp_path):
    base, _, args = _setup(tmp_path)
    repo_root = tmp_path / "repo1"
    goldset = repo_root / "docs/retrieval/review_queries.v1.json"
    goldset.parent.mkdir(parents=True)
    source_goldset = (
        Path(__file__).resolve().parents[3]
        / "docs/retrieval/review_queries.v1.json"
    )
    goldset.write_bytes(source_goldset.read_bytes())
    args["repo_summaries"] = [{"root": repo_root, "name": "repo1"}]

    derived_paths = build_derived_artifacts(**args)

    eval_path = base.with_suffix(".retrieval_eval.json")
    assert eval_path in derived_paths
    report = json.loads(eval_path.read_text(encoding="utf-8"))
    assert report["benchmark"]["canonical"] is True
    assert report["benchmark"]["query_source"] == (
        "docs/retrieval/review_queries.v1.json"
    )
    assert report["benchmark"]["evaluation_mode"] == "default_lexical"
    assert report["benchmark"]["default_promotion_allowed"] is False
    assert report["metrics"]["question_hits"] + report["metrics"][
        "question_misses"
    ] == 20
    assert "expected_target_recall@10" in report["metrics"]


def test_derived_snapshot_does_not_swallow_invalid_canonical_goldset(tmp_path):
    _, _, args = _setup(tmp_path)
    repo_root = tmp_path / "repo1"
    goldset = repo_root / "docs/retrieval/review_queries.v1.json"
    goldset.parent.mkdir(parents=True)
    goldset.write_text("[]", encoding="utf-8")
    args["repo_summaries"] = [{"root": repo_root, "name": "repo1"}]

    with pytest.raises(
        SnapshotRetrievalMeasurementError, match="canonical_goldset_invalid"
    ):
        build_derived_artifacts(**args)


def test_derived_snapshot_degrades_when_jsonschema_is_unavailable(
    tmp_path, monkeypatch
):
    base, _, args = _setup(tmp_path)
    repo_root = tmp_path / "repo1"
    goldset = repo_root / "docs/retrieval/review_queries.v1.json"
    goldset.parent.mkdir(parents=True)
    source_goldset = (
        Path(__file__).resolve().parents[3]
        / "docs/retrieval/review_queries.v1.json"
    )
    goldset.write_bytes(source_goldset.read_bytes())
    args["repo_summaries"] = [{"root": repo_root, "name": "repo1"}]

    original_import = builtins.__import__

    def import_without_jsonschema(name, *import_args, **import_kwargs):
        if name == "jsonschema":
            raise ImportError("simulated Pythonista runtime without jsonschema")
        return original_import(name, *import_args, **import_kwargs)

    monkeypatch.setattr(builtins, "__import__", import_without_jsonschema)

    derived_paths = build_derived_artifacts(**args)

    sqlite_path = args["chunk_path"].with_suffix(".index.sqlite")
    eval_path = base.with_suffix(".retrieval_eval.json")
    graph_path = base.with_suffix(".graph_index.json")
    assert sqlite_path in derived_paths
    assert eval_path not in derived_paths
    assert not eval_path.exists()
    assert graph_path in derived_paths

