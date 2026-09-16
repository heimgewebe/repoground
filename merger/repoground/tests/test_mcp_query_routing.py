import json

from merger.repoground.tests.test_ask_context_cli import (
    _add_artifact,
    _complete_basic_bundle,
)
from merger.repoground.core import ask_context, mcp_tools


def test_symbol_definition_intent_is_conservative_and_bilingual():
    assert (
        mcp_tools._symbol_definition_intent(
            "Wo ist die Funktion snapshot_status definiert?"
        )
        == "snapshot_status"
    )
    assert (
        mcp_tools._symbol_definition_intent("Where is `snapshot_status` defined?")
        == "snapshot_status"
    )
    assert mcp_tools._symbol_definition_intent("How does snapshot status work?") is None
    assert (
        mcp_tools._symbol_definition_intent("Wo wird `snapshot_status` aufgerufen?")
        is None
    )
    assert (
        mcp_tools._symbol_definition_intent("Where is `snapshot_status` called?")
        is None
    )


def test_call_navigation_intent_is_conservative_and_bilingual():
    assert mcp_tools._call_navigation_intent(
        "Which Python functions directly call _cursor_offset?"
    ) == ("callers", "_cursor_offset")
    assert mcp_tools._call_navigation_intent("What functions call _cursor_offset?") == (
        "callers",
        "_cursor_offset",
    )
    assert mcp_tools._call_navigation_intent(
        "Welche Funktionen rufen `_cursor_offset` direkt auf?"
    ) == ("callers", "_cursor_offset")
    assert mcp_tools._call_navigation_intent(
        "Which functions does build_current_work_projection directly call?"
    ) == ("callees", "build_current_work_projection")
    assert mcp_tools._call_navigation_intent(
        "Welche Funktionen ruft `build_current_work_projection` direkt auf?"
    ) == ("callees", "build_current_work_projection")
    assert (
        mcp_tools._call_navigation_intent(
            "Welche Funktion ruft `_cursor_offset` direkt auf?"
        )
        is None
    )
    assert (
        mcp_tools._call_navigation_intent(
            "Which functions indirectly call _cursor_offset?"
        )
        is None
    )
    assert (
        mcp_tools._call_navigation_intent("Where is `_cursor_offset` called?") is None
    )
    assert mcp_tools._call_navigation_intent("How does call routing work?") is None


def _call_result(*, relation: str):
    common = {
        "status": "available",
        "availability": {"status": "pass"},
        "freshness": {"status": "not_comparable"},
        "hit_count": 1,
        "k": 5,
        "truncated": False,
        "total_call_site_count": 1,
        "call_graph_coverage": {
            "scope": "observed_call_edges",
            "completeness": "partial",
            "confidence_model": "observed_resolution_coverage_proxy",
            "model_scope": "observed_static_python_call_edges",
            "resolved_ratio": 0.5,
            "resolved_call_edges": 1,
            "total_call_edges": 2,
            "skipped_files_count": 0,
        },
    }
    if relation == "callers":
        common.update(
            {
                "target_symbol": {"id": "target", "name": "_cursor_offset"},
                "target_candidates": [],
                "callers": [
                    {
                        "caller_symbol": {
                            "id": "caller",
                            "name": "build_current_work_projection",
                            "path": "src/grabowski_current_work.py",
                            "range_ref": "file:src/grabowski_current_work.py#L2088-L2427",
                        },
                        "call_site_count": 1,
                        "call_sites": [
                            {
                                "range_ref": "file:src/grabowski_current_work.py#L2260-L2260"
                            }
                        ],
                    }
                ],
                "total_caller_count": 1,
                "unresolved_reference_count": 0,
                "unresolved_references": [],
            }
        )
    else:
        common.update(
            {
                "caller_symbol": {
                    "id": "caller",
                    "name": "build_current_work_projection",
                },
                "caller_candidates": [],
                "callees": [
                    {
                        "callee_symbol": {
                            "id": "callee",
                            "name": "_cursor_offset",
                            "path": "src/grabowski_current_work.py",
                            "range_ref": "file:src/grabowski_current_work.py#L900-L910",
                        },
                        "call_site_count": 1,
                        "call_sites": [
                            {
                                "range_ref": "file:src/grabowski_current_work.py#L2260-L2260"
                            }
                        ],
                        "relation_types": ["calls"],
                    }
                ],
                "total_callee_count": 1,
                "unresolved_call_site_count": 0,
                "unresolved_call_sites": [],
            }
        )
    return {"status": "available", "result": common}


def test_query_routes_direct_caller_question_to_call_graph(monkeypatch):
    monkeypatch.setattr(
        mcp_tools, "get_callers", lambda **_arguments: _call_result(relation="callers")
    )
    monkeypatch.setattr(
        ask_context,
        "build_ask_context_pack",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("text fallback must not run for a direct caller intent")
        ),
    )
    result = mcp_tools.query_existing_index(
        bundle_manifest="demo.bundle.manifest.json",
        query="Which Python functions directly call _cursor_offset?",
        k=5,
    )
    assert result["route"] == "callers"
    assert result["intent"] == {"kind": "callers", "symbol": "_cursor_offset"}
    assert (
        result["retrieval"]["strategy"] == "callers"
        and result["retrieval"]["fts_query"] is None
    )
    assert result["budget"]["context_bytes_used"] == 0
    assert result["navigation"]["total_caller_count"] == 1
    assert result["navigation"]["call_graph_coverage"]["resolved_ratio"] == 0.5
    assert (
        result["navigation_hits"][0]["caller_symbol"]["name"]
        == "build_current_work_projection"
    )


def test_query_routes_direct_callee_question_to_call_graph(monkeypatch):
    monkeypatch.setattr(
        mcp_tools, "get_callees", lambda **_arguments: _call_result(relation="callees")
    )
    monkeypatch.setattr(
        ask_context,
        "build_ask_context_pack",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("text fallback must not run for a direct callee intent")
        ),
    )
    result = mcp_tools.query_existing_index(
        bundle_manifest="demo.bundle.manifest.json",
        query="Which functions does build_current_work_projection directly call?",
        k=5,
    )
    assert result["route"] == "callees"
    assert result["intent"] == {
        "kind": "callees",
        "symbol": "build_current_work_projection",
    }
    assert (
        result["retrieval"]["strategy"] == "callees"
        and result["retrieval"]["fts_query"] is None
    )
    assert result["budget"]["context_bytes_used"] == 0
    assert result["navigation"]["total_callee_count"] == 1
    assert result["navigation"]["call_graph_coverage"]["resolved_ratio"] == 0.5
    assert result["navigation_hits"][0]["callee_symbol"]["name"] == "_cursor_offset"


def test_call_graph_intent_falls_back_to_text_when_navigation_is_unavailable(
    monkeypatch,
):
    monkeypatch.setattr(
        mcp_tools,
        "get_callers",
        lambda **_arguments: {"status": "missing", "result": {"status": "missing"}},
    )
    monkeypatch.setattr(
        ask_context,
        "build_ask_context_pack",
        lambda *_args, **_kwargs: {
            "retrieval": {
                "raw_query": "Which functions call missing_symbol?",
                "fts_query": "missing_symbol",
                "strategy": "exact_and",
                "match_count": 0,
            },
            "retrieval_hits": [],
            "resolved_ranges": [],
            "retrieval_infrastructure": {
                "status": "available",
                "index_resolved": True,
                "error_code": None,
                "detail": None,
            },
            "budget": {"max_context_tokens": 1000},
            "availability": {"status": "available", "caveats": []},
            "freshness": {"status": "fresh", "caveats": []},
            "answer_scaffold": {"caveats_to_surface": []},
        },
    )
    result = mcp_tools.query_existing_index(
        bundle_manifest="demo.bundle.manifest.json",
        query="Which functions call missing_symbol?",
        max_context_tokens=1000,
    )
    assert result["route"] == "text_retrieval"


def test_query_routes_exact_definition_question_to_symbol_index(monkeypatch):
    monkeypatch.setattr(
        mcp_tools,
        "find_symbol",
        lambda **_arguments: {
            "status": "available",
            "result": {
                "status": "available",
                "availability": {"status": "pass"},
                "freshness": {"status": "not_comparable"},
                "hits": [
                    {
                        "id": "exact",
                        "kind": "function",
                        "name": "snapshot_status",
                        "qualified_name": "snapshot_status",
                        "path": "src/snapshot.py",
                        "start_line": 10,
                        "end_line": 20,
                        "range_ref": "file:src/snapshot.py#L10-L20",
                        "source_range": {
                            "path": "src/snapshot.py",
                            "start_line": 10,
                            "end_line": 20,
                        },
                    },
                    {
                        "id": "fuzzy",
                        "kind": "function",
                        "name": "update_snapshot_status",
                        "qualified_name": "update_snapshot_status",
                        "path": "src/other.py",
                        "start_line": 1,
                        "end_line": 2,
                    },
                ],
            },
        },
    )
    monkeypatch.setattr(
        ask_context,
        "build_ask_context_pack",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("text fallback must not run for an exact symbol hit")
        ),
    )

    result = mcp_tools.query_existing_index(
        bundle_manifest="demo.bundle.manifest.json",
        query="Wo ist die Funktion snapshot_status definiert?",
        k=5,
    )

    assert result["route"] == "symbol_definition"
    assert result["retrieval"]["strategy"] == "symbol_definition"
    assert result["navigation_hits"] == [
        {
            "id": "exact",
            "kind": "function",
            "name": "snapshot_status",
            "qualified_name": "snapshot_status",
            "path": "src/snapshot.py",
            "start_line": 10,
            "end_line": 20,
            "range_ref": "file:src/snapshot.py#L10-L20",
            "source_range": {
                "path": "src/snapshot.py",
                "start_line": 10,
                "end_line": 20,
            },
        }
    ]
    assert result["resolved_ranges"] == []
    assert result["availability"] == {"status": "available", "caveats": []}
    assert result["freshness"]["status"] == "not_comparable"
    assert result["budget"]["truncated"] is False


def test_symbol_definition_scopes_structure_lookup_to_symbol_name(monkeypatch):
    observed_queries: list[str] = []
    monkeypatch.setattr(
        mcp_tools,
        "find_symbol",
        lambda **_arguments: {
            "status": "available",
            "result": {
                "status": "available",
                "availability": {"status": "pass"},
                "freshness": {"status": "not_comparable"},
                "hits": [
                    {
                        "id": "render-service-unit",
                        "kind": "function",
                        "name": "render_service_unit",
                        "qualified_name": "render_service_unit",
                        "path": "src/render.py",
                        "start_line": 10,
                        "end_line": 20,
                        "range_ref": "file:src/render.py#L10-L20",
                    }
                ],
            },
        },
    )

    def fake_language_structure(_manifest_path, *, query, **_kwargs):
        observed_queries.append(query)
        return {
            "status": "available",
            "reason": None,
            "retrieval_hits": [],
            "resolved_ranges": [],
            "structured_evidence": None,
            "used_bytes": 0,
            "used_unicode_characters": 0,
            "omissions": [],
            "truncated": False,
        }

    monkeypatch.setattr(
        ask_context, "_language_structure_for_query", fake_language_structure
    )
    result = mcp_tools.query_existing_index(
        bundle_manifest="demo.bundle.manifest.json",
        query="Where is the function render_service_unit defined?",
        k=5,
    )

    assert result["route"] == "symbol_definition"
    assert result["navigation_hits"][0]["name"] == "render_service_unit"
    assert observed_queries == ["render_service_unit"]


def test_exact_symbol_structure_filter_rejects_component_only_matches():
    response = {
        "status": "available",
        "content_json": {
            "record_count": 3,
            "records": [
                {"id": "definition", "symbol": "render_service_unit"},
                {
                    "id": "relation",
                    "symbol": "caller",
                    "target_symbol": "render_service_unit",
                },
                {"id": "component-noise", "symbol": "render_report"},
            ],
        },
    }

    filtered = mcp_tools._filter_language_structure_for_exact_symbol(
        response, symbol_name="render_service_unit"
    )

    assert response["content_json"]["record_count"] == 3
    assert filtered["content_json"]["record_count"] == 2
    assert [record["id"] for record in filtered["content_json"]["records"]] == [
        "definition",
        "relation",
    ]


def test_compact_symbol_hits_reports_total_before_limit():
    result = {
        "result": {
            "hits": [
                {
                    "id": "one",
                    "name": "run",
                    "qualified_name": "run",
                    "path": "src/a.py",
                    "start_line": 1,
                },
                {
                    "id": "two",
                    "name": "run",
                    "qualified_name": "Worker.run",
                    "path": "src/b.py",
                    "start_line": 2,
                },
            ]
        }
    }

    hits, total = mcp_tools._compact_symbol_hits(result, name="run", k=1)

    assert [hit["id"] for hit in hits] == ["one"]
    assert total == 2


def test_query_uses_text_retrieval_for_broad_question(monkeypatch):
    monkeypatch.setattr(
        ask_context,
        "build_ask_context_pack",
        lambda *_args, **_kwargs: {
            "retrieval": {
                "raw_query": "How does freshness work?",
                "fts_query": "freshness",
                "strategy": "exact_and",
                "match_count": 1,
            },
            "retrieval_hits": [],
            "resolved_ranges": [],
            "retrieval_infrastructure": {
                "status": "available",
                "index_resolved": True,
                "error_code": None,
                "detail": None,
            },
            "budget": {"max_context_tokens": 1000},
            "availability": {"status": "available", "caveats": []},
            "freshness": {"status": "fresh", "caveats": []},
            "answer_scaffold": {"caveats_to_surface": []},
        },
    )

    result = mcp_tools.query_existing_index(
        bundle_manifest="demo.bundle.manifest.json",
        query="How does freshness work?",
        max_context_tokens=1000,
    )

    assert result["route"] == "text_retrieval"
    assert result["retrieval"]["strategy"] == "exact_and"
    assert "navigation_hits" not in result


def test_snapshot_status_surfaces_unhealthy_exact_manifest(tmp_path):
    bundle = _complete_basic_bundle(tmp_path)
    _add_artifact(
        bundle,
        "output_health",
        "demo.output_health.json",
        json.dumps({"verdict": "fail"}) + "\n",
    )
    post_path = bundle["manifest"].parent / "demo.bundle_health.post.json"
    post_path.write_text(json.dumps({"status": "pass"}) + "\n", encoding="utf-8")
    document = json.loads(bundle["manifest"].read_text(encoding="utf-8"))
    document["links"] = {
        "post_emit_health_path": post_path.name,
        "bundle_surface_validation_status": "pass",
        "agent_export_gate_status": "pass",
        "export_safety_report_status": "pass",
    }
    bundle["manifest"].write_text(json.dumps(document), encoding="utf-8")

    result = mcp_tools.snapshot_status(bundle_manifest=bundle["manifest"])

    assert result["status"] == "unhealthy"
    assert result["health"]["health_status"] == "invalid"
    assert any("expected 'pass'" in reason for reason in result["health"]["reasons"])
    assert result["snapshot"]["health_status"] == "invalid"
