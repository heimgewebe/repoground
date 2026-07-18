"""Bounded read-only RepoBrief call navigation over coherent v1 artifacts."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path

import pytest

from merger.repoground.core import bundle_access, mcp_tools
from merger.repoground.core.bundle_access import (
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


@pytest.fixture(autouse=True)
def _reset_call_navigation_caches():
    bundle_access._clear_call_navigation_caches()
    bundle_access._WARNED_INVALID_CACHE_VALIDATION_VALUES.clear()
    yield
    bundle_access._clear_call_navigation_caches()
    bundle_access._WARNED_INVALID_CACHE_VALIDATION_VALUES.clear()


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


def test_navigation_cache_reuses_validated_call_state(tmp_path, monkeypatch):
    manifest = _bundle(tmp_path)
    original = bundle_access._load_call_graph_source
    calls = 0

    def counted(manifest_path):
        nonlocal calls
        calls += 1
        return original(manifest_path)

    monkeypatch.setattr(bundle_access, "_load_call_graph_source", counted)

    cold = find_references(manifest, "target", k=10)
    warm = find_references(manifest, "target", k=10)

    assert cold == warm
    assert calls == 1
    assert len(bundle_access._CALL_NAVIGATION_CACHE) == 1


def test_public_navigation_results_cannot_mutate_cached_state(tmp_path):
    manifest, _, symbol_index = _write_bundle(tmp_path)
    symbol_payload = json.loads(symbol_index.read_text(encoding="utf-8"))
    target = next(item for item in symbol_payload["symbols"] if item["id"] == TARGET_ID)
    target["decorators"] = ["registered"]
    symbol_index.write_text(json.dumps(symbol_payload), encoding="utf-8")
    _refresh_manifest_artifact(manifest, "python_symbol_index_json", symbol_index)

    first = get_callers(manifest, "target", path="pkg/target.py", k=10)
    expected = json.loads(json.dumps(first))

    first["target_symbol"]["decorators"].append("mutated")
    first["call_graph"]["sha256"] = "mutated"
    first["symbol_index"]["sha256"] = "mutated"
    first["call_graph_metadata"]["resolution_counts"]["resolved"] = 0
    first["callers"][0]["call_sites"][0]["resolved_target_ids"].clear()
    first["unresolved_references"][0]["candidate_target_ids"].append("mutated")

    second = get_callers(manifest, "target", path="pkg/target.py", k=10)

    assert second == expected

def test_call_graph_content_must_match_manifest_hash(tmp_path):
    manifest, call_graph, _ = _write_bundle(tmp_path)
    assert find_references(manifest, "target")["status"] == "available"
    bundle_access._clear_call_navigation_caches()

    payload = json.loads(call_graph.read_text(encoding="utf-8"))
    payload["calls"][0]["simple_name"] = "tampered"
    call_graph.write_text(json.dumps(payload), encoding="utf-8")

    result = find_references(manifest, "target")

    assert result["status"] == "invalid"
    assert result["error_code"] in {
        "python_call_graph_json_bytes_mismatch",
        "python_call_graph_json_sha256_mismatch",
    }


def test_symbol_index_content_must_match_manifest_hash(tmp_path):
    manifest, _, symbol_index = _write_bundle(tmp_path)
    assert get_callers(
        manifest, "target", path="pkg/target.py"
    )["status"] == "available"
    bundle_access._clear_call_navigation_caches()

    payload = json.loads(symbol_index.read_text(encoding="utf-8"))
    payload["symbols"][0]["name"] = "tampered"
    symbol_index.write_text(json.dumps(payload), encoding="utf-8")

    result = get_callers(manifest, "target", path="pkg/target.py")

    assert result["status"] == "invalid"
    assert result["error_code"] in {
        "python_symbol_index_json_bytes_mismatch",
        "python_symbol_index_json_sha256_mismatch",
    }


def test_cache_detects_same_size_change_with_restored_mtime(tmp_path):
    manifest, call_graph, _ = _write_bundle(tmp_path)
    assert find_references(manifest, "target")["status"] == "available"
    before = call_graph.stat()
    raw = call_graph.read_bytes()
    tampered = raw.replace(b"target", b"tamper", 1)
    assert len(tampered) == len(raw)

    call_graph.write_bytes(tampered)
    os.utime(call_graph, ns=(before.st_atime_ns, before.st_mtime_ns))
    after = call_graph.stat()
    assert after.st_size == before.st_size
    assert after.st_mtime_ns == before.st_mtime_ns
    assert after.st_ctime_ns != before.st_ctime_ns

    result = find_references(manifest, "target")

    assert result["status"] == "invalid"
    assert result["error_code"] == "python_call_graph_json_sha256_mismatch"


def test_call_graph_change_invalidates_cached_navigation_state(tmp_path, monkeypatch):
    manifest, call_graph, _ = _write_bundle(tmp_path)
    original = bundle_access._load_call_graph_source
    loads = 0

    def counted(manifest_path):
        nonlocal loads
        loads += 1
        return original(manifest_path)

    monkeypatch.setattr(bundle_access, "_load_call_graph_source", counted)
    before = find_references(manifest, "target", k=10)

    payload = json.loads(call_graph.read_text(encoding="utf-8"))
    payload["calls"][0]["simple_name"] = "renamed"
    payload["calls"][0]["callee_expression"] = "renamed"
    call_graph.write_text(json.dumps(payload), encoding="utf-8")
    _refresh_manifest_artifact(manifest, "python_call_graph_json", call_graph)

    after = find_references(manifest, "target", k=10)

    assert before["total_match_count"] == 4
    assert after["total_match_count"] == 3
    assert loads == 2


def test_symbol_change_invalidates_cached_symbol_state(tmp_path, monkeypatch):
    manifest, _, symbol_index = _write_bundle(tmp_path)
    original = bundle_access._load_symbol_index_source
    loads = 0

    def counted(manifest_path):
        nonlocal loads
        loads += 1
        return original(manifest_path)

    monkeypatch.setattr(bundle_access, "_load_symbol_index_source", counted)
    before = get_callers(manifest, "target", path="pkg/target.py", k=10)

    payload = json.loads(symbol_index.read_text(encoding="utf-8"))
    payload["symbols"][0]["name"] = "renamed"
    payload["symbols"][0]["qualified_name"] = "renamed"
    symbol_index.write_text(json.dumps(payload), encoding="utf-8")
    _refresh_manifest_artifact(manifest, "python_symbol_index_json", symbol_index)

    after = get_callers(manifest, "target", path="pkg/target.py", k=10)

    assert before["status"] == "available"
    assert after["status"] == "missing"
    assert after["error_code"] == "symbol_not_found"
    assert loads == 2


def test_stale_call_generation_is_evicted_with_dependent_symbol_state(tmp_path):
    manifest, call_graph, _ = _write_bundle(tmp_path)
    assert get_callers(
        manifest, "target", path="pkg/target.py", k=10
    )["status"] == "available"
    stale_call_fingerprint = next(iter(bundle_access._CALL_NAVIGATION_CACHE))
    assert any(
        cache_key[0] == stale_call_fingerprint
        for cache_key in bundle_access._SYMBOL_NAVIGATION_CACHE
    )

    payload = json.loads(call_graph.read_text(encoding="utf-8"))
    payload["calls"][0]["simple_name"] = "renamed"
    payload["calls"][0]["callee_expression"] = "renamed"
    call_graph.write_text(json.dumps(payload), encoding="utf-8")
    _refresh_manifest_artifact(manifest, "python_call_graph_json", call_graph)

    result = get_callers(manifest, "target", path="pkg/target.py", k=10)

    assert result["status"] == "available"
    assert stale_call_fingerprint not in bundle_access._CALL_NAVIGATION_CACHE
    assert not any(
        cache_key[0] == stale_call_fingerprint
        for cache_key in bundle_access._SYMBOL_NAVIGATION_CACHE
    )
    assert len(bundle_access._CALL_NAVIGATION_CACHE) == 1
    assert len(bundle_access._SYMBOL_NAVIGATION_CACHE) == 1


def test_stale_symbol_generation_is_evicted_before_replacement(tmp_path):
    manifest, _, symbol_index = _write_bundle(tmp_path)
    assert get_callers(
        manifest, "target", path="pkg/target.py", k=10
    )["status"] == "available"
    stale_symbol_key = next(iter(bundle_access._SYMBOL_NAVIGATION_CACHE))

    payload = json.loads(symbol_index.read_text(encoding="utf-8"))
    target = next(item for item in payload["symbols"] if item["id"] == TARGET_ID)
    target["decorators"] = ["updated"]
    symbol_index.write_text(json.dumps(payload), encoding="utf-8")
    _refresh_manifest_artifact(manifest, "python_symbol_index_json", symbol_index)

    result = get_callers(manifest, "target", path="pkg/target.py", k=10)

    assert result["status"] == "available"
    assert stale_symbol_key not in bundle_access._SYMBOL_NAVIGATION_CACHE
    assert len(bundle_access._SYMBOL_NAVIGATION_CACHE) == 1


def test_cold_and_warm_navigation_results_are_byte_equivalent(tmp_path):
    manifest = _bundle(tmp_path)
    queries = (
        (find_references, (manifest, "target"), {"k": 3}),
        (
            get_callers,
            (manifest, "target"),
            {"path": "pkg/target.py", "k": 3},
        ),
        (
            get_callees,
            (manifest, "caller_one"),
            {"path": "pkg/a.py", "k": 3},
        ),
    )

    for reader, args, kwargs in queries:
        bundle_access._clear_call_navigation_caches()
        cold = json.dumps(reader(*args, **kwargs), sort_keys=True, separators=(",", ":"))
        warm = json.dumps(reader(*args, **kwargs), sort_keys=True, separators=(",", ":"))
        assert cold == warm


def test_navigation_cache_is_lru_bounded(tmp_path):
    manifests = []
    for index in range(bundle_access._CALL_NAVIGATION_CACHE_MAX_ENTRIES + 1):
        bundle_dir = tmp_path / f"bundle-{index}"
        bundle_dir.mkdir()
        manifest = _bundle(bundle_dir)
        manifests.append(str(manifest.resolve()))
        assert get_callers(manifest, "target", path="pkg/target.py")["status"] == "available"

    assert len(bundle_access._CALL_NAVIGATION_CACHE) == 2
    assert not any(k.manifest_path == manifests[0] for k in bundle_access._CALL_NAVIGATION_CACHE)
    assert not any(
        key[0].manifest_path == manifests[0]
        for key in bundle_access._SYMBOL_NAVIGATION_CACHE
    )
    assert any(k.manifest_path == manifests[-1] for k in bundle_access._CALL_NAVIGATION_CACHE)


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
    manifest = _bundle(tmp_path)
    result = get_callers(manifest, "target", k=10)
    expected = json.loads(json.dumps(result))

    assert result["status"] == "invalid"
    assert result["error_code"] == "symbol_ambiguous"
    assert [item["path"] for item in result["target_candidates"]] == [
        "pkg/other_target.py",
        "pkg/target.py",
    ]
    assert result["callers"] == []

    result["symbol_index"]["sha256"] = "mutated"
    result["target_candidates"][0]["decorators"].append("mutated")

    assert get_callers(manifest, "target", k=10) == expected


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
    wrapped = mcp_tools.find_references(
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

    monkeypatch.setattr(bundle_access, "_load_call_graph_source", fail_if_loaded)

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
    references = mcp_tools.find_references(
        bundle_manifest=manifest, name="target", k=1
    )
    callers = mcp_tools.get_callers(
        bundle_manifest=manifest,
        name="target",
        path="pkg/target.py",
        k=10,
    )
    callees = mcp_tools.get_callees(
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

def test_call_graph_change_during_index_build_fails_closed(tmp_path, monkeypatch):
    manifest, call_graph, _ = _write_bundle(tmp_path)
    from merger.repoground.core.call_navigation_index import CallNavigationIndex

    original_build = CallNavigationIndex.build

    def tampered_build(calls):
        payload = json.loads(call_graph.read_text(encoding="utf-8"))
        payload["calls"][0]["simple_name"] = "tampered"
        call_graph.write_text(json.dumps(payload), encoding="utf-8")
        return original_build(calls)

    monkeypatch.setattr(CallNavigationIndex, "build", tampered_build)

    result = find_references(manifest, "target")
    assert result["status"] == "invalid"
    assert result["error_code"] == "python_call_graph_source_changed_during_load"


def test_symbol_index_change_during_index_build_fails_closed(tmp_path, monkeypatch):
    manifest, _, symbol_index = _write_bundle(tmp_path)
    from merger.repoground.core.call_navigation_index import SymbolNavigationIndex

    original_build = SymbolNavigationIndex.build

    def tampered_build(symbols):
        payload = json.loads(symbol_index.read_text(encoding="utf-8"))
        payload["symbols"][0]["name"] = "tampered"
        symbol_index.write_text(json.dumps(payload), encoding="utf-8")
        return original_build(symbols)

    monkeypatch.setattr(SymbolNavigationIndex, "build", tampered_build)

    result = get_callers(manifest, "target", path="pkg/target.py")
    assert result["status"] == "invalid"
    assert result["error_code"] == "python_symbol_index_source_changed_during_load"


def test_call_graph_change_during_symbol_index_build_fails_closed(
    tmp_path, monkeypatch
):
    manifest, call_graph, _ = _write_bundle(tmp_path)
    from merger.repoground.core.call_navigation_index import SymbolNavigationIndex

    original_build = SymbolNavigationIndex.build

    def tampered_build(symbols):
        payload = json.loads(call_graph.read_text(encoding="utf-8"))
        payload["calls"][0]["simple_name"] = "tampered"
        call_graph.write_text(json.dumps(payload), encoding="utf-8")
        return original_build(symbols)

    monkeypatch.setattr(SymbolNavigationIndex, "build", tampered_build)

    result = get_callers(manifest, "target", path="pkg/target.py")
    assert result["status"] == "invalid"
    assert result["error_code"] == "python_call_graph_source_changed_during_load"


def test_warm_navigation_cache_does_not_reload_artifact_json(tmp_path, monkeypatch):
    manifest = _bundle(tmp_path)
    assert get_callers(manifest, "target", path="pkg/target.py")["status"] == "available"

    def forbidden_source_load(*_args, **_kwargs):
        raise AssertionError("warm navigation cache must not reload artifact JSON")

    monkeypatch.setattr(
        bundle_access, "_read_registered_artifact_source", forbidden_source_load
    )

    assert find_references(manifest, "target")["status"] == "available"
    assert get_callers(manifest, "target", path="pkg/target.py")["status"] == "available"


def test_call_graph_loader_swap_fails_closed_even_when_original_is_restored(
    tmp_path, monkeypatch
):
    manifest, call_graph, _ = _write_bundle(tmp_path)
    original_graph = call_graph.read_bytes()
    original_manifest = manifest.read_bytes()
    alternate_payload = json.loads(original_graph)
    alternate_payload["calls"][0]["simple_name"] = "renamed"
    alternate_payload["calls"][0]["callee_expression"] = "renamed"
    alternate_graph = json.dumps(alternate_payload).encode("utf-8")
    alternate_manifest = json.loads(original_manifest)
    record = next(
        item
        for item in alternate_manifest["artifacts"]
        if item["role"] == "python_call_graph_json"
    )
    record["bytes"] = len(alternate_graph)
    record["sha256"] = hashlib.sha256(alternate_graph).hexdigest()
    alternate_manifest_bytes = json.dumps(alternate_manifest).encode("utf-8")
    original_loader = bundle_access._load_call_graph_source

    def swapped_loader(manifest_path):
        call_graph.write_bytes(alternate_graph)
        manifest.write_bytes(alternate_manifest_bytes)
        loaded = original_loader(manifest_path)
        call_graph.write_bytes(original_graph)
        manifest.write_bytes(original_manifest)
        return loaded

    monkeypatch.setattr(bundle_access, "_load_call_graph_source", swapped_loader)

    result = find_references(manifest, "target")

    assert result["status"] == "invalid"
    assert result["error_code"] == "python_call_graph_source_changed_during_load"


def test_navigation_uses_actual_hash_when_manifest_omits_bytes_and_sha256(tmp_path):
    manifest, call_graph, _ = _write_bundle(tmp_path)
    manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
    for artifact in manifest_payload["artifacts"]:
        artifact.pop("bytes", None)
        artifact.pop("sha256", None)
    manifest.write_text(json.dumps(manifest_payload), encoding="utf-8")

    before = find_references(manifest, "target")
    before_callers = get_callers(manifest, "target", path="pkg/target.py")
    payload = json.loads(call_graph.read_text(encoding="utf-8"))
    payload["calls"][0]["simple_name"] = "renamed"
    payload["calls"][0]["callee_expression"] = "renamed"
    call_graph.write_text(json.dumps(payload), encoding="utf-8")
    after = find_references(manifest, "target")
    after_callers = get_callers(manifest, "target", path="pkg/target.py")

    assert before["status"] == "available"
    assert before_callers["status"] == "available"
    assert before["total_match_count"] == 4
    assert after["status"] == "available"
    assert after["total_match_count"] == 3
    assert after_callers["status"] == "available"
    assert len(bundle_access._CALL_NAVIGATION_CACHE) == 1
    assert {
        key.artifact_sha256 for key in bundle_access._CALL_NAVIGATION_CACHE
    } == {_sha(call_graph)}


def test_parallel_navigation_is_isolated_for_same_and_different_bundles(tmp_path):
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    first_dir.mkdir()
    second_dir.mkdir()
    first = _bundle(first_dir)
    second = _bundle(second_dir)
    manifests = [first, first, second, second] * 4

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(
            executor.map(
                lambda item: get_callers(
                    item, "target", path="pkg/target.py", k=10
                ),
                manifests,
            )
        )

    assert all(result["status"] == "available" for result in results)
    assert all(result["total_caller_count"] == 1 for result in results)
    assert {
        key.manifest_path for key in bundle_access._CALL_NAVIGATION_CACHE
    } == {str(first.resolve()), str(second.resolve())}


def test_warm_navigation_fast_path_does_not_reread_call_graph_bytes(
    tmp_path, monkeypatch
):
    manifest, call_graph, _ = _write_bundle(tmp_path)
    assert get_callers(manifest, "target", path="pkg/target.py")["status"] == "available"

    def forbidden_stable_read(path):
        raise AssertionError(f"default warm cache hit must not read bytes: {path}")

    monkeypatch.delenv("LENSKIT_REPOBRIEF_CACHE_VALIDATION", raising=False)
    monkeypatch.delenv("LENSKIT_REPOBRIEF_STRICT_CACHE_HASH", raising=False)
    monkeypatch.setattr(
        bundle_access,
        "_read_stable_regular_file_bytes",
        forbidden_stable_read,
    )
    monkeypatch.setattr(
        bundle_access,
        "_read_stable_artifact_bytes",
        forbidden_stable_read,
    )

    result = get_callers(manifest, "target", path="pkg/target.py")
    assert result["status"] == "available"


def test_descriptor_pinned_read_rejects_atomic_path_replacement(
    tmp_path, monkeypatch
):
    artifact = tmp_path / "artifact.json"
    replacement = tmp_path / "replacement.json"
    artifact.write_bytes(b"original")
    replacement.write_bytes(b"replaced")
    original_stat = Path.stat
    replaced = False

    def replacing_stat(path, *args, **kwargs):
        nonlocal replaced
        if path == artifact and not replaced:
            replaced = True
            os.replace(replacement, artifact)
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", replacing_stat)

    raw, stat_result, failure, _detail = (
        bundle_access._read_stable_artifact_bytes(artifact)
    )

    assert replaced is True
    assert raw is None
    assert stat_result is None
    assert failure == "source_changed"


def test_strict_navigation_cache_hash_uses_descriptor_pinned_read(
    tmp_path, monkeypatch
):
    manifest, call_graph, _ = _write_bundle(tmp_path)
    assert get_callers(manifest, "target", path="pkg/target.py")["status"] == "available"

    original_reader = bundle_access._read_stable_artifact_bytes
    call_graph_path = call_graph.resolve()
    call_graph_reads = 0

    def counting_reader(path):
        nonlocal call_graph_reads
        if path.resolve() == call_graph_path:
            call_graph_reads += 1
        return original_reader(path)

    monkeypatch.setenv("LENSKIT_REPOBRIEF_CACHE_VALIDATION", "strict")
    monkeypatch.setattr(
        bundle_access, "_read_stable_artifact_bytes", counting_reader
    )

    result = get_callers(manifest, "target", path="pkg/target.py")
    assert result["status"] == "available"
    assert call_graph_reads >= 1


def test_invalid_cache_validation_mode_falls_back_to_strict(
    tmp_path, monkeypatch, caplog
):
    manifest, call_graph, _ = _write_bundle(tmp_path)
    assert get_callers(manifest, "target", path="pkg/target.py")["status"] == "available"

    original_reader = bundle_access._read_stable_artifact_bytes
    call_graph_path = call_graph.resolve()
    call_graph_reads = 0

    def counting_reader(path):
        nonlocal call_graph_reads
        if path.resolve() == call_graph_path:
            call_graph_reads += 1
        return original_reader(path)

    monkeypatch.setenv("LENSKIT_REPOBRIEF_CACHE_VALIDATION", "typo")
    monkeypatch.setattr(
        bundle_access, "_read_stable_artifact_bytes", counting_reader
    )

    caplog.set_level("WARNING")
    result = get_callers(manifest, "target", path="pkg/target.py")
    result_again = get_callers(manifest, "target", path="pkg/target.py")
    assert result["status"] == "available"
    assert result_again["status"] == "available"
    assert call_graph_reads >= 1
    warnings = [
        record
        for record in caplog.records
        if "LENSKIT_REPOBRIEF_CACHE_VALIDATION" in record.getMessage()
        and "typo" in record.getMessage()
    ]
    assert len(warnings) == 1


def test_weak_file_identity_automatically_uses_content_hash(
    tmp_path, monkeypatch
):
    manifest, call_graph, _ = _write_bundle(tmp_path)
    original_reader = bundle_access._read_stable_artifact_bytes
    call_graph_path = call_graph.resolve()
    call_graph_reads = 0

    class WeakStat:
        def __init__(self, source):
            self._source = source
            self.st_dev = 0
            self.st_ino = 0
            self.st_size = source.st_size
            self.st_mtime_ns = source.st_mtime_ns
            self.st_ctime_ns = source.st_ctime_ns

        def __getattr__(self, name):
            return getattr(self._source, name)

    original_fstat = os.fstat
    original_path_stat = Path.stat

    def weak_fstat(descriptor):
        return WeakStat(original_fstat(descriptor))

    def weak_path_stat(path, *args, **kwargs):
        return WeakStat(original_path_stat(path, *args, **kwargs))

    def weak_identity_reader(path):
        nonlocal call_graph_reads
        raw, stat_result, failure, detail = original_reader(path)
        if path.resolve() == call_graph_path and stat_result is not None:
            call_graph_reads += 1
        return raw, stat_result, failure, detail

    monkeypatch.delenv("LENSKIT_REPOBRIEF_CACHE_VALIDATION", raising=False)
    monkeypatch.delenv("LENSKIT_REPOBRIEF_STRICT_CACHE_HASH", raising=False)
    monkeypatch.setattr(os, "fstat", weak_fstat)
    monkeypatch.setattr(Path, "stat", weak_path_stat)
    monkeypatch.setattr(
        bundle_access,
        "_read_stable_artifact_bytes",
        weak_identity_reader,
    )

    result = get_callers(manifest, "target", path="pkg/target.py")
    assert result["status"] == "available"
    reads_after_cold_load = call_graph_reads
    assert reads_after_cold_load >= 2

    result = get_callers(manifest, "target", path="pkg/target.py")
    assert result["status"] == "available"
    assert call_graph_reads > reads_after_cold_load


def test_weak_manifest_identity_automatically_uses_content_hash(
    tmp_path, monkeypatch
):
    manifest, _, _ = _write_bundle(tmp_path)
    original_reader = bundle_access._read_stable_regular_file_bytes
    manifest_path = manifest.resolve()
    manifest_reads = 0

    class WeakStat:
        def __init__(self, source):
            self.st_dev = 0
            self.st_ino = 0
            self.st_size = source.st_size
            self.st_mtime_ns = source.st_mtime_ns
            self.st_ctime_ns = source.st_ctime_ns

    def weak_manifest_reader(path):
        nonlocal manifest_reads
        raw, stat_result, failure, detail = original_reader(path)
        if path.resolve() == manifest_path and stat_result is not None:
            manifest_reads += 1
            stat_result = WeakStat(stat_result)
        return raw, stat_result, failure, detail

    monkeypatch.delenv("LENSKIT_REPOBRIEF_CACHE_VALIDATION", raising=False)
    monkeypatch.delenv("LENSKIT_REPOBRIEF_STRICT_CACHE_HASH", raising=False)
    monkeypatch.setattr(
        bundle_access,
        "_read_stable_regular_file_bytes",
        weak_manifest_reader,
    )

    result = get_callers(manifest, "target", path="pkg/target.py")
    assert result["status"] == "available"
    reads_after_cold_load = manifest_reads
    assert reads_after_cold_load >= 2

    result = get_callers(manifest, "target", path="pkg/target.py")
    assert result["status"] == "available"
    assert manifest_reads > reads_after_cold_load


def test_strict_warm_validation_rejects_tampered_bytes_with_same_identity(
    tmp_path, monkeypatch
):
    manifest, call_graph, _ = _write_bundle(tmp_path)
    assert get_callers(manifest, "target", path="pkg/target.py")["status"] == "available"

    fingerprint = next(
        key
        for key in bundle_access._CALL_NAVIGATION_CACHE
        if key.absolute_path == str(call_graph.resolve())
    )
    original_reader = bundle_access._read_stable_artifact_bytes

    def tampered_reader(path):
        raw, stat_result, failure, detail = original_reader(path)
        if path.resolve() != call_graph.resolve() or raw is None:
            return raw, stat_result, failure, detail
        tampered = bytearray(raw)
        tampered[-2] = ord(" ") if tampered[-2] != ord(" ") else ord("\t")
        return bytes(tampered), stat_result, failure, detail

    monkeypatch.setattr(
        bundle_access,
        "_read_stable_artifact_bytes",
        tampered_reader,
    )

    assert not bundle_access._artifact_source_is_current(
        fingerprint,
        verify_content=True,
    )


def test_atomic_pathname_exchange_during_stable_read_is_rejected(tmp_path, monkeypatch):
    artifact = tmp_path / "artifact.json"
    replacement = tmp_path / "replacement.json"
    artifact.write_text('{"version": 1}\n', encoding="utf-8")
    replacement.write_text('{"version": 2}\n', encoding="utf-8")
    original_open = Path.open
    replaced = False

    def replacing_open(path, *args, **kwargs):
        nonlocal replaced
        handle = original_open(path, *args, **kwargs)
        if Path(path).resolve() == artifact.resolve() and not replaced:
            os.replace(replacement, artifact)
            replaced = True
        return handle

    monkeypatch.setattr(Path, "open", replacing_open)

    raw, stat_result, failure, detail = bundle_access._read_stable_artifact_bytes(
        artifact
    )

    assert raw is None
    assert stat_result is None
    assert failure == "source_changed"
    assert detail is None


def test_manifest_change_during_full_verification_is_rejected(tmp_path, monkeypatch):
    manifest, call_graph, _ = _write_bundle(tmp_path)
    assert find_references(manifest, "target")["status"] == "available"
    fingerprint = next(iter(bundle_access._CALL_NAVIGATION_CACHE))
    original_reader = bundle_access._read_stable_artifact_bytes
    changed = False

    def mutating_artifact_reader(path):
        nonlocal changed
        result = original_reader(path)
        if path.resolve() == call_graph.resolve() and not changed:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            payload["run_id"] = "changed-during-verification"
            manifest.write_text(json.dumps(payload), encoding="utf-8")
            changed = True
        return result

    monkeypatch.setenv("LENSKIT_REPOBRIEF_CACHE_VALIDATION", "strict")
    monkeypatch.setattr(
        bundle_access,
        "_read_stable_artifact_bytes",
        mutating_artifact_reader,
    )

    assert not bundle_access._artifact_source_is_current(fingerprint)


def test_legacy_strict_hash_switch_remains_supported(tmp_path, monkeypatch):
    manifest, call_graph, _ = _write_bundle(tmp_path)
    assert get_callers(manifest, "target", path="pkg/target.py")["status"] == "available"

    original_reader = bundle_access._read_stable_artifact_bytes
    call_graph_path = call_graph.resolve()
    call_graph_reads = 0

    def counting_reader(path):
        nonlocal call_graph_reads
        if path.resolve() == call_graph_path:
            call_graph_reads += 1
        return original_reader(path)

    monkeypatch.delenv("LENSKIT_REPOBRIEF_CACHE_VALIDATION", raising=False)
    monkeypatch.setenv("LENSKIT_REPOBRIEF_STRICT_CACHE_HASH", "1")
    monkeypatch.setattr(
        bundle_access,
        "_read_stable_artifact_bytes",
        counting_reader,
    )

    result = get_callers(manifest, "target", path="pkg/target.py")
    assert result["status"] == "available"
    assert call_graph_reads >= 1
