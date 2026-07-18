import json
from merger.repoground.cli.main import main
from merger.repoground.core import review_coverage as cov


def _delta_context() -> dict:
    return {
        "kind": "repobrief.delta_context_compiler",
        "version": "v1",
        "status": "pass",
        "diff": {"file_count": 3},
        "changed_files": [
            {
                "path": "merger/repoground/core/example.py",
                "change_status": "modified",
                "binary": False,
                "hunks": [
                    {
                        "header": "@@ -10,3 +10,4 @@",
                        "changed_range": {"start_line": 10, "end_line": 13, "line_count": 4, "basis": "new"},
                    }
                ],
            },
            {
                "path": "merger/repoground/core/other.py",
                "change_status": "modified",
                "binary": False,
                "hunks": [
                    {
                        "header": "@@ -20,2 +20,3 @@",
                        "changed_range": {"start_line": 20, "end_line": 22, "line_count": 3, "basis": "new"},
                    }
                ],
            },
            {
                "path": "assets/logo.png",
                "change_status": "modified",
                "binary": True,
                "hunks": [],
            },
        ],
    }


def test_review_coverage_measures_cited_and_uncovered_ranges_from_text():
    review = "I checked merger/repoground/core/example.py#L10-L13 and noted assets/logo.png."

    result = cov.compile_review_coverage(
        delta_context=_delta_context(),
        review_text=review,
        min_range_coverage=0.75,
    )

    assert result["kind"] == "repobrief.review_coverage"
    assert result["status"] == "warn"
    assert result["coverage"]["total_relevant_ranges"] == 3
    assert result["coverage"]["cited_relevant_ranges"] == 2
    assert result["coverage"]["uncovered_relevant_ranges"] == 1
    assert result["coverage"]["range_coverage_ratio"] == 2 / 3
    assert result["thresholds"]["range_threshold_met"] is False
    assert result["thresholds"]["advisory"] is True
    assert result["bureau_evidence"]["requires_external_policy_to_gate"] is True
    assert result["mutation_boundary"]["writes"] == []
    assert "merge_readiness" in result["does_not_establish"]
    assert result["uncovered_ranges"][0]["path"] == "merger/repoground/core/other.py"


def test_review_coverage_passes_when_threshold_is_met():
    review = "See merger/repoground/core/example.py:10-13 and merger/repoground/core/other.py:L20-L22. assets/logo.png"

    result = cov.compile_review_coverage(
        delta_context=_delta_context(),
        review_text=review,
        min_range_coverage=1.0,
    )

    assert result["status"] == "pass"
    assert result["coverage"]["range_coverage_ratio"] == 1.0
    assert result["uncovered_ranges"] == []


def test_review_coverage_extracts_json_source_ranges():
    review_json = {
        "reviews": [
            {"finding": "ok", "source_range": {"file_path": "merger/repoground/core/example.py", "start_line": 10, "end_line": 13}},
            {"path": "merger/repoground/core/other.py", "line_range": [20, 22]},
        ]
    }

    result = cov.compile_review_coverage(
        delta_context=_delta_context(),
        review_text=json.dumps(review_json),
        review_json=review_json,
        min_range_coverage=0.6,
    )

    assert result["status"] == "pass"
    assert result["coverage"]["cited_relevant_ranges"] == 2
    assert result["coverage"]["uncovered_relevant_ranges"] == 1
    assert result["citations"]["citation_count"] == 2


def test_file_only_json_citation_does_not_cover_line_range():
    result = cov.compile_review_coverage(
        delta_context=_delta_context(),
        review_text=json.dumps({"path": "merger/repoground/core/example.py"}),
        review_json={"path": "merger/repoground/core/example.py"},
        min_range_coverage=0.1,
    )

    assert result["status"] == "warn"
    assert result["coverage"]["cited_relevant_ranges"] == 0
    assert {item["path"] for item in result["uncovered_ranges"]} == {
        "merger/repoground/core/example.py",
        "merger/repoground/core/other.py",
        "assets/logo.png",
    }


def test_review_coverage_no_citations_is_warn_not_proof():
    result = cov.compile_review_coverage(
        delta_context=_delta_context(),
        review_text="Looks good to me.",
        min_range_coverage=0.1,
    )

    assert result["status"] == "warn"
    assert result["coverage"]["cited_relevant_ranges"] == 0
    assert any(gap["source"] == "review" and gap["status"] == "no_citations" for gap in result["gaps"])
    assert result["bureau_evidence"]["does_not_authorize_merge"] is True


def test_review_coverage_no_citations_warns_even_with_zero_threshold():
    result = cov.compile_review_coverage(
        delta_context=_delta_context(),
        review_text="Looks good to me.",
        min_range_coverage=0.0,
    )

    assert result["status"] == "warn"
    assert result["thresholds"]["range_threshold_met"] is True
    assert any(gap["source"] == "review" and gap["severity"] == "warn" for gap in result["gaps"])


def test_review_coverage_invalid_delta_context_is_invalid():
    result = cov.compile_review_coverage(
        delta_context={"kind": "repobrief.delta_context_compiler"},
        review_text="merger/repoground/core/example.py#L10-L13",
    )

    assert result["status"] == "invalid"
    assert result["coverage"]["total_relevant_ranges"] == 0
    assert any(gap["source"] == "delta_context" and gap["severity"] == "error" for gap in result["gaps"])


def test_review_coverage_rejects_invalid_threshold():
    result = cov.compile_review_coverage(
        delta_context=_delta_context(),
        review_text="x",
        min_range_coverage=1.5,
    )

    assert result["status"] == "invalid"
    assert result["error_code"] == "threshold_invalid"


def test_review_coverage_parses_root_level_file_citation():
    delta = {
        "changed_files": [
            {
                "path": "README.md",
                "change_status": "modified",
                "binary": False,
                "hunks": [{"changed_range": {"start_line": 1, "end_line": 3, "basis": "new"}}],
            }
        ]
    }

    result = cov.compile_review_coverage(
        delta_context=delta,
        review_text="Reviewed README.md#L1-L3.",
        min_range_coverage=1.0,
    )

    assert result["status"] == "pass"
    assert result["coverage"]["range_coverage_ratio"] == 1.0
    assert result["citations"]["line_citations"][0]["path"] == "README.md"


def test_review_coverage_parses_parent_path_with_nested_source_range():
    review_json = {
        "path": "merger/repoground/core/example.py",
        "source_range": {"start_line": 10, "end_line": 13},
    }

    result = cov.compile_review_coverage(
        delta_context=_delta_context(),
        review_text=json.dumps(review_json),
        review_json=review_json,
        min_range_coverage=0.3,
    )

    assert result["status"] == "pass"
    assert result["coverage"]["cited_relevant_ranges"] == 1
    assert result["citations"]["line_citations"][0]["start_line"] == 10


def test_review_coverage_counts_only_cited_line_intersections():
    delta = {
        "changed_files": [
            {
                "path": "src/big.py",
                "change_status": "modified",
                "binary": False,
                "hunks": [{"changed_range": {"start_line": 1, "end_line": 100, "basis": "new"}}],
            }
        ]
    }

    result = cov.compile_review_coverage(
        delta_context=delta,
        review_text="Reviewed src/big.py#L1.",
        min_range_coverage=1.0,
    )

    assert result["status"] == "pass"
    assert result["coverage"]["cited_relevant_ranges"] == 1
    assert result["coverage"]["cited_relevant_lines"] == 1
    assert result["coverage"]["total_relevant_lines"] == 100
    assert result["coverage"]["line_coverage_ratio"] == 0.01


def test_review_coverage_cli_outputs_json_and_advisory_warn_exit_zero(tmp_path, capsys):
    delta = tmp_path / "delta.json"
    delta.write_text(json.dumps(_delta_context()), encoding="utf-8")
    review = tmp_path / "review.md"
    review.write_text("Only merger/repoground/core/example.py#L10-L13 was inspected.", encoding="utf-8")

    rc = main([
        "repobrief",
        "review-coverage",
        "compile",
        "--delta-context",
        str(delta),
        "--review",
        str(review),
        "--min-range-coverage",
        "0.8",
        "--policy-name",
        "demo-advisory",
    ])

    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["kind"] == "repobrief.review_coverage"
    assert out["status"] == "warn"
    assert out["policy_name"] == "demo-advisory"
    assert out["thresholds"]["external_policy_required_to_gate"] is True
