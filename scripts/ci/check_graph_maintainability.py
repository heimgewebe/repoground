#!/usr/bin/env python3
"""Fail on graph-noise regression or new/worse C901 complexity debt."""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from merger.repoground.architecture.graph_maintainability import (  # noqa: E402
    evaluate_graph_policy,
    measure_graph_maintainability,
)

DEFAULT_POLICY = Path("config/repoground-graph-maintainability.v1.json")
_C901_PATTERN = re.compile(
    r"`(?P<name>[^`]+)` is too complex "
    r"\((?P<complexity>\d+) > (?P<limit>\d+)\)"
)


@dataclass(frozen=True)
class ComplexityFinding:
    path: str
    qualified_name: str
    complexity: int
    limit: int

    @property
    def identity(self) -> str:
        return f"{self.path}::{self.qualified_name}"


class _QualifiedNameCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.stack: list[str] = []
        self.by_line: dict[int, str] = {}

    def _visit_scope(self, node: ast.AST, name: str) -> None:
        self.stack.append(name)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            self.by_line[node.lineno] = ".".join(self.stack)
        self.generic_visit(node)
        self.stack.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._visit_scope(node, node.name)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_scope(node, node.name)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_scope(node, node.name)


def _qualified_names(path: Path) -> dict[int, str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    collector = _QualifiedNameCollector()
    collector.visit(tree)
    return collector.by_line


def collect_complexity_findings(repo_root: Path) -> list[ComplexityFinding]:
    """Run Ruff C901 and bind each finding to its AST-qualified function name."""

    command = [
        "ruff",
        "check",
        "--config",
        "ruff-ci.toml",
        "--select",
        "C901",
        "--output-format",
        "json",
        ".",
    ]
    completed = subprocess.run(
        command,
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode not in {0, 1}:
        raise RuntimeError(f"ruff C901 scan failed: {completed.stderr.strip()}")
    try:
        rows = json.loads(completed.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise RuntimeError("ruff C901 output is not valid JSON") from exc

    name_cache: dict[Path, dict[int, str]] = {}
    findings: list[ComplexityFinding] = []
    for row in rows:
        match = _C901_PATTERN.fullmatch(str(row.get("message", "")))
        if row.get("code") != "C901" or match is None:
            raise RuntimeError(f"unexpected Ruff diagnostic in C901 scan: {row!r}")
        absolute = Path(row["filename"]).resolve()
        try:
            relative = absolute.relative_to(repo_root).as_posix()
        except ValueError as exc:
            raise RuntimeError(f"Ruff finding escapes repository: {absolute}") from exc
        if absolute not in name_cache:
            name_cache[absolute] = _qualified_names(absolute)
        line = int(row["location"]["row"])
        qualified_name = name_cache[absolute].get(line)
        if qualified_name is None:
            raise RuntimeError(
                f"cannot bind C901 finding to AST function: {relative}:{line}"
            )
        if qualified_name.rsplit(".", 1)[-1] != match.group("name"):
            raise RuntimeError(
                "Ruff/AST function mismatch: "
                f"{relative}:{line} {match.group('name')} != {qualified_name}"
            )
        findings.append(
            ComplexityFinding(
                path=relative,
                qualified_name=qualified_name,
                complexity=int(match.group("complexity")),
                limit=int(match.group("limit")),
            )
        )
    return sorted(findings, key=lambda item: item.identity)


def _validate_complexity_baseline(
    baseline: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]] | None]:
    findings: list[dict[str, Any]] = []
    if (
        baseline.get("kind") != "repoground.c901_baseline"
        or baseline.get("version") != "1.0"
    ):
        findings.append({"code": "complexity_baseline_identity_invalid"})
    rows = baseline.get("findings")
    if not isinstance(rows, list):
        findings.append(
            {"code": "complexity_baseline_invalid", "detail": "findings missing"}
        )
        return findings, None
    if baseline.get("finding_count") != len(rows):
        findings.append(
            {
                "code": "complexity_baseline_count_mismatch",
                "recorded": baseline.get("finding_count"),
                "observed": len(rows),
            }
        )
    observed_max = max(
        (int(row.get("max_complexity", -1)) for row in rows),
        default=0,
    )
    if baseline.get("max_complexity") != observed_max:
        findings.append(
            {
                "code": "complexity_baseline_maximum_mismatch",
                "recorded": baseline.get("max_complexity"),
                "observed": observed_max,
            }
        )
    return findings, rows


def _allowed_complexity(
    rows: list[dict[str, Any]],
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    allowed: dict[str, int] = {}
    findings: list[dict[str, Any]] = []
    for row in rows:
        identity = f"{row.get('path')}::{row.get('qualified_name')}"
        if identity in allowed:
            findings.append(
                {"code": "complexity_baseline_duplicate", "identity": identity}
            )
        else:
            allowed[identity] = int(row.get("max_complexity", -1))
    if list(allowed) != sorted(allowed):
        findings.append({"code": "complexity_baseline_not_sorted"})
    return allowed, findings


def _complexity_regressions(
    current: list[ComplexityFinding],
    allowed: dict[str, int],
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for item in current:
        maximum = allowed.get(item.identity)
        if maximum is None:
            findings.append(
                {
                    "code": "new_complexity_violation",
                    "identity": item.identity,
                    "complexity": item.complexity,
                }
            )
        elif item.complexity > maximum:
            findings.append(
                {
                    "code": "complexity_regression",
                    "identity": item.identity,
                    "complexity": item.complexity,
                    "maximum": maximum,
                }
            )
    return findings


_BUDGET_DIMENSIONS = (
    # (budget key, dimension label shared with the recorded references)
    ("finding_count_max", "finding_count"),
    ("max_complexity_max", "max_complexity"),
    ("excess_total_max", "excess_total"),
)

#: Recorded scans a ceiling may never exceed. Every budgeted dimension must be
#: bounded by at least one of them, otherwise a ceiling could be raised without
#: limit and the ratchet would only appear to hold.
_REFERENCE_KEYS = ("historical_reference", "slice_start_reference")


def measure_complexity_budget(current: list[ComplexityFinding]) -> dict[str, int]:
    """Aggregate the three budgeted complexity dimensions of a scan."""

    return {
        "finding_count": len(current),
        "max_complexity": max((item.complexity for item in current), default=0),
        # Excess is the complexity mass above the configured threshold. It falls
        # when a function is split even if the split creates further findings.
        "excess_total": sum(max(item.complexity - item.limit, 0) for item in current),
    }


def _recorded_references(budget: dict[str, Any], label: str) -> list[tuple[str, Any]]:
    """Return every recorded scan that bounds one budgeted dimension."""

    recorded: list[tuple[str, Any]] = []
    for key in _REFERENCE_KEYS:
        reference = budget.get(key)
        if isinstance(reference, dict) and label in reference:
            recorded.append((key, reference[label]))
    return recorded


def _budget_dimension_findings(
    budget: dict[str, Any],
    observed: dict[str, int],
    budget_key: str,
    label: str,
) -> list[dict[str, Any]]:
    ceiling = budget.get(budget_key)
    if not isinstance(ceiling, int) or isinstance(ceiling, bool):
        return [{"code": "complexity_budget_invalid", "dimension": budget_key}]

    findings: list[dict[str, Any]] = []
    if observed[label] > ceiling:
        findings.append(
            {
                "code": "complexity_budget_exceeded",
                "dimension": label,
                "observed": observed[label],
                "budget": ceiling,
            }
        )

    recorded = _recorded_references(budget, label)
    if not recorded:
        # An unbounded ceiling could be raised at will, so it is a finding.
        findings.append(
            {"code": "complexity_budget_reference_missing", "dimension": label}
        )
    for reference_key, value in recorded:
        if not isinstance(value, int) or isinstance(value, bool):
            findings.append(
                {
                    "code": "complexity_budget_reference_invalid",
                    "dimension": label,
                    "reference": reference_key,
                }
            )
        elif ceiling > value:
            findings.append(
                {
                    "code": "complexity_budget_raised_above_reference",
                    "dimension": label,
                    "budget": ceiling,
                    "reference": reference_key,
                    "recorded": value,
                }
            )
    return findings


def evaluate_complexity_budget(
    current: list[ComplexityFinding],
    budget: Any,
) -> list[dict[str, Any]]:
    """Reject scans above the recorded budget, and budgets above the references.

    Fail-closed: a missing or malformed budget is itself a finding, so removing
    the budget cannot silently disable the ratchet, and every ceiling must be
    bounded by at least one recorded scan.
    """

    if not isinstance(budget, dict):
        return [{"code": "complexity_budget_missing"}]
    if not any(isinstance(budget.get(key), dict) for key in _REFERENCE_KEYS):
        return [{"code": "complexity_budget_reference_missing"}]

    observed = measure_complexity_budget(current)
    findings: list[dict[str, Any]] = []
    for budget_key, label in _BUDGET_DIMENSIONS:
        findings += _budget_dimension_findings(budget, observed, budget_key, label)
    return findings


def compare_complexity_baseline(
    current: list[ComplexityFinding],
    baseline: dict[str, Any],
) -> list[dict[str, Any]]:
    """Allow resolved debt; reject malformed, new or worse complexity debt."""

    findings, rows = _validate_complexity_baseline(baseline)
    if rows is None:
        return findings
    allowed, structural_findings = _allowed_complexity(rows)
    return findings + structural_findings + _complexity_regressions(current, allowed)


def check(repo_root: Path, policy_path: Path) -> dict[str, Any]:
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    measurement = measure_graph_maintainability(repo_root)
    graph_findings = evaluate_graph_policy(measurement, policy)
    baseline_path = repo_root / policy["complexity"]["baseline_path"]
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    current_complexity = collect_complexity_findings(repo_root)
    complexity_findings = compare_complexity_baseline(current_complexity, baseline)
    budget_findings = evaluate_complexity_budget(
        current_complexity, policy["complexity"].get("budget")
    )
    findings = graph_findings + complexity_findings + budget_findings
    baseline_identities = {
        f"{row['path']}::{row['qualified_name']}" for row in baseline["findings"]
    }
    current_identities = {item.identity for item in current_complexity}
    return {
        "kind": "repoground.graph_maintainability_check",
        "version": "1.0",
        "status": "pass" if not findings else "fail",
        "measurement": measurement,
        "complexity": {
            "baseline_count": len(baseline_identities),
            "current_count": len(current_identities),
            "resolved_count": len(baseline_identities - current_identities),
            "new_count": len(current_identities - baseline_identities),
            "current_max": max(
                (item.complexity for item in current_complexity),
                default=0,
            ),
            "budget": policy["complexity"].get("budget"),
            "observed_budget_dimensions": measure_complexity_budget(current_complexity),
        },
        "findings": findings,
        "does_not_establish": [
            "absence of maintainability problems below C901 threshold",
            "semantic correctness of graph classification",
            "runtime reachability",
            "architecture quality",
            "test completeness",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    policy = args.policy if args.policy.is_absolute() else root / args.policy
    report = check(root, policy)
    if args.format == "json":
        print(json.dumps(report, indent=2, sort_keys=True))
    elif report["findings"]:
        for finding in report["findings"]:
            print(json.dumps(finding, sort_keys=True))
    else:
        print("Graph maintainability ratchets: pass")
    return 1 if report["findings"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
