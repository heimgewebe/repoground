import json
from pathlib import Path

import jsonschema
import pytest

from merger.repoground.retrieval import index_db
from merger.repoground.retrieval.eval_core import do_eval
from merger.repoground.retrieval.query_core import execute_query
from merger.repoground.retrieval.review_eval import run_review_retrieval_baseline
from merger.repoground.retrieval.review_query import execute_review_query


@pytest.fixture
def review_fixture(tmp_path):
    repo_root = tmp_path / "repo"
    goldset = repo_root / "docs/retrieval/review_queries.v1.json"
    goldset.parent.mkdir(parents=True)
    query = "Find widget implementation, tests, contract, and documentation"
    goldset.write_text(
        json.dumps(
            [
                {
                    "query": query,
                    "category": "widget",
                    "expected_patterns": [
                        "src/widget.py",
                        "tests/test_widget.py",
                        "contracts/widget.schema.json",
                        "docs/widget.md",
                    ],
                    "filters": {},
                }
            ]
        ),
        encoding="utf-8",
    )

    dump_path = tmp_path / "dump.json"
    chunks_path = tmp_path / "chunks.jsonl"
    index_path = tmp_path / "index.sqlite"
    chunks = [
        {
            "chunk_id": "source-1",
            "repo_id": "fixture",
            "path": "src/widget.py",
            "content": "widget implementation",
            "start_line": 1,
            "end_line": 1,
            "layer": "core",
            "artifact_type": "code",
            "content_sha256": "1" * 64,
        },
        {
            "chunk_id": "source-2",
            "repo_id": "fixture",
            "path": "src/widget.py",
            "content": "widget helper implementation",
            "start_line": 2,
            "end_line": 2,
            "layer": "core",
            "artifact_type": "code",
            "content_sha256": "2" * 64,
        },
        {
            "chunk_id": "test-1",
            "repo_id": "fixture",
            "path": "tests/test_widget.py",
            "content": "widget tests",
            "start_line": 1,
            "end_line": 1,
            "layer": "test",
            "artifact_type": "code",
            "content_sha256": "3" * 64,
        },
        {
            "chunk_id": "contract-1",
            "repo_id": "fixture",
            "path": "contracts/widget.schema.json",
            "content": "widget contract schema",
            "start_line": 1,
            "end_line": 1,
            "layer": "contract",
            "artifact_type": "schema",
            "content_sha256": "4" * 64,
        },
        {
            "chunk_id": "docs-1",
            "repo_id": "fixture",
            "path": "docs/widget.md",
            "content": "widget documentation",
            "start_line": 1,
            "end_line": 1,
            "layer": "docs",
            "artifact_type": "doc",
            "content_sha256": "5" * 64,
        },
        {
            "chunk_id": "goldset-1",
            "repo_id": "fixture",
            "path": "docs/retrieval/review_queries.v1.json",
            "content": query,
            "start_line": 1,
            "end_line": 1,
            "layer": "docs",
            "artifact_type": "eval",
            "content_sha256": "6" * 64,
        },
    ]
    chunks_path.write_text(
        "".join(json.dumps(chunk) + "\n" for chunk in chunks),
        encoding="utf-8",
    )
    dump_path.write_text(json.dumps({"fixture": True}), encoding="utf-8")
    index_db.build_index(dump_path, chunks_path, index_path)
    return repo_root, goldset, index_path, query


def test_review_query_fuses_unique_role_paths_deterministically(review_fixture):
    _, _, index_path, query = review_fixture
    exclusions = ["docs/retrieval/review_queries.v1.json"]

    first = execute_review_query(
        index_path,
        query,
        k=10,
        explain=True,
        excluded_paths=exclusions,
    )
    second = execute_review_query(
        index_path,
        query,
        k=10,
        explain=True,
        excluded_paths=exclusions,
    )

    first_paths = [hit["path"] for hit in first["results"]]
    second_paths = [hit["path"] for hit in second["results"]]
    assert first_paths == second_paths
    assert len(first_paths) == len(set(first_paths)) == 4
    assert set(first_paths) == {
        "src/widget.py",
        "tests/test_widget.py",
        "contracts/widget.schema.json",
        "docs/widget.md",
    }
    assert first["engine"] == "fts5+review_intent_v1"
    assert first["query_mode"] == "review_intent"
    assert first["applied_exclusions"]["application"] == (
        "before_order_by_and_limit_per_lane"
    )
    assert first["explain"]["fusion"]["method"] == "round_robin_unique_path"
    for hit in first["results"]:
        diagnostics = hit["why"]["diagnostics"]["review_intent"]
        assert diagnostics["plan_version"] == "review_intent.v1"
        assert diagnostics["fusion_method"] == "round_robin_unique_path"


def test_review_query_preserves_legacy_top_hit(review_fixture):
    _, _, index_path, _ = review_fixture
    query = "widget tests"

    legacy = execute_query(index_path, query, k=10)
    review = execute_review_query(index_path, query, k=10, explain=True)

    assert legacy["results"][0]["path"] == "tests/test_widget.py"
    assert review["results"][0]["path"] == legacy["results"][0]["path"]
    assert review["explain"]["fusion"]["lane_order"][0] == "legacy"
    diagnostics = review["results"][0]["why"]["diagnostics"]["review_intent"]
    assert diagnostics["selected_from_lane"] == "legacy"
    assert diagnostics["variant"] == "legacy_router"


def test_review_query_validates_against_query_result_contract(review_fixture):
    _, _, index_path, query = review_fixture
    result = execute_review_query(
        index_path,
        query,
        k=10,
        excluded_paths=["docs/retrieval/review_queries.v1.json"],
    )
    schema_path = (
        Path(__file__).parent.parent / "contracts/query-result.v1.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    jsonschema.validate(instance=result, schema=schema)


def test_legacy_query_path_remains_legacy(review_fixture):
    _, _, index_path, _ = review_fixture
    result = execute_query(index_path, "widget", k=10, explain=True)

    assert result["engine"] == "fts5"
    assert result["query_mode"] == "fts"
    assert "review_intent_router" not in result["explain"]
    assert all(
        "review_intent" not in hit["why"].get("diagnostics", {})
        for hit in result["results"]
    )


def test_review_intent_improves_fixture_without_default_promotion(review_fixture):
    repo_root, goldset, index_path, _ = review_fixture
    legacy = run_review_retrieval_baseline(
        index_path,
        goldset,
        k=10,
        repo_root=repo_root,
    )
    review = run_review_retrieval_baseline(
        index_path,
        goldset,
        k=10,
        repo_root=repo_root,
        review_intent=True,
    )

    assert legacy is not None
    assert review is not None
    assert legacy["metrics"]["expected_target_hits"] == 0
    assert review["metrics"]["expected_target_hits"] == 4
    assert legacy["metrics"]["recall@10"] == 0.0
    assert review["metrics"]["recall@10"] == 100.0
    condition = review["measurement_conditions"]["review_intent"]
    assert condition["ranking_algorithm_changed"] is True
    assert condition["default_promoted"] is False


def test_review_eval_validates_against_retrieval_eval_contract(review_fixture):
    repo_root, goldset, index_path, _ = review_fixture
    result = do_eval(
        index_path,
        goldset,
        10,
        is_json_mode=True,
        excluded_paths=["docs/retrieval/review_queries.v1.json"],
        review_intent=True,
    )
    assert result is not None
    schema_path = (
        Path(__file__).parent.parent / "contracts/retrieval-eval.v1.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    jsonschema.validate(instance=result, schema=schema)


def test_review_query_rejects_invalid_k(review_fixture):
    _, _, index_path, query = review_fixture

    with pytest.raises(ValueError, match="k must be at least 1"):
        execute_review_query(index_path, query, k=0)


def test_cli_query_review_intent_opt_in_uses_review_router(review_fixture, capsys):
    from argparse import Namespace
    from merger.repoground.cli import cmd_query

    _, _, index_path, query = review_fixture
    args = Namespace(
        index=str(index_path),
        q=query,
        k=4,
        repo=None,
        path=None,
        ext=None,
        layer=None,
        artifact_type=None,
        emit="json",
        stale_policy="ignore",
        embedding_policy=None,
        explain=True,
        graph_index=None,
        graph_weights=None,
        test_penalty=0.75,
        output_profile=None,
        context_window_lines=0,
        context_mode="exact",
        build_context_bundle=False,
        overmatch_guard=False,
        review_intent=True,
        trace=False,
        range_coverage_report=False,
        citation_map=None,
    )

    rc = cmd_query.run_query(args)
    assert rc == 0
    data = json.loads(capsys.readouterr().out)

    assert data["query_mode"] == "review_intent"
    assert data["engine"] == "fts5+review_intent_v1"
    assert data["count"] == 4
    assert "review_intent_router" in data["explain"]
    assert data["explain"]["fusion"]["method"] == "round_robin_unique_path"
    assert "This opt-in result does not establish readiness for default promotion." in data["claim_boundaries"]["does_not_prove"]


def test_cli_query_review_intent_rejects_context_options(review_fixture, capsys):
    from argparse import Namespace
    from merger.repoground.cli import cmd_query

    _, _, index_path, query = review_fixture
    args = Namespace(
        index=str(index_path),
        q=query,
        k=4,
        repo=None,
        path=None,
        ext=None,
        layer=None,
        artifact_type=None,
        emit="json",
        stale_policy="ignore",
        embedding_policy=None,
        explain=True,
        graph_index=None,
        graph_weights=None,
        test_penalty=0.75,
        output_profile="review_context",
        context_window_lines=0,
        context_mode="exact",
        build_context_bundle=False,
        overmatch_guard=False,
        review_intent=True,
        trace=False,
        range_coverage_report=False,
        citation_map=None,
    )

    rc = cmd_query.run_query(args)
    assert rc == 1
    assert "--review-intent does not combine" in capsys.readouterr().err
