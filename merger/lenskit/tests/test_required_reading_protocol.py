import json
import pytest
from pathlib import Path

try:
    import jsonschema
    from jsonschema import ValidationError
except ImportError:
    jsonschema = None
    ValidationError = None

from merger.lenskit.core.required_reading import (
    default_required_reading_protocol,
    resolve_required_reading,
)

_SCHEMA_PATH = (
    Path(__file__).parent.parent / "contracts" / "required-reading-protocol.v1.schema.json"
)
_EXPECTED_PROFILES = {
    "basic_repo_question",
    "pr_review",
    "roadmap_status_claim",
    "artifact_surface_review",
    "retrieval_quality_review",
    "security_export_review",
}
_EXPECTED_PROFILE_KEYS = {
    "required",
    "recommended",
    "insufficient",
    "citation_required",
    "answer_checklist_required",
    "does_not_establish",
}


def _require_jsonschema():
    if jsonschema is None:
        pytest.skip("jsonschema not installed")


def _load_schema() -> dict:
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


# ── 1. default_required_reading_protocol() is schema-valid ──────────────────

def test_default_protocol_is_schema_valid():
    _require_jsonschema()
    schema = _load_schema()
    protocol = default_required_reading_protocol()
    jsonschema.validate(instance=protocol, schema=schema)


# ── 2. All expected profiles present ────────────────────────────────────────

def test_all_agent_pack_profiles_present():
    protocol = default_required_reading_protocol()
    assert set(protocol["task_profiles"].keys()) == _EXPECTED_PROFILES


# ── 3. Each profile has the required keys ───────────────────────────────────

def test_each_profile_has_required_keys():
    protocol = default_required_reading_protocol()
    for name, profile in protocol["task_profiles"].items():
        missing = _EXPECTED_PROFILE_KEYS - set(profile.keys())
        assert not missing, f"Profile '{name}' missing keys: {missing}"


# ── 4. basic_repo_question: all roles present → pass ────────────────────────

def test_basic_repo_question_all_present_is_pass():
    protocol = default_required_reading_protocol()
    result = resolve_required_reading(
        protocol,
        available_roles={"agent_reading_pack", "canonical_md", "citation_map_jsonl"},
        task_profile="basic_repo_question",
    )
    assert result["status"] == "pass"
    assert result["missing_required"] == []
    assert result["missing_recommended"] == []


# ── 5. basic_repo_question: required present, recommended missing → warn ────

def test_basic_repo_question_missing_recommended_is_warn():
    protocol = default_required_reading_protocol()
    result = resolve_required_reading(
        protocol,
        available_roles={"agent_reading_pack", "canonical_md"},
        task_profile="basic_repo_question",
    )
    assert result["status"] == "warn"
    assert result["missing_required"] == []
    assert "citation_map_jsonl" in result["missing_recommended"]


# ── 6. pr_review: required role missing → fail ──────────────────────────────

def test_pr_review_missing_required_is_fail():
    protocol = default_required_reading_protocol()
    # citation_map_jsonl is required for pr_review
    result = resolve_required_reading(
        protocol,
        available_roles={"agent_reading_pack", "canonical_md", "post_emit_health"},
        task_profile="pr_review",
    )
    assert result["status"] == "fail"
    assert "citation_map_jsonl" in result["missing_required"]


# ── 7. pr_review: all required present, recommended missing → warn ───────────

def test_pr_review_all_required_missing_recommended_is_warn():
    protocol = default_required_reading_protocol()
    result = resolve_required_reading(
        protocol,
        available_roles={
            "agent_reading_pack",
            "canonical_md",
            "citation_map_jsonl",
            "post_emit_health",
        },
        task_profile="pr_review",
    )
    assert result["status"] == "warn"
    assert result["missing_required"] == []
    assert len(result["missing_recommended"]) > 0


# ── 8. Unknown task_profile → not_applicable ────────────────────────────────

def test_unknown_task_profile_is_not_applicable():
    protocol = default_required_reading_protocol()
    result = resolve_required_reading(
        protocol,
        available_roles={"canonical_md"},
        task_profile="nonexistent_profile",
    )
    assert result["status"] == "not_applicable"
    assert result["required"] == []
    assert result["recommended"] == []


# ── 9. Output lists are deterministically sorted ────────────────────────────

def test_output_lists_are_sorted():
    protocol = default_required_reading_protocol()
    result = resolve_required_reading(
        protocol,
        available_roles={"canonical_md", "agent_reading_pack"},
        task_profile="pr_review",
    )
    for key in ("required", "recommended", "insufficient",
                "available_required", "missing_required",
                "available_recommended", "missing_recommended"):
        lst = result[key]
        assert lst == sorted(lst), f"List '{key}' is not sorted: {lst}"


# ── 10. does_not_establish missing from task_profile → schema invalid ────────

def test_schema_invalid_when_does_not_establish_missing():
    _require_jsonschema()
    schema = _load_schema()
    protocol = default_required_reading_protocol()
    # Remove does_not_establish from one profile
    del protocol["task_profiles"]["basic_repo_question"]["does_not_establish"]
    with pytest.raises(ValidationError):
        jsonschema.validate(instance=protocol, schema=schema)


# ── 11. Extra field in task_profile → schema invalid (additionalProperties:false) ──

def test_schema_invalid_when_extra_field_in_profile():
    _require_jsonschema()
    schema = _load_schema()
    protocol = default_required_reading_protocol()
    protocol["task_profiles"]["basic_repo_question"]["unexpected_field"] = "should_fail"
    with pytest.raises(ValidationError):
        jsonschema.validate(instance=protocol, schema=schema)


# ── 12. Metadata Preservation and Neutral Defaults ─────────────────────────

def test_resolver_preserves_profile_metadata():
    protocol = default_required_reading_protocol()
    result = resolve_required_reading(
        protocol,
        available_roles={"agent_reading_pack", "canonical_md", "citation_map_jsonl"},
        task_profile="basic_repo_question",
    )
    profile = protocol["task_profiles"]["basic_repo_question"]

    assert result["citation_required"] == profile["citation_required"]
    assert result["answer_checklist_required"] == profile["answer_checklist_required"]
    assert result["does_not_establish"] == sorted(profile["does_not_establish"])


def test_unknown_task_profile_returns_neutral_metadata():
    protocol = default_required_reading_protocol()
    result = resolve_required_reading(
        protocol,
        available_roles={"canonical_md"},
        task_profile="unknown",
    )
    assert result["status"] == "not_applicable"
    assert result["citation_required"] is False
    assert result["answer_checklist_required"] is False
    assert result["does_not_establish"] == []


# ── 13. Mutation Protection ──────────────────────────────────────────────────

def test_default_protocol_returns_fresh_lists():
    first = default_required_reading_protocol()
    first["task_profiles"]["basic_repo_question"]["required"].append("mutated")
    second = default_required_reading_protocol()
    assert "mutated" not in second["task_profiles"]["basic_repo_question"]["required"]


# ── 14. Schema Negative Tests for does_not_establish ─────────────────────────

def test_schema_invalid_when_protocol_does_not_establish_empty():
    _require_jsonschema()
    schema = _load_schema()
    protocol = default_required_reading_protocol()
    protocol["does_not_establish"] = []
    with pytest.raises(ValidationError):
        jsonschema.validate(instance=protocol, schema=schema)


def test_schema_invalid_when_profile_does_not_establish_empty():
    _require_jsonschema()
    schema = _load_schema()
    protocol = default_required_reading_protocol()
    protocol["task_profiles"]["basic_repo_question"]["does_not_establish"] = []
    with pytest.raises(ValidationError):
        jsonschema.validate(instance=protocol, schema=schema)


def test_schema_invalid_when_does_not_establish_missing_required_invariant():
    _require_jsonschema()
    schema = _load_schema()
    
    # Missing 'repo_understood'
    protocol = default_required_reading_protocol()
    protocol["does_not_establish"] = [
        "answer_safe_without_citations",
        "claims_true",
        "all_relevant_context_used",
        "forensic_ready",
    ]
    with pytest.raises(ValidationError):
        jsonschema.validate(instance=protocol, schema=schema)

    # Profile missing 'claims_true'
    protocol2 = default_required_reading_protocol()
    protocol2["task_profiles"]["basic_repo_question"]["does_not_establish"] = [
        "repo_understood",
        "answer_safe_without_citations",
        "all_relevant_context_used",
        "forensic_ready",
    ]
    with pytest.raises(ValidationError):
        jsonschema.validate(instance=protocol2, schema=schema)


def test_schema_invalid_when_does_not_establish_has_duplicates():
    _require_jsonschema()
    schema = _load_schema()
    protocol = default_required_reading_protocol()
    protocol["does_not_establish"] = [
        "repo_understood",
        "answer_safe_without_citations",
        "claims_true",
        "all_relevant_context_used",
        "forensic_ready",
        "forensic_ready",  # Duplicate
    ]
    with pytest.raises(ValidationError):
        jsonschema.validate(instance=protocol, schema=schema)


# ── 15. basic_repo_question.citation_required default ───────────────────────

def test_basic_repo_question_does_not_require_citation_by_default():
    protocol = default_required_reading_protocol()
    assert protocol["task_profiles"]["basic_repo_question"]["citation_required"] is False


def test_security_export_review_profile_requires_export_safety():
    protocol = default_required_reading_protocol()
    result = resolve_required_reading(
        protocol,
        {"agent_reading_pack", "canonical_md", "post_emit_health"},
        "security_export_review",
    )
    assert result["status"] == "fail"
    assert "export_safety_report" in result["missing_required"]
    assert "treating export_safety_report as secret absence" in result["insufficient"]
