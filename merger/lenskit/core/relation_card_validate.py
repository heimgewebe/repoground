"""Source-aware validator for Relation Cards v1.

Validation is fail-closed and reuses the existing lens-family check shape
(``status`` / ``checks[].name`` / ``checks[].status`` / ``checks[].detail`` /
``checks[].validation.{mode,engine,reason}`` / ``dependencies``). A ``pass`` means
only that the card matches the v1 schema, that the source graph matches
``architecture.graph.v1``, that the card resolves to exactly one projected source
edge, and that the card preserves that edge's evidence without upgrade. It does
not prove truth, runtime correctness, a runtime dependency, causality, review
completeness or safety.
"""
from __future__ import annotations

import importlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from merger.lenskit.core.dependency_diagnostics import jsonschema_dependency
from merger.lenskit.core.relation_cards import (
    card_identity,
    produce_relation_cards,
)

KIND = "lenskit.relation_card_validation"
VERSION = "1.0"
ENGINE = "relation_card_validate"

# What a Relation Card validation PASS does NOT prove (validator-level negative
# semantics, distinct from the card-level does_not_establish tuple).
VALIDATOR_DOES_NOT_ESTABLISH = (
    "truth",
    "repo_understood",
    "review_complete",
    "test_sufficiency",
    "runtime_correctness",
    "regression_absence",
    "change_impact",
    "safety",
    "runtime_dependency",
    "causality",
    "source_authenticity",
)

_CARD_SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent / "contracts" / "relation-card.v1.schema.json"
)
_SOURCE_SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent / "contracts" / "architecture.graph.v1.schema.json"
)
_STATUS_WEIGHT = {"pass": 0, "warn": 1, "fail": 2}

# Card fields that must be preserved verbatim from the projected source edge.
# Identity (source/target/evidence position) is checked by source_producer_coherence;
# this tuple is the explicit anti-upgrade assertion for the remaining fields and a
# defense-in-depth guard when a permissive custom card schema is supplied.
_PRESERVED_FIELDS = (
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
)


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


def _load_default_card_schema() -> dict[str, Any]:
    return json.loads(_CARD_SCHEMA_PATH.read_text(encoding="utf-8"))


def _load_default_source_schema() -> dict[str, Any]:
    return json.loads(_SOURCE_SCHEMA_PATH.read_text(encoding="utf-8"))


def _load_jsonschema() -> tuple[Any | None, str | None]:
    try:
        return importlib.import_module("jsonschema"), None
    except Exception as exc:  # pragma: no cover - exact import error varies by host.
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


def _schema_check(
    jsonschema: Any,
    name: str,
    instance: Mapping[str, Any],
    schema: Mapping[str, Any],
    *,
    artifact: str,
) -> dict[str, Any]:
    try:
        jsonschema.Draft7Validator.check_schema(schema)
        validator = jsonschema.Draft7Validator(schema)
        errors = list(validator.iter_errors(instance))
    except Exception as exc:
        return _check(
            name,
            "fail",
            f"{artifact} schema could not be used: {type(exc).__name__}: {exc}",
            mode="jsonschema",
            engine="jsonschema",
            reason="schema_invalid",
        )
    if errors:
        return _check(
            name,
            "fail",
            f"{artifact} schema validation failed with {len(errors)} error(s)",
            mode="jsonschema",
            engine="jsonschema",
            reason="available",
            extra={"errors": _schema_errors(errors)},
        )
    return _check(
        name,
        "pass",
        f"{artifact} schema validation passed",
        mode="jsonschema",
        engine="jsonschema",
        reason="available",
    )





def validate_relation_card(
    card: Mapping[str, Any],
    *,
    source_graph: Mapping[str, Any],
    schema: Mapping[str, Any] | None = None,
    source_schema: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate one Relation Card against its source graph, fail-closed.

    Check order (all must pass): ``schema_validation`` (card),
    ``source_schema_validation`` (graph), ``source_producer_coherence`` (the card
    resolves to exactly one projected source edge), ``evidence_preservation`` (the
    card preserves that edge's projection without alteration or upgrade).
    """
    checks: list[dict[str, Any]] = []
    jsonschema, import_error = _load_jsonschema()
    jsonschema_available = jsonschema is not None

    if jsonschema is None:
        checks.append(
            _check(
                "schema_validation",
                "fail",
                "jsonschema is unavailable; Relation Card full validation cannot run",
                mode="skipped_unavailable",
                engine="jsonschema",
                reason="dependency_unavailable",
                extra={"error": import_error or "jsonschema unavailable"},
            )
        )
        return _assemble(checks, jsonschema_available=jsonschema_available)

    # 1. Card schema.
    card_schema = schema if schema is not None else _load_default_card_schema()
    card_check = _schema_check(
        jsonschema, "schema_validation", card, card_schema, artifact="relation-card"
    )
    checks.append(card_check)
    if card_check["status"] == "fail":
        return _assemble(checks, jsonschema_available=jsonschema_available)

    # 2. Source-graph schema.
    src_schema = source_schema if source_schema is not None else _load_default_source_schema()
    source_check = _schema_check(
        jsonschema,
        "source_schema_validation",
        source_graph,
        src_schema,
        artifact="architecture-graph source",
    )
    checks.append(source_check)
    if source_check["status"] == "fail":
        return _assemble(checks, jsonschema_available=jsonschema_available)

    # 3. Source-producer coherence: the card must resolve to exactly one edge of
    #    the controlled projection recomputed from the source graph.
    try:
        expected_cards = produce_relation_cards(source_graph)
    except Exception as exc:
        checks.append(
            _check(
                "source_producer_coherence",
                "fail",
                f"could not recompute Relation Cards from source graph: {type(exc).__name__}: {exc}",
                mode="structural_precheck",
                engine=ENGINE,
                reason="producer_coherence_check",
            )
        )
        return _assemble(checks, jsonschema_available=jsonschema_available)

    try:
        identity = card_identity(card)
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        checks.append(
            _check(
                "source_producer_coherence",
                "fail",
                f"Relation Card is structurally incomplete and missing identity fields: {type(exc).__name__}",
                mode="structural_precheck",
                engine=ENGINE,
                reason="producer_coherence_check",
            )
        )
        return _assemble(checks, jsonschema_available=jsonschema_available)

    matches = [c for c in expected_cards if card_identity(c) == identity]
    match = matches[0] if len(matches) == 1 else None

    if match is None:
        checks.append(
            _check(
                "source_producer_coherence",
                "fail",
                "Relation Card does not resolve to exactly one import edge in the source graph projection",
                mode="structural_precheck",
                engine=ENGINE,
                reason="producer_coherence_check",
                extra={
                    "source": card.get("source") if isinstance(card, Mapping) else None,
                    "target": card.get("target") if isinstance(card, Mapping) else None,
                    "evidence": card.get("evidence") if isinstance(card, Mapping) else None,
                },
            )
        )
        return _assemble(checks, jsonschema_available=jsonschema_available)
    checks.append(
        _check(
            "source_producer_coherence",
            "pass",
            "Relation Card resolves to exactly one projected source edge",
            mode="structural_precheck",
            engine=ENGINE,
            reason="producer_coherence_check",
        )
    )

    # 4. Evidence preservation: nothing was altered or upgraded relative to the
    #    controlled projection of the resolved edge.
    mismatches = [
        {"field": field, "expected": match.get(field), "actual": card.get(field)}
    mismatches = [
        {"field": field, "expected": match.get(field), "actual": card.get(field)}
        for field in _PRESERVED_FIELDS
        if card.get(field) != match.get(field)
    ]
    unexpected_fields = sorted(set(card) - set(match))
    if mismatches or unexpected_fields:
        checks.append(
            _check(
                "evidence_preservation",
                "fail",
                "Relation Card alters, upgrades or extends the projected source evidence",
                mode="structural_precheck",
                engine=ENGINE,
                reason="evidence_preservation_check",
                extra={
                    "mismatches": mismatches,
                    "unexpected_fields": unexpected_fields,
                },
            )
        )
        checks.append(
            _check(
                "evidence_preservation",
                "pass",
                "Relation Card preserves relation, source rule, derivation type, "
                "evidence level, addresses and evidence without upgrade",
                mode="structural_precheck",
                engine=ENGINE,
                reason="evidence_preservation_check",
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
            required_for=[
                "relation_card_schema",
                "architecture_graph_source_schema",
            ],
        ),
        "does_not_establish": list(VALIDATOR_DOES_NOT_ESTABLISH),
    }
