from merger.lenskit.core import repobrief_access
from merger.lenskit.tests.test_repobrief_resolved_evidence_query import (
    _build_resolved_bundle,
    _sha256,
    _sqlite_sidecars,
)


def test_query_existing_index_projects_source_citations(tmp_path):
    bundle = _build_resolved_bundle(tmp_path)
    result = repobrief_access.query_existing_index(
        bundle["manifest"], "hello", k=5, project_sources=True
    )
    assert result["status"] == "available"
    assert result["project_sources"] is True
    assert result["resolve_evidence"] is False
    assert result["resolved_evidence"] is None
    assert result["evidence_resolution_used"] is True
    projection = result["source_citation_projection"]
    assert projection["kind"] == "repobrief.source_citation_projection"
    assert projection["hit_count"] == 1
    assert projection["citation_count"] == 1
    assert projection["unresolved_count"] == 0
    assert projection["range_unresolved_count"] == 0
    assert projection["citation_unresolved_count"] == 0
    assert projection["text_excerpt_max_chars"] == repobrief_access.TEXT_EXCERPT_MAX_CHARS
    item = projection["items"][0]
    assert item["text_excerpt"] == bundle["chunk_text"]
    assert item["text_truncated"] is False
    assert item["citation_status"] == "resolved"
    assert item["citation_id"] == bundle["citation_id"]
    assert item["source_range"]["file_path"] == bundle["canonical"].name
    assert item["citation_range"]["file_path"] == bundle["canonical"].name


def test_query_existing_index_projection_is_read_only(tmp_path):
    bundle = _build_resolved_bundle(tmp_path)
    index_path = bundle["index_path"]

    before_files = {path.name for path in tmp_path.iterdir()}
    before_hashes = {path.name: _sha256(path) for path in tmp_path.iterdir() if path.is_file()}

    result = repobrief_access.query_existing_index(
        bundle["manifest"], "hello", k=5, project_sources=True
    )

    after_files = {path.name for path in tmp_path.iterdir()}
    after_hashes = {path.name: _sha256(path) for path in tmp_path.iterdir() if path.is_file()}

    assert result["status"] == "available"
    assert before_files == after_files
    assert before_hashes == after_hashes
    assert not any(path.exists() for path in _sqlite_sidecars(index_path))
    assert result["mutation_boundary"]["writes"] == []


def test_query_existing_index_projection_degrades_without_citation_map(tmp_path):
    bundle = _build_resolved_bundle(tmp_path, with_citation_map=False)
    result = repobrief_access.query_existing_index(
        bundle["manifest"], "hello", k=5, project_sources=True
    )
    item = result["source_citation_projection"]["items"][0]
    assert item["range_status"] == "resolved"
    assert item["citation_status"] == "unavailable"
    assert item["citation_id"] is None
    assert item["citation_range"] is None
    assert item["source_range"]["file_path"] == bundle["canonical"].name
    assert item["source_range"]["start_byte"] is not None
    assert item["source_range"]["end_byte"] is not None


def test_query_existing_index_projection_defaults_off(tmp_path):
    bundle = _build_resolved_bundle(tmp_path)
    result = repobrief_access.query_existing_index(bundle["manifest"], "hello", k=5)
    assert result["status"] == "available"
    assert result["project_sources"] is False
    assert result["source_citation_projection"] is None
    assert result["resolved_evidence"] is None


def test_source_citation_projection_preserves_zero_start_byte():
    source_range = {
        "artifact_role": "canonical_md",
        "file_path": "brief.md",
        "start_byte": 0,
        "end_byte": 5,
        "start_line": 1,
        "end_line": 1,
        "content_sha256": "a" * 64,
    }
    projection = repobrief_access._project_source_citations({
        "hits": [{
            "chunk_id": "c0",
            "path": "brief.md",
            "range_status": "resolved",
            "range_ref_source": "range_ref",
            "range_ref": source_range,
            "range": {"text": "hello", "sha256": "a" * 64},
            "citation_status": "unavailable",
            "citation_id": None,
            "citation": None,
        }]
    })
    item = projection["items"][0]
    assert item["source_range"]["start_byte"] == 0
    assert item["source_range"]["end_byte"] == 5
    assert item["text_excerpt"] == "hello"


def test_source_citation_projection_prefers_complete_citation_range_over_partial_range_ref():
    projection = repobrief_access._project_source_citations({
        "hits": [{
            "chunk_id": "c1",
            "path": "brief.md",
            "range_status": "resolved",
            "range_ref_source": "range_ref",
            "range_ref": {"file_path": "partial.md"},
            "range": {
                "text": "hello",
                "file_path": "range.md",
                "start_byte": 1,
                "end_byte": 6,
                "sha256": "b" * 64,
            },
            "citation_status": "resolved",
            "citation_id": "cit_0000000000000001",
            "citation": {
                "canonical_range": {
                    "file_path": "citation.md",
                    "start_byte": 4,
                    "end_byte": 9,
                    "start_line": 2,
                    "end_line": 2,
                    "content_sha256": "a" * 64,
                }
            },
        }]
    })

    item = projection["items"][0]
    assert item["source_range"]["file_path"] == "citation.md"
    assert item["source_range"]["start_byte"] == 4
    assert item["source_range"]["end_byte"] == 9


def test_source_citation_projection_counts_only_resolved_citations_with_id():
    projection = repobrief_access._project_source_citations({
        "hits": [{
            "chunk_id": "c1",
            "path": "brief.md",
            "range_status": "resolved",
            "range_ref_source": "range_ref",
            "range_ref": {
                "file_path": "brief.md",
                "start_byte": 0,
                "end_byte": 5,
            },
            "range": {"text": "hello"},
            "citation_status": "resolved",
            "citation_id": None,
            "citation": None,
        }]
    })

    assert projection["citation_count"] == 0
    assert projection["range_unresolved_count"] == 0
    assert projection["citation_unresolved_count"] == 0


def test_source_citation_projection_rejects_non_dict_resolved_evidence():
    projection = repobrief_access._project_source_citations(["not", "a", "dict"])

    assert projection["status"] == "unavailable"
    assert projection["hit_count"] == 0
    assert projection["citation_count"] == 0
    assert projection["unresolved_count"] == 0
    assert projection["range_unresolved_count"] == 0
    assert projection["citation_unresolved_count"] == 0
    assert projection["text_excerpt_max_chars"] == repobrief_access.TEXT_EXCERPT_MAX_CHARS
    assert projection["items"] == []


def test_source_range_projection_ignores_bool_line_pair():
    source_range = repobrief_access._source_range_projection({
        "file_path": "brief.md",
        "start_byte": 0,
        "end_byte": 5,
        "lines": [True, 2],
    })

    assert source_range["start_line"] is None
    assert source_range["end_line"] is None


def test_query_existing_index_rejects_non_boolean_project_sources(tmp_path):
    manifest = tmp_path / "demo.bundle.manifest.json"
    manifest.write_text('{"artifacts": []}', encoding="utf-8")
    result = repobrief_access.query_existing_index(
        manifest, "hello", k=1, project_sources="yes"
    )
    assert result["status"] == "invalid"
    assert result["error_code"] == "project_sources_invalid"


def test_source_citation_projection_ignores_structurally_invalid_range_identity():
    projection = repobrief_access._project_source_citations({
        "hits": [{
            "chunk_id": "c1",
            "path": "brief.md",
            "range_status": "resolved",
            "range_ref_source": "range_ref",
            "range_ref": {
                "file_path": "bad.md",
                "start_byte": True,
                "end_byte": 5,
            },
            "range": {
                "text": "hello",
                "file_path": "good.md",
                "start_byte": 0,
                "end_byte": 5,
            },
            "citation_status": "unavailable",
            "citation_id": None,
            "citation": None,
        }]
    })

    assert projection["items"][0]["source_range"]["file_path"] == "good.md"


def test_source_citation_projection_ignores_range_ref_when_range_status_unresolved():
    projection = repobrief_access._project_source_citations({
        "hits": [{
            "chunk_id": "c1",
            "path": "brief.md",
            "range_status": "unresolved",
            "range_ref_source": "range_ref",
            "range_ref": {
                "file_path": "stale.md",
                "start_byte": 0,
                "end_byte": 5,
            },
            "range": {
                "text": "hello",
                "file_path": "resolved-output.md",
                "start_byte": 0,
                "end_byte": 5,
            },
            "citation_status": "unavailable",
            "citation_id": None,
            "citation": None,
        }]
    })

    item = projection["items"][0]
    assert item["source_range"]["file_path"] == "resolved-output.md"
    assert projection["range_unresolved_count"] == 1
