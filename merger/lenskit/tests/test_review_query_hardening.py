import json

from merger.lenskit.retrieval import index_db
from merger.lenskit.retrieval.eval_core import do_eval
from merger.lenskit.retrieval.review_query import execute_review_query


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
