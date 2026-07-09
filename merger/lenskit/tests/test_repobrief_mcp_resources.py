import json
from pathlib import Path

import pytest

from merger.lenskit.core import repobrief_mcp_resources as mcp_resources
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
    _add_artifact(bundle, "extra_json", "extra.json", "{\"ok\": true}\n")

    result = read_mcp_resource(
        "repobrief://snapshot/demo/artifact/extra_json",
        bundle_root=bundle["manifest"].parent,
    )

    assert result["status"] == "available"
    assert result["resource_role"] == "extra_json"
    assert result["content_json"] == {"ok": True}
    assert "mcp_server_available" in result["does_not_establish"]


def test_mcp_read_bundle_manifest_artifact_role_is_available(tmp_path):
    bundle = _complete_basic_bundle(tmp_path)

    result = read_mcp_resource(
        "repobrief://snapshot/demo/artifact/bundle_manifest",
        bundle_root=bundle["manifest"].parent,
    )

    assert result["status"] == "available"
    assert result["resource_role"] == "bundle_manifest"
    assert result["content_json"]["run_id"] == "run-1"


def test_mcp_file_bundle_root_accepts_only_real_bundle_manifest(tmp_path):
    bundle = _complete_basic_bundle(tmp_path)

    ok = read_mcp_resource("repobrief://snapshot/demo/manifest", bundle_root=bundle["manifest"])

    assert ok["status"] == "available"
    assert ok["content_json"]["kind"] == "repolens.bundle.manifest"

    secret = tmp_path / "demo.txt"
    secret.write_text("plain secret\n", encoding="utf-8")
    missing = read_mcp_resource("repobrief://snapshot/demo/manifest", bundle_root=secret)

    assert missing["status"] == "blocked"
    assert missing["reason"] == "bundle root is not a RepoLens bundle manifest file"
    assert "content_text" not in missing


def test_mcp_file_bundle_root_rejects_fake_manifest_shape(tmp_path):
    fake = tmp_path / "fake.bundle.manifest.json"
    fake.write_text(json.dumps({"kind": "not-a-repolens-manifest", "run_id": "fake", "artifacts": []}), encoding="utf-8")

    result = read_mcp_resource("repobrief://snapshot/fake/manifest", bundle_root=fake)

    assert result["status"] == "blocked"
    assert result["reason"] == "bundle root is not a valid RepoLens bundle manifest"
    assert "content_text" not in result


def test_mcp_artifact_resource_blocks_paths_outside_bundle_root(tmp_path):
    bundle = _complete_basic_bundle(tmp_path)
    outside = tmp_path.parent / "secret.txt"
    outside.write_text("do not read me\n", encoding="utf-8")
    data = json.loads(bundle["manifest"].read_text(encoding="utf-8"))
    data["artifacts"].append({
        "role": "escape_attempt",
        "path": str(outside),
        "content_type": "text/plain",
        "bytes": outside.stat().st_size,
        "sha256": "0" * 64,
    })
    bundle["manifest"].write_text(json.dumps(data), encoding="utf-8")

    result = read_mcp_resource(
        "repobrief://snapshot/demo/artifact/escape_attempt",
        bundle_root=bundle["manifest"].parent,
    )

    assert result["status"] == "blocked"
    assert "content_text" not in result
    assert "do not read me" not in json.dumps(result)
    assert result["reason"] == "artifact path escapes bundle root for role: escape_attempt"


def test_mcp_artifact_resource_blocks_relative_escape_paths(tmp_path):
    bundle = _complete_basic_bundle(tmp_path)
    outside = tmp_path.parent / f"{tmp_path.name}-relative-secret.txt"
    outside.write_text("relative secret\n", encoding="utf-8")
    data = json.loads(bundle["manifest"].read_text(encoding="utf-8"))
    data["artifacts"].append({
        "role": "relative_escape",
        "path": f"../{outside.name}",
        "content_type": "text/plain",
        "bytes": outside.stat().st_size,
        "sha256": "0" * 64,
    })
    bundle["manifest"].write_text(json.dumps(data), encoding="utf-8")

    result = read_mcp_resource(
        "repobrief://snapshot/demo/artifact/relative_escape",
        bundle_root=bundle["manifest"].parent,
    )

    assert result["status"] == "blocked"
    assert "content_text" not in result
    assert "relative secret" not in json.dumps(result)


def test_mcp_artifact_resource_blocks_symlink_escape_paths(tmp_path):
    bundle = _complete_basic_bundle(tmp_path)
    outside = tmp_path.parent / f"{tmp_path.name}-symlink-secret.txt"
    outside.write_text("symlink secret\n", encoding="utf-8")
    link = tmp_path / "linked_secret.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation not supported on this platform")
    data = json.loads(bundle["manifest"].read_text(encoding="utf-8"))
    data["artifacts"].append({
        "role": "symlink_escape",
        "path": link.name,
        "content_type": "text/plain",
        "bytes": outside.stat().st_size,
        "sha256": "0" * 64,
    })
    bundle["manifest"].write_text(json.dumps(data), encoding="utf-8")

    result = read_mcp_resource(
        "repobrief://snapshot/demo/artifact/symlink_escape",
        bundle_root=bundle["manifest"].parent,
    )

    assert result["status"] == "blocked"
    assert "content_text" not in result
    assert "symlink secret" not in json.dumps(result)


def test_mcp_artifact_resource_blocks_integrity_mismatch(tmp_path):
    bundle = _complete_basic_bundle(tmp_path)
    _add_artifact(bundle, "mutable", "mutable.txt", "before\n")
    (bundle["manifest"].parent / "mutable.txt").write_text("after\n", encoding="utf-8")

    result = read_mcp_resource(
        "repobrief://snapshot/demo/artifact/mutable",
        bundle_root=bundle["manifest"].parent,
    )

    assert result["status"] == "integrity_mismatch"
    assert "content_text" not in result
    assert result["reason"] in {
        "artifact byte size does not match manifest",
        "artifact sha256 does not match manifest",
    }


def test_mcp_artifact_resource_blocks_missing_integrity_metadata(tmp_path):
    bundle = _complete_basic_bundle(tmp_path)
    data = json.loads(bundle["manifest"].read_text(encoding="utf-8"))
    data["artifacts"].append({
        "role": "no_integrity",
        "path": "no_integrity.txt",
        "content_type": "text/plain",
    })
    (bundle["manifest"].parent / "no_integrity.txt").write_text("not trusted\n", encoding="utf-8")
    bundle["manifest"].write_text(json.dumps(data), encoding="utf-8")

    result = read_mcp_resource(
        "repobrief://snapshot/demo/artifact/no_integrity",
        bundle_root=bundle["manifest"].parent,
    )

    assert result["status"] == "integrity_unavailable"
    assert result["reason"] == "artifact byte size is missing or invalid in manifest"
    assert "content_text" not in result


def test_mcp_artifact_resource_blocks_invalid_sha_metadata(tmp_path):
    bundle = _complete_basic_bundle(tmp_path)
    data = json.loads(bundle["manifest"].read_text(encoding="utf-8"))
    content = "not trusted\n"
    artifact = bundle["manifest"].parent / "bad_sha.txt"
    artifact.write_text(content, encoding="utf-8")
    data["artifacts"].append({
        "role": "bad_sha",
        "path": artifact.name,
        "content_type": "text/plain",
        "bytes": artifact.stat().st_size,
        "sha256": "not-a-sha",
    })
    bundle["manifest"].write_text(json.dumps(data), encoding="utf-8")

    result = read_mcp_resource(
        "repobrief://snapshot/demo/artifact/bad_sha",
        bundle_root=bundle["manifest"].parent,
    )

    assert result["status"] == "integrity_unavailable"
    assert result["reason"] == "artifact sha256 is missing or invalid in manifest"
    assert "content_text" not in result


def test_mcp_artifact_resource_blocks_oversized_content(tmp_path, monkeypatch):
    bundle = _complete_basic_bundle(tmp_path)
    _add_artifact(bundle, "oversized", "oversized.txt", "0123456789\n")
    monkeypatch.setattr(mcp_resources, "MAX_RESOURCE_BYTES", 4)

    result = read_mcp_resource(
        "repobrief://snapshot/demo/artifact/oversized",
        bundle_root=bundle["manifest"].parent,
    )

    assert result["status"] == "blocked"
    assert result["reason"] == "artifact exceeds MCP resource size limit"
    assert "content_text" not in result


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
