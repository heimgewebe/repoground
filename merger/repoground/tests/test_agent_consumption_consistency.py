import json
from pathlib import Path

import pytest

jsonschema = pytest.importorskip("jsonschema")

from merger.repoground.core.agent_consumption_validate import (
    DOES_NOT_ESTABLISH,
    validate_agent_consumption,
)

_SCHEMA_PATH = (
    Path(__file__).parent.parent
    / "contracts"
    / "agent-consumption-trace.v1.schema.json"
)


def _schema() -> dict:
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


def _required(**overrides) -> dict:
    result = {
        "task_profile": "pr_review",
        "required": ["canonical_md"],
        "recommended": ["citation_map_jsonl"],
        "status": "pass",
    }
    result.update(overrides)
    return result


def _answer(**overrides) -> dict:
    result = {
        "task_profile": "pr_review",
        "declared_artifacts": ["canonical_md", "citation_map_jsonl"],
        "declared_citations": [],
        "declared_ranges": [],
        "unread_required_artifacts": [],
        "unread_recommended_artifacts": [],
        "epistemic_gaps": [],
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }
    result.update(overrides)
    return result


def _without(source: dict, field: str) -> dict:
    result = dict(source)
    result.pop(field)
    return result


def _codes(trace: dict) -> list[str]:
    return [diagnostic["code"] for diagnostic in trace["diagnostics"]]


def _assert_schema_valid(trace: dict) -> None:
    jsonschema.validate(instance=trace, schema=_schema())


def test_read_and_unread_declaration_is_fail_closed():
    trace = validate_agent_consumption(
        _required(),
        _answer(unread_required_artifacts=["canonical_md"]),
    )

    assert trace["status"] == "fail"
    assert "contradictory_artifact_declaration" in _codes(trace)
    assert "unread_required_artifact" in _codes(trace)
    assert trace["missing_required_artifacts"] == []
    _assert_schema_valid(trace)


def test_both_unread_classifications_are_contradictory():
    trace = validate_agent_consumption(
        _required(),
        _answer(
            declared_artifacts=[],
            unread_required_artifacts=["canonical_md"],
            unread_recommended_artifacts=["canonical_md"],
        ),
    )

    assert trace["status"] == "fail"
    assert "contradictory_artifact_declaration" in _codes(trace)
    assert "unexpected_unread_artifact" in _codes(trace)
    _assert_schema_valid(trace)


def test_unread_role_must_match_resolved_expectation_class():
    trace = validate_agent_consumption(
        _required(),
        _answer(
            declared_artifacts=["canonical_md"],
            unread_required_artifacts=["citation_map_jsonl"],
        ),
    )

    assert trace["status"] == "fail"
    assert "unexpected_unread_artifact" in _codes(trace)
    assert "missing_recommended_artifact" in _codes(trace)
    _assert_schema_valid(trace)


@pytest.mark.parametrize("field", ["required", "recommended"])
def test_missing_required_reading_comparison_field_is_fail_closed(field):
    trace = validate_agent_consumption(
        _without(_required(), field),
        _answer(),
    )

    assert trace["status"] == "fail"
    assert "invalid_input_field" in _codes(trace)
    _assert_schema_valid(trace)


def test_missing_declared_artifacts_is_fail_closed():
    trace = validate_agent_consumption(
        _required(),
        _without(_answer(), "declared_artifacts"),
    )

    assert trace["status"] == "fail"
    assert "invalid_input_field" in _codes(trace)
    _assert_schema_valid(trace)


def test_null_required_comparison_field_is_fail_closed():
    trace = validate_agent_consumption(
        _required(required=None),
        _answer(),
    )

    assert trace["status"] == "fail"
    assert "invalid_input_field" in _codes(trace)
    _assert_schema_valid(trace)


def test_unknown_required_reading_status_is_fail_closed():
    trace = validate_agent_consumption(
        _required(status="invented"),
        _answer(),
    )

    assert trace["status"] == "fail"
    assert "invalid_input_field" in _codes(trace)
    _assert_schema_valid(trace)


def test_invalid_profile_type_becomes_schema_valid_failure():
    trace = validate_agent_consumption(
        _required(task_profile=7),
        _answer(),
    )

    assert trace["task_profile"] == "pr_review"
    assert trace["status"] == "fail"
    assert "invalid_input_field" in _codes(trace)
    _assert_schema_valid(trace)


def test_invalid_role_container_does_not_crash_or_escape_schema():
    trace = validate_agent_consumption(
        _required(),
        _answer(declared_artifacts=42),
    )

    assert trace["declared_artifacts"] == []
    assert trace["status"] == "fail"
    assert "invalid_input_field" in _codes(trace)
    _assert_schema_valid(trace)


def test_scalar_string_role_shorthand_remains_compatible():
    trace = validate_agent_consumption(
        _required(required="canonical_md", recommended=[]),
        _answer(declared_artifacts="canonical_md"),
    )

    assert trace["required_artifacts"] == ["canonical_md"]
    assert trace["declared_artifacts"] == ["canonical_md"]
    assert trace["status"] == "pass"
    _assert_schema_valid(trace)


def test_invalid_passthrough_container_is_normalized_fail_closed():
    trace = validate_agent_consumption(
        _required(),
        _answer(declared_citations="not-an-array"),
    )

    assert trace["declared_citations"] == []
    assert trace["status"] == "fail"
    assert "invalid_input_field" in _codes(trace)
    _assert_schema_valid(trace)


def test_negative_semantics_scalar_does_not_crash():
    trace = validate_agent_consumption(
        _required(),
        _answer(does_not_establish=1),
    )

    assert trace["status"] == "fail"
    assert "missing_negative_semantics" in _codes(trace)
    _assert_schema_valid(trace)


def test_passthrough_objects_do_not_share_mutable_identity():
    citations = [{"citation_id": "c-1", "meta": {"line": 7}}]
    trace = validate_agent_consumption(
        _required(),
        _answer(declared_citations=citations),
    )

    trace["declared_citations"][0]["meta"]["line"] = 99
    assert citations[0]["meta"]["line"] == 7


def test_not_applicable_does_not_hide_self_contradiction():
    trace = validate_agent_consumption(
        _required(
            task_profile="does_not_exist",
            required=[],
            recommended=[],
            status="not_applicable",
        ),
        _answer(
            task_profile="does_not_exist",
            declared_artifacts=["canonical_md"],
            unread_required_artifacts=["canonical_md"],
        ),
    )

    assert trace["status"] == "fail"
    assert "task_profile_not_applicable" in _codes(trace)
    assert "contradictory_artifact_declaration" in _codes(trace)
    assert "unexpected_unread_artifact" not in _codes(trace)
    _assert_schema_valid(trace)
