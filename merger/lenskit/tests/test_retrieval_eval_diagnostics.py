"""
Tests for retrieval evaluation diagnostics calibrator.

Tests all diagnostic categories without modifying retrieval behavior.
"""

import json
import pytest
from pathlib import Path
from merger.lenskit.retrieval.eval_diagnostics import (
    ReturnEvalDiagnosticsCalibrator,
    DiagnosticsRecord,
    IndexInspector,
    MissingArtifactError,
)
import jsonschema


@pytest.fixture
def tmp_artifacts(tmp_path):
    """Create temporary index and canonical artifacts for testing."""
    # Create chunk_index.jsonl
    index_file = tmp_path / "chunks.jsonl"
    chunks = [
        {"chunk_id": "c1", "path": "src/auth/login.py", "content": "def login(): pass"},
        {"chunk_id": "c2", "path": "src/config/settings.py", "content": "SECRET = 'x'"},
        {"chunk_id": "c3", "path": "docs/api.md", "content": "# API"},
        {"chunk_id": "c4", "path": "src/utils/helpers.py", "content": "def help(): pass"},
    ]
    with open(index_file, "w", encoding="utf-8") as f:
        for chunk in chunks:
            f.write(json.dumps(chunk) + "\n")

    # Create canonical_md
    canonical_file = tmp_path / "canonical.md"
    canonical_content = """# Canonical Content

## Files
- `src/auth/login.py`: Authentication module
- `src/config/settings.py`: Configuration settings
- `docs/api.md`: API documentation
- `src/utils/helpers.py`: Helper utilities
"""
    canonical_file.write_text(canonical_content, encoding="utf-8")

    # Create citation_map_jsonl
    citation_file = tmp_path / "citation_map.jsonl"
    citations = [
        {"citation_id": "src/auth/login.py", "path": "src/auth/login.py", "refs": []},
        {"citation_id": "src/config/settings.py", "path": "src/config/settings.py", "refs": []},
        {"citation_id": "docs/api.md", "path": "docs/api.md", "refs": []},
    ]
    with open(citation_file, "w", encoding="utf-8") as f:
        for citation in citations:
            f.write(json.dumps(citation) + "\n")

    return {
        "index": index_file,
        "canonical": canonical_file,
        "citation": citation_file,
        "tmp_path": tmp_path,
    }


class TestDiagnosticsRecord:
    """Test DiagnosticsRecord class."""

    def test_valid_record(self):
        """Test creating a valid diagnostics record."""
        record = DiagnosticsRecord(
            query_id="q1",
            query_text="find login",
            expected_target="src/auth/login.py",
            primary_diagnosis="target_in_top_k",
            diagnosis_details={"confidence": "high", "rank_in_results": 1},
        )
        assert record.query_id == "q1"
        assert record.primary_diagnosis == "target_in_top_k"

    def test_invalid_diagnosis(self):
        """Test that invalid diagnosis raises error."""
        with pytest.raises(ValueError):
            DiagnosticsRecord(
                query_id="q1",
                query_text="find login",
                expected_target="src/auth/login.py",
                primary_diagnosis="invalid_diagnosis",
                diagnosis_details={},
            )

    def test_to_dict(self):
        """Test converting record to dict."""
        record = DiagnosticsRecord(
            query_id="q1",
            query_text="find login",
            expected_target="src/auth/login.py",
            primary_diagnosis="target_in_top_k",
            diagnosis_details={"confidence": "high"},
        )
        d = record.to_dict()
        assert d["query_id"] == "q1"
        assert d["primary_diagnosis"] == "target_in_top_k"


class TestIndexInspector:
    """Test IndexInspector class."""

    def test_load_index_paths(self, tmp_artifacts):
        """Test loading paths from chunk index."""
        inspector = IndexInspector(tmp_artifacts["index"])
        paths = inspector.load_index_paths()
        assert "src/auth/login.py" in paths
        assert "src/config/settings.py" in paths
        assert len(paths) >= 3

    def test_load_index_paths_missing_file(self):
        """Test loading non-existent index file."""
        inspector = IndexInspector(Path("/nonexistent/file.jsonl"))
        with pytest.raises(MissingArtifactError):
            inspector.load_index_paths()

    def test_load_canonical_md(self, tmp_artifacts):
        """Test loading canonical_md content."""
        inspector = IndexInspector()
        content = inspector.load_canonical_md(tmp_artifacts["canonical"])
        assert "Canonical Content" in content
        assert "src/auth/login.py" in content

    def test_load_canonical_md_missing(self):
        """Test loading non-existent canonical_md."""
        inspector = IndexInspector()
        with pytest.raises(MissingArtifactError):
            inspector.load_canonical_md(Path("/nonexistent/canonical.md"))

    def test_check_target_in_canonical_exact_match(self, tmp_artifacts):
        """Test exact target match in canonical_md."""
        inspector = IndexInspector()
        content = inspector.load_canonical_md(tmp_artifacts["canonical"])
        exists, status, variants = inspector.check_target_in_canonical(
            "src/auth/login.py", content
        )
        assert exists is True
        assert status == "exact_match"

    def test_check_target_in_canonical_not_found(self, tmp_artifacts):
        """Test target not in canonical_md."""
        inspector = IndexInspector()
        content = inspector.load_canonical_md(tmp_artifacts["canonical"])
        exists, status, variants = inspector.check_target_in_canonical(
            "src/nonexistent.py", content
        )
        assert exists is False
        assert status == "not_found"

    def test_load_citation_map(self, tmp_artifacts):
        """Test loading citation_map."""
        inspector = IndexInspector()
        citation_map = inspector.load_citation_map(tmp_artifacts["citation"])
        assert "src/auth/login.py" in citation_map


class TestReturnEvalDiagnosticsCalibrator:
    """Test ReturnEvalDiagnosticsCalibrator class."""

    def test_init_with_artifacts(self, tmp_artifacts):
        """Test initializing calibrator with artifact paths."""
        calibrator = ReturnEvalDiagnosticsCalibrator(
            index_path=tmp_artifacts["index"],
            canonical_path=tmp_artifacts["canonical"],
            citation_path=tmp_artifacts["citation"],
        )
        assert calibrator.index_path == tmp_artifacts["index"]

    def test_diagnose_target_in_top_k(self, tmp_artifacts):
        """Test diagnosis when target is found in results."""
        calibrator = ReturnEvalDiagnosticsCalibrator(
            index_path=tmp_artifacts["index"],
            canonical_path=tmp_artifacts["canonical"],
        )
        record = calibrator.diagnose_miss(
            query_id="q1",
            query_text="find login",
            expected_target="src/auth/login.py",
            found_in_results=True,
            rank_in_results=1,
            top_k=10,
        )
        assert record.primary_diagnosis == "target_in_top_k"
        assert record.diagnosis_details["confidence"] == "high"

    def test_diagnose_target_missing_from_index(self, tmp_artifacts):
        """Test diagnosis when target missing from index."""
        calibrator = ReturnEvalDiagnosticsCalibrator(
            index_path=tmp_artifacts["index"],
            canonical_path=tmp_artifacts["canonical"],
        )
        record = calibrator.diagnose_miss(
            query_id="q2",
            query_text="find missing",
            expected_target="src/nonexistent/missing.py",
            found_in_results=False,
            rank_in_results=None,
            top_k=10,
        )
        assert record.primary_diagnosis == "target_missing_from_index"
        assert record.diagnosis_details["target_found_in_index"] is False

    def test_diagnose_target_exists_not_in_top_k(self, tmp_artifacts):
        """Test diagnosis when target in index but outside top-k."""
        calibrator = ReturnEvalDiagnosticsCalibrator(
            index_path=tmp_artifacts["index"],
            canonical_path=tmp_artifacts["canonical"],
        )
        record = calibrator.diagnose_miss(
            query_id="q3",
            query_text="find helpers",
            expected_target="src/utils/helpers.py",
            found_in_results=False,
            rank_in_results=15,
            top_k=10,
        )
        assert record.primary_diagnosis == "target_exists_not_in_top_k"
        assert record.diagnosis_details["target_found_in_index"] is True

    def test_diagnose_target_missing_from_canonical(self, tmp_artifacts):
        """Test diagnosis when target missing from canonical_md."""
        calibrator = ReturnEvalDiagnosticsCalibrator(
            index_path=tmp_artifacts["index"],
            canonical_path=tmp_artifacts["canonical"],
        )
        # Add a chunk to index that's not in canonical
        with open(tmp_artifacts["index"], "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "chunk_id": "c_extra",
                "path": "src/extra/new.py",
                "content": "new code"
            }) + "\n")

        record = calibrator.diagnose_miss(
            query_id="q4",
            query_text="find new",
            expected_target="src/extra/new.py",
            found_in_results=False,
            rank_in_results=None,
            top_k=10,
        )
        # Target is in index but not in canonical
        assert record.primary_diagnosis == "target_missing_from_canonical"

    def test_diagnose_stale_expected_target(self, tmp_artifacts):
        """Test diagnosis of stale expected targets."""
        calibrator = ReturnEvalDiagnosticsCalibrator(
            index_path=tmp_artifacts["index"],
            canonical_path=tmp_artifacts["canonical"],
        )
        record = calibrator.diagnose_miss(
            query_id="q5",
            query_text="find old",
            expected_target="/tmp/old_snapshot.py",  # Stale indicator
            found_in_results=False,
            rank_in_results=None,
            top_k=10,
        )
        assert record.primary_diagnosis == "stale_expected_target"

    def test_diagnose_ambiguous_query(self, tmp_artifacts):
        """Test diagnosis of ambiguous targets."""
        calibrator = ReturnEvalDiagnosticsCalibrator(
            index_path=tmp_artifacts["index"],
            canonical_path=tmp_artifacts["canonical"],
        )
        record = calibrator.diagnose_miss(
            query_id="q6",
            query_text="find it",
            expected_target="",  # Empty target
            found_in_results=False,
            rank_in_results=None,
            top_k=10,
        )
        assert record.primary_diagnosis == "query_target_ambiguous"

    def test_diagnose_zero_hits(self, tmp_artifacts):
        """Test diagnosis when query returns zero hits."""
        calibrator = ReturnEvalDiagnosticsCalibrator(
            index_path=tmp_artifacts["index"],
            canonical_path=tmp_artifacts["canonical"],
        )
        record = calibrator.diagnose_miss(
            query_id="q7",
            query_text="find xyz",
            expected_target="src/xyz/file.py",
            found_in_results=False,
            rank_in_results=None,
            top_k=10,
            query_had_zero_hits=True,
        )
        assert record.diagnosis_details["query_had_zero_hits"] is True

    def test_generate_report(self, tmp_artifacts):
        """Test generating a complete diagnostic report."""
        calibrator = ReturnEvalDiagnosticsCalibrator(
            index_path=tmp_artifacts["index"],
            canonical_path=tmp_artifacts["canonical"],
            citation_path=tmp_artifacts["citation"],
        )
        misses = [
            {
                "query_id": "q1",
                "query_text": "find login",
                "expected_target": "src/auth/login.py",
                "found_in_results": True,
                "rank_in_results": 1,
                "top_k": 10,
                "query_had_zero_hits": False,
            },
            {
                "query_id": "q2",
                "query_text": "find missing",
                "expected_target": "src/nonexistent.py",
                "found_in_results": False,
                "rank_in_results": None,
                "top_k": 10,
                "query_had_zero_hits": False,
            },
            {
                "query_id": "q3",
                "query_text": "find helpers",
                "expected_target": "src/utils/helpers.py",
                "found_in_results": False,
                "rank_in_results": 15,
                "top_k": 10,
                "query_had_zero_hits": False,
            },
        ]
        report = calibrator.generate_report(misses)
        
        # Verify report structure
        assert "metadata" in report
        assert "diagnostics" in report
        assert report["metadata"]["total_misses"] == 3
        assert report["metadata"]["version"] == "1.0"
        assert "timestamp" in report["metadata"]

        # Verify diagnostic breakdowns
        breakdowns = report["metadata"]["diagnostic_breakdowns"]
        # q1: found in results -> target_in_top_k
        # q2: not in index -> target_missing_from_index
        # q3: in index and canonical, but not in citation_map -> target_missing_from_citation_map
        assert breakdowns["target_in_top_k"] == 1, f"Expected 1 target_in_top_k, got {breakdowns}"
        assert breakdowns["target_missing_from_index"] == 1, f"Expected 1 target_missing_from_index, got {breakdowns}"
        # src/utils/helpers.py is not in citation_map, so it gets that diagnosis instead of ranking
        assert breakdowns["target_missing_from_citation_map"] == 1, f"Expected 1 target_missing_from_citation_map, got {breakdowns}"

        # Verify diagnostics array
        assert len(report["diagnostics"]) == 3
        # Verify sorting is by query_id + expected_target
        assert report["diagnostics"][0]["query_id"] == "q1"

    def test_save_report(self, tmp_artifacts):
        """Test saving report to file."""
        output_file = tmp_artifacts["tmp_path"] / "diagnostics_report.json"
        calibrator = ReturnEvalDiagnosticsCalibrator(
            index_path=tmp_artifacts["index"],
            canonical_path=tmp_artifacts["canonical"],
        )
        misses = [
            {
                "query_id": "q1",
                "query_text": "find login",
                "expected_target": "src/auth/login.py",
                "found_in_results": True,
                "rank_in_results": 1,
                "top_k": 10,
                "query_had_zero_hits": False,
            },
        ]
        report = calibrator.generate_report(misses)
        calibrator.save_report(report, output_file)
        
        assert output_file.exists()
        saved_data = json.loads(output_file.read_text(encoding="utf-8"))
        assert saved_data["metadata"]["total_misses"] == 1

    def test_report_conforms_to_schema(self, tmp_artifacts):
        """Test that generated report conforms to schema."""
        calibrator = ReturnEvalDiagnosticsCalibrator(
            index_path=tmp_artifacts["index"],
            canonical_path=tmp_artifacts["canonical"],
        )
        misses = [
            {
                "query_id": "q1",
                "query_text": "find login",
                "expected_target": "src/auth/login.py",
                "found_in_results": True,
                "rank_in_results": 1,
                "top_k": 10,
                "query_had_zero_hits": False,
            },
        ]
        report = calibrator.generate_report(misses)
        
        # Load the schema
        schema_path = Path(__file__).resolve().parent.parent / "contracts" / "retrieval-eval-diagnostics.v1.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        
        # Validate report against schema
        try:
            jsonschema.validate(instance=report, schema=schema)
        except jsonschema.ValidationError as e:
            pytest.fail(f"Report does not conform to schema: {e.message}")

    def test_deterministic_sorting(self, tmp_artifacts):
        """Test that diagnostics are deterministically sorted."""
        calibrator = ReturnEvalDiagnosticsCalibrator(
            index_path=tmp_artifacts["index"],
            canonical_path=tmp_artifacts["canonical"],
        )
        misses = [
            {
                "query_id": "q3",
                "query_text": "z query",
                "expected_target": "z target",
                "found_in_results": False,
                "rank_in_results": None,
                "top_k": 10,
                "query_had_zero_hits": False,
            },
            {
                "query_id": "q1",
                "query_text": "a query",
                "expected_target": "a target",
                "found_in_results": False,
                "rank_in_results": None,
                "top_k": 10,
                "query_had_zero_hits": False,
            },
            {
                "query_id": "q2",
                "query_text": "m query",
                "expected_target": "m target",
                "found_in_results": False,
                "rank_in_results": None,
                "top_k": 10,
                "query_had_zero_hits": False,
            },
        ]
        report = calibrator.generate_report(misses)
        
        # Check ordering by query_id
        query_ids = [d["query_id"] for d in report["diagnostics"]]
        assert query_ids == sorted(query_ids)


def test_secondary_diagnoses():
    """Test that secondary diagnoses are correctly set."""
    record = DiagnosticsRecord(
        query_id="q1",
        query_text="find login",
        expected_target="src/auth/login.py",
        primary_diagnosis="target_exists_not_in_top_k",
        diagnosis_details={
            "confidence": "medium",
            "secondary_diagnoses": ["low_query_specificity", "index_stale"],
        },
    )
    assert len(record.diagnosis_details["secondary_diagnoses"]) == 2
