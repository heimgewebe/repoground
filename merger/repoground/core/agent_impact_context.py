"""Deterministic read-only impact and edit context for RepoGround bundles.

The producer composes already-emitted RepoGround artifacts. It does not scan a
repository, execute code, refresh snapshots, mutate Git, or issue review
verdicts. Every relation keeps its source direction and evidence level.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from merger.repoground.architecture.path_classification import is_test_path as _is_test_path

KIND = "repobrief.agent_impact_context"
VERSION = "1.0"
MODES = ("impact", "edit")
MAX_ITEMS_LIMIT = 200

_EDIT_CONTEXT_NONVERDICTS = (
    "complete_blast_radius",
    "runtime_breakage",
    "test_sufficiency",
    "merge_readiness",
)

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

_CORE_SOURCES = {
    "architecture_graph_json",
    "python_symbol_index_json",
    "entrypoints_json",
}
_CALL_GRAPH_RELATION_TYPES = frozenset({"calls", "constructs"})
_RISK_RELEVANCE_PRIORITY = {
    "target_caller_symbol_id": 0,
    "candidate_target_id": 1,
    "qualified_name": 2,
    "simple_name": 3,
}
_BLOCKING_SOURCE_STATUSES = {
    "blocked",
    "stale",
    "stale_or_mismatched",
    "invalid_json",
    "invalid_schema",
}


@dataclass(frozen=True)
class _Request:
    mode: str
    max_items: int
    target_symbol: str | None
    paths: frozenset[str]


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
    invalid_shape = (
        text.startswith("/")
        or "\\" in text
        or "//" in text
        or text.endswith("/")
    )
    path = PurePosixPath(text)
    invalid_segment = any(part in {"", ".", ".."} for part in path.parts)
    if invalid_shape or invalid_segment:
        raise ValueError(
            f"{field} must be a canonical repository-relative path"
        )
    return path.as_posix()


def _bounded_int(value: Any, *, field: str, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be an integer")
    if not 1 <= value <= MAX_ITEMS_LIMIT:
        raise ValueError(f"{field} must be between 1 and {MAX_ITEMS_LIMIT}")
    return value


def _changed_path_set(changed_paths: Any) -> set[str]:
    if changed_paths is None:
        return set()
    if isinstance(changed_paths, (str, bytes, bytearray, Mapping)):
        raise TypeError("changed_paths must be an iterable of path strings")
    return {
        _repo_path(value, field="changed_paths[]")
        for value in changed_paths
    }


def _request(
    *,
    target_path: Any,
    target_symbol: Any,
    changed_paths: Any,
    mode: Any,
    max_items: Any,
) -> _Request:
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES!r}")
    paths = _changed_path_set(changed_paths)
    if target_path is not None:
        paths.add(_repo_path(target_path, field="target_path"))
    symbol = _clean_text(target_symbol, field="target_symbol")
    if not paths and not symbol:
        raise ValueError(
            "at least one of target_path, target_symbol or changed_paths "
            "is required"
        )
    return _Request(
        mode=str(mode),
        max_items=_bounded_int(max_items, field="max_items", default=25),
        target_symbol=symbol,
        paths=frozenset(paths),
    )


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
        by_source.setdefault(source, {"source": source}).update(dict(raw))
    return [by_source[name] for name in sorted(by_source)]


def _unavailable_gaps(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "source": item.get("source"),
            "status": item.get("status"),
            "reason": "source_unavailable",
        }
        for item in sources
        if item.get("status") != "available"
    ]


def _identity_gaps(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "source": item.get("source"),
            "status": "identity_missing",
            "reason": "available_source_has_no_bundle_identity",
        }
        for item in sources
        if item.get("source") in _CORE_SOURCES
        and item.get("status") == "available"
        and not (
            item.get("run_id")
            and item.get("canonical_dump_index_sha256")
        )
    ]


def _blocking_sources(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "source": item.get("source"),
            "status": item.get("status"),
            "error_code": item.get("error_code"),
        }
        for item in sources
        if item.get("source") in _CORE_SOURCES
        and item.get("status") in _BLOCKING_SOURCE_STATUSES
    ]


def _identity_set(sources: list[dict[str, Any]]) -> set[tuple[str, str]]:
    return {
        (str(item["run_id"]), str(item["canonical_dump_index_sha256"]))
        for item in sources
        if item.get("source") in _CORE_SOURCES
        and item.get("status") == "available"
        and item.get("run_id")
        and item.get("canonical_dump_index_sha256")
    }


def _coherence(
    sources: list[dict[str, Any]],
) -> tuple[str, str | None, str | None, list[dict[str, Any]]]:
    gaps = _unavailable_gaps(sources) + _identity_gaps(sources)
    blocked = _blocking_sources(sources)
    identities = _identity_set(sources)
    if blocked:
        gaps.append(
            {
                "source": "artifact_coherence",
                "status": "blocked",
                "reason": "required_source_untrusted",
                "sources": blocked,
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
        return "coherent", run_id, digest, gaps
    gaps.append(
        {
            "source": "artifact_coherence",
            "status": "unknown",
            "reason": "no_shared_provenance_identity_available",
        }
    )
    return "unknown", None, None, gaps


def _path_class(path: str) -> str:
    if _is_test_path(path):
        return "test"
    if path.startswith("docs/") or "/docs/" in f"/{path}":
        return "documentation"
    is_contract = (
        "/contracts/" in f"/{path}"
        or path.startswith("contracts/")
        or path.endswith(".schema.json")
    )
    return "contract" if is_contract else "implementation"


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
        nodes_by_id[node_id] = dict(raw)
        if isinstance(path, str) and path:
            id_by_path.setdefault(path, node_id)
    return nodes_by_id, id_by_path


def _symbol_matches(
    symbol: Mapping[str, Any],
    *,
    folded_symbol: str | None,
    target_paths: set[str],
) -> tuple[bool, bool]:
    values = (
        symbol.get("id"),
        symbol.get("name"),
        symbol.get("qualified_name"),
    )
    exact = bool(
        folded_symbol
        and any(
            isinstance(value, str) and value.casefold() == folded_symbol
            for value in values
        )
    )
    path = symbol.get("path")
    return exact, isinstance(path, str) and path in target_paths


def _symbol_key(symbol: Mapping[str, Any]) -> str:
    return str(
        symbol.get("id")
        or (
            symbol.get("path"),
            symbol.get("qualified_name"),
            symbol.get("start_line"),
        )
    )


def _exact_symbol_preferences(
    ordered: list[dict[str, Any]],
    *,
    target_symbol: str | None,
    target_paths: set[str],
) -> tuple[dict[str, Any] | None, dict[str, dict[str, Any]]]:
    folded = target_symbol.casefold() if target_symbol else None
    if folded is None:
        return None, {}

    first_exact: dict[str, Any] | None = None
    exact_by_path: dict[str, dict[str, Any]] = {}
    for symbol in ordered:
        exact, _path_match = _symbol_matches(
            symbol,
            folded_symbol=folded,
            target_paths=target_paths,
        )
        if not exact:
            continue
        if first_exact is None:
            first_exact = symbol
        path = symbol.get("path")
        if isinstance(path, str) and path in target_paths:
            exact_by_path.setdefault(path, symbol)
    return first_exact, exact_by_path


def _select_symbols(
    ordered: list[dict[str, Any]],
    *,
    target_symbol: str | None,
    target_paths: set[str],
    max_items: int,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    selected_keys: set[str] = set()
    represented_paths: set[str] = set()

    def add(symbol: dict[str, Any]) -> None:
        key = _symbol_key(symbol)
        if key in selected_keys or len(selected) >= max_items:
            return
        selected.append(symbol)
        selected_keys.add(key)
        path = symbol.get("path")
        if isinstance(path, str) and path in target_paths:
            represented_paths.add(path)

    first_exact, exact_by_path = _exact_symbol_preferences(
        ordered,
        target_symbol=target_symbol,
        target_paths=target_paths,
    )
    if first_exact is not None:
        add(first_exact)

    for symbol in ordered:
        path = symbol.get("path")
        if (
            isinstance(path, str)
            and path in target_paths
            and path not in represented_paths
        ):
            add(exact_by_path.get(path, symbol))

    for symbol in ordered:
        add(symbol)

    return selected


def _matching_symbols(
    symbol_index: Mapping[str, Any],
    *,
    target_symbol: str | None,
    target_paths: set[str],
    max_items: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], set[str], bool]:
    matches: list[dict[str, Any]] = []
    derived_paths: set[str] = set()
    folded = target_symbol.casefold() if target_symbol else None
    for raw in _items(symbol_index.get("symbols")):
        if not isinstance(raw, Mapping):
            continue
        exact, path_match = _symbol_matches(
            raw,
            folded_symbol=folded,
            target_paths=target_paths,
        )
        if not (exact or path_match):
            continue
        symbol = dict(raw)
        matches.append(symbol)
        if exact and isinstance(symbol.get("path"), str):
            derived_paths.add(str(symbol["path"]))
    matches.sort(
        key=lambda item: (
            str(item.get("path", "")),
            int(item.get("start_line", 0) or 0),
            str(item.get("qualified_name", "")),
        )
    )
    unique: dict[str, dict[str, Any]] = {}
    for symbol in matches:
        unique.setdefault(_symbol_key(symbol), symbol)
    ordered = list(unique.values())
    selected = _select_symbols(
        ordered,
        target_symbol=target_symbol,
        target_paths=target_paths,
        max_items=max_items,
    )
    return selected, ordered, derived_paths, len(ordered) > max_items


def _symbols_by_id(symbol_index: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(raw["id"]): dict(raw)
        for raw in _items(symbol_index.get("symbols"))
        if isinstance(raw, Mapping) and isinstance(raw.get("id"), str) and raw.get("id")
    }


def _source_status(
    source_states: list[dict[str, Any]],
    source: str,
) -> Mapping[str, Any]:
    for item in source_states:
        if item.get("source") == source:
            return item
    return {"source": source, "status": "missing"}


def _artifact_freshness(
    document: Mapping[str, Any],
    *,
    source: str,
    source_states: list[dict[str, Any]],
    coherence: str,
    expected_run_id: str | None,
    expected_digest: str | None,
) -> dict[str, Any]:
    source_state = _source_status(source_states, source)
    source_status = str(source_state.get("status", "missing"))
    run_id, digest = _identity(document)
    if source_status != "available":
        freshness_status = source_status
    elif not document:
        freshness_status = "missing"
    elif not run_id or not digest:
        freshness_status = "identity_missing"
    elif coherence != "coherent" or expected_run_id is None or expected_digest is None:
        freshness_status = "coherence_unknown"
    elif (run_id, digest) != (expected_run_id, expected_digest):
        freshness_status = "stale_or_mismatched"
    else:
        freshness_status = "coherent"
    return {
        "source": source,
        "status": freshness_status,
        "run_id": run_id,
        "canonical_dump_index_sha256": digest,
        "artifact_sha256": source_state.get("sha256"),
    }


def _caller_definition_range(call: Mapping[str, Any]) -> str | None:
    path = call.get("path")
    start = call.get("caller_start_line")
    end = call.get("caller_end_line")
    if isinstance(path, str) and isinstance(start, int) and isinstance(end, int):
        return f"file:{path}#L{start}-L{end}"
    return None


def _call_relation_record(
    call: Mapping[str, Any],
    *,
    relation_kind: str,
    peer_symbol: Mapping[str, Any] | None,
    target_symbol_ids: set[str],
    relation_freshness: Mapping[str, Any],
    symbol_freshness: Mapping[str, Any],
) -> dict[str, Any]:
    if relation_kind == "direct_caller":
        path = call.get("path")
        symbol_id = call.get("caller_symbol_id")
        qualified_name = call.get("caller_qualified_name")
        peer_range = _caller_definition_range(call)
        direction = "incoming"
        peer_freshness = relation_freshness
    else:
        peer = peer_symbol or {}
        path = peer.get("path")
        symbol_id = peer.get("id")
        qualified_name = peer.get("qualified_name")
        peer_range = peer.get("range_ref")
        direction = "outgoing"
        peer_freshness = symbol_freshness
    call_site = call.get("range_ref")
    relation_type = call.get("relation_type")
    return {
        "relation_kind": relation_kind,
        "direction": direction,
        "path": path,
        "symbol_id": symbol_id,
        "qualified_name": qualified_name,
        "target_symbol_ids": sorted(target_symbol_ids),
        "relation_type": relation_type,
        "relation_types": ([relation_type] if isinstance(relation_type, str) else []),
        "evidence_level": call.get("evidence_level"),
        "resolution_status": call.get("resolution_status"),
        "resolution_reason": call.get("resolution_reason"),
        "source_ranges": {
            "call_site": call_site,
            "call_sites": [call_site] if isinstance(call_site, str) else [],
            "peer_definition": peer_range,
        },
        "freshness": dict(relation_freshness),
        "provenance": {
            "relation": dict(relation_freshness),
            "peer_definition": dict(peer_freshness),
        },
        "omission_reason": None,
    }


def _call_relation_identity(item: Mapping[str, Any]) -> tuple[Any, ...]:
    relation_kind = item.get("relation_kind")
    symbol_id = item.get("symbol_id")
    if isinstance(symbol_id, str) and symbol_id:
        return (relation_kind, "symbol", symbol_id)
    source_ranges = _mapping(item.get("source_ranges"))
    return (
        relation_kind,
        "scope",
        item.get("path"),
        item.get("qualified_name"),
        source_ranges.get("peer_definition"),
    )


def _aggregate_call_relations(
    relations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    grouped: dict[tuple[Any, ...], dict[str, Any]] = {}
    for relation in relations:
        key = _call_relation_identity(relation)
        if key not in grouped:
            value = dict(relation)
            value["source_ranges"] = dict(_mapping(relation.get("source_ranges")))
            value["target_symbol_ids"] = list(relation.get("target_symbol_ids") or [])
            value["relation_types"] = list(relation.get("relation_types") or [])
            grouped[key] = value
            continue
        current = grouped[key]
        current_ranges = dict(_mapping(current.get("source_ranges")))
        incoming_ranges = _mapping(relation.get("source_ranges"))
        call_sites = {
            str(value)
            for value in (
                list(current_ranges.get("call_sites") or [])
                + list(incoming_ranges.get("call_sites") or [])
            )
            if isinstance(value, str) and value
        }
        current_ranges["call_sites"] = sorted(call_sites)
        current_ranges["call_site"] = (
            current_ranges["call_sites"][0] if current_ranges["call_sites"] else None
        )
        current["source_ranges"] = current_ranges
        current["target_symbol_ids"] = sorted(
            {
                str(value)
                for value in (
                    list(current.get("target_symbol_ids") or [])
                    + list(relation.get("target_symbol_ids") or [])
                )
                if isinstance(value, str) and value
            }
        )
        relation_types = sorted(
            {
                str(value)
                for value in (
                    list(current.get("relation_types") or [])
                    + list(relation.get("relation_types") or [])
                )
                if isinstance(value, str) and value
            }
        )
        current["relation_types"] = relation_types
        current["relation_type"] = relation_types[0] if relation_types else None
    ordered = list(grouped.values())
    ordered.sort(
        key=lambda item: (
            str(item.get("path", "")),
            str(item.get("qualified_name", "")),
            str(item.get("symbol_id", "")),
        )
    )
    return ordered


def _call_risk_record(
    call: Mapping[str, Any],
    *,
    freshness: Mapping[str, Any],
    uncertainty_reason: str,
    relevance_basis: str,
) -> dict[str, Any]:
    return {
        "kind": "unresolved_call_relation",
        "path": call.get("path"),
        "caller_symbol_id": call.get("caller_symbol_id"),
        "caller_qualified_name": call.get("caller_qualified_name"),
        "callee_expression": call.get("callee_expression"),
        "simple_name": call.get("simple_name"),
        "candidate_target_ids": list(call.get("candidate_target_ids") or []),
        "evidence_level": call.get("evidence_level"),
        "resolution_status": call.get("resolution_status"),
        "resolution_reason": call.get("resolution_reason"),
        "relation_type": call.get("relation_type"),
        "relevance_basis": relevance_basis,
        "risk_priority": _RISK_RELEVANCE_PRIORITY[relevance_basis],
        "source_ranges": {
            "call_site": call.get("range_ref"),
            "caller_definition": _caller_definition_range(call),
        },
        "freshness": dict(freshness),
        "provenance": {"relation": dict(freshness)},
        "uncertainty_reason": uncertainty_reason,
        # Backward-compatible projection; budget omissions remain in the
        # section-level omission_reasons mapping.
        "omission_reason": uncertainty_reason,
    }


def _call_risk_relevance(
    call: Mapping[str, Any],
    *,
    target_ids: set[str],
    target_qualified_names: set[str],
    target_simple_names: set[str],
    candidate_ids: set[str],
) -> str | None:
    caller_id = call.get("caller_symbol_id")
    if isinstance(caller_id, str) and caller_id in target_ids:
        return "target_caller_symbol_id"
    if target_ids.intersection(candidate_ids):
        return "candidate_target_id"
    callee_expression = call.get("callee_expression")
    if (
        isinstance(callee_expression, str)
        and callee_expression.casefold() in target_qualified_names
    ):
        return "qualified_name"
    simple_name = call.get("simple_name")
    if isinstance(simple_name, str) and simple_name.casefold() in target_simple_names:
        return "simple_name"
    return None



def _call_graph_record_context(
    call: Mapping[str, Any],
    *,
    target_ids: set[str],
    target_qualified_names: set[str],
    target_simple_names: set[str],
    symbols_by_id: Mapping[str, Mapping[str, Any]],
    relation_freshness: Mapping[str, Any],
    symbol_freshness: Mapping[str, Any],
) -> tuple[
    dict[str, Any] | None,
    dict[str, Any] | None,
    dict[str, Any] | None,
]:
    resolved_ids = {
        str(value)
        for value in _items(call.get("resolved_target_ids"))
        if isinstance(value, str) and value
    }
    candidate_ids = {
        str(value)
        for value in _items(call.get("candidate_target_ids"))
        if isinstance(value, str) and value
    }
    caller_id = call.get("caller_symbol_id")
    relation_type_supported = call.get("relation_type") in _CALL_GRAPH_RELATION_TYPES
    s1_resolved = (
        relation_type_supported
        and call.get("evidence_level") == "S1"
        and call.get("resolution_status") == "resolved"
        and len(resolved_ids) == 1
    )
    caller_relation: dict[str, Any] | None = None
    callee_relation: dict[str, Any] | None = None
    risk: dict[str, Any] | None = None
    if s1_resolved:
        matched_target_ids = target_ids.intersection(resolved_ids)
        if matched_target_ids:
            caller_relation = _call_relation_record(
                call,
                relation_kind="direct_caller",
                peer_symbol=None,
                target_symbol_ids=matched_target_ids,
                relation_freshness=relation_freshness,
                symbol_freshness=symbol_freshness,
            )
        if isinstance(caller_id, str) and caller_id in target_ids:
            resolved_id = next(iter(resolved_ids))
            peer_symbol = symbols_by_id.get(resolved_id)
            if peer_symbol is not None:
                callee_relation = _call_relation_record(
                    call,
                    relation_kind="direct_callee",
                    peer_symbol=peer_symbol,
                    target_symbol_ids={caller_id},
                    relation_freshness=relation_freshness,
                    symbol_freshness=symbol_freshness,
                )
            else:
                risk = _call_risk_record(
                    call,
                    freshness=relation_freshness,
                    uncertainty_reason="resolved_target_missing_from_symbol_index",
                    relevance_basis="target_caller_symbol_id",
                )
        return caller_relation, callee_relation, risk

    relevance_basis = _call_risk_relevance(
        call,
        target_ids=target_ids,
        target_qualified_names=target_qualified_names,
        target_simple_names=target_simple_names,
        candidate_ids=candidate_ids,
    )
    if relevance_basis is None:
        return None, None, None
    uncertainty_reason = (
        "unsupported_relation_type"
        if not relation_type_supported
        else "not_s1_resolved_unique_relation"
    )
    risk = _call_risk_record(
        call,
        freshness=relation_freshness,
        uncertainty_reason=uncertainty_reason,
        relevance_basis=relevance_basis,
    )
    return None, None, risk

def _call_graph_context(
    call_graph: Mapping[str, Any],
    *,
    target_symbols: list[dict[str, Any]],
    symbol_index: Mapping[str, Any],
    source_states: list[dict[str, Any]],
    coherence: str,
    expected_run_id: str | None,
    expected_digest: str | None,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    relation_freshness = _artifact_freshness(
        call_graph,
        source="python_call_graph_json",
        source_states=source_states,
        coherence=coherence,
        expected_run_id=expected_run_id,
        expected_digest=expected_digest,
    )
    symbol_freshness = _artifact_freshness(
        symbol_index,
        source="python_symbol_index_json",
        source_states=source_states,
        coherence=coherence,
        expected_run_id=expected_run_id,
        expected_digest=expected_digest,
    )
    if relation_freshness.get("status") != "coherent":
        status = str(relation_freshness.get("status", "missing"))
        return (
            [],
            [],
            [],
            [
                {
                    "kind": (
                        "call_graph_source_unavailable"
                        if status == "missing"
                        else "call_graph_source_untrusted"
                    ),
                    "freshness": relation_freshness,
                    "coverage_reason": (
                        "python_call_graph_json_unavailable"
                        if status == "missing"
                        else "python_call_graph_json_not_coherent_with_core_sources"
                    ),
                }
            ],
        )

    target_ids = {
        str(item["id"])
        for item in target_symbols
        if isinstance(item.get("id"), str) and item.get("id")
    }
    target_qualified_names = {
        str(item["qualified_name"]).casefold()
        for item in target_symbols
        if isinstance(item.get("qualified_name"), str) and item.get("qualified_name")
    }
    target_simple_names = {
        str(item["name"]).casefold()
        for item in target_symbols
        if isinstance(item.get("name"), str) and item.get("name")
    }
    target_simple_names.update(
        name.rsplit(".", 1)[-1] for name in target_qualified_names
    )

    symbols_by_id = _symbols_by_id(symbol_index)
    callers: list[dict[str, Any]] = []
    callees: list[dict[str, Any]] = []
    risks: list[dict[str, Any]] = []
    coverage_gaps: list[dict[str, Any]] = []
    for raw in _items(call_graph.get("calls")):
        if not isinstance(raw, Mapping):
            continue
        caller_relation, callee_relation, risk = _call_graph_record_context(
            raw,
            target_ids=target_ids,
            target_qualified_names=target_qualified_names,
            target_simple_names=target_simple_names,
            symbols_by_id=symbols_by_id,
            relation_freshness=relation_freshness,
            symbol_freshness=symbol_freshness,
        )
        if caller_relation is not None:
            callers.append(caller_relation)
        if callee_relation is not None:
            callees.append(callee_relation)
        if risk is not None:
            risks.append(risk)

    skipped_files = call_graph.get("skipped_files_count")
    skipped_errors = call_graph.get("skipped_errors_total_count")
    if not isinstance(skipped_errors, int):
        skipped_errors = len(_items(call_graph.get("skipped_errors")))
    if isinstance(skipped_files, int) and (skipped_files > 0 or skipped_errors > 0):
        coverage_gaps.append(
            {
                "kind": "call_graph_parse_coverage_gap",
                "skipped_files_count": skipped_files,
                "skipped_errors_total_count": skipped_errors,
                "freshness": relation_freshness,
                "coverage_reason": "call_graph_parse_coverage_incomplete",
            }
        )

    risks.sort(
        key=lambda item: (
            int(item.get("risk_priority", 99)),
            str(item.get("path", "")),
            str(_mapping(item.get("source_ranges")).get("call_site", "")),
            str(item.get("uncertainty_reason", "")),
        )
    )
    return (
        _aggregate_call_relations(callers),
        _aggregate_call_relations(callees),
        risks,
        coverage_gaps,
    )


def _relation_record(
    edge: Mapping[str, Any],
    *,
    direction: str,
    target_node: Mapping[str, Any],
    peer_node: Mapping[str, Any],
) -> dict[str, Any]:
    target_path = target_node.get("path")
    peer_path = peer_node.get("path")
    evidence = edge.get("evidence")
    return {
        "direction": direction,
        "edge_type": edge.get("edge_type"),
        "evidence_level": edge.get("evidence_level"),
        "evidence": dict(evidence) if isinstance(evidence, Mapping) else None,
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


def _edge_records(
    edge: Mapping[str, Any],
    *,
    target_ids: set[str],
    nodes_by_id: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    src = edge.get("src")
    dst = edge.get("dst")
    if not isinstance(src, str) or not isinstance(dst, str):
        return []
    records: list[dict[str, Any]] = []
    if src in target_ids and dst in nodes_by_id:
        records.append(
            _relation_record(
                edge,
                direction="outgoing",
                target_node=nodes_by_id[src],
                peer_node=nodes_by_id[dst],
            )
        )
    if dst in target_ids and src in nodes_by_id:
        records.append(
            _relation_record(
                edge,
                direction="incoming",
                target_node=nodes_by_id[dst],
                peer_node=nodes_by_id[src],
            )
        )
    return records


def _relations(
    graph: Mapping[str, Any],
    *,
    target_paths: set[str],
    max_items: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], set[str], bool]:
    nodes_by_id, id_by_path = _node_index(graph)
    target_ids = {id_by_path[path] for path in target_paths if path in id_by_path}
    records = [
        record
        for raw in _items(graph.get("edges"))
        if isinstance(raw, Mapping)
        for record in _edge_records(
            raw,
            target_ids=target_ids,
            nodes_by_id=nodes_by_id,
        )
    ]
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


def _graph_test_candidates(
    relations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            "path": str(peer["path"]),
            "evidence_type": "graph_edge",
            "direction": relation.get("direction"),
            "edge_type": relation.get("edge_type"),
            "evidence_level": relation.get("evidence_level"),
            "evidence": relation.get("evidence"),
        }
        for relation in relations
        for peer in [_mapping(relation.get("peer"))]
        if peer.get("is_test") and isinstance(peer.get("path"), str)
    ]


def _test_path_guesses(target_path: str) -> set[str]:
    path = PurePosixPath(target_path)
    stem = path.stem
    return {
        f"tests/test_{stem}.py",
        f"merger/repoground/tests/test_{stem}.py",
        (path.parent / "tests" / f"test_{stem}.py").as_posix(),
    }


def _conventional_test_candidates(
    target_paths: set[str],
    known_paths: set[str],
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    python_targets = [
        path
        for path in sorted(target_paths)
        if PurePosixPath(path).suffix == ".py" and not _is_test_path(path)
    ]
    for target_path in python_targets:
        for guess in sorted(_test_path_guesses(target_path)):
            if guess not in known_paths:
                continue
            candidates.append(
                {
                    "path": guess,
                    "evidence_type": "symbol_index_path_match",
                    "reason": "conventional_test_path_present_in_symbol_index",
                }
            )
    return candidates


def _unique_ranked(
    candidates: list[dict[str, Any]],
    *,
    rank: Mapping[str, int],
    max_items: int,
) -> tuple[list[dict[str, Any]], bool]:
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


def _changed_test_candidates(
    target_paths: set[str],
) -> list[dict[str, Any]]:
    return [
        {
            "path": path,
            "evidence_type": "changed_test_path",
            "reason": "changed_path_is_test",
        }
        for path in sorted(target_paths)
        if _is_test_path(path)
    ]


def _related_tests(
    *,
    target_paths: set[str],
    all_relations: list[dict[str, Any]],
    symbol_index: Mapping[str, Any],
    max_items: int,
) -> tuple[list[dict[str, Any]], bool]:
    known_paths = {
        str(item["path"])
        for item in _items(symbol_index.get("symbols"))
        if isinstance(item, Mapping) and isinstance(item.get("path"), str)
    }
    candidates = _changed_test_candidates(target_paths)
    candidates.extend(_graph_test_candidates(all_relations))
    candidates.extend(_conventional_test_candidates(target_paths, known_paths))
    return _unique_ranked(
        candidates,
        rank={
            "changed_test_path": 0,
            "graph_edge": 1,
            "symbol_index_path_match": 2,
        },
        max_items=max_items,
    )


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


def _graph_support(relations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for relation in relations:
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
    return candidates


def _query_support(query_context: Any) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
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
    return candidates


def _supporting_context(
    *,
    all_relations: list[dict[str, Any]],
    query_context: Any,
    max_items: int,
) -> tuple[list[dict[str, Any]], bool]:
    candidates = _graph_support(all_relations) + _query_support(query_context)
    return _unique_ranked(
        candidates,
        rank={"graph_edge": 0, "resolved_query": 1},
        max_items=max_items,
    )


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


def _symbol_reads(symbols: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "path": symbol.get("path"),
            "range_ref": symbol.get("range_ref"),
            "qualified_name": symbol.get("qualified_name"),
            "reason": "target_symbol",
            "priority": 0,
        }
        for symbol in symbols
    ]


def _path_reads(
    target_paths: set[str],
    symbols: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    symbol_paths = {
        str(symbol["path"])
        for symbol in symbols
        if isinstance(symbol.get("path"), str)
    }
    return [
        {
            "path": path,
            "range_ref": None,
            "qualified_name": None,
            "reason": "target_path",
            "priority": 1,
        }
        for path in sorted(target_paths - symbol_paths)
    ]


def _relation_reads(relations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "path": _mapping(relation.get("peer")).get("path"),
            "range_ref": None,
            "qualified_name": None,
            "reason": f"{relation.get('direction')}_graph_relation",
            "priority": 2,
        }
        for relation in relations
    ]


def _section_reads(
    items: list[dict[str, Any]],
    *,
    reason_prefix: str,
    reason_field: str,
    priority: int,
) -> list[dict[str, Any]]:
    return [
        {
            "path": item.get("path"),
            "range_ref": None,
            "qualified_name": None,
            "reason": f"{reason_prefix}{item.get(reason_field)}",
            "priority": priority,
        }
        for item in items
    ]



def _call_relation_reads(relations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "path": item.get("path"),
            "range_ref": (
                _mapping(item.get("source_ranges")).get("peer_definition")
                or _mapping(item.get("source_ranges")).get("call_site")
            ),
            "qualified_name": item.get("qualified_name"),
            "reason": item.get("relation_kind"),
            "priority": 2,
        }
        for item in relations
        if isinstance(item.get("path"), str)
    ]


def _budgeted_section(
    items: list[dict[str, Any]],
    *,
    max_items: int,
) -> dict[str, Any]:
    selected: list[dict[str, Any]] = []
    for item in items[:max_items]:
        value = dict(item)
        value.setdefault("omission_reason", None)
        selected.append(value)
    omitted_count = max(0, len(items) - max_items)
    return {
        "budget": max_items,
        "selected": selected,
        "omitted_count": omitted_count,
        "omission_reasons": (
            {"section_budget_exceeded": omitted_count}
            if omitted_count
            else {}
        ),
    }


def _edit_selection(
    *,
    target_symbols: list[dict[str, Any]],
    direct_callers: list[dict[str, Any]],
    direct_callees: list[dict[str, Any]],
    entrypoints: list[dict[str, Any]],
    related_tests: list[dict[str, Any]],
    supporting: list[dict[str, Any]],
    unresolved_risks: list[dict[str, Any]],
    max_items: int,
) -> dict[str, Any]:
    target_definitions = [
        {
            "path": item.get("path"),
            "range_ref": item.get("range_ref"),
            "symbol_id": item.get("id"),
            "qualified_name": item.get("qualified_name"),
            "kind": item.get("kind"),
        }
        for item in target_symbols
    ]
    contract_items = [
        dict(item)
        for item in supporting
        if item.get("path_class") == "contract"
    ]
    return {
        "target_definitions": _budgeted_section(
            target_definitions,
            max_items=max_items,
        ),
        "direct_callers": _budgeted_section(direct_callers, max_items=max_items),
        "direct_callees": _budgeted_section(direct_callees, max_items=max_items),
        "entrypoints": _budgeted_section(entrypoints, max_items=max_items),
        "tests": _budgeted_section(related_tests, max_items=max_items),
        "contracts": _budgeted_section(contract_items, max_items=max_items),
        "unresolved_risk_boundaries": _budgeted_section(
            unresolved_risks,
            max_items=max_items,
        ),
    }


def _first_reads(
    *,
    target_paths: set[str],
    target_symbols: list[dict[str, Any]],
    call_relations: list[dict[str, Any]],
    relations: list[dict[str, Any]],
    related_tests: list[dict[str, Any]],
    supporting: list[dict[str, Any]],
    max_items: int,
) -> list[dict[str, Any]]:
    candidates = _symbol_reads(target_symbols)
    candidates.extend(_path_reads(target_paths, target_symbols))
    candidates.extend(_call_relation_reads(call_relations))
    candidates.extend(_relation_reads(relations))
    candidates.extend(
        _section_reads(
            related_tests,
            reason_prefix="related_test:",
            reason_field="evidence_type",
            priority=3,
        )
    )
    candidates.extend(
        _section_reads(
            supporting,
            reason_prefix="supporting_",
            reason_field="path_class",
            priority=4,
        )
    )
    unique: dict[tuple[str, Any], dict[str, Any]] = {}
    for item in candidates:
        path = item.get("path")
        if isinstance(path, str):
            unique.setdefault((path, item.get("range_ref")), item)
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


def _invalid_result(
    exc: Exception,
    *,
    mode: Any,
    target_path: Any,
    target_symbol: Any,
) -> dict[str, Any]:
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


def _blocked_result(
    request: _Request,
    *,
    source_states: list[dict[str, Any]],
    coherence: str,
    gaps: list[dict[str, Any]],
) -> dict[str, Any]:
    paths = sorted(request.paths)
    result = _base_result(
        status="blocked",
        mode=request.mode,
        target_path=paths[0] if len(paths) == 1 else None,
        target_symbol=request.target_symbol,
    )
    result["target"]["paths"] = paths
    result["source_statuses"] = source_states
    result["provenance"] = {
        "status": coherence,
        "run_id": None,
        "canonical_dump_index_sha256": None,
    }
    result["gaps"] = gaps
    return result


def _target_gaps(
    *,
    paths: set[str],
    id_by_path: Mapping[str, str],
    target_symbol: str | None,
    target_symbols: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    gaps: list[dict[str, Any]] = []
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
    if target_symbol and not target_symbols:
        gaps.append(
            {
                "source": "python_symbol_index_json",
                "status": "missing_target",
                "reason": "target_symbol_not_found",
                "symbol": target_symbol,
            }
        )
    return gaps


def _result_status(
    *,
    resolved_target: bool,
    gaps: list[dict[str, Any]],
    coherence: str,
) -> str:
    if not resolved_target:
        return "missing_target"
    if gaps or coherence == "unknown":
        return "partial"
    return "available"


def _select_impact_relations(
    architecture_relations: list[dict[str, Any]],
    call_relations: list[dict[str, Any]],
    *,
    max_items: int,
) -> tuple[list[dict[str, Any]], bool]:
    combined = architecture_relations + call_relations
    if max_items <= 0:
        return [], bool(combined)
    if not architecture_relations or not call_relations or max_items == 1:
        selected = combined[:max_items]
        return selected, len(combined) > len(selected)

    # Put coherent call evidence first so downstream byte-bounded consumers
    # retain the more specific causal relation when only one relation fits.
    # The max_items == 1 branch above intentionally preserves legacy behavior.
    selected = [call_relations[0], architecture_relations[0]]
    remaining = max_items - len(selected)
    if remaining > 0:
        selected.extend(architecture_relations[1 : 1 + remaining])
        remaining = max_items - len(selected)
    if remaining > 0:
        selected.extend(call_relations[1 : 1 + remaining])
    return selected, len(combined) > len(selected)



def build_agent_impact_context(
    *,
    target_path: Any = None,
    target_symbol: Any = None,
    changed_paths: Any = None,
    mode: Any = "impact",
    max_items: Any = 25,
    architecture_graph: Any = None,
    symbol_index: Any = None,
    python_call_graph: Any = None,
    entrypoints: Any = None,
    relation_cards: Any = None,
    query_context: Any = None,
    source_statuses: Any = None,
) -> dict[str, Any]:
    """Build a bounded impact/edit context from existing RepoGround artifacts."""

    try:
        request = _request(
            target_path=target_path,
            target_symbol=target_symbol,
            changed_paths=changed_paths,
            mode=mode,
            max_items=max_items,
        )
    except (TypeError, ValueError) as exc:
        return _invalid_result(
            exc,
            mode=mode,
            target_path=target_path,
            target_symbol=target_symbol,
        )

    graph = _mapping(architecture_graph)
    symbols = _mapping(symbol_index)
    call_graph = _mapping(python_call_graph)
    entrypoint_doc = _mapping(entrypoints)
    cards = list(relation_cards) if isinstance(relation_cards, list) else []
    calculated_states = [
        _source_state("architecture_graph_json", graph),
        _source_state("python_symbol_index_json", symbols),
        _source_state("entrypoints_json", entrypoint_doc),
    ]
    if call_graph:
        calculated_states.append(
            _source_state("python_call_graph_json", call_graph)
        )
    states = _merge_source_states(calculated_states, source_statuses)
    coherence, run_id, digest, gaps = _coherence(states)
    if coherence == "blocked":
        return _blocked_result(
            request,
            source_states=states,
            coherence=coherence,
            gaps=gaps,
        )

    paths = set(request.paths)
    (
        target_symbols,
        all_target_symbols,
        derived_paths,
        symbols_truncated,
    ) = _matching_symbols(
        symbols,
        target_symbol=request.target_symbol,
        target_paths=paths,
        max_items=request.max_items,
    )
    paths.update(derived_paths)
    relations, all_relations, peers, relations_truncated = _relations(
        graph,
        target_paths=paths,
        max_items=request.max_items,
    )
    related_tests, tests_truncated = _related_tests(
        target_paths=paths,
        all_relations=all_relations,
        symbol_index=symbols,
        max_items=request.max_items,
    )
    supporting, supporting_truncated = _supporting_context(
        all_relations=all_relations,
        query_context=query_context,
        max_items=request.max_items,
    )
    entrypoint_hits, entrypoints_truncated = _entrypoints(
        entrypoint_doc,
        relevant_paths=paths | peers,
        max_items=request.max_items,
    )
    card_hits, cards_truncated = _relation_cards(
        cards,
        target_paths=paths,
        max_items=request.max_items,
    )
    direct_callers: list[dict[str, Any]] = []
    direct_callees: list[dict[str, Any]] = []
    unresolved_risks: list[dict[str, Any]] = []
    call_graph_coverage_gaps: list[dict[str, Any]] = []
    edit_selection: dict[str, Any] = {}
    # Impact consumers need trusted call relations as evidence, but edit-only
    # selection, unresolved-risk projection and coverage-gap semantics stay
    # confined to edit mode. Missing optional call graphs therefore do not
    # degrade ordinary impact requests.
    if request.mode == "edit" or bool(call_graph):
        (
            direct_callers,
            direct_callees,
            unresolved_risks,
            call_graph_coverage_gaps,
        ) = _call_graph_context(
            call_graph,
            target_symbols=all_target_symbols,
            symbol_index=symbols,
            source_states=states,
            coherence=coherence,
            expected_run_id=run_id,
            expected_digest=digest,
        )

    if request.mode == "impact":
        impact_call_relations = direct_callers + direct_callees
        relations, relations_truncated = _select_impact_relations(
            all_relations,
            impact_call_relations,
            max_items=request.max_items,
        )

    if request.mode == "edit":
        gaps.extend(call_graph_coverage_gaps)
        edit_selection = _edit_selection(
            target_symbols=all_target_symbols,
            direct_callers=direct_callers,
            direct_callees=direct_callees,
            entrypoints=entrypoint_hits,
            related_tests=related_tests,
            supporting=supporting,
            unresolved_risks=unresolved_risks,
            max_items=request.max_items,
        )

    _nodes_by_id, id_by_path = _node_index(graph)
    gaps.extend(
        _target_gaps(
            paths=paths,
            id_by_path=id_by_path,
            target_symbol=request.target_symbol,
            target_symbols=target_symbols,
        )
    )
    resolved_target = bool(
        target_symbols or any(path in id_by_path for path in paths)
    )
    result = _base_result(
        status=_result_status(
            resolved_target=resolved_target,
            gaps=gaps,
            coherence=coherence,
        ),
        mode=request.mode,
        target_path=sorted(paths)[0] if len(paths) == 1 else None,
        target_symbol=request.target_symbol,
    )
    result.update(
        {
            "target": {
                "path": sorted(paths)[0] if len(paths) == 1 else None,
                "paths": sorted(paths),
                "symbol": request.target_symbol,
            },
            "provenance": {
                "status": coherence,
                "run_id": run_id,
                "canonical_dump_index_sha256": digest,
            },
            "source_statuses": states,
            "target_symbols": target_symbols,
            "relations": relations,
            "related_tests": related_tests,
            "supporting_context": supporting,
            "entrypoints": entrypoint_hits,
            "relation_cards": card_hits,
            "gaps": gaps,
            "truncation": {
                "max_items_per_section": request.max_items,
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
    if request.mode == "edit":
        selected_call_relations = (
            edit_selection["direct_callers"]["selected"]
            + edit_selection["direct_callees"]["selected"]
        )
        result["edit_context"] = {
            "recommended_first_reads": _first_reads(
                target_paths=paths,
                target_symbols=target_symbols,
                call_relations=selected_call_relations,
                relations=relations,
                related_tests=related_tests,
                supporting=supporting,
                max_items=request.max_items,
            ),
            "selection": edit_selection,
            "nonverdicts": list(_EDIT_CONTEXT_NONVERDICTS),
            "call_graph_coverage_gaps": call_graph_coverage_gaps,
            "relation_count": len(relations),
            "direct_caller_count": len(direct_callers),
            "direct_callee_count": len(direct_callees),
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
