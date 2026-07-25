from __future__ import annotations

from scripts.benchmarks.compare_repoground_core_paths import (
    _aggregate_case,
    _compare_case,
)


def _row(timing: float, memory: int, samples: int = 5) -> dict[str, object]:
    return {
        "samples": samples,
        "wall_seconds_median": timing,
        "peak_traced_bytes": memory,
    }


def test_aggregate_case_uses_median_and_keeps_round_values() -> None:
    aggregate = _aggregate_case([_row(1.0, 100), _row(1.2, 120)])
    assert aggregate["wall_seconds_median"] == 1.1
    assert aggregate["peak_traced_bytes"] == 110
    assert aggregate["samples_per_round"] == [5, 5]


def test_compare_case_accepts_values_inside_predeclared_gate() -> None:
    result = _compare_case(
        {"wall_seconds_median": 1.0, "peak_traced_bytes": 100},
        {"wall_seconds_median": 1.049, "peak_traced_bytes": 104},
    )
    assert result["status"] == "pass"
    assert result["timing_pass"] is True
    assert result["memory_pass"] is True


def test_compare_case_rejects_timing_or_memory_regression() -> None:
    timing = _compare_case(
        {"wall_seconds_median": 1.0, "peak_traced_bytes": 100},
        {"wall_seconds_median": 1.051, "peak_traced_bytes": 100},
    )
    memory = _compare_case(
        {"wall_seconds_median": 1.0, "peak_traced_bytes": 100},
        {"wall_seconds_median": 1.0, "peak_traced_bytes": 106},
    )
    assert timing["status"] == "fail"
    assert memory["status"] == "fail"


def test_compare_case_requires_identical_skip_contract() -> None:
    same = _compare_case(
        {"skipped": ["not requested"], "rounds": 2},
        {"skipped": ["not requested"], "rounds": 2},
    )
    different = _compare_case(
        {"skipped": ["not requested"], "rounds": 2},
        {"skipped": ["unavailable"], "rounds": 2},
    )
    assert same["status"] == "skip"
    assert different["status"] == "fail"
