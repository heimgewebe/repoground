import json
from pathlib import Path

import pytest

from merger.lenskit.architecture.graph_quality_eval import (
    GraphQualityGoldsetError,
    evaluate_graph_quality_fixture,
    load_graph_quality_goldset,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
GOLDSET_PATH = REPO_ROOT / "docs/retrieval/graph_quality_goldset.v1.json"
BASELINE_PATH = REPO_ROOT / "docs/diagnostics/graph-quality-baseline.v1.json"


def _load():
    goldset = load_graph_quality_goldset(GOLDSET_PATH)
    return goldset, REPO_ROOT / goldset["fixture_root"]


def test_goldset_references_existing_fixture_sources():
    goldset, fixture_root = _load()
    paths = {case["source"] for case in goldset["local_resolution_cases"]}
    paths.update(case["target"] for case in goldset["local_resolution_cases"])
    paths.update(
        case["source"] for case in goldset["external_preservation_cases"]
    )
    for case in goldset["external_preservation_cases"]:
        paths.update(case.get("forbidden_targets", []))
    paths.update(case["path"] for case in goldset["layer_cases"])
    paths.update(case["path"] for case in goldset["parse_failure_cases"])

    for relative_path in sorted(paths):
        assert (fixture_root / relative_path).is_file(), relative_path

    import_cases = list(goldset["local_resolution_cases"])
    import_cases.extend(
        case
        for case in goldset["external_preservation_cases"]
        if "import_form" in case
    )
    for case in import_cases:
        source = (fixture_root / case["source"]).read_text(encoding="utf-8")
        assert case["import_form"] in source


def test_fixture_python_files_are_not_pytest_collectable():
    _, fixture_root = _load()

    for path in fixture_root.rglob("*.py"):
        assert not path.name.startswith("test_")
        assert not path.name.endswith("_test.py")


def test_goldset_has_nontrivial_packaging_coverage():
    goldset, _ = _load()

    assert goldset["version"] == "1.1"
    assert len(goldset["local_resolution_cases"]) >= 7
    assert len(goldset["external_preservation_cases"]) >= 3
    assert len(goldset["layer_cases"]) >= 8
    assert len(goldset["parse_failure_cases"]) >= 1
    assert {case["expected"] for case in goldset["layer_cases"]} >= {
        "cli",
        "core",
        "test",
        "infra",
        "unknown",
    }
    assert any(
        case.get("forbidden_targets")
        for case in goldset["external_preservation_cases"]
    )


def test_baseline_is_reproducible():
    goldset, fixture_root = _load()
    report = evaluate_graph_quality_fixture(fixture_root, goldset)
    committed = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))

    assert report == committed
    assert report["metrics"] == {
        "local_resolution": {
            "total": 7,
            "hits": 5,
            "misses": 2,
            "recall": 0.714286,
        },
        "external_preservation": {
            "total": 3,
            "hits": 3,
            "misses": 0,
            "accuracy": 1.0,
        },
        "layer_assignment": {
            "total": 8,
            "hits": 8,
            "misses": 0,
            "accuracy": 1.0,
            "unknown_file_share": 0.588235,
        },
        "parse_failure_handling": {
            "total": 1,
            "hits": 1,
            "misses": 0,
            "accuracy": 1.0,
        },
    }
    assert report["coverage"] == {
        "files_seen": 18,
        "files_parsed": 17,
        "parse_failures": 1,
    }


def test_baseline_exposes_packaging_gaps_without_external_regression():
    goldset, fixture_root = _load()
    report = evaluate_graph_quality_fixture(fixture_root, goldset)

    misses = {
        case["id"]
        for case in report["cases"]["local_resolution"]
        if not case["found"]
    }
    assert misses == {
        "src-layout-import-root-gap",
        "namespace-import-root-gap",
    }
    assert all(case["found"] for case in report["cases"]["external_preservation"])
    assert all(case["found"] for case in report["cases"]["layer_assignment"])
    assert all(case["found"] for case in report["cases"]["parse_failure_handling"])

    ambiguous = next(
        case
        for case in report["cases"]["external_preservation"]
        if case["id"] == "ambiguous-search-roots-remain-external"
    )
    assert ambiguous["forbidden_target_hits"] == []


def test_goldset_rejects_duplicate_case_ids(tmp_path):
    payload = json.loads(GOLDSET_PATH.read_text(encoding="utf-8"))
    payload["parse_failure_cases"][0]["id"] = payload[
        "local_resolution_cases"
    ][0]["id"]
    path = tmp_path / "duplicate.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(GraphQualityGoldsetError, match="duplicate case id"):
        load_graph_quality_goldset(path)


def test_goldset_rejects_invalid_forbidden_targets(tmp_path):
    payload = json.loads(GOLDSET_PATH.read_text(encoding="utf-8"))
    payload["external_preservation_cases"][-1]["forbidden_targets"] = "not-a-list"
    path = tmp_path / "invalid-forbidden-targets.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(GraphQualityGoldsetError, match="forbidden_targets"):
        load_graph_quality_goldset(path)
