from scripts.proofs.review_intent_router_audit import compare_baselines


def _baseline(*, recall, mrr, target_hits, category_recall, category_mrr):
    return {
        "metrics": {
            "total_queries": 2,
            "recall@10": recall,
            "MRR": mrr,
            "zero_hit_ratio": 0.5,
            "expected_target_total": 4,
            "expected_target_hits": target_hits,
        },
        "categories": {
            "sample": {
                "total_queries": 2,
                "hits": 1,
                "misses": 1,
                "recall@10": category_recall,
                "MRR": category_mrr,
            }
        },
    }


def test_compare_baselines_passes_on_gain_without_category_regression():
    legacy = _baseline(
        recall=50.0,
        mrr=0.25,
        target_hits=1,
        category_recall=50.0,
        category_mrr=0.25,
    )
    review = _baseline(
        recall=100.0,
        mrr=0.5,
        target_hits=3,
        category_recall=100.0,
        category_mrr=0.5,
    )

    comparison = compare_baselines(legacy, review, k=10)

    assert comparison["gates"]["passed"] is True
    assert comparison["regressions"] == {"recall": [], "mrr": []}
    assert comparison["aggregate"]["delta_recall"] == 50.0
    assert comparison["categories"][0]["delta_mrr"] == 0.25


def test_compare_baselines_fails_closed_on_category_mrr_regression():
    legacy = _baseline(
        recall=50.0,
        mrr=0.25,
        target_hits=1,
        category_recall=100.0,
        category_mrr=1.0,
    )
    review = _baseline(
        recall=100.0,
        mrr=0.5,
        target_hits=3,
        category_recall=100.0,
        category_mrr=0.5,
    )

    comparison = compare_baselines(legacy, review, k=10)

    assert comparison["gates"]["passed"] is False
    assert comparison["gates"]["no_category_recall_regression"] is True
    assert comparison["gates"]["no_category_mrr_regression"] is False
    assert comparison["regressions"]["mrr"] == ["sample"]
