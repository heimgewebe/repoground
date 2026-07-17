import copy

import pytest

import merger.repoground.core.lens_card_validate as validator_mod
from merger.repoground.core.lens_cards import produce_lens_card
from merger.repoground.core.lens_facets import FACET_SOURCE_RULES, V1_DERIVATION_TYPE


def _facet(facet: str) -> dict:
    return {
        "facet": facet,
        "source_rule": FACET_SOURCE_RULES[facet],
        "derivation_type": V1_DERIVATION_TYPE,
    }


def _check(result: dict, name: str) -> dict:
    matches = [check for check in result["checks"] if check["name"] == name]
    assert len(matches) == 1
    return matches[0]


def test_producer_card_validates_successfully() -> None:
    card = produce_lens_card("merger/repoground/contracts/lens-card.v1.schema.json")
    result = validator_mod.validate_lens_card(card)

    assert result["status"] == "pass"
    schema_check = _check(result, "schema_validation")
    assert schema_check["status"] == "pass"
    assert schema_check["validation"] == {
        "mode": "jsonschema",
        "engine": "jsonschema",
        "reason": "available",
    }

    coherence_check = _check(result, "producer_coherence")
    assert coherence_check["status"] == "pass"
    assert coherence_check["validation"] == {
        "mode": "structural_precheck",
        "engine": "lens_card_validate",
        "reason": "producer_coherence_check",
    }

    assert result["dependencies"]["jsonschema"]["available"] is True
    assert "truth" in result["does_not_establish"]
    assert "repo_understood" in result["does_not_establish"]
    assert "review_complete" in result["does_not_establish"]
    assert "change_impact" in result["does_not_establish"]
    assert "safety" in result["does_not_establish"]


def test_known_but_wrong_primary_lens_fails() -> None:
    card = produce_lens_card("merger/repoground/contracts/lens-card.v1.schema.json")
    card["primary_lens"] = "core"
    result = validator_mod.validate_lens_card(card)

    assert result["status"] == "fail"
    coherence_check = _check(result, "producer_coherence")
    mismatch = coherence_check["mismatches"][0]
    assert mismatch["field"] == "primary_lens"
    assert coherence_check["validation"] == {
        "mode": "structural_precheck",
        "engine": "lens_card_validate",
        "reason": "producer_coherence_check",
    }


def test_known_but_wrong_facet_fails() -> None:
    card = produce_lens_card("merger/repoground/contracts/lens-card.v1.schema.json")
    card["facets"] = [_facet("test")]
    result = validator_mod.validate_lens_card(card)

    assert result["status"] == "fail"
    coherence_check = _check(result, "producer_coherence")
    assert coherence_check["status"] == "fail"
    assert coherence_check["validation"] == {
        "mode": "structural_precheck",
        "engine": "lens_card_validate",
        "reason": "producer_coherence_check",
    }


def test_incomplete_facet_list_fails() -> None:
    card = produce_lens_card("merger/repoground/retrieval/test_eval_capability.py")
    assert len(card["facets"]) == 2
    card["facets"] = card["facets"][:1]
    result = validator_mod.validate_lens_card(card)

    assert result["status"] == "fail"
    coherence_check = _check(result, "producer_coherence")
    assert coherence_check["mismatches"][0]["field"] == "facets"
    assert coherence_check["validation"] == {
        "mode": "structural_precheck",
        "engine": "lens_card_validate",
        "reason": "producer_coherence_check",
    }


def test_extra_facet_assignment_fails() -> None:
    card = produce_lens_card("merger/repoground/core/lenses.py")
    card["facets"] = [_facet("retrieval")]
    result = validator_mod.validate_lens_card(card)

    assert result["status"] == "fail"
    coherence_check = _check(result, "producer_coherence")
    assert coherence_check["mismatches"][0]["field"] == "facets"


def test_wrong_matched_rule_fails() -> None:
    card = produce_lens_card("merger/repoground/core/lenses.py")
    card["matched_rule"] = "core: wrong but non-empty controlled-looking rule"
    result = validator_mod.validate_lens_card(card)

    assert result["status"] == "fail"
    coherence_check = _check(result, "producer_coherence")
    assert coherence_check["mismatches"][0]["field"] == "matched_rule"


def test_wrong_navigation_ref_fails() -> None:
    card = produce_lens_card("merger/repoground/core/lenses.py")
    card["navigation_refs"] = [{"kind": "repo_path", "target": "docs/other.md"}]
    result = validator_mod.validate_lens_card(card)

    assert result["status"] == "fail"
    coherence_check = _check(result, "producer_coherence")
    assert coherence_check["mismatches"][0]["field"] == "navigation_refs"


def test_unsorted_facets_fail() -> None:
    card = produce_lens_card("merger/repoground/retrieval/test_eval_capability.py")
    card["facets"] = list(reversed(card["facets"]))
    result = validator_mod.validate_lens_card(card)

    assert result["status"] == "fail"
    coherence_check = _check(result, "producer_coherence")
    assert coherence_check["mismatches"][0]["field"] == "facets"


def test_forbidden_fields_fail_schema_validation() -> None:
    card = produce_lens_card("merger/repoground/core/lenses.py")
    card["confidence_class"] = "high"
    result = validator_mod.validate_lens_card(card)

    assert result["status"] == "fail"
    schema_check = _check(result, "schema_validation")
    assert schema_check["status"] == "fail"
    assert schema_check["validation"] == {
        "mode": "jsonschema",
        "engine": "jsonschema",
        "reason": "available",
    }
    assert schema_check["errors"][0]["validator"] == "additionalProperties"


def test_error_order_is_deterministic() -> None:
    card = produce_lens_card("merger/repoground/core/lenses.py")
    card["kind"] = "wrong"
    card["version"] = "2.0"
    card["confidence_class"] = "high"

    first = validator_mod.validate_lens_card(copy.deepcopy(card))
    second = validator_mod.validate_lens_card(copy.deepcopy(card))

    assert first == second
    assert first["status"] == "fail"


def test_missing_jsonschema_degrades_machine_readably_and_never_passes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_import_module = validator_mod.importlib.import_module

    def fake_import_module(name: str):
        if name == "jsonschema":
            raise ModuleNotFoundError("simulated missing jsonschema")
        return original_import_module(name)

    monkeypatch.setattr(validator_mod.importlib, "import_module", fake_import_module)

    result = validator_mod.validate_lens_card(
        produce_lens_card("merger/repoground/contracts/lens-card.v1.schema.json")
    )

    assert result["status"] == "fail"
    assert result["dependencies"]["jsonschema"]["available"] is False
    assert result["dependencies"]["jsonschema"]["effect"] == "validation_degraded"

    schema_check = _check(result, "schema_validation")
    assert schema_check["status"] == "fail"
    assert schema_check["validation"] == {
        "mode": "skipped_unavailable",
        "engine": "jsonschema",
        "reason": "dependency_unavailable",
    }

    # keine Producer-Kohärenzprüfung nach dem Schema-Skip
    assert not any(check["name"] == "producer_coherence" for check in result["checks"])


def test_invalid_schema_passed_fails_gracefully() -> None:
    card = produce_lens_card("merger/repoground/contracts/lens-card.v1.schema.json")
    result = validator_mod.validate_lens_card(card, schema={"type": "invalid_type"})

    assert result["status"] == "fail"
    schema_check = _check(result, "schema_validation")
    assert schema_check["status"] == "fail"
    assert schema_check["validation"] == {
        "mode": "jsonschema",
        "engine": "jsonschema",
        "reason": "schema_invalid",
    }


def test_producer_exception_caught(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_produce(*args, **kwargs):
        raise ValueError("simulated crash")

    monkeypatch.setattr("merger.repoground.core.lens_card_validate.produce_lens_card", fake_produce)

    card = produce_lens_card("merger/repoground/contracts/lens-card.v1.schema.json")
    result = validator_mod.validate_lens_card(card)

    assert result["status"] == "fail"
    coherence_check = _check(result, "producer_coherence")
    assert coherence_check["status"] == "fail"
    assert "simulated crash" in coherence_check["detail"]
    assert coherence_check["validation"] == {
        "mode": "structural_precheck",
        "engine": "lens_card_validate",
        "reason": "producer_coherence_check",
    }
