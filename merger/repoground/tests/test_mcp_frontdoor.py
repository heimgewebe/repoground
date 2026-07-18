from pathlib import Path

from merger.repoground.core import mcp_tools
from merger.repoground.tests.test_answer_grounding_verifier import _bundle, _declaration
from merger.repoground.tests.test_ask_context_cli import _complete_basic_bundle


def test_mcp_ask_context_exposes_same_context_pack_semantics(tmp_path):
    bundle = _complete_basic_bundle(tmp_path)

    result = mcp_tools.ask_context(
        bundle_manifest=bundle["manifest"],
        query="hello",
        task_profile="basic_repo_question",
        max_context_tokens=8000,
        max_answer_tokens=1200,
        k=5,
    )

    assert result["kind"] == "repobrief.mcp.read_only_frontdoor"
    assert result["tool"] == "ask_context"
    assert result["status"] == "ok"
    assert result["request_semantics"] == "repobrief.ask_request.v1"
    assert result["context_pack_semantics"] == "repobrief.ask_context_pack.v1"
    assert result["context_pack"]["kind"] == "repobrief.ask_context_pack"
    assert result["context_pack"]["required_reading"]["status"] == "pass"
    assert result["context_pack"]["resolved_ranges"][0]["status"] == "resolved"
    assert result["mutation_boundary"]["writes"] == []
    assert result["mutation_boundary"]["read_paths_do_not_refresh"] is True
    assert "snapshot_create_side_effect" in result["mutation_boundary"]["forbidden_operations"]
    assert "secret_read" in result["mutation_boundary"]["forbidden_operations"]


def test_mcp_grounding_verify_exposes_same_verdict_semantics(tmp_path):
    manifest, citation_map, range_ref = _bundle(tmp_path)
    declaration = _declaration(range_ref)
    declaration["declared_artifacts"] = [
        "agent_reading_pack",
        "canonical_md",
        "citation_map_jsonl",
        "snapshot_plan_json",
    ]

    result = mcp_tools.grounding_verify(
        declaration=declaration,
        bundle_manifest=manifest,
        citation_map=citation_map,
        task_profile="basic_repo_question",
    )

    assert result["kind"] == "repobrief.mcp.read_only_frontdoor"
    assert result["tool"] == "grounding_verify"
    assert result["status"] == "pass"
    assert result["declaration_semantics"] == "repobrief.answer_grounding_declaration.v1"
    assert result["verdict_semantics"] == "repobrief.answer_grounding_verdict.v1"
    assert result["verdict"]["kind"] == "repobrief.answer_grounding_verdict"
    assert result["verdict"]["status"] == "pass"
    assert result["mutation_boundary"]["writes"] == []
    assert "git_push" in result["mutation_boundary"]["forbidden_operations"]
    assert "auto_merge" in result["mutation_boundary"]["forbidden_operations"]


def test_mcp_read_only_frontdoor_does_not_call_snapshot_create(monkeypatch, tmp_path):
    bundle = _complete_basic_bundle(tmp_path)

    def forbidden_snapshot_create(**_kwargs):
        raise AssertionError("read-only MCP frontdoor must not call snapshot_create")

    monkeypatch.setattr(mcp_tools, "snapshot_create", forbidden_snapshot_create)

    result = mcp_tools.ask_context(
        bundle_manifest=bundle["manifest"],
        query="hello",
    )

    assert result["status"] == "ok"
    assert result["mutation_boundary"]["writes"] == []


def test_mcp_read_only_frontdoor_does_not_write_bundle_files(tmp_path):
    bundle = _complete_basic_bundle(tmp_path)
    before = {path.name for path in Path(tmp_path).iterdir()}

    mcp_tools.ask_context(bundle_manifest=bundle["manifest"], query="hello")

    after = {path.name for path in Path(tmp_path).iterdir()}
    assert after == before
