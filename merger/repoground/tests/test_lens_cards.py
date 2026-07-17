import ast
import copy
import json
from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest

from merger.repoground.core.lens_cards import (
    AUTHORITY,
    CANONICALITY,
    KIND,
    VERSION,
    produce_lens_card,
    produce_lens_cards,
)
from merger.repoground.core.lens_facets import (
    DOES_NOT_ESTABLISH,
    FACET_IDS,
    FACET_SOURCE_RULES,
    SOURCE_RULES,
    V1_DERIVATION_TYPE,
)
from merger.repoground.core.lenses import LENS_IDS


def _schema() -> dict:
    schema_path = Path(__file__).parent.parent / "contracts" / "lens-card.v1.schema.json"
    return json.loads(schema_path.read_text(encoding="utf-8"))


def _validate(card: dict) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.validate(instance=card, schema=_schema())


def _assert_invalid(card: dict) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=card, schema=_schema())


def _valid_card(path: str = "merger/repoground/contracts/lens-card.v1.schema.json") -> dict:
    return produce_lens_card(path)


def _facet(facet: str, source_rule: str | None = None) -> dict:
    return {
        "facet": facet,
        "source_rule": source_rule or FACET_SOURCE_RULES[facet],
        "derivation_type": V1_DERIVATION_TYPE,
    }


def test_schema_validates_minimal_card() -> None:
    card = _valid_card()
    assert card["kind"] == KIND
    assert card["version"] == VERSION
    assert card["authority"] == AUTHORITY
    assert card["canonicality"] == CANONICALITY
    assert card["path"] == "merger/repoground/contracts/lens-card.v1.schema.json"
    assert card["primary_lens"] == "data_models"
    assert card["matched_rule"]
    assert card["facets"] == [_facet("contract")]
    assert card["navigation_refs"] == [{"kind": "repo_path", "target": card["path"]}]
    assert card["does_not_establish"] == list(DOES_NOT_ESTABLISH)
    _validate(card)


def test_schema_validates_card_with_empty_facet_list() -> None:
    card = _valid_card("merger/repoground/core/lenses.py")
    assert card["primary_lens"] == "core"
    assert card["facets"] == []
    _validate(card)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("kind", "lenskit.lens_facet_report"),
        ("version", "2.0"),
        ("authority", "canonical_content"),
        ("canonicality", "content_source"),
    ],
)
def test_schema_rejects_wrong_root_constants(field: str, value: str) -> None:
    card = _valid_card()
    card[field] = value
    _assert_invalid(card)


def test_schema_rejects_unknown_primary_lens() -> None:
    card = _valid_card()
    card["primary_lens"] = "security"
    _assert_invalid(card)


def test_schema_rejects_empty_matched_rule() -> None:
    card = _valid_card()
    card["matched_rule"] = ""
    _assert_invalid(card)


def test_schema_rejects_unknown_facet() -> None:
    card = _valid_card()
    card["facets"] = [
        {
            "facet": "security",
            "source_rule": "contract_schema_suffix",
            "derivation_type": V1_DERIVATION_TYPE,
        }
    ]
    _assert_invalid(card)


def test_schema_rejects_unknown_source_rule() -> None:
    card = _valid_card()
    card["facets"][0]["source_rule"] = "security_marker"
    _assert_invalid(card)


def test_schema_rejects_facet_source_rule_mismatch() -> None:
    card = _valid_card()
    card["facets"][0]["source_rule"] = "test_module_marker"
    _assert_invalid(card)


@pytest.mark.parametrize("derivation_type", ["derived", "heuristic"])
def test_schema_rejects_non_direct_derivation_types(derivation_type: str) -> None:
    card = _valid_card()
    card["facets"][0]["derivation_type"] = derivation_type
    _assert_invalid(card)


def test_schema_rejects_duplicate_facet_assignments() -> None:
    card = _valid_card()
    card["facets"] = [_facet("contract"), _facet("contract")]
    _assert_invalid(card)


def test_schema_rejects_missing_negative_semantics() -> None:
    card = _valid_card()
    del card["does_not_establish"]
    _assert_invalid(card)


def test_schema_rejects_reordered_negative_semantics() -> None:
    card = _valid_card()
    card["does_not_establish"] = list(reversed(DOES_NOT_ESTABLISH))
    _assert_invalid(card)


def test_schema_rejects_extra_negative_semantics() -> None:
    card = _valid_card()
    card["does_not_establish"] = list(DOES_NOT_ESTABLISH) + ["repo_understood"]
    _assert_invalid(card)


def test_schema_rejects_formally_wrong_navigation_ref() -> None:
    card = _valid_card()
    card["navigation_refs"][0]["target"] = "a//b"
    _assert_invalid(card)


def test_schema_rejects_unknown_navigation_ref_type() -> None:
    card = _valid_card()
    card["navigation_refs"][0]["kind"] = "evidence"
    _assert_invalid(card)


@pytest.mark.parametrize(
    ("container", "field"),
    [
        ("root", "extra"),
        ("facet", "extra"),
        ("navigation_ref", "extra"),
    ],
)
def test_schema_rejects_unknown_root_and_item_fields(container: str, field: str) -> None:
    card = _valid_card()
    if container == "root":
        card[field] = True
    elif container == "facet":
        card["facets"][0][field] = True
    else:
        card["navigation_refs"][0][field] = True
    _assert_invalid(card)


@pytest.mark.parametrize(
    "field",
    [
        "confidence",
        "confidence_class",
        "relations",
        "states",
        "task_context",
        "evidence_refs",
        "score",
        "priority",
        "risk",
        "severity",
        "verdict",
        "approved",
        "reviewed",
        "safe",
        "unsafe",
        "complete",
        "covered",
        "critical",
        "impact",
        "breaks",
        "requires_fix",
        "fix",
    ],
)
def test_schema_rejects_forbidden_judgement_fields(field: str) -> None:
    card = _valid_card()
    card[field] = True
    _assert_invalid(card)


@pytest.mark.parametrize(
    ("path", "expected_lens", "expected_facets"),
    [
        ("merger/repoground/core/lenses.py", "core", []),
        (
            "merger/repoground/contracts/lens-card.v1.schema.json",
            "data_models",
            ["contract"],
        ),
        ("merger/repoground/tests/test_lens_cards.py", "guards", ["test"]),
        ("merger/repoground/retrieval/review_eval.py", "core", ["retrieval"]),
        ("docs/architecture/lens-model.md", "entrypoints", []),
    ],
)
def test_producer_real_repo_paths(
    path: str,
    expected_lens: str,
    expected_facets: list[str],
) -> None:
    card = produce_lens_card(path)
    assert card["path"] == path
    assert card["primary_lens"] == expected_lens
    assert [item["facet"] for item in card["facets"]] == expected_facets
    assert card["navigation_refs"] == [{"kind": "repo_path", "target": path}]
    _validate(card)


def test_producer_synthetic_multi_facet_path() -> None:
    card = produce_lens_card("merger/repoground/retrieval/test_eval_capability.py")
    assert [item["facet"] for item in card["facets"]] == ["retrieval", "test"]
    _validate(card)


def test_same_input_yields_same_card() -> None:
    path = "merger/repoground/retrieval/test_eval_capability.py"
    assert produce_lens_card(path) == produce_lens_card(path)


def test_batch_order_does_not_change_output() -> None:
    paths = [
        "docs/architecture/lens-model.md",
        "merger/repoground/contracts/lens-card.v1.schema.json",
        "merger/repoground/retrieval/test_eval_capability.py",
        "merger/repoground/core/lenses.py",
    ]
    assert produce_lens_cards(paths) == produce_lens_cards(reversed(paths))


def test_batch_deduplicates_paths() -> None:
    paths = [
        "merger/repoground/core/lenses.py",
        PurePosixPath("merger/repoground/core/lenses.py"),
        "merger/repoground/core/lenses.py",
    ]
    cards = produce_lens_cards(paths)
    assert [card["path"] for card in cards] == ["merger/repoground/core/lenses.py"]


def test_batch_accepts_generator() -> None:
    paths = (path for path in ["merger/repoground/core/lenses.py"])
    assert [card["path"] for card in produce_lens_cards(paths)] == [
        "merger/repoground/core/lenses.py"
    ]


@pytest.mark.parametrize(
    "single",
    [
        "merger/repoground/core/lenses.py",
        b"merger/repoground/core/lenses.py",
        bytearray(b"merger/repoground/core/lenses.py"),
        PurePosixPath("merger/repoground/core/lenses.py"),
        Path("merger/repoground/core/lenses.py"),
        PureWindowsPath("merger/repoground/core/lenses.py"),
    ],
)
def test_batch_rejects_single_path_like_argument(single: object) -> None:
    with pytest.raises(TypeError, match="iterable"):
        produce_lens_cards(single)  # type: ignore[arg-type]


def test_batch_empty_input_yields_empty_list() -> None:
    assert produce_lens_cards([]) == []


def test_batch_does_not_mutate_input_list() -> None:
    paths = ["merger/repoground/core/lenses.py"]
    original = list(paths)
    produce_lens_cards(paths)
    assert paths == original


def test_bad_element_inside_batch_is_not_swallowed() -> None:
    with pytest.raises(ValueError):
        produce_lens_cards(["merger/repoground/core/lenses.py", "a//b"])


def test_unicode_emoji_and_zwj_paths_remain_valid() -> None:
    emoji = "docs/" + chr(0x1F50D) + ".md"
    zwj = (
        "docs/"
        + chr(0x1F468)
        + chr(0x200D)
        + chr(0x1F469)
        + chr(0x200D)
        + chr(0x1F467)
        + ".md"
    )
    assert produce_lens_card(emoji)["path"] == emoji
    assert produce_lens_card(zwj)["path"] == zwj


@pytest.mark.parametrize(
    "bad_path",
    [
        "a" + chr(0x00) + "b",
        "a" + chr(0x1F) + "b",
        "a" + chr(0x7F) + "b",
        "a" + chr(0x80) + "b",
        "a" + chr(0x85) + "b",
        "a" + chr(0x9F) + "b",
        "a" + chr(0x2028) + "b",
        "a" + chr(0x2029) + "b",
        "a" + chr(0xFEFF) + "b",
        "a" + chr(0xD800) + "b",
        "a" + chr(0xDCFF) + "b",
    ],
)
def test_control_separator_bom_and_surrogate_paths_are_rejected(bad_path: str) -> None:
    with pytest.raises(ValueError):
        produce_lens_card(bad_path)


def test_lens_and_facet_ids_are_unchanged() -> None:
    assert LENS_IDS == [
        "entrypoints",
        "core",
        "interfaces",
        "data_models",
        "pipelines",
        "ui",
        "guards",
    ]
    assert FACET_IDS == ("contract", "test", "retrieval")


def test_producer_uses_public_primary_lens_explanation(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_explain(path: str) -> tuple[str, str]:
        calls.append(path)
        return "ui", "controlled-existing-rule"

    monkeypatch.setattr(
        "merger.repoground.core.lens_cards.explain_primary_lens", fake_explain
    )

    card = produce_lens_card("docs/page.md")

    assert calls == ["docs/page.md"]
    assert card["primary_lens"] == "ui"
    assert card["matched_rule"] == "controlled-existing-rule"


def test_producer_uses_public_infer_facets(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[object] = []

    def fake_infer(path: object) -> list[dict]:
        calls.append(path)
        return [
            {
                "path": str(path),
                "facet": "retrieval",
                "source_rule": "retrieval_surface_path",
                "derivation_type": "direct",
                "does_not_establish": ["not projected"],
            }
        ]

    monkeypatch.setattr(
        "merger.repoground.core.lens_cards.infer_facets", fake_infer
    )

    card = produce_lens_card("docs/page.md")

    assert calls == ["docs/page.md"]
    assert card["facets"] == [_facet("retrieval")]


def _imports_private_or_rule_engine(py_path: Path) -> list[str]:
    tree = ast.parse(py_path.read_text(encoding="utf-8"))
    findings: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module.startswith("merger.repoground.core."):
                for alias in node.names:
                    if alias.name.startswith("_"):
                        findings.append(f"private import {module}.{alias.name}")
                    if alias.name == "infer_lens":
                        findings.append("direct infer_lens import")
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            for marker in (
                ".schema.json",
                "test_module_marker",
                "retrieval_surface_path",
                "contracts/schemas/models/types",
                "workflow marker",
            ):
                if marker in node.value:
                    findings.append(f"copied rule marker {marker}")
    return findings


def test_lens_card_module_imports_no_private_helpers_or_classification_rules() -> None:
    core = Path(__file__).parent.parent / "core" / "lens_cards.py"
    assert _imports_private_or_rule_engine(core) == []


def test_producer_does_not_mutate_returned_cards_between_calls() -> None:
    card = produce_lens_card("merger/repoground/contracts/lens-card.v1.schema.json")
    mutated = copy.deepcopy(card)
    mutated["facets"].append(_facet("retrieval"))

    assert produce_lens_card(card["path"]) == card
    assert mutated != card


def test_contract_vocabulary_parity() -> None:
    schema = _schema()
    assert schema["properties"]["primary_lens"]["enum"] == LENS_IDS
    facet_def = schema["definitions"]["facet"]
    assert facet_def["properties"]["facet"]["enum"] == list(FACET_IDS)
    assert facet_def["properties"]["source_rule"]["enum"] == list(SOURCE_RULES)
    assert facet_def["properties"]["derivation_type"]["const"] == V1_DERIVATION_TYPE
    bindings = {
        clause["if"]["properties"]["facet"]["const"]: clause["then"]["properties"][
            "source_rule"
        ]["const"]
        for clause in facet_def["allOf"]
    }
    assert bindings == FACET_SOURCE_RULES
