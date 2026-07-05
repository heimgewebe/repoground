from merger.lenskit.core import repobrief_access
from merger.lenskit.tests.test_repobrief_resolved_evidence_query import _build_resolved_bundle


def test_query_existing_index_projects_source_citations(tmp_path):
    bundle = _build_resolved_bundle(tmp_path)
    result = repobrief_access.query_existing_index(
        bundle["manifest"], "hello", k=5, project_sources=True
    )
    assert result["status"] == "available"
    assert result["project_sources"] is True
    projection = result["source_citation_projection"]
    assert projection["kind"] == "repobrief.source_citation_projection"
    assert projection["hit_count"] == 1
    assert projection["citation_count"] == 1
    assert projection["unresolved_count"] == 0
    item = projection["items"][0]
    assert item["text"] == bundle["chunk_text"]
    assert item["citation_status"] == "resolved"
    assert item["citation_id"] == bundle["citation_id"]
    assert item["source_range"]["file_path"] == bundle["canonical"].name


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


def test_query_existing_index_rejects_non_boolean_project_sources(tmp_path):
    manifest = tmp_path / "demo.bundle.manifest.json"
    manifest.write_text('{"artifacts": []}', encoding="utf-8")
    result = repobrief_access.query_existing_index(
        manifest, "hello", k=1, project_sources="yes"
    )
    assert result["status"] == "invalid"
    assert result["error_code"] == "project_sources_invalid"
