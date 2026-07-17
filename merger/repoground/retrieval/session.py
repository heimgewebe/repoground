"""
Agent query session builder.

Builds a structured session object from a query result, combining information
from a projected context_bundle and/or a federation_trace.

Design notes:
- resolved_bundles is extracted from context_bundle.hits[*].epistemics.bundle_origin
  (a string, never an object — confirmed by query-context-bundle.v1.schema.json and
  query_core.py:build_context_bundle()).
- federation_trace.bundle_status is a dict {repo_id: status_str}; there is no
  queried_bundles list. Successfully queried bundles have status "ok" or "stale"
  (stale bundles still ran the query against their potentially outdated index).
"""
from pathlib import Path

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Bundle status values that mean the query actually executed against that bundle.
_SUCCESSFUL_BUNDLE_STATUSES = frozenset({"ok", "stale"})


def build_agent_query_session_v2(
    query: str,
    context_bundle: Optional[Dict[str, Any]] = None,
    federation_trace: Optional[Dict[str, Any]] = None,
    query_trace_id: Optional[str] = None,
    context_bundle_id: Optional[str] = None,
    agent_query_session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Builds a minimal agent query session from a query result.

    Extracts resolved_bundles — the unique set of bundle/repo identifiers that
    contributed hits or were successfully queried — from the two canonical sources:

    1. context_bundle.hits[*].epistemics.bundle_origin (string) for projected results.
    2. federation_trace.bundle_status keys where status is "ok" or "stale".

    Provenance fields are always emitted:
    - session_authority is always "agent_context_projection".
    - context_source (top-level) maps the internal session_meta value to the
      canonical provenance enum: "both" → "mixed", "none" → "unknown".
    - artifact_refs carries runtime artifact store IDs; null when unavailable.
    - claim_boundaries explicitly states what this session proves and does not prove.

    Args:
        query: The original query text.
        context_bundle: Optional projected context bundle (from execute_query /
            execute_federated_query with build_context=True).
        federation_trace: Optional federation execution trace (from
            execute_federated_query with trace=True).
        query_trace_id: Optional stable artifact store ID of the query_trace artifact.
        context_bundle_id: Optional stable artifact store ID of the context_bundle artifact.
        agent_query_session_id: Optional stable artifact store ID of this session artifact.
            Service responses normally keep this null because the assigned self-ID is exposed
            via artifact_ids.agent_query_session in the API response.

    Returns:
        A dict conforming to agent-query-session.v2.schema.json.
    """
    resolved: List[str] = []

    # Source 1: bundle origins from context bundle hits.
    # epistemics.bundle_origin is a string set by build_context_bundle():
    #   "bundle_origin": hit.get("repo_id", "local")
    if context_bundle is not None:
        for hit in context_bundle.get("hits", []):
            origin = hit.get("epistemics", {}).get("bundle_origin")
            if origin and isinstance(origin, str):
                resolved.append(origin)

    # Source 2: successfully queried bundles from the federation trace.
    # federation_trace.bundle_status is a dict {repo_id: status_str}.
    # "ok" = query ran and returned results (possibly empty).
    # "stale" = query ran against an outdated index — still counts as resolved.
    if federation_trace is not None:
        bundle_status = federation_trace.get("bundle_status", {})
        if not isinstance(bundle_status, dict):
            logger.warning(
                "federation_trace.bundle_status is not a dict (got %s); skipping",
                type(bundle_status).__name__,
            )
        else:
            for repo_id, status in bundle_status.items():
                if status in _SUCCESSFUL_BUNDLE_STATUSES and isinstance(repo_id, str) and repo_id:
                    resolved.append(repo_id)

    # Deduplicate and sort for determinism.
    resolved_bundles = sorted(set(resolved))

    # Determine context source for observability.
    has_projected = context_bundle is not None
    has_federated = federation_trace is not None
    if has_projected and has_federated:
        context_source = "both"
    elif has_projected:
        context_source = "projected"
    elif has_federated:
        context_source = "federated"
    else:
        context_source = "none"

    hits_count = len(context_bundle.get("hits", [])) if context_bundle is not None else 0

    session_meta: Dict[str, Any] = {"context_source": context_source}
    if federation_trace is not None:
        session_meta["federation_bundle_count"] = federation_trace.get("queried_bundles_total")
        session_meta["federation_effective_count"] = federation_trace.get("queried_bundles_effective")
    else:
        session_meta["federation_bundle_count"] = None
        session_meta["federation_effective_count"] = None

    # Top-level context_source uses the canonical provenance enum for v2 consumers.
    # Mapping: "both" → "mixed" (projected + federated), "none" → "unknown".
    _context_source_map = {
        "projected": "projected",
        "federated": "federated",
        "both": "mixed",
        "none": "unknown",
    }
    top_level_context_source = _context_source_map.get(context_source, "unknown")

    return {
        "query": query,
        "resolved_bundles": resolved_bundles,
        "hits_count": hits_count,
        "session_meta": session_meta,
        "session_authority": "agent_context_projection",
        "context_source": top_level_context_source,
        "artifact_refs": {
            "query_trace_id": query_trace_id,
            "context_bundle_id": context_bundle_id,
            "agent_query_session_id": agent_query_session_id,
        },
        "claim_boundaries": {
            "proves": [
                "This session was built from these query results and bundle/context references."
            ],
            "does_not_prove": [
                "This session does not prove live repository state.",
                "This session does not prove semantic completeness.",
                "This session is an agent context projection, not canonical repository content.",
            ],
        },
    }


def build_agent_query_session(
    request_contract: Dict[str, Any],
    result: Dict[str, Any],
    query_trace_ref: Optional[str] = None,
    context_bundle_ref: Optional[str] = None,
    diagnostics_ref: Optional[str] = None,
    out_dir: Optional[Path] = None,
    index_path: Optional[str] = None
) -> Dict[str, Any]:
    """
    Builds the formal agent_query_session.json artifact from query execution results.

    This function adheres to the agent_query_session.v1 contract and strictly extracts
    resolved bundles and warnings from the provided result without inventing references.

    Note on v1 vs v2 (do not naively migrate): this v1 builder is the on-disk
    *file-artifact* shape used by the `lenskit query --trace` flow. It computes
    integrity SHA256s (refs.integrity) and an environment block, and its output is
    validated against agent-query-session.v1.schema.json (see test_cli_agent_session.py).
    `build_agent_query_session_v2` is the *runtime-inline* shape used by the service
    (claim_boundaries, artifact_refs store IDs) validated against the v2 schema; it does
    NOT compute integrity/environment and takes different inputs (context_bundle /
    federation_trace instead of the raw result). The two are parallel delivery shapes,
    not predecessor/successor — swapping this caller to v2 would drop the integrity and
    environment data and change the emitted schema. Consolidating to a single session
    schema is tracked in docs/architecture/inconsistencies.md (§7).
    """
    import importlib.metadata
    from datetime import datetime, timezone
    import hashlib

    resolved_bundles = set()

    # Depending on whether we're dealing with a raw result or a projected context_bundle
    hits = []
    if "context_bundle" in result and "hits" in result["context_bundle"]:
        hits = result["context_bundle"]["hits"]
    elif "hits" in result:
        # Projected directly to bundle
        hits = result["hits"]
    elif "results" in result:
        # Raw execute_query output
        hits = result["results"]

    for hit in hits:
        # 1. Backwards compatible top-level repo_id
        if "repo_id" in hit and isinstance(hit["repo_id"], str):
            resolved_bundles.add(hit["repo_id"])
        # 2. Epistemics bundle_origin (Context-Bundle.v1 contract)
        elif "epistemics" in hit and isinstance(hit["epistemics"], dict):
            bundle_origin = hit["epistemics"].get("bundle_origin")
            if bundle_origin and isinstance(bundle_origin, str):
                resolved_bundles.add(bundle_origin)
        # 3. Explicit range_ref repo_id
        elif "range_ref" in hit and isinstance(hit["range_ref"], dict):
            repo_id = hit["range_ref"].get("repo_id")
            if repo_id and isinstance(repo_id, str):
                resolved_bundles.add(repo_id)

    # 4. Fallback: file-artifact federation_trace shape.
    # This branch handles the CLI/file-artifact form validated by
    # federation-trace.v1.schema.json (`bundles[]`).
    # Current API/v2 runtime paths use the inline runtime shape
    # (`bundle_status`, `bundle_errors`, `bundle_traces`, ...), not `bundles[]`.
    # New code should not rely on this branch unless it intentionally consumes
    # the file-artifact compatibility shape.
    if "federation_trace" in result and "bundles" in result["federation_trace"]:
        for bundle in result["federation_trace"]["bundles"]:
            if bundle.get("status") == "ok" and "repo_id" in bundle and isinstance(bundle["repo_id"], str):
                resolved_bundles.add(bundle["repo_id"])

    warnings: List[str] = []
    if "warnings" in result:
        warnings = result["warnings"]

    # Calculate integrity hashes
    integrity = {
        "query_trace_sha256": None,
        "context_bundle_sha256": None
    }

    base_dir = out_dir if out_dir else Path.cwd()

    if query_trace_ref:
        trace_path = base_dir / query_trace_ref
        try:
            if trace_path.exists():
                integrity["query_trace_sha256"] = hashlib.sha256(trace_path.read_bytes()).hexdigest()
        except OSError as e:
            logger.warning("Failed to compute SHA256 for query trace at %s: %s", trace_path, e)

    if context_bundle_ref:
        bundle_path = base_dir / context_bundle_ref
        try:
            if bundle_path.exists():
                integrity["context_bundle_sha256"] = hashlib.sha256(bundle_path.read_bytes()).hexdigest()
        except OSError as e:
            logger.warning("Failed to compute SHA256 for context bundle at %s: %s", bundle_path, e)

    try:
        lenskit_version = importlib.metadata.version("lenskit")
    except importlib.metadata.PackageNotFoundError:
        lenskit_version = "unknown"

    environment = {
        "lenskit_version": lenskit_version,
        "index_path": index_path,
        "timestamp_utc": datetime.now(timezone.utc).isoformat()
    }

    session = {
        "request": request_contract,
        "resolved_bundles": sorted(list(resolved_bundles)),
        "refs": {
            "query_trace_ref": query_trace_ref,
            "context_bundle_ref": context_bundle_ref,
            "diagnostics_ref": diagnostics_ref,
            "integrity": integrity
        },
        "warnings": warnings,
        "environment": environment
    }

    return session
