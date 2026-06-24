"""Tests for the relation cards producer v1.

Relation Cards are a deterministic projection of already-detected local
import edges from an ``architecture.graph.v1`` mapping. These tests use small
inline graph mappings for precise control plus the real architecture import-graph
golden fixture for an integration check; they never build a second, incompatible
graph world.
"""
import copy
import json
from pathlib import Path

import jsonschema
import pytest

from merger.lenskit.core.relation_cards import (
    DOES_NOT_ESTABLISH,
    SourceValidationError,
    produce_relation_cards,
)

_CONTRACTS = Path(__file__).parent.parent / "contracts"
_CARD_SCHEMA_PATH = _CONTRACTS / "relation-card.v1.schema.json"
_GRAPH_FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "architecture_import_graph"
    / "expected.graph.json"
)

_CARD_SCHEMA = json.loads(_CARD_SCHEMA_PATH.read_text(encoding="utf-8"))


# --- graph builders --------------------------------------------------------


def _file_node(path, **kw):
    node = {
        "node_id": f"file:{path}",
        "kind": "file",
        "path": path,
        "repo": "",
        "is_test": False,
    }
    node.update(kw)
    return node


def _node(node_id, kind, path="", **kw):
    node = {
        "node_id": node_id,
        "kind": kind,
        "path": path,
        "repo": "",
        "is_test": False,
    }
    node.update(kw)
    return node


def _edge(src_id, dst_id, *, start=1, end=None, edge_type="import",
          evidence_level="S1", source_path=None, evidence=None):
    if evidence is None:
        evidence = {"source_path": source_path if source_path is not None else src_id[5:]}
        if start is not None:
            evidence["start_line"] = start
            evidence["end_line"] = end if end is not None else start
    return {
        "src": src_id,
        "dst": dst_id,
        "edge_type": edge_type,
        "evidence_level": evidence_level,
        "evidence": evidence,
    }


def _graph(nodes, edges):
    counts = {}
    for e in edges:
        counts[e["edge_type"]] = counts.get(e["edge_type"], 0) + 1
    return {
        "kind": "lenskit.architecture.graph",
        "version": "1.0",
        "run_id": "test_run",
        "canonical_dump_index_sha256": "0" * 64,
        "granularity": "file",
        "nodes": nodes,
        "edges": edges,
        "coverage": {
            "files_seen": len(nodes),
            "files_parsed": len(nodes),
            "edge_counts_by_type": counts,
            "unknown_layer_share": 0.0,
        },
    }


def _file_to_file_graph(src="a.py", dst="b.py", start=3, end=None):
    return _graph(
        [_file_node(src), _file_node(dst)],
        [_edge(f"file:{src}", f"file:{dst}", start=start, end=end)],
    )


def _valid_card():
    return produce_relation_cards(_file_to_file_graph())[0]


def _card_errors(card):
    jsonschema.Draft7Validator.check_schema(_CARD_SCHEMA)
    validator = jsonschema.Draft7Validator(_CARD_SCHEMA)
    return [e.message for e in validator.iter_errors(card)]


# --- producer --------------------------------------------------------------


class TestProducer:
    def test_single_file_to_file_edge_yields_one_card(self):
        cards = produce_relation_cards(_file_to_file_graph())
        assert len(cards) == 1

    def test_relation_is_imports(self):
        assert _valid_card()["relation"] == "imports"

    def test_source_rule_is_architecture_graph_import_edge(self):
        assert _valid_card()["source_rule"] == "architecture_graph_import_edge"

    def test_source_rule_does_not_assert_python_ast(self):
        assert "python_ast_import" not in _valid_card().values()

    def test_derivation_type_is_heuristic(self):
        assert _valid_card()["derivation_type"] == "heuristic"

    def test_evidence_level_stays_s1(self):
        assert _valid_card()["evidence_level"] == "S1"

    def test_source_and_target_paths_are_carried_over(self):
        card = produce_relation_cards(_file_to_file_graph("pkg/a.py", "pkg/b.py", start=5))[0]
        assert card["source"] == {"kind": "repo_path", "path": "pkg/a.py"}
        assert card["target"] == {"kind": "repo_path", "path": "pkg/b.py"}
        assert card["evidence"] == {"source_path": "pkg/a.py", "start_line": 5, "end_line": 5}

    def test_two_edges_sorted_deterministically(self):
        graph = _graph(
            [_file_node("a.py"), _file_node("b.py"), _file_node("c.py")],
            [
                _edge("file:c.py", "file:a.py", start=1),
                _edge("file:a.py", "file:b.py", start=1),
            ],
        )
        cards = produce_relation_cards(graph)
        assert [(c["source"]["path"], c["target"]["path"]) for c in cards] == [
            ("a.py", "b.py"),
            ("c.py", "a.py"),
        ]

    def test_input_order_does_not_change_output(self):
        graph = _graph(
            [_file_node("a.py"), _file_node("b.py"), _file_node("c.py")],
            [
                _edge("file:a.py", "file:b.py", start=2),
                _edge("file:c.py", "file:a.py", start=1),
                _edge("file:a.py", "file:c.py", start=1),
            ],
        )
        reversed_graph = copy.deepcopy(graph)
        reversed_graph["edges"] = list(reversed(reversed_graph["edges"]))
        reversed_graph["nodes"] = list(reversed(reversed_graph["nodes"]))
        assert produce_relation_cards(graph) == produce_relation_cards(reversed_graph)

    def test_exact_duplicate_edges_yield_one_card(self):
        edge = _edge("file:a.py", "file:b.py", start=3)
        graph = _graph([_file_node("a.py"), _file_node("b.py")], [edge, copy.deepcopy(edge)])
        assert len(produce_relation_cards(graph)) == 1

    def test_distinct_evidence_lines_are_not_aggregated(self):
        graph = _graph(
            [_file_node("a.py"), _file_node("b.py")],
            [
                _edge("file:a.py", "file:b.py", start=1),
                _edge("file:a.py", "file:b.py", start=2),
            ],
        )
        cards = produce_relation_cards(graph)
        assert len(cards) == 2
        assert sorted(c["evidence"]["start_line"] for c in cards) == [1, 2]

    def test_external_module_nodes_are_excluded(self):
        graph = _graph(
            [_file_node("a.py"), _node("module:os", "external")],
            [_edge("file:a.py", "module:os", start=1)],
        )
        assert produce_relation_cards(graph) == []

    def test_package_and_module_kind_nodes_without_path_are_not_projected(self):
        graph = _graph(
            [
                _file_node("a.py"),
                _node("module:pkg", "module"),
                _node("package:pkg", "package"),
            ],
            [
                _edge("file:a.py", "module:pkg", start=1),
                _edge("file:a.py", "package:pkg", start=2),
            ],
        )
        assert produce_relation_cards(graph) == []

    def test_unsupported_valid_edge_types_are_ignored(self):
        # require/config-link/string-ref/call-heuristic are schema-valid but
        # outside the imports-only v1 surface: deterministically ignored.
        nodes = [_file_node("a.py"), _file_node("b.py")]
        edges = [
            _edge("file:a.py", "file:b.py", start=1, edge_type="require"),
            _edge("file:a.py", "file:b.py", start=2, edge_type="config-link"),
            _edge("file:a.py", "file:b.py", start=3, edge_type="string-ref"),
            _edge("file:a.py", "file:b.py", start=4, edge_type="call-heuristic"),
        ]
        assert produce_relation_cards(_graph(nodes, edges)) == []

    def test_non_s1_import_edges_are_ignored(self):
        nodes = [_file_node("a.py"), _file_node("b.py")]
        edges = [_edge("file:a.py", "file:b.py", start=1, evidence_level="S0")]
        assert produce_relation_cards(_graph(nodes, edges)) == []

    def test_empty_edge_list_yields_empty_output(self):
        assert produce_relation_cards(_graph([_file_node("a.py")], [])) == []

    def test_invalid_source_graph_fails_closed(self):
        graph = _file_to_file_graph()
        del graph["coverage"]
        with pytest.raises(SourceValidationError):
            produce_relation_cards(graph)

    def test_duplicate_node_id_fails_closed(self):
        graph = _graph([_file_node("a.py"), _file_node("a.py")], [])
        with pytest.raises(SourceValidationError) as exc:
            produce_relation_cards(graph)
        assert exc.value.errors[0]["validator"] == "unique_node_id"
        assert exc.value.errors[0]["message"] == "duplicate node_id: file:a.py"

    def test_duplicate_node_id_failure_is_independent_of_node_order(self):
        graph1 = _graph([_node("file:a.py", "file", path="x"), _node("file:a.py", "file", path="y")], [])
        graph2 = _graph([_node("file:a.py", "file", path="y"), _node("file:a.py", "file", path="x")], [])

        with pytest.raises(SourceValidationError) as exc1:
            produce_relation_cards(graph1)
        with pytest.raises(SourceValidationError) as exc2:
            produce_relation_cards(graph2)

        assert exc1.value.errors[0]["message"] == "duplicate node_id: file:a.py"
        assert exc2.value.errors[0]["message"] == "duplicate node_id: file:a.py"

    def test_dangling_edge_src_fails_closed(self):
        graph = _graph([_file_node("b.py")], [_edge("file:a.py", "file:b.py")])
        with pytest.raises(SourceValidationError) as exc:
            produce_relation_cards(graph)
        assert exc.value.errors[0]["validator"] == "edge_reference"
        assert exc.value.errors[0]["message"] == "edge src does not resolve: file:a.py"

    def test_dangling_edge_dst_fails_closed(self):
        graph = _graph([_file_node("a.py")], [_edge("file:a.py", "file:b.py")])
        with pytest.raises(SourceValidationError) as exc:
            produce_relation_cards(graph)
        assert exc.value.errors[0]["validator"] == "edge_reference"
        assert exc.value.errors[0]["message"] == "edge dst does not resolve: file:b.py"

    def test_unknown_edge_type_fails_source_validation(self):
        graph = _file_to_file_graph()
        graph["edges"][0]["edge_type"] = "totally-unknown"
        with pytest.raises(SourceValidationError):
            produce_relation_cards(graph)

    @pytest.mark.parametrize("bad_path", ["../evil.py", "a/../b.py"])
    def test_traversal_paths_are_rejected(self, bad_path):
        for nodes, edges in (
            (
                [_file_node(bad_path), _file_node("b.py")],
                [_edge(f"file:{bad_path}", "file:b.py", start=1)],
            ),
            (
                [_file_node("a.py"), _file_node(bad_path)],
                [_edge("file:a.py", f"file:{bad_path}", start=1, source_path="a.py")],
            ),
        ):
            with pytest.raises(SourceValidationError):
                produce_relation_cards(_graph(nodes, edges))

    @pytest.mark.parametrize("bad_path", ["/abs.py", "C:/win.py"])
    def test_absolute_paths_are_rejected(self, bad_path):
        nodes = [_file_node("a.py"), _file_node(bad_path)]
        edges = [_edge("file:a.py", f"file:{bad_path}", start=1, source_path="a.py")]
        with pytest.raises(SourceValidationError):
            produce_relation_cards(_graph(nodes, edges))

    def test_evidence_source_path_mismatch_fails_closed(self):
        nodes = [_file_node("a.py"), _file_node("b.py")]
        edges = [_edge("file:a.py", "file:b.py", start=1, source_path="other.py")]
        with pytest.raises(SourceValidationError):
            produce_relation_cards(_graph(nodes, edges))

    def test_no_impact_causality_review_or_safety_fields(self):
        card = _valid_card()
        assert set(card.keys()) == {
            "kind",
            "version",
            "authority",
            "canonicality",
            "relation",
            "source",
            "target",
            "source_rule",
            "derivation_type",
            "evidence_level",
            "evidence",
            "does_not_establish",
        }
        forbidden = {
            "verdict", "approved", "safe", "complete", "covered", "critical",
            "impact", "breaks", "requires_fix", "runtime_dependency", "causal",
            "change_impact", "review_priority", "risk", "severity",
        }
        # Forbidden tokens may only appear as negative-boundary VALUES, never keys.
        def _keys(obj):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    yield k
                    yield from _keys(v)
            elif isinstance(obj, list):
                for item in obj:
                    yield from _keys(item)
        assert forbidden.isdisjoint(set(_keys(card)))

    def test_input_mapping_is_not_mutated(self):
        graph = _file_to_file_graph()
        original = copy.deepcopy(graph)
        produce_relation_cards(graph)
        assert graph == original

    def test_non_mapping_input_raises_type_error(self):
        with pytest.raises(TypeError):
            produce_relation_cards([1, 2, 3])

    def test_does_not_establish_is_fixed_twelve_tuple(self):
        assert DOES_NOT_ESTABLISH == (
            "truth",
            "correctness",
            "completeness",
            "runtime_behavior",
            "test_sufficiency",
            "regression_absence",
            "semantic_importance",
            "review_priority",
            "change_impact",
            "runtime_dependency",
            "causality",
            "security_assessment",
        )
        assert _valid_card()["does_not_establish"] == list(DOES_NOT_ESTABLISH)


# --- determinism -----------------------------------------------------------


class TestDeterminism:
    def test_identical_python_and_json_for_reordered_source(self):
        graph = _graph(
            [_file_node("a.py"), _file_node("b.py"), _file_node("c.py")],
            [
                _edge("file:a.py", "file:b.py", start=2),
                _edge("file:c.py", "file:a.py", start=1),
                _edge("file:b.py", "file:c.py", start=4),
            ],
        )
        shuffled = copy.deepcopy(graph)
        shuffled["edges"] = [shuffled["edges"][i] for i in (2, 0, 1)]
        shuffled["nodes"] = list(reversed(shuffled["nodes"]))

        first = produce_relation_cards(graph)
        second = produce_relation_cards(shuffled)
        assert first == second
        assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


# --- real golden fixture (no second graph world) ---------------------------


class TestRealGraphFixture:
    def test_projects_only_local_file_to_file_imports(self):
        graph = json.loads(_GRAPH_FIXTURE.read_text(encoding="utf-8"))
        cards = produce_relation_cards(graph)
        pairs = [(c["source"]["path"], c["target"]["path"], c["evidence"]["start_line"]) for c in cards]
        assert pairs == [
            ("a.py", "b.py", 3),
            ("pkg/__init__.py", "pkg/submodule.py", 1),
            ("pkg/__init__.py", "pkg/submodule.py", 2),
            ("pkg/nested/m.py", "pkg/submodule.py", 1),
            ("pkg/nested/m.py", "pkg/submodule.py", 2),
            ("sub/__init__.py", "sub/x.py", 1),
        ]
        # No external module: target ever appears as a card endpoint.
        assert all("module:" not in c["target"]["path"] for c in cards)
        for card in cards:
            assert _card_errors(card) == []


# --- contract --------------------------------------------------------------


class TestContract:
    def test_valid_minimal_card(self):
        assert _card_errors(_valid_card()) == []

    def test_unknown_relation_rejected(self):
        card = _valid_card()
        card["relation"] = "mentions"
        assert _card_errors(card)

    def test_unknown_source_rule_rejected(self):
        card = _valid_card()
        card["source_rule"] = "regex_guess"
        assert _card_errors(card)

    def test_unknown_derivation_type_rejected(self):
        card = _valid_card()
        card["derivation_type"] = "direct"
        assert _card_errors(card)

    def test_unknown_evidence_level_rejected(self):
        card = _valid_card()
        card["evidence_level"] = "S2"
        assert _card_errors(card)

    def test_missing_source_address_rejected(self):
        card = _valid_card()
        del card["source"]
        assert _card_errors(card)

    def test_missing_target_address_rejected(self):
        card = _valid_card()
        del card["target"]
        assert _card_errors(card)

    def test_empty_path_rejected(self):
        card = _valid_card()
        card["source"]["path"] = ""
        assert _card_errors(card)

    def test_absolute_path_rejected(self):
        card = _valid_card()
        card["target"]["path"] = "/abs.py"
        assert _card_errors(card)

    def test_traversal_path_rejected(self):
        card = _valid_card()
        card["target"]["path"] = "../escape.py"
        assert _card_errors(card)

    def test_missing_evidence_rejected(self):
        card = _valid_card()
        del card["evidence"]
        assert _card_errors(card)

    def test_additional_properties_rejected(self):
        card = _valid_card()
        card["impact"] = "high"
        assert _card_errors(card)

    def test_additional_endpoint_property_rejected(self):
        card = _valid_card()
        card["source"]["weight"] = 9
        assert _card_errors(card)

    def test_incomplete_negative_semantics_rejected(self):
        card = _valid_card()
        card["does_not_establish"] = card["does_not_establish"][:-1]
        assert _card_errors(card)

    def test_reordered_negative_semantics_rejected(self):
        card = _valid_card()
        dne = list(card["does_not_establish"])
        dne[0], dne[1] = dne[1], dne[0]
        card["does_not_establish"] = dne
        assert _card_errors(card)

    def test_wrong_authority_rejected(self):
        card = _valid_card()
        card["authority"] = "canonical_content"
        assert _card_errors(card)

    def test_wrong_canonicality_rejected(self):
        card = _valid_card()
        card["canonicality"] = "canonical"
        assert _card_errors(card)

    def test_repo_path_pattern_matches_lens_card(self):
        lens_card = json.loads((_CONTRACTS / "lens-card.v1.schema.json").read_text(encoding="utf-8"))
        assert (
            _CARD_SCHEMA["definitions"]["repo_path"]["pattern"]
            == lens_card["definitions"]["repo_path"]["pattern"]
        )
