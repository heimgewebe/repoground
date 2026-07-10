import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

try:
    import jsonschema
except ImportError:
    jsonschema = None

from ..core.path_security import resolve_secure_path
from .graph_source_validation import (
    GraphIndexCompilationError,
    load_source,
    require_coherence,
)

logger = logging.getLogger(__name__)

_GRAPH_INDEX_SCHEMA_PATH = (
    Path(__file__).parent.parent
    / "contracts"
    / "architecture.graph_index.v1.schema.json"
)


def load_graph_index(
    root: Path,
    relative_path: str,
    expected_sha256: Optional[str] = None,
) -> Dict[str, Any]:
    """Load a graph index through a root-bounded relative path."""

    try:
        path = resolve_secure_path(root, relative_path)
    except ValueError as exc:
        logger.warning("Graph index path rejected: %s", exc)
        return {"status": "invalid_path", "graph": None}

    if not path.exists():  # lgtm[py/path-injection]
        return {"status": "not_found", "graph": None}
    try:
        with path.open(encoding="utf-8") as handle:  # lgtm[py/path-injection]
            data = json.load(handle)
    except json.JSONDecodeError:
        return {"status": "invalid_json", "graph": None}
    except OSError as exc:
        logger.warning("Graph index file unreadable: %s", exc)
        return {"status": "unreadable", "graph": None}

    if jsonschema is None:
        logger.warning(
            "Graph index validation unavailable because jsonschema is not installed"
        )
        return {"status": "validation_unavailable", "graph": None}

    try:
        with _GRAPH_INDEX_SCHEMA_PATH.open(encoding="utf-8") as handle:
            schema = json.load(handle)
        jsonschema.Draft7Validator.check_schema(schema)
        validator = jsonschema.Draft7Validator(schema)
        validator.validate(data)
    except jsonschema.ValidationError as exc:
        logger.warning("Graph index schema validation failed: %s", exc)
        return {"status": "invalid_schema", "graph": None}
    except (OSError, json.JSONDecodeError, jsonschema.SchemaError) as exc:
        logger.error("Graph index schema validation unavailable: %s", exc)
        return {"status": "validation_unavailable", "graph": None}

    if expected_sha256:
        graph_sha = data.get("canonical_dump_index_sha256")
        if not graph_sha or graph_sha != expected_sha256:
            return {"status": "stale_or_mismatched", "graph": data}
    return {"status": "ok", "graph": data}


def _sibling_dump_index(
    graph_path: Path,
    entrypoints_path: Path,
) -> Path | None:
    graph_suffix = ".architecture_graph.json"
    entrypoints_suffix = ".entrypoints.json"
    if not graph_path.name.endswith(graph_suffix):
        return None
    if not entrypoints_path.name.endswith(entrypoints_suffix):
        return None

    graph_stem = graph_path.name[: -len(graph_suffix)]
    entrypoints_stem = entrypoints_path.name[: -len(entrypoints_suffix)]
    if graph_path.parent != entrypoints_path.parent or graph_stem != entrypoints_stem:
        return None

    candidate = graph_path.parent / f"{graph_stem}.dump_index.json"
    return candidate if candidate.is_file() else None


def _infer_bundle_provenance(
    graph_path: Path,
    entrypoints_path: Path,
) -> tuple[str | None, str | None]:
    dump_index_path = _sibling_dump_index(graph_path, entrypoints_path)
    if dump_index_path is None:
        return None, None

    try:
        raw_dump_index = dump_index_path.read_bytes()
        dump_index = json.loads(raw_dump_index.decode("utf-8"))
        run_id = dump_index["run_id"]
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
    ) as exc:
        raise GraphIndexCompilationError(
            "bundle_provenance_unavailable",
            f"sibling dump index is unusable: {dump_index_path}",
            source="expected_provenance",
            errors=[str(exc)],
        ) from exc

    if not isinstance(run_id, str) or not run_id:
        raise GraphIndexCompilationError(
            "invalid_expected_provenance",
            "sibling dump index run_id must be a non-empty string",
            source="expected_provenance",
        )

    digest = hashlib.sha256(raw_dump_index).hexdigest()
    return run_id, digest


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
    if expected_run_id is None and expected_canonical_sha256 is None:
        expected_run_id, expected_canonical_sha256 = _infer_bundle_provenance(
            graph_path,
            entrypoints_path,
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
