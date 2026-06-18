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
                "role": "post_emit_health",
                "path": "health.json",
                "content_type": "application/json",
                "bytes": 300,
                "sha256": "cccc",
                "authority": "diagnostic",
                "canonicality": "derived",
                "risk_class": "diagnostic"
            },
            {
                "role": "output_health",
                "path": "out.json",
                "content_type": "application/json",
                "bytes": 400,
                "sha256": "dddd",
                "authority": "diagnostic_signal",
                "canonicality": "diagnostic",
                "risk_class": "diagnostic"
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
            },
            {
                "role": "bundle_surface_validation",
                "path": "surface_valid.json",
                "content_type": "application/json",
                "bytes": 700,
                "sha256": "gggg",
                "authority": "diagnostic_signal",
                "canonicality": "diagnostic",
                "risk_class": "diagnostic"
            }
        ]
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

