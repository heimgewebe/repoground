from __future__ import annotations

from collections.abc import Mapping
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


def produce_pr_delta_card(
    delta_context: Mapping[str, Any],
    file_entry: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(delta_context, Mapping):
        raise TypeError("delta_context must be a mapping")
    if not isinstance(file_entry, Mapping):
        raise TypeError("file_entry must be a mapping")

    if delta_context.get("source_kind") != SOURCE_KIND:
        raise ValueError(f"Invalid source_kind: expected {SOURCE_KIND}")
    if delta_context.get("source_version") != SOURCE_VERSION:
        raise ValueError(f"Invalid source_version: expected {SOURCE_VERSION}")

    repo = delta_context.get("repo")
    if not repo or not isinstance(repo, str):
        raise ValueError("repo must be a non-empty string")

    generated_at = delta_context.get("generated_at")
    if not generated_at or not isinstance(generated_at, str):
        raise ValueError("generated_at must be a valid string")

    path = file_entry.get("path")
    if not path or not isinstance(path, str):
        raise ValueError("path must be a non-empty string")

    status = file_entry.get("status")
    if status not in CHANGE_STATUSES:
        raise ValueError(f"Invalid change_status: {status}")

    # Project from lens card
    lens_card = produce_lens_card(path)

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


def produce_pr_delta_cards(
    delta: Mapping[str, Any],
) -> list[dict[str, Any]]:
    if not isinstance(delta, Mapping):
        raise TypeError("delta must be a mapping")

    # Check root attributes
    if delta.get("kind") != SOURCE_KIND:
        raise ValueError(f"Delta kind must be {SOURCE_KIND}")
    if delta.get("version") != SOURCE_VERSION:
        raise ValueError(f"Delta version must be {SOURCE_VERSION}")

    repo = delta.get("repo")
    if not repo or not isinstance(repo, str):
        raise ValueError("Delta repo must be a non-empty string")

    generated_at = delta.get("generated_at")
    if not generated_at or not isinstance(generated_at, str):
        raise ValueError("Delta generated_at must be a string")

    summary = delta.get("summary")
    if not isinstance(summary, Mapping):
        raise ValueError("Delta summary must be a mapping")

    files = delta.get("files")
    if not isinstance(files, list):
        raise ValueError("Delta files must be a list")

    delta_context = {
        "source_kind": SOURCE_KIND,
        "source_version": SOURCE_VERSION,
        "repo": repo,
        "generated_at": generated_at,
    }

    cards: list[dict[str, Any]] = []
    seen_paths: set[str] = set()

    counts = {"added": 0, "changed": 0, "removed": 0}

    for file_entry in files:
        if not isinstance(file_entry, Mapping):
            raise TypeError("File entry must be a mapping")

        path = file_entry.get("path")
        if not isinstance(path, str):
            raise ValueError("File entry path must be a string")

        if path in seen_paths:
            raise ValueError(f"Duplicate path in delta: {path}")
        seen_paths.add(path)

        status = file_entry.get("status")
        if status in counts:
            counts[status] += 1

        card = produce_pr_delta_card(delta_context, file_entry)
        cards.append(card)

    for st in ("added", "changed", "removed"):
        if summary.get(st) != counts[st]:
            raise ValueError("Source summary counts do not match file entries")

    # Sort deterministically by canonical path
    cards.sort(key=lambda c: str(c["path"]))

    return cards
