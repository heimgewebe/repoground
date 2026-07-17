from pathlib import Path


DOC = Path(__file__).parents[3] / "docs" / "proofs" / "query-range-ref-audit-proof.md"


def test_query_range_ref_audit_records_current_surfaces_and_gaps():
    text = DOC.read_text(encoding="utf-8")
    for token in (
        "range_ref",
        "derived_range_ref",
        "content_range_ref",
        "query-result.v1.schema.json",
        "claim_boundaries",
        "result_ranges",
        "citation_map_jsonl",
        "all-hit range guarantee",
        "query-range-coverage report",
        "does not establish",
    ):
        assert token in text


def test_query_range_ref_audit_keeps_diagnostic_boundary():
    text = DOC.read_text(encoding="utf-8")
    for forbidden in (
        "answer correctness: true",
        "claim truth: true",
        "retrieval completeness: true",
        "repo_understood: true",
        "every query result is citation-ready: true",
    ):
        assert forbidden not in text
