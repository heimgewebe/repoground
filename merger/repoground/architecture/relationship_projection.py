"""Versioned, deterministic relation projection over the existing graph artifacts.

This module intentionally has no parser, persistence, graph store or publisher.
It joins the already-produced symbol, call and architecture import graph records
without promoting unresolved static evidence into a proven relationship.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import PurePosixPath
from typing import Any, Mapping

KIND = "lenskit.relationship_projection"
VERSION = "1.0"
MAX_EDGES = 250_000
SHA256 = re.compile(r"^[0-9a-f]{64}$")
NONCLAIMS = (
    "runtime_behavior",
    "complete_dependencies",
    "dynamic_call_resolution",
    "test_sufficiency",
    "merge_readiness",
)

def _require_document(label: str, value: Mapping[str, Any], kind: str) -> None:
    if not isinstance(value, Mapping) or value.get("kind") != kind or value.get("version") != "1.0":
        raise ValueError(f"{label}: incompatible producer kind or version")
    if not isinstance(value.get("run_id"), str) or not value["run_id"]:
        raise ValueError(f"{label}: missing run_id")
    sha = value.get("canonical_dump_index_sha256")
    if not isinstance(sha, str) or SHA256.fullmatch(sha) is None:
        raise ValueError(f"{label}: invalid canonical SHA-256")

def _safe_path(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ValueError("relation source path is not canonical")
    path = PurePosixPath(value)
    if path.is_absolute() or str(path) != value or any(part in (".", "..") for part in value.split("/")):
        raise ValueError("relation source path is not canonical")
    return value

def _source(path: object, start: object, end: object) -> dict[str, Any]:
    canonical = _safe_path(path)
    if (not isinstance(start, int) or isinstance(start, bool) or start < 1
            or not isinstance(end, int) or isinstance(end, bool) or end < start):
        raise ValueError("relation source range is invalid")
    return {
        "path": canonical,
        "start_line": start,
        "end_line": end,
        "range_ref": f"file:{canonical}#L{start}-L{end}",
    }

def _edge(kind: str, src: str, dst: str, evidence: dict[str, Any],
          status: str, level: str, origin: str, *,
          candidates: list[str] | None = None) -> dict[str, Any]:
    if status not in ("resolved", "ambiguous", "unresolved", "candidate"):
        raise ValueError("unsupported resolution status")
    if level not in ("S0", "S1") or (status != "resolved" and level != "S0"):
        raise ValueError("invalid evidence promotion")
    record: dict[str, Any] = {
        "relation": kind, "src": src, "dst": dst,
        "resolution_status": status, "evidence_level": level,
        "source": evidence, "origin_artifact": origin,
    }
    if candidates:
        record["candidate_target_ids"] = sorted(set(candidates))[:20]
    payload = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    record["id"] = "rel:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return record


def _definition_edges(
    symbols: list[dict[str, Any]], known_files: set[str], gaps: Counter[str]
) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    for symbol in symbols:
        src = "file:" + _safe_path(symbol["path"])
        if src not in known_files:
            gaps["symbol_file_not_in_import_graph"] += 1
            continue
        edges.append(_edge(
            "defines", src, symbol["id"],
            _source(symbol["path"], symbol["start_line"], symbol["end_line"]),
            "resolved", "S1", "python_symbol_index_json",
        ))
    return edges


def _import_edges(
    imports: list[dict[str, Any]], known_files: set[str], gaps: Counter[str]
) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    for entry in imports:
        if entry.get("edge_type") != "import":
            continue
        src, dst = entry["src"], entry["dst"]
        evidence = entry["evidence"]
        if not isinstance(src, str) or src not in known_files or not isinstance(dst, str):
            gaps["import_missing_source_or_target"] += 1
            continue
        status = "resolved" if dst.startswith("file:") and dst in known_files else "unresolved"
        if status == "unresolved":
            gaps["import_external_or_ambiguous"] += 1
        edges.append(_edge(
            "imports", src, dst,
            _source(evidence["source_path"], evidence["start_line"], evidence["end_line"]),
            status, "S1" if status == "resolved" else "S0", "architecture_graph_json",
        ))
    return edges


def _call_target(
    call: dict[str, Any], known_symbols: set[str], gaps: Counter[str]
) -> tuple[str, str, str]:
    status = call.get("resolution_status", "unresolved")
    resolved = call.get("resolved_target_ids", [])
    if (status == "resolved" and isinstance(resolved, list) and len(resolved) == 1
            and resolved[0] in known_symbols
            and call.get("evidence_level") == "S1"):
        return resolved[0], "resolved", "S1"
    if status == "resolved":
        gaps["call_target_not_in_symbol_index"] += 1
        status = "unresolved"
    else:
        gaps["call_" + str(status)] += 1
    site = f"{call['path']}:{call['start_line']}:{call.get('start_col', 0)}:{call['callee_expression']}"
    dst = "unresolved-call:" + hashlib.sha256(site.encode("utf-8")).hexdigest()
    return dst, status, "S0"


def _call_edges(
    calls: list[dict[str, Any]], known_files: set[str],
    known_symbols: set[str], gaps: Counter[str],
) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    for call in calls:
        path = _safe_path(call["path"])
        src = call.get("caller_symbol_id") or ("file:" + path)
        if src not in known_symbols and src not in known_files:
            gaps["call_caller_not_in_graph"] += 1
            continue
        source = _source(path, call["start_line"], call["end_line"])
        dst, status, level = _call_target(call, known_symbols, gaps)
        candidate = call.get("candidate_target_ids", [])
        edges.append(_edge(
            "calls", src, dst, source, status, level, "python_call_graph_json",
            candidates=candidate if level == "S0" and isinstance(candidate, list) else None,
        ))
        # A syntactic test call is not evidence of test coverage/sufficiency.
        if level == "S1" and (path.startswith("tests/") or path.rsplit("/", 1)[-1].startswith("test_")):
            edges.append(_edge("tests", "file:" + path, dst, source, status, level, "python_call_graph_json"))
    return edges


def project_relationships(
    *, symbol_index: Mapping[str, Any],
    call_graph: Mapping[str, Any],
    architecture_graph: Mapping[str, Any],
    max_edges: int = MAX_EDGES,
) -> dict[str, Any]:
    """Project S0/S1 directed relations from three co-revision producer artifacts.

    Caller must supply trusted/manifest-validated artifacts. The shared canonical
    hash proves metadata coherence, not that the worktree is clean or the source
    tree still matches the original files.
    """
    if isinstance(max_edges, bool) or not isinstance(max_edges, int) or not 1 <= max_edges <= MAX_EDGES:
        raise ValueError("max_edges outside bounded range")
    _require_document("symbols", symbol_index, "lenskit.python_symbol_index")
    _require_document("calls", call_graph, "lenskit.python_call_graph")
    _require_document("imports", architecture_graph, "lenskit.architecture.graph")
    identities = {
        (item["run_id"], item["canonical_dump_index_sha256"])
        for item in (symbol_index, call_graph, architecture_graph)
    }
    if len(identities) != 1:
        raise ValueError("graph producer provenance mismatch")

    symbols = symbol_index.get("symbols")
    calls = call_graph.get("calls")
    imports = architecture_graph.get("edges")
    nodes = architecture_graph.get("nodes")
    if not all(isinstance(rows, list) for rows in (symbols, calls, imports, nodes)):
        raise ValueError("source artifact records are missing")
    known_symbols = {item["id"] for item in symbols if isinstance(item, dict) and isinstance(item.get("id"), str)}
    known_files = {
        item["node_id"] for item in nodes
        if isinstance(item, dict) and item.get("kind") == "file" and isinstance(item.get("node_id"), str)
    }
    edges: list[dict[str, Any]] = []
    gaps: Counter[str] = Counter()

    edges.extend(_definition_edges(symbols, known_files, gaps))
    edges.extend(_import_edges(imports, known_files, gaps))
    edges.extend(_call_edges(calls, known_files, known_symbols, gaps))

    unique = {edge["id"]: edge for edge in edges}
    ordered = sorted(unique.values(), key=lambda item: (
        item["source"]["path"], item["source"]["start_line"],
        item["relation"], item["src"], item["dst"], item["id"],
    ))
    selected = ordered[:max_edges]
    counts = Counter(item["relation"] for item in selected)
    resolutions = Counter(item["resolution_status"] for item in selected)
    run_id, canonical_sha = next(iter(identities))
    return {
        "kind": KIND, "version": VERSION,
        "run_id": run_id, "canonical_dump_index_sha256": canonical_sha,
        "edges": selected,
        "coverage": {
            "relation_counts": {key: counts[key] for key in sorted(counts)},
            "resolution_counts": {key: resolutions[key] for key in sorted(resolutions)},
            "total_edges": len(ordered), "emitted_edges": len(selected),
            "truncated": len(ordered) > len(selected),
            "symbol_records_seen": len(symbols), "call_records_seen": len(calls),
            "import_records_seen": len(imports),
            "producer_skipped_python_symbol_files": symbol_index.get("skipped_files_count", 0),
            "producer_skipped_python_call_files": call_graph.get("skipped_files_count", 0),
            "producer_repository_truncated": architecture_graph.get("coverage", {}).get("repository_truncated", False),
            "gaps": {key: gaps[key] for key in sorted(gaps)},
        },
        "does_not_establish": list(NONCLAIMS),
    }

def generate_relationship_document(
    repo_root: "Path",
    run_id: str,
    canonical_sha256: str,
    *,
    max_edges: int = MAX_EDGES,
) -> dict[str, Any]:
    """Compose the existing producers, then project a coherent relation response.

    The caller provides the snapshot identity; production consumers must obtain
    it from a validated bundle manifest and must check source freshness.
    """
    from merger.repoground.architecture.call_graph import generate_call_graph_document
    from merger.repoground.architecture.import_graph import generate_import_graph_document
    from merger.repoground.architecture.symbol_index import generate_symbol_index_document

    return project_relationships(
        symbol_index=generate_symbol_index_document(repo_root, run_id, canonical_sha256),
        call_graph=generate_call_graph_document(repo_root, run_id, canonical_sha256),
        architecture_graph=generate_import_graph_document(repo_root, run_id, canonical_sha256),
        max_edges=max_edges,
    )