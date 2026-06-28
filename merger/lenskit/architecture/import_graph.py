"""
Extracts a Python import graph via static AST analysis.

Resolver boundaries (S1 heuristic):
- This artifact is static evidence and does not represent runtime causality.
- Local modules are resolved only when a unique repository-relative Python path exists.
- Ambiguous or unavailable module names remain external module strings.
- Relative imports and repository-root absolute imports are supported.
- Star imports are not semantically expanded.
- Layers are inferred from explicit path segments only; unmatched paths remain unknown.
"""

from __future__ import annotations

import ast
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, TypedDict

logger = logging.getLogger(__name__)

_SKIP_DIRECTORIES = {"__pycache__", "env", "node_modules", "venv"}
_INFRA_SEGMENTS = {"infra", "scripts", "tools"}


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
    name = Path(path).name
    return name.startswith("test_") or name.endswith("_test.py")


def _infer_layer(path: str) -> str:
    parts = set(Path(path).parts)
    if _is_test_file(path) or parts.intersection({"test", "tests"}):
        return "test"
    if "cli" in parts:
        return "cli"
    if "core" in parts:
        return "core"
    if parts.intersection(_INFRA_SEGMENTS):
        return "infra"
    return "unknown"


def _iter_python_files(repo_root: Path) -> list[Path]:
    paths: list[Path] = []
    for root, dirs, files in os.walk(repo_root):
        dirs[:] = sorted(
            directory
            for directory in dirs
            if not directory.startswith(".") and directory not in _SKIP_DIRECTORIES
        )
        for filename in sorted(files):
            if filename.endswith(".py"):
                paths.append(Path(root) / filename)
    return paths


def _module_name_for_path(relative_path: Path) -> str | None:
    module_parts = list(relative_path.with_suffix("").parts)
    if module_parts and module_parts[-1] == "__init__":
        module_parts.pop()
    return ".".join(module_parts) or None


def _build_local_module_index(
    repo_root: Path,
    python_files: list[Path],
) -> dict[str, str]:
    candidates: dict[str, list[str]] = {}
    for file_path in python_files:
        relative_path = file_path.relative_to(repo_root)
        module_name = _module_name_for_path(relative_path)
        if module_name is None:
            continue
        candidates.setdefault(module_name, []).append(relative_path.as_posix())

    return {
        module_name: paths[0]
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
) -> GraphDocument:
    """Build a deterministic static Python import graph for ``repo_root``."""

    nodes: dict[str, Node] = {}
    edges: list[Edge] = []
    files_parsed = 0
    python_files = _iter_python_files(repo_root)
    module_index = _build_local_module_index(repo_root, python_files)

    for file_path in python_files:
        relative_path = file_path.relative_to(repo_root).as_posix()
        try:
            content = file_path.read_text(encoding="utf-8")
            tree = ast.parse(content, filename=relative_path)
            files_parsed += 1
        except Exception as exc:
            logger.warning("Could not parse AST for %s: %s", relative_path, exc)
            continue

        node_id = f"file:{relative_path}"
        file_node: Node = {
            "node_id": node_id,
            "kind": "file",
            "path": relative_path,
            "repo": "",
            "language": "python",
            "layer": _infer_layer(relative_path),
            "is_test": _is_test_file(relative_path),
            "size_bytes": file_path.stat().st_size,
        }
        nodes[node_id] = file_node

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
        },
    }
