"""Read-only navigation over the Observed Call Overlay v1 (S2).

The overlay deliberately gets its own read surface instead of being folded into
:func:`merger.repoground.core.call_graph_navigation.get_callers`. A consumer
that wants observed evidence has to ask for it, and what it gets back is
labelled S2 throughout, so no result can be mistaken for a wider static claim.

When a static call graph is supplied the reader adds a
``static_correspondence`` per relation. That field compares the two artifacts;
it never rewrites either of them. ``matches_s0_candidate`` in particular does
*not* promote the static call site to S1 — the static graph still says
"candidate", and the overlay separately says "seen once, under this command".
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from merger.repoground.architecture.observed_call_overlay_contract import (
    ABSENCE_SEMANTICS,
    OBSERVED_EVIDENCE_LEVEL,
)
from merger.repoground.core.context_compiler import _read_only_mutation_boundary
from merger.repoground.core.observed_call_overlay_validation import (
    error as _overlay_error,
)
from merger.repoground.core.observed_call_overlay_validation import (
    validate_observed_call_overlay,
)

OBSERVED_CALLERS_KIND = "repobrief.observed_call_callers"
OBSERVED_CALLEES_KIND = "repobrief.observed_call_callees"
MAX_OBSERVED_SEARCH_K = 200

STATIC_CORRESPONDENCE_VALUES = (
    "matches_s1",
    "matches_s0_candidate",
    "absent_from_static_graph",
    "static_graph_not_supplied",
)

_DOES_NOT_ESTABLISH = (
    "complete_call_graph",
    "runtime_reachability",
    "dead_code",
    "unreachable_code",
    "static_resolution_upgrade",
    "dynamic_dispatch_resolution",
    "coverage_sufficiency",
    "test_sufficiency",
    "review_completeness",
    "merge_readiness",
)


def _read_json(path: Path) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, _overlay_error(
            "observed_call_overlay_unreadable",
            f"observed_call_overlay could not be read: {type(exc).__name__} - {exc}",
        )
    if not isinstance(payload, dict):
        return None, _overlay_error(
            "observed_call_overlay_invalid_kind",
            "observed_call_overlay must be a JSON object",
        )
    return payload, None


def _empty(kind: str) -> dict[str, Any]:
    if kind == OBSERVED_CALLERS_KIND:
        return {"target_symbol_ids": [], "observed_callers": []}
    return {"caller_symbol_ids": [], "observed_callees": []}


def _invalid(
    kind: str,
    overlay_path: Path,
    failure: Mapping[str, Any],
    *,
    name: Any,
    k: Any,
    path: Any,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "version": "v1",
        "status": failure.get("status", "invalid"),
        "error": failure.get("error"),
        "error_code": failure.get("error_code"),
        "overlay_path": str(overlay_path),
        "name": name,
        "k": k,
        "filters": {"path": path},
        "observation": None,
        "evidence_level": OBSERVED_EVIDENCE_LEVEL,
        "absence_semantics": ABSENCE_SEMANTICS,
        **_empty(kind),
        "mutation_boundary": _read_only_mutation_boundary(),
        "does_not_establish": list(_DOES_NOT_ESTABLISH),
    }


def _static_pairs(
    call_graph: Mapping[str, Any] | None,
) -> tuple[set[tuple[str | None, str]], set[tuple[str | None, str]]]:
    """Return the ``(caller_symbol_id, callee_symbol_id)`` pairs the static graph holds."""

    resolved: set[tuple[str | None, str]] = set()
    candidate: set[tuple[str | None, str]] = set()
    if call_graph is None:
        return resolved, candidate
    for row in call_graph.get("calls", []):
        if not isinstance(row, dict):
            continue
        caller = row.get("caller_symbol_id")
        caller_key = caller if isinstance(caller, str) else None
        for target in row.get("resolved_target_ids", []) or []:
            if isinstance(target, str):
                resolved.add((caller_key, target))
        for target in row.get("candidate_target_ids", []) or []:
            if isinstance(target, str):
                candidate.add((caller_key, target))
    return resolved, candidate


def _correspondence(
    relation: Mapping[str, Any],
    resolved: set[tuple[str | None, str]],
    candidate: set[tuple[str | None, str]],
    *,
    static_supplied: bool,
) -> str:
    if not static_supplied:
        return "static_graph_not_supplied"
    callee = relation.get("callee_symbol_id")
    if not isinstance(callee, str):
        return "absent_from_static_graph"
    caller = relation.get("caller_symbol_id")
    caller_key = caller if isinstance(caller, str) else None
    pair = (caller_key, callee)
    if pair in resolved:
        return "matches_s1"
    if pair in candidate:
        return "matches_s0_candidate"
    return "absent_from_static_graph"


def _matches_name(value: Any, query: str) -> bool:
    """Match a qualified name exactly, by simple name, or by dotted suffix.

    The suffix form lets ``targets.leaf`` select ``callobs.targets.leaf``
    without matching an unrelated ``other_targets.leaf``.
    """

    if not isinstance(value, str):
        return False
    folded = value.casefold()
    return (
        folded == query
        or folded.rsplit(".", 1)[-1] == query
        or folded.endswith(f".{query}")
    )


def _projected(
    relation: Mapping[str, Any],
    correspondence: str,
) -> dict[str, Any]:
    projection = dict(relation)
    projection["static_correspondence"] = correspondence
    return projection


def _validated_inputs(
    kind: str,
    overlay_path: Path,
    call_graph_path: Path | None,
    *,
    name: Any,
    k: Any,
    path: Any,
) -> tuple[dict[str, Any], dict[str, Any] | None] | dict[str, Any]:
    if not isinstance(name, str) or not name.strip():
        return _invalid(
            kind,
            overlay_path,
            _overlay_error("name_invalid", "name must be a non-empty string"),
            name=name,
            k=k,
            path=path,
        )
    if not isinstance(k, int) or isinstance(k, bool) or k < 1 or k > MAX_OBSERVED_SEARCH_K:
        return _invalid(
            kind,
            overlay_path,
            _overlay_error(
                "k_out_of_bounds",
                f"k must be an integer between 1 and {MAX_OBSERVED_SEARCH_K}",
            ),
            name=name,
            k=k,
            path=path,
        )
    overlay, failure = _read_json(overlay_path)
    if failure is not None:
        return _invalid(kind, overlay_path, failure, name=name, k=k, path=path)
    call_graph: dict[str, Any] | None = None
    if call_graph_path is not None:
        call_graph, failure = _read_json(call_graph_path)
        if failure is not None:
            return _invalid(kind, overlay_path, failure, name=name, k=k, path=path)
    failure = validate_observed_call_overlay(overlay, call_graph)
    if failure is not None:
        return _invalid(kind, overlay_path, failure, name=name, k=k, path=path)
    assert overlay is not None
    return overlay, call_graph


def _result(
    kind: str,
    overlay_path: Path,
    overlay: Mapping[str, Any],
    *,
    name: str,
    k: int,
    path: str | None,
    static_supplied: bool,
    selected_ids: Iterable[str],
    selected_key: str,
    relations_key: str,
    relations: list[dict[str, Any]],
    total: int,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "version": "v1",
        "status": "available",
        "overlay_path": str(overlay_path),
        "name": name,
        "k": k,
        "filters": {"path": path},
        "evidence_level": OBSERVED_EVIDENCE_LEVEL,
        "observation": dict(overlay["observation"]),
        "execution_outcome": dict(overlay["execution_outcome"]),
        "static_correspondence_supplied": static_supplied,
        selected_key: sorted(selected_ids),
        "total_relation_count": total,
        "hit_count": len(relations),
        "truncated": total > k,
        relations_key: relations,
        "absence_semantics": ABSENCE_SEMANTICS,
        "mutation_boundary": _read_only_mutation_boundary(),
        "does_not_establish": list(_DOES_NOT_ESTABLISH),
    }


def get_observed_callers(
    overlay: str | Path,
    name: str,
    path: str | None = None,
    k: int = 25,
    *,
    call_graph: str | Path | None = None,
) -> dict[str, Any]:
    """Return the observed callers of every symbol matching ``name``."""

    overlay_path = Path(overlay)
    call_graph_path = Path(call_graph) if call_graph is not None else None
    validated = _validated_inputs(
        OBSERVED_CALLERS_KIND,
        overlay_path,
        call_graph_path,
        name=name,
        k=k,
        path=path,
    )
    if isinstance(validated, dict):
        return validated
    document, static_graph = validated  # type: ignore[misc]
    query = name.strip().casefold()
    path_filter = path.strip().casefold() if isinstance(path, str) and path.strip() else None
    resolved, candidate = _static_pairs(static_graph)
    matched: list[dict[str, Any]] = []
    selected_ids: set[str] = set()
    for relation in document["relations"]:
        if not _matches_name(relation.get("callee_qualified_name"), query) and not (
            relation.get("callee_runtime_name", "").casefold() == query
        ):
            continue
        if path_filter and path_filter not in str(relation.get("callee_path", "")).casefold():
            continue
        callee_id = relation.get("callee_symbol_id")
        if isinstance(callee_id, str):
            selected_ids.add(callee_id)
        matched.append(
            _projected(
                relation,
                _correspondence(
                    relation, resolved, candidate, static_supplied=static_graph is not None
                ),
            )
        )
    return _result(
        OBSERVED_CALLERS_KIND,
        overlay_path,
        document,
        name=name,
        k=k,
        path=path,
        static_supplied=static_graph is not None,
        selected_ids=selected_ids,
        selected_key="target_symbol_ids",
        relations_key="observed_callers",
        relations=matched[:k],
        total=len(matched),
    )


def get_observed_callees(
    overlay: str | Path,
    name: str,
    path: str | None = None,
    k: int = 25,
    *,
    call_graph: str | Path | None = None,
) -> dict[str, Any]:
    """Return what every symbol matching ``name`` was observed to call."""

    overlay_path = Path(overlay)
    call_graph_path = Path(call_graph) if call_graph is not None else None
    validated = _validated_inputs(
        OBSERVED_CALLEES_KIND,
        overlay_path,
        call_graph_path,
        name=name,
        k=k,
        path=path,
    )
    if isinstance(validated, dict):
        return validated
    document, static_graph = validated  # type: ignore[misc]
    query = name.strip().casefold()
    path_filter = path.strip().casefold() if isinstance(path, str) and path.strip() else None
    resolved, candidate = _static_pairs(static_graph)
    matched: list[dict[str, Any]] = []
    selected_ids: set[str] = set()
    for relation in document["relations"]:
        if not _matches_name(relation.get("caller_qualified_name"), query) and not (
            relation.get("caller_runtime_name", "").casefold() == query
        ):
            continue
        if path_filter and path_filter not in str(relation.get("caller_path") or "").casefold():
            continue
        caller_id = relation.get("caller_symbol_id")
        if isinstance(caller_id, str):
            selected_ids.add(caller_id)
        matched.append(
            _projected(
                relation,
                _correspondence(
                    relation, resolved, candidate, static_supplied=static_graph is not None
                ),
            )
        )
    return _result(
        OBSERVED_CALLEES_KIND,
        overlay_path,
        document,
        name=name,
        k=k,
        path=path,
        static_supplied=static_graph is not None,
        selected_ids=selected_ids,
        selected_key="caller_symbol_ids",
        relations_key="observed_callees",
        relations=matched[:k],
        total=len(matched),
    )
