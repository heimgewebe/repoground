from fastapi import FastAPI, HTTPException, BackgroundTasks, Query, Depends, Body, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse, HTMLResponse, RedirectResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool
from typing import List, Optional, Dict, Any, Union
from pathlib import Path
import os
import asyncio
import json
import time
from pydantic import BaseModel
import ipaddress
import logging
import re
import uuid
from datetime import datetime, timezone

from .models import JobRequest, Job, Artifact, AtlasRequest, AtlasArtifact, AtlasEffective, calculate_job_hash, PrescanRequest, PrescanResponse, FSRoot, FSRootsResponse, FederationQueryRequest, QueryRequest, ArtifactLookupRequest, TraceLookupRequest, ContextLookupRequest
from .jobstore import JobStore
from .query_artifact_store import QueryArtifactStore
from .runner import JobRunner
from .logging_provider import LogProvider, FileLogProvider
from .auth import verify_token
from ..adapters.security import (
    get_security_config,
    validate_hub_path,
    validate_repo_name,
    InvalidPathError,
    AccessDeniedError,
)
from ..adapters.filesystem import resolve_fs_path, list_allowed_roots, issue_fs_token
from ..adapters.atlas import AtlasScanner, render_atlas_md
from ..adapters.metarepo import sync_from_metarepo
from merger.lenskit.atlas.planner import plan_atlas_outputs, write_mode_outputs
from merger.lenskit.atlas.lifecycle import run_scan_lifecycle
from ..adapters import sources as sources_refresh
from ..adapters import diagnostics as diagnostics_rebuild

from merger.lenskit.core.merge import get_merges_dir, SPEC_VERSION, prescan_repo

# Global Version Info
SERVER_START_TIME = datetime.now(timezone.utc).isoformat()

# Logging setup
logger = logging.getLogger(__name__)

def _get_server_version():
    # 1. Env Var (Canonical for builds)
    env_ver = os.getenv("RLENS_VERSION")
    if env_ver:
        return env_ver

    # 2. Git Hash
    try:
        import subprocess
        # Robustly find git root
        cwd_candidate = Path(__file__).parent
        try:
            repo_root = subprocess.check_output(
                ["git", "rev-parse", "--show-toplevel"],
                cwd=str(cwd_candidate),
                stderr=subprocess.DEVNULL
            ).decode().strip()
        except Exception:
            repo_root = str(cwd_candidate)

        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo_root,
            stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception as exc:
        logger.debug("Falling back to dev server version: %s", exc)

    return "dev"

SERVER_VERSION = _get_server_version()

# Build ID for cache busting
# If RLENS_BUILD_ID is set (CI/CD), use it (stable per build).
# Else fall back to SERVER_VERSION (if git hash).
# If dev/unknown, append timestamp to force reload on restarts.
_env_build_id = os.getenv("RLENS_BUILD_ID")
if _env_build_id:
    BUILD_ID = _env_build_id
elif SERVER_VERSION != "dev":
    BUILD_ID = SERVER_VERSION
else:
    BUILD_ID = f"dev-{int(time.time())}"

ACTIVE_JOB_STATUSES = {"queued", "running", "canceling"}


def _parse_iso_utc(value: Any) -> Optional[datetime]:
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _mark_persisted_active_jobs_terminal(job_store: JobStore) -> int:
    now = datetime.now(timezone.utc).isoformat()
    interrupted_error = "interrupted by service restart; job was not resumed"
    system_log_line = (
        "[system] Job marked failed on service startup because rLens does not "
        "resume persisted active jobs."
    )

    reconciled = 0
    for job in job_store.get_all_jobs():
        if job.status not in ACTIVE_JOB_STATUSES:
            continue

        job.status = "failed"
        job.error = interrupted_error
        job.finished_at = now

        # Preserve a useful trace in the job log before saving the terminal state.
        job_store.append_log_line(job.id, system_log_line)
        job_store.update_job(job)
        reconciled += 1

    return reconciled

app = FastAPI(title="rLens", version=SERVER_VERSION)

@app.exception_handler(InvalidPathError)
async def invalid_path_handler(request: Request, exc: InvalidPathError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})

@app.exception_handler(AccessDeniedError)
async def access_denied_handler(request: Request, exc: AccessDeniedError):
    return JSONResponse(status_code=403, content={"detail": str(exc)})

# GC Configuration
GC_MAX_JOBS = int(os.getenv("RLENS_GC_MAX_JOBS", "100"))
GC_MAX_AGE_HOURS = int(os.getenv("RLENS_GC_MAX_AGE_HOURS", "24"))
# SSE Configuration
SSE_IDLE_RECHECK_SEC = 5.0

def _is_loopback_host(host: str) -> bool:
    h = (host or "").strip().lower()
    if h in ("127.0.0.1", "localhost", "::1"):
        return True
    try:
        return ipaddress.ip_address(h).is_loopback
    except Exception:
        return False

# Cache-Control Middleware to support aggressive busting for WebUI
# This is critical for preventing browsers (Brave/Chrome) from serving stale UI
@app.middleware("http")
async def add_cache_control_header(request: Request, call_next):
    response = await call_next(request)

    # Target specific UI assets and the root index
    # Note: request.url.path includes the leading slash
    path = request.url.path
    if path in ["/", "/index.html", "/app.js", "/style.css"]:
        # "no-store" is the strongest directive.
        # "must-revalidate" is implied by no-store in modern browsers, but harmless.
        # We simplify to no-store but keep Pragma/Expires for legacy/proxy robustness.
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"

    return response

def _write_json_atomic(path: Path, data: dict) -> None:
    """Writes JSON data to a file atomically to prevent partial reads."""
    tmp_path = path.with_suffix(path.suffix + f".tmp.{os.getpid()}.{uuid.uuid4().hex}")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, path)

# Global State
class ServiceState:
    hub: Path = None
    merges_dir: Path = None
    job_store: JobStore = None
    query_artifact_store: QueryArtifactStore = None
    runner: JobRunner = None
    log_provider: LogProvider = None

state = ServiceState()

def init_service(hub_path: Path, token: Optional[str] = None, host: str = "127.0.0.1", merges_dir: Optional[Path] = None):
    state.hub = hub_path
    state.merges_dir = merges_dir
    state.job_store = JobStore(hub_path)
    reconciled_jobs = _mark_persisted_active_jobs_terminal(state.job_store)
    if reconciled_jobs:
        logger.info("Reconciled %s persisted active job(s) on startup.", reconciled_jobs)
    # Co-locate QueryArtifactStore with the effective merges dir so query artifacts
    # land alongside the outputs they reference.  JobStore uses hub_path/merges
    # unconditionally; QueryArtifactStore follows state.merges_dir when set.
    _effective_merges = merges_dir if merges_dir else get_merges_dir(hub_path)
    state.query_artifact_store = QueryArtifactStore(_effective_merges / ".rlens-service")
    state.runner = JobRunner(state.job_store)
    state.log_provider = FileLogProvider(state.job_store)

    # Configure Security
    sec = get_security_config()
    sec.set_token(token)
    # Allowlist the Hub
    sec.add_allowlist_root(hub_path)
    # Allowlist Merges Dir if separate
    if merges_dir:
        sec.add_allowlist_root(merges_dir)

    # Allow System Root (Home) for Atlas
    # "System" root maps to user home (e.g. /home/alex), not /
    try:
        sec.add_allowlist_root(Path.home().resolve())
    except Exception as e:
        logger.debug("Could not allow system root: %s", e, exc_info=True)

    # Root Access: enabled by default on loopback with auth
    is_loopback = _is_loopback_host(host)
    has_token = bool(token or os.getenv("RLENS_TOKEN") or os.getenv("RLENS_FS_TOKEN_SECRET"))

    if is_loopback and has_token:
        root = Path("/").resolve()
        if root not in getattr(sec, "allowlist_roots", []):
            logger.warning("Root allowlisted (loopback + auth).")
            sec.add_allowlist_root(root)
    else:
        logger.warning(
            "Root browsing refused (loopback=%s, has_token=%s).",
            is_loopback,
            has_token
        )

    # Apply CORS based on host
    # Prevent middleware duplication (if init called multiple times in tests)
    has_cors = any(m.cls == CORSMiddleware for m in app.user_middleware)
    if not has_cors:
        if _is_loopback_host(host):
            # Regex for localhost/127.0.0.1 with any port
            allow_origin_regex = r"^http://(localhost|127\.0\.0\.1)(:\d+)?$"
            allow_origins = []
        else:
            allow_origin_regex = None
            allow_origins = [] # Strict for non-loopback by default

        app.add_middleware(
            CORSMiddleware,
            allow_origins=allow_origins,
            allow_origin_regex=allow_origin_regex,
            allow_credentials=False,
            allow_methods=["GET", "POST"],
            allow_headers=["Authorization", "Content-Type", "x-rlens-token"],
        )

def _list_dir(candidate: Path) -> Dict[str, Any]:
    # Defense-in-depth: always re-validate before touching the filesystem.
    sec = get_security_config()
    resolved = sec.validate_path(candidate)

    if not resolved.exists():
        raise HTTPException(status_code=404, detail="Path not found")
    if not resolved.is_dir():
        raise HTTPException(status_code=400, detail="Not a directory")

    dirs: List[str] = []
    files: List[str] = []
    entries: List[Dict[str, Any]] = []

    try:
        for child in sorted(resolved.iterdir(), key=lambda x: x.name.lower()):
            if child.is_dir():
                dirs.append(child.name)
                entries.append({"name": child.name, "type": "dir", "token": issue_fs_token(child.resolve())})
            else:
                files.append(child.name)
                entries.append({"name": child.name, "type": "file"})
    except OSError as e:
        logger.error("Error listing %s: %s", resolved, e)
        raise HTTPException(status_code=500, detail="Error listing directory")

    return {"abs": str(resolved), "dirs": dirs, "files": files, "entries": entries}

@app.get("/api/fs/roots", response_model=FSRootsResponse, dependencies=[Depends(verify_token)])
def api_fs_roots():
    """
    Return a stable list of allowed roots for the picker & agents.
    The client should prefer token navigation.
    """
    roots = list_allowed_roots(state.hub, getattr(state, "merges_dir", None))
    # Add tokens for each root
    out = []
    for r in roots:
        p = Path(r["path"]).resolve()
        out.append(FSRoot(
            id=r["id"],
            path=str(p), # Ensure reported path matches token path exactly
            token=issue_fs_token(p)
        ))
    return FSRootsResponse(roots=out)

@app.get("/api/fs", dependencies=[Depends(verify_token)])
@app.get("/api/fs/list", dependencies=[Depends(verify_token)])
def api_fs_list(token: Optional[str] = None, root: Optional[str] = None, rel: Optional[str] = None):
    """
    FS listing endpoint.
    Canonical: ?token=<opaque>
    Transitional: ?root=<root_id>&rel=   (base only; subpaths require tokens)
    """
    hub = state.hub
    merges_dir = getattr(state, "merges_dir", None)
    trusted = resolve_fs_path(hub=hub, merges_dir=merges_dir, root_id=root, rel_path=rel, token=token)
    payload = _list_dir(trusted.path)
    # Add parent token for upward navigation if possible
    try:
        # Only offer parent if parent itself is allowed (avoid broken Up + reduce taint)
        sec = get_security_config()
        p = trusted.path
        if p.parent and p.parent != p:
            parent_resolved = sec.validate_path(p.parent)
            payload["parent_token"] = issue_fs_token(parent_resolved)
    except Exception as exc:
        logger.debug("Skipping parent token generation for %s: %s", trusted.path, exc)
    return {"root": root, "rel": rel, "token": token, **payload}

@app.post("/api/sources/refresh", dependencies=[Depends(verify_token)])
def api_sources_refresh():
    if not state.hub:
        raise HTTPException(status_code=400, detail="Hub not configured")
    try:
        return sources_refresh.refresh(state.hub)
    except Exception:
        logger.exception("Sources refresh failed")
        raise HTTPException(status_code=500, detail="Sources refresh failed")

@app.post("/api/diagnostics/rebuild", dependencies=[Depends(verify_token)])
def api_diagnostics_rebuild():
    if not state.hub:
        raise HTTPException(status_code=400, detail="Hub not configured")
    try:
        return diagnostics_rebuild.rebuild(state.hub)
    except Exception:
        logger.exception("Diagnostics rebuild failed")
        raise HTTPException(status_code=500, detail="Diagnostics rebuild failed")

@app.get("/api/diagnostics", dependencies=[Depends(verify_token)])
def api_diagnostics_lookup():
    """Read-only diagnostics lookup over the persisted snapshot."""
    if not state.hub:
        raise HTTPException(status_code=400, detail="Hub not configured")

    diag_path = state.hub / ".gewebe" / "cache" / "diagnostics.snapshot.json"
    if not diag_path.exists():
        return {
            "status": "not_found",
            "snapshot": None,
            "freshness": None,
            "warnings": ["diagnostics.snapshot.json not found"],
        }

    try:
        snapshot_text = diag_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        logger.exception("Failed to read diagnostics snapshot")
        return {
            "status": "error",
            "snapshot": None,
            "freshness": None,
            "warnings": ["Unable to read diagnostics snapshot"],
        }

    try:
        snapshot = json.loads(snapshot_text)
    except json.JSONDecodeError:
        logger.exception("Failed to parse diagnostics snapshot JSON")
        return {
            "status": "error",
            "snapshot": None,
            "freshness": None,
            "warnings": ["Invalid diagnostics snapshot JSON"],
        }

    if not isinstance(snapshot, dict):
        logger.warning(
            "Diagnostics snapshot JSON must be an object, got %s",
            type(snapshot).__name__,
        )
        return {
            "status": "error",
            "snapshot": None,
            "freshness": None,
            "warnings": ["Invalid diagnostics snapshot payload: expected JSON object"],
        }

    generated_at = _parse_iso_utc(snapshot.get("generated_at"))
    freshness = None
    if generated_at is not None:
        age_seconds = max(int((datetime.now(timezone.utc) - generated_at).total_seconds()), 0)
        freshness = {
            "generated_at": snapshot.get("generated_at"),
            "ttl_hours": diagnostics_rebuild.TTL_HOURS,
            "is_stale": age_seconds > diagnostics_rebuild.TTL_HOURS * 3600,
            "age_seconds": age_seconds,
        }

    return {
        "status": "ok",
        "snapshot": snapshot,
        "freshness": freshness,
        "warnings": [],
    }

@app.post("/api/extras/refresh_all", dependencies=[Depends(verify_token)])
def api_extras_refresh_all(payload: Dict[str, Any] = Body(default_factory=dict)):
    """
    Orchestrates optional metarepo-sync + sources refresh + diagnostics rebuild.

    SAFE DEFAULTS:
      - no sync unless explicitly requested
      - apply-sync only if payload.sync.mode == "apply"

    Example:
      { "sync": { "mode": "dry_run" } }
      { "sync": { "mode": "apply" } }
    """
    if not state.hub:
        raise HTTPException(status_code=400, detail="Hub not configured")

    # Sync only if explicitly requested with a valid mode.
    # This prevents accidental sync runs from payloads like { "sync": {} }.
    sync_cfg = payload.get("sync")
    sync_mode = None
    should_sync = False
    if isinstance(sync_cfg, dict):
        m = sync_cfg.get("mode")
        if m in ("dry_run", "apply"):
            sync_mode = m
            should_sync = True

    result = {
        "status": "ok",
        "sync": {"skipped": True},
        "refresh": {},
        "diagnostics": {}
    }

    # 1. Optional Sync
    if should_sync:
        try:
            # We assume "dry_run" is NOT what we want for a "refresh" button, we want "apply".
            # Or should we default to dry_run? User says "refresh_all... optionaler sync...".
            # Usually "refresh" implies getting latest state.
            # But sync_from_metarepo modifies disk (Manifest -> Fleet).
            # Let s assume "apply" is desired if sync=True.
            # Also target list? Default to all? None = all.
            mode = "apply" if sync_mode == "apply" else "dry_run"
            sync_report = sync_from_metarepo(hub_path=state.hub, mode=mode, targets=None)

            if sync_report.get("status") != "ok":
                # Hard fail as requested
                # Warning: msg might contain sensitive details if generated by sync logic
                # However, usually "message" is user-facing. We'll trust sync report message for now,
                # or sanitize it if unsure. Let's use a generic error for safety.
                logger.error("Sync failed in refresh_all: %s", sync_report)
                raise HTTPException(status_code=500, detail="Sync failed")

            result["sync"] = sync_report
        except HTTPException:
            raise
        except Exception:
            logger.exception("Sync failed during refresh_all")
            raise HTTPException(status_code=500, detail="Sync failed")

    # 2. Sources Refresh
    try:
        refresh_res = sources_refresh.refresh(state.hub)
        result["refresh"] = refresh_res
    except Exception:
        logger.exception("Sources refresh failed during refresh_all")
        raise HTTPException(status_code=500, detail="Sources refresh failed")

    # 3. Diagnostics Rebuild
    try:
        diag_res = diagnostics_rebuild.rebuild(state.hub)
        result["diagnostics"] = diag_res
    except Exception:
        logger.exception("Diagnostics rebuild failed during refresh_all")
        raise HTTPException(status_code=500, detail="Diagnostics rebuild failed")

    return result

@app.get("/api/version")
def api_version():
    return {
        "version": SERVER_VERSION,
        "build_id": BUILD_ID,
        "started_at": SERVER_START_TIME
    }

@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "version": SPEC_VERSION,
        "server_version": SERVER_VERSION,
        "hub": str(state.hub),
        "merges_dir": str(state.merges_dir) if state.merges_dir else None,
        "auth_enabled": bool(get_security_config().token),
        "running_jobs": sum(
            1 for j in state.job_store.get_all_jobs()
            if j.status in ACTIVE_JOB_STATUSES
        ) if state.job_store else 0
    }

@app.get("/api/repos", dependencies=[Depends(verify_token)])
def list_repos(hub: Optional[str] = None):
    # If hub provided, validate it first
    target_hub = state.hub
    if hub:
        target_hub = validate_hub_path(hub)

    # Use runner's helper or core helper
    from .runner import _find_repos
    return _find_repos(target_hub)

@app.post("/api/prescan", response_model=PrescanResponse, dependencies=[Depends(verify_token)])
def api_prescan(request: PrescanRequest):
    if not state.hub:
        raise HTTPException(status_code=400, detail="Hub not configured")

    # Resolve repo
    repo_name = validate_repo_name(request.repo)
    repo_root = state.hub / repo_name
    if not repo_root.exists() or not repo_root.is_dir():
        raise HTTPException(status_code=404, detail=f"Repo {repo_name} not found")

    try:
        # Run prescan
        result = prescan_repo(
            repo_root=repo_root,
            max_depth=request.max_depth,
            ignore_globs=request.ignore_globs
        )
        # Convert to response
        return PrescanResponse(
            root=result["root"],
            tree=result["tree"],
            signature=result["signature"],
            file_count=result["file_count"],
            total_bytes=result["total_bytes"]
        )
    except Exception as e:
        logger.exception("Prescan failed")
        raise HTTPException(status_code=500, detail=str(e))


def _is_safe_filename(name: str) -> bool:
    if not name or name in {".", ".."}:
        return False
    if "/" in name or "\\" in name or ":" in name:
        return False
    p = Path(name)
    return p.name == name and not p.is_absolute()


def _extract_projected_context_bundle(projected: Any) -> Optional[Dict[str, Any]]:
    """Return the context-bundle payload from a result-like dict.

    Accepted input shapes:
    - Wrapper: {"context_bundle": {...}, ...}
    - Direct bundle: {"query": ..., "hits": [...], ...}

    Returns the bundle dict for both shapes so callers do not need to branch.
    Returns None when projected is not a dict or does not contain a bundle-like payload.
    """
    if not isinstance(projected, dict):
        return None
    cb = projected.get("context_bundle")
    if isinstance(cb, dict):
        return cb
    if "hits" in projected:
        return projected
    return None


@app.post("/api/federation/query", dependencies=[Depends(verify_token)])
def api_federation_query(request: FederationQueryRequest):
    from ..retrieval.federation_query import execute_federated_query
    from ..retrieval.output_projection import project_output
    from ..cli.policy_loader import load_and_validate_embedding_policy, EmbeddingPolicyError
    from ..retrieval.session import build_agent_query_session_v2

    if not state.hub:
        raise HTTPException(status_code=400, detail="Hub not configured")


    if not _is_safe_filename(request.federation_index):
        raise HTTPException(status_code=400, detail="Invalid federation_index path")

    merges_dir = state.merges_dir or get_merges_dir(state.hub)
    fed_index_path = merges_dir / request.federation_index

    if not fed_index_path.exists():
        raise HTTPException(status_code=404, detail="Federation index not found")


    applied_filters = {
        "repo": request.repo,
        "path": request.path,
        "ext": request.ext,
        "layer": request.layer,
        "artifact_type": request.artifact_type
    }

    policy_instance = None
    if request.embedding_policy:
        if not _is_safe_filename(request.embedding_policy):
            raise HTTPException(status_code=400, detail="Invalid embedding_policy path")
        policy_path = fed_index_path.parent / request.embedding_policy
        try:
            policy_instance = load_and_validate_embedding_policy(policy_path)
        except EmbeddingPolicyError as e:
            raise HTTPException(status_code=400, detail=str(e))

    try:
        result = execute_federated_query(
            federation_index_path=fed_index_path,
            query_text=request.q,
            k=request.k,
            filters=applied_filters,
            embedding_policy=policy_instance,
            explain=request.explain,
            trace=request.trace,
            build_context=request.build_context_bundle or bool(request.output_profile)
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    projected = project_output(result, request.output_profile)

    # Build agent_query_session when trace is active and a context_bundle is present.
    # Use _extract_projected_context_bundle — the same helper used by the storage block
    # below — so session-creation and storage share identical context-bundle recognition.
    # This handles both wrapper-form {"context_bundle": ...} and direct-bundle form
    # {"hits": [...], ...} uniformly, closing the asymmetry where storage handled both
    # forms but session-creation only handled wrapper-form.
    #
    # Today, trace=True always produces wrapper-form in the federation path because
    # execute_federated_query always emits federation_trace when trace=True, and
    # project_output() always wraps when federation_trace is present. The symmetry
    # fix future-proofs against changes to either of those functions.
    _fed_session: Optional[Dict[str, Any]] = None
    _fed_cb_for_session = _extract_projected_context_bundle(projected) if isinstance(projected, dict) else None
    if request.trace and _fed_cb_for_session is not None:
        _fed_session = build_agent_query_session_v2(
            request.q,
            context_bundle=_fed_cb_for_session,
            federation_trace=result.get("federation_trace"),
        )
        # Inject into projected only when it is wrapper-form. When projected is
        # direct-bundle form, agent_query_session must NOT be mutated directly into
        # the bundle (additionalProperties: false); it is attached in the wrapping
        # step inside the storage block, or via the no-store fallback below.
        if isinstance(projected, dict) and "context_bundle" in projected:
            projected["agent_query_session"] = _fed_session

    # Store query runtime artifacts so they can be retrieved via artifact_lookup.
    # Triggered when trace=True or build_context_bundle=True to keep storage opt-in.
    # Note: federation does not produce a standalone query_trace artifact; query_trace_id
    # will remain null in artifact_refs.
    _fed_should_store = request.trace or request.build_context_bundle
    if _fed_should_store and state.query_artifact_store is not None and isinstance(projected, dict):
        from datetime import datetime, timezone as _tz
        _fed_run_id = uuid.uuid4().hex
        _fed_provenance = {
            "source_query": request.q,
            "timestamp": datetime.now(_tz.utc).isoformat(),
            "index_id": request.federation_index,
        }
        _fed_artifact_ids: dict = {}

        # context_bundle: store the projected form returned to the client.
        # Use the helper to handle both wrapper-form (projected["context_bundle"])
        # and direct-bundle form (projected has "hits" at top level, no "context_bundle" key).
        _fed_cb = _extract_projected_context_bundle(projected)
        if _fed_cb is not None:
            _fed_artifact_ids["context_bundle"] = state.query_artifact_store.store(
                "context_bundle", _fed_cb, _fed_provenance, run_id=_fed_run_id
            )

        # Backfill context_bundle_id before storing the session.
        # query_trace_id stays null (no standalone federation query_trace artifact).
        # agent_query_session_id is intentionally null — circular self-reference; the
        # assigned ID is surfaced via artifact_ids.agent_query_session in the response.
        if _fed_session is not None:
            _fed_session["artifact_refs"]["context_bundle_id"] = _fed_artifact_ids.get("context_bundle")
            _fed_artifact_ids["agent_query_session"] = state.query_artifact_store.store(
                "agent_query_session", _fed_session, _fed_provenance, run_id=_fed_run_id
            )

        if _fed_artifact_ids:
            # Same wrapping rule as /api/query: don't inject artifact_ids into a bare
            # context_bundle (additionalProperties: false on the bundle schema).
            if "hits" in projected and "context_bundle" not in projected:
                # Direct-bundle form: wrap and include session if present (session was not
                # injected above for direct-bundle form; include it in the wrapper now).
                wrapper: Dict[str, Any] = {"context_bundle": projected, "artifact_ids": _fed_artifact_ids}
                if _fed_session is not None:
                    wrapper["agent_query_session"] = _fed_session
                projected = wrapper
            else:
                projected["artifact_ids"] = _fed_artifact_ids
    elif _fed_session is not None and isinstance(projected, dict) and "hits" in projected and "context_bundle" not in projected:
        # No-store path, direct-bundle form: wrap to carry session without artifact_ids.
        projected = {"context_bundle": projected, "agent_query_session": _fed_session}

    return projected

@app.post("/api/query", dependencies=[Depends(verify_token)])
def api_query(request: QueryRequest):
    from ..retrieval.query_core import execute_query
    from ..retrieval.output_projection import project_output
    from ..cli.stale_check import check_stale_index
    from ..cli.policy_loader import load_and_validate_embedding_policy, EmbeddingPolicyError
    from ..retrieval.session import build_agent_query_session_v2

    art = state.job_store.get_artifact(request.index_id)
    if not art:
        raise HTTPException(status_code=404, detail=f"Artifact not found: {request.index_id}")

    # Resolve artifact path (canonical key is sqlite_index, fallback to index_sqlite for legacy test compat)
    filename = art.paths.get("sqlite_index") or art.paths.get("index_sqlite")
    if not filename:
         raise HTTPException(status_code=400, detail="Artifact does not contain an SQLite index")

    # Use the established artifact base directory logic
    if art.merges_dir:
        p = Path(art.merges_dir)
        merges_dir = (Path(art.hub) / p) if not p.is_absolute() else p
    elif getattr(art.params, "merges_dir", None) and art.params.merges_dir:
        p = Path(art.params.merges_dir)
        merges_dir = (Path(art.hub) / p) if not p.is_absolute() else p
    else:
        # Avoid direct circular imports if possible, or replicate the fallback
        merges_dir = Path(art.hub) / "merges"
    merges_dir = merges_dir.resolve()

    index_path = merges_dir / filename
    if not index_path.exists():
         raise HTTPException(status_code=404, detail="Index file missing on disk")

    is_stale = check_stale_index(index_path, stale_policy=request.stale_policy)
    if is_stale and request.stale_policy == "fail":
         raise HTTPException(status_code=400, detail="Index is stale")

    applied_filters = {
        "repo": request.repo,
        "path": request.path,
        "ext": request.ext,
        "layer": request.layer,
        "artifact_type": request.artifact_type
    }


    policy_instance = None
    if request.embedding_policy:
        if not _is_safe_filename(request.embedding_policy):
            raise HTTPException(status_code=400, detail="Invalid embedding_policy path")
        policy_path = index_path.parent / request.embedding_policy
        try:
            policy_instance = load_and_validate_embedding_policy(policy_path)
        except EmbeddingPolicyError as e:
            raise HTTPException(status_code=400, detail=str(e))

    graph_index_path = None
    if request.graph_index:
        if not _is_safe_filename(request.graph_index):
            raise HTTPException(status_code=400, detail="Invalid graph_index path")
        graph_index_path = index_path.parent / request.graph_index
        if not graph_index_path.exists():
            raise HTTPException(status_code=404, detail="Explicitly provided graph index file does not exist")

    if request.context_mode == "window" and request.context_window_lines <= 0:
        raise HTTPException(status_code=400, detail="--context-mode window requires --context-window-lines > 0")

    if request.context_window_lines > 0 and request.context_mode != "window":
        raise HTTPException(status_code=400, detail="--context-window-lines requires --context-mode window")

    build_context = (
        request.build_context_bundle
        or bool(request.output_profile)
        or request.context_mode != "exact"
        or request.context_window_lines > 0
    )

    try:
        result = execute_query(
            index_path=index_path,
            query_text=request.q,
            k=request.k,
            filters=applied_filters,
            embedding_policy=policy_instance,
            explain=request.explain,
            overmatch_guard=request.overmatch_guard,
            graph_index_path=graph_index_path,
            graph_weights=request.graph_weights,
            test_penalty=request.test_penalty,
            trace=request.trace,
            build_context=build_context,
            context_mode=request.context_mode,
            context_window_lines=request.context_window_lines
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    projected = project_output(result, request.output_profile)

    # Build agent_query_session when trace is active and a context_bundle wrapper is present.
    # This is done unconditionally here so the session exists in both the store-active and
    # store-disabled paths. Artifact IDs are backfilled into artifact_refs if storage runs.
    _agent_session: Optional[Dict[str, Any]] = None
    if request.trace and isinstance(projected, dict) and "context_bundle" in projected:
        _agent_session = build_agent_query_session_v2(request.q, projected.get("context_bundle"))
        projected["agent_query_session"] = _agent_session

    # Store query runtime artifacts so they can be retrieved via artifact_lookup.
    # Triggered when trace=True or build_context_bundle=True to keep storage opt-in.
    _should_store = request.trace or request.build_context_bundle
    if _should_store and state.query_artifact_store is not None and isinstance(projected, dict):
        from datetime import datetime, timezone as _tz
        _run_id = uuid.uuid4().hex
        _provenance = {
            "source_query": request.q,
            "timestamp": datetime.now(_tz.utc).isoformat(),
            "index_id": request.index_id,
        }
        _artifact_ids: dict = {}

        # query_trace: always in the raw result when trace=True
        if "query_trace" in result:
            _artifact_ids["query_trace"] = state.query_artifact_store.store(
                "query_trace", result["query_trace"], _provenance, run_id=_run_id
            )

        # context_bundle: stored in the projected (profile-stripped) form as returned
        # by the API — not the raw internal state from execute_query().  An artifact
        # lookup will therefore return the same shape a client received, which may have
        # had explain blocks or graph_context removed by the output_profile.  Known
        # limitation: the raw pre-projection bundle is not separately addressable.
        _cb = projected.get("context_bundle")
        if _cb is None and "hits" in projected:
            _cb = projected  # direct bundle format (no-wrapper profile path)
        if _cb is not None:
            _artifact_ids["context_bundle"] = state.query_artifact_store.store(
                "context_bundle", _cb, _provenance, run_id=_run_id
            )

        # Backfill artifact IDs into the session's artifact_refs now that we have them.
        # agent_query_session_id is intentionally null — the self-ID is circular: the session
        # is stored below, but backfilling would require a second store write with no update
        # mechanism in QueryArtifactStore.  The assigned ID is surfaced via
        # artifact_ids.agent_query_session in the response instead.
        if _agent_session is not None:
            _agent_session["artifact_refs"]["query_trace_id"] = _artifact_ids.get("query_trace")
            _agent_session["artifact_refs"]["context_bundle_id"] = _artifact_ids.get("context_bundle")
            _artifact_ids["agent_query_session"] = state.query_artifact_store.store(
                "agent_query_session", _agent_session, _provenance, run_id=_run_id
            )

        if _artifact_ids:
            # artifact_ids must not be injected into a direct context bundle because
            # query-context-bundle.v1.schema.json has additionalProperties: false.
            # Three projected shapes are possible (see project_output docstring):
            #   1. No profile → raw result dict (no schema restriction on extra keys).
            #   2. Profile + wrapper → {"context_bundle": ..., ...} (wrapper accepts extras).
            #   3. Profile, no wrapper → direct bundle at top level (hits key, strict schema).
            # Only case 3 requires wrapping.
            if "hits" in projected and "context_bundle" not in projected:
                projected = {"context_bundle": projected, "artifact_ids": _artifact_ids}
            else:
                projected["artifact_ids"] = _artifact_ids

    return projected

@app.post("/api/jobs", response_model=Job, dependencies=[Depends(verify_token)])
def create_job(request: JobRequest):
    # Validate Hub in request
    req_hub = state.hub
    if request.hub:
         req_hub = validate_hub_path(request.hub)

    # Apply default merges dir if not specified
    if not request.merges_dir and state.merges_dir:
        request.merges_dir = str(state.merges_dir)

    # Validate repo names early (API must be strict)
    if request.repos:
        request.repos = [validate_repo_name(r) for r in request.repos]

    # Validate strict_include_paths_by_repo (Sync Check for 400)
    if request.strict_include_paths_by_repo and request.include_paths_by_repo:
        if not request.repos:
             # Implicit all repos? If so, we can't easily validate keys without listing dir.
             # But usually strict mode is used with explicit repos.
             pass
        else:
            missing = [r for r in request.repos if r not in request.include_paths_by_repo]
            if missing:
                raise HTTPException(status_code=400, detail=f"Strict Mode Violation: include_paths_by_repo missing keys for: {missing}")

    # --- Idempotency & GC ---
    resolved_hub_str = str(req_hub)
    content_hash = calculate_job_hash(request, resolved_hub_str, SPEC_VERSION)

    # Lazy GC
    state.job_store.cleanup_jobs(max_jobs=GC_MAX_JOBS, max_age_hours=GC_MAX_AGE_HOURS)

    existing = state.job_store.find_job_by_hash(content_hash)
    if existing and not request.force_new:
        # An identical job that is still active is always safe to reuse: its
        # pre-pull (if any) has not finished, so its result will reflect the
        # freshly-synced state once it completes.
        if existing.status in ("queued", "running", "canceling"):
            logger.info("Reusing existing active job %s", existing.id)
            return existing

        # A succeeded job is only reusable when the new request does NOT ask for an
        # *effective* pre-pull. effective_pre_pull = pre_pull and not plan_only:
        # a plan-only job never mutates repos, so its cached result is still valid;
        # but a real pre_pull=True request wants a fresh repo-sync check the cached
        # result cannot provide, so we run a new job. (force_new bypasses reuse.)
        if existing.status == "succeeded":
            effective_pre_pull = request.pre_pull and not request.plan_only
            if effective_pre_pull:
                logger.info(
                    "Not reusing succeeded job %s because pre_pull=True requires a fresh repo-sync check.",
                    existing.id,
                )
            else:
                logger.info("Reusing existing succeeded job %s", existing.id)
                return existing

    job = Job.create(request, content_hash=content_hash)
    job.hub_resolved = resolved_hub_str
    state.job_store.add_job(job)
    state.runner.submit_job(job.id)
    return job

@app.get("/api/jobs", response_model=List[Job], dependencies=[Depends(verify_token)])
def get_jobs(status: Optional[str] = None, limit: int = 20):
    jobs = state.job_store.get_all_jobs()
    if status:
        jobs = [j for j in jobs if j.status == status]
    return jobs[:limit]

@app.get("/api/jobs/{job_id}", response_model=Job, dependencies=[Depends(verify_token)])
def get_job(job_id: str):
    job = state.job_store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job

@app.post("/api/jobs/{job_id}/cancel", dependencies=[Depends(verify_token)])
def cancel_job(job_id: str):
    job = state.job_store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status in ["succeeded", "failed", "canceled"]:
        return {"status": job.status, "message": "Job already finished"}

    if job.status in ["queued", "running"]:
        job.status = "canceling"
        state.job_store.update_job(job)
    return {"status": job.status}

@app.get("/api/jobs/{job_id}/logs", dependencies=[Depends(verify_token)], response_model=None)
async def stream_logs(request: Request, job_id: str, last_id: Optional[int] = Query(None)):
    # SSE Stream
    job = state.job_store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    loop = asyncio.get_running_loop()

    # Determine start index
    # Prioritize Last-Event-ID header if present
    start_idx = 0
    if request.headers.get("Last-Event-ID"):
        try:
            # Last-Event-ID is a 1-based line id; negative values are clamped defensively
            start_idx = max(0, int(request.headers.get("Last-Event-ID")))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid Last-Event-ID")
    elif last_id is not None:
        start_idx = max(0, last_id)

    async def log_generator():
        event = asyncio.Event()

        def notify():
            loop.call_soon_threadsafe(event.set)

        # last_idx here represents 'last_line_id' (1-based index)
        # 0 means "nothing sent yet"
        last_idx = start_idx

        state.job_store.subscribe_to_logs(job_id, notify)
        try:
            while True:
                # Clear event *before* processing to avoid dropping signals
                # that arrive between the loop processing and wait()
                event.clear()

                # Stop work if client disconnected (prevents zombie generators)
                try:
                    if await request.is_disconnected():
                        break
                except Exception as exc:
                    logger.debug("Failed to check client disconnect state for job %s: %s", job_id, exc)

                # Read logs from file (async safe)
                # Use abstracted provider to allow deterministic mocking in tests
                # Optimized: read chunks using line skip (O(1) memory, preserves line-based semantics)
                chunk_data = await run_in_threadpool(state.log_provider.read_log_chunk, job_id, last_idx)

                if chunk_data:
                    for line, new_id in chunk_data:
                        yield f"id: {new_id}\ndata: {line}\n\n"
                        last_idx = new_id

                # Check status for completion
                current_job = await run_in_threadpool(state.job_store.get_job, job_id)
                if not current_job:
                    break

                if current_job.status in ["succeeded", "failed", "canceled"]:
                    # Ensure we sent everything
                    chunk_data = await run_in_threadpool(state.log_provider.read_log_chunk, job_id, last_idx)
                    if chunk_data:
                        for line, new_id in chunk_data:
                            yield f"id: {new_id}\ndata: {line}\n\n"
                            last_idx = new_id

                    yield "event: end\ndata: end\n\n"
                    break

                # Wait for next event instead of polling, but wake periodically
                # to detect client disconnects if no events are arriving.
                try:
                    await asyncio.wait_for(event.wait(), timeout=SSE_IDLE_RECHECK_SEC)
                except asyncio.TimeoutError:
                    pass
        finally:
            state.job_store.unsubscribe_from_logs(job_id, notify)

    return StreamingResponse(log_generator(), media_type="text/event-stream")

@app.get("/api/artifacts", response_model=List[Artifact], dependencies=[Depends(verify_token)])
def list_artifacts(repo: Optional[str] = None):
    arts = state.job_store.get_all_artifacts()
    if repo:
        arts = [a for a in arts if repo in a.repos]
    return arts

@app.get("/api/artifacts/latest", dependencies=[Depends(verify_token)])
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

@app.get("/api/artifacts/{id}", dependencies=[Depends(verify_token)])
def get_artifact(id: str):
    art = state.job_store.get_artifact(id)
    if not art:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return art



# ---------------------------------------------------------------------------
# Runtime artifact metadata helpers (shared by artifact_lookup / trace_lookup /
# context_lookup).  Keeping the field tuple and copy helper in one place means
# all three endpoints update automatically when the metadata schema changes.
# ---------------------------------------------------------------------------

_RUNTIME_META_FIELDS = (
    "authority",
    "canonicality",
    "artifact_shape",
    "retention_policy",
    "lifecycle_status",
    "expires_at",
    "claim_boundaries",
)


def _copy_runtime_metadata(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Return a dict containing only the runtime metadata fields present in *entry*."""
    return {field: entry[field] for field in _RUNTIME_META_FIELDS if field in entry}


@app.post("/api/artifact_lookup", dependencies=[Depends(verify_token)])
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

@app.post("/api/trace_lookup", dependencies=[Depends(verify_token)])
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


@app.post("/api/context_lookup", dependencies=[Depends(verify_token)])
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


@app.get("/api/artifacts/{id}/download", dependencies=[Depends(verify_token)])
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

# Atlas API

class ResolvedAtlasRoot(BaseModel):
    scan_root: Path
    root_kind: str
    is_internal_abs_path: bool

def resolve_atlas_root(request: AtlasRequest, hub_dir: Path, merges_dir: Optional[Path]) -> ResolvedAtlasRoot:
    """
    Central resolver for Atlas roots.
    Translates the formalized root model (preset | token | abs_path) into a safe, absolute Path.
    """
    # Canonical model enforces explicit root_kind, root_value, and root_token.
    # Deprecated legacy fields (root, root_id) are ignored here entirely.
    root_kind = request.root_kind
    root_value = request.root_value

    if root_kind == "token":
        if not request.root_token:
            raise HTTPException(status_code=400, detail="root_token is required when root_kind='token'")
        trusted = resolve_fs_path(hub=hub_dir, merges_dir=merges_dir, token=request.root_token)
        return ResolvedAtlasRoot(scan_root=trusted.path, root_kind="token", is_internal_abs_path=False)

    elif root_kind == "preset":
        preset = root_value
        if not preset:
            raise HTTPException(status_code=400, detail="root_value is required when root_kind='preset'")
        if preset not in ("hub", "merges", "system"):
            raise HTTPException(status_code=400, detail=f"Invalid preset: {preset}")

        trusted = resolve_fs_path(hub=hub_dir, merges_dir=merges_dir, root_id=preset, rel_path="")
        return ResolvedAtlasRoot(scan_root=trusted.path, root_kind="preset", is_internal_abs_path=False)

    elif root_kind == "abs_path":
        abs_path_str = root_value
        if not abs_path_str:
            raise HTTPException(status_code=400, detail="root_value is required when root_kind='abs_path'")

        try:
            if "\x00" in abs_path_str:
                raise ValueError("Invalid characters in path")

            raw_path = os.path.expanduser(abs_path_str)
            p = Path(raw_path)

            if any(part == ".." for part in p.parts):
                raise ValueError("Path traversal not allowed")

            # Must be an absolute path
            # We don't want to enforce Posix-only strictly if running on Windows,
            # but we want to ensure it's structurally absolute via Path logic.
            if not p.is_absolute():
                raise ValueError("Path must be absolute")

            # Return the validated absolute path directly.
            # We explicitly avoid p.resolve() here to maintain the exact user input structure,
            # avoiding unnecessary symlink expansions that alter semantic intent.
            return ResolvedAtlasRoot(scan_root=p, root_kind="abs_path", is_internal_abs_path=True)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Invalid absolute path: {e}")
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid absolute path for root_kind='abs_path'")

    else:
        raise HTTPException(status_code=400, detail=f"Invalid root_kind: {root_kind}")

@app.post("/api/atlas", response_model=AtlasArtifact, dependencies=[Depends(verify_token)])
async def create_atlas(request: AtlasRequest, background_tasks: BackgroundTasks):
    # Determine root to scan
    hub = state.hub
    if not hub:
        raise HTTPException(status_code=400, detail="Hub not configured")

    # Validation
    if request.max_file_size is not None and request.max_file_size <= 0:
        raise HTTPException(status_code=400, detail="max_file_size must be a positive integer or null.")

    # Defaults for effective params
    effective_max_depth = request.max_depth
    effective_max_entries = request.max_entries
    effective_excludes = (request.exclude_globs or []).copy()

    # Resolve scan root using the new central resolver
    try:
        resolved = resolve_atlas_root(request, hub, state.merges_dir)
        scan_root = resolved.scan_root

        # System Guardrails
        if resolved.root_kind == "preset" and request.root_value == "system":
            # Enforce safer defaults (Depth/Limit)
            if effective_max_depth > 6:
                effective_max_depth = 6

            if effective_max_entries > 200000:
                effective_max_entries = 200000

            # Enforce strict excludes for system root
            # Includes Linux/Pop!_OS standard paths + generic secrets
            hard_excludes = [
                "**/.ssh/**", "**/.gnupg/**", "**/.password-store/**",
                "**/.aws/**", "**/.kube/**",
                "**/.mozilla/**", "**/.config/google-chrome/**", "**/.config/chromium/**",
                "**/.local/share/keyrings/**",
                "**/Keychain/**", "**/Safari/**"
            ]

            for ex in hard_excludes:
                if ex not in effective_excludes:
                    effective_excludes.append(ex)

    except HTTPException as e:
         raise e

    # Generate ID
    scan_id = f"atlas-{int(time.time())}"

    # Define output paths
    merges_dir = state.merges_dir or get_merges_dir(hub)
    if not merges_dir.exists():
        merges_dir.mkdir(parents=True, exist_ok=True)

    json_filename = f"{scan_id}.json"

    # Get planned outputs
    planned_outputs = plan_atlas_outputs(request.scan_mode, scan_id)

    # Write initial "running" state
    initial_state = {
        "status": "running",
        "root": str(scan_root),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "effective": {
            "max_depth": effective_max_depth,
            "max_entries": effective_max_entries,
            "exclude_globs": effective_excludes
        },
        "stats": {}
    }
    _write_json_atomic(merges_dir / json_filename, initial_state)

    # JSON artifact file is canonical for API lifecycle — helpers to read
    # and write its status field so run_scan_lifecycle can operate on it.
    json_path = merges_dir / json_filename

    def _mark_api_failed(error_msg: str) -> None:
        _mark_api_artifact_failed(json_path, initial_state, error_msg)

    def _is_api_still_running() -> bool:
        try:
            with open(json_path, "r", encoding="utf-8") as fh:
                return json.load(fh).get("status") == "running"
        except Exception:
            return False

    # Helper to run scan and save
    def run_scan_and_save():
        def _do_scan():
            inventory_path = None
            if "inventory" in planned_outputs:
                inventory_path = merges_dir / planned_outputs["inventory"]

            dirs_inventory_path = None
            if "dirs" in planned_outputs:
                dirs_inventory_path = merges_dir / planned_outputs["dirs"]

            scanner = AtlasScanner(
                root=scan_root,
                max_depth=effective_max_depth,
                max_entries=effective_max_entries,
                exclude_globs=effective_excludes,
                inventory_strict=request.inventory_strict,
                no_default_excludes=request.no_default_excludes,
                max_file_size=request.max_file_size,
                snapshot_id=f"snap_api_{int(time.time())}", # Temporary dummy ID until service adopts full registry logic
                enable_content_stats=(request.scan_mode == "content")
            )

            # Mutable progress template — stats field is replaced on each
            # callback invocation.  Only the static envelope (status, root,
            # created_at, effective) is reused across calls.
            progress_template = {
                "status": initial_state["status"],
                "root": initial_state.get("root", ""),
                "created_at": initial_state["created_at"],
                "effective": initial_state.get("effective"),
                "stats": {}
            }

            def _api_progress(files: int, dirs: int, bytes_total: int):
                progress_template["stats"] = {
                    "files_seen": files,
                    "dirs_seen": dirs,
                    "bytes_seen": bytes_total,
                    "last_progress_at": datetime.now(timezone.utc).isoformat()
                }
                try:
                    _write_json_atomic(json_path, progress_template)
                except Exception:
                    pass  # never let progress IO abort the scan

            result = scanner.scan(inventory_file=inventory_path, dirs_inventory_file=dirs_inventory_path, on_progress=_api_progress)

            # Merge with initial state to preserve required fields, then update status
            result["status"] = "complete"
            result["created_at"] = initial_state["created_at"]
            result["effective"] = initial_state["effective"]

            # Additional structural JSONs for new modes
            write_mode_outputs(planned_outputs, result, merges_dir)

            # JSON artifact is canonical for API lifecycle — mark complete here.
            _write_json_atomic(json_path, result)

            # Render and Save MD (Summary)
            md_content = render_atlas_md(result)
            summary_path = merges_dir / planned_outputs["summary"]
            with open(summary_path, "w", encoding="utf-8") as f:
                f.write(md_content)

            logger.info("Atlas scan completed: %s", scan_id)

        run_scan_lifecycle(
            scan_fn=_do_scan,
            mark_failed=_mark_api_failed,
            is_still_running=_is_api_still_running,
            label=f"api-scan:{scan_id}",
        )

    background_tasks.add_task(run_scan_and_save)

    # Build paths dict using planned outputs, plus internal json
    paths = {"json": json_filename}
    # For backward-compatibility mapped keys, and new keys
    for k, v in planned_outputs.items():
        if k == "summary":
            paths["md"] = v
        elif k == "dirs":
            paths["dirs_inventory"] = v
        else:
            paths[k] = v

    return AtlasArtifact(
        id=scan_id,
        status="running",
        created_at=initial_state["created_at"],
        hub=str(hub),
        root_scanned=str(scan_root),
        paths=paths,
        stats={}, # Empty initially
        effective=AtlasEffective(
            max_depth=effective_max_depth,
            max_entries=effective_max_entries,
            exclude_globs=effective_excludes
        )
    )

@app.post("/api/sync/metarepo", dependencies=[Depends(verify_token)])
def api_sync_metarepo(payload: Dict[str, Any]):
    """
    Trigger a metarepo synchronization (Manifest -> Fleet).
    Payload: { "mode": "dry_run"|"apply", "targets": ["wgx", "ci", ...] }
    """
    mode = payload.get("mode", "dry_run")
    if mode not in ("dry_run", "apply"):
        raise HTTPException(status_code=400, detail="Invalid mode. Must be 'dry_run' or 'apply'.")

    targets = payload.get("targets")
    if targets is not None and not isinstance(targets, list):
        raise HTTPException(status_code=400, detail="Targets must be a list of strings.")

    hub_path = state.hub
    if not hub_path:
        raise HTTPException(status_code=400, detail="Hub not configured")

    try:
        report = sync_from_metarepo(hub_path=hub_path, mode=mode, targets=targets)

        # IMPORTANT: do not return HTTP 200 for failed sync runs.
        # sync_from_metarepo must return {"status": "ok"|"error", ...}
        status = report.get("status")
        if status and status != "ok":
            msg = report.get("message") or report.get("error") or "Sync failed"
            # Treat as server-side failure of the sync feature contract.
            raise HTTPException(status_code=500, detail=msg)

        # Backward-compat: older error payloads used {"error": "..."} without status
        if "error" in report and report.get("error"):
            raise HTTPException(status_code=500, detail=str(report["error"]))

        return report
    except HTTPException:
        # Preserve explicit HTTP failures
        raise
    except Exception as e:
        logger.exception("Sync failed")
        raise HTTPException(status_code=500, detail=str(e))

def _normalize_atlas_status(raw: str) -> str:
    """Normalize legacy status values to the canonical vocabulary.

    Older artifacts may contain ``"completed"`` instead of ``"complete"``.
    This function maps known legacy synonyms so that API consumers always
    see the canonical set: ``running | complete | failed``.
    """
    if raw == "completed":
        return "complete"
    return raw


def _read_atlas_artifact_json(path: Path) -> dict:
    """Read an atlas artifact JSON file and normalize its status field.

    Returns a dict with ``status`` mapped through :func:`_normalize_atlas_status`
    and a default of ``"complete"`` when the key is absent.  Returns an empty
    dict if the file does not contain a JSON object (callers use ``.get()``
    with defaults for all field accesses).
    Raises on IO/JSON errors — callers are expected to handle exceptions.
    """
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        return {}
    data["status"] = _normalize_atlas_status(data.get("status", "complete"))
    return data


def _mark_api_artifact_failed(json_path: Path, initial_state: dict, error_msg: str) -> None:
    """Mark an API-managed atlas artifact as *failed*, preserving progress data.

    Best-effort: loads the current artifact state so that progress counters
    (``files_seen``, ``dirs_seen``, ``bytes_seen``, ``last_progress_at``) survive
    the failure transition.  Falls back to *initial_state* if the file is
    unreadable (e.g. disk full before first write).
    """
    current = None
    try:
        with open(json_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
            if isinstance(data, dict):
                current = data
    except Exception:
        logger.warning(
            "_mark_api_artifact_failed: could not read current artifact state "
            "from %s; falling back to initial_state", json_path,
        )
    base = current if current else initial_state.copy()
    base["status"] = "failed"
    base["error"] = error_msg
    _write_json_atomic(json_path, base)

@app.get("/api/atlas", response_model=List[AtlasArtifact], dependencies=[Depends(verify_token)])
def list_atlas():
    merges_dir = state.merges_dir
    if not merges_dir and state.hub:
        merges_dir = get_merges_dir(state.hub)

    if not merges_dir or not merges_dir.exists():
        return []

    # Find atlas files
    # Pattern: atlas-{timestamp}.json
    files = list(merges_dir.glob("atlas-*.json"))

    # Sort by name (timestamp) desc
    files = sorted(files, key=lambda f: f.name, reverse=True)

    artifacts = []
    for file in files:
        data = {}
        error_msg = None
        try:
            data = _read_atlas_artifact_json(file)
            stats = data.get("stats", {})
            scan_root = data.get("root", "?")
            status = data.get("status", "complete")
            effective = data.get("effective", None)
            if effective:
                effective = AtlasEffective(**effective)
            error_msg = data.get("error")
        except Exception:
            logger.warning("Failed to read/parse atlas artifact: %s", file.name)
            stats = {}
            scan_root = "?"
            status = "failed"
            effective = None
            error_msg = "Unreadable artifact JSON"

        scan_id = file.stem # atlas-123456

        # Construct paths
        paths = {"json": file.name}

        possible_suffixes = {
            "md": ".summary.md",
            "inventory": ".inventory.jsonl",
            "dirs_inventory": ".dirs.jsonl",
            "topology": ".topology.json",
            "content": ".content.json",
            "workspaces": ".workspaces.json",
            "hotspots": ".hotspots.json",
            # Legacy fallbacks
            "md_legacy": ".md",
            "dirs_legacy": ".dirs_inventory.jsonl"
        }

        for key, suffix in possible_suffixes.items():
            candidate = file.with_name(f"{scan_id}{suffix}")
            if candidate.exists():
                mapped_key = "md" if key == "md_legacy" else ("dirs_inventory" if key == "dirs_legacy" else key)
                if mapped_key not in paths:
                    paths[mapped_key] = candidate.name

        created_at = datetime.fromtimestamp(file.stat().st_mtime, timezone.utc).isoformat()
        if "created_at" in data:
            created_at = data["created_at"]

        # Stale detection — is_stalled is a *derived diagnostic flag*, not a
        # status class.  It is computed from last_progress_at (or created_at
        # as fallback) and never persisted.  Threshold: 60 seconds.
        is_stalled = False
        if status == "running":
            last_progress = stats.get("last_progress_at")
            ref_timestamp = last_progress or created_at
            if ref_timestamp:
                try:
                    ts_str = ref_timestamp.replace("Z", "+00:00")
                    ts_dt = datetime.fromisoformat(ts_str)
                    if (datetime.now(timezone.utc) - ts_dt).total_seconds() > 60:
                        is_stalled = True
                except (ValueError, TypeError):
                    pass

        artifacts.append(AtlasArtifact(
            id=scan_id,
            status=status,
            created_at=created_at,
            hub=str(state.hub),
            root_scanned=scan_root,
            paths=paths,
            stats=stats,
            effective=effective,
            error=error_msg,
            is_stalled=is_stalled
        ))

    return artifacts

@app.get("/api/atlas/latest", dependencies=[Depends(verify_token)])
def get_latest_atlas():
    merges_dir = state.merges_dir
    if not merges_dir and state.hub:
        merges_dir = get_merges_dir(state.hub)

    if not merges_dir or not merges_dir.exists():
        raise HTTPException(status_code=404, detail="No atlas artifacts found (no merges dir)")

    # Find atlas files
    # Pattern: atlas-{timestamp}.json
    files = list(merges_dir.glob("atlas-*.json"))
    if not files:
         raise HTTPException(status_code=404, detail="No atlas artifacts found")

    # Sort by name (timestamp) desc
    files = sorted(files, key=lambda f: f.name, reverse=True)

    latest_file = None
    data = {}
    stats = {}
    scan_root = "?"
    status = "complete"
    effective = None

    for file in files:
        try:
            data = _read_atlas_artifact_json(file)
            status = data.get("status", "complete")
            if status == "complete":
                latest_file = file
                stats = data.get("stats", {})
                scan_root = data.get("root", "?")
                effective = data.get("effective", None)
                if effective:
                    effective = AtlasEffective(**effective)
                break
        except Exception:
            continue

    if not latest_file:
        raise HTTPException(status_code=404, detail="No complete atlas artifacts found")

    scan_id = latest_file.stem # atlas-123456

    # Construct paths
    paths = {"json": latest_file.name}

    possible_suffixes = {
        "md": ".summary.md",
        "inventory": ".inventory.jsonl",
        "dirs_inventory": ".dirs.jsonl",
        "topology": ".topology.json",
        "content": ".content.json",
        "workspaces": ".workspaces.json",
        "hotspots": ".hotspots.json",
        # Legacy fallbacks
        "md_legacy": ".md",
        "dirs_legacy": ".dirs_inventory.jsonl"
    }

    for key, suffix in possible_suffixes.items():
        candidate = latest_file.with_name(f"{scan_id}{suffix}")
        if candidate.exists():
            mapped_key = "md" if key == "md_legacy" else ("dirs_inventory" if key == "dirs_legacy" else key)
            if mapped_key not in paths:
                paths[mapped_key] = candidate.name

    created_at = datetime.fromtimestamp(latest_file.stat().st_mtime, timezone.utc).isoformat()
    if "created_at" in data:
        created_at = data["created_at"]

    return AtlasArtifact(
        id=scan_id,
        status="complete",
        created_at=created_at,
        hub=str(state.hub),
        root_scanned=scan_root,
        paths=paths,
        stats=stats,
        effective=effective
    )

@app.get("/api/atlas/{id}/download", dependencies=[Depends(verify_token)])
def download_atlas(id: str, key: str = "md"):
    # Hard allowlist: atlas ids are generated as "atlas-<unix_ts>"
    if not re.fullmatch(r"atlas-\d+", (id or "").strip()):
        raise HTTPException(status_code=400, detail="Invalid atlas id format")

    allowed_keys = ("json", "md", "inventory", "dirs_inventory", "topology", "content", "workspaces", "hotspots")
    if key not in allowed_keys:
        raise HTTPException(status_code=400, detail=f"Invalid key. Use one of {allowed_keys}.")

    if not state.hub:
        raise HTTPException(status_code=400, detail="Hub not configured")

    merges_dir = (state.merges_dir or get_merges_dir(state.hub)).resolve()
    if not merges_dir.exists():
        raise HTTPException(status_code=404, detail="Merges directory not found")

    # IMPORTANT: do NOT build a path from user input.
    # Enumerate allowed files and then select by id.
    candidates = {}

    # Map key to extension, supporting new planner names and legacy fallbacks
    ext_map = {
        "json": [".json"],
        "md": [".summary.md", ".md"],
        "inventory": [".inventory.jsonl"],
        "dirs_inventory": [".dirs.jsonl", ".dirs_inventory.jsonl"],
        "topology": [".topology.json"],
        "content": [".content.json"],
        "workspaces": [".workspaces.json"],
        "hotspots": [".hotspots.json"]
    }
    exts = ext_map[key]

    # Glob pattern needs to match suffix carefully
    for ext in exts:
        for p in merges_dir.glob(f"atlas-*{ext}"):
            try:
                rp = p.resolve()
                rp.relative_to(merges_dir)  # containment even under symlinks
            except Exception:
                continue

            # Robust ID matching:
            if p.name.startswith(id + "."):
                 # if multiple extensions match, the first one found wins
                 if id not in candidates:
                     candidates[id] = rp

    file_path = candidates.get(id)
    if not file_path:
        raise HTTPException(status_code=404, detail="File not found")

    # Unified file serving with security checks
    try:
        # Use relative_to on resolved paths for maximum robustness even if file_path came from glob()
        rel_path = file_path.resolve().relative_to(merges_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied")

    return _serve_file(merges_dir, rel_path)

@app.post("/api/export/webmaschine", dependencies=[Depends(verify_token)])
def export_webmaschine():
    """
    Prepares an export directory for 'webmaschine'.
    """
    hub = state.hub
    if not hub:
        raise HTTPException(status_code=400, detail="Hub not configured")

    # User said: "Erzeugt Verzeichnis exports/webmaschine/"
    # Where? Usually relative to where repolens is running or the repo root?
    # Or inside the Hub? "hub/exports"?
    # "innerhalb des Repos" context suggests inside the tooling repo?
    # But repolensd runs on the user's machine on a "Hub".
    # Let's put it in `merges_dir/../exports/webmaschine` to be near output?
    # Or just `hub/exports`?
    # Let's try `hub/exports/webmaschine` if hub is writable.

    target_dir = hub / "exports" / "webmaschine"

    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / "atlas").mkdir(exist_ok=True)
        (target_dir / "repos").mkdir(exist_ok=True)

        # 1. Copy latest Atlas
        # Reuse get_latest_atlas logic
        try:
            latest = get_latest_atlas()
            merges_dir = state.merges_dir or get_merges_dir(hub)

            import shutil
            shutil.copy2(merges_dir / latest.paths["json"], target_dir / "atlas" / "latest.json")
            shutil.copy2(merges_dir / latest.paths["md"], target_dir / "atlas" / "latest.md")
        except HTTPException:
            logger.warning("No atlas found to export")

        # 2. Export Repos Index
        # We can just dump _find_repos result
        from .runner import _find_repos
        repos = _find_repos(hub)
        with open(target_dir / "repos" / "index.json", "w", encoding="utf-8") as f:
            json.dump(repos, f, indent=2)

        # 3. Machine Definition (machine.json)
        machine_roots = []
        try:
            # Check if system is allowed/resolved (maps to Home)
            sys_root = Path.home().resolve()
            sec = get_security_config()
            sec.validate_path(sys_root)
            machine_roots.append(str(sys_root))
        except Exception as e:
            logger.debug("System root not available for export: %s", e, exc_info=True)

        machine_def = {
            "hub": str(hub.resolve()),
            "roots": machine_roots
        }

        with open(target_dir / "machine.json", "w", encoding="utf-8") as f:
            json.dump(machine_def, f, indent=2)

        # 4. README
        readme_content = """# Webmaschine Export

This directory contains the latest atlas and repository index from RepoLens.

## Update
Run `POST /api/export/webmaschine` to update these files.
"""
        with open(target_dir / "README.md", "w", encoding="utf-8") as f:
            f.write(readme_content)

        return {"status": "ok", "path": str(target_dir)}

    except Exception as e:
        logger.exception("Export failed")
        raise HTTPException(status_code=500, detail=f"Export failed: {e}")

# Serve static UI with Templating
# app.py is in lenskit/service. webui is in lenskit/frontends/webui.
current_dir = Path(__file__).parent
webui_dir = current_dir.parent / "frontends" / "webui"

# Pre-load raw template
_raw_index_template = None

def get_raw_index_template():
    global _raw_index_template
    if _raw_index_template is None:
        index_path = webui_dir / "index.html"
        if index_path.exists():
            content = index_path.read_text(encoding="utf-8")
            # Inject Build ID (Static per process)
            content = content.replace("__RLENS_BUILD__", BUILD_ID)
            _raw_index_template = content
        else:
            _raw_index_template = ""
    return _raw_index_template


@app.get("/ui", include_in_schema=False)
def ui_redirect(request: Request):
    # Dynamic redirect to a valid entry point
    # We redirect to /ui/ which is handled by serve_ui_index
    # and keeps the user under the /ui path segment (better for proxies)
    root_path = request.scope.get("root_path", "").rstrip("/")
    return RedirectResponse(url=f"{root_path}/ui/")

@app.get("/ui/", response_class=HTMLResponse, include_in_schema=False)
def serve_ui_index(request: Request):
    return serve_index(request)

@app.get("/", response_class=HTMLResponse)
@app.get("/index.html", response_class=HTMLResponse)
def serve_index(request: Request):
    content = get_raw_index_template()
    if not content:
         return HTMLResponse("<h1>rLens UI not found</h1>", status_code=404)

    # Dynamic Asset Base calculation
    # e.g. /prefix or ""
    root_path = request.scope.get("root_path", "").rstrip("/")

    # Asset base should point to where StaticFiles are mounted.
    # We mount at /ui. So base is {root_path}/ui/
    asset_base = f"{root_path}/ui/"

    final_content = content.replace("__RLENS_ASSET_BASE__", asset_base)

    headers = {
        "Cache-Control": "no-store, max-age=0",
        "Pragma": "no-cache",
        "Expires": "0"
    }
    return HTMLResponse(final_content, headers=headers)

if webui_dir.exists():
    # Mount assets at /ui.
    # Note: explicit route @app.get("/ui/") defined above takes precedence
    # for exactly "/ui/", allowing us to serve the templated index there.
    # StaticFiles handles /ui/style.css, etc.
    app.mount("/ui", StaticFiles(directory=str(webui_dir), html=False), name="webui")
