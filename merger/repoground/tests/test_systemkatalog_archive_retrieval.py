import json

from merger.repoground.retrieval import index_db, query_core
from merger.repoground.retrieval.federation_query import execute_federated_query_from_bundles
from merger.repoground.service.models import FederationQueryRequest, QueryRequest


def _build_systemkatalog_index(tmp_path, *, repo_id="heimgewebe/systemkatalog"):
    bundle = tmp_path / "systemkatalog"
    bundle.mkdir()
    dump_path = bundle / "dump.json"
    chunks_path = bundle / "chunks.jsonl"
    db_path = bundle / "chunk_index.index.sqlite"
    chunks = [
        {
            "chunk_id": "active",
            "repo_id": repo_id,
            "path": "docs/maintenance/current.md",
            "content": "maintenance current system catalog procedure",
            "start_line": 1,
            "end_line": 1,
            "layer": "docs",
            "artifact_type": "doc",
            "content_sha256": "a" * 64,
            "source_file": "docs/maintenance/current.md",
            "start_byte": 0,
            "end_byte": 44,
        },
        {
            "chunk_id": "archive",
            "repo_id": repo_id,
            "path": "docs/archive/cabinet-era/maintenance.md",
            "content": "maintenance archived system catalog procedure",
            "start_line": 1,
            "end_line": 1,
            "layer": "docs",
            "artifact_type": "doc",
            "content_sha256": "b" * 64,
            "source_file": "docs/archive/cabinet-era/maintenance.md",
            "start_byte": 0,
            "end_byte": 45,
        },
        {
            "chunk_id": "archive-windows",
            "repo_id": repo_id,
            "path": r"docs\archive\cabinet-era\legacy.md",
            "content": "maintenance archived legacy system catalog procedure",
            "start_line": 1,
            "end_line": 1,
            "layer": "docs",
            "artifact_type": "doc",
            "content_sha256": "c" * 64,
            "source_file": r"docs\archive\cabinet-era\legacy.md",
            "start_byte": 0,
            "end_byte": 52,
        },
    ]
    with chunks_path.open("w", encoding="utf-8") as handle:
        for chunk in chunks:
            handle.write(json.dumps(chunk) + "\n")
    dump_path.write_text(json.dumps({"fixture": "systemkatalog"}), encoding="utf-8")
    index_db.build_index(dump_path, chunks_path, db_path)
    return bundle, db_path


def test_systemkatalog_current_retrieval_excludes_cabinet_era_by_default(tmp_path):
    _, db_path = _build_systemkatalog_index(tmp_path)

    result = query_core.execute_query(db_path, "maintenance", k=10, explain=True)

    assert [hit["chunk_id"] for hit in result["results"]] == ["active"]
    assert result["applied_filters"]["archive_scope"] == "current"


def test_systemkatalog_history_scope_explicitly_opts_archive_back_in(tmp_path):
    _, db_path = _build_systemkatalog_index(tmp_path)

    result = query_core.execute_query(
        db_path,
        "maintenance",
        k=10,
        filters={"archive_scope": "history"},
    )

    assert {hit["chunk_id"] for hit in result["results"]} == {
        "active",
        "archive",
        "archive-windows",
    }
    assert result["applied_filters"]["archive_scope"] == "history"


def test_federation_uses_published_systemkatalog_identity_for_archive_boundary(tmp_path):
    bundle, _ = _build_systemkatalog_index(tmp_path, repo_id="legacy-local-id")
    specs = [{"repo_id": "heimgewebe/systemkatalog", "bundle_path": bundle.name}]

    current = execute_federated_query_from_bundles(
        specs,
        "maintenance",
        k=10,
        base_path=tmp_path,
    )
    history = execute_federated_query_from_bundles(
        specs,
        "maintenance",
        k=10,
        filters={"archive_scope": "history"},
        base_path=tmp_path,
    )

    assert [hit["chunk_id"] for hit in current["results"]] == ["active"]
    assert {hit["chunk_id"] for hit in history["results"]} == {
        "active",
        "archive",
        "archive-windows",
    }


def test_query_models_default_to_current_and_allow_explicit_history():
    direct = QueryRequest(index_id="systemkatalog", q="maintenance")
    federated = FederationQueryRequest(
        federation_index="fleet.json",
        q="maintenance",
        archive_scope="history",
    )

    assert direct.archive_scope == "current"
    assert federated.archive_scope == "history"
