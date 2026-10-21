"""Retrieval resilience and source-address surfacing for RepoBrief ask packs.

Covers two guarantees added on top of the deterministic FTS retrieval:

* the ask pack never returns silently empty context — it reports the executed
  FTS query, a strategy, and a caveat, and falls back to a labelled relaxed OR
  match when the strict AND query finds nothing;
* resolved ranges surface the original repository source address so navigation
  tasks do not have to parse it out of the excerpt text.
"""

import unicodedata

from merger.repoground.core.ask_context import (
    _content_tokens,
    _or_fts_query,
    _resolved_ranges,
    _resolved_ranges_with_budget,
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
    assert pack["retrieval_hits"] == []
    assert pack["resolved_ranges"] == []
    assert "structured_evidence" not in pack
    no_evidence_caveats = [
        caveat
        for caveat in pack["answer_scaffold"]["caveats_to_surface"]
        if caveat["kind"] == "other" and "No evidence matched" in caveat["detail"]
    ]
    assert len(no_evidence_caveats) == 1


def test_content_tokens_drop_stopwords_and_dedupe():
    assert _content_tokens("How does the live freshness live check work?") == [
        "live",
        "freshness",
        "check",
        "work",
    ]
    # An all-stopword query yields no content tokens, so no OR retry is attempted.
    assert _content_tokens("how does the is are") == []


def test_content_tokens_preserve_unicode_words_for_or_fallback():
    assert _content_tokens("Wie funktioniert die Übergabe?") == [
        "funktioniert",
        "übergabe",
    ]


def test_content_tokens_normalize_decomposed_unicode_for_or_fallback():
    query = unicodedata.normalize("NFD", "Wie funktioniert die Übergabe?")

    assert _content_tokens(query) == [
        "funktioniert",
        "übergabe",
    ]


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


def test_resolved_ranges_enforce_utf8_bytes_without_splitting_unicode():
    query_result = {
        "resolved_evidence": {
            "hits": [
                {
                    "artifact_role": "canonical_md",
                    "range_status": "resolved",
                    "range": {"text": "é🙂z"},
                    "source_path": "docs/unicode.md",
                    "range_ref": {"ref": "unicode"},
                }
            ]
        }
    }

    ranges, used_bytes, used_characters, truncated, omissions = (
        _resolved_ranges_with_budget(
            query_result,
            max_context_tokens=100,
            max_context_bytes=5,
        )
    )

    assert ranges[0]["text_excerpt"] == "é"
    assert ranges[0]["text_excerpt_bytes"] == 2
    assert ranges[0]["text_excerpt_characters"] == 1
    assert used_bytes == 2
    assert used_characters == 1
    assert used_bytes != used_characters
    assert truncated is True
    assert omissions[0]["reason"] == "excerpt_truncated"


def test_relaxed_or_preserves_diverse_source_paths_and_original_citations(monkeypatch):
    """Overlapping test chunks must not hide an indexed implementation chunk."""
    from pathlib import Path

    from merger.repoground.core import ask_context as context

    # This order reproduces the observed Codex finalizer miss at small k:
    # one test file occupies three high-BM25 chunks; implementation ranks sixth.
    paths = [
        "tests/test_job_finalizer.py",
        "tests/test_job_finalizer.py",
        "docs/security-model.md",
        "tests/test_job_finalizer.py",
        "tests/test_deploy_runtime.py",
        "src/grabowski_job_finalizer.py",
    ]
    results = [
        {"chunk_id": f"chunk-{index}", "source_path": path, "score": float(index)}
        for index, path in enumerate(paths)
    ]
    evidence = [
        {
            "chunk_id": f"chunk-{index}",
            "source_path": path,
            "range_status": "resolved",
            "range_ref": {"ref": f"range-{index}"},
            "range": {"text": f"verified source evidence for {path}"},
            "source_line_range": {"start_line": 1, "end_line": 1},
            "citation_id": f"cit_{index}",
        }
        for index, path in enumerate(paths)
    ]
    projected = [
        {"chunk_id": f"chunk-{index}", "citation_id": f"cit_{index}"}
        for index in range(len(paths))
    ]
    calls = []

    def fake_index_query(_manifest, _query, k, prepared_fts_query=None):
        calls.append((k, prepared_fts_query))
        if prepared_fts_query is None:
            return {
                "status": "available",
                "query_result": {"results": [], "fts_query": "strict AND"},
                "resolved_evidence": {"hits": []},
            }
        return {
            "status": "available",
            "query_result": {"results": results[:k], "fts_query": prepared_fts_query},
            "resolved_evidence": {"hits": evidence[:k]},
            "source_citation_projection": {"items": projected[:k]},
        }

    monkeypatch.setattr(context, "_run_query", fake_index_query)
    monkeypatch.setattr(context, "_relaxed_path_index_reads", lambda *_a, **_k: [])
    pack = context._query_context(
        Path("unused-bound-manifest"),
        query="Find job finalizer implementation and real test",
        k=3,
        max_context_tokens=1000,
        max_context_bytes=4000,
    )
    retrieved = pack["resolved_ranges"]
    assert calls[0][0] == 3
    assert calls[1][0] > 3  # bounded overfetch before selecting exactly k
    assert len(retrieved) == 3
    assert len({item["source_path"] for item in retrieved}) == 3
    assert "src/grabowski_job_finalizer.py" in {
        item["source_path"] for item in retrieved
    }
    assert {item["citation_id"] for item in retrieved} <= {
        item["citation_id"] for item in pack["retrieval_hits"]
    }
    assert pack["strategy"] == "or_relaxed"
    assert pack["used_bytes"] <= 4000


def test_broad_navigation_or_fallback_recovers_verified_source_paths(monkeypatch):
    """The read-only OR fallback should not hide implementation behind test hits."""
    from pathlib import Path

    from merger.repoground.core import ask_context as module

    def evidence(paths):
        rows = []
        resolved = []
        projections = []
        for number, path in enumerate(paths):
            chunk_id = f"chunk-{number}-{path}"
            citation_id = f"cit_{number:02d}abcdef"
            rows.append({"chunk_id": chunk_id, "source_path": path, "score": -1.0})
            resolved.append(
                {
                    "chunk_id": chunk_id,
                    "source_path": path,
                    "range_status": "resolved",
                    "range": {"text": f"Bounded, verified contents of {path}"},
                    "source_line_range": {"start_line": 1, "end_line": 2},
                    "range_ref": {"ref": chunk_id},
                    "citation_id": citation_id,
                }
            )
            projections.append({"chunk_id": chunk_id, "citation_id": citation_id})
        return {
            "status": "available",
            "query_result": {"results": rows, "fts_query": '"finalizer" OR "runtime"'},
            "resolved_evidence": {"hits": resolved},
            "source_citation_projection": {"items": projections},
        }

    tests = [
        (
            "Job finalizer implementation and corresponding real test",
            [
                "tests/test_job_finalizer.py",
                "docs/security-model.md",
                "tests/test_runtime.py",
            ],
            {
                "finalizer": [
                    "tests/test_job_finalizer.py",
                    "src/grabowski_job_finalizer.py",
                ],
            },
            {"src/grabowski_job_finalizer.py"},
        ),
        (
            "Find configured runtime entrypoint and Grabowski operator implementation",
            [
                "tests/test_deployment_metadata.py",
                "tools/deploy_runtime.py",
                "src/grabowski_mcp.py",
            ],
            {
                "runtime": [
                    "tools/deploy_runtime.py",
                    "src/grabowski_runtime.py",
                    "config/runtime-entrypoint.json",
                ],
                "entrypoint": ["config/runtime-entrypoint.json"],
            },
            {"src/grabowski_runtime.py", "config/runtime-entrypoint.json"},
        ),
    ]
    for query, original, source_paths, required in tests:
        calls = []

        def fake_run(_manifest, _query, _k, prepared_fts_query=None):
            return evidence([] if prepared_fts_query is None else original)

        def fake_index(_manifest, query_text, *, filters=None, **kwargs):
            path = (filters or {}).get("path", "")
            calls.append((query_text, path, kwargs))
            # The path hint is an FTS-constrained substring filter, not an
            # exact-path query. Every simulated candidate still has evidence.
            return evidence(source_paths.get(path, []))

        monkeypatch.setattr(module, "_run_query", fake_run)
        monkeypatch.setattr(module, "query_existing_index", fake_index)
        state = module._query_context(
            Path("/immutable/manifest.json"),
            query=query,
            k=3,
            max_context_tokens=5000,
            max_context_bytes=10000,
        )
        returned = {hit["source_path"] for hit in state["resolved_ranges"]}
        assert state["strategy"] == "or_relaxed"
        assert required <= returned
        assert len(state["resolved_ranges"]) <= 3
        assert state["used_bytes"] <= 10000
        assert all(
            hit["citation_id"].startswith("cit_") for hit in state["resolved_ranges"]
        )
        assert all(call[2].get("k", 0) <= 100 for call in calls)
        assert 1 <= len(calls) <= 2
        assert all(
            q == query and options.get("prepared_fts_query") for q, _, options in calls
        )


def test_balanced_relaxed_ranges_reserves_bytes_for_each_verified_source():
    from merger.repoground.core.ask_context import _balanced_relaxed_ranges

    paths = [
        "tests/test_runtime.py",
        "src/grabowski_runtime.py",
        "config/runtime-entrypoint.json",
    ]
    selected = {
        "resolved_evidence": {
            "hits": [
                {
                    "chunk_id": f"chunk-{i}",
                    "source_path": path,
                    "range_status": "resolved",
                    "range_ref": {"ref": f"range-{i}"},
                    "range": {"text": "verified " + ("x" * 1000)},
                    "citation_id": f"cit_{i}",
                }
                for i, path in enumerate(paths)
            ]
        }
    }
    ranges, used_bytes, _chars, truncated, _omissions = _balanced_relaxed_ranges(
        selected, max_context_tokens=1000, max_context_bytes=900
    )
    assert [row["source_path"] for row in ranges] == paths
    assert 0 < used_bytes <= 900
    assert all(row["text_excerpt_bytes"] <= 300 for row in ranges)
    assert truncated is True


def test_relaxed_source_candidates_retain_sparse_and_substring_matched_sources():
    from merger.repoground.core.ask_context import (
        _balanced_relaxed_ranges,
        _prefer_diverse_relaxed_sources,
    )

    def indexed(paths):
        rows = []
        hits = []
        citations = []
        for path in paths:
            ref = "chunk:" + path
            rows.append({"chunk_id": ref, "source_path": path})
            hits.append(
                {
                    "chunk_id": ref,
                    "source_path": path,
                    "range_status": "resolved",
                    "range_ref": {"ref": ref},
                    "range": {"text": "verified source" * 35},
                    "citation_id": "cit_" + str(len(hits)),
                }
            )
            citations.append({"chunk_id": ref, "citation_id": hits[-1]["citation_id"]})
        return {
            "query_result": {"results": rows},
            "resolved_evidence": {"hits": hits},
            "source_citation_projection": {"items": citations},
        }

    original = indexed(["tests/test_runtime.py"])
    # The path index can return another substring match first. That must not
    # prevent the real implementation from being selected and cited.
    hints = indexed(["fixtures/src/grabowski_runtime.py", "src/grabowski_runtime.py"])
    selected = _prefer_diverse_relaxed_sources(
        original,
        query="Find Grabowski runtime implementation",
        k=5,
        path_results=[hints],
    )
    ranges, used, _chars, _truncated, _omissions = _balanced_relaxed_ranges(
        selected, max_context_tokens=1000, max_context_bytes=6000
    )
    assert len(ranges) == 3  # fewer than k is still a valid complete result
    assert {row["source_path"] for row in ranges} == {
        "tests/test_runtime.py",
        "fixtures/src/grabowski_runtime.py",
        "src/grabowski_runtime.py",
    }
    assert 0 < used <= 6000
    assert {hit["citation_id"] for hit in selected["resolved_evidence"]["hits"]} == {
        row["citation_id"] for row in ranges
    }
