import json
from pathlib import Path

import pytest

try:
    import jsonschema
    from jsonschema import ValidationError
except ImportError:
    jsonschema = None
    ValidationError = None

_SCHEMA_PATH = (
    Path(__file__).parent.parent / "contracts" / "answer-compliance.v1.schema.json"
)

def _require_jsonschema():
    if jsonschema is None:
        pytest.skip("jsonschema not installed")

def _load_schema() -> dict:
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))

def _minimal_valid_answer_compliance() -> dict:
    return {
        "kind": "lenskit.answer_compliance",
        "version": "1.0",
        "task_profile": "pr_review",
        "declared_artifacts": [
            "agent_reading_pack",
            "canonical_md",
            "citation_map_jsonl"
        ],
        "declared_citations": [
            {
                "citation_id": "c-example",
                "purpose": "support a specific claim"
            }
        ],
        "declared_ranges": [
            {
                "artifact": "canonical_md",
                "range_ref": {
                    "file_path": "lenskit-max-example_merge.md",
                    "start_line": 1,
                    "end_line": 3
                },
                "purpose": "verify cited canonical content"
            }
        ],
        "unread_required_artifacts": [],
        "unread_recommended_artifacts": [
            "bundle_surface_validation"
        ],
        "epistemic_gaps": [
            {
                "kind": "test_not_run",
                "detail": "No local pytest run was executed for this answer."
            }
        ],
        "does_not_establish": [
            "actual_reading_proven",
            "answer_correct",
            "repo_understood",
            "all_relevant_context_used",
            "claims_true",
            "test_sufficiency",
            "regression_absence",
            "runtime_behavior",
            "forensic_ready"
        ]
    }

def test_minimal_valid_instance():
    _require_jsonschema()
    schema = _load_schema()
    instance = _minimal_valid_answer_compliance()
    jsonschema.validate(instance=instance, schema=schema)

def test_kind_must_be_lenskit_answer_compliance():
    _require_jsonschema()
    schema = _load_schema()
    instance = _minimal_valid_answer_compliance()
    instance["kind"] = "wrong_kind"
    with pytest.raises(ValidationError, match="wrong_kind"):
        jsonschema.validate(instance=instance, schema=schema)

def test_version_must_be_1_0():
    _require_jsonschema()
    schema = _load_schema()
    instance = _minimal_valid_answer_compliance()
    instance["version"] = "2.0"
    with pytest.raises(ValidationError, match="2.0"):
        jsonschema.validate(instance=instance, schema=schema)

def test_missing_required_field_invalid():
    _require_jsonschema()
    schema = _load_schema()
    instance = _minimal_valid_answer_compliance()
    del instance["task_profile"]
    with pytest.raises(ValidationError, match="task_profile"):
        jsonschema.validate(instance=instance, schema=schema)

def test_additional_properties_invalid():
    _require_jsonschema()
    schema = _load_schema()
    instance = _minimal_valid_answer_compliance()
    instance["extra_field"] = "value"
    with pytest.raises(ValidationError, match="extra_field"):
        jsonschema.validate(instance=instance, schema=schema)

def test_does_not_establish_empty_invalid():
    _require_jsonschema()
    schema = _load_schema()
    instance = _minimal_valid_answer_compliance()
    instance["does_not_establish"] = []
    with pytest.raises(ValidationError):
        jsonschema.validate(instance=instance, schema=schema)

def test_does_not_establish_missing_required_invalid():
    _require_jsonschema()
    schema = _load_schema()
    instance = _minimal_valid_answer_compliance()
    instance["does_not_establish"] = [
        "actual_reading_proven",
        "answer_correct",
        "repo_understood",
        "all_relevant_context_used",
        "claims_true",
        "test_sufficiency",
        "regression_absence",
        "runtime_behavior"
        # missing forensic_ready
    ]
    with pytest.raises(ValidationError):
        jsonschema.validate(instance=instance, schema=schema)

def test_does_not_establish_with_duplicates_invalid():
    _require_jsonschema()
    schema = _load_schema()
    instance = _minimal_valid_answer_compliance()
    instance["does_not_establish"].append("actual_reading_proven")
    with pytest.raises(ValidationError):
        jsonschema.validate(instance=instance, schema=schema)

def test_arrays_must_have_unique_items():
    _require_jsonschema()
    schema = _load_schema()
    instance = _minimal_valid_answer_compliance()
    
    # test declared_artifacts
    instance["declared_artifacts"] = ["doc1", "doc1"]
    with pytest.raises(ValidationError):
        jsonschema.validate(instance=instance, schema=schema)
    instance["declared_artifacts"] = []

    # test unread_required_artifacts
    instance["unread_required_artifacts"] = ["doc1", "doc1"]
    with pytest.raises(ValidationError):
        jsonschema.validate(instance=instance, schema=schema)
    instance["unread_required_artifacts"] = []

    # test unread_recommended_artifacts
    instance["unread_recommended_artifacts"] = ["doc1", "doc1"]
    with pytest.raises(ValidationError):
        jsonschema.validate(instance=instance, schema=schema)

def test_epistemic_gap_invalid_kind():
    _require_jsonschema()
    schema = _load_schema()
    instance = _minimal_valid_answer_compliance()
    instance["epistemic_gaps"][0]["kind"] = "not_a_real_gap"
    with pytest.raises(ValidationError):
        jsonschema.validate(instance=instance, schema=schema)

def test_epistemic_gap_missing_detail():
    _require_jsonschema()
    schema = _load_schema()
    instance = _minimal_valid_answer_compliance()
    del instance["epistemic_gaps"][0]["detail"]
    with pytest.raises(ValidationError):
        jsonschema.validate(instance=instance, schema=schema)

def test_citation_declaration_missing_id():
    _require_jsonschema()
    schema = _load_schema()
    instance = _minimal_valid_answer_compliance()
    del instance["declared_citations"][0]["citation_id"]
    with pytest.raises(ValidationError):
        jsonschema.validate(instance=instance, schema=schema)

def test_range_declaration_missing_artifact():
    _require_jsonschema()
    schema = _load_schema()
    instance = _minimal_valid_answer_compliance()
    del instance["declared_ranges"][0]["artifact"]
    with pytest.raises(ValidationError):
        jsonschema.validate(instance=instance, schema=schema)

def test_range_declaration_missing_range_ref():
    _require_jsonschema()
    schema = _load_schema()
    instance = _minimal_valid_answer_compliance()
    del instance["declared_ranges"][0]["range_ref"]
    with pytest.raises(ValidationError):
        jsonschema.validate(instance=instance, schema=schema)

def test_schema_has_no_status_field():
    schema = _load_schema()
    assert "status" not in schema["properties"]
    assert "pass" not in schema["properties"]
    assert "warn" not in schema["properties"]
    assert "fail" not in schema["properties"]

def test_top_level_fields_are_declared():
    schema = _load_schema()
    # verify used_* fields are not required and declared_* are required
    required = schema["required"]
    assert "declared_artifacts" in required
    assert "declared_citations" in required
    assert "declared_ranges" in required
    assert not any(f.startswith("used_") for f in required)
    assert not any(f.startswith("used_") for f in schema["properties"])
