# -*- coding: utf-8 -*-

"""
metarepo_sync.py – Synchronization engine for metarepo-managed files.
Implements strict manifest-based sync with managed markers.
"""

import json
import hashlib
import datetime
import shutil
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import timezone
from pathlib import Path
from typing import Dict, List, Optional, Any

# YAML is mandatory for this service feature
import yaml

# Use centralized strict path resolver
try:
    from merger.repoground.core.path_security import resolve_secure_path
except ImportError:
    from merger.repoground.core.path_security import resolve_secure_path

SYNC_REPORT_REL_PATH = Path(".gewebe/out/sync.report.json")
MANIFEST_REL_PATH = Path("sync/metarepo-sync.yml")
MANAGED_MARKER_DEFAULT = "managed-by: metarepo-sync"

# Hash computation sentinel values
HASH_FILE_NOT_FOUND = ""
HASH_COMPUTATION_ERROR = "ERROR"

logger = logging.getLogger(__name__)


def assert_report_shape(report: Dict[str, Any]) -> None:
    """
    Validates the report structure against minimal contract requirements.
    Sets status="error" and increments summary["error"] if violated.
    """
    issues = []

    # Check status presence
    if "status" not in report:
        issues.append("Missing 'status' field")

    # Check summary keys
    summary = report.get("summary", {})
    required_keys = {"add", "update", "skip", "blocked", "error"}
    if not isinstance(summary, dict) or not required_keys.issubset(summary.keys()):
        issues.append(f"Invalid summary keys. Expected {required_keys}")

    # Check details actions (uppercase enum)
    valid_actions = {"ADD", "UPDATE", "SKIP", "BLOCKED", "ERROR"}
    details = report.get("details", [])
    if isinstance(details, list):
        for idx, d in enumerate(details):
            action = d.get("action")
            if action not in valid_actions:
                issues.append(f"Invalid action '{action}' at details[{idx}]")
    else:
        issues.append("Details is not a list")

    if issues:
        report["status"] = "error"
        # Ensure summary exists to modify
        if not isinstance(report.get("summary"), dict):
            report["summary"] = {k: 0 for k in required_keys}

        report["summary"]["error"] += len(issues)
        for i in issues:
            logger.error("Report contract violation: %s", i)


def compute_file_hash(path: Path) -> str:
    """Compute SHA256 hash of a file."""
    if not path.exists():
        return HASH_FILE_NOT_FOUND
    sha256 = hashlib.sha256()
    try:
        with path.open("rb") as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                sha256.update(chunk)
        return sha256.hexdigest()
    except OSError:
        return HASH_COMPUTATION_ERROR


def has_managed_marker(path: Path, marker: str) -> bool:
    """
    Check if the first 5 lines of the file contain the managed marker.
    """
    if not path.exists() or not path.is_file():
        return False

    try:
        # Read beginning of file (up to 8KB or 20 lines) to find marker
        with path.open("r", encoding="utf-8", errors="ignore") as f:
            chunk = f.read(8192)  # 8KB
            lines = chunk.splitlines()[:20]  # Check first 20 lines
            for line in lines:
                if marker in line:
                    return True
    except OSError:
        pass
    return False


def load_manifest(metarepo_path: Path) -> Optional[Dict[str, Any]]:
    """Load the sync manifest from metarepo."""
    manifest_file = metarepo_path / MANIFEST_REL_PATH
    if not manifest_file.exists():
        return None

    try:
        with manifest_file.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except Exception:
        return None


def _should_process_entry(entry: Dict[str, Any], targets: Optional[List[str]]) -> bool:
    """
    Filter entries based on target list.
    Matches segments: 'wgx' matches 'wgx', 'wgx/foo', 'wgx:bar', but NOT 'wgx_extra'.
    """
    if not targets:
        return True

    eid = entry.get("id", "")
    for t in targets:
        # Exact match
        if eid == t:
            return True
        # Prefix match with separator
        if eid.startswith(t + "/") or eid.startswith(t + ":"):
            return True
    return False


def sync_repo(
    repo_root: Path,
    metarepo_root: Path,
    manifest: Dict[str, Any],
    mode: str,
    target_filter: Optional[List[str]] = None,
    source_hashes: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    Sync a single repository against the manifest.

    Args:
        repo_root: Root directory of the repository to synchronize.
        metarepo_root: Root directory of the metarepo.
        manifest: Parsed manifest dictionary loaded from the metarepo.
        mode: Sync mode ("apply" or "dry_run").
        target_filter: Optional list of target identifiers used to limit which manifest entries are processed.
        source_hashes: Optional precomputed cache mapping entry_id -> sha256 hex digest (len==64).

    Returns:
        A structured report describing the outcome of the synchronization.
    """
    managed_marker = manifest.get("managed_marker", MANAGED_MARKER_DEFAULT)

    report: Dict[str, Any] = {
        "version": 1,
        "source": "metarepo",
        "mode": mode,
        "status": "ok",  # Optimistic, set to error on failures
        "generated_at": datetime.datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "metarepo_path": str(metarepo_root),
        "manifest_path": str(metarepo_root / MANIFEST_REL_PATH),
        "summary": {"add": 0, "update": 0, "skip": 0, "blocked": 0, "error": 0},
        "details": [],
    }

    entries = manifest.get("entries", [])

    for entry in entries:
        if not _should_process_entry(entry, target_filter):
            continue

        entry_id = entry.get("id", "unknown")
        src_rel = entry.get("source")
        target_rels = entry.get("targets", [])
        sync_mode = entry.get("mode", "copy")  # copy, copy_if_missing

        # Source must be safe and exist
        try:
            src_path = resolve_secure_path(metarepo_root, src_rel)
        except ValueError as e:
            report["details"].append(
                {"id": entry_id, "target": src_rel, "action": "ERROR", "reason": f"Invalid source path: {e}"}
            )
            report["summary"]["error"] += 1
            report["status"] = "error"
            continue

        if not src_path.exists():
            report["details"].append(
                {"id": entry_id, "target": src_rel, "action": "ERROR", "reason": f"Source not found: {src_rel}"}
            )
            report["summary"]["error"] += 1
            report["status"] = "error"
            continue

        if source_hashes and entry_id in source_hashes:
            src_hash = source_hashes[entry_id]
        else:
            src_hash = compute_file_hash(src_path)

        if src_hash == HASH_COMPUTATION_ERROR:
            report["details"].append(
                {"id": entry_id, "target": src_rel, "action": "ERROR", "reason": "source_hash_failed"}
            )
            report["summary"]["error"] += 1
            report["status"] = "error"
            continue

        for tgt_rel in target_rels:
            try:
                tgt_path = resolve_secure_path(repo_root, tgt_rel)
            except ValueError as e:
                report["details"].append(
                    {
                        "id": entry_id,
                        "target": tgt_rel,
                        "action": "ERROR",
                        "reason": f"Invalid target path (traversal): {e}",
                    }
                )
                report["summary"]["error"] += 1
                report["status"] = "error"
                continue

            action = "SKIP"
            reason = ""

            if not tgt_path.exists():
                action = "ADD"
            else:
                tgt_hash = compute_file_hash(tgt_path)
                if tgt_hash == HASH_COMPUTATION_ERROR:
                    action = "ERROR"
                    reason = "target_hash_failed"
                    report["status"] = "error"
                elif tgt_hash == src_hash:
                    action = "SKIP"
                    reason = "identical"
                else:
                    if sync_mode == "copy_if_missing":
                        action = "SKIP"
                        reason = "exists_preserve"
                    elif sync_mode == "copy":
                        if has_managed_marker(tgt_path, managed_marker):
                            action = "UPDATE"
                        else:
                            action = "BLOCKED"
                            reason = "missing_marker"
                    else:
                        action = "SKIP"
                        reason = f"unknown_mode_{sync_mode}"

            if mode == "apply" and action in ("ADD", "UPDATE"):
                try:
                    if action == "UPDATE":
                        timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
                        backup_path = tgt_path.with_suffix(tgt_path.suffix + f".bak.{timestamp}")
                        try:
                            shutil.copy2(tgt_path, backup_path)
                        except Exception as e:
                            raise RuntimeError(f"Backup failed: {e}")

                    tgt_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src_path, tgt_path)
                except Exception as e:
                    action = "ERROR"
                    reason = str(e)

            key = action.lower()
            if key in report["summary"]:
                report["summary"][key] += 1
            else:
                report["summary"]["error"] += 1
                report["status"] = "error"

            if action == "ERROR":
                report["status"] = "error"

            report["details"].append({"id": entry_id, "target": tgt_rel, "action": action, "reason": reason})

    assert_report_shape(report)

    try:
        out_file = repo_root / SYNC_REPORT_REL_PATH
        out_file.parent.mkdir(parents=True, exist_ok=True)
        with out_file.open("w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
    except Exception:
        pass

    return report


def sync_from_metarepo(hub_path: Path, mode: str = "dry_run", targets: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Orchestrate the sync from metarepo to all other repos in the hub.
    Returns an aggregated report.
    """
    if not hub_path or not hub_path.exists():
        return {"status": "error", "message": "Invalid hub path"}

    metarepo_root = hub_path / "metarepo"
    if not metarepo_root.exists():
        return {"status": "error", "message": "metarepo not found in hub"}

    manifest = load_manifest(metarepo_root)
    if not manifest:
        return {"status": "error", "message": "Manifest not found or invalid (sync/metarepo-sync.yml)"}

    results: Dict[str, Any] = {}
    aggregated_summary = {"add": 0, "update": 0, "skip": 0, "blocked": 0, "error": 0}

    # Pre-compute source hashes to avoid redundant I/O (only for entries we will process)
    source_hashes: Dict[str, str] = {}
    for entry in manifest.get("entries", []):
        if not _should_process_entry(entry, targets):
            continue

        entry_id = entry.get("id")
        src_rel = entry.get("source")
        if not entry_id or not src_rel:
            logger.warning("Manifest entry missing id/source: id=%r source=%r", entry_id, src_rel)
            continue

        try:
            p = resolve_secure_path(metarepo_root, src_rel)
            if not p.exists():
                continue

            h = compute_file_hash(p)
            if h and h != HASH_COMPUTATION_ERROR and len(h) == 64 and all(c in "0123456789abcdef" for c in h):
                source_hashes[entry_id] = h
            else:
                logger.warning("Invalid hash computed for entry_id=%s src=%s: %r", entry_id, src_rel, h)
        except Exception as e:
            logger.warning(
                "Source hash precompute failed for entry_id=%s src=%s: %s",
                entry_id,
                src_rel,
                e,
                exc_info=True,
            )

    # Repo discovery
    valid_repos: List[Path] = []
    for item in hub_path.iterdir():
        if not item.is_dir():
            continue
        if item.name.startswith("."):
            continue
        if item.name in ("metarepo", "node_modules", "venv", "__pycache__"):
            continue

        has_git = (item / ".git").exists()
        has_ai_context = (item / ".ai-context.yml").exists()
        if has_git or has_ai_context:
            valid_repos.append(item)

    # Parallelize repo sync
    with ThreadPoolExecutor(max_workers=8) as executor:
        future_to_repo = {
            executor.submit(sync_repo, repo, metarepo_root, manifest, mode, targets, source_hashes): repo.name
            for repo in valid_repos
        }

        for future in as_completed(future_to_repo):
            repo_name = future_to_repo[future]
            try:
                repo_report = future.result()
                results[repo_name] = repo_report

                for k in aggregated_summary:
                    aggregated_summary[k] += repo_report.get("summary", {}).get(k, 0)
            except Exception as exc:
                logger.error("Sync failed for %s: %s", repo_name, exc, exc_info=True)
                aggregated_summary["error"] += 1
                results[repo_name] = {
                    "status": "error",
                    "details": [{"action": "ERROR", "reason": str(exc)}],
                    "summary": {"add": 0, "update": 0, "skip": 0, "blocked": 0, "error": 1},
                }

    final_status = "ok"
    if aggregated_summary["error"] > 0:
        final_status = "error"
    else:
        if any(r.get("status") == "error" for r in results.values()):
            final_status = "error"

    sorted_results = dict(sorted(results.items()))

    return {
        "status": final_status,
        "mode": mode,
        "manifest_version": manifest.get("version"),
        "timestamp": datetime.datetime.now(timezone.utc).isoformat(),
        "aggregate_summary": aggregated_summary,
        "repos": sorted_results,
    }
