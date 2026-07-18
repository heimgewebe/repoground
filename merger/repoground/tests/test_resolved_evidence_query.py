import hashlib
import json

from merger.repoground.core import bundle_access
from merger.repoground.core.citation_id import make_citation_id


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sqlite_sidecars(index_path):
    return {
        index_path.with_name(index_path.name + suffix)
        for suffix in ("-wal", "-shm", "-journal")
    }


def _build_resolved_bundle(tmp_path, with_citation_map=True):
    from merger.repoground.retrieval import index_db

    canonical = tmp_path / "brief.md"
    canonical.write_text("# Brief\n\nhello resolved world\n", encoding="utf-8")
    content = canonical.read_bytes()
    start = content.index(b"hello")
    end = len(content)
    chunk_bytes = content[start:end]
    chunk_sha = _sha256_bytes(chunk_bytes)
    canonical_sha = _sha256_bytes(content)

    range_ref = {
        "artifact_role": "canonical_md",
        "repo_id": "demo",
        "file_path": canonical.name,
        "start_byte": start,
        "end_byte": end,
        "start_line": 3,
        "end_line": 3,
        "content_sha256": chunk_sha,
    }
    chunk = {
        "chunk_id": "c1",
        "repo_id": "demo",
        "path": canonical.name,
        "content": chunk_bytes.decode("utf-8"),
        "start_byte": start,
        "end_byte": end,
        "start_line": 3,
        "end_line": 3,
        "layer": "core",
        "artifact_type": "doc",
        "content_sha256": chunk_sha,
        "content_range_ref": range_ref,
    }
    chunk_path = tmp_path / "chunks.jsonl"
    chunk_path.write_text(json.dumps(chunk) + "\n", encoding="utf-8")
    dump_path = tmp_path / "dump.json"
    dump_path.write_text(json.dumps({"version": "1.0", "repos": {"demo": {}}}), encoding="utf-8")
    index_path = tmp_path / "demo.index.sqlite"
    index_db.build_index(dump_path, chunk_path, index_path)

    citation_id = make_citation_id(canonical_sha, start, end, chunk_sha)
    artifacts = [
        {
            "role": "canonical_md",
            "path": canonical.name,
            "content_type": "text/markdown",
            "bytes": len(content),
            "sha256": canonical_sha,
        },
        {"role": "sqlite_index", "path": index_path.name},
    ]
    if with_citation_map:
        citation_map_path = tmp_path / "demo.citation_map.jsonl"
        row = {
            "citation_id": citation_id,
            "repo_id": "demo",
            "chunk_id": "c1",
            "snapshot": {
                "run_id": "run-1",
                "canonical_md_path": canonical.name,
                "canonical_md_sha256": canonical_sha,
            },
            "canonical_range": {
                "file_path": canonical.name,
                "start_byte": start,
                "end_byte": end,
                "start_line": 3,
                "end_line": 3,
                "content_sha256": chunk_sha,
            },
            "produced_by": "citation_map_producer/v1",
        }
        citation_map_path.write_text(json.dumps(row) + "\n", encoding="utf-8")
        artifacts.append({"role": "citation_map_jsonl", "path": citation_map_path.name})

    manifest = tmp_path / "demo.bundle.manifest.json"
    manifest.write_text(
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
    return {
        "manifest": manifest,
        "index_path": index_path,
        "canonical": canonical,
        "chunk_text": chunk_bytes.decode("utf-8"),
        "citation_id": citation_id,
    }


def test_query_existing_index_resolves_hit_evidence_and_citation(tmp_path):
    bundle = _build_resolved_bundle(tmp_path)

    result = bundle_access.query_existing_index(
        bundle["manifest"], "hello", k=5, resolve_evidence=True
    )

    assert result["status"] == "available"
    assert result["resolve_evidence"] is True
    resolved = result["resolved_evidence"]
    assert resolved["kind"] == "repobrief.resolved_evidence"
    assert resolved["version"] == "v1"
    assert resolved["citation_map"]["status"] == "available"
    assert resolved["citation_map"]["row_count"] == 1
    assert resolved["hit_count"] == 1
    hit = resolved["hits"][0]
    assert hit["chunk_id"] == "c1"
    assert hit["range_ref_source"] == "range_ref"
    assert hit["range_status"] == "resolved"
    assert hit["range"]["text"] == bundle["chunk_text"]
    assert hit["range_error_code"] is None
    citation_range_ref = hit["citation"]["range_ref"]
    assert citation_range_ref["artifact_role"] == "canonical_md"
    assert citation_range_ref["repo_id"] == "demo"
    assert citation_range_ref["file_path"] == bundle["canonical"].name
    assert citation_range_ref["chunk_id"] == "c1"
    resolved_range = bundle_access.range_get(bundle["manifest"], citation_range_ref)
    assert resolved_range["status"] == "available"
    assert resolved_range["range"]["text"] == bundle["chunk_text"]
    assert resolved["does_not_establish"] == result["does_not_establish"]
    assert result["mutation_boundary"]["writes"] == []


def test_query_existing_index_synthesizes_legacy_citation_range_ref(tmp_path):
    bundle = _build_resolved_bundle(tmp_path)
    citation_map_path = tmp_path / "demo.citation_map.jsonl"
    row = json.loads(citation_map_path.read_text(encoding="utf-8"))
    row.pop("range_ref", None)
    citation_map_path.write_text(json.dumps(row) + "\n", encoding="utf-8")

    result = bundle_access.query_existing_index(
        bundle["manifest"], "hello", k=5, resolve_evidence=True
    )

    hit = result["resolved_evidence"]["hits"][0]
    citation_range_ref = hit["citation"]["range_ref"]
    assert citation_range_ref["artifact_role"] == "canonical_md"
    assert citation_range_ref["repo_id"] == "demo"
    assert citation_range_ref["file_path"] == bundle["canonical"].name
    assert citation_range_ref["chunk_id"] == "c1"
    assert bundle_access.range_get(bundle["manifest"], citation_range_ref)["status"] == "available"


def test_query_existing_index_degrades_when_citation_map_missing(tmp_path):
    bundle = _build_resolved_bundle(tmp_path, with_citation_map=False)

    result = bundle_access.query_existing_index(
        bundle["manifest"], "hello", k=5, resolve_evidence=True
    )

    assert result["status"] == "available"
    resolved = result["resolved_evidence"]
    assert resolved["citation_map"]["status"] == "missing"
    assert resolved["citation_map"]["error_code"] == "citation_map_jsonl_missing"
    hit = resolved["hits"][0]
    assert hit["range_status"] == "resolved"
    assert hit["range"]["text"] == bundle["chunk_text"]
    assert hit["citation_status"] == "unavailable"
    assert hit["citation_id"] is None
    assert hit["citation"] is None


def test_query_existing_index_resolution_is_read_only(tmp_path):
    bundle = _build_resolved_bundle(tmp_path)
    index_path = bundle["index_path"]

    before_files = {path.name for path in tmp_path.iterdir()}
    before_hashes = {path.name: _sha256(path) for path in tmp_path.iterdir() if path.is_file()}

    result = bundle_access.query_existing_index(
        bundle["manifest"], "hello", k=5, resolve_evidence=True
    )

    after_files = {path.name for path in tmp_path.iterdir()}
    after_hashes = {path.name: _sha256(path) for path in tmp_path.iterdir() if path.is_file()}

    assert result["status"] == "available"
    assert result["resolved_evidence"]["hits"][0]["range_status"] == "resolved"
    assert before_files == after_files
    assert before_hashes == after_hashes
    assert not any(path.exists() for path in _sqlite_sidecars(index_path))
    assert result["mutation_boundary"]["writes"] == []
    assert result["mutation_boundary"]["read_paths_do_not_refresh"] is True


def test_query_existing_index_resolution_defaults_off(tmp_path):
    bundle = _build_resolved_bundle(tmp_path)

    result = bundle_access.query_existing_index(bundle["manifest"], "hello", k=5)

    assert result["status"] == "available"
    assert result["resolve_evidence"] is False
    assert result["resolved_evidence"] is None


def test_query_existing_index_rejects_non_boolean_resolve_evidence(tmp_path):
    manifest = tmp_path / "demo.bundle.manifest.json"
    manifest.write_text(
        json.dumps({
            "kind": "repolens.bundle.manifest",
            "version": "1.0",
            "run_id": "run-1",
            "artifacts": [],
            "links": {},
            "capabilities": {},
        }),
        encoding="utf-8",
    )

    for bad_value in ("yes", 1, None):
        result = bundle_access.query_existing_index(
            manifest, "hello", k=1, resolve_evidence=bad_value
        )

        assert result["status"] == "invalid"
        assert result["error_code"] == "resolve_evidence_invalid"
        assert result["query_result"] is None


def test_query_existing_index_reports_invalid_citation_map_rows(tmp_path):
    bundle = _build_resolved_bundle(tmp_path)
    citation_map_path = tmp_path / "demo.citation_map.jsonl"
    with citation_map_path.open("a", encoding="utf-8") as handle:
        handle.write("not json\n")
        handle.write(json.dumps({"chunk_id": "missing-citation-id"}) + "\n")

    result = bundle_access.query_existing_index(
        bundle["manifest"], "hello", k=5, resolve_evidence=True
    )

    assert result["status"] == "available"
    citation_map = result["resolved_evidence"]["citation_map"]
    assert citation_map["status"] == "available"
    assert citation_map["row_count"] == 1
    assert citation_map["invalid_row_count"] == 2
    hit = result["resolved_evidence"]["hits"][0]
    assert hit["citation_status"] == "resolved"
    assert hit["citation_id"] == bundle["citation_id"]


def test_resolved_evidence_uses_derived_range_ref_when_range_ref_missing(tmp_path):
    bundle = _build_resolved_bundle(tmp_path)
    base = bundle_access.query_existing_index(bundle["manifest"], "hello", k=1)
    hit = dict(base["query_result"]["results"][0])
    range_ref = hit.pop("range_ref")
    hit.pop("chunk_id", None)
    hit["derived_range_ref"] = range_ref

    resolved = bundle_access._resolve_query_evidence(bundle["manifest"], {"results": [hit]})

    assert resolved["hit_count"] == 1
    resolved_hit = resolved["hits"][0]
    assert resolved_hit["range_ref_source"] == "derived_range_ref"
    assert resolved_hit["range_status"] == "resolved"
    assert resolved_hit["range"]["text"] == bundle["chunk_text"]
    assert resolved_hit["citation_status"] == "resolved"
    assert resolved_hit["citation_id"] == bundle["citation_id"]


def test_resolved_evidence_skips_citation_map_for_empty_hits(tmp_path):
    bundle = _build_resolved_bundle(tmp_path)
    citation_map_path = tmp_path / "demo.citation_map.jsonl"
    citation_map_path.write_text("not json\n", encoding="utf-8")

    result = bundle_access.query_existing_index(
        bundle["manifest"], "no-such-token", k=5, resolve_evidence=True
    )

    assert result["status"] == "available"
    resolved = result["resolved_evidence"]
    assert resolved["hit_count"] == 0
    assert resolved["hits"] == []
    assert resolved["citation_map"]["status"] == "skipped"
    assert resolved["citation_map"]["reason"] == "no_hits"
    assert resolved["citation_map"]["invalid_row_count"] == 0


def test_resolved_evidence_falls_back_to_derived_range_ref_when_range_ref_invalid(tmp_path):
    bundle = _build_resolved_bundle(tmp_path)
    base = bundle_access.query_existing_index(bundle["manifest"], "hello", k=1)
    hit = dict(base["query_result"]["results"][0])
    valid_range_ref = hit.pop("range_ref")
    hit.pop("chunk_id", None)
    hit["range_ref"] = {"artifact_role": "source_file", "path": "outside.py"}
    hit["derived_range_ref"] = valid_range_ref

    resolved = bundle_access._resolve_query_evidence(bundle["manifest"], {"results": [hit]})

    assert resolved["hit_count"] == 1
    resolved_hit = resolved["hits"][0]
    assert resolved_hit["range_ref_source"] == "derived_range_ref"
    assert resolved_hit["range_status"] == "resolved"
    assert resolved_hit["range_ref"] == valid_range_ref
    assert resolved_hit["range_error_code"] is None
    assert resolved_hit["range"]["text"] == bundle["chunk_text"]
    assert resolved_hit["citation_status"] == "resolved"
    assert resolved_hit["citation_id"] == bundle["citation_id"]


def test_query_existing_index_rejects_structurally_malformed_citation_row(tmp_path):
    bundle = _build_resolved_bundle(tmp_path)
    citation_map_path = tmp_path / "demo.citation_map.jsonl"
    citation_map_path.write_text(
        json.dumps({
            "citation_id": "cit_0000000000000001",
            "repo_id": "demo",
            "chunk_id": "c1",
        })
        + "\n",
        encoding="utf-8",
    )

    result = bundle_access.query_existing_index(
        bundle["manifest"], "hello", k=5, resolve_evidence=True
    )

    assert result["status"] == "available"
    citation_map = result["resolved_evidence"]["citation_map"]
    assert citation_map["status"] == "available"
    assert citation_map["row_count"] == 0
    assert citation_map["invalid_row_count"] == 1
    hit = result["resolved_evidence"]["hits"][0]
    assert hit["citation_status"] == "unmatched"
    assert hit["citation_id"] is None
    assert hit["citation"] is None


def test_resolved_evidence_matches_v2_range_ref_without_chunk_id(tmp_path):
    from merger.repoground.core.range_resolver import build_explicit_range_ref_v2

    bundle = _build_resolved_bundle(tmp_path)
    citation_map_path = tmp_path / "demo.citation_map.jsonl"
    row = json.loads(citation_map_path.read_text(encoding="utf-8"))
    row.pop("chunk_id")
    citation_map_path.write_text(json.dumps(row) + "\n", encoding="utf-8")

    base = bundle_access.query_existing_index(bundle["manifest"], "hello", k=1)
    hit = dict(base["query_result"]["results"][0])
    v1_ref = hit.pop("range_ref")
    hit.pop("chunk_id", None)

    canonical_bytes = bundle["canonical"].read_bytes()
    v2_ref = build_explicit_range_ref_v2(
        artifact_role="canonical_md",
        artifact_path=bundle["canonical"].name,
        artifact_byte_start=v1_ref["start_byte"],
        artifact_byte_end=v1_ref["end_byte"],
        artifact_line_start=v1_ref["start_line"],
        artifact_line_end=v1_ref["end_line"],
        source_file_path=bundle["canonical"].name,
        source_line_start=v1_ref["start_line"],
        source_line_end=v1_ref["end_line"],
        content_sha256=_sha256_bytes(canonical_bytes),
        range_content_sha256=v1_ref["content_sha256"],
        repo_id="demo",
    )
    hit["range_ref"] = v2_ref

    resolved = bundle_access._resolve_query_evidence(bundle["manifest"], {"results": [hit]})

    assert resolved["hit_count"] == 1
    resolved_hit = resolved["hits"][0]
    assert resolved_hit["range_status"] == "resolved"
    assert resolved_hit["range_ref_source"] == "range_ref"
    assert resolved_hit["citation_status"] == "resolved"
    assert resolved_hit["citation_id"] == bundle["citation_id"]


def test_resolved_evidence_hits_are_directly_usable(tmp_path):
    bundle = _build_resolved_bundle(tmp_path)

    result = bundle_access.query_existing_index(
        bundle["manifest"], "hello", k=1, resolve_evidence=True
    )

    assert result["availability"]["kind"] == "repobrief.snapshot_availability"
    assert result["freshness"]["status"] == "unknown"
    resolved = result["resolved_evidence"]
    assert resolved["availability"] == result["availability"]
    assert resolved["freshness"] == result["freshness"]
    hit = resolved["hits"][0]
    assert hit["text_excerpt"] == bundle["chunk_text"]
    assert hit["text_truncated"] is False
    assert hit["source_path"] == bundle["canonical"].name
    assert hit["line_range"] == {"start_line": 3, "end_line": 3, "display": "3-3"}
    assert hit["source_line_range"] == {"start_line": 3, "end_line": 3, "display": "3-3"}
    assert hit["artifact_role"] == "canonical_md"
    assert hit["artifact_path"] == bundle["canonical"].name
    assert hit["range_ref_verified"] is True
    assert hit["citation_verified"] is True
    assert hit["availability"]["snapshot_status"] == result["availability"]["status"]
    assert hit["availability"]["artifact"]["role"] == "canonical_md"
    assert hit["availability"]["artifact"]["availability"] == "available"
    assert hit["availability"]["index_artifact"]["role"] == "sqlite_index"
    assert hit["availability"]["index_artifact"]["availability"] == "available"
    assert hit["freshness"] == result["freshness"]


def test_repobrief_query_cli_defaults_to_resolved_evidence(tmp_path, capsys):
    from merger.repoground.cli.main import main

    bundle = _build_resolved_bundle(tmp_path)

    rc = main([
        "repobrief",
        "query",
        "--bundle-manifest",
        str(bundle["manifest"]),
        "--q",
        "hello",
        "--k",
        "1",
    ])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["kind"] == "repobrief.query_existing_index"
    assert data["status"] == "available"
    assert data["resolve_evidence"] is True
    assert data["project_sources"] is True
    assert data["evidence_resolution_used"] is True
    assert data["freshness"]["status"] == "unknown"
    assert data["availability"]["kind"] == "repobrief.snapshot_availability"
    hit = data["resolved_evidence"]["hits"][0]
    assert hit["text_excerpt"] == bundle["chunk_text"]
    assert hit["source_path"] == bundle["canonical"].name
    assert hit["line_range"]["display"] == "3-3"
    assert hit["citation_id"] == bundle["citation_id"]
    assert data["source_citation_projection"]["items"][0]["citation_id"] == bundle["citation_id"]
    assert data["mutation_boundary"]["writes"] == []
    assert data["mutation_boundary"]["read_paths_do_not_refresh"] is True


def test_repobrief_query_cli_can_emit_raw_bounded_index_result(tmp_path, capsys):
    from merger.repoground.cli.main import main

    bundle = _build_resolved_bundle(tmp_path)

    rc = main([
        "repobrief",
        "query",
        "--bundle-manifest",
        str(bundle["manifest"]),
        "--q",
        "hello",
        "--k",
        "1",
        "--raw-index-result",
    ])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["resolve_evidence"] is False
    assert data["project_sources"] is False
    assert data["evidence_resolution_used"] is False
    assert data["resolved_evidence"] is None
    assert data["source_citation_projection"] is None
    assert data["query_result"]["count"] == 1
    assert data["freshness"]["status"] == "unknown"
