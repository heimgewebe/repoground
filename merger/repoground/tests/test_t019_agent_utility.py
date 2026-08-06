from __future__ import annotations

import json
from pathlib import Path

import pytest

from merger.repoground.core.context_budgeting import select_relevance_budgeted_context
from merger.repoground.core.response_projection import project_read_result
from merger.repoground.retrieval.hybrid_activation import (
    build_hybrid_route_binding,
    execute_profile_gated_query,
    file_sha256,
    resolve_profile_activation,
)
from merger.repoground.retrieval.natural_language_eval import (
    evaluate_paired_routes,
    load_goldset,
    validate_goldset,
)

ROOT = Path(__file__).resolve().parents[3]
ROUTING_EVIDENCE = ROOT / "docs/retrieval/task-profile-routing-evidence.v1.json"
GOLDSET = ROOT / "docs/retrieval/t019-natural-language-goldset.v1.json"
COMMIT = "cfd341b00c6a36125a014dbfa54cf78c8215da75"
SHA = "a" * 64


def test_multilingual_goldset_is_complete_and_targets_real_paths() -> None:
    goldset = load_goldset(GOLDSET)
    assert validate_goldset(goldset) == []
    assert {case["language"] for case in goldset["cases"]} >= {"de", "en"}
    assert {case["category"] for case in goldset["cases"]} == {
        "exact_identifier",
        "paraphrase",
        "synonym",
        "compound",
        "true_miss",
    }
    for case in goldset["cases"]:
        for target in case["expected_paths"]:
            assert (ROOT / target).is_file(), target


def test_profile_gate_keeps_default_lexical_and_allows_explicit_review_opt_in() -> None:
    default = resolve_profile_activation(
        ROUTING_EVIDENCE,
        task_profile="review",
        explicit_opt_in=False,
    )
    opted_in = resolve_profile_activation(
        ROUTING_EVIDENCE,
        task_profile="review",
        explicit_opt_in=True,
    )
    blocked = resolve_profile_activation(
        ROUTING_EVIDENCE,
        task_profile="basic_repo_question",
        explicit_opt_in=True,
    )
    assert default["activated"] is False
    assert default["activation_mode"] == "opt_in_required"
    assert opted_in["activated"] is True
    assert opted_in["activation_mode"] == "explicit_profile_opt_in"
    assert blocked["activated"] is False
    assert blocked["activation_mode"] == "profile_gate_blocked"
    assert all(
        item["global_default_promoted"] is False
        for item in (default, opted_in, blocked)
    )


def test_hybrid_binding_requires_exact_model_index_manifest_and_commit(
    tmp_path: Path,
) -> None:
    index = tmp_path / "index.sqlite"
    manifest = tmp_path / "bundle.manifest.json"
    index.write_bytes(b"index")
    manifest.write_text("{}", encoding="utf-8")
    policy = {
        "model_name": "local-fixture-model",
        "dimensions": 8,
        "provider": "local",
        "similarity_metric": "cosine",
        "fallback_behavior": "ignore",
    }
    model = {
        "model_name": "local-fixture-model",
        "model_revision": "fixture-v1",
        "model_artifact_sha256": SHA,
        "tokenizer_sha256": "b" * 64,
    }
    activation = resolve_profile_activation(
        ROUTING_EVIDENCE,
        task_profile="review",
        explicit_opt_in=True,
    )
    binding = build_hybrid_route_binding(
        activation=activation,
        embedding_policy=policy,
        model_binding=model,
        index_path=index,
        index_sha256=file_sha256(index),
        bundle_manifest_path=manifest,
        bundle_manifest_sha256=file_sha256(manifest),
        repository_commit=COMMIT,
        routing_evidence_path=ROUTING_EVIDENCE,
    )
    assert binding["status"] == "bound"
    assert binding["embedding_policy"]["sha256"]
    assert binding["routing_evidence"]["sha256"] == file_sha256(ROUTING_EVIDENCE)
    broken = build_hybrid_route_binding(
        activation=activation,
        embedding_policy=policy,
        model_binding={**model, "model_artifact_sha256": "missing"},
        index_path=index,
        index_sha256=file_sha256(index),
        bundle_manifest_path=manifest,
        bundle_manifest_sha256=file_sha256(manifest),
        repository_commit=COMMIT,
        routing_evidence_path=ROUTING_EVIDENCE,
    )
    assert broken["status"] == "invalid"


def test_runtime_activation_passes_policy_only_after_gate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from merger.repoground.retrieval import query_core

    seen = []

    def fake_execute_query(index_path, query_text, **kwargs):
        seen.append(kwargs.get("embedding_policy"))
        return {"query": query_text, "results": [], "count": 0}

    monkeypatch.setattr(query_core, "execute_query", fake_execute_query)
    index = tmp_path / "index.sqlite"
    manifest = tmp_path / "bundle.manifest.json"
    index.write_bytes(b"index")
    manifest.write_text("{}", encoding="utf-8")
    policy = {
        "model_name": "local-fixture-model",
        "dimensions": 8,
        "provider": "local",
        "similarity_metric": "cosine",
        "fallback_behavior": "ignore",
    }
    model = {
        "model_name": "local-fixture-model",
        "model_revision": "fixture-v1",
        "model_artifact_sha256": SHA,
        "tokenizer_sha256": "b" * 64,
    }
    common = dict(
        index_path=index,
        query_text="natural repository question",
        k=5,
        routing_evidence=ROUTING_EVIDENCE,
        task_profile="review",
        embedding_policy=policy,
        model_binding=model,
        index_sha256=file_sha256(index),
        bundle_manifest_path=manifest,
        bundle_manifest_sha256=file_sha256(manifest),
        repository_commit=COMMIT,
    )
    fallback = execute_profile_gated_query(**common, explicit_opt_in=False)
    activated = execute_profile_gated_query(**common, explicit_opt_in=True)
    assert seen == [None, policy]
    assert (
        fallback["hybrid_retrieval"]["executed_route"]
        == "deterministic_lexical_fallback"
    )
    assert (
        activated["hybrid_retrieval"]["executed_route"]
        == "profile_gated_hybrid_semantic"
    )


def test_relevance_budgeting_prefers_changed_authoritative_path_and_records_bytes() -> (
    None
):
    candidates = [
        {
            "id": "lane-first",
            "source": "resolved_evidence",
            "priority": 10,
            "estimated_tokens": 10,
            "path": "docs/background.md",
            "trust": {"canonicality": "navigation_index"},
        },
        {
            "id": "changed",
            "source": "changed_path",
            "priority": 5,
            "estimated_tokens": 10,
            "path": "merger/repoground/core/context_compiler.py",
            "trust": {"canonicality": "content_source"},
        },
        {
            "id": "diverse",
            "source": "python_symbol_index_json",
            "priority": 20,
            "estimated_tokens": 10,
            "path": "merger/repoground/retrieval/query_core.py",
            "trust": {"canonicality": "navigation_index"},
        },
    ]
    selected, omitted, trace = select_relevance_budgeted_context(
        candidates,
        token_budget=20,
        byte_budget=80,
        bytes_per_token=4.0,
        changed_paths=["merger/repoground/core/context_compiler.py"],
    )
    assert selected[0]["id"] == "changed"
    assert trace["per_lane_selection_caps"] is False
    assert trace["hard_budgets"]["used_bytes"] == 80
    assert len(selected) == 2 and len(omitted) == 1
    assert omitted[0]["required_bytes"] == 40
    assert omitted[0]["budget_remaining_bytes"] == 0


def test_paired_evaluator_reports_all_required_metrics_and_blocks_default_promotion() -> (
    None
):
    goldset = load_goldset(GOLDSET)
    targets = {case["query"]: case["expected_paths"] for case in goldset["cases"]}

    def baseline(query: str, _k: int):
        paths = targets[query]
        return {
            "paths": paths[:1],
            "latency_ms": 10,
            "context_bytes": 100,
            "tool_calls": 2,
        }

    def candidate(query: str, _k: int):
        paths = targets[query]
        return {
            "paths": paths,
            "latency_ms": 11,
            "context_bytes": 90,
            "tool_calls": 2,
        }

    report = evaluate_paired_routes(
        goldset,
        baseline_runner=baseline,
        candidate_runner=candidate,
        k=10,
        bindings={"repository_commit": COMMIT, "bundle_manifest_sha256": SHA},
    )
    assert report["status"] == "passed"
    assert report["default_promotion_allowed"] is False
    for route in (report["baseline"], report["candidate"]):
        assert {
            "recall_at_k",
            "mrr",
            "miss_taxonomy",
            "latency_ms",
            "context_bytes",
            "tool_calls",
        } <= set(route)


def test_compact_projection_is_smaller_without_losing_mutable_status_or_boundaries(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "bundle.manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    verbose = {
        "status": "warn",
        "error": "truncated",
        "truncated": True,
        "hits": [{"path": "a.py", "range": {"start_line": 1, "end_line": 2}}],
        "availability": {
            "status": "warn",
            "profile": "agent",
            "freshness": {"status": "fresh", "commit": COMMIT},
            "graph_availability": {"status": "available", "detail": "x" * 1000},
            "artifacts": [
                {
                    "role": f"role-{index}",
                    "availability": "available",
                    "requirement": "optional",
                    "detail": "y" * 200,
                }
                for index in range(8)
            ],
        },
        "freshness": {"status": "fresh", "commit": COMMIT},
        "mutation_boundary": {
            "writes": [],
            "read_paths_do_not_refresh": True,
            "not_reachable_from_snapshot_create": True,
            "forbidden_operations": [
                "secret_read",
                "snapshot_create_side_effect",
                "other",
            ],
        },
        "does_not_establish": ["truth", "completeness", "merge_readiness"],
    }
    compact = project_read_result(verbose, manifest, verbose=False)
    verbose_bytes = len(json.dumps(verbose, sort_keys=True).encode())
    compact_bytes = len(json.dumps(compact, sort_keys=True).encode())
    assert compact_bytes <= verbose_bytes * 0.5
    assert compact["status"] == "warn"
    assert compact["error"] == "truncated"
    assert compact["truncated"] is True
    assert compact["hits"] == verbose["hits"]
    assert (
        compact["freshness"]["commit_identity"]["repositories"][0]["git_commit"]
        == COMMIT
    )
    assert compact["mutation_boundary"]["read_only"] is True
    assert compact["does_not_establish"]["items"] == verbose["does_not_establish"]
