from __future__ import annotations

from pathlib import Path

import pytest

from merger.repoground.core.agent_impact_eval import (
    evaluate_agent_impact_goldset,
)
from merger.repoground.core.agent_impact_refinement import (
    refine_agent_impact_context,
    resolved_query_test_candidates,
)
from merger.repoground.tests.test_agent_impact_adapter import (
    _impact_adapter,
)


def _query_context(*items: dict) -> dict:
    return {
        "query": {
            "source_citation_projection": {
                "items": list(items),
            }
        }
    }


def test_resolved_query_candidates_keep_navigation_authority() -> None:
    candidates = resolved_query_test_candidates(
        _query_context(
            {
                "path": "tests/test_job_finalizer.py",
                "citation_id": "citation-test",
                "source_range": {"start_line": 1, "end_line": 20},
                "range_status": "resolved",
            },
            {"path": "docs/finalizer.md", "citation_id": "citation-doc"},
            {"path": "", "citation_id": "citation-empty"},
            {"path": "../escape.py", "citation_id": "citation-escape"},
        )
    )

    assert candidates == [
        {
            "path": "tests/test_job_finalizer.py",
            "evidence_type": "resolved_query",
            "reason": "test_like_path_from_resolved_query_projection",
            "citation_id": "citation-test",
            "source_range": {"start_line": 1, "end_line": 20},
            "range_status": "resolved",
            "authority": "resolved_navigation_evidence",
            "canonicality": "derived",
        }
    ]


def test_resolved_query_candidates_recognize_cross_language_test_names() -> None:
    candidates = resolved_query_test_candidates(
        _query_context(
            {
                "path": "apps/web/src/lib/map/nodes.test.ts",
                "citation_id": "citation-ts-test",
                "range_status": "resolved",
            },
            {
                "path": "apps/web/src/lib/map/nodes.ts",
                "citation_id": "citation-ts-source",
            },
        )
    )

    assert [item["path"] for item in candidates] == [
        "apps/web/src/lib/map/nodes.test.ts"
    ]


def test_refinement_prioritizes_changed_test_path_evidence() -> None:
    base = {
        "status": "available",
        "related_tests": [
            {
                "path": "apps/web/src/lib/map/nodes.test.ts",
                "evidence_type": "changed_test_path",
                "reason": "changed_path_is_test",
            },
            {
                "path": "tests/test_graph.py",
                "evidence_type": "graph_edge",
            },
        ],
        "truncation": {"related_tests": False},
        "composition": {},
        "edit_context": {
            "recommended_first_reads": [
                {
                    "path": "src/target.py",
                    "range_ref": None,
                    "qualified_name": None,
                    "reason": "target_path",
                },
                {
                    "path": "apps/web/src/lib/map/nodes.test.ts",
                    "range_ref": None,
                    "qualified_name": None,
                    "reason": "related_test:changed_test_path",
                },
            ],
            "related_test_count": 2,
        },
    }

    refined = refine_agent_impact_context(base, _query_context(), max_items=20)

    assert [item["evidence_type"] for item in refined["related_tests"]] == [
        "changed_test_path",
        "graph_edge",
    ]
    assert [
        item["reason"]
        for item in refined["edit_context"]["recommended_first_reads"]
    ] == [
        "target_path",
        "related_test:changed_test_path",
    ]


def test_refinement_keeps_strong_evidence_and_suppresses_guesses() -> None:
    base = {
        "status": "available",
        "related_tests": [
            {
                "path": "tests/test_graph.py",
                "evidence_type": "graph_edge",
            },
            {
                "path": "tests/test_symbol.py",
                "evidence_type": "symbol_index_path_match",
            },
            {
                "path": "tests/test_guess.py",
                "evidence_type": "heuristic",
            },
        ],
        "truncation": {"related_tests": False},
        "composition": {},
        "edit_context": {
            "recommended_first_reads": [
                {
                    "path": "src/finalizer.py",
                    "range_ref": None,
                    "qualified_name": None,
                    "reason": "target_path",
                },
                {
                    "path": "tests/test_guess.py",
                    "range_ref": None,
                    "qualified_name": None,
                    "reason": "related_test:heuristic",
                },
            ],
            "related_test_count": 3,
        },
    }
    refined = refine_agent_impact_context(
        base,
        _query_context(
            {
                "path": "tests/test_job_finalizer.py",
                "citation_id": "citation-test",
                "range_status": "resolved",
            }
        ),
        max_items=20,
    )

    assert [
        item["evidence_type"] for item in refined["related_tests"]
    ] == [
        "graph_edge",
        "symbol_index_path_match",
        "resolved_query",
    ]
    resolved = refined["related_tests"][2]
    assert resolved["path"] == "tests/test_job_finalizer.py"
    assert resolved["citation_id"] == "citation-test"
    assert resolved.get("edge_type") is None
    assert refined["composition"]["heuristic_test_candidates_suppressed"] == 1
    assert (
        refined["composition"][
            "heuristics_suppressed_only_with_resolved_query_tests"
        ]
        is False
    )
    assert refined["composition"]["heuristic_test_candidates_always_suppressed"] is True
    assert refined["composition"]["resolved_query_tests_are_graph_edges"] is False
    assert refined["composition"]["resolved_query_tests_establish_coverage"] is False
    reads = refined["edit_context"]["recommended_first_reads"]
    assert [item["reason"] for item in reads] == [
        "target_path",
        "related_test:resolved_query",
    ]


def test_refinement_suppresses_heuristics_without_resolved_test() -> None:
    base = {
        "status": "available",
        "related_tests": [
            {
                "path": "tests/test_guess.py",
                "evidence_type": "heuristic",
            }
        ],
        "truncation": {"related_tests": False},
        "composition": {},
        "edit_context": {
            "recommended_first_reads": [
                {
                    "path": "tests/test_guess.py",
                    "range_ref": None,
                    "qualified_name": None,
                    "reason": "related_test:heuristic",
                }
            ]
        },
    }

    refined = refine_agent_impact_context(
        base,
        _query_context(),
        max_items=20,
    )

    assert refined["related_tests"] == []
    assert refined["composition"]["heuristic_test_candidates_suppressed"] == 1
    assert refined["composition"]["heuristic_test_candidates_always_suppressed"] is True
    assert refined["edit_context"]["recommended_first_reads"] == []


def test_adapter_emits_resolved_query_test_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, _bundle, _config = _impact_adapter(tmp_path)

    monkeypatch.setattr(
        adapter,
        "query_existing_index",
        lambda *args, **kwargs: {
            "status": "available",
            "query": {
                "source_citation_projection": {
                    "items": [
                        {
                            "path": "tests/test_demo.py",
                            "citation_id": "resolved-test",
                            "range_status": "resolved",
                        }
                    ]
                }
            },
        },
    )

    result = adapter.agent_impact_context(
        "demo",
        target_path="src/demo.py",
        mode="edit",
        include_query_context=True,
    )

    matches = [
        item
        for item in result["related_tests"]
        if item["path"] == "tests/test_demo.py"
    ]
    assert {item["evidence_type"] for item in matches} == {
        "graph_edge",
        "symbol_index_path_match",
        "resolved_query",
    }
    resolved = next(
        item for item in matches if item["evidence_type"] == "resolved_query"
    )
    assert resolved["citation_id"] == "resolved-test"
    assert result["composition"]["heuristic_test_candidates_suppressed"] == 0
    assert result["composition"]["heuristic_test_candidates_always_suppressed"] is True
    assert result["mutation_boundary"]["writes"] == []


def _goldset() -> dict:
    return {
        "id": "compression-test",
        "minimum_target_recall_advantage": 0.2,
        "minimum_context_path_reduction_at_equal_or_better_recall": 0.2,
        "cases": [
            {
                "id": "case-1",
                "expected_paths": ["tests/test_target.py"],
            }
        ],
    }


def test_compression_establishes_utility_only_at_equal_or_better_recall() -> None:
    report = evaluate_agent_impact_goldset(
        _goldset(),
        {
            "case-1": {
                "baseline_paths": [
                    "src/target.py",
                    "tests/test_target.py",
                    "docs/target.md",
                    "contracts/target.schema.json",
                    "src/helper.py",
                ],
                "impact_context": {
                    "target": {"paths": ["src/target.py"]},
                    "related_tests": [
                        {
                            "path": "tests/test_target.py",
                            "evidence_type": "resolved_query",
                        }
                    ],
                    "entrypoints": [{"path": ""}],
                    "relations": [],
                    "gaps": [],
                    "source_statuses": [],
                },
            }
        },
    )

    case = report["cases"][0]
    assert case["impact_paths"] == [
        "src/target.py",
        "tests/test_target.py",
    ]
    assert case["context_path_reduction_ratio"] == pytest.approx(0.6)
    assert report["metrics"]["context_path_reduction_ratio"] == pytest.approx(
        0.6
    )
    assert report["metrics"]["no_case_regression"] is True
    assert (
        report["decision"]["navigation_utility_established_for_goldset"]
        is True
    )
    assert report["decision"]["reason"] == (
        "fixed_goldset_compression_threshold_met_at_equal_or_better_recall"
    )
    assert report["decision"]["default_promoted"] is False


def test_compression_cannot_mask_recall_regression() -> None:
    report = evaluate_agent_impact_goldset(
        _goldset(),
        {
            "case-1": {
                "baseline_paths": [
                    "src/target.py",
                    "tests/test_target.py",
                    "docs/target.md",
                    "src/helper.py",
                ],
                "impact_context": {
                    "target": {"paths": ["src/target.py"]},
                    "related_tests": [],
                    "relations": [],
                    "gaps": [],
                    "source_statuses": [],
                },
            }
        },
    )

    assert report["metrics"]["context_path_reduction_ratio"] == 0.75
    assert report["metrics"]["no_case_regression"] is False
    assert (
        report["decision"]["navigation_utility_established_for_goldset"]
        is False
    )
    assert report["decision"]["default_promoted"] is False
