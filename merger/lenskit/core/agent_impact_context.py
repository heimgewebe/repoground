"""Deterministic read-only impact and edit context for RepoBrief bundles.

The producer composes already-emitted Lenskit artifacts. It does not scan a
repository, execute code, refresh snapshots, mutate Git, or issue review
verdicts. Every relation keeps its source direction and evidence level.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import PurePosixPath
from typing import Any

KIND = "repobrief.agent_impact_context"
VERSION = "1.0"
MODES = ("impact", "edit")
MAX_ITEMS_LIMIT = 200

DOES_NOT_ESTABLISH = (
    "complete_call_graph",
    "complete_blast_radius",
    "runtime_behavior",
    "correctness",
    "test_sufficiency",
    "test_coverage",
    "review_completeness",
    "merge_readiness",
    "security_correctness",
    "repository_understanding",
    "agent_quality_improvement",
)

MUTATION_BOUNDARY = {
    "writes": [],
    "does_not_mutate": [
        "git",
        "pull_requests",
        "patches",
        "source_working_tree",
        "brief_bundle_artifacts",
        "memory_stores",
    ],
    "read_paths_do_not_refresh": True,
}


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _items(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _clean_text(value: Any, *, field: str, required: bool = False) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    text = value.strip()
    if required and not text:
        raise ValueError(f"{field} must not be empty")
    return text or None


def _repo_path(value: Any, *, field: str) -> str:
    text = _clean_text(value, field=field, required=True)
    assert text is not None
    if (
        text.startswith("/")
        or "\\" in text
        or "//" in text
        or text.endswith("/")
    ):
        raise ValueError(f"{field} must be a canonical repository-relative path")
    path = PurePosixPath(text)
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"{field} must not contain empty, dot or parent segments")
    return path.as_posix()


def _bounded_int(value: Any, *, field: str, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be an integer")
    if value < 1 or value > MAX_ITEMS_LIMIT:
        raise ValueError(f"{field} must be between 1 and {MAX_ITEMS_LIMIT}")
    return value


def _identity(document: Any) -> tuple[str | None, str | None]:
    item = _mapping(document)
    run_id = item.get("run_id")
    digest = item.get("canonical_dump_index_sha256")
    return (
        run_id if isinstance(run_id, str) and run_id else None,
        digest if isinstance(digest, str) and digest else None,
    )


def _source_state(source: str, document: Any) -> dict[str, Any]:
    item = _mapping(document)
    run_id, digest = _identity(item)
    return {
        "source": source,
        "status": "available" if item else "missing",
        "run_id": run_id,
        "canonical_dump_index_sha256": digest,
    }


def _merge_source_states(
    calculated: list[dict[str, Any]],
    supplied: Any,
) -> list[dict[str, Any]]:
    by_source = {str(item["source"]): dict(item) for item in calculated}
    for raw in supplied if isinstance(supplied, list) else []:
        if not isinstance(raw, Mapping):
            continue
        source = raw.get("source")
        if not isinstance(source, str) or not source:
            continue
        current = by_source.setdefault(source, {"source": source})
        current.update(dict(raw))
    return [by_source[name] for name in sorted(by_source)]


def _coherence(
    sources: list[dict[str, Any]],
) -> tuple[str, str | None, str | None, list[dict[str, Any]]]:
    identities = {
        (item.get("run_id"), item.get("canonical_dump_index_sha256"))
        for item in sources
        if item.get("status") == "available"
        and item.get("run_id")
        and item.get("canonical_dump_index_sha256")
    }
    gaps = [
        {
            "source": item.get("source"),
            "status": item.get("status"),
            "reason": "source_unavailable",
        }
        for item in sources
        if item.get("status") != "available"
    ]
    gaps.extend(
        {
            "source": item.get("source"),
            "status": "identity_missing",
            "reason": "available_source_has_no_bundle_identity",
        }
        for item in sources
        if item.get("status") == "available"
        and not (
            item.get("run_id")
            and item.get("canonical_dump_index_sha256")
        )
        and item.get("source")
        in {
            "architecture_graph_json",
            "python_symbol_index_json",
            "entrypoints_json",
        }
    )
    blocking_sources = [
        item
        for item in sources
        if item.get("source")
        in {
            "architecture_graph_json",
            "python_symbol_index_json",
            "entrypoints_json",
        }
        and item.get("status")
        in {
            "blocked",
            "stale",
            "stale_or_mismatched",
            "invalid_json",
            "invalid_schema",
        }
    ]
    if blocking_sources:
        gaps.append(
            {
                "source": "artifact_coherence",
                "status": "blocked",
                "reason": "required_source_untrusted",
                "sources": [
                    {
                        "source": item.get("source"),
                        "status": item.get("status"),
                        "error_code": item.get("error_code"),
                    }
                    for item in blocking_sources
                ],
            }
        )
        return "blocked", None, None, gaps
    if len(identities) > 1:
        gaps.append(
            {
                "source": "artifact_coherence",
                "status": "blocked",
                "reason": "run_id_or_canonical_digest_mismatch",
                "identities": [
                    {
                        "run_id": run_id,
                        "canonical_dump_index_sha256": digest,
                    }
                    for run_id, digest in sorted(identities)
                ],
            }
        )
        return "blocked", None, None, gaps
    if identities:
        run_id, digest = next(iter(identities))
        return "coherent", str(run_id), str(digest), gaps
    gaps.append(
        {
            "source": "artifact_coherence",
            "status": "unknown",
            "reason": "no_shared_provenance_identity_available",
        }
    )
    return "unknown", None, None, gaps


def _is_test_path(path: str) -> bool:
    name = PurePosixPath(path).name
    return (
        "/tests/" in f"/{path}"
        or path.startswith("tests/")
        or name.startswith("test_")
        or name.endswith("_test.py")
    )


def _path_class(path: str) -> str:
    if _is_test_path(path):
        return "test"
    if path.startswith("docs/") or "/docs/" in f"/{path}":
        return "documentation"
    if (
        "/contracts/" in f"/{path}"
        or path.startswith("contracts/")
        or path.endswith(".schema.json")
    ):
        return "contract"
    return "implementation"


def _node_index(
    graph: Mapping[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    nodes_by_id: dict[str, dict[str, Any]] = {}
    id_by_path: dict[str, str] = {}
    for raw in _items(graph.get("nodes")):
        if not isinstance(raw, Mapping):
            continue
        node_id = raw.get("node_id")
        path = raw.get("path")
        if not isinstance(node_id, str) or not node_id:
            continue
        node = dict(raw)
        nodes_by_id[node_id] = node
        if isinstance(path, str) and path and path not in id_by_path:
            id_by_path[path] = node_id
    return nodes_by_id, id_by_path


def _matching_symbols(
    symbol_index: Mapping[str, Any],
    *,
    target_symbol: str | None,
    target_paths: set[str],
    max_items: int,
) -> tuple[list[dict[str, Any]], set[str], bool]:
    matches: list[dict[str, Any]] = []
    derived_paths: set[str] = set()
    folded = target_symbol.casefold() if target_symbol else None
    for raw in _items(symbol_index.get("symbols")):
        if not isinstance(raw, Mapping):
            continue
        symbol = dict(raw)
        path = symbol.get("path")
        values = (
            symbol.get("id"),
            symbol.get("name"),
            symbol.get("qualified_name"),
        )
        exact = bool(
            folded
            and any(
                isinstance(value, str) and value.casefold() == folded
                for value in values
            )
        )
        path_match = isinstance(path, str) and path in target_paths
        if not exact and not path_match:
            continue
        matches.append(symbol)
        if exact and isinstance(path, str):
            derived_paths.add(path)
    matches.sort(
        key=lambda item: (
            str(item.get("path", "")),
            int(item.get("start_line", 0) or 0),
            str(item.get("qualified_name", "")),
        )
    )
    unique: dict[str, dict[str, Any]] = {}
    for symbol in matches:
        key = str(
            symbol.get("id")
            or (
                symbol.get("path"),
                symbol.get("qualified_name"),
                symbol.get("start_line"),
            )
        )
        unique.setdefault(key, symbol)
    ordered = list(unique.values())
    return ordered[:max_items], derived_paths, len(ordered) > max_items


def _relation_record(
    edge: Mapping[str, Any],
    *,
    direction: str,
    target_node: Mapping[str, Any],
    peer_node: Mapping[str, Any],
) -> dict[str, Any]:
    target_path = target_node.get("path")
    peer_path = peer_node.get("path")
    return {
        "direction": direction,
        "edge_type": edge.get("edge_type"),
        "evidence_level": edge.get("evidence_level"),
        "evidence": (
            dict(edge["evidence"])
            if isinstance(edge.get("evidence"), Mapping)
            else None
        ),
        "target": {
            "node_id": target_node.get("node_id"),
            "path": target_path,
            "kind": target_node.get("kind"),
        },
        "peer": {
            "node_id": peer_node.get("node_id"),
            "path": peer_path,
            "kind": peer_node.get("kind"),
            "is_test": bool(peer_node.get("is_test"))
            or bool(isinstance(peer_path, str) and _is_test_path(peer_path)),
            "path_class": (
                _path_class(peer_path) if isinstance(peer_path, str) else None
            ),
        },
        "authority": "derived_graph_evidence",
        "canonicality": "derived",
    }


def _relations(
    graph: Mapping[str, Any],
    *,
    target_paths: set[str],
    max_items: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], set[str], bool]:
    nodes_by_id, id_by_path = _node_index(graph)
    target_ids = {id_by_path[path] for path in target_paths if path in id_by_path}
    records: list[dict[str, Any]] = []
    for raw in _items(graph.get("edges")):
        if not isinstance(raw, Mapping):
            continue
        src = raw.get("src")
        dst = raw.get("dst")
        if not isinstance(src, str) or not isinstance(dst, str):
            continue
        if src in target_ids and dst in nodes_by_id:
            records.append(
                _relation_record(
                    raw,
                    direction="outgoing",
                    target_node=nodes_by_id[src],
                    peer_node=nodes_by_id[dst],
                )
            )
        if dst in target_ids and src in nodes_by_id:
            records.append(
                _relation_record(
                    raw,
                    direction="incoming",
                    target_node=nodes_by_id[dst],
                    peer_node=nodes_by_id[src],
                )
            )
    records.sort(
        key=lambda item: (
            str(item.get("direction", "")),
            str(_mapping(item.get("peer")).get("path", "")),
            str(item.get("edge_type", "")),
            str(item.get("evidence_level", "")),
        )
    )
    peer_paths = {
        str(path)
        for item in records
        for path in [_mapping(item.get("peer")).get("path")]
        if isinstance(path, str)
    }
    return records[:max_items], records, peer_paths, len(records) > max_items


def _related_tests(
    *,
    target_paths: set[str],
    all_relations: list[dict[str, Any]],
    symbol_index: Mapping[str, Any],
    max_items: int,
) -> tuple[list[dict[str, Any]], bool]:
    candidates: list[dict[str, Any]] = []
    for relation in all_relations:
        peer = _mapping(relation.get("peer"))
        peer_path = peer.get("path")
        if peer.get("is_test") and isinstance(peer_path, str):
            candidates.append(
                {
                    "path": peer_path,
                    "evidence_type": "graph_edge",
                    "direction": relation.get("direction"),
                    "edge_type": relation.get("edge_type"),
                    "evidence_level": relation.get("evidence_level"),
                    "evidence": relation.get("evidence"),
                }
            )

    known_paths = {
        str(item.get("path"))
        for item in _items(symbol_index.get("symbols"))
        if isinstance(item, Mapping) and isinstance(item.get("path"), str)
    }
    for target_path in sorted(target_paths):
        path = PurePosixPath(target_path)
        if path.suffix != ".py" or _is_test_path(target_path):
            continue
        stem = path.stem
        guesses = {
            f"tests/test_{stem}.py",
            f"merger/lenskit/tests/test_{stem}.py",
            (path.parent / "tests" / f"test_{stem}.py").as_posix(),
        }
        for guess in sorted(guesses):
            if guess in known_paths:
                candidates.append(
                    {
                        "path": guess,
                        "evidence_type": "symbol_index_path_match",
                        "reason": "conventional_test_path_present_in_symbol_index",
                    }
                )
            else:
                candidates.append(
                    {
                        "path": guess,
                        "evidence_type": "heuristic",
                        "reason": "python_test_naming_convention",
                    }
                )

    rank = {"graph_edge": 0, "symbol_index_path_match": 1, "heuristic": 2}
    unique: dict[tuple[str, str], dict[str, Any]] = {}
    for item in candidates:
        path = item.get("path")
        evidence_type = item.get("evidence_type")
        if isinstance(path, str) and isinstance(evidence_type, str):
            unique.setdefault((path, evidence_type), item)
    ordered = sorted(
        unique.values(),
        key=lambda item: (
            rank.get(str(item.get("evidence_type")), 99),
            str(item.get("path", "")),
        ),
    )
    return ordered[:max_items], len(ordered) > max_items


def _query_items(query_context: Any) -> list[dict[str, Any]]:
    root = _mapping(query_context)
    query = _mapping(root.get("query"))
    projection = _mapping(query.get("source_citation_projection"))
    if not projection:
        projection = _mapping(root.get("source_citation_projection"))
    return [
        dict(item)
        for item in _items(projection.get("items"))
        if isinstance(item, Mapping)
    ]


def _supporting_context(
    *,
    all_relations: list[dict[str, Any]],
    query_context: Any,
    max_items: int,
) -> tuple[list[dict[str, Any]], bool]:
    candidates: list[dict[str, Any]] = []
    for relation in all_relations:
        peer = _mapping(relation.get("peer"))
        path = peer.get("path")
        if not isinstance(path, str):
            continue
        path_class = _path_class(path)
        if path_class not in {"documentation", "contract"}:
            continue
        candidates.append(
            {
                "path": path,
                "path_class": path_class,
                "evidence_type": "graph_edge",
                "direction": relation.get("direction"),
                "edge_type": relation.get("edge_type"),
                "evidence_level": relation.get("evidence_level"),
            }
        )
    for item in _query_items(query_context):
        path = item.get("path")
        if not isinstance(path, str):
            continue
        path_class = _path_class(path)
        if path_class not in {"documentation", "contract"}:
            continue
        candidates.append(
            {
                "path": path,
                "path_class": path_class,
                "evidence_type": "resolved_query",
                "citation_id": item.get("citation_id"),
                "source_range": item.get("source_range"),
                "range_status": item.get("range_status"),
            }
        )
    unique: dict[tuple[str, str], dict[str, Any]] = {}
    for item in candidates:
        unique.setdefault(
            (str(item.get("path")), str(item.get("evidence_type"))),
            item,
        )
    rank = {"graph_edge": 0, "resolved_query": 1}
    ordered = sorted(
        unique.values(),
        key=lambda item: (
            rank.get(str(item.get("evidence_type")), 99),
            str(item.get("path", "")),
        ),
    )
    return ordered[:max_items], len(ordered) > max_items


def _entrypoints(
    entrypoint_doc: Mapping[str, Any],
    *,
    relevant_paths: set[str],
    max_items: int,
) -> tuple[list[dict[str, Any]], bool]:
    candidates = [
        dict(item)
        for item in _items(entrypoint_doc.get("entrypoints"))
        if isinstance(item, Mapping)
        and isinstance(item.get("path"), str)
        and item.get("path") in relevant_paths
    ]
    candidates.sort(
        key=lambda item: (
            str(item.get("projection", "")),
            str(item.get("type", "")),
            str(item.get("path", "")),
            str(item.get("symbol", "")),
        )
    )
    return candidates[:max_items], len(candidates) > max_items


def _contains_path(value: Any, paths: set[str], *, depth: int = 0) -> bool:
    if depth > 8:
        return False
    if isinstance(value, str):
        return value in paths
    if isinstance(value, Mapping):
        return any(
            _contains_path(item, paths, depth=depth + 1)
            for item in value.values()
        )
    if isinstance(value, list):
        return any(
            _contains_path(item, paths, depth=depth + 1)
            for item in value
        )
    return False


def _relation_cards(
    cards: Iterable[Any],
    *,
    target_paths: set[str],
    max_items: int,
) -> tuple[list[dict[str, Any]], bool]:
    matches = [
        dict(card)
        for card in cards
        if isinstance(card, Mapping) and _contains_path(card, target_paths)
    ]
    matches.sort(
        key=lambda item: (
            str(item.get("card_type", "")),
            str(item.get("card_id", item.get("id", ""))),
        )
    )
    return matches[:max_items], len(matches) > max_items


def _first_reads(
    *,
    target_paths: set[str],
    target_symbols: list[dict[str, Any]],
    relations: list[dict[str, Any]],
    related_tests: list[dict[str, Any]],
    supporting: list[dict[str, Any]],
    max_items: int,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for symbol in target_symbols:
        candidates.append(
            {
                "path": symbol.get("path"),
                "range_ref": symbol.get("range_ref"),
                "qualified_name": symbol.get("qualified_name"),
                "reason": "target_symbol",
                "priority": 0,
            }
        )
    symbol_paths = {
        symbol.get("path")
        for symbol in target_symbols
        if isinstance(symbol.get("path"), str)
    }
    for path in sorted(target_paths - symbol_paths):
        candidates.append(
            {
                "path": path,
                "range_ref": None,
                "qualified_name": None,
                "reason": "target_path",
                "priority": 1,
            }
        )
    for relation in relations:
        peer = _mapping(relation.get("peer"))
        candidates.append(
            {
                "path": peer.get("path"),
                "range_ref": None,
                "qualified_name": None,
                "reason": f"{relation.get('direction')}_graph_relation",
                "priority": 2,
            }
        )
    for item in related_tests:
        candidates.append(
            {
                "path": item.get("path"),
                "range_ref": None,
                "qualified_name": None,
                "reason": f"related_test:{item.get('evidence_type')}",
                "priority": 3,
            }
        )
    for item in supporting:
        candidates.append(
            {
                "path": item.get("path"),
                "range_ref": None,
                "qualified_name": None,
                "reason": f"supporting_{item.get('path_class')}",
                "priority": 4,
            }
        )

    unique: dict[tuple[Any, Any], dict[str, Any]] = {}
    for item in candidates:
        if not isinstance(item.get("path"), str):
            continue
        key = (item.get("path"), item.get("range_ref"))
        unique.setdefault(key, item)
    ordered = sorted(
        unique.values(),
        key=lambda item: (
            int(item.get("priority", 99)),
            str(item.get("path", "")),
            str(item.get("range_ref", "")),
        ),
    )
    for item in ordered:
        item.pop("priority", None)
    return ordered[:max_items]


def _base_result(
    *,
    status: str,
    mode: Any,
    target_path: Any,
    target_symbol: Any,
) -> dict[str, Any]:
    return {
        "kind": KIND,
        "version": VERSION,
        "status": status,
        "mode": mode if isinstance(mode, str) else None,
        "target": {
            "path": target_path if isinstance(target_path, str) else None,
            "paths": [],
            "symbol": target_symbol if isinstance(target_symbol, str) else None,
        },
        "target_symbols": [],
        "relations": [],
        "related_tests": [],
        "supporting_context": [],
        "entrypoints": [],
        "relation_cards": [],
        "gaps": [],
        "truncation": {},
        "mutation_boundary": {
            **MUTATION_BOUNDARY,
            "does_not_mutate": list(MUTATION_BOUNDARY["does_not_mutate"]),
        },
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }


def build_agent_impact_context(
    *,
    target_path: Any = None,
    target_symbol: Any = None,
    changed_paths: Any = None,
    mode: Any = "impact",
    max_items: Any = 25,
    architecture_graph: Any = None,
    symbol_index: Any = None,
    entrypoints: Any = None,
    relation_cards: Any = None,
    query_context: Any = None,
    source_statuses: Any = None,
) -> dict[str, Any]:
    """Build a bounded impact/edit context from existing Lenskit artifacts."""

    try:
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES!r}")
        limit = _bounded_int(max_items, field="max_items", default=25)
        clean_symbol = _clean_text(target_symbol, field="target_symbol")
        paths: set[str] = set()
        if target_path is not None:
            paths.add(_repo_path(target_path, field="target_path"))
        if changed_paths is not None:
            if isinstance(changed_paths, (str, bytes, bytearray, Mapping)):
                raise TypeError(
                    "changed_paths must be an iterable of path strings"
                )
            for value in changed_paths:
                paths.add(_repo_path(value, field="changed_paths[]"))
        if not paths and not clean_symbol:
            raise ValueError(
                "at least one of target_path, target_symbol or changed_paths "
                "is required"
            )
    except (TypeError, ValueError) as exc:
        result = _base_result(
            status="invalid",
            mode=mode,
            target_path=target_path,
            target_symbol=target_symbol,
        )
        result.update(
            {
                "error": str(exc),
                "error_code": "agent_impact_request_invalid",
            }
        )
        return result

    graph = _mapping(architecture_graph)
    symbols = _mapping(symbol_index)
    entrypoint_doc = _mapping(entrypoints)
    cards = list(relation_cards) if isinstance(relation_cards, list) else []

    states = _merge_source_states(
        [
            _source_state("architecture_graph_json", graph),
            _source_state("python_symbol_index_json", symbols),
            _source_state("entrypoints_json", entrypoint_doc),
        ],
        source_statuses,
    )
    coherence, run_id, digest, gaps = _coherence(states)

    result = _base_result(
        status="blocked" if coherence == "blocked" else "available",
        mode=mode,
        target_path=None,
        target_symbol=clean_symbol,
    )
    result["source_statuses"] = states
    result["provenance"] = {
        "status": coherence,
        "run_id": run_id,
        "canonical_dump_index_sha256": digest,
    }
    if coherence == "blocked":
        result["gaps"] = gaps
        result["target"]["paths"] = sorted(paths)
        result["target"]["path"] = (
            sorted(paths)[0] if len(paths) == 1 else None
        )
        return result

    target_symbols, derived_paths, symbols_truncated = _matching_symbols(
        symbols,
        target_symbol=clean_symbol,
        target_paths=paths,
        max_items=limit,
    )
    paths.update(derived_paths)

    relations, all_relations, peer_paths, relations_truncated = _relations(
        graph,
        target_paths=paths,
        max_items=limit,
    )
    related_tests, tests_truncated = _related_tests(
        target_paths=paths,
        all_relations=all_relations,
        symbol_index=symbols,
        max_items=limit,
    )
    supporting, supporting_truncated = _supporting_context(
        all_relations=all_relations,
        query_context=query_context,
        max_items=limit,
    )
    entrypoint_hits, entrypoints_truncated = _entrypoints(
        entrypoint_doc,
        relevant_paths=paths | peer_paths,
        max_items=limit,
    )
    card_hits, cards_truncated = _relation_cards(
        cards,
        target_paths=paths,
        max_items=limit,
    )

    _nodes_by_id, id_by_path = _node_index(graph)
    missing_paths = sorted(path for path in paths if path not in id_by_path)
    if missing_paths:
        gaps.append(
            {
                "source": "architecture_graph_json",
                "status": "missing_target",
                "reason": "target_path_not_present_as_graph_node",
                "paths": missing_paths,
            }
        )
    if clean_symbol and not target_symbols:
        gaps.append(
            {
                "source": "python_symbol_index_json",
                "status": "missing_target",
                "reason": "target_symbol_not_found",
                "symbol": clean_symbol,
            }
        )

    resolved_target = bool(
        target_symbols or any(path in id_by_path for path in paths)
    )
    status = "available"
    if not resolved_target:
        status = "missing_target"
    elif gaps or coherence == "unknown":
        status = "partial"

    result.update(
        {
            "status": status,
            "target": {
                "path": sorted(paths)[0] if len(paths) == 1 else None,
                "paths": sorted(paths),
                "symbol": clean_symbol,
            },
            "target_symbols": target_symbols,
            "relations": relations,
            "related_tests": related_tests,
            "supporting_context": supporting,
            "entrypoints": entrypoint_hits,
            "relation_cards": card_hits,
            "gaps": gaps,
            "truncation": {
                "max_items_per_section": limit,
                "target_symbols": symbols_truncated,
                "relations": relations_truncated,
                "related_tests": tests_truncated,
                "supporting_context": supporting_truncated,
                "entrypoints": entrypoints_truncated,
                "relation_cards": cards_truncated,
            },
            "composition": {
                "delta_context_input": "changed_paths_only",
                "does_not_parse_or_apply_diff": True,
                "query_context_used": bool(_query_items(query_context)),
            },
        }
    )
    if mode == "edit":
        result["edit_context"] = {
            "recommended_first_reads": _first_reads(
                target_paths=paths,
                target_symbols=target_symbols,
                relations=relations,
                related_tests=related_tests,
                supporting=supporting,
                max_items=limit,
            ),
            "relation_count": len(relations),
            "related_test_count": len(related_tests),
            "supporting_context_count": len(supporting),
            "entrypoint_count": len(entrypoint_hits),
        }
    return result


__all__ = [
    "DOES_NOT_ESTABLISH",
    "KIND",
    "MUTATION_BOUNDARY",
    "VERSION",
    "build_agent_impact_context",
]
