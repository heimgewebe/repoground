from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from merger.lenskit.core.lens_cards import produce_lens_card

KIND = "lenskit.pr_delta_card"
VERSION = "1.0"
AUTHORITY = "diagnostic_signal"
CANONICALITY = "diagnostic"
SOURCE_KIND = "repolens.pr_schau.delta"
SOURCE_VERSION = 1

CHANGE_STATUSES = ("added", "changed", "removed")

DOES_NOT_ESTABLISH = (
    "truth",
    "correctness",
    "completeness",
    "runtime_behavior",
    "test_sufficiency",
    "regression_absence",
    "semantic_importance",
    "review_priority",
    "change_impact",
    "github_pull_request_identity",
    "commit_identity",
    "rename_identity",
    "hunk_identity",
    "symbol_impact",
    "causality",
    "risk",
)

_SOURCE_SCHEMA_PATH = Path(__file__).parent.parent / "contracts" / "pr-schau-delta.v1.schema.json"

class SourceValidationError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        errors: list[dict[str, str]] | None = None,
    ) -> None:
        super().__init__(message)
        self.errors = errors or []

def _load_jsonschema():
    try:
        import jsonschema
        return jsonschema
    except ImportError:
        raise SourceValidationError("jsonschema library is required to produce PR Delta Cards")

def _load_source_schema() -> Mapping[str, Any]:
    return json.loads(_SOURCE_SCHEMA_PATH.read_text(encoding="utf-8"))

def _schema_error_path(error: Any) -> str:
    parts = [str(part) for part in error.path]
    return "$" if not parts else "$." + ".".join(parts)

def _source_schema_errors(errors: list[Any]) -> list[dict[str, str]]:
    ordered = sorted(
        errors,
        key=lambda e: (
            tuple(str(part) for part in e.path),
            tuple(str(part) for part in e.schema_path),
            e.message,
        ),
    )
    return [
        {
            "path": _schema_error_path(e),
            "validator": str(e.validator),
            "message": e.message,
        }
        for e in ordered
    ]

def _source_format_checker(jsonschema: Any) -> Any:
    checker = jsonschema.FormatChecker()
    registered = getattr(checker, "checkers", None)

    if not isinstance(registered, Mapping) or "date-time" not in registered:
        raise SourceValidationError(
            "jsonschema date-time format validation is unavailable; "
            "install jsonschema[format-nongpl]"
        )

    return checker

def _validate_source_delta(source_delta: Mapping[str, Any]) -> None:
    jsonschema = _load_jsonschema()
    schema = _load_source_schema()

    # Check schema itself
    jsonschema.Draft202012Validator.check_schema(schema)

    validator = jsonschema.Draft202012Validator(
        schema,
        format_checker=_source_format_checker(jsonschema),
    )
    raw_errors = list(validator.iter_errors(source_delta))

    if raw_errors:
        structured_errors = _source_schema_errors(raw_errors)
        raise SourceValidationError(
            f"Source delta validation failed with {len(structured_errors)} error(s)",
            errors=structured_errors
        )

    summary = source_delta["summary"]
    counts = {"added": 0, "changed": 0, "removed": 0}
    seen_paths = set()

    for f in source_delta["files"]:
        path = f["path"]
        if path in seen_paths:
            raise SourceValidationError(f"Duplicate path in delta: {path}")
        seen_paths.add(path)
        counts[f["status"]] += 1

    for st in CHANGE_STATUSES:
        val = summary.get(st)
        if type(val) is not int or val != counts[st]:
            raise SourceValidationError(f"Source summary counts do not match file entries for '{st}'")


def _project_pr_delta_card(
    delta_context: Mapping[str, Any],
    file_entry: Mapping[str, Any],
) -> dict[str, Any]:
    # Pure internal projection helper
    repo = delta_context.get("repo", "")
    generated_at = delta_context["generated_at"]
    path = file_entry["path"]
    status = file_entry["status"]

    try:
        lens_card = produce_lens_card(path)
    except (TypeError, ValueError) as exc:
        raise SourceValidationError(
            f"Source delta path is not accepted by Lens Card v1: {path!r}"
        ) from exc

    return {
        "kind": KIND,
        "version": VERSION,
        "authority": AUTHORITY,
        "canonicality": CANONICALITY,
        "delta_context": {
            "source_kind": SOURCE_KIND,
            "source_version": SOURCE_VERSION,
            "repo": repo,
            "generated_at": generated_at,
        },
        "path": lens_card["path"],
        "change_status": status,
        "primary_lens": lens_card["primary_lens"],
        "matched_rule": lens_card["matched_rule"],
        "facets": lens_card["facets"],
        "navigation_refs": lens_card["navigation_refs"],
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }

def produce_pr_delta_card(
    source_delta: Mapping[str, Any],
    path: str,
) -> dict[str, Any]:
    if not isinstance(source_delta, Mapping):
        raise TypeError("source_delta must be a mapping")

    _validate_source_delta(source_delta)

    matches = [f for f in source_delta["files"] if f["path"] == path]
    if not matches:
        raise ValueError(f"Path '{path}' not found in source delta")
    if len(matches) > 1:
        raise ValueError(f"Multiple entries found for path '{path}'")

    delta_context = {
        "source_kind": source_delta["kind"],
        "source_version": source_delta["version"],
        "repo": source_delta.get("repo", ""),
        "generated_at": source_delta["generated_at"],
    }

    return _project_pr_delta_card(delta_context, matches[0])

def produce_pr_delta_cards(
    source_delta: Mapping[str, Any],
) -> list[dict[str, Any]]:
    if not isinstance(source_delta, Mapping):
        raise TypeError("source_delta must be a mapping")

    _validate_source_delta(source_delta)

    delta_context = {
        "source_kind": source_delta["kind"],
        "source_version": source_delta["version"],
        "repo": source_delta.get("repo", ""),
        "generated_at": source_delta["generated_at"],
    }

    cards = []
    for file_entry in source_delta["files"]:
        card = _project_pr_delta_card(delta_context, file_entry)
        cards.append(card)

    cards.sort(key=lambda c: str(c["path"]))
    return cards
