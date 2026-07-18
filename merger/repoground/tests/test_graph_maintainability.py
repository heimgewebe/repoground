from __future__ import annotations

import json
from pathlib import Path

from merger.repoground.architecture.graph_maintainability import (
    evaluate_graph_policy,
    measure_graph_maintainability,
)
from scripts.ci.check_graph_maintainability import (
    ComplexityFinding,
    compare_complexity_baseline,
)

ROOT = Path(__file__).resolve().parents[3]
POLICY = ROOT / "config/repoground-graph-maintainability.v1.json"


def _policy() -> dict:
    return json.loads(POLICY.read_text(encoding="utf-8"))


def test_real_repository_graph_noise_policy_passes() -> None:
    measurement = measure_graph_maintainability(ROOT)

    assert evaluate_graph_policy(measurement, _policy()) == []
    assert measurement["graph"]["file_unknown_layer_share"] == 0.0
    assert measurement["graph"]["projections"]["product"]["unknown_layer_share"] == 0.0
    assert measurement["entrypoints"]["projection_sum"] == measurement["entrypoints"]["total"]
    assert set(measurement["entrypoints"]["counts_by_projection"]) == {
        "product",
        "test",
        "fixture",
        "script",
    }


def test_graph_policy_rejects_product_unknown_noise() -> None:
    measurement = measure_graph_maintainability(ROOT)
    measurement["graph"]["projections"]["product"]["unknown_layer_share"] = 0.5

    assert [item["code"] for item in evaluate_graph_policy(measurement, _policy())] == [
        "graph_product_unknown_layer_share_maximum_violated"
    ]


def test_complexity_baseline_allows_resolved_debt() -> None:
    baseline = {
        "kind": "repoground.c901_baseline",
        "version": "1.0",
        "finding_count": 2,
        "max_complexity": 14,
        "findings": [
            {"path": "a.py", "qualified_name": "old", "max_complexity": 12},
            {"path": "b.py", "qualified_name": "kept", "max_complexity": 14},
        ]
    }
    current = [ComplexityFinding("b.py", "kept", 13, 10)]

    assert compare_complexity_baseline(current, baseline) == []


def test_complexity_baseline_rejects_new_or_worse_debt() -> None:
    baseline = {
        "kind": "repoground.c901_baseline",
        "version": "1.0",
        "finding_count": 1,
        "max_complexity": 14,
        "findings": [
            {"path": "b.py", "qualified_name": "kept", "max_complexity": 14}
        ],
    }
    current = [
        ComplexityFinding("b.py", "kept", 15, 10),
        ComplexityFinding("c.py", "new", 11, 10),
    ]

    assert [item["code"] for item in compare_complexity_baseline(current, baseline)] == [
        "complexity_regression",
        "new_complexity_violation",
    ]


def test_complexity_baseline_rejects_structural_drift() -> None:
    baseline = {
        "kind": "wrong",
        "version": "1.0",
        "finding_count": 2,
        "max_complexity": 99,
        "findings": [
            {"path": "b.py", "qualified_name": "z", "max_complexity": 12},
            {"path": "a.py", "qualified_name": "a", "max_complexity": 11},
        ],
    }

    assert [
        item["code"] for item in compare_complexity_baseline([], baseline)
    ] == [
        "complexity_baseline_identity_invalid",
        "complexity_baseline_maximum_mismatch",
        "complexity_baseline_not_sorted",
    ]


def test_lint_workflow_runs_graph_maintainability_ratchet() -> None:
    workflow = (ROOT / ".github/workflows/lint.yml").read_text(encoding="utf-8")
    assert "scripts/ci/check_graph_maintainability.py" in workflow
