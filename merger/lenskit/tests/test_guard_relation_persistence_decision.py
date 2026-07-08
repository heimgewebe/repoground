import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DECISION = ROOT / "docs" / "proofs" / "guard-relation-persistence-decision.v1.json"
GOLDSET = ROOT / "docs" / "retrieval" / "guard_relation_goldset.v1.json"
EVALUATOR = ROOT / "scripts" / "proofs" / "guard_relation_goldset_eval.py"
PROOF = ROOT / "docs" / "proofs" / "guard-relation-persistence-decision-v1-proof.md"


def _eval_module():
    spec = importlib.util.spec_from_file_location("grg_eval", EVALUATOR)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _decision():
    return json.loads(DECISION.read_text(encoding="utf-8"))


def test_guard_relation_persistence_decision_keeps_persistence_blocked():
    decision = _decision()

    assert decision["kind"] == "lenskit.guard_relation_persistence_decision"
    assert decision["version"] == "1.0"
    assert decision["status"] == "blocked"
    assert decision["decision"]["persist_guard_relation_cards"] is False
    assert decision["decision"]["decision_class"] == "keep_blocked"
    assert "persistent_guard_relation_cards" in decision["blocked_current_use"]
    assert "diagnostic_goldset" in decision["allowed_current_use"]


def test_guard_relation_persistence_decision_names_no_current_consumer():
    decision = _decision()
    consumer_need = decision["consumer_need"]

    assert consumer_need["concrete_consumer"] is None
    assert consumer_need["consumer_status"] == "not_established"
    reviewed = {item["name"]: item["status"] for item in consumer_need["reviewed_possible_consumers"]}
    assert reviewed["Retrieval v2 relation-aware ranking"] == "possible_future_consumer"
    assert reviewed["RepoBrief context and delta compilers"] == "not_required"
    assert reviewed["Bureau task verification"] == "not_required"


def test_guard_relation_persistence_thresholds_block_current_goldset_metrics():
    decision = _decision()
    thresholds = decision["required_thresholds_before_persistence"]
    evidence = decision["current_evidence"]

    assert thresholds["consumer_must_be_named"] is True
    assert thresholds["minimum_precision"] == 0.95
    assert thresholds["minimum_resolved_positive_recall"] == 0.95
    assert thresholds["maximum_false_positive_rate_on_resolved_negative_cases"] == 0.05
    assert thresholds["maximum_unresolved_cases_per_relation_type"] == 0
    assert thresholds["negative_semantics_must_be_preserved"] is True
    assert evidence["threshold_evaluation"] == {
        "consumer_named": False,
        "precision_threshold_met": False,
        "resolved_positive_recall_threshold_met": True,
        "false_positive_rate_threshold_met": False,
        "unresolved_case_threshold_met": False,
        "negative_semantics_available": True,
    }
    assert set(evidence["block_reasons"]) >= {
        "no_concrete_consumer",
        "precision_below_threshold",
        "false_positive_rate_above_threshold",
        "unresolved_cases_present",
    }


def test_guard_relation_persistence_decision_matches_live_goldset_evaluator():
    decision = _decision()
    report = _eval_module().evaluate_goldset(GOLDSET)

    assert decision["current_evidence"]["source_goldset"] == "docs/retrieval/guard_relation_goldset.v1.json"
    assert decision["current_evidence"]["relation_types"] == report["relation_types"]
    assert decision["current_evidence"]["by_relation"] == report["by_relation"]
    assert decision["decision"]["persist_guard_relation_cards"] == report["decision"]["persist_guard_relation_cards"]


def test_guard_relation_persistence_decision_preserves_negative_semantics_and_non_claims():
    decision = _decision()
    proof = PROOF.read_text(encoding="utf-8")

    for token in (
        "test_sufficiency",
        "runtime_correctness",
        "regression_absence",
        "schema_runtime_equivalence",
        "coverage_completeness",
        "guard_effectiveness",
        "causality",
    ):
        assert token in decision["negative_semantics"] or token in decision["does_not_establish"]
        assert token in proof
    assert "merge_readiness" in decision["does_not_establish"]
    assert "need_for_persistent_guard_relation_cards" in decision["does_not_establish"]


def test_guard_relation_persistence_decision_does_not_add_producer_or_bundle_role():
    decision = _decision()

    assert "bundle_artifact_emission_for_guard_relations" in decision["blocked_current_use"]
    assert "default_retrieval_ranking_signal" in decision["blocked_current_use"]
    assert "review_or_merge_gate" in decision["blocked_current_use"]
