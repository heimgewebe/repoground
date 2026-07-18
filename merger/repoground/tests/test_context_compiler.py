import hashlib
import json
from pathlib import Path

from merger.repoground.cli.main import main
from merger.repoground.core import context_compiler
from merger.repoground.core.citation_id import make_citation_id
from merger.repoground.core.context_compiler import compile_context_plan


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _artifact(role: str, path: Path, **extra):
    return {
        "role": role,
        "path": path.name,
        "content_type": extra.pop("content_type", "application/json"),
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
        **extra,
    }


def _write_complete_bundle(tmp_path: Path) -> Path:
    from merger.repoground.retrieval import index_db

    canonical = tmp_path / "brief.md"
    canonical.write_text("# Brief\n\nhello context compiler world\n", encoding="utf-8")
    content = canonical.read_bytes()
    start = content.index(b"hello")
    end = len(content)
    chunk_bytes = content[start:end]
    chunk_sha = _sha256_bytes(chunk_bytes)
    canonical_sha = _sha256_bytes(content)
    range_ref = {
        "artifact_role": "canonical_md",
        "repo_id": "demo",
        "file_path": canonical.name,
        "start_byte": start,
        "end_byte": end,
        "start_line": 3,
        "end_line": 3,
        "content_sha256": chunk_sha,
    }
    chunk = {
        "chunk_id": "c1",
        "repo_id": "demo",
        "path": canonical.name,
        "content": chunk_bytes.decode("utf-8"),
        "start_byte": start,
        "end_byte": end,
        "start_line": 3,
        "end_line": 3,
        "layer": "core",
        "artifact_type": "doc",
        "content_sha256": chunk_sha,
        "content_range_ref": range_ref,
    }
    chunk_path = tmp_path / "chunks.jsonl"
    chunk_path.write_text(json.dumps(chunk) + "\n", encoding="utf-8")
    dump_path = tmp_path / "dump.json"
    dump_path.write_text(json.dumps({"version": "1.0", "repos": {"demo": {}}}), encoding="utf-8")
    index_path = tmp_path / "demo.index.sqlite"
    index_db.build_index(dump_path, chunk_path, index_path)

    citation_id = make_citation_id(canonical_sha, start, end, chunk_sha)
    citation_map = tmp_path / "demo.citation_map.jsonl"
    citation_map.write_text(
        json.dumps(
            {
                "citation_id": citation_id,
                "repo_id": "demo",
                "chunk_id": "c1",
                "snapshot": {
                    "run_id": "run-1",
                    "canonical_md_path": canonical.name,
                    "canonical_md_sha256": canonical_sha,
                },
                "canonical_range": {
                    "file_path": canonical.name,
                    "start_byte": start,
                    "end_byte": end,
                    "start_line": 3,
                    "end_line": 3,
                    "content_sha256": chunk_sha,
                },
                "range_ref": range_ref,
                "produced_by": "citation_map_producer/v1",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    agent_pack = tmp_path / "demo.agent.md"
    agent_pack.write_text("# Agent Pack\n\nRead canonical_md for truth.\n", encoding="utf-8")
    symbol_index = tmp_path / "demo.python_symbol_index.json"
    symbol_index.write_text(
        json.dumps(
            {
                "kind": "lenskit.python_symbol_index",
                "version": "1.0",
                "run_id": "run-1",
                "canonical_dump_index_sha256": "a" * 64,
                "language": "python",
                "symbol_kinds": ["class", "function", "async_function"],
                "symbols": [
                    {
                        "id": "py:pkg/context.py:class:ContextCompiler",
                        "kind": "class",
                        "name": "ContextCompiler",
                        "qualified_name": "ContextCompiler",
                        "module": "pkg.context",
                        "path": "pkg/context.py",
                        "start_line": 10,
                        "end_line": 30,
                        "range_ref": "file:pkg/context.py#L10-L30",
                    }
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
        ),
        encoding="utf-8",
    )
    relation_cards = tmp_path / "demo.relation_cards.jsonl"
    relation_cards.write_text(
        json.dumps(
            {
                "kind": "lenskit.relation_card",
                "version": "1.0",
                "id": "rel-1",
                "relation": "imports",
                "source": {"kind": "repo_path", "path": "pkg/context_compiler.py"},
                "target": {"kind": "repo_path", "path": "pkg/token_budget.py"},
                "evidence": {"source_path": "pkg/context_compiler.py", "start_line": 1, "end_line": 1},
                "evidence_level": "S1",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "demo.bundle.manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "kind": "repolens.bundle.manifest",
                "version": "1.0",
                "run_id": "run-1",
                "created_at": "2026-07-08T10:00:00Z",
                "artifacts": [
                    _artifact("canonical_md", canonical, content_type="text/markdown"),
                    _artifact("agent_reading_pack", agent_pack, content_type="text/markdown"),
                    _artifact("chunk_index_jsonl", chunk_path, content_type="application/x-ndjson"),
                    _artifact("sqlite_index", index_path, content_type="application/vnd.sqlite3"),
                    _artifact("citation_map_jsonl", citation_map, content_type="application/x-ndjson"),
                    _artifact("python_symbol_index_json", symbol_index),
                    _artifact("relation_cards_jsonl", relation_cards, content_type="application/x-ndjson"),
                ],
                "links": {},
                "capabilities": {"repobrief_profile": "agent-portable"},
            }
        ),
        encoding="utf-8",
    )
    return manifest


def _write_fallback_bundle(tmp_path: Path) -> Path:
    canonical = tmp_path / "brief.md"
    canonical.write_text("# Brief\n\nOnly canonical fallback is available.\n", encoding="utf-8")
    agent_pack = tmp_path / "demo.agent.md"
    agent_pack.write_text("# Agent Pack\n", encoding="utf-8")
    manifest = tmp_path / "demo.bundle.manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "kind": "repolens.bundle.manifest",
                "version": "1.0",
                "run_id": "run-fallback",
                "artifacts": [
                    _artifact("canonical_md", canonical, content_type="text/markdown"),
                    _artifact("agent_reading_pack", agent_pack, content_type="text/markdown"),
                ],
                "links": {},
                "capabilities": {},
            }
        ),
        encoding="utf-8",
    )
    return manifest


def _refresh_artifact_metadata(manifest: Path, *, role: str, artifact_path: Path) -> None:
    manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
    artifact = next(
        item
        for item in manifest_payload["artifacts"]
        if item["role"] == role
    )
    artifact["bytes"] = artifact_path.stat().st_size
    artifact["sha256"] = _sha256(artifact_path)
    manifest.write_text(json.dumps(manifest_payload), encoding="utf-8")


def test_compile_context_plan_selects_ordered_evidence_with_citations(tmp_path):
    manifest = _write_complete_bundle(tmp_path)

    plan = compile_context_plan(
        manifest,
        task="Explain the context compiler",
        task_profile="basic_repo_question",
        query="context compiler",
        context_budget_tokens=120,
        bytes_per_token=4.0,
    )

    assert plan["kind"] == "repobrief.context_compiler"
    assert plan["status"] in {"pass", "warn"}
    assert plan["selected_context"][0]["source"] == "resolved_evidence"
    first_citation = plan["selected_context"][0]["citations"][0]
    assert first_citation["source_range"]["file_path"] == "brief.md"
    assert plan["selected_context"][0]["source_range"]["file_path"] == "brief.md"
    assert any(item["source"] == "python_symbol_index_json" for item in plan["selected_context"])
    assert any(item["source"] == "relation_cards_jsonl" for item in plan["selected_context"])
    assert plan["signals"]["relation_cards_jsonl"]["status"] == "available"
    assert plan["fallback_context"]["available"] is True
    assert plan["mutation_boundary"]["writes"] == []
    assert "exact_token_count" in plan["does_not_establish"]


def test_compile_context_plan_streams_relation_cards_without_read_text(tmp_path, monkeypatch):
    manifest = _write_complete_bundle(tmp_path)
    relation_cards = tmp_path / "demo.relation_cards.jsonl"
    original_read_text = Path.read_text

    def guarded_read_text(path, *args, **kwargs):
        if path == relation_cards:
            raise AssertionError("relation cards must be streamed instead of loaded wholesale")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded_read_text)

    plan = compile_context_plan(
        manifest,
        task="Explain the context compiler",
        task_profile="basic_repo_question",
        query="context compiler",
        context_budget_tokens=120,
        bytes_per_token=4.0,
    )

    assert plan["signals"]["relation_cards_jsonl"]["status"] == "available"
    assert any(item["source"] == "relation_cards_jsonl" for item in plan["selected_context"])


def test_compile_context_plan_bounds_invalid_relation_row_details(tmp_path):
    manifest = _write_complete_bundle(tmp_path)
    relation_cards = tmp_path / "demo.relation_cards.jsonl"
    valid_row = relation_cards.read_text(encoding="utf-8")
    relation_cards.write_text("not-json\n" * 12 + valid_row, encoding="utf-8")

    _refresh_artifact_metadata(manifest, role="relation_cards_jsonl", artifact_path=relation_cards)

    plan = compile_context_plan(
        manifest,
        task="Explain the context compiler",
        task_profile="basic_repo_question",
        query="context compiler",
        context_budget_tokens=120,
        bytes_per_token=4.0,
    )

    signal = plan["signals"]["relation_cards_jsonl"]
    relation_gap = next(gap for gap in plan["gaps"] if gap["source"] == "relation_cards_jsonl")
    assert signal["status"] == "warn"
    assert signal["invalid_row_count"] == 12
    assert signal["invalid_row_count_scope"] == "complete_artifact"
    assert signal["json_row_validation_complete"] is True
    assert signal["candidate_limit_reached"] is False
    assert signal["row_error_sample_count"] == 10
    assert signal["row_errors_truncated"] is True
    assert relation_gap["invalid_row_count"] == 12
    assert relation_gap["row_error_sample_limit"] == 10
    assert relation_gap["row_errors_truncated"] is True
    assert len(relation_gap["row_errors"]) == 10
    assert {item["error_type"] for item in relation_gap["row_errors"]} == {"json_decode"}
    assert all(item["message"] for item in relation_gap["row_errors"])
    assert all("error" not in item for item in relation_gap["row_errors"])


def test_compile_context_plan_does_not_match_missing_values_as_none(tmp_path):
    manifest = _write_complete_bundle(tmp_path)
    relation_cards = tmp_path / "demo.relation_cards.jsonl"
    relation_card = json.loads(relation_cards.read_text(encoding="utf-8"))
    relation_card.pop("relation")
    relation_cards.write_text(json.dumps(relation_card) + "\n", encoding="utf-8")
    _refresh_artifact_metadata(manifest, role="relation_cards_jsonl", artifact_path=relation_cards)

    plan = compile_context_plan(
        manifest,
        task="Find none",
        task_profile="basic_repo_question",
        query="none",
        context_budget_tokens=120,
        bytes_per_token=4.0,
    )

    signal = plan["signals"]["relation_cards_jsonl"]
    assert signal["status"] == "available"
    assert signal["hit_count"] == 0
    assert not any(item["source"] == "relation_cards_jsonl" for item in plan["selected_context"])


def test_compile_context_plan_compact_fallback_is_case_insensitive(tmp_path):
    manifest = _write_complete_bundle(tmp_path)

    plan = compile_context_plan(
        manifest,
        task="Explain the context compiler",
        task_profile="basic_repo_question",
        query="CONTEXT-COMPILER",
        context_budget_tokens=120,
        bytes_per_token=4.0,
    )

    signal = plan["signals"]["relation_cards_jsonl"]
    assert signal["status"] == "available"
    assert signal["hit_count"] == 1
    assert any(item["source"] == "relation_cards_jsonl" for item in plan["selected_context"])


def test_compile_context_plan_bounds_invalid_rows_before_hit_limit(tmp_path):
    manifest = _write_complete_bundle(tmp_path)
    relation_cards = tmp_path / "demo.relation_cards.jsonl"
    valid_row = relation_cards.read_text(encoding="utf-8")
    relation_cards.write_text(
        "not-json\n" * 12 + valid_row + "unparsed-invalid-tail\n",
        encoding="utf-8",
    )
    _refresh_artifact_metadata(manifest, role="relation_cards_jsonl", artifact_path=relation_cards)

    plan = compile_context_plan(
        manifest,
        task="Explain the context compiler",
        task_profile="basic_repo_question",
        query="context compiler",
        context_budget_tokens=120,
        signal_k=1,
        bytes_per_token=4.0,
    )

    signal = plan["signals"]["relation_cards_jsonl"]
    relation_gap = next(gap for gap in plan["gaps"] if gap["source"] == "relation_cards_jsonl")
    assert signal["status"] == "warn"
    assert signal["candidate_limit_reached"] is True
    assert signal["json_row_validation_complete"] is False
    assert signal["invalid_row_count"] == 12
    assert signal["invalid_row_count_scope"] == "parsed_prefix"
    assert signal["row_error_sample_count"] == 10
    assert signal["row_errors_truncated"] is True
    assert relation_gap["row_errors_truncated"] is True
    assert len(relation_gap["row_errors"]) == 10


def test_compile_context_plan_prioritizes_relation_match_order_not_source_row(tmp_path):
    manifest = _write_complete_bundle(tmp_path)
    relation_cards = tmp_path / "demo.relation_cards.jsonl"
    matching_card = json.loads(relation_cards.read_text(encoding="utf-8"))
    filler_cards = [
        {
            "kind": "lenskit.relation_card",
            "version": "1.0",
            "id": f"filler-{index}",
            "relation": "imports",
            "source": {"kind": "repo_path", "path": f"pkg/filler_{index}.py"},
            "target": {"kind": "repo_path", "path": "pkg/other.py"},
            "evidence": {},
            "evidence_level": "S1",
        }
        for index in range(100)
    ]
    rows = [*filler_cards, matching_card]
    relation_cards.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )
    _refresh_artifact_metadata(manifest, role="relation_cards_jsonl", artifact_path=relation_cards)

    plan = compile_context_plan(
        manifest,
        task="Explain the context compiler",
        task_profile="basic_repo_question",
        query="context compiler",
        context_budget_tokens=120,
        signal_k=1,
        bytes_per_token=4.0,
    )

    relation_items = [
        item
        for item in plan["selected_context"] + plan["omitted_context"]
        if item["source"] == "relation_cards_jsonl"
    ]
    assert len(relation_items) == 1
    assert relation_items[0]["id"] == "relation:101"
    assert relation_items[0]["priority"] == 25


def test_compile_context_plan_reports_json_validation_scope_after_hit_limit(tmp_path):
    manifest = _write_complete_bundle(tmp_path)
    relation_cards = tmp_path / "demo.relation_cards.jsonl"
    relation_cards.write_text(
        relation_cards.read_text(encoding="utf-8") + "not-json\n",
        encoding="utf-8",
    )
    _refresh_artifact_metadata(manifest, role="relation_cards_jsonl", artifact_path=relation_cards)

    plan = compile_context_plan(
        manifest,
        task="Explain the context compiler",
        task_profile="basic_repo_question",
        query="context compiler",
        context_budget_tokens=120,
        signal_k=1,
        bytes_per_token=4.0,
    )

    signal = plan["signals"]["relation_cards_jsonl"]
    assert signal["status"] == "available"
    assert signal["candidate_limit_reached"] is True
    assert signal["json_row_validation_complete"] is False
    assert signal["tail_utf8_validation_complete"] is True
    assert signal["invalid_row_count"] == 0
    assert signal["invalid_row_count_scope"] == "parsed_prefix"


def test_compile_context_plan_rejects_invalid_utf8_before_relation_hit(tmp_path):
    manifest = _write_complete_bundle(tmp_path)
    relation_cards = tmp_path / "demo.relation_cards.jsonl"
    relation_cards.write_bytes(b"\xff" + relation_cards.read_bytes())
    _refresh_artifact_metadata(manifest, role="relation_cards_jsonl", artifact_path=relation_cards)

    plan = compile_context_plan(
        manifest,
        task="Explain the context compiler",
        task_profile="basic_repo_question",
        query="context compiler",
        context_budget_tokens=120,
        signal_k=1,
        bytes_per_token=4.0,
    )

    signal = plan["signals"]["relation_cards_jsonl"]
    relation_gap = next(gap for gap in plan["gaps"] if gap["source"] == "relation_cards_jsonl")
    assert signal["status"] == "invalid"
    assert signal["error_code"] == "relation_cards_jsonl_unreadable"
    assert relation_gap["error_code"] == "relation_cards_jsonl_unreadable"
    assert not any(item["source"] == "relation_cards_jsonl" for item in plan["selected_context"])


def test_compile_context_plan_rejects_invalid_utf8_after_relation_hit(tmp_path, monkeypatch):
    manifest = _write_complete_bundle(tmp_path)
    relation_cards = tmp_path / "demo.relation_cards.jsonl"
    relation_cards.write_bytes(
        relation_cards.read_bytes()
        + b" " * (256 * 1024)
        + b"\xff"
    )
    _refresh_artifact_metadata(manifest, role="relation_cards_jsonl", artifact_path=relation_cards)
    consumed_tail = False
    original_consume = context_compiler._consume_text_stream

    def tracking_consume(handle):
        nonlocal consumed_tail
        consumed_tail = True
        return original_consume(handle)

    monkeypatch.setattr(context_compiler, "_consume_text_stream", tracking_consume)

    plan = compile_context_plan(
        manifest,
        task="Explain the context compiler",
        task_profile="basic_repo_question",
        query="context compiler",
        context_budget_tokens=120,
        signal_k=1,
        bytes_per_token=4.0,
    )

    signal = plan["signals"]["relation_cards_jsonl"]
    relation_gap = next(gap for gap in plan["gaps"] if gap["source"] == "relation_cards_jsonl")
    assert consumed_tail is True
    assert signal["status"] == "invalid"
    assert signal["error_code"] == "relation_cards_jsonl_unreadable"
    assert relation_gap["error_code"] == "relation_cards_jsonl_unreadable"
    assert not any(item["source"] == "relation_cards_jsonl" for item in plan["selected_context"])


def test_compile_context_plan_falls_back_to_required_reading_when_signals_missing(tmp_path):
    manifest = _write_fallback_bundle(tmp_path)

    plan = compile_context_plan(
        manifest,
        task="Fallback only",
        task_profile="basic_repo_question",
        context_budget_tokens=100,
    )

    assert plan["status"] == "warn"
    selected_roles = {item.get("artifact_role") for item in plan["selected_context"]}
    assert {"canonical_md", "agent_reading_pack"}.issubset(selected_roles)
    assert plan["signals"]["resolved_evidence"]["status"] == "missing"
    assert plan["signals"]["python_symbol_index_json"]["status"] == "missing"
    assert any(gap["source"] == "resolved_evidence" for gap in plan["gaps"])
    assert plan["fallback_context"]["available"] is True


def test_compile_context_plan_records_omitted_candidates_when_budget_is_small(tmp_path):
    manifest = _write_complete_bundle(tmp_path)

    plan = compile_context_plan(
        manifest,
        task="Explain the context compiler",
        task_profile="basic_repo_question",
        query="context compiler",
        context_budget_tokens=12,
        bytes_per_token=4.0,
    )

    assert plan["status"] == "warn"
    assert plan["selected_count"] >= 1
    assert plan["omitted_count"] >= 1
    assert "estimated_tokens_exceed_remaining_budget" in plan["selection_trace"]["omission_reasons"]
    assert all("budget_remaining_tokens" in item for item in plan["omitted_context"])


def test_compile_context_plan_rejects_invalid_budget(tmp_path):
    manifest = _write_fallback_bundle(tmp_path)

    plan = compile_context_plan(
        manifest,
        task="invalid",
        context_budget_tokens=0,
    )

    assert plan["status"] == "invalid"
    assert plan["error_code"] == "context_budget_out_of_bounds"
    assert plan["mutation_boundary"]["writes"] == []


def test_compile_context_plan_rejects_zero_signal_k(tmp_path):
    manifest = _write_fallback_bundle(tmp_path)

    plan = compile_context_plan(
        manifest,
        task="invalid",
        signal_k=0,
    )

    assert plan["status"] == "invalid"
    assert plan["error_code"] == "signal_k_out_of_bounds"
    assert plan["mutation_boundary"]["writes"] == []


def test_compile_context_plan_rejects_invalid_bytes_per_token(tmp_path):
    manifest = _write_fallback_bundle(tmp_path)

    plan = compile_context_plan(
        manifest,
        task="invalid",
        bytes_per_token="four",
    )

    assert plan["status"] == "invalid"
    assert plan["error_code"] == "bytes_per_token_invalid"


def test_context_compile_cli_outputs_plan(tmp_path, capsys):
    manifest = _write_complete_bundle(tmp_path)

    rc = main([
        "repobrief",
        "context",
        "compile",
        "--bundle-manifest",
        str(manifest),
        "--task",
        "Explain the context compiler",
        "--query",
        "context compiler",
        "--context-budget",
        "120",
    ])

    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["kind"] == "repobrief.context_compiler"
    assert out["selected_count"] >= 1
    assert out["budget"]["context_budget_tokens"] == 120
