import json
import pytest
from pathlib import Path
from merger.lenskit.cli.main import main as lenskit_main
from merger.lenskit.core.federation import init_federation, add_bundle

def test_federation_add_cli_dispatch(tmp_path: Path, capsys):
    out_path = tmp_path / "fed.json"
    init_federation("my-fed", out_path)

    bundle_path = tmp_path / "b1"
    bundle_path.mkdir()

    exit_code = lenskit_main(["federation", "add", "--index", str(out_path), "--repo", "r1", "--bundle", str(bundle_path)])
    assert exit_code == 0

    captured = capsys.readouterr()
    assert "Successfully added bundle 'r1'" in captured.out

def test_federation_inspect_cli_dispatch(tmp_path: Path, capsys):
    out_path = tmp_path / "fed.json"
    init_federation("my-fed", out_path)

    exit_code = lenskit_main(["federation", "inspect", "--index", str(out_path)])
    assert exit_code == 0

    captured = capsys.readouterr()
    assert "my-fed" in captured.out
    assert "bundle_count" in captured.out

def test_federation_validate_cli_dispatch(tmp_path: Path, capsys):
    out_path = tmp_path / "fed.json"
    init_federation("my-fed", out_path)

    exit_code = lenskit_main(["federation", "validate", "--index", str(out_path)])
    assert exit_code == 0

    captured = capsys.readouterr()
    assert "is valid" in captured.out

def test_rlens_federation_add_dispatch(tmp_path: Path, monkeypatch, capsys):
    out_path = tmp_path / "fed.json"
    init_federation("my-fed", out_path)

    bundle_path = tmp_path / "b1"
    bundle_path.mkdir()

    monkeypatch.setattr(
        "sys.argv",
        ["rlens", "federation", "add", "--index", str(out_path), "--repo", "r1", "--bundle", str(bundle_path)]
    )

    from merger.lenskit.cli import rlens

    with pytest.raises(SystemExit) as exc_info:
        rlens.main()

    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "Successfully added bundle 'r1'" in captured.out

def test_rlens_federation_inspect_dispatch(tmp_path: Path, monkeypatch, capsys):
    out_path = tmp_path / "fed.json"
    init_federation("my-fed", out_path)

    monkeypatch.setattr(
        "sys.argv",
        ["rlens", "federation", "inspect", "--index", str(out_path)]
    )

    from merger.lenskit.cli import rlens

    with pytest.raises(SystemExit) as exc_info:
        rlens.main()

    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "my-fed" in captured.out

def test_rlens_federation_validate_dispatch(tmp_path: Path, monkeypatch, capsys):
    out_path = tmp_path / "fed.json"
    init_federation("my-fed", out_path)

    monkeypatch.setattr(
        "sys.argv",
        ["rlens", "federation", "validate", "--index", str(out_path)]
    )

    from merger.lenskit.cli import rlens

    with pytest.raises(SystemExit) as exc_info:
        rlens.main()

    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "is valid" in captured.out

def test_rlens_federation_query_dispatch(tmp_path: Path, monkeypatch, capsys):
    out_path = tmp_path / "fed.json"
    init_federation("my-fed", out_path)

    bundle_path = tmp_path / "b1"
    bundle_path.mkdir()

    from merger.lenskit.retrieval import index_db

    b1_dump = bundle_path / "dump.json"
    b1_chunks = bundle_path / "chunks.jsonl"
    db_path = bundle_path / "chunk_index.index.sqlite"

    chunk_data = [
        {"chunk_id": "c1", "repo_id": "repo1", "path": "src/main.py", "content": "hello repo1", "start_line": 1, "end_line": 1, "layer": "core", "artifact_type": "code", "content_sha256": "h1", "source_file": "src/main.py", "start_byte": 0, "end_byte": 100}
    ]
    with b1_chunks.open("w", encoding="utf-8") as f:
        for c in chunk_data:
            f.write(json.dumps(c) + "\n")
    b1_dump.write_text(json.dumps({"dummy": "data"}), encoding="utf-8")
    index_db.build_index(b1_dump, b1_chunks, db_path)

    add_bundle(out_path, "repo1", str(bundle_path))

    monkeypatch.setattr(
        "sys.argv",
        ["rlens", "federation", "query", "--index", str(out_path), "-q", "hello"]
    )

    from merger.lenskit.cli import rlens

    with pytest.raises(SystemExit) as excinfo:
        rlens.main()

    assert excinfo.value.code == 0
    captured = capsys.readouterr()
    parsed = json.loads(captured.out)
    assert parsed["count"] == 1
    assert parsed["results"][0]["federation_bundle"] == "repo1"

def test_federation_query_cli_dispatch(tmp_path: Path, capsys):
    out_path = tmp_path / "fed.json"
    init_federation("my-fed", out_path)

    from merger.lenskit.cli import main

    # main.main returns an integer code, it doesn't sys.exit directly here.
    ret = main.main(["federation", "query", "--index", str(out_path), "-q", "hello"])
    assert ret == 0

    captured = capsys.readouterr()
    parsed = json.loads(captured.out.strip())
    # An empty federation implies a successful, empty query case returning count == 0.
    assert parsed["count"] == 0
    assert parsed["results"] == []

def test_federation_query_cli_trace_projection(tmp_path: Path, monkeypatch):
    # Isolate execution to tmp_path to verify file creation safely
    monkeypatch.chdir(tmp_path)

    out_path = tmp_path / "fed.json"
    init_federation("trace-fed", out_path)

    bundle_path = tmp_path / "b1"
    bundle_path.mkdir()

    from merger.lenskit.retrieval import index_db

    b1_dump = bundle_path / "dump.json"
    b1_chunks = bundle_path / "chunks.jsonl"
    db_path = bundle_path / "chunk_index.index.sqlite"

    chunk_data = [
        {"chunk_id": "c1", "repo_id": "repo1", "path": "src/main.py", "content": "hello repo1", "start_line": 1, "end_line": 1, "layer": "core", "artifact_type": "code", "content_sha256": "h1", "source_file": "src/main.py", "start_byte": 0, "end_byte": 100},
        {"chunk_id": "c2", "repo_id": "repo1", "path": "src/other.py", "content": "hello repo1 again", "start_line": 1, "end_line": 1, "layer": "core", "artifact_type": "code", "content_sha256": "h2", "source_file": "src/other.py", "start_byte": 0, "end_byte": 100}
    ]
    with b1_chunks.open("w", encoding="utf-8") as f:
        for c in chunk_data:
            f.write(json.dumps(c) + "\n")
    b1_dump.write_text(json.dumps({"dummy": "data"}), encoding="utf-8")
    index_db.build_index(b1_dump, b1_chunks, db_path)

    add_bundle(out_path, "repo1", str(bundle_path))

    from merger.lenskit.cli import main

    # Execute with k=1 to force slicing, so we can verify total_results semantics
    # 'hello' matches both chunks in b1_chunks, but the sqlite query_core passes `fetch_k = max(k, 50)` if semantic reranking is used.
    # Actually `execute_query` fetches up to `k` locally. If we pass `k=1`, local bundles only return 1 hit each!
    # To fix this, `execute_federated_query` must request a larger `k` locally, or we accept it's `total_candidates_found_across_returned_bundles`.
    # Wait, `execute_federated_query` calls `execute_query(k=k)`. So local slice is applied before global slice!
    # Therefore, if local bundles return 1 hit each, `all_results` has 1 hit.
    # Ah, in this test setup `b1` has 2 chunks matching 'hello'. `execute_query(k=1)` will only return 1 hit from `b1`!
    # Wait! If we pass `-k 1`, `execute_query` fetches 1 hit. `total_candidates_found` will be 1.
    # To test global slicing, we need `all_results` to be larger than global `k`.
    # But `execute_federated_query` passes the global `k` to local `execute_query`. So each bundle returns up to `k`.
    # If `k=1`, local returns 1. If we have 2 bundles, `all_results` is 2. Global slice is 1. `total_candidates_found` is 2.
    # Ah! The test setup only created `b1`! Let's add `b2` to the test!

    bundle_path2 = tmp_path / "b2"
    bundle_path2.mkdir()
    b2_dump = bundle_path2 / "dump.json"
    b2_chunks = bundle_path2 / "chunks.jsonl"
    b2_db = bundle_path2 / "chunk_index.index.sqlite"

    chunk_data2 = [
        {"chunk_id": "c3", "repo_id": "repo2", "path": "src/main.py", "content": "hello repo2", "start_line": 1, "end_line": 1, "layer": "core", "artifact_type": "code", "content_sha256": "h3", "source_file": "src/main.py", "start_byte": 0, "end_byte": 100}
    ]
    with b2_chunks.open("w", encoding="utf-8") as f:
        for c in chunk_data2:
            f.write(json.dumps(c) + "\n")
    b2_dump.write_text(json.dumps({"dummy": "data"}), encoding="utf-8")
    index_db.build_index(b2_dump, b2_chunks, b2_db)
    add_bundle(out_path, "repo2", str(bundle_path2))

    ret = main.main(["federation", "query", "--index", str(out_path), "-q", "hello", "-k", "1", "--trace"])
    assert ret == 0

    trace_file = tmp_path / "federation_trace.json"
    assert trace_file.exists(), "federation_trace.json was not created in CWD"

    with trace_file.open("r", encoding="utf-8") as f:
        trace_data = json.load(f)

    assert "query" in trace_data
    assert "timestamp" in trace_data
    assert "total_results" in trace_data
    assert "bundles" in trace_data

    # We had 2 hits, but k=1. total_results must be 2.
    assert trace_data["total_results"] == 2

    # Check bundle projection
    assert len(trace_data["bundles"]) == 2

    # Hard schema validation — skip only if jsonschema is not installed
    try:
        import jsonschema
    except ImportError:
        pytest.skip("jsonschema not installed")
    schema_path = Path(__file__).parent.parent / "contracts" / "federation-trace.v1.schema.json"
    assert schema_path.exists(), "federation-trace.v1.schema.json not found"
    with schema_path.open("r", encoding="utf-8") as sf:
        schema = json.load(sf)
    jsonschema.validate(instance=trace_data, schema=schema)

def test_federation_query_trace_writes_conflicts_json(tmp_path: Path, monkeypatch):
    # Isolate execution to tmp_path to verify file creation safely
    monkeypatch.chdir(tmp_path)

    out_path = tmp_path / "fed.json"
    init_federation("conflict-fed", out_path)

    # Bundle 1
    bundle_path1 = tmp_path / "b1"
    bundle_path1.mkdir()
    from merger.lenskit.retrieval import index_db
    b1_dump = bundle_path1 / "dump.json"
    b1_chunks = bundle_path1 / "chunks.jsonl"
    b1_db = bundle_path1 / "chunk_index.index.sqlite"

    chunk_data1 = [
        {"chunk_id": "c1", "repo_id": "repo1", "path": "src/main.py", "content": "hello repo1", "start_line": 1, "end_line": 1, "layer": "core", "artifact_type": "code", "content_sha256": "h1", "source_file": "src/main.py", "start_byte": 0, "end_byte": 100}
    ]
    with b1_chunks.open("w", encoding="utf-8") as f:
        for c in chunk_data1:
            f.write(json.dumps(c) + "\n")
    b1_dump.write_text(json.dumps({"dummy": "data"}), encoding="utf-8")
    index_db.build_index(b1_dump, b1_chunks, b1_db)
    add_bundle(out_path, "repo1", str(bundle_path1))

    # Bundle 2 (Same path/filename to trigger conflict heuristic)
    bundle_path2 = tmp_path / "b2"
    bundle_path2.mkdir()
    b2_dump = bundle_path2 / "dump.json"
    b2_chunks = bundle_path2 / "chunks.jsonl"
    b2_db = bundle_path2 / "chunk_index.index.sqlite"

    chunk_data2 = [
        {"chunk_id": "c2", "repo_id": "repo2", "path": "src/main.py", "content": "hello repo2", "start_line": 1, "end_line": 1, "layer": "core", "artifact_type": "code", "content_sha256": "h2", "source_file": "src/main.py", "start_byte": 0, "end_byte": 100}
    ]
    with b2_chunks.open("w", encoding="utf-8") as f:
        for c in chunk_data2:
            f.write(json.dumps(c) + "\n")
    b2_dump.write_text(json.dumps({"dummy": "data"}), encoding="utf-8")
    index_db.build_index(b2_dump, b2_chunks, b2_db)
    add_bundle(out_path, "repo2", str(bundle_path2))

    from merger.lenskit.cli import main

    # Execute with trace enabled to trigger conflicts artifact generation
    ret = main.main(["federation", "query", "--index", str(out_path), "-q", "hello", "--trace"])
    assert ret == 0

    conflicts_file = tmp_path / "federation_conflicts.json"
    assert conflicts_file.exists(), "federation_conflicts.json was not created in CWD"

    with conflicts_file.open("r", encoding="utf-8") as f:
        conflicts_data = json.load(f)

    assert isinstance(conflicts_data, list)
    assert len(conflicts_data) == 1

    conflict = conflicts_data[0]
    assert "conflict_id" in conflict
    assert conflict["type"] == "path"
    assert "main.py" in conflict["description"]

    # Optional schema validation
    try:
        import jsonschema
        schema_path = Path(__file__).parent.parent / "contracts" / "federation-conflicts.v1.schema.json"
        if schema_path.exists():
            with schema_path.open("r", encoding="utf-8") as sf:
                schema = json.load(sf)
            jsonschema.validate(instance=conflicts_data, schema=schema)
    except ImportError:
        pass

def test_federation_query_without_trace_skips_conflicts_json(tmp_path: Path, monkeypatch):
    # Isolate execution to tmp_path
    monkeypatch.chdir(tmp_path)

    out_path = tmp_path / "fed.json"
    init_federation("conflict-fed", out_path)

    # Bundle 1
    bundle_path1 = tmp_path / "b1"
    bundle_path1.mkdir()
    from merger.lenskit.retrieval import index_db
    b1_dump = bundle_path1 / "dump.json"
    b1_chunks = bundle_path1 / "chunks.jsonl"
    b1_db = bundle_path1 / "chunk_index.index.sqlite"

    chunk_data1 = [
        {"chunk_id": "c1", "repo_id": "repo1", "path": "src/main.py", "content": "hello repo1", "start_line": 1, "end_line": 1, "layer": "core", "artifact_type": "code", "content_sha256": "h1", "source_file": "src/main.py", "start_byte": 0, "end_byte": 100}
    ]
    with b1_chunks.open("w", encoding="utf-8") as f:
        for c in chunk_data1:
            f.write(json.dumps(c) + "\n")
    b1_dump.write_text(json.dumps({"dummy": "data"}), encoding="utf-8")
    index_db.build_index(b1_dump, b1_chunks, b1_db)
    add_bundle(out_path, "repo1", str(bundle_path1))

    # Bundle 2 (Same path/filename to trigger conflict heuristic)
    bundle_path2 = tmp_path / "b2"
    bundle_path2.mkdir()
    b2_dump = bundle_path2 / "dump.json"
    b2_chunks = bundle_path2 / "chunks.jsonl"
    b2_db = bundle_path2 / "chunk_index.index.sqlite"

    chunk_data2 = [
        {"chunk_id": "c2", "repo_id": "repo2", "path": "src/main.py", "content": "hello repo2", "start_line": 1, "end_line": 1, "layer": "core", "artifact_type": "code", "content_sha256": "h2", "source_file": "src/main.py", "start_byte": 0, "end_byte": 100}
    ]
    with b2_chunks.open("w", encoding="utf-8") as f:
        for c in chunk_data2:
            f.write(json.dumps(c) + "\n")
    b2_dump.write_text(json.dumps({"dummy": "data"}), encoding="utf-8")
    index_db.build_index(b2_dump, b2_chunks, b2_db)
    add_bundle(out_path, "repo2", str(bundle_path2))

    from merger.lenskit.cli import main

    # Execute WITHOUT --trace. Conflict generation in logic occurs, but CLI should not persist it.
    ret = main.main(["federation", "query", "--index", str(out_path), "-q", "hello"])
    assert ret == 0

    conflicts_file = tmp_path / "federation_conflicts.json"
    assert not conflicts_file.exists(), "federation_conflicts.json was incorrectly created without --trace"

def test_federation_query_trace_without_conflicts_skips_json(tmp_path: Path, monkeypatch):
    # Isolate execution to tmp_path
    monkeypatch.chdir(tmp_path)

    out_path = tmp_path / "fed.json"
    init_federation("no-conflict-fed", out_path)

    # Bundle 1
    bundle_path1 = tmp_path / "b1"
    bundle_path1.mkdir()
    from merger.lenskit.retrieval import index_db
    b1_dump = bundle_path1 / "dump.json"
    b1_chunks = bundle_path1 / "chunks.jsonl"
    b1_db = bundle_path1 / "chunk_index.index.sqlite"

    chunk_data1 = [
        {"chunk_id": "c1", "repo_id": "repo1", "path": "src/main.py", "content": "hello repo1", "start_line": 1, "end_line": 1, "layer": "core", "artifact_type": "code", "content_sha256": "h1", "source_file": "src/main.py", "start_byte": 0, "end_byte": 100}
    ]
    with b1_chunks.open("w", encoding="utf-8") as f:
        for c in chunk_data1:
            f.write(json.dumps(c) + "\n")
    b1_dump.write_text(json.dumps({"dummy": "data"}), encoding="utf-8")
    index_db.build_index(b1_dump, b1_chunks, b1_db)
    add_bundle(out_path, "repo1", str(bundle_path1))

    # Bundle 2 (Different path/filename, no conflict)
    bundle_path2 = tmp_path / "b2"
    bundle_path2.mkdir()
    b2_dump = bundle_path2 / "dump.json"
    b2_chunks = bundle_path2 / "chunks.jsonl"
    b2_db = bundle_path2 / "chunk_index.index.sqlite"

    chunk_data2 = [
        {"chunk_id": "c2", "repo_id": "repo2", "path": "src/other.py", "content": "hello repo2", "start_line": 1, "end_line": 1, "layer": "core", "artifact_type": "code", "content_sha256": "h2", "source_file": "src/other.py", "start_byte": 0, "end_byte": 100}
    ]
    with b2_chunks.open("w", encoding="utf-8") as f:
        for c in chunk_data2:
            f.write(json.dumps(c) + "\n")
    b2_dump.write_text(json.dumps({"dummy": "data"}), encoding="utf-8")
    index_db.build_index(b2_dump, b2_chunks, b2_db)
    add_bundle(out_path, "repo2", str(bundle_path2))

    from merger.lenskit.cli import main

    # Execute WITH --trace. Conflict generation in logic does NOT occur.
    ret = main.main(["federation", "query", "--index", str(out_path), "-q", "hello", "--trace"])
    assert ret == 0

    conflicts_file = tmp_path / "federation_conflicts.json"
    assert not conflicts_file.exists(), "federation_conflicts.json was incorrectly created despite no conflicts"


# ── cross_repo_links CLI persistence tests ───────────────────────────────────

def _make_two_bundle_fed(tmp_path, fed_id="crl-fed"):
    """Helper: build a federation index with two bundles sharing a query hit."""
    out_path = tmp_path / "fed.json"
    init_federation(fed_id, out_path)

    from merger.lenskit.retrieval import index_db as idb

    for repo_id, sub in (("repo1", "b1"), ("repo2", "b2")):
        bp = tmp_path / sub
        bp.mkdir()
        chunks_file = bp / "chunks.jsonl"
        dump_file = bp / "dump.json"
        db_file = bp / "chunk_index.index.sqlite"
        chunk = {
            "chunk_id": f"{repo_id}-c1",
            "repo_id": repo_id,
            "path": f"src/{sub}.py",
            "content": f"hello {repo_id}",
            "start_line": 1, "end_line": 1,
            "layer": "core", "artifact_type": "code",
            "content_sha256": f"h{sub}",
            "source_file": f"src/{sub}.py",
            "start_byte": 0, "end_byte": 100,
        }
        with chunks_file.open("w", encoding="utf-8") as f:
            f.write(json.dumps(chunk) + "\n")
        dump_file.write_text(json.dumps({"dummy": "data"}), encoding="utf-8")
        idb.build_index(dump_file, chunks_file, db_file)
        add_bundle(out_path, repo_id, str(bp))

    return out_path


def test_federation_query_trace_writes_cross_repo_links_json(tmp_path: Path, monkeypatch):
    """CLI --trace with multi-bundle results writes cross_repo_links.json."""
    monkeypatch.chdir(tmp_path)
    out_path = _make_two_bundle_fed(tmp_path)

    from merger.lenskit.cli import main

    ret = main.main(["federation", "query", "--index", str(out_path), "-q", "hello", "--trace"])
    assert ret == 0

    links_file = tmp_path / "cross_repo_links.json"
    assert links_file.exists(), "cross_repo_links.json must be created when multiple bundles contribute"

    with links_file.open("r", encoding="utf-8") as f:
        links_data = json.load(f)

    assert isinstance(links_data, list)
    assert len(links_data) >= 1

    link = links_data[0]
    assert "source_repo" in link
    assert "target_repo" in link
    assert link["confidence"] == "inferred"
    assert link["link_type"] == "co_occurrence"
    assert isinstance(link["evidence_refs"], list)

    # Schema validation — validate the whole artifact (array) against the schema
    try:
        import jsonschema
        schema_path = Path(__file__).parent.parent / "contracts" / "cross-repo-links.v1.schema.json"
        if schema_path.exists():
            with schema_path.open("r", encoding="utf-8") as sf:
                schema = json.load(sf)
            jsonschema.validate(instance=links_data, schema=schema)
    except ImportError:
        pass


def test_federation_query_without_trace_skips_cross_repo_links_json(tmp_path: Path, monkeypatch):
    """CLI without --trace must NOT write cross_repo_links.json."""
    monkeypatch.chdir(tmp_path)
    out_path = _make_two_bundle_fed(tmp_path)

    from merger.lenskit.cli import main

    ret = main.main(["federation", "query", "--index", str(out_path), "-q", "hello"])
    assert ret == 0

    links_file = tmp_path / "cross_repo_links.json"
    assert not links_file.exists(), "cross_repo_links.json must not be created without --trace"


def test_federation_query_trace_skips_cross_repo_links_json_single_bundle(tmp_path: Path, monkeypatch):
    """CLI --trace with single-bundle results must NOT write cross_repo_links.json."""
    monkeypatch.chdir(tmp_path)

    out_path = tmp_path / "fed.json"
    init_federation("single-fed", out_path)

    from merger.lenskit.retrieval import index_db as idb

    bp = tmp_path / "b1"
    bp.mkdir()
    chunks_file = bp / "chunks.jsonl"
    dump_file = bp / "dump.json"
    db_file = bp / "chunk_index.index.sqlite"
    chunk = {
        "chunk_id": "c1", "repo_id": "repo1", "path": "src/main.py",
        "content": "hello repo1", "start_line": 1, "end_line": 1,
        "layer": "core", "artifact_type": "code", "content_sha256": "h1",
        "source_file": "src/main.py", "start_byte": 0, "end_byte": 100,
    }
    with chunks_file.open("w", encoding="utf-8") as f:
        f.write(json.dumps(chunk) + "\n")
    dump_file.write_text(json.dumps({"dummy": "data"}), encoding="utf-8")
    idb.build_index(dump_file, chunks_file, db_file)
    add_bundle(out_path, "repo1", str(bp))

    from merger.lenskit.cli import main

    ret = main.main(["federation", "query", "--index", str(out_path), "-q", "hello", "--trace"])
    assert ret == 0

    links_file = tmp_path / "cross_repo_links.json"
    assert not links_file.exists(), "cross_repo_links.json must not be created for single-bundle queries"


# ── federation_trace.json negative persistence test ──────────────────────────

def test_federation_query_without_trace_skips_federation_trace_json(tmp_path: Path, monkeypatch):
    """CLI without --trace must NOT write federation_trace.json."""
    monkeypatch.chdir(tmp_path)
    out_path = _make_two_bundle_fed(tmp_path)

    from merger.lenskit.cli import main

    ret = main.main(["federation", "query", "--index", str(out_path), "-q", "hello"])
    assert ret == 0

    trace_file = tmp_path / "federation_trace.json"
    assert not trace_file.exists(), "federation_trace.json must not be created without --trace"



# ── federation-trace.v1.schema.json negative schema tests ────────────────────

def test_federation_trace_schema_rejects_root_extra_field():
    """federation-trace.v1.schema.json must reject an unexpected root-level field."""
    try:
        import jsonschema
    except ImportError:
        pytest.skip("jsonschema not installed")

    schema_path = Path(__file__).parent.parent / "contracts" / "federation-trace.v1.schema.json"
    assert schema_path.exists(), "federation-trace.v1.schema.json not found"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    invalid_trace = {
        "query": "hello",
        "timestamp": "2026-05-06T00:00:00+00:00",
        "total_results": 1,
        "bundles": [],
        "disallowed_root_field": "must_be_rejected",
    }

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=invalid_trace, schema=schema)


def test_federation_trace_schema_rejects_bundle_item_extra_field():
    """federation-trace.v1.schema.json must reject an unexpected field inside a bundle item."""
    try:
        import jsonschema
    except ImportError:
        pytest.skip("jsonschema not installed")

    schema_path = Path(__file__).parent.parent / "contracts" / "federation-trace.v1.schema.json"
    assert schema_path.exists(), "federation-trace.v1.schema.json not found"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    invalid_trace = {
        "query": "hello",
        "timestamp": "2026-05-06T00:00:00+00:00",
        "total_results": 1,
        "bundles": [
            {
                "repo_id": "repo1",
                "bundle_path": "/data/repo1",
                "status": "ok",
                "disallowed_bundle_field": "must_be_rejected",
            }
        ],
    }

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=invalid_trace, schema=schema)


# ── Shape-Dissonanz-Grenztest ─────────────────────────────────────────────────
# federation_trace existiert unter demselben Namen in zwei strukturell verschiedenen Formen:
#   (1) CLI-Dateiartefakt federation_trace.json: query, timestamp, total_results, bundles[]
#       → schema-validiert durch federation-trace.v1.schema.json
#   (2) Runtime-Inline-Form in API/Projektionspfad: queried_bundles_total, bundle_status, ...
#       → kein eigenes JSON-Schema; federation-trace.v1.schema.json gilt hier NICHT
# Dieser Test schützt die Grenze: das Schema muss die Runtime-Form ablehnen.

def test_federation_trace_schema_does_not_describe_runtime_form():
    """federation-trace.v1.schema.json must reject the runtime inline federation_trace shape.

    The runtime form (from execute_federated_query with trace=True, passed through
    output_projection.py into the API wrapper) carries different fields than the
    CLI file artifact validated by this schema. Applying the schema to the runtime
    form must fail — this test guards against accidental shape unification.
    """
    try:
        import jsonschema
    except ImportError:
        pytest.skip("jsonschema not installed")

    schema_path = Path(__file__).parent.parent / "contracts" / "federation-trace.v1.schema.json"
    assert schema_path.exists(), "federation-trace.v1.schema.json not found"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    # Canonical runtime form: produced by execute_federated_query(trace=True)
    runtime_federation_trace = {
        "queried_bundles_total": 2,
        "queried_bundles_effective": 2,
        "bundle_status": {"repo1": "ok", "repo2": "stale"},
        "bundle_errors": {},
        "bundle_traces": {},
    }

    # The runtime form must NOT validate against the CLI file artifact schema.
    # It is missing required fields (query, timestamp, total_results, bundles) and
    # carries additional fields that additionalProperties:false rejects.
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=runtime_federation_trace, schema=schema)

