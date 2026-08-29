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
