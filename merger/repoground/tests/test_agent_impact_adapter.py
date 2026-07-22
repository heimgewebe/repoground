from __future__ import annotations

import hashlib
import json
from pathlib import Path

from merger.repoground.cli.agent_impact import main as impact_cli_main
from merger.repoground.core.agent_impact_adapter import (
    RepoGroundAgentImpactAdapter,
)
from merger.repoground.tests.test_readonly_adapter import (
    _adapter,
    _add_artifact,
    _seal_existing_artifact,
)

DIGEST = "b" * 64
def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _impact_adapter(
    tmp_path: Path,
) -> tuple[RepoGroundAgentImpactAdapter, dict, Path]:
    _base_adapter, bundle, config = _adapter(tmp_path)
    manifest = bundle["manifest"]
    symbol_path = manifest.parent / "demo.python_symbol_index.json"
    symbol_path.write_text(
        json.dumps(
            {
                "kind": "lenskit.python_symbol_index",
                "version": "1.0",
                "run_id": "run-1",
                "canonical_dump_index_sha256": DIGEST,
                "language": "python",
                "symbol_kinds": ["function"],
                "symbols": [
                    {
                        "id": "sym-demo",
                        "kind": "function",
                        "name": "hello_adapter",
                        "qualified_name": "demo.hello_adapter",
                        "module": "demo",
                        "path": "src/demo.py",
                        "start_line": 3,
                        "end_line": 5,
                        "range_ref": "file:src/demo.py#L3-L5",
                        "decorators": [],
                    },
                    {
                        "id": "sym-test",
                        "kind": "function",
                        "name": "test_hello_adapter",
                        "qualified_name": (
                            "tests.test_demo.test_hello_adapter"
                        ),
                        "module": "tests.test_demo",
                        "path": "tests/test_demo.py",
                        "start_line": 1,
                        "end_line": 5,
                        "range_ref": "file:tests/test_demo.py#L1-L5",
                        "decorators": [],
                    },
                ],
                "skipped_files_count": 0,
                "skipped_errors": [],
                "does_not_establish": [
                    "call_graph_completeness",
                    "dependency_completeness",
                    "runtime_behavior",
                    "import_success",
                    "test_sufficiency",
                    "review_impact",
                    "merge_readiness",
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    _seal_existing_artifact(bundle, "python_symbol_index_json")

    _add_artifact(
        bundle,
        "python_call_graph_json",
        "demo.python_call_graph.json",
        json.dumps(
            {
                "kind": "lenskit.python_call_graph",
                "version": "1.0",
                "run_id": "run-1",
                "canonical_dump_index_sha256": DIGEST,
                "language": "python",
                "evidence_model": {
                    "S0": "unresolved or ambiguous static candidate",
                    "S1": "one uniquely resolved local target",
                },
                "resolution_statuses": [
                    "resolved",
                    "candidate",
                    "ambiguous",
                    "unresolved",
                ],
                "relation_types": ["calls", "constructs"],
                "call_count": 2,
                "resolution_counts": {
                    "resolved": 2,
                    "candidate": 0,
                    "ambiguous": 0,
                    "unresolved": 0,
                },
                "evidence_counts": {"S0": 0, "S1": 2},
                "relation_counts": {"calls": 2, "constructs": 0},
                "calls": [
                    {
                        "path": "tests/test_demo.py",
                        "start_line": 3,
                        "start_col": 4,
                        "end_line": 3,
                        "end_col": 20,
                        "range_ref": "file:tests/test_demo.py#L3-L3",
                        "callee_expression": "hello_adapter",
                        "simple_name": "hello_adapter",
                        "caller_scope": "symbol",
                        "caller_symbol_id": "sym-test",
                        "caller_qualified_name": (
                            "tests.test_demo.test_hello_adapter"
                        ),
                        "caller_kind": "function",
                        "caller_start_line": 1,
                        "caller_end_line": 5,
                        "relation_type": "calls",
                        "evidence_level": "S1",
                        "resolution_status": "resolved",
                        "resolution_reason": "unique_symbol_resolution",
                        "resolved_target_ids": ["sym-demo"],
                        "candidate_target_ids": [],
                    },
                    {
                        "path": "src/demo.py",
                        "start_line": 4,
                        "start_col": 4,
                        "end_line": 4,
                        "end_col": 20,
                        "range_ref": "file:src/demo.py#L4-L4",
                        "callee_expression": "test_hello_adapter",
                        "simple_name": "test_hello_adapter",
                        "caller_scope": "symbol",
                        "caller_symbol_id": "sym-demo",
                        "caller_qualified_name": "demo.hello_adapter",
                        "caller_kind": "function",
                        "caller_start_line": 3,
                        "caller_end_line": 5,
                        "relation_type": "calls",
                        "evidence_level": "S1",
                        "resolution_status": "resolved",
                        "resolution_reason": "unique_symbol_resolution",
                        "resolved_target_ids": ["sym-test"],
                        "candidate_target_ids": [],
                    },
                ],
                "skipped_files_count": 0,
                "skipped_errors": [],
                "skipped_errors_total_count": 0,
                "does_not_establish": [
                    "complete_call_graph",
                    "runtime_reachability",
                    "dynamic_dispatch_resolution",
                    "dependency_completeness",
                    "import_success",
                    "test_sufficiency",
                    "review_completeness",
                    "merge_readiness",
                ],
            }
        )
        + "\n",
    )

    _add_artifact(
        bundle,
        "architecture_graph_json",
        "demo.architecture_graph.json",
        json.dumps(
            {
                "kind": "lenskit.architecture.graph",
                "version": "1.0",
                "run_id": "run-1",
                "canonical_dump_index_sha256": DIGEST,
                "nodes": [
                    {
                        "node_id": "file:src/demo.py",
                        "kind": "file",
                        "path": "src/demo.py",
                        "repo": "demo",
                        "is_test": False,
                    },
                    {
                        "node_id": "file:tests/test_demo.py",
                        "kind": "file",
                        "path": "tests/test_demo.py",
                        "repo": "demo",
                        "is_test": True,
                    },
                    {
                        "node_id": "file:docs/demo.md",
                        "kind": "file",
                        "path": "docs/demo.md",
                        "repo": "demo",
                        "is_test": False,
                    },
                ],
                "edges": [
                    {
                        "src": "file:tests/test_demo.py",
                        "dst": "file:src/demo.py",
                        "edge_type": "import",
                        "evidence_level": "S1",
                        "evidence": {
                            "source_path": "tests/test_demo.py",
                            "start_line": 1,
                        },
                    },
                    {
                        "src": "file:src/demo.py",
                        "dst": "file:docs/demo.md",
                        "edge_type": "string-ref",
                        "evidence_level": "S0",
                        "evidence": {
                            "source_path": "src/demo.py",
                            "start_line": 3,
                        },
                    },
                ],
                "coverage": {
                    "files_seen": 3,
                    "files_parsed": 3,
                    "edge_counts_by_type": {
                        "import": 1,
                        "string-ref": 1,
                    },
                    "unknown_layer_share": 0.0,
                },
            }
        )
        + "\n",
    )
    _add_artifact(
        bundle,
        "entrypoints_json",
        "demo.entrypoints.json",
        json.dumps(
            {
                "kind": "lenskit.entrypoints",
                "version": "1.0",
                "run_id": "run-1",
                "canonical_dump_index_sha256": DIGEST,
                "entrypoints": [
                    {
                        "id": "demo-cli",
                        "type": "cli",
                        "path": "src/demo.py",
                        "symbol": "hello_adapter",
                        "evidence_level": "S1",
                        "projection": "product",
                    }
                ],
            }
        )
        + "\n",
    )
    _add_artifact(
        bundle,
        "relation_cards_jsonl",
        "demo.relation_cards.jsonl",
        json.dumps(
            {
                "kind": "lenskit.relation_card",
                "version": "1.0",
                "card_id": "dependency.demo",
                "card_type": "dependency",
                "navigation_refs": [
                    {"kind": "repo_path", "target": "src/demo.py"}
                ],
            }
        )
        + "\n",
    )
    return RepoGroundAgentImpactAdapter.from_config(config), bundle, config


def test_agent_impact_adapter_composes_integrity_checked_reads_without_writes(
    tmp_path: Path,
) -> None:
    adapter, bundle, _config = _impact_adapter(tmp_path)
    before = {
        path.name: _sha(path)
        for path in tmp_path.iterdir()
        if path.is_file()
    }

    result = adapter.agent_impact_context(
        "demo",
        target_symbol="hello_adapter",
        mode="edit",
        include_query_context=False,
    )

    after = {
        path.name: _sha(path)
        for path in tmp_path.iterdir()
        if path.is_file()
    }
    assert result["status"] == "available"
    assert result["target"]["paths"] == ["src/demo.py"]
    assert result["relations"][0]["direction"] == "incoming"
    assert result["related_tests"][0]["path"] == "tests/test_demo.py"
    assert result["entrypoints"][0]["type"] == "cli"
    selection = result["edit_context"]["selection"]
    caller = selection["direct_callers"]["selected"][0]
    callee = selection["direct_callees"]["selected"][0]
    assert caller["path"] == "tests/test_demo.py"
    assert callee["path"] == "tests/test_demo.py"
    assert caller["evidence_level"] == callee["evidence_level"] == "S1"
    assert caller["freshness"]["status"] == "coherent"
    assert callee["freshness"]["status"] == "coherent"
    assert result["relation_cards"][0]["card_id"] == "dependency.demo"
    assert result["mutation_boundary"]["writes"] == []
    assert before == after
    assert not any(
        path.exists()
        for suffix in ("-wal", "-shm", "-journal")
        for path in [
            bundle["index_path"].with_name(
                bundle["index_path"].name + suffix
            )
        ]
    )


def test_agent_impact_adapter_skips_large_call_graph_without_target_symbols(
    tmp_path: Path,
    monkeypatch,
) -> None:
    adapter, _bundle, _config = _impact_adapter(tmp_path)

    def unexpected_projection(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("call graph projection should not run without target symbols")

    monkeypatch.setattr(
        "merger.repoground.core.agent_impact_adapter.project_call_graph_for_impact",
        unexpected_projection,
    )
    result = adapter.agent_impact_context(
        "demo",
        target_path="docs/not-a-python-symbol.md",
        mode="impact",
        include_query_context=False,
    )

    assert result["call_graph_projection"]["status"] == "skipped"
    assert result["call_graph_projection"]["reason"] == "no_target_symbols"
    assert not any(
        item.get("source") == "python_call_graph_json"
        for item in result.get("source_statuses", [])
    )


def test_agent_impact_adapter_projects_coherent_call_graph_relations_in_impact_mode(
    tmp_path: Path,
) -> None:
    adapter, _bundle, _config = _impact_adapter(tmp_path)

    result = adapter.agent_impact_context(
        "demo",
        target_symbol="hello_adapter",
        mode="impact",
        include_query_context=False,
    )

    call_relations = [
        item
        for item in result["relations"]
        if isinstance(item.get("freshness"), dict)
        and item["freshness"].get("source") == "python_call_graph_json"
    ]
    assert result["status"] == "available"
    assert "edit_context" not in result
    assert call_relations
    assert {item["relation_kind"] for item in call_relations} == {
        "direct_caller",
        "direct_callee",
    }
    assert all(item["freshness"]["status"] == "coherent" for item in call_relations)


def test_agent_impact_adapter_keeps_exact_later_path_reachable_for_call_graph(
    tmp_path: Path,
) -> None:
    adapter, bundle, _config = _impact_adapter(tmp_path)
    root = bundle["manifest"].parent
    symbol_path = root / "demo.python_symbol_index.json"
    symbol_document = json.loads(symbol_path.read_text(encoding="utf-8"))
    symbol_document["symbols"] = [
        {
            "id": "sym-early-exact",
            "kind": "function",
            "name": "needle",
            "qualified_name": "a_many.needle",
            "module": "a_many",
            "path": "src/a_many.py",
            "start_line": 1,
            "end_line": 2,
            "range_ref": "file:src/a_many.py#L1-L2",
            "decorators": [],
        },
        {
            "id": "sym-early-2",
            "kind": "function",
            "name": "early_two",
            "qualified_name": "a_many.early_two",
            "module": "a_many",
            "path": "src/a_many.py",
            "start_line": 10,
            "end_line": 11,
            "range_ref": "file:src/a_many.py#L10-L11",
            "decorators": [],
        },
        {
            "id": "sym-peer",
            "kind": "function",
            "name": "peer",
            "qualified_name": "peer.peer",
            "module": "peer",
            "path": "src/peer.py",
            "start_line": 3,
            "end_line": 5,
            "range_ref": "file:src/peer.py#L3-L5",
            "decorators": [],
        },
        {
            "id": "sym-late-non-target",
            "kind": "function",
            "name": "alpha",
            "qualified_name": "z_late.alpha",
            "module": "z_late",
            "path": "src/z_late.py",
            "start_line": 1,
            "end_line": 1,
            "range_ref": "file:src/z_late.py#L1-L1",
            "decorators": [],
        },
        {
            "id": "sym-late",
            "kind": "function",
            "name": "needle",
            "qualified_name": "z_late.needle",
            "module": "z_late",
            "path": "src/z_late.py",
            "start_line": 2,
            "end_line": 3,
            "range_ref": "file:src/z_late.py#L2-L3",
            "decorators": [],
        },
    ]
    symbol_path.write_text(json.dumps(symbol_document) + "\n", encoding="utf-8")
    _seal_existing_artifact(bundle, "python_symbol_index_json")

    call_graph_path = root / "demo.python_call_graph.json"
    call_graph = json.loads(call_graph_path.read_text(encoding="utf-8"))
    call_graph.update(
        {
            "call_count": 1,
            "resolution_counts": {
                "resolved": 1,
                "candidate": 0,
                "ambiguous": 0,
                "unresolved": 0,
            },
            "evidence_counts": {"S0": 0, "S1": 1},
            "relation_counts": {"calls": 1, "constructs": 0},
            "calls": [
                {
                    "path": "src/z_late.py",
                    "start_line": 3,
                    "start_col": 4,
                    "end_line": 3,
                    "end_col": 10,
                    "range_ref": "file:src/z_late.py#L3-L3",
                    "callee_expression": "peer",
                    "simple_name": "peer",
                    "caller_scope": "symbol",
                    "caller_symbol_id": "sym-late",
                    "caller_qualified_name": "z_late.needle",
                    "caller_kind": "function",
                    "caller_start_line": 2,
                    "caller_end_line": 3,
                    "relation_type": "calls",
                    "evidence_level": "S1",
                    "resolution_status": "resolved",
                    "resolution_reason": "unique_symbol_resolution",
                    "resolved_target_ids": ["sym-peer"],
                    "candidate_target_ids": [],
                }
            ],
        }
    )
    call_graph_path.write_text(json.dumps(call_graph) + "\n", encoding="utf-8")
    _seal_existing_artifact(bundle, "python_call_graph_json")

    result = adapter.agent_impact_context(
        "demo",
        target_symbol="needle",
        changed_paths=["src/a_many.py", "src/z_late.py"],
        mode="impact",
        max_items=2,
        include_query_context=False,
    )

    assert [item["id"] for item in result["target_symbols"]] == [
        "sym-early-exact",
        "sym-late",
    ]
    assert result["call_graph_projection"]["selected_call_count"] == 1
    call_relations = [
        item
        for item in result["relations"]
        if isinstance(item.get("freshness"), dict)
        and item["freshness"].get("source") == "python_call_graph_json"
    ]
    assert len(call_relations) == 1
    relation = call_relations[0]
    assert relation["relation_kind"] == "direct_callee"
    assert relation["symbol_id"] == "sym-peer"
    assert relation["target_symbol_ids"] == ["sym-late"]
    assert relation["evidence_level"] == "S1"
    assert relation["resolution_status"] == "resolved"
    assert relation["freshness"]["status"] == "coherent"


def test_agent_impact_adapter_dispatches_and_validates_arguments(
    tmp_path: Path,
) -> None:
    adapter, _bundle, _config = _impact_adapter(tmp_path)

    result = adapter.dispatch(
        {
            "action": "agent_impact_context",
            "snapshot_id": "demo",
            "target_path": "src/demo.py",
            "include_query_context": False,
            "max_items": True,
        }
    )

    assert result["status"] == "invalid"
    assert result["error_code"] == "agent_impact_request_invalid"


def test_agent_impact_adapter_blocks_tampered_required_artifact(
    tmp_path: Path,
) -> None:
    adapter, bundle, _config = _impact_adapter(tmp_path)
    graph_path = (
        bundle["manifest"].parent / "demo.architecture_graph.json"
    )
    graph_path.write_text("{}\n", encoding="utf-8")

    result = adapter.agent_impact_context(
        "demo",
        target_path="src/demo.py",
        include_query_context=False,
    )

    assert result["status"] == "blocked"
    assert result["relations"] == []
    assert any(
        gap.get("reason") == "required_source_untrusted"
        for gap in result["gaps"]
    )



def test_agent_impact_adapter_degrades_tampered_optional_call_graph(
    tmp_path: Path,
) -> None:
    adapter, bundle, _config = _impact_adapter(tmp_path)
    call_graph_path = (
        bundle["manifest"].parent / "demo.python_call_graph.json"
    )
    call_graph_path.write_text("{}\n", encoding="utf-8")

    result = adapter.agent_impact_context(
        "demo",
        target_symbol="hello_adapter",
        mode="edit",
        include_query_context=False,
    )

    assert result["status"] == "partial"
    assert result["edit_context"]["direct_caller_count"] == 0
    assert result["edit_context"]["direct_callee_count"] == 0
    gap = result["edit_context"]["call_graph_coverage_gaps"][0]
    assert gap["kind"] == "call_graph_source_untrusted"
    assert gap["freshness"]["source"] == "python_call_graph_json"
    assert gap["freshness"]["status"] == "blocked"


def test_agent_impact_cli_uses_registered_snapshot(
    tmp_path: Path,
    capsys,
) -> None:
    _adapter_instance, _bundle, config = _impact_adapter(tmp_path)

    exit_code = impact_cli_main(
        [
            "--config",
            str(config),
            "--snapshot-id",
            "demo",
            "--target-symbol",
            "hello_adapter",
            "--mode",
            "impact",
            "--no-query-context",
        ]
    )
    result = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert result["action"] == "agent_impact_context"
    assert result["target"]["paths"] == ["src/demo.py"]
