import json
from pathlib import Path

import pytest

try:
    import jsonschema
    from jsonschema import ValidationError
except ImportError:
    jsonschema = None
    ValidationError = None

from merger.lenskit.core.agent_consumption_validate import (
    DOES_NOT_ESTABLISH,
    validate_agent_consumption,
)
from merger.lenskit.core.required_reading import (
    default_required_reading_protocol,
    resolve_required_reading,
)

_SCHEMA_PATH = (
    Path(__file__).parent.parent
    / "contracts"
    / "agent-consumption-trace.v1.schema.json"
)

_NINE = [
    "actual_reading_proven",
    "answer_correct",
    "repo_understood",
    "all_relevant_context_used",
    "claims_true",
    "test_sufficiency",
    "regression_absence",
    "runtime_behavior",
    "forensic_ready",
]


def _require_jsonschema():
    if jsonschema is None:
        pytest.skip("jsonschema not installed")


def _load_schema() -> dict:
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


# ── Fixtures ────────────────────────────────────────────────────────────────


def _required_reading_result(**overrides) -> dict:
    """A resolved Required Reading result (shape of resolve_required_reading)."""
    base = {
        "task_profile": "pr_review",
        "required": ["agent_reading_pack", "canonical_md"],
        "recommended": ["citation_map_jsonl"],
        "status": "pass",
    }
    base.update(overrides)
    return base


def _answer_compliance(**overrides) -> dict:
    base = {
        "kind": "lenskit.answer_compliance",
        "version": "1.0",
        "task_profile": "pr_review",
        "declared_artifacts": [
            "agent_reading_pack",
            "canonical_md",
            "citation_map_jsonl",
        ],
        "declared_citations": [],
        "declared_ranges": [],
        "unread_required_artifacts": [],
        "unread_recommended_artifacts": [],
        "epistemic_gaps": [],
        "does_not_establish": list(_NINE),
    }
    base.update(overrides)
    return base


def _minimal_pass_trace() -> dict:
    """Schema-level fixture: a minimal, hand-written pass trace."""
    return {
        "kind": "lenskit.agent_consumption_trace",
        "version": "1.0",
        "task_profile": "pr_review",
        "status": "pass",
        "required_artifacts": ["agent_reading_pack", "canonical_md"],
        "recommended_artifacts": [],
        "declared_artifacts": ["agent_reading_pack", "canonical_md"],
        "missing_required_artifacts": [],
        "missing_recommended_artifacts": [],
        "unknown_declared_artifacts": [],
        "unread_required_artifacts": [],
        "unread_recommended_artifacts": [],
        "declared_citations": [],
        "declared_ranges": [],
        "epistemic_gaps": [],
        "diagnostics": [],
        "does_not_establish": list(_NINE),
    }


def _codes(trace: dict) -> set[str]:
    return {d["code"] for d in trace["diagnostics"]}


def test_core_boundaries_match_test_fixture():
    assert list(DOES_NOT_ESTABLISH) == _NINE



# ── 1. Minimal pass trace is schema-valid ─────────────────────────────────────


def test_minimal_pass_trace_is_schema_valid():
    _require_jsonschema()
    jsonschema.validate(instance=_minimal_pass_trace(), schema=_load_schema())


# ── 2. kind must be lenskit.agent_consumption_trace ──────────────────────────


def test_kind_must_be_agent_consumption_trace():
    _require_jsonschema()
    instance = _minimal_pass_trace()
    instance["kind"] = "wrong_kind"
    with pytest.raises(ValidationError, match="wrong_kind"):
        jsonschema.validate(instance=instance, schema=_load_schema())


# ── 3. version must be 1.0 ───────────────────────────────────────────────────


def test_version_must_be_1_0():
    _require_jsonschema()
    instance = _minimal_pass_trace()
    instance["version"] = "2.0"
    with pytest.raises(ValidationError, match="2.0"):
        jsonschema.validate(instance=instance, schema=_load_schema())


# ── 4. status enum blocks unknown values ─────────────────────────────────────


def test_status_enum_blocks_unknown_value():
    _require_jsonschema()
    instance = _minimal_pass_trace()
    instance["status"] = "bogus"
    with pytest.raises(ValidationError):
        jsonschema.validate(instance=instance, schema=_load_schema())


# ── 5. does_not_establish with exactly nine values is valid ──────────────────


def test_does_not_establish_nine_values_valid():
    _require_jsonschema()
    instance = _minimal_pass_trace()
    assert len(instance["does_not_establish"]) == 9
    jsonschema.validate(instance=instance, schema=_load_schema())


# ── 6. does_not_establish with a missing value is invalid ────────────────────


def test_does_not_establish_missing_value_invalid():
    _require_jsonschema()
    instance = _minimal_pass_trace()
    instance["does_not_establish"] = _NINE[:-1]  # eight values
    with pytest.raises(ValidationError):
        jsonschema.validate(instance=instance, schema=_load_schema())


# ── 7. does_not_establish with a tenth value is invalid ──────────────────────


def test_does_not_establish_tenth_value_invalid():
    _require_jsonschema()
    instance = _minimal_pass_trace()
    instance["does_not_establish"] = _NINE + ["answer_safe_without_citations"]
    with pytest.raises(ValidationError):
        jsonschema.validate(instance=instance, schema=_load_schema())


# ── 8. does_not_establish with an unknown value is invalid ───────────────────


def test_does_not_establish_unknown_value_invalid():
    _require_jsonschema()
    instance = _minimal_pass_trace()
    instance["does_not_establish"] = _NINE[:-1] + ["invented_boundary"]
    with pytest.raises(ValidationError):
        jsonschema.validate(instance=instance, schema=_load_schema())


# ── 9. required artifact missing -> fail ─────────────────────────────────────


def test_missing_required_artifact_is_fail():
    rr = _required_reading_result(recommended=[])
    ac = _answer_compliance(declared_artifacts=["agent_reading_pack"])
    trace = validate_agent_consumption(rr, ac)
    assert trace["status"] == "fail"
    assert "missing_required_artifact" in _codes(trace)
    assert trace["missing_required_artifacts"] == ["canonical_md"]


# ── 10. required artifact declared unread -> fail ────────────────────────────


def test_unread_required_artifact_is_fail():
    rr = _required_reading_result(recommended=[])
    ac = _answer_compliance(
        declared_artifacts=["agent_reading_pack"],
        unread_required_artifacts=["canonical_md"],
    )
    trace = validate_agent_consumption(rr, ac)
    assert trace["status"] == "fail"
    assert "unread_required_artifact" in _codes(trace)
    # honest unread declaration is surfaced, not double-counted as missing
    assert trace["unread_required_artifacts"] == ["canonical_md"]
    assert trace["missing_required_artifacts"] == []


# ── 11. recommended artifact missing -> warn ─────────────────────────────────


def test_missing_recommended_artifact_is_warn():
    rr = _required_reading_result()
    ac = _answer_compliance(
        declared_artifacts=["agent_reading_pack", "canonical_md"],
    )
    trace = validate_agent_consumption(rr, ac)
    assert trace["status"] == "warn"
    assert "missing_recommended_artifact" in _codes(trace)
    assert trace["missing_recommended_artifacts"] == ["citation_map_jsonl"]


# ── 12. recommended artifact declared unread -> warn ─────────────────────────


def test_unread_recommended_artifact_is_warn():
    rr = _required_reading_result()
    ac = _answer_compliance(
        declared_artifacts=["agent_reading_pack", "canonical_md"],
        unread_recommended_artifacts=["citation_map_jsonl"],
    )
    trace = validate_agent_consumption(rr, ac)
    assert trace["status"] == "warn"
    assert "unread_recommended_artifact" in _codes(trace)
    assert trace["unread_recommended_artifacts"] == ["citation_map_jsonl"]


# ── 13. unknown declared artifact (available_roles=None) -> warn ─────────────


def test_unknown_declared_artifact_is_warn():
    rr = _required_reading_result(recommended=[])
    ac = _answer_compliance(
        declared_artifacts=["agent_reading_pack", "canonical_md", "mystery_role"],
    )
    trace = validate_agent_consumption(rr, ac)
    assert trace["status"] == "warn"
    assert "unknown_declared_artifact" in _codes(trace)
    assert trace["unknown_declared_artifacts"] == ["mystery_role"]


# ── 14. task_profile mismatch -> fail ────────────────────────────────────────


def test_task_profile_mismatch_is_fail():
    rr = _required_reading_result(task_profile="pr_review", recommended=[])
    ac = _answer_compliance(
        task_profile="basic_repo_question",
        declared_artifacts=["agent_reading_pack", "canonical_md"],
    )
    trace = validate_agent_consumption(rr, ac)
    assert trace["status"] == "fail"
    assert "task_profile_mismatch" in _codes(trace)


# ── 15. unknown / not_applicable profile -> not_applicable ───────────────────


def test_not_applicable_profile():
    # Real resolver naturally returns not_applicable for an unknown profile.
    protocol = default_required_reading_protocol()
    rr = resolve_required_reading(
        protocol, available_roles=set(), task_profile="does_not_exist"
    )
    ac = _answer_compliance(task_profile="does_not_exist")
    trace = validate_agent_consumption(rr, ac)
    assert trace["status"] == "not_applicable"
    assert "task_profile_not_applicable" in _codes(trace)
    # not_applicable stops further evaluation
    assert "missing_required_artifact" not in _codes(trace)
    assert "task_profile_mismatch" not in _codes(trace)


# ── 16. pass when required satisfied and no warn/fail diagnostics ─────────────


def test_pass_when_required_satisfied():
    rr = _required_reading_result(recommended=[])
    ac = _answer_compliance(
        declared_artifacts=["agent_reading_pack", "canonical_md"],
    )
    trace = validate_agent_consumption(rr, ac)
    assert trace["status"] == "pass"
    assert trace["diagnostics"] == []


# ── 17. fail beats warn ──────────────────────────────────────────────────────


def test_fail_beats_warn():
    # canonical_md missing (fail) AND citation_map_jsonl missing (warn)
    rr = _required_reading_result()
    ac = _answer_compliance(declared_artifacts=["agent_reading_pack"])
    trace = validate_agent_consumption(rr, ac)
    codes = _codes(trace)
    assert "missing_required_artifact" in codes
    assert "missing_recommended_artifact" in codes
    assert trace["status"] == "fail"


# ── 18. declared_citations are adopted ───────────────────────────────────────


def test_declared_citations_are_adopted():
    citations = [{"citation_id": "c-1", "purpose": "support a claim"}]
    rr = _required_reading_result(recommended=[])
    ac = _answer_compliance(
        declared_artifacts=["agent_reading_pack", "canonical_md"],
        declared_citations=citations,
    )
    trace = validate_agent_consumption(rr, ac)
    assert trace["declared_citations"] == citations


# ── 19. declared_ranges are adopted ──────────────────────────────────────────


def test_declared_ranges_are_adopted():
    ranges = [
        {
            "artifact": "canonical_md",
            "range_ref": {
                "file_path": "lenskit-max-example_merge.md",
                "start_line": 1,
                "end_line": 3,
            },
            "purpose": "verify cited content",
        }
    ]
    rr = _required_reading_result(recommended=[])
    ac = _answer_compliance(
        declared_artifacts=["agent_reading_pack", "canonical_md"],
        declared_ranges=ranges,
    )
    trace = validate_agent_consumption(rr, ac)
    assert trace["declared_ranges"] == ranges


# ── 20. epistemic_gaps are adopted ───────────────────────────────────────────


def test_epistemic_gaps_are_adopted():
    gaps = [{"kind": "test_not_run", "detail": "No pytest run was executed."}]
    rr = _required_reading_result(recommended=[])
    ac = _answer_compliance(
        declared_artifacts=["agent_reading_pack", "canonical_md"],
        epistemic_gaps=gaps,
    )
    trace = validate_agent_consumption(rr, ac)
    assert trace["epistemic_gaps"] == gaps


# ── 21. trace makes no truth / correctness / actual-reading claim ────────────


def test_trace_makes_no_truth_claim():
    rr = _required_reading_result(recommended=[])
    ac = _answer_compliance(
        declared_artifacts=["agent_reading_pack", "canonical_md"],
    )
    trace = validate_agent_consumption(rr, ac)
    # The nine boundaries only ever appear as declared non-establishment,
    # never as a positive top-level assertion.
    for boundary in _NINE:
        assert boundary not in trace
    assert trace["does_not_establish"] == list(DOES_NOT_ESTABLISH)
    assert set(trace["does_not_establish"]) == set(_NINE)
    # No boolean truth flags anywhere in the trace.
    assert True not in trace.values()


# ── 22. available_roles prevents false-positive unknown_declared_artifact ────


def test_available_roles_prevents_false_positive_unknown():
    rr = _required_reading_result(recommended=[])
    ac = _answer_compliance(
        declared_artifacts=["agent_reading_pack", "canonical_md", "mystery_role"],
    )
    trace = validate_agent_consumption(
        rr, ac, available_roles={"mystery_role"}
    )
    assert "unknown_declared_artifact" not in _codes(trace)
    assert trace["unknown_declared_artifacts"] == []
    assert trace["status"] == "pass"


# ── 23. available_roles=None warns conservatively on unknown declared role ───


def test_available_roles_none_warns_conservatively():
    rr = _required_reading_result(recommended=[])
    ac = _answer_compliance(
        declared_artifacts=["agent_reading_pack", "canonical_md", "mystery_role"],
    )
    trace = validate_agent_consumption(rr, ac, available_roles=None)
    assert "unknown_declared_artifact" in _codes(trace)
    assert trace["unknown_declared_artifacts"] == ["mystery_role"]


# ── Negative semantics rule ──────────────────────────────────────────────────


def test_missing_negative_semantics_is_fail():
    rr = _required_reading_result(recommended=[])
    ac = _answer_compliance(
        declared_artifacts=["agent_reading_pack", "canonical_md"],
        does_not_establish=_NINE[:-1],  # missing forensic_ready
    )
    trace = validate_agent_consumption(rr, ac)
    assert trace["status"] == "fail"
    assert "missing_negative_semantics" in _codes(trace)
    # The trace still declares its own full set of boundaries.
    assert trace["does_not_establish"] == list(DOES_NOT_ESTABLISH)


# ── Validator output is schema-valid for every status ────────────────────────


def test_validator_pass_output_is_schema_valid():
    _require_jsonschema()
    rr = _required_reading_result(recommended=[])
    ac = _answer_compliance(
        declared_artifacts=["agent_reading_pack", "canonical_md"],
    )
    trace = validate_agent_consumption(rr, ac)
    assert trace["status"] == "pass"
    jsonschema.validate(instance=trace, schema=_load_schema())


def test_validator_warn_output_is_schema_valid():
    _require_jsonschema()
    rr = _required_reading_result()
    ac = _answer_compliance(
        declared_artifacts=["agent_reading_pack", "canonical_md"],
    )
    trace = validate_agent_consumption(rr, ac)
    assert trace["status"] == "warn"
    jsonschema.validate(instance=trace, schema=_load_schema())


def test_validator_fail_output_is_schema_valid():
    _require_jsonschema()
    rr = _required_reading_result()
    ac = _answer_compliance(declared_artifacts=["agent_reading_pack"])
    trace = validate_agent_consumption(rr, ac)
    assert trace["status"] == "fail"
    jsonschema.validate(instance=trace, schema=_load_schema())


def test_validator_not_applicable_output_is_schema_valid():
    _require_jsonschema()
    protocol = default_required_reading_protocol()
    rr = resolve_required_reading(
        protocol, available_roles=set(), task_profile="does_not_exist"
    )
    ac = _answer_compliance(task_profile="does_not_exist")
    trace = validate_agent_consumption(rr, ac)
    assert trace["status"] == "not_applicable"
    jsonschema.validate(instance=trace, schema=_load_schema())


def test_invalid_negative_semantics_not_applicable_output_is_schema_valid():
    _require_jsonschema()
    protocol = default_required_reading_protocol()
    rr = resolve_required_reading(
        protocol,
        available_roles=set(),
        task_profile="does_not_exist",
    )
    ac = _answer_compliance(
        task_profile="does_not_exist",
        does_not_establish=_NINE[:-1],
    )
    trace = validate_agent_consumption(rr, ac)
    assert trace["status"] == "fail"
    assert "task_profile_not_applicable" in _codes(trace)
    assert "missing_negative_semantics" in _codes(trace)
    jsonschema.validate(instance=trace, schema=_load_schema())



# ── Reuse of the real Required Reading resolver end-to-end ───────────────────


def test_end_to_end_with_real_resolver_is_schema_valid():
    _require_jsonschema()
    protocol = default_required_reading_protocol()
    # pr_review requires agent_reading_pack, canonical_md, citation_map_jsonl,
    # post_emit_health and recommends bundle_surface_validation,
    # claim_evidence_map_json.
    rr = resolve_required_reading(
        protocol,
        available_roles={
            "agent_reading_pack",
            "canonical_md",
            "citation_map_jsonl",
            "post_emit_health",
            "bundle_surface_validation",
            "claim_evidence_map_json",
        },
        task_profile="pr_review",
    )
    ac = _answer_compliance(
        task_profile="pr_review",
        declared_artifacts=sorted(rr["required"] + rr["recommended"]),
    )
    trace = validate_agent_consumption(
        rr, ac, available_roles=set(rr["required"]) | set(rr["recommended"])
    )
    assert trace["status"] == "pass"
    jsonschema.validate(instance=trace, schema=_load_schema())


# ── Determinism ──────────────────────────────────────────────────────────────


def test_validator_is_deterministic():
    rr = _required_reading_result()
    ac = _answer_compliance(declared_artifacts=["agent_reading_pack", "zzz_role"])
    first = validate_agent_consumption(rr, ac)
    second = validate_agent_consumption(rr, ac)
    assert first == second
    # lists are deterministically sorted
    for key in (
        "required_artifacts",
        "recommended_artifacts",
        "declared_artifacts",
        "missing_required_artifacts",
        "missing_recommended_artifacts",
        "unknown_declared_artifacts",
    ):
        assert first[key] == sorted(first[key])


# ── Hardening: exact does_not_establish boundary check ───────────────────────


def test_answer_compliance_extra_negative_semantics_is_fail():
    rr = _required_reading_result(recommended=[])
    ac = _answer_compliance(
        declared_artifacts=["agent_reading_pack", "canonical_md"],
        does_not_establish=_NINE + ["answer_safe_without_citations"],
    )
    trace = validate_agent_consumption(rr, ac)
    assert trace["status"] == "fail"
    assert "missing_negative_semantics" in _codes(trace)
    # the trace still outputs its own exact nine boundaries
    assert trace["does_not_establish"] == list(DOES_NOT_ESTABLISH)


def test_answer_compliance_unknown_negative_semantics_is_fail():
    rr = _required_reading_result(recommended=[])
    ac = _answer_compliance(
        declared_artifacts=["agent_reading_pack", "canonical_md"],
        does_not_establish=_NINE[:-1] + ["invented_boundary"],
    )
    trace = validate_agent_consumption(rr, ac)
    assert trace["status"] == "fail"
    assert "missing_negative_semantics" in _codes(trace)


# ── Hardening: diagnostics[].code enum in schema ─────────────────────────────


def test_diagnostic_code_unknown_invalid():
    _require_jsonschema()
    instance = _minimal_pass_trace()
    instance["diagnostics"] = [
        {
            "code": "invented_diagnostic_code",
            "severity": "warn",
            "detail": "This code is not part of the contract.",
        }
    ]
    with pytest.raises(ValidationError):
        jsonschema.validate(instance=instance, schema=_load_schema())


def test_diagnostic_artifact_property_is_schema_valid():
    _require_jsonschema()
    instance = _minimal_pass_trace()
    instance["status"] = "fail"
    instance["diagnostics"] = [
        {
            "code": "missing_required_artifact",
            "severity": "fail",
            "detail": "Required artifact was not declared.",
            "artifact": "canonical_md",
        }
    ]
    jsonschema.validate(instance=instance, schema=_load_schema())


@pytest.mark.parametrize(
    "code,severity",
    [
        ("task_profile_mismatch", "fail"),
        ("task_profile_not_applicable", "info"),
        ("missing_required_artifact", "fail"),
        ("unread_required_artifact", "fail"),
        ("missing_recommended_artifact", "warn"),
        ("unread_recommended_artifact", "warn"),
        ("unknown_declared_artifact", "warn"),
        ("missing_negative_semantics", "fail"),
    ],
)
def test_known_diagnostic_codes_are_schema_valid(code, severity):
    _require_jsonschema()
    schema = _load_schema()
    instance = _minimal_pass_trace()
    if severity == "fail":
        instance["status"] = "fail"
    elif severity == "warn":
        instance["status"] = "warn"
    else:
        instance["status"] = "not_applicable"
    instance["diagnostics"] = [
        {"code": code, "severity": severity, "detail": "Known diagnostic code."}
    ]
    jsonschema.validate(instance=instance, schema=schema)


# ── Polish: diagnostics ordered by severity (fail > warn > info) ─────────────


def test_diagnostics_are_sorted_by_severity_then_code():
    # one fail (missing required) and one+ warn (unread recommended, unknown)
    rr = _required_reading_result(
        required=["canonical_md"],
        recommended=["citation_map_jsonl"],
    )
    ac = _answer_compliance(
        declared_artifacts=["mystery_role"],
        unread_recommended_artifacts=["citation_map_jsonl"],
    )
    trace = validate_agent_consumption(rr, ac)
    severities = [d["severity"] for d in trace["diagnostics"]]
    assert severities == sorted(
        severities,
        key={"fail": 0, "warn": 1, "info": 2}.get,
    )
    assert trace["diagnostics"][0]["severity"] == "fail"


# ── Polish: _norm_roles scalar string guard ──────────────────────────────────


def test_norm_roles_treats_scalar_string_as_single_role():
    rr = _required_reading_result(required=["canonical_md"], recommended=[])
    ac = _answer_compliance(declared_artifacts="canonical_md")
    trace = validate_agent_consumption(rr, ac)
    assert trace["declared_artifacts"] == ["canonical_md"]
    assert trace["status"] == "pass"


# ── Polish: negative semantics evaluated before not_applicable ───────────────


def test_answer_compliance_duplicate_negative_semantics_is_fail():
    rr = _required_reading_result(recommended=[])
    ac = _answer_compliance(
        declared_artifacts=["agent_reading_pack", "canonical_md"],
        does_not_establish=_NINE[:-1] + ["actual_reading_proven"],
    )
    trace = validate_agent_consumption(rr, ac)
    assert trace["status"] == "fail"
    assert "missing_negative_semantics" in _codes(trace)


def test_invalid_negative_semantics_beats_not_applicable():
    protocol = default_required_reading_protocol()
    rr = resolve_required_reading(
        protocol,
        available_roles=set(),
        task_profile="does_not_exist",
    )
    ac = _answer_compliance(
        task_profile="does_not_exist",
        does_not_establish=_NINE[:-1],
    )
    trace = validate_agent_consumption(rr, ac)
    assert trace["status"] == "fail"
    codes = _codes(trace)
    assert "task_profile_not_applicable" in codes
    assert "missing_negative_semantics" in codes


def test_valid_negative_semantics_allows_not_applicable():
    protocol = default_required_reading_protocol()
    rr = resolve_required_reading(
        protocol,
        available_roles=set(),
        task_profile="does_not_exist",
    )
    ac = _answer_compliance(task_profile="does_not_exist")
    trace = validate_agent_consumption(rr, ac)
    assert trace["status"] == "not_applicable"
    assert "task_profile_not_applicable" in _codes(trace)
    assert "missing_negative_semantics" not in _codes(trace)
