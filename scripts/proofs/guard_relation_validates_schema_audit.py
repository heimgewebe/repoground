#!/usr/bin/env python3
"""Base-source-bound, falsifiable audit for the ``validates_schema`` target proof.

Diagnosis-only. This is NOT a production relation contract, producer or runtime
validator. It reads a *fixed historical snapshot* (never the working tree),
re-derives an independent observation set with a deliberately narrow, declared
jsonschema grammar, and verifies the manually reviewed flow manifest against it.
Mismatches fail closed.

Design (separation of powers):

  reviewed inputs (manual)        derived observations (machine)
  - flow manifest rows       +    - base-bound infer_facets
  - meta manifest rows            - receiver-resolved engine/meta callsites
  - text-only explanations        - resolved vs. unresolved partition
          \\                       - schema-file coverage from the tree
           \\                      - test-facet inventory from the snapshot
            +--> comparison gate (require, fail-closed) --> derived report

The committed audit JSON keeps the reviewed inputs verbatim and replaces the
``derived`` section with a freshly computed one. A tampered manifest row (wrong
callsite, missing schema, foreign ``.validate``) makes a gate fail, so the
comparison is not a tautology. Gates use ``require`` / ``AuditError`` (never
``assert``) so they stay active under ``python -O``.

Grammar boundary: only jsonschema receivers proven by scope- and source-order-
aware intra-module binding are ``derived_ast``. Loader-indirect and unproven
parameter-injected validators are ``manual_source_review`` and listed explicitly;
any *new* unresolved candidate fails the audit. Historical ``lens_facets`` source
is restricted to standard-library imports before execution.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

AUDIT_FILENAME = "guard-relation-cards-v1b-validates-schema-audit.json"
# Committed audit lives in docs/proofs/; this script lives in scripts/proofs/.
DEFAULT_MANIFEST = (
    Path(__file__).resolve().parent.parent.parent
    / "docs" / "proofs" / AUDIT_FILENAME
)
LENS_FACETS_PATHS = (
    "merger/repoground/core/lens_facets.py",
    "merger/lenskit/core/lens_facets.py",
)
JSONSCHEMA_CONSTRUCTORS = {
    "Draft3Validator", "Draft4Validator", "Draft6Validator",
    "Draft7Validator", "Draft201909Validator", "Draft202012Validator",
}


class AuditError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AuditError(message)


# ---------------------------------------------------------------------------
# Reviewed-input typing
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Flow:
    source_path: str
    relation_owner_symbol: str
    relation_call_line: int
    engine_owner_symbol: str
    engine_call_line: int
    schema_path: str
    schema_fragment: str | None
    activation_condition: str
    target_scope: str
    schema_binding_origin: str
    resolved_engine: str
    validator_draft: str
    format_checker_mode: str
    dependency_requirement: str
    missing_dependency_outcome: str
    schema_requirement: str
    missing_schema_outcome: str
    meta_guard_present: bool
    schema_path_definition_line: int | None
    schema_load_line: int | None


@dataclass(frozen=True)
class MetaFlow:
    source_path: str
    engine_owner_symbol: str
    engine_call_line: int
    schema_path: str
    followed_by_instance_validation: bool
    schema_binding_verification: str


def typed_value(name: str, value: str) -> Any:
    if name in {
        "relation_call_line", "engine_call_line",
        "schema_path_definition_line", "schema_load_line",
    }:
        return int(value) if value else None
    if name in {"meta_guard_present", "followed_by_instance_validation"}:
        return value == "1"
    if name == "schema_fragment":
        return value or None
    return value


def parse_rows(names: list[str], rows: list[str], kind: type) -> tuple:
    require(names == [item.name for item in fields(kind)], f"field mismatch: {names}")
    records = []
    for number, row in enumerate(rows):
        values = row.split("|")
        require(len(values) == len(names), f"row {number}: {len(values)} fields")
        records.append(kind(**{
            name: typed_value(name, value)
            for name, value in zip(names, values, strict=True)
        }))
    return tuple(records)


# ---------------------------------------------------------------------------
# Snapshot access (read-only, base-source-bound, isolated git env)
# ---------------------------------------------------------------------------
def git(repo: str, *args: str) -> str:
    env = dict(os.environ)
    env.update(
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_TERMINAL_PROMPT="0",
        LC_ALL="C",
    )
    return subprocess.run(
        ["git", "-C", repo, *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
        env=env,
    ).stdout


def inventory_sha(paths: list[str]) -> str:
    payload = "\n".join(sorted(set(paths))) + "\n"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_base_infer_facets(repo: str, base_sha: str):
    """Load ``infer_facets`` from the exact base snapshot.

    RepoGround 3 snapshots use the canonical path. Pre-3.0 snapshots are read
    from the documented legacy path; the source is never taken from the
    working tree and no identifier is rewritten.
    """
    source = None
    source_path = None
    for candidate in LENS_FACETS_PATHS:
        try:
            source = git(repo, "show", f"{base_sha}:{candidate}")
            source_path = candidate
            break
        except subprocess.CalledProcessError:
            continue
    require(source is not None and source_path is not None, "base snapshot lens_facets.py missing")
    label = f"{source_path}@{base_sha[:12]}"
    validate_base_import_policy(source, label)
    import types
    module = types.ModuleType("lens_facets_base")
    exec(compile(source, label, "exec"), module.__dict__)  # noqa: S102
    facets = getattr(module, "infer_facets", None)
    require(callable(facets), "base snapshot lens_facets.infer_facets missing")
    return facets


# ---------------------------------------------------------------------------
# Receiver-resolved jsonschema grammar
# ---------------------------------------------------------------------------
_BIND_JSONSCHEMA_MODULE = "jsonschema_module"
_BIND_OPTIONAL_JSONSCHEMA_MODULE = "optional_jsonschema_module"
_BIND_VALIDATE_FUNCTION = "validate_function"
_BIND_VALIDATOR_CONSTRUCTOR = "validator_constructor"
_BIND_VALIDATORS_MODULE = "validators_module"
_BIND_VALIDATOR_FOR = "validator_for"
_BIND_VALIDATOR_INSTANCE = "validator_instance"
_BIND_NONE = "none"
_BIND_UNKNOWN = "unknown"
_MODULE_BINDINGS = {_BIND_JSONSCHEMA_MODULE, _BIND_OPTIONAL_JSONSCHEMA_MODULE}


@dataclass
class _PendingFunction:
    node: ast.FunctionDef | ast.AsyncFunctionDef
    owners: tuple[str, ...]


@dataclass
class _Scope:
    kind: str
    bindings: dict[str, str]
    global_names: set[str]
    nonlocal_names: set[str]
    pending_functions: list[_PendingFunction] = field(default_factory=list)


class _LocalBinderCollector(ast.NodeVisitor):
    """Collect names local to one function without entering nested scopes."""

    def __init__(self) -> None:
        self.names: set[str] = set()
        self.global_names: set[str] = set()
        self.nonlocal_names: set[str] = set()

    def visit_Name(self, node: ast.Name) -> None:  # noqa: N802
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self.names.add(node.id)

    def visit_Import(self, node: ast.Import) -> None:  # noqa: N802
        for alias in node.names:
            self.names.add(alias.asname or alias.name.split(".", 1)[0])

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802
        for alias in node.names:
            if alias.name != "*":
                self.names.add(alias.asname or alias.name)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        self.names.add(node.name)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
        self.names.add(node.name)

    def visit_Lambda(self, node: ast.Lambda) -> None:  # noqa: N802
        return

    def visit_ListComp(self, node: ast.ListComp) -> None:  # noqa: N802
        return

    visit_SetComp = visit_ListComp
    visit_GeneratorExp = visit_ListComp

    def visit_DictComp(self, node: ast.DictComp) -> None:  # noqa: N802
        return

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:  # noqa: N802
        if node.name:
            self.names.add(node.name)
        for statement in node.body:
            self.visit(statement)

    def visit_Global(self, node: ast.Global) -> None:  # noqa: N802
        self.global_names.update(node.names)

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:  # noqa: N802
        self.nonlocal_names.update(node.names)

    def visit_MatchAs(self, node: ast.MatchAs) -> None:  # noqa: N802
        if node.name:
            self.names.add(node.name)
        if node.pattern is not None:
            self.visit(node.pattern)

    def visit_MatchStar(self, node: ast.MatchStar) -> None:  # noqa: N802
        if node.name:
            self.names.add(node.name)

    def visit_MatchMapping(self, node: ast.MatchMapping) -> None:  # noqa: N802
        if node.rest:
            self.names.add(node.rest)
        self.generic_visit(node)


def _argument_names(arguments: ast.arguments) -> set[str]:
    items = [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]
    names = {item.arg for item in items}
    if arguments.vararg is not None:
        names.add(arguments.vararg.arg)
    if arguments.kwarg is not None:
        names.add(arguments.kwarg.arg)
    return names


def _function_locals(
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda,
) -> tuple[set[str], set[str], set[str]]:
    collector = _LocalBinderCollector()
    if isinstance(node, ast.Lambda):
        collector.visit(node.body)
    else:
        for statement in node.body:
            collector.visit(statement)
    names = collector.names | _argument_names(node.args)
    names -= collector.global_names | collector.nonlocal_names
    return names, collector.global_names, collector.nonlocal_names


def _bound_names(target: ast.AST) -> set[str]:
    if isinstance(target, ast.Name):
        return {target.id}
    if isinstance(target, (ast.Tuple, ast.List)):
        return set().union(*(_bound_names(item) for item in target.elts))
    if isinstance(target, ast.Starred):
        return _bound_names(target.value)
    return set()


def _pattern_names(pattern: ast.pattern) -> set[str]:
    if isinstance(pattern, ast.MatchAs):
        names = {pattern.name} if pattern.name else set()
        if pattern.pattern is not None:
            names.update(_pattern_names(pattern.pattern))
        return names
    if isinstance(pattern, ast.MatchStar):
        return {pattern.name} if pattern.name else set()
    if isinstance(pattern, ast.MatchMapping):
        names = {pattern.rest} if pattern.rest else set()
        for item in pattern.patterns:
            names.update(_pattern_names(item))
        return names
    if isinstance(pattern, ast.MatchSequence):
        return set().union(*(_pattern_names(item) for item in pattern.patterns))
    if isinstance(pattern, ast.MatchClass):
        items = [*pattern.patterns, *pattern.kwd_patterns]
        return set().union(*(_pattern_names(item) for item in items))
    if isinstance(pattern, ast.MatchOr):
        return set().union(*(_pattern_names(item) for item in pattern.patterns))
    return set()


def _merge_binding(kinds: set[str | None]) -> str | None:
    if len(kinds) == 1:
        return next(iter(kinds))
    optional_parts = {
        _BIND_JSONSCHEMA_MODULE,
        _BIND_OPTIONAL_JSONSCHEMA_MODULE,
        _BIND_NONE,
    }
    if kinds <= optional_parts and _BIND_NONE in kinds and kinds & _MODULE_BINDINGS:
        return _BIND_OPTIONAL_JSONSCHEMA_MODULE
    if kinds == {None}:
        return None
    return _BIND_UNKNOWN


def _merge_environments(environments: list[dict[str, str]]) -> dict[str, str]:
    names = set().union(*(set(environment) for environment in environments))
    merged: dict[str, str] = {}
    for name in names:
        kind = _merge_binding({environment.get(name) for environment in environments})
        if kind is not None:
            merged[name] = kind
    return merged


def _block_terminates(statements: list[ast.stmt]) -> bool:
    if not statements:
        return False
    last = statements[-1]
    if isinstance(last, (ast.Return, ast.Raise)):
        return True
    if isinstance(last, ast.If) and last.orelse:
        return _block_terminates(last.body) and _block_terminates(last.orelse)
    return False


def validate_base_import_policy(source: str, path: str) -> None:
    """Fail closed if historical ``lens_facets`` could import live repo code."""
    tree = ast.parse(source, filename=path)
    allowed = set(sys.stdlib_module_names) | {"__future__"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            require(
                node.level == 0,
                f"base import policy: relative import in {path}:{node.lineno}",
            )
            modules = [node.module or ""]
            imported_loader = node.module == "importlib" and any(
                alias.name == "import_module" for alias in node.names
            )
            require(
                not imported_loader,
                f"base import policy: dynamic import binding in {path}:{node.lineno}",
            )
        else:
            modules = []
        for module in modules:
            root = module.split(".", 1)[0]
            require(
                root in allowed,
                f"base import policy: non-stdlib import {module!r} in {path}:{node.lineno}",
            )
        if isinstance(node, ast.Call):
            func = node.func
            dynamic = isinstance(func, ast.Name) and func.id == "__import__"
            dynamic = dynamic or (
                isinstance(func, ast.Attribute) and func.attr == "import_module"
            )
            require(
                not dynamic,
                f"base import policy: dynamic import in {path}:{node.lineno}",
            )


def analyze(source: str, path: str):
    """Return resolved engine, resolved meta, and unresolved candidate sets.

    The grammar is deliberately conservative. Bindings are tracked in source
    order and per lexical scope; ambiguous control-flow merges become unknown.
    Sets contain ``(owner_symbol, lineno)``; unresolved entries add a kind tag
    (``unresolved_engine`` / ``unresolved_meta``).
    """
    tree = ast.parse(source, filename=path)
    engines: set[tuple[str, int]] = set()
    metas: set[tuple[str, int]] = set()
    unresolved: set[tuple[str, int, str]] = set()

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.owners: list[str] = []
            self.scopes: list[_Scope] = [
                _Scope("module", {}, set(), set())
            ]

        @property
        def scope(self) -> _Scope:
            return self.scopes[-1]

        def owner(self) -> str:
            return ".".join(self.owners) if self.owners else "<module>"

        def visit_Module(self, node: ast.Module) -> None:  # noqa: N802
            self.visit_statements(node.body)
            self.visit_pending_functions()

        def visit_pending_functions(self) -> None:
            while self.scope.pending_functions:
                pending = self.scope.pending_functions.pop(0)
                self.analyze_function_body(pending)

        def analyze_function_body(self, pending: _PendingFunction) -> None:
            node = pending.node
            local_names, global_names, nonlocal_names = _function_locals(node)
            prior_owners = self.owners
            self.owners = list(pending.owners)
            self.scopes.append(_Scope(
                "function",
                {name: _BIND_UNKNOWN for name in local_names},
                global_names,
                nonlocal_names,
            ))
            self.visit_statements(node.body)
            self.visit_pending_functions()
            self.scopes.pop()
            self.owners = prior_owners

        def lookup(self, name: str) -> str | None:
            current = self.scope
            if current.kind == "function" and name in current.global_names:
                return self.scopes[0].bindings.get(name)
            if current.kind == "function" and name in current.nonlocal_names:
                for scope in reversed(self.scopes[:-1]):
                    if scope.kind == "function" and name in scope.bindings:
                        return scope.bindings[name]
                return None

            crossed_function = False
            for scope in reversed(self.scopes):
                if crossed_function and scope.kind == "class":
                    continue
                if name in scope.bindings:
                    return scope.bindings[name]
                if scope.kind == "function":
                    crossed_function = True
            return None

        def bind(self, name: str, kind: str) -> None:
            current = self.scope
            if current.kind == "function" and name in current.global_names:
                self.scopes[0].bindings[name] = _BIND_UNKNOWN
                return
            if current.kind == "function" and name in current.nonlocal_names:
                for scope in reversed(self.scopes[:-1]):
                    if scope.kind == "function" and name in scope.bindings:
                        scope.bindings[name] = _BIND_UNKNOWN
                        return
                current.bindings[name] = _BIND_UNKNOWN
                return
            current.bindings[name] = kind

        def expression_binding(self, node: ast.AST) -> str:
            if isinstance(node, ast.Name):
                return self.lookup(node.id) or _BIND_UNKNOWN
            if isinstance(node, ast.Constant) and node.value is None:
                return _BIND_NONE
            if isinstance(node, ast.Attribute):
                base = self.expression_binding(node.value)
                if base in _MODULE_BINDINGS:
                    if node.attr == "validate":
                        return _BIND_VALIDATE_FUNCTION
                    if node.attr in JSONSCHEMA_CONSTRUCTORS:
                        return _BIND_VALIDATOR_CONSTRUCTOR
                    if node.attr == "validators":
                        return _BIND_VALIDATORS_MODULE
                if base == _BIND_VALIDATORS_MODULE and node.attr == "validator_for":
                    return _BIND_VALIDATOR_FOR
                return _BIND_UNKNOWN
            if isinstance(node, ast.Call):
                callee = self.expression_binding(node.func)
                if callee == _BIND_VALIDATOR_FOR:
                    return _BIND_VALIDATOR_CONSTRUCTOR
                if callee == _BIND_VALIDATOR_CONSTRUCTOR:
                    return _BIND_VALIDATOR_INSTANCE
                return _BIND_UNKNOWN
            if isinstance(node, ast.IfExp):
                return _merge_binding({
                    self.expression_binding(node.body),
                    self.expression_binding(node.orelse),
                }) or _BIND_UNKNOWN
            return _BIND_UNKNOWN

        def assignment_binding(self, value: ast.AST) -> str:
            kind = self.expression_binding(value)
            if kind in {_BIND_VALIDATOR_INSTANCE, _BIND_NONE}:
                return kind
            return _BIND_UNKNOWN

        def visit_statements(self, statements: list[ast.stmt]) -> None:
            for statement in statements:
                self.visit(statement)

        def analyze_branch(
            self,
            statements: list[ast.stmt],
            baseline: dict[str, str],
        ) -> tuple[dict[str, str], bool]:
            self.scope.bindings = dict(baseline)
            self.visit_statements(statements)
            return dict(self.scope.bindings), _block_terminates(statements)

        def visit_Import(self, node: ast.Import) -> None:  # noqa: N802
            for alias in node.names:
                bound = alias.asname or alias.name.split(".", 1)[0]
                if alias.name == "jsonschema":
                    kind = _BIND_JSONSCHEMA_MODULE
                elif alias.name == "jsonschema.validators":
                    kind = (
                        _BIND_VALIDATORS_MODULE
                        if alias.asname
                        else _BIND_JSONSCHEMA_MODULE
                    )
                else:
                    kind = _BIND_UNKNOWN
                self.bind(bound, kind)

        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802
            for alias in node.names:
                if alias.name == "*":
                    continue
                bound = alias.asname or alias.name
                kind = _BIND_UNKNOWN
                if node.level == 0 and node.module == "jsonschema":
                    if alias.name == "validate":
                        kind = _BIND_VALIDATE_FUNCTION
                    elif alias.name in JSONSCHEMA_CONSTRUCTORS:
                        kind = _BIND_VALIDATOR_CONSTRUCTOR
                    elif alias.name == "validators":
                        kind = _BIND_VALIDATORS_MODULE
                elif node.level == 0 and node.module == "jsonschema.validators":
                    if alias.name == "validator_for":
                        kind = _BIND_VALIDATOR_FOR
                    elif alias.name in JSONSCHEMA_CONSTRUCTORS:
                        kind = _BIND_VALIDATOR_CONSTRUCTOR
                self.bind(bound, kind)

        def visit_Assign(self, node: ast.Assign) -> None:  # noqa: N802
            self.visit(node.value)
            kind = self.assignment_binding(node.value)
            for target in node.targets:
                names = _bound_names(target)
                target_kind = kind if isinstance(target, ast.Name) else _BIND_UNKNOWN
                for name in names:
                    self.bind(name, target_kind)

        def visit_AnnAssign(self, node: ast.AnnAssign) -> None:  # noqa: N802
            if node.annotation is not None:
                self.visit(node.annotation)
            if node.value is not None:
                self.visit(node.value)
                kind = self.assignment_binding(node.value)
            else:
                kind = _BIND_UNKNOWN
            for name in _bound_names(node.target):
                self.bind(name, kind if isinstance(node.target, ast.Name) else _BIND_UNKNOWN)

        def visit_AugAssign(self, node: ast.AugAssign) -> None:  # noqa: N802
            self.visit(node.value)
            for name in _bound_names(node.target):
                self.bind(name, _BIND_UNKNOWN)

        def visit_NamedExpr(self, node: ast.NamedExpr) -> None:  # noqa: N802
            self.visit(node.value)
            kind = self.assignment_binding(node.value)
            for name in _bound_names(node.target):
                self.bind(name, kind)

        def visit_Delete(self, node: ast.Delete) -> None:  # noqa: N802
            for target in node.targets:
                for name in _bound_names(target):
                    self.bind(name, _BIND_UNKNOWN)

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
            self._visit_function(node)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
            self._visit_function(node)

        def _visit_function(
            self,
            node: ast.FunctionDef | ast.AsyncFunctionDef,
        ) -> None:
            for decorator in node.decorator_list:
                self.visit(decorator)
            for default in [*node.args.defaults, *node.args.kw_defaults]:
                if default is not None:
                    self.visit(default)
            if node.returns is not None:
                self.visit(node.returns)
            arguments = [
                *node.args.posonlyargs,
                *node.args.args,
                *node.args.kwonlyargs,
            ]
            if node.args.vararg is not None:
                arguments.append(node.args.vararg)
            if node.args.kwarg is not None:
                arguments.append(node.args.kwarg)
            for argument in arguments:
                if argument.annotation is not None:
                    self.visit(argument.annotation)
            self.bind(node.name, _BIND_UNKNOWN)
            self.scope.pending_functions.append(
                _PendingFunction(node, tuple([*self.owners, node.name]))
            )

        def visit_Lambda(self, node: ast.Lambda) -> None:  # noqa: N802
            for default in [*node.args.defaults, *node.args.kw_defaults]:
                if default is not None:
                    self.visit(default)
            local_names, global_names, nonlocal_names = _function_locals(node)
            self.scopes.append(_Scope(
                "function",
                {name: _BIND_UNKNOWN for name in local_names},
                global_names,
                nonlocal_names,
            ))
            self.visit(node.body)
            self.scopes.pop()

        def _visit_comprehension(
            self,
            node: ast.ListComp | ast.SetComp | ast.GeneratorExp | ast.DictComp,
        ) -> None:
            generators = node.generators
            if not generators:
                return

            # Python evaluates the first iterable in the surrounding scope, then
            # creates an implicit nested scope for targets, filters and payload.
            self.visit(generators[0].iter)
            local_names = set().union(
                *(_bound_names(generator.target) for generator in generators)
            )
            self.scopes.append(_Scope(
                "function",
                {name: _BIND_UNKNOWN for name in local_names},
                set(),
                set(),
            ))
            for index, generator in enumerate(generators):
                if index:
                    self.visit(generator.iter)
                for name in _bound_names(generator.target):
                    self.bind(name, _BIND_UNKNOWN)
                for condition in generator.ifs:
                    self.visit(condition)
            if isinstance(node, ast.DictComp):
                self.visit(node.key)
                self.visit(node.value)
            else:
                self.visit(node.elt)
            self.scopes.pop()

        def visit_ListComp(self, node: ast.ListComp) -> None:  # noqa: N802
            self._visit_comprehension(node)

        def visit_SetComp(self, node: ast.SetComp) -> None:  # noqa: N802
            self._visit_comprehension(node)

        def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:  # noqa: N802
            self._visit_comprehension(node)

        def visit_DictComp(self, node: ast.DictComp) -> None:  # noqa: N802
            self._visit_comprehension(node)

        def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
            for decorator in node.decorator_list:
                self.visit(decorator)
            for base in node.bases:
                self.visit(base)
            for keyword in node.keywords:
                self.visit(keyword.value)
            self.bind(node.name, _BIND_UNKNOWN)

            self.owners.append(node.name)
            self.scopes.append(_Scope("class", {}, set(), set()))
            self.visit_statements(node.body)
            self.visit_pending_functions()
            self.scopes.pop()
            self.owners.pop()

        def visit_If(self, node: ast.If) -> None:  # noqa: N802
            self.visit(node.test)
            baseline = dict(self.scope.bindings)
            body, body_terminates = self.analyze_branch(node.body, baseline)
            if node.orelse:
                other, other_terminates = self.analyze_branch(node.orelse, baseline)
            else:
                other, other_terminates = baseline, False
            reachable = [
                environment
                for environment, terminates in (
                    (body, body_terminates),
                    (other, other_terminates),
                )
                if not terminates
            ]
            self.scope.bindings = (
                _merge_environments(reachable) if reachable else baseline
            )

        def visit_Try(self, node: ast.Try) -> None:  # noqa: N802
            baseline = dict(self.scope.bindings)
            body, body_terminates = self.analyze_branch(node.body, baseline)
            if not body_terminates and node.orelse:
                body, body_terminates = self.analyze_branch(node.orelse, body)
            paths: list[dict[str, str]] = []
            if not body_terminates:
                paths.append(body)
            for handler in node.handlers:
                handler_start = dict(baseline)
                self.scope.bindings = handler_start
                if handler.type is not None:
                    self.visit(handler.type)
                if handler.name:
                    self.bind(handler.name, _BIND_UNKNOWN)
                self.visit_statements(handler.body)
                if not _block_terminates(handler.body):
                    paths.append(dict(self.scope.bindings))
            if not paths:
                paths = [baseline]
            if node.finalbody:
                final_paths = []
                for environment in paths:
                    result, _ = self.analyze_branch(node.finalbody, environment)
                    final_paths.append(result)
                paths = final_paths
            self.scope.bindings = _merge_environments(paths)

        visit_TryStar = visit_Try

        def visit_For(self, node: ast.For) -> None:  # noqa: N802
            self._visit_loop(node, node.iter)

        def visit_AsyncFor(self, node: ast.AsyncFor) -> None:  # noqa: N802
            self._visit_loop(node, node.iter)

        def _visit_loop(self, node: ast.For | ast.AsyncFor, value: ast.AST) -> None:
            self.visit(value)
            baseline = dict(self.scope.bindings)
            self.scope.bindings = dict(baseline)
            for name in _bound_names(node.target):
                self.bind(name, _BIND_UNKNOWN)
            self.visit_statements(node.body)
            body = dict(self.scope.bindings)
            merged = _merge_environments([baseline, body])
            if node.orelse:
                other, _ = self.analyze_branch(node.orelse, merged)
                merged = other
            self.scope.bindings = merged

        def visit_While(self, node: ast.While) -> None:  # noqa: N802
            self.visit(node.test)
            baseline = dict(self.scope.bindings)
            body, _ = self.analyze_branch(node.body, baseline)
            merged = _merge_environments([baseline, body])
            if node.orelse:
                merged, _ = self.analyze_branch(node.orelse, merged)
            self.scope.bindings = merged

        def visit_With(self, node: ast.With) -> None:  # noqa: N802
            for item in node.items:
                self.visit(item.context_expr)
                if item.optional_vars is not None:
                    for name in _bound_names(item.optional_vars):
                        self.bind(name, _BIND_UNKNOWN)
            self.visit_statements(node.body)

        visit_AsyncWith = visit_With

        def visit_Match(self, node: ast.Match) -> None:  # noqa: N802
            self.visit(node.subject)
            baseline = dict(self.scope.bindings)
            paths = [baseline]
            for case in node.cases:
                self.scope.bindings = dict(baseline)
                for name in _pattern_names(case.pattern):
                    self.bind(name, _BIND_UNKNOWN)
                if case.guard is not None:
                    self.visit(case.guard)
                self.visit_statements(case.body)
                if not _block_terminates(case.body):
                    paths.append(dict(self.scope.bindings))
            self.scope.bindings = _merge_environments(paths)

        def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
            kind: str | None = None
            func = node.func
            if isinstance(func, ast.Name):
                if self.lookup(func.id) == _BIND_VALIDATE_FUNCTION:
                    kind = "engine"
            elif isinstance(func, ast.Attribute):
                receiver = self.expression_binding(func.value)
                if func.attr == "validate":
                    if receiver in _MODULE_BINDINGS | {_BIND_VALIDATOR_INSTANCE}:
                        kind = "engine"
                    else:
                        kind = "unresolved_engine"
                elif func.attr == "iter_errors":
                    if receiver == _BIND_VALIDATOR_INSTANCE:
                        kind = "engine"
                    else:
                        kind = "unresolved_engine"
                elif func.attr == "check_schema":
                    if receiver in (
                        _MODULE_BINDINGS
                        | {_BIND_VALIDATOR_CONSTRUCTOR, _BIND_VALIDATOR_INSTANCE}
                    ):
                        kind = "meta"
                    else:
                        kind = "unresolved_meta"
            if kind == "engine":
                engines.add((self.owner(), node.lineno))
            elif kind == "meta":
                metas.add((self.owner(), node.lineno))
            elif kind in {"unresolved_engine", "unresolved_meta"}:
                unresolved.add((self.owner(), node.lineno, kind))
            self.generic_visit(node)

    Visitor().visit(tree)
    return engines, metas, unresolved


def collect_relation_calls(source: str, path: str) -> set[tuple[str, int, str]]:
    """Return owner/line/callee triples for intra-source relation callsites."""
    tree = ast.parse(source, filename=path)
    calls: set[tuple[str, int, str]] = set()

    def callee_symbol(node: ast.AST) -> str | None:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return node.attr
        return None

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.owners: list[str] = []

        def owner(self) -> str:
            return ".".join(self.owners) if self.owners else "<module>"

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
            for decorator in node.decorator_list:
                self.visit(decorator)
            for default in [*node.args.defaults, *node.args.kw_defaults]:
                if default is not None:
                    self.visit(default)
            if node.returns is not None:
                self.visit(node.returns)
            self.owners.append(node.name)
            self.visit_statements(node.body)
            self.owners.pop()

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_statements(self, statements: list[ast.stmt]) -> None:
            for statement in statements:
                self.visit(statement)

        def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
            for decorator in node.decorator_list:
                self.visit(decorator)
            for base in node.bases:
                self.visit(base)
            for keyword in node.keywords:
                self.visit(keyword.value)
            self.owners.append(node.name)
            self.visit_statements(node.body)
            self.owners.pop()

        def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
            symbol = callee_symbol(node.func)
            if symbol is not None:
                calls.add((self.owner(), node.lineno, symbol))
            self.generic_visit(node)

    Visitor().visit(tree)
    return calls


@dataclass(frozen=True)
class UnresolvedPartition:
    manual_engine: set[tuple[str, str, int]]
    manual_meta: set[tuple[str, str, int]]
    foreign_engine: set[tuple[str, str, int]]
    foreign_meta: set[tuple[str, str, int]]


def _unresolved_entry_key(entry: dict[str, Any]) -> tuple[str, str, int]:
    require(isinstance(entry, dict), "unresolved candidate disposition must be an object")
    try:
        source_path = entry["source_path"]
        owner_symbol = entry["owner_symbol"]
        call_line = entry["call_line"]
        disposition = entry["disposition"]
        reason = entry["reason"]
    except KeyError as exc:
        raise AuditError(f"unresolved candidate disposition missing {exc.args[0]}") from exc
    require(isinstance(source_path, str) and source_path, "unresolved candidate source_path invalid")
    require(isinstance(owner_symbol, str) and owner_symbol, "unresolved candidate owner_symbol invalid")
    require(isinstance(call_line, int), "unresolved candidate call_line invalid")
    require(
        disposition in {"manual_jsonschema", "foreign_non_jsonschema"},
        f"unresolved candidate disposition invalid: {disposition!r}",
    )
    require(isinstance(reason, str) and reason.strip(), "unresolved candidate reason invalid")
    return source_path, owner_symbol, call_line


def _legacy_unresolved_dispositions(
    candidates: set[tuple[str, str, int, str]],
    reviewed_engine: set[tuple[str, str, int]],
    reviewed_meta: set[tuple[str, str, int]],
) -> dict[str, list[dict[str, Any]]]:
    """Treat the historical manifest's reviewed unresolved callsites as manual.

    The legacy manifest predates explicit unresolved-candidate dispositions. This
    adapter does not bless new candidates: anything not already represented by a
    reviewed flow is left uncovered and still fails the partition gate.
    """
    engine: list[dict[str, Any]] = []
    meta: list[dict[str, Any]] = []
    for source_path, owner_symbol, call_line, kind in sorted(candidates):
        key = (source_path, owner_symbol, call_line)
        if kind == "unresolved_engine" and key in reviewed_engine:
            engine.append({
                "source_path": source_path,
                "owner_symbol": owner_symbol,
                "call_line": call_line,
                "disposition": "manual_jsonschema",
                "reason": "legacy reviewed flow manifest callsite",
            })
        elif kind == "unresolved_meta" and key in reviewed_meta:
            meta.append({
                "source_path": source_path,
                "owner_symbol": owner_symbol,
                "call_line": call_line,
                "disposition": "manual_jsonschema",
                "reason": "legacy reviewed meta manifest callsite",
            })
    return {"engine": engine, "meta": meta}


def partition_unresolved_candidates(
    candidates: set[tuple[str, str, int, str]],
    dispositions: dict[str, Any],
    *,
    reviewed_engine: set[tuple[str, str, int]],
    reviewed_meta: set[tuple[str, str, int]],
) -> UnresolvedPartition:
    require(isinstance(dispositions, dict), "unresolved candidate dispositions invalid")
    candidate_engine = {
        (source_path, owner_symbol, call_line)
        for source_path, owner_symbol, call_line, kind in candidates
        if kind == "unresolved_engine"
    }
    candidate_meta = {
        (source_path, owner_symbol, call_line)
        for source_path, owner_symbol, call_line, kind in candidates
        if kind == "unresolved_meta"
    }
    require(
        len(candidate_engine) + len(candidate_meta) == len(candidates),
        "unresolved candidate kind invalid",
    )

    manual_engine: set[tuple[str, str, int]] = set()
    manual_meta: set[tuple[str, str, int]] = set()
    foreign_engine: set[tuple[str, str, int]] = set()
    foreign_meta: set[tuple[str, str, int]] = set()

    observed: dict[str, set[tuple[str, str, int]]] = {"engine": set(), "meta": set()}
    for kind, reviewed, manual, foreign in (
        ("engine", reviewed_engine, manual_engine, foreign_engine),
        ("meta", reviewed_meta, manual_meta, foreign_meta),
    ):
        entries = dispositions.get(kind, [])
        require(isinstance(entries, list), f"unresolved candidate {kind} dispositions invalid")
        for entry in entries:
            key = _unresolved_entry_key(entry)
            require(
                key not in observed[kind],
                "unresolved candidate disposition duplicate",
            )
            observed[kind].add(key)
            if entry["disposition"] == "manual_jsonschema":
                require(
                    key in reviewed,
                    "manual_jsonschema disposition without reviewed flow",
                )
                manual.add(key)
            else:
                require(
                    key not in reviewed,
                    "foreign_non_jsonschema disposition overlaps reviewed flow",
                )
                foreign.add(key)

    require(
        observed["engine"] == candidate_engine and observed["meta"] == candidate_meta,
        "unresolved candidate disposition mismatch: "
        f"engine_only_candidates={sorted(candidate_engine - observed['engine'])} "
        f"engine_only_dispositions={sorted(observed['engine'] - candidate_engine)} "
        f"meta_only_candidates={sorted(candidate_meta - observed['meta'])} "
        f"meta_only_dispositions={sorted(observed['meta'] - candidate_meta)}",
    )
    return UnresolvedPartition(
        manual_engine=manual_engine,
        manual_meta=manual_meta,
        foreign_engine=foreign_engine,
        foreign_meta=foreign_meta,
    )


def negative_control_result_ok(
    exit_code: int,
    combined_output: str,
    expected_message: str,
) -> bool:
    return exit_code == 2 and expected_message in combined_output


# ---------------------------------------------------------------------------
# Derived helpers
# ---------------------------------------------------------------------------
def direct(flow: Flow) -> bool:
    return (flow.relation_owner_symbol == flow.engine_owner_symbol
            and flow.relation_call_line == flow.engine_call_line)


def semantic_key(flow: Flow) -> tuple[str, ...]:
    return (flow.source_path, flow.relation_owner_symbol, flow.engine_owner_symbol,
            flow.schema_path, flow.schema_fragment or "", flow.activation_condition,
            flow.target_scope)


def snapshot_key(flow: Flow) -> tuple[str, ...]:
    return (flow.source_path, flow.relation_owner_symbol, str(flow.relation_call_line),
            flow.engine_owner_symbol, str(flow.engine_call_line), flow.schema_path,
            flow.schema_fragment or "", flow.activation_condition, flow.target_scope)


def axis(flows: tuple[Flow, ...], name: str) -> dict[str, int]:
    return dict(sorted(Counter(str(getattr(f, name)) for f in flows).items()))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="base-source-bound validates_schema audit")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--manifest")
    args = parser.parse_args(argv)

    manifest_path = Path(args.manifest) if args.manifest else DEFAULT_MANIFEST
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    require(args.base_sha == manifest["base"], "base mismatch")

    tree_oid = git(args.repo, "rev-parse", f"{args.base_sha}^{{tree}}").strip()
    raw = git(args.repo, "ls-tree", "-r", "--name-only", args.base_sha).splitlines()
    paths = sorted(set(raw))
    require([len(paths), inventory_sha(paths)] == manifest["inv"], "inventory mismatch")

    infer_facets = load_base_infer_facets(args.repo, args.base_sha)

    def is_test(path: str) -> bool:
        return any(item.get("facet") == "test" for item in infer_facets(path))

    flows = parse_rows(manifest["fields"], manifest["flows"], Flow)
    meta = parse_rows(manifest["meta_fields"], manifest["meta"], MetaFlow)
    accepted = tuple(f for f in flows if f.target_scope == "in_repo")
    external = tuple(f for f in flows if f.target_scope != "in_repo")

    # ---- derive observations from the snapshot --------------------------
    resolved_engine: set[tuple[str, str, int]] = set()
    resolved_meta: set[tuple[str, str, int]] = set()
    unresolved_prod: set[tuple[str, str, int, str]] = set()
    relation_calls: set[tuple[str, str, int, str]] = set()
    test_resolved: set[str] = set()
    test_unresolved_only: set[str] = set()
    text_files: set[str] = set()
    parse_failures: set[str] = set()
    schema_files = sorted(p for p in paths if p.endswith(".schema.json"))

    for path in (p for p in paths if p.endswith(".py")):
        source = git(args.repo, "show", f"{args.base_sha}:{path}")
        if "jsonschema" in source:
            text_files.add(path)
        try:
            engines, metas, unresolved = analyze(source, path)
        except SyntaxError:
            parse_failures.add(path)
            continue
        relation_calls.update(
            (path, owner, line, callee)
            for owner, line, callee in collect_relation_calls(source, path)
        )
        if is_test(path):
            if engines:
                test_resolved.add(path)
            elif unresolved:
                test_unresolved_only.add(path)
            continue
        resolved_engine.update((path, owner, line) for owner, line in engines)
        resolved_meta.update((path, owner, line) for owner, line in metas)
        unresolved_prod.update((path, owner, line, kind) for owner, line, kind in unresolved)

    expected_parse_failure_rows = manifest.get("expected_parse_failures")
    require(
        isinstance(expected_parse_failure_rows, list)
        and all(isinstance(item, str) and item for item in expected_parse_failure_rows),
        "expected_parse_failures must be an explicit list of non-empty paths",
    )
    expected_parse_failures = set(expected_parse_failure_rows)
    require(
        len(expected_parse_failures) == len(expected_parse_failure_rows),
        "expected_parse_failures contains duplicates",
    )
    require(
        parse_failures == expected_parse_failures,
        f"parse failures: unexpected={sorted(parse_failures - expected_parse_failures)} "
        f"missing={sorted(expected_parse_failures - parse_failures)}",
    )

    # ---- reviewed callsite sets ----------------------------------------
    reviewed_engine = {(f.source_path, f.engine_owner_symbol, f.engine_call_line) for f in flows}
    reviewed_meta = {(m.source_path, m.engine_owner_symbol, m.engine_call_line) for m in meta}

    # Every unresolved production candidate requires an explicit disposition.
    unresolved_dispositions = manifest.get("unresolved_candidates")
    require(
        unresolved_dispositions is not None,
        "unresolved_candidates must be explicit",
    )
    unresolved_partition = partition_unresolved_candidates(
        unresolved_prod,
        unresolved_dispositions,
        reviewed_engine=reviewed_engine,
        reviewed_meta=reviewed_meta,
    )
    manual_engine = unresolved_partition.manual_engine
    manual_meta = unresolved_partition.manual_meta
    proven_engine = resolved_engine | manual_engine

    # ---- falsifiable comparison gate -----------------------------------
    reviewed_relation = {
        (
            f.source_path,
            f.relation_owner_symbol,
            f.relation_call_line,
            f.engine_owner_symbol,
            f.engine_call_line,
        )
        for f in flows
    }
    derived_relation = set()
    for flow in flows:
        engine_key = (
            flow.source_path,
            flow.engine_owner_symbol,
            flow.engine_call_line,
        )
        relation_key = (
            flow.source_path,
            flow.relation_owner_symbol,
            flow.relation_call_line,
            flow.engine_owner_symbol,
            flow.engine_call_line,
        )
        if direct(flow):
            if engine_key in proven_engine:
                derived_relation.add(relation_key)
        elif (
            engine_key in proven_engine
            and (
                flow.source_path,
                flow.relation_owner_symbol,
                flow.relation_call_line,
                flow.engine_owner_symbol,
            )
            in relation_calls
        ):
            derived_relation.add(relation_key)
    require(
        derived_relation == reviewed_relation,
        "relation callsite mismatch: "
        f"only_review={sorted(reviewed_relation - derived_relation)} "
        f"only_ast={sorted(derived_relation - reviewed_relation)}",
    )

    # Every reviewed engine callsite must be corroborated by the snapshot AST at
    # the exact (path, owner, line): either receiver-resolved or flagged as an
    # unresolved candidate. A wrong line, a missing row, an extra row or a *new*
    # unresolved candidate all break this exact-equality gate.
    require(
        proven_engine == reviewed_engine,
        "engine callsite mismatch: "
        f"only_review={sorted(reviewed_engine - proven_engine)} "
        f"only_ast={sorted(proven_engine - reviewed_engine)}",
    )
    require(
        resolved_meta | manual_meta == reviewed_meta,
        "meta callsite mismatch: "
        f"only_review={sorted(reviewed_meta - (resolved_meta | manual_meta))} "
        f"only_ast={sorted((resolved_meta | manual_meta) - reviewed_meta)}",
    )

    # text-only candidate explanation must stay exhaustive
    engine_files = {p for p, _, _ in resolved_engine} | {p for p, _, _ in manual_engine}
    non_test_text = {p for p in text_files if not is_test(p)}
    require(
        non_test_text - engine_files == set(manifest["text_only"]),
        "text-only candidate mismatch: "
        f"{sorted((non_test_text - engine_files) ^ set(manifest['text_only']))}",
    )

    # ---- derive schema coverage (no hard-coded totals) -----------------
    in_repo_schema_targets = sorted({f.schema_path for f in accepted})
    require(all(s in set(paths) for s in in_repo_schema_targets), "schema target missing from tree")
    schemas_with_relation = sorted(set(schema_files) & set(in_repo_schema_targets))
    schemas_without_relation = sorted(set(schema_files) - set(schemas_with_relation))

    # ---- derive aggregates ---------------------------------------------
    summary = {
        "accepted_flows": len(accepted),
        "engine_callsites": len(reviewed_engine),
        "external_flows": len(external),
        "meta_callsites": len(reviewed_meta),
        "meta_flows": len(meta),
        "module_schema_targets": len({(f.source_path, f.schema_path) for f in accepted}),
        "modules": len({f.source_path for f in accepted}),
        "schema_files": len(schema_files),
        "schema_targets": len(in_repo_schema_targets),
        "schemas_without_relation": len(schemas_without_relation),
        "semantic_keys": len({semantic_key(f) for f in accepted}),
        "test_files": len(test_resolved | test_unresolved_only),
    }
    if "summary" in manifest:  # bootstrap safety vs the prior committed shape
        require(summary == manifest["summary"], f"summary mismatch: {summary}")
    require(len({snapshot_key(f) for f in accepted}) == len(accepted), "snapshot keys not unique")

    axes = {
        "engine_invocation": dict(sorted(Counter(
            "direct" if direct(f) else "delegated" for f in accepted).items())),
        **{name: axis(accepted, name) for name in (
            "activation_condition", "dependency_requirement", "format_checker_mode",
            "missing_dependency_outcome", "missing_schema_outcome", "resolved_engine",
            "schema_binding_origin", "schema_requirement", "target_scope", "validator_draft",
        )},
    }

    derived = {
        "snapshot_tree_oid": tree_oid,
        "generated_from_historical_snapshot": True,
        "current_head_not_assessed": True,
        "runtime_execution_not_proven": True,
        "provenance": {
            "engine_callsites_derived_ast": len(resolved_engine),
            "engine_callsites_manual_source_review": len(manual_engine),
            "meta_callsites_derived_ast": len(resolved_meta),
            "meta_callsites_manual_source_review": len(manual_meta),
        },
        "engine_callsites": {
            "derived_ast": sorted(f"{p}|{o}|{ln}" for p, o, ln in resolved_engine),
            "manual_source_review": sorted(f"{p}|{o}|{ln}" for p, o, ln in manual_engine),
        },
        "meta_callsites": {
            "derived_ast": sorted(f"{p}|{o}|{ln}" for p, o, ln in resolved_meta),
            "manual_source_review": sorted(f"{p}|{o}|{ln}" for p, o, ln in manual_meta),
        },
        "schema_coverage": {
            "total": len(schema_files),
            "with_accepted_relation": len(schemas_with_relation),
            "without_accepted_relation": len(schemas_without_relation),
            "with_accepted_relation_files": schemas_with_relation,
            "without_accepted_relation_files": schemas_without_relation,
        },
        "test_inventory": {
            "classification": "base-snapshot lens_facets.infer_facets (facet == 'test')",
            "resolved_engine_count": len(test_resolved),
            "unresolved_only_count": len(test_unresolved_only),
            "union_count": len(test_resolved | test_unresolved_only),
            "resolved_engine_files": sorted(test_resolved),
            "unresolved_only_files": sorted(test_unresolved_only),
        },
        "parse_failures": sorted(parse_failures),
        "axes": axes,
        "summary": summary,
        "checks": [
            "base_bound_infer_facets",
            "base_infer_facets_stdlib_import_guard",
            "scope_and_source_order_binding_grammar",
            "receiver_resolved_grammar",
            "resolved_engine_subset_of_reviewed",
            "engine_coverage_resolved_plus_manual_equals_reviewed",
            "no_new_unresolved_engine_candidate",
            "meta_coverage_resolved_plus_manual_equals_reviewed",
            "no_new_unresolved_meta_candidate",
            "text_only_exhaustive",
            "schema_targets_present_in_tree",
            "schema_coverage_closed",
            "summary_recomputed_from_flows",
            "snapshot_keys_unique",
        ],
        "limitations": [
            "Validators reached through a project-local loader or an unproven function parameter are manual_source_review, not derived_ast.",
            "Intermodular alias passing, dynamic wrappers and non-jsonschema validators are out of grammar.",
            "Historical lens_facets source is stdlib-import-only, but executes under the current Python interpreter and standard library.",
            "External (metarepo) schema targets are not resolved against any external snapshot.",
            "load_only / path_reference_only callsites are not inventoried.",
            "Runtime execution and current HEAD are not assessed.",
        ],
    }

    out = {k: manifest[k] for k in (
        "base", "inv", "grammar", "limits", "fields", "flows",
        "meta_fields", "meta", "text_only", "expected_parse_failures",
        "unresolved_candidates",
    ) if k in manifest}
    out["derived"] = derived

    Path(args.output).write_text(
        json.dumps(out, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    print(
        f"OK wrote {args.output}: {len(accepted)} in-repo flows, {len(external)} external; "
        f"engine derived {len(resolved_engine)} + manual {len(manual_engine)}; "
        f"meta derived {len(resolved_meta)} + manual {len(manual_meta)}; "
        f"tests resolved {len(test_resolved)} + unresolved-only {len(test_unresolved_only)}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AuditError as exc:
        print(f"STOP: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
