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


def test_ordinary_relaxed_or_keeps_bm25_order_without_path_hints(monkeypatch):
    """Non-navigation fallback must not substitute filename overlap for BM25."""
    from pathlib import Path
    from merger.repoground.core import ask_context as context

    paths = [
        "src/error_flow.py",
        "src/session_timeout.py",
        "src/authentication.py",
    ]

    def indexed(source_paths):
        rows = [
            {"chunk_id": f"chunk-{i}", "source_path": path}
            for i, path in enumerate(source_paths)
        ]
        hits = [
            {
                "chunk_id": row["chunk_id"],
                "source_path": row["source_path"],
                "range_status": "resolved",
                "range_ref": {"ref": row["chunk_id"]},
                "range": {"text": "verified ranked explanation " + row["source_path"]},
                "citation_id": f"cit_{i}",
            }
            for i, row in enumerate(rows)
        ]
        return {
            "status": "available",
            "query_result": {
                "results": rows,
                "fts_query": '"authentication" OR "expired"',
            },
            "resolved_evidence": {"hits": hits},
            "source_citation_projection": {
                "items": [
                    {"chunk_id": hit["chunk_id"], "citation_id": hit["citation_id"]}
                    for hit in hits
                ],
            },
        }

    calls = []

    def query(_manifest, _question, k, prepared_fts_query=None):
        return indexed([] if prepared_fts_query is None else paths[:k])

    def path_lookup(*_args, **_kwargs):
        calls.append("path-index")
        return [indexed(["src/authentication.py"])]

    monkeypatch.setattr(context, "_run_query", query)
    monkeypatch.setattr(context, "_relaxed_path_index_reads", path_lookup)
    state = context._query_context(
        Path("immutable-manifest"),
        query="Why does authentication fail for an expired token?",
        k=2,
        max_context_tokens=1000,
        max_context_bytes=4000,
    )
    assert state["strategy"] == "or_relaxed"
    assert [row["source_path"] for row in state["resolved_ranges"]] == paths[:2]
    assert calls == []
    assert state["used_bytes"] <= 4000


def test_relaxed_response_projects_only_emitted_cited_source_rows(monkeypatch):
    """Overfetch and path-only hints must not leak raw candidate rows as answers."""
    from pathlib import Path
    from merger.repoground.core import ask_context as context

    def indexed(label, paths):
        rows = []
        hits = []
        citations = []
        for i, source in enumerate(paths):
            ref = f"{label}-chunk-{i}"
            citation = f"cit_{label}_{i}"
            rows.append({"chunk_id": ref, "source_path": source, "score": i})
            hits.append(
                {
                    "chunk_id": ref,
                    "source_path": source,
                    "range_status": "resolved",
                    "range_ref": {"ref": ref},
                    "citation_id": citation,
                    "range": {"text": "verified source " + source},
                }
            )
            citations.append({"chunk_id": ref, "citation_id": citation})
        return {
            "status": "available",
            "bundle_manifest": "immutable",
            "index_artifact": {
                "sha256": "a" * 64,
                "path": "index.sqlite",
                "bytes": 4096,
            },
            "query_result": {"results": rows},
            "resolved_evidence": {"hits": hits},
            "source_citation_projection": {"items": citations},
        }

    ranked = indexed(
        "rank",
        [
            "tests/test_runtime.py",
            "src/unrelated.py",
            "tests/test_extra.py",
        ],
    )
    source_hint = indexed("hint", ["src/runtime_entrypoint.py"])

    monkeypatch.setattr(
        context,
        "_run_query",
        lambda _manifest, _query, _k, prepared_fts_query=None: (
            ranked if prepared_fts_query is not None else indexed("strict", [])
        ),
    )
    monkeypatch.setattr(
        context,
        "_relaxed_path_index_reads",
        lambda *_args, **_kwargs: [source_hint],
    )
    for budget in (1, 4000):
        pack = context._query_context(
            Path("/immutable/bundle"),
            query="Find configured runtime entrypoint implementation",
            k=2,
            max_context_tokens=1000,
            max_context_bytes=budget,
        )
        assert pack["strategy"] == "or_relaxed"
        returned = pack["resolved_ranges"]
        projected = pack["query_result"]
        rows = projected["query_result"]["results"]
        assert 0 < len(rows) == len(returned) <= 2
        assert [row["source_path"] for row in rows] == [
            row["source_path"] for row in returned
        ]
        assert projected["query_result"]["fts_query"] == pack["fts_query"]
        cited = [row["citation_id"] for row in returned]
        assert [hit["citation_id"] for hit in pack["retrieval_hits"]] == cited
        assert [
            hit["citation_id"]
            for hit in projected["source_citation_projection"]["items"]
        ] == cited
        assert {
            hit["citation_id"] for hit in projected["resolved_evidence"]["hits"]
        } == set(cited)
        assert pack["used_bytes"] <= budget
    assert "src/runtime_entrypoint.py" in {
        row["source_path"]
        for row in context._query_context(
            Path("/immutable/bundle"),
            query="Find configured runtime entrypoint implementation",
            k=2,
            max_context_tokens=1000,
            max_context_bytes=4000,
        )["resolved_ranges"]
    }


def test_relaxed_source_pool_skips_missing_or_mismatched_citation_projection():
    """An uncitable resolved hit must not consume one of the k valid slots."""
    from merger.repoground.core.ask_context import (
        _balanced_relaxed_ranges,
        _prefer_diverse_relaxed_sources,
    )

    paths = [
        "src/no_citation.py",
        "src/wrong_citation.py",
        "src/verified_a.py",
        "src/verified_b.py",
    ]
    rows = [
        {"chunk_id": f"chunk-{i}", "source_path": path} for i, path in enumerate(paths)
    ]
    hits = [
        {
            "chunk_id": row["chunk_id"],
            "source_path": row["source_path"],
            "range_status": "resolved",
            "range_ref": {"ref": row["chunk_id"]},
            "range": {"text": "verified source contents"},
            **({} if i == 0 else {"citation_id": f"cit_{i}"}),
        }
        for i, row in enumerate(rows)
    ]
    projected = [
        {
            "chunk_id": f"chunk-{i}",
            "citation_id": ("cit_wrong" if i == 1 else f"cit_{i}"),
        }
        for i in range(1, 4)
    ]
    selected = _prefer_diverse_relaxed_sources(
        {
            "query_result": {"results": rows},
            "resolved_evidence": {"hits": hits},
            "source_citation_projection": {"items": projected},
        },
        query="Why does the cache expire unexpectedly?",
        k=2,
        path_results=[],
    )
    assert [row["source_path"] for row in selected["query_result"]["results"]] == paths[
        2:
    ]
    ranges, used, _chars, _cut, _omissions = _balanced_relaxed_ranges(
        selected,
        max_context_tokens=100,
        max_context_bytes=300,
    )
    assert used > 0
    assert [r["citation_id"] for r in ranges] == ["cit_2", "cit_3"]
    assert [
        r["citation_id"] for r in selected["source_citation_projection"]["items"]
    ] == [
        "cit_2",
        "cit_3",
    ]


def test_source_navigation_requires_an_actual_locator_phrase():
    from merger.repoground.core.ask_context import _navigation_path_intent

    for text, is_navigation in (
        ("Why does file upload fail?", False),
        ("Why is this implementation slow?", False),
        ("How is the cache path computed?", False),
        ("Why is the config file not reloaded?", False),
        ("Find job finalizer implementation and real test", True),
        ("Find configured runtime entrypoint and operator implementation", True),
        ("Where is job_finalizer handled?", True),
        ("Where is X handled?", True),
        ("Wo wird job_finalizer implementiert?", True),
        ("Which module defines job_finalizer?", True),
    ):
        assert _navigation_path_intent(text) is is_navigation, text


def test_path_hints_skip_locator_words_and_scale_with_requested_k(monkeypatch):
    from pathlib import Path
    from merger.repoground.core import ask_context as context

    calls = []

    def indexed(_manifest, _query, *, filters, k, **_kwargs):
        calls.append((filters["path"], k))
        return {"status": "available"}

    monkeypatch.setattr(context, "query_existing_index", indexed)
    context._relaxed_path_index_reads(
        Path("/immutable/index"),
        query="Locate job_finalizer implemented",
        fts_query='"job" OR "finalizer"',
        k=1,
    )
    assert calls[0][0] == "job_finalizer"
    assert 1 <= len(calls) <= 2
    assert all(0 < count <= 8 for _term, count in calls)
    assert all(term not in {"locate", "implemented"} for term, _count in calls)
    calls.clear()
    context._relaxed_path_index_reads(
        Path("/immutable/index"),
        query="Locate retry backoff",
        fts_query='"retry" OR "backoff"',
        k=1,
    )
    assert [term for term, _count in calls] == ["retry", "backoff"]
    calls.clear()
    context._relaxed_path_index_reads(
        Path("/immutable/index"),
        query="Locate configured runtime entrypoint module",
        fts_query='"runtime" OR "entrypoint"',
        k=2,
    )
    # "entrypoint" is a meaningful source-path identifier, not filler.
    assert [term for term, _count in calls] == ["runtime", "entrypoint"]


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
            "bundle_manifest": "immutable",
            "index_artifact": {
                "sha256": "a" * 64,
                "path": "index.sqlite",
                "bytes": 4096,
            },
            "query_result": {"results": rows, "fts_query": '"finalizer" OR "runtime"'},
            "resolved_evidence": {"hits": resolved},
            "source_citation_projection": {"items": projections},
        }

    tests = [
        (
            "Find job finalizer implementation and corresponding real test",
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
            "Find generated operator context surface and associated consumer-surface benchmark evidence",
            [
                "docs/consumer-surface-v1.md",
                "tools/consumer_surface_benchmark.py",
            ],
            {"operator": ["docs/generated/operator-context.v1.json"]},
            {"docs/generated/operator-context.v1.json"},
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


def test_balanced_relaxed_ranges_preserves_evidence_under_tiny_budgets():
    """Tiny positive budgets must return verified evidence, not lose every hit."""
    from merger.repoground.core.ask_context import _balanced_relaxed_ranges

    selected = {
        "resolved_evidence": {
            "hits": [
                {
                    "chunk_id": f"chunk-{i}",
                    "source_path": f"src/source_{i}.py",
                    "range_status": "resolved",
                    "range_ref": {"ref": f"range-{i}"},
                    "range": {"text": "verified source"},
                    "citation_id": f"cit_{i}",
                }
                for i in range(3)
            ]
        }
    }

    ranges, used, chars, truncated, omissions = _balanced_relaxed_ranges(
        selected, max_context_tokens=100, max_context_bytes=2
    )
    assert [row["source_path"] for row in ranges] == [
        "src/source_0.py",
        "src/source_1.py",
    ]
    assert [row["citation_id"] for row in ranges] == ["cit_0", "cit_1"]
    assert used == chars == 2
    assert all(row["text_excerpt_bytes"] == 1 for row in ranges)
    assert truncated is True
    assert omissions


def test_balanced_relaxed_ranges_uses_spare_bytes_for_utf8_evidence():
    """A share too small for UTF-8 must not discard the usable total budget."""
    from merger.repoground.core.ask_context import _balanced_relaxed_ranges

    selected = {
        "resolved_evidence": {
            "hits": [
                {
                    "chunk_id": f"utf8-{i}",
                    "source_path": f"src/unicode_{i}.py",
                    "range_status": "resolved",
                    "range_ref": {"ref": f"ref-{i}"},
                    "range": {"text": "évidence"},
                    "citation_id": f"cit_{i}",
                }
                for i in range(2)
            ]
        }
    }

    ranges, used, chars, truncated, omissions = _balanced_relaxed_ranges(
        selected, max_context_tokens=100, max_context_bytes=2
    )
    assert len(ranges) == 1
    assert ranges[0]["source_path"] == "src/unicode_0.py"
    assert ranges[0]["citation_id"] == "cit_0"
    assert ranges[0]["text_excerpt"] == "é"
    assert ranges[0]["text_excerpt_bytes"] == 2
    assert used == 2
    assert chars == 1
    assert truncated is True
    assert omissions


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


def test_navigation_requires_locator_even_for_implementation_and_test_nouns():
    """A noun phrase is not sufficient to rerank an explanatory search."""
    from merger.repoground.core.ask_context import _navigation_path_intent

    assert not _navigation_path_intent(
        "Why does the runtime implementation have a corresponding test?"
    )
    assert _navigation_path_intent(
        "Job finalizer implementation and corresponding real test"
    )
    assert _navigation_path_intent(
        "Find job finalizer implementation and corresponding real test"
    )
    assert _navigation_path_intent("Where is retry implemented?")


def test_relaxed_navigation_k_one_skips_ineffective_path_index_reads(monkeypatch):
    """When the first verified OR candidate fills k=1, path hints cannot help."""
    from pathlib import Path
    from merger.repoground.core import ask_context as context

    reads = []
    path = "src/retry.py"
    result = {
        "status": "available",
        "query_result": {
            "results": [{"chunk_id": "retry", "source_path": path}],
            "fts_query": '"retry" OR "implementation"',
        },
        "resolved_evidence": {
            "hits": [
                {
                    "chunk_id": "retry",
                    "source_path": path,
                    "range_status": "resolved",
                    "range_ref": {"ref": "retry"},
                    "range": {"text": "Verified retry implementation"},
                    "citation_id": "cit_retry",
                }
            ]
        },
        "source_citation_projection": {
            "items": [{"chunk_id": "retry", "citation_id": "cit_retry"}]
        },
    }

    def fake_run(_manifest, _query, _k, prepared_fts_query=None):
        if prepared_fts_query is None:
            return {
                "status": "available",
                "query_result": {"results": []},
                "resolved_evidence": {"hits": []},
            }
        return result

    def fake_path_reads(*_args, **_kwargs):
        reads.append(True)
        return []

    monkeypatch.setattr(context, "_run_query", fake_run)
    monkeypatch.setattr(context, "_relaxed_path_index_reads", fake_path_reads)
    state = context._query_context(
        Path("immutable-manifest"),
        query="Find retry implementation",
        k=1,
        max_context_tokens=100,
        max_context_bytes=500,
    )

    assert state["strategy"] == "or_relaxed"
    assert [hit["source_path"] for hit in state["resolved_ranges"]] == [path]
    assert not reads


def test_ordinary_or_keeps_two_verified_chunks_from_same_source():
    """BM25 is chunk-ranked for explanations; diversity is navigation-only."""
    from merger.repoground.core.ask_context import _prefer_diverse_relaxed_sources

    paths = ["src/a.py", "src/a.py", "src/b.py"]
    rows = [
        {"chunk_id": f"chunk-{i}", "source_path": source}
        for i, source in enumerate(paths)
    ]
    indexed = {
        "query_result": {"results": rows},
        "resolved_evidence": {
            "hits": [
                {
                    "chunk_id": row["chunk_id"],
                    "source_path": row["source_path"],
                    "range_status": "resolved",
                    "range_ref": {"ref": row["chunk_id"]},
                    "range": {"text": "verified text"},
                    "citation_id": f"cit_{i}",
                }
                for i, row in enumerate(rows)
            ]
        },
        "source_citation_projection": {
            "items": [
                {"chunk_id": row["chunk_id"], "citation_id": f"cit_{i}"}
                for i, row in enumerate(rows)
            ]
        },
    }
    selected = _prefer_diverse_relaxed_sources(
        indexed, query="Why does retry backoff work?", k=2, path_results=[]
    )
    assert [row["chunk_id"] for row in selected["query_result"]["results"]] == [
        "chunk-0",
        "chunk-1",
    ]


def test_relaxed_or_keeps_index_metadata_and_reports_uncitable_candidates(monkeypatch):
    """Excluded stale evidence cannot be silently converted into a clean result."""
    from pathlib import Path
    from merger.repoground.core import ask_context as context

    rows = [
        {"chunk_id": "stale", "source_path": "src/stale.py"},
        {"chunk_id": "valid", "source_path": "src/valid.py"},
    ]
    indexed = {
        "status": "available",
        "index_identity": {"sha256": "a" * 64},
        "warnings": [{"kind": "stale_range"}],
        "query_result": {"results": rows, "fts_query": "generated", "index_total": 2},
        "resolved_evidence": {
            "hits": [
                {
                    "chunk_id": "stale",
                    "source_path": "src/stale.py",
                    "range_status": "stale",
                    "range": {"text": "untrusted stale range"},
                    "citation_id": "cit_stale",
                },
                {
                    "chunk_id": "valid",
                    "source_path": "src/valid.py",
                    "range_status": "resolved",
                    "range_ref": {"ref": "valid"},
                    "range": {"text": "verified source"},
                    "citation_id": "cit_valid",
                },
            ],
            "resolver_version": "index-only",
        },
        "source_citation_projection": {
            "items": [{"chunk_id": "valid", "citation_id": "cit_valid"}],
            "authority": "verified",
        },
    }
    monkeypatch.setattr(
        context,
        "_run_query",
        lambda _manifest, _query, _k, prepared_fts_query=None: (
            indexed
            if prepared_fts_query is not None
            else {
                "status": "available",
                "query_result": {"results": []},
                "resolved_evidence": {"hits": []},
            }
        ),
    )
    monkeypatch.setattr(context, "_relaxed_path_index_reads", lambda **_kw: [])
    state = context._query_context(
        Path("immutable"),
        query="Why does retry backoff fail?",
        k=2,
        max_context_tokens=100,
        max_context_bytes=400,
    )
    emitted = state["query_result"]
    assert emitted["index_identity"] == indexed["index_identity"]
    assert emitted["warnings"] == indexed["warnings"]
    assert emitted["query_result"]["index_total"] == 2
    assert emitted["resolved_evidence"]["resolver_version"] == "index-only"
    assert emitted["source_citation_projection"]["authority"] == "verified"
    assert [row["chunk_id"] for row in emitted["query_result"]["results"]] == ["valid"]
    assert [hit["citation_id"] for hit in state["retrieval_hits"]] == ["cit_valid"]
    assert any(
        omission["reason"] == "unverified_index_evidence" and omission["ref"] == "stale"
        for omission in state["omissions"]
    )


def test_explanatory_location_words_do_not_invoke_navigation_ranking():
    from merger.repoground.core.ask_context import _navigation_path_intent

    for query in (
        "Why can't the loader find the config file?",
        "Where does this test fail?",
        "Which handler swallows the error?",
        "Why does runtime implementation call find source?",
        "Warum findet das Programm die Datei nicht?",
    ):
        assert not _navigation_path_intent(query), query
    for query in (
        "Where is retry implemented?",
        "Find configured runtime entrypoint and operator implementation",
        "Which module defines job_finalizer?",
        "Wo wird job_finalizer implementiert?",
    ):
        assert _navigation_path_intent(query), query


def test_ordinary_k_one_or_does_not_overfetch_twenty_four_sources(monkeypatch):
    from pathlib import Path
    from merger.repoground.core import ask_context as context

    observed = []

    def fake_run(_manifest, _query, k, prepared_fts_query=None):
        if prepared_fts_query is None:
            return {
                "status": "available",
                "query_result": {"results": []},
                "resolved_evidence": {"hits": []},
            }
        observed.append(k)
        return {
            "status": "available",
            "query_result": {
                "results": [{"chunk_id": "only", "source_path": "src/only.py"}]
            },
            "resolved_evidence": {
                "hits": [
                    {
                        "chunk_id": "only",
                        "source_path": "src/only.py",
                        "range_status": "resolved",
                        "range_ref": {"ref": "only"},
                        "range": {"text": "verified"},
                        "citation_id": "cit_only",
                    }
                ]
            },
            "source_citation_projection": {
                "items": [{"chunk_id": "only", "citation_id": "cit_only"}]
            },
        }

    monkeypatch.setattr(context, "_run_query", fake_run)
    state = context._query_context(
        Path("immutable"),
        query="Why does the retry implementation fail?",
        k=1,
        max_context_tokens=100,
        max_context_bytes=100,
    )
    assert len(state["resolved_ranges"]) == 1
    assert observed and observed[0] <= 3


def test_navigation_interrogative_vs_locator_construction_20261021():
    """Location intent is grammatical; find/which tokens alone are not enough."""
    from merger.repoground.core.ask_context import _navigation_path_intent

    for query in (
        "Find out why this implementation is slow",
        "Find out how this context surface is generated",
        "Find out what the retry handler does",
        "Find out whether the implementation is thread-safe",
        "Find out when this test runs",
        "Find out which handler swallows the error",
        "Find why this implementation is slow",
        "Find what the retry handler does",
        "Find whether this implementation is thread-safe",
        "Find when this test runs",
        "Find how the retry handler works",
        "Find which handler swallows the error",
        "Please find what this test verifies",
        "Finde heraus warum diese Implementierung langsam ist",
        "Finde was dieser Test prüft",
        "Zeige mir wie die Implementierung funktioniert",
        "Suche warum die Datei nicht geladen wird",
        "Locate why this retry handler fails",
        "Finde bitte heraus warum die Implementierung langsam ist",
        "Finden Sie heraus warum die Implementierung langsam ist",
        "Wo schlägt dieser Test fehl?",
        "Wo scheitert dieser Test?",
        "Find out where does this test fail?",
        "Find the root cause why this implementation is slow",
        "Finde den Grund warum dieser Test fehlschlägt",
        "Where exactly does this test fail?",
        "Wo genau schlägt dieser Test fehl?",
        "Why can't the loader find the config file?",
        "Where does this test fail?",
        "Which handler swallows the error?",
        "How is the cache path computed?",
        "Why does the runtime implementation have a corresponding test?",
    ):
        assert not _navigation_path_intent(query), query
    for query in (
        "Please find the retry implementation",
        "Find generated operator context surface and associated consumer-surface benchmark evidence",
        "Find out where the retry implementation lives",
        "Find out which file implements retry",
        "Find which file implements retry",
        "Find where the retry implementation lives",
        "Find out what file implements retry",
        "Finde heraus wo die Implementierung liegt",
        "Finde welche Datei retry implementiert",
        "Zeige mir die Implementierung",
        "Suche die Datei mit dem Entrypoint",
        "Finde bitte heraus wo die Implementierung liegt",
        "Finden Sie heraus wo die Implementierung liegt",
        "Wo liegt die Implementierung?",
        "Wo ist der Test definiert?",
        "Where exactly is the retry implementation?",
        "Wo genau liegt die Implementierung?",
        "Find the root module implementing retry",
        "In which file is retry implemented?",
        "Find job finalizer implementation and real test",
        "Job finalizer implementation and corresponding real test",
        "Wo wird retry implementiert?",
    ):
        assert _navigation_path_intent(query), query


def test_path_hint_missing_citation_survives_as_degraded_diagnostic(monkeypatch):
    """Filtered index candidates rejected as uncitable must not disappear silently."""
    from pathlib import Path
    from merger.repoground.core import ask_context as context

    def response(chunk, source, cited=True):
        row = {"chunk_id": chunk, "source_path": source}
        hit = {
            "chunk_id": chunk,
            "source_path": source,
            "range_status": "resolved",
            "range_ref": {"ref": chunk},
            "range": {"text": "Verified source" if cited else "Unverified hint"},
        }
        if cited:
            hit["citation_id"] = "cit_" + chunk
        return {
            "status": "available",
            "bundle_manifest": "immutable",
            "index_artifact": {
                "sha256": "a" * 64,
                "path": "index.sqlite",
                "bytes": 4096,
            },
            "query_result": {"results": [row]},
            "resolved_evidence": {"hits": [hit]},
            "source_citation_projection": {
                "items": [{"chunk_id": chunk, "citation_id": "cit_" + chunk}]
                if cited
                else []
            },
        }

    def fake_run(_manifest, _query, _k, prepared_fts_query=None):
        if prepared_fts_query is None:
            return {
                "status": "available",
                "query_result": {"results": []},
                "resolved_evidence": {"hits": []},
            }
        return response("baseline", "tests/test_retry.py")

    monkeypatch.setattr(context, "_run_query", fake_run)
    monkeypatch.setattr(
        context,
        "_relaxed_path_index_reads",
        lambda *_args, **_kw: [
            response("uncitable-hint", "src/retry.py", False),
            response("uncitable-hint", "src/retry.py", False),
        ],
    )
    state = context._query_context(
        Path("immutable"),
        query="Find retry implementation",
        k=2,
        max_context_tokens=100,
        max_context_bytes=500,
    )
    assert [row["source_path"] for row in state["resolved_ranges"]] == [
        "tests/test_retry.py"
    ]
    assert any(
        omission.get("reason") == "unverified_index_evidence"
        and omission.get("ref") == "uncitable-hint"
        for omission in state["omissions"]
    )
    assert (
        sum(
            row.get("reason") == "unverified_index_evidence"
            and row.get("ref") == "uncitable-hint"
            for row in state["omissions"]
        )
        == 1
    )


def test_path_hints_reject_other_index_snapshot_and_forward_warnings(monkeypatch):
    """OR and filtered citations must have the same verified index artifact."""
    from pathlib import Path

    from merger.repoground.core import ask_context as context

    def indexed(ref, source, sha, warnings=None):
        citation = "cit_" + ref
        return {
            "status": "available",
            "bundle_manifest": "immutable",
            "index_artifact": {
                "sha256": sha,
                "path": "index.sqlite",
                "bytes": 4096,
            },
            "warnings": warnings or [],
            "query_result": {"results": [{"chunk_id": ref, "source_path": source}]},
            "resolved_evidence": {
                "hits": [
                    {
                        "chunk_id": ref,
                        "source_path": source,
                        "range_status": "resolved",
                        "range_ref": {"ref": ref},
                        "range": {"text": "Verified " + source},
                        "citation_id": citation,
                    }
                ]
            },
            "source_citation_projection": {
                "items": [{"chunk_id": ref, "citation_id": citation}]
            },
        }

    primary = indexed("baseline", "tests/test_retry.py", "a" * 64)
    safe = indexed(
        "safe",
        "src/retry.py",
        "a" * 64,
        warnings=[{"kind": "stale_source", "detail": "filtered read caveat"}],
    )
    stale = indexed("alien", "src/alien.py", "b" * 64)

    def run(_manifest, _query, _k, prepared_fts_query=None):
        if prepared_fts_query is None:
            return {
                "status": "available",
                "query_result": {"results": []},
                "resolved_evidence": {"hits": []},
            }
        return primary

    monkeypatch.setattr(context, "_run_query", run)
    monkeypatch.setattr(
        context,
        "_relaxed_path_index_reads",
        lambda *_args, **_kw: [safe, stale],
    )
    state = context._query_context(
        Path("immutable"),
        query="Find retry implementation",
        k=3,
        max_context_tokens=200,
        max_context_bytes=800,
    )
    assert [row["source_path"] for row in state["resolved_ranges"]] == [
        "tests/test_retry.py",
        "src/retry.py",
    ]
    assert {"kind": "stale_source", "detail": "filtered read caveat"} in (
        state["query_result"].get("warnings") or []
    )
    assert any(
        row.get("reason") == "index_artifact_mismatch" for row in state["omissions"]
    )


def test_find_out_in_which_file_preserves_source_location_intent():
    """Explicit file/module complements after find out remain navigation."""
    from merger.repoground.core.ask_context import _navigation_path_intent

    for query in (
        "Find out in which file retry is implemented",
        "Find out in which module retry is implemented",
        "Finde heraus in welcher Datei retry implementiert ist",
        "Finden Sie heraus in welcher Datei retry implementiert ist",
    ):
        assert _navigation_path_intent(query), query

    for query in (
        "Find out what caused the error",
        "Find which handler swallows the error",
        "Where exactly does this test fail?",
        "Find out in which way retry is implemented",
    ):
        assert not _navigation_path_intent(query), query
