import hashlib
import json
from pathlib import Path

from merger.repoground.cli.main import main
import merger.repoground.core.delta_context as dc


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


def _sample_diff() -> str:
    return """diff --git a/merger/repoground/core/example.py b/merger/repoground/core/example.py
index 1111111..2222222 100644
--- a/merger/repoground/core/example.py
+++ b/merger/repoground/core/example.py
@@ -10,3 +10,4 @@ def existing():
 old = 1
+new = 2
 keep = 3
diff --git a/docs/old.md b/docs/new.md
similarity index 90%
rename from docs/old.md
rename to docs/new.md
--- a/docs/old.md
+++ b/docs/new.md
@@ -1,2 +1,2 @@
-old title
+new title
diff --git a/merger/repoground/core/added.py b/merger/repoground/core/added.py
new file mode 100644
--- /dev/null
+++ b/merger/repoground/core/added.py
@@ -0,0 +1,2 @@
+fresh
+code
diff --git a/merger/repoground/core/removed.py b/merger/repoground/core/removed.py
deleted file mode 100644
--- a/merger/repoground/core/removed.py
+++ /dev/null
@@ -1,2 +0,0 @@
-dead
-code
"""


def _write_bundle(tmp_path: Path) -> Path:
    from merger.repoground.retrieval import index_db

    canonical = tmp_path / "brief.md"
    canonical.write_text(
        "# Brief\n\nmerger/repoground/core/example.py defines ExampleCompiler.\n",
        encoding="utf-8",
    )
    content = canonical.read_bytes()
    start = content.index(b"merger/repoground/core/example.py")
    end = len(content)
    chunk_bytes = content[start:end]
    chunk = {
        "chunk_id": "c1",
        "repo_id": "demo",
        "path": "merger/repoground/core/example.py",
        "content": chunk_bytes.decode("utf-8"),
        "start_byte": start,
        "end_byte": end,
        "start_line": 3,
        "end_line": 3,
        "layer": "core",
        "artifact_type": "code",
        "content_sha256": _sha256_bytes(chunk_bytes),
        "content_range_ref": {
            "artifact_role": "canonical_md",
            "repo_id": "demo",
            "file_path": canonical.name,
            "start_byte": start,
            "end_byte": end,
            "start_line": 3,
            "end_line": 3,
            "content_sha256": _sha256_bytes(chunk_bytes),
        },
    }
    chunk_path = tmp_path / "chunks.jsonl"
    chunk_path.write_text(json.dumps(chunk) + "\n", encoding="utf-8")
    dump_path = tmp_path / "dump.json"
    dump_path.write_text(json.dumps({"version": "1.0", "repos": {"demo": {}}}), encoding="utf-8")
    index_path = tmp_path / "demo.index.sqlite"
    index_db.build_index(dump_path, chunk_path, index_path)

    agent_pack = tmp_path / "agent.md"
    agent_pack.write_text("# Agent Pack\n", encoding="utf-8")
    symbol_index = tmp_path / "symbols.json"
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
                        "id": "py:merger/repoground/core/example.py:class:ExampleCompiler",
                        "kind": "class",
                        "name": "ExampleCompiler",
                        "qualified_name": "ExampleCompiler",
                        "module": "merger.repoground.core.example",
                        "path": "merger/repoground/core/example.py",
                        "start_line": 10,
                        "end_line": 20,
                        "range_ref": "file:merger/repoground/core/example.py#L10-L20",
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
    relation_cards = tmp_path / "relations.jsonl"
    relation_cards.write_text(
        json.dumps(
            {
                "kind": "lenskit.relation_card",
                "version": "1.0",
                "relation": "imports",
                "source": {"kind": "repo_path", "path": "merger/repoground/core/example.py"},
                "target": {"kind": "repo_path", "path": "merger/repoground/tests/test_example.py"},
                "evidence": {"source_path": "merger/repoground/core/example.py", "start_line": 1, "end_line": 1},
                "evidence_level": "S1",
                "does_not_establish": ["runtime_dependency", "causality"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "bundle.manifest.json"
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


def test_parse_unified_diff_extracts_changed_ranges_and_surrounding_context():
    parsed = dc.parse_unified_diff(_sample_diff(), context_window_lines=5)

    assert parsed["file_count"] == 4
    assert parsed["change_status_counts"] == {"modified": 1, "renamed": 1, "added": 1, "deleted": 1}
    first = parsed["files"][0]
    assert first["path"] == "merger/repoground/core/example.py"
    assert first["hunks"][0]["new_range"] == {"start_line": 10, "end_line": 13, "line_count": 4, "empty": False, "basis": "new"}
    assert first["hunks"][0]["surrounding_range"]["start_line"] == 5
    added = parsed["files"][2]
    assert added["change_status"] == "added"
    assert added["hunks"][0]["changed_range"]["basis"] == "new"
    deleted = parsed["files"][3]
    assert deleted["change_status"] == "deleted"
    assert deleted["hunks"][0]["changed_range"]["basis"] == "old"


def test_compile_delta_context_without_bundle_is_context_only_and_passes_with_info_gap(tmp_path):
    diff = tmp_path / "change.diff"
    diff.write_text(_sample_diff(), encoding="utf-8")

    result = dc.compile_delta_context(diff_path=diff, context_budget_tokens=5000)

    assert result["kind"] == "repobrief.delta_context_compiler"
    assert result["status"] == "pass"
    assert result["input_validity"] == "valid"
    assert result["signal_quality"] == "complete_or_not_requested"
    assert result["context_completeness"] == "within_budget"
    assert result["diff"]["file_count"] == 4
    assert result["signals"]["bundle"]["status"] == "not_requested"
    assert any(gap["source"] == "bundle_manifest" and gap["severity"] == "info" for gap in result["gaps"])
    assert result["review_boundary"] == {
        "context_only": True,
        "verdict": None,
        "approval": False,
        "rejection": False,
        "merge_authorization": False,
    }
    assert result["mutation_boundary"]["writes"] == []
    assert "merge_readiness" in result["does_not_establish"]
    assert any(item["source"] == "diff" for item in result["review_context"])


def test_compile_delta_context_uses_optional_bundle_signals(tmp_path):
    diff = tmp_path / "change.diff"
    diff.write_text(_sample_diff(), encoding="utf-8")
    manifest = _write_bundle(tmp_path)

    result = dc.compile_delta_context(
        diff_path=diff,
        bundle_manifest=manifest,
        context_budget_tokens=5000,
        signal_k=5,
    )

    assert result["status"] in {"pass", "warn"}
    assert result["signals"]["bundle"]["status"] == "ok"
    assert result["signals"]["python_symbol_index_json"]["hit_count"] >= 1
    assert result["signals"]["relation_cards_jsonl"]["hit_count"] == 1
    assert result["signals"]["resolved_evidence"]["hit_count"] >= 1
    assert any(gap["source"] == "freshness" for gap in result["gaps"])
    assert any(gap["source"] == "graph_availability" for gap in result["gaps"])
    sources = {item["source"] for item in result["review_context"]}
    assert {"diff", "python_symbol_index_json", "relation_cards_jsonl", "resolved_evidence"}.issubset(sources)
    assert result["review_boundary"]["verdict"] is None


def test_compile_delta_context_small_budget_omits_context(tmp_path):
    diff = tmp_path / "change.diff"
    diff.write_text(_sample_diff(), encoding="utf-8")

    result = dc.compile_delta_context(diff_path=diff, context_budget_tokens=20)

    assert result["status"] == "warn"
    assert result["omitted_context"]
    assert "estimated_tokens_exceed_remaining_budget" in result["selection_trace"]["omission_reasons"]


def test_compile_delta_context_invalid_empty_diff_fails(tmp_path):
    diff = tmp_path / "empty.diff"
    diff.write_text("not a unified diff\n", encoding="utf-8")

    result = dc.compile_delta_context(diff_path=diff)

    assert result["status"] == "invalid"
    assert result["input_validity"] == "invalid"
    assert result["changed_files"] == []
    assert any(gap["source"] == "diff" and gap["severity"] == "error" for gap in result["gaps"])


def test_delta_context_cli_outputs_json(tmp_path, capsys):
    diff = tmp_path / "change.diff"
    diff.write_text(_sample_diff(), encoding="utf-8")

    rc = main([
        "repobrief",
        "delta-context",
        "compile",
        "--diff",
        str(diff),
        "--context-budget",
        "500",
    ])

    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["kind"] == "repobrief.delta_context_compiler"
    assert out["review_boundary"]["approval"] is False



def test_compile_delta_context_empty_optional_signal_hits_do_not_warn(tmp_path):
    diff = tmp_path / "doc.diff"
    diff.write_text(
        """diff --git a/docs/guide.md b/docs/guide.md
--- a/docs/guide.md
+++ b/docs/guide.md
@@ -1,1 +1,2 @@
 title
+more
""",
        encoding="utf-8",
    )
    manifest = _write_bundle(tmp_path)

    result = dc.compile_delta_context(
        diff_path=diff,
        bundle_manifest=manifest,
        context_budget_tokens=500,
    )

    assert result["input_validity"] == "valid"
    # The synthetic bundle has degraded availability, so the overall result may warn,
    # but empty symbol/relation/evidence searches are informational only.
    empty_optional = [
        gap for gap in result["gaps"]
        if gap["source"] in {"python_symbol_index_json", "relation_cards_jsonl", "resolved_evidence"}
        and gap["status"] == "empty"
    ]
    assert empty_optional
    assert all(gap["severity"] == "info" for gap in empty_optional)
    assert result["signals"]["python_symbol_index_json"]["status"] in {"empty", "available"}


def test_likely_refs_for_nested_test_path_points_outside_test_file(tmp_path):
    diff = tmp_path / "test.diff"
    diff.write_text(
        """diff --git a/merger/repoground/tests/test_example.py b/merger/repoground/tests/test_example.py
--- a/merger/repoground/tests/test_example.py
+++ b/merger/repoground/tests/test_example.py
@@ -1,1 +1,2 @@
 def test_example(): pass
+def test_more(): pass
""",
        encoding="utf-8",
    )

    result = dc.compile_delta_context(diff_path=diff)
    file_item = result["review_context"][0]
    hints = {item["path_hint"] for item in file_item["likely_refs"] if item["kind"] == "implementation_candidate"}

    assert "merger/repoground/tests/test_example.py" not in hints
    assert "merger/repoground/core/example.py" in hints
    assert "example.py" in hints


def test_parse_unified_diff_supports_no_prefix_and_binary_file():
    parsed = dc.parse_unified_diff(
        """diff --git src/a.py src/a.py
--- src/a.py
+++ src/a.py
@@ -1 +1 @@
-old
+new
diff --git assets/logo.png assets/logo.png
Binary files assets/logo.png and assets/logo.png differ
""",
        context_window_lines=0,
    )

    assert parsed["file_count"] == 2
    assert parsed["files"][0]["path"] == "src/a.py"
    assert parsed["files"][0]["hunk_count"] == 1
    assert parsed["files"][1]["path"] == "assets/logo.png"
    assert parsed["files"][1]["hunk_count"] == 0
    assert parsed["files"][1]["binary"] is True



def test_changed_path_signal_queries_are_deduplicated(monkeypatch, tmp_path):
    diff = tmp_path / "dup.diff"
    diff.write_text(
        """diff --git a/src/a.py b/src/a.py
--- a/src/a.py
+++ b/src/a.py
@@ -1 +1 @@
-old
+new
diff --git a/src/a.py b/src/a.py
--- a/src/a.py
+++ b/src/a.py
@@ -3 +3 @@
-old2
+new2
""",
        encoding="utf-8",
    )
    manifest = _write_bundle(tmp_path)
    calls = []

    def fake_symbol_search(bundle_manifest, query, *, k=25, kind=None, path=None):
        calls.append(query)
        return {"status": "available", "hit_count": 0, "hits": []}

    monkeypatch.setattr(dc, "search_symbol_index", fake_symbol_search)
    result = dc.compile_delta_context(diff_path=diff, bundle_manifest=manifest, context_budget_tokens=5000)

    assert result["diff"]["file_count"] == 2
    assert calls.count("src/a.py a.py a") <= 1
    assert len({tuple(call for call in calls)}) == 1

def test_relation_card_scan_is_lazy_and_reports_invalid_rows(tmp_path):
    diff = tmp_path / "change.diff"
    diff.write_text(_sample_diff(), encoding="utf-8")
    manifest = _write_bundle(tmp_path)
    manifest_data = json.loads(manifest.read_text(encoding="utf-8"))
    relation_artifact = next(item for item in manifest_data["artifacts"] if item["role"] == "relation_cards_jsonl")
    relation_path = tmp_path / relation_artifact["path"]
    relation_path.write_text(
        '{not json but mentions merger/repoground/core/example.py}\n'
        + json.dumps(
            {
                "kind": "lenskit.relation_card",
                "source": {"kind": "repo_path", "path": "merger/repoground/core/example.py"},
                "target": {"kind": "repo_path", "path": "merger/repoground/tests/test_example.py"},
                "relation": "imports",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    relation_artifact["bytes"] = relation_path.stat().st_size
    relation_artifact["sha256"] = _sha256(relation_path)
    manifest.write_text(json.dumps(manifest_data), encoding="utf-8")

    result = dc.compile_delta_context(diff_path=diff, bundle_manifest=manifest, context_budget_tokens=5000)

    assert result["signals"]["relation_cards_jsonl"]["status"] == "warn"
    assert result["signals"]["relation_cards_jsonl"]["invalid_row_count"] == 1
    assert any(gap["source"] == "relation_cards_jsonl" and gap["severity"] == "warn" for gap in result["gaps"])
