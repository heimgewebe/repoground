from fastapi import FastAPI, HTTPException, Depends, Body, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional, Dict, Any
from pathlib import Path
import os
import json
import time
import shutil
import subprocess
import ipaddress
import logging
import re
import uuid
from datetime import datetime, timezone

from .models import PrescanRequest, PrescanResponse, FSRoot, FSRootsResponse
from .jobstore import JobStore
from .query_artifact_store import QueryArtifactStore
from .runner import JobRunner
from .logging_provider import LogProvider, FileLogProvider
from .auth import verify_token
from .access_log import SafeAccessLogMiddleware
from ..adapters.security import (
    get_security_config,
    validate_hub_path,
    validate_repo_name,
    InvalidPathError,
    AccessDeniedError,
)
from ..adapters.filesystem import resolve_fs_path, list_allowed_roots, issue_fs_token
from ..adapters.atlas import AtlasScanner, render_atlas_md  # noqa: F401 - router compatibility exports
from ..adapters.metarepo import sync_from_metarepo
from ..adapters import sources as sources_refresh
from ..adapters import diagnostics as diagnostics_rebuild

from merger.repoground.core.merge import get_merges_dir, SPEC_VERSION, prescan_repo
from merger.repoground import __version__ as PRODUCT_VERSION  # noqa: F401 - router compatibility export

# Global Version Info
SERVER_START_TIME = datetime.now(timezone.utc).isoformat()

# Logging setup
logger = logging.getLogger(__name__)

def _get_server_version():
    # 1. Env Var (Canonical for builds)
    env_ver = os.getenv("REPOGROUND_VERSION")
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

# Unambiguous aliases for the version identities exposed over the API.
#
# - PRODUCT_VERSION: the RepoGround release/product version (semver, e.g. "3.0.0"),
#   sourced from merger.repoground.__version__ / RELEASE_VERSION.
# - CONTRACT_VERSION: the report/merge contract (spec) version (e.g. "2.4"), sourced
#   from merger.repoground.core.merge.SPEC_VERSION. This is unrelated to the product
#   release version and only changes when the report/contract shape changes.
# - BUILD_COMMIT: the build/server identity (env override or short git commit hash,
#   "dev" otherwise), sourced from SERVER_VERSION above.
CONTRACT_VERSION = SPEC_VERSION
BUILD_COMMIT = SERVER_VERSION

# Build ID for cache busting
# If REPOGROUND_BUILD_ID is set, use it (stable per build).
# Else fall back to SERVER_VERSION (if git hash).
# If dev/unknown, append timestamp to force reload on restarts.
_env_build_id = os.getenv("REPOGROUND_BUILD_ID")
if _env_build_id:
    BUILD_ID = _env_build_id
elif SERVER_VERSION != "dev":
    BUILD_ID = SERVER_VERSION
else:
    BUILD_ID = f"dev-{int(time.time())}"

ACTIVE_JOB_STATUSES = {"queued", "running", "canceling"}
SERVICE_UNIT_NAME_RE = re.compile(r"^[A-Za-z0-9_.@-]+$")


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
        "[system] Job marked failed on service startup because RepoGround does not "
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


def _count_active_jobs() -> int:
    if not state.job_store:
        return 0
    return sum(1 for job in state.job_store.get_all_jobs() if job.status in ACTIVE_JOB_STATUSES)


def _service_restart_feature_flag_enabled() -> bool:
    return os.getenv("REPOGROUND_ENABLE_SERVICE_RESTART") == "1"


def _service_restart_unit() -> Optional[str]:
    raw = (os.getenv("REPOGROUND_SERVICE_UNIT") or "repoground").strip()
    if not raw:
        return None
    if not SERVICE_UNIT_NAME_RE.fullmatch(raw):
        logger.warning("Refusing invalid REPOGROUND_SERVICE_UNIT=%r", raw)
        return None
    if raw != "repoground":
        logger.warning("Refusing non-canonical REPOGROUND_SERVICE_UNIT=%r", raw)
        return None
    return raw


def _service_restart_trusted_local_admin() -> bool:
    return _is_loopback_host(getattr(state, "host", "")) and bool(get_security_config().token)


def _service_restart_enabled_for_request() -> bool:
    return (
        _service_restart_feature_flag_enabled()
        and _service_restart_trusted_local_admin()
        and _service_restart_unit() is not None
    )


def _schedule_service_restart(unit: str) -> None:
    systemd_run = shutil.which("systemd-run")
    if systemd_run is None:
        raise RuntimeError("systemd-run is not available")

    command = [
        systemd_run,
        "--user",
        "--on-active=1s",
        "systemctl",
        "--user",
        "restart",
        unit,
    ]
    try:
        subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("systemd-run timed out") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip() or "systemd-run failed"
        raise RuntimeError(detail) from exc

app = FastAPI(title="RepoGround", version=SERVER_VERSION)
app.add_middleware(SafeAccessLogMiddleware)

@app.exception_handler(InvalidPathError)
async def invalid_path_handler(request: Request, exc: InvalidPathError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})

@app.exception_handler(AccessDeniedError)
async def access_denied_handler(request: Request, exc: AccessDeniedError):
    return JSONResponse(status_code=403, content={"detail": str(exc)})

# GC Configuration
GC_MAX_JOBS = int(os.getenv("REPOGROUND_GC_MAX_JOBS", "100"))
GC_MAX_AGE_HOURS = int(os.getenv("REPOGROUND_GC_MAX_AGE_HOURS", "24"))
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
    host: str = "127.0.0.1"

state = ServiceState()

def init_service(hub_path: Path, token: Optional[str] = None, host: str = "127.0.0.1", merges_dir: Optional[Path] = None):
    state.hub = hub_path
    state.merges_dir = merges_dir
    state.host = host
    state.job_store = JobStore(hub_path)
    reconciled_jobs = _mark_persisted_active_jobs_terminal(state.job_store)
    if reconciled_jobs:
        logger.info("Reconciled %s persisted active job(s) on startup.", reconciled_jobs)
    # Co-locate QueryArtifactStore with the effective merges dir so query artifacts
    # land alongside the outputs they reference.  JobStore uses hub_path/merges
    # unconditionally; QueryArtifactStore follows state.merges_dir when set.
    _effective_merges = merges_dir if merges_dir else get_merges_dir(hub_path)
    state.query_artifact_store = QueryArtifactStore(_effective_merges / ".repoground-service")
    state.runner = JobRunner(state.job_store)
    state.log_provider = FileLogProvider(state.job_store)

    # Configure Security from scratch. init_service may be called repeatedly
    # in one process (tests, embedded use, controlled reconfiguration); roots
    # from an earlier configuration must not remain authorized.
    sec = get_security_config()
    sec.allowlist_roots.clear()
    sec.set_token(token)
    sec.set_sensitive_fs_access(False)

    # Allowlist the Hub
    sec.add_allowlist_root(hub_path)
    # Allowlist Merges Dir if separate
    if merges_dir:
        sec.add_allowlist_root(merges_dir)

    # Sensitive filesystem access is available only on loopback with the
    # bearer token that verify_token actually enforces. Loopback alone is not
    # an authorization boundary: other local processes or users can connect.
    # REPOGROUND_FS_TOKEN_SECRET signs navigation tokens but is not request auth.
    is_loopback = _is_loopback_host(host)
    has_token = bool(sec.token)

    if is_loopback and has_token:
        try:
            root = Path("/").resolve()
            sec.add_allowlist_root(root)
        except (OSError, RuntimeError, ValueError) as exc:
            raise RuntimeError(
                "Authenticated filesystem-root access could not be initialized"
            ) from exc

        home_root: Optional[Path] = None
        try:
            home_root = Path.home().resolve()
            sec.add_allowlist_root(home_root)
        except (OSError, RuntimeError, ValueError) as exc:
            home_root = None
            logger.warning(
                "Home preset unavailable; authenticated filesystem-root browsing remains enabled (%s).",
                type(exc).__name__,
            )

        sec.set_sensitive_fs_access(True, home_preset_root=home_root)
        if home_root is None:
            logger.warning(
                "Sensitive filesystem browsing enabled (root only; loopback + auth)."
            )
        else:
            logger.warning(
                "Sensitive filesystem browsing enabled (home + root; loopback + auth)."
            )
    else:
        logger.warning(
            "Sensitive filesystem browsing refused (home + root; loopback=%s, has_token=%s).",
            is_loopback,
            has_token,
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
            allow_headers=["Authorization", "Content-Type"],
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


@app.get("/api/admin/capabilities", dependencies=[Depends(verify_token)])
def admin_capabilities():
    return {
        "service_restart_enabled": _service_restart_enabled_for_request(),
    }


@app.post("/api/admin/restart", dependencies=[Depends(verify_token)])
def api_admin_restart():
    if not _service_restart_enabled_for_request():
        raise HTTPException(status_code=403, detail="Service restart is disabled")

    active_jobs = _count_active_jobs()
    if active_jobs:
        return JSONResponse(
            status_code=409,
            content={
                "status": "blocked",
                "reason": "jobs_running",
                "running_jobs": active_jobs,
            },
        )

    unit = _service_restart_unit()
    if unit is None:
        raise HTTPException(status_code=403, detail="Service restart is disabled")

    try:
        _schedule_service_restart(unit)
    except RuntimeError as exc:
        logger.warning("Failed to schedule RepoGround service restart for %s: %s", unit, exc)
        return JSONResponse(
            status_code=503,
            content={
                "status": "error",
                "reason": "scheduler_failed",
            },
        )

    return JSONResponse(
        status_code=202,
        content={
            "status": "scheduled",
            "unit": unit,
            "message": "RepoGround restart scheduled",
        },
    )

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
    repo_root = _resolve_request_path(state.hub, repo_name, label="repository")
    if not repo_root.exists() or not repo_root.is_dir():  # lgtm[py/path-injection] codeql-boundary:service-api-root-bounded-files
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
    except Exception as exc:
        logger.exception("Prescan failed: %s", type(exc).__name__)
        raise HTTPException(status_code=500, detail="Prescan failed") from exc


# Domain routers. The provider resolves this module lazily so historical
# test and embedding hooks that replace app-level collaborators keep working.
import sys

from .artifact_router import build_router as build_artifact_router
from .atlas_router import build_router as build_atlas_router
from .health_router import build_router as build_health_router
from .job_router import build_router as build_job_router
from .query_router import build_router as build_query_router
from .path_helpers import is_safe_filename as _is_safe_filename, resolve_request_path as _resolve_request_path


def _service_app_provider():
    return sys.modules[__name__]


(health_router, api_version, health) = build_health_router(_service_app_provider)
(
    query_router,
    _extract_projected_context_bundle,
    api_federation_query,
    api_query,
) = build_query_router(_service_app_provider)
(
    job_router,
    _cleanup_source_snapshots_after_gc,
    create_job,
    get_jobs,
    get_job,
    cancel_job,
    stream_logs,
) = build_job_router(_service_app_provider)
(
    artifact_router,
    list_artifacts,
    get_latest_artifact,
    get_artifact,
    _copy_runtime_metadata,
    api_artifact_lookup,
    api_trace_lookup,
    api_context_lookup,
    _serve_file,
    download_artifact,
) = build_artifact_router(_service_app_provider)
(
    atlas_router,
    ResolvedAtlasRoot,
    resolve_atlas_root,
    create_atlas,
    api_sync_metarepo,
    _normalize_atlas_status,
    _atlas_primary_artifact_files,
    _read_atlas_artifact_json,
    _mark_api_artifact_failed,
    list_atlas,
    get_latest_atlas,
    download_atlas,
    export_webmaschine,
) = build_atlas_router(_service_app_provider, serve_file=_serve_file)

for _domain_router in (health_router, query_router, job_router, artifact_router, atlas_router):
    app.include_router(_domain_router)

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
            content = content.replace("__REPOGROUND_BUILD__", BUILD_ID)
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
        return HTMLResponse("<h1>RepoGround UI not found</h1>", status_code=404)

    # Dynamic Asset Base calculation
    # e.g. /prefix or ""
    root_path = request.scope.get("root_path", "").rstrip("/")

    # Asset base should point to where StaticFiles are mounted.
    # We mount at /ui. So base is {root_path}/ui/
    asset_base = f"{root_path}/ui/"

    final_content = content.replace("__REPOGROUND_ASSET_BASE__", asset_base)

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
