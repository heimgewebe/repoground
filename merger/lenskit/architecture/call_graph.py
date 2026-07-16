"""Deterministic, evidence-graded static Python call extraction.

The producer parses source text only. It records every ``ast.Call`` and resolves
only a deliberately small set of targets that are unique under the modelled
lexical bindings. Everything else remains explicit S0 navigation evidence.
"""
from __future__ import annotations

import ast
import os
from operator import attrgetter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

from merger.lenskit.architecture.call_graph_contract import (
    MAX_SKIPPED_ERRORS,
    PRODUCER_NONCLAIMS,
)
from merger.lenskit.architecture.symbol_index import (
    EXCLUDED_DIRS,
    _module_name,
    _range_ref,
    _symbol_id,
)

RESOLUTION_STATUSES = ("resolved", "candidate", "ambiguous", "unresolved")
EVIDENCE_LEVELS = ("S0", "S1")
RELATION_TYPES = ("calls", "constructs")
CALLER_KINDS = ("module", "class", "function", "async_function")
DOES_NOT_ESTABLISH = PRODUCER_NONCLAIMS

_FUNCTION_KINDS = ("function", "async_function")


@dataclass(frozen=True, slots=True)
class _ScopeFrame:
    """Immutable lexical-scope snapshot shared safely by recorded calls."""

    name: str | None
    kind: str
    local_bindings: frozenset[str] = field(default_factory=frozenset)
    global_names: frozenset[str] = field(default_factory=frozenset)
    nonlocal_names: frozenset[str] = field(default_factory=frozenset)
    start_line: int | None = None
    end_line: int | None = None
    receiver_name: str | None = None


class _ModuleState:
    """Per-module definitions, imports, bindings and unresolved raw calls."""

    def __init__(self, path: str, module: str) -> None:
        self.path = path
        self.module = module
        self.functions: dict[str, list[str]] = {}
        self.classes: dict[str, list[str]] = {}
        self.methods: dict[tuple[str, str], list[str]] = {}
        self.symbol_kinds: dict[str, str] = {}
        self.from_imports: dict[str, tuple[str, str]] = {}
        self.module_aliases: dict[str, str] = {}
        self.imported_module_names: set[str] = set()
        self.binding_sources: dict[str, set[str]] = {}
        self.calls: list[dict[str, Any]] = []

    def add_binding(self, name: str, source: str) -> None:
        self.binding_sources.setdefault(name, set()).add(source)

    def add_symbol(self, symbol_id: str, kind: str) -> None:
        self.symbol_kinds[symbol_id] = kind


def _relative_import_base(module: str, is_package: bool, level: int) -> str | None:
    parts = module.split(".") if module else []
    if not is_package:
        parts = parts[:-1]
    drop = level - 1
    if drop > len(parts):
        return None
    if drop:
        parts = parts[: len(parts) - drop]
    return ".".join(parts)


def _argument_names(arguments: ast.arguments) -> set[str]:
    names = {arg.arg for arg in (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs)}
    if arguments.vararg is not None:
        names.add(arguments.vararg.arg)
    if arguments.kwarg is not None:
        names.add(arguments.kwarg.arg)
    return names


class _BindingCollector(ast.NodeVisitor):
    """Collect bindings owned by one function, lambda, class or comprehension."""

    def __init__(self) -> None:
        self.local: set[str] = set()
        self.global_names: set[str] = set()
        self.nonlocal_names: set[str] = set()

    def visit_Name(self, node: ast.Name) -> Any:
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self.local.add(node.id)
        return None

    def visit_Global(self, node: ast.Global) -> Any:
        self.global_names.update(node.names)
        return None

    def visit_Nonlocal(self, node: ast.Nonlocal) -> Any:
        self.nonlocal_names.update(node.names)
        return None

    def visit_Import(self, node: ast.Import) -> Any:
        for alias in node.names:
            self.local.add(alias.asname or alias.name.split(".")[0])
        return None

    def visit_ImportFrom(self, node: ast.ImportFrom) -> Any:
        for alias in node.names:
            if alias.name != "*":
                self.local.add(alias.asname or alias.name)
        return None

    def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
        self.local.add(node.name)
        return None

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> Any:
        self.local.add(node.name)
        return None

    def visit_ClassDef(self, node: ast.ClassDef) -> Any:
        self.local.add(node.name)
        return None

    def visit_Lambda(self, node: ast.Lambda) -> Any:
        return None

    def visit_ListComp(self, node: ast.ListComp) -> Any:
        return None

    def visit_SetComp(self, node: ast.SetComp) -> Any:
        return None

    def visit_DictComp(self, node: ast.DictComp) -> Any:
        return None

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> Any:
        return None

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> Any:
        if isinstance(node.name, str):
            self.local.add(node.name)
        for statement in node.body:
            self.visit(statement)
        return None


def _function_frame(
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda,
    *,
    name: str | None,
    kind: str,
    receiver_name: str | None,
) -> _ScopeFrame:
    collector = _BindingCollector()
    collector.local.update(_argument_names(node.args))
    body: Iterable[ast.AST] = (node.body,) if isinstance(node, ast.Lambda) else node.body
    for statement in body:
        collector.visit(statement)
    collector.local.difference_update(collector.global_names)
    return _ScopeFrame(
        name=name,
        kind=kind,
        local_bindings=frozenset(collector.local),
        global_names=frozenset(collector.global_names),
        nonlocal_names=frozenset(collector.nonlocal_names),
        start_line=int(getattr(node, "lineno", 0) or 0) or None,
        end_line=int(getattr(node, "end_lineno", 0) or 0) or None,
        receiver_name=receiver_name,
    )


def _class_frame(node: ast.ClassDef) -> _ScopeFrame:
    collector = _BindingCollector()
    for statement in node.body:
        collector.visit(statement)
    return _ScopeFrame(
        name=node.name,
        kind="class",
        local_bindings=frozenset(collector.local),
        start_line=int(getattr(node, "lineno", 0) or 0) or None,
        end_line=int(getattr(node, "end_lineno", 0) or 0) or None,
    )


def _target_names(target: ast.AST) -> set[str]:
    return {
        child.id
        for child in ast.walk(target)
        if isinstance(child, ast.Name) and isinstance(child.ctx, (ast.Store, ast.Del))
    }


class _CallGraphVisitor(ast.NodeVisitor):
    def __init__(self, path: str, is_package: bool) -> None:
        self.state = _ModuleState(path, _module_name(path))
        self.is_package = is_package
        self.stack: list[_ScopeFrame] = []

    def _qualified(self, name: str) -> str:
        return ".".join([*(frame.name for frame in self.stack if frame.name), name])

    def _register_def(self, name: str, kind: str) -> None:
        qualified_name = self._qualified(name)
        symbol_id = _symbol_id(self.state.path, qualified_name, kind)
        self.state.add_symbol(symbol_id, kind)
        named_frames = [frame for frame in self.stack if frame.name]
        if not named_frames:
            self.state.add_binding(name, "def" if kind in _FUNCTION_KINDS else "class")
            table = self.state.functions if kind in _FUNCTION_KINDS else self.state.classes
            table.setdefault(name, []).append(symbol_id)
        elif kind in _FUNCTION_KINDS and named_frames[-1].kind == "class":
            class_qualified = ".".join(frame.name for frame in named_frames if frame.name)
            self.state.methods.setdefault((class_qualified, name), []).append(symbol_id)

    def _visit_present(self, nodes: Iterable[ast.AST | None]) -> None:
        for child in nodes:
            if child is not None:
                self.visit(child)

    def _visit_function_header(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        arguments = (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)
        optional_nodes = (
            *node.args.kw_defaults,
            *map(attrgetter("annotation"), arguments),
            getattr(node.args.vararg, "annotation", None),
            getattr(node.args.kwarg, "annotation", None),
            node.returns,
        )
        self._visit_present(node.decorator_list)
        self._visit_present(node.args.defaults)
        self._visit_present(optional_nodes)
        self._visit_present(getattr(node, "type_params", ()))

    def _direct_method_receiver(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
        if not self.stack or self.stack[-1].kind != "class":
            return None
        positional = (*node.args.posonlyargs, *node.args.args)
        return positional[0].arg if positional else None

    def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
        self._register_def(node.name, "function")
        self._visit_function_header(node)
        frame = _function_frame(
            node,
            name=node.name,
            kind="function",
            receiver_name=self._direct_method_receiver(node),
        )
        self.stack.append(frame)
        for statement in node.body:
            self.visit(statement)
        self.stack.pop()
        return None

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> Any:
        self._register_def(node.name, "async_function")
        self._visit_function_header(node)
        frame = _function_frame(
            node,
            name=node.name,
            kind="async_function",
            receiver_name=self._direct_method_receiver(node),
        )
        self.stack.append(frame)
        for statement in node.body:
            self.visit(statement)
        self.stack.pop()
        return None

    def visit_ClassDef(self, node: ast.ClassDef) -> Any:
        self._register_def(node.name, "class")
        for decorator in node.decorator_list:
            self.visit(decorator)
        for base in node.bases:
            self.visit(base)
        for keyword in node.keywords:
            self.visit(keyword.value)
        for type_param in getattr(node, "type_params", ()):
            self.visit(type_param)
        self.stack.append(_class_frame(node))
        for statement in node.body:
            self.visit(statement)
        self.stack.pop()
        return None

    def visit_Lambda(self, node: ast.Lambda) -> Any:
        self.stack.append(
            _function_frame(node, name=None, kind="lambda", receiver_name=None)
        )
        self.visit(node.body)
        self.stack.pop()
        return None

    def _visit_comprehension(
        self,
        node: ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp,
    ) -> None:
        generators = node.generators
        if not generators:
            return

        # Python evaluates the outermost iterable before entering the implicit
        # comprehension scope. Later iterables see only targets bound by earlier
        # generators; nested comprehensions create their own frames when visited.
        self.visit(generators[0].iter)
        local: set[str] = set()
        self.stack.append(_ScopeFrame(name=None, kind="comprehension"))
        try:
            for index, generator in enumerate(generators):
                if index:
                    self.visit(generator.iter)
                local.update(_target_names(generator.target))
                self.stack[-1] = _ScopeFrame(
                    name=None,
                    kind="comprehension",
                    local_bindings=frozenset(local),
                )
                self.visit(generator.target)
                for condition in generator.ifs:
                    self.visit(condition)

            if isinstance(node, ast.DictComp):
                self.visit(node.key)
                self.visit(node.value)
            else:
                self.visit(node.elt)
        finally:
            self.stack.pop()

    def visit_ListComp(self, node: ast.ListComp) -> Any:
        self._visit_comprehension(node)
        return None

    def visit_SetComp(self, node: ast.SetComp) -> Any:
        self._visit_comprehension(node)
        return None

    def visit_DictComp(self, node: ast.DictComp) -> Any:
        self._visit_comprehension(node)
        return None

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> Any:
        self._visit_comprehension(node)
        return None

    def visit_Import(self, node: ast.Import) -> Any:
        if not self.stack:
            for alias in node.names:
                if alias.asname:
                    self.state.module_aliases[alias.asname] = alias.name
                    self.state.add_binding(alias.asname, "import")
                else:
                    self.state.imported_module_names.add(alias.name)
                    self.state.add_binding(alias.name.split(".")[0], "import")
        return None

    def visit_ImportFrom(self, node: ast.ImportFrom) -> Any:
        if not self.stack:
            if node.level:
                base = _relative_import_base(self.state.module, self.is_package, node.level)
                source = None if base is None else ".".join(
                    part for part in (base, node.module or "") if part
                )
            else:
                source = node.module
            for alias in node.names:
                if alias.name == "*":
                    continue
                local = alias.asname or alias.name
                self.state.add_binding(local, "import")
                if source:
                    self.state.from_imports[local] = (source, alias.name)
        return None

    def _bind_module_target(self, target: ast.expr) -> None:
        if isinstance(target, ast.Name):
            self.state.add_binding(target.id, "assign")
        elif isinstance(target, (ast.Tuple, ast.List)):
            for element in target.elts:
                self._bind_module_target(element)

    def visit_Assign(self, node: ast.Assign) -> Any:
        if not self.stack:
            for target in node.targets:
                self._bind_module_target(target)
        self.generic_visit(node)
        return None

    def visit_AnnAssign(self, node: ast.AnnAssign) -> Any:
        if not self.stack:
            self._bind_module_target(node.target)
        self.generic_visit(node)
        return None

    def visit_NamedExpr(self, node: ast.NamedExpr) -> Any:
        if not self.stack:
            self._bind_module_target(node.target)
        self.generic_visit(node)
        return None

    def visit_Call(self, node: ast.Call) -> Any:
        start_line = getattr(node, "lineno", None)
        if isinstance(start_line, int) and start_line >= 1:
            start_col = max(int(getattr(node, "col_offset", 0) or 0), 0)
            raw_end_line = getattr(node, "end_lineno", None)
            end_line = (
                raw_end_line
                if isinstance(raw_end_line, int) and raw_end_line >= start_line
                else start_line
            )
            raw_end_col = getattr(node, "end_col_offset", None)
            if isinstance(raw_end_col, int) and raw_end_col >= 0:
                end_col = raw_end_col
            else:
                end_col = start_col if end_line == start_line else 0
            if end_line == start_line and end_col < start_col:
                end_col = start_col
            self.state.calls.append(
                {
                    "start_line": start_line,
                    "start_col": start_col,
                    "end_line": end_line,
                    "end_col": end_col,
                    "func": node.func,
                    # The stack list changes while traversing; its frozen frames do not.
                    "stack": tuple(self.stack),
                }
            )
        self.generic_visit(node)
        return None


def _dotted_parts(node: ast.expr) -> list[str] | None:
    parts: list[str] = []
    current: ast.expr = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
        return list(reversed(parts))
    return None


def _named_frames(stack: Sequence[_ScopeFrame]) -> list[_ScopeFrame]:
    return [frame for frame in stack if frame.name and frame.kind in CALLER_KINDS]


def _caller_fields(path: str, stack: Sequence[_ScopeFrame]) -> dict[str, Any]:
    named = _named_frames(stack)
    if not named:
        return {
            "caller_scope": "module",
            "caller_symbol_id": None,
            "caller_qualified_name": None,
            "caller_kind": "module",
            "caller_start_line": None,
            "caller_end_line": None,
        }
    qualified_name = ".".join(frame.name for frame in named if frame.name)
    kind = named[-1].kind
    return {
        "caller_scope": "symbol",
        "caller_symbol_id": _symbol_id(path, qualified_name, kind),
        "caller_qualified_name": qualified_name,
        "caller_kind": kind,
        "caller_start_line": named[-1].start_line,
        "caller_end_line": named[-1].end_line,
    }


def _verdict(
    status: str,
    reason: str,
    *,
    resolved: list[str] | None = None,
    candidates: list[str] | None = None,
    relation_type: str = "calls",
) -> dict[str, Any]:
    return {
        "relation_type": relation_type,
        "evidence_level": "S1" if status == "resolved" else "S0",
        "resolution_status": status,
        "resolution_reason": reason,
        "resolved_target_ids": sorted(set(resolved or [])),
        "candidate_target_ids": sorted(set(candidates or [])),
    }


class _Resolver:
    """Apply only unique static bindings; uncertainty stays visible as S0."""

    def __init__(self, modules: dict[str, list[_ModuleState]]) -> None:
        self.modules = modules

    def _target_in_module(self, module: str, name: str, reason_prefix: str) -> dict[str, Any]:
        states = self.modules.get(module, [])
        if not states:
            return _verdict("unresolved", f"{reason_prefix}_foreign_module")
        functions = [
            symbol_id
            for state in states
            for symbol_id in state.functions.get(name, [])
        ]
        classes = [
            symbol_id
            for state in states
            for symbol_id in state.classes.get(name, [])
        ]
        all_targets = sorted(set(functions) | set(classes))
        definition_count = len(functions) + len(classes)
        if len(states) > 1:
            return _verdict(
                "ambiguous",
                f"{reason_prefix}_module_collision",
                candidates=all_targets,
            )
        if definition_count == 1:
            target_id = all_targets[0]
            relation_type = "constructs" if classes else "calls"
            return _verdict(
                "resolved",
                reason_prefix,
                resolved=[target_id],
                relation_type=relation_type,
            )
        if definition_count > 1:
            return _verdict(
                "ambiguous",
                f"{reason_prefix}_multiple_definitions",
                candidates=all_targets,
            )
        return _verdict("unresolved", f"{reason_prefix}_name_not_found")

    def _shadow_reason(
        self, name: str, stack: Sequence[_ScopeFrame]
    ) -> tuple[str | None, bool]:
        inside_function = False
        for frame in reversed(stack):
            if frame.kind in (*_FUNCTION_KINDS, "lambda"):
                inside_function = True
                if name in frame.global_names:
                    return None, True
                if name in frame.nonlocal_names:
                    return "nonlocal_binding", False
                if name in frame.local_bindings:
                    return "lexically_shadowed_name", False
            elif frame.kind == "comprehension" and name in frame.local_bindings:
                return "comprehension_binding", False
            elif frame.kind == "class" and not inside_function and name in frame.local_bindings:
                return "class_scope_binding", False
        return None, False

    def _recursive_target(
        self, state: _ModuleState, name: str, stack: Sequence[_ScopeFrame]
    ) -> dict[str, Any] | None:
        for depth in range(len(stack), 0, -1):
            frame = stack[depth - 1]
            if frame.kind not in _FUNCTION_KINDS or frame.name != name:
                continue
            named = _named_frames(stack[:depth])
            # Bare-name recursion is safe in v1 only for one uniquely bound
            # top-level function. Inside methods, ``foo()`` is a global lookup,
            # and repeated module definitions can rebind the name at runtime.
            if len(named) != 1:
                return None
            targets = state.functions.get(name, [])
            if state.binding_sources.get(name, set()) != {"def"} or len(targets) != 1:
                return None
            qualified = named[0].name
            target_id = _symbol_id(state.path, qualified, frame.kind)
            if targets[0] != target_id:
                return None
            return _verdict(
                "resolved",
                "direct_recursion",
                resolved=[target_id],
            )
        return None

    def _imported_binding_candidates(
        self, imported: tuple[str, str] | None
    ) -> set[str]:
        if imported is None:
            return set()
        module, name = imported
        return {
            symbol_id
            for imported_state in self.modules.get(module, [])
            for symbol_id in (
                *imported_state.functions.get(name, []),
                *imported_state.classes.get(name, []),
            )
        }

    def _multiple_binding_verdict(
        self, state: _ModuleState, name: str, candidates: list[str]
    ) -> dict[str, Any]:
        combined = sorted(
            set(candidates)
            | self._imported_binding_candidates(state.from_imports.get(name))
        )
        return _verdict(
            "ambiguous", "multiple_module_level_bindings", candidates=combined
        )

    def _local_binding_verdict(
        self, local_functions: list[str], local_classes: list[str]
    ) -> dict[str, Any]:
        candidates = sorted(set(local_functions) | set(local_classes))
        definition_count = len(local_functions) + len(local_classes)
        if definition_count == 1:
            relation_type = "constructs" if local_classes else "calls"
            reason = "local_class_constructor" if local_classes else "local_module_function"
            return _verdict(
                "resolved",
                reason,
                resolved=[candidates[0]],
                relation_type=relation_type,
            )
        if definition_count > 1:
            reason = (
                "local_module_function_multiple_definitions"
                if local_functions and not local_classes
                else "local_module_multiple_definitions"
            )
            return _verdict("ambiguous", reason, candidates=candidates)
        return _verdict("unresolved", "unknown_name")

    def _resolve_name(
        self, state: _ModuleState, name: str, stack: Sequence[_ScopeFrame]
    ) -> dict[str, Any]:
        shadow_reason, force_module = self._shadow_reason(name, stack)
        if shadow_reason:
            return _verdict("unresolved", shadow_reason)
        if not force_module:
            recursive = self._recursive_target(state, name, stack)
            if recursive is not None:
                return recursive

        sources = state.binding_sources.get(name, set())
        local_functions = state.functions.get(name, [])
        local_classes = state.classes.get(name, [])
        candidates = sorted(set(local_functions) | set(local_classes))
        if "assign" in sources:
            status = "candidate" if candidates else "unresolved"
            return _verdict(status, "name_rebound_at_module_level", candidates=candidates)
        if len(sources) > 1:
            return self._multiple_binding_verdict(state, name, candidates)
        if name in state.from_imports:
            source_module, original = state.from_imports[name]
            return self._target_in_module(source_module, original, "imported_internal_name")
        if "import" in sources:
            return _verdict("unresolved", "module_object_called")
        return self._local_binding_verdict(local_functions, local_classes)

    def _direct_method_context(
        self, root: str, stack: Sequence[_ScopeFrame]
    ) -> tuple[_ScopeFrame, _ScopeFrame] | None:
        function_index: int | None = None
        for index in range(len(stack) - 1, -1, -1):
            frame = stack[index]
            if frame.kind in (*_FUNCTION_KINDS, "lambda"):
                function_index = index
                break
        if function_index is None:
            return None
        method = stack[function_index]
        if method.kind not in _FUNCTION_KINDS or method.receiver_name != root:
            return None
        if function_index == 0 or stack[function_index - 1].kind != "class":
            return None
        return method, stack[function_index - 1]

    def _resolve_receiver_dotted(
        self, state: _ModuleState, parts: list[str], stack: Sequence[_ScopeFrame]
    ) -> dict[str, Any]:
        if len(parts) != 2:
            return _verdict("unresolved", "nested_receiver_attribute_call")
        context = self._direct_method_context(parts[0], stack)
        if context is None:
            return _verdict("unresolved", "receiver_not_direct_method_parameter")
        _, class_frame = context
        class_index = next(
            index for index, frame in enumerate(stack) if frame is class_frame
        )
        class_named = _named_frames(stack[: class_index + 1])
        class_qualified = ".".join(frame.name for frame in class_named if frame.name)
        methods = state.methods.get((class_qualified, parts[1]), [])
        if len(methods) == 1:
            return _verdict(
                "resolved", f"{parts[0]}_method_same_class", resolved=methods
            )
        if len(methods) > 1:
            return _verdict(
                "ambiguous",
                "method_multiple_definitions_in_same_class",
                candidates=methods,
            )
        return _verdict("unresolved", "method_not_defined_in_same_class")

    def _resolve_module_dotted(
        self, state: _ModuleState, parts: list[str], stack: Sequence[_ScopeFrame]
    ) -> dict[str, Any]:
        shadow_reason, _ = self._shadow_reason(parts[0], stack)
        if shadow_reason:
            return _verdict("unresolved", f"attribute_root_{shadow_reason}")
        root_sources = state.binding_sources.get(parts[0], set())
        if "assign" in root_sources or len(root_sources) > 1:
            return _verdict("unresolved", "shadowed_attribute_root")
        module_alias = state.module_aliases.get(parts[0])
        if module_alias is not None:
            if len(parts) == 2:
                return self._target_in_module(
                    module_alias, parts[1], "module_alias_call"
                )
            return _verdict("unresolved", "nested_module_attribute")
        for split in range(len(parts) - 1, 0, -1):
            dotted = ".".join(parts[:split])
            if dotted in state.imported_module_names:
                if split == len(parts) - 1:
                    return self._target_in_module(
                        dotted, parts[-1], "module_alias_call"
                    )
                return _verdict("unresolved", "nested_module_attribute")
        return _verdict("unresolved", "dynamic_attribute_call")

    def _resolve_dotted(
        self, state: _ModuleState, parts: list[str], stack: Sequence[_ScopeFrame]
    ) -> dict[str, Any]:
        if parts[0] in ("self", "cls"):
            return self._resolve_receiver_dotted(state, parts, stack)
        return self._resolve_module_dotted(state, parts, stack)

    def resolve(self, state: _ModuleState, raw_call: dict[str, Any]) -> dict[str, Any]:
        func = raw_call["func"]
        stack = raw_call["stack"]
        if isinstance(func, ast.Name):
            simple_name: str | None = func.id
            verdict = self._resolve_name(state, func.id, stack)
        else:
            parts = _dotted_parts(func)
            if parts is not None:
                simple_name = parts[-1]
                verdict = self._resolve_dotted(state, parts, stack)
            else:
                simple_name = func.attr if isinstance(func, ast.Attribute) else None
                verdict = _verdict("unresolved", "dynamic_callee_expression")
        record = {
            "path": state.path,
            "start_line": raw_call["start_line"],
            "start_col": raw_call["start_col"],
            "end_line": raw_call["end_line"],
            "end_col": raw_call["end_col"],
            "range_ref": _range_ref(state.path, raw_call["start_line"], raw_call["end_line"]),
            "callee_expression": ast.unparse(func),
            "simple_name": simple_name,
        }
        record.update(_caller_fields(state.path, stack))
        record.update(verdict)
        return record


def extract_python_calls(repo_root: Path) -> tuple[list[dict[str, Any]], int, list[str]]:
    """Return deterministic call records plus bounded parse diagnostics."""
    modules: dict[str, list[_ModuleState]] = {}
    skipped_files_count = 0
    skipped_errors: list[str] = []
    for root, dirs, files in os.walk(repo_root, topdown=True):
        dirs[:] = sorted(directory for directory in dirs if directory not in EXCLUDED_DIRS)
        for file_name in sorted(files):
            if not file_name.endswith(".py"):
                continue
            path = Path(root) / file_name
            rel_path = path.relative_to(repo_root).as_posix()
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except (OSError, SyntaxError, UnicodeDecodeError) as exc:
                skipped_files_count += 1
                if len(skipped_errors) < MAX_SKIPPED_ERRORS:
                    skipped_errors.append(
                        f"Failed to parse {rel_path}: {type(exc).__name__} - {exc}"
                    )
                continue
            visitor = _CallGraphVisitor(rel_path, is_package=file_name == "__init__.py")
            visitor.visit(tree)
            modules.setdefault(visitor.state.module, []).append(visitor.state)

    resolver = _Resolver(modules)
    calls = [
        resolver.resolve(state, raw_call)
        for module in sorted(modules)
        for state in sorted(modules[module], key=lambda item: item.path)
        for raw_call in state.calls
    ]
    calls.sort(
        key=lambda item: (
            item["path"],
            item["start_line"],
            item["start_col"],
            item["callee_expression"],
            item["caller_symbol_id"] or "",
        )
    )
    return calls, skipped_files_count, skipped_errors


def generate_call_graph_document(
    repo_root: Path, run_id: str, canonical_sha256: str
) -> dict[str, Any]:
    calls, skipped_count, skipped_errors = extract_python_calls(repo_root)
    resolution_counts = {status: 0 for status in RESOLUTION_STATUSES}
    evidence_counts = {level: 0 for level in EVIDENCE_LEVELS}
    relation_counts = {relation: 0 for relation in RELATION_TYPES}
    for call in calls:
        resolution_counts[call["resolution_status"]] += 1
        evidence_counts[call["evidence_level"]] += 1
        relation_counts[call["relation_type"]] += 1
    return {
        "kind": "lenskit.python_call_graph",
        "version": "1.0",
        "run_id": run_id,
        "canonical_dump_index_sha256": canonical_sha256,
        "language": "python",
        "evidence_model": {
            "S0": "syntactic call site whose target is candidate, ambiguous, shadowed or unresolved",
            "S1": "one unique local target resolved from modelled static bindings",
        },
        "resolution_statuses": list(RESOLUTION_STATUSES),
        "relation_types": list(RELATION_TYPES),
        "call_count": len(calls),
        "resolution_counts": resolution_counts,
        "evidence_counts": evidence_counts,
        "relation_counts": relation_counts,
        "calls": calls,
        "skipped_files_count": skipped_count,
        "skipped_errors": skipped_errors,
        "skipped_errors_total_count": skipped_count,
        "skipped_errors_truncated": skipped_count > len(skipped_errors),
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }
