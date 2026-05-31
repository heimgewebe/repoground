import json
import pytest
from pathlib import Path

import jsonschema
from merger.lenskit.tests._test_constants import TEST_CONFIG_SHA256, TEST_ARTIFACT_SHA256


def _assert_manifest_has_output_health_presence_gate(manifest: dict):
    roles = {artifact["role"] for artifact in manifest["artifacts"]}
    assert "output_health" in roles, "bundle manifest semantic gate requires an output_health artifact"

@pytest.fixture
def schema():
    schema_path = Path(__file__).parent.parent / "contracts" / "bundle-manifest.v1.schema.json"
    with schema_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def test_valid_bundle_manifest(schema):
    valid_data = {
        "kind": "repolens.bundle.manifest",
        "version": "1.0",
        "run_id": "test-run-1234",
        "created_at": "2023-10-12T10:00:00Z",
        "generator": {
            "name": "lenskit-test",
            "version": "v1.2.3",
            "config_sha256": TEST_CONFIG_SHA256
        },
        "artifacts": [
            {
                "role": "canonical_md",
                "path": "output.md",
                "content_type": "text/markdown",
                "bytes": 1024,
                "sha256": TEST_ARTIFACT_SHA256,
                "interpretation": {"mode": "role_only"}
            },
            {
                "role": "index_sidecar_json",
                "path": "sidecar.json",
                "content_type": "application/json",
                "bytes": 2048,
                "sha256": TEST_ARTIFACT_SHA256,
                "contract": {
                    "id": "repolens-agent",
                    "version": "v2"
                },
                "interpretation": {"mode": "contract"}
            }
        ],
        "links": {
            "canonical_dump_index_sha256": TEST_ARTIFACT_SHA256
        },
        "capabilities": {
            "fts5_bm25": True
        }
    }
    jsonschema.validate(instance=valid_data, schema=schema)


def test_manifest_health_gate_accepts_output_health(schema):
    valid_data = {
        "kind": "repolens.bundle.manifest",
        "version": "1.0",
        "run_id": "test-run-1234",
        "created_at": "2023-10-12T10:00:00Z",
        "generator": {
            "name": "lenskit-test",
            "version": "v1.2.3",
            "config_sha256": TEST_CONFIG_SHA256
        },
        "artifacts": [
            {
                "role": "canonical_md",
                "path": "output.md",
                "content_type": "text/markdown",
                "bytes": 1024,
                "sha256": TEST_ARTIFACT_SHA256,
                "interpretation": {"mode": "role_only"}
            },
            {
                "role": "output_health",
                "path": "output.output_health.json",
                "content_type": "application/json",
                "bytes": 512,
                "sha256": TEST_ARTIFACT_SHA256,
                "interpretation": {"mode": "role_only"}
            }
        ],
        "links": {},
        "capabilities": {}
    }

    jsonschema.validate(instance=valid_data, schema=schema)
    _assert_manifest_has_output_health_presence_gate(valid_data)


def test_missing_output_health_passes_schema_but_fails_presence_gate(schema):
    manifest_without_output_health = {
        "kind": "repolens.bundle.manifest",
        "version": "1.0",
        "run_id": "test-run-1234",
        "created_at": "2023-10-12T10:00:00Z",
        "generator": {
            "name": "lenskit-test",
            "version": "v1.2.3",
            "config_sha256": TEST_CONFIG_SHA256
        },
        "artifacts": [
            {
                "role": "canonical_md",
                "path": "output.md",
                "content_type": "text/markdown",
                "bytes": 1024,
                "sha256": TEST_ARTIFACT_SHA256,
                "interpretation": {"mode": "role_only"}
            }
        ],
        "links": {},
        "capabilities": {}
    }

    # The JSON schema enforces structural validity and remains backward-compatible
    # with historical or minimal manifests. Requiring output_health is a separate
    # output_health presence gate, not a v1 schema constraint.
    jsonschema.validate(instance=manifest_without_output_health, schema=schema)
    with pytest.raises(AssertionError, match="output_health"):
        _assert_manifest_has_output_health_presence_gate(manifest_without_output_health)


def test_invalid_bundle_manifest_role_only_with_contract(schema):
    invalid_data = {
        "kind": "repolens.bundle.manifest",
        "version": "1.0",
        "run_id": "test-run-1234",
        "created_at": "2023-10-12T10:00:00Z",
        "generator": {
            "name": "lenskit-test",
            "version": "v1.2.3",
            "config_sha256": TEST_CONFIG_SHA256
        },
        "artifacts": [
            {
                "role": "canonical_md",
                "path": "output.md",
                "content_type": "text/markdown",
                "bytes": 1024,
                "sha256": TEST_ARTIFACT_SHA256,
                "interpretation": {"mode": "role_only"},
                "contract": {"id": "foo", "version": "1.0"}
            }
        ],
        "links": {},
        "capabilities": {}
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=invalid_data, schema=schema)


def test_invalid_bundle_manifest_contract_missing_interpretation(schema):
    invalid_data = {
        "kind": "repolens.bundle.manifest",
        "version": "1.0",
        "run_id": "test-run-1234",
        "created_at": "2023-10-12T10:00:00Z",
        "generator": {
            "name": "lenskit-test",
            "version": "v1.2.3",
            "config_sha256": TEST_CONFIG_SHA256
        },
        "artifacts": [
            {
                "role": "index_sidecar_json",
                "path": "sidecar.json",
                "content_type": "application/json",
                "bytes": 2048,
                "sha256": TEST_ARTIFACT_SHA256,
                "contract": {
                    "id": "repolens-agent",
                    "version": "v2"
                }
            }
        ],
        "links": {},
        "capabilities": {}
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=invalid_data, schema=schema)


def test_invalid_bundle_manifest_interpretation_contract_without_contract(schema):
    invalid_data = {
        "kind": "repolens.bundle.manifest",
        "version": "1.0",
        "run_id": "test-run-1234",
        "created_at": "2023-10-12T10:00:00Z",
        "generator": {
            "name": "lenskit-test",
            "version": "v1.2.3",
            "config_sha256": TEST_CONFIG_SHA256
        },
        "artifacts": [
            {
                "role": "canonical_md",
                "path": "output.md",
                "content_type": "text/markdown",
                "bytes": 1024,
                "sha256": TEST_ARTIFACT_SHA256,
                "interpretation": {"mode": "contract"}
            }
        ],
        "links": {},
        "capabilities": {}
    }

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=invalid_data, schema=schema)


def test_valid_bundle_manifest_missing_interpretation_for_role_only_artifact(schema):
    valid_data = {
        "kind": "repolens.bundle.manifest",
        "version": "1.0",
        "run_id": "test-run-1234",
        "created_at": "2023-10-12T10:00:00Z",
        "generator": {
            "name": "lenskit-test",
            "version": "v1.2.3",
            "config_sha256": TEST_CONFIG_SHA256
        },
        "artifacts": [
            {
                "role": "canonical_md",
                "path": "output.md",
                "content_type": "text/markdown",
                "bytes": 1024,
                "sha256": TEST_ARTIFACT_SHA256
                # interpretation omitted for backward compatibility
            }
        ],
        "links": {},
        "capabilities": {}
    }

    jsonschema.validate(instance=valid_data, schema=schema)


def test_invalid_bundle_manifest_missing_required(schema):
    invalid_data = {
        "kind": "repolens.bundle.manifest",
        "version": "1.0"
        # missing run_id, created_at, generator, artifacts, links, capabilities
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=invalid_data, schema=schema)


def test_invalid_bundle_manifest_bad_role(schema):
    invalid_data = {
        "kind": "repolens.bundle.manifest",
        "version": "1.0",
        "run_id": "test-run-1234",
        "created_at": "2023-10-12T10:00:00Z",
        "generator": {
            "name": "lenskit-test",
            "version": "v1.2.3",
            "config_sha256": TEST_CONFIG_SHA256
        },
        "artifacts": [
            {
                "role": "invalid_role_not_in_enum",
                "path": "output.md",
                "content_type": "text/markdown",
                "bytes": 1024,
                "sha256": TEST_ARTIFACT_SHA256,
                "interpretation": {"mode": "role_only"}
            }
        ],
        "links": {},
        "capabilities": {}
    }
    with pytest.raises(jsonschema.ValidationError) as exc:
        jsonschema.validate(instance=invalid_data, schema=schema)
    assert exc.value.validator == "enum"
    assert exc.value.instance == "invalid_role_not_in_enum"


# ---------------------------------------------------------------------------
# Authority / canonicality (Phase 1 of Artifact Integrity blueprint).
# Fields stay optional in v1.0 for backward compatibility, but values are
# constrained per role when present so that index/cache/diagnostic artifacts
# cannot disguise themselves as canonical content.
# ---------------------------------------------------------------------------


def _wrap_artifact(artifact_entry):
    return {
        "kind": "repolens.bundle.manifest",
        "version": "1.0",
        "run_id": "test-run-authority",
        "created_at": "2026-04-26T10:00:00Z",
        "generator": {
            "name": "lenskit-test",
            "version": "v1.2.3",
            "config_sha256": TEST_CONFIG_SHA256
        },
        "artifacts": [artifact_entry],
        "links": {},
        "capabilities": {}
    }


def test_authority_fields_optional_for_canonical_md(schema):
    artifact = {
        "role": "canonical_md",
        "path": "output.md",
        "content_type": "text/markdown",
        "bytes": 1024,
        "sha256": TEST_ARTIFACT_SHA256
        # authority/canonicality omitted: must remain valid (backward compat).
    }
    jsonschema.validate(instance=_wrap_artifact(artifact), schema=schema)


def test_authority_fields_accepted_when_correct(schema):
    artifact = {
        "role": "canonical_md",
        "path": "output.md",
        "content_type": "text/markdown",
        "bytes": 1024,
        "sha256": TEST_ARTIFACT_SHA256,
        "authority": "canonical_content",
        "canonicality": "content_source",
        "regenerable": True,
        "staleness_sensitive": False
    }
    jsonschema.validate(instance=_wrap_artifact(artifact), schema=schema)


def test_sqlite_index_cannot_claim_canonical_content(schema):
    artifact = {
        "role": "sqlite_index",
        "path": "out.index.sqlite",
        "content_type": "application/octet-stream",
        "bytes": 4096,
        "sha256": TEST_ARTIFACT_SHA256,
        "interpretation": {"mode": "role_only"},
        "authority": "canonical_content"  # forbidden: cache must not pose as content source
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=_wrap_artifact(artifact), schema=schema)


def test_architecture_summary_cannot_claim_content_source(schema):
    artifact = {
        "role": "architecture_summary",
        "path": "out_architecture.md",
        "content_type": "text/markdown",
        "bytes": 2048,
        "sha256": TEST_ARTIFACT_SHA256,
        "contract": {"id": "architecture-summary", "version": "v1"},
        "interpretation": {"mode": "contract"},
        "canonicality": "content_source"  # forbidden: diagnostic must not pose as content source
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=_wrap_artifact(artifact), schema=schema)


def test_index_sidecar_json_cannot_claim_content_source(schema):
    artifact = {
        "role": "index_sidecar_json",
        "path": "sidecar.json",
        "content_type": "application/json",
        "bytes": 2048,
        "sha256": TEST_ARTIFACT_SHA256,
        "contract": {"id": "repolens-agent", "version": "v2"},
        "interpretation": {"mode": "contract"},
        "canonicality": "content_source"  # forbidden: navigation index, not content
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=_wrap_artifact(artifact), schema=schema)


def test_canonical_md_cannot_be_marked_as_cache(schema):
    artifact = {
        "role": "canonical_md",
        "path": "output.md",
        "content_type": "text/markdown",
        "bytes": 1024,
        "sha256": TEST_ARTIFACT_SHA256,
        "authority": "runtime_cache"  # forbidden: canonical content must keep its authority
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=_wrap_artifact(artifact), schema=schema)


def test_authority_unknown_value_rejected(schema):
    artifact = {
        "role": "canonical_md",
        "path": "output.md",
        "content_type": "text/markdown",
        "bytes": 1024,
        "sha256": TEST_ARTIFACT_SHA256,
        "authority": "not_a_real_authority"
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=_wrap_artifact(artifact), schema=schema)


def test_canonicality_unknown_value_rejected(schema):
    artifact = {
        "role": "canonical_md",
        "path": "output.md",
        "content_type": "text/markdown",
        "bytes": 1024,
        "sha256": TEST_ARTIFACT_SHA256,
        "canonicality": "wishful_thinking"
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=_wrap_artifact(artifact), schema=schema)


# Phase 3.5: per-role authority/canonicality constraints for additional
# bundle-manifest roles. Producer-emitted roles (retrieval_eval_json,
# graph_index_json) are now annotated by the producer; delta_json carries
# its constraint as a future-form so that any external manifest builder
# cannot misrepresent it as canonical content.

def test_retrieval_eval_json_authority_accepted_when_correct(schema):
    artifact = {
        "role": "retrieval_eval_json",
        "path": "out.retrieval_eval.json",
        "content_type": "application/json",
        "bytes": 2048,
        "sha256": TEST_ARTIFACT_SHA256,
        "contract": {"id": "retrieval-eval", "version": "v1"},
        "interpretation": {"mode": "contract"},
        "authority": "diagnostic_signal",
        "canonicality": "diagnostic",
        "regenerable": True,
        "staleness_sensitive": True
    }
    jsonschema.validate(instance=_wrap_artifact(artifact), schema=schema)


def test_retrieval_eval_json_cannot_claim_content_source(schema):
    artifact = {
        "role": "retrieval_eval_json",
        "path": "out.retrieval_eval.json",
        "content_type": "application/json",
        "bytes": 2048,
        "sha256": TEST_ARTIFACT_SHA256,
        "contract": {"id": "retrieval-eval", "version": "v1"},
        "interpretation": {"mode": "contract"},
        "canonicality": "content_source"  # forbidden: diagnostic, not content
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=_wrap_artifact(artifact), schema=schema)


def test_retrieval_eval_json_cannot_claim_canonical_content(schema):
    artifact = {
        "role": "retrieval_eval_json",
        "path": "out.retrieval_eval.json",
        "content_type": "application/json",
        "bytes": 2048,
        "sha256": TEST_ARTIFACT_SHA256,
        "contract": {"id": "retrieval-eval", "version": "v1"},
        "interpretation": {"mode": "contract"},
        "authority": "canonical_content"  # forbidden: eval is diagnostic, not canonical
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=_wrap_artifact(artifact), schema=schema)


def test_graph_index_json_authority_accepted_when_correct(schema):
    artifact = {
        "role": "graph_index_json",
        "path": "out.graph_index.json",
        "content_type": "application/json",
        "bytes": 2048,
        "sha256": TEST_ARTIFACT_SHA256,
        "contract": {"id": "architecture.graph_index", "version": "v1"},
        "interpretation": {"mode": "contract"},
        "authority": "retrieval_index",
        "canonicality": "derived",
        "regenerable": True,
        "staleness_sensitive": True
    }
    jsonschema.validate(instance=_wrap_artifact(artifact), schema=schema)


def test_graph_index_json_cannot_claim_canonical_content(schema):
    artifact = {
        "role": "graph_index_json",
        "path": "out.graph_index.json",
        "content_type": "application/json",
        "bytes": 2048,
        "sha256": TEST_ARTIFACT_SHA256,
        "contract": {"id": "architecture.graph_index", "version": "v1"},
        "interpretation": {"mode": "contract"},
        "authority": "canonical_content"  # forbidden: derived index, not canonical content
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=_wrap_artifact(artifact), schema=schema)


def test_graph_index_json_cannot_claim_content_source(schema):
    artifact = {
        "role": "graph_index_json",
        "path": "out.graph_index.json",
        "content_type": "application/json",
        "bytes": 2048,
        "sha256": TEST_ARTIFACT_SHA256,
        "contract": {"id": "architecture.graph_index", "version": "v1"},
        "interpretation": {"mode": "contract"},
        "canonicality": "content_source"  # forbidden: graph index does not contain content
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=_wrap_artifact(artifact), schema=schema)


def test_delta_json_cannot_claim_content_source(schema):
    artifact = {
        "role": "delta_json",
        "path": "delta.json",
        "content_type": "application/json",
        "bytes": 1024,
        "sha256": TEST_ARTIFACT_SHA256,
        "contract": {"id": "pr-schau-delta", "version": "1.0"},
        "interpretation": {"mode": "contract"},
        "canonicality": "content_source"  # forbidden: delta is diagnostic, not content
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=_wrap_artifact(artifact), schema=schema)


def test_delta_json_cannot_claim_canonical_content(schema):
    artifact = {
        "role": "delta_json",
        "path": "delta.json",
        "content_type": "application/json",
        "bytes": 1024,
        "sha256": TEST_ARTIFACT_SHA256,
        "contract": {"id": "pr-schau-delta", "version": "1.0"},
        "interpretation": {"mode": "contract"},
        "authority": "canonical_content"  # forbidden: delta is diagnostic, not canonical
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=_wrap_artifact(artifact), schema=schema)


# ---------------------------------------------------------------------------
# citation_map_jsonl: navigation_index / derived (Phase 1 — registry-only,
# no producer yet). Old bundles without this role remain valid.
# ---------------------------------------------------------------------------

def test_citation_map_jsonl_valid_with_correct_authority(schema):
    # All required and constrained fields present and correct.
    artifact = {
        "role": "citation_map_jsonl",
        "path": "out.citation_map.jsonl",
        "content_type": "application/x-ndjson",
        "bytes": 2048,
        "sha256": TEST_ARTIFACT_SHA256,
        "contract": {"id": "citation-map", "version": "v1"},
        "interpretation": {"mode": "contract"},
        "authority": "navigation_index",
        "canonicality": "derived",
        "regenerable": True,
        "staleness_sensitive": True
    }
    jsonschema.validate(instance=_wrap_artifact(artifact), schema=schema)


def test_citation_map_jsonl_requires_authority(schema):
    # Missing authority field.
    artifact = {
        "role": "citation_map_jsonl",
        "path": "out.citation_map.jsonl",
        "content_type": "application/x-ndjson",
        "bytes": 2048,
        "sha256": TEST_ARTIFACT_SHA256,
        "contract": {"id": "citation-map", "version": "v1"},
        "interpretation": {"mode": "contract"},
        "canonicality": "derived",
        "regenerable": True,
        "staleness_sensitive": True
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=_wrap_artifact(artifact), schema=schema)


def test_citation_map_jsonl_requires_canonicality(schema):
    # Missing canonicality field.
    artifact = {
        "role": "citation_map_jsonl",
        "path": "out.citation_map.jsonl",
        "content_type": "application/x-ndjson",
        "bytes": 2048,
        "sha256": TEST_ARTIFACT_SHA256,
        "contract": {"id": "citation-map", "version": "v1"},
        "interpretation": {"mode": "contract"},
        "authority": "navigation_index",
        "regenerable": True,
        "staleness_sensitive": True
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=_wrap_artifact(artifact), schema=schema)


def test_citation_map_jsonl_requires_contract(schema):
    # Missing contract field.
    artifact = {
        "role": "citation_map_jsonl",
        "path": "out.citation_map.jsonl",
        "content_type": "application/x-ndjson",
        "bytes": 2048,
        "sha256": TEST_ARTIFACT_SHA256,
        "interpretation": {"mode": "role_only"},
        "authority": "navigation_index",
        "canonicality": "derived",
        "regenerable": True,
        "staleness_sensitive": True
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=_wrap_artifact(artifact), schema=schema)


def test_citation_map_jsonl_requires_regenerable(schema):
    # Missing regenerable field.
    artifact = {
        "role": "citation_map_jsonl",
        "path": "out.citation_map.jsonl",
        "content_type": "application/x-ndjson",
        "bytes": 2048,
        "sha256": TEST_ARTIFACT_SHA256,
        "contract": {"id": "citation-map", "version": "v1"},
        "interpretation": {"mode": "contract"},
        "authority": "navigation_index",
        "canonicality": "derived",
        "staleness_sensitive": True
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=_wrap_artifact(artifact), schema=schema)


def test_citation_map_jsonl_requires_staleness_sensitive(schema):
    # Missing staleness_sensitive field.
    artifact = {
        "role": "citation_map_jsonl",
        "path": "out.citation_map.jsonl",
        "content_type": "application/x-ndjson",
        "bytes": 2048,
        "sha256": TEST_ARTIFACT_SHA256,
        "contract": {"id": "citation-map", "version": "v1"},
        "interpretation": {"mode": "contract"},
        "authority": "navigation_index",
        "canonicality": "derived",
        "regenerable": True
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=_wrap_artifact(artifact), schema=schema)


def test_citation_map_jsonl_wrong_contract_id_rejected(schema):
    # Wrong contract id.
    artifact = {
        "role": "citation_map_jsonl",
        "path": "out.citation_map.jsonl",
        "content_type": "application/x-ndjson",
        "bytes": 2048,
        "sha256": TEST_ARTIFACT_SHA256,
        "contract": {"id": "wrong-contract", "version": "v1"},
        "interpretation": {"mode": "contract"},
        "authority": "navigation_index",
        "canonicality": "derived",
        "regenerable": True,
        "staleness_sensitive": True
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=_wrap_artifact(artifact), schema=schema)


def test_citation_map_jsonl_wrong_contract_version_rejected(schema):
    # Wrong contract version.
    artifact = {
        "role": "citation_map_jsonl",
        "path": "out.citation_map.jsonl",
        "content_type": "application/x-ndjson",
        "bytes": 2048,
        "sha256": TEST_ARTIFACT_SHA256,
        "contract": {"id": "citation-map", "version": "v2"},
        "interpretation": {"mode": "contract"},
        "authority": "navigation_index",
        "canonicality": "derived",
        "regenerable": True,
        "staleness_sensitive": True
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=_wrap_artifact(artifact), schema=schema)


def test_citation_map_jsonl_wrong_content_type_rejected(schema):
    # Wrong content_type.
    artifact = {
        "role": "citation_map_jsonl",
        "path": "out.citation_map.jsonl",
        "content_type": "application/json",
        "bytes": 2048,
        "sha256": TEST_ARTIFACT_SHA256,
        "contract": {"id": "citation-map", "version": "v1"},
        "interpretation": {"mode": "contract"},
        "authority": "navigation_index",
        "canonicality": "derived",
        "regenerable": True,
        "staleness_sensitive": True
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=_wrap_artifact(artifact), schema=schema)


def test_citation_map_jsonl_regenerable_false_rejected(schema):
    # regenerable must be true.
    artifact = {
        "role": "citation_map_jsonl",
        "path": "out.citation_map.jsonl",
        "content_type": "application/x-ndjson",
        "bytes": 2048,
        "sha256": TEST_ARTIFACT_SHA256,
        "contract": {"id": "citation-map", "version": "v1"},
        "interpretation": {"mode": "contract"},
        "authority": "navigation_index",
        "canonicality": "derived",
        "regenerable": False,
        "staleness_sensitive": True
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=_wrap_artifact(artifact), schema=schema)


def test_citation_map_jsonl_staleness_sensitive_false_rejected(schema):
    # staleness_sensitive must be true.
    artifact = {
        "role": "citation_map_jsonl",
        "path": "out.citation_map.jsonl",
        "content_type": "application/x-ndjson",
        "bytes": 2048,
        "sha256": TEST_ARTIFACT_SHA256,
        "contract": {"id": "citation-map", "version": "v1"},
        "interpretation": {"mode": "contract"},
        "authority": "navigation_index",
        "canonicality": "derived",
        "regenerable": True,
        "staleness_sensitive": False
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=_wrap_artifact(artifact), schema=schema)


def test_citation_map_jsonl_optional_old_bundle_remains_valid(schema):
    # Existing bundle without citation_map_jsonl must stay valid.
    artifact = {
        "role": "canonical_md",
        "path": "output.md",
        "content_type": "text/markdown",
        "bytes": 1024,
        "sha256": TEST_ARTIFACT_SHA256,
        "interpretation": {"mode": "role_only"}
    }
    jsonschema.validate(instance=_wrap_artifact(artifact), schema=schema)


def test_citation_map_jsonl_cannot_claim_canonical_content(schema):
    # Wrong authority value (must be navigation_index).
    artifact = {
        "role": "citation_map_jsonl",
        "path": "out.citation_map.jsonl",
        "content_type": "application/x-ndjson",
        "bytes": 2048,
        "sha256": TEST_ARTIFACT_SHA256,
        "contract": {"id": "citation-map", "version": "v1"},
        "interpretation": {"mode": "contract"},
        "authority": "canonical_content",  # forbidden: navigation index, not content
        "canonicality": "derived",
        "regenerable": True,
        "staleness_sensitive": True
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=_wrap_artifact(artifact), schema=schema)


def test_citation_map_jsonl_cannot_claim_runtime_cache(schema):
    # Wrong authority value (must be navigation_index).
    artifact = {
        "role": "citation_map_jsonl",
        "path": "out.citation_map.jsonl",
        "content_type": "application/x-ndjson",
        "bytes": 2048,
        "sha256": TEST_ARTIFACT_SHA256,
        "contract": {"id": "citation-map", "version": "v1"},
        "interpretation": {"mode": "contract"},
        "authority": "runtime_cache",  # forbidden: derived navigation index, not cache
        "canonicality": "derived",
        "regenerable": True,
        "staleness_sensitive": True
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=_wrap_artifact(artifact), schema=schema)


def test_citation_map_jsonl_cannot_claim_content_source(schema):
    # Wrong canonicality value (must be derived).
    artifact = {
        "role": "citation_map_jsonl",
        "path": "out.citation_map.jsonl",
        "content_type": "application/x-ndjson",
        "bytes": 2048,
        "sha256": TEST_ARTIFACT_SHA256,
        "contract": {"id": "citation-map", "version": "v1"},
        "interpretation": {"mode": "contract"},
        "authority": "navigation_index",
        "canonicality": "content_source",  # forbidden: citation map is derived, not content source
        "regenerable": True,
        "staleness_sensitive": True
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=_wrap_artifact(artifact), schema=schema)


def test_citation_map_jsonl_cannot_claim_cache(schema):
    # Wrong canonicality value (must be derived).
    artifact = {
        "role": "citation_map_jsonl",
        "path": "out.citation_map.jsonl",
        "content_type": "application/x-ndjson",
        "bytes": 2048,
        "sha256": TEST_ARTIFACT_SHA256,
        "contract": {"id": "citation-map", "version": "v1"},
        "interpretation": {"mode": "contract"},
        "authority": "navigation_index",
        "canonicality": "cache",  # forbidden: derived navigation artifact, not a cache
        "regenerable": True,
        "staleness_sensitive": True
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=_wrap_artifact(artifact), schema=schema)


# ---------------------------------------------------------------------------
# claim_evidence_map_json: navigation_index / derived / evidence_index.
# Reference-only claim->evidence index; never canonical content.
# ---------------------------------------------------------------------------

def test_claim_evidence_map_json_valid_with_correct_contract(schema):
    artifact = {
        "role": "claim_evidence_map_json",
        "path": "out.claim_evidence_map.json",
        "content_type": "application/json",
        "bytes": 2048,
        "sha256": TEST_ARTIFACT_SHA256,
        "contract": {"id": "claim-evidence-map", "version": "v1"},
        "interpretation": {"mode": "contract"},
        "authority": "navigation_index",
        "canonicality": "derived",
        "risk_class": "evidence_index",
        "regenerable": True,
        "staleness_sensitive": True,
    }
    jsonschema.validate(instance=_wrap_artifact(artifact), schema=schema)


def test_claim_evidence_map_json_wrong_contract_id_rejected(schema):
    artifact = {
        "role": "claim_evidence_map_json",
        "path": "out.claim_evidence_map.json",
        "content_type": "application/json",
        "bytes": 2048,
        "sha256": TEST_ARTIFACT_SHA256,
        "contract": {"id": "citation-map", "version": "v1"},
        "interpretation": {"mode": "contract"},
        "authority": "navigation_index",
        "canonicality": "derived",
        "risk_class": "evidence_index",
        "regenerable": True,
        "staleness_sensitive": True,
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=_wrap_artifact(artifact), schema=schema)


def test_claim_evidence_map_json_cannot_claim_canonical_content(schema):
    artifact = {
        "role": "claim_evidence_map_json",
        "path": "out.claim_evidence_map.json",
        "content_type": "application/json",
        "bytes": 2048,
        "sha256": TEST_ARTIFACT_SHA256,
        "contract": {"id": "claim-evidence-map", "version": "v1"},
        "interpretation": {"mode": "contract"},
        "authority": "canonical_content",
        "canonicality": "derived",
        "risk_class": "evidence_index",
        "regenerable": True,
        "staleness_sensitive": True,
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=_wrap_artifact(artifact), schema=schema)
