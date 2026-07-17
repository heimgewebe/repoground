import pytest

from merger.repoground.core.history_lens import build_history_lens


RECORDS = [
    {"commit": "a" * 40, "path": "src/a.py", "pr": 1, "author": "Ada", "summary": "touch a"},
    {"commit": "b" * 40, "path": "src/a.py", "pr": 2, "author": "Bob", "summary": "touch a again"},
    {"commit": "c" * 40, "path": "src/b.py", "pr": 3, "author": "Cyd", "summary": "touch b"},
]


def test_history_lens_is_derived_navigation_not_canonical_truth():
    lens = build_history_lens(RECORDS, profile="summary")

    assert lens["kind"] == "repobrief.history_lens"
    assert lens["derived_navigation"] is True
    assert lens["canonical_content_truth"] is False
    assert "canonical_content_truth" in lens["does_not_establish"]
    assert lens["file_churn"] == [
        {"path": "src/a.py", "commit_count": 2, "navigation_only": True},
        {"path": "src/b.py", "commit_count": 1, "navigation_only": True},
    ]


def test_history_lens_export_profile_controls_metadata_inclusion():
    disabled = build_history_lens(RECORDS, profile="disabled")
    full_without_authors = build_history_lens(RECORDS, profile="full")
    full_with_authors = build_history_lens(RECORDS, profile="full", include_author_metadata=True)

    assert disabled["status"] == "not_applicable"
    assert disabled["export_policy"]["history_metadata_included"] is False
    assert full_without_authors["export_policy"]["history_metadata_included"] is True
    assert full_without_authors["export_policy"]["author_metadata_included"] is False
    assert "author" not in full_without_authors["provenance_chains"][0]
    assert full_with_authors["export_policy"]["author_metadata_included"] is True
    assert full_with_authors["provenance_chains"][0]["author"] == "Ada"


def test_history_lens_forbids_blame_ownership_correctness_and_completeness_verdicts():
    lens = build_history_lens(RECORDS, profile="summary")

    assert "person_blame" in lens["forbidden_verdicts"]
    assert "ownership" in lens["forbidden_verdicts"]
    assert "correctness" in lens["forbidden_verdicts"]
    assert "completeness" in lens["forbidden_verdicts"]
    assert "ownership_verdict" in lens["does_not_establish"]


def test_history_lens_preserves_live_state_boundary():
    lens = build_history_lens(RECORDS, profile="summary")

    assert "live GitHub/CI/PR checks" in lens["live_state_boundary"]
    assert "live_github_state" in lens["does_not_establish"]
    assert "ci_state" in lens["does_not_establish"]
    assert "pull_request_state" in lens["does_not_establish"]


def test_history_lens_rejects_unknown_profile():
    with pytest.raises(ValueError, match="unsupported history lens profile"):
        build_history_lens(RECORDS, profile="unsafe")
