"""Tests for the review retrieval metric baseline + miss diagnostics adapter.

These tests prove the baseline measures the review goldset and reconciles misses
with the existing taxonomy. They use deterministic synthetic eval output (or a
deterministic mini index) so no test depends on, or asserts, real-world retrieval
quality and none implies a ranking improvement.
"""

import json
from pathlib import Path

import pytest

from merger.lenskit.retrieval import index_db
from merger.lenskit.retrieval.eval_diagnostics import (
    DiagnosticsRecord,
    RetrievalEvalDiagnosticsCalibrator,
)
from merger.lenskit.retrieval.review_eval import (
    DOES_NOT_ESTABLISH,
    build_review_retrieval_baseline,
    classify_target_kind,
    load_review_queries,
    normalize_review_queries,
    run_review_retrieval_baseline,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
REVIEW_QUERIES_PATH = REPO_ROOT / "docs/retrieval/review_queries.v1.json"
BASELINE_DOC_PATH = REPO_ROOT / "docs/diagnostics/review-retrieval-baseline.md"
REQUIRED_CATEGORIES = {
    "agent_pack",
    "claim_evidence",
    "citation_map",
    "post_emit_health",
    "bundle_surface",
    "bundle_manifest",
    "retrieval",
    "router",
    "cli",
    "contracts",
    "security",
    "source_acquisition",
    "pr_schau",
    "range_ref",
    "lenses",
}


def _synthetic_eval_results():
    """Deterministic do_eval-like output exercising hits, misses, and zero-hits."""
    return {
        "metrics": {
            "recall@10": 50.0,
            "MRR": 0.5,
            "zero_hit_ratio": 0.25,
            "total_queries": 4,
            "categories": {
                "cli": {"total_queries": 2, "base_hits": 1, "recall@10": 50.0, "MRR": 0.5},
                "security": {"total_queries": 2, "base_hits": 1, "recall@10": 50.0, "MRR": 0.25},
            },
        },
        "details": [
            {
                "query": "find the cli eval entrypoint",
                "category": "cli",
                "expected": ["merger/lenskit/cli/cmd_eval.py", "run_eval"],
                "is_relevant": True,
                "found_count": 3,
                "top_results": [
                    "merger/lenskit/cli/cmd_eval.py",
                    "merger/lenskit/cli/other.py",
                    "docs/notes.md",
                ],
            },
            {
                "query": "find the cli index builder",
                "category": "cli",
                "expected": ["merger/lenskit/cli/cmd_index.py"],
                "is_relevant": False,
                "found_count": 2,
                "top_results": ["merger/lenskit/cli/other.py", "docs/notes.md"],
            },
            {
                "query": "security review tests",
                "category": "security",
                "expected": ["merger/lenskit/tests/test_security.py"],
                "is_relevant": True,
                "found_count": 1,
                "top_results": ["merger/lenskit/tests/test_security.py"],
            },
            {
                "query": "totally unmatched query string",
                "category": "security",
                "expected": ["merger/lenskit/core/nowhere.py"],
                "is_relevant": False,
                "found_count": 0,
                "top_results": [],
            },
        ],
    }


# --- loader / normalization ------------------------------------------------


def test_review_goldset_loads_and_normalizes():
    queries = load_review_queries(REVIEW_QUERIES_PATH)
    assert len(queries) == 20
    first = queries[0]
    assert first["query_id"] == "RQ-01"
    assert first["query"]
    assert first["category"]
    assert isinstance(first["expected_targets"], list) and first["expected_targets"]


def test_normalize_accepts_envelope_and_preserves_multiple_targets():
    raw = {
        "queries": [
            {
                "query": "q",
                "category": "cli",
                "expected_patterns": ["a/b.py", "symbol_one", "symbol_two"],
            }
        ]
    }
    normalized = normalize_review_queries(raw)
    assert normalized[0]["query_id"] == "RQ-01"
    assert normalized[0]["expected_targets"] == ["a/b.py", "symbol_one", "symbol_two"]


def test_normalize_rejects_invalid_shape():
    with pytest.raises(ValueError):
        normalize_review_queries(42)


def test_classify_target_kind():
    assert classify_target_kind("merger/lenskit/core/merge.py") == "path"
    assert classify_target_kind("merger/lenskit/tests/test_merge.py") == "test_path"
    assert classify_target_kind("README.md") == "path"
    assert classify_target_kind("run_query") == "symbol_or_text"
    assert classify_target_kind("") == "unknown"
    assert classify_target_kind("merger/lenskit/tests/") == "test_path"
    assert classify_target_kind("merger/lenskit/core/") == "path"


# --- baseline structure / metrics ------------------------------------------


def test_baseline_exposes_core_metrics():
    baseline = build_review_retrieval_baseline(_synthetic_eval_results(), k=10)
    metrics = baseline["metrics"]
    assert metrics["total_queries"] == 4
    assert metrics["recall@10"] == 50.0
    assert metrics["MRR"] == 0.5
    assert metrics["zero_hit_ratio"] == 0.25
    assert baseline["authority"] == "diagnostic_signal"


def test_baseline_aggregates_categories():
    baseline = build_review_retrieval_baseline(_synthetic_eval_results(), k=10)
    cats = baseline["categories"]
    assert set(cats) == {"cli", "security"}
    assert cats["cli"]["total_queries"] == 2
    assert cats["cli"]["hits"] == 1
    assert cats["cli"]["misses"] == 1
    assert cats["cli"]["recall@10"] == 50.0
    assert "MRR" in cats["cli"]


def test_expected_target_hit_records_carry_id_target_status_and_rank():
    baseline = build_review_retrieval_baseline(_synthetic_eval_results(), k=10)
    q0 = baseline["queries"][0]
    assert q0["query_id"] == "RQ-01"
    assert q0["top_k"] == 10

    by_target = {rec["target"]: rec for rec in q0["expected_targets"]}
    # Two distinct expected targets on one query are reported separately.
    assert set(by_target) == {"merger/lenskit/cli/cmd_eval.py", "run_eval"}

    hit = by_target["merger/lenskit/cli/cmd_eval.py"]
    assert hit["found"] is True
    assert hit["rank"] == 1
    assert hit["matched_result"] == "merger/lenskit/cli/cmd_eval.py"
    assert hit["target_kind"] == "path"
    assert hit["diagnosis"] == "target_in_top_k"

    # The symbolic target is not in this path-only synthetic result set.
    sym = by_target["run_eval"]
    assert sym["found"] is False
    assert sym["rank"] is None
    assert sym["target_kind"] == "symbol_or_text"


def test_expected_target_totals_count_hits_and_misses():
    baseline = build_review_retrieval_baseline(_synthetic_eval_results(), k=10)
    metrics = baseline["metrics"]
    # 5 expected targets total across 4 queries; 2 land in top-k.
    assert metrics["expected_target_total"] == 5
    assert metrics["expected_target_hits"] == 2
    assert metrics["expected_target_misses"] == 3


def test_zero_hit_query_is_flagged():
    baseline = build_review_retrieval_baseline(_synthetic_eval_results(), k=10)
    zero_hit_queries = [q for q in baseline["queries"] if q["query_had_zero_hits"]]
    assert len(zero_hit_queries) == 1
    assert zero_hit_queries[0]["query"] == "totally unmatched query string"


# --- miss diagnostics via existing taxonomy --------------------------------


def test_miss_diagnostics_use_existing_taxonomy(tmp_path):
    # A readable mini index lets the calibrator distinguish "missing from index"
    # from a target that exists but is outside top-k.
    index_file = tmp_path / "chunks.jsonl"
    index_file.write_text(
        json.dumps({"chunk_id": "c1", "path": "merger/lenskit/cli/cmd_index.py"}) + "\n",
        encoding="utf-8",
    )
    calibrator = RetrievalEvalDiagnosticsCalibrator(index_path=index_file)

    baseline = build_review_retrieval_baseline(
        _synthetic_eval_results(), k=10, calibrator=calibrator
    )

    # Every diagnosis must come from the existing taxonomy vocabulary.
    valid = DiagnosticsRecord.PRIMARY_DIAGNOSES
    for q in baseline["queries"]:
        for rec in q["expected_targets"]:
            assert rec["diagnosis"] in valid

    # cmd_index.py exists in the index but is absent from this query's top-k.
    q1_targets = baseline["queries"][1]["expected_targets"]
    assert q1_targets[0]["diagnosis"] == "target_exists_not_in_top_k"

    # nowhere.py is absent from the index entirely.
    q3_targets = baseline["queries"][3]["expected_targets"]
    assert q3_targets[0]["diagnosis"] == "target_missing_from_index"


def test_miss_taxonomy_summary_counts_deterministically():
    baseline = build_review_retrieval_baseline(_synthetic_eval_results(), k=10)
    summary = baseline["miss_taxonomy_summary"]
    # Every taxonomy key is present and counts sum to the total expected targets.
    assert set(summary) == set(DiagnosticsRecord.PRIMARY_DIAGNOSES)
    assert sum(summary.values()) == baseline["metrics"]["expected_target_total"]
    # The two top-k hits are reflected.
    assert summary["target_in_top_k"] == 2

    # Determinism: building twice yields identical summaries.
    again = build_review_retrieval_baseline(_synthetic_eval_results(), k=10)
    assert again["miss_taxonomy_summary"] == summary


def test_baseline_carries_inference_boundaries():
    baseline = build_review_retrieval_baseline(_synthetic_eval_results(), k=10)
    assert baseline["does_not_establish"] == list(DOES_NOT_ESTABLISH)


# --- end-to-end against the real 20-query goldset --------------------------


def _mini_index(tmp_path):
    dump_path = tmp_path / "dump.json"
    chunk_path = tmp_path / "chunks.jsonl"
    db_path = tmp_path / "index.sqlite"
    chunks = [
        {
            "chunk_id": "c1",
            "repo_id": "r1",
            "path": "merger/lenskit/cli/cmd_eval.py",
            "content": "def run_eval(): pass",
            "start_line": 1,
            "end_line": 1,
            "layer": "core",
            "artifact_type": "code",
        },
        {
            "chunk_id": "c2",
            "repo_id": "r1",
            "path": "docs/notes.md",
            "content": "retrieval review notes",
            "start_line": 1,
            "end_line": 1,
            "layer": "docs",
            "artifact_type": "doc",
        },
    ]
    with chunk_path.open("w", encoding="utf-8") as f:
        for chunk in chunks:
            f.write(json.dumps(chunk) + "\n")
    dump_path.write_text(json.dumps({"dummy": "data"}), encoding="utf-8")
    index_db.build_index(dump_path, chunk_path, db_path)
    return db_path


def test_all_twenty_review_queries_flow_into_baseline(tmp_path):
    db_path = _mini_index(tmp_path)
    baseline = run_review_retrieval_baseline(db_path, REVIEW_QUERIES_PATH, k=10)
    assert baseline is not None

    # All 20 queries are measured and every blueprint category aggregates,
    # not collapsed into "uncategorized".
    assert baseline["metrics"]["total_queries"] == 20
    assert len(baseline["queries"]) == 20
    assert set(baseline["categories"]) == REQUIRED_CATEGORIES
    assert "uncategorized" not in baseline["categories"]

    # recall@10, MRR and zero_hit_ratio are reported (values are not asserted as
    # "good": this is a measuring instrument, not a quality gate).
    metrics = baseline["metrics"]
    assert "recall@10" in metrics
    assert "MRR" in metrics
    assert "zero_hit_ratio" in metrics
    assert isinstance(metrics["expected_target_total"], int)


def test_baseline_doc_states_boundaries():
    text = BASELINE_DOC_PATH.read_text(encoding="utf-8")
    assert "does not establish review completeness" in text
    assert "A hit does not prove answer correctness." in text
    assert "A miss does not prove code absence." in text


def test_unknown_diagnosis_fallback():
    class _UnknownDiagnosisCalibrator:
        def diagnose_miss(self, **kwargs):
            class _Record:
                primary_diagnosis = "new_unexpected_diagnosis"

                def to_dict(self):
                    return {
                        "primary_diagnosis": self.primary_diagnosis,
                        "query_id": kwargs.get("query_id"),
                        "expected_target": kwargs.get("expected_target"),
                    }

            return _Record()

    eval_res = _synthetic_eval_results()
    baseline = build_review_retrieval_baseline(
        eval_res,
        k=10,
        calibrator=_UnknownDiagnosisCalibrator(),  # type: ignore[arg-type]
    )

    assert "new_unexpected_diagnosis" not in baseline["miss_taxonomy_summary"]
    assert baseline["miss_taxonomy_summary"]["diagnostic_inconclusive"] >= 1

    # Check target records diagnosis field
    q0 = baseline["queries"][0]
    target_rec = q0["expected_targets"][0]
    assert target_rec["diagnosis"] == "diagnostic_inconclusive"
