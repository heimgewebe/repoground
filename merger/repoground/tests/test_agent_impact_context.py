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


def test_related_tests_keep_graph_symbol_and_heuristic_evidence_separate() -> None:
    result = _context()
    observed = {
        (item["path"], item["evidence_type"])
        for item in result["related_tests"]
    }

    assert ("tests/test_app.py", "graph_edge") in observed
    assert ("tests/test_app.py", "symbol_index_path_match") in observed
    assert (
        "merger/repoground/tests/test_app.py",
        "heuristic",
    ) in observed
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
