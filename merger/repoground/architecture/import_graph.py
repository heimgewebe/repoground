"""
Extracts a bounded repository file graph with Python import edges via static
AST analysis.

Resolver boundaries (S1 heuristic):
- This artifact is static evidence and does not represent runtime causality.
- Local modules are resolved only when a unique repository-relative or explicitly
  rooted Python path exists.
- Ambiguous or unavailable module names remain external module strings.
- Relative imports and repository-root absolute imports are supported.
- Explicit source roots add module-name candidates; they do not establish runtime
  ``sys.path`` or precedence.
- Star imports are not semantically expanded.
- Layers are inferred from explicit path segments only; unmatched paths remain unknown.
"""

from __future__ import annotations

import ast
import logging
import os
from collections.abc import Iterator, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, TypedDict

from merger.repoground.architecture.path_classification import (
    infer_architecture_layer,
    is_test_path,
)

logger = logging.getLogger(__name__)

_SKIP_DIRECTORIES = {"__pycache__", "env", "node_modules", "venv"}
_GRAPH_SKIP_DIRECTORIES = _SKIP_DIRECTORIES | {"build", "dist", "target"}
_HARD_MAX_GRAPH_FILES = 50_000
_HARD_MAX_GRAPH_SOURCE_BYTES = 512 * 1024 * 1024
_DEFAULT_MAX_GRAPH_FILES = _HARD_MAX_GRAPH_FILES
_DEFAULT_MAX_GRAPH_SOURCE_BYTES = _HARD_MAX_GRAPH_SOURCE_BYTES

_GRAPH_FILE_LANGUAGES = {
    ".js": "javascript",
    ".json": "json",
    ".jsx": "javascript",
    ".md": "markdown",
    ".py": "python",
    ".rs": "rust",
    ".sql": "sql",
    ".svelte": "svelte",
    ".toml": "toml",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".yaml": "yaml",
    ".yml": "yaml",
}


class SourceRootError(ValueError):
    """An explicit source-root declaration is invalid for the repository snapshot."""


class Evidence(TypedDict, total=False):
    source_path: str
    start_line: int
    end_line: int
    extract: str


class Edge(TypedDict):
    src: str
    dst: str
    edge_type: Literal["import", "require", "config-link", "string-ref", "call-heuristic"]
    evidence_level: Literal["S0", "S1", "S2"]
    evidence: Evidence


class Node(TypedDict, total=False):
    node_id: str
    kind: Literal["file", "package", "module", "external"]
    path: str
    repo: str
    language: str
    layer: str
    is_test: bool
    size_bytes: int


class Coverage(TypedDict):
    files_seen: int
    files_parsed: int
    edge_counts_by_type: dict[str, int]
    unknown_layer_share: float
    repository_file_unknown_layer_share: float
    repository_files_seen: int
    repository_files_included: int
    repository_bytes_seen: int
    repository_bytes_included: int
    repository_truncated: bool
    max_repository_files: int
    max_repository_source_bytes: int


class GraphDocument(TypedDict, total=False):
    kind: Literal["lenskit.architecture.graph"]
    version: Literal["1.0"]
    run_id: str
    canonical_dump_index_sha256: str
    generated_at: str
    granularity: str
    nodes: list[Node]
    edges: list[Edge]
    coverage: Coverage


def _is_test_file(path: str) -> bool:
    return is_test_path(path)


def _infer_layer(path: str) -> str:
    return infer_architecture_layer(path)


def _scan_graph_source_files(repo_root: Path) -> tuple[list[Path], list[Path]]:
    """Scan once while preserving legacy Python and bounded inventory scope."""

    python_files: list[Path] = []
    inventory_files: list[Path] = []
    for root, dirs, files in os.walk(repo_root):
        dirs[:] = sorted(
            directory
            for directory in dirs
            if (not directory.startswith(".") or directory == ".github")
            and directory not in _SKIP_DIRECTORIES
        )
        root_path = Path(root)
        relative_root = root_path.relative_to(repo_root)
        root_parts = set(relative_root.parts)
        for filename in sorted(files):
            file_path = root_path / filename
            suffix = file_path.suffix.lower()
            if suffix == ".py":
                if ".github" not in root_parts:
                    python_files.append(file_path)
                continue
            if suffix not in _GRAPH_FILE_LANGUAGES:
                continue
            if filename.lower().endswith(".graph.json"):
                continue
            if root_parts.intersection(_GRAPH_SKIP_DIRECTORIES - _SKIP_DIRECTORIES):
                continue
            inventory_files.append(file_path)
    return python_files, inventory_files


def _bounded_graph_source_files(
    repo_root: Path,
    python_files: list[Path],
    inventory_files: list[Path],
    *,
    max_files: int,
    max_source_bytes: int,
) -> tuple[list[Path], list[Path], dict[str, int | bool]]:
    if not 0 < max_files <= _HARD_MAX_GRAPH_FILES:
        raise ValueError(
            f"max_graph_files must be between 1 and {_HARD_MAX_GRAPH_FILES}"
        )
    if not 0 < max_source_bytes <= _HARD_MAX_GRAPH_SOURCE_BYTES:
        raise ValueError(
            "max_graph_source_bytes must be between 1 and "
            f"{_HARD_MAX_GRAPH_SOURCE_BYTES}"
        )

    python_set = set(python_files)
    candidates = sorted(
        [*python_files, *inventory_files],
        key=lambda path: path.relative_to(repo_root).as_posix(),
    )
    sized: list[tuple[Path, int]] = []
    total_bytes = 0
    for file_path in candidates:
        relative_path = file_path.relative_to(repo_root).as_posix()
        try:
            size_bytes = file_path.stat().st_size
        except OSError as exc:
            logger.warning("Could not stat graph source %s: %s", relative_path, exc)
            continue
        sized.append((file_path, size_bytes))
        total_bytes += size_bytes

    selected: list[Path] = []
    selected_bytes = 0
    truncated = False
    for file_path, size_bytes in sized:
        if len(selected) >= max_files or selected_bytes + size_bytes > max_source_bytes:
            truncated = True
            continue
        selected.append(file_path)
        selected_bytes += size_bytes

    selected_python = [path for path in selected if path in python_set]
    selected_inventory = [path for path in selected if path not in python_set]
    return selected_python, selected_inventory, {
        "repository_files_seen": len(sized),
        "repository_files_included": len(selected),
        "repository_bytes_seen": total_bytes,
        "repository_bytes_included": selected_bytes,
        "repository_truncated": truncated,
        "max_repository_files": max_files,
        "max_repository_source_bytes": max_source_bytes,
    }


def _iter_parsed_python_files(
    repo_root: Path,
    python_files: list[Path],
) -> Iterator[tuple[Path, str, ast.AST]]:
    for file_path in python_files:
        relative_path = file_path.relative_to(repo_root).as_posix()
        try:
            content = file_path.read_text(encoding="utf-8")
            tree = ast.parse(content, filename=relative_path)
        except Exception as exc:
            logger.warning("Could not parse AST for %s: %s", relative_path, exc)
            continue
        yield file_path, relative_path, tree


def _inventory_file_node(repo_root: Path, file_path: Path) -> Node | None:
    relative_path = file_path.relative_to(repo_root).as_posix()
    try:
        size_bytes = file_path.stat().st_size
    except OSError as exc:
        logger.warning("Could not stat graph file %s: %s", relative_path, exc)
        return None
    node_id = f"file:{relative_path}"
    return {
        "node_id": node_id,
        "kind": "file",
        "path": relative_path,
        "repo": "",
        "language": _GRAPH_FILE_LANGUAGES[file_path.suffix.lower()],
        "layer": _infer_layer(relative_path),
        "is_test": _is_test_file(relative_path),
        "size_bytes": size_bytes,
    }


def _add_inventory_file_nodes(
    nodes: dict[str, Node],
    repo_root: Path,
    inventory_files: list[Path],
) -> None:
    for file_path in inventory_files:
        node = _inventory_file_node(repo_root, file_path)
        if node is not None:
            nodes[node["node_id"]] = node


def _normalize_source_roots(
    repo_root: Path,
    source_roots: Sequence[str],
) -> tuple[Path, ...]:
    if not source_roots:
        return ()

    resolved_repo = repo_root.resolve()
    if not resolved_repo.is_dir():
        raise SourceRootError("repository root is not an existing directory")

    normalized: list[Path] = []
    seen: set[str] = set()
    for raw_root in source_roots:
        if not isinstance(raw_root, str) or not raw_root:
            raise SourceRootError("source root must be a non-empty string")
        if (
            raw_root != raw_root.strip()
            or raw_root.startswith("/")
            or raw_root.endswith("/")
            or "\\" in raw_root
            or "\x00" in raw_root
            or "//" in raw_root
        ):
            raise SourceRootError(
                f"source root must be a canonical relative POSIX path: {raw_root!r}"
            )
        parts = raw_root.split("/")
        if any(part in {"", ".", ".."} for part in parts):
            raise SourceRootError(
                f"source root must not contain dot segments: {raw_root!r}"
            )
        if raw_root in seen:
            raise SourceRootError(f"duplicate source root: {raw_root!r}")
        seen.add(raw_root)

        relative_root = Path(*parts)
        resolved_root = (resolved_repo / relative_root).resolve()
        try:
            resolved_root.relative_to(resolved_repo)
        except ValueError as exc:
            raise SourceRootError(
                f"source root escapes repository: {raw_root!r}"
            ) from exc
        if not resolved_root.is_dir():
            raise SourceRootError(
                f"source root is not an existing directory: {raw_root!r}"
            )
        normalized.append(relative_root)

    return tuple(sorted(normalized, key=lambda item: item.as_posix()))


def _module_name_for_path(relative_path: Path) -> str | None:
    module_parts = list(relative_path.with_suffix("").parts)
    if module_parts and module_parts[-1] == "__init__":
        module_parts.pop()
    return ".".join(module_parts) or None


def _module_paths_for_file(
    relative_path: Path,
    source_roots: Sequence[Path],
) -> tuple[Path, ...]:
    module_paths = {relative_path}
    for source_root in source_roots:
        try:
            module_paths.add(relative_path.relative_to(source_root))
        except ValueError:
            continue
    return tuple(sorted(module_paths, key=lambda item: item.as_posix()))


def _build_local_module_index(
    repo_root: Path,
    python_files: list[Path],
    source_roots: Sequence[Path] = (),
) -> dict[str, str]:
    candidates: dict[str, set[str]] = {}
    for file_path in python_files:
        relative_path = file_path.relative_to(repo_root)
        repository_path = relative_path.as_posix()
        for module_path in _module_paths_for_file(relative_path, source_roots):
            module_name = _module_name_for_path(module_path)
            if module_name is None:
                continue
            candidates.setdefault(module_name, set()).add(repository_path)

    return {
        module_name: min(paths)
        for module_name, paths in candidates.items()
        if len(paths) == 1
    }


def _local_file_id(module_name: str | None, module_index: dict[str, str]) -> str | None:
    if not module_name:
        return None
    relative_path = module_index.get(module_name)
    return f"file:{relative_path}" if relative_path is not None else None


def _relative_base_module(source_path: str, level: int, module: str | None) -> str | None:
    package_parts = list(Path(source_path).parent.parts)
    ascend = level - 1
    if ascend > len(package_parts):
        return None
    if ascend:
        package_parts = package_parts[:-ascend]
    if module:
        package_parts.extend(module.split("."))
    return ".".join(package_parts) or None


def _import_destinations(
    node: ast.Import,
    module_index: dict[str, str],
) -> list[str]:
    destinations: list[str] = []
    for alias in node.names:
        local_id = _local_file_id(alias.name, module_index)
        destinations.append(local_id or f"module:{alias.name}")
    return destinations


def _import_from_destinations(
    node: ast.ImportFrom,
    source_path: str,
    module_index: dict[str, str],
) -> list[str]:
    if node.level:
        base_module = _relative_base_module(source_path, node.level, node.module)
        unresolved_base = f"{'.' * node.level}{node.module or ''}"
    else:
        base_module = node.module
        unresolved_base = node.module or ""

    destinations: list[str] = []
    local_base = _local_file_id(base_module, module_index)
    if local_base is not None and (node.module is not None or node.level == 0):
        destinations.append(local_base)

    local_children: list[str] = []
    for alias in node.names:
        if alias.name == "*":
            continue
        child_module = f"{base_module}.{alias.name}" if base_module else alias.name
        local_child = _local_file_id(child_module, module_index)
        if local_child is not None:
            local_children.append(local_child)
    destinations.extend(local_children)

    if destinations:
        return destinations

    if unresolved_base:
        destinations.append(f"module:{unresolved_base}")
    for alias in node.names:
        if alias.name == "*":
            continue
        unresolved_child = (
            f"{unresolved_base}.{alias.name}" if unresolved_base else alias.name
        )
        destinations.append(f"module:{unresolved_child}")
    return destinations


def _evidence(node: ast.AST, source_path: str) -> Evidence:
    evidence: Evidence = {"source_path": source_path}
    line_number = getattr(node, "lineno", None)
    if line_number is not None:
        evidence["start_line"] = line_number
        evidence["end_line"] = getattr(node, "end_lineno", line_number)
    return evidence


def _ensure_destination_node(nodes: dict[str, Node], destination: str) -> None:
    if destination in nodes:
        return
    if destination.startswith("file:"):
        path = destination.removeprefix("file:")
        nodes[destination] = {
            "node_id": destination,
            "kind": "file",
            "path": path,
            "repo": "",
            "language": "python",
            "layer": _infer_layer(path),
            "is_test": _is_test_file(path),
            "size_bytes": 0,
        }
        return
    nodes[destination] = {
        "node_id": destination,
        "kind": "external",
        "path": "",
        "repo": "",
        "language": "python",
        "layer": "unknown",
        "is_test": False,
        "size_bytes": 0,
    }


def generate_import_graph_document(
    repo_root: Path,
    run_id: str,
    canonical_dump_index_sha256: str,
    *,
    source_roots: Sequence[str] = (),
    max_graph_files: int = _DEFAULT_MAX_GRAPH_FILES,
    max_graph_source_bytes: int = _DEFAULT_MAX_GRAPH_SOURCE_BYTES,
) -> GraphDocument:
    """Build a deterministic repository file graph with static Python import edges."""

    nodes: dict[str, Node] = {}
    edges: list[Edge] = []
    files_parsed = 0
    normalized_source_roots = _normalize_source_roots(repo_root, source_roots)
    scanned_python_files, scanned_inventory_files = _scan_graph_source_files(repo_root)
    python_files, inventory_files, source_coverage = _bounded_graph_source_files(
        repo_root,
        scanned_python_files,
        scanned_inventory_files,
        max_files=max_graph_files,
        max_source_bytes=max_graph_source_bytes,
    )
    module_index = _build_local_module_index(
        repo_root,
        python_files,
        normalized_source_roots,
    )

    _add_inventory_file_nodes(nodes, repo_root, inventory_files)

    for file_path, relative_path, tree in _iter_parsed_python_files(
        repo_root,
        python_files,
    ):
        files_parsed += 1
        node_id = f"file:{relative_path}"
        nodes[node_id] = {
            "node_id": node_id,
            "kind": "file",
            "path": relative_path,
            "repo": "",
            "language": "python",
            "layer": _infer_layer(relative_path),
            "is_test": _is_test_file(relative_path),
            "size_bytes": file_path.stat().st_size,
        }

        for syntax_node in ast.walk(tree):
            if isinstance(syntax_node, ast.Import):
                destinations = _import_destinations(syntax_node, module_index)
            elif isinstance(syntax_node, ast.ImportFrom):
                destinations = _import_from_destinations(
                    syntax_node,
                    relative_path,
                    module_index,
                )
            else:
                continue

            evidence = _evidence(syntax_node, relative_path)
            for destination in destinations:
                _ensure_destination_node(nodes, destination)
                edges.append(
                    {
                        "src": node_id,
                        "dst": destination,
                        "edge_type": "import",
                        "evidence_level": "S1",
                        "evidence": evidence,
                    }
                )

    sorted_nodes = sorted(nodes.values(), key=lambda item: item["node_id"])
    unique_edges: dict[tuple[str, str, int], Edge] = {}
    for edge in edges:
        key = (
            edge["src"],
            edge["dst"],
            edge["evidence"].get("start_line", 0),
        )
        unique_edges.setdefault(key, edge)
    sorted_edges = sorted(
        unique_edges.values(),
        key=lambda item: (
            item["src"],
            item["dst"],
            item["evidence"].get("start_line", 0),
        ),
    )

    unknown_layer_count = sum(
        1 for node in sorted_nodes if node.get("layer") == "unknown"
    )
    unknown_layer_share = (
        unknown_layer_count / len(sorted_nodes) if sorted_nodes else 0.0
    )
    repository_file_nodes = [
        node for node in sorted_nodes if node.get("kind") == "file"
    ]
    repository_file_unknown_layer_count = sum(
        1 for node in repository_file_nodes if node.get("layer") == "unknown"
    )
    repository_file_unknown_layer_share = (
        repository_file_unknown_layer_count / len(repository_file_nodes)
        if repository_file_nodes
        else 0.0
    )
    edge_counts_by_type: dict[str, int] = {}
    for edge in sorted_edges:
        edge_type = edge["edge_type"]
        edge_counts_by_type[edge_type] = edge_counts_by_type.get(edge_type, 0) + 1

    files_seen = len(python_files)
    if files_seen > 0 and files_parsed / files_seen < 0.5:
        logger.warning(
            "Low AST parsing coverage: %.2f%%",
            (files_parsed / files_seen) * 100,
        )

    return {
        "kind": "lenskit.architecture.graph",
        "version": "1.0",
        "run_id": run_id,
        "canonical_dump_index_sha256": canonical_dump_index_sha256,
        "generated_at": (
            datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        ),
        "granularity": "file",
        "nodes": sorted_nodes,
        "edges": sorted_edges,
        "coverage": {
            "files_seen": files_seen,
            "files_parsed": files_parsed,
            "edge_counts_by_type": edge_counts_by_type,
            "unknown_layer_share": unknown_layer_share,
            "repository_file_unknown_layer_share": repository_file_unknown_layer_share,
            **source_coverage,
        },
    }
