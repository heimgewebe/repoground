"""Concept Cards v1 — deterministic task-navigation cards for agents.

Concept Cards are compact navigation objects for four task-facing card types:

* ``concept``: glossary-like repo concepts such as canonical truth or range refs.
* ``dependency``: a human-scale dependency axis, not a runtime dependency proof.
* ``failure``: a known failure mode with symptoms and diagnostic entrypoints.
* ``query``: a reusable question shape with likely navigation targets.

The producer performs no repository scan, executes no code, reads no files and
infers no hidden semantics. It only validates and projects explicitly supplied
registry specs into a strict, schema-shaped, deterministic navigation surface.
"""
from __future__ import annotations

import os
import re
from collections.abc import Iterable, Mapping
from pathlib import PurePosixPath
from typing import Any

from merger.repoground.core.lens_facets import infer_facets

KIND = "lenskit.concept_card"
VERSION = "1.0"
AUTHORITY = "navigation_index"
CANONICALITY = "derived"
SOURCE_RULE = "concept_card_registry_v1"
DERIVATION_TYPE = "direct"

CARD_TYPES = ("concept", "dependency", "failure", "query")
NAVIGATION_REF_KINDS = ("repo_path", "artifact_role", "card_id", "query")

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
    "runtime_dependency",
    "causality",
    "security_assessment",
)

DEFAULT_CONCEPT_CARD_SPECS: tuple[dict[str, Any], ...] = (
    {
        "card_type": "concept",
        "card_id": "concept.canonical-truth",
        "title": "Canonical truth",
        "summary": "The canonical Markdown is the content source for emitted bundle navigation.",
        "aliases": ["canonical_md", "merge.md"],
        "related_card_ids": ["concept.citation-range"],
        "navigation_refs": [
            {"kind": "artifact_role", "target": "canonical_md"},
            {"kind": "repo_path", "target": "docs/architecture/lens-model.md"},
        ],
    },
    {
        "card_type": "concept",
        "card_id": "concept.citation-range",
        "title": "Citation range",
        "summary": "A citation range is a stable navigation address that must resolve back to canonical content.",
        "aliases": ["citation_id", "canonical_range", "range_ref"],
        "related_card_ids": ["concept.canonical-truth"],
        "navigation_refs": [
            {"kind": "artifact_role", "target": "citation_map_jsonl"},
            {"kind": "repo_path", "target": "merger/repoground/core/citation_map.py"},
            {"kind": "repo_path", "target": "merger/repoground/core/range_resolver.py"},
        ],
    },
    {
        "card_type": "dependency",
        "card_id": "dependency.canonical-to-citation-range",
        "title": "Canonical content to citation ranges",
        "summary": "Citation ranges are useful only when their addressability is tied back to canonical content.",
        "from_card_id": "concept.canonical-truth",
        "to_card_id": "concept.citation-range",
        "relation": "citation addressability depends on canonical content ranges",
        "navigation_refs": [
            {"kind": "card_id", "target": "concept.canonical-truth"},
            {"kind": "repo_path", "target": "merger/repoground/core/citation_map.py"},
            {"kind": "repo_path", "target": "merger/repoground/core/range_resolver.py"},
        ],
    },
    {
        "card_type": "failure",
        "card_id": "failure.citation-range-drift",
        "title": "Citation range drift",
        "summary": "A citation may remain syntactically valid while pointing at the wrong or stale content range.",
        "symptoms": [
            "citation resolves but quoted evidence looks unrelated",
            "range validation passes only against an unexpected canonical slice",
        ],
        "diagnostic_entrypoints": ["citation_map", "range_resolver", "bundle_surface_validation"],
        "navigation_refs": [
            {"kind": "repo_path", "target": "merger/repoground/core/citation_map.py"},
            {"kind": "repo_path", "target": "merger/repoground/core/citation_validate.py"},
            {"kind": "repo_path", "target": "merger/repoground/core/bundle_surface_validate.py"},
        ],
    },
    {
        "card_type": "query",
        "card_id": "query.find-task-entrypoint",
        "title": "Find a task entrypoint",
        "summary": "Reusable question shape for locating the smallest useful start surface for an agent task.",
        "query_patterns": [
            "Where should an agent start for this task?",
            "Which card, file, or artifact role is the safest first read?",
        ],
        "navigation_refs": [
            {"kind": "artifact_role", "target": "agent_reading_pack"},
            {"kind": "artifact_role", "target": "claim_evidence_map_json"},
            {"kind": "query", "target": "task entrypoint"},
        ],
    },
)

_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._:-]{1,119}$")
_WS_PATTERN = re.compile(r"\s+")


def _clean_text(value: Any, *, field: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    text = _WS_PATTERN.sub(" ", value.strip())
    if not text:
        raise ValueError(f"{field} must not be empty")
    return text


def _clean_optional_text(value: Any, *, field: str) -> str | None:
    if value is None:
        return None
    return _clean_text(value, field=field)


def _clean_id(value: Any, *, field: str) -> str:
    text = _clean_text(value, field=field)
    if not _ID_PATTERN.fullmatch(text):
        raise ValueError(
            f"{field} must match {_ID_PATTERN.pattern!r}; got {text!r}"
        )
    return text


def _clean_card_type(value: Any) -> str:
    card_type = _clean_text(value, field="card_type")
    if card_type not in CARD_TYPES:
        raise ValueError(f"card_type must be one of {CARD_TYPES!r}; got {card_type!r}")
    return card_type


def _dedupe_sorted_texts(values: Any, *, field: str) -> list[str]:
    if values is None:
        return []
    if isinstance(values, (str, bytes, bytearray, os.PathLike)):
        raise TypeError(f"{field} must be an iterable of strings, not one string")
    cleaned = {_clean_text(value, field=f"{field}[]") for value in values}
    return sorted(cleaned)


def _canonical_repo_path(value: Any, *, field: str) -> str:
    if isinstance(value, PurePosixPath):
        path = value.as_posix()
    else:
        path = _clean_text(value, field=field)
    # Delegate lexical repo-path acceptance to the public Facet v1 producer.
    # Empty facet output is valid; validation side effects are what matter here.
    infer_facets(path)
    return path


def _project_navigation_ref(raw: Mapping[str, Any]) -> dict[str, str]:
    if not isinstance(raw, Mapping):
        raise TypeError("navigation_refs[] must be mappings")
    kind = _clean_text(raw.get("kind"), field="navigation_refs[].kind")
    if kind not in NAVIGATION_REF_KINDS:
        raise ValueError(
            f"navigation ref kind must be one of {NAVIGATION_REF_KINDS!r}; got {kind!r}"
        )
    target_field = "target" if "target" in raw else "path"
    target = raw.get(target_field)
    if kind == "repo_path":
        target_text = _canonical_repo_path(target, field="navigation_refs[].target")
    elif kind == "artifact_role":
        target_text = _clean_id(target, field="navigation_refs[].target")
    elif kind == "card_id":
        target_text = _clean_id(target, field="navigation_refs[].target")
    else:
        target_text = _clean_text(target, field="navigation_refs[].target")
    return {"kind": kind, "target": target_text}


def _project_navigation_refs(values: Any) -> list[dict[str, str]]:
    if values is None:
        raise ValueError("navigation_refs must not be missing")
    if isinstance(values, Mapping) or isinstance(values, (str, bytes, bytearray, os.PathLike)):
        raise TypeError("navigation_refs must be an iterable of mappings")
    refs = [_project_navigation_ref(value) for value in values]
    if not refs:
        raise ValueError("navigation_refs must not be empty")
    unique = {(ref["kind"], ref["target"]): ref for ref in refs}
    return [unique[key] for key in sorted(unique)]


def _project_payload(card_type: str, spec: Mapping[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if card_type == "concept":
        payload["aliases"] = _dedupe_sorted_texts(spec.get("aliases", []), field="aliases")
        payload["related_card_ids"] = [
            _clean_id(value, field="related_card_ids[]")
            for value in _dedupe_sorted_texts(
                spec.get("related_card_ids", []), field="related_card_ids"
            )
        ]
    elif card_type == "dependency":
        payload["from_card_id"] = _clean_id(spec.get("from_card_id"), field="from_card_id")
        payload["to_card_id"] = _clean_id(spec.get("to_card_id"), field="to_card_id")
        payload["relation"] = _clean_text(spec.get("relation"), field="relation")
    elif card_type == "failure":
        payload["symptoms"] = _dedupe_sorted_texts(spec.get("symptoms", []), field="symptoms")
        payload["diagnostic_entrypoints"] = _dedupe_sorted_texts(
            spec.get("diagnostic_entrypoints", []), field="diagnostic_entrypoints"
        )
    else:
        patterns = _dedupe_sorted_texts(spec.get("query_patterns", []), field="query_patterns")
        if not patterns:
            raise ValueError("query card requires at least one query_patterns entry")
        payload["query_patterns"] = patterns
    return payload


def produce_concept_card(spec: Mapping[str, Any]) -> dict[str, Any]:
    """Project one explicit registry spec into one Concept Card v1.

    The resulting card is a deterministic navigation aid. It is deliberately
    unable to assert truth, completeness, runtime dependency, causality, review
    priority or security status.
    """
    if not isinstance(spec, Mapping):
        raise TypeError("spec must be a mapping")

    card_type = _clean_card_type(spec.get("card_type"))
    card = {
        "kind": KIND,
        "version": VERSION,
        "authority": AUTHORITY,
        "canonicality": CANONICALITY,
        "card_id": _clean_id(spec.get("card_id"), field="card_id"),
        "card_type": card_type,
        "title": _clean_text(spec.get("title"), field="title"),
        "summary": _clean_text(spec.get("summary"), field="summary"),
        "source_rule": SOURCE_RULE,
        "derivation_type": DERIVATION_TYPE,
        "navigation_refs": _project_navigation_refs(spec.get("navigation_refs")),
        "payload": _project_payload(card_type, spec),
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }
    notes = _clean_optional_text(spec.get("notes"), field="notes")
    if notes is not None:
        card["notes"] = notes
    return card


def produce_concept_cards(specs: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Produce sorted cards, deduplicating only identical projections."""
    if isinstance(specs, (Mapping, str, bytes, bytearray, os.PathLike)):
        raise TypeError("specs must be an iterable of mapping specs")

    cards_by_id: dict[str, dict[str, Any]] = {}
    for spec in specs:
        card = produce_concept_card(spec)
        card_id = card["card_id"]
        previous = cards_by_id.get(card_id)
        if previous is not None:
            if previous != card:
                raise ValueError(f"card_id collision: {card_id!r}")
            continue
        cards_by_id[card_id] = card
    return [cards_by_id[card_id] for card_id in sorted(cards_by_id)]


def produce_default_concept_cards() -> list[dict[str, Any]]:
    """Produce the built-in starter set for the four Concept Card v1 surfaces."""
    return produce_concept_cards(DEFAULT_CONCEPT_CARD_SPECS)
