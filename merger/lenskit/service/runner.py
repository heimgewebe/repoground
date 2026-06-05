import concurrent.futures
import sys
import os
import uuid
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import List

from .models import Artifact
from .jobstore import JobStore
from .repo_sync import (
    plan_pre_pull_repos,
    apply_pre_pull_plans,
    is_self_repo,
    PrePullStatus,
    HARD_FAIL_STATUSES,
    WARN_STATUSES,
)
from ..adapters.security import validate_source_dir, get_security_config, SecurityViolationError

logger = logging.getLogger(__name__)

# Import core logic.
# Since this file is in merger/repoLens/service/runner.py,
# and merger/repoLens is usually in sys.path when running repolens.py.
# We can try absolute import first.

from ..core.merge import (
    get_merges_dir,
    scan_repo,
    write_reports_v2,
    _normalize_ext_list,
    ExtrasConfig,
    SKIP_ROOTS,
    MERGES_DIR_NAME,
    parse_human_size,
)

def _find_repos(hub: Path) -> List[str]:
    from ..adapters.security import validate_source_dir
    hub = validate_source_dir(hub)
    repos = []
    if not hub.exists():
        return []
    for child in sorted(hub.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_dir():
            continue
        if child.name in SKIP_ROOTS:
            continue
        if child.name == MERGES_DIR_NAME:
            continue
        if child.name.startswith("."):
            continue
        repos.append(child.name)
    return repos

def _diagnostic_norm_repo_key(s: str) -> str:
    """
    Robust normalization for diagnostic logging only.
    Removes leading './', trailing '/', converts backslashes, lowercases.
    """
    s = s.strip().lower().replace("\\", "/")
    # Remove leading './'
    while s.startswith("./"):
        s = s[2:]
    # Remove leading '/' just in case (e.g. .//repo -> /repo) - wait, .// -> / after replace ./
    # Logic: s.startswith("./") handles "./repo" -> "repo".
    # But ".//repo" -> "/repo" after one pass? No.
    # .//repo -> startswith ./ ? YES. s[2:] -> /repo.
    # /repo does NOT start with ./.
    # So we should also strip leading slashes if we want pure key normalization?
    # The requirement was "robust". Let's strip leading slashes too.
    s = s.lstrip("/")

    # Finally, if s is just ".", return empty.
    if s == ".":
        return ""

    return s.rstrip("/")

def _parse_extras_csv(extras_csv: str) -> ExtrasConfig:
    config = ExtrasConfig()
    items = [x.strip().lower() for x in (extras_csv or "").split(",") if x.strip()]
    for item in items:
        if item == "ai_heatmap":
            print("[Warning] Deprecated: 'ai_heatmap' is now 'heatmap'. Please update your config.", file=sys.stderr)
            item = "heatmap"
        if hasattr(config, item):
            setattr(config, item, True)
    return config

ARTIFACT_PATH_FIELDS = {
    "chunk_index": "chunk_index",
    "dump_index": "dump_index",
    "sqlite_index": "sqlite_index",
    "retrieval_eval": "retrieval_eval",
    "derived_manifest": "derived_manifest",
    "bundle_manifest": "bundle_manifest",
}

class JobRunner:
    def __init__(self, job_store: JobStore, max_workers: int = 1):
        self.job_store = job_store
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
        self.futures = {}

    def submit_job(self, job_id: str) -> None:
        job = self.job_store.get_job(job_id)
        if not job or job.status != "queued":
            return

        future = self.executor.submit(self._run_job, job_id)
        self.futures[job_id] = future

    def _run_job(self, job_id: str) -> None:
        job = self.job_store.get_job(job_id)
        if not job:
            return

        if job.status in ("canceled", "canceling"):
            job.status = "canceled"
            job.finished_at = datetime.now(timezone.utc).isoformat()
            self.job_store.update_job(job)
            return

        # Update status to running
        job.status = "running"
        job.started_at = datetime.now(timezone.utc).isoformat()
        self.job_store.update_job(job)

        def log(msg: str) -> None:
            ts = datetime.now(timezone.utc).strftime("%H:%M:%SZ")
            line = f"[{ts}] {msg}"
            self.job_store.append_log_line(job.id, line)
            # Keep a small in-memory tail for API convenience (optional)
            job.logs.append(line)
            if len(job.logs) > 200:
                job.logs = job.logs[-200:]
            # Save job state less aggressively: only on status changes or every N lines
            # For simplicity, we update job here to keep 'logs' tail sync, but strictly we could skip it.
            # self.job_store.update_job(job)
            # To avoid excessive writes, we DON'T call update_job for every log line anymore.
            pass

        try:
            req = job.request

            # 1. Use resolved Hub from job
            if not job.hub_resolved:
                raise ValueError("Internal: hub_resolved missing on job")
            hub = Path(job.hub_resolved)
            log(f"Using hub: {hub}")

            # 2. Determine Repos
            if req.repos:
                repo_names = req.repos
                log(f"Selected specific repos: {repo_names}")
            else:
                repo_names = _find_repos(hub)
                log(f"Auto-detected all repos: {repo_names}")

            if not repo_names:
                raise ValueError("No repositories found or selected.")

            sources = []
            for name in repo_names:
                p = hub / name
                if p.exists() and p.is_dir():
                    validate_source_dir(p)
                    sources.append(p)
                else:
                    log(f"Warning: Repo {name} not found at {p}")

            if not sources:
                raise ValueError("No valid repository sources found.")

            # 2b. Pre-pull preflight (bounded repo-sync mutation).
            # Runs AFTER source resolution/validation and BEFORE any scan so the
            # dump reflects current upstream state instead of a stale checkout.
            # Intentionally NOT in core/merge.py: merge-core reads repo content and
            # writes artifacts; fast-forwarding a working tree is a local mutation
            # and belongs in service preparation.
            # effective_pre_pull couples the request to plan_only: a plan-only job
            # MUST NOT mutate local repos (no fetch, no merge, no apply).
            # Two-phase (plan all → apply all) guarantees no repo is fast-forwarded
            # when another repo's plan hard-fails. Strictly fast-forward-only
            # (see service/repo_sync.py) — no shell, pull, reset, rebase, stash,
            # checkout, switch or clean.
            effective_pre_pull = req.pre_pull and not req.plan_only
            if effective_pre_pull:
                log("Pre-pull enabled: planning updates for all repositories (fast-forward only)...")
                plans = plan_pre_pull_repos(sources)

                hard_failures = []
                prepull_warned = False
                for plan in plans:
                    log(f"Pre-pull plan {plan.repo}: {plan.status} - {plan.message}")
                    if plan.stderr:
                        # stderr is already credential-redacted by repo_sync.
                        log(f"Pre-pull plan {plan.repo} detail: {plan.stderr.strip()}")
                    if plan.status in WARN_STATUSES:
                        warn = f"Pre-pull {plan.repo}: {plan.status} - {plan.message}"
                        job.warnings.append(warn)
                        prepull_warned = True
                    if plan.status in HARD_FAIL_STATUSES:
                        hard_failures.append(plan)

                if prepull_warned:
                    self.job_store.update_job(job)

                if hard_failures:
                    # Abort BEFORE applying any fast-forward, so no repo is left
                    # partially updated when another repo hard-fails during the plan phase.
                    detail = "; ".join(f"{p.repo}: {p.status} - {p.message}" for p in hard_failures)
                    raise ValueError(
                        f"Pre-pull plan failed (no repo HEADs or working trees were fast-forwarded): {detail}"
                    )

                log("Pre-pull plan OK: applying fast-forwards...")
                results = apply_pre_pull_plans(plans)
                results_warned = False
                for result in results:
                    log(f"Pre-pull apply {result.repo}: {result.status} - {result.message}")
                    if result.stderr:
                        log(f"Pre-pull apply {result.repo} detail: {result.stderr.strip()}")

                    if result.status in HARD_FAIL_STATUSES:
                        raise ValueError(f"Pre-pull apply failed for {result.repo}: {result.status} - {result.message}")

                    # Only an ACTUAL fast-forward of the running code repo warrants a
                    # restart reminder (files changed but the live process keeps old
                    # modules). Never auto-restart — that would kill this very job.
                    if result.status == PrePullStatus.FAST_FORWARDED and is_self_repo(Path(result.path)):
                        restart_warn = (
                            f"WARN pre_pull fast-forwarded the running rLens code repository "
                            f"'{result.repo}'. Restart rlens.service after updating lenskit; a "
                            f"running Python service does not reload modules automatically."
                        )
                        log(restart_warn)
                        job.warnings.append(restart_warn)
                        results_warned = True

                if results_warned:
                    self.job_store.update_job(job)
            elif req.pre_pull and req.plan_only:
                log("Pre-pull skipped because plan_only=True.")
            else:
                log("Pre-pull disabled by request.")

            # 3. Scan Repos
            max_bytes = parse_human_size(req.max_bytes or "0")
            ext_list = _normalize_ext_list(",".join(req.extensions)) if req.extensions else None
            path_filter = req.path_filter
            include_paths = req.include_paths

            summaries = []
            total_sources = len(sources)
            warnings_dirty = False
            for i, src in enumerate(sources, 1):
                # Refresh job status from store to detect external cancel
                current_job = self.job_store.get_job(job_id)
                if current_job and current_job.status in ("canceled", "canceling"):
                    log("Job canceled by user during scan.")
                    current_job.status = "canceled"
                    current_job.finished_at = datetime.now(timezone.utc).isoformat()
                    self.job_store.update_job(current_job)
                    return

                # Defense in depth: validate each src before scanning
                validate_source_dir(src)

                # Determine include_paths for this specific repo
                # Priority: include_paths_by_repo (if key exists) > include_paths (global)
                current_include_paths = include_paths
                if req.include_paths_by_repo is not None:
                    if src.name in req.include_paths_by_repo:
                        current_include_paths = req.include_paths_by_repo[src.name]
                    else:
                        # Key missing
                        # Check strict mode flag
                        if req.strict_include_paths_by_repo:
                            # Strict Mode: Hard Fail

                            # Diagnostic: check if normalization would have helped (before failing)
                            norm_key = _diagnostic_norm_repo_key(src.name)
                            available_norm = [_diagnostic_norm_repo_key(k) for k in req.include_paths_by_repo.keys()]
                            if norm_key in available_norm:
                                log("INFO key would match after normalization (diagnostic only)")

                            err_msg = f"Strict Mode Violation: include_paths_by_repo is active but missing key for repo '{src.name}'. Available: {list(req.include_paths_by_repo.keys())}"
                            log(f"ERROR {err_msg}")
                            raise ValueError(err_msg)
                        else:
                            # Soft Mode: Warn and Fallback to global include_paths (Backward Compatibility)
                            # Only warn if fallback results in FULL SCAN (None) or if explicit request mismatches
                            is_explicit_repo = req.repos and src.name in req.repos

                            if is_explicit_repo or current_include_paths is None:
                                fallback_status = "FULL SCAN" if current_include_paths is None else f"global paths ({len(current_include_paths)} items)"
                                msg = f"WARN include_paths_by_repo has no entry for requested repo '{src.name}'. Fallback: {fallback_status}. (Enable strict_include_paths_by_repo for hard fail)"
                                log(msg)
                                job.warnings.append(msg)
                                warnings_dirty = True

                    # Check for empty list in current_include_paths (which means 'scan nothing' or accident)
                    if current_include_paths is not None and len(current_include_paths) == 0:
                        msg = f"WARN Repo '{src.name}' has empty include paths ([]). This will scan NOTHING (except critical files). If you meant ALL, use null."
                        log(msg)
                        job.warnings.append(msg)
                        warnings_dirty = True

                log(f"Scanning {i}/{total_sources}: {src.name} ...")
                # Note: scan_repo can be slow.
                # Optimization: Skip MD5 for plan_only jobs to reduce scan cost.
                # plan_only is currently the proxy for "no hashes needed" (content/manifest skipped).
                should_hash = not req.plan_only
                summary = scan_repo(src, ext_list, path_filter, max_bytes, include_paths=current_include_paths, calculate_md5=should_hash, include_hidden=req.include_hidden)
                summaries.append(summary)

            if warnings_dirty:
                self.job_store.update_job(job)

            # 4. Write Reports
            log("Generating reports...")
            if req.merges_dir:
                p = Path(req.merges_dir)
                if not p.is_absolute():
                    # Resolve relative paths against HUB to ensure visibility in container environments
                    merges_dir = (hub / p).resolve()
                    log(f"Resolved relative merges_dir '{p}' to '{merges_dir}'")
                else:
                    merges_dir = p.resolve()

                merges_dir.mkdir(parents=True, exist_ok=True)
                # Ensure security/validation for custom merges_dir if needed
                try:
                    # Use the validated, canonical path
                    merges_dir = get_security_config().validate_path(merges_dir)
                    # Update request object so Artifact reflects reality (absolute canonical path)
                    req.merges_dir = str(merges_dir.resolve())
                except SecurityViolationError as e:
                    log(f"Security Warning: merges_dir '{merges_dir}' validation failed: {e}")
                    raise ValueError(f"SECURITY: merges_dir not allowed: {e}")
            else:
                merges_dir = get_merges_dir(hub)

            # Log the effective output directory
            log(f"Writing reports to: {merges_dir.resolve()}")

            # Re-check cancel status before write (expensive operation)
            job = self.job_store.get_job(job_id)
            if job.status in ("canceled", "canceling"):
                log("Job canceled by user before write.")
                job.status = "canceled"
                job.finished_at = datetime.now(timezone.utc).isoformat()
                self.job_store.update_job(job)
                return

            split_size = parse_human_size(req.split_size or "25MB")
            extras = _parse_extras_csv(req.extras)
            if req.json_sidecar:
                extras.json_sidecar = True

            generator_info = {
                "name": "rlens",
                "version": os.getenv("RLENS_VERSION", "dev"),
                "platform": "service"
            }

            artifacts_obj = write_reports_v2(
                merges_dir,
                hub,
                summaries,
                req.level,
                req.mode,
                max_bytes,
                req.plan_only,
                req.code_only,
                split_size,
                debug=False,
                path_filter=path_filter,
                ext_filter=ext_list,
                extras=extras,
                meta_density=req.meta_density,
                output_mode=req.output_mode,
                redact_secrets=req.redact_secrets,
                generator_info=generator_info,
            )

            # 5. Register Artifacts
            out_paths = artifacts_obj.get_all_paths()

            # Verify primary artifact exists (Sanity Check)
            primary_path = artifacts_obj.get_primary_path()
            if primary_path:
                if not primary_path.exists():
                    raise RuntimeError(f"FATAL: Primary artifact '{primary_path}' reported but not found on disk.")
                log(f"Primary Artifact: {primary_path}")

            display_limit = 10
            truncated_paths = [str(p) for p in out_paths[:display_limit]]
            more_count = len(out_paths) - display_limit
            msg = f"Generated {len(out_paths)} files: {truncated_paths}"
            if more_count > 0:
                msg += f" (+{more_count} more)"
            log(msg)

            # Map outputs to Artifact record
            path_map = {}
            if artifacts_obj.index_json:
                path_map["json"] = artifacts_obj.index_json.name

            if artifacts_obj.canonical_md:
                path_map["md"] = artifacts_obj.canonical_md.name

            for attr, key in ARTIFACT_PATH_FIELDS.items():
                value = getattr(artifacts_obj, attr, None)
                if value:
                    path_map[key] = value.name

            for i, p in enumerate(artifacts_obj.md_parts):
                path_map[f"md_part_{i+1}"] = p.name

            if artifacts_obj.other:
                for i, p in enumerate(artifacts_obj.other):
                    path_map[f"other_{i+1}"] = p.name

            artifact_id = str(uuid.uuid4())

            art = Artifact(
                id=artifact_id,
                job_id=job_id,
                hub=str(hub),
                repos=repo_names,
                created_at=datetime.now(timezone.utc).isoformat(),
                paths=path_map,
                params=req,
                merges_dir=str(merges_dir.resolve())
            )

            self.job_store.add_artifact(art)
            job.artifact_ids.append(artifact_id)

            job.status = "succeeded"
            job.finished_at = datetime.now(timezone.utc).isoformat()
            log("Job completed successfully.")
            self.job_store.update_job(job)

        except Exception as e:
            job.status = "failed"
            job.error = str(e)
            job.finished_at = datetime.now(timezone.utc).isoformat()
            log(f"Error: {e}")
            logger.exception("Job %s failed", job_id)
            self.job_store.update_job(job)
