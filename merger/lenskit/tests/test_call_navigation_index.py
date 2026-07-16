"""Equivalence and source-binding tests for process-local call navigation indexes."""

from __future__ import annotations

import hashlib
import json

import pytest

from merger.lenskit.core.call_navigation_index import (
    CallNavigationIndex,
    SymbolNavigationIndex,
    linear_calls_for_symbol,
    linear_reference_calls,
    linear_target_related_calls,
)


def _call(position: int) -> dict:
    target = position % 31
    caller = position % 47
    status = ("resolved", "candidate", "unresolved")[position % 3]
    target_id = f"py:pkg:t{target}.py:function:target_{target}"
    simple_name = f"target_{target}"
    expression = (
        simple_name
        if position % 5
        else f"registry.handlers.{simple_name}"
    )
    return {
        "path": f"pkg/c{caller}.py",
        "start_line": position // 47 + 1,
        "start_col": position % 13,
        "end_line": position // 47 + 1,
        "end_col": position % 13 + 8,
        "range_ref": f"file:pkg/c{caller}.py#L{position // 47 + 1}-L{position // 47 + 1}",
        "callee_expression": expression,
        "simple_name": simple_name,
        "caller_scope": "symbol",
        "caller_symbol_id": f"py:pkg:c{caller}.py:function:caller_{caller}",
        "caller_qualified_name": f"caller_{caller}",
        "caller_kind": "function",
        "caller_start_line": 1,
        "caller_end_line": 100,
        "relation_type": "calls",
        "evidence_level": "S1" if status == "resolved" else "S0",
        "resolution_status": status,
        "resolution_reason": f"fixture_{status}",
        "resolved_target_ids": [target_id] if status == "resolved" else [],
        "candidate_target_ids": [target_id] if status == "candidate" else [],
    }


def _symbol(caller: int) -> dict:
    return {
        "id": f"py:pkg:c{caller}.py:function:caller_{caller}",
        "kind": "function",
        "name": f"caller_{caller}",
        "qualified_name": f"caller_{caller}",
        "module": f"pkg.c{caller}",
        "path": f"pkg/c{caller}.py",
        "start_line": 1,
        "end_line": 100,
        "range_ref": f"file:pkg/c{caller}.py#L1-L100",
    }


def test_indexed_reference_search_is_order_equivalent_for_exact_substring_and_short_queries():
    calls = [_call(position) for position in range(2500)]
    calls.reverse()  # Prove ordering does not depend on canonical producer order.
    index = CallNavigationIndex.build(calls)

    for query in ("target_7", "handlers", "get", "tar", "missing"):
        assert index.reference_calls(query) == linear_reference_calls(calls, query)


def test_indexed_target_and_caller_navigation_are_row_equivalent():
    calls = [_call(position) for position in range(2500)]
    index = CallNavigationIndex.build(calls)
    target_id = "py:pkg:t11.py:function:target_11"
    query = "target_11"
    symbol = _symbol(19)

    assert index.target_related_calls(target_id, query) == linear_target_related_calls(
        calls, target_id, query
    )
    assert index.calls_for_symbol(symbol) == linear_calls_for_symbol(calls, symbol)


def test_symbol_index_preserves_exact_selection_and_duplicate_order():
    symbols = [_symbol(3), _symbol(1), _symbol(2)]
    duplicate = dict(_symbol(1))
    duplicate["path"] = "other/c1.py"
    duplicate["module"] = "other.c1"
    symbols.append(duplicate)
    index = SymbolNavigationIndex.build(symbols)

    assert [row["path"] for row in index.select("caller_1", None)] == [
        "other/c1.py",
        "pkg/c1.py",
    ]
    assert [row["path"] for row in index.select("caller_1", "pkg/")] == [
        "pkg/c1.py"
    ]
    assert index.select("missing", None) == []


def test_index_postings_are_immutable_and_retain_source_row_identity():
    calls = [_call(0), _call(1)]
    index = CallNavigationIndex.build(calls)

    assert index.calls[0] is calls[0]
    with pytest.raises(TypeError):
        index.simple_name_positions["new"] = (0,)  # type: ignore[index]


def test_persisted_candidate_reconstructs_equivalent_index_and_rejects_wrong_source():
    calls = [_call(position) for position in range(500)]
    source_bytes = json.dumps(calls, sort_keys=True, separators=(",", ":")).encode()
    source_sha = hashlib.sha256(source_bytes).hexdigest()
    original = CallNavigationIndex.build(calls)
    projection = original.persisted_projection(source_sha)

    restored = CallNavigationIndex.from_persisted_projection(
        calls, projection, source_sha
    )

    assert restored.reference_calls("target_7") == original.reference_calls("target_7")
    assert restored.target_related_calls(
        "py:pkg:t7.py:function:target_7", "target_7"
    ) == original.target_related_calls(
        "py:pkg:t7.py:function:target_7", "target_7"
    )
    with pytest.raises(ValueError, match="source binding mismatch"):
        CallNavigationIndex.from_persisted_projection(calls, projection, "0" * 64)


def test_persisted_candidate_is_deterministic_and_source_hash_bound():
    calls = [_call(position) for position in range(200)]
    index = CallNavigationIndex.build(calls)
    source_bytes = json.dumps(calls, sort_keys=True, separators=(",", ":")).encode()
    source_sha = hashlib.sha256(source_bytes).hexdigest()

    first = json.dumps(
        index.persisted_projection(source_sha), sort_keys=True, separators=(",", ":")
    ).encode()
    second = json.dumps(
        index.persisted_projection(source_sha), sort_keys=True, separators=(",", ":")
    ).encode()

    assert first == second
    payload = json.loads(first)
    assert payload["source_calls_sha256"] == source_sha
    assert payload["source_call_count"] == len(calls)
    assert payload["kind"] == "lenskit.python_call_navigation_index"
