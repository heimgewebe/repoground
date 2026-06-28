from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .import_graph import GraphDocument, generate_import_graph_document


class GraphQualityGoldsetError(ValueError):
    """The graph-quality goldset is structurally invalid."""


def load_graph_quality_goldset(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GraphQualityGoldsetError(f"cannot load graph goldset: {path}") from exc

    if not isinstance(payload, dict):
        raise GraphQualityGoldsetError("graph goldset must be a JSON object")
    if payload.get("kind") != "lenskit.graph_quality_goldset":
        raise GraphQualityGoldsetError("unexpected graph goldset kind")
    if payload.get("version") != "1.0":
        raise GraphQualityGoldsetError("unsupported graph goldset version")

    for key in (
        "fixture_root",
        "local_resolution_cases",
        "external_preservation_cases",
        "layer_cases",
        "does_not_establish",
    ):
        if key not in payload:
            raise GraphQualityGoldsetError(f"graph goldset missing {key}")

    case_ids: set[str] = set()
    for case in payload["local_resolution_cases"]:
        if not isinstance(case, Mapping):
            raise GraphQualityGoldsetError("local resolution case must be an object")
        required = {"id", "source", "target", "import_form"}
        if not required.issubset(case):
            raise GraphQualityGoldsetError("local resolution case is incomplete")
        case_id = str(case["id"])
        if case_id in case_ids:
            raise GraphQualityGoldsetError(f"duplicate case id: {case_id}")
        case_ids.add(case_id)

    for case in payload["external_preservation_cases"]:
        if not isinstance(case, Mapping):
            raise GraphQualityGoldsetError("external preservation case must be an object")
        required = {"id", "source", "module"}
        if not required.issubset(case):
            raise GraphQualityGoldsetError("external preservation case is incomplete")
        case_id = str(case["id"])
        if case_id in case_ids:
            raise GraphQualityGoldsetError(f"duplicate case id: {case_id}")
        case_ids.add(case_id)

    for case in payload["layer_cases"]:
        if not isinstance(case, Mapping) or not {"path", "expected"}.issubset(case):
            raise GraphQualityGoldsetError("layer case is incomplete")

    return payload


def _ratio(hits: int, total: int) -> float:
    return round(hits / total, 6) if total else 0.0


def evaluate_graph_quality_document(
    graph: GraphDocument,
    goldset: Mapping[str, Any],
) -> dict[str, Any]:
    edge_pairs = {(edge["src"], edge["dst"]) for edge in graph.get("edges", [])}
    nodes = {node["node_id"]: node for node in graph.get("nodes", [])}

    local_results = []
    for case in goldset["local_resolution_cases"]:
        source_id = f"file:{case['source']}"
        target_id = f"file:{case['target']}"
        found = (source_id, target_id) in edge_pairs
        local_results.append(
            {
                "id": case["id"],
                "source": case["source"],
                "target": case["target"],
                "found": found,
            }
        )

    external_results = []
    for case in goldset["external_preservation_cases"]:
        source_id = f"file:{case['source']}"
        target_id = f"module:{case['module']}"
        node = nodes.get(target_id)
        found = (source_id, target_id) in edge_pairs and bool(
            node and node.get("kind") == "external"
        )
        external_results.append(
            {
                "id": case["id"],
                "source": case["source"],
                "module": case["module"],
                "found": found,
            }
        )

    layer_results = []
    for case in goldset["layer_cases"]:
        node = nodes.get(f"file:{case['path']}")
        actual = node.get("layer") if node else None
        layer_results.append(
            {
                "path": case["path"],
                "expected": case["expected"],
                "actual": actual,
                "found": actual == case["expected"],
            }
        )

    local_hits = sum(item["found"] for item in local_results)
    external_hits = sum(item["found"] for item in external_results)
    layer_hits = sum(item["found"] for item in layer_results)
    file_nodes = [node for node in graph.get("nodes", []) if node.get("kind") == "file"]
    unknown_file_layers = sum(node.get("layer") == "unknown" for node in file_nodes)

    return {
        "kind": "lenskit.graph_quality_baseline",
        "version": "1.0",
        "metrics": {
            "local_resolution": {
                "total": len(local_results),
                "hits": local_hits,
                "misses": len(local_results) - local_hits,
                "recall": _ratio(local_hits, len(local_results)),
            },
            "external_preservation": {
                "total": len(external_results),
                "hits": external_hits,
                "misses": len(external_results) - external_hits,
                "accuracy": _ratio(external_hits, len(external_results)),
            },
            "layer_assignment": {
                "total": len(layer_results),
                "hits": layer_hits,
                "misses": len(layer_results) - layer_hits,
                "accuracy": _ratio(layer_hits, len(layer_results)),
                "unknown_file_share": _ratio(unknown_file_layers, len(file_nodes)),
            },
        },
        "cases": {
            "local_resolution": local_results,
            "external_preservation": external_results,
            "layer_assignment": layer_results,
        },
        "does_not_establish": list(goldset["does_not_establish"]),
    }


def evaluate_graph_quality_fixture(
    repo_root: Path,
    goldset: Mapping[str, Any],
) -> dict[str, Any]:
    graph = generate_import_graph_document(
        repo_root,
        run_id="graph-quality-goldset-v1",
        canonical_dump_index_sha256="0" * 64,
    )
    return evaluate_graph_quality_document(graph, goldset)
