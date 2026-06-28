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
    paths.update(case["path"] for case in goldset["layer_cases"])

    for relative_path in sorted(paths):
        assert (fixture_root / relative_path).is_file(), relative_path

    for case in goldset["local_resolution_cases"]:
        source = (fixture_root / case["source"]).read_text(encoding="utf-8")
        assert case["import_form"] in source


def test_fixture_python_files_are_not_pytest_collectable():
    _, fixture_root = _load()

    for path in fixture_root.rglob("*.py"):
        assert not path.name.startswith("test_")
        assert not path.name.endswith("_test.py")


def test_goldset_has_nontrivial_coverage():
    goldset, _ = _load()

    assert len(goldset["local_resolution_cases"]) >= 4
    assert len(goldset["external_preservation_cases"]) >= 2
    assert len(goldset["layer_cases"]) >= 6
    assert {case["expected"] for case in goldset["layer_cases"]} >= {
        "cli",
        "core",
        "test",
        "infra",
        "unknown",
    }


def test_baseline_is_reproducible():
    goldset, fixture_root = _load()
    report = evaluate_graph_quality_fixture(fixture_root, goldset)
    committed = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))

    assert report == committed
    assert report["metrics"] == {
        "local_resolution": {
            "total": 4,
            "hits": 1,
            "misses": 3,
            "recall": 0.25,
        },
        "external_preservation": {
            "total": 2,
            "hits": 2,
            "misses": 0,
            "accuracy": 1.0,
        },
        "layer_assignment": {
            "total": 6,
            "hits": 1,
            "misses": 5,
            "accuracy": 0.166667,
            "unknown_file_share": 1.0,
        },
    }


def test_baseline_exposes_case_level_gaps():
    goldset, fixture_root = _load()
    report = evaluate_graph_quality_fixture(fixture_root, goldset)
    resolution = {
        case["id"]
        for case in report["cases"]["local_resolution"]
        if not case["found"]
    }
    layers = {
        case["path"]
        for case in report["cases"]["layer_assignment"]
        if not case["found"]
    }

    assert resolution == {
        "absolute-from-cli",
        "absolute-from-test",
        "absolute-from-worker",
    }
    assert layers == {
        "cli/main.py",
        "core/service.py",
        "core/utils.py",
        "tests/service_case.py",
        "scripts/worker.py",
    }


def test_goldset_rejects_duplicate_case_ids(tmp_path):
    payload = json.loads(GOLDSET_PATH.read_text(encoding="utf-8"))
    payload["external_preservation_cases"][0]["id"] = payload[
        "local_resolution_cases"
    ][0]["id"]
    path = tmp_path / "duplicate.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(GraphQualityGoldsetError, match="duplicate case id"):
        load_graph_quality_goldset(path)
