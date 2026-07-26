"""python_call_graph v1 producer: deterministic AST call sites, safe resolution only.

The fixed utility goldset below is shared with the call-navigation tests. It
covers every safe resolution rule (local module function, imported internal
name, module alias, self/cls method, direct recursion) plus the conservative
outcomes (ambiguous, dynamic, foreign, module scope, parse errors).
"""

import ast
import json
from pathlib import Path

import jsonschema
import pytest

from merger.repoground.architecture.call_graph import (
    DOES_NOT_ESTABLISH,
    MAX_SKIPPED_ERRORS,
    _CallGraphVisitor,
    _Resolver,
    extract_python_calls,
    generate_call_graph_document,
)
from merger.repoground.core.bundle_access import _call_record_is_valid

GOLDSET_TEXT_PY = """import os.path
import utilkit.numbers as num
from utilkit.numbers import double
from external_lib import shim


def slugify(value):
    return normalize(value)


def normalize(value):
    return value.strip()


def walk(node):
    if node:
        walk(node)
    return double(node) + num.triple(node) + os.path.join("a", "b") + shim(node)


class Formatter:
    def format(self, value):
        return self.indent(value)

    def indent(self, value):
        return self.missing(value)

    @classmethod
    def build(cls):
        return cls.default()

    @classmethod
    def default(cls):
        return Formatter()


TOP = slugify("Hi")
"""

GOLDSET_NUMBERS_PY = """def double(x):
    return x * 2


def triple(x):
    return x * 3


if True:
    def cond(x):
        return x
else:
    def cond(x):
        return -x


def use_cond(x):
    return cond(x)


def use_double(x):
    return double(double(x))
"""


def write_utility_goldset(root: Path) -> Path:
    """Write the fixed small utility goldset used by producer and access tests."""
    package = root / "utilkit"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "text.py").write_text(GOLDSET_TEXT_PY, encoding="utf-8")
    (package / "numbers.py").write_text(GOLDSET_NUMBERS_PY, encoding="utf-8")
    (package / "broken.py").write_text("def broken(:\n", encoding="utf-8")
    return root


def _calls_by_expression(calls: list[dict], expression: str) -> list[dict]:
    return [call for call in calls if call["callee_expression"] == expression]


def _single_call(calls: list[dict], expression: str) -> dict:
    matches = _calls_by_expression(calls, expression)
    assert len(matches) == 1, f"expected exactly one call {expression!r}, got {matches}"
    return matches[0]


def test_call_graph_document_is_deterministic_and_matches_schema(tmp_path):
    write_utility_goldset(tmp_path)

    first = generate_call_graph_document(tmp_path, "run-1", "a" * 64)
    second = generate_call_graph_document(tmp_path, "run-1", "a" * 64)

    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)

    schema_path = (
        Path(__file__).parent.parent / "contracts" / "python-call-graph.v1.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    jsonschema.validate(instance=first, schema=schema)

    assert first["kind"] == "lenskit.python_call_graph"
    assert first["version"] == "1.0"
    assert first["run_id"] == "run-1"
    assert first["canonical_dump_index_sha256"] == "a" * 64
    assert first["call_count"] == len(first["calls"])
    assert sum(first["resolution_counts"].values()) == first["call_count"]
    assert sum(first["evidence_counts"].values()) == first["call_count"]
    assert sum(first["relation_counts"].values()) == first["call_count"]
    assert first["resolution_statuses"] == [
        "resolved",
        "candidate",
        "ambiguous",
        "unresolved",
    ]
    assert first["relation_types"] == ["calls", "constructs"]
    # Calls are sorted by path, line, column, expression.
    keys = [
        (c["path"], c["start_line"], c["start_col"], c["callee_expression"])
        for c in first["calls"]
    ]
    assert keys == sorted(keys)


def test_call_graph_does_not_establish_contains_required_boundaries(tmp_path):
    write_utility_goldset(tmp_path)
    doc = generate_call_graph_document(tmp_path, "run-1", "a" * 64)

    for boundary in (
        "complete_call_graph",
        "runtime_reachability",
        "dynamic_dispatch_resolution",
        "dependency_completeness",
        "transitive_import_resolution",
        "import_success",
        "test_sufficiency",
        "review_completeness",
        "merge_readiness",
    ):
        assert boundary in doc["does_not_establish"]
    assert tuple(doc["does_not_establish"]) == DOES_NOT_ESTABLISH


def test_safe_resolution_local_module_function(tmp_path):
    write_utility_goldset(tmp_path)
    calls, _, _ = extract_python_calls(tmp_path)

    call = _single_call(calls, "normalize")
    assert call["resolution_status"] == "resolved"
    assert call["resolution_reason"] == "local_module_function"
    assert call["evidence_level"] == "S1"
    assert call["relation_type"] == "calls"
    assert call["resolved_target_ids"] == ["py:utilkit:text.py:function:normalize"]
    assert call["caller_qualified_name"] == "slugify"
    assert call["caller_scope"] == "symbol"
    assert call["simple_name"] == "normalize"
    assert call["range_ref"].startswith("file:utilkit/text.py#L")


def test_safe_resolution_imported_internal_name_and_alias(tmp_path):
    write_utility_goldset(tmp_path)
    calls, _, _ = extract_python_calls(tmp_path)

    imported = [
        call
        for call in _calls_by_expression(calls, "double")
        if call["path"] == "utilkit/text.py"
    ]
    assert len(imported) == 1
    assert imported[0]["resolution_status"] == "resolved"
    assert imported[0]["resolution_reason"] == "imported_internal_name"
    assert imported[0]["resolved_target_ids"] == [
        "py:utilkit:numbers.py:function:double"
    ]

    alias = _single_call(calls, "num.triple")
    assert alias["resolution_status"] == "resolved"
    assert alias["resolution_reason"] == "module_alias_call"
    assert alias["resolved_target_ids"] == ["py:utilkit:numbers.py:function:triple"]
    assert alias["simple_name"] == "triple"


def test_safe_resolution_local_module_imports_after_binding(tmp_path):
    package = tmp_path / "toolkit"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "target.py").write_text("def run():\n    return 1\n", encoding="utf-8")
    (package / "consumer.py").write_text(
        """
def from_import():
    from toolkit import target
    return target.run()


def alias_import():
    import toolkit.target as local_target
    return local_target.run()


def simple_import():
    from toolkit.target import run
    return run()


def before_simple_binding():
    run()
    from toolkit.target import run


def before_binding():
    local_target.run()
    import toolkit.target as local_target
""",
        encoding="utf-8",
    )

    calls, _, _ = extract_python_calls(tmp_path)
    target_calls = _calls_by_expression(calls, "target.run")
    alias_calls = _calls_by_expression(calls, "local_target.run")
    simple_calls = _calls_by_expression(calls, "run")

    assert len(target_calls) == 1
    assert target_calls[0]["resolution_status"] == "resolved"
    assert target_calls[0]["resolution_reason"] == "local_from_import_module_call"
    assert target_calls[0]["resolved_target_ids"] == [
        "py:toolkit:target.py:function:run"
    ]

    assert len(alias_calls) == 2
    resolved = next(
        call for call in alias_calls if call["caller_qualified_name"] == "alias_import"
    )
    unresolved = next(
        call
        for call in alias_calls
        if call["caller_qualified_name"] == "before_binding"
    )
    assert resolved["resolution_status"] == "resolved"
    assert resolved["resolution_reason"] == "local_module_alias_call"
    assert resolved["resolved_target_ids"] == ["py:toolkit:target.py:function:run"]
    assert unresolved["resolution_status"] == "unresolved"
    assert unresolved["resolution_reason"] == "attribute_root_lexically_shadowed_name"
    assert unresolved["resolved_target_ids"] == []

    assert len(simple_calls) == 2
    simple_resolved = next(
        call
        for call in simple_calls
        if call["caller_qualified_name"] == "simple_import"
    )
    simple_unresolved = next(
        call
        for call in simple_calls
        if call["caller_qualified_name"] == "before_simple_binding"
    )
    assert simple_resolved["resolution_status"] == "resolved"
    assert simple_resolved["resolution_reason"] == "local_imported_internal_name"
    assert simple_resolved["resolved_target_ids"] == [
        "py:toolkit:target.py:function:run"
    ]
    assert simple_unresolved["resolution_status"] == "unresolved"
    assert simple_unresolved["resolution_reason"] == "lexically_shadowed_name"
    assert simple_unresolved["resolved_target_ids"] == []


def test_local_import_is_invalidated_by_later_rebinding(tmp_path):
    target = tmp_path / "pkg" / "target.py"
    target.parent.mkdir(parents=True)
    target.write_text("def run():\n    return 1\n", encoding="utf-8")
    (tmp_path / "consumer.py").write_text(
        """
def before():
    from pkg.target import run
    run()
    run = lambda: 2
    run()

def dotted():
    import pkg.target as local_target
    local_target.run()
    local_target = object()
    local_target.run()
""",
        encoding="utf-8",
    )

    calls, _, _ = extract_python_calls(tmp_path)
    simple = [call for call in calls if call["callee_expression"] == "run"]
    dotted = [call for call in calls if call["callee_expression"] == "local_target.run"]

    assert [call["evidence_level"] for call in simple] == ["S1", "S0"]
    assert simple[0]["resolution_reason"] == "local_imported_internal_name"
    assert simple[1]["resolution_reason"] == "lexically_shadowed_name"
    assert [call["evidence_level"] for call in dotted] == ["S1", "S0"]
    assert dotted[0]["resolution_reason"] == "local_module_alias_call"
    assert dotted[1]["resolution_reason"] == "attribute_root_lexically_shadowed_name"


def test_local_import_is_invalidated_by_control_flow_bindings(tmp_path):
    target = tmp_path / "pkg" / "target.py"
    target.parent.mkdir(parents=True)
    target.write_text("def run():\n    return 1\n", encoding="utf-8")
    (tmp_path / "consumer.py").write_text(
        """
def for_binding(items):
    from pkg.target import run
    for run in items:
        pass
    run()

async def async_for_binding(items):
    from pkg.target import run
    async for run in items:
        pass
    run()

def with_binding(manager):
    import pkg.target as local_target
    with manager as local_target:
        pass
    local_target.run()

async def async_with_binding(manager):
    import pkg.target as local_target
    async with manager as local_target:
        pass
    local_target.run()

def except_binding():
    from pkg.target import run
    try:
        raise RuntimeError()
    except RuntimeError as run:
        pass
    run()

def match_binding(value):
    import pkg.target as local_target
    match value:
        case {"target": local_target}:
            pass
    local_target.run()
""",
        encoding="utf-8",
    )

    calls, _, _ = extract_python_calls(tmp_path)
    simple = [call for call in calls if call["callee_expression"] == "run"]
    dotted = [call for call in calls if call["callee_expression"] == "local_target.run"]

    assert {call["caller_qualified_name"] for call in simple} == {
        "for_binding",
        "async_for_binding",
        "except_binding",
    }
    assert {call["caller_qualified_name"] for call in dotted} == {
        "with_binding",
        "async_with_binding",
        "match_binding",
    }
    assert all(call["evidence_level"] == "S0" for call in (*simple, *dotted))
    assert all(call["resolved_target_ids"] == [] for call in (*simple, *dotted))
    assert all(
        call["resolution_reason"] == "lexically_shadowed_name" for call in simple
    )
    assert all(
        call["resolution_reason"] == "attribute_root_lexically_shadowed_name"
        for call in dotted
    )


def test_loop_iter_and_test_rebindings_precede_the_zero_iteration_path(tmp_path):
    target = tmp_path / "pkg" / "target.py"
    target.parent.mkdir(parents=True)
    target.write_text("def run():\n    return 1\n", encoding="utf-8")
    (tmp_path / "consumer.py").write_text(
        """
def sync_for_rebinding(items):
    from pkg.target import run
    for item in (run := items):
        return item
    run()


async def async_for_rebinding(items):
    from pkg.target import run
    async for item in (run := items):
        return item
    run()


def while_rebinding(condition):
    from pkg.target import run
    while (run := condition):
        return run
    run()


def sync_for_unrelated_rebinding(items):
    from pkg.target import run
    for item in (observed := items):
        return item
    run()


async def async_for_unrelated_rebinding(items):
    from pkg.target import run
    async for item in (observed := items):
        return item
    run()


def while_unrelated_rebinding(condition):
    from pkg.target import run
    while (observed := condition):
        return observed
    run()


def loop_target_is_not_bound_on_zero_path(items):
    for run in (observed := items):
        return run
    run()
""",
        encoding="utf-8",
    )

    calls, _, _ = extract_python_calls(tmp_path)
    run_calls = {
        call["caller_qualified_name"]: call
        for call in calls
        if call["callee_expression"] == "run"
    }

    assert {name: call["evidence_level"] for name, call in run_calls.items()} == {
        "sync_for_rebinding": "S0",
        "async_for_rebinding": "S0",
        "while_rebinding": "S0",
        "sync_for_unrelated_rebinding": "S1",
        "async_for_unrelated_rebinding": "S1",
        "while_unrelated_rebinding": "S1",
        "loop_target_is_not_bound_on_zero_path": "S0",
    }
    assert all(
        run_calls[name]["resolution_reason"] == "lexically_shadowed_name"
        for name in (
            "sync_for_rebinding",
            "async_for_rebinding",
            "while_rebinding",
            "loop_target_is_not_bound_on_zero_path",
        )
    )
    assert all(
        run_calls[name]["resolution_reason"] == "local_imported_internal_name"
        for name in (
            "sync_for_unrelated_rebinding",
            "async_for_unrelated_rebinding",
            "while_unrelated_rebinding",
        )
    )


def test_local_import_can_be_reestablished_after_rebinding(tmp_path):
    target = tmp_path / "pkg" / "target.py"
    target.parent.mkdir(parents=True)
    target.write_text("def run():\n    return 1\n", encoding="utf-8")
    (tmp_path / "consumer.py").write_text(
        """
def caller():
    from pkg.target import run
    run = lambda: 2
    from pkg.target import run
    run()
""",
        encoding="utf-8",
    )

    calls, _, _ = extract_python_calls(tmp_path)
    call = _single_call(calls, "run")
    assert call["evidence_level"] == "S1"
    assert call["resolution_reason"] == "local_imported_internal_name"


def test_for_else_import_binding_intersects_possible_break_paths(tmp_path):
    target = tmp_path / "pkg" / "target.py"
    target.parent.mkdir(parents=True)
    target.write_text("def run():\n    return 1\n", encoding="utf-8")
    (tmp_path / "consumer.py").write_text(
        """
def break_skips_else(items):
    for run in items:
        if run:
            break
    else:
        from pkg.target import run
    run()


def no_break_runs_else(items):
    for run in items:
        pass
    else:
        from pkg.target import run
    run()


async def async_break_skips_else(items):
    async for run in items:
        if run:
            break
    else:
        from pkg.target import run
    run()


async def async_no_break_runs_else(items):
    async for run in items:
        pass
    else:
        from pkg.target import run
    run()


def nested_break_does_not_skip_outer_else(items):
    for item in items:
        for nested in items:
            break
    else:
        from pkg.target import run
    run()
""",
        encoding="utf-8",
    )

    calls, _, _ = extract_python_calls(tmp_path)
    run_calls = {
        call["caller_qualified_name"]: call
        for call in calls
        if call["callee_expression"] == "run"
    }

    assert run_calls["break_skips_else"]["evidence_level"] == "S0"
    assert run_calls["async_break_skips_else"]["evidence_level"] == "S0"
    assert run_calls["no_break_runs_else"]["evidence_level"] == "S1"
    assert run_calls["async_no_break_runs_else"]["evidence_level"] == "S1"
    assert run_calls["nested_break_does_not_skip_outer_else"]["evidence_level"] == "S1"
    assert run_calls["no_break_runs_else"]["resolution_reason"] == (
        "local_imported_internal_name"
    )


def test_loop_target_conditional_reimport_does_not_escape_as_s1(tmp_path):
    target = tmp_path / "pkg" / "target.py"
    target.parent.mkdir(parents=True)
    target.write_text("def run():\n    return 1\n", encoding="utf-8")
    (tmp_path / "consumer.py").write_text(
        """
def sync_if_false(items):
    from pkg.target import run
    for run in items:
        if False:
            from pkg.target import run
    run()


def sync_if_conditional(items, restore):
    from pkg.target import run
    for run in items:
        if restore:
            from pkg.target import run
    run()


async def async_if_false(items):
    from pkg.target import run
    async for run in items:
        if False:
            from pkg.target import run
    run()


async def async_if_conditional(items, restore):
    from pkg.target import run
    async for run in items:
        if restore:
            from pkg.target import run
    run()


def sync_conditional_reimport_before_break(items, restore, stop):
    from pkg.target import run
    for run in items:
        if restore:
            from pkg.target import run
        if stop:
            break
    else:
        from pkg.target import run
    run()


async def async_if_false_before_break(items):
    from pkg.target import run
    async for run in items:
        if False:
            from pkg.target import run
        break
    else:
        from pkg.target import run
    run()


def nested_loop_targets_remain_conservative(items, restore):
    from pkg.target import run
    for run in items:
        for nested in items:
            if restore:
                from pkg.target import run
    run()
""",
        encoding="utf-8",
    )

    calls, _, _ = extract_python_calls(tmp_path)
    run_calls = {
        call["caller_qualified_name"]: call
        for call in calls
        if call["callee_expression"] == "run"
    }

    assert set(run_calls) == {
        "sync_if_false",
        "sync_if_conditional",
        "async_if_false",
        "async_if_conditional",
        "sync_conditional_reimport_before_break",
        "async_if_false_before_break",
        "nested_loop_targets_remain_conservative",
    }
    assert all(call["evidence_level"] == "S0" for call in run_calls.values())
    assert all(
        call["resolution_reason"] == "lexically_shadowed_name"
        for call in run_calls.values()
    )


def test_if_import_paths_merge_before_sync_and_async_breaks(tmp_path):
    target = tmp_path / "pkg" / "target.py"
    target.parent.mkdir(parents=True)
    target.write_text("def run():\n    return 1\n", encoding="utf-8")
    (tmp_path / "consumer.py").write_text(
        """
def left_call():
    return None


def right_call():
    return None


def conditional_import(items, cond):
    for item in items:
        if cond:
            from pkg.target import run
        break
    else:
        from pkg.target import run
    run()


async def async_conditional_import(items, cond):
    async for item in items:
        if cond:
            from pkg.target import run
        break
    else:
        from pkg.target import run
    run()


def both_branches_import(items, cond):
    for item in items:
        if cond:
            left_call()
            from pkg.target import run
        else:
            right_call()
            from pkg.target import run
        break
    else:
        from pkg.target import run
    run()


async def async_both_branches_import(items, cond):
    async for item in items:
        if cond:
            left_call()
            from pkg.target import run
        else:
            right_call()
            from pkg.target import run
        break
    else:
        from pkg.target import run
    run()
""",
        encoding="utf-8",
    )

    calls, _, _ = extract_python_calls(tmp_path)
    run_calls = {
        call["caller_qualified_name"]: call
        for call in calls
        if call["callee_expression"] == "run"
    }

    assert run_calls["conditional_import"]["evidence_level"] == "S0"
    assert run_calls["async_conditional_import"]["evidence_level"] == "S0"
    assert run_calls["both_branches_import"]["evidence_level"] == "S1"
    assert run_calls["async_both_branches_import"]["evidence_level"] == "S1"
    assert len(_calls_by_expression(calls, "left_call")) == 2
    assert len(_calls_by_expression(calls, "right_call")) == 2


def test_if_import_merge_uses_only_reachable_fallthrough_paths(tmp_path):
    target = tmp_path / "pkg" / "target.py"
    target.parent.mkdir(parents=True)
    target.write_text("def run():\n    return 1\n", encoding="utf-8")
    (tmp_path / "consumer.py").write_text(
        """
def body_return_else_import(cond):
    if cond:
        body_probe()
        return
    else:
        else_probe()
        from pkg.target import run
    run()


def body_raise_else_import(cond):
    if cond:
        body_probe()
        raise RuntimeError
    else:
        else_probe()
        from pkg.target import run
    run()


def body_import_else_return(cond):
    if cond:
        body_probe()
        from pkg.target import run
    else:
        else_probe()
        return
    run()


def conditional_return_without_import(cond, nested):
    if cond:
        if nested:
            return
    else:
        from pkg.target import run
    run()


def both_reachable_branches_import(cond):
    if cond:
        from pkg.target import run
    else:
        from pkg.target import run
    run()
""",
        encoding="utf-8",
    )

    calls, _, _ = extract_python_calls(tmp_path)
    run_calls = {
        call["caller_qualified_name"]: call
        for call in calls
        if call["callee_expression"] == "run"
    }

    assert {name: call["evidence_level"] for name, call in run_calls.items()} == {
        "body_return_else_import": "S1",
        "body_raise_else_import": "S1",
        "body_import_else_return": "S1",
        "conditional_return_without_import": "S0",
        "both_reachable_branches_import": "S1",
    }
    assert all(
        run_calls[name]["resolution_reason"] == "local_imported_internal_name"
        for name in (
            "body_return_else_import",
            "body_raise_else_import",
            "body_import_else_return",
            "both_reachable_branches_import",
        )
    )
    assert run_calls["conditional_return_without_import"]["resolution_reason"] == (
        "lexically_shadowed_name"
    )
    assert len(_calls_by_expression(calls, "body_probe")) == 3
    assert len(_calls_by_expression(calls, "else_probe")) == 3


def test_try_fallthrough_keeps_only_safe_reachable_import_paths(tmp_path):
    target = tmp_path / "pkg" / "target.py"
    target.parent.mkdir(parents=True)
    target.write_text("def run():\n    return 1\n", encoding="utf-8")
    (tmp_path / "consumer.py").write_text(
        """
def try_return_finally_pass(cond):
    if cond:
        try:
            return
        finally:
            pass
    else:
        from pkg.target import run
    run()


def try_raise_finally_pass(cond):
    if cond:
        try:
            raise RuntimeError
        finally:
            pass
    else:
        from pkg.target import run
    run()


def try_fallthrough_finally_return(cond):
    if cond:
        try:
            body_probe()
        finally:
            return
    else:
        from pkg.target import run
    run()


def all_try_exits_terminate(cond):
    if cond:
        try:
            body_probe()
        except RuntimeError:
            return
        else:
            raise ValueError
    else:
        from pkg.target import run
    run()


def handler_can_fall_through(cond):
    if cond:
        try:
            return result_probe()
        except RuntimeError:
            handler_probe()
        finally:
            cleanup_probe()
    else:
        from pkg.target import run
    run()


def nonterminating_finally_falls_through(cond):
    if cond:
        try:
            body_probe()
        finally:
            cleanup_probe()
    else:
        from pkg.target import run
    run()


def import_may_fail_before_handler_fallthrough(cond):
    if cond:
        try:
            from pkg.target import run
            return result_probe()
        except Exception:
            handler_probe()
    else:
        from pkg.target import run
    run()
""",
        encoding="utf-8",
    )

    calls, _, _ = extract_python_calls(tmp_path)
    run_calls = {
        call["caller_qualified_name"]: call
        for call in calls
        if call["callee_expression"] == "run"
    }

    assert {name: call["evidence_level"] for name, call in run_calls.items()} == {
        "try_return_finally_pass": "S1",
        "try_raise_finally_pass": "S1",
        "try_fallthrough_finally_return": "S1",
        "all_try_exits_terminate": "S1",
        "handler_can_fall_through": "S0",
        "nonterminating_finally_falls_through": "S0",
        "import_may_fail_before_handler_fallthrough": "S0",
    }
    assert all(
        run_calls[name]["resolution_reason"] == "local_imported_internal_name"
        for name in (
            "try_return_finally_pass",
            "try_raise_finally_pass",
            "try_fallthrough_finally_return",
            "all_try_exits_terminate",
        )
    )
    assert all(
        run_calls[name]["resolution_reason"] == "lexically_shadowed_name"
        for name in (
            "handler_can_fall_through",
            "nonterminating_finally_falls_through",
            "import_may_fail_before_handler_fallthrough",
        )
    )


@pytest.mark.skipif(not hasattr(ast, "TryStar"), reason="requires Python 3.11+")
def test_try_star_terminating_paths_do_not_dilute_else_import(tmp_path):
    target = tmp_path / "pkg" / "target.py"
    target.parent.mkdir(parents=True)
    target.write_text("def run():\n    return 1\n", encoding="utf-8")
    (tmp_path / "consumer.py").write_text(
        """
def try_star_return(cond):
    if cond:
        try:
            return
        except* RuntimeError:
            raise
    else:
        from pkg.target import run
    run()
""",
        encoding="utf-8",
    )

    calls, _, _ = extract_python_calls(tmp_path)
    run_call = next(call for call in calls if call["callee_expression"] == "run")

    assert run_call["evidence_level"] == "S1"
    assert run_call["resolution_reason"] == "local_imported_internal_name"


def test_loop_break_and_continue_states_are_path_sensitive_and_nested(tmp_path):
    package = tmp_path / "pkg"
    package.mkdir(parents=True)
    (package / "target.py").write_text(
        "def run():\n    return 1\n",
        encoding="utf-8",
    )
    (package / "other.py").write_text(
        "def run():\n    return 2\n",
        encoding="utf-8",
    )
    (tmp_path / "consumer.py").write_text(
        """
def break_branch_does_not_reach_following_body(items, stop):
    for item in items:
        if stop:
            from pkg.other import run
            break
        else:
            from pkg.target import run
        run()


def continue_branch_does_not_reach_following_body(items, skip):
    for item in items:
        if skip:
            from pkg.other import run
            continue
        else:
            from pkg.target import run
        run()


def continue_binding_affects_loop_exit(items, skip):
    from pkg.target import run
    for item in items:
        if skip:
            from pkg.other import run
            continue
        from pkg.target import run
    run()


def nested_loop_exits_stay_with_the_inner_loop(items):
    for outer in items:
        from pkg.target import run
        for inner in items:
            if inner:
                break
            continue
        run()
""",
        encoding="utf-8",
    )

    calls, _, _ = extract_python_calls(tmp_path)
    run_calls = {
        call["caller_qualified_name"]: call
        for call in calls
        if call["callee_expression"] == "run"
    }

    assert (
        run_calls["break_branch_does_not_reach_following_body"]["evidence_level"]
        == "S1"
    )
    assert (
        run_calls["continue_branch_does_not_reach_following_body"]["evidence_level"]
        == "S1"
    )
    assert run_calls["continue_binding_affects_loop_exit"]["evidence_level"] == "S0"
    assert (
        run_calls["nested_loop_exits_stay_with_the_inner_loop"]["evidence_level"]
        == "S1"
    )
    assert run_calls["continue_binding_affects_loop_exit"]["resolution_reason"] == (
        "lexically_shadowed_name"
    )


def test_break_paths_apply_finally_import_bindings_for_all_loop_kinds(tmp_path):
    target = tmp_path / "pkg" / "target.py"
    target.parent.mkdir(parents=True)
    target.write_text("def run():\n    return 1\n", encoding="utf-8")
    (tmp_path / "consumer.py").write_text(
        """
def sync_for(items):
    for item in items:
        try:
            break
        finally:
            from pkg.target import run
    else:
        from pkg.target import run
    run()


async def async_for(items):
    async for item in items:
        try:
            break
        finally:
            from pkg.target import run
    else:
        from pkg.target import run
    run()


def while_loop(condition):
    while condition:
        try:
            break
        finally:
            from pkg.target import run
    else:
        from pkg.target import run
    run()
""",
        encoding="utf-8",
    )

    calls, _, _ = extract_python_calls(tmp_path)
    run_calls = {
        call["caller_qualified_name"]: call
        for call in calls
        if call["callee_expression"] == "run"
    }

    assert set(run_calls) == {"sync_for", "async_for", "while_loop"}
    assert all(call["evidence_level"] == "S1" for call in run_calls.values())
    assert all(
        call["resolution_reason"] == "local_imported_internal_name"
        for call in run_calls.values()
    )


def test_break_paths_keep_invalidating_and_divergent_finally_bindings_s0(tmp_path):
    package = tmp_path / "pkg"
    package.mkdir(parents=True)
    (package / "target.py").write_text(
        "def run():\n    return 1\n",
        encoding="utf-8",
    )
    (package / "other.py").write_text(
        "def run():\n    return 2\n",
        encoding="utf-8",
    )
    (tmp_path / "consumer.py").write_text(
        """
def invalidated(items):
    for item in items:
        try:
            break
        finally:
            run = lambda: None
    else:
        from pkg.target import run
    run()


async def divergent(items):
    async for item in items:
        try:
            break
        finally:
            from pkg.other import run
    else:
        from pkg.target import run
    run()


def conditional(condition, restore):
    while condition:
        try:
            break
        finally:
            if restore:
                from pkg.target import run
    else:
        from pkg.target import run
    run()


def nested_break_is_isolated(items):
    for outer in items:
        for inner in items:
            try:
                break
            finally:
                from pkg.other import run
    else:
        from pkg.target import run
    run()
""",
        encoding="utf-8",
    )

    calls, _, _ = extract_python_calls(tmp_path)
    run_calls = {
        call["caller_qualified_name"]: call
        for call in calls
        if call["callee_expression"] == "run"
    }

    assert run_calls["invalidated"]["evidence_level"] == "S0"
    assert run_calls["divergent"]["evidence_level"] == "S0"
    assert run_calls["conditional"]["evidence_level"] == "S0"
    assert run_calls["nested_break_is_isolated"]["evidence_level"] == "S1"


def test_continue_paths_apply_and_override_finally_bindings(tmp_path):
    package = tmp_path / "pkg"
    package.mkdir(parents=True)
    (package / "target.py").write_text(
        "def run():\n    return 1\n",
        encoding="utf-8",
    )
    (package / "other.py").write_text(
        "def run():\n    return 2\n",
        encoding="utf-8",
    )
    (tmp_path / "consumer.py").write_text(
        """
def continue_finally_restores_selected_binding(items):
    from pkg.target import run
    for item in items:
        try:
            from pkg.other import run
            continue
        finally:
            from pkg.target import run
    run()


def continue_finally_diverges_from_zero_iteration(items):
    from pkg.target import run
    for item in items:
        try:
            continue
        finally:
            from pkg.other import run
    run()


def finally_break_overrides_continue_and_skips_else(items):
    for item in items:
        try:
            continue
        finally:
            from pkg.other import run
            break
    else:
        from pkg.target import run
    run()


def finally_continue_overrides_break_and_reaches_else(items):
    for item in items:
        try:
            break
        finally:
            from pkg.other import run
            continue
    else:
        from pkg.target import run
    run()
""",
        encoding="utf-8",
    )

    calls, _, _ = extract_python_calls(tmp_path)
    run_calls = {
        call["caller_qualified_name"]: call
        for call in calls
        if call["callee_expression"] == "run"
    }

    assert (
        run_calls["continue_finally_restores_selected_binding"]["evidence_level"]
        == "S1"
    )
    assert (
        run_calls["continue_finally_diverges_from_zero_iteration"]["evidence_level"]
        == "S0"
    )
    assert (
        run_calls["finally_break_overrides_continue_and_skips_else"]["evidence_level"]
        == "S0"
    )
    assert (
        run_calls["finally_continue_overrides_break_and_reaches_else"]["evidence_level"]
        == "S1"
    )


@pytest.mark.parametrize("expression_field", ("bound", "default_value"))
@pytest.mark.parametrize(
    ("parameter_names", "expected_expression_resolution"),
    (
        (("run", "T"), ("S0", "type_parameter_binding")),
        (("T", "run"), ("S1", "local_imported_internal_name")),
    ),
)
def test_type_alias_type_parameter_expressions_use_sequential_scope(
    expression_field,
    parameter_names,
    expected_expression_resolution,
):
    type_alias_class = type(
        "TypeAlias",
        (ast.AST,),
        {"_fields": ("name", "type_params", "value")},
    )
    type_parameter_class = type(
        "TypeVar",
        (ast.AST,),
        {"_fields": ("name", "bound", "default_value")},
    )
    tree = ast.parse(
        """
def caller():
    from pkg.target import run
    marker()
    run()
"""
    )
    function = tree.body[0]
    assert isinstance(function, ast.FunctionDef)
    marker = function.body[1]
    assert isinstance(marker, ast.Expr)
    alias_value = ast.Call(
        func=ast.Name(id="run", ctx=ast.Load()),
        args=[],
        keywords=[],
    )
    type_parameters = []
    for parameter_name in parameter_names:
        type_parameter = type_parameter_class()
        type_parameter.name = parameter_name
        type_parameter.bound = None
        type_parameter.default_value = None
        if parameter_name == "T":
            setattr(
                type_parameter,
                expression_field,
                ast.Call(
                    func=ast.Name(id="run", ctx=ast.Load()),
                    args=[],
                    keywords=[],
                ),
            )
        type_parameters.append(type_parameter)
    alias = type_alias_class()
    alias.name = ast.Name(id="Alias", ctx=ast.Store())
    alias.type_params = type_parameters
    alias.value = alias_value
    function.body[1] = ast.copy_location(alias, marker)
    ast.fix_missing_locations(tree)

    target_tree = ast.parse("def run():\n    return 1\n")
    target_visitor = _CallGraphVisitor("pkg/target.py", is_package=False)
    target_visitor.visit(target_tree)
    consumer_visitor = _CallGraphVisitor("consumer.py", is_package=False)
    consumer_visitor.visit(tree)
    modules = {
        target_visitor.state.module: [target_visitor.state],
        consumer_visitor.state.module: [consumer_visitor.state],
    }
    resolver = _Resolver(modules)
    calls = [
        resolver.resolve(consumer_visitor.state, raw)
        for raw in consumer_visitor.state.calls
    ]
    run_calls = [call for call in calls if call["callee_expression"] == "run"]

    expected_level, expected_reason = expected_expression_resolution
    assert [call["evidence_level"] for call in run_calls] == [
        expected_level,
        "S0",
        "S1",
    ]
    assert [call["resolution_reason"] for call in run_calls] == [
        expected_reason,
        "type_parameter_binding",
        "local_imported_internal_name",
    ]


def test_synthetic_type_alias_rebinding_invalidates_all_local_import_forms():
    type_alias_class = type(
        "TypeAlias",
        (ast.AST,),
        {"_fields": ("name", "type_params", "value")},
    )
    tree = ast.parse(
        """
def caller():
    from pkg.target import run
    import pkg.target as target_module
    run()
    target_module.run()
    marker()
    run()
    target_module.run()
"""
    )
    function = tree.body[0]
    assert isinstance(function, ast.FunctionDef)
    marker = function.body[4]
    assert isinstance(marker, ast.Expr)

    aliases = []
    for name in ("run", "target_module"):
        alias = type_alias_class()
        alias.name = ast.Name(id=name, ctx=ast.Store())
        alias.type_params = []
        alias.value = ast.Name(id="int", ctx=ast.Load())
        aliases.append(ast.copy_location(alias, marker))
    function.body[4:5] = aliases
    ast.fix_missing_locations(tree)

    target_visitor = _CallGraphVisitor("pkg/target.py", is_package=False)
    target_visitor.visit(ast.parse("def run():\n    return 1\n"))
    consumer_visitor = _CallGraphVisitor("consumer.py", is_package=False)
    consumer_visitor.visit(tree)
    resolver = _Resolver(
        {
            target_visitor.state.module: [target_visitor.state],
            consumer_visitor.state.module: [consumer_visitor.state],
        }
    )
    calls = [
        resolver.resolve(consumer_visitor.state, raw)
        for raw in consumer_visitor.state.calls
    ]

    run_calls = _calls_by_expression(calls, "run")
    dotted_calls = _calls_by_expression(calls, "target_module.run")
    assert [
        (call["evidence_level"], call["resolution_reason"]) for call in run_calls
    ] == [
        ("S1", "local_imported_internal_name"),
        ("S0", "lexically_shadowed_name"),
    ]
    assert [
        (call["evidence_level"], call["resolution_reason"]) for call in dotted_calls
    ] == [
        ("S1", "local_module_alias_call"),
        ("S0", "attribute_root_lexically_shadowed_name"),
    ]


@pytest.mark.parametrize(
    ("alias_statement", "expected_evidence"),
    (
        ("type Alias[run] = run()", ["S0", "S1"]),
        ("type Alias[left, run, right] = run()", ["S0", "S1"]),
        ("type Alias[T] = run()", ["S1", "S1"]),
    ),
)
def test_type_alias_parameter_scope_with_python312_syntax(
    tmp_path,
    alias_statement,
    expected_evidence,
):
    if not hasattr(ast, "TypeAlias"):
        pytest.skip("requires the Python 3.12 type-alias AST and parser")

    target = tmp_path / "pkg" / "target.py"
    target.parent.mkdir(parents=True)
    target.write_text("def run():\n    return 1\n", encoding="utf-8")
    (tmp_path / "consumer.py").write_text(
        f"""
def caller():
    from pkg.target import run
    {alias_statement}
    run()
""",
        encoding="utf-8",
    )

    calls, _, _ = extract_python_calls(tmp_path)
    run_calls = _calls_by_expression(calls, "run")

    assert [call["evidence_level"] for call in run_calls] == expected_evidence
    if expected_evidence[0] == "S0":
        assert run_calls[0]["resolution_reason"] == "type_parameter_binding"
    assert run_calls[1]["resolution_reason"] == "local_imported_internal_name"


def test_type_alias_later_bound_sees_earlier_parameter_with_python312_syntax(
    tmp_path,
):
    if not hasattr(ast, "TypeAlias"):
        pytest.skip("requires the Python 3.12 type-alias AST and parser")

    target = tmp_path / "pkg" / "target.py"
    target.parent.mkdir(parents=True)
    target.write_text("def run():\n    return 1\n", encoding="utf-8")
    (tmp_path / "consumer.py").write_text(
        """
def caller():
    from pkg.target import run
    type Alias[run, T: run()] = T
    run()
""",
        encoding="utf-8",
    )

    calls, _, _ = extract_python_calls(tmp_path)
    run_calls = _calls_by_expression(calls, "run")

    assert [call["evidence_level"] for call in run_calls] == ["S0", "S1"]
    assert run_calls[0]["resolution_reason"] == "type_parameter_binding"
    assert run_calls[1]["resolution_reason"] == "local_imported_internal_name"


@pytest.mark.parametrize(
    "alias_statement",
    (
        "type Alias[run: run()] = int",
        "type Alias[T: run(), run] = T",
    ),
)
def test_type_alias_bound_does_not_see_current_or_later_parameter_with_python312_syntax(
    tmp_path,
    alias_statement,
):
    if not hasattr(ast, "TypeAlias"):
        pytest.skip("requires the Python 3.12 type-alias AST and parser")

    target = tmp_path / "pkg" / "target.py"
    target.parent.mkdir(parents=True)
    target.write_text("def run():\n    return 1\n", encoding="utf-8")
    (tmp_path / "consumer.py").write_text(
        f"""
def caller():
    from pkg.target import run
    {alias_statement}
    run()
""",
        encoding="utf-8",
    )

    calls, _, _ = extract_python_calls(tmp_path)
    run_calls = _calls_by_expression(calls, "run")

    assert [call["evidence_level"] for call in run_calls] == ["S1", "S1"]
    assert all(
        call["resolution_reason"] == "local_imported_internal_name"
        for call in run_calls
    )


def test_type_alias_value_sees_all_parameters_with_python312_syntax(tmp_path):
    target = tmp_path / "pkg" / "target.py"
    target.parent.mkdir(parents=True)
    target.write_text(
        "def left():\n    return 1\n\n\ndef run():\n    return 2\n",
        encoding="utf-8",
    )
    (tmp_path / "consumer.py").write_text(
        """
def caller():
    from pkg.target import left, run
    type Alias[left, run] = tuple[left(), run()]
    left()
    run()
""",
        encoding="utf-8",
    )

    if not hasattr(ast, "TypeAlias"):
        pytest.skip("requires the Python 3.12 type-alias AST and parser")

    calls, _, _ = extract_python_calls(tmp_path)
    left_calls = _calls_by_expression(calls, "left")
    run_calls = _calls_by_expression(calls, "run")

    assert [call["evidence_level"] for call in left_calls] == ["S0", "S1"]
    assert [call["evidence_level"] for call in run_calls] == ["S0", "S1"]
    assert left_calls[0]["resolution_reason"] == "type_parameter_binding"
    assert run_calls[0]["resolution_reason"] == "type_parameter_binding"
    assert left_calls[1]["resolution_reason"] == "local_imported_internal_name"
    assert run_calls[1]["resolution_reason"] == "local_imported_internal_name"


def test_type_alias_syntax_invalidates_import_when_parser_supports_it(tmp_path):
    if not hasattr(ast, "TypeAlias"):
        pytest.skip("requires the Python 3.12 type-alias AST and parser")

    source = """
def caller():
    from pkg.target import run
    run()
    type run = int
    run()
"""
    try:
        ast.parse(source)
    except SyntaxError:
        pytest.skip("type-alias syntax is unavailable in this parser")

    target = tmp_path / "pkg" / "target.py"
    target.parent.mkdir(parents=True)
    target.write_text("def run():\n    return 1\n", encoding="utf-8")
    (tmp_path / "consumer.py").write_text(source, encoding="utf-8")

    calls, _, _ = extract_python_calls(tmp_path)
    run_calls = _calls_by_expression(calls, "run")

    assert [call["evidence_level"] for call in run_calls] == ["S1", "S0"]
    assert run_calls[1]["resolution_reason"] == "lexically_shadowed_name"


def test_type_alias_lazy_value_self_binding_with_python312_syntax(tmp_path):
    if not hasattr(ast, "TypeAlias"):
        pytest.skip("requires the Python 3.12 type-alias AST and parser")

    target = tmp_path / "pkg" / "target.py"
    target.parent.mkdir(parents=True)
    target.write_text("def run():\n    return 1\n", encoding="utf-8")
    (tmp_path / "consumer.py").write_text(
        """
def local_recursive():
    from pkg.target import run
    type run = run()
    run()


class ClassRecursive:
    from pkg.target import run
    type run = run()
    run()


def non_colliding():
    from pkg.target import run
    type Alias = run()
    run()


def recursive_with_type_parameters():
    from pkg.target import run
    type run[T: run()] = tuple[T, run()]
    run()
""",
        encoding="utf-8",
    )

    calls, _, _ = extract_python_calls(tmp_path)
    run_calls: dict[str, list[dict]] = {}
    for call in calls:
        if call["callee_expression"] == "run":
            run_calls.setdefault(call["caller_qualified_name"], []).append(call)

    assert [
        (call["evidence_level"], call["resolution_reason"])
        for call in run_calls["local_recursive"]
    ] == [
        ("S0", "type_alias_self_binding"),
        ("S0", "lexically_shadowed_name"),
    ]
    assert [
        (call["evidence_level"], call["resolution_reason"])
        for call in run_calls["ClassRecursive"]
    ] == [
        ("S0", "type_alias_self_binding"),
        ("S0", "class_scope_binding"),
    ]
    assert [
        (call["evidence_level"], call["resolution_reason"])
        for call in run_calls["non_colliding"]
    ] == [
        ("S1", "local_imported_internal_name"),
        ("S1", "local_imported_internal_name"),
    ]
    assert [
        (call["evidence_level"], call["resolution_reason"])
        for call in run_calls["recursive_with_type_parameters"]
    ] == [
        ("S1", "local_imported_internal_name"),
        ("S0", "type_alias_self_binding"),
        ("S0", "lexically_shadowed_name"),
    ]


def test_method_does_not_resolve_bare_class_scope_imports(tmp_path):
    target = tmp_path / "toolkit" / "target.py"
    target.parent.mkdir(parents=True)
    target.write_text("def run():\n    return 1\n", encoding="utf-8")
    (tmp_path / "consumer.py").write_text(
        """
class Consumer:
    from toolkit.target import run
    import toolkit.target as local_target

    def bare(self):
        run()

    def dotted(self):
        local_target.run()
""",
        encoding="utf-8",
    )

    calls, _, _ = extract_python_calls(tmp_path)
    bare = _single_call(calls, "run")
    dotted = _single_call(calls, "local_target.run")

    assert bare["caller_qualified_name"] == "Consumer.bare"
    assert bare["resolution_status"] == "unresolved"
    assert bare["resolved_target_ids"] == []
    assert dotted["caller_qualified_name"] == "Consumer.dotted"
    assert dotted["resolution_status"] == "unresolved"
    assert dotted["resolved_target_ids"] == []


def test_safe_resolution_self_and_cls_methods_same_class(tmp_path):
    write_utility_goldset(tmp_path)
    calls, _, _ = extract_python_calls(tmp_path)

    self_call = _single_call(calls, "self.indent")
    assert self_call["resolution_status"] == "resolved"
    assert self_call["resolution_reason"] == "self_method_same_class"
    assert self_call["resolved_target_ids"] == [
        "py:utilkit:text.py:function:Formatter.indent"
    ]
    assert self_call["caller_qualified_name"] == "Formatter.format"

    cls_call = _single_call(calls, "cls.default")
    assert cls_call["resolution_status"] == "resolved"
    assert cls_call["resolution_reason"] == "cls_method_same_class"
    assert cls_call["resolved_target_ids"] == [
        "py:utilkit:text.py:function:Formatter.default"
    ]


def test_safe_resolution_direct_recursion(tmp_path):
    write_utility_goldset(tmp_path)
    calls, _, _ = extract_python_calls(tmp_path)

    recursive = [
        call
        for call in _calls_by_expression(calls, "walk")
        if call["caller_qualified_name"] == "walk"
    ]
    assert len(recursive) == 1
    assert recursive[0]["resolution_status"] == "resolved"
    assert recursive[0]["resolution_reason"] == "direct_recursion"
    assert recursive[0]["resolved_target_ids"] == ["py:utilkit:text.py:function:walk"]


def test_ambiguous_multiple_definitions_stay_unresolved_as_ambiguous(tmp_path):
    write_utility_goldset(tmp_path)
    calls, _, _ = extract_python_calls(tmp_path)

    call = _single_call(calls, "cond")
    assert call["resolution_status"] == "ambiguous"
    assert call["evidence_level"] == "S0"
    assert call["resolution_reason"] == "local_module_function_multiple_definitions"
    assert call["resolved_target_ids"] == []
    # Both conditional definitions share the same qualified name, so the
    # deduplicated candidate set is a single id — the status stays ambiguous.
    assert call["candidate_target_ids"] == ["py:utilkit:numbers.py:function:cond"]


def test_dynamic_attribute_and_undefined_method_stay_unresolved(tmp_path):
    write_utility_goldset(tmp_path)
    calls, _, _ = extract_python_calls(tmp_path)

    dynamic = _single_call(calls, "value.strip")
    assert dynamic["resolution_status"] == "unresolved"
    assert dynamic["resolution_reason"] == "attribute_root_lexically_shadowed_name"
    assert dynamic["evidence_level"] == "S0"
    assert dynamic["resolved_target_ids"] == []
    assert dynamic["candidate_target_ids"] == []

    missing = _single_call(calls, "self.missing")
    assert missing["resolution_status"] == "unresolved"
    assert missing["resolution_reason"] == "method_not_defined_in_same_class"


def test_foreign_calls_stay_unresolved(tmp_path):
    write_utility_goldset(tmp_path)
    calls, _, _ = extract_python_calls(tmp_path)

    stdlib = _single_call(calls, "os.path.join")
    assert stdlib["resolution_status"] == "unresolved"
    assert stdlib["resolution_reason"] == "module_alias_call_foreign_module"

    external = _single_call(calls, "shim")
    assert external["resolution_status"] == "unresolved"
    assert external["resolution_reason"] == "imported_internal_name_foreign_module"


def test_local_class_instantiation_is_unique_construct_relation(tmp_path):
    write_utility_goldset(tmp_path)
    calls, _, _ = extract_python_calls(tmp_path)

    call = _single_call(calls, "Formatter")
    assert call["resolution_status"] == "resolved"
    assert call["evidence_level"] == "S1"
    assert call["relation_type"] == "constructs"
    assert call["resolved_target_ids"] == ["py:utilkit:text.py:class:Formatter"]
    assert call["candidate_target_ids"] == []


def test_module_scope_caller_is_recorded(tmp_path):
    write_utility_goldset(tmp_path)
    calls, _, _ = extract_python_calls(tmp_path)

    call = _single_call(calls, "slugify")
    assert call["caller_scope"] == "module"
    assert call["caller_symbol_id"] is None
    assert call["caller_qualified_name"] is None
    assert call["caller_kind"] == "module"
    assert call["resolution_status"] == "resolved"


def test_parse_errors_are_counted_and_documented_bounded(tmp_path):
    write_utility_goldset(tmp_path)
    doc = generate_call_graph_document(tmp_path, "run-1", "a" * 64)

    assert doc["skipped_files_count"] == 1
    assert doc["skipped_errors_total_count"] == 1
    assert doc["skipped_errors_truncated"] is False
    assert len(doc["skipped_errors"]) == 1
    assert "utilkit/broken.py" in doc["skipped_errors"][0]
    assert "SyntaxError" in doc["skipped_errors"][0]
    # The broken file contributes no call records.
    assert all(call["path"] != "utilkit/broken.py" for call in doc["calls"])


def test_parse_error_truncation_is_explicit(tmp_path):
    for index in range(25):
        (tmp_path / f"broken_{index:02d}.py").write_text(
            "def broken(:\n", encoding="utf-8"
        )

    doc = generate_call_graph_document(tmp_path, "run-1", "a" * 64)

    assert doc["skipped_files_count"] == 25
    assert doc["skipped_errors_total_count"] == 25
    assert len(doc["skipped_errors"]) == MAX_SKIPPED_ERRORS
    assert doc["skipped_errors_truncated"] is True


def test_call_graph_schema_matches_shared_diagnostic_limit():
    schema_path = (
        Path(__file__).parents[1] / "contracts" / "python-call-graph.v1.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    assert schema["properties"]["skipped_errors"]["maxItems"] == MAX_SKIPPED_ERRORS
    assert set(DOES_NOT_ESTABLISH) <= set(
        schema["properties"]["does_not_establish"]["items"]["enum"]
    )


def test_missing_ast_end_position_is_normalized_to_valid_range():
    tree = ast.parse("def caller():\n    return target()\n")
    call_node = next(node for node in ast.walk(tree) if isinstance(node, ast.Call))
    call_node.end_lineno = None
    call_node.end_col_offset = None

    visitor = _CallGraphVisitor("sample.py", is_package=False)
    visitor.visit(tree)
    state = visitor.state
    record = _Resolver({state.module: [state]}).resolve(state, state.calls[0])

    assert record["start_line"] == record["end_line"] == 2
    assert record["end_col"] == record["start_col"]
    assert _call_record_is_valid(record) is True


SCOPE_GOLDSET_PY = """
def target():
    return 1


def decorator(value):
    return value


def base_factory():
    return object


@decorator(target())
def decorated(value=target()):
    return value


class Built(base_factory()):
    marker = target()


def parameter_shadow(target):
    return target()


def assignment_shadow():
    target = lambda: 2
    return target()


def import_shadow():
    from external_lib import target
    return target()


def nested_shadow():
    def target():
        return 3
    return target()


def global_call():
    global target
    return target()


def nonlocal_case():
    target = lambda: 4
    def inner():
        nonlocal target
        return target()
    return inner()


def comprehension_shadow(items):
    return [target() for target in items]


def walrus_shadow(value):
    if target := value:
        return target()
    return None


def loop_shadow(items):
    for target in items:
        return target()
    return None


def lambda_shadow():
    return (lambda target: target())(target)


class Receiver:
    def okay(self):
        return self.other()

    def other(self):
        return 1

    def wrong(alias):
        return self.other()
"""


def _write_scope_goldset(root: Path) -> None:
    package = root / "scopekit"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "scopes.py").write_text(SCOPE_GOLDSET_PY, encoding="utf-8")


def _scope_call(calls: list[dict], expression: str, caller: str | None) -> dict:
    matches = [
        call
        for call in calls
        if call["path"] == "scopekit/scopes.py"
        and call["callee_expression"] == expression
        and call["caller_qualified_name"] == caller
    ]
    assert len(matches) == 1, matches
    return matches[0]


def test_lexical_shadowing_never_upgrades_to_s1(tmp_path):
    _write_scope_goldset(tmp_path)
    calls, _, _ = extract_python_calls(tmp_path)

    expected = {
        "parameter_shadow": "lexically_shadowed_name",
        "assignment_shadow": "lexically_shadowed_name",
        "import_shadow": "lexically_shadowed_name",
        "nested_shadow": "lexically_shadowed_name",
        "nonlocal_case.inner": "nonlocal_binding",
        "comprehension_shadow": "comprehension_binding",
        "walrus_shadow": "lexically_shadowed_name",
        "loop_shadow": "lexically_shadowed_name",
    }
    for caller, reason in expected.items():
        call = _scope_call(calls, "target", caller)
        assert call["resolution_status"] == "unresolved"
        assert call["evidence_level"] == "S0"
        assert call["resolution_reason"] == reason
        assert call["resolved_target_ids"] == []

    lambda_call = [
        call
        for call in calls
        if call["path"] == "scopekit/scopes.py"
        and call["callee_expression"] == "target"
        and call["resolution_reason"] == "lexically_shadowed_name"
        and call["caller_qualified_name"] == "lambda_shadow"
    ]
    assert len(lambda_call) == 1


def test_nested_comprehension_targets_do_not_leak_into_outer_scope(tmp_path):
    (tmp_path / "sample.py").write_text(
        "def target():\n"
        "    return 1\n\n"
        "def caller(items):\n"
        "    return [target() for item in [item for target in items]]\n",
        encoding="utf-8",
    )

    calls, _, _ = extract_python_calls(tmp_path)
    call = next(
        row
        for row in calls
        if row["caller_qualified_name"] == "caller"
        and row["callee_expression"] == "target"
    )

    assert call["resolution_status"] == "resolved"
    assert call["resolution_reason"] == "local_module_function"


def test_comprehension_generator_bindings_follow_python_evaluation_order(tmp_path):
    (tmp_path / "sample.py").write_text(
        "def target():\n"
        "    return [1]\n\n"
        "def before_binding(items):\n"
        "    return [item for target in target()]\n\n"
        "def later_binding(items):\n"
        "    return [item for item in target() for target in items]\n\n"
        "def prior_binding(items):\n"
        "    return [item for target in items for item in target()]\n",
        encoding="utf-8",
    )

    calls, _, _ = extract_python_calls(tmp_path)
    by_caller = {
        row["caller_qualified_name"]: row
        for row in calls
        if row["callee_expression"] == "target"
    }

    assert by_caller["before_binding"]["resolution_status"] == "resolved"
    assert by_caller["before_binding"]["resolution_reason"] == "local_module_function"
    assert by_caller["later_binding"]["resolution_status"] == "resolved"
    assert by_caller["later_binding"]["resolution_reason"] == "local_module_function"
    assert by_caller["prior_binding"]["resolution_status"] == "unresolved"
    assert by_caller["prior_binding"]["resolution_reason"] == "comprehension_binding"


def test_global_binding_can_resolve_module_symbol(tmp_path):
    _write_scope_goldset(tmp_path)
    calls, _, _ = extract_python_calls(tmp_path)

    call = _scope_call(calls, "target", "global_call")
    assert call["resolution_status"] == "resolved"
    assert call["evidence_level"] == "S1"
    assert call["resolved_target_ids"] == ["py:scopekit:scopes.py:function:target"]


def test_definition_header_calls_belong_to_enclosing_scope(tmp_path):
    _write_scope_goldset(tmp_path)
    calls, _, _ = extract_python_calls(tmp_path)

    module_target_calls = [
        call
        for call in calls
        if call["path"] == "scopekit/scopes.py"
        and call["callee_expression"] == "target"
        and call["caller_scope"] == "module"
    ]
    assert len(module_target_calls) == 2
    assert all(call["caller_symbol_id"] is None for call in module_target_calls)

    base = _scope_call(calls, "base_factory", None)
    assert base["caller_scope"] == "module"
    class_body = _scope_call(calls, "target", "Built")
    assert class_body["caller_kind"] == "class"


def test_self_resolution_requires_actual_direct_method_receiver(tmp_path):
    _write_scope_goldset(tmp_path)
    calls, _, _ = extract_python_calls(tmp_path)

    safe = _scope_call(calls, "self.other", "Receiver.okay")
    assert safe["resolution_status"] == "resolved"
    assert safe["evidence_level"] == "S1"
    assert safe["resolved_target_ids"] == [
        "py:scopekit:scopes.py:function:Receiver.other"
    ]

    unsafe = _scope_call(calls, "self.other", "Receiver.wrong")
    assert unsafe["resolution_status"] == "unresolved"
    assert unsafe["evidence_level"] == "S0"
    assert unsafe["resolution_reason"] == "receiver_not_direct_method_parameter"


def test_module_name_collision_preserves_all_calls_and_refuses_resolution(tmp_path):
    (tmp_path / "foo.py").write_text(
        "def target():\n    return 1\n\ndef file_caller():\n    return target()\n",
        encoding="utf-8",
    )
    package = tmp_path / "foo"
    package.mkdir()
    (package / "__init__.py").write_text(
        "def target():\n    return 2\n\ndef package_caller():\n    return target()\n",
        encoding="utf-8",
    )
    (tmp_path / "consumer.py").write_text(
        "import foo\n"
        "from foo import target\n\n"
        "def caller():\n"
        "    return target()\n\n"
        "def alias_caller():\n"
        "    return foo.target()\n",
        encoding="utf-8",
    )

    calls, _, _ = extract_python_calls(tmp_path)
    local_paths = {
        call["path"]
        for call in calls
        if call["simple_name"] == "target"
        and call["caller_qualified_name"] in {"file_caller", "package_caller"}
    }
    assert local_paths == {"foo.py", "foo/__init__.py"}

    imported = next(
        call
        for call in calls
        if call["path"] == "consumer.py"
        and call["caller_qualified_name"] == "caller"
        and call["simple_name"] == "target"
    )
    assert imported["resolution_status"] == "ambiguous"
    assert imported["evidence_level"] == "S0"
    assert imported["resolution_reason"] == "imported_internal_name_module_collision"
    assert set(imported["candidate_target_ids"]) == {
        "py:foo.py:function:target",
        "py:foo:__init__.py:function:target",
    }

    aliased = next(
        call
        for call in calls
        if call["path"] == "consumer.py"
        and call["caller_qualified_name"] == "alias_caller"
        and call["callee_expression"] == "foo.target"
    )
    assert aliased["resolution_status"] == "ambiguous"
    assert aliased["evidence_level"] == "S0"
    assert aliased["resolution_reason"] == "module_alias_call_module_collision"
    assert set(aliased["candidate_target_ids"]) == {
        "py:foo.py:function:target",
        "py:foo:__init__.py:function:target",
    }


def test_bare_method_name_is_not_treated_as_direct_recursion(tmp_path):
    (tmp_path / "sample.py").write_text(
        "class Worker:\n    def run(self):\n        return run()\n",
        encoding="utf-8",
    )

    calls, _, _ = extract_python_calls(tmp_path)
    call = _single_call(calls, "run")

    assert call["caller_qualified_name"] == "Worker.run"
    assert call["resolution_status"] == "unresolved"
    assert call["evidence_level"] == "S0"
    assert call["resolution_reason"] == "unknown_name"
    assert call["resolved_target_ids"] == []


def test_redefined_module_function_is_not_treated_as_direct_recursion(tmp_path):
    (tmp_path / "sample.py").write_text(
        "def walk():\n    return walk()\n\ndef walk():\n    return 0\n",
        encoding="utf-8",
    )

    calls, _, _ = extract_python_calls(tmp_path)
    call = _single_call(calls, "walk")

    assert call["caller_qualified_name"] == "walk"
    assert call["resolution_status"] == "ambiguous"
    assert call["evidence_level"] == "S0"
    assert call["resolution_reason"] == "local_module_function_multiple_definitions"
    assert call["resolved_target_ids"] == []
