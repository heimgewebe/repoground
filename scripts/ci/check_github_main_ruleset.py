#!/usr/bin/env python3
"""Validate an observed GitHub ruleset against RepoGround's required-check policy.

The observed ruleset JSON is read from stdin. This checker is deliberately
read-only and network-free; callers remain responsible for obtaining current
GitHub API data.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = ROOT / "config" / "github-main-required-checks.v1.json"
KIND = "repoground.github_main_required_checks_validation"
VERSION = "v1"


class RulesetValidationError(ValueError):
    """Raised when policy or observed ruleset input is structurally invalid."""


def _load_object(raw: str, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RulesetValidationError(f"{label} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise RulesetValidationError(f"{label} must be a JSON object")
    return value


def load_policy() -> dict[str, Any]:
    try:
        policy = _load_object(POLICY_PATH.read_text(encoding="utf-8"), label="policy")
    except OSError as exc:
        raise RulesetValidationError(f"cannot read policy: {POLICY_PATH}") from exc
    if policy.get("schema_version") != 1:
        raise RulesetValidationError("policy schema_version must be 1")
    repository = policy.get("repository")
    if not isinstance(repository, str) or not repository.strip():
        raise RulesetValidationError("policy repository must be non-empty")
    if policy.get("source_type") != "Repository":
        raise RulesetValidationError("policy source_type must be Repository")
    ruleset = policy.get("ruleset")
    if not isinstance(ruleset, dict):
        raise RulesetValidationError("policy ruleset must be an object")
    return policy


def api_payload(policy: dict[str, Any]) -> dict[str, Any]:
    """Return the exact create/update payload encoded by the policy."""
    ruleset = policy.get("ruleset")
    if not isinstance(ruleset, dict):
        raise RulesetValidationError("policy ruleset must be an object")
    return json.loads(json.dumps(ruleset))


def _required_rule(ruleset: dict[str, Any], *, label: str) -> dict[str, Any]:
    rules = ruleset.get("rules")
    if not isinstance(rules, list):
        raise RulesetValidationError(f"{label}.rules must be a list")
    if len(rules) != 1:
        raise RulesetValidationError(
            f"{label} must contain exactly one rule; found {len(rules)}"
        )
    rule = rules[0]
    if not isinstance(rule, dict) or rule.get("type") != "required_status_checks":
        raise RulesetValidationError(
            f"{label} only rule must be required_status_checks"
        )
    return rule


def _check_pairs(rule: dict[str, Any], *, label: str) -> Counter[tuple[str, int | None]]:
    parameters = rule.get("parameters")
    if not isinstance(parameters, dict):
        raise RulesetValidationError(f"{label}.parameters must be an object")
    checks = parameters.get("required_status_checks")
    if not isinstance(checks, list):
        raise RulesetValidationError(f"{label}.required_status_checks must be a list")
    pairs: Counter[tuple[str, int | None]] = Counter()
    for index, item in enumerate(checks):
        if not isinstance(item, dict):
            raise RulesetValidationError(f"{label}.required_status_checks[{index}] must be an object")
        context = item.get("context")
        integration_id = item.get("integration_id")
        if not isinstance(context, str) or not context.strip():
            raise RulesetValidationError(
                f"{label}.required_status_checks[{index}].context must be non-empty"
            )
        if integration_id is not None and not isinstance(integration_id, int):
            raise RulesetValidationError(
                f"{label}.required_status_checks[{index}].integration_id must be an integer"
            )
        pairs[(context, integration_id)] += 1
    return pairs


def validate_ruleset(policy: dict[str, Any], observed: dict[str, Any]) -> dict[str, Any]:
    expected = api_payload(policy)
    findings: list[str] = []

    expected_source = policy["repository"]
    expected_source_type = policy["source_type"]
    if observed.get("source") != expected_source:
        findings.append(
            f"source mismatch: expected {expected_source!r}, found {observed.get('source')!r}"
        )
    if observed.get("source_type") != expected_source_type:
        findings.append(
            "source_type mismatch: expected "
            f"{expected_source_type!r}, found {observed.get('source_type')!r}"
        )

    for field in ("name", "target", "enforcement", "bypass_actors"):
        if observed.get(field) != expected.get(field):
            findings.append(
                f"{field} mismatch: expected {expected.get(field)!r}, found {observed.get(field)!r}"
            )

    expected_conditions = expected.get("conditions")
    observed_conditions = observed.get("conditions")
    if observed_conditions != expected_conditions:
        findings.append(
            "conditions mismatch: expected "
            + json.dumps(expected_conditions, sort_keys=True)
            + ", found "
            + json.dumps(observed_conditions, sort_keys=True)
        )

    expected_rule = _required_rule(expected, label="policy.ruleset")
    try:
        observed_rule = _required_rule(observed, label="observed")
    except RulesetValidationError as exc:
        findings.append(str(exc))
        observed_rule = None

    if observed_rule is not None:
        expected_parameters = expected_rule["parameters"]
        observed_parameters = observed_rule.get("parameters")
        if not isinstance(observed_parameters, dict):
            findings.append("observed required_status_checks parameters must be an object")
        else:
            for field in (
                "strict_required_status_checks_policy",
                "do_not_enforce_on_create",
            ):
                if observed_parameters.get(field) != expected_parameters.get(field):
                    findings.append(
                        f"{field} mismatch: expected {expected_parameters.get(field)!r}, "
                        f"found {observed_parameters.get(field)!r}"
                    )
            try:
                expected_pairs = _check_pairs(expected_rule, label="policy rule")
                observed_pairs = _check_pairs(observed_rule, label="observed rule")
            except RulesetValidationError as exc:
                findings.append(str(exc))
            else:
                missing = expected_pairs - observed_pairs
                unexpected = observed_pairs - expected_pairs
                if missing:
                    findings.append(
                        "missing required checks: "
                        + json.dumps(sorted(missing.elements()), sort_keys=True)
                    )
                if unexpected:
                    findings.append(
                        "unexpected required checks: "
                        + json.dumps(sorted(unexpected.elements()), sort_keys=True)
                    )

    status = "pass" if not findings else "fail"
    return {
        "kind": KIND,
        "version": VERSION,
        "status": status,
        "repository": policy.get("repository"),
        "observed_source": observed.get("source"),
        "observed_source_type": observed.get("source_type"),
        "ruleset_id": observed.get("id"),
        "ruleset_name": observed.get("name"),
        "findings": findings,
        "required_checks": [
            {"context": context, "integration_id": integration_id}
            for context, integration_id in sorted(_check_pairs(expected_rule, label="policy rule"))
        ],
        "does_not_establish": list(policy.get("does_not_establish", [])),
    }


def main() -> int:
    try:
        policy = load_policy()
        observed = _load_object(sys.stdin.read(), label="observed ruleset")
        report = validate_ruleset(policy, observed)
    except RulesetValidationError as exc:
        print(f"ruleset validation error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
