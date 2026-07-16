"""Bounded read-only RepoBrief call navigation over coherent v1 artifacts."""
import hashlib
import json
from pathlib import Path

import pytest

from merger.lenskit.core import repobrief_access, repobrief_mcp_tools
from merger.lenskit.core.repobrief_access import (
    find_references,
    get_callees,
    get_callers,
)

RUN_ID = "run-1"
CANONICAL_SHA = "a" * 64
TARGET_ID = "py:pkg:target.py:function:target"
OTHER_TARGET_ID = "py:pkg:other_target.py:function:target"
HELPER_ID = "py:pkg:helper.py:function:helper"
CALLER_ONE_ID = "py:pkg:a.py:function:caller_one"
CALLER_TWO_ID = "py:pkg:b.py:function:caller_two"
OTHER_CALLER_ID = "py:pkg:c.py:function:other_caller"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _symbol(
    symbol_id: str,
    *,
    name: str,
    path: str,
    line: int,
    qualified_name: str | None = None,
    kind: str = "function",
    end_line: int | None = None,
) -> dict:
    qualified = qualified_name or name
    module = path.removesuffix(".py").replace("/", ".")
    return {
        "id": symbol_id,
        "kind": kind,
        "name": name,
        "qualified_name": qualified,
        "module": module,
        "path": path,
        "start_line": line,
        "end_line": end_line if end_line is not None else line + 2,
        "range_ref": (
            f"file:{path}#L{line}-L"
            f"{end_line if end_line is not None else line + 2}"
        ),
    }


def _call(
    path: str,
    line: int,
    *,
    caller_id: str,
    caller: str,
    expression: str,
    simple_name: str,
    status: str,
    reason: str,
    target_id: str | None = None,
    candidate_ids: list[str] | None = None,
    relation_type: str = "calls",
    caller_start_line: int = 1,
    caller_end_line: int = 45,
) -> dict:
    return {
        "path": path,
        "start_line": line,
        "start_col": 4,
        "end_line": line,
        "end_col": 18,
        "range_ref": f"file:{path}#L{line}-L{line}",
        "callee_expression": expression,
        "simple_name": simple_name,
        "caller_scope": "symbol",
        "caller_symbol_id": caller_id,
        "caller_qualified_name": caller,
        "caller_kind": "function",
        "caller_start_line": caller_start_line,
        "caller_end_line": caller_end_line,
        "relation_type": relation_type,
        "evidence_level": "S1" if status == "resolved" else "S0",
        "resolution_status": status,
        "resolution_reason": reason,
        "resolved_target_ids": [target_id] if target_id else [],
        "candidate_target_ids": candidate_ids or [],
    }


def _fixture_calls() -> list[dict]:
    return [
        _call(
            "pkg/a.py",
            10,
            caller_id=CALLER_ONE_ID,
            caller="caller_one",
            expression="target",
            simple_name="target",
            status="resolved",
            reason="imported_internal_name",
            target_id=TARGET_ID,
        ),
        _call(
            "pkg/a.py",
            20,
            caller_id=CALLER_ONE_ID,
            caller="caller_one",
            expression="target",
            simple_name="target",
            status="resolved",
            reason="imported_internal_name",
            target_id=TARGET_ID,
        ),
        _call(
            "pkg/a.py",
            30,
            caller_id=CALLER_ONE_ID,
            caller="caller_one",
            expression="helper",
            simple_name="helper",
            status="resolved",
            reason="imported_internal_name",
            target_id=HELPER_ID,
        ),
        _call(
            "pkg/a.py",
            40,
            caller_id=CALLER_ONE_ID,
            caller="caller_one",
            expression="client.send",
            simple_name="send",
            status="unresolved",
            reason="dynamic_attribute_call",
        ),
        _call(
            "pkg/b.py",
            7,
            caller_id=CALLER_TWO_ID,
            caller="caller_two",
            expression="target",
            simple_name="target",
            status="unresolved",
            reason="lexically_shadowed_name",
        ),
        _call(
            "pkg/c.py",
            5,
            caller_id=OTHER_CALLER_ID,
            caller="other_caller",
            expression="target",
            simple_name="target",
            status="resolved",
            reason="imported_internal_name",
            target_id=OTHER_TARGET_ID,
        ),
    ]


def _count(calls: list[dict], field: str, keys: tuple[str, ...]) -> dict[str, int]:
    result = {key: 0 for key in keys}
    for call in calls:
        result[call[field]] += 1
    return result


def _write_bundle(tmp_path: Path) -> tuple[Path, Path, Path]:
    symbols = [
        _symbol(TARGET_ID, name="target", path="pkg/target.py", line=1),
        _symbol(OTHER_TARGET_ID, name="target", path="pkg/other_target.py", line=1),
        _symbol(HELPER_ID, name="helper", path="pkg/helper.py", line=1),
        _symbol(
            CALLER_ONE_ID, name="caller_one", path="pkg/a.py", line=1, end_line=45
        ),
        _symbol(
            CALLER_TWO_ID, name="caller_two", path="pkg/b.py", line=1, end_line=45
        ),
        _symbol(
            OTHER_CALLER_ID, name="other_caller", path="pkg/c.py", line=1, end_line=45
        ),
    ]
    symbol_index = tmp_path / "demo.python_symbol_index.json"
    symbol_index.write_text(
        json.dumps(
            {
                "kind": "lenskit.python_symbol_index",
                "version": "1.0",
                "run_id": RUN_ID,
                "canonical_dump_index_sha256": CANONICAL_SHA,
                "language": "python",
                "symbol_kinds": ["class", "function", "async_function"],
                "symbols": symbols,
                "skipped_files_count": 0,
                "skipped_errors": [],
                "does_not_establish": ["call_graph_completeness"],
            }
        ),
        encoding="utf-8",
    )

    calls = _fixture_calls()
    call_graph = tmp_path / "demo.python_call_graph.json"
    call_graph.write_text(
        json.dumps(
            {
                "kind": "lenskit.python_call_graph",
                "version": "1.0",
                "run_id": RUN_ID,
                "canonical_dump_index_sha256": CANONICAL_SHA,
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
                "call_count": len(calls),
                "resolution_counts": _count(
                    calls,
                    "resolution_status",
                    ("resolved", "candidate", "ambiguous", "unresolved"),
                ),
                "evidence_counts": _count(
                    calls, "evidence_level", ("S0", "S1")
                ),
                "relation_counts": _count(
                    calls, "relation_type", ("calls", "constructs")
                ),
                "calls": calls,
                "skipped_files_count": 0,
                "skipped_errors": [],
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
        ),
        encoding="utf-8",
    )

    manifest = tmp_path / "demo.bundle.manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "kind": "repolens.bundle.manifest",
                "run_id": RUN_ID,
                "artifacts": [
                    {
                        "role": "python_symbol_index_json",
                        "path": symbol_index.name,
                        "content_type": "application/json",
                        "bytes": symbol_index.stat().st_size,
                        "sha256": _sha(symbol_index),
                    },
                    {
                        "role": "python_call_graph_json",
                        "path": call_graph.name,
                        "content_type": "application/json",
                        "bytes": call_graph.stat().st_size,
                        "sha256": _sha(call_graph),
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return manifest, call_graph, symbol_index


def _bundle(tmp_path: Path) -> Path:
    return _write_bundle(tmp_path)[0]


def _refresh_manifest_artifact(manifest: Path, role: str, artifact: Path) -> None:
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    record = next(item for item in payload["artifacts"] if item["role"] == role)
    record["bytes"] = artifact.stat().st_size
    record["sha256"] = _sha(artifact)
    manifest.write_text(json.dumps(payload), encoding="utf-8")


def test_find_references_returns_bounded_s0_and_s1_evidence(tmp_path):
    result = find_references(_bundle(tmp_path), "target", k=2)
    assert result["status"] == "available"
    assert result["total_match_count"] == 4
    assert result["exact_match_count"] == 4
    assert result["hit_count"] == 2
    assert result["truncated"] is True
    assert [hit["start_line"] for hit in result["hits"]] == [10, 20]
    assert all(hit["evidence_level"] == "S1" for hit in result["hits"])
    assert all(hit["relation_type"] == "calls" for hit in result["hits"])
    assert "complete_call_graph" in result["does_not_establish"]


def test_get_callers_fails_closed_when_target_name_is_ambiguous(tmp_path):
    result = get_callers(_bundle(tmp_path), "target", k=10)
    assert result["status"] == "invalid"
    assert result["error_code"] == "symbol_ambiguous"
    assert [item["path"] for item in result["target_candidates"]] == [
        "pkg/other_target.py",
        "pkg/target.py",
    ]
    assert result["callers"] == []


def test_get_callers_uses_target_identity_and_separates_textual_matches(tmp_path):
    result = get_callers(
        _bundle(tmp_path), "target", path="pkg/target.py", k=10
    )
    assert result["status"] == "available"
    assert result["target_symbol"]["id"] == TARGET_ID
    assert result["total_caller_count"] == 1
    assert result["total_call_site_count"] == 2
    assert [caller["caller_qualified_name"] for caller in result["callers"]] == [
        "caller_one"
    ]
    assert result["callers"][0]["call_site_count"] == 2
    assert result["unresolved_reference_count"] == 2
    assert {
        item["relation_to_selected_target"]
        for item in result["unresolved_references"]
    } == {"textual_name_only"}
    assert {item["path"] for item in result["unresolved_references"]} == {
        "pkg/b.py",
        "pkg/c.py",
    }


def test_get_callees_returns_resolved_targets_and_unresolved_sites(tmp_path):
    result = get_callees(
        _bundle(tmp_path), "caller_one", path="pkg/a.py", k=10
    )
    assert result["status"] == "available"
    assert result["caller_symbol"]["id"] == CALLER_ONE_ID
    assert result["total_callee_count"] == 2
    assert result["total_call_site_count"] == 4
    assert [item["callee_symbol"]["id"] for item in result["callees"]] == [
        HELPER_ID,
        TARGET_ID,
    ]
    target = next(
        item for item in result["callees"] if item["callee_symbol"]["id"] == TARGET_ID
    )
    assert target["call_site_count"] == 2
    assert target["relation_types"] == ["calls"]
    assert result["unresolved_call_site_count"] == 1
    assert result["unresolved_call_sites"][0]["callee_expression"] == "client.send"
    assert result["unresolved_call_sites"][0]["evidence_level"] == "S0"


def test_invalid_navigation_payloads_preserve_filters_and_full_shape(tmp_path):
    manifest = _bundle(tmp_path)

    access_result = find_references(manifest, "", path="pkg/a.py")
    wrapped = repobrief_mcp_tools.find_references(
        bundle_manifest=str(manifest), name="", path="pkg/a.py"
    )

    assert access_result["status"] == "invalid"
    assert access_result["filters"] == {"path": "pkg/a.py"}
    assert access_result["hits"] == []
    assert access_result["call_graph"] is None
    assert wrapped["status"] == "invalid"
    assert wrapped["result"] == access_result


@pytest.mark.parametrize("reader", [find_references, get_callers, get_callees])
def test_invalid_navigation_name_fails_before_artifact_io(tmp_path, monkeypatch, reader):
    def fail_if_loaded(_manifest_path):
        raise AssertionError("invalid primitive input must not load the call graph")

    monkeypatch.setattr(repobrief_access, "_load_call_graph", fail_if_loaded)

    result = reader(tmp_path / "missing.bundle.manifest.json", "")

    assert result["status"] == "invalid"
    assert result["error_code"] == "name_invalid"
    assert result["call_graph"] is None


def test_navigation_path_filter_and_invalid_k_fail_closed(tmp_path):
    manifest = _bundle(tmp_path)
    filtered = find_references(manifest, "target", path="pkg/b.py")
    assert [hit["path"] for hit in filtered["hits"]] == ["pkg/b.py"]
    invalid = get_callers(manifest, "target", k=0)
    assert invalid["status"] == "invalid"
    assert invalid["error_code"] == "k_out_of_bounds"
    assert invalid["callers"] == []


def test_navigation_rejects_mismatched_symbol_binding(tmp_path):
    manifest, _, symbol_index = _write_bundle(tmp_path)
    payload = json.loads(symbol_index.read_text(encoding="utf-8"))
    payload["run_id"] = "different-run"
    symbol_index.write_text(json.dumps(payload), encoding="utf-8")
    _refresh_manifest_artifact(manifest, "python_symbol_index_json", symbol_index)

    result = get_callers(
        manifest, "target", path="pkg/target.py", k=10
    )
    assert result["status"] == "invalid"
    assert result["error_code"] == "call_symbol_run_id_mismatch"
    assert result["callers"] == []


def test_navigation_rejects_inconsistent_parse_diagnostic_counts(tmp_path):
    manifest, call_graph, _ = _write_bundle(tmp_path)
    payload = json.loads(call_graph.read_text(encoding="utf-8"))
    payload["skipped_files_count"] = 1
    payload["skipped_errors"] = ["broken.py: SyntaxError"]
    payload["skipped_errors_total_count"] = 2
    payload["skipped_errors_truncated"] = True
    call_graph.write_text(json.dumps(payload), encoding="utf-8")
    _refresh_manifest_artifact(manifest, "python_call_graph_json", call_graph)

    result = find_references(manifest, "target")

    assert result["status"] == "invalid"
    assert result["error_code"] == "python_call_graph_parse_diagnostics_invalid"
    assert result["hits"] == []


def test_legacy_parse_diagnostics_use_one_normalized_metadata_projection(tmp_path):
    manifest, call_graph, _ = _write_bundle(tmp_path)
    payload = json.loads(call_graph.read_text(encoding="utf-8"))
    payload["skipped_files_count"] = 2
    payload["skipped_errors"] = ["broken.py: SyntaxError"]
    payload.pop("skipped_errors_total_count", None)
    payload.pop("skipped_errors_truncated", None)
    call_graph.write_text(json.dumps(payload), encoding="utf-8")
    _refresh_manifest_artifact(manifest, "python_call_graph_json", call_graph)

    result = find_references(manifest, "target")

    assert result["status"] == "available"
    assert result["call_graph_metadata"]["skipped_files_count"] == 2
    assert result["call_graph_metadata"]["skipped_errors_total_count"] == 2
    assert result["call_graph_metadata"]["skipped_errors_truncated"] is True


def test_navigation_rejects_invalid_aggregate_counts(tmp_path):
    manifest, call_graph, _ = _write_bundle(tmp_path)
    payload = json.loads(call_graph.read_text(encoding="utf-8"))
    payload["evidence_counts"]["S1"] += 1
    call_graph.write_text(json.dumps(payload), encoding="utf-8")
    _refresh_manifest_artifact(manifest, "python_call_graph_json", call_graph)

    result = find_references(manifest, "target")
    assert result["status"] == "invalid"
    assert result["error_code"] == "python_call_graph_evidence_counts_mismatch"
    assert result["hits"] == []


def test_mcp_tools_wrap_read_only_results(tmp_path):
    manifest = str(_bundle(tmp_path))
    references = repobrief_mcp_tools.find_references(
        bundle_manifest=manifest, name="target", k=1
    )
    callers = repobrief_mcp_tools.get_callers(
        bundle_manifest=manifest,
        name="target",
        path="pkg/target.py",
        k=10,
    )
    callees = repobrief_mcp_tools.get_callees(
        bundle_manifest=manifest,
        name="caller_one",
        path="pkg/a.py",
        k=10,
    )
    assert references["tool"] == "find_references"
    assert references["result"]["hit_count"] == 1
    assert callers["tool"] == "get_callers"
    assert callers["result"]["total_caller_count"] == 1
    assert callees["tool"] == "get_callees"
    assert callees["result"]["total_callee_count"] == 2
    assert references["mutation_boundary"]["writes"] == []
    assert callees["mutation_boundary"]["writes"] == []


def test_call_navigation_reports_missing_artifact(tmp_path):
    manifest = tmp_path / "empty.bundle.manifest.json"
    manifest.write_text(
        json.dumps(
            {"kind": "repolens.bundle.manifest", "run_id": "x", "artifacts": []}
        ),
        encoding="utf-8",
    )
    result = find_references(manifest, "target")
    assert result["status"] == "missing"
    assert result["error_code"] == "python_call_graph_json_missing"
    assert result["hits"] == []


def test_unrelated_duplicate_symbol_id_does_not_invalidate_target_navigation(tmp_path):
    manifest, _, symbol_index = _write_bundle(tmp_path)
    payload = json.loads(symbol_index.read_text(encoding="utf-8"))
    duplicate = dict(next(item for item in payload["symbols"] if item["id"] == HELPER_ID))
    duplicate["start_line"] = 50
    duplicate["end_line"] = 52
    duplicate["range_ref"] = "file:pkg/helper.py#L50-L52"
    payload["symbols"].append(duplicate)
    symbol_index.write_text(json.dumps(payload), encoding="utf-8")
    _refresh_manifest_artifact(manifest, "python_symbol_index_json", symbol_index)

    result = get_callers(
        manifest, "target", path="pkg/target.py", k=10
    )
    assert result["status"] == "available"
    assert result["target_symbol"]["id"] == TARGET_ID
    assert result["total_caller_count"] == 1


def test_get_callers_keeps_duplicate_definition_ranges_separate(tmp_path):
    manifest, call_graph, symbol_index = _write_bundle(tmp_path)
    symbol_payload = json.loads(symbol_index.read_text(encoding="utf-8"))
    symbol_payload["symbols"].append(
        _symbol(
            CALLER_ONE_ID,
            name="caller_one",
            path="pkg/a.py",
            line=50,
            end_line=60,
        )
    )
    symbol_index.write_text(json.dumps(symbol_payload), encoding="utf-8")
    _refresh_manifest_artifact(manifest, "python_symbol_index_json", symbol_index)

    graph_payload = json.loads(call_graph.read_text(encoding="utf-8"))
    graph_payload["calls"].append(
        _call(
            "pkg/a.py",
            52,
            caller_id=CALLER_ONE_ID,
            caller="caller_one",
            expression="target",
            simple_name="target",
            status="resolved",
            reason="imported_internal_name",
            target_id=TARGET_ID,
            caller_start_line=50,
            caller_end_line=60,
        )
    )
    calls = graph_payload["calls"]
    graph_payload["call_count"] = len(calls)
    graph_payload["resolution_counts"] = _count(
        calls,
        "resolution_status",
        ("resolved", "candidate", "ambiguous", "unresolved"),
    )
    graph_payload["evidence_counts"] = _count(
        calls, "evidence_level", ("S0", "S1")
    )
    graph_payload["relation_counts"] = _count(
        calls, "relation_type", ("calls", "constructs")
    )
    call_graph.write_text(json.dumps(graph_payload), encoding="utf-8")
    _refresh_manifest_artifact(manifest, "python_call_graph_json", call_graph)

    result = get_callers(manifest, "target", path="pkg/target.py", k=10)

    assert result["status"] == "available"
    assert result["total_caller_count"] == 2
    assert result["total_call_site_count"] == 3
    assert [item["caller_symbol"]["start_line"] for item in result["callers"]] == [
        1,
        50,
    ]
    assert [item["call_site_count"] for item in result["callers"]] == [2, 1]


def test_navigation_rejects_call_range_that_disagrees_with_source_fields(tmp_path):
    manifest, call_graph, _ = _write_bundle(tmp_path)
    payload = json.loads(call_graph.read_text(encoding="utf-8"))
    payload["calls"][0]["range_ref"] = "file:pkg/a.py#L999-L999"
    call_graph.write_text(json.dumps(payload), encoding="utf-8")
    _refresh_manifest_artifact(manifest, "python_call_graph_json", call_graph)

    result = find_references(manifest, "target")

    assert result["status"] == "invalid"
    assert result["error_code"] == "python_call_graph_call_record_invalid"
