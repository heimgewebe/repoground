"""Bounded graph-noise and entrypoint-projection measurements."""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from merger.repoground.architecture.entrypoints import generate_entrypoints_document
from merger.repoground.architecture.import_graph import generate_import_graph_document
from merger.repoground.architecture.path_classification import path_projection

PROJECTIONS = ("product", "test", "fixture", "script")


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def measure_graph_maintainability(repo_root: Path) -> dict[str, Any]:
    """Measure real-repository graph noise without mixing external modules in."""

    graph = generate_import_graph_document(repo_root, "maintainability", "0" * 64)
    entrypoints = generate_entrypoints_document(
        repo_root,
        "maintainability",
        "0" * 64,
    )
    file_nodes = [node for node in graph["nodes"] if node["kind"] == "file"]
    external_nodes = [node for node in graph["nodes"] if node["kind"] == "external"]
    projected: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for node in file_nodes:
        projected[path_projection(node["path"])].append(node)

    projection_metrics: dict[str, dict[str, Any]] = {}
    for projection in PROJECTIONS:
        nodes = projected[projection]
        unknown = sum(node.get("layer") == "unknown" for node in nodes)
        projection_metrics[projection] = {
            "file_count": len(nodes),
            "unknown_layer_count": unknown,
            "unknown_layer_share": _ratio(unknown, len(nodes)),
            "layers": dict(sorted(Counter(node.get("layer") for node in nodes).items())),
        }

    coverage = graph["coverage"]
    parsed = int(coverage["files_parsed"])
    seen = int(coverage["files_seen"])
    unknown_files = sum(node.get("layer") == "unknown" for node in file_nodes)
    entrypoint_counts = entrypoints["entrypoint_counts_by_projection"]
    return {
        "kind": "repoground.graph_maintainability_measurement",
        "version": "1.0",
        "graph": {
            "file_node_count": len(file_nodes),
            "external_node_count": len(external_nodes),
            "edge_count": len(graph["edges"]),
            "files_seen": seen,
            "files_parsed": parsed,
            "parse_success_rate": _ratio(parsed, seen),
            "file_unknown_layer_count": unknown_files,
            "file_unknown_layer_share": _ratio(unknown_files, len(file_nodes)),
            "external_to_file_ratio": _ratio(len(external_nodes), len(file_nodes)),
            "edges_per_parsed_file": _ratio(len(graph["edges"]), parsed),
            "legacy_all_node_unknown_share": coverage["unknown_layer_share"],
            "projections": projection_metrics,
        },
        "entrypoints": {
            "total": len(entrypoints["entrypoints"]),
            "counts_by_projection": entrypoint_counts,
            "projection_sum": sum(entrypoint_counts.values()),
            "skipped_files_count": entrypoints.get("skipped_files_count", 0),
        },
        "does_not_establish": [
            "runtime call reachability",
            "semantic correctness of inferred layers",
            "complete entrypoint discovery",
            "absence of dynamic imports",
            "overall maintainability",
        ],
    }


def evaluate_graph_policy(
    measurement: dict[str, Any],
    policy: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return deterministic threshold findings for one measurement."""

    findings: list[dict[str, Any]] = []
    graph = measurement["graph"]
    graph_policy = policy["graph"]
    checks = (
        ("parse_success_rate", "minimum", graph_policy["parse_success_rate_min"]),
        (
            "file_unknown_layer_share",
            "maximum",
            graph_policy["file_unknown_layer_share_max"],
        ),
        (
            "external_to_file_ratio",
            "maximum",
            graph_policy["external_to_file_ratio_max"],
        ),
        (
            "edges_per_parsed_file",
            "maximum",
            graph_policy["edges_per_parsed_file_max"],
        ),
    )
    for metric, direction, limit in checks:
        observed = graph[metric]
        failed = observed < limit if direction == "minimum" else observed > limit
        if failed:
            findings.append(
                {
                    "code": f"graph_{metric}_{direction}_violated",
                    "metric": metric,
                    "observed": observed,
                    "limit": limit,
                }
            )

    product = graph["projections"]["product"]
    product_limit = graph_policy["product_unknown_layer_share_max"]
    if product["unknown_layer_share"] > product_limit:
        findings.append(
            {
                "code": "graph_product_unknown_layer_share_maximum_violated",
                "metric": "product_unknown_layer_share",
                "observed": product["unknown_layer_share"],
                "limit": product_limit,
            }
        )

    required = set(policy["entrypoints"]["required_projections"])
    counts = measurement["entrypoints"]["counts_by_projection"]
    if set(counts) != required:
        findings.append(
            {
                "code": "entrypoint_projection_set_mismatch",
                "observed": sorted(counts),
                "required": sorted(required),
            }
        )
    if measurement["entrypoints"]["projection_sum"] != measurement["entrypoints"]["total"]:
        findings.append(
            {
                "code": "entrypoint_projection_count_mismatch",
                "observed": measurement["entrypoints"]["projection_sum"],
                "required": measurement["entrypoints"]["total"],
            }
        )
    return findings
