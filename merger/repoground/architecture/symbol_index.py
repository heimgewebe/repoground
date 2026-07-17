from __future__ import annotations

import ast
import os
from pathlib import Path, PurePosixPath
from typing import Any

EXCLUDED_DIRS = frozenset({
    ".git",
    ".grabowski",
    ".claude",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    "venv",
    ".venv",
    "__pycache__",
    "node_modules",
    "build",
    "dist",
})
SYMBOL_KINDS = ("class", "function", "async_function")
DOES_NOT_ESTABLISH = (
    "call_graph_completeness",
    "dependency_completeness",
    "runtime_behavior",
    "import_success",
    "test_sufficiency",
    "review_impact",
    "merge_readiness",
)


def _range_ref(path: str, start_line: int, end_line: int) -> str:
    return f"file:{path}#L{start_line}-L{end_line}"


def _module_name(path: str) -> str:
    posix = PurePosixPath(path)
    if posix.name == "__init__.py":
        parts = posix.parent.parts
    else:
        parts = posix.with_suffix("").parts
    return ".".join(part for part in parts if part)


def _symbol_id(path: str, qualified_name: str, kind: str) -> str:
    normalized = path.replace("/", ":")
    return f"py:{normalized}:{kind}:{qualified_name}"


class _SymbolVisitor(ast.NodeVisitor):
    def __init__(self, path: str) -> None:
        self.path = path
        self.module = _module_name(path)
        self.stack: list[str] = []
        self.symbols: list[dict[str, Any]] = []

    def _add_symbol(self, node: ast.AST, name: str, kind: str, decorators: list[str] | None = None) -> None:
        start = getattr(node, "lineno", None)
        end = getattr(node, "end_lineno", None) or start
        if not isinstance(start, int) or not isinstance(end, int):
            return
        qualified_parts = [*self.stack, name]
        qualified_name = ".".join(qualified_parts)
        symbol: dict[str, Any] = {
            "id": _symbol_id(self.path, qualified_name, kind),
            "kind": kind,
            "name": name,
            "qualified_name": qualified_name,
            "module": self.module,
            "path": self.path,
            "start_line": start,
            "end_line": end,
            "range_ref": _range_ref(self.path, start, end),
        }
        if decorators:
            symbol["decorators"] = decorators
        self.symbols.append(symbol)

    def visit_ClassDef(self, node: ast.ClassDef) -> Any:
        self._add_symbol(node, node.name, "class", _decorator_names(node.decorator_list))
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
        self._add_symbol(node, node.name, "function", _decorator_names(node.decorator_list))
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> Any:
        self._add_symbol(node, node.name, "async_function", _decorator_names(node.decorator_list))
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()


def _decorator_names(decorators: list[ast.expr]) -> list[str]:
    names: list[str] = []
    for decorator in decorators:
        if isinstance(decorator, ast.Name):
            names.append(decorator.id)
        elif isinstance(decorator, ast.Attribute):
            names.append(decorator.attr)
        elif isinstance(decorator, ast.Call):
            func = decorator.func
            if isinstance(func, ast.Name):
                names.append(func.id)
            elif isinstance(func, ast.Attribute):
                names.append(func.attr)
    return sorted(set(names))


def extract_python_symbols(repo_root: Path) -> tuple[list[dict[str, Any]], int, list[str]]:
    symbols: list[dict[str, Any]] = []
    skipped_files_count = 0
    skipped_errors: list[str] = []

    # Keep os.walk lazy and top-down: wrapping it in sorted(...) consumes the
    # whole tree before dirs[:] can prune excluded subdirectories. Sorting
    # dirs and files here preserves deterministic traversal order.
    for root, dirs, files in os.walk(repo_root, topdown=True):
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDED_DIRS)
        for file_name in sorted(files):
            if not file_name.endswith(".py"):
                continue
            path = Path(root) / file_name
            rel_path = path.relative_to(repo_root).as_posix()
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except (OSError, SyntaxError, UnicodeDecodeError) as exc:
                skipped_files_count += 1
                if len(skipped_errors) < 20:
                    skipped_errors.append(f"Failed to parse {rel_path}: {type(exc).__name__} - {exc}")
                continue
            visitor = _SymbolVisitor(rel_path)
            visitor.visit(tree)
            symbols.extend(visitor.symbols)

    return sorted(symbols, key=lambda item: (item["path"], item["start_line"], item["qualified_name"], item["kind"])), skipped_files_count, skipped_errors


def generate_symbol_index_document(repo_root: Path, run_id: str, canonical_sha256: str) -> dict[str, Any]:
    symbols, skipped_count, skipped_errors = extract_python_symbols(repo_root)
    return {
        "kind": "lenskit.python_symbol_index",
        "version": "1.0",
        "run_id": run_id,
        "canonical_dump_index_sha256": canonical_sha256,
        "language": "python",
        "symbol_kinds": list(SYMBOL_KINDS),
        "symbols": symbols,
        "skipped_files_count": skipped_count,
        "skipped_errors": skipped_errors,
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }
