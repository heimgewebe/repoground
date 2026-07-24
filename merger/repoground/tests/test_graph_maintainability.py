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
    evaluate_complexity_budget,
    measure_complexity_budget,
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


def _budget_scan(complexities: list[int]) -> list[ComplexityFinding]:
    return [
        ComplexityFinding("a.py", f"f{index}", complexity, 10)
        for index, complexity in enumerate(complexities)
    ]


def _budget(**overrides) -> dict:
    budget = {
        "historical_reference": {"finding_count": 213, "max_complexity": 170},
        "slice_start_reference": {
            "finding_count": 200,
            "max_complexity": 170,
            "excess_total": 2654,
        },
        "finding_count_max": 10,
        "max_complexity_max": 50,
        "excess_total_max": 100,
    }
    budget.update(overrides)
    return budget


def test_complexity_budget_accepts_a_scan_inside_every_dimension() -> None:
    assert evaluate_complexity_budget(_budget_scan([40, 30]), _budget()) == []


def test_complexity_budget_rejects_each_exceeded_dimension() -> None:
    findings = evaluate_complexity_budget(
        _budget_scan([60] * 11),
        _budget(),
    )

    assert sorted({item["dimension"] for item in findings}) == [
        "excess_total",
        "finding_count",
        "max_complexity",
    ]
    assert {item["code"] for item in findings} == {"complexity_budget_exceeded"}


def test_complexity_budget_rewards_splitting_a_function() -> None:
    """Splitting one hotspot raises the count but must lower the excess mass."""

    before = measure_complexity_budget(_budget_scan([48]))
    after = measure_complexity_budget(_budget_scan([16, 14, 12]))

    assert after["finding_count"] > before["finding_count"]
    assert after["max_complexity"] < before["max_complexity"]
    assert after["excess_total"] < before["excess_total"]


def test_complexity_budget_rejects_ceilings_above_any_recorded_reference() -> None:
    findings = evaluate_complexity_budget(
        _budget_scan([12]),
        _budget(finding_count_max=214, max_complexity_max=171),
    )

    assert {item["code"] for item in findings} == {
        "complexity_budget_raised_above_reference"
    }
    # 214 exceeds both recorded finding counts, 171 exceeds both maxima.
    assert sorted((item["dimension"], item["reference"]) for item in findings) == [
        ("finding_count", "historical_reference"),
        ("finding_count", "slice_start_reference"),
        ("max_complexity", "historical_reference"),
        ("max_complexity", "slice_start_reference"),
    ]


def test_complexity_budget_rejects_a_raised_excess_ceiling() -> None:
    """Excess mass is the dimension a rewritten baseline cannot fake away."""

    findings = evaluate_complexity_budget(
        _budget_scan([12]),
        _budget(excess_total_max=2655),
    )

    assert [(item["code"], item["dimension"]) for item in findings] == [
        ("complexity_budget_raised_above_reference", "excess_total")
    ]


def test_complexity_budget_rejects_an_unbounded_dimension() -> None:
    """A ceiling no recorded scan bounds could be raised without limit."""

    budget = _budget()
    del budget["slice_start_reference"]

    assert [
        (item["code"], item["dimension"])
        for item in evaluate_complexity_budget(_budget_scan([12]), budget)
    ] == [("complexity_budget_reference_missing", "excess_total")]


def test_complexity_budget_is_fail_closed_when_absent_or_malformed() -> None:
    assert [item["code"] for item in evaluate_complexity_budget([], None)] == [
        "complexity_budget_missing"
    ]
    assert [
        item["code"] for item in evaluate_complexity_budget([], {"finding_count_max": 1})
    ] == ["complexity_budget_reference_missing"]
    assert [
        item["code"]
        for item in evaluate_complexity_budget(
            [], _budget(max_complexity_max="none")
        )
    ] == ["complexity_budget_invalid"]


def test_repository_complexity_budget_binds_the_recorded_baseline() -> None:
    budget = _policy()["complexity"]["budget"]
    reference = budget["historical_reference"]
    slice_start = budget["slice_start_reference"]
    baseline = json.loads(
        (ROOT / _policy()["complexity"]["baseline_path"]).read_text(encoding="utf-8")
    )

    assert reference["finding_count"] == 213
    assert reference["max_complexity"] == 170
    assert budget["finding_count_max"] < reference["finding_count"]
    assert budget["max_complexity_max"] < reference["max_complexity"]
    # The slice must beat where it started, not only the older reference.
    assert budget["finding_count_max"] < slice_start["finding_count"]
    assert budget["max_complexity_max"] < slice_start["max_complexity"]
    assert budget["excess_total_max"] < slice_start["excess_total"]
    assert baseline["finding_count"] <= budget["finding_count_max"]
    assert baseline["max_complexity"] <= budget["max_complexity_max"]
    assert (
        sum(max(row["max_complexity"] - baseline["threshold"], 0) for row in baseline["findings"])
        <= budget["excess_total_max"]
    )


def test_lint_workflow_runs_graph_maintainability_ratchet() -> None:
    workflow = (ROOT / ".github/workflows/lint.yml").read_text(encoding="utf-8")
    assert "scripts/ci/check_graph_maintainability.py" in workflow
