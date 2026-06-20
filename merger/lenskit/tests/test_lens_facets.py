import ast
import json
from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest

from merger.lenskit.core.lens_facets import (
    DERIVATION_TYPES,
    DOES_NOT_ESTABLISH,
    FACET_IDS,
    FACET_SOURCE_RULES,
    KIND,
    SOURCE_RULES,
    V1_DERIVATION_TYPE,
    VERSION,
    _normalize_path,
    infer_facets,
    produce_facet_report,
)
from merger.lenskit.core.lenses import LENS_IDS, infer_lens


def _schema() -> dict:
    schema_path = (
        Path(__file__).parent.parent / "contracts" / "lens-facet.v1.schema.json"
    )
    return json.loads(schema_path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# Rule goldset over REAL tracked repo paths. Hand-written (not derived from the
# producer) so it states what each facet should mean and why others do not.
# --------------------------------------------------------------------------- #
# (path, {facet: source_rule})
_REAL_GOLDSET = [
    # contract: the controlled `.schema.json` extension.
    ("merger/lenskit/contracts/lens-facet.v1.schema.json", {"contract": "contract_schema_suffix"}),
    ("merger/lenskit/contracts/primary-lens-audit.v1.schema.json", {"contract": "contract_schema_suffix"}),
    ("merger/lenskit/contracts/export-safety-report.v1.schema.json", {"contract": "contract_schema_suffix"}),
    # test: real Python and JavaScript test modules.
    ("merger/lenskit/tests/test_lens_facets.py", {"test": "test_module_marker"}),
    ("merger/lenskit/tests/test_primary_lens_audit.py", {"test": "test_module_marker"}),
    ("merger/lenskit/frontends/webui/tests/test_materialize.js", {"test": "test_module_marker"}),
    ("merger/lenskit/frontends/webui/tests/test_pre_pull_payload.js", {"test": "test_module_marker"}),
    # retrieval: real controlled retrieval surfaces, including a retrieval fixture
    # (Variant A: a retrieval-related surface, not a production-status claim).
    ("merger/lenskit/retrieval/review_eval.py", {"retrieval": "retrieval_surface_path"}),
    ("docs/retrieval/review_queries.v1.json", {"retrieval": "retrieval_surface_path"}),
    ("merger/lenskit/tests/fixtures/retrieval/mini_chunk_index.jsonl", {"retrieval": "retrieval_surface_path"}),
    # negative: a real fixture whose name matches a test marker -> NOT a test.
    ("merger/lenskit/tests/fixtures/architecture_import_graph/test_c.py", {}),
    # negative: real test-support helper that is not itself a test module.
    ("merger/lenskit/tests/bundle_fixtures.py", {}),
    # negative: ordinary core source -> no facet.
    ("merger/lenskit/core/lenses.py", {}),
]

# Synthetic capability fixtures: these paths do NOT exist in the repo today.
# They exist only to exercise multi-facet capability and the contract-facet
# boundary; they are NOT evidence of real current multi-facet assignments.
_SYNTHETIC_CAPABILITY = [
    # synthetic: a schema living on the retrieval surface -> contract + retrieval.
    (
        "merger/lenskit/retrieval/retrieval-state.v1.schema.json",
        {"contract": "contract_schema_suffix", "retrieval": "retrieval_surface_path"},
    ),
    # synthetic: a test module on the retrieval surface -> test + retrieval.
    (
        "merger/lenskit/retrieval/test_eval_capability.py",
        {"test": "test_module_marker", "retrieval": "retrieval_surface_path"},
    ),
    # synthetic: a .proto is a contract concept but NOT a v1 `contract` facet.
    ("src/contracts/user.proto", {}),
]

_ALL_GOLDSET = _REAL_GOLDSET + _SYNTHETIC_CAPABILITY


# --------------------------------------------------------------------------- #
# Canonical / non-canonical path tables (shared by core and schema tests).
# --------------------------------------------------------------------------- #
_INVALID_PATHS = [
    "",
    "   ",
    ".",
    "./a.schema.json",
    "a/./b.schema.json",
    "a//b.schema.json",
    "a/",
    "/absolute/path",
    "../x",
    "a/../b",
    r"a\b",
    "C:/foo.schema.json",
    "c:/foo.schema.json",
]

_VALID_PATHS = [
    ".github/workflows/ci.yml",
    "merger/lenskit/core/lenses.py",
    "docs/architecture/lens-model.md",
    "a",
    "a.b",
    "a-b/c_d.schema.json",
]


# --------------------------------------------------------------------------- #
# Contract tests (schema validation; jsonschema is optional in portable
# runtimes, but the reference CI installs it so these run there).
# --------------------------------------------------------------------------- #
def _valid_item() -> dict:
    return {
        "path": "merger/lenskit/contracts/lens-facet.v1.schema.json",
        "facet": "contract",
        "source_rule": "contract_schema_suffix",
        "derivation_type": "direct",
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }


def _report_with_item(item: dict) -> dict:
    return {
        "kind": KIND,
        "version": VERSION,
        "items": [item],
        "summary": {"item_count": 1, "target_count": 1, "facet_counts": {item["facet"]: 1}},
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }


def test_schema_validates_minimal_report():
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.validate(instance=_report_with_item(_valid_item()), schema=_schema())


def test_schema_validates_empty_report():
    jsonschema = pytest.importorskip("jsonschema")
    report = produce_facet_report([])
    assert report["summary"] == {"item_count": 0, "target_count": 0, "facet_counts": {}}
    jsonschema.validate(instance=report, schema=_schema())


def test_schema_validates_generated_report():
    jsonschema = pytest.importorskip("jsonschema")
    report = produce_facet_report([path for path, _ in _ALL_GOLDSET])
    jsonschema.validate(instance=report, schema=_schema())


def test_schema_validates_multi_facet_capability():
    jsonschema = pytest.importorskip("jsonschema")
    report = produce_facet_report(["merger/lenskit/retrieval/test_eval_capability.py"])
    assert {item["facet"] for item in report["items"]} == {"test", "retrieval"}
    jsonschema.validate(instance=report, schema=_schema())


def test_schema_rejects_unknown_facet():
    jsonschema = pytest.importorskip("jsonschema")
    item = _valid_item()
    item["facet"] = "security"
    report = _report_with_item(item)
    report["summary"]["facet_counts"] = {"contract": 1}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=report, schema=_schema())


def test_schema_rejects_derived_in_v1():
    jsonschema = pytest.importorskip("jsonschema")
    item = _valid_item()
    item["derivation_type"] = "derived"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=_report_with_item(item), schema=_schema())


def test_schema_rejects_heuristic_in_v1():
    jsonschema = pytest.importorskip("jsonschema")
    item = _valid_item()
    item["derivation_type"] = "heuristic"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=_report_with_item(item), schema=_schema())


def test_schema_rejects_missing_source_rule():
    jsonschema = pytest.importorskip("jsonschema")
    item = _valid_item()
    del item["source_rule"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=_report_with_item(item), schema=_schema())


def test_schema_rejects_facet_rule_mismatch():
    jsonschema = pytest.importorskip("jsonschema")
    item = _valid_item()
    item["source_rule"] = "test_module_marker"  # wrong rule for facet=contract
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=_report_with_item(item), schema=_schema())


def test_schema_rejects_missing_does_not_establish():
    jsonschema = pytest.importorskip("jsonschema")
    item = _valid_item()
    del item["does_not_establish"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=_report_with_item(item), schema=_schema())


def test_schema_rejects_reordered_does_not_establish():
    jsonschema = pytest.importorskip("jsonschema")
    item = _valid_item()
    item["does_not_establish"] = list(reversed(DOES_NOT_ESTABLISH))
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=_report_with_item(item), schema=_schema())


def test_schema_rejects_truncated_does_not_establish():
    jsonschema = pytest.importorskip("jsonschema")
    item = _valid_item()
    item["does_not_establish"] = list(DOES_NOT_ESTABLISH)[:8]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=_report_with_item(item), schema=_schema())


def test_schema_rejects_extended_does_not_establish():
    jsonschema = pytest.importorskip("jsonschema")
    item = _valid_item()
    item["does_not_establish"] = list(DOES_NOT_ESTABLISH) + ["extra"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=_report_with_item(item), schema=_schema())


def test_schema_rejects_duplicate_items():
    jsonschema = pytest.importorskip("jsonschema")
    report = _report_with_item(_valid_item())
    report["items"] = [_valid_item(), _valid_item()]
    report["summary"] = {"item_count": 2, "target_count": 1, "facet_counts": {"contract": 2}}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=report, schema=_schema())


def test_schema_rejects_additional_item_field():
    jsonschema = pytest.importorskip("jsonschema")
    item = _valid_item()
    item["review_priority"] = "high"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=_report_with_item(item), schema=_schema())


def test_schema_rejects_wrong_kind():
    jsonschema = pytest.importorskip("jsonschema")
    report = _report_with_item(_valid_item())
    report["kind"] = "lenskit.primary_lens_audit"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=report, schema=_schema())


def test_schema_rejects_wrong_version():
    jsonschema = pytest.importorskip("jsonschema")
    report = _report_with_item(_valid_item())
    report["version"] = "2.0"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=report, schema=_schema())


def test_schema_rejects_invalid_summary_key():
    jsonschema = pytest.importorskip("jsonschema")
    report = _report_with_item(_valid_item())
    report["summary"]["facet_counts"] = {"banana": 1}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=report, schema=_schema())


@pytest.mark.parametrize("bad_path", _INVALID_PATHS)
def test_schema_rejects_non_canonical_item_paths(bad_path):
    jsonschema = pytest.importorskip("jsonschema")
    item = _valid_item()
    item["path"] = bad_path
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=_report_with_item(item), schema=_schema())


@pytest.mark.parametrize("good_path", _VALID_PATHS)
def test_schema_accepts_canonical_item_paths(good_path):
    jsonschema = pytest.importorskip("jsonschema")
    item = _valid_item()
    item["path"] = good_path
    jsonschema.validate(instance=_report_with_item(item), schema=_schema())


# --------------------------------------------------------------------------- #
# Python <-> schema vocabulary parity (catches core/schema drift).
# --------------------------------------------------------------------------- #
def test_facet_enum_parity():
    item = _schema()["definitions"]["item"]
    assert item["properties"]["facet"]["enum"] == list(FACET_IDS)


def test_source_rule_enum_parity():
    item = _schema()["definitions"]["item"]
    assert item["properties"]["source_rule"]["enum"] == list(SOURCE_RULES)


def test_facet_counts_enum_parity():
    schema = _schema()
    names = schema["properties"]["summary"]["properties"]["facet_counts"]["propertyNames"]
    assert names["enum"] == list(FACET_IDS)


def test_derivation_type_const_parity():
    item = _schema()["definitions"]["item"]
    assert item["properties"]["derivation_type"]["const"] == V1_DERIVATION_TYPE


def test_does_not_establish_canonical_parity():
    dne = _schema()["definitions"]["does_not_establish"]
    consts = [entry["const"] for entry in dne["items"]]
    assert consts == list(DOES_NOT_ESTABLISH)
    assert dne["minItems"] == dne["maxItems"] == len(DOES_NOT_ESTABLISH)
    assert dne["additionalItems"] is False


def test_each_facet_binds_to_exactly_one_rule():
    item = _schema()["definitions"]["item"]
    bindings = {}
    for clause in item["allOf"]:
        facet = clause["if"]["properties"]["facet"]["const"]
        rule = clause["then"]["properties"]["source_rule"]["const"]
        bindings[facet] = rule
    assert bindings == FACET_SOURCE_RULES
    assert set(bindings) == set(FACET_IDS)


# --------------------------------------------------------------------------- #
# Path identity (core): canonical grammar, host-independent, type-gated.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("good_path", _VALID_PATHS)
def test_core_accepts_canonical_paths(good_path):
    assert _normalize_path(good_path) == good_path


@pytest.mark.parametrize("bad_path", _INVALID_PATHS)
def test_core_rejects_non_canonical_paths(bad_path):
    with pytest.raises(ValueError):
        _normalize_path(bad_path)


def test_core_does_not_silently_normalize():
    # These must FAIL, not be rewritten to a/b.
    for noisy in ("./a.schema.json", "a//b.schema.json", "a/./b.schema.json"):
        with pytest.raises(ValueError):
            _normalize_path(noisy)


def test_windows_drive_is_host_independent():
    with pytest.raises(ValueError, match="drive"):
        _normalize_path("C:/foo.schema.json")
    with pytest.raises(ValueError, match="drive"):
        _normalize_path("c:/foo.schema.json")


def test_rejects_pure_windows_relative_path():
    # A PureWindowsPath must NOT be silently coerced to POSIX via as_posix().
    with pytest.raises(TypeError):
        _normalize_path(PureWindowsPath(r"a\b"))


def test_rejects_pure_windows_drive_path():
    with pytest.raises(TypeError):
        _normalize_path(PureWindowsPath("C:/foo"))


def test_accepts_pure_posix_path():
    assert _normalize_path(PurePosixPath("a/b")) == "a/b"


def test_windows_string_and_path_object_are_both_rejected():
    # The string form trips the backslash rule (ValueError); the Windows path
    # object trips the type gate (TypeError). Neither yields a coerced "a/b".
    with pytest.raises(ValueError):
        _normalize_path(r"a\b")
    with pytest.raises(TypeError):
        _normalize_path(PureWindowsPath(r"a\b"))


def test_fixture_and_retrieval_segments_are_exact():
    # Observable behavior: only the exact segment matches, not a substring.
    assert infer_facets("myfixtures/test_x.py") == [
        {
            "path": "myfixtures/test_x.py",
            "facet": "test",
            "source_rule": "test_module_marker",
            "derivation_type": V1_DERIVATION_TYPE,
            "does_not_establish": list(DOES_NOT_ESTABLISH),
        }
    ]  # "myfixtures" is not "fixtures" -> still a test
    assert infer_facets("src/myretrieval/data.json") == []  # not the retrieval segment
    assert [i["facet"] for i in infer_facets("src/retrieval/data.json")] == ["retrieval"]


@pytest.mark.parametrize("bad_type", [None, 123, 1.5, object(), ["a"], {"a": 1}])
def test_core_rejects_non_path_types(bad_type):
    with pytest.raises(TypeError):
        _normalize_path(bad_type)


def test_produce_report_rejects_non_path_types():
    with pytest.raises(TypeError):
        produce_facet_report([None])


def test_accepts_str_and_purepath_objects():
    str_report = produce_facet_report(["merger/lenskit/retrieval/review_eval.py"])
    path_report = produce_facet_report([Path("merger/lenskit/retrieval/review_eval.py")])
    pure_report = produce_facet_report([PurePosixPath("merger/lenskit/retrieval/review_eval.py")])
    assert str_report == path_report == pure_report


def _imports_lens_audit(py_path: Path) -> bool:
    """AST check: does the module import anything from/as lens_audit?"""
    tree = ast.parse(py_path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any("lens_audit" in alias.name for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            if node.module and "lens_audit" in node.module:
                return True
    return False


def test_facet_module_does_not_import_lens_audit():
    # AST guard (robust to multiline/aliased imports): neither the producer nor
    # this test may couple to lens_audit, especially its private _normalize_path.
    core = Path(__file__).parent.parent / "core" / "lens_facets.py"
    assert not _imports_lens_audit(core)
    assert not _imports_lens_audit(Path(__file__))


# --------------------------------------------------------------------------- #
# Semantic tests: rule goldset, positives, negatives, multi-facet capability.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("path,expected", _ALL_GOLDSET)
def test_goldset_facets_and_rules(path, expected):
    items = infer_facets(path)
    got = {item["facet"]: item["source_rule"] for item in items}
    assert got == expected
    for item in items:
        assert item["path"] == path
        assert item["derivation_type"] == V1_DERIVATION_TYPE
        assert item["does_not_establish"] == list(DOES_NOT_ESTABLISH)


def test_real_js_test_module_is_detected():
    items = infer_facets("merger/lenskit/frontends/webui/tests/test_materialize.js")
    assert [item["facet"] for item in items] == ["test"]


def test_fixture_test_marker_is_excluded():
    # The classic false positive: a fixture named test_*.py must NOT be a test.
    assert infer_facets("merger/lenskit/tests/fixtures/architecture_import_graph/test_c.py") == []


def test_retrieval_fixture_is_a_retrieval_surface():
    # Variant A: retrieval fixtures are a retrieval surface (not a test).
    items = infer_facets("merger/lenskit/tests/fixtures/retrieval/mini_chunk_index.jsonl")
    assert [item["facet"] for item in items] == ["retrieval"]


def test_each_v1_facet_has_a_real_positive_example():
    produced = {
        facet
        for path, _ in _REAL_GOLDSET
        for facet in (item["facet"] for item in infer_facets(path))
    }
    assert produced == set(FACET_IDS)


def test_path_without_facet_is_valid_and_empty():
    assert infer_facets("merger/lenskit/core/lenses.py") == []
    report = produce_facet_report(["merger/lenskit/core/lenses.py"])
    assert report["items"] == []
    assert report["summary"]["target_count"] == 0


def test_multi_facet_capability_is_synthetic():
    items = infer_facets("merger/lenskit/retrieval/test_eval_capability.py")
    facets = sorted(item["facet"] for item in items)
    assert facets == ["retrieval", "test"]
    assert len(facets) == len(set(facets))


def test_contract_facet_is_narrower_than_data_models_lens():
    # A .proto is a data_models primary lens but NOT a v1 contract facet.
    assert infer_lens(Path("src/contracts/user.proto")) == "data_models"
    assert infer_facets("src/contracts/user.proto") == []


def test_facets_do_not_restate_primary_lens():
    report = produce_facet_report([path for path, _ in _ALL_GOLDSET])
    payload = json.dumps(report, sort_keys=True)
    # Quoted token form so a path that merely contains "primary_lens" does not trip.
    assert '"primary_lens"' not in payload
    assert '"matched_rule"' not in payload


def test_only_controlled_vocabulary_is_emitted():
    report = produce_facet_report([path for path, _ in _ALL_GOLDSET])
    for item in report["items"]:
        assert item["facet"] in FACET_IDS
        assert item["source_rule"] in SOURCE_RULES
        assert item["derivation_type"] in DERIVATION_TYPES


def test_no_excluded_or_authority_fields():
    report = produce_facet_report([path for path, _ in _ALL_GOLDSET])
    payload = json.dumps(report, sort_keys=True)
    forbidden_facets = (
        '"security"', '"claim_boundary"', '"artifact_surface"', '"diagnostic"',
        '"uncertainty"', '"unknown"', '"other"', '"unclassified"',
    )
    for fragment in forbidden_facets:
        assert fragment not in payload
    forbidden_claims = (
        '"verdict"', '"approved"', '"requires_fix"', '"confidence"',
        '"confidence_class"', '"safe": true', '"critical": true',
        '"impact": true', '"covered": true', '"reviewed": true',
    )
    for fragment in forbidden_claims:
        assert fragment not in payload


def test_v1_producer_only_emits_direct():
    report = produce_facet_report([path for path, _ in _ALL_GOLDSET])
    assert {item["derivation_type"] for item in report["items"]} == {V1_DERIVATION_TYPE}


def test_primary_lens_surface_is_unchanged():
    assert LENS_IDS == [
        "entrypoints",
        "core",
        "interfaces",
        "data_models",
        "pipelines",
        "ui",
        "guards",
    ]
    assert infer_lens(Path("merger/lenskit/core/lenses.py")) == "core"
    assert infer_lens(Path("merger/lenskit/contracts/x.schema.json")) == "data_models"


# --------------------------------------------------------------------------- #
# Summary tests (mechanical) + boundary note.
# --------------------------------------------------------------------------- #
def test_summary_counts_are_mechanical():
    report = produce_facet_report(
        [
            "merger/lenskit/contracts/a.schema.json",
            "merger/lenskit/contracts/b.schema.json",
            "merger/lenskit/retrieval/test_x_capability.py",  # test + retrieval (2 facets, 1 path)
            "merger/lenskit/core/lenses.py",  # no facet
        ]
    )
    assert report["summary"]["item_count"] == 4
    assert report["summary"]["target_count"] == 3
    assert report["summary"]["facet_counts"] == {"contract": 2, "retrieval": 1, "test": 1}
    assert list(report["summary"]["facet_counts"]) == sorted(report["summary"]["facet_counts"])


def test_summary_coherence_is_a_producer_invariant():
    # The schema validates summary TYPE/SHAPE only; it does not (and JSON Schema
    # draft-07 cannot) recompute the counters against items. Coherence is the
    # producer's invariant, asserted here directly.
    report = produce_facet_report([path for path, _ in _ALL_GOLDSET])
    assert report["summary"]["item_count"] == len(report["items"])
    assert report["summary"]["target_count"] == len({i["path"] for i in report["items"]})


# --------------------------------------------------------------------------- #
# Determinism tests.
# --------------------------------------------------------------------------- #
_DET_PATHS = [
    "merger/lenskit/retrieval/test_eval_capability.py",
    "merger/lenskit/contracts/a.schema.json",
    "docs/retrieval/queries.json",
    "merger/lenskit/tests/test_x.py",
    "merger/lenskit/core/lenses.py",
]


def test_input_order_does_not_change_output():
    assert produce_facet_report(_DET_PATHS) == produce_facet_report(list(reversed(_DET_PATHS)))


def test_duplicate_paths_are_deduplicated():
    assert produce_facet_report(_DET_PATHS) == produce_facet_report(_DET_PATHS + _DET_PATHS)


def test_repeated_runs_are_identical():
    assert produce_facet_report(_DET_PATHS) == produce_facet_report(_DET_PATHS)


def test_items_are_sorted_by_path_then_facet():
    report = produce_facet_report(_DET_PATHS)
    keys = [(item["path"], item["facet"]) for item in report["items"]]
    assert keys == sorted(keys)


def test_no_duplicate_path_facet_pairs():
    report = produce_facet_report(_DET_PATHS + _DET_PATHS)
    keys = [(item["path"], item["facet"]) for item in report["items"]]
    assert len(keys) == len(set(keys))


def test_inputs_are_not_mutated():
    paths = list(_DET_PATHS)
    produce_facet_report(paths)
    assert paths == _DET_PATHS


def test_report_top_level_shape():
    report = produce_facet_report(_DET_PATHS)
    assert report["kind"] == KIND
    assert report["version"] == VERSION
    assert report["does_not_establish"] == list(DOES_NOT_ESTABLISH)
    assert set(report["summary"]) == {"item_count", "target_count", "facet_counts"}
