from __future__ import annotations

from collections.abc import Callable
from types import ModuleType
from typing import Any, Dict, List, Optional
from pathlib import Path
from datetime import datetime, timezone
import json
import os
import re
import time

from fastapi import APIRouter, BackgroundTasks, HTTPException, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .auth import verify_token
from .models import (
    AtlasArtifact,
    AtlasEffective,
    AtlasRequest,
)
from .router_support import AttributeProxy, dynamic_callable
from ..adapters.security import AccessDeniedError, InvalidPathError
from ..adapters.metarepo import sync_from_metarepo
from merger.repoground.atlas.lifecycle import run_scan_lifecycle
from merger.repoground.atlas.planner import plan_atlas_outputs, write_mode_outputs
from merger.repoground.core.merge import get_merges_dir

_ATLAS_PRIMARY_ARTIFACT_RE = re.compile(r"^atlas-[0-9]+[.]json$")

router = APIRouter()


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

        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Invalid absolute path: {e}")
        except (TypeError, OSError):
            raise HTTPException(status_code=400, detail="Invalid absolute path for root_kind='abs_path'")

        # Absolute-path mode is not an authorization bypass. Canonicalize and
        # enforce the same allowlist used by presets and signed navigation
        # tokens. AccessDeniedError intentionally propagates to the 403 handler.
        validated = get_security_config().validate_path(p)
        return ResolvedAtlasRoot(
            scan_root=validated,
            root_kind="abs_path",
            is_internal_abs_path=True,
        )

    else:
        raise HTTPException(status_code=400, detail=f"Invalid root_kind: {root_kind}")

@router.post('/api/atlas', response_model=AtlasArtifact, dependencies=[Depends(verify_token)])
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
                "**/Keychain/**", "**/Safari/**",
                "**/core", "**/core.[0-9]*", "**/*.core"
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

@router.post('/api/sync/metarepo', dependencies=[Depends(verify_token)])
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

def _atlas_primary_artifact_files(merges_dir: Path) -> list[Path]:
    """Return only API-managed Atlas primary artifact JSON files.

    Atlas sidecars and external observation receipts deliberately share the
    ``atlas-`` prefix, but they are not valid ``AtlasArtifact`` records.  The
    service creates primary artifacts as ``atlas-<unix_ts>.json`` and the
    download endpoint accepts the same ID vocabulary, so list/latest must use
    that exact boundary instead of a broad ``atlas-*.json`` glob.
    """

    return sorted(
        (
            path
            for path in merges_dir.glob("atlas-*.json")
            if _ATLAS_PRIMARY_ARTIFACT_RE.fullmatch(path.name)
        ),
        key=lambda path: path.name,
        reverse=True,
    )

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

@router.get('/api/atlas', response_model=List[AtlasArtifact], dependencies=[Depends(verify_token)])
def list_atlas():
    merges_dir = state.merges_dir
    if not merges_dir and state.hub:
        merges_dir = get_merges_dir(state.hub)

    if not merges_dir or not merges_dir.exists():
        return []

    files = _atlas_primary_artifact_files(merges_dir)

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

@router.get('/api/atlas/latest', dependencies=[Depends(verify_token)])
def get_latest_atlas():
    merges_dir = state.merges_dir
    if not merges_dir and state.hub:
        merges_dir = get_merges_dir(state.hub)

    if not merges_dir or not merges_dir.exists():
        raise HTTPException(status_code=404, detail="No atlas artifacts found (no merges dir)")

    files = _atlas_primary_artifact_files(merges_dir)
    if not files:
        raise HTTPException(status_code=404, detail="No atlas artifacts found")

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

@router.get('/api/atlas/{id}/download', dependencies=[Depends(verify_token)])
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

@router.post('/api/export/webmaschine', dependencies=[Depends(verify_token)])
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
            # Export only the Home preset resolved and stored during startup.
            sec = get_security_config()
            sys_root = sec.home_preset_root
            if sys_root is not None:
                sec.validate_path(sys_root)
                machine_roots.append(str(sys_root))
        except (InvalidPathError, AccessDeniedError, OSError, RuntimeError) as exc:
            logger.debug("System root not available for export: %s", exc, exc_info=True)

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


def build_router(
    app_provider: Callable[[], ModuleType],
    *,
    serve_file: Callable[..., FileResponse],
):
    global state, logger, get_security_config, resolve_fs_path
    global AtlasScanner, render_atlas_md, _write_json_atomic, _serve_file
    state = AttributeProxy(app_provider, 'state')
    logger = AttributeProxy(app_provider, 'logger')
    get_security_config = dynamic_callable(app_provider, 'get_security_config')
    resolve_fs_path = dynamic_callable(app_provider, 'resolve_fs_path')
    AtlasScanner = dynamic_callable(app_provider, 'AtlasScanner')
    render_atlas_md = dynamic_callable(app_provider, 'render_atlas_md')
    _write_json_atomic = dynamic_callable(app_provider, '_write_json_atomic')
    _serve_file = serve_file
    return (
        router,
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
    )
