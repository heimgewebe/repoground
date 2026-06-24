"""Tests for the C2.4 anti-hallucination contract lint.

Covers the two contract-static rules (L3 boundary presence, L5 truth-language)
with synthetic schemas, and asserts the lint is green on the real contract set
with an empty deferral registry. The former sole deferral
(retrieval-eval-diagnostics.v1) was resolved by the C2.6 boundary-normalizing
follow-up that gave the contract a required root does_not_prove boundary; the
deferral *mechanism* itself is still exercised here via a synthetic registry
entry.
"""
import json
from pathlib import Path
import pytest

from merger.lenskit.core.anti_hallucination_lint import (
    DEFERRED_BOUNDARY_CONTRACTS,
    ENFORCED_RULES,
    OUT_OF_SCOPE_RULES,
    audit_deferral_registry,
    lint_contract_schema,
    lint_contracts,
    lint_contracts_dir,
    load_contract_schemas,
)

_CONTRACTS_DIR = Path(__file__).parent.parent / "contracts"


# --- helpers ---------------------------------------------------------------


def _diag_schema(extra_props: dict | None = None) -> dict:
    """A minimal diagnostic_signal contract with a boundary array."""
    props = {
        "authority": {"type": "string", "const": "diagnostic_signal"},
        "does_not_mean": {"type": "array", "items": {"type": "string"}},
    }
    if extra_props:
        props.update(extra_props)
    return {"type": "object", "properties": props}


# --- L5: Unsupported Truth Language ----------------------------------------


def test_l5_flags_forbidden_property_name():
    schema = _diag_schema({"understanding_score": {"type": "number"}})
    findings = lint_contract_schema(schema, contract_name="x.schema.json")
    l5 = [f for f in findings if f.rule == "L5"]
    assert len(l5) == 1
    assert l5[0].severity == "error"
    assert l5[0].location == "properties.understanding_score"


def test_l5_flags_forbidden_nested_property_name():
    schema = _diag_schema(
        {
            "block": {
                "type": "object",
                "properties": {"agent_safe": {"type": "boolean"}},
            }
        }
    )
    findings = lint_contract_schema(schema, contract_name="x.schema.json")
    assert any(f.rule == "L5" and f.location == "properties.agent_safe" for f in findings)


def test_l5_flags_forbidden_verdict_enum_value():
    schema = _diag_schema(
        {"verdict": {"type": "string", "enum": ["pass", "proven"]}}
    )
    findings = lint_contract_schema(schema, contract_name="x.schema.json")
    l5 = [f for f in findings if f.rule == "L5"]
    assert len(l5) == 1
    assert "proven" in l5[0].message


def test_l5_flags_forbidden_verdict_enum_value_in_items():
    schema = _diag_schema(
        {"status": {"type": "array", "items": {"enum": ["ok", "verified"]}}}
    )
    findings = lint_contract_schema(schema, contract_name="x.schema.json")
    assert any(f.rule == "L5" and "verified" in f.message for f in findings)


def test_l5_clean_status_enum_is_not_flagged():
    schema = _diag_schema(
        {"status": {"type": "string", "enum": ["pass", "warn", "fail", "blocked"]}}
    )
    findings = lint_contract_schema(schema, contract_name="x.schema.json")
    assert [f for f in findings if f.rule == "L5"] == []


def test_l5_does_not_flag_complete_or_true_status_values():
    # 'complete'/'true'/'false' are legitimate status/enum tokens — only forbidden
    # as verdict values are checked, and these are not in that set.
    schema = _diag_schema(
        {"projection_status": {"type": "string", "enum": ["complete", "degraded", "blocked"]}}
    )
    findings = lint_contract_schema(schema, contract_name="x.schema.json")
    assert [f for f in findings if f.rule == "L5"] == []


def test_l5_does_not_scan_disclaimer_array_values():
    # does_not_mean legitimately *names* forbidden inferences as negatives; its
    # string values must never be treated as forbidden property names/values.
    schema = {
        "type": "object",
        "properties": {
            "authority": {"type": "string", "const": "diagnostic_signal"},
            "does_not_mean": {
                "type": "array",
                "items": {"type": "string"},
                "allOf": [
                    {"contains": {"const": "answer_safe_without_citations"}},
                    {"contains": {"const": "claims_true"}},
                    {"contains": {"const": "retrieval_complete"}},
                ],
            },
            "forbidden_inferences": {"type": "array", "items": {"type": "string"}},
        },
    }
    findings = lint_contract_schema(schema, contract_name="x.schema.json")
    assert [f for f in findings if f.rule == "L5"] == []


def test_l5_flags_forbidden_verdict_const_value():
    schema = _diag_schema(
        {"status": {"type": "string", "const": "proven"}}
    )
    findings = lint_contract_schema(schema, contract_name="x.schema.json")
    assert any(f.rule == "L5" and "proven" in f.message for f in findings)


def test_l5_flags_forbidden_verdict_const_value_in_items():
    schema = _diag_schema(
        {"status": {"type": "array", "items": {"const": "verified"}}}
    )
    findings = lint_contract_schema(schema, contract_name="x.schema.json")
    assert any(f.rule == "L5" and "verified" in f.message for f in findings)


# --- L3: Missing Inference Boundary ----------------------------------------


def test_l3_flags_diagnostic_signal_without_boundary():
    schema = {
        "type": "object",
        "properties": {"authority": {"type": "string", "const": "diagnostic_signal"}},
    }
    findings = lint_contract_schema(schema, contract_name="novel.schema.json")
    l3 = [f for f in findings if f.rule == "L3"]
    assert len(l3) == 1
    assert l3[0].severity == "error"
    assert l3[0].location == "root.authority"


def test_l3_flags_runtime_observation_without_boundary():
    schema = {
        "type": "object",
        "properties": {"authority": {"type": "string", "const": "runtime_observation"}},
    }
    findings = lint_contract_schema(schema, contract_name="novel.schema.json")
    assert any(f.rule == "L3" and f.severity == "error" for f in findings)


def test_l3_flags_session_authority_without_boundary():
    schema = {
        "type": "object",
        "properties": {
            "session_authority": {"type": "string", "const": "agent_context_projection"}
        },
    }
    findings = lint_contract_schema(schema, contract_name="novel.schema.json")
    assert any(f.rule == "L3" and f.severity == "error" for f in findings)


def test_l3_passes_with_does_not_mean_boundary():
    findings = lint_contract_schema(_diag_schema(), contract_name="ok.schema.json")
    assert [f for f in findings if f.rule == "L3"] == []


def test_l3_passes_with_does_not_establish_boundary():
    schema = {
        "type": "object",
        "properties": {
            "authority": {"type": "string", "const": "diagnostic_signal"},
            "does_not_establish": {"type": "array", "items": {"type": "string"}},
        },
    }
    findings = lint_contract_schema(schema, contract_name="ok.schema.json")
    assert [f for f in findings if f.rule == "L3"] == []


def test_l3_passes_with_claim_boundaries():
    schema = {
        "type": "object",
        "properties": {
            "authority": {"type": "string", "const": "runtime_observation"},
            "claim_boundaries": {"type": "object"},
        },
    }
    findings = lint_contract_schema(schema, contract_name="ok.schema.json")
    assert [f for f in findings if f.rule == "L3"] == []


def test_l3_rejects_does_not_mean_boundary_with_wrong_type():
    schema = {
        "type": "object",
        "properties": {
            "authority": {"type": "string", "const": "diagnostic_signal"},
            "does_not_mean": {"type": "string"},
        },
    }
    findings = lint_contract_schema(schema, contract_name="bad.schema.json")
    assert any(f.rule == "L3" and f.severity == "error" for f in findings)


def test_l3_rejects_does_not_prove_boundary_with_wrong_type():
    schema = {
        "type": "object",
        "properties": {
            "authority": {"type": "string", "const": "diagnostic_signal"},
            "does_not_prove": {"type": "object"},
        },
    }
    findings = lint_contract_schema(schema, contract_name="bad.schema.json")
    assert any(f.rule == "L3" and f.severity == "error" for f in findings)


def test_l3_rejects_does_not_establish_boundary_with_wrong_type():
    schema = {
        "type": "object",
        "properties": {
            "authority": {"type": "string", "const": "diagnostic_signal"},
            "does_not_establish": {"type": "string"},
        },
    }
    findings = lint_contract_schema(schema, contract_name="bad.schema.json")
    assert any(f.rule == "L3" and f.severity == "error" for f in findings)


def test_l3_rejects_claim_boundaries_boundary_with_wrong_type():
    schema = {
        "type": "object",
        "properties": {
            "authority": {"type": "string", "const": "diagnostic_signal"},
            "claim_boundaries": {"type": "array", "items": {"type": "string"}},
        },
    }
    findings = lint_contract_schema(schema, contract_name="bad.schema.json")
    assert any(f.rule == "L3" and f.severity == "error" for f in findings)


def test_l3_passes_with_valid_local_ref_boundary():
    schema = {
        "type": "object",
        "definitions": {
            "boundary": {
                "type": "array",
                "items": {"type": "string"},
            }
        },
        "properties": {
            "authority": {"type": "string", "const": "diagnostic_signal"},
            "does_not_establish": {"$ref": "#/definitions/boundary"},
        },
    }
    findings = lint_contract_schema(schema, contract_name="ok.schema.json")
    assert [f for f in findings if f.rule == "L3"] == []


def test_l3_rejects_missing_ref_target():
    schema = {
        "type": "object",
        "definitions": {},
        "properties": {
            "authority": {"type": "string", "const": "diagnostic_signal"},
            "does_not_establish": {"$ref": "#/definitions/missing"},
        },
    }
    findings = lint_contract_schema(schema, contract_name="bad.schema.json")
    assert any(f.rule == "L3" and f.severity == "error" for f in findings)


def test_l3_rejects_non_textual_ref():
    schema = {
        "type": "object",
        "properties": {
            "authority": {"type": "string", "const": "diagnostic_signal"},
            "does_not_establish": {"$ref": 123},
        },
    }
    findings = lint_contract_schema(schema, contract_name="bad.schema.json")
    assert any(f.rule == "L3" and f.severity == "error" for f in findings)


def test_l3_rejects_definitions_with_wrong_type():
    schema = {
        "type": "object",
        "definitions": [],
        "properties": {
            "authority": {"type": "string", "const": "diagnostic_signal"},
            "does_not_establish": {"$ref": "#/definitions/boundary"},
        },
    }
    findings = lint_contract_schema(schema, contract_name="bad.schema.json")
    assert any(f.rule == "L3" and f.severity == "error" for f in findings)


def test_l3_rejects_resolved_target_with_wrong_type():
    schema = {
        "type": "object",
        "definitions": {
            "boundary": {
                "type": "string"
            }
        },
        "properties": {
            "authority": {"type": "string", "const": "diagnostic_signal"},
            "does_not_establish": {"$ref": "#/definitions/boundary"},
        },
    }
    findings = lint_contract_schema(schema, contract_name="bad.schema.json")
    assert any(f.rule == "L3" and f.severity == "error" for f in findings)


def test_l3_rejects_nested_local_path():
    schema = {
        "type": "object",
        "definitions": {
            "group/boundary": {
                "type": "array"
            },
            "boundary": {
                "type": "array"
            }
        },
        "properties": {
            "authority": {"type": "string", "const": "diagnostic_signal"},
            "does_not_establish": {"$ref": "#/definitions/group/boundary"},
        },
    }
    findings = lint_contract_schema(schema, contract_name="bad.schema.json")
    assert any(f.rule == "L3" and f.severity == "error" for f in findings)


def test_l3_rejects_external_or_other_ref():
    for ref_val in ["https://example.invalid/schema.json#/boundary", "#/$defs/boundary"]:
        schema = {
            "type": "object",
            "properties": {
                "authority": {"type": "string", "const": "diagnostic_signal"},
                "does_not_establish": {"$ref": ref_val},
            },
        }
        findings = lint_contract_schema(schema, contract_name="bad.schema.json")
        assert any(f.rule == "L3" and f.severity == "error" for f in findings)


def test_l3_ignores_non_self_declaring_registry_schema():
    # bundle-manifest style: authority is a per-role nested enum, not a root const
    # self-declaration. Such a registry must NOT be governed by L3.
    schema = {
        "type": "object",
        "properties": {
            "artifacts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "authority": {
                            "type": "string",
                            "enum": ["diagnostic_signal", "navigation_index"],
                        }
                    },
                },
            }
        },
    }
    findings = lint_contract_schema(schema, contract_name="registry.schema.json")
    assert [f for f in findings if f.rule == "L3"] == []


def test_l3_ignores_non_governed_authority_const():
    schema = {
        "type": "object",
        "properties": {"authority": {"type": "string", "const": "canonical_content"}},
    }
    findings = lint_contract_schema(schema, contract_name="content.schema.json")
    assert [f for f in findings if f.rule == "L3"] == []


def test_l3_deferral_mechanism_downgrades_registered_contract(monkeypatch):
    # The live registry is currently empty (the retrieval-eval-diagnostics.v1
    # deferral was resolved). The deferral *mechanism* must still downgrade a
    # registered contract's missing-boundary finding to a non-blocking `deferred`,
    # while an unregistered contract with the same gap stays a blocking `error`.
    schema = {
        "type": "object",
        "properties": {"authority": {"type": "string", "const": "diagnostic_signal"}},
    }
    monkeypatch.setitem(
        DEFERRED_BOUNDARY_CONTRACTS, "synthetic-deferred.v1.schema.json", "synthetic rationale"
    )

    deferred = lint_contract_schema(schema, contract_name="synthetic-deferred.v1.schema.json")
    l3_deferred = [f for f in deferred if f.rule == "L3"]
    assert len(l3_deferred) == 1
    assert l3_deferred[0].severity == "deferred"

    blocking = lint_contract_schema(schema, contract_name="unregistered.v1.schema.json")
    assert any(f.rule == "L3" and f.severity == "error" for f in blocking)


# --- Report shape ----------------------------------------------------------


def test_report_self_declares_diagnostic_authority_and_disclaimers():
    schema = _diag_schema()
    report = lint_contracts({"a.schema.json": schema})
    d = report.to_dict()
    assert d["kind"] == "lenskit.anti_hallucination_lint"
    assert d["authority"] == "diagnostic_signal"
    assert d["risk_class"] == "diagnostic"
    assert d["status"] == "pass"
    assert d["rules_enforced"] == list(ENFORCED_RULES)
    assert set(d["rules_out_of_scope"]) == set(OUT_OF_SCOPE_RULES)
    assert any("does_not_prove_artifacts_are_truthful" in m for m in d["does_not_mean"])


def test_report_status_fail_on_error():
    bad = {
        "type": "object",
        "properties": {"agent_ready": {"type": "boolean"}},
    }
    report = lint_contracts({"bad.schema.json": bad})
    assert report.status == "fail"
    assert report.error_count == 1


# --- Integration against the real contract set -----------------------------


def test_real_contracts_lint_is_green():
    report = lint_contracts_dir(_CONTRACTS_DIR)
    assert report.status == "pass", [f.to_dict() for f in report.findings]
    assert report.error_count == 0
    assert report.contracts_scanned >= 30


def test_real_contracts_deferral_set_matches_registry():
    report = lint_contracts_dir(_CONTRACTS_DIR)
    deferred = {f.contract for f in report.deferred}
    assert deferred == set(DEFERRED_BOUNDARY_CONTRACTS)
    # The registry is currently empty: every self-declaring contract carries a
    # root boundary, so there are no tracked deferrals.
    assert report.deferred_count == 0


def test_retrieval_eval_diagnostics_carries_root_boundary():
    # The former sole deferral now carries a required root does_not_prove array,
    # so it is no longer registered and produces no L3 finding (blocking or deferred).
    name = "retrieval-eval-diagnostics.v1.schema.json"
    assert name not in DEFERRED_BOUNDARY_CONTRACTS
    schema = load_contract_schemas(_CONTRACTS_DIR)[name]
    findings = lint_contract_schema(schema, contract_name=name)
    assert [f for f in findings if f.rule == "L3"] == []


def test_real_contracts_normalized_self_declarers_pass_l3():
    # Every contract that self-declares a boundary-requiring authority and is NOT
    # in the deferral registry must carry a root boundary (no L3 error).
    schemas = load_contract_schemas(_CONTRACTS_DIR)
    report = lint_contracts(schemas)
    l3_errors = [f for f in report.findings if f.rule == "L3"]
    assert l3_errors == [], [f.to_dict() for f in l3_errors]


def test_deferral_registry_is_not_stale():
    schemas = load_contract_schemas(_CONTRACTS_DIR)
    assert audit_deferral_registry(schemas) == []


# --- CLI smoke -------------------------------------------------------------


def test_cli_governance_lint_exit_zero():
    from merger.lenskit.cli.main import main

    assert main(["governance", "lint"]) == 0


def test_cli_governance_lint_json_is_valid(capsys):
    from merger.lenskit.cli.main import main

    rc = main(["governance", "lint", "--json"])
    assert rc == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["status"] == "pass"
    assert payload["authority"] == "diagnostic_signal"
    assert payload["error_count"] == 0


def test_l5_flags_forbidden_verdict_const_value_in_composition():
    schema = _diag_schema(
        {"status": {"oneOf": [{"const": "verified"}, {"const": "pass"}]}}
    )
    findings = lint_contract_schema(schema, contract_name="x.schema.json")
    assert any(f.rule == "L5" and "verified" in f.message for f in findings)


def test_load_contract_schemas_rejects_missing_dir(tmp_path):
    with pytest.raises(ValueError, match="contracts dir does not exist"):
        load_contract_schemas(tmp_path / "missing")


def test_load_contract_schemas_rejects_non_directory(tmp_path):
    not_a_dir = tmp_path / "not-a-dir"
    not_a_dir.write_text("not a directory", encoding="utf-8")

    with pytest.raises(ValueError, match="contracts dir is not a directory"):
        load_contract_schemas(not_a_dir)


def test_load_contract_schemas_rejects_empty_contract_dir(tmp_path):
    empty_dir = tmp_path / "empty-contracts"
    empty_dir.mkdir()

    with pytest.raises(ValueError, match=r"no \*\.schema\.json files found"):
        load_contract_schemas(empty_dir)


def test_relation_card_contract_is_lint_clean():
    # Relation Cards declare navigation_index authority (not boundary-requiring)
    # and carry no forbidden truth-language property names or verdict-field
    # values. The does_not_establish negative-boundary VALUES — including
    # runtime_dependency, causality, change_impact and security_assessment — name
    # the forbidden inferences as negatives and must never be flagged.
    name = "relation-card.v1.schema.json"
    schema = load_contract_schemas(_CONTRACTS_DIR)[name]
    findings = lint_contract_schema(schema, contract_name=name)
    assert findings == [], [f.to_dict() for f in findings]
