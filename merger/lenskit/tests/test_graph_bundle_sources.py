import json

from merger.lenskit.architecture.bundle_sources import ensure_bundle_graph_sources


SHA = "a" * 64


def _repo(tmp_path, name="repo1"):
    root = tmp_path / name
    root.mkdir()
    (root / "main.py").write_text(
        "import os\n\nif __name__ == '__main__':\n    print(os.name)\n",
        encoding="utf-8",
    )
    return {"root": root, "name": name}


def test_produces_bundle_bound_sources_for_single_repo(tmp_path):
    base = tmp_path / "bundle"

    result = ensure_bundle_graph_sources(
        base_path=base,
        repo_summaries=[_repo(tmp_path)],
        run_id="run-1",
        canonical_dump_index_sha256=SHA,
        generated_at="2026-06-28T12:00:00Z",
    )

    assert result.status == "produced"
    graph = json.loads(result.graph_path.read_text(encoding="utf-8"))
    entrypoints = json.loads(result.entrypoints_path.read_text(encoding="utf-8"))
    assert graph["run_id"] == entrypoints["run_id"] == "run-1"
    assert graph["canonical_dump_index_sha256"] == SHA
    assert entrypoints["canonical_dump_index_sha256"] == SHA
    assert graph["generated_at"] == "2026-06-28T12:00:00Z"
    file_nodes = [node for node in graph["nodes"] if node["kind"] == "file"]
    assert file_nodes
    assert {node["repo"] for node in file_nodes} == {"repo1"}
    assert entrypoints["entrypoints"][0]["path"] == "main.py"


def test_skips_automatic_production_for_multi_repo(tmp_path):
    result = ensure_bundle_graph_sources(
        base_path=tmp_path / "bundle",
        repo_summaries=[_repo(tmp_path, "repo1"), _repo(tmp_path, "repo2")],
        run_id="run-1",
        canonical_dump_index_sha256=SHA,
        generated_at="2026-06-28T12:00:00Z",
    )

    assert result.status == "skipped"
    assert result.reason == "multi-repo graph identity is out of scope"
    assert not result.graph_path.exists()
    assert not result.entrypoints_path.exists()


def test_preserves_partial_pair_for_fail_closed_compiler(tmp_path):
    base = tmp_path / "bundle"
    graph_path = base.with_suffix(".architecture_graph.json")
    graph_path.write_text("{}", encoding="utf-8")

    result = ensure_bundle_graph_sources(
        base_path=base,
        repo_summaries=[_repo(tmp_path)],
        run_id="run-1",
        canonical_dump_index_sha256=SHA,
        generated_at="2026-06-28T12:00:00Z",
    )

    assert result.status == "partial"
    assert graph_path.read_text(encoding="utf-8") == "{}"
    assert not result.entrypoints_path.exists()
