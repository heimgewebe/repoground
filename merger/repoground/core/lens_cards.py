from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import PurePosixPath
from typing import Any

from merger.repoground.core.lens_audit import explain_primary_lens
from merger.repoground.core.lens_facets import (
    DOES_NOT_ESTABLISH,
    infer_facets,
)

KIND = "lenskit.lens_card"
VERSION = "1.0"
AUTHORITY = "navigation_index"
CANONICALITY = "derived"
LENS_CARD_DENSITIES = ("verbose", "compact")


def _canonical_path_after_facet_gate(path: str | PurePosixPath) -> str:
    if isinstance(path, str):
        return path
    if isinstance(path, PurePosixPath):
        return path.as_posix()
    raise TypeError(
        "lens card path must be str or PurePosixPath, "
        f"got {type(path).__name__}"
    )


def _project_facet(item: dict[str, Any]) -> dict[str, str]:
    return {
        "facet": item["facet"],
        "source_rule": item["source_rule"],
        "derivation_type": item["derivation_type"],
    }


def produce_lens_card(path: str | PurePosixPath) -> dict[str, Any]:
    """Produce one deterministic Lens Card for one accepted repo path.

    The path boundary is delegated to the public Facet Model v1 producer API:
    ``infer_facets()`` validates the same strict path surface even when it
    returns no facet assignments. The remaining fields are projections from the
    public Primary Lens Audit explanation and Facet Model output.
    """
    facet_items = infer_facets(path)
    posix = _canonical_path_after_facet_gate(path)
    primary_lens, matched_rule = explain_primary_lens(posix)
    facets = [_project_facet(item) for item in facet_items]
    facets.sort(
        key=lambda item: (
            item["facet"],
            item["source_rule"],
            item["derivation_type"],
        )
    )

    return {
        "kind": KIND,
        "version": VERSION,
        "authority": AUTHORITY,
        "canonicality": CANONICALITY,
        "path": posix,
        "primary_lens": primary_lens,
        "matched_rule": matched_rule,
        "facets": facets,
        "navigation_refs": [{"kind": "repo_path", "target": posix}],
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }


def produce_lens_card_collection(
    paths: Iterable[str | PurePosixPath],
    *,
    density: str = "verbose",
) -> dict[str, Any]:
    """Produce an in-memory Lens Card collection for bounded consumers.

    ``verbose`` preserves the existing self-contained card shape. ``compact``
    removes only the repeated per-card ``does_not_establish`` field and carries
    the same mandatory negative semantics once at collection level. This helper
    does not register a bundle artifact or a new single-card schema.
    """
    if density not in LENS_CARD_DENSITIES:
        raise ValueError(
            f"density must be one of {LENS_CARD_DENSITIES}, got {density!r}"
        )

    cards = produce_lens_cards(paths)
    if density == "compact":
        cards = [
            {
                key: value
                for key, value in card.items()
                if key != "does_not_establish"
            }
            for card in cards
        ]

    return {
        "kind": "lenskit.lens_card_collection",
        "version": "1.0",
        "authority": AUTHORITY,
        "canonicality": CANONICALITY,
        "density": density,
        "cards": cards,
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }


def produce_lens_cards(paths: Iterable[str | PurePosixPath]) -> list[dict[str, Any]]:
    """Produce a sorted, deduplicated in-memory list of Lens Cards."""
    if isinstance(paths, (str, bytes, bytearray, os.PathLike)):
        raise TypeError(
            "paths must be an iterable of path values, not one path-like value; "
            "use produce_lens_card() for a single path"
        )

    cards_by_path: dict[str, dict[str, Any]] = {}
    for path in paths:
        card = produce_lens_card(path)
        cards_by_path.setdefault(card["path"], card)

    return [cards_by_path[path] for path in sorted(cards_by_path)]
