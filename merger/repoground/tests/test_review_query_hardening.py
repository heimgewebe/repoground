import json

from merger.repoground.retrieval import index_db
from merger.repoground.retrieval.eval_core import do_eval
from merger.repoground.retrieval.review_query import (
    _rerank_source_lane,
    execute_review_query,
)


def _build_review_index(tmp_path, chunks):
    dump_path = tmp_path / "adaptive-dump.json"
    chunks_path = tmp_path / "adaptive-chunks.jsonl"
    index_path = tmp_path / "adaptive-index.sqlite"
    dump_path.write_text(json.dumps({"fixture": True}), encoding="utf-8")
    chunks_path.write_text(
        "".join(json.dumps(chunk) + "\n" for chunk in chunks),
        encoding="utf-8",
    )
    index_db.build_index(dump_path, chunks_path, index_path)
    return index_path


def _review_chunk(chunk_id, path, *, start_line=1):
    return {
        "chunk_id": chunk_id,
        "repo_id": "fixture",
        "path": path,
        "content": "widget implementation",
        "start_line": start_line,
        "end_line": start_line,
        "layer": "core",
        "artifact_type": "code",
        "content_sha256": "1" * 64,
    }


def test_review_query_fetches_past_duplicate_chunk_window(tmp_path):
    chunks = [
        _review_chunk(
            f"dominant-{index:03d}",
            "src/aaa_widget.py",
            start_line=index + 1,
        )
        for index in range(60)
    ]
    chunks.extend(
        _review_chunk(f"other-{index:03d}", f"src/widget_{index:03d}.py")
        for index in range(12)
    )
    index_path = _build_review_index(tmp_path, chunks)

    result = execute_review_query(index_path, "widget", k=10, explain=True)
    paths = [hit["path"] for hit in result["results"]]

    assert result["count"] == 10
    assert len(paths) == len(set(paths)) == 10
    assert any(path != "src/aaa_widget.py" for path in paths)
    collection = result["explain"]["lanes"][0]["variant_collection"][
        "legacy_router"
    ]
    assert collection["attempts"] > 1
    assert collection["fetch_k"] > 50


def test_review_query_honors_k_above_former_candidate_cap(tmp_path):
    chunks = [
        _review_chunk(f"unique-{index:03d}", f"src/widget_{index:03d}.py")
        for index in range(300)
    ]
    index_path = _build_review_index(tmp_path, chunks)

    result = execute_review_query(index_path, "widget", k=250, explain=True)

    assert result["count"] == 250
    assert len({hit["path"] for hit in result["results"]}) == 250
    assert (
        result["explain"]["fusion"]["candidate_unique_paths_per_lane"]
        >= 250
    )


def test_review_query_marks_non_executable_plan_as_legacy_fallback(tmp_path):
    chunks = [_review_chunk("source", "src/widget.py")]
    index_path = _build_review_index(tmp_path, chunks)
    query = "Find the"

    direct = execute_review_query(index_path, query, k=5, explain=True)

    assert direct["query_mode"] == "review_intent_fallback"
    assert direct["explain"]["review_intent_fallback"] == {
        "reason": "no_executable_review_lanes",
        "executed_query_mode": "fts",
        "fallback": "legacy",
    }

    goldset = tmp_path / "fallback-goldset.json"
    goldset.write_text(
        json.dumps(
            [
                {
                    "query": query,
                    "category": "fallback",
                    "expected_patterns": ["src/widget.py"],
                    "filters": {},
                }
            ]
        ),
        encoding="utf-8",
    )
    report = do_eval(
        index_path,
        goldset,
        5,
        is_json_mode=True,
        review_intent=True,
    )

    assert report is not None
    condition = report["measurement_conditions"]["review_intent"]
    assert condition["requested"] is True
    assert condition["executed_queries"] == 0
    assert condition["fallback_queries"] == 1
    assert condition["error_queries"] == 0
    assert condition["fallback_mode"] == "legacy"
    assert condition["ranking_algorithm_changed"] is False
    assert report["details"][0]["query_mode"] == "review_intent_fallback"


def test_source_lane_rerank_prefers_source_layer_and_subject_path():
    def hit(path, layer, lane_rank):
        return {
            "path": path,
            "layer": layer,
            "why": {
                "diagnostics": {
                    "review_intent": {
                        "lane": "source",
                        "variant": "strict",
                        "lane_rank": lane_rank,
                    }
                }
            },
        }

    hits = [
        hit("merger/repoground/tests/test_output_health.py", "test", 1),
        hit("docs/proofs/agent-reading-pack-proof.md", "docs", 2),
        hit("merger/repoground/contracts/agent-reading-pack.json", "unknown", 3),
        hit("merger/repoground/cli/cmd_agent_pack.py", "cli", 4),
        hit("merger/repoground/core/agent_reading_pack.py", "core", 5),
        hit("merger/repoground/core/bundle_surface_validate.py", "core", 6),
    ]

    reranked = _rerank_source_lane(hits, anchor_terms=["agent", "reading", "pack"])

    assert [item["path"] for item in reranked[:3]] == [
        "merger/repoground/core/agent_reading_pack.py",
        "merger/repoground/cli/cmd_agent_pack.py",
        "merger/repoground/core/bundle_surface_validate.py",
    ]
    diagnostic = reranked[0]["why"]["diagnostics"]["review_intent"][
        "source_role_rerank"
    ]
    assert diagnostic["original_lane_rank"] == 5
    assert diagnostic["reranked_lane_rank"] == 1
    assert diagnostic["path_anchor_matches"] == 3
    assert diagnostic["non_source_layer_penalty"] == 0
    contract_hit = next(
        item for item in reranked if "/contracts/" in item["path"]
    )
    contract_diag = contract_hit["why"]["diagnostics"]["review_intent"][
        "source_role_rerank"
    ]
    assert contract_diag["layer"] == "unknown"
    assert contract_diag["non_source_path_penalty"] == 1
    assert contract_diag["non_source_penalty"] == 1


def test_source_lane_rerank_preserves_strict_before_relaxed():
    def hit(path, variant, lane_rank):
        return {
            "path": path,
            "layer": "core",
            "why": {
                "diagnostics": {
                    "review_intent": {
                        "lane": "source",
                        "variant": variant,
                        "lane_rank": lane_rank,
                    }
                }
            },
        }

    hits = [
        hit("src/implementation.py", "strict", 1),
        hit("src/alpha_beta.py", "relaxed", 2),
    ]

    reranked = _rerank_source_lane(hits, anchor_terms=["alpha", "beta"])

    assert [item["path"] for item in reranked] == [
        "src/implementation.py",
        "src/alpha_beta.py",
    ]
    assert reranked[0]["why"]["diagnostics"]["review_intent"][
        "source_role_rerank"
    ]["variant_rank"] == 0
    assert reranked[1]["why"]["diagnostics"]["review_intent"][
        "source_role_rerank"
    ]["variant_rank"] == 1


def test_review_query_source_lane_does_not_let_test_prose_occupy_source_slot(tmp_path):
    chunks = [
        {
            **_review_chunk("noise-test", "tests/test_output_health.py"),
            "layer": "test",
            "content": "agent reading pack " * 8,
        },
        {
            **_review_chunk("noise-doc", "docs/proofs/agent-reading-pack-proof.md"),
            "layer": "docs",
            "content": "agent reading pack " * 8,
        },
        {
            **_review_chunk("source", "src/core/agent_reading_pack.py"),
            "layer": "core",
            "content": "def produce_agent_reading_pack(): pass",
        },
        {
            **_review_chunk("target-test", "tests/test_agent_reading_pack.py"),
            "layer": "test",
            "content": "agent reading pack producer",
        },
    ]
    index_path = _build_review_index(tmp_path, chunks)

    result = execute_review_query(
        index_path,
        "Find the Agent Reading Pack producer and its primary tests",
        k=3,
        explain=True,
    )
    paths = [item["path"] for item in result["results"]]

    assert "src/core/agent_reading_pack.py" in paths
    source_hit = next(
        item
        for item in result["results"]
        if item["path"] == "src/core/agent_reading_pack.py"
    )
    review_diag = source_hit["why"]["diagnostics"]["review_intent"]
    assert review_diag["selected_from_lane"] == "source"
    assert review_diag["source_role_rerank"]["path_anchor_matches"] == 3
