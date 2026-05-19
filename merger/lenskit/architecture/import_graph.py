"""
Extracts a Python import graph via static AST analysis.

Resolver Boundaries (S1 MVP):
- This artifact is S1 (static heuristic) and does not represent runtime causality.
- Relative import resolution is an MVP heuristic and might not resolve complex edge cases.
- Absolute ImportFrom edges intentionally generate edges to both the base module and the submodule.
- Targets that cannot be safely resolved locally remain as modular/external string representations.
- Star imports (`*`) are not semantically expanded.
- `repo` and `layer` attributes are currently placeholders or minimal.
"""

import ast
import os
import logging
from typing import TypedDict, List, Dict, Literal
from pathlib import Path
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

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
    edge_counts_by_type: Dict[str, int]
    unknown_layer_share: float

class GraphDocument(TypedDict, total=False):
    kind: Literal["lenskit.architecture.graph"]
    version: Literal["1.0"]
    run_id: str
    canonical_dump_index_sha256: str
    generated_at: str
    granularity: str
    nodes: List[Node]
    edges: List[Edge]
    coverage: Coverage


def _is_test_file(path: str) -> bool:
    name = Path(path).name
    return name.startswith("test_") or name.endswith("_test.py")

def _get_module_id(import_name: str) -> str:
    """Returns a deterministic node_id for an imported module."""
    # E.g. 'os.path' -> 'external:os.path' for external modules.
    # In a simple MVP, we treat all imported modules as external or local.
    # For simplicity in this graph MVP, we prefix with 'module:'
    return f"module:{import_name}"


def generate_import_graph_document(
    repo_root: Path,
    run_id: str,
    canonical_dump_index_sha256: str
) -> GraphDocument:
    """
    Parses Python files in the given repository root via AST to build an import graph.
    Returns a JSON-serializable dict conforming to architecture.graph.v1.schema.json.
    """
    nodes: Dict[str, Node] = {}
    edges: List[Edge] = []

    files_seen = 0
    files_parsed = 0

    # We will build up nodes and edges while traversing.
    for root, dirs, files in os.walk(repo_root):
        # Exclude common directories to ignore
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ('__pycache__', 'venv', 'env', 'node_modules')]

        for file in files:
            if file.endswith('.py'):
                files_seen += 1
                file_path = Path(root) / file
                rel_path = file_path.relative_to(repo_root).as_posix()

                try:
                    content = file_path.read_text(encoding='utf-8')
                    tree = ast.parse(content, filename=rel_path)
                    files_parsed += 1
                except Exception as e:
                    logger.warning("Could not parse AST for %s: %s", rel_path, e)
                    continue

                # Register the file as a node
                node_id = f"file:{rel_path}"
                stat = file_path.stat()
                is_test = _is_test_file(rel_path)

                if node_id not in nodes:
                    nodes[node_id] = {
                        "node_id": node_id,
                        "kind": "file",
                        "path": rel_path,
                        "repo": "",  # In a full run, this is injected
                        "language": "python",
                        "layer": "unknown",
                        "is_test": is_test,
                        "size_bytes": stat.st_size
                    }
                else:
                    # Update placeholder node
                    nodes[node_id]["size_bytes"] = stat.st_size

                # Find imports
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            dst_module = alias.name
                            dst_id = _get_module_id(dst_module)

                            destinations = [dst_module]

                            evidence: Evidence = {
                                "source_path": rel_path,
                            }
                            if hasattr(node, 'lineno'):
                                evidence["start_line"] = node.lineno
                                evidence["end_line"] = getattr(node, 'end_lineno', node.lineno)

                            for dest in destinations:
                                dst_id = _get_module_id(dest)
                                if dst_id not in nodes:
                                    nodes[dst_id] = {
                                        "node_id": dst_id,
                                        "kind": "external",
                                        "path": "",
                                        "repo": "",
                                        "language": "python",
                                        "layer": "unknown",
                                        "is_test": False,
                                        "size_bytes": 0
                                    }
                                edges.append({
                                    "src": node_id,
                                    "dst": dst_id,
                                    "edge_type": "import",
                                    "evidence_level": "S1",
                                    "evidence": evidence
                                })

                    elif isinstance(node, ast.ImportFrom):
                        destinations = []
                        is_relative = node.level > 0

                        if is_relative:
                            # Relative imports
                            if node.module is not None:
                                current_dir = file_path.parent
                                for _ in range(node.level - 1):
                                    current_dir = current_dir.parent

                                # Try resolving to a file if alias is not '*'
                                for alias in node.names:
                                    if alias.name == "*":
                                        continue

                                    # Target could be current_dir / module_dir / alias.name.py
                                    # Or target could be current_dir / module.py (and alias is just something inside)
                                    # We try module_dir / alias.name.py first
                                    module_parts = node.module.split('.')

                                    target_dir = current_dir
                                    for part in module_parts:
                                        target_dir = target_dir / part

                                    target_file = target_dir / f"{alias.name}.py"
                                    if target_file.is_file():
                                        destinations.append(f"file:{target_file.relative_to(repo_root).as_posix()}")
                                    elif (current_dir / f"{module_parts[0]}.py").is_file():
                                        # e.g., from .b import bar where b is b.py
                                        destinations.append(f"file:{(current_dir / f'{module_parts[0]}.py').relative_to(repo_root).as_posix()}")
                                    else:
                                        # Fallback to string module representations
                                        dest_mod = "." * node.level + node.module
                                        destinations.append(f"module:{dest_mod}")
                                        destinations.append(f"module:{dest_mod}.{alias.name}")
                            else:
                                # from . import b
                                current_dir = file_path.parent
                                for _ in range(node.level - 1):
                                    current_dir = current_dir.parent

                                for alias in node.names:
                                    target_file = current_dir / f"{alias.name}.py"
                                    if target_file.is_file():
                                        destinations.append(f"file:{target_file.relative_to(repo_root).as_posix()}")
                                    else:
                                        destinations.append(f"module:{'.' * node.level}{alias.name}")
                        else:
                            # Absolute ImportFrom (e.g., from os import path)
                            if node.module is not None:
                                destinations.append(f"module:{node.module}")
                                for alias in node.names:
                                    if alias.name != "*":
                                        destinations.append(f"module:{node.module}.{alias.name}")

                        evidence: Evidence = {
                            "source_path": rel_path,
                        }
                        if hasattr(node, 'lineno'):
                            evidence["start_line"] = node.lineno
                            evidence["end_line"] = getattr(node, 'end_lineno', node.lineno)

                        for dest in destinations:
                            if dest.startswith("file:"):
                                dst_id = dest
                                # if it's a file but not in nodes, we can add a placeholder, it will be filled when visited
                                if dst_id not in nodes:
                                    nodes[dst_id] = {
                                        "node_id": dst_id,
                                        "kind": "file",
                                        "path": dest[5:],
                                        "repo": "",
                                        "language": "python",
                                        "layer": "unknown",
                                        "is_test": _is_test_file(dest[5:]),
                                        "size_bytes": 0 # placeholder
                                    }
                            else:
                                dst_id = dest
                                if dst_id not in nodes:
                                    nodes[dst_id] = {
                                        "node_id": dst_id,
                                        "kind": "external",
                                        "path": "",
                                        "repo": "",
                                        "language": "python",
                                        "layer": "unknown",
                                        "is_test": False,
                                        "size_bytes": 0
                                    }

                            edges.append({
                                "src": node_id,
                                "dst": dst_id,
                                "edge_type": "import",
                                "evidence_level": "S1",
                                "evidence": evidence
                            })

    # Determinism: sort nodes and edges
    sorted_nodes = sorted(nodes.values(), key=lambda n: n["node_id"])

    # Deduplicate edges
    unique_edges = {}
    for e in edges:
        key = (e["src"], e["dst"], e["evidence"].get("start_line", 0))
        if key not in unique_edges:
            unique_edges[key] = e

    sorted_edges = sorted(unique_edges.values(), key=lambda e: (e["src"], e["dst"], e["evidence"].get("start_line", 0)))

    # Coverage
    unknown_layer_count = sum(1 for n in sorted_nodes if n.get("layer") == "unknown")
    unknown_layer_share = (unknown_layer_count / len(sorted_nodes)) if sorted_nodes else 0.0

    edge_counts_by_type = {}
    for e in sorted_edges:
        edge_counts_by_type[e["edge_type"]] = edge_counts_by_type.get(e["edge_type"], 0) + 1

    coverage: Coverage = {
        "files_seen": files_seen,
        "files_parsed": files_parsed,
        "edge_counts_by_type": edge_counts_by_type,
        "unknown_layer_share": unknown_layer_share
    }

    if files_seen > 0 and files_parsed / files_seen < 0.5:
        logger.warning("Low AST parsing coverage: %.2f%%", (files_parsed / files_seen) * 100)

    doc: GraphDocument = {
        "kind": "lenskit.architecture.graph",
        "version": "1.0",
        "run_id": run_id,
        "canonical_dump_index_sha256": canonical_dump_index_sha256,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "granularity": "file",
        "nodes": sorted_nodes,
        "edges": sorted_edges,
        "coverage": coverage
    }

    return doc
