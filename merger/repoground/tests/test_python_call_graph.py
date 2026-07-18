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

from merger.repoground.architecture.call_graph import (
    DOES_NOT_ESTABLISH,
    MAX_SKIPPED_ERRORS,
    _CallGraphVisitor,
    _Resolver,
    extract_python_calls,
    generate_call_graph_document,
)
from merger.repoground.core.bundle_access import _call_record_is_valid

GOLDSET_TEXT_PY = '''import os.path
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
'''

GOLDSET_NUMBERS_PY = '''def double(x):
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
'''


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

    schema_path = Path(__file__).parent.parent / "contracts" / "python-call-graph.v1.schema.json"
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
    assert first["resolution_statuses"] == ["resolved", "candidate", "ambiguous", "unresolved"]
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
    assert imported[0]["resolved_target_ids"] == ["py:utilkit:numbers.py:function:double"]

    alias = _single_call(calls, "num.triple")
    assert alias["resolution_status"] == "resolved"
    assert alias["resolution_reason"] == "module_alias_call"
    assert alias["resolved_target_ids"] == ["py:utilkit:numbers.py:function:triple"]
    assert alias["simple_name"] == "triple"


def test_safe_resolution_self_and_cls_methods_same_class(tmp_path):
    write_utility_goldset(tmp_path)
    calls, _, _ = extract_python_calls(tmp_path)

    self_call = _single_call(calls, "self.indent")
    assert self_call["resolution_status"] == "resolved"
    assert self_call["resolution_reason"] == "self_method_same_class"
    assert self_call["resolved_target_ids"] == ["py:utilkit:text.py:function:Formatter.indent"]
    assert self_call["caller_qualified_name"] == "Formatter.format"

    cls_call = _single_call(calls, "cls.default")
    assert cls_call["resolution_status"] == "resolved"
    assert cls_call["resolution_reason"] == "cls_method_same_class"
    assert cls_call["resolved_target_ids"] == ["py:utilkit:text.py:function:Formatter.default"]


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


SCOPE_GOLDSET_PY = '''
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
'''


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
        "def target():\n"
        "    return 1\n\n"
        "def file_caller():\n"
        "    return target()\n",
        encoding="utf-8",
    )
    package = tmp_path / "foo"
    package.mkdir()
    (package / "__init__.py").write_text(
        "def target():\n"
        "    return 2\n\n"
        "def package_caller():\n"
        "    return target()\n",
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
        "class Worker:\n"
        "    def run(self):\n"
        "        return run()\n",
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
        "def walk():\n"
        "    return walk()\n"
        "\n"
        "def walk():\n"
        "    return 0\n",
        encoding="utf-8",
    )

    calls, _, _ = extract_python_calls(tmp_path)
    call = _single_call(calls, "walk")

    assert call["caller_qualified_name"] == "walk"
    assert call["resolution_status"] == "ambiguous"
    assert call["evidence_level"] == "S0"
    assert call["resolution_reason"] == "local_module_function_multiple_definitions"
    assert call["resolved_target_ids"] == []
