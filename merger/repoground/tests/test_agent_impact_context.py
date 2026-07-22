from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from merger.repoground.core.agent_impact_context import (
    DOES_NOT_ESTABLISH,
    build_agent_impact_context,
)
from merger.repoground.core.agent_impact_eval import (
    evaluate_agent_impact_goldset,
)

ROOT = Path(__file__).resolve().parents[3]
SCHEMA = (
    ROOT
    / "merger/repoground/contracts/agent-impact-context.v1.schema.json"
)
GOLDSET_SCHEMA = (
    ROOT
    / "merger/repoground/contracts/agent-impact-goldset.v1.schema.json"
)
DIGEST = "a" * 64


def _fixture_documents() -> tuple[dict, dict, dict, list[dict], dict]:
    graph = {
        "kind": "lenskit.architecture.graph",
        "version": "1.0",
        "run_id": "run-1",
        "canonical_dump_index_sha256": DIGEST,
        "nodes": [
            {
                "node_id": "file:src/app.py",
                "kind": "file",
                "path": "src/app.py",
                "repo": "demo",
                "is_test": False,
            },
            {
                "node_id": "file:src/db.py",
                "kind": "file",
                "path": "src/db.py",
                "repo": "demo",
                "is_test": False,
            },
            {
                "node_id": "file:tests/test_app.py",
                "kind": "file",
                "path": "tests/test_app.py",
                "repo": "demo",
                "is_test": True,
            },
            {
                "node_id": "file:docs/app.md",
                "kind": "file",
                "path": "docs/app.md",
                "repo": "demo",
                "is_test": False,
            },
            {
                "node_id": "file:contracts/app.schema.json",
                "kind": "file",
                "path": "contracts/app.schema.json",
                "repo": "demo",
                "is_test": False,
            },
        ],
        "edges": [
            {
                "src": "file:src/app.py",
                "dst": "file:src/db.py",
                "edge_type": "import",
                "evidence_level": "S1",
                "evidence": {
                    "source_path": "src/app.py",
                    "start_line": 1,
                },
            },
            {
                "src": "file:tests/test_app.py",
                "dst": "file:src/app.py",
                "edge_type": "import",
                "evidence_level": "S1",
                "evidence": {
                    "source_path": "tests/test_app.py",
                    "start_line": 1,
                },
            },
            {
                "src": "file:src/app.py",
                "dst": "file:docs/app.md",
                "edge_type": "string-ref",
                "evidence_level": "S0",
                "evidence": {
                    "source_path": "src/app.py",
                    "start_line": 5,
                },
            },
            {
                "src": "file:src/app.py",
                "dst": "file:contracts/app.schema.json",
                "edge_type": "config-link",
                "evidence_level": "S1",
                "evidence": {
                    "source_path": "src/app.py",
                    "start_line": 6,
                },
            },
        ],
        "coverage": {
            "files_seen": 5,
            "files_parsed": 5,
            "edge_counts_by_type": {},
            "unknown_layer_share": 0.0,
        },
    }
    symbols = {
        "kind": "lenskit.python_symbol_index",
        "version": "1.0",
        "run_id": "run-1",
        "canonical_dump_index_sha256": DIGEST,
        "language": "python",
        "symbol_kinds": ["function"],
        "symbols": [
            {
                "id": "sym-app",
                "kind": "function",
                "name": "run_app",
                "qualified_name": "app.run_app",
                "module": "app",
                "path": "src/app.py",
                "start_line": 10,
                "end_line": 20,
                "range_ref": "file:src/app.py#L10-L20",
                "decorators": [],
            },
            {
                "id": "sym-db",
                "kind": "function",
                "name": "load_data",
                "qualified_name": "db.load_data",
                "module": "db",
                "path": "src/db.py",
                "start_line": 2,
                "end_line": 7,
                "range_ref": "file:src/db.py#L2-L7",
                "decorators": [],
            },
            {
                "id": "sym-test",
                "kind": "function",
                "name": "test_run_app",
                "qualified_name": "tests.test_app.test_run_app",
                "module": "tests.test_app",
                "path": "tests/test_app.py",
                "start_line": 1,
                "end_line": 8,
                "range_ref": "file:tests/test_app.py#L1-L8",
                "decorators": [],
            },
        ],
        "skipped_files_count": 0,
        "skipped_errors": [],
        "does_not_establish": [
            "call_graph_completeness",
            "dependency_completeness",
            "runtime_behavior",
            "import_success",
            "test_sufficiency",
            "review_impact",
            "merge_readiness",
        ],
    }
    entrypoints = {
        "kind": "lenskit.entrypoints",
        "version": "1.0",
        "run_id": "run-1",
        "canonical_dump_index_sha256": DIGEST,
        "entrypoints": [
            {
                "id": "web-app",
                "type": "web",
                "path": "src/app.py",
                "symbol": "run_app",
                "evidence_level": "S1",
                "projection": "product",
            }
        ],
    }
    relation_cards = [
        {
            "kind": "lenskit.relation_card",
            "version": "1.0",
            "card_id": "dependency.app-db",
            "card_type": "dependency",
            "navigation_refs": [
                {"kind": "repo_path", "target": "src/app.py"}
            ],
            "does_not_establish": ["runtime_dependency"],
        }
    ]
    query_context = {
        "query": {
            "source_citation_projection": {
                "items": [
                    {
                        "path": "docs/app.md",
                        "citation_id": "citation-1",
                        "range_status": "resolved",
                    }
                ]
            }
        }
    }
    return graph, symbols, entrypoints, relation_cards, query_context



def _fixture_call_graph() -> dict:
    def call(
        *,
        path: str,
        line: int,
        caller_id: str | None,
        caller_name: str | None,
        caller_start: int | None,
        caller_end: int | None,
        callee: str,
        simple_name: str | None,
        evidence: str,
        status: str,
        reason: str,
        resolved: list[str],
        candidates: list[str],
    ) -> dict:
        return {
            "path": path,
            "start_line": line,
            "start_col": 4,
            "end_line": line,
            "end_col": 20,
            "range_ref": f"file:{path}#L{line}-L{line}",
            "callee_expression": callee,
            "simple_name": simple_name,
            "caller_scope": "symbol" if caller_id else "module",
            "caller_symbol_id": caller_id,
            "caller_qualified_name": caller_name,
            "caller_kind": "function" if caller_id else "module",
            "caller_start_line": caller_start,
            "caller_end_line": caller_end,
            "relation_type": "calls",
            "evidence_level": evidence,
            "resolution_status": status,
            "resolution_reason": reason,
            "resolved_target_ids": resolved,
            "candidate_target_ids": candidates,
        }

    calls = [
        call(
            path="tests/test_app.py",
            line=5,
            caller_id="sym-test",
            caller_name="tests.test_app.test_run_app",
            caller_start=1,
            caller_end=8,
            callee="run_app",
            simple_name="run_app",
            evidence="S1",
            status="resolved",
            reason="unique_symbol_resolution",
            resolved=["sym-app"],
            candidates=[],
        ),
        call(
            path="src/worker.py",
            line=30,
            caller_id="sym-worker",
            caller_name="worker.process",
            caller_start=25,
            caller_end=35,
            callee="run_app",
            simple_name="run_app",
            evidence="S1",
            status="resolved",
            reason="unique_symbol_resolution",
            resolved=["sym-app"],
            candidates=[],
        ),
        call(
            path="src/app.py",
            line=14,
            caller_id="sym-app",
            caller_name="app.run_app",
            caller_start=10,
            caller_end=20,
            callee="load_data",
            simple_name="load_data",
            evidence="S1",
            status="resolved",
            reason="unique_symbol_resolution",
            resolved=["sym-db"],
            candidates=[],
        ),
        call(
            path="src/plugin.py",
            line=11,
            caller_id="sym-plugin",
            caller_name="plugin.activate",
            caller_start=8,
            caller_end=15,
            callee="run_app",
            simple_name="run_app",
            evidence="S0",
            status="candidate",
            reason="name_match_not_unique",
            resolved=[],
            candidates=["sym-app"],
        ),
    ]
    return {
        "kind": "lenskit.python_call_graph",
        "version": "1.0",
        "run_id": "run-1",
        "canonical_dump_index_sha256": DIGEST,
        "language": "python",
        "evidence_model": {"S0": "candidate", "S1": "resolved"},
        "resolution_statuses": ["resolved", "candidate", "ambiguous", "unresolved"],
        "relation_types": ["calls", "constructs"],
        "call_count": len(calls),
        "resolution_counts": {"resolved": 3, "candidate": 1, "ambiguous": 0, "unresolved": 0},
        "evidence_counts": {"S0": 1, "S1": 3},
        "relation_counts": {"calls": 4, "constructs": 0},
        "calls": calls,
        "skipped_files_count": 0,
        "skipped_errors": [],
        "skipped_errors_total_count": 0,
        "skipped_errors_truncated": False,
        "does_not_establish": [
            "complete_call_graph",
            "runtime_reachability",
            "dynamic_dispatch_resolution",
            "dependency_completeness",
            "transitive_import_resolution",
            "import_success",
            "test_sufficiency",
            "review_completeness",
            "merge_readiness",
        ],
    }


def _context(**overrides):
    graph, symbols, entrypoints, cards, query = _fixture_documents()
    values = {
        "target_symbol": "run_app",
        "mode": "edit",
        "max_items": 10,
        "architecture_graph": graph,
        "symbol_index": symbols,
        "python_call_graph": _fixture_call_graph(),
        "entrypoints": entrypoints,
        "relation_cards": cards,
        "query_context": query,
    }
    values.update(overrides)
    return build_agent_impact_context(**values)


def _selection_symbol(
    symbol_id: str,
    *,
    path: str,
    name: str,
    line: int,
) -> dict:
    return {
        "id": symbol_id,
        "kind": "function",
        "name": name,
        "qualified_name": f"selection.{name}",
        "module": "selection",
        "path": path,
        "start_line": line,
        "end_line": line + 1,
        "range_ref": f"file:{path}#L{line}-L{line + 1}",
        "decorators": [],
    }


def _selection_context(
    symbol_records: list[dict],
    *,
    changed_paths: list[str],
    max_items: int,
    target_symbol: str | None = None,
) -> dict:
    graph, symbols, entrypoints, cards, query = _fixture_documents()
    symbols["symbols"] = symbol_records
    return build_agent_impact_context(
        target_symbol=target_symbol,
        changed_paths=changed_paths,
        mode="impact",
        max_items=max_items,
        architecture_graph=graph,
        symbol_index=symbols,
        entrypoints=entrypoints,
        relation_cards=cards,
        query_context=query,
    )


def test_agent_impact_context_is_schema_valid_and_deterministic() -> None:
    first = _context()
    second = _context()

    assert first == second
    jsonschema.validate(
        first,
        json.loads(SCHEMA.read_text(encoding="utf-8")),
    )
    assert first["status"] == "available"
    assert first["mutation_boundary"]["writes"] == []
    assert set(DOES_NOT_ESTABLISH) <= set(first["does_not_establish"])


def test_target_symbols_preserve_requested_path_diversity_before_filling() -> None:
    test_path = "scripts/ci/tests/test_kubernetes_platform_contract.py"
    source_path = "scripts/platform/kind_reference.py"
    symbols = [
        _selection_symbol("test-1", path=test_path, name="test_first", line=1),
        _selection_symbol("test-2", path=test_path, name="test_second", line=10),
        _selection_symbol("test-3", path=test_path, name="test_third", line=20),
        _selection_symbol("source-1", path=source_path, name="ProofError", line=1),
        _selection_symbol("source-2", path=source_path, name="run_kind", line=10),
    ]

    result = _selection_context(
        symbols,
        changed_paths=[test_path, source_path],
        max_items=2,
    )

    assert [item["id"] for item in result["target_symbols"]] == [
        "test-1",
        "source-1",
    ]
    assert result["truncation"]["target_symbols"] is True


def test_target_symbols_prioritize_an_exact_symbol_before_path_diversity() -> None:
    test_path = "scripts/ci/tests/test_kubernetes_platform_contract.py"
    source_path = "scripts/platform/kind_reference.py"
    symbols = [
        _selection_symbol("test-1", path=test_path, name="test_first", line=1),
        _selection_symbol("test-2", path=test_path, name="test_second", line=10),
        _selection_symbol("proof-error", path=source_path, name="ProofError", line=1),
    ]

    result = _selection_context(
        symbols,
        changed_paths=[test_path, source_path],
        target_symbol="ProofError",
        max_items=1,
    )

    assert [item["id"] for item in result["target_symbols"]] == ["proof-error"]
    assert result["target"]["paths"] == [test_path, source_path]


def test_target_symbol_path_diversity_is_deterministic_when_paths_exceed_budget() -> None:
    paths = ["src/c.py", "src/a.py", "src/b.py"]
    symbols = [
        _selection_symbol("c", path=paths[0], name="c", line=1),
        _selection_symbol("a", path=paths[1], name="a", line=1),
        _selection_symbol("b", path=paths[2], name="b", line=1),
    ]

    first = _selection_context(
        symbols,
        changed_paths=paths,
        max_items=2,
    )
    second = _selection_context(
        list(reversed(symbols)),
        changed_paths=list(reversed(paths)),
        max_items=2,
    )

    assert [item["id"] for item in first["target_symbols"]] == ["a", "b"]
    assert first == second


def test_target_path_without_symbols_does_not_consume_diversity_budget() -> None:
    paths = ["src/a.py", "src/empty.py", "src/z.py"]
    symbols = [
        _selection_symbol("a-1", path=paths[0], name="a_first", line=1),
        _selection_symbol("a-2", path=paths[0], name="a_second", line=10),
        _selection_symbol("z-1", path=paths[2], name="z_first", line=1),
    ]

    result = _selection_context(
        symbols,
        changed_paths=paths,
        max_items=2,
    )

    assert [item["id"] for item in result["target_symbols"]] == ["a-1", "z-1"]


def test_agent_impact_context_preserves_relation_direction_and_evidence() -> None:
    result = _context()
    relation_keys = {
        (
            item["direction"],
            item["peer"]["path"],
            item["edge_type"],
            item["evidence_level"],
        )
        for item in result["relations"]
    }

    assert ("incoming", "tests/test_app.py", "import", "S1") in relation_keys
    assert ("outgoing", "src/db.py", "import", "S1") in relation_keys
    assert (
        "outgoing",
        "contracts/app.schema.json",
        "config-link",
        "S1",
    ) in relation_keys
    assert all(
        item["authority"] == "derived_graph_evidence"
        for item in result["relations"]
    )


def test_related_tests_require_graph_or_symbol_index_evidence() -> None:
    result = _context()
    observed = {
        (item["path"], item["evidence_type"])
        for item in result["related_tests"]
    }

    assert ("tests/test_app.py", "graph_edge") in observed
    assert ("tests/test_app.py", "symbol_index_path_match") in observed
    assert all(
        item["evidence_type"] in {"graph_edge", "symbol_index_path_match"}
        for item in result["related_tests"]
    )
    assert not any(item["evidence_type"] == "heuristic" for item in result["related_tests"])
    assert "test_sufficiency" in result["does_not_establish"]
    assert "test_coverage" in result["does_not_establish"]


def test_edit_context_bundles_target_support_and_entrypoint_reads() -> None:
    result = _context()
    support = {
        (item["path"], item["path_class"], item["evidence_type"])
        for item in result["supporting_context"]
    }
    reads = {
        (item["path"], item["reason"])
        for item in result["edit_context"]["recommended_first_reads"]
    }

    assert (
        "contracts/app.schema.json",
        "contract",
        "graph_edge",
    ) in support
    assert ("docs/app.md", "documentation", "resolved_query") in support
    assert result["entrypoints"][0]["path"] == "src/app.py"
    assert ("src/app.py", "target_symbol") in reads
    assert ("tests/test_app.py", "incoming_graph_relation") in reads
    assert result["composition"]["does_not_parse_or_apply_diff"] is True



def test_impact_context_projects_coherent_call_graph_relations_without_edit_semantics() -> None:
    result = _context(mode="impact")

    call_relations = [
        item
        for item in result["relations"]
        if isinstance(item.get("freshness"), dict)
        and item["freshness"].get("source") == "python_call_graph_json"
    ]

    assert "edit_context" not in result
    assert {item["relation_kind"] for item in call_relations} == {
        "direct_caller",
        "direct_callee",
    }
    assert all(item["freshness"]["status"] == "coherent" for item in call_relations)
    assert all(
        item["provenance"]["relation"]["source"] == "python_call_graph_json"
        for item in call_relations
    )


def test_impact_context_preserves_source_diversity_when_relations_are_bounded() -> None:
    result = _context(mode="impact", max_items=2)

    call_relations = [
        item
        for item in result["relations"]
        if isinstance(item.get("freshness"), dict)
        and item["freshness"].get("source") == "python_call_graph_json"
    ]
    architecture_relations = [
        item for item in result["relations"] if item not in call_relations
    ]

    assert len(result["relations"]) == 2
    assert len(architecture_relations) == 1
    assert len(call_relations) == 1
    assert result["relations"][0] == call_relations[0]
    assert call_relations[0]["freshness"]["status"] == "coherent"
    assert result["truncation"]["relations"] is True


def test_impact_context_keeps_single_relation_budget_backward_compatible() -> None:
    result = _context(mode="impact", max_items=1)

    assert len(result["relations"]) == 1
    assert not (
        isinstance(result["relations"][0].get("freshness"), dict)
        and result["relations"][0]["freshness"].get("source")
        == "python_call_graph_json"
    )
    assert result["truncation"]["relations"] is True



def test_impact_context_does_not_project_untrusted_call_graph_relations() -> None:
    call_graph = _fixture_call_graph()
    call_graph["run_id"] = "other-run"

    result = _context(mode="impact", python_call_graph=call_graph)

    assert result["status"] == "available"
    assert "edit_context" not in result
    assert not any(
        isinstance(item.get("freshness"), dict)
        and item["freshness"].get("source") == "python_call_graph_json"
        for item in result["relations"]
    )


def test_impact_context_keeps_optional_missing_call_graph_non_degrading() -> None:
    result = _context(mode="impact", python_call_graph=None)

    assert result["status"] == "available"
    assert "edit_context" not in result
    assert not any(
        isinstance(item.get("freshness"), dict)
        and item["freshness"].get("source") == "python_call_graph_json"
        for item in result["relations"]
    )


def test_edit_context_separately_budgets_proven_call_graph_relations() -> None:
    result = _context(max_items=1)
    selection = result["edit_context"]["selection"]
    assert set(selection) == {
        "target_definitions",
        "direct_callers",
        "direct_callees",
        "entrypoints",
        "tests",
        "contracts",
        "unresolved_risk_boundaries",
    }
    assert all(section["budget"] == 1 for section in selection.values())
    assert all(len(section["selected"]) <= 1 for section in selection.values())
    caller = selection["direct_callers"]["selected"][0]
    callee = selection["direct_callees"]["selected"][0]
    assert caller["relation_kind"] == "direct_caller"
    assert callee["relation_kind"] == "direct_callee"
    assert caller["evidence_level"] == callee["evidence_level"] == "S1"
    assert caller["resolution_status"] == callee["resolution_status"] == "resolved"
    assert caller["freshness"]["status"] == "coherent"
    assert callee["freshness"]["status"] == "coherent"
    assert caller["source_ranges"]["call_site"].startswith("file:")
    assert caller["source_ranges"]["peer_definition"].startswith("file:")
    assert callee["source_ranges"]["call_site"].startswith("file:")
    assert callee["source_ranges"]["peer_definition"] == "file:src/db.py#L2-L7"
    assert caller["omission_reason"] is None
    assert callee["omission_reason"] is None
    assert selection["direct_callers"]["omitted_count"] == 1
    assert selection["direct_callers"]["omission_reasons"] == {
        "section_budget_exceeded": 1
    }
    assert "omitted" not in selection["direct_callers"]
    risk = selection["unresolved_risk_boundaries"]["selected"][0]
    assert risk["evidence_level"] == "S0"
    assert risk["omission_reason"] == "not_s1_resolved_unique_relation"
    assert selection["entrypoints"]["selected"][0]["path"] == "src/app.py"
    assert selection["tests"]["selected"][0]["path"] == "tests/test_app.py"
    assert selection["contracts"]["selected"][0]["path"] == "contracts/app.schema.json"
    assert set(result["edit_context"]["nonverdicts"]) == {
        "complete_blast_radius",
        "runtime_breakage",
        "test_sufficiency",
        "merge_readiness",
    }
    assert "complete_blast_radius" in result["does_not_establish"]
    assert "test_sufficiency" in result["does_not_establish"]
    assert "merge_readiness" in result["does_not_establish"]



def test_call_relations_aggregate_callsites_before_section_budgeting() -> None:
    call_graph = _fixture_call_graph()
    duplicate = dict(call_graph["calls"][0])
    duplicate.update(
        {
            "start_line": 7,
            "end_line": 7,
            "range_ref": "file:tests/test_app.py#L7-L7",
        }
    )
    call_graph["calls"].append(duplicate)

    result = _context(max_items=2, python_call_graph=call_graph)
    section = result["edit_context"]["selection"]["direct_callers"]

    assert result["edit_context"]["direct_caller_count"] == 2
    assert section["omitted_count"] == 0
    by_symbol = {item["symbol_id"]: item for item in section["selected"]}
    assert set(by_symbol) == {"sym-test", "sym-worker"}
    assert by_symbol["sym-test"]["source_ranges"]["call_sites"] == [
        "file:tests/test_app.py#L5-L5",
        "file:tests/test_app.py#L7-L7",
    ]


def test_call_graph_discovery_uses_all_targets_before_target_budgeting() -> None:
    graph, symbols, entrypoints, cards, query = _fixture_documents()
    symbols["symbols"].extend(
        [
            {
                "id": "sym-app-helper",
                "kind": "function",
                "name": "helper",
                "qualified_name": "app.helper",
                "module": "app",
                "path": "src/app.py",
                "start_line": 30,
                "end_line": 35,
                "range_ref": "file:src/app.py#L30-L35",
                "decorators": [],
            },
            {
                "id": "sym-late",
                "kind": "function",
                "name": "late_target",
                "qualified_name": "late.late_target",
                "module": "late",
                "path": "src/late.py",
                "start_line": 1,
                "end_line": 4,
                "range_ref": "file:src/late.py#L1-L4",
                "decorators": [],
            },
        ]
    )
    call_graph = _fixture_call_graph()
    late_call = dict(call_graph["calls"][2])
    late_call.update(
        {
            "path": "src/app.py",
            "start_line": 32,
            "end_line": 32,
            "range_ref": "file:src/app.py#L32-L32",
            "caller_symbol_id": "sym-app-helper",
            "caller_qualified_name": "app.helper",
            "caller_start_line": 30,
            "caller_end_line": 35,
            "callee_expression": "late_target",
            "simple_name": "late_target",
            "resolved_target_ids": ["sym-late"],
        }
    )
    call_graph["calls"].append(late_call)

    result = build_agent_impact_context(
        target_path="src/app.py",
        mode="edit",
        max_items=1,
        architecture_graph=graph,
        symbol_index=symbols,
        python_call_graph=call_graph,
        entrypoints=entrypoints,
        relation_cards=cards,
        query_context=query,
    )

    assert len(result["target_symbols"]) == 1
    assert result["truncation"]["target_symbols"] is True
    assert result["edit_context"]["direct_callee_count"] == 2
    assert result["edit_context"]["selection"]["direct_callees"]["omitted_count"] == 1


def test_missing_optional_call_graph_degrades_edit_context_without_blocking() -> None:
    result = _context(python_call_graph=None)

    assert result["status"] == "partial"
    assert result["edit_context"]["direct_caller_count"] == 0
    assert result["edit_context"]["direct_callee_count"] == 0
    assert result["edit_context"]["call_graph_coverage_gaps"][0]["kind"] == (
        "call_graph_source_unavailable"
    )
    assert result["provenance"]["status"] == "coherent"


def test_mismatched_optional_call_graph_is_not_used_as_trusted_evidence() -> None:
    call_graph = _fixture_call_graph()
    call_graph["run_id"] = "other-run"

    result = _context(python_call_graph=call_graph)

    assert result["status"] == "partial"
    assert result["provenance"]["status"] == "coherent"
    assert result["edit_context"]["direct_caller_count"] == 0
    gap = result["edit_context"]["call_graph_coverage_gaps"][0]
    assert gap["kind"] == "call_graph_source_untrusted"
    assert gap["freshness"]["status"] == "stale_or_mismatched"


def test_unresolved_target_callee_stays_a_risk_boundary() -> None:
    call_graph = _fixture_call_graph()
    candidate = dict(call_graph["calls"][2])
    candidate.update(
        {
            "start_line": 18,
            "end_line": 18,
            "range_ref": "file:src/app.py#L18-L18",
            "callee_expression": "dynamic_peer",
            "simple_name": "dynamic_peer",
            "evidence_level": "S0",
            "resolution_status": "candidate",
            "resolution_reason": "name_match_not_unique",
            "resolved_target_ids": [],
            "candidate_target_ids": ["sym-dynamic"],
        }
    )
    call_graph["calls"].append(candidate)

    result = _context(python_call_graph=call_graph)
    risks = result["edit_context"]["selection"]["unresolved_risk_boundaries"][
        "selected"
    ]

    assert any(
        item["relevance_basis"] == "target_caller_symbol_id"
        and item["uncertainty_reason"] == "not_s1_resolved_unique_relation"
        for item in risks
    )
    assert all(
        item.get("symbol_id") != "sym-dynamic"
        for item in result["edit_context"]["selection"]["direct_callees"]["selected"]
    )


def test_structured_risk_evidence_outranks_simple_name_fallback() -> None:
    call_graph = _fixture_call_graph()
    simple_only = dict(call_graph["calls"][3])
    simple_only.update(
        {
            "path": "aaa_simple.py",
            "caller_symbol_id": "sym-unrelated",
            "caller_qualified_name": "unrelated.run",
            "candidate_target_ids": [],
        }
    )
    call_graph["calls"].insert(0, simple_only)

    result = _context(max_items=1, python_call_graph=call_graph)
    risk = result["edit_context"]["selection"]["unresolved_risk_boundaries"][
        "selected"
    ][0]

    assert risk["relevance_basis"] == "candidate_target_id"
    assert risk["risk_priority"] == 1


def test_module_level_direct_caller_keeps_stable_scope_identity() -> None:
    call_graph = _fixture_call_graph()
    module_call = dict(call_graph["calls"][0])
    module_call.update(
        {
            "path": "src/bootstrap.py",
            "range_ref": "file:src/bootstrap.py#L4-L4",
            "caller_scope": "module",
            "caller_symbol_id": None,
            "caller_qualified_name": None,
            "caller_kind": "module",
            "caller_start_line": None,
            "caller_end_line": None,
        }
    )
    call_graph["calls"].append(module_call)

    result = _context(python_call_graph=call_graph)
    callers = result["edit_context"]["selection"]["direct_callers"]["selected"]

    assert any(
        item["path"] == "src/bootstrap.py" and item["symbol_id"] is None
        for item in callers
    )


def test_parse_coverage_gap_does_not_consume_relation_risk_budget() -> None:
    call_graph = _fixture_call_graph()
    call_graph["skipped_files_count"] = 3
    call_graph["skipped_errors_total_count"] = 2

    result = _context(max_items=1, python_call_graph=call_graph)

    risk_section = result["edit_context"]["selection"]["unresolved_risk_boundaries"]
    assert len(risk_section["selected"]) == 1
    assert risk_section["selected"][0]["kind"] == "unresolved_call_relation"
    coverage_gaps = result["edit_context"]["call_graph_coverage_gaps"]
    assert len(coverage_gaps) == 1
    gap = coverage_gaps[0]
    assert gap["kind"] == "call_graph_parse_coverage_gap"
    assert gap["skipped_files_count"] == 3
    assert gap["skipped_errors_total_count"] == 2
    assert gap["coverage_reason"] == "call_graph_parse_coverage_incomplete"
    assert gap["freshness"]["source"] == "python_call_graph_json"
    assert gap["freshness"]["status"] == "coherent"


def test_constructs_relation_is_preserved_as_direct_callee() -> None:
    graph, symbols, entrypoints, cards, query = _fixture_documents()
    symbols["symbols"].append(
        {
            "id": "sym-widget",
            "kind": "class",
            "name": "Widget",
            "qualified_name": "widget.Widget",
            "module": "widget",
            "path": "src/widget.py",
            "start_line": 1,
            "end_line": 8,
            "range_ref": "file:src/widget.py#L1-L8",
            "decorators": [],
        }
    )
    call_graph = _fixture_call_graph()
    construct = dict(call_graph["calls"][2])
    construct.update(
        {
            "start_line": 16,
            "end_line": 16,
            "range_ref": "file:src/app.py#L16-L16",
            "callee_expression": "Widget",
            "simple_name": "Widget",
            "relation_type": "constructs",
            "resolved_target_ids": ["sym-widget"],
        }
    )
    call_graph["calls"].append(construct)

    result = build_agent_impact_context(
        target_symbol="run_app",
        mode="edit",
        max_items=10,
        architecture_graph=graph,
        symbol_index=symbols,
        python_call_graph=call_graph,
        entrypoints=entrypoints,
        relation_cards=cards,
        query_context=query,
    )
    callees = result["edit_context"]["selection"]["direct_callees"]["selected"]
    widget = next(item for item in callees if item["symbol_id"] == "sym-widget")

    assert widget["relation_type"] == "constructs"
    assert widget["relation_types"] == ["constructs"]


def test_callee_provenance_retains_relation_and_symbol_sources() -> None:
    result = _context()
    callee = result["edit_context"]["selection"]["direct_callees"]["selected"][0]

    assert callee["provenance"]["relation"]["source"] == "python_call_graph_json"
    assert callee["provenance"]["relation"]["status"] == "coherent"
    assert callee["provenance"]["peer_definition"]["source"] == (
        "python_symbol_index_json"
    )
    assert callee["provenance"]["peer_definition"]["status"] == "coherent"

def test_mismatched_bundle_identities_block_impact_projection() -> None:
    graph, symbols, entrypoints, cards, query = _fixture_documents()
    symbols["run_id"] = "other-run"

    result = build_agent_impact_context(
        target_path="src/app.py",
        architecture_graph=graph,
        symbol_index=symbols,
        entrypoints=entrypoints,
        relation_cards=cards,
        query_context=query,
    )

    assert result["status"] == "blocked"
    assert result["relations"] == []
    assert any(
        gap.get("reason") == "run_id_or_canonical_digest_mismatch"
        for gap in result["gaps"]
    )


@pytest.mark.parametrize(
    ("kwargs", "error_fragment"),
    [
        ({"target_path": "../escape.py"}, "canonical repository-relative"),
        ({"target_path": "src/app.py", "mode": "review"}, "mode must be"),
        ({"target_path": "src/app.py", "max_items": True}, "must be an integer"),
        ({}, "at least one of"),
    ],
)
def test_invalid_requests_fail_closed(kwargs, error_fragment) -> None:
    result = build_agent_impact_context(**kwargs)

    assert result["status"] == "invalid"
    assert result["error_code"] == "agent_impact_request_invalid"
    assert error_fragment in result["error"]
    assert result["relations"] == []


def test_missing_target_is_explicit_not_inferred_as_current() -> None:
    graph, symbols, entrypoints, cards, query = _fixture_documents()

    result = build_agent_impact_context(
        target_path="src/missing.py",
        architecture_graph=graph,
        symbol_index=symbols,
        entrypoints=entrypoints,
        relation_cards=cards,
        query_context=query,
    )

    assert result["status"] == "missing_target"
    assert result["relations"] == []
    assert any(
        gap.get("reason") == "target_path_not_present_as_graph_node"
        for gap in result["gaps"]
    )


def test_fixed_goldset_eval_requires_threshold_and_no_case_regression() -> None:
    context = _context()
    goldset = json.loads(
        (
            ROOT
            / "docs/retrieval/repobrief_agent_impact_goldset.v1.json"
        ).read_text(encoding="utf-8")
    )
    jsonschema.validate(
        goldset,
        json.loads(GOLDSET_SCHEMA.read_text(encoding="utf-8")),
    )
    report = evaluate_agent_impact_goldset(
        goldset,
        {
            "app-structural-impact": {
                "baseline_paths": ["src/db.py"],
                "impact_context": context,
            },
            "app-edit-reading-set": {
                "baseline_paths": ["src/app.py"],
                "impact_context": context,
            },
        },
    )

    assert report["metrics"]["baseline_target_recall"] == pytest.approx(
        0.2916666667
    )
    assert report["metrics"]["impact_target_recall"] == 1.0
    assert report["metrics"]["target_recall_advantage"] == pytest.approx(
        0.7083333333
    )
    assert report["metrics"]["no_case_regression"] is True
    assert (
        report["decision"]["navigation_utility_established_for_goldset"]
        is True
    )
    assert report["decision"]["default_promoted"] is False
    committed = json.loads(
        (
            ROOT
            / "docs/diagnostics/"
            "repobrief-agent-impact-context-fixture-eval-v1.json"
        ).read_text(encoding="utf-8")
    )
    assert committed["metrics"] == report["metrics"]
    assert committed["decision"] == report["decision"]
    assert committed["measurement_scope"] == "synthetic_contract_fixture"
    assert "default_promotion" in report["does_not_establish"]
