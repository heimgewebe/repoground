"""Retrieval resilience and source-address surfacing for RepoBrief ask packs.

Covers two guarantees added on top of the deterministic FTS retrieval:

* the ask pack never returns silently empty context — it reports the executed
  FTS query, a strategy, and a caveat, and falls back to a labelled relaxed OR
  match when the strict AND query finds nothing;
* resolved ranges surface the original repository source address so navigation
  tasks do not have to parse it out of the excerpt text.
"""

from merger.repoground.core.ask_context import (
    _content_tokens,
    _or_fts_query,
    _resolved_ranges,
    build_ask_context_pack,
)
from merger.repoground.tests.test_ask_context_cli import (
    _complete_basic_bundle,
    _validate_context_pack,
)


def test_exact_match_reports_strategy_and_source_address(tmp_path):
    bundle = _complete_basic_bundle(tmp_path)

    pack = build_ask_context_pack(bundle["manifest"], query="hello", k=5)

    _validate_context_pack(pack)
    assert pack["retrieval"]["strategy"] == "exact_and"
    assert pack["retrieval"]["match_count"] >= 1
    assert pack["retrieval"]["fts_query"] == "hello"

    first = pack["resolved_ranges"][0]
    assert first["source_path"] == "brief.md"
    assert first["source_line_range"]["start_line"] == 3
    assert first["citation_id"].startswith("cit_")


def test_natural_language_query_falls_back_to_labelled_or(tmp_path):
    bundle = _complete_basic_bundle(tmp_path)

    # "work" is absent from the indexed chunk, so the strict AND query is empty;
    # the OR relaxation over content tokens recovers a candidate.
    pack = build_ask_context_pack(
        bundle["manifest"], query="How does hello resolved work?", k=5
    )

    _validate_context_pack(pack)
    assert pack["retrieval"]["strategy"] == "or_relaxed"
    assert pack["retrieval"]["match_count"] >= 1
    assert " OR " in pack["retrieval"]["fts_query"]
    assert any(
        caveat["kind"] == "other" and "relaxed OR-matches" in caveat["detail"]
        for caveat in pack["answer_scaffold"]["caveats_to_surface"]
    )


def test_no_match_query_signals_emptiness_instead_of_silence(tmp_path):
    bundle = _complete_basic_bundle(tmp_path)

    pack = build_ask_context_pack(
        bundle["manifest"], query="zzznosuchterm qqqmissing", k=5
    )

    _validate_context_pack(pack)
    assert pack["retrieval"]["strategy"] == "none"
    assert pack["retrieval"]["match_count"] == 0
    assert pack["resolved_ranges"] == []
    assert any(
        caveat["kind"] == "other" and "No evidence matched" in caveat["detail"]
        for caveat in pack["answer_scaffold"]["caveats_to_surface"]
    )


def test_content_tokens_drop_stopwords_and_dedupe():
    assert _content_tokens("How does the live freshness live check work?") == [
        "live",
        "freshness",
        "check",
        "work",
    ]
    # An all-stopword query yields no content tokens, so no OR retry is attempted.
    assert _content_tokens("how does the is are") == []


def test_content_tokens_adds_deterministic_snake_case_parts_for_or_fallback():
    assert _content_tokens("How does build_live_repo_address work?") == [
        "build_live_repo_address",
        "build",
        "live",
        "repo",
        "address",
        "work",
    ]


def test_or_fts_query_quotes_terms_to_keep_them_literal():
    assert _or_fts_query(["live", "freshness"]) == '"live" OR "freshness"'


def test_resolved_ranges_share_budget_and_drop_empty_or_duplicate_hits():
    base = {
        "artifact_role": "canonical_md",
        "range_status": "resolved",
        "range": {"text": "x" * 5000},
    }
    query_result = {
        "resolved_evidence": {
            "hits": [
                {
                    **base,
                    "source_path": "src/first.py",
                    "source_line_range": {"start_line": 1, "end_line": 10},
                    "range_ref": {"ref": "first"},
                },
                {
                    **base,
                    "source_path": "src/second.py",
                    "source_line_range": {"start_line": 1, "end_line": 10},
                    "range_ref": {"ref": "second"},
                },
                {
                    **base,
                    "source_path": "docs/diagnostics/third.json",
                    "source_line_range": {"start_line": 1, "end_line": 10},
                    "range_ref": {"ref": "third"},
                },
                {
                    **base,
                    "range": {"text": ""},
                    "source_path": "src/empty.py",
                    "range_ref": {"ref": "empty"},
                },
                {
                    **base,
                    "source_path": "src/first.py",
                    "source_line_range": {"start_line": 1, "end_line": 10},
                    "range_ref": {"ref": "first"},
                },
            ]
        }
    }

    ranges, used_chars, truncated = _resolved_ranges(
        query_result, max_context_tokens=1000
    )

    assert [item["source_path"] for item in ranges] == [
        "src/first.py",
        "src/second.py",
        "docs/diagnostics/third.json",
    ]
    assert all(0 < len(item["text_excerpt"]) <= 1600 for item in ranges)
    assert used_chars <= 4000
    assert truncated is True
