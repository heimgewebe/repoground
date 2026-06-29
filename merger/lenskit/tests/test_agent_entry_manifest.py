import json
from pathlib import Path

import jsonschema
import pytest

from merger.lenskit.core.agent_entry_manifest import build_agent_entry_manifest

SCHEMA_PATH = Path(__file__).parent.parent / "contracts" / "agent-entry-manifest.v1.schema.json"


@pytest.fixture
def schema():
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def valid_bundle_fixture() -> dict:
    return {
        "run_id": "run-1",
        "created_at": "2026-06-18T00:00:00Z",
        "artifacts": [
            {
                "role": "canonical_md",
                "path": "lenskit_merge.md",
                "sha256": "abc",
                "authority": "canonical_content",
                "canonicality": "content_source",
            },
            {
                "role": "agent_reading_pack",
                "path": "lenskit_merge.agent_reading_pack.md",
                "sha256": "def",
                "authority": "navigation_index",
                "canonicality": "derived",
            },
            {
                "role": "post_emit_health",
                "path": "lenskit_merge.bundle_health.post.json",
                "sha256": "ghi",
                "authority": "diagnostic",
                "canonicality": "derived",
            },
        ],
    }


def realistic_bundle_manifest_fixture() -> dict:
    return {
        "run_id": "run-xyz",
        "created_at": "2026-06-18T02:00:00Z",
        "artifacts": [
            {
                "role": "canonical_md",
                "path": "merge.md",
                "content_type": "text/markdown",
                "bytes": 100,
                "sha256": "aaaa",
                "authority": "canonical_content",
                "canonicality": "content_source",
                "risk_class": "content"
            },
            {
                "role": "agent_reading_pack",
                "path": "pack.md",
                "content_type": "text/markdown",
                "bytes": 200,
                "sha256": "bbbb",
                "authority": "navigation_index",
                "canonicality": "derived",
                "risk_class": "navigation"
            },
            {
                "role": "claim_evidence_map_json",
                "path": "claim_evidence.json",
                "content_type": "application/json",
                "bytes": 500,
                "sha256": "eeee",
                "authority": "navigation_index",
                "canonicality": "derived",
                "risk_class": "evidence_index"
            },
            {
                "role": "citation_map_jsonl",
                "path": "citation.jsonl",
                "content_type": "application/x-ndjson",
                "bytes": 600,
                "sha256": "ffff",
                "authority": "navigation_index",
                "canonicality": "derived",
                "risk_class": "navigation"
            }
        ],
        "links": {
            "post_emit_health_path": "health.json",
            "bundle_surface_validation_path": "surface_valid.json",
            "bundle_surface_validation_status": "pass"
        }
    }


def test_agent_entry_manifest_minimal_valid(schema):
    report = build_agent_entry_manifest(
        valid_bundle_fixture(),
        created_at="2026-06-18T01:00:00Z",
    )
    jsonschema.validate(instance=report, schema=schema)
    assert report["kind"] == "lenskit.agent_entry_manifest"
    assert report["version"] == "1.0"
    assert report["bundle_run_id"] == "run-1"
    assert report["created_at"] == "2026-06-18T01:00:00Z"
    assert report["authority"] == "navigation_index"
    assert report["canonicality"] == "derived"
    assert report["risk_class"] == "navigation"
    assert report["canonical_source"]["role"] == "canonical_md"


def test_agent_entry_manifest_missing_bundle_run_id_raises():
    bundle = valid_bundle_fixture()
    bundle.pop("run_id")
    with pytest.raises(ValueError, match="bundle_run_id"):
        build_agent_entry_manifest(bundle, created_at="2026-06-18T00:00:00Z")


def test_agent_entry_manifest_missing_canonical_md_raises():
    bundle = {"run_id": "run-1", "artifacts": []}
    with pytest.raises(ValueError, match="canonical_md"):
        build_agent_entry_manifest(bundle, created_at="2026-06-18T00:00:00Z")


def test_agent_entry_manifest_rejects_noncanonical_canonical_md_authority():
    bundle = valid_bundle_fixture()
    bundle["artifacts"][0]["authority"] = "navigation_index"
    with pytest.raises(ValueError, match="canonical_content"):
        build_agent_entry_manifest(bundle, created_at="2026-06-18T00:00:00Z")


def test_agent_entry_manifest_rejects_non_content_source_canonical_md():
    bundle = valid_bundle_fixture()
    bundle["artifacts"][0]["canonicality"] = "derived"
    with pytest.raises(ValueError, match="content_source"):
        build_agent_entry_manifest(bundle, created_at="2026-06-18T00:00:00Z")


def test_agent_entry_manifest_missing_canonical_md_path_raises():
    bundle = valid_bundle_fixture()
    bundle["artifacts"][0].pop("path")
    with pytest.raises(ValueError, match="canonical_md path"):
        build_agent_entry_manifest(bundle, created_at="2026-06-18T00:00:00Z")


def test_agent_entry_manifest_read_first_order_is_deterministic(schema):
    bundle = {
        "run_id": "run-1",
        "artifacts": [
            {
                "role": "post_emit_health",
                "path": "post.json",
                "sha256": "1",
                "authority": "diagnostic",
                "canonicality": "derived",
            },
            {
                "role": "canonical_md",
                "path": "merge.md",
                "sha256": "2",
                "authority": "canonical_content",
                "canonicality": "content_source",
            },
            {
                "role": "agent_reading_pack",
                "path": "pack.md",
                "sha256": "3",
                "authority": "navigation_index",
                "canonicality": "derived",
            },
        ],
    }
    report = build_agent_entry_manifest(bundle, created_at="2026-06-18T00:00:00Z")
    jsonschema.validate(instance=report, schema=schema)
    assert [x["role"] for x in report["read_first"]] == [
        "agent_reading_pack",
        "post_emit_health",
        "canonical_md",
    ]


def test_agent_entry_manifest_reports_unavailable_surfaces(schema):
    bundle = {
        "run_id": "run-1",
        "artifacts": [
            {
                "role": "canonical_md",
                "path": "merge.md",
                "sha256": "abc",
                "authority": "canonical_content",
                "canonicality": "content_source",
            }
        ],
    }
    report = build_agent_entry_manifest(bundle, created_at="2026-06-18T00:00:00Z")
    jsonschema.validate(instance=report, schema=schema)
    unavailable = {x["role"] for x in report["unavailable_surfaces"]}
    assert "agent_reading_pack" in unavailable
    assert "post_emit_health" in unavailable


def test_agent_entry_manifest_export_safety_report_may_be_unavailable(schema):
    report = build_agent_entry_manifest(valid_bundle_fixture(), created_at="2026-06-18T00:00:00Z")
    jsonschema.validate(instance=report, schema=schema)
    unavailable = {x["role"] for x in report["unavailable_surfaces"]}
    assert "export_safety_report" in unavailable


def test_agent_entry_manifest_does_not_establish_boundary(schema):
    report = build_agent_entry_manifest(valid_bundle_fixture(), created_at="2026-06-18T00:00:00Z")
    jsonschema.validate(instance=report, schema=schema)
    required = {
        "repo_understood",
        "answer_safe_without_citations",
        "claims_true",
        "forensic_ready",
        "all_relevant_context_used",
    }
    assert required.issubset(set(report["does_not_establish"]))


def test_agent_entry_manifest_schema_rejects_unknown_top_level_field(schema):
    report = build_agent_entry_manifest(valid_bundle_fixture(), created_at="2026-06-18T00:00:00Z")
    report["safe"] = True
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=report, schema=schema)


def test_agent_entry_manifest_does_not_emit_truth_or_safety_flags(schema):
    report = build_agent_entry_manifest(valid_bundle_fixture(), created_at="2026-06-18T00:00:00Z")
    jsonschema.validate(instance=report, schema=schema)
    forbidden = {
        "safe",
        "ready",
        "verified",
        "correct",
        "complete",
        "repo_understood",
        "claims_true",
        "forensic_ready",
    }
    assert forbidden.isdisjoint(report.keys())


def test_agent_entry_manifest_uses_bundle_created_at_when_not_explicit(schema):
    report = build_agent_entry_manifest(valid_bundle_fixture())
    assert report["created_at"] == "2026-06-18T00:00:00Z"


def test_agent_entry_manifest_created_at_unknown_when_absent(schema):
    bundle = valid_bundle_fixture()
    bundle.pop("created_at")
    report = build_agent_entry_manifest(bundle)
    jsonschema.validate(instance=report, schema=schema)
    assert report["created_at"] == "unknown"


def test_agent_entry_manifest_available_surfaces_include_manifest_artifacts(schema):
    report = build_agent_entry_manifest(valid_bundle_fixture(), created_at="2026-06-18T00:00:00Z")
    jsonschema.validate(instance=report, schema=schema)
    roles = {x["role"] for x in report["available_surfaces"]}
    assert {"canonical_md", "agent_reading_pack", "post_emit_health"}.issubset(roles)


def test_agent_entry_manifest_accepts_realistic_bundle_manifest_shape(schema):
    report = build_agent_entry_manifest(
        realistic_bundle_manifest_fixture(),
        created_at="2026-06-18T02:00:00Z",
    )
    jsonschema.validate(instance=report, schema=schema)
    assert report["bundle_run_id"]
    assert report["canonical_source"]["role"] == "canonical_md"
    assert report["canonical_source"]["authority"] == "canonical_content"
    assert report["canonical_source"]["canonicality"] == "content_source"
    available_roles = {surface["role"] for surface in report["available_surfaces"]}
    assert "canonical_md" in available_roles
    assert "agent_reading_pack" in available_roles
    assert "post_emit_health" in available_roles
    read_first_roles = [surface["role"] for surface in report["read_first"]]
    assert read_first_roles[:1] == ["agent_reading_pack"]


def test_agent_entry_manifest_non_list_artifacts_raises_missing_canonical_md():
    bundle = {
        "run_id": "run-1",
        "artifacts": {
            "role": "canonical_md",
            "path": "merge.md",
            "sha256": "abc",
            "authority": "canonical_content",
            "canonicality": "content_source",
        },
    }
    with pytest.raises(ValueError, match="canonical_md"):
        build_agent_entry_manifest(bundle, created_at="2026-06-18T00:00:00Z")


def test_agent_entry_manifest_ignores_non_dict_artifacts(schema):
    bundle = valid_bundle_fixture()
    bundle["artifacts"].append("bad")
    bundle["artifacts"].append(123)
    report = build_agent_entry_manifest(bundle, created_at="2026-06-18T00:00:00Z")
    jsonschema.validate(instance=report, schema=schema)
    roles = {surface["role"] for surface in report["available_surfaces"]}
    assert "canonical_md" in roles


def test_agent_entry_manifest_skips_artifacts_without_role_or_path(schema):
    bundle = valid_bundle_fixture()
    bundle["artifacts"].extend(
        [
            {"path": "no-role.json", "sha256": "x"},
            {"role": "no_path", "sha256": "y"},
        ]
    )
    report = build_agent_entry_manifest(bundle, created_at="2026-06-18T00:00:00Z")
    jsonschema.validate(instance=report, schema=schema)
    roles = {surface["role"] for surface in report["available_surfaces"]}
    assert "no_path" not in roles


def test_agent_entry_manifest_includes_linked_post_emit_health_in_available_and_read_first(schema):
    bundle = {
        "run_id": "run-1",
        "created_at": "2026-06-18T00:00:00Z",
        "artifacts": [
            {
                "role": "canonical_md",
                "path": "merge.md",
                "sha256": "abc",
                "authority": "canonical_content",
                "canonicality": "content_source",
            },
            {
                "role": "agent_reading_pack",
                "path": "pack.md",
                "sha256": "def",
                "authority": "navigation_index",
                "canonicality": "derived",
            },
        ],
        "links": {
            "post_emit_health_path": "merge.bundle_health.post.json",
        },
    }
    report = build_agent_entry_manifest(bundle, created_at="2026-06-18T01:00:00Z")
    jsonschema.validate(instance=report, schema=schema)
    available = {surface["role"] for surface in report["available_surfaces"]}
    unavailable = {surface["role"] for surface in report["unavailable_surfaces"]}
    read_first = [surface["role"] for surface in report["read_first"]]
    assert "post_emit_health" in available
    assert "post_emit_health" not in unavailable
    assert "post_emit_health" in read_first


def test_agent_entry_manifest_includes_linked_bundle_surface_validation(schema):
    bundle = {
        "run_id": "run-1",
        "created_at": "2026-06-18T00:00:00Z",
        "artifacts": [
            {
                "role": "canonical_md",
                "path": "merge.md",
                "sha256": "abc",
                "authority": "canonical_content",
                "canonicality": "content_source",
            }
        ],
        "links": {
            "bundle_surface_validation_path": "merge.bundle_surface_validation.json",
            "bundle_surface_validation_status": "pass",
        },
    }
    report = build_agent_entry_manifest(bundle, created_at="2026-06-18T01:00:00Z")
    jsonschema.validate(instance=report, schema=schema)
    available = {surface["role"] for surface in report["available_surfaces"]}
    unavailable = {surface["role"] for surface in report["unavailable_surfaces"]}
    assert "bundle_surface_validation" in available
    assert "bundle_surface_validation" not in unavailable


def test_agent_entry_manifest_artifact_surface_wins_over_link_duplicate(schema):
    bundle = {
        "run_id": "run-1",
        "created_at": "2026-06-18T00:00:00Z",
        "artifacts": [
            {
                "role": "canonical_md",
                "path": "merge.md",
                "sha256": "abc",
                "authority": "canonical_content",
                "canonicality": "content_source",
            },
            {
                "role": "post_emit_health",
                "path": "artifact-post.json",
                "sha256": "post-sha",
                "authority": "diagnostic_signal",
                "canonicality": "diagnostic",
            },
        ],
        "links": {
            "post_emit_health_path": "linked-post.json",
        },
    }
    report = build_agent_entry_manifest(bundle, created_at="2026-06-18T01:00:00Z")
    jsonschema.validate(instance=report, schema=schema)
    post_surfaces = [
        surface for surface in report["available_surfaces"]
        if surface["role"] == "post_emit_health"
    ]
    assert len(post_surfaces) == 1
    assert post_surfaces[0]["path"] == "artifact-post.json"
    assert post_surfaces[0]["sha256"] == "post-sha"


def test_agent_entry_manifest_infers_canonical_md_authority_and_canonicality_when_missing(schema):
    bundle = {
        "run_id": "run-1",
        "created_at": "2026-06-18T00:00:00Z",
        "artifacts": [
            {
                "role": "canonical_md",
                "path": "merge.md",
                "sha256": "abc",
            }
        ],
    }
    report = build_agent_entry_manifest(bundle, created_at="2026-06-18T01:00:00Z")
    jsonschema.validate(instance=report, schema=schema)
    assert report["canonical_source"]["authority"] == "canonical_content"
    assert report["canonical_source"]["canonicality"] == "content_source"


def test_agent_entry_manifest_schema_rejects_extra_does_not_establish_value(schema):
    report = build_agent_entry_manifest(valid_bundle_fixture(), created_at="2026-06-18T00:00:00Z")
    report["does_not_establish"].append("invented_boundary")
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=report, schema=schema)


def test_agent_entry_manifest_schema_rejects_duplicate_does_not_establish_value(schema):
    report = build_agent_entry_manifest(valid_bundle_fixture(), created_at="2026-06-18T00:00:00Z")
    report["does_not_establish"] = [
        "repo_understood",
        "repo_understood",
        "answer_safe_without_citations",
        "claims_true",
        "forensic_ready",
    ]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=report, schema=schema)


def test_agent_entry_manifest_rejects_multiple_canonical_md_artifacts():
    bundle = valid_bundle_fixture()
    bundle["artifacts"].append(
        {
            "role": "canonical_md",
            "path": "other.md",
            "sha256": "other",
            "authority": "canonical_content",
            "canonicality": "content_source",
        }
    )
    with pytest.raises(ValueError, match="multiple canonical_md artifacts"):
        build_agent_entry_manifest(bundle, created_at="2026-06-18T00:00:00Z")


def test_agent_entry_manifest_linked_sidecars_have_diagnostic_metadata(schema):
    bundle = {
        "run_id": "run-1",
        "created_at": "2026-06-18T00:00:00Z",
        "artifacts": [
            {
                "role": "canonical_md",
                "path": "merge.md",
                "sha256": "abc",
                "authority": "canonical_content",
                "canonicality": "content_source",
            }
        ],
        "links": {
            "post_emit_health_path": "merge.bundle_health.post.json",
            "bundle_surface_validation_path": "merge.bundle_surface_validation.json",
        },
    }
    report = build_agent_entry_manifest(bundle, created_at="2026-06-18T00:00:00Z")
    jsonschema.validate(instance=report, schema=schema)
    surfaces = {surface["role"]: surface for surface in report["available_surfaces"]}
    assert surfaces["post_emit_health"]["authority"] == "diagnostic_signal"
    assert surfaces["post_emit_health"]["canonicality"] == "diagnostic"
    assert surfaces["bundle_surface_validation"]["authority"] == "diagnostic_signal"
    assert surfaces["bundle_surface_validation"]["canonicality"] == "diagnostic"


def test_agent_entry_manifest_ignores_non_string_link_paths(schema):
    bundle = valid_bundle_fixture()
    bundle["artifacts"] = [
        artifact
        for artifact in bundle["artifacts"]
        if artifact["role"] != "post_emit_health"
    ]
    bundle["links"] = {
        "post_emit_health_path": 123,
        "bundle_surface_validation_path": [],
    }
    report = build_agent_entry_manifest(bundle, created_at="2026-06-18T00:00:00Z")
    jsonschema.validate(instance=report, schema=schema)
    unavailable = {surface["role"] for surface in report["unavailable_surfaces"]}
    assert "post_emit_health" in unavailable
    assert "bundle_surface_validation" in unavailable

def test_agent_entry_manifest_excludes_self_artifact(schema):
    bundle = valid_bundle_fixture()
    bundle["artifacts"].append(
        {
            "role": "agent_entry_manifest",
            "path": "merge.agent_entry_manifest.json",
            "sha256": "self-sha",
            "authority": "navigation_index",
            "canonicality": "derived",
            "risk_class": "navigation",
        }
    )
    report = build_agent_entry_manifest(bundle, created_at="2026-06-18T00:00:00Z")
    jsonschema.validate(instance=report, schema=schema)
    available = {surface["role"] for surface in report["available_surfaces"]}
    assert "agent_entry_manifest" not in available


def test_produce_agent_entry_manifest_writes_default_output(tmp_path, schema):
    from merger.lenskit.core.agent_entry_manifest import produce_agent_entry_manifest

    manifest_path = tmp_path / "bundle.bundle.manifest.json"
    manifest_path.write_text(json.dumps(valid_bundle_fixture()), encoding="utf-8")

    report = produce_agent_entry_manifest(str(manifest_path))

    assert report["status"] == "ok"
    out_path = tmp_path / "bundle.agent_entry_manifest.json"
    assert Path(report["output_path"]) == out_path
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    jsonschema.validate(instance=payload, schema=schema)
    assert payload["kind"] == "lenskit.agent_entry_manifest"
    assert payload["bundle_run_id"] == "run-1"


def test_produce_agent_entry_manifest_rejects_manifest_collision(tmp_path):
    from merger.lenskit.core.agent_entry_manifest import produce_agent_entry_manifest

    manifest_path = tmp_path / "bundle.bundle.manifest.json"
    manifest_path.write_text(json.dumps(valid_bundle_fixture()), encoding="utf-8")

    report = produce_agent_entry_manifest(str(manifest_path), str(manifest_path))

    assert report["status"] == "fail"
    assert report["error_kind"] == "output_path_error"
