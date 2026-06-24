"""Relation Cards v1 — deterministic projection of local import edges from architecture.graph.v1.

A Relation Card is a compact navigation object that projects exactly one
already-detected local import edge from an ``architecture.graph.v1``
mapping. This producer **does not detect relations**: it reads a graph mapping
that was produced elsewhere (``merger/lenskit/architecture/import_graph.py``) and
projects the supported subset of its edges into schema-shaped cards.

Supported subset (v1, imports-only):

* ``edge_type == import``
* ``evidence_level == S1``
* both endpoints are local ``kind == file`` nodes with a valid repo-relative path

Everything else (``require`` / ``config-link`` / ``string-ref`` /
``call-heuristic`` edges, non-S1 edges, and edges touching external ``module:``
nodes) is **not** a Relation Card v1 surface. Source-schema-valid but
unsupported edges are deterministically ignored: the output is a v1 projection
of the supported subset, not a complete projection of every graph edge. Edges
that are not even schema-valid never reach projection — they fail source
validation first.

The producer performs no I/O on the repository: it reads no files, scans no
repository, runs no git process, builds no graph, and uses no tree-sitter or
text search. Its only input is an already-loaded graph mapping.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from merger.lenskit.core.lens_facets import _normalize_path

KIND = "lenskit.relation_card"
VERSION = "1.0"
AUTHORITY = "navigation_index"
CANONICALITY = "derived"
RELATION = "imports"
SOURCE_RULE = "architecture_graph_import_edge"
DERIVATION_TYPE = "heuristic"
EVIDENCE_LEVEL = "S1"

# Supported source-edge selectors (architecture.graph.v1).
SUPPORTED_EDGE_TYPE = "import"
SUPPORTED_EVIDENCE_LEVEL = "S1"
FILE_NODE_KIND = "file"

# Fixed canonical negative-semantics tuple. The first nine are the shared
# lens-family baseline (docs/architecture/lens-model.md section 15); the final
# three are the relation-specific additions. Emitted in this exact, fixed order;
# the v1 contract pins both the values and the order.
DOES_NOT_ESTABLISH = (
    "truth",
    "correctness",
    "completeness",
    "runtime_behavior",
    "test_sufficiency",
    "regression_absence",
    "semantic_importance",
    "review_priority",
    "change_impact",
    "runtime_dependency",
    "causality",
    "security_assessment",
)

_SOURCE_SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent
    / "contracts"
    / "architecture.graph.v1.schema.json"
)


class SourceValidationError(ValueError):
    """Raised when the source graph cannot be trusted as a projection input.

    Carries the structured schema errors (when available) so callers — most
    importantly the source-aware validator — can surface a deterministic,
    fail-closed report instead of an opaque exception.
    """

    def __init__(self, message: str, *, errors: list[dict[str, str]] | None = None) -> None:
        super().__init__(message)
        self.errors = errors or []


def _load_jsonschema() -> Any:
    try:
        import jsonschema
    except ImportError as exc:  # fail closed: never silently skip source validation.
        raise SourceValidationError(
            "jsonschema library is required to produce Relation Cards"
        ) from exc
    return jsonschema


def _load_source_schema() -> Mapping[str, Any]:
    return json.loads(_SOURCE_SCHEMA_PATH.read_text(encoding="utf-8"))


def _schema_error_path(error: Any) -> str:
    parts = [str(part) for part in error.path]
    return "$" if not parts else "$." + ".".join(parts)


def _source_schema_errors(errors: list[Any]) -> list[dict[str, str]]:
    ordered = sorted(
        errors,
        key=lambda e: (
            tuple(str(part) for part in e.path),
            tuple(str(part) for part in e.schema_path),
            e.message,
        ),
    )
    return [
        {
            "path": _schema_error_path(e),
            "validator": str(e.validator),
            "message": e.message,
        }
        for e in ordered
    ]


def _validate_source_graph(graph_mapping: Mapping[str, Any]) -> None:
    """Validate the source graph against architecture.graph.v1 (fail closed).

    Unknown or schema-violating edge types must never be silently ignored; they
    fail here, before any projection happens.
    """
    jsonschema = _load_jsonschema()
    schema = _load_source_schema()
    jsonschema.Draft7Validator.check_schema(schema)
    validator = jsonschema.Draft7Validator(schema)
    raw_errors = list(validator.iter_errors(graph_mapping))
    if raw_errors:
        structured = _source_schema_errors(raw_errors)
        raise SourceValidationError(
            f"Source graph validation failed with {len(structured)} error(s)",
            errors=structured,
        )


def _validate_source_graph_integrity(graph_mapping: Mapping[str, Any]) -> None:
    nodes = graph_mapping.get("nodes", [])
    edges = graph_mapping.get("edges", [])

    seen_nodes: set[str] = set()
    duplicate_nodes: set[str] = set()

    for node in nodes:
        if isinstance(node, Mapping):
            node_id = node.get("node_id")
            if isinstance(node_id, str):
                if node_id in seen_nodes:
                    duplicate_nodes.add(node_id)
                else:
                    seen_nodes.add(node_id)

    errors = []
    if duplicate_nodes:
        for dup in sorted(duplicate_nodes):
            errors.append({
                "path": "$.nodes",
                "validator": "unique_node_id",
                "message": f"duplicate node_id: {dup}"
            })

    missing_src: set[str] = set()
    missing_dst: set[str] = set()

    for edge in edges:
        if isinstance(edge, Mapping):
            src = edge.get("src")
            dst = edge.get("dst")
            if isinstance(src, str) and src not in seen_nodes:
                missing_src.add(src)
            if isinstance(dst, str) and dst not in seen_nodes:
                missing_dst.add(dst)

    for src in sorted(missing_src):
        errors.append({
            "path": "$.edges",
            "validator": "edge_reference",
            "message": f"edge src does not resolve: {src}"
        })
    for dst in sorted(missing_dst):
        errors.append({
            "path": "$.edges",
            "validator": "edge_reference",
            "message": f"edge dst does not resolve: {dst}"
        })

    if errors:
        raise SourceValidationError(
            f"Source graph integrity failed with {len(errors)} error(s)",
            errors=errors
        )


def _node_index(graph_mapping: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    index: dict[str, Mapping[str, Any]] = {}
    for node in graph_mapping.get("nodes", []):
        if isinstance(node, Mapping):
            node_id = node.get("node_id")
            if isinstance(node_id, str):
                index[node_id] = node
    return index


def _is_local_file_node(node: Any) -> bool:
    return isinstance(node, Mapping) and node.get("kind") == FILE_NODE_KIND


def _validated_repo_path(raw: Any, *, role: str) -> str:
    """Return the strict repo-relative path of a local file node.

    A local ``file`` node whose path is empty, absolute, contains ``..`` or is
    otherwise outside the controlled lexical path model is treated as a corrupt
    or hostile source, not as an unsupported edge: the projection fails closed
    rather than emitting a card with an unsafe address.
    """
    try:
        return _normalize_path(raw)
    except (TypeError, ValueError) as exc:
        raise SourceValidationError(
            f"{role} file node path is not a valid repo-relative path: {raw!r}"
        ) from exc


def _project_evidence(
    raw_evidence: Any, *, source_path: str
) -> dict[str, Any]:
    """Carry the source edge evidence over verbatim, without extension or upgrade.

    The evidence of a projected local import edge is located in the importing
    (source) file. A mismatch between ``evidence.source_path`` and the source
    file node path is an inconsistent source and fails closed.
    """
    if not isinstance(raw_evidence, Mapping):
        raise SourceValidationError("import edge is missing structured evidence")
    raw_source = raw_evidence.get("source_path")
    if raw_source != source_path:
        raise SourceValidationError(
            f"import edge evidence.source_path {raw_source!r} does not match the "
            f"importing source file {source_path!r}"
        )
    evidence: dict[str, Any] = {"source_path": source_path}
    for key in ("start_line", "end_line"):
        if key in raw_evidence:
            value = raw_evidence[key]
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise SourceValidationError(
                    f"import edge evidence.{key} must be a positive integer"
                )
            evidence[key] = value
    return evidence


def _project_relation_card(
    edge: Any, node_index: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any] | None:
    """Project one supported source edge into a Relation Card, else ``None``.

    Returns ``None`` for any source-schema-valid edge that is outside the v1
    imports-only / file->file / S1 surface; such edges are deterministically
    ignored. Eligible file->file edges with an unsafe path or inconsistent
    evidence fail closed via :class:`SourceValidationError`.
    """
    if not isinstance(edge, Mapping):
        return None
    if edge.get("edge_type") != SUPPORTED_EDGE_TYPE:
        return None
    if edge.get("evidence_level") != SUPPORTED_EVIDENCE_LEVEL:
        return None

    src_node = node_index.get(edge.get("src"))
    dst_node = node_index.get(edge.get("dst"))
    if not _is_local_file_node(src_node) or not _is_local_file_node(dst_node):
        return None

    source_path = _validated_repo_path(src_node.get("path"), role="source")
    target_path = _validated_repo_path(dst_node.get("path"), role="target")
    evidence = _project_evidence(edge.get("evidence"), source_path=source_path)

    return {
        "kind": KIND,
        "version": VERSION,
        "authority": AUTHORITY,
        "canonicality": CANONICALITY,
        "relation": RELATION,
        "source": {"kind": "repo_path", "path": source_path},
        "target": {"kind": "repo_path", "path": target_path},
        "source_rule": SOURCE_RULE,
        "derivation_type": DERIVATION_TYPE,
        "evidence_level": EVIDENCE_LEVEL,
        "evidence": evidence,
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }


def _evidence_tuple(card: Mapping[str, Any]) -> tuple[Any, ...]:
    evidence = card["evidence"]
    return (
        evidence["source_path"],
        evidence.get("start_line", 0),
        evidence.get("end_line", 0),
    )


def card_identity(card: Mapping[str, Any]) -> tuple[Any, ...]:
    """Deterministic identity of a Relation Card.

    A card corresponds to exactly one canonical source edge, identified by its
    source path, target path and full evidence position. Distinct source edges
    with different evidence positions are therefore never collapsed; only exactly
    identical cards share an identity and are deduplicated.
    """
    return (card["source"]["path"], card["target"]["path"]) + _evidence_tuple(card)


def _sort_key(card: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        card["source"]["path"],
        card["target"]["path"],
        card["relation"],
    ) + _evidence_tuple(card)


def produce_relation_cards(graph_mapping: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Project the supported subset of an architecture.graph.v1 mapping.

    The graph is validated against ``architecture.graph.v1`` first (fail closed
    if ``jsonschema`` is unavailable or the graph is invalid). Only local
    file->file ``import`` edges at ``S1`` are projected; every other edge is
    deterministically ignored. The result is a stably sorted, exact-duplicate
    deduplicated list — input order does not affect the output or its order, and
    no lossy aggregation is performed.
    """
    if not isinstance(graph_mapping, Mapping):
        raise TypeError("graph_mapping must be a mapping")

    _validate_source_graph(graph_mapping)
    _validate_source_graph_integrity(graph_mapping)
    node_index = _node_index(graph_mapping)

    cards: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for edge in graph_mapping.get("edges", []):
        card = _project_relation_card(edge, node_index)
        if card is None:
            continue
        identity = card_identity(card)
        if identity in seen:
            continue
        seen.add(identity)
        cards.append(card)

    cards.sort(key=_sort_key)
    return cards
