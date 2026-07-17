"""Tests for retrieval evaluation diagnostics calibrator."""

import json
from pathlib import Path

import jsonschema
import pytest

from merger.repoground.retrieval.eval_diagnostics import (
    DOES_NOT_PROVE,
    DiagnosticsRecord,
    IndexInspector,
    MissingArtifactError,
    RetrievalEvalDiagnosticsCalibrator,
)
from merger.repoground.retrieval.eval_diagnostics_integration import _extract_misses_from_eval


@pytest.fixture
def tmp_artifacts(tmp_path):
    """Create temporary index/canonical/citation artifacts using real citation semantics."""
    index_file = tmp_path / "chunks.jsonl"
    chunks = [
        {"chunk_id": "c1", "path": "merger/repoground/core/merge.py", "content": "def iter_report_blocks(): pass"},
        {"chunk_id": "c2", "path": "merger/repoground/core/chunker.py", "content": "class Chunker: pass"},
        {"chunk_id": "c3", "path": "merger/repoground/retrieval/index_db.py", "content": "def build_index(): pass"},
        {"chunk_id": "c4", "path": "merger/repoground/core/missing_citation.py", "content": "x = 1"},
    ]
    with index_file.open("w", encoding="utf-8") as f:
        for chunk in chunks:
            f.write(json.dumps(chunk) + "\n")

    canonical_file = tmp_path / "canonical.md"
    canonical_file.write_text(
        "\n".join(
            [
                "# Canonical Content",
                "- `merger/repoground/core/merge.py`",
                "- `merger/repoground/core/chunker.py`",
                "- `merger/repoground/retrieval/index_db.py`",
                "- `merger/repoground/core/missing_citation.py`",
            ]
        ),
        encoding="utf-8",
    )

    citation_file = tmp_path / "citation_map.jsonl"
    citations = [
        {
            "citation_id": "cit-1",
            "chunk_id": "c1",
            "canonical_range": {"start_byte": 0, "end_byte": 10},
        },
        {
            "citation_id": "cit-2",
            "chunk_id": "c2",
            "canonical_range": {"start_byte": 11, "end_byte": 20},
        },
        {
            "citation_id": "cit-3",
            "chunk_id": "c3",
            "canonical_range": {"start_byte": 21, "end_byte": 30},
        },
    ]
    with citation_file.open("w", encoding="utf-8") as f:
        for citation in citations:
            f.write(json.dumps(citation) + "\n")

    return {
        "index": index_file,
        "canonical": canonical_file,
        "citation": citation_file,
        "tmp_path": tmp_path,
    }


class TestDiagnosticsRecord:
    def test_valid_record(self):
        record = DiagnosticsRecord(
            query_id="q1",
            query_text="find merge",
            expected_target="merge.py",
            primary_diagnosis="target_in_top_k",
            diagnosis_details={"confidence": "high"},
        )
        assert record.to_dict()["primary_diagnosis"] == "target_in_top_k"

    def test_invalid_diagnosis(self):
        with pytest.raises(ValueError):
            DiagnosticsRecord(
                query_id="q1",
                query_text="find merge",
                expected_target="merge.py",
                primary_diagnosis="invalid",
                diagnosis_details={},
            )


class TestIndexInspector:
    def test_load_index_paths(self, tmp_artifacts):
        inspector = IndexInspector(tmp_artifacts["index"])
        paths = inspector.load_index_paths()
        assert "merger/repoground/core/merge.py" in paths

    def test_load_index_paths_missing(self):
        inspector = IndexInspector(Path("/does/not/exist.jsonl"))
        with pytest.raises(MissingArtifactError):
            inspector.load_index_paths()

    def test_path_to_chunk_ids(self, tmp_artifacts):
        inspector = IndexInspector(tmp_artifacts["index"])
        mapping = inspector.load_path_to_chunk_ids()
        assert mapping["merger/repoground/core/merge.py"] == {"c1"}


class TestIntegrationExtraction:
    def test_extract_uses_details_structure(self):
        eval_results = {
            "metrics": {"total_queries": 2},
            "details": [
                {
                    "query": "merge",
                    "expected": ["merge.py", "iter_report_blocks"],
                    "is_relevant": False,
                    "found_count": 2,
                    "top_results": ["merger/repoground/core/merge.py", "merger/repoground/core/chunker.py"],
                },
                {
                    "query": "chunk",
                    "expected": ["chunker.py"],
                    "is_relevant": True,
                    "found_count": 1,
                    "top_results": ["merger/repoground/core/chunker.py"],
                },
            ],
        }

        misses = _extract_misses_from_eval(eval_results)
        assert len(misses) == 2
        assert misses[0]["query_id"] == "q0"
        assert misses[0]["query_had_zero_hits"] is False
        assert misses[0]["top_k"] == 2

    def test_extract_rejects_legacy_results_key(self):
        eval_results = {
            "metrics": {},
            "results": [{"query": "x", "is_relevant": False, "expected": ["a"], "top_results": [], "found_count": 0}],
        }
        with pytest.raises(ValueError):
            _extract_misses_from_eval(eval_results)

    def test_extract_rejects_missing_details_field(self):
        eval_results = {"metrics": {"total_queries": 1}}
        with pytest.raises(ValueError, match="Expected retrieval_eval field 'details'\\."):
            _extract_misses_from_eval(eval_results)

    def test_extract_do_eval_like_details_object(self):
        """Extraction must consume do_eval-like details entries, not a legacy results shape."""
        eval_results = {
            "metrics": {
                "recall@10": 50.0,
                "MRR": 0.5,
                "total_queries": 2,
            },
            "details": [
                {
                    "query": "merge",
                    "category": "core",
                    "expected": ["merge.py", "iter_report_blocks"],
                    "is_relevant": False,
                    "found_count": 1,
                    "top_results": ["merger/repoground/core/chunker.py"],
                    "rr": None,
                    "why": {"why_fail": "expected path not in top-k"},
                    "explain": {},
                },
                {
                    "query": "chunk",
                    "category": "core",
                    "expected": ["chunker.py"],
                    "is_relevant": True,
                    "found_count": 1,
                    "top_results": ["merger/repoground/core/chunker.py"],
                    "rr": 1.0,
                    "why": {},
                    "explain": {},
                },
            ],
            "claim_boundaries": {
                "proves": ["synthetic do_eval-like object"],
                "does_not_prove": ["anything beyond test scope"],
                "evidence_basis": ["query_results"],
                "requires_live_check": True,
            },
            "miss_taxonomy": {
                "version": "1.0",
                "authority": "diagnostic_signal",
                "risk_class": "diagnostic",
                "classification_basis": ["retrieval_eval_expectations"],
                "does_not_prove": ["taxonomy_is_diagnostic_not_authoritative"],
                "aggregate": {
                    "total_cases_classified": 2,
                    "total_misses": 1,
                    "by_type": {
                        "zero_results": 0,
                        "expected_not_in_top_k": 1,
                        "expected_rank_below_k": 0,
                        "expected_path_not_indexed": 0,
                        "expected_symbol_not_indexed": 0,
                        "path_or_symbol_metadata_missing": 0,
                        "possible_query_vocabulary_gap": 0,
                        "possible_filter_scope_gap": 0,
                        "noise_or_fixture_hit": 0,
                        "stale_eval_input": 0,
                        "query_execution_error": 0,
                        "unknown": 0,
                    },
                },
                "cases": [],
            },
        }

        misses = _extract_misses_from_eval(eval_results)
        assert len(misses) == 2
        # top_k is inferred from metrics (recall@10), not from len(top_results)=1
        assert misses[0]["top_k"] == 10
        assert misses[1]["top_k"] == 10
        assert misses[0]["query_had_zero_hits"] is False
        assert misses[0]["expected_target"] == "merge.py"
        assert misses[1]["expected_target"] == "iter_report_blocks"


class TestRetrievalEvalDiagnosticsCalibrator:
    def test_all_good_hit(self, tmp_artifacts):
        calibrator = RetrievalEvalDiagnosticsCalibrator(
            index_path=tmp_artifacts["index"],
            canonical_path=tmp_artifacts["canonical"],
            citation_path=tmp_artifacts["citation"],
        )
        record = calibrator.diagnose_miss(
            query_id="q1",
            query_text="find merge",
            expected_target="merge.py",
            found_in_results=True,
            rank_in_results=1,
            top_k=10,
        )
        assert record.primary_diagnosis == "target_in_top_k"

    def test_target_exists_not_observed_in_top_k_without_rank_claim(self, tmp_artifacts):
        calibrator = RetrievalEvalDiagnosticsCalibrator(
            index_path=tmp_artifacts["index"],
            canonical_path=tmp_artifacts["canonical"],
            citation_path=tmp_artifacts["citation"],
        )
        record = calibrator.diagnose_miss(
            query_id="q2",
            query_text="find merge",
            expected_target="merge.py",
            found_in_results=False,
            rank_in_results=None,
            top_k=10,
        )
        assert record.primary_diagnosis == "target_exists_not_in_top_k"
        assert record.diagnosis_details["rank_in_results"] is None

    def test_mixed_expected_path_and_symbol_pattern(self, tmp_artifacts):
        eval_results = {
            "metrics": {"total_queries": 1},
            "details": [
                {
                    "query": "merge",
                    "expected": ["merge.py", "iter_report_blocks"],
                    "is_relevant": False,
                    "found_count": 1,
                    "top_results": ["merger/repoground/core/chunker.py"],
                }
            ],
        }

        misses = _extract_misses_from_eval(eval_results)
        assert len(misses) == 2

        calibrator = RetrievalEvalDiagnosticsCalibrator(
            index_path=tmp_artifacts["index"],
            canonical_path=tmp_artifacts["canonical"],
            citation_path=tmp_artifacts["citation"],
        )

        by_target = {}
        for miss in misses:
            rec = calibrator.diagnose_miss(**miss)
            by_target[miss["expected_target"]] = rec.primary_diagnosis

        assert by_target["merge.py"] in {
            "target_exists_not_in_top_k",
            "target_missing_from_citation_map",
            "target_missing_from_canonical",
        }
        assert by_target["iter_report_blocks"] in {
            "query_target_ambiguous",
            "diagnostic_inconclusive",
        }
        assert by_target["iter_report_blocks"] != "target_missing_from_index"

    def test_target_missing_from_index(self, tmp_artifacts):
        calibrator = RetrievalEvalDiagnosticsCalibrator(
            index_path=tmp_artifacts["index"],
            canonical_path=tmp_artifacts["canonical"],
            citation_path=tmp_artifacts["citation"],
        )
        record = calibrator.diagnose_miss(
            query_id="q3",
            query_text="find nope",
            expected_target="does/not/exist.py",
            found_in_results=False,
            rank_in_results=None,
            top_k=10,
        )
        assert record.primary_diagnosis == "target_missing_from_index"

    def test_stale_expected_target(self, tmp_artifacts):
        calibrator = RetrievalEvalDiagnosticsCalibrator(
            index_path=tmp_artifacts["index"],
            canonical_path=tmp_artifacts["canonical"],
            citation_path=tmp_artifacts["citation"],
        )
        record = calibrator.diagnose_miss(
            query_id="q4",
            query_text="find old",
            expected_target="/tmp/old_snapshot.py",
            found_in_results=False,
            rank_in_results=None,
            top_k=10,
        )
        assert record.primary_diagnosis == "stale_expected_target"

    def test_ambiguous_empty_expected_target(self, tmp_artifacts):
        calibrator = RetrievalEvalDiagnosticsCalibrator(
            index_path=tmp_artifacts["index"],
            canonical_path=tmp_artifacts["canonical"],
            citation_path=tmp_artifacts["citation"],
        )
        record = calibrator.diagnose_miss(
            query_id="q5",
            query_text="find ???",
            expected_target="",
            found_in_results=False,
            rank_in_results=None,
            top_k=None,
        )
        assert record.primary_diagnosis == "query_target_ambiguous"

    def test_citation_map_checked_via_chunk_id_bridge(self, tmp_artifacts):
        calibrator = RetrievalEvalDiagnosticsCalibrator(
            index_path=tmp_artifacts["index"],
            canonical_path=tmp_artifacts["canonical"],
            citation_path=tmp_artifacts["citation"],
        )
        record = calibrator.diagnose_miss(
            query_id="q6",
            query_text="find merge",
            expected_target="merge.py",
            found_in_results=False,
            rank_in_results=None,
            top_k=10,
        )
        assert record.diagnosis_details["target_found_in_citation_map"] is True
        assert record.primary_diagnosis != "target_missing_from_citation_map"

    def test_missing_citation_detected_when_chunk_has_no_citation(self, tmp_artifacts):
        calibrator = RetrievalEvalDiagnosticsCalibrator(
            index_path=tmp_artifacts["index"],
            canonical_path=tmp_artifacts["canonical"],
            citation_path=tmp_artifacts["citation"],
        )
        record = calibrator.diagnose_miss(
            query_id="q7",
            query_text="find missing citation",
            expected_target="missing_citation.py",
            found_in_results=False,
            rank_in_results=None,
            top_k=10,
        )
        assert record.primary_diagnosis == "target_missing_from_citation_map"

    def test_schema_validation(self, tmp_artifacts):
        calibrator = RetrievalEvalDiagnosticsCalibrator(
            index_path=tmp_artifacts["index"],
            canonical_path=tmp_artifacts["canonical"],
            citation_path=tmp_artifacts["citation"],
        )
        report = calibrator.generate_report(
            [
                {
                    "query_id": "q9",
                    "query_text": "find merge",
                    "expected_target": "merge.py",
                    "found_in_results": False,
                    "rank_in_results": None,
                    "top_k": 2,
                    "query_had_zero_hits": False,
                }
            ]
        )

        schema_path = (
            Path(__file__).resolve().parent.parent
            / "contracts"
            / "retrieval-eval-diagnostics.v1.schema.json"
        )
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        jsonschema.validate(instance=report, schema=schema)

    def test_report_carries_does_not_prove_boundary(self, tmp_artifacts):
        # C1 L3: the diagnostics artifact must carry a machine-readable inference
        # boundary (resolves the C2.4-tracked deferral). The producer emits the
        # canonical does_not_prove entries the contract requires.
        calibrator = RetrievalEvalDiagnosticsCalibrator(index_path=tmp_artifacts["index"])
        report = calibrator.generate_report([])

        boundary = report["does_not_prove"]
        assert isinstance(boundary, list) and boundary
        assert list(DOES_NOT_PROVE) == boundary
        for token in (
            "absence_of_retrieval_hit_does_not_prove_absence_in_repository",
            "miss_diagnosis_does_not_prove_claim_truth_or_falsehood",
            "primary_diagnosis_does_not_prove_root_cause_certainty",
            "retrieval_eval_does_not_prove_retrieval_completeness",
            "diagnosis_is_diagnostic_not_authoritative",
        ):
            assert token in boundary

    def test_schema_requires_does_not_prove_boundary(self, tmp_artifacts):
        # The boundary is required: a report missing it fails contract validation
        # (locks the C2.4 deferral resolution against regression).
        calibrator = RetrievalEvalDiagnosticsCalibrator(index_path=tmp_artifacts["index"])
        report = calibrator.generate_report([])
        report.pop("does_not_prove")

        schema_path = (
            Path(__file__).resolve().parent.parent
            / "contracts"
            / "retrieval-eval-diagnostics.v1.schema.json"
        )
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=report, schema=schema)

    def test_deterministic_sorting(self, tmp_artifacts):
        calibrator = RetrievalEvalDiagnosticsCalibrator(index_path=tmp_artifacts["index"])
        report = calibrator.generate_report(
            [
                {"query_id": "q3", "query_text": "z", "expected_target": "b.py", "found_in_results": False, "rank_in_results": None, "top_k": None, "query_had_zero_hits": True},
                {"query_id": "q1", "query_text": "a", "expected_target": "a.py", "found_in_results": False, "rank_in_results": None, "top_k": None, "query_had_zero_hits": True},
            ]
        )
        assert [d["query_id"] for d in report["diagnostics"]] == ["q1", "q3"]

    def test_index_stats_total_chunks_vs_total_paths(self, tmp_path):
        index_file = tmp_path / "chunks.jsonl"
        chunks = [
            {"chunk_id": "c1", "path": "merger/repoground/core/merge.py", "content": "part 1"},
            {"chunk_id": "c2", "path": "merger/repoground/core/merge.py", "content": "part 2"},
        ]
        with index_file.open("w", encoding="utf-8") as f:
            for chunk in chunks:
                f.write(json.dumps(chunk) + "\n")

        calibrator = RetrievalEvalDiagnosticsCalibrator(index_path=index_file)
        report = calibrator.generate_report([])

        stats = report["metadata"]["index_stats"]
        assert stats["total_paths"] == 1
        assert stats["total_chunks"] == 2

    def test_unreadable_index_is_inconclusive_not_missing(self):
        calibrator = RetrievalEvalDiagnosticsCalibrator(index_path=Path("/does/not/exist.jsonl"))
        record = calibrator.diagnose_miss(
            query_id="q_missing_index",
            query_text="find merge",
            expected_target="merge.py",
            found_in_results=False,
            rank_in_results=None,
            top_k=10,
        )
        assert record.primary_diagnosis == "diagnostic_inconclusive"
        assert record.primary_diagnosis != "target_missing_from_index"
        note = record.diagnosis_details.get("instrumentation_notes")
        assert isinstance(note, str)
        assert "index" in note.lower()
        assert "unavailable" in note.lower()

    def test_readable_empty_index_can_be_missing_from_index(self, tmp_path):
        index_file = tmp_path / "empty_chunks.jsonl"
        index_file.write_text("", encoding="utf-8")

        calibrator = RetrievalEvalDiagnosticsCalibrator(index_path=index_file)
        record = calibrator.diagnose_miss(
            query_id="q_empty_index",
            query_text="find merge",
            expected_target="merge.py",
            found_in_results=False,
            rank_in_results=None,
            top_k=10,
        )
        assert record.primary_diagnosis == "target_missing_from_index"

    def test_unsupported_index_format_is_inconclusive_not_missing(self, tmp_path):
        sqlite_like_index = tmp_path / "chunk_index.index.sqlite"
        sqlite_like_index.write_text("not-a-jsonl-index", encoding="utf-8")

        calibrator = RetrievalEvalDiagnosticsCalibrator(index_path=sqlite_like_index)
        record = calibrator.diagnose_miss(
            query_id="q_sqlite_index",
            query_text="find merge",
            expected_target="merge.py",
            found_in_results=False,
            rank_in_results=None,
            top_k=10,
        )
        assert record.primary_diagnosis == "diagnostic_inconclusive"
        assert record.primary_diagnosis != "target_missing_from_index"
        note = record.diagnosis_details.get("instrumentation_notes")
        assert isinstance(note, str)
        assert "index" in note.lower() or "unsupported" in note.lower()

    def test_found_outside_top_k_not_classified_as_top_k_hit(self, tmp_artifacts):
        calibrator = RetrievalEvalDiagnosticsCalibrator(
            index_path=tmp_artifacts["index"],
            canonical_path=tmp_artifacts["canonical"],
            citation_path=tmp_artifacts["citation"],
        )
        record = calibrator.diagnose_miss(
            query_id="q_overfetch",
            query_text="find merge",
            expected_target="merge.py",
            found_in_results=True,
            rank_in_results=45,
            top_k=10,
        )
        assert record.primary_diagnosis == "target_exists_not_in_top_k"
        assert record.primary_diagnosis != "target_in_top_k"
        assert record.diagnosis_details["rank_in_results"] == 45
