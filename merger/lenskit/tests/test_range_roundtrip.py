import json
import hashlib
from merger.lenskit.retrieval import index_db, query_core
from merger.lenskit.core.range_resolver import resolve_range_ref

def test_range_roundtrip(tmp_path):
    # This tests the explicit stored range_ref logic (e.g. from an earlier implementation)

    # 1. Setup the workspace files
    manifest_path = tmp_path / "bundle.manifest.json"
    artifact_path = tmp_path / "code.md"
    content = b"Line 1\nHello World\nLine 3\n"
    artifact_path.write_bytes(content)

    start_byte = 7
    end_byte = 19 # "Hello World\n"
    expected_sha256 = hashlib.sha256(content[start_byte:end_byte]).hexdigest()

    manifest_data = {
        "kind": "repolens.bundle.manifest",
        "run_id": "test-run",
        "artifacts": [
            {
                "role": "canonical_md",
                "path": "code.md"
            }
        ]
    }
    manifest_path.write_text(json.dumps(manifest_data), encoding="utf-8")

    # 2. Build the Index with range_ref attached
    db_path = tmp_path / "index.sqlite"
    dump_path = tmp_path / "dump.json"
    chunk_path = tmp_path / "chunks.jsonl"

    # source_file is included explicitly for test clarity; it is optional for indexing
    # and helps keep stored-range and fallback-range scenarios easy to distinguish.

    ref_obj = {
        "artifact_role": "canonical_md",
        "repo_id": "r1",
        "file_path": "code.md",
        "start_byte": start_byte,
        "end_byte": end_byte,
        "start_line": 2,
        "end_line": 2,
        "content_sha256": expected_sha256
    }

    chunk_data = [
        {
            "chunk_id": "c1", "repo_id": "r1", "path": "code.md", "content": "Hello World\n",
            "start_line": 2, "end_line": 2, "start_byte": start_byte, "end_byte": end_byte, "layer": "core", "artifact_type": "code", "content_sha256": expected_sha256,
            "content_range_ref": ref_obj,
            "source_file": "code.md"
        }
    ]
    with chunk_path.open("w", encoding="utf-8") as f:
        for c in chunk_data:
            f.write(json.dumps(c) + "\n")

    dump_path.write_text(json.dumps({"dummy": "data"}))
    index_db.build_index(dump_path, chunk_path, db_path)

    # 3. Query the text
    res = query_core.execute_query(db_path, query_text="Hello", k=1)
    assert res["count"] == 1
    hit = res["results"][0]

    # 4. Resolve the text
    assert "range_ref" in hit
    retrieved_ref = hit["range_ref"]

    resolved = resolve_range_ref(manifest_path, retrieved_ref)

    # 5. Assert match
    assert resolved["text"] == "Hello World\n"
    assert resolved["sha256"] == expected_sha256

def test_derived_range_roundtrip_fallback(tmp_path):
    # This tests the dynamic fallback logic where query_core derives a source-backed range_ref.

    # 1. Setup the workspace files (hub/merges/run_id/bundle.manifest.json)
    hub_path = tmp_path / "hub"
    hub_path.mkdir()
    merges_dir = hub_path / "merges"
    run_dir = merges_dir / "test-run"
    run_dir.mkdir(parents=True)
    manifest_path = run_dir / "bundle.manifest.json"

    # Create the original source file in the hub
    repo_dir = hub_path / "r1"
    repo_dir.mkdir()
    artifact_path = repo_dir / "code.md"
    content = b"Line 1\nHello World\nLine 3\n"
    artifact_path.write_bytes(content)

    start_byte = 7
    end_byte = 19 # "Hello World\n"
    expected_sha256 = hashlib.sha256(content[start_byte:end_byte]).hexdigest()

    manifest_data = {
        "kind": "repolens.bundle.manifest",
        "run_id": "test-run",
        "artifacts": [] # source_file doesn't need to be in artifacts
    }
    manifest_path.write_text(json.dumps(manifest_data), encoding="utf-8")

    # 2. Build the Index (we rely on dynamic derivation by query_core now)
    db_path = run_dir / "index.sqlite"
    dump_path = run_dir / "dump.json"
    chunk_path = run_dir / "chunks.jsonl"

    chunk_data = [
        {
            "chunk_id": "c1", "repo_id": "r1", "path": "code.md", "content": "Hello World\n",
            "start_line": 2, "end_line": 2, "start_byte": start_byte, "end_byte": end_byte,
            "layer": "core", "artifact_type": "code", "content_sha256": expected_sha256,
            "source_file": "code.md"
            # NOTE: We DO NOT provide content_range_ref here. We expect the query to derive derived_range_ref!
            # `source_file` is injected here explicitly to test the DB populator and the new fallback path.
        }
    ]
    with chunk_path.open("w", encoding="utf-8") as f:
        for c in chunk_data:
            f.write(json.dumps(c) + "\n")

    dump_path.write_text(json.dumps({"dummy": "data"}))
    index_db.build_index(dump_path, chunk_path, db_path)

    # 3. Query the text
    res = query_core.execute_query(db_path, query_text="Hello", k=1)
    assert res["count"] == 1
    hit = res["results"][0]

    # 4. Resolve the text
    assert "range_ref" not in hit
    assert "derived_range_ref" in hit
    retrieved_ref = hit["derived_range_ref"]

    resolved = resolve_range_ref(manifest_path, retrieved_ref)

    # 5. Assert match
    assert resolved["text"] == "Hello World\n"
    assert resolved["sha256"] == expected_sha256
