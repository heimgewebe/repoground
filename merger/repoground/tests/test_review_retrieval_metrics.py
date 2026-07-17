"""Tests for the review retrieval metric baseline + miss diagnostics adapter.

These tests prove the baseline measures the review goldset and reconciles misses
with the existing taxonomy. They use deterministic synthetic eval output (or a
deterministic mini index) so no test depends on, or asserts, real-world retrieval
quality and none implies a ranking improvement.
"""

import json
from pathlib import Path

import jsonschema
import pytest

from merger.repoground.retrieval import index_db
from merger.repoground.retrieval.query_core import execute_query
from merger.repoground.retrieval.eval_diagnostics import (
    DiagnosticsRecord,
    RetrievalEvalDiagnosticsCalibrator,
)
from merger.repoground.retrieval.review_eval import (
    DOES_NOT_ESTABLISH,
    build_review_retrieval_baseline,
    classify_target_kind,
    load_review_queries,
    normalize_review_queries,
    run_review_retrieval_baseline,
    run_snapshot_retrieval_evaluation,
    SnapshotRetrievalMeasurementError,
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
                "expected": ["merger/repoground/cli/cmd_eval.py", "run_eval"],
                "is_relevant": True,
                "found_count": 3,
                "top_results": [
                    "merger/repoground/cli/cmd_eval.py",
                    "merger/repoground/cli/other.py",
                    "docs/notes.md",
                ],
            },
            {
                "query": "find the cli index builder",
                "category": "cli",
                "expected": ["merger/repoground/cli/cmd_index.py"],
                "is_relevant": False,
                "found_count": 2,
                "top_results": ["merger/repoground/cli/other.py", "docs/notes.md"],
            },
            {
                "query": "security review tests",
                "category": "security",
                "expected": ["merger/repoground/tests/test_security.py"],
                "is_relevant": True,
                "found_count": 1,
                "top_results": ["merger/repoground/tests/test_security.py"],
            },
            {
                "query": "totally unmatched query string",
                "category": "security",
                "expected": ["merger/repoground/core/nowhere.py"],
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
    assert classify_target_kind("merger/repoground/core/merge.py") == "path"
    assert classify_target_kind("merger/repoground/tests/test_merge.py") == "test_path"
    assert classify_target_kind("README.md") == "path"
    assert classify_target_kind("run_query") == "symbol_or_text"
    assert classify_target_kind("") == "unknown"
    assert classify_target_kind("merger/repoground/tests/") == "test_path"
    assert classify_target_kind("merger/repoground/core/") == "path"


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
    assert set(by_target) == {"merger/repoground/cli/cmd_eval.py", "run_eval"}

    hit = by_target["merger/repoground/cli/cmd_eval.py"]
    assert hit["found"] is True
    assert hit["rank"] == 1
    assert hit["matched_result"] == "merger/repoground/cli/cmd_eval.py"
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
        json.dumps({"chunk_id": "c1", "path": "merger/repoground/cli/cmd_index.py"}) + "\n",
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
            "path": "merger/repoground/cli/cmd_eval.py",
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
    assert "measurement_conditions" not in baseline


def _self_hit_index(tmp_path, *, include_similar: bool = True):
    dump_path = tmp_path / "self-hit-dump.json"
    chunk_path = tmp_path / "self-hit-chunks.jsonl"
    db_path = tmp_path / "self-hit-index.sqlite"
    chunks = [
        {
            "chunk_id": "goldset",
            "repo_id": "r1",
            "path": "docs/retrieval/review_queries.v1.json",
            "content": "needle",
            "start_line": 1,
            "end_line": 1,
            "layer": "docs",
            "artifact_type": "config",
        },
        {
            "chunk_id": "target",
            "repo_id": "r1",
            "path": "merger/repoground/core/target.py",
            "content": "needle",
            "start_line": 1,
            "end_line": 1,
            "layer": "core",
            "artifact_type": "code",
        },
    ]
    if include_similar:
        chunks.insert(
            1,
            {
                "chunk_id": "similar",
                "repo_id": "r1",
                "path": "docs/retrieval/review_queries.v1.json.copy",
                "content": "needle",
                "start_line": 1,
                "end_line": 1,
                "layer": "docs",
                "artifact_type": "config",
            },
        )
    with chunk_path.open("w", encoding="utf-8") as handle:
        for chunk in chunks:
            handle.write(json.dumps(chunk) + "\n")
    dump_path.write_text(json.dumps({"dummy": "data"}), encoding="utf-8")
    index_db.build_index(dump_path, chunk_path, db_path)
    return db_path


def test_query_path_exclusion_is_exact_and_applied_before_limit(tmp_path):
    db_path = _self_hit_index(tmp_path)

    default_result = execute_query(db_path, "", k=2, explain=True)
    explicit_default = execute_query(
        db_path, "", k=2, explain=True, excluded_paths=None
    )
    assert explicit_default == default_result
    assert [hit["path"] for hit in default_result["results"]] == [
        "docs/retrieval/review_queries.v1.json",
        "docs/retrieval/review_queries.v1.json.copy",
    ]

    excluded_result = execute_query(
        db_path,
        "",
        k=2,
        explain=True,
        excluded_paths=["docs/retrieval/review_queries.v1.json"],
    )
    assert [hit["path"] for hit in excluded_result["results"]] == [
        "docs/retrieval/review_queries.v1.json.copy",
        "merger/repoground/core/target.py",
    ]
    assert excluded_result["explain"]["excluded_paths"] == [
        "docs/retrieval/review_queries.v1.json"
    ]

    deduplicated = execute_query(
        db_path,
        "",
        k=2,
        excluded_paths=[
            "merger/repoground/core/target.py",
            "docs/retrieval/review_queries.v1.json",
            "docs/retrieval/review_queries.v1.json",
        ],
    )
    assert deduplicated["applied_exclusions"]["paths"] == [
        "docs/retrieval/review_queries.v1.json",
        "merger/repoground/core/target.py",
    ]


@pytest.mark.parametrize(
    "unsafe_path",
    ["", ".", "../escape.json", "a//b", "/absolute.json", r"docs\retrieval\queries.json"],
)
def test_query_path_exclusion_rejects_unsafe_paths(tmp_path, unsafe_path):
    db_path = _self_hit_index(tmp_path)
    with pytest.raises(ValueError):
        execute_query(db_path, "needle", excluded_paths=[unsafe_path])


def test_review_baseline_excludes_repo_local_goldset_and_reports_provenance(tmp_path):
    repo_root = tmp_path / "repo"
    goldset_path = repo_root / "docs/retrieval/review_queries.v1.json"
    goldset_path.parent.mkdir(parents=True)
    goldset_path.write_text(
        json.dumps(
            [
                {
                    "query": "",
                    "category": "retrieval",
                    "expected_patterns": ["merger/repoground/core/target.py"],
                    "filters": {},
                }
            ]
        ),
        encoding="utf-8",
    )
    db_path = _self_hit_index(tmp_path, include_similar=False)

    baseline = run_review_retrieval_baseline(
        db_path,
        goldset_path,
        k=1,
        repo_root=repo_root,
    )
    assert baseline is not None
    assert baseline["metrics"]["expected_target_hits"] == 1
    assert baseline["measurement_conditions"] == {
        "path_exclusions": [
            {
                "path": "docs/retrieval/review_queries.v1.json",
                "reason": "goldset_self_reference",
            }
        ],
        "match": "exact_repository_path",
        "application": "before_order_by_and_limit",
        "ranking_algorithm_changed": False,
        "does_not_establish": [
            "Excluded paths are outside this measurement run only.",
            "An excluded path is not established as irrelevant.",
            "Changed metrics do not establish a ranking improvement.",
        ],
    }


def test_review_baseline_rejects_goldset_outside_repo_root(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    goldset_path = tmp_path / "outside.json"
    goldset_path.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="inside repo_root"):
        run_review_retrieval_baseline(
            _self_hit_index(tmp_path),
            goldset_path,
            repo_root=repo_root,
        )


def test_baseline_doc_states_boundaries():
    text = BASELINE_DOC_PATH.read_text(encoding="utf-8")
    assert "does not establish review completeness" in text
    assert "A hit does not prove answer correctness." in text
    assert "A miss does not prove code absence." in text
    assert "goldset_self_reference" in text
    assert "does not establish a ranking improvement" in text



# --- snapshot benchmark selection / promotion boundary ---------------------


def _copy_canonical_goldset(repo_root: Path) -> Path:
    target = repo_root / "docs/retrieval/review_queries.v1.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(REVIEW_QUERIES_PATH.read_bytes())
    return target


def _generic_queries(path: Path) -> Path:
    path.write_text(
        json.dumps(
            [
                {
                    "query": "find the cli eval entrypoint",
                    "category": "cli",
                    "expected_patterns": ["merger/repoground/cli/cmd_eval.py"],
                    "filters": {},
                    "accept_criteria": {"recall_at_10": 0.1},
                }
            ]
        ),
        encoding="utf-8",
    )
    return path


def test_snapshot_uses_repository_goldset_and_separates_recall(tmp_path):
    repo_root = tmp_path / "repo"
    _copy_canonical_goldset(repo_root)
    db_path = _mini_index(tmp_path)
    generic = _generic_queries(tmp_path / "generic.json")

    report = run_snapshot_retrieval_evaluation(
        db_path,
        repo_root=repo_root,
        generic_queries_path=generic,
        k=10,
    )

    assert report is not None
    benchmark = report["benchmark"]
    assert benchmark["kind"] == "repository_review_goldset"
    assert benchmark["scope"] == "repository_specific"
    assert benchmark["canonical"] is True
    assert benchmark["evaluation_mode"] == "default_lexical"
    assert benchmark["default_promotion_allowed"] is False
    assert benchmark["promotion_status"] == "blocked"
    assert "review_intent" not in report.get("measurement_conditions", {})

    metrics = report["metrics"]
    assert metrics["question_recall@10"] == metrics["recall@10"]
    assert metrics["question_hits"] + metrics["question_misses"] == 20
    assert (
        metrics["expected_target_hits"] + metrics["expected_target_misses"]
        == metrics["expected_target_total"]
    )
    assert "expected_target_recall@10" in metrics
    assert report["review_measurement"]["acceptance"][
        "does_not_allow_default_promotion"
    ] is True

    schema = json.loads(
        (REPO_ROOT / "merger/repoground/contracts/retrieval-eval.v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    jsonschema.validate(instance=report, schema=schema)


def test_snapshot_generic_fallback_is_explicitly_noncanonical(tmp_path):
    repo_root = tmp_path / "repo-without-goldset"
    repo_root.mkdir()
    report = run_snapshot_retrieval_evaluation(
        _mini_index(tmp_path),
        repo_root=repo_root,
        generic_queries_path=_generic_queries(tmp_path / "generic.json"),
        k=10,
    )

    assert report is not None
    benchmark = report["benchmark"]
    assert benchmark["kind"] == "generic_example"
    assert benchmark["scope"] == "generic_diagnostic_sample"
    assert benchmark["canonical"] is False
    assert benchmark["default_promotion_allowed"] is False
    assert "repository_specific_goldset_missing" in benchmark[
        "promotion_block_reasons"
    ]
    assert "review_measurement" not in report

    schema = json.loads(
        (REPO_ROOT / "merger/repoground/contracts/retrieval-eval.v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    jsonschema.validate(instance=report, schema=schema)


@pytest.mark.parametrize(
    ("mutation", "expected_message"),
    [
        ({"canonical": False}, "True was expected"),
        ({"scope": "generic_diagnostic_sample"}, "repository_specific"),
        ({"validation_status": "not_applicable"}, "pass"),
    ],
)
def test_retrieval_schema_rejects_contradictory_canonical_benchmark(
    tmp_path, mutation, expected_message
):
    repo_root = tmp_path / "repo"
    _copy_canonical_goldset(repo_root)
    report = run_snapshot_retrieval_evaluation(
        _mini_index(tmp_path),
        repo_root=repo_root,
        generic_queries_path=_generic_queries(tmp_path / "generic.json"),
        k=10,
    )
    assert report is not None
    report["benchmark"].update(mutation)
    schema = json.loads(
        (REPO_ROOT / "merger/repoground/contracts/retrieval-eval.v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    with pytest.raises(jsonschema.ValidationError, match=expected_message):
        jsonschema.validate(instance=report, schema=schema)


def test_retrieval_schema_requires_review_measurement_for_canonical_benchmark(
    tmp_path,
):
    repo_root = tmp_path / "repo"
    _copy_canonical_goldset(repo_root)
    report = run_snapshot_retrieval_evaluation(
        _mini_index(tmp_path),
        repo_root=repo_root,
        generic_queries_path=_generic_queries(tmp_path / "generic.json"),
        k=10,
    )
    assert report is not None
    report.pop("review_measurement")
    schema = json.loads(
        (REPO_ROOT / "merger/repoground/contracts/retrieval-eval.v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=report, schema=schema)


def test_invalid_canonical_goldset_fails_without_generic_fallback(
    tmp_path, monkeypatch
):
    repo_root = tmp_path / "repo"
    goldset = repo_root / "docs/retrieval/review_queries.v1.json"
    goldset.parent.mkdir(parents=True)
    goldset.write_text("[]", encoding="utf-8")
    generic = _generic_queries(tmp_path / "generic.json")

    def unexpected_eval(*args, **kwargs):
        raise AssertionError("generic fallback must not run")

    monkeypatch.setattr(
        "merger.repoground.retrieval.review_eval.do_eval", unexpected_eval
    )
    with pytest.raises(
        SnapshotRetrievalMeasurementError, match="canonical_goldset_invalid"
    ) as caught:
        run_snapshot_retrieval_evaluation(
            tmp_path / "unused.sqlite",
            repo_root=repo_root,
            generic_queries_path=generic,
            k=10,
        )
    assert caught.value.code == "canonical_goldset_invalid"


def test_baseline_reports_category_and_query_target_coverage():
    queries = []
    for idx, detail in enumerate(_synthetic_eval_results()["details"], start=1):
        queries.append(
            {
                "query_id": f"RQ-{idx:02d}",
                "query": detail["query"],
                "category": detail["category"],
                "expected_targets": detail["expected"],
                "filters": {},
                "accept_criteria": {"recall_at_10": 0.5},
            }
        )
    baseline = build_review_retrieval_baseline(
        _synthetic_eval_results(), k=10, review_queries=queries
    )

    assert baseline["metrics"]["question_recall@10"] == 50.0
    assert baseline["metrics"]["expected_target_recall@10"] == 40.0
    assert baseline["categories"]["cli"]["expected_target_total"] == 3
    assert baseline["categories"]["cli"]["expected_target_hits"] == 1
    assert baseline["categories"]["security"]["expected_target_recall@10"] == 50.0
    assert baseline["acceptance"] == {
        "criterion": "recall_at_10",
        "evaluated_queries": 4,
        "passed_queries": 2,
        "failed_queries": 2,
        "status": "fail",
        "does_not_allow_default_promotion": True,
    }

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

    # Check that "new_unexpected_diagnosis" is not in target records
    for q in baseline["queries"]:
        for rec in q["expected_targets"]:
            assert rec["diagnosis"] != "new_unexpected_diagnosis"

    # Check that "new_unexpected_diagnosis" is not in miss_diagnostics
    assert all(
        rec["primary_diagnosis"] != "new_unexpected_diagnosis"
        for rec in baseline["miss_diagnostics"]
    )
