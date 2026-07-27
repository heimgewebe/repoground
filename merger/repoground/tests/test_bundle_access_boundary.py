import hashlib
import json
import os
import stat
from pathlib import Path

from merger.repoground.core import bundle_access


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


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sealed_artifact(path, role="sqlite_index"):
    return {
        "role": role,
        "path": path.name,
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _sqlite_sidecars(index_path):
    return {
        index_path.with_name(index_path.name + suffix)
        for suffix in ("-wal", "-shm", "-journal")
    }


def _queryable_sqlite_bundle(tmp_path):
    from merger.repoground.retrieval import index_db

    dump_path = tmp_path / "dump.json"
    chunk_path = tmp_path / "chunks.jsonl"
    manifest = tmp_path / "demo.bundle.manifest.json"
    index_path = tmp_path / "index.index.sqlite"
    chunk_path.write_text(
        json.dumps(
            {
                "chunk_id": "c1",
                "repo_id": "demo",
                "path": "src/main.py",
                "content": "def main(): print('portable hello')",
                "start_line": 1,
                "end_line": 1,
                "layer": "core",
                "artifact_type": "code",
                "content_sha256": "h1",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    dump_path.write_text(
        json.dumps({"version": "1.0", "repos": {"demo": {}}}),
        encoding="utf-8",
    )
    index_db.build_index(dump_path, chunk_path, index_path)
    _write_manifest(manifest, [_sealed_artifact(index_path)])
    return manifest, index_path


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

    result = bundle_access.range_get(manifest, ref)

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

    result = bundle_access.range_get(manifest, ref)

    assert result["status"] == "invalid"
    assert result["error_code"] == "source_file_outside_bundle_boundary"
    assert result["range"] is None
    assert "source_file range_refs" in result["error"]
    assert result["mutation_boundary"]["writes"] == []


def test_range_get_reports_hash_mismatch_structurally(tmp_path):
    artifact = tmp_path / "brief.md"
    artifact.write_text("alpha\nbeta\n", encoding="utf-8")
    content = artifact.read_bytes()
    manifest = tmp_path / "demo.bundle.manifest.json"
    _write_manifest(manifest, [{"role": "canonical_md", "path": artifact.name}])
    ref = {
        "artifact_role": "canonical_md",
        "repo_id": "demo",
        "file_path": artifact.name,
        "start_byte": 0,
        "end_byte": len(content),
        "start_line": 1,
        "end_line": 2,
        "content_sha256": "0" * 64,
    }

    result = bundle_access.range_get(manifest, ref)

    assert result["status"] == "invalid"
    assert result["error_code"] == "content_hash_mismatch"
    assert result["range"] is None


def test_query_existing_index_reports_missing_without_creating(tmp_path):
    manifest = tmp_path / "demo.bundle.manifest.json"
    missing_index = tmp_path / "missing.index.sqlite"
    _write_manifest(manifest, [{"role": "sqlite_index", "path": missing_index.name}])

    result = bundle_access.query_existing_index(manifest, "hello", k=1)

    assert result["status"] == "missing"
    assert result["error_code"] == "sqlite_index_file_missing"
    assert result["query_result"] is None
    assert not missing_index.exists()
    assert result["mutation_boundary"]["writes"] == []


def test_query_existing_index_rejects_unbounded_k(tmp_path):
    manifest = tmp_path / "demo.bundle.manifest.json"
    _write_manifest(manifest, [])

    result = bundle_access.query_existing_index(manifest, "hello", k=101)

    assert result["status"] == "invalid"
    assert result["error_code"] == "k_out_of_bounds"
    assert result["query_result"] is None


def test_query_existing_index_rejects_non_integer_k(tmp_path):
    manifest = tmp_path / "demo.bundle.manifest.json"
    _write_manifest(manifest, [])

    for bad_k in ("5", 2.0, True, None):
        result = bundle_access.query_existing_index(manifest, "hello", k=bad_k)

        assert result["status"] == "invalid"
        assert result["error_code"] == "k_out_of_bounds"
        assert result["query_result"] is None


def test_query_existing_index_rejects_non_sqlite_artifact_path(tmp_path):
    bad_index = tmp_path / "index.txt"
    bad_index.write_text("not sqlite", encoding="utf-8")
    manifest = tmp_path / "demo.bundle.manifest.json"
    _write_manifest(manifest, [_sealed_artifact(bad_index)])

    result = bundle_access.query_existing_index(manifest, "hello", k=1)

    assert result["status"] == "invalid"
    assert result["error_code"] == "sqlite_index_path_invalid"
    assert "expected canonical read-only index file" in result["error"]
    assert bad_index.exists()


def test_noncanonical_sqlite_role_is_rejected_before_open_or_hash(
    monkeypatch,
    tmp_path,
):
    bad_index = tmp_path / "large-payload.bin"
    bad_index.write_bytes(b"x" * (2 * bundle_access._SQLITE_HASH_CHUNK_BYTES))
    manifest = tmp_path / "demo.bundle.manifest.json"
    _write_manifest(
        manifest,
        [
            {
                "role": "sqlite_index",
                "path": bad_index.name,
                "bytes": bad_index.stat().st_size,
                "sha256": "0" * 64,
            }
        ],
    )

    def forbidden_open(*_args, **_kwargs):
        raise AssertionError("noncanonical sqlite_index must not be opened")

    def forbidden_hash(*_args, **_kwargs):
        raise AssertionError("noncanonical sqlite_index must not be hashed")

    monkeypatch.setattr(bundle_access, "_open_sqlite_artifact", forbidden_open)
    monkeypatch.setattr(bundle_access, "_verify_sqlite_handle", forbidden_hash)

    result = bundle_access.query_existing_index(manifest, "hello", k=1)

    assert result["status"] == "invalid"
    assert result["error_code"] == "sqlite_index_path_invalid"
    assert "expected canonical read-only index file" in result["error"]


def test_query_existing_index_forces_read_only_query_mode(monkeypatch, tmp_path):
    from merger.repoground.retrieval import query_core

    index_path = tmp_path / "index.index.sqlite"
    index_path.write_bytes(b"not a real sqlite database; execute_query is mocked")
    manifest = tmp_path / "demo.bundle.manifest.json"
    _write_manifest(manifest, [_sealed_artifact(index_path)])
    observed = {}

    def fake_execute_query(index_path_arg, query, **kwargs):
        observed["index_path"] = index_path_arg
        observed["query"] = query
        observed["kwargs"] = kwargs
        return {"count": 0, "results": []}

    monkeypatch.setattr(query_core, "execute_query", fake_execute_query)

    result = bundle_access.query_existing_index(manifest, "hello", k=3)

    assert result["status"] == "available"
    assert observed["index_path"].parent in {
        Path("/proc/self/fd"),
        Path("/dev/fd"),
    }
    assert observed["index_path"].name.isdecimal()
    assert observed["query"] == "hello"
    assert observed["kwargs"]["read_only"] is True
    assert observed["kwargs"]["_validated_read_only_source_path"] == index_path
    assert observed["kwargs"]["build_context"] is False
    assert observed["kwargs"]["trace"] is False


def test_query_existing_index_uses_and_cleans_portable_verified_copy(
    monkeypatch,
    tmp_path,
):
    from merger.repoground.retrieval import query_core

    manifest, index_path = _queryable_sqlite_bundle(tmp_path)
    original_index_sha256 = _sha256(index_path)
    original_execute_query = query_core.execute_query
    observed = {}
    monkeypatch.setattr(
        bundle_access,
        "_FILE_DESCRIPTOR_ROOTS",
        (tmp_path / "missing-proc-fd", tmp_path / "missing-dev-fd"),
    )

    def observing_execute_query(index_path_arg, query, **kwargs):
        portable_path = Path(index_path_arg)
        observed["path"] = portable_path
        observed["parent"] = portable_path.parent
        assert portable_path != index_path
        assert portable_path.name == "verified.index.sqlite"
        assert stat.S_IMODE(portable_path.stat().st_mode) & 0o222 == 0
        assert kwargs["_validated_read_only_source_path"] is None
        return original_execute_query(index_path_arg, query, **kwargs)

    monkeypatch.setattr(query_core, "execute_query", observing_execute_query)

    result = bundle_access.query_existing_index(manifest, "portable", k=1)

    assert result["status"] == "available"
    assert result["query_result"]["count"] == 1
    assert result["query_result"]["results"][0]["path"] == "src/main.py"
    assert not observed["path"].exists()
    assert not observed["parent"].exists()
    assert _sha256(index_path) == original_index_sha256
    assert not any(path.exists() for path in _sqlite_sidecars(index_path))


def test_portable_sqlite_copy_integrity_failure_blocks_query_and_cleans_up(
    monkeypatch,
    tmp_path,
):
    from merger.repoground.retrieval import query_core

    manifest, _ = _queryable_sqlite_bundle(tmp_path)
    original_write_copy = bundle_access._write_portable_sqlite_copy
    observed = {}
    monkeypatch.setattr(
        bundle_access,
        "_FILE_DESCRIPTOR_ROOTS",
        (tmp_path / "missing-proc-fd", tmp_path / "missing-dev-fd"),
    )

    def corrupt_copy(handle, destination, **kwargs):
        original_write_copy(handle, destination, **kwargs)
        observed["path"] = destination
        observed["parent"] = destination.parent
        os.chmod(destination, stat.S_IRUSR | stat.S_IWUSR)
        with destination.open("ab") as copy:
            copy.write(b"corrupt")
        os.chmod(destination, stat.S_IRUSR)

    def forbidden_query(*_args, **_kwargs):
        raise AssertionError("SQLite must not open an invalid portable copy")

    monkeypatch.setattr(
        bundle_access,
        "_write_portable_sqlite_copy",
        corrupt_copy,
    )
    monkeypatch.setattr(query_core, "execute_query", forbidden_query)

    result = bundle_access.query_existing_index(manifest, "portable", k=1)

    assert result["status"] == "invalid"
    assert result["error_code"] == "sqlite_index_integrity_mismatch"
    assert result["query_result"] is None
    assert not observed["path"].exists()
    assert not observed["parent"].exists()


def test_portable_sqlite_copy_post_query_tampering_discards_result_and_cleans_up(
    monkeypatch,
    tmp_path,
):
    from merger.repoground.retrieval import query_core

    manifest, _ = _queryable_sqlite_bundle(tmp_path)
    original_execute_query = query_core.execute_query
    observed = {}
    monkeypatch.setattr(
        bundle_access,
        "_FILE_DESCRIPTOR_ROOTS",
        (tmp_path / "missing-proc-fd", tmp_path / "missing-dev-fd"),
    )

    def execute_then_tamper(index_path_arg, query, **kwargs):
        result = original_execute_query(index_path_arg, query, **kwargs)
        portable_path = Path(index_path_arg)
        observed["path"] = portable_path
        observed["parent"] = portable_path.parent
        os.chmod(portable_path, stat.S_IRUSR | stat.S_IWUSR)
        with portable_path.open("ab") as copy:
            copy.write(b"tampered")
        os.chmod(portable_path, stat.S_IRUSR)
        return result

    monkeypatch.setattr(query_core, "execute_query", execute_then_tamper)

    result = bundle_access.query_existing_index(manifest, "portable", k=1)

    assert result["status"] == "invalid"
    assert result["error_code"] == "sqlite_index_integrity_mismatch"
    assert result["query_result"] is None
    assert not observed["path"].exists()
    assert not observed["parent"].exists()


def test_query_existing_index_rejects_manifest_integrity_drift_before_sqlite_open(
    monkeypatch,
    tmp_path,
):
    from merger.repoground.retrieval import query_core

    index_path = tmp_path / "index.index.sqlite"
    index_path.write_bytes(b"generation-a")
    manifest = tmp_path / "demo.bundle.manifest.json"
    _write_manifest(manifest, [_sealed_artifact(index_path)])
    index_path.write_bytes(b"generation-b")

    def forbidden_query(*_args, **_kwargs):
        raise AssertionError("SQLite must not open after integrity drift")

    monkeypatch.setattr(query_core, "execute_query", forbidden_query)

    result = bundle_access.query_existing_index(manifest, "hello", k=1)

    assert result["status"] == "invalid"
    assert result["error_code"] == "sqlite_index_integrity_mismatch"
    assert result["query_result"] is None


def test_query_existing_index_reads_prebuilt_sqlite_index_without_mutation(tmp_path):
    from merger.repoground.retrieval import index_db

    dump_path = tmp_path / "dump.json"
    chunk_path = tmp_path / "chunks.jsonl"
    manifest = tmp_path / "demo.bundle.manifest.json"
    index_path = tmp_path / "index.index.sqlite"
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
    _write_manifest(manifest, [_sealed_artifact(index_path)])

    before_files = {path.name for path in tmp_path.iterdir()}
    before_hash = _sha256(index_path)
    result = bundle_access.query_existing_index(manifest, "hello", k=1)
    after_hash = _sha256(index_path)
    after_files = {path.name for path in tmp_path.iterdir()}

    assert result["status"] == "available"
    assert result["query_result"]["count"] == 1
    assert result["query_result"]["results"][0]["path"] == "src/main.py"
    assert result["mutation_boundary"]["writes"] == []
    assert before_files == after_files
    assert before_hash == after_hash
    assert not any(path.exists() for path in _sqlite_sidecars(index_path))
