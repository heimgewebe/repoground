"""Deterministic, evidence-graded static Python call extraction.

The producer parses source text only. It records every ``ast.Call`` and resolves
only a deliberately small set of targets that are unique under the modelled
lexical bindings. Everything else remains explicit S0 navigation evidence.
"""

from __future__ import annotations

import ast
import hashlib
import os
import sys
from dataclasses import dataclass, field, replace
from operator import attrgetter
from pathlib import Path
from threading import RLock
from typing import Any, Iterable, Iterator, Sequence

from merger.repoground.architecture.call_graph_contract import (
    MAX_SKIPPED_ERRORS,
    PRODUCER_NONCLAIMS,
)
from merger.repoground.architecture.symbol_index import (
    EXCLUDED_DIRS,
    _module_name,
    _range_ref,
    _symbol_id,
)

try:
    from concurrent.futures import ProcessPoolExecutor as _ProcessPoolExecutor
except ImportError:  # pragma: no cover - platform-dependent stdlib surface
    _ProcessPoolExecutor = None

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
    module_aliases: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    from_imports: tuple[tuple[str, str, str], ...] = field(default_factory=tuple)
    start_line: int | None = None
    end_line: int | None = None
    receiver_name: str | None = None
    receiver_aliases: tuple[str, ...] = field(default_factory=tuple)
    type_alias_name: str | None = None


@dataclass(frozen=True, slots=True)
class _RawCall:
    """Immutable handoff from AST collection to deterministic resolution."""

    start_line: int
    start_col: int
    end_line: int
    end_col: int
    func: ast.expr
    stack: tuple[_ScopeFrame, ...]


CALL_GRAPH_CACHE_SCHEMA_VERSION = 2
CALL_GRAPH_PRODUCER_VERSION = (
    f"python-call-graph-v1-cache-{CALL_GRAPH_CACHE_SCHEMA_VERSION}-"
    f"py{sys.version_info.major}.{sys.version_info.minor}"
)
DEFAULT_CALL_GRAPH_MAX_WORKERS = max(1, min(4, os.cpu_count() or 1))
DEFAULT_CALL_GRAPH_MAX_IN_FLIGHT_BYTES = 64 * 1024 * 1024
_MIN_PARALLEL_FILES = 8
_MIN_PARALLEL_BYTES = 128 * 1024


@dataclass(frozen=True, slots=True)
class _CachedRawCall:
    start_line: int
    start_col: int
    end_line: int
    end_col: int
    callee_expression: str
    stack: tuple[_ScopeFrame, ...]


@dataclass(frozen=True, slots=True)
class _ModuleSnapshot:
    path: str
    module: str
    functions: tuple[tuple[str, tuple[str, ...]], ...]
    classes: tuple[tuple[str, tuple[str, ...]], ...]
    class_bases: tuple[tuple[str, tuple[str, ...]], ...]
    methods: tuple[tuple[str, str, tuple[str, ...]], ...]
    symbol_kinds: tuple[tuple[str, str], ...]
    from_imports: tuple[tuple[str, str, str], ...]
    module_aliases: tuple[tuple[str, str], ...]
    imported_module_names: tuple[str, ...]
    star_imports: tuple[str, ...]
    has_module_getattr: bool
    binding_sources: tuple[tuple[str, tuple[str, ...]], ...]
    calls: tuple[_CachedRawCall, ...]


@dataclass(frozen=True, slots=True)
class _CallGraphCacheEntry:
    content_sha256: str
    producer_version: str
    snapshot: _ModuleSnapshot


@dataclass(slots=True)
class CallGraphBuildCache:
    """Process-local, input-bound cache of immutable per-file analysis snapshots."""

    _entries: dict[str, _CallGraphCacheEntry] = field(
        default_factory=dict, init=False, repr=False
    )
    _lock: Any = field(default_factory=RLock, init=False, repr=False, compare=False)

    def lookup(self, path: str, content_sha256: str) -> _ModuleSnapshot | None:
        with self._lock:
            entry = self._entries.get(path)
            if (
                entry is None
                or entry.content_sha256 != content_sha256
                or entry.producer_version != CALL_GRAPH_PRODUCER_VERSION
            ):
                return None
            return entry.snapshot

    def replace(self, entries: dict[str, _CallGraphCacheEntry]) -> None:
        with self._lock:
            self._entries = dict(entries)

    @property
    def entry_count(self) -> int:
        with self._lock:
            return len(self._entries)


_DEFAULT_BUILD_CACHE = CallGraphBuildCache()


@dataclass(frozen=True, slots=True)
class _PythonFileInput:
    path: Path
    relative_path: str
    content_sha256: str
    size_bytes: int
    is_package: bool


@dataclass(frozen=True, slots=True)
class _ParseOutcome:
    snapshot: _ModuleSnapshot | None
    error: str | None = None


class _ModuleState:
    """Per-module definitions, imports, bindings and unresolved raw calls."""

    def __init__(self, path: str, module: str) -> None:
        self.path = path
        self.module = module
        self.functions: dict[str, list[str]] = {}
        self.classes: dict[str, list[str]] = {}
        self.class_bases: dict[str, tuple[str, ...]] = {}
        self.methods: dict[tuple[str, str], list[str]] = {}
        self.symbol_kinds: dict[str, str] = {}
        self.from_imports: dict[str, tuple[str, str]] = {}
        self.module_aliases: dict[str, str] = {}
        self.imported_module_names: set[str] = set()
        self.star_imports: set[str] = set()
        self.has_module_getattr = False
        self.binding_sources: dict[str, set[str]] = {}
        self.calls: list[_RawCall] = []

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
    names = {
        arg.arg
        for arg in (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs)
    }
    if arguments.vararg is not None:
        names.add(arguments.vararg.arg)
    if arguments.kwarg is not None:
        names.add(arguments.kwarg.arg)
    return names


def _match_pattern_names(pattern: ast.pattern) -> set[str]:
    names: set[str] = set()
    for child in ast.walk(pattern):
        if isinstance(child, ast.MatchAs) and child.name:
            names.add(child.name)
        elif isinstance(child, ast.MatchStar) and child.name:
            names.add(child.name)
        elif isinstance(child, ast.MatchMapping) and child.rest:
            names.add(child.rest)
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

    def visit_TypeAlias(self, node: Any) -> Any:
        name = getattr(node, "name", None)
        if isinstance(name, ast.Name):
            self.local.add(name.id)
        for type_param in getattr(node, "type_params", ()):  # Python 3.12+
            if isinstance(type_param, ast.AST):
                self.visit(type_param)
        value = getattr(node, "value", None)
        if isinstance(value, ast.AST):
            self.visit(value)
        return None

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> Any:
        if isinstance(node.name, str):
            self.local.add(node.name)
        for statement in node.body:
            self.visit(statement)
        return None

    def visit_Match(self, node: ast.Match) -> Any:
        for case in node.cases:
            self.local.update(_match_pattern_names(case.pattern))
            if case.guard is not None:
                self.visit(case.guard)
            for statement in case.body:
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
    body: Iterable[ast.AST] = (
        (node.body,) if isinstance(node, ast.Lambda) else node.body
    )
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


def _type_parameter_names(type_params: Iterable[ast.AST]) -> set[str]:
    names: set[str] = set()
    for type_param in type_params:
        name = getattr(type_param, "name", None)
        if isinstance(name, str):
            names.add(name)
        elif isinstance(name, ast.Name):
            names.add(name.id)
    return names


def _match_pattern_is_irrefutable(pattern: ast.pattern) -> bool:
    if isinstance(pattern, ast.MatchAs):
        return pattern.pattern is None or _match_pattern_is_irrefutable(pattern.pattern)
    if isinstance(pattern, ast.MatchOr):
        return any(_match_pattern_is_irrefutable(item) for item in pattern.patterns)
    return False


def _match_is_exhaustive(node: ast.Match) -> bool:
    return any(
        case.guard is None and _match_pattern_is_irrefutable(case.pattern)
        for case in node.cases
    )


def _match_falls_through(node: ast.Match) -> bool:
    if not _match_is_exhaustive(node):
        return True
    for case in node.cases:
        if _statements_fall_through(case.body):
            return True
        if case.guard is None and _match_pattern_is_irrefutable(case.pattern):
            return False
    return False


def _statement_falls_through(statement: ast.stmt) -> bool:
    if isinstance(statement, (ast.Return, ast.Raise, ast.Break, ast.Continue)):
        return False
    if isinstance(statement, ast.If):
        return _statements_fall_through(statement.body) or _statements_fall_through(
            statement.orelse
        )
    if isinstance(statement, ast.Match):
        return _match_falls_through(statement)
    try_star_type = getattr(ast, "TryStar", None)
    if isinstance(statement, ast.Try) or (
        try_star_type is not None and isinstance(statement, try_star_type)
    ):
        if statement.finalbody and not _statements_fall_through(statement.finalbody):
            return False
        normal_path_falls_through = _statements_fall_through(
            statement.body
        ) and _statements_fall_through(statement.orelse)
        handler_falls_through = any(
            _statements_fall_through(handler.body) for handler in statement.handlers
        )
        return normal_path_falls_through or handler_falls_through
    if isinstance(statement, (ast.With, ast.AsyncWith)):
        return _statements_fall_through(statement.body)
    return True


def _statements_fall_through(statements: Sequence[ast.stmt]) -> bool:
    return all(_statement_falls_through(statement) for statement in statements)


def _type_alias_binding_reason(frame: _ScopeFrame, name: str) -> str:
    if name == frame.type_alias_name:
        return "type_alias_self_binding"
    return "type_parameter_binding"


class _CallGraphVisitor(ast.NodeVisitor):
    def __init__(self, path: str, is_package: bool) -> None:
        self.state = _ModuleState(path, _module_name(path))
        self.is_package = is_package
        self.stack: list[_ScopeFrame] = []
        self._loop_break_bindings: list[list[dict[str, tuple[str, ...]]]] = []
        self._loop_continue_bindings: list[list[dict[str, tuple[str, ...]]]] = []
        self._suppress_loop_exits = 0

    def _qualified(self, name: str) -> str:
        return ".".join([*(frame.name for frame in self.stack if frame.name), name])

    def _register_def(self, name: str, kind: str) -> None:
        qualified_name = self._qualified(name)
        symbol_id = _symbol_id(self.state.path, qualified_name, kind)
        self.state.add_symbol(symbol_id, kind)
        named_frames = [frame for frame in self.stack if frame.name]
        if not named_frames:
            if kind in _FUNCTION_KINDS and name == "__getattr__":
                self.state.has_module_getattr = True
            self.state.add_binding(name, "def" if kind in _FUNCTION_KINDS else "class")
            table = (
                self.state.functions if kind in _FUNCTION_KINDS else self.state.classes
            )
            table.setdefault(name, []).append(symbol_id)
        elif kind in _FUNCTION_KINDS and named_frames[-1].kind == "class":
            class_qualified = ".".join(
                frame.name for frame in named_frames if frame.name
            )
            self.state.methods.setdefault((class_qualified, name), []).append(symbol_id)

    def _visit_present(self, nodes: Iterable[ast.AST | None]) -> None:
        for child in nodes:
            if child is not None:
                self.visit(child)

    def _visit_function_header(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> None:
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

    def _direct_method_receiver(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> str | None:
        if not self.stack or self.stack[-1].kind != "class":
            return None
        positional = (*node.args.posonlyargs, *node.args.args)
        return positional[0].arg if positional else None

    def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
        self._register_def(node.name, "function")
        self._visit_function_header(node)
        self._invalidate_local_imports({node.name})
        frame = _function_frame(
            node,
            name=node.name,
            kind="function",
            receiver_name=self._direct_method_receiver(node),
        )
        self.stack.append(frame)
        self._visit_statement_list(node.body)
        self.stack.pop()
        return None

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> Any:
        self._register_def(node.name, "async_function")
        self._visit_function_header(node)
        self._invalidate_local_imports({node.name})
        frame = _function_frame(
            node,
            name=node.name,
            kind="async_function",
            receiver_name=self._direct_method_receiver(node),
        )
        self.stack.append(frame)
        self._visit_statement_list(node.body)
        self.stack.pop()
        return None

    def visit_ClassDef(self, node: ast.ClassDef) -> Any:
        is_top_level = not self.stack
        self._register_def(node.name, "class")
        if is_top_level:
            self.state.class_bases[node.name] = tuple(
                base.id if isinstance(base, ast.Name) else "<dynamic>"
                for base in node.bases
            )
        for decorator in node.decorator_list:
            self.visit(decorator)
        for base in node.bases:
            self.visit(base)
        for keyword in node.keywords:
            self.visit(keyword.value)
        for type_param in getattr(node, "type_params", ()):
            self.visit(type_param)
        self._invalidate_local_imports({node.name})
        self.stack.append(_class_frame(node))
        self._visit_statement_list(node.body)
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

        aliases = dict(self.stack[-1].module_aliases)
        imports = {
            local: (module, original)
            for local, module, original in self.stack[-1].from_imports
        }
        for alias in node.names:
            local = alias.asname or alias.name.split(".")[0]
            aliases[local] = alias.name if alias.asname else local
            imports.pop(local, None)
        self.stack[-1] = replace(
            self.stack[-1],
            module_aliases=tuple(sorted(aliases.items())),
            from_imports=tuple(
                sorted(
                    (local, module, original)
                    for local, (module, original) in imports.items()
                )
            ),
        )
        return None

    def visit_ImportFrom(self, node: ast.ImportFrom) -> Any:
        if node.level:
            base = _relative_import_base(self.state.module, self.is_package, node.level)
            source = (
                None
                if base is None
                else ".".join(part for part in (base, node.module or "") if part)
            )
        else:
            source = node.module
        if not self.stack:
            for alias in node.names:
                if alias.name == "*":
                    if source:
                        self.state.star_imports.add(source)
                    continue
                local = alias.asname or alias.name
                self.state.add_binding(local, "import")
                if source:
                    self.state.from_imports[local] = (source, alias.name)
            return None

        imports = {
            local: (module, original)
            for local, module, original in self.stack[-1].from_imports
        }
        aliases = dict(self.stack[-1].module_aliases)
        for alias in node.names:
            if alias.name == "*" or not source:
                continue
            local = alias.asname or alias.name
            imports[local] = (source, alias.name)
            aliases.pop(local, None)
        self.stack[-1] = replace(
            self.stack[-1],
            module_aliases=tuple(sorted(aliases.items())),
            from_imports=tuple(
                sorted(
                    (local, module, original)
                    for local, (module, original) in imports.items()
                )
            ),
        )
        return None

    def _invalidate_local_imports(self, names: set[str]) -> None:
        if not self.stack or not names:
            return
        frame = self.stack[-1]
        aliases = tuple(
            (local, module)
            for local, module in frame.module_aliases
            if local not in names
        )
        imports = tuple(
            (local, module, original)
            for local, module, original in frame.from_imports
            if local not in names
        )
        if aliases != frame.module_aliases or imports != frame.from_imports:
            self.stack[-1] = replace(
                frame,
                module_aliases=aliases,
                from_imports=imports,
            )

    def _local_import_bindings(self) -> dict[str, tuple[str, ...]]:
        if not self.stack:
            return {}
        frame = self.stack[-1]
        bindings = {local: ("module", module) for local, module in frame.module_aliases}
        bindings.update(
            {
                local: ("symbol", module, original)
                for local, module, original in frame.from_imports
            }
        )
        return bindings

    def _set_local_import_bindings(self, bindings: dict[str, tuple[str, ...]]) -> None:
        if not self.stack:
            return
        frame = self.stack[-1]
        self.stack[-1] = replace(
            frame,
            module_aliases=tuple(
                sorted(
                    (local, binding[1])
                    for local, binding in bindings.items()
                    if binding[0] == "module"
                )
            ),
            from_imports=tuple(
                sorted(
                    (local, binding[1], binding[2])
                    for local, binding in bindings.items()
                    if binding[0] == "symbol"
                )
            ),
        )

    @staticmethod
    def _intersect_import_bindings(
        *states: dict[str, tuple[str, ...]],
    ) -> dict[str, tuple[str, ...]]:
        if not states:
            return {}
        first, *rest = states
        return {
            name: binding
            for name, binding in first.items()
            if all(state.get(name) == binding for state in rest)
        }

    def _visit_unreachable_statement_list(self, statements: Sequence[ast.stmt]) -> None:
        imports_before = self._local_import_bindings()
        self._suppress_loop_exits += 1
        try:
            for statement in statements:
                self.visit(statement)
        finally:
            self._suppress_loop_exits -= 1
            self._set_local_import_bindings(imports_before)

    def _visit_statement_list(self, statements: Sequence[ast.stmt]) -> bool:
        for index, statement in enumerate(statements):
            self.visit(statement)
            if not _statement_falls_through(statement):
                self._visit_unreachable_statement_list(statements[index + 1 :])
                return False
        return True

    def _bind_or_invalidate_names(self, names: set[str]) -> None:
        if not names:
            return
        if self.stack:
            self._invalidate_local_imports(names)
            frame = self.stack[-1]
            receiver_aliases = tuple(
                alias for alias in frame.receiver_aliases if alias not in names
            )
            if receiver_aliases != frame.receiver_aliases:
                self.stack[-1] = replace(
                    frame, receiver_aliases=receiver_aliases
                )
            return
        for name in names:
            self.state.add_binding(name, "assign")

    def _bind_or_invalidate_targets(self, targets: Iterable[ast.expr]) -> None:
        target_list = tuple(targets)
        names = set().union(*(_target_names(target) for target in target_list))
        self._bind_or_invalidate_names(names)

    def _establish_receiver_aliases(
        self, targets: Iterable[ast.expr], value: ast.expr | None
    ) -> None:
        if not self.stack or value is None:
            return
        frame = self.stack[-1]
        if frame.kind not in _FUNCTION_KINDS or frame.receiver_name is None:
            return
        known_receivers = {frame.receiver_name, *frame.receiver_aliases}
        if not isinstance(value, ast.Name) or value.id not in known_receivers:
            return
        target_list = tuple(targets)
        if not target_list or not all(isinstance(target, ast.Name) for target in target_list):
            return
        aliases = set(frame.receiver_aliases)
        aliases.update(
            target.id
            for target in target_list
            if isinstance(target, ast.Name) and target.id != frame.receiver_name
        )
        self.stack[-1] = replace(
            frame, receiver_aliases=tuple(sorted(aliases))
        )

    def _bind_module_target(self, target: ast.expr) -> None:
        if isinstance(target, ast.Name):
            self.state.add_binding(target.id, "assign")
        elif isinstance(target, (ast.Tuple, ast.List)):
            for element in target.elts:
                self._bind_module_target(element)

    def visit_Assign(self, node: ast.Assign) -> Any:
        self.visit(node.value)
        for target in node.targets:
            self.visit(target)
        self._bind_or_invalidate_targets(node.targets)
        self._establish_receiver_aliases(node.targets, node.value)
        return None

    def visit_AnnAssign(self, node: ast.AnnAssign) -> Any:
        self.visit(node.annotation)
        if node.value is not None:
            self.visit(node.value)
        self.visit(node.target)
        self._bind_or_invalidate_targets((node.target,))
        self._establish_receiver_aliases((node.target,), node.value)
        return None

    def visit_AugAssign(self, node: ast.AugAssign) -> Any:
        self.visit(node.target)
        self.visit(node.value)
        self._bind_or_invalidate_targets((node.target,))
        return None

    def visit_NamedExpr(self, node: ast.NamedExpr) -> Any:
        self.visit(node.value)
        self.visit(node.target)
        self._bind_or_invalidate_targets((node.target,))
        self._establish_receiver_aliases((node.target,), node.value)
        return None

    def visit_Delete(self, node: ast.Delete) -> Any:
        for target in node.targets:
            self.visit(target)
        self._bind_or_invalidate_targets(node.targets)
        return None

    def visit_TypeAlias(self, node: Any) -> Any:
        name = getattr(node, "name", None)
        alias_name = name.id if isinstance(name, ast.Name) else None
        type_params = tuple(getattr(node, "type_params", ()))  # Python 3.12+
        visible_type_parameters: set[str] = set()
        for type_param in type_params:
            if isinstance(type_param, ast.AST):
                self.stack.append(
                    _ScopeFrame(
                        name=None,
                        kind="type_alias",
                        local_bindings=frozenset(visible_type_parameters),
                    )
                )
                try:
                    self.visit(type_param)
                finally:
                    self.stack.pop()
                visible_type_parameters.update(_type_parameter_names((type_param,)))
        value = getattr(node, "value", None)
        if isinstance(value, ast.AST):
            self.stack.append(
                _ScopeFrame(
                    name=None,
                    kind="type_alias",
                    local_bindings=frozenset(
                        visible_type_parameters
                        | ({alias_name} if alias_name is not None else set())
                    ),
                    type_alias_name=alias_name,
                )
            )
            try:
                self.visit(value)
            finally:
                self.stack.pop()
        if isinstance(name, ast.Name):
            self._bind_or_invalidate_names({name.id})
        return None

    def visit_If(self, node: ast.If) -> Any:
        self.visit(node.test)
        imports_before = self._local_import_bindings()

        body_falls_through = self._visit_statement_list(node.body)
        imports_after_body = self._local_import_bindings()

        self._set_local_import_bindings(imports_before)
        else_falls_through = self._visit_statement_list(node.orelse)
        imports_after_else = self._local_import_bindings()

        reachable_states = []
        if body_falls_through:
            reachable_states.append(imports_after_body)
        if else_falls_through:
            reachable_states.append(imports_after_else)
        self._set_local_import_bindings(
            self._intersect_import_bindings(*reachable_states)
        )
        return None

    @staticmethod
    def _binding_names_in_statements(statements: Iterable[ast.stmt]) -> set[str]:
        collector = _BindingCollector()
        for statement in statements:
            collector.visit(statement)
        return collector.local

    @staticmethod
    def _loop_exit_checkpoint(
        exit_stack: list[list[dict[str, tuple[str, ...]]]],
    ) -> tuple[list[dict[str, tuple[str, ...]]] | None, int]:
        if not exit_stack:
            return None, 0
        states = exit_stack[-1]
        return states, len(states)

    @staticmethod
    def _take_loop_exits_since(
        checkpoint: tuple[list[dict[str, tuple[str, ...]]] | None, int],
    ) -> list[dict[str, tuple[str, ...]]]:
        states, start = checkpoint
        if states is None:
            return []
        pending = list(states[start:])
        del states[start:]
        return pending

    @staticmethod
    def _bindings_without_names(
        bindings: dict[str, tuple[str, ...]],
        changed_names: set[str],
    ) -> dict[str, tuple[str, ...]]:
        return {
            name: binding
            for name, binding in bindings.items()
            if name not in changed_names
        }

    def _visit_try_handler(self, handler: ast.ExceptHandler) -> bool:
        if handler.type is not None:
            self.visit(handler.type)
        handler_names = {handler.name} if isinstance(handler.name, str) else set()
        self._bind_or_invalidate_names(handler_names)
        handler_falls_through = self._visit_statement_list(handler.body)
        self._bind_or_invalidate_names(handler_names)
        return handler_falls_through

    def _visit_try_handlers(
        self,
        handlers: Sequence[ast.ExceptHandler],
        handler_entry: dict[str, tuple[str, ...]],
    ) -> list[dict[str, tuple[str, ...]]]:
        normal_exit_states = []
        for handler in handlers:
            self._set_local_import_bindings(handler_entry)
            if self._visit_try_handler(handler):
                normal_exit_states.append(self._local_import_bindings())
        return normal_exit_states

    def _visit_try_else_path(
        self,
        statements: Sequence[ast.stmt],
        *,
        body_falls_through: bool,
        imports_after_body: dict[str, tuple[str, ...]],
    ) -> list[dict[str, tuple[str, ...]]]:
        self._set_local_import_bindings(imports_after_body)
        if not body_falls_through:
            self._visit_unreachable_statement_list(statements)
            return []
        if self._visit_statement_list(statements):
            return [self._local_import_bindings()]
        return []

    def _visit_try_except_else_paths(
        self,
        node: ast.Try | ast.TryStar,
        imports_before_try: dict[str, tuple[str, ...]],
    ) -> list[dict[str, tuple[str, ...]]]:
        body_falls_through = self._visit_statement_list(node.body)
        imports_after_body = self._local_import_bindings()
        handler_entry = self._bindings_without_names(
            imports_before_try,
            self._binding_names_in_statements(node.body),
        )
        normal_exit_states = self._visit_try_handlers(
            node.handlers,
            handler_entry,
        )
        normal_exit_states.extend(
            self._visit_try_else_path(
                node.orelse,
                body_falls_through=body_falls_through,
                imports_after_body=imports_after_body,
            )
        )
        return normal_exit_states

    def _exceptional_finally_entry(
        self,
        node: ast.Try | ast.TryStar,
        imports_before_try: dict[str, tuple[str, ...]],
    ) -> dict[str, tuple[str, ...]]:
        changed_before_finally = self._binding_names_in_statements(
            [
                *node.body,
                *(statement for handler in node.handlers for statement in handler.body),
                *node.orelse,
            ]
        )
        changed_before_finally.update(
            handler.name for handler in node.handlers if isinstance(handler.name, str)
        )
        return self._bindings_without_names(
            imports_before_try,
            changed_before_finally,
        )

    @staticmethod
    def _apply_finally_bindings(
        imports: dict[str, tuple[str, ...]],
        imports_after_finally: dict[str, tuple[str, ...]],
        changed_names: set[str],
    ) -> dict[str, tuple[str, ...]]:
        result = {
            local: binding
            for local, binding in imports.items()
            if local not in changed_names
        }
        result.update(
            {
                local: binding
                for local, binding in imports_after_finally.items()
                if local in changed_names
            }
        )
        return result

    def _paths_after_finally(
        self,
        paths: Sequence[dict[str, tuple[str, ...]]],
        *,
        final_falls_through: bool,
        imports_after_finally: dict[str, tuple[str, ...]],
        changed_names: set[str],
    ) -> list[dict[str, tuple[str, ...]]]:
        if not final_falls_through:
            return []
        return [
            self._apply_finally_bindings(
                imports,
                imports_after_finally,
                changed_names,
            )
            for imports in paths
        ]

    @staticmethod
    def _restore_loop_exits_after_finally(
        checkpoint: tuple[list[dict[str, tuple[str, ...]]] | None, int],
        resumed_exits: Sequence[dict[str, tuple[str, ...]]],
    ) -> None:
        states, start = checkpoint
        if states is None:
            return
        exits_from_finally = list(states[start:])
        states[start:] = [*resumed_exits, *exits_from_finally]

    def _visit_try_finally_paths(
        self,
        node: ast.Try | ast.TryStar,
        *,
        imports_before_try: dict[str, tuple[str, ...]],
        normal_exit_states: Sequence[dict[str, tuple[str, ...]]],
        break_checkpoint: tuple[
            list[dict[str, tuple[str, ...]]] | None,
            int,
        ],
        continue_checkpoint: tuple[
            list[dict[str, tuple[str, ...]]] | None,
            int,
        ],
    ) -> None:
        pending_breaks = self._take_loop_exits_since(break_checkpoint)
        pending_continues = self._take_loop_exits_since(continue_checkpoint)
        finally_entry = self._intersect_import_bindings(
            *normal_exit_states,
            *pending_breaks,
            *pending_continues,
            self._exceptional_finally_entry(node, imports_before_try),
        )
        self._set_local_import_bindings(finally_entry)
        final_falls_through = self._visit_statement_list(node.finalbody)
        imports_after_finally = self._local_import_bindings()
        changed_names = self._binding_names_in_statements(node.finalbody)

        normal_after_finally = self._paths_after_finally(
            normal_exit_states,
            final_falls_through=final_falls_through,
            imports_after_finally=imports_after_finally,
            changed_names=changed_names,
        )
        self._set_local_import_bindings(
            self._intersect_import_bindings(*normal_after_finally)
        )
        breaks_after_finally = self._paths_after_finally(
            pending_breaks,
            final_falls_through=final_falls_through,
            imports_after_finally=imports_after_finally,
            changed_names=changed_names,
        )
        self._restore_loop_exits_after_finally(
            break_checkpoint,
            breaks_after_finally,
        )
        continues_after_finally = self._paths_after_finally(
            pending_continues,
            final_falls_through=final_falls_through,
            imports_after_finally=imports_after_finally,
            changed_names=changed_names,
        )
        self._restore_loop_exits_after_finally(
            continue_checkpoint,
            continues_after_finally,
        )

    def _visit_try_statement(self, node: ast.Try | ast.TryStar) -> None:
        imports_before_try = self._local_import_bindings()
        break_checkpoint = self._loop_exit_checkpoint(self._loop_break_bindings)
        continue_checkpoint = self._loop_exit_checkpoint(self._loop_continue_bindings)
        normal_exit_states = self._visit_try_except_else_paths(
            node,
            imports_before_try,
        )
        self._set_local_import_bindings(
            self._intersect_import_bindings(*normal_exit_states)
        )
        if node.finalbody:
            self._visit_try_finally_paths(
                node,
                imports_before_try=imports_before_try,
                normal_exit_states=normal_exit_states,
                break_checkpoint=break_checkpoint,
                continue_checkpoint=continue_checkpoint,
            )

    def visit_Try(self, node: ast.Try) -> Any:
        self._visit_try_statement(node)
        return None

    def visit_TryStar(self, node: ast.TryStar) -> Any:
        self._visit_try_statement(node)
        return None

    def _visit_for_statement(self, node: ast.For | ast.AsyncFor) -> None:
        self.visit(node.iter)
        imports_after_iter = self._local_import_bindings()
        self.visit(node.target)
        names = _target_names(node.target)
        self._bind_or_invalidate_names(names)
        self._loop_break_bindings.append([])
        self._loop_continue_bindings.append([])
        try:
            body_falls_through = self._visit_statement_list(node.body)
        finally:
            break_bindings = self._loop_break_bindings.pop()
            continue_bindings = self._loop_continue_bindings.pop()

        def without_target_names(
            state: dict[str, tuple[str, ...]],
        ) -> dict[str, tuple[str, ...]]:
            return {
                name: binding for name, binding in state.items() if name not in names
            }

        break_bindings = [
            without_target_names(break_state) for break_state in break_bindings
        ]
        continue_bindings = [
            without_target_names(continue_state) for continue_state in continue_bindings
        ]

        # The loop may execute zero times. A target-name reimport observed while
        # walking the body is not definite: it may be conditional, and another
        # iteration rebinds the target first. ``else`` may establish it again.
        # Other imports must agree before the loop and on body fallthrough.
        imports_after_body = {
            name: binding
            for name, binding in self._local_import_bindings().items()
            if name not in names
        }
        normal_exit_states = [imports_after_iter, *continue_bindings]
        if body_falls_through:
            normal_exit_states.append(imports_after_body)
        self._set_local_import_bindings(
            self._intersect_import_bindings(*normal_exit_states)
        )
        else_falls_through = self._visit_statement_list(node.orelse)
        imports_after_else = self._local_import_bindings()

        # Every possible break skips ``else``. Keep only the identical import
        # bindings present on the else path and on every observed break path.
        reachable_states = list(break_bindings)
        if else_falls_through:
            reachable_states.append(imports_after_else)
        self._set_local_import_bindings(
            self._intersect_import_bindings(*reachable_states)
        )

    def visit_For(self, node: ast.For) -> Any:
        self._visit_for_statement(node)
        return None

    def visit_AsyncFor(self, node: ast.AsyncFor) -> Any:
        self._visit_for_statement(node)
        return None

    def visit_While(self, node: ast.While) -> Any:
        self.visit(node.test)
        imports_after_test = self._local_import_bindings()
        self._loop_break_bindings.append([])
        self._loop_continue_bindings.append([])
        try:
            body_falls_through = self._visit_statement_list(node.body)
        finally:
            break_bindings = self._loop_break_bindings.pop()
            continue_bindings = self._loop_continue_bindings.pop()
        normal_exit_states = [imports_after_test, *continue_bindings]
        if body_falls_through:
            normal_exit_states.append(self._local_import_bindings())
        self._set_local_import_bindings(
            self._intersect_import_bindings(*normal_exit_states)
        )
        else_falls_through = self._visit_statement_list(node.orelse)
        reachable_states = list(break_bindings)
        if else_falls_through:
            reachable_states.append(self._local_import_bindings())
        self._set_local_import_bindings(
            self._intersect_import_bindings(*reachable_states)
        )
        return None

    def visit_Break(self, _node: ast.Break) -> Any:
        if self._loop_break_bindings and not self._suppress_loop_exits:
            self._loop_break_bindings[-1].append(self._local_import_bindings())
        return None

    def visit_Continue(self, _node: ast.Continue) -> Any:
        if self._loop_continue_bindings and not self._suppress_loop_exits:
            self._loop_continue_bindings[-1].append(self._local_import_bindings())
        return None

    def _visit_with_statement(self, node: ast.With | ast.AsyncWith) -> None:
        for item in node.items:
            self.visit(item.context_expr)
            if item.optional_vars is not None:
                self.visit(item.optional_vars)
                self._bind_or_invalidate_targets((item.optional_vars,))
        for statement in node.body:
            self.visit(statement)

    def visit_With(self, node: ast.With) -> Any:
        self._visit_with_statement(node)
        return None

    def visit_AsyncWith(self, node: ast.AsyncWith) -> Any:
        self._visit_with_statement(node)
        return None

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> Any:
        if node.type is not None:
            self.visit(node.type)
        names = {node.name} if isinstance(node.name, str) else set()
        self._bind_or_invalidate_names(names)
        for statement in node.body:
            self.visit(statement)
        # Python clears an exception target after the handler suite.
        self._bind_or_invalidate_names(names)
        return None

    def visit_Match(self, node: ast.Match) -> Any:
        self.visit(node.subject)
        if not self.stack:
            for case in node.cases:
                for name in _match_pattern_names(case.pattern):
                    self.state.add_binding(name, "assign")
        next_case_state = self._local_import_bindings()
        fallthrough_states: list[dict[str, tuple[str, ...]]] = []
        exhaustive = False
        for case in node.cases:
            pattern_names = _match_pattern_names(case.pattern)
            pattern_miss_state = next_case_state
            pattern_success_state = self._bindings_without_names(
                next_case_state,
                pattern_names,
            )
            self._set_local_import_bindings(pattern_success_state)
            self.visit(case.pattern)
            if case.guard is not None:
                self.visit(case.guard)
                guard_state = self._local_import_bindings()
                # A later case can be reached either because this pattern did not
                # match or because its guard was false. Retain only imports that
                # survive both paths.
                next_case_state = self._intersect_import_bindings(
                    pattern_miss_state,
                    guard_state,
                )
            else:
                guard_state = pattern_success_state
                next_case_state = pattern_miss_state
            self._set_local_import_bindings(guard_state)
            if self._visit_statement_list(case.body):
                fallthrough_states.append(self._local_import_bindings())
            if case.guard is None and _match_pattern_is_irrefutable(case.pattern):
                exhaustive = True
                break
        if not exhaustive:
            # A refutable match may select no case. The pre-match path is therefore
            # a reachable exit and must prevent conditional imports becoming S1.
            fallthrough_states.append(next_case_state)
        self._set_local_import_bindings(
            self._intersect_import_bindings(*fallthrough_states)
        )
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
                _RawCall(
                    start_line=start_line,
                    start_col=start_col,
                    end_line=end_line,
                    end_col=end_col,
                    func=node.func,
                    # The stack list changes while traversing; its frozen frames do not.
                    stack=tuple(self.stack),
                )
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


def _visible_import_frames(
    stack: Sequence[_ScopeFrame],
) -> Iterator[_ScopeFrame]:
    inside_function = False
    for frame in reversed(stack):
        if frame.kind in (*_FUNCTION_KINDS, "lambda"):
            inside_function = True
        if inside_function and frame.kind == "class":
            continue
        yield frame


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

    def _target_in_module(
        self,
        module: str,
        name: str,
        reason_prefix: str,
        *,
        _visited: frozenset[tuple[str, str]] = frozenset(),
    ) -> dict[str, Any]:
        key = (module, name)
        if key in _visited:
            return _verdict("unresolved", "transitive_import_cycle")
        states = self.modules.get(module, [])
        if not states:
            return _verdict("unresolved", f"{reason_prefix}_foreign_module")
        functions = [
            symbol_id for state in states for symbol_id in state.functions.get(name, [])
        ]
        classes = [
            symbol_id for state in states for symbol_id in state.classes.get(name, [])
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
        state = states[0]
        imported = state.from_imports.get(name)
        if imported is not None:
            source_module, original = imported
            return self._target_in_module(
                source_module,
                original,
                "transitive_imported_internal_name",
                _visited=_visited | {key},
            )
        if state.has_module_getattr:
            return _verdict(
                "unresolved", f"{reason_prefix}_module_getattr_dispatch"
            )
        if state.star_imports:
            return _verdict("unresolved", f"{reason_prefix}_star_import_unresolved")
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
            elif frame.kind == "type_alias" and name in frame.local_bindings:
                return _type_alias_binding_reason(frame, name), False
            elif (
                frame.kind == "class"
                and not inside_function
                and name in frame.local_bindings
            ):
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
            reason = (
                "local_class_constructor" if local_classes else "local_module_function"
            )
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

    def _resolve_local_import_name(
        self, name: str, stack: Sequence[_ScopeFrame]
    ) -> dict[str, Any] | None:
        for frame in _visible_import_frames(stack):
            if frame.kind in (*_FUNCTION_KINDS, "lambda"):
                if name in frame.global_names or name in frame.nonlocal_names:
                    return None
            imported = {
                local: (module, original)
                for local, module, original in frame.from_imports
            }.get(name)
            if imported is not None:
                source_module, original = imported
                if source_module not in self.modules:
                    return None
                return self._target_in_module(
                    source_module,
                    original,
                    "local_imported_internal_name",
                )
            if name in frame.local_bindings:
                return None
        return None

    def _resolve_name(
        self, state: _ModuleState, name: str, stack: Sequence[_ScopeFrame]
    ) -> dict[str, Any]:
        local_import = self._resolve_local_import_name(name, stack)
        if local_import is not None:
            return local_import
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
            return _verdict(
                status, "name_rebound_at_module_level", candidates=candidates
            )
        if len(sources) > 1:
            return self._multiple_binding_verdict(state, name, candidates)
        if name in state.from_imports:
            source_module, original = state.from_imports[name]
            return self._target_in_module(
                source_module, original, "imported_internal_name"
            )
        if "import" in sources:
            return _verdict("unresolved", "module_object_called")
        verdict = self._local_binding_verdict(local_functions, local_classes)
        if verdict["resolution_reason"] == "unknown_name" and state.star_imports:
            return _verdict("unresolved", "star_import_unresolved")
        return verdict

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
        valid_receivers = {method.receiver_name, *method.receiver_aliases}
        if method.kind not in _FUNCTION_KINDS or root not in valid_receivers:
            return None
        if function_index == 0 or stack[function_index - 1].kind != "class":
            return None
        return method, stack[function_index - 1]

    def _resolve_single_inheritance_method(
        self,
        state: _ModuleState,
        class_name: str,
        method_name: str,
        reason: str,
    ) -> dict[str, Any]:
        visited: set[str] = set()
        current = class_name
        while True:
            if current in visited:
                return _verdict("unresolved", "single_inheritance_cycle")
            visited.add(current)
            bases = state.class_bases.get(current, ())
            if not bases:
                return _verdict("unresolved", "method_not_defined_in_same_class")
            if len(bases) > 1:
                return _verdict(
                    "unresolved", "mixin_or_multiple_inheritance_not_promoted"
                )
            base = bases[0]
            if base == "<dynamic>":
                return _verdict("unresolved", "dynamic_base_class_not_promoted")
            if len(state.classes.get(base, [])) != 1:
                return _verdict(
                    "unresolved", "single_inheritance_nonlocal_or_ambiguous_base"
                )
            methods = state.methods.get((base, method_name), [])
            if len(methods) == 1:
                return _verdict("resolved", reason, resolved=methods)
            if len(methods) > 1:
                return _verdict(
                    "ambiguous",
                    "inherited_method_multiple_definitions",
                    candidates=methods,
                )
            current = base

    def _resolve_receiver_dotted(
        self, state: _ModuleState, parts: list[str], stack: Sequence[_ScopeFrame]
    ) -> dict[str, Any]:
        if len(parts) != 2:
            return _verdict("unresolved", "nested_receiver_attribute_call")
        context = self._direct_method_context(parts[0], stack)
        if context is None:
            return _verdict("unresolved", "receiver_not_direct_method_parameter")
        method_frame, class_frame = context
        class_index = next(
            index for index, frame in enumerate(stack) if frame is class_frame
        )
        class_named = _named_frames(stack[: class_index + 1])
        class_qualified = ".".join(frame.name for frame in class_named if frame.name)
        methods = state.methods.get((class_qualified, parts[1]), [])
        is_alias = parts[0] != method_frame.receiver_name
        if len(methods) == 1:
            reason = (
                "receiver_alias_method_same_class"
                if is_alias
                else f"{parts[0]}_method_same_class"
            )
            return _verdict("resolved", reason, resolved=methods)
        if len(methods) > 1:
            return _verdict(
                "ambiguous",
                "method_multiple_definitions_in_same_class",
                candidates=methods,
            )
        reason = (
            "receiver_alias_single_inheritance_method"
            if is_alias
            else f"{parts[0]}_single_inheritance_method"
        )
        return self._resolve_single_inheritance_method(
            state, class_qualified, parts[1], reason
        )

    def _resolve_local_import_dotted(
        self, parts: list[str], stack: Sequence[_ScopeFrame]
    ) -> dict[str, Any] | None:
        root = parts[0]
        for frame in _visible_import_frames(stack):
            if frame.kind in (*_FUNCTION_KINDS, "lambda"):
                if root in frame.global_names:
                    return None
                if root in frame.nonlocal_names:
                    continue

            module_alias = dict(frame.module_aliases).get(root)
            if module_alias is not None:
                target_module = ".".join(
                    part for part in (module_alias, *parts[1:-1]) if part
                )
                if target_module not in self.modules:
                    return None
                return self._target_in_module(
                    target_module,
                    parts[-1],
                    "local_module_alias_call",
                )

            imported = {
                local: (module, original)
                for local, module, original in frame.from_imports
            }.get(root)
            if imported is not None:
                source, original = imported
                imported_module = ".".join(
                    part for part in (source, original, *parts[1:-1]) if part
                )
                if imported_module not in self.modules:
                    return None
                return self._target_in_module(
                    imported_module,
                    parts[-1],
                    "local_from_import_module_call",
                )

            if root in frame.local_bindings:
                return _verdict("unresolved", "attribute_root_lexically_shadowed_name")
        return None

    def _resolve_module_dotted(
        self, state: _ModuleState, parts: list[str], stack: Sequence[_ScopeFrame]
    ) -> dict[str, Any]:
        local_import = self._resolve_local_import_dotted(parts, stack)
        if local_import is not None:
            return local_import
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

    def _resolve_super_attribute(
        self,
        state: _ModuleState,
        func: ast.Attribute,
        stack: Sequence[_ScopeFrame],
    ) -> dict[str, Any]:
        super_call = func.value
        if not isinstance(super_call, ast.Call):
            return _verdict("unresolved", "dynamic_super_expression")
        if super_call.args or super_call.keywords:
            return _verdict("unresolved", "super_arguments_not_promoted")
        function_index: int | None = None
        for index in range(len(stack) - 1, -1, -1):
            if stack[index].kind in (*_FUNCTION_KINDS, "lambda"):
                function_index = index
                break
        if function_index is None or function_index == 0:
            return _verdict("unresolved", "super_outside_direct_method")
        method = stack[function_index]
        class_frame = stack[function_index - 1]
        if (
            method.kind not in _FUNCTION_KINDS
            or method.receiver_name is None
            or class_frame.kind != "class"
        ):
            return _verdict("unresolved", "super_outside_direct_method")
        class_named = _named_frames(stack[:function_index])
        class_qualified = ".".join(frame.name for frame in class_named if frame.name)
        return self._resolve_single_inheritance_method(
            state,
            class_qualified,
            func.attr,
            "super_single_inheritance_method",
        )

    def _resolve_dotted(
        self, state: _ModuleState, parts: list[str], stack: Sequence[_ScopeFrame]
    ) -> dict[str, Any]:
        if self._direct_method_context(parts[0], stack) is not None:
            return self._resolve_receiver_dotted(state, parts, stack)
        if parts[0] in {"self", "cls"}:
            return _verdict("unresolved", "receiver_not_direct_method_parameter")
        return self._resolve_module_dotted(state, parts, stack)

    def resolve(self, state: _ModuleState, raw_call: _RawCall) -> dict[str, Any]:
        func = raw_call.func
        stack = raw_call.stack
        if isinstance(func, ast.Name):
            simple_name: str | None = func.id
            verdict = self._resolve_name(state, func.id, stack)
        else:
            if (
                isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Call)
                and isinstance(func.value.func, ast.Name)
                and func.value.func.id == "super"
            ):
                simple_name = func.attr
                verdict = self._resolve_super_attribute(state, func, stack)
            else:
                parts = _dotted_parts(func)
                if parts is not None:
                    simple_name = parts[-1]
                    verdict = self._resolve_dotted(state, parts, stack)
                else:
                    simple_name = (
                        func.attr if isinstance(func, ast.Attribute) else None
                    )
                    verdict = _verdict("unresolved", "dynamic_callee_expression")
        record = {
            "path": state.path,
            "start_line": raw_call.start_line,
            "start_col": raw_call.start_col,
            "end_line": raw_call.end_line,
            "end_col": raw_call.end_col,
            "range_ref": _range_ref(state.path, raw_call.start_line, raw_call.end_line),
            "callee_expression": ast.unparse(func),
            "simple_name": simple_name,
        }
        record.update(_caller_fields(state.path, stack))
        record.update(verdict)
        return record


def _snapshot_module_state(state: _ModuleState) -> _ModuleSnapshot:
    return _ModuleSnapshot(
        path=state.path,
        module=state.module,
        functions=tuple(
            (name, tuple(values)) for name, values in sorted(state.functions.items())
        ),
        classes=tuple(
            (name, tuple(values)) for name, values in sorted(state.classes.items())
        ),
        class_bases=tuple(
            (name, tuple(values))
            for name, values in sorted(state.class_bases.items())
        ),
        methods=tuple(
            (owner, name, tuple(values))
            for (owner, name), values in sorted(state.methods.items())
        ),
        symbol_kinds=tuple(sorted(state.symbol_kinds.items())),
        from_imports=tuple(
            (name, module, original)
            for name, (module, original) in sorted(state.from_imports.items())
        ),
        module_aliases=tuple(sorted(state.module_aliases.items())),
        imported_module_names=tuple(sorted(state.imported_module_names)),
        star_imports=tuple(sorted(state.star_imports)),
        has_module_getattr=state.has_module_getattr,
        binding_sources=tuple(
            (name, tuple(sorted(values)))
            for name, values in sorted(state.binding_sources.items())
        ),
        calls=tuple(
            _CachedRawCall(
                start_line=raw_call.start_line,
                start_col=raw_call.start_col,
                end_line=raw_call.end_line,
                end_col=raw_call.end_col,
                callee_expression=ast.unparse(raw_call.func),
                stack=raw_call.stack,
            )
            for raw_call in state.calls
        ),
    )


def _restore_module_state(snapshot: _ModuleSnapshot) -> _ModuleState:
    state = _ModuleState(snapshot.path, snapshot.module)
    state.functions = {name: list(values) for name, values in snapshot.functions}
    state.classes = {name: list(values) for name, values in snapshot.classes}
    state.class_bases = {
        name: tuple(values) for name, values in snapshot.class_bases
    }
    state.methods = {
        (owner, name): list(values) for owner, name, values in snapshot.methods
    }
    state.symbol_kinds = dict(snapshot.symbol_kinds)
    state.from_imports = {
        name: (module, original) for name, module, original in snapshot.from_imports
    }
    state.module_aliases = dict(snapshot.module_aliases)
    state.imported_module_names = set(snapshot.imported_module_names)
    state.star_imports = set(snapshot.star_imports)
    state.has_module_getattr = snapshot.has_module_getattr
    state.binding_sources = {
        name: set(values) for name, values in snapshot.binding_sources
    }
    state.calls = [
        _RawCall(
            start_line=raw_call.start_line,
            start_col=raw_call.start_col,
            end_line=raw_call.end_line,
            end_col=raw_call.end_col,
            func=ast.parse(raw_call.callee_expression, mode="eval").body,
            stack=raw_call.stack,
        )
        for raw_call in snapshot.calls
    ]
    return state


def _parse_python_source(
    relative_path: str,
    filename: str,
    is_package: bool,
    source: str,
) -> _ParseOutcome:
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as exc:
        return _ParseOutcome(
            snapshot=None,
            error=(f"Failed to parse {relative_path}: {type(exc).__name__} - {exc}"),
        )
    visitor = _CallGraphVisitor(relative_path, is_package=is_package)
    visitor.visit(tree)
    return _ParseOutcome(snapshot=_snapshot_module_state(visitor.state))


def _fingerprint_python_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _read_parse_input(item: _PythonFileInput) -> tuple[str | None, str | None]:
    try:
        payload = item.path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != item.content_sha256:
            raise OSError("source changed while the call graph was being generated")
        return payload.decode("utf-8"), None
    except (OSError, UnicodeDecodeError) as exc:
        return None, (
            f"Failed to parse {item.relative_path}: {type(exc).__name__} - {exc}"
        )


def _parse_serial(
    items: Sequence[_PythonFileInput],
) -> dict[str, _ParseOutcome]:
    outcomes: dict[str, _ParseOutcome] = {}
    for item in items:
        source, error = _read_parse_input(item)
        if error is not None:
            outcomes[item.relative_path] = _ParseOutcome(None, error)
            continue
        assert source is not None
        outcomes[item.relative_path] = _parse_python_source(
            item.relative_path,
            str(item.path),
            item.is_package,
            source,
        )
    return outcomes


def _parse_bounded_parallel(
    items: Sequence[_PythonFileInput],
    *,
    max_workers: int,
    max_in_flight_bytes: int,
) -> tuple[dict[str, _ParseOutcome], int, int, str | None]:
    outcomes: dict[str, _ParseOutcome] = {}
    peak_in_flight_bytes = 0
    parallel_files = 0
    executor_type = _ProcessPoolExecutor
    if executor_type is None:
        return (
            _parse_serial(items),
            0,
            0,
            "ProcessPoolExecutor unavailable",
        )
    try:
        with executor_type(max_workers=max_workers) as executor:
            index = 0
            while index < len(items):
                batch: list[tuple[_PythonFileInput, str]] = []
                batch_bytes = 0
                while index < len(items):
                    item = items[index]
                    if item.size_bytes > max_in_flight_bytes:
                        source, error = _read_parse_input(item)
                        outcomes[item.relative_path] = (
                            _ParseOutcome(None, error)
                            if error is not None
                            else _parse_python_source(
                                item.relative_path,
                                str(item.path),
                                item.is_package,
                                source or "",
                            )
                        )
                        index += 1
                        continue
                    if batch and (
                        len(batch) >= max_workers * 2
                        or batch_bytes + item.size_bytes > max_in_flight_bytes
                    ):
                        break
                    source, error = _read_parse_input(item)
                    index += 1
                    if error is not None:
                        outcomes[item.relative_path] = _ParseOutcome(None, error)
                        continue
                    assert source is not None
                    batch.append((item, source))
                    batch_bytes += len(source.encode("utf-8"))
                if not batch:
                    continue
                peak_in_flight_bytes = max(peak_in_flight_bytes, batch_bytes)
                futures = [
                    executor.submit(
                        _parse_python_source,
                        item.relative_path,
                        str(item.path),
                        item.is_package,
                        source,
                    )
                    for item, source in batch
                ]
                for (item, _), future in zip(batch, futures):
                    outcomes[item.relative_path] = future.result()
                    parallel_files += 1
        return outcomes, parallel_files, peak_in_flight_bytes, None
    except Exception as exc:
        # Discard every parallel result. A complete serial retry prevents a
        # worker failure from producing a mixed or partial graph.
        return (
            _parse_serial(items),
            0,
            0,
            f"{type(exc).__name__}: {exc}",
        )


def _normalized_worker_count(max_workers: int | None) -> int:
    value = DEFAULT_CALL_GRAPH_MAX_WORKERS if max_workers is None else max_workers
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("max_workers must be a positive integer or None")
    return min(value, 32)


def _collect_python_inputs(
    repo_root: Path, cache: CallGraphBuildCache | None
) -> tuple[
    list[str],
    dict[str, _PythonFileInput],
    dict[str, _ParseOutcome],
    int,
    list[_PythonFileInput],
]:
    ordered_paths: list[str] = []
    inputs: dict[str, _PythonFileInput] = {}
    outcomes: dict[str, _ParseOutcome] = {}
    cache_hits = 0
    cache_misses: list[_PythonFileInput] = []
    for root, dirs, files in os.walk(repo_root, topdown=True):
        dirs[:] = sorted(
            directory for directory in dirs if directory not in EXCLUDED_DIRS
        )
        for file_name in sorted(files):
            if not file_name.endswith(".py"):
                continue
            path = Path(root) / file_name
            rel_path = path.relative_to(repo_root).as_posix()
            ordered_paths.append(rel_path)
            try:
                content_sha256, size_bytes = _fingerprint_python_file(path)
            except OSError as exc:
                outcomes[rel_path] = _ParseOutcome(
                    None,
                    f"Failed to parse {rel_path}: {type(exc).__name__} - {exc}",
                )
                continue
            item = _PythonFileInput(
                path=path,
                relative_path=rel_path,
                content_sha256=content_sha256,
                size_bytes=size_bytes,
                is_package=file_name == "__init__.py",
            )
            inputs[rel_path] = item
            snapshot = None if cache is None else cache.lookup(rel_path, content_sha256)
            if snapshot is None:
                cache_misses.append(item)
                continue
            try:
                _restore_module_state(snapshot)
            except (SyntaxError, ValueError, TypeError):
                cache_misses.append(item)
                continue
            outcomes[rel_path] = _ParseOutcome(snapshot=snapshot)
            cache_hits += 1
    return ordered_paths, inputs, outcomes, cache_hits, cache_misses


def _assemble_module_states(
    ordered_paths: Sequence[str],
    inputs: dict[str, _PythonFileInput],
    outcomes: dict[str, _ParseOutcome],
    cache: CallGraphBuildCache | None,
) -> tuple[dict[str, list[_ModuleState]], int, list[str]]:
    modules: dict[str, list[_ModuleState]] = {}
    current_cache_entries: dict[str, _CallGraphCacheEntry] = {}
    skipped_files_count = 0
    skipped_errors: list[str] = []
    for rel_path in ordered_paths:
        outcome = outcomes[rel_path]
        if outcome.error is not None or outcome.snapshot is None:
            skipped_files_count += 1
            if len(skipped_errors) < MAX_SKIPPED_ERRORS:
                skipped_errors.append(outcome.error or f"Failed to parse {rel_path}")
            continue
        state = _restore_module_state(outcome.snapshot)
        modules.setdefault(state.module, []).append(state)
        item = inputs[rel_path]
        current_cache_entries[rel_path] = _CallGraphCacheEntry(
            content_sha256=item.content_sha256,
            producer_version=CALL_GRAPH_PRODUCER_VERSION,
            snapshot=outcome.snapshot,
        )
    if cache is not None:
        cache.replace(current_cache_entries)
    return modules, skipped_files_count, skipped_errors


def extract_python_calls(
    repo_root: Path,
    *,
    cache: CallGraphBuildCache | None = None,
    max_workers: int | None = None,
    max_in_flight_bytes: int = DEFAULT_CALL_GRAPH_MAX_IN_FLIGHT_BYTES,
    build_report: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], int, list[str]]:
    """Return deterministic calls with optional hash-bound reuse and parsing."""
    workers = _normalized_worker_count(max_workers)
    if (
        isinstance(max_in_flight_bytes, bool)
        or not isinstance(max_in_flight_bytes, int)
        or max_in_flight_bytes < 1
    ):
        raise ValueError("max_in_flight_bytes must be a positive integer")

    ordered_paths, inputs, outcomes, cache_hits, cache_misses = _collect_python_inputs(
        repo_root, cache
    )

    parallel_eligible = (
        workers > 1
        and len(cache_misses) >= _MIN_PARALLEL_FILES
        and sum(item.size_bytes for item in cache_misses) >= _MIN_PARALLEL_BYTES
    )
    parallel_files = 0
    peak_in_flight_bytes = 0
    fallback_reason: str | None = None
    if parallel_eligible:
        parsed, parallel_files, peak_in_flight_bytes, fallback_reason = (
            _parse_bounded_parallel(
                cache_misses,
                max_workers=workers,
                max_in_flight_bytes=max_in_flight_bytes,
            )
        )
    else:
        parsed = _parse_serial(cache_misses)
    outcomes.update(parsed)

    modules, skipped_files_count, skipped_errors = _assemble_module_states(
        ordered_paths, inputs, outcomes, cache
    )

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
    if build_report is not None:
        build_report.clear()
        build_report.update(
            {
                "schema_version": 1,
                "producer_version": CALL_GRAPH_PRODUCER_VERSION,
                "python_file_count": len(ordered_paths),
                "cache_hits": cache_hits,
                "cache_misses": len(cache_misses),
                "cache_entries": 0 if cache is None else cache.entry_count,
                "max_workers": workers,
                "parallel_eligible": parallel_eligible,
                "parallel_files": parallel_files,
                "serial_files": len(cache_misses) - parallel_files,
                "max_in_flight_bytes": max_in_flight_bytes,
                "peak_in_flight_bytes": peak_in_flight_bytes,
                "parallel_fallback": fallback_reason is not None,
                "parallel_fallback_reason": fallback_reason,
            }
        )
    return calls, skipped_files_count, skipped_errors


def generate_call_graph_document(
    repo_root: Path,
    run_id: str,
    canonical_sha256: str,
    *,
    cache: CallGraphBuildCache | None = None,
    max_workers: int | None = None,
    max_in_flight_bytes: int = DEFAULT_CALL_GRAPH_MAX_IN_FLIGHT_BYTES,
    build_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    calls, skipped_count, skipped_errors = extract_python_calls(
        repo_root,
        cache=_DEFAULT_BUILD_CACHE if cache is None else cache,
        max_workers=max_workers,
        max_in_flight_bytes=max_in_flight_bytes,
        build_report=build_report,
    )
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
