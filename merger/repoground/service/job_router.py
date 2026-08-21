from __future__ import annotations

from collections.abc import Callable
from types import ModuleType
from typing import List, Optional
import asyncio

from fastapi import APIRouter, HTTPException, Query, Request, Depends
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from .auth import verify_token
from .models import (
    Job,
    JobRequest,
    calculate_job_hash,
)
from .source_acquisition import resolve_effective_source_mode
from .router_support import AttributeProxy
from ..adapters.security import validate_hub_path, validate_repo_name
from merger.repoground.core.merge import SPEC_VERSION

router = APIRouter()


def _cleanup_source_snapshots_after_gc() -> None:
    snapshot_cleanup = state.job_store.cleanup_source_snapshots(apply=True)
    if snapshot_cleanup.get("status") == "blocked":
        logger.warning("Source snapshot cleanup blocked: %s", snapshot_cleanup)


def _reuse_succeeded_job(existing: Job, request: JobRequest) -> bool:
    effective_source_mode = resolve_effective_source_mode(request)
    if effective_source_mode == "local_ff":
        logger.info(
            "Not reusing succeeded job %s because local_ff requires a fresh repo-sync check.",
            existing.id,
        )
        return False
    if effective_source_mode == "remote_snapshot":
        logger.info(
            "Not reusing succeeded job %s because remote_snapshot requires fresh remote resolution.",
            existing.id,
        )
        return False
    logger.info("Reusing existing succeeded job %s", existing.id)
    return True

@router.post('/api/jobs', response_model=Job, dependencies=[Depends(verify_token)])
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
    state.job_store.cleanup_jobs(max_jobs=_get_gc_max_jobs(), max_age_hours=_get_gc_max_age_hours())
    _cleanup_source_snapshots_after_gc()

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
        # A succeeded remote_snapshot job is likewise never reused: moving ref
        # names are not content-stable, so the cached result may no longer match
        # the current remote. (See rlens-source-acquisition-blueprint.md.)
        if existing.status == "succeeded" and _reuse_succeeded_job(existing, request):
            return existing

    job = Job.create(request, content_hash=content_hash)
    job.hub_resolved = resolved_hub_str
    state.job_store.add_job(job)
    state.runner.submit_job(job.id)
    return job

@router.get('/api/jobs', response_model=List[Job], dependencies=[Depends(verify_token)])
def get_jobs(status: Optional[str] = None, limit: int = 20):
    jobs = state.job_store.get_all_jobs()
    if status:
        jobs = [j for j in jobs if j.status == status]
    return jobs[:limit]

@router.get('/api/jobs/{job_id}', response_model=Job, dependencies=[Depends(verify_token)])
def get_job(job_id: str):
    job = state.job_store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job

@router.post('/api/jobs/{job_id}/cancel', dependencies=[Depends(verify_token)])
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

@router.get('/api/jobs/{job_id}/logs', dependencies=[Depends(verify_token)], response_model=None)
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
                    await asyncio.wait_for(event.wait(), timeout=_get_sse_idle_recheck_sec())
                except asyncio.TimeoutError:
                    pass
        finally:
            state.job_store.unsubscribe_from_logs(job_id, notify)

    return StreamingResponse(log_generator(), media_type="text/event-stream")


def build_router(app_provider: Callable[[], ModuleType]):
    global state, logger, _get_gc_max_age_hours, _get_gc_max_jobs, _get_sse_idle_recheck_sec
    state = AttributeProxy(app_provider, 'state')
    logger = AttributeProxy(app_provider, 'logger')
    # Resolve GC/SSE knobs on every access so monkeypatches on app remain effective.
    def _attr(name: str):
        def read():
            return getattr(app_provider(), name)
        return read

    _get_gc_max_age_hours = _attr('GC_MAX_AGE_HOURS')
    _get_gc_max_jobs = _attr('GC_MAX_JOBS')
    _get_sse_idle_recheck_sec = _attr('SSE_IDLE_RECHECK_SEC')
    return (
        router,
        _cleanup_source_snapshots_after_gc,
        create_job,
        get_jobs,
        get_job,
        cancel_job,
        stream_logs,
    )
