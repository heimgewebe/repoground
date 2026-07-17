import json
import subprocess

from merger.repoground.retrieval.retrieval_promotion_gate import build_promotion_gate_report


def _report(*, recall=0.5, mrr=0.5, target_hits=5, target_total=10, miss_count=2, fallback_count=0, category_recall=0.5, category_mrr=0.5):
    return {
        "metrics": {
            "recall@10": recall,
            "MRR": mrr,
            "expected_target_hits": target_hits,
            "expected_target_total": target_total,
        },
        "categories": {
            "contracts": {"recall@10": category_recall, "MRR": category_mrr},
        },
        "miss_diagnostics": [{} for _ in range(miss_count)],
        "measurement_conditions": {
            "review_intent": {"fallback_count": fallback_count}
        } if fallback_count else {},
    }


def _gate_names(report):
    return {gate["name"]: gate for gate in report["gates"]}


def test_promotion_gate_passes_non_regression_but_does_not_allow_default_promotion():
    legacy = _report()
    review = _report(recall=0.7, mrr=0.6, target_hits=7, miss_count=1, category_recall=0.7, category_mrr=0.6)

    report = build_promotion_gate_report(legacy, review, graph_report={"status": "fresh"}, range_report={"counts": {"malformed_hits": 0}})

    assert report["status"] == "passed"
    assert report["promote_default"] is False
    assert report["decision"]["default_promotion_allowed"] is False
    assert "review_completeness" in report["does_not_establish"]


def test_promotion_gate_blocks_category_regression():
    legacy = _report(category_recall=0.8, category_mrr=0.8)
    review = _report(recall=0.9, mrr=0.9, target_hits=8, category_recall=0.7, category_mrr=0.9)

    report = build_promotion_gate_report(legacy, review)
    gates = _gate_names(report)

    assert report["status"] == "blocked"
    assert gates["per_category_non_regression"]["passed"] is False


def test_promotion_gate_blocks_fallback_stale_graph_and_range_failures():
    legacy = _report()
    review = _report(recall=0.8, mrr=0.8, target_hits=8, miss_count=1, fallback_count=1, category_recall=0.8, category_mrr=0.8)

    report = build_promotion_gate_report(
        legacy,
        review,
        graph_report={"status": "stale_or_mismatched"},
        range_report={"counts": {"malformed_hits": 1}},
    )
    gates = _gate_names(report)

    assert report["status"] == "blocked"
    assert gates["fallback_count_zero"]["passed"] is False
    assert gates["fresh_graph_if_supplied"]["passed"] is False
    assert gates["range_citation_health_ok_if_supplied"]["passed"] is False


def test_promotion_gate_script_writes_json(tmp_path):
    legacy = tmp_path / "legacy.json"
    review = tmp_path / "review.json"
    out = tmp_path / "gate.json"
    legacy.write_text(json.dumps(_report()), encoding="utf-8")
    review.write_text(json.dumps(_report(recall=0.6, mrr=0.6, target_hits=6, miss_count=1, category_recall=0.6, category_mrr=0.6)), encoding="utf-8")

    subprocess.check_call([
        "python3",
        "scripts/proofs/retrieval_promotion_gate.py",
        "--legacy",
        str(legacy),
        "--review",
        str(review),
        "--out",
        str(out),
    ])

    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["kind"] == "lenskit.retrieval_promotion_gate"
    assert payload["status"] == "passed"
    assert payload["promote_default"] is False
