import copy
import json
from pathlib import Path, PurePosixPath

import pytest

from merger.repoground.core.concept_cards import (
    AUTHORITY,
    CANONICALITY,
    CARD_TYPES,
    DEFAULT_CONCEPT_CARD_SPECS,
    DOES_NOT_ESTABLISH,
    KIND,
    VERSION,
    produce_concept_card,
    produce_concept_cards,
    produce_default_concept_cards,
)


def _schema() -> dict:
    schema_path = Path(__file__).parent.parent / "contracts" / "concept-card.v1.schema.json"
    return json.loads(schema_path.read_text(encoding="utf-8"))


def _validate(card: dict) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.validate(instance=card, schema=_schema())


def _assert_invalid(card: dict) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=card, schema=_schema())


def _spec(card_type: str = "concept", card_id: str = "concept.canonical-truth") -> dict:
    base = {
        "card_type": card_type,
        "card_id": card_id,
        "title": "Canonical truth",
        "summary": "The canonical Markdown is the content source for the emitted bundle.",
        "navigation_refs": [
            {"kind": "repo_path", "target": "docs/architecture/lens-model.md"},
            {"kind": "artifact_role", "target": "canonical_md"},
        ],
    }
    if card_type == "concept":
        base.update({"aliases": ["merge.md", "canonical_md"], "related_card_ids": []})
    elif card_type == "dependency":
        base.update(
            {
                "from_card_id": "concept.canonical-truth",
                "to_card_id": "concept.citation-range",
                "relation": "range citations derive their addressability from canonical content",
            }
        )
    elif card_type == "failure":
        base.update(
            {
                "symptoms": ["citation resolves to the wrong range"],
                "diagnostic_entrypoints": ["citation_map", "range_resolver"],
            }
        )
    elif card_type == "query":
        base.update({"query_patterns": ["Where is canonical truth defined?"]})
    return base


def test_schema_validates_concept_card() -> None:
    card = produce_concept_card(_spec())
    assert card["kind"] == KIND
    assert card["version"] == VERSION
    assert card["authority"] == AUTHORITY
    assert card["canonicality"] == CANONICALITY
    assert card["card_id"] == "concept.canonical-truth"
    assert card["card_type"] == "concept"
    assert card["source_rule"] == "concept_card_registry_v1"
    assert card["derivation_type"] == "direct"
    assert card["payload"] == {
        "aliases": ["canonical_md", "merge.md"],
        "related_card_ids": [],
    }
    assert card["does_not_establish"] == list(DOES_NOT_ESTABLISH)
    _validate(card)


@pytest.mark.parametrize(
    ("card_type", "card_id", "expected_payload_key"),
    [
        ("concept", "concept.canonical-truth", "aliases"),
        ("dependency", "dependency.canonical-to-range", "relation"),
        ("failure", "failure.citation-range-drift", "symptoms"),
        ("query", "query.canonical-truth", "query_patterns"),
    ],
)
def test_schema_validates_all_card_types(
    card_type: str, card_id: str, expected_payload_key: str
) -> None:
    card = produce_concept_card(_spec(card_type, card_id))
    assert card["card_type"] == card_type
    assert expected_payload_key in card["payload"]
    _validate(card)


def test_default_concept_cards_cover_all_card_types() -> None:
    cards = produce_default_concept_cards()
    assert [card["card_type"] for card in cards] == [
        "concept",
        "concept",
        "dependency",
        "failure",
        "query",
    ]
    assert len(DEFAULT_CONCEPT_CARD_SPECS) == 5
    for card in cards:
        _validate(card)


def test_default_concept_cards_do_not_have_dangling_card_refs() -> None:
    cards = produce_default_concept_cards()
    card_ids = {card["card_id"] for card in cards}

    referenced_ids: set[str] = set()
    for card in cards:
        for ref in card["navigation_refs"]:
            if ref["kind"] == "card_id":
                referenced_ids.add(ref["target"])
        payload = card["payload"]
        for key in ("from_card_id", "to_card_id"):
            if key in payload:
                referenced_ids.add(payload[key])
        for value in payload.get("related_card_ids", []):
            referenced_ids.add(value)

    assert referenced_ids <= card_ids


def test_card_types_are_pinned() -> None:
    assert CARD_TYPES == ("concept", "dependency", "failure", "query")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("kind", "lenskit.lens_card"),
        ("version", "2.0"),
        ("authority", "canonical_content"),
        ("canonicality", "content_source"),
        ("source_rule", "heuristic_scan"),
        ("derivation_type", "heuristic"),
    ],
)
def test_schema_rejects_wrong_root_constants(field: str, value: str) -> None:
    card = produce_concept_card(_spec())
    card[field] = value
    _assert_invalid(card)


def test_schema_rejects_payload_shape_that_does_not_match_card_type() -> None:
    card = produce_concept_card(_spec("query", "query.canonical-truth"))
    card["payload"] = {"aliases": []}
    _assert_invalid(card)


def test_schema_rejects_missing_negative_semantics() -> None:
    card = produce_concept_card(_spec())
    del card["does_not_establish"]
    _assert_invalid(card)


def test_schema_rejects_reordered_negative_semantics() -> None:
    card = produce_concept_card(_spec())
    card["does_not_establish"] = list(reversed(DOES_NOT_ESTABLISH))
    _assert_invalid(card)


def test_schema_rejects_unknown_root_field() -> None:
    card = produce_concept_card(_spec())
    card["extra"] = True
    _assert_invalid(card)


def test_producer_sorts_and_deduplicates_navigation_refs_and_text_lists() -> None:
    spec = _spec()
    spec["aliases"] = [" merge.md ", "canonical_md", "merge.md"]
    spec["navigation_refs"] = [
        {"kind": "repo_path", "target": PurePosixPath("docs/architecture/lens-model.md")},
        {"kind": "artifact_role", "target": "canonical_md"},
        {"kind": "artifact_role", "target": "canonical_md"},
    ]

    card = produce_concept_card(spec)

    assert card["payload"]["aliases"] == ["canonical_md", "merge.md"]
    assert card["navigation_refs"] == [
        {"kind": "artifact_role", "target": "canonical_md"},
        {"kind": "repo_path", "target": "docs/architecture/lens-model.md"},
    ]
    _validate(card)


def test_batch_output_is_sorted_and_deduplicated_by_card_id() -> None:
    cards = produce_concept_cards(
        [
            _spec("query", "query.canonical-truth"),
            _spec("concept", "concept.canonical-truth"),
            _spec("query", "query.canonical-truth"),
        ]
    )
    assert [card["card_id"] for card in cards] == [
        "concept.canonical-truth",
        "query.canonical-truth",
    ]


def test_batch_rejects_single_mapping_instead_of_iterable() -> None:
    with pytest.raises(TypeError, match="iterable"):
        produce_concept_cards(_spec())  # type: ignore[arg-type]


def test_batch_rejects_conflicting_duplicate_card_id() -> None:
    first = _spec("query", "query.canonical-truth")
    second = _spec("query", "query.canonical-truth")
    second["title"] = "Different title"

    with pytest.raises(ValueError, match="card_id collision"):
        produce_concept_cards([first, second])

@pytest.mark.parametrize("bad_path", ["a//b", "../secret.md", "/abs/path.md", "a\\b"])
def test_repo_path_navigation_refs_use_facet_path_gate(bad_path: str) -> None:
    spec = _spec()
    spec["navigation_refs"] = [{"kind": "repo_path", "target": bad_path}]
    with pytest.raises(ValueError):
        produce_concept_card(spec)


def test_query_card_requires_query_pattern() -> None:
    spec = _spec("query", "query.canonical-truth")
    spec["query_patterns"] = []
    with pytest.raises(ValueError, match="query_patterns"):
        produce_concept_card(spec)


def test_producer_does_not_mutate_returned_cards_between_calls() -> None:
    spec = _spec()
    card = produce_concept_card(spec)
    mutated = copy.deepcopy(card)
    mutated["payload"]["aliases"].append("mutated")

    assert produce_concept_card(spec) == card
    assert mutated != card
