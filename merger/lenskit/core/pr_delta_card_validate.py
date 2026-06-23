from __future__ import annotations

import importlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from merger.lenskit.core.dependency_diagnostics import jsonschema_dependency
from merger.lenskit.core.pr_delta_cards import produce_pr_delta_card

KIND = "lenskit.pr_delta_card_validation"
VERSION = "1.0"
ENGINE = "pr_delta_card_validate"

VALIDATOR_DOES_NOT_ESTABLISH = (
    "truth",
    "repo_understood",
    "review_complete",
    "test_sufficiency",
    "runtime_correctness",
    "regression_absence",
    "change_impact",
    "safety",
    "github_pull_request_identity",
    "commit_identity",
    "source_authenticity",
)

_SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent / "contracts" / "pr-delta-card.v1.schema.json"
)
_STATUS_WEIGHT = {"pass": 0, "warn": 1, "fail": 2}


def _validation(mode: str, engine: str, reason: str) -> dict[str, str]:
    return {"mode": mode, "engine": engine, "reason": reason}


def _check(
    name: str,
    status: str,
    detail: str,
    *,
    mode: str,
    engine: str,
    reason: str,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "name": name,
        "status": status,
        "detail": detail,
        "validation": _validation(mode, engine, reason),
    }
    if extra:
        result.update(extra)
    return result


def _rollup(checks: list[Mapping[str, Any]]) -> str:
    worst = "pass"
    for check in checks:
        status = check.get("status")
        if isinstance(status, str) and _STATUS_WEIGHT.get(status, 0) > _STATUS_WEIGHT[worst]:
            worst = status
    return worst


def _load_default_schema() -> dict[str, Any]:
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


def _load_jsonschema() -> tuple[Any | None, str | None]:
    try:
        return importlib.import_module("jsonschema"), None
    except Exception as exc:  # pragma: no cover
        return None, f"{type(exc).__name__}: {exc}"


def _schema_error_path(error: Any) -> str:
    parts = [str(part) for part in error.path]
    return "$" if not parts else "$." + ".".join(parts)


def _schema_errors(errors: list[Any]) -> list[dict[str, str]]:
    ordered = sorted(
        errors,
        key=lambda error: (
            tuple(str(part) for part in error.path),
            tuple(str(part) for part in error.schema_path),
            error.message,
        ),
    )
    return [
        {
            "path": _schema_error_path(error),
            "validator": str(error.validator),
            "message": error.message,
        }
        for error in ordered
    ]


def validate_pr_delta_card(
    card: Mapping[str, Any],
    *,
    source_delta: Mapping[str, Any],
    schema: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate one PR Delta Card formally and against concrete source evidence."""
    checks: list[dict[str, Any]] = []
    jsonschema, import_error = _load_jsonschema()
    jsonschema_available = jsonschema is not None

    if jsonschema is None:
        checks.append(
            _check(
                "schema_validation",
                "fail",
                "jsonschema is unavailable; PR Delta Card full validation cannot run",
                mode="skipped_unavailable",
                engine="jsonschema",
                reason="dependency_unavailable",
                extra={"error": import_error or "jsonschema unavailable"},
            )
        )
        return _assemble(checks, jsonschema_available=jsonschema_available)

    active_schema: Mapping[str, Any]
    try:
        active_schema = schema if schema is not None else _load_default_schema()
        jsonschema.Draft7Validator.check_schema(active_schema)
        validator = jsonschema.Draft7Validator(active_schema, format_checker=jsonschema.FormatChecker())
        errors = list(validator.iter_errors(card))
    except Exception as exc:
        checks.append(
            _check(
                "schema_validation",
                "fail",
                f"pr-delta-card schema could not be used: {type(exc).__name__}: {exc}",
                mode="jsonschema",
                engine="jsonschema",
                reason="schema_invalid",
            )
        )
        return _assemble(checks, jsonschema_available=jsonschema_available)

    if errors:
        checks.append(
            _check(
                "schema_validation",
                "fail",
                f"pr-delta-card schema validation failed with {len(errors)} error(s)",
                mode="jsonschema",
                engine="jsonschema",
                reason="available",
                extra={"errors": _schema_errors(errors)},
            )
        )
        return _assemble(checks, jsonschema_available=jsonschema_available)

    checks.append(
        _check(
            "schema_validation",
            "pass",
            "pr-delta-card schema validation passed",
            mode="jsonschema",
            engine="jsonschema",
            reason="available",
        )
    )

    try:
        expected = produce_pr_delta_card(source_delta, card.get("path", ""))
    except Exception as exc:
        checks.append(
            _check(
                "source_producer_coherence",
                "fail",
                f"could not compute PR Delta Card from source evidence: {type(exc).__name__}: {exc}",
                mode="structural_precheck",
                engine=ENGINE,
                reason="producer_coherence_check",
            )
        )
        return _assemble(checks, jsonschema_available=jsonschema_available)

    compared_fields = (
        "kind",
        "version",
        "authority",
        "canonicality",
        "delta_context",
        "path",
        "change_status",
        "primary_lens",
        "matched_rule",
        "facets",
        "navigation_refs",
        "does_not_establish",
    )
    mismatches = [
        {
            "field": field,
            "expected": expected[field],
            "actual": card.get(field),
        }
        for field in compared_fields
        if card.get(field) != expected[field]
    ]
    if mismatches:
        checks.append(
            _check(
                "source_producer_coherence",
                "fail",
                "PR Delta Card does not match the controlled producer output from source evidence",
                mode="structural_precheck",
                engine=ENGINE,
                reason="producer_coherence_check",
                extra={"mismatches": mismatches},
            )
        )
    else:
        checks.append(
            _check(
                "source_producer_coherence",
                "pass",
                "PR Delta Card matches the controlled producer output from source evidence",
                mode="structural_precheck",
                engine=ENGINE,
                reason="producer_coherence_check",
            )
        )

    return _assemble(checks, jsonschema_available=jsonschema_available)


def _assemble(
    checks: list[dict[str, Any]],
    *,
    jsonschema_available: bool,
) -> dict[str, Any]:
    return {
        "kind": KIND,
        "version": VERSION,
        "status": _rollup(checks),
        "checks": checks,
        "dependencies": jsonschema_dependency(
            available=jsonschema_available,
            required_for=["pr_delta_card_schema"],
        ),
        "does_not_establish": list(VALIDATOR_DOES_NOT_ESTABLISH),
    }
