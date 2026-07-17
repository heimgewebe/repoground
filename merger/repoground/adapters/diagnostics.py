import json
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, Any

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "diagnostics.snapshot.v1"
TTL_HOURS = 24

def rebuild(hub_path: Path) -> Dict[str, Any]:
    """
    Rebuilds diagnostics snapshot based on fleet.snapshot.json expectations.
    """
    gewebe_dir = hub_path / ".gewebe"
    cache_dir = gewebe_dir / "cache"
    # Ensure cache dir exists
    cache_dir.mkdir(parents=True, exist_ok=True)

    fleet_snap_path = cache_dir / "fleet.snapshot.json"
    diag_out_path = cache_dir / "diagnostics.snapshot.json"

    ts = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    # 1. Load Fleet Snapshot
    if not fleet_snap_path.exists():
        diag = {
            "status": "error",
            "generated_at": ts,
            "data": {},
            "error": "fleet.snapshot.json missing"
        }
        with open(diag_out_path, "w", encoding="utf-8") as f:
            json.dump(diag, f, indent=2)
        return {"status": "error", "message": "Fleet snapshot missing"}

    try:
        fleet_data = json.loads(fleet_snap_path.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("Failed to load fleet snapshot")
        diag = {
            "status": "error",
            "generated_at": ts,
            "data": {},
            "error": "Invalid fleet snapshot"
        }
        with open(diag_out_path, "w", encoding="utf-8") as f:
            json.dump(diag, f, indent=2)
        return {"status": "error", "message": "Invalid fleet snapshot"}

    if fleet_data.get("status") != "ok":
         diag = {
            "status": "error",
            "generated_at": ts,
            "data": {},
            "error": "Fleet snapshot is in error state"
        }
         with open(diag_out_path, "w", encoding="utf-8") as f:
            json.dump(diag, f, indent=2)
         return {"status": "error", "message": "Fleet snapshot is in error state"}

    # P3: TTL check (>24h)
    snapshot_ts_str = fleet_data.get("generated_at")
    snapshot_status_override = None
    if snapshot_ts_str:
        try:
            snap_ts = datetime.strptime(snapshot_ts_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            now_ts = datetime.now(timezone.utc)
            if now_ts - snap_ts > timedelta(hours=TTL_HOURS):
                snapshot_status_override = "warn"
        except ValueError:
            pass

    repos = fleet_data.get("data", {}).get("repos", {})
    results = {}

    # 2. Iterate Fleet Repos and check local state
    for repo_name, meta in repos.items():
        repo_path = hub_path / repo_name

        # Check existence
        if not repo_path.is_dir():
            results[repo_name] = {
                "status": "missing",
                "checks": []
            }
            continue

        checks = []

        # Profile Expectation
        wgx = meta.get("wgx") if isinstance(meta.get("wgx"), dict) else {}
        expected = wgx.get("profile_expected")
        if expected is True:
            profile_path = repo_path / ".wgx" / "profile.yml"
            if not profile_path.exists():
                checks.append({
                    "code": "missing_wgx_profile",
                    "severity": "warn",
                    "message": ".wgx/profile.yml expected but missing"
                })

        results[repo_name] = {
            "status": "ok" if not checks else "issue",
            "checks": checks,
            # Pass through role for convenience
            "role": meta.get("role", "unknown")
        }

    # P3: Summary & Issues Total
    summary = {
        "ok": sum(1 for r in results.values() if r["status"] == "ok"),
        "issue": sum(1 for r in results.values() if r["status"] == "issue"),
        "missing": sum(1 for r in results.values() if r["status"] == "missing")
    }
    issues_total = sum(len(r["checks"]) for r in results.values())

    diag_status = snapshot_status_override or "ok"
    if summary["issue"] > 0 or summary["missing"] > 0:
        # If we have issues, the overall diagnostics status might still be OK (as in "process ran ok"),
        # but logically it reflects the fleet health.
        # "status" here usually means "did the diagnostic process succeed".
        # However, P3 says "optional: TTL/outdated ... status: warn".
        # So status refers to the validity of the diagnostic snapshot itself.
        pass

    diag = {
        "schema_version": SCHEMA_VERSION,
        "status": diag_status,
        "generated_at": ts,
        "source_snapshot": { "fleet_generated_at": fleet_data.get("generated_at") },
        "summary": { **summary, "issues_total": issues_total },
        "data": results
    }

    with open(diag_out_path, "w", encoding="utf-8") as f:
        json.dump(diag, f, indent=2)

    return {
        "status": diag_status,
        "summary": summary,
        "issues_total": issues_total
    }
