import json

from merger.lenskit.architecture.bundle_sources import ensure_bundle_graph_sources
from merger.lenskit.cli.main import main


SHA = "a" * 64


def test_architecture_cli_import_graph_uses_configured_roots(tmp_path, capsys):
    src = tmp_path / "src"
    src.mkdir()
    (src / "app.py").write_text("import lib\n", encoding="utf-8")
    (src / "lib.py").write_text("VALUE = 1\n", encoding="utf-8")

    rc = main(["architecture", "--repo", str(tmp_path), "--import-graph", "--" + "source-roots", "src"])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    edges = {(edge["src"], edge["dst"]) for edge in payload["edges"]}
    assert ("file:src/app.py", "file:src/lib.py") in edges
    assert ("file:src/app.py", "module:lib") not in edges


def test_architecture_cli_roots_file_shape_is_fail_closed(tmp_path, capsys):
    roots_file = tmp_path / "roots.json"
    roots_file.write_text(json.dumps({"kind": "wrong", "version": "1.0", "roots": ["src"]}), encoding="utf-8")

    rc = main(["architecture", "--repo", str(tmp_path), "--import-graph", "--" + "source-roots-file", str(roots_file)])

    assert rc == 2
    assert "invalid kind" in capsys.readouterr().err


def test_bundle_graph_sources_use_summary_roots(tmp_path):
    repo_root = tmp_path / "repo1"
    src = repo_root / "src"
    src.mkdir(parents=True)
    (src / "app.py").write_text("import lib\n", encoding="utf-8")
    (src / "lib.py").write_text("VALUE = 1\n", encoding="utf-8")

    chunk_index = tmp_path / "repo1.chunk_index.jsonl"
    records = [
        {"repo": "repo1", "path": "src/app.py", "source_status": "full", "truncated": False, "source_range": {"status": "declared"}},
        {"repo": "repo1", "path": "src/lib.py", "source_status": "full", "truncated": False, "source_range": {"status": "declared"}},
    ]
    chunk_index.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")

    result = ensure_bundle_graph_sources(
        base_path=tmp_path / "bundle",
        chunk_index_path=chunk_index,
        repo_summaries=[{"root": repo_root, "name": "repo1", "source_roots": ["src"]}],
        run_id="run-1",
        canonical_dump_index_sha256=SHA,
        generated_at="2026-07-01T00:00:00Z",
    )

    assert result.status == "produced"
    graph = json.loads(result.graph_path.read_text(encoding="utf-8"))
    edges = {(edge["src"], edge["dst"]) for edge in graph["edges"]}
    assert ("file:src/app.py", "file:src/lib.py") in edges
    assert ("file:src/app.py", "module:lib") not in edges
