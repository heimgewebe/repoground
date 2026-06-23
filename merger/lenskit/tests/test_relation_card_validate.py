"""Source-aware validator tests for Relation Cards v1.

The validator is fail-closed and reuses the existing lens-family check shape.
These tests redefine their own tiny graph builders (no cross-test private
imports) and exercise the full check order, each fail-closed branch, and the
explicit anti-upgrade evidence-preservation guard.
"""
import copy

import pytest

from merger.lenskit.core.relation_cards import produce_relation_cards
from merger.lenskit.core.relation_card_validate import (
    VALIDATOR_DOES_NOT_ESTABLISH,
    validate_relation_card,
)

_CHECK_ORDER = [
    "schema_validation",
    "source_schema_validation",
    "source_producer_coherence",
    "evidence_preservation",
]


def _file_node(path):
    return {
        "node_id": f"file:{path}",
        "kind": "file",
        "path": path,
        "repo": "",
        "is_test": False,
    }


def _import_edge(src, dst, start=3):
    return {
        "src": f"file:{src}",
        "dst": f"file:{dst}",
        "edge_type": "import",
        "evidence_level": "S1",
        "evidence": {"source_path": src, "start_line": start, "end_line": start},
    }


def _graph(src="a.py", dst="b.py", start=3):
    return {
        "kind": "lenskit.architecture.graph",
        "version": "1.0",
        "run_id": "test_run",
        "canonical_dump_index_sha256": "0" * 64,
        "granularity": "file",
        "nodes": [_file_node(src), _file_node(dst)],
        "edges": [_import_edge(src, dst, start)],
        "coverage": {
            "files_seen": 2,
            "files_parsed": 2,
            "edge_counts_by_type": {"import": 1},
            "unknown_layer_share": 0.0,
        },
    }


def _card(graph=None):
    graph = graph or _graph()
    return produce_relation_cards(graph)[0]


def _check(val, name):
    matches = [c for c in val["checks"] if c["name"] == name]
    assert len(matches) == 1, f"expected exactly one {name} check"
    return matches[0]


class TestValidatorHappyPath:
    def test_valid_card_and_source_pass(self):
        graph = _graph()
        val = validate_relation_card(_card(graph), source_graph=graph)
        assert val["status"] == "pass"
        assert [c["name"] for c in val["checks"]] == _CHECK_ORDER
        assert all(c["status"] == "pass" for c in val["checks"])

    def test_assembled_shape(self):
        graph = _graph()
        val = validate_relation_card(_card(graph), source_graph=graph)
        assert val["kind"] == "lenskit.relation_card_validation"
        assert val["version"] == "1.0"
        assert val["dependencies"]["jsonschema"]["available"] is True
        assert val["dependencies"]["jsonschema"]["required_for"] == [
            "relation_card_schema",
            "architecture_graph_source_schema",
        ]
        assert val["does_not_establish"] == list(VALIDATOR_DOES_NOT_ESTABLISH)

    def test_each_check_has_validation_shape(self):
        graph = _graph()
        val = validate_relation_card(_card(graph), source_graph=graph)
        for check in val["checks"]:
            assert set(check["validation"]) == {"mode", "engine", "reason"}
            assert isinstance(check["detail"], str) and check["detail"]


class TestCardSchemaLayer:
    def test_card_schema_error_short_circuits(self):
        graph = _graph()
        card = _card(graph)
        del card["kind"]
        val = validate_relation_card(card, source_graph=graph)
        assert val["status"] == "fail"
        assert [c["name"] for c in val["checks"]] == ["schema_validation"]
        assert _check(val, "schema_validation")["status"] == "fail"

    def test_structured_schema_error_report(self):
        graph = _graph()
        card = _card(graph)
        del card["kind"]
        del card["version"]
        val = validate_relation_card(card, source_graph=graph)
        errors = _check(val, "schema_validation")["errors"]
        assert all(set(e) == {"path", "validator", "message"} for e in errors)
        assert [e["validator"] for e in errors] == ["required", "required"]

    def test_invalid_supplied_card_schema(self):
        graph = _graph()
        val = validate_relation_card(_card(graph), source_graph=graph, schema={"type": "invalid"})
        assert val["status"] == "fail"
        assert _check(val, "schema_validation")["validation"]["reason"] == "schema_invalid"

    @pytest.mark.parametrize("field,value", [
        ("relation", "tests"),
        ("source_rule", "regex_guess"),
        ("derivation_type", "direct"),
        ("evidence_level", "S2"),
    ])
    def test_const_field_mutation_fails_schema(self, field, value):
        graph = _graph()
        card = _card(graph)
        card[field] = value
        val = validate_relation_card(card, source_graph=graph)
        assert val["status"] == "fail"
        assert _check(val, "schema_validation")["status"] == "fail"


class TestSourceSchemaLayer:
    def test_source_schema_error(self):
        graph = _graph()
        card = _card(graph)
        bad = copy.deepcopy(graph)
        del bad["coverage"]
        val = validate_relation_card(card, source_graph=bad)
        assert val["status"] == "fail"
        assert _check(val, "schema_validation")["status"] == "pass"
        ss = _check(val, "source_schema_validation")
        assert ss["status"] == "fail"
        assert "errors" in ss
        # short-circuits before coherence
        assert [c["name"] for c in val["checks"]] == [
            "schema_validation",
            "source_schema_validation",
        ]

    def test_invalid_supplied_source_schema(self):
        graph = _graph()
        val = validate_relation_card(
            _card(graph), source_graph=graph, source_schema={"type": "invalid"}
        )
        assert val["status"] == "fail"
        assert _check(val, "source_schema_validation")["validation"]["reason"] == "schema_invalid"


class TestCoherenceLayer:
    def test_source_edge_missing(self):
        card = _card(_graph("a.py", "b.py"))
        other = _graph("c.py", "d.py")
        val = validate_relation_card(card, source_graph=other)
        assert val["status"] == "fail"
        assert _check(val, "source_producer_coherence")["status"] == "fail"

    def test_source_path_manipulated(self):
        graph = _graph()
        card = _card(graph)
        card["source"]["path"] = "z.py"
        val = validate_relation_card(card, source_graph=graph)
        assert val["status"] == "fail"
        assert _check(val, "source_producer_coherence")["status"] == "fail"

    def test_target_path_manipulated(self):
        graph = _graph()
        card = _card(graph)
        card["target"]["path"] = "z.py"
        val = validate_relation_card(card, source_graph=graph)
        assert val["status"] == "fail"
        assert _check(val, "source_producer_coherence")["status"] == "fail"

    def test_evidence_position_manipulated(self):
        graph = _graph()
        card = _card(graph)
        card["evidence"]["start_line"] = 99
        val = validate_relation_card(card, source_graph=graph)
        assert val["status"] == "fail"
        assert _check(val, "source_producer_coherence")["status"] == "fail"

    def test_controlled_producer_exception(self, monkeypatch):
        graph = _graph()
        card = _card(graph)

        def boom(*args, **kwargs):
            raise RuntimeError("synthetic producer failure")

        monkeypatch.setattr(
            f"{validate_relation_card.__module__}.produce_relation_cards", boom
        )
        val = validate_relation_card(card, source_graph=graph)
        assert val["status"] == "fail"
        coherence = _check(val, "source_producer_coherence")
        assert coherence["status"] == "fail"
        assert "synthetic producer failure" in coherence["detail"]

    def test_empty_card_permissive_schema_fails_structurally(self):
        graph = _graph()
        val = validate_relation_card({}, source_graph=graph, schema={"type": "object"})
        assert val["status"] == "fail"
        assert _check(val, "source_producer_coherence")["status"] == "fail"
        assert _check(val, "source_producer_coherence")["validation"]["reason"] == "producer_coherence_check"

    def test_missing_source_permissive_schema_fails_structurally(self):
        graph = _graph()
        card = _card(graph)
        del card["source"]
        val = validate_relation_card(card, source_graph=graph, schema={"type": "object"})
        assert val["status"] == "fail"
        assert _check(val, "source_producer_coherence")["status"] == "fail"
        assert _check(val, "source_producer_coherence")["validation"]["reason"] == "producer_coherence_check"

    def test_missing_source_path_permissive_schema_fails_structurally(self):
        graph = _graph()
        card = _card(graph)
        del card["source"]["path"]
        val = validate_relation_card(card, source_graph=graph, schema={"type": "object"})
        assert val["status"] == "fail"
        assert _check(val, "source_producer_coherence")["status"] == "fail"
        assert _check(val, "source_producer_coherence")["validation"]["reason"] == "producer_coherence_check"

    def test_target_not_mapping_permissive_schema_fails_structurally(self):
        graph = _graph()
        card = _card(graph)
        card["target"] = "not-a-mapping"
        val = validate_relation_card(card, source_graph=graph, schema={"type": "object"})
        assert val["status"] == "fail"
        assert _check(val, "source_producer_coherence")["status"] == "fail"
        assert _check(val, "source_producer_coherence")["validation"]["reason"] == "producer_coherence_check"

    def test_evidence_not_mapping_permissive_schema_fails_structurally(self):
        graph = _graph()
        card = _card(graph)
        card["evidence"] = "not-a-mapping"
        val = validate_relation_card(card, source_graph=graph, schema={"type": "object"})
        assert val["status"] == "fail"
        assert _check(val, "source_producer_coherence")["status"] == "fail"
        assert _check(val, "source_producer_coherence")["validation"]["reason"] == "producer_coherence_check"


class TestEvidencePreservation:
    def test_upgrade_caught_under_permissive_schema(self):
        # A permissive supplied schema lets a semantic upgrade past the schema
        # layer; evidence_preservation must still catch it.
        graph = _graph()
        card = _card(graph)
        card["evidence_level"] = "S2"
        val = validate_relation_card(card, source_graph=graph, schema={"type": "object"})
        assert val["status"] == "fail"
        assert [c["name"] for c in val["checks"]] == _CHECK_ORDER
        assert _check(val, "schema_validation")["status"] == "pass"
        assert _check(val, "source_producer_coherence")["status"] == "pass"
        preservation = _check(val, "evidence_preservation")
        assert preservation["status"] == "fail"
        assert any(m["field"] == "evidence_level" for m in preservation["mismatches"])

    def test_does_not_establish_downgrade_caught_under_permissive_schema(self):
        graph = _graph()
        card = _card(graph)
        card["does_not_establish"] = ["truth"]
        val = validate_relation_card(card, source_graph=graph, schema={"type": "object"})
        assert val["status"] == "fail"
        preservation = _check(val, "evidence_preservation")
        assert preservation["status"] == "fail"
        assert any(m["field"] == "does_not_establish" for m in preservation["mismatches"])



    def test_additional_claim_field_caught_under_permissive_schema(self):
        graph = _graph()
        card = _card(graph)
        card["impact"] = "high"

        val = validate_relation_card(
            card,
            source_graph=graph,
            schema={"type": "object"},
        )

        assert val["status"] == "fail"
        assert _check(val, "schema_validation")["status"] == "pass"
        assert _check(val, "source_schema_validation")["status"] == "pass"
        assert _check(val, "source_producer_coherence")["status"] == "pass"

        preservation = _check(val, "evidence_preservation")
        assert preservation["status"] == "fail"
        assert preservation["mismatches"] == []
        assert preservation["unexpected_fields"] == ["impact"]


class TestDependencyLayer:
    def test_missing_jsonschema_fails_closed(self, monkeypatch):
        import sys

        graph = _graph()
        card = _card(graph)
        monkeypatch.setitem(sys.modules, "jsonschema", None)
        val = validate_relation_card(card, source_graph=graph)
        assert val["status"] == "fail"
        assert any(
            c["validation"]["reason"] == "dependency_unavailable" for c in val["checks"]
        )
        assert val["dependencies"]["jsonschema"]["available"] is False
        assert val["dependencies"]["jsonschema"]["required_for"] == [
            "relation_card_schema",
            "architecture_graph_source_schema",
        ]


class TestRollup:
    def test_overall_fail_when_one_mandatory_check_fails(self):
        graph = _graph()
        card = _card(graph)
        card["evidence"]["start_line"] = 42  # breaks coherence only
        val = validate_relation_card(card, source_graph=graph)
        statuses = {c["name"]: c["status"] for c in val["checks"]}
        assert statuses["schema_validation"] == "pass"
        assert statuses["source_schema_validation"] == "pass"
        assert statuses["source_producer_coherence"] == "fail"
        assert val["status"] == "fail"
