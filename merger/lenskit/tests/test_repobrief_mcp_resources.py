import json
from pathlib import Path

import pytest

from merger.lenskit.core.repobrief_mcp_resources import (
    RepoBriefMcpResourceError,
    list_mcp_resources,
    read_mcp_resource,
    resource_templates,
)
from merger.lenskit.tests.test_repobrief_ask_cli import _add_artifact, _complete_basic_bundle


def _bundle_with_health(tmp_path: Path) -> dict:
    bundle = _complete_basic_bundle(tmp_path)
    _add_artifact(
        bundle,
        "post_emit_health",
        "demo.bundle_health.post.json",
        json.dumps({"kind": "health", "status": "pass"}) + "\n",
    )
    return bundle


def test_mcp_resource_templates_define_read_only_snapshot_surface():
    templates = resource_templates()

    assert templates["templates"] == [
        "repobrief://snapshot/{stem}/manifest",
        "repobrief://snapshot/{stem}/canonical",
        "repobrief://snapshot/{stem}/reading-pack",
        "repobrief://snapshot/{stem}/health",
        "repobrief://snapshot/{stem}/availability",
        "repobrief://snapshot/{stem}/artifact/{role}",
    ]
    assert templates["mutation_boundary"]["writes"] == []
    assert templates["mutation_boundary"]["does_not_create_snapshots"] is True
    assert "git_fetch" in templates["mutation_boundary"]["forbidden_operations"]
    assert "secret_read" in templates["mutation_boundary"]["forbidden_operations"]


def test_mcp_resource_list_exposes_concrete_snapshot_resources(tmp_path):
    bundle = _bundle_with_health(tmp_path)

    listed = list_mcp_resources(bundle["manifest"].parent)
    uris = {item["uri"] for item in listed["resources"]}

    assert "repobrief://snapshot/demo/manifest" in uris
    assert "repobrief://snapshot/demo/canonical" in uris
    assert "repobrief://snapshot/demo/reading-pack" in uris
    assert "repobrief://snapshot/demo/health" in uris
    assert "repobrief://snapshot/demo/availability" in uris
    assert "repobrief://snapshot/demo/artifact/canonical_md" in uris
    assert listed["mutation_boundary"]["writes"] == []


def test_mcp_read_manifest_resource_carries_context_and_content(tmp_path):
    bundle = _bundle_with_health(tmp_path)

    result = read_mcp_resource(
        "repobrief://snapshot/demo/manifest",
        bundle_root=bundle["manifest"].parent,
    )

    assert result["status"] == "available"
    assert result["resource_role"] == "bundle_manifest"
    assert result["content_json"]["run_id"] == "run-1"
    assert result["snapshot_context"]["health"]["status"] == "available"
    assert "freshness" in result["snapshot_context"]
    assert "availability" in result["snapshot_context"]
    assert result["mutation_boundary"]["read_paths_do_not_refresh"] is True


def test_mcp_read_canonical_reading_pack_health_and_availability_resources(tmp_path):
    bundle = _bundle_with_health(tmp_path)

    canonical = read_mcp_resource("repobrief://snapshot/demo/canonical", bundle_root=bundle["manifest"].parent)
    reading = read_mcp_resource("repobrief://snapshot/demo/reading-pack", bundle_root=bundle["manifest"].parent)
    health = read_mcp_resource("repobrief://snapshot/demo/health", bundle_root=bundle["manifest"].parent)
    availability = read_mcp_resource("repobrief://snapshot/demo/availability", bundle_root=bundle["manifest"].parent)

    assert canonical["resource_role"] == "canonical_md"
    assert "hello resolved world" in canonical["content_text"]
    assert reading["resource_role"] == "agent_reading_pack"
    assert "Agent pack" in reading["content_text"]
    assert health["resource_role"] == "post_emit_health"
    assert health["content_json"]["status"] == "pass"
    assert availability["resource_role"] == "availability_model"
    assert availability["content_json"]["status"] in {"available", "partial", "missing", "unknown", "pass", "warn", "fail"}


def test_mcp_read_arbitrary_artifact_resource(tmp_path):
    bundle = _complete_basic_bundle(tmp_path)

    result = read_mcp_resource(
        "repobrief://snapshot/demo/artifact/citation_map_jsonl",
        bundle_root=bundle["manifest"].parent,
    )

    assert result["status"] == "available"
    assert result["resource_role"] == "citation_map_jsonl"
    assert "cit_" in result["content_text"]
    assert "mcp_server_available" in result["does_not_establish"]


def test_each_listed_mcp_resource_read_carries_context(tmp_path):
    bundle = _bundle_with_health(tmp_path)
    listed = list_mcp_resources(bundle["manifest"].parent)

    for item in listed["resources"]:
        result = read_mcp_resource(item["uri"], bundle_root=bundle["manifest"].parent)
        assert "health" in result["snapshot_context"]
        assert "freshness" in result["snapshot_context"]
        assert "availability" in result["snapshot_context"]
        assert result["mutation_boundary"]["writes"] == []
        assert result["mutation_boundary"]["does_not_create_snapshots"] is True



def test_mcp_missing_snapshot_explains_missing_context(tmp_path):
    result = read_mcp_resource("repobrief://snapshot/missing/manifest", bundle_root=tmp_path)

    assert result["status"] == "missing"
    assert result["bundle_manifest"] is None
    assert result["snapshot_context"]["availability"]["status"] == "unknown"
    assert "snapshot stem not found" in result["snapshot_context"]["availability"]["reason"]


def test_mcp_resource_reads_do_not_write_bundle_files(tmp_path):
    bundle = _bundle_with_health(tmp_path)
    before = {path.name for path in tmp_path.iterdir()}

    read_mcp_resource("repobrief://snapshot/demo/manifest", bundle_root=bundle["manifest"].parent)
    read_mcp_resource("repobrief://snapshot/demo/canonical", bundle_root=bundle["manifest"].parent)
    list_mcp_resources(bundle["manifest"].parent)

    after = {path.name for path in tmp_path.iterdir()}
    assert after == before


@pytest.mark.parametrize(
    "uri",
    [
        "file:///tmp/demo",
        "repobrief://snapshot/demo/unknown",
        "repobrief://snapshot/demo/artifact",
        "repobrief://snapshot/../manifest",
        "repobrief://snapshot/demo/artifact/../secret",
    ],
)
def test_mcp_resource_rejects_invalid_or_escape_uris(tmp_path, uri):
    with pytest.raises(RepoBriefMcpResourceError):
        read_mcp_resource(uri, bundle_root=tmp_path)
