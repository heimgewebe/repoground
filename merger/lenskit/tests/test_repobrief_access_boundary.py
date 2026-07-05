import hashlib
import json

from merger.lenskit.core import repobrief_access


def _write_manifest(path, artifacts):
    path.write_text(
        json.dumps({
            "kind": "repolens.bundle.manifest",
            "version": "1.0",
            "run_id": "run-1",
            "artifacts": artifacts,
            "links": {},
            "capabilities": {},
        }),
        encoding="utf-8",
    )


def test_range_get_reads_existing_artifact_without_mutation(tmp_path):
    artifact = tmp_path / "brief.md"
    artifact.write_text("alpha\nbeta\n", encoding="utf-8")
    content = artifact.read_bytes()
    start = content.index(b"beta")
    end = len(content)
    manifest = tmp_path / "demo.bundle.manifest.json"
    _write_manifest(manifest, [{
        "role": "canonical_md",
        "path": artifact.name,
        "content_type": "text/markdown",
        "bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }])
    ref = {
        "artifact_role": "canonical_md",
        "repo_id": "demo",
        "file_path": artifact.name,
        "start_byte": start,
        "end_byte": end,
        "start_line": 2,
        "end_line": 2,
        "content_sha256": hashlib.sha256(content[start:end]).hexdigest(),
    }

    result = repobrief_access.range_get(manifest, ref)

    assert result["status"] == "available"
    assert result["range"]["text"] == "beta\n"
    assert result["mutation_boundary"]["writes"] == []
    assert result["mutation_boundary"]["read_paths_do_not_refresh"] is True


def test_range_get_rejects_source_file_ranges_without_reading_workspace(tmp_path):
    hub = tmp_path / "hub"
    run_dir = hub / "merges" / "run-1"
    source_dir = hub / "demo" / "src"
    run_dir.mkdir(parents=True)
    source_dir.mkdir(parents=True)

    source_file = source_dir / "secret.py"
    source_file.write_text("secret = True\n", encoding="utf-8")
    content = source_file.read_bytes()
    manifest = run_dir / "demo.bundle.manifest.json"
    _write_manifest(manifest, [])
    ref = {
        "artifact_role": "source_file",
        "repo_id": "demo",
        "file_path": "src/secret.py",
        "start_byte": 0,
        "end_byte": len(content),
        "start_line": 1,
        "end_line": 1,
        "content_sha256": hashlib.sha256(content).hexdigest(),
    }

    result = repobrief_access.range_get(manifest, ref)

    assert result["status"] == "invalid"
    assert result["range"] is None
    assert "source_file range_refs" in result["error"]
    assert result["mutation_boundary"]["writes"] == []


def test_query_existing_index_reports_missing_without_creating(tmp_path):
    manifest = tmp_path / "demo.bundle.manifest.json"
    missing_index = tmp_path / "missing.sqlite"
    _write_manifest(manifest, [{"role": "sqlite_index", "path": missing_index.name}])

    result = repobrief_access.query_existing_index(manifest, "hello", k=1)

    assert result["status"] == "missing"
    assert result["query_result"] is None
    assert not missing_index.exists()
    assert result["mutation_boundary"]["writes"] == []


def test_query_existing_index_reads_prebuilt_sqlite_index(tmp_path):
    from merger.lenskit.retrieval import index_db

    dump_path = tmp_path / "dump.json"
    chunk_path = tmp_path / "chunks.jsonl"
    index_path = tmp_path / "index.sqlite"
    manifest = tmp_path / "demo.bundle.manifest.json"

    chunk = {
        "chunk_id": "c1",
        "repo_id": "demo",
        "path": "src/main.py",
        "content": "def main(): print('hello world')",
        "start_line": 1,
        "end_line": 1,
        "layer": "core",
        "artifact_type": "code",
        "content_sha256": "h1",
    }
    chunk_path.write_text(json.dumps(chunk) + "\n", encoding="utf-8")
    dump_path.write_text(json.dumps({"version": "1.0", "repos": {"demo": {}}}), encoding="utf-8")
    index_db.build_index(dump_path, chunk_path, index_path)
    _write_manifest(manifest, [{"role": "sqlite_index", "path": index_path.name}])

    before_files = {path.name for path in tmp_path.iterdir()}
    result = repobrief_access.query_existing_index(manifest, "hello", k=1)
    after_files = {path.name for path in tmp_path.iterdir()}

    assert result["status"] == "available"
    assert result["query_result"]["count"] == 1
    assert result["query_result"]["results"][0]["path"] == "src/main.py"
    assert result["mutation_boundary"]["writes"] == []
    assert before_files == after_files
