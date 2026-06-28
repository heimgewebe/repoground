import hashlib
import json

from merger.lenskit.core.constants import ArtifactRole


def _write_current_sources(base_path, run_id: str, sha256: str) -> None:
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
    base_path.with_suffix(".architecture_graph.json").write_text(
        json.dumps(graph), encoding="utf-8"
    )
    base_path.with_suffix(".entrypoints.json").write_text(
        json.dumps(entrypoints), encoding="utf-8"
    )


def test_bundle_manifest_graph_uses_current_bundle_provenance(tmp_path, monkeypatch):
    import merger.lenskit.core.merge as merge_mod
    from merger.lenskit.tests._test_constants import make_generator_info

    repo_dir = tmp_path / "repo1"
    repo_dir.mkdir()
    (repo_dir / "main.py").write_text("def main(): pass\n", encoding="utf-8")

    hub = tmp_path / "hub"
    hub.mkdir()
    merges_dir = hub / "merges"
    merges_dir.mkdir()
    docs_dir = hub / "docs" / "retrieval"
    docs_dir.mkdir(parents=True)
    (docs_dir / "queries.md").write_text(
        '1. **"test"**\n   *Expected:* `main.py`\n', encoding="utf-8"
    )

    original_build = merge_mod.build_derived_artifacts

    def build_with_current_sources(
        dump_index_path,
        chunk_path,
        base_name_func,
        run_id,
        hub_path,
        generator_info,
        repo_names,
        debug,
    ):
        dump_sha = hashlib.sha256(dump_index_path.read_bytes()).hexdigest()
        _write_current_sources(base_name_func(part_suffix=""), run_id, dump_sha)
        return original_build(
            dump_index_path,
            chunk_path,
            base_name_func,
            run_id,
            hub_path,
            generator_info,
            repo_names,
            debug,
        )

    monkeypatch.setattr(merge_mod, "build_derived_artifacts", build_with_current_sources)

    artifacts = merge_mod.write_reports_v2(
        merges_dir=merges_dir,
        hub=hub,
        repo_summaries=[merge_mod.scan_repo(repo_dir)],
        detail="full",
        mode="unified",
        max_bytes=100000,
        plan_only=False,
        code_only=False,
        split_size=0,
        debug=True,
        extras=merge_mod.ExtrasConfig.from_csv("architecture")[0],
        output_mode="dual",
        generator_info=make_generator_info(),
    )

    manifest = json.loads(artifacts.bundle_manifest.read_text(encoding="utf-8"))
    graph_entries = [
        artifact
        for artifact in manifest["artifacts"]
        if artifact.get("role") == ArtifactRole.GRAPH_INDEX_JSON.value
    ]
    assert len(graph_entries) == 1
    graph_entry = graph_entries[0]
    assert graph_entry["contract"] == {
        "id": "architecture.graph_index",
        "version": "v1",
    }
    assert graph_entry["authority"] == "retrieval_index"
    assert graph_entry["canonicality"] == "derived"
    assert graph_entry["regenerable"] is True
    assert graph_entry["staleness_sensitive"] is True

    eval_entries = [
        artifact
        for artifact in manifest["artifacts"]
        if artifact.get("role") == ArtifactRole.RETRIEVAL_EVAL_JSON.value
    ]
    assert len(eval_entries) == 1
    eval_entry = eval_entries[0]
    assert eval_entry["contract"] == {"id": "retrieval-eval", "version": "v1"}
    assert eval_entry["authority"] == "diagnostic_signal"
    assert eval_entry["canonicality"] == "diagnostic"
    assert eval_entry["regenerable"] is True
    assert eval_entry["staleness_sensitive"] is True
