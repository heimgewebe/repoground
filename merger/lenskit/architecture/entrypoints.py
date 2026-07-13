"""Static Python entrypoint extraction with maintenance projections."""

from __future__ import annotations

import ast
import os
from collections import Counter
from pathlib import Path
from typing import Any

from merger.lenskit.architecture.path_classification import path_projection

_SKIP_DIRECTORIES = {
    ".git",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "venv",
}


def _iter_python_files(repo_root: Path) -> list[Path]:
    paths: list[Path] = []
    for root, directories, filenames in os.walk(repo_root):
        directories[:] = sorted(
            directory
            for directory in directories
            if directory not in _SKIP_DIRECTORIES
        )
        for filename in sorted(filenames):
            if filename.endswith(".py"):
                paths.append(Path(root) / filename)
    return paths


def _stable_id(prefix: str, relative_path: str) -> str:
    normalized = relative_path.replace("/", "_").replace(".", "_")
    return f"{prefix}_{normalized}"


def _is_main_name(node: ast.AST) -> bool:
    return isinstance(node, ast.Name) and node.id == "__name__"


def _is_main_literal(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value == "__main__"


def _main_block_line(tree: ast.AST) -> int | None:
    for node in ast.walk(tree):
        if not isinstance(node, ast.If) or not isinstance(node.test, ast.Compare):
            continue
        comparison = node.test
        if len(comparison.ops) != 1 or not isinstance(comparison.ops[0], ast.Eq):
            continue
        if len(comparison.comparators) != 1:
            continue
        left = comparison.left
        right = comparison.comparators[0]
        if (_is_main_name(left) and _is_main_literal(right)) or (
            _is_main_literal(left) and _is_main_name(right)
        ):
            return node.lineno
    return None


def _module_main_entrypoint(relative_path: str) -> dict[str, Any]:
    return {
        "id": _stable_id("module_main", relative_path),
        "type": "module_main",
        "projection": path_projection(relative_path),
        "path": relative_path,
        "evidence_level": "S0",
        "evidence": {
            "source_path": relative_path,
            "extract": "__main__.py file detected",
        },
    }


def _cli_entrypoint(relative_path: str, line: int) -> dict[str, Any]:
    return {
        "id": _stable_id("cli", relative_path),
        "type": "cli",
        "projection": path_projection(relative_path),
        "path": relative_path,
        "evidence_level": "S1",
        "evidence": {
            "source_path": relative_path,
            "start_line": line,
            "extract": "if __name__ == '__main__': block detected",
        },
    }


def _entrypoint_for_file(file_path: Path, repo_root: Path) -> dict[str, Any] | None:
    relative_path = file_path.relative_to(repo_root).as_posix()
    if file_path.name == "__main__.py":
        return _module_main_entrypoint(relative_path)
    content = file_path.read_text(encoding="utf-8")
    tree = ast.parse(content, filename=str(file_path))
    line = _main_block_line(tree)
    return _cli_entrypoint(relative_path, line) if line is not None else None


def extract_entrypoints(repo_root: Path) -> list[dict[str, Any]]:
    """Return deterministic Python entrypoints for one repository snapshot."""

    entrypoints, _, _ = extract_entrypoints_with_stats(repo_root)
    return entrypoints


def extract_entrypoints_with_stats(
    repo_root: Path,
) -> tuple[list[dict[str, Any]], int, list[str]]:
    """Return entrypoints plus bounded parse-error diagnostics."""

    entrypoints: list[dict[str, Any]] = []
    skipped_errors: list[str] = []
    skipped_count = 0
    for file_path in _iter_python_files(repo_root):
        relative_path = file_path.relative_to(repo_root).as_posix()
        try:
            entrypoint = _entrypoint_for_file(file_path, repo_root)
        except (OSError, UnicodeError, SyntaxError, ValueError) as exc:
            skipped_count += 1
            if len(skipped_errors) < 10:
                skipped_errors.append(
                    f"Failed to parse {relative_path}: {type(exc).__name__} - {exc}"
                )
            continue
        if entrypoint is not None:
            entrypoints.append(entrypoint)
    return sorted(entrypoints, key=lambda item: item["id"]), skipped_count, skipped_errors


def generate_entrypoints_document(
    repo_root: Path,
    run_id: str,
    canonical_sha256: str,
) -> dict[str, Any]:
    """Generate a schema-compatible entrypoint document with split projections."""

    entrypoints, skipped_count, skipped_errors = extract_entrypoints_with_stats(repo_root)
    counts = Counter(item["projection"] for item in entrypoints)
    return {
        "kind": "lenskit.entrypoints",
        "version": "1.0",
        "run_id": run_id,
        "canonical_dump_index_sha256": canonical_sha256,
        "skipped_files_count": skipped_count,
        "skipped_errors": skipped_errors,
        "entrypoint_counts_by_projection": {
            projection: counts.get(projection, 0)
            for projection in ("product", "test", "fixture", "script")
        },
        "entrypoints": entrypoints,
    }
