import json
import uuid
import datetime
from pathlib import Path
from typing import Dict, Any, List, Tuple

from merger.repoground.atlas.paths import resolve_atlas_base_dir, resolve_artifact_ref, resolve_snapshot_dir


def _load_inventory_index(inv_path: Path) -> Dict[str, Dict[str, Any]]:
    """
    Robustly loads a JSONL inventory file line by line into a dictionary keyed by `rel_path`.
    Skips malformed lines, empty lines, or entries missing a valid string `rel_path`.
    """
    files = {}
    with open(inv_path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                item = json.loads(line)
                if not isinstance(item, dict):
                    continue
                rel_path = item.get("rel_path")
                if not rel_path or not isinstance(rel_path, str):
                    continue
                files[rel_path] = item
            except json.JSONDecodeError:
                continue
    return files


def _compare_file_sets(from_files: Dict[str, Dict[str, Any]], to_files: Dict[str, Dict[str, Any]]) -> Tuple[List[str], List[str], List[str]]:
    """
    Compares two file sets (keyed by path) and returns sorted lists of new, removed, and changed file paths.
    """
    new_files = []
    removed_files = []
    changed_files = []

    for path in to_files:
        if path not in from_files:
            new_files.append(path)
        else:
            old_item = from_files[path]
            new_item = to_files[path]

            if old_item.get("size_bytes") != new_item.get("size_bytes") or old_item.get("mtime") != new_item.get("mtime") or old_item.get("is_symlink") != new_item.get("is_symlink"):
                changed_files.append(path)

    for path in from_files:
        if path not in to_files:
            removed_files.append(path)

    new_files.sort()
    removed_files.sort()
    changed_files.sort()

    return new_files, removed_files, changed_files


def compute_snapshot_delta(registry, from_snap_id: str, to_snap_id: str) -> Dict[str, Any]:
    from_snap = registry.get_snapshot(from_snap_id)
    to_snap = registry.get_snapshot(to_snap_id)

    if not from_snap:
        raise ValueError(f"Snapshot not found: {from_snap_id}")
    if not to_snap:
        raise ValueError(f"Snapshot not found: {to_snap_id}")

    if from_snap["status"] != "complete" or to_snap["status"] != "complete":
        raise ValueError("Deltas can only be computed between snapshots with status='complete'.")

    if from_snap["machine_id"] != to_snap["machine_id"] or from_snap["root_id"] != to_snap["root_id"]:
        raise ValueError("Snapshots must belong to the same machine and root for a direct delta calculation.")

    machine_id = from_snap["machine_id"]
    root_id = from_snap["root_id"]

    if not getattr(registry, 'db_path', None):
        raise ValueError("Cannot compute snapshot delta without a canonical registry db_path.")
    atlas_base = resolve_atlas_base_dir(registry.db_path)

    from_inv_path = None
    if from_snap["inventory_ref"]:
        from_inv_path = resolve_artifact_ref(atlas_base, from_snap["inventory_ref"])
    to_inv_path = None
    if to_snap["inventory_ref"]:
        to_inv_path = resolve_artifact_ref(atlas_base, to_snap["inventory_ref"])

    if not from_inv_path or not from_inv_path.exists():
        raise FileNotFoundError(f"Inventory missing for snapshot {from_snap_id}")
    if not to_inv_path or not to_inv_path.exists():
        raise FileNotFoundError(f"Inventory missing for snapshot {to_snap_id}")

    from_files = _load_inventory_index(from_inv_path)
    to_files = _load_inventory_index(to_inv_path)

    new_files, removed_files, changed_files = _compare_file_sets(from_files, to_files)

    delta_id = f"delta_{uuid.uuid4().hex[:8]}"
    created_at = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()

    delta = {
        "delta_id": delta_id,
        "from_snapshot_id": from_snap_id,
        "to_snapshot_id": to_snap_id,
        "created_at": created_at,
        "new_files": new_files,
        "removed_files": removed_files,
        "changed_files": changed_files,
        "summary": {
            "new_count": len(new_files),
            "removed_count": len(removed_files),
            "changed_count": len(changed_files)
        }
    }

    # Store in the to_snapshot directory as per convention: snapshots/<snapshot_id>/
    snapshot_dir = resolve_snapshot_dir(atlas_base, machine_id, root_id, to_snap_id)
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    delta_filename = f"{delta_id}.json"
    delta_path = snapshot_dir / delta_filename

    with open(delta_path, "w", encoding="utf-8") as f:
        json.dump(delta, f, indent=2)

    try:
        delta_ref = delta_path.relative_to(atlas_base).as_posix()
    except ValueError:
        delta_ref = delta_path.as_posix()

    registry.register_delta(delta_id, from_snap_id, to_snap_id, delta_ref, created_at)

    return delta

# Drift Note: The `compute_snapshot_comparison` function shares the inventory parsing
# and file comparison loops with `compute_snapshot_delta` via internal helpers.
# This maintains robustness across both modes while keeping strict semantic separation
# between temporal deltas (same root, persisted) and structural comparisons (cross-root, diagnostic).
def compute_snapshot_comparison(registry, from_snap_id: str, to_snap_id: str) -> Dict[str, Any]:
    from_snap = registry.get_snapshot(from_snap_id)
    to_snap = registry.get_snapshot(to_snap_id)

    if not from_snap:
        raise ValueError(f"Snapshot not found: {from_snap_id}")
    if not to_snap:
        raise ValueError(f"Snapshot not found: {to_snap_id}")

    if from_snap["status"] != "complete" or to_snap["status"] != "complete":
        raise ValueError("Comparisons can only be computed between snapshots with status='complete'.")

    from_root = registry.get_root(from_snap["root_id"])
    to_root = registry.get_root(to_snap["root_id"])

    if not getattr(registry, 'db_path', None):
        raise ValueError("Cannot compute snapshot comparison without a canonical registry db_path.")
    atlas_base = resolve_atlas_base_dir(registry.db_path)

    from_inv_path = None
    if from_snap["inventory_ref"]:
        from_inv_path = resolve_artifact_ref(atlas_base, from_snap["inventory_ref"])
    to_inv_path = None
    if to_snap["inventory_ref"]:
        to_inv_path = resolve_artifact_ref(atlas_base, to_snap["inventory_ref"])

    if not from_inv_path or not from_inv_path.exists():
        raise FileNotFoundError(f"Inventory missing for snapshot {from_snap_id}")
    if not to_inv_path or not to_inv_path.exists():
        raise FileNotFoundError(f"Inventory missing for snapshot {to_snap_id}")

    from_files = _load_inventory_index(from_inv_path)
    to_files = _load_inventory_index(to_inv_path)

    new_files, removed_files, changed_files = _compare_file_sets(from_files, to_files)

    is_cross_root = (from_snap["machine_id"] != to_snap["machine_id"]) or (from_snap["root_id"] != to_snap["root_id"])
    mode = "cross-root-comparison" if is_cross_root else "same-root-delta"

    comparison_id = f"cmp_{uuid.uuid4().hex[:8]}"
    created_at = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()

    comparison = {
        "comparison_id": comparison_id,
        "mode": mode,
        "is_cross_root": is_cross_root,
        "from_snapshot_id": from_snap_id,
        "to_snapshot_id": to_snap_id,
        "from_machine_id": from_snap["machine_id"],
        "to_machine_id": to_snap["machine_id"],
        "from_root_id": from_snap["root_id"],
        "to_root_id": to_snap["root_id"],
        "from_root_value": from_root.get("root_value") if from_root else None,
        "to_root_value": to_root.get("root_value") if to_root else None,
        "created_at": created_at,
        "new_files": new_files,
        "removed_files": removed_files,
        "changed_files": changed_files,
        "summary": {
            "new_count": len(new_files),
            "removed_count": len(removed_files),
            "changed_count": len(changed_files)
        }
    }

    # Unlike compute_snapshot_delta, we don't automatically store comparison results
    # to the snapshot directory or registry because comparisons are often transient/diagnostic.
    # If they needed persistence later, they'd get a separate registry table.

    return comparison
