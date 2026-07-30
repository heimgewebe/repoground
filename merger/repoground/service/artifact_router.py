from __future__ import annotations

from collections.abc import Callable
from types import ModuleType
from typing import Any, Dict, List, Optional, Union
from pathlib import Path

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import FileResponse

from .auth import verify_token
from .models import (
    Artifact,
    ArtifactLookupRequest,
    ContextLookupRequest,
    TraceLookupRequest,
)
from .router_support import AttributeProxy, dynamic_callable
from ..adapters.security import AccessDeniedError, InvalidPathError
from merger.repoground.core.merge import get_merges_dir

_RUNTIME_META_FIELDS = (
    "authority",
    "canonicality",
    "artifact_shape",
    "retention_policy",
    "lifecycle_status",
    "expires_at",
    "claim_boundaries",
)

router = APIRouter()


@router.get('/api/artifacts', response_model=List[Artifact], dependencies=[Depends(verify_token)])
def list_artifacts(repo: Optional[str] = None):
    arts = state.job_store.get_all_artifacts()
    if repo:
        arts = [a for a in arts if repo in a.repos]
    return arts

@router.get('/api/artifacts/latest', dependencies=[Depends(verify_token)])
def get_latest_artifact(repo: str, level: str = "max", mode: str = "gesamt"):
    # "Heimgewebe-Hebel" - Return the single latest matching artifact
    arts = state.job_store.get_all_artifacts()
    matches = []

    for a in arts:
        # Filter by params
        if a.params.level != level:
            continue
        if a.params.mode != mode:
            continue

        # Filter by repo
        # If artifact covers specific repos, 'repo' must be in that list.
        # If artifact covers all (empty list/None), it counts as a match for any repo query?
        # Or does 'latest?repo=X' imply "Snapshot of X"?
        # Usually "Snapshot of X" means X is in the list.
        if a.repos:
            if repo in a.repos:
                matches.append(a)
        else:
            # Artifact is for ALL repos.
            # Does this count as "latest artifact for repo X"?
            # Yes, if X is in the hub. We assume it is.
            matches.append(a)

    if not matches:
        raise HTTPException(status_code=404, detail="No matching artifact found")

    # Sort by created_at desc (lexicographical ISO string sort works)
    # The JobStore already returns sorted list (desc), but to be safe/explicit:
    latest = max(matches, key=lambda x: x.created_at)
    return latest

@router.get('/api/artifacts/{id}', dependencies=[Depends(verify_token)])
def get_artifact(id: str):
    art = state.job_store.get_artifact(id)
    if not art:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return art

def _copy_runtime_metadata(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Return a dict containing only the runtime metadata fields present in *entry*."""
    return {field: entry[field] for field in _RUNTIME_META_FIELDS if field in entry}

@router.post('/api/artifact_lookup', dependencies=[Depends(verify_token)])
def api_artifact_lookup(request: ArtifactLookupRequest):
    """Retrieve a previously stored query runtime artifact by stable ID.

    Artifacts (query_trace, context_bundle, agent_query_session) are stored
    automatically when a query is executed with trace=True or
    build_context_bundle=True. The artifact_ids map is included in the query
    response so callers can extract the IDs for subsequent lookups.

    This endpoint is read-only and never recomputes anything.
    """
    if state.query_artifact_store is None:
        return {
            "artifact_type": request.artifact_type,
            "id": request.id,
            "status": "error",
            "artifact": None,
            "warnings": ["Query artifact store not initialized"],
        }

    entry = state.query_artifact_store.get(request.id)

    if entry is None:
        return {
            "artifact_type": request.artifact_type,
            "id": request.id,
            "status": "not_found",
            "artifact": None,
            "warnings": [f"No artifact found with id={request.id!r}"],
        }

    if entry["artifact_type"] != request.artifact_type:
        return {
            "artifact_type": request.artifact_type,
            "id": request.id,
            "status": "not_found",
            "artifact": None,
            "warnings": [
                f"Artifact {request.id!r} has type {entry['artifact_type']!r}, "
                f"not {request.artifact_type!r}"
            ],
        }

    artifact_payload: Dict[str, Any] = {
        "provenance": entry["provenance"],
        "created_at": entry["created_at"],
        "data": entry["data"],
        **_copy_runtime_metadata(entry),
    }

    return {
        "artifact_type": entry["artifact_type"],
        "id": entry["id"],
        "status": "ok",
        "artifact": artifact_payload,
        "warnings": [],
    }

@router.post('/api/trace_lookup', dependencies=[Depends(verify_token)])
def api_trace_lookup(request: TraceLookupRequest):
    """Retrieve a previously stored query_trace artifact by stable ID.

    Typed read-only facade over the QueryArtifactStore. Only artifacts of
    type 'query_trace' are returned. If the ID exists but refers to a
    different artifact type, status 'not_found' is returned with a warning
    naming the actual type — no foreign artifact data is leaked.

    This endpoint is read-only and never recomputes anything.
    """
    if state.query_artifact_store is None:
        return {
            "status": "error",
            "id": request.id,
            "trace": None,
            "provenance": None,
            "created_at": None,
            "warnings": ["Query artifact store not initialized"],
        }

    entry = state.query_artifact_store.get(request.id)

    if entry is None:
        return {
            "status": "not_found",
            "id": request.id,
            "trace": None,
            "provenance": None,
            "created_at": None,
            "warnings": [f"No artifact found with id={request.id!r}"],
        }

    if entry["artifact_type"] != "query_trace":
        return {
            "status": "not_found",
            "id": request.id,
            "trace": None,
            "provenance": None,
            "created_at": None,
            "warnings": [
                f"Artifact {request.id!r} has type {entry['artifact_type']!r}, not 'query_trace'"
            ],
        }

    resp: Dict[str, Any] = {
        "status": "ok",
        "id": entry["id"],
        "trace": entry["data"],
        "provenance": entry["provenance"],
        "created_at": entry["created_at"],
        "warnings": [],
        **_copy_runtime_metadata(entry),
    }
    return resp

@router.post('/api/context_lookup', dependencies=[Depends(verify_token)])
def api_context_lookup(request: ContextLookupRequest):
    """Retrieve a previously stored context_bundle artifact by stable ID.

    Typed read-only facade over the QueryArtifactStore. Only artifacts of
    type 'context_bundle' are returned. If the ID exists but refers to a
    different artifact type, status 'not_found' is returned with a warning
    naming the actual type — no foreign artifact data is leaked.

    This endpoint is read-only and never recomputes or re-executes a query.
    """
    if state.query_artifact_store is None:
        return {
            "status": "error",
            "id": request.id,
            "context_bundle": None,
            "provenance": None,
            "created_at": None,
            "warnings": ["Query artifact store not initialized"],
        }

    entry = state.query_artifact_store.get(request.id)

    if entry is None:
        return {
            "status": "not_found",
            "id": request.id,
            "context_bundle": None,
            "provenance": None,
            "created_at": None,
            "warnings": [f"No artifact found with id={request.id!r}"],
        }

    if entry["artifact_type"] != "context_bundle":
        return {
            "status": "not_found",
            "id": request.id,
            "context_bundle": None,
            "provenance": None,
            "created_at": None,
            "warnings": [
                f"Artifact {request.id!r} has type {entry['artifact_type']!r}, not 'context_bundle'"
            ],
        }

    resp: Dict[str, Any] = {
        "status": "ok",
        "id": entry["id"],
        "context_bundle": entry["data"],
        "provenance": entry["provenance"],
        "created_at": entry["created_at"],
        "warnings": [],
        **_copy_runtime_metadata(entry),
    }
    return resp

def _serve_file(base_dir: Path, requested_path: Union[str, Path], filename: Optional[str] = None) -> FileResponse:
    """
    Unified file serving logic with security checks.
    1. Validates base_dir against security allowlist.
    2. Derives file_path from base_dir + requested_path.
    3. Ensures file_path is within base_dir.
    4. Returns a FileResponse.
    """
    # 1. Early Traversal & Absolute Path Guard (UX/400)
    req_p = Path(requested_path)
    # Stricter segment check to allow filenames like "foo..bar.md" while blocking traversal
    if req_p.is_absolute() or any(part == ".." for part in req_p.parts) or "\\" in str(req_p):
        raise HTTPException(status_code=400, detail="Invalid path: Traversal, absolute paths, or backslashes not allowed")

    sec = get_security_config()
    try:
        # 2. Validate Base (returns canonical path)
        resolved_base = sec.validate_path(base_dir)

        # 3. Derive File Path
        # Joining with Path(requested_path) is now safe because we checked is_absolute()
        target_path = resolved_base / req_p

        # 4. Validate Target
        # validate_path returns resolved/canonical paths.
        resolved_file = sec.validate_path(target_path)

        # 5. Consistency: Explicitly check if file is inside the intended validated base_dir
        resolved_file.relative_to(resolved_base)

        if not resolved_file.exists():
            raise HTTPException(status_code=404, detail="File on disk missing")

        if not resolved_file.is_file():
            raise HTTPException(status_code=404, detail="Not a regular file")

        return FileResponse(resolved_file, filename=filename or resolved_file.name)
    except AccessDeniedError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except InvalidPathError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied: File outside of expected directory")

@router.get('/api/artifacts/{id}/download', dependencies=[Depends(verify_token)])
def download_artifact(id: str, key: str = "md"):
    art = state.job_store.get_artifact(id)
    if not art:
        raise HTTPException(status_code=404, detail="Artifact not found")

    filename = art.paths.get(key)
    if not filename:
        # Try finding part
        if key == "md" and "canonical_md" in art.paths:
            filename = art.paths["canonical_md"]
        elif key == "json" and "index_json" in art.paths:
             filename = art.paths["index_json"]
        else:
             raise HTTPException(status_code=404, detail=f"File key '{key}' not found in artifact")

    # Determine base directory
    # Priority 1: Effective merges_dir captured at creation time (new field)
    if art.merges_dir:
        p = Path(art.merges_dir)
        if not p.is_absolute():
            # Resolve relative paths against HUB (defense in depth for drifted persistence)
            merges_dir = (Path(art.hub) / p)
        else:
            merges_dir = p
    # Priority 2: Requested merges_dir (params)
    # Backward compatibility: if art.merges_dir is None (legacy artifacts)
    elif art.params.merges_dir:
        p = Path(art.params.merges_dir)
        if not p.is_absolute():
            merges_dir = (Path(art.hub) / p)
        else:
            merges_dir = p
    else:
        # Default: hub/merges
        merges_dir = get_merges_dir(Path(art.hub))

    # Ensure merges_dir is absolute/canonical for security validation
    # (Addresses potential relative paths in legacy artifacts)
    merges_dir = merges_dir.resolve()

    # Unified file serving with security checks
    return _serve_file(merges_dir, filename, filename=filename)


def build_router(app_provider: Callable[[], ModuleType]):
    global state, get_security_config
    state = AttributeProxy(app_provider, 'state')
    get_security_config = dynamic_callable(app_provider, 'get_security_config')
    return (
        router,
        list_artifacts,
        get_latest_artifact,
        get_artifact,
        _copy_runtime_metadata,
        api_artifact_lookup,
        api_trace_lookup,
        api_context_lookup,
        _serve_file,
        download_artifact,
    )
