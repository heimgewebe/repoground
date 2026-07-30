from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any, Dict, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException

from .auth import verify_token
from .models import FederationQueryRequest, QueryRequest
from .router_support import AttributeProxy
from .path_helpers import is_safe_filename as _is_safe_filename, resolve_request_path as _resolve_request_path
from merger.repoground.core.merge import get_merges_dir

router = APIRouter()


def _extract_projected_context_bundle(projected: Any) -> Optional[Dict[str, Any]]:
    """Return a context bundle from wrapper or direct-bundle projections."""
    if not isinstance(projected, dict):
        return None
    context_bundle = projected.get("context_bundle")
    if isinstance(context_bundle, dict):
        return context_bundle
    if "hits" in projected:
        return projected
    return None


def _query_filters(request: FederationQueryRequest | QueryRequest) -> Dict[str, Any]:
    return {
        "repo": request.repo,
        "path": request.path,
        "ext": request.ext,
        "layer": request.layer,
        "artifact_type": request.artifact_type,
    }


def _load_embedding_policy(base_dir: Path, filename: Optional[str]) -> Any:
    from ..cli.policy_loader import EmbeddingPolicyError, load_and_validate_embedding_policy

    if not filename:
        return None
    if not _is_safe_filename(filename):
        raise HTTPException(status_code=400, detail="Invalid embedding_policy path")
    policy_path = _resolve_request_path(base_dir, filename, label="embedding policy")
    try:
        return load_and_validate_embedding_policy(policy_path)
    except EmbeddingPolicyError as exc:
        logger.warning("Embedding policy rejected: %s", type(exc).__name__)
        raise HTTPException(status_code=400, detail="Invalid embedding policy") from exc


def _runtime_provenance(query: str, index_id: str) -> Dict[str, Any]:
    from datetime import datetime, timezone

    return {
        "source_query": query,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "index_id": index_id,
    }


def _resolve_federation_index(request: FederationQueryRequest) -> Path:
    if not state.hub:
        raise HTTPException(status_code=400, detail="Hub not configured")
    if not _is_safe_filename(request.federation_index):
        raise HTTPException(status_code=400, detail="Invalid federation_index path")
    merges_dir = state.merges_dir or get_merges_dir(state.hub)
    index_path = _resolve_request_path(
        merges_dir,
        request.federation_index,
        label="federation index",
    )
    if not index_path.exists():  # lgtm[py/path-injection] codeql-boundary:service-api-root-bounded-files
        raise HTTPException(status_code=404, detail="Federation index not found")
    return index_path


def _execute_federated_query(request: FederationQueryRequest, index_path: Path, policy: Any) -> Dict[str, Any]:
    from ..retrieval.federation_query import execute_federated_query

    try:
        return execute_federated_query(
            federation_index_path=index_path,
            query_text=request.q,
            k=request.k,
            filters=_query_filters(request),
            embedding_policy=policy,
            explain=request.explain,
            trace=request.trace,
            build_context=request.build_context_bundle or bool(request.output_profile),
            allow_external_bundle_paths=False,
        )
    except ValueError as exc:
        logger.warning("Federation query rejected: %s", type(exc).__name__)
        raise HTTPException(status_code=400, detail="Invalid federation query") from exc
    except FileNotFoundError as exc:
        logger.warning("Federation query input missing: %s", type(exc).__name__)
        raise HTTPException(status_code=404, detail="Federation query input not found") from exc
    except RuntimeError as exc:
        logger.exception("Federation query failed: %s", type(exc).__name__)
        raise HTTPException(status_code=500, detail="Federation query failed") from exc


def _build_federation_session(
    request: FederationQueryRequest,
    result: Dict[str, Any],
    projected: Any,
) -> Optional[Dict[str, Any]]:
    from ..retrieval.session import build_agent_query_session_v2

    context_bundle = _extract_projected_context_bundle(projected)
    if not request.trace or context_bundle is None:
        return None
    session = build_agent_query_session_v2(
        request.q,
        context_bundle=context_bundle,
        federation_trace=result.get("federation_trace"),
    )
    if isinstance(projected, dict) and "context_bundle" in projected:
        projected["agent_query_session"] = session
    return session


def _attach_federation_metadata(
    projected: Dict[str, Any],
    artifact_ids: Dict[str, str],
    session: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    if not artifact_ids and session is None:
        return projected
    direct_bundle = "hits" in projected and "context_bundle" not in projected
    if direct_bundle:
        wrapper: Dict[str, Any] = {"context_bundle": projected}
        if artifact_ids:
            wrapper["artifact_ids"] = artifact_ids
        if session is not None:
            wrapper["agent_query_session"] = session
        return wrapper
    if artifact_ids:
        projected["artifact_ids"] = artifact_ids
    return projected


def _store_federation_artifacts(
    request: FederationQueryRequest,
    projected: Any,
    session: Optional[Dict[str, Any]],
) -> Any:
    should_store = request.trace or request.build_context_bundle
    if not isinstance(projected, dict):
        return projected
    if not should_store or state.query_artifact_store is None:
        return _attach_federation_metadata(projected, {}, session)

    run_id = uuid.uuid4().hex
    provenance = _runtime_provenance(request.q, request.federation_index)
    artifact_ids: Dict[str, str] = {}
    context_bundle = _extract_projected_context_bundle(projected)
    if context_bundle is not None:
        artifact_ids["context_bundle"] = state.query_artifact_store.store(
            "context_bundle",
            context_bundle,
            provenance,
            run_id=run_id,
        )
    if session is not None:
        session["artifact_refs"]["context_bundle_id"] = artifact_ids.get("context_bundle")
        artifact_ids["agent_query_session"] = state.query_artifact_store.store(
            "agent_query_session",
            session,
            provenance,
            run_id=run_id,
        )
    return _attach_federation_metadata(projected, artifact_ids, session)


@router.post("/api/federation/query", dependencies=[Depends(verify_token)])
def api_federation_query(request: FederationQueryRequest):
    from ..retrieval.output_projection import project_output

    index_path = _resolve_federation_index(request)
    policy = _load_embedding_policy(index_path.parent, request.embedding_policy)
    result = _execute_federated_query(request, index_path, policy)
    projected = project_output(result, request.output_profile)
    session = _build_federation_session(request, result, projected)
    return _store_federation_artifacts(request, projected, session)


def _artifact_merges_dir(artifact: Any) -> Path:
    if artifact.merges_dir:
        configured = Path(artifact.merges_dir)
    elif getattr(artifact.params, "merges_dir", None) and artifact.params.merges_dir:
        configured = Path(artifact.params.merges_dir)
    else:
        return (Path(artifact.hub) / "merges").resolve()
    if configured.is_absolute():
        return configured.resolve()
    return (Path(artifact.hub) / configured).resolve()


def _resolve_query_index(request: QueryRequest) -> Path:
    from ..cli.stale_check import check_stale_index

    artifact = state.job_store.get_artifact(request.index_id)
    if not artifact:
        raise HTTPException(status_code=404, detail=f"Artifact not found: {request.index_id}")
    filename = artifact.paths.get("sqlite_index") or artifact.paths.get("index_sqlite")
    if not filename:
        raise HTTPException(status_code=400, detail="Artifact does not contain an SQLite index")
    index_path = _resolve_request_path(
        _artifact_merges_dir(artifact),
        filename,
        label="index artifact",
    )
    if not index_path.exists():  # lgtm[py/path-injection] codeql-boundary:service-api-root-bounded-files
        raise HTTPException(status_code=404, detail="Index file missing on disk")
    if check_stale_index(index_path, stale_policy=request.stale_policy) and request.stale_policy == "fail":
        raise HTTPException(status_code=400, detail="Index is stale")
    return index_path


def _resolve_graph_index(request: QueryRequest, index_path: Path) -> Optional[Path]:
    if not request.graph_index:
        return None
    if not _is_safe_filename(request.graph_index):
        raise HTTPException(status_code=400, detail="Invalid graph_index path")
    graph_path = _resolve_request_path(
        index_path.parent,
        request.graph_index,
        label="graph index",
    )
    if not graph_path.exists():  # lgtm[py/path-injection] codeql-boundary:service-api-root-bounded-files
        raise HTTPException(
            status_code=404,
            detail="Explicitly provided graph index file does not exist",
        )
    return graph_path


def _validate_context_options(request: QueryRequest) -> bool:
    if request.context_mode == "window" and request.context_window_lines <= 0:
        raise HTTPException(
            status_code=400,
            detail="--context-mode window requires --context-window-lines > 0",
        )
    if request.context_window_lines > 0 and request.context_mode != "window":
        raise HTTPException(
            status_code=400,
            detail="--context-window-lines requires --context-mode window",
        )
    return (
        request.build_context_bundle
        or bool(request.output_profile)
        or request.context_mode != "exact"
        or request.context_window_lines > 0
    )


def _execute_query_request(
    request: QueryRequest,
    index_path: Path,
    graph_index_path: Optional[Path],
    policy: Any,
    build_context: bool,
) -> Dict[str, Any]:
    from ..retrieval.query_core import execute_query

    try:
        return execute_query(
            index_path=index_path,
            query_text=request.q,
            k=request.k,
            filters=_query_filters(request),
            embedding_policy=policy,
            explain=request.explain,
            overmatch_guard=request.overmatch_guard,
            graph_index_path=graph_index_path,
            graph_weights=request.graph_weights,
            test_penalty=request.test_penalty,
            trace=request.trace,
            build_context=build_context,
            context_mode=request.context_mode,
            context_window_lines=request.context_window_lines,
            read_only=True,
        )
    except ValueError as exc:
        logger.warning("Query rejected: %s", type(exc).__name__)
        raise HTTPException(status_code=400, detail="Invalid query request") from exc
    except FileNotFoundError as exc:
        logger.warning("Query input missing: %s", type(exc).__name__)
        raise HTTPException(status_code=404, detail="Query input not found") from exc
    except RuntimeError as exc:
        logger.exception("Query execution failed: %s", type(exc).__name__)
        raise HTTPException(status_code=500, detail="Query execution failed") from exc


def _build_query_session(request: QueryRequest, projected: Any) -> Optional[Dict[str, Any]]:
    from ..retrieval.session import build_agent_query_session_v2

    if not request.trace or not isinstance(projected, dict) or "context_bundle" not in projected:
        return None
    session = build_agent_query_session_v2(request.q, projected.get("context_bundle"))
    projected["agent_query_session"] = session
    return session


def _query_context_bundle(projected: Dict[str, Any]) -> Any:
    context_bundle = projected.get("context_bundle")
    if context_bundle is None and "hits" in projected:
        return projected
    return context_bundle


def _attach_query_artifact_ids(
    projected: Dict[str, Any],
    artifact_ids: Dict[str, str],
) -> Dict[str, Any]:
    if not artifact_ids:
        return projected
    if "hits" in projected and "context_bundle" not in projected:
        return {"context_bundle": projected, "artifact_ids": artifact_ids}
    projected["artifact_ids"] = artifact_ids
    return projected


def _store_query_artifacts(
    request: QueryRequest,
    result: Dict[str, Any],
    projected: Any,
    session: Optional[Dict[str, Any]],
) -> Any:
    should_store = request.trace or request.build_context_bundle
    if not should_store or state.query_artifact_store is None or not isinstance(projected, dict):
        return projected

    run_id = uuid.uuid4().hex
    provenance = _runtime_provenance(request.q, request.index_id)
    artifact_ids: Dict[str, str] = {}
    if "query_trace" in result:
        artifact_ids["query_trace"] = state.query_artifact_store.store(
            "query_trace",
            result["query_trace"],
            provenance,
            run_id=run_id,
        )
    context_bundle = _query_context_bundle(projected)
    if context_bundle is not None:
        artifact_ids["context_bundle"] = state.query_artifact_store.store(
            "context_bundle",
            context_bundle,
            provenance,
            run_id=run_id,
        )
    if session is not None:
        session["artifact_refs"]["query_trace_id"] = artifact_ids.get("query_trace")
        session["artifact_refs"]["context_bundle_id"] = artifact_ids.get("context_bundle")
        artifact_ids["agent_query_session"] = state.query_artifact_store.store(
            "agent_query_session",
            session,
            provenance,
            run_id=run_id,
        )
    return _attach_query_artifact_ids(projected, artifact_ids)


@router.post("/api/query", dependencies=[Depends(verify_token)])
def api_query(request: QueryRequest):
    from ..retrieval.output_projection import project_output

    index_path = _resolve_query_index(request)
    policy = _load_embedding_policy(index_path.parent, request.embedding_policy)
    graph_index_path = _resolve_graph_index(request, index_path)
    build_context = _validate_context_options(request)
    result = _execute_query_request(
        request,
        index_path,
        graph_index_path,
        policy,
        build_context,
    )
    projected = project_output(result, request.output_profile)
    session = _build_query_session(request, projected)
    return _store_query_artifacts(request, result, projected, session)


def build_router(app_provider: Callable[[], ModuleType]):
    global state, logger
    state = AttributeProxy(app_provider, "state")
    logger = AttributeProxy(app_provider, "logger")
    return (
        router,
        _extract_projected_context_bundle,
        api_federation_query,
        api_query,
    )
