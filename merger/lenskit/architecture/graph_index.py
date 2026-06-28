import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

try:
    import jsonschema
except ImportError:
    jsonschema = None

from .graph_source_validation import (
    GraphIndexCompilationError,
    load_source,
    require_coherence,
)

logger = logging.getLogger(__name__)


def load_graph_index(
    path: Path,
    expected_sha256: Optional[str] = None,
) -> Dict[str, Any]:
    """Load and validate a graph index while preserving the status contract."""

    if not path.exists():
        return {"status": "not_found", "graph": None}
    try:
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except json.JSONDecodeError:
        return {"status": "invalid_json", "graph": None}
    except OSError as exc:
        logger.warning("Graph index file unreadable: %s", exc)
        return {"status": "unreadable", "graph": None}

    schema_path = (
        Path(__file__).parent.parent
        / "contracts"
        / "architecture.graph_index.v1.schema.json"
    )
    if schema_path.exists():
        if jsonschema is None:
            logger.warning(
                "Schema validation skipped because jsonschema is unavailable "
                "in this environment."
            )
        else:
            try:
                with schema_path.open(encoding="utf-8") as handle:
                    schema = json.load(handle)
                jsonschema.validate(instance=data, schema=schema)
            except jsonschema.ValidationError as exc:
                logger.warning("Graph index schema validation failed: %s", exc)
                return {"status": "invalid_schema", "graph": None}
            except Exception as exc:
                logger.error("Error reading/validating graph schema: %s", exc)
                return {"status": "invalid_schema", "graph": None}

    if expected_sha256:
        graph_sha = data.get("canonical_dump_index_sha256")
        if not graph_sha or graph_sha != expected_sha256:
            return {"status": "stale_or_mismatched", "graph": data}
    return {"status": "ok", "graph": data}


def compile_graph_index(
    graph_path: Path,
    entrypoints_path: Path,
    *,
    expected_run_id: str | None = None,
    expected_canonical_sha256: str | None = None,
) -> Dict[str, Any]:
    """Compile distances from validated, provenance-coherent source documents."""

    graph = load_source(
        graph_path,
        "architecture.graph.v1.schema.json",
        "architecture_graph",
    )
    entrypoints = load_source(
        entrypoints_path,
        "entrypoints.v1.schema.json",
        "entrypoints",
    )
    run_id, canonical_sha = require_coherence(
        graph,
        entrypoints,
        expected_run_id=expected_run_id,
        expected_canonical_sha256=expected_canonical_sha256,
    )

    index: Dict[str, Any] = {
        "kind": "lenskit.architecture.graph_index",
        "version": "1.0",
        "run_id": run_id,
        "canonical_dump_index_sha256": canonical_sha,
        "distances": {},
        "metrics": {
            "entrypoint_count": 0,
            "nodes_reachable": 0,
            "unreachable_nodes": 0,
        },
    }
    adjacency: dict[str, list[str]] = {}
    nodes_by_path: dict[str, str] = {}
    node_meta_by_id: dict[str, dict[str, Any]] = {}

    for node in graph["nodes"]:
        node_id = node["node_id"]
        adjacency[node_id] = []
        node_meta_by_id[node_id] = node
        if node.get("path"):
            nodes_by_path[node["path"]] = node_id

    for edge in graph["edges"]:
        if edge["src"] in adjacency:
            adjacency[edge["src"]].append(edge["dst"])
    for neighbors in adjacency.values():
        neighbors.sort()

    entrypoint_nodes = {
        nodes_by_path[item["path"]]
        for item in entrypoints["entrypoints"]
        if item.get("path") in nodes_by_path
    }
    index["metrics"]["entrypoint_count"] = len(entrypoint_nodes)

    distances: dict[str, int] = {}
    queue = sorted(entrypoint_nodes)
    for node_id in queue:
        distances[node_id] = 0
    head = 0
    while head < len(queue):
        current = queue[head]
        head += 1
        for neighbor in adjacency.get(current, []):
            if neighbor not in distances:
                distances[neighbor] = distances[current] + 1
                queue.append(neighbor)

    for node_id in sorted(adjacency):
        distance = distances.get(node_id, -1)
        index["distances"][node_id] = distance
        path = node_meta_by_id[node_id].get("path")
        if path and f"file:{path}" != node_id:
            index["distances"][f"file:{path}"] = distance

    reachable = sum(node_id in distances for node_id in adjacency)
    index["metrics"]["nodes_reachable"] = reachable
    index["metrics"]["unreachable_nodes"] = len(adjacency) - reachable
    return index


__all__ = [
    "GraphIndexCompilationError",
    "compile_graph_index",
    "load_graph_index",
]
