"""Retrieval resilience and source-address surfacing for RepoBrief ask packs.

Covers two guarantees added on top of the deterministic FTS retrieval:

* the ask pack never returns silently empty context — it reports the executed
  FTS query, a strategy, and a caveat, and falls back to a labelled relaxed OR
  match when the strict AND query finds nothing;
* resolved ranges surface the original repository source address so navigation
  tasks do not have to parse it out of the excerpt text.
"""
from merger.lenskit.core.repobrief_ask import (
    _content_tokens,
    _or_fts_query,
    build_ask_context_pack,
)
from merger.lenskit.tests.test_repobrief_ask_cli import (
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


def test_or_fts_query_quotes_terms_to_keep_them_literal():
    assert _or_fts_query(["live", "freshness"]) == '"live" OR "freshness"'
