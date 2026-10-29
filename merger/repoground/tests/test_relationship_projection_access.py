"""Consumer integrity boundaries using actual generated bundle artifacts."""
from __future__ import annotations

import copy
import hashlib
import json

import pytest

from merger.repoground.core import agent_impact_context, relationship_projection_access
from merger.repoground.core.relationship_projection_access import read_structure_neighborhood
from merger.repoground.tests.test_relationship_projection_publication import published_bundle, role_record


@pytest.fixture
def published(tmp_path):
    return published_bundle(tmp_path)


def rewrite_manifest(artifacts, manifest):
    artifacts.bundle_manifest.write_text(json.dumps(manifest), encoding="utf-8")


def rewrite_projection(artifacts, manifest, document):
    raw = json.dumps(document, sort_keys=True).encode("utf-8")
    artifacts.relationship_projection.write_bytes(raw)
    record = role_record(manifest)
    record.update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    rewrite_manifest(artifacts, manifest)


def query(artifacts):
    return read_structure_neighborhood(artifacts.bundle_manifest, target_id="file:README.md")


def test_missing_role_is_explicitly_unavailable(published):
    _, _, artifacts, manifest = published
    manifest["artifacts"] = [r for r in manifest["artifacts"] if r["role"] != "relationship_projection_json"]
    rewrite_manifest(artifacts, manifest)
    result = query(artifacts)
    assert result["status"] == "unavailable"
    assert result["error_code"].endswith("_missing")


@pytest.mark.parametrize("fault", ["duplicate", "path_escape", "missing_integrity", "missing_size",
                                  "wrong_contract", "wrong_authority", "wrong_boolean", "tampered_bytes"])
def test_registered_bad_artifact_fails_closed(published, fault):
    _, _, artifacts, manifest = published
    record = role_record(manifest)
    if fault == "duplicate":
        manifest["artifacts"].append(copy.deepcopy(record))
    elif fault == "path_escape":
        record["path"] = "../outside.json"
    elif fault == "missing_integrity":
        record.pop("bytes")
        record.pop("sha256")
    elif fault == "missing_size":
        record.pop("bytes")
    elif fault == "wrong_contract":
        record["contract"]["version"] = "v2"
    elif fault == "wrong_authority":
        record["authority"] = "canonical_content"
    elif fault == "wrong_boolean":
        record["staleness_sensitive"] = False
    else:
        artifacts.relationship_projection.write_bytes(b"{}")
    rewrite_manifest(artifacts, manifest)
    result = query(artifacts)
    assert result["status"] == "blocked"
    assert result["error_code"]


@pytest.mark.parametrize("fault", ["run", "dump", "links", "range", "duplicate_edge",
                                  "coverage", "nonclaims", "resolved_s0"])
def test_rehashed_semantic_contradictions_are_rejected(published, fault):
    _, _, artifacts, manifest = published
    document = json.loads(artifacts.relationship_projection.read_text())
    if fault == "run":
        document["run_id"] = "another-generation"
    elif fault == "dump":
        document["canonical_dump_index_sha256"] = "b" * 64
    elif fault == "links":
        manifest.setdefault("links", {})["canonical_dump_index_sha256"] = "b" * 64
    elif fault == "range":
        document["edges"][0]["source"]["range_ref"] = "file:other.py#L1-L1"
    elif fault == "duplicate_edge":
        document["edges"].append(copy.deepcopy(document["edges"][0]))
    elif fault == "coverage":
        document["coverage"]["emitted_edges"] += 1
    elif fault == "nonclaims":
        document["does_not_establish"] = []
    else:
        from merger.repoground.architecture.relationship_projection import _edge
        edge = next(edge for edge in document["edges"] if edge["resolution_status"] == "resolved")
        replacement = _edge(
            edge["relation"], edge["src"], edge["dst"], edge["source"], "resolved", "S0",
            edge["origin_artifact"],
        )
        document["edges"][document["edges"].index(edge)] = replacement
    rewrite_projection(artifacts, manifest, document)
    result = query(artifacts)
    assert result["status"] == "blocked"
    assert result["error_code"]



@pytest.mark.parametrize("fault", [
    "missing_src", "unknown_relation", "malformed_edge_id", "extra_edge_key",
    "boolean_source_line", "duplicate_nonclaims", "missing_run_id",
    "negative_coverage_count",
])
def test_rehashed_schema_faults_fail_closed_with_fast_validator(published, fault):
    _, _, artifacts, manifest = published
    document = json.loads(artifacts.relationship_projection.read_text())
    edge = document["edges"][0]
    if fault == "missing_src":
        edge.pop("src")
    elif fault == "unknown_relation":
        edge["relation"] = "nonexistent"
    elif fault == "malformed_edge_id":
        edge["id"] = "rel:bad"
    elif fault == "extra_edge_key":
        edge["unexpected"] = True
    elif fault == "boolean_source_line":
        edge["source"]["start_line"] = True
    elif fault == "duplicate_nonclaims":
        document["does_not_establish"] = ["same", "same"]
    elif fault == "missing_run_id":
        document.pop("run_id")
    else:
        document["coverage"]["total_edges"] = -1
    rewrite_projection(artifacts, manifest, document)
    result = query(artifacts)
    assert result["status"] == "blocked"
    assert result["error_code"].endswith("_invalid_schema")


def test_fast_validator_is_used_when_available(published, monkeypatch):
    if relationship_projection_access.fastjsonschema is None:
        pytest.skip("fastjsonschema is not installed in minimal developer environment")
    _, _, artifacts, _ = published

    def forbidden_legacy(*_args, **_kwargs):
        pytest.fail("legacy JSONSchema validation was unexpectedly used")

    monkeypatch.setattr(relationship_projection_access, "validate_document", forbidden_legacy)
    assert query(artifacts)["status"] == "available"


def test_missing_optional_fast_validator_keeps_existing_reader(published, monkeypatch):
    _, _, artifacts, _ = published
    monkeypatch.setattr(relationship_projection_access, "fastjsonschema", None)
    assert query(artifacts)["status"] == "available"



def test_artifact_change_during_real_compilation_fails_closed(published, monkeypatch):
    _, _, artifacts, _ = published
    original = agent_impact_context.compile_structure_neighborhood
    def change_after_calculation(**kwargs):
        result = original(**kwargs)
        with artifacts.relationship_projection.open("ab") as stream:
            stream.write(b"\n")
        return result
    monkeypatch.setattr(agent_impact_context, "compile_structure_neighborhood", change_after_calculation)
    result = query(artifacts)
    assert result["status"] == "blocked"
    assert result["error_code"].endswith("_source_changed")


@pytest.mark.parametrize("maximum", [True, 0, 201])
def test_reader_enforces_bounded_query_limit(published, maximum):
    _, _, artifacts, _ = published
    with pytest.raises(ValueError, match="max_items"):
        read_structure_neighborhood(artifacts.bundle_manifest, target_id="file:README.md", max_items=maximum)


def test_real_projection_truncation_is_visible(published):
    _, _, artifacts, _ = published
    result = read_structure_neighborhood(
        artifacts.bundle_manifest, target_id="file:pkg/core.py", max_items=1,
    )
    assert result["status"] == "available"
    assert len(result["incoming"]) <= 1
    assert len(result["outgoing"]) <= 1
    assert result["truncated"] is True
