import copy
import json
from pathlib import Path

import jsonschema
import pytest

import merger.repoground.core as core_api
from merger.repoground.core.system_relation_overlay import (
    SystemRelationOverlayError,
    normalize_system_relation_evidence,
)

EVIDENCE_SHA = "a" * 64
REPOSITORY_COMMIT = "b" * 40


def _range(start_line: int, end_line: int | None = None) -> dict[str, int]:
    return {
        "start_line": start_line,
        "start_character": 0,
        "end_line": start_line if end_line is None else end_line,
        "end_character": 80,
    }


def _record(
    relation: str,
    subject_kind: str,
    subject_identity: str,
    target_kind: str,
    target_identity: str,
    path: str,
    source_kind: str,
    start_line: int,
    evidence_class: str,
    contract_identity=None,
):
    return {
        "relation": relation,
        "subject": {"kind": subject_kind, "identity": subject_identity},
        "target": {"kind": target_kind, "identity": target_identity},
        "source": {
            "path": path,
            "kind": source_kind,
            "range": _range(start_line),
        },
        "evidence_class": evidence_class,
        "contract_identity": contract_identity,
    }


def _evidence() -> dict:
    return {
        "kind": "repoground.system_relation_evidence",
        "version": "1.0",
        "producer": {"name": "fixture-collector", "version": "1.2.3"},
        "records": [
            _record(
                "build_target",
                "repository",
                "heimgewebe/repoground",
                "build_target",
                "python-wheel",
                "pyproject.toml",
                "manifest",
                10,
                "manifest_declaration",
            ),
            _record(
                "package_target",
                "package",
                "repoground",
                "package_target",
                "release-wheel",
                ".github/workflows/release.yml",
                "workflow",
                30,
                "workflow_declaration",
            ),
            _record(
                "test_registration",
                "test",
                "tests/test_cli.py::test_run",
                "test_target",
                "merger.repoground.cli.main",
                "pytest.ini",
                "test_registry",
                2,
                "explicit_test_registration",
            ),
            _record(
                "test_registration",
                "test",
                "tests/test_cli.py::test_dispatch",
                "test_target",
                "merger.repoground.cli.main",
                "merger/repoground/tests/test_cli.py",
                "source_file",
                14,
                "test_import_or_reference",
            ),
            _record(
                "test_registration",
                "test",
                "tests/test_guess.py::test_name_only",
                "test_target",
                "merger.repoground.core.guessed",
                "merger/repoground/tests/test_guess.py",
                "source_file",
                7,
                "test_naming_heuristic",
            ),
            _record(
                "validates_schema",
                "validator",
                "merger.repoground.core.relation_card_validate.validate_relation_card",
                "schema_contract",
                "relation-card.v1",
                "merger/repoground/core/relation_card_validate.py",
                "source_file",
                42,
                "schema_validation_call",
                {
                    "kind": "schema",
                    "id": "https://repoground.merger/schemas/relation-card.v1.json",
                    "version": "1.0",
                },
            ),
            _record(
                "produces_artifact",
                "artifact_producer",
                "merger.repoground.core.bundle_sidecars.write_relation_cards_jsonl",
                "artifact_contract",
                "relation_cards_jsonl",
                "merger/repoground/core/bundle_sidecars.py",
                "source_file",
                150,
                "artifact_declaration",
                {
                    "kind": "artifact",
                    "id": "relation_cards_jsonl",
                    "version": "1.0",
                },
            ),
            _record(
                "consumes_artifact",
                "artifact_consumer",
                "merger.repoground.core.relation_card_validate.validate_relation_cards",
                "artifact_contract",
                "relation_cards_jsonl",
                "merger/repoground/core/relation_card_validate.py",
                "source_file",
                80,
                "artifact_declaration",
                {
                    "kind": "artifact",
                    "id": "relation_cards_jsonl",
                    "version": "1.0",
                },
            ),
        ],
    }


def _artifact(evidence=None):
    return normalize_system_relation_evidence(
        _evidence() if evidence is None else evidence,
        evidence_sha256=EVIDENCE_SHA,
        repository_commit=REPOSITORY_COMMIT,
    )


def _schema() -> dict:
    path = (
        Path(__file__).parent.parent
        / "contracts"
        / "system-relation-overlay.v1.schema.json"
    )
    return json.loads(path.read_text(encoding="utf-8"))


def test_projects_all_relation_families_with_fixed_navigation_boundary():
    artifact = _artifact()

    assert artifact["status"] == "available"
    assert artifact["authority"] == "navigation_index"
    assert artifact["canonicality"] == "derived"
    assert artifact["risk_class"] == "navigation"
    assert artifact["record_count"] == 8
    assert artifact["relation_kinds"] == [
        "build_target",
        "consumes_artifact",
        "package_target",
        "produces_artifact",
        "test_registration",
        "validates_schema",
    ]
    assert artifact["source"] == {
        "format": "repoground_system_relation_evidence_v1",
        "evidence_sha256": EVIDENCE_SHA,
        "repository_commit": REPOSITORY_COMMIT,
        "producer": {"name": "fixture-collector", "version": "1.2.3"},
    }
    assert artifact["consumer_enablement"] == {
        "eligible_for_review": False,
        "default_promoted": False,
    }
    assert "runtime_correctness" in artifact["does_not_establish"]
    assert "build_success" in artifact["does_not_establish"]
    assert "test_sufficiency" in artifact["does_not_establish"]
    assert "schema_conformance" in artifact["does_not_establish"]
    assert "artifact_materialization" in artifact["does_not_establish"]
    assert "not evidence that the relation is absent" in artifact["absence_semantics"]


def test_build_and_package_relations_keep_manifest_or_workflow_ranges():
    records = {
        record["relation"]: record
        for record in _artifact()["records"]
        if record["relation"] in {"build_target", "package_target"}
    }

    assert records["build_target"]["source"] == {
        "path": "pyproject.toml",
        "kind": "manifest",
        "range": _range(10),
    }
    assert records["package_target"]["source"] == {
        "path": ".github/workflows/release.yml",
        "kind": "workflow",
        "range": _range(30),
    }


def test_test_registration_distinguishes_declared_reference_and_heuristic_evidence():
    profiles = {
        record["evidence"]["class"]: (
            record["evidence"]["level"],
            record["evidence"]["strength"],
        )
        for record in _artifact()["records"]
        if record["relation"] == "test_registration"
    }

    assert profiles == {
        "explicit_test_registration": ("S1", "declared"),
        "test_import_or_reference": ("S0", "referenced"),
        "test_naming_heuristic": ("S0", "heuristic"),
    }


def test_schema_and_artifact_relations_preserve_contract_identity():
    records = _artifact()["records"]
    schema_record = next(
        record for record in records if record["relation"] == "validates_schema"
    )
    artifact_records = [
        record
        for record in records
        if record["relation"] in {"produces_artifact", "consumes_artifact"}
    ]

    assert schema_record["contract_identity"] == {
        "kind": "schema",
        "id": "https://repoground.merger/schemas/relation-card.v1.json",
        "version": "1.0",
    }
    assert all(
        record["contract_identity"]
        == {"kind": "artifact", "id": "relation_cards_jsonl", "version": "1.0"}
        for record in artifact_records
    )


def test_output_and_record_ids_are_deterministic_under_input_reordering():
    first = _evidence()
    second = copy.deepcopy(first)
    second["records"].reverse()

    assert _artifact(first) == _artifact(second)
    assert all(
        len(record["record_id_sha256"]) == 64
        for record in _artifact(first)["records"]
    )


def test_exact_duplicates_are_deduplicated_and_reported():
    evidence = _evidence()
    evidence["records"].append(copy.deepcopy(evidence["records"][0]))

    artifact = _artifact(evidence)

    assert artifact["status"] == "degraded"
    assert artifact["record_count"] == 8
    assert artifact["degradations"] == [
        {
            "code": "duplicate_records_deduplicated",
            "message": "Exact duplicate relation records were removed deterministically.",
            "count": 1,
        }
    ]


def test_empty_evidence_is_explicitly_degraded_not_silent_success():
    evidence = _evidence()
    evidence["records"] = []

    artifact = _artifact(evidence)

    assert artifact["status"] == "degraded"
    assert artifact["record_count"] == 0
    assert artifact["relation_kinds"] == []
    assert artifact["evidence_classes"] == []
    assert artifact["degradations"][0]["code"] == "records_empty"


@pytest.mark.parametrize("path", ["../escape.toml", "/absolute.toml", "a//b.toml"])
def test_unsafe_repository_paths_fail_closed(path):
    evidence = _evidence()
    evidence["records"][0]["source"]["path"] = path

    with pytest.raises(SystemRelationOverlayError, match="safe repository-relative path"):
        _artifact(evidence)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("start_line", 0),
        ("start_character", -1),
        ("end_line", True),
        ("end_character", -1),
    ],
)
def test_invalid_ranges_fail_closed(field, value):
    evidence = _evidence()
    evidence["records"][0]["source"]["range"][field] = value

    with pytest.raises(SystemRelationOverlayError, match="must be an integer"):
        _artifact(evidence)


def test_reversed_range_fails_closed():
    evidence = _evidence()
    evidence["records"][0]["source"]["range"] = {
        "start_line": 4,
        "start_character": 0,
        "end_line": 3,
        "end_character": 80,
    }

    with pytest.raises(SystemRelationOverlayError, match="end precedes"):
        _artifact(evidence)


@pytest.mark.parametrize(
    ("relation", "evidence_class"),
    [
        ("build_target", "test_naming_heuristic"),
        ("test_registration", "manifest_declaration"),
        ("validates_schema", "artifact_declaration"),
        ("produces_artifact", "schema_validation_call"),
    ],
)
def test_relation_and_evidence_class_mismatches_fail_closed(relation, evidence_class):
    evidence = _evidence()
    evidence["records"][0]["relation"] = relation
    evidence["records"][0]["evidence_class"] = evidence_class

    with pytest.raises(SystemRelationOverlayError, match="incompatible with relation"):
        _artifact(evidence)


def test_evidence_class_and_source_kind_mismatch_fails_closed():
    evidence = _evidence()
    evidence["records"][0]["source"]["kind"] = "workflow"

    with pytest.raises(SystemRelationOverlayError, match="incompatible with evidence_class"):
        _artifact(evidence)


def test_schema_and_artifact_relations_require_matching_contract_kinds():
    evidence = _evidence()
    schema_record = next(
        record for record in evidence["records"] if record["relation"] == "validates_schema"
    )
    schema_record["contract_identity"]["kind"] = "artifact"

    with pytest.raises(SystemRelationOverlayError, match="must be 'schema'"):
        _artifact(evidence)


def test_build_test_and_package_relations_reject_contract_identity():
    evidence = _evidence()
    evidence["records"][0]["contract_identity"] = {
        "kind": "artifact",
        "id": "unexpected",
        "version": "1.0",
    }

    with pytest.raises(SystemRelationOverlayError, match="must be null"):
        _artifact(evidence)


@pytest.mark.parametrize(
    ("evidence_sha256", "repository_commit", "match"),
    [
        ("bad", REPOSITORY_COMMIT, "evidence_sha256"),
        (EVIDENCE_SHA, "bad", "repository_commit"),
    ],
)
def test_invalid_provenance_digests_fail_closed(
    evidence_sha256, repository_commit, match
):
    with pytest.raises(SystemRelationOverlayError, match=match):
        normalize_system_relation_evidence(
            _evidence(),
            evidence_sha256=evidence_sha256,
            repository_commit=repository_commit,
        )


def test_input_shapes_are_strict_and_reject_unbound_metadata():
    evidence = _evidence()
    evidence["records"][0]["confidence"] = 1.0

    with pytest.raises(SystemRelationOverlayError, match="fields must be exactly"):
        _artifact(evidence)


def test_artifact_matches_contract_and_contract_rejects_semantic_upgrades():
    artifact = _artifact()
    schema = _schema()

    jsonschema.Draft7Validator.check_schema(schema)
    jsonschema.validate(instance=artifact, schema=schema)

    upgraded = copy.deepcopy(artifact)
    heuristic = next(
        record
        for record in upgraded["records"]
        if record["evidence"]["class"] == "test_naming_heuristic"
    )
    heuristic["evidence"]["level"] = "S1"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=upgraded, schema=schema)

    wrong_contract = copy.deepcopy(artifact)
    schema_record = next(
        record
        for record in wrong_contract["records"]
        if record["relation"] == "validates_schema"
    )
    schema_record["contract_identity"]["kind"] = "artifact"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=wrong_contract, schema=schema)


def test_public_core_api_exports_overlay_without_promoting_it():
    assert core_api.SystemRelationOverlayError is SystemRelationOverlayError
    assert (
        core_api.normalize_system_relation_evidence
        is normalize_system_relation_evidence
    )
    assert "normalize_system_relation_evidence" in core_api.__all__
    assert core_api.__core_version__ == "2.4.0"
