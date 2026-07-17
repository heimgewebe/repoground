import json
from pathlib import Path

from merger.repoground.architecture import graph_source_validation
from merger.repoground.core.merge import build_derived_artifacts


def test_graph_side_artifacts_skip_when_schema_dependency_absent(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    source = repo / "src" / "main.py"
    source.parent.mkdir(parents=True)
    source.write_text("def main():\n    return 1\n", encoding="utf-8")

    dump = tmp_path / "bundle.dump_index.json"
    dump.write_text(json.dumps({"contract": "dump-index", "artifacts": {}}), encoding="utf-8")

    chunks = tmp_path / "bundle.chunk_index.jsonl"
    chunks.write_text(json.dumps({
        "chunk_id": "c1",
        "repo": "sample",
        "path": "src/main.py",
        "source_status": "full",
        "truncated": False,
        "source_range": {"status": "declared"},
    }) + "\n", encoding="utf-8")

    monkeypatch.setattr(graph_source_validation, "json" + "schema", None)

    def base_name(part_suffix=""):
        return tmp_path / f"bundle{part_suffix or ''}"

    paths = build_derived_artifacts(
        dump, chunks, base_name, "run", tmp_path, {"name": "test"}, ["sample"], True,
        repo_summaries=[{"name": "sample", "root": str(repo)}],
    )

    names = {Path(path).name for path in paths}
    assert "bundle.graph_index.json" not in names
    assert "bundle.architecture_graph.json" not in names
    assert "bundle.entrypoints.json" not in names
