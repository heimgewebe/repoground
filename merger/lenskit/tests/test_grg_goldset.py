import copy
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
GOLDSET = ROOT / "docs" / "retrieval" / ("guard_" + "relation_goldset.v1.json")
SCRIPT = ROOT / "scripts" / "proofs" / ("guard_" + "relation_goldset_eval.py")


def _module():
    spec = importlib.util.spec_from_file_location("grg_eval", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_guard_relation_goldset_evaluates_false_positive_and_unresolved_cases():
    report = _module().evaluate_goldset(GOLDSET)

    assert report["kind"] == "lenskit.guard_relation_goldset_eval"
    assert report["relation_types"] == ["tests_by_name", "validates_schema"]
    for relation_type in report["relation_types"]:
        metrics = report["by_relation"][relation_type]
        assert metrics["total"] == 4
        assert metrics["true_positive"] == 2
        assert metrics["false_positive"] == 1
        assert metrics["unresolved"] == 1
        assert metrics["precision"] == 0.666667
    assert report["decision"]["persist_guard_relation_cards"] is False


def test_guard_relation_goldset_preserves_negative_semantics():
    payload = json.loads(GOLDSET.read_text(encoding="utf-8"))
    for token in (
        "test_sufficiency",
        "runtime_correctness",
        "regression_absence",
        "schema_runtime_equivalence",
    ):
        assert token in payload["negative_semantics"]
        assert token in payload["does_not_establish"]


def test_guard_relation_goldset_rejects_duplicate_case_ids(tmp_path):
    payload = json.loads(GOLDSET.read_text(encoding="utf-8"))
    clone = copy.deepcopy(payload["cases"][0])
    payload["cases"].append(clone)
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate case id"):
        _module().evaluate_goldset(path)
