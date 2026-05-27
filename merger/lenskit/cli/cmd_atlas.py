import re
import argparse
import sys
import json
import os
import socket
import datetime
import hashlib
import tempfile
from enum import Enum
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Any, Optional

from merger.lenskit.adapters.atlas import AtlasScanner, render_atlas_md
from merger.lenskit.atlas.planner import plan_atlas_outputs, write_mode_outputs
from merger.lenskit.atlas.registry import AtlasRegistry
from merger.lenskit.atlas.paths import resolve_atlas_base_dir, resolve_snapshot_dir, resolve_artifact_ref
from merger.lenskit.atlas.lifecycle import run_scan_lifecycle

def run_atlas_machines(args: argparse.Namespace) -> int:
    registry_path = Path("atlas/registry/atlas_registry.sqlite").resolve()
    with AtlasRegistry(registry_path) as registry:
        machines = registry.list_machines()
    print(json.dumps(machines, indent=2))
    return 0

def run_atlas_machine_health(args: argparse.Namespace) -> int:
    registry_path = Path("atlas/registry/atlas_registry.sqlite").resolve()
    with AtlasRegistry(registry_path) as registry:
        health_reports = registry.get_machine_health()
    print(json.dumps(health_reports, indent=2))
    return 0

def run_atlas_roots(args: argparse.Namespace) -> int:
    registry_path = Path("atlas/registry/atlas_registry.sqlite").resolve()
    with AtlasRegistry(registry_path) as registry:
        roots = registry.list_roots()

    if getattr(args, "group_by_label", False):
        grouped = {}
        for root in roots:
            label = root.get("label")
            grouped.setdefault(label, []).append(root)

        sorted_labels = sorted(grouped.keys(), key=lambda k: (k is not None, k if k is not None else ""))
        for label in sorted_labels:
            display_label = "(none)" if label is None else label
            print(f"{display_label}:")
            items = sorted(grouped[label], key=lambda x: (x['machine_id'], x['root_id']))
            for item in items:
                print(f"  - machine: {item['machine_id']} | id: {item['root_id']} -> {item['root_value']}")
    else:
        print(json.dumps(roots, indent=2))

    return 0

def run_atlas_snapshots(args: argparse.Namespace) -> int:
    registry_path = Path("atlas/registry/atlas_registry.sqlite").resolve()
    with AtlasRegistry(registry_path) as registry:
        snapshots = registry.list_snapshots()
    print(json.dumps(snapshots, indent=2))
    return 0


class SnapshotRefKind(Enum):
    SNAPSHOT_ID = "snapshot_id"
    MACHINE_PATH = "machine_path"
    MACHINE_LABEL = "machine_label"

@dataclass
class ParsedSnapshotRef:
    kind: SnapshotRefKind
    value: str
    machine_id: Optional[str] = None

def parse_snapshot_ref(ref: str) -> ParsedSnapshotRef:
    """
    Parses an Atlas snapshot reference string into a structured Enum-typed object.

    Explicit Grammar rules:
    - `machine_id:label:root_label`: Resolves against a semantic label on a given machine.
      `machine_id` and `root_label` are explicitly trimmed. Neither may be empty.
      `root_label` may contain further colons.
    - `machine_id:path`: Resolves against a specific absolute path on a given machine.
      `machine_id` is trimmed and must not be empty.
      `path` is intentionally NOT trimmed to support trailing whitespaces in valid filesystem paths.
      It must not be empty.
    - `snapshot_id` (fallback): Resolves directly against an exact snapshot identifier. Must not be empty.
    """
    if ":" in ref:
        parts = ref.split(":", 2)
        if len(parts) > 1 and parts[1].strip() == "label":
            machine_id = parts[0].strip()
            if not machine_id:
                raise ValueError(f"Invalid snapshot reference '{ref}': expected syntax 'machine_id:label:<root_label>' with a non-empty machine_id")
            if len(parts) != 3:
                raise ValueError(f"Invalid snapshot reference '{ref}': expected syntax 'machine_id:label:<root_label>' with a non-empty root_label")
            root_label = parts[2].strip()
            if not root_label:
                raise ValueError(f"Invalid snapshot reference '{ref}': expected syntax 'machine_id:label:<root_label>' with a non-empty root_label")
            return ParsedSnapshotRef(kind=SnapshotRefKind.MACHINE_LABEL, machine_id=machine_id, value=root_label)
        else:
            machine_id, root_value = ref.split(":", 1)
            machine_id = machine_id.strip()
            if not machine_id:
                raise ValueError(f"Invalid snapshot reference '{ref}': expected syntax 'machine_id:path' with a non-empty machine_id")
            if not root_value:
                raise ValueError(f"Invalid snapshot reference '{ref}': expected syntax 'machine_id:path' with a non-empty path")
            return ParsedSnapshotRef(kind=SnapshotRefKind.MACHINE_PATH, machine_id=machine_id, value=root_value)

    value = ref.strip()
    if not value:
        raise ValueError("Invalid snapshot reference: cannot be empty")
    return ParsedSnapshotRef(kind=SnapshotRefKind.SNAPSHOT_ID, value=value)

def _resolve_snapshot_ref(ref: str, registry) -> str:
    parsed = parse_snapshot_ref(ref)

    if parsed.kind == SnapshotRefKind.SNAPSHOT_ID:
        return parsed.value

    target_root_ids = []

    if parsed.kind == SnapshotRefKind.MACHINE_LABEL:
        for r in registry.list_roots():
            if r["machine_id"] == parsed.machine_id and r.get("label") == parsed.value:
                target_root_ids.append(r["root_id"])

        if not target_root_ids:
            raise ValueError(f"No root found for machine '{parsed.machine_id}' with label '{parsed.value}'")

        if len(target_root_ids) > 1:
            raise ValueError(f"Multiple roots found for machine '{parsed.machine_id}' with label '{parsed.value}'; use machine:path or snapshot_id for explicit disambiguation")

        target_root_id = target_root_ids[0]

        snapshots = registry.list_complete_snapshots(root_id=target_root_id)
        if not snapshots:
            raise ValueError(f"No complete snapshot found for machine '{parsed.machine_id}' and label '{parsed.value}'")

    elif parsed.kind == SnapshotRefKind.MACHINE_PATH:
        def normalize_path(p: str) -> str:
            # Conservative normalization for trivial variants (e.g., trailing slashes, /./)
            # without semantically reinterpreting absolute/relative meanings.
            import posixpath
            return posixpath.normpath(p)

        norm_root_value = normalize_path(parsed.value)

        for r in registry.list_roots():
            if r["machine_id"] == parsed.machine_id and normalize_path(r["root_value"]) == norm_root_value:
                target_root_ids.append(r["root_id"])

        if not target_root_ids:
            raise ValueError(f"No root found for machine '{parsed.machine_id}' and path '{parsed.value}'")

        if len(target_root_ids) > 1:
            raise ValueError(f"Ambiguous root reference: multiple roots match machine '{parsed.machine_id}' and path '{parsed.value}'")

        target_root_id = target_root_ids[0]

        snapshots = registry.list_complete_snapshots(root_id=target_root_id)
        if not snapshots:
            raise ValueError(f"No complete snapshots found for root '{target_root_id}'")

    else:
        raise ValueError(f"Unsupported snapshot reference kind: {parsed.kind}")

    # Ensure deterministic sort by created_at descending just in case DB defaults shift
    # missing created_at should sink to bottom or error, but they should all have it
    def safe_sort_key(s):
        return (s.get("created_at", ""), s.get("snapshot_id", ""))

    sorted_snaps = sorted(snapshots, key=safe_sort_key, reverse=True)
    return sorted_snaps[0]["snapshot_id"]

def run_atlas_diff(args: argparse.Namespace) -> int:
    from merger.lenskit.atlas.diff import compute_snapshot_delta, compute_snapshot_comparison
    registry_path = Path("atlas/registry/atlas_registry.sqlite").resolve()
    try:
        with AtlasRegistry(registry_path) as registry:
            from_snap_id = _resolve_snapshot_ref(args.from_snapshot, registry)
            to_snap_id = _resolve_snapshot_ref(args.to_snapshot, registry)

            from_snap = registry.get_snapshot(from_snap_id)
            to_snap = registry.get_snapshot(to_snap_id)

            if not from_snap:
                raise ValueError(f"Snapshot not found: {from_snap_id}")
            if not to_snap:
                raise ValueError(f"Snapshot not found: {to_snap_id}")

            if from_snap["machine_id"] == to_snap["machine_id"] and from_snap["root_id"] == to_snap["root_id"]:
                delta = compute_snapshot_delta(registry, from_snap_id, to_snap_id)
                print(f"Delta: {delta['delta_id']} ({delta['from_snapshot_id']} -> {delta['to_snapshot_id']})")
                print("Mode: same-root-delta")
            else:
                delta = compute_snapshot_comparison(registry, from_snap_id, to_snap_id)
                print(f"Comparison: {delta['comparison_id']}")
                print("Mode: cross-root-comparison")
                from_desc = f"{delta['from_machine_id']}:{delta['from_root_value']} ({delta['from_snapshot_id']})"
                to_desc = f"{delta['to_machine_id']}:{delta['to_root_value']} ({delta['to_snapshot_id']})"
                print(f"From: {from_desc}")
                print(f"To:   {to_desc}")

        print(f"Summary: {json.dumps(delta['summary'], indent=2)}")
        print(f"\nNew files: {len(delta['new_files'])}")
        for f in delta['new_files'][:10]:
            print(f"  + {f}")
        if len(delta['new_files']) > 10:
            print(f"  ... and {len(delta['new_files']) - 10} more")

        print(f"\nRemoved files: {len(delta['removed_files'])}")
        for f in delta['removed_files'][:10]:
            print(f"  - {f}")
        if len(delta['removed_files']) > 10:
            print(f"  ... and {len(delta['removed_files']) - 10} more")

        print(f"\nChanged files: {len(delta['changed_files'])}")
        for f in delta['changed_files'][:10]:
            print(f"  ~ {f}")
        if len(delta['changed_files']) > 10:
            print(f"  ... and {len(delta['changed_files']) - 10} more")

        return 0
    except Exception as e:
        print(f"Error computing diff: {e}", file=sys.stderr)
        return 1

def run_atlas_search(args: argparse.Namespace) -> int:
    from merger.lenskit.atlas.search import AtlasSearch
    registry_path = Path("atlas/registry/atlas_registry.sqlite").resolve()
    try:
        searcher = AtlasSearch(registry_path)

        results = searcher.search(
            query=args.query,
            machine_id=args.machine_id,
            root_id=args.root_id,
            snapshot_id=args.snapshot_id,
            path_pattern=args.path,
            name_pattern=args.name,
            ext=args.ext,
            min_size=args.min_size,
            max_size=args.max_size,
            date_after=args.date_after,
            date_before=args.date_before,
            content_query=getattr(args, 'content_query', None)
        )

        # Print results
        for r in results:
            print(f"[{r.get('machine_id')}][{r.get('root_id')}] {r.get('rel_path')} ({r.get('size_bytes')} bytes) - {r.get('mtime')}")
            if 'content_snippet' in r:
                print(f"  Snippet: {r['content_snippet']}")

        print(f"\nTotal results: {len(results)}")

        return 0
    except Exception as e:
        print(f"Error executing search: {e}", file=sys.stderr)
        return 1

def run_atlas_analyze(args: argparse.Namespace) -> int:
    if args.analyze_command == "duplicates":
        return _run_analyze_duplicates(args.snapshot_id)
    if args.analyze_command == "orphans":
        return _run_analyze_orphans(args.snapshot_id)
    if args.analyze_command == "disk":
        return _run_analyze_disk(args.snapshot_id)
    if args.analyze_command == "backup-gap":
        return _run_analyze_backup_gap(args.source_snapshot, args.backup_snapshot)
    if args.analyze_command == "growth":
        return _run_analyze_growth(args.source_snapshot, args.target_snapshot)
    return 1

def _run_analyze_orphans(snapshot_id: str) -> int:
    from merger.lenskit.atlas.registry import AtlasRegistry
    from merger.lenskit.atlas.paths import resolve_atlas_base_dir, resolve_artifact_ref, resolve_snapshot_dir

    registry_path = Path("atlas/registry/atlas_registry.sqlite").resolve()
    with AtlasRegistry(registry_path) as registry:
        snapshot = registry.get_snapshot(snapshot_id)
        if not snapshot:
            print(f"Error: Snapshot '{snapshot_id}' not found.", file=sys.stderr)
            return 1

        if snapshot['status'] != 'complete':
            print(f"Error: Snapshot '{snapshot_id}' is not complete.", file=sys.stderr)
            return 1

        root = registry.get_root(snapshot['root_id'])
        if not root:
            print(f"Error: Root '{snapshot['root_id']}' not found.", file=sys.stderr)
            return 1

    if not snapshot.get('inventory_ref'):
        print(f"Error: Snapshot '{snapshot_id}' has no inventory_ref.", file=sys.stderr)
        return 1

    base_dir = resolve_atlas_base_dir(registry_path)
    inventory_path = resolve_artifact_ref(base_dir, snapshot['inventory_ref'])

    if not inventory_path or not inventory_path.exists():
        print(f"Error: Inventory file not found at {inventory_path}", file=sys.stderr)
        return 1

    root_path = Path(root['root_value'])
    if not root_path.exists() or not root_path.is_dir():
        print(f"Error: Root path '{root_path}' does not exist or is not a directory.", file=sys.stderr)
        return 1

    # Load files from the snapshot
    snapshot_files = set()
    with inventory_path.open('r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                rel_path = entry.get('rel_path')
                if rel_path:
                    # Treat snapshot files directly as canonical string representation
                    snapshot_files.add(rel_path)
            except json.JSONDecodeError:
                continue

    # Load live files from the root
    live_files = set()
    for root_dir, _, files in os.walk(root_path):
        rel_root = Path(root_dir).relative_to(root_path)
        for name in files:
            rel_file_path = rel_root / name
            live_files.add(rel_file_path.as_posix())

    # Orphans are files in the live system that are not in the snapshot
    orphans = live_files - snapshot_files
    # Dead files are files in the snapshot that are not in the live system
    dead_files = snapshot_files - live_files

    report = {
        "snapshot_id": snapshot_id,
        "analyzed_at": datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat(),
        "root_path": str(root_path),
        "total_live_files": len(live_files),
        "total_snapshot_files": len(snapshot_files),
        "orphan_count": len(orphans),
        "dead_file_count": len(dead_files),
        "orphans": sorted(list(orphans)),
        "dead_files": sorted(list(dead_files))
    }

    # Write to orphans.json in the snapshot directory
    snapshot_dir = resolve_snapshot_dir(base_dir, snapshot['machine_id'], snapshot['root_id'], snapshot_id)
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    out_path = snapshot_dir / "orphans.json"

    fd, temp_path = tempfile.mkstemp(dir=str(snapshot_dir), prefix=".tmp_orphans.json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, str(out_path))
    except Exception:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        raise

    try:
        rel_out = out_path.relative_to(base_dir)
        ref = rel_out.as_posix()
    except ValueError:
        ref = out_path.as_posix()

    # Register in SQLite
    with AtlasRegistry(registry_path) as registry:
        registry.update_snapshot_artifacts(snapshot_id, {"orphans": ref})

    print(json.dumps(report, indent=2))
    return 0


def _run_analyze_duplicates(snapshot_id: str) -> int:
    from merger.lenskit.atlas.registry import AtlasRegistry
    from merger.lenskit.atlas.paths import resolve_atlas_base_dir, resolve_artifact_ref, resolve_snapshot_dir

    registry_path = Path("atlas/registry/atlas_registry.sqlite").resolve()
    with AtlasRegistry(registry_path) as registry:
        snapshot = registry.get_snapshot(snapshot_id)
        if not snapshot:
            print(f"Error: Snapshot '{snapshot_id}' not found.", file=sys.stderr)
            return 1

        if snapshot['status'] != 'complete':
            print(f"Error: Snapshot '{snapshot_id}' is not complete.", file=sys.stderr)
            return 1

        root = registry.get_root(snapshot['root_id'])
        if not root:
            print(f"Error: Root '{snapshot['root_id']}' not found.", file=sys.stderr)
            return 1

    if not snapshot.get('inventory_ref'):
        print(f"Error: Snapshot '{snapshot_id}' has no inventory_ref.", file=sys.stderr)
        return 1

    base_dir = resolve_atlas_base_dir(registry_path)
    inventory_path = resolve_artifact_ref(base_dir, snapshot['inventory_ref'])

    if not inventory_path or not inventory_path.exists():
        print(f"Error: Inventory file not found at {inventory_path}", file=sys.stderr)
        return 1

    # Phase 1: Group by size using minimal entries
    size_groups: Dict[int, List[Dict[str, Any]]] = {}
    with inventory_path.open('r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            if entry.get('is_symlink') or entry.get('size_bytes', 0) == 0:
                continue

            rel_path = entry.get('rel_path')
            size = entry.get('size_bytes')

            # Defensive guard: skip invalid entries
            if not rel_path or not isinstance(size, int):
                continue

            if size not in size_groups:
                size_groups[size] = []

            # Store only what is needed
            min_entry = {
                "rel_path": rel_path,
                "size_bytes": size,
                "quick_hash": entry.get('quick_hash'),
                "checksum": entry.get('checksum')
            }
            size_groups[size].append(min_entry)

    # Phase 2: Compute full hash for potential duplicates
    root_path = Path(root['root_value'])
    duplicates_list = []

    for size, entries in size_groups.items():
        if len(entries) < 2:
            continue

        hash_groups: Dict[str, Dict[str, Any]] = {}
        for entry in entries:
            # Determine grouping hash and its verification status
            grouping_key = None
            is_verified = False

            # 1. Use existing checksum if present
            if entry.get('checksum'):
                grouping_key = entry['checksum']
                is_verified = True
            # 2. Otherwise use existing quick_hash (heuristic)
            elif entry.get('quick_hash'):
                grouping_key = f"quick:{entry['quick_hash']}"
                is_verified = False
            # 3. Otherwise compute live SHA256 (confirmed)
            else:
                try:
                    # Securely resolve path and ensure it doesn't escape the root
                    f_path = (root_path / entry['rel_path']).resolve()
                    if f_path.is_file() and f_path.is_relative_to(root_path.resolve()):
                        sha256 = hashlib.sha256()
                        with f_path.open('rb') as hf:
                            for chunk in iter(lambda: hf.read(8192), b""):
                                sha256.update(chunk)
                        grouping_key = f"sha256:{sha256.hexdigest()}"
                        is_verified = True
                except (OSError, ValueError, RuntimeError):
                    pass

            if grouping_key:
                if grouping_key not in hash_groups:
                    hash_groups[grouping_key] = {"verified": is_verified, "members": []}
                # Demote verification status if a group mixes confirmed and heuristic hashes
                # (Though with our prefixing, a "quick:" will never match a "sha256:")
                if not is_verified:
                    hash_groups[grouping_key]["verified"] = False
                hash_groups[grouping_key]["members"].append(entry)

        # Phase 3: Collect duplicates
        for h, grp_data in hash_groups.items():
            grp = grp_data["members"]
            is_verified = grp_data["verified"]
            if len(grp) > 1:
                dup_id = f"dup_{hashlib.sha256(h.encode('utf-8')).hexdigest()[:12]}"

                dup_entry = {
                    "duplicate_id": dup_id,
                    "checksum_verified": is_verified,
                    "size_bytes": size,
                    "members": [
                        {
                            "machine_id": snapshot['machine_id'],
                            "root_id": snapshot['root_id'],
                            "rel_path": e['rel_path']
                        } for e in grp
                    ]
                }

                if is_verified:
                    dup_entry["checksum"] = h
                else:
                    dup_entry["quick_hash"] = h.replace("quick:", "", 1) if h.startswith("quick:") else h

                duplicates_list.append(dup_entry)

    duplicates_list.sort(key=lambda x: x['size_bytes'], reverse=True)

    report = {
        "snapshot_id": snapshot_id,
        "analyzed_at": datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat(),
        "duplicate_groups_count": len(duplicates_list),
        "total_wasted_bytes": sum(g['size_bytes'] * (len(g['members']) - 1) for g in duplicates_list),
        "duplicates": duplicates_list
    }

    # Output to snapshot directory and update registry
    snapshot_dir = resolve_snapshot_dir(base_dir, snapshot['machine_id'], snapshot['root_id'], snapshot_id)
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    duplicates_path = snapshot_dir / "duplicates.json"

    # Write atomically
    fd, temp_path = tempfile.mkstemp(dir=str(snapshot_dir), prefix=".tmp_duplicates.json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, str(duplicates_path))
    except Exception:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        raise

    try:
        dup_ref = duplicates_path.relative_to(base_dir).as_posix()
    except ValueError:
        dup_ref = duplicates_path.as_posix()

    registry_path = Path("atlas/registry/atlas_registry.sqlite").resolve()
    with AtlasRegistry(registry_path) as registry:
        registry.update_snapshot_artifacts(snapshot_id, {"duplicates": dup_ref})

    print(json.dumps(report, indent=2))
    return 0

def run_atlas_history(args: argparse.Namespace) -> int:
    registry_path = Path("atlas/registry/atlas_registry.sqlite").resolve()
    atlas_base = resolve_atlas_base_dir(registry_path)
    try:
        with AtlasRegistry(registry_path) as registry:
            snapshots = registry.list_snapshots()

        snapshots = [s for s in snapshots if s["status"] == "complete" and s["machine_id"] == args.machine_id and s["root_id"] == args.root_id]

        if not snapshots:
            print(f"No complete snapshots found for machine '{args.machine_id}' and root '{args.root_id}'", file=sys.stderr)
            return 1

        print(f"History for '{args.rel_path}' on machine '{args.machine_id}', root '{args.root_id}':")
        # Reverse to get chronological order (oldest first) since list_snapshots returns DESC
        snapshots.reverse()

        last_seen = None
        for snap in snapshots:
            inv_ref = snap.get("inventory_ref")
            if not inv_ref:
                print(f"Warning: Snapshot '{snap['snapshot_id']}' has no inventory_ref. Skipping.", file=sys.stderr)
                continue
            inv_path = resolve_artifact_ref(atlas_base, inv_ref)
            if not inv_path.exists():
                print(f"Warning: Inventory file '{inv_path}' for snapshot '{snap['snapshot_id']}' not found. Skipping.", file=sys.stderr)
                continue

            file_data = None
            with open(inv_path, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip(): continue
                    item = json.loads(line)
                    if item.get("rel_path") == args.rel_path:
                        file_data = item
                        break

            if file_data:
                current_state = f"size={file_data.get('size_bytes')}, mtime={file_data.get('mtime')}, symlink={file_data.get('is_symlink')}"
                if last_seen is None:
                    print(f"[{snap['created_at']}] {snap['snapshot_id']}: CREATED ({current_state})")
                elif last_seen != current_state:
                    print(f"[{snap['created_at']}] {snap['snapshot_id']}: MODIFIED ({current_state})")
                else:
                    print(f"[{snap['created_at']}] {snap['snapshot_id']}: UNCHANGED")
                last_seen = current_state
            else:
                if last_seen is not None:
                    print(f"[{snap['created_at']}] {snap['snapshot_id']}: DELETED")
                last_seen = None

        return 0
    except Exception as e:
        print(f"Error computing history: {e}", file=sys.stderr)
        return 1


def run_atlas_scan(args: argparse.Namespace) -> int:
    try:
        raw_path = os.path.expanduser(args.path)
        norm_path = os.path.normpath(raw_path)

        if not os.path.isabs(norm_path) and not args.path.startswith(('/', '\\')):
            print("Error: Path must be absolute.", file=sys.stderr)
            return 1

        # Avoid .resolve() to maintain semantic parity with backend app.py
        # (which drops resolve() to dodge CodeQL path injection sinks on user input)
        scan_root = Path(norm_path)

        exclude_globs = []
        if args.exclude:
            exclude_globs = [x.strip() for x in args.exclude.split(",") if x.strip()]

        if args.no_max_file_size:
            max_file_size = None
        else:
            max_file_size = 50 * 1024 * 1024 # default
            if args.max_file_size is not None:
                max_file_size = args.max_file_size * 1024 * 1024

        # Setup Registry
        registry_path = Path("atlas/registry/atlas_registry.sqlite").resolve()
        atlas_base = resolve_atlas_base_dir(registry_path)
        registry = AtlasRegistry(registry_path)

        # Register Machine
        host_arg = getattr(args, "hostname", None)
        hostname = host_arg if host_arg is not None else socket.gethostname()

        mach_arg = getattr(args, "machine_id", None)
        machine_id = mach_arg if mach_arg is not None else os.environ.get("ATLAS_MACHINE_ID", hostname)

        machine_id = machine_id.strip().lower()
        machine_id = registry.register_machine(machine_id, hostname)

        # Register Root
        # Ensure we always use absolute path as canonical value
        root_value = str(scan_root)
        root_hash = hashlib.md5(root_value.encode("utf-8"), usedforsecurity=False).hexdigest()[:8] # nosec B303

        explicit_root_id = getattr(args, "root_id", None)
        explicit_root_label = getattr(args, "root_label", None)

        if explicit_root_id is not None:
            if explicit_root_id.strip() == "":
                print("Error: root-id cannot be explicitly empty.", file=sys.stderr)
                return 1
            root_id = explicit_root_id.strip()
            if not re.match(r"^[A-Za-z0-9._-]+$", root_id) or root_id in [".", ".."]:
                print(f"Error: explicit root-id '{root_id}' is invalid. It must be filesystem-safe, matching ^[A-Za-z0-9._-]+$ and cannot be '.' or '..'.", file=sys.stderr)
                return 1
        else:
            safe_name = re.sub(r'[^A-Za-z0-9._-]', '-', scan_root.name)
            safe_name = safe_name.strip('-')
            if not safe_name or safe_name in ['.', '..']:
                safe_name = 'root'
            root_id = f"{machine_id}__{safe_name}_{root_hash}"

        if explicit_root_label is not None:
            if explicit_root_label.strip() == "":
                print("Error: root-label cannot be explicitly empty.", file=sys.stderr)
                return 1
            root_label = explicit_root_label.strip()
        else:
            safe_label = scan_root.name.strip().lower()
            if not safe_label:
                anchor = (scan_root.drive or scan_root.anchor or "").strip().lower()
                safe_label = re.sub(r'[^a-z0-9]', '', anchor)
                if not safe_label:
                    safe_label = "root"
            root_label = re.sub(r'\s+', '-', safe_label)

        try:
            registry.register_root(root_id, machine_id, "abs_path", root_value, label=root_label)
        except ValueError as e:
            print(f"Error during root registration: {e}", file=sys.stderr)
            return 1

        # Configure Snapshot Identity
        timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")

        # Determine effective scan config hash BEFORE instantiating Scanner
        # so we can pass it down for proper cache invalidation.
        temp_scanner = AtlasScanner(root=scan_root, exclude_globs=exclude_globs if exclude_globs else None, no_default_excludes=args.no_default_excludes, max_file_size=max_file_size)
        eff_excludes = temp_scanner.exclude_globs
        eff_ex_str = ",".join(sorted(eff_excludes))
        config_str = f"mode={args.mode}|depth={args.depth}|limit={args.limit}|ex={eff_ex_str}|maxfs={max_file_size}"
        short_hash = hashlib.md5(config_str.encode("utf-8"), usedforsecurity=False).hexdigest()[:8] # nosec B303

        incremental_inventory = None
        incremental_dirs_inventory = None
        previous_scan_config_hash = None
        if args.incremental:
            snapshots = registry.list_snapshots()
            # Find the latest complete snapshot for this root
            latest_snap = next((s for s in snapshots if s["status"] == "complete" and s["machine_id"] == machine_id and s["root_id"] == root_id), None)
            if latest_snap:
                previous_scan_config_hash = latest_snap.get("scan_config_hash")
                if latest_snap.get("inventory_ref"):
                    inv_path = resolve_artifact_ref(atlas_base, latest_snap["inventory_ref"])
                    if inv_path.exists():
                        incremental_inventory = inv_path
                    else:
                        print(f"Warning: Incremental requested, but previous inventory file not found: {inv_path}", file=sys.stderr)
                if latest_snap.get("dirs_ref"):
                    dirs_path = resolve_artifact_ref(atlas_base, latest_snap["dirs_ref"])
                    if dirs_path.exists():
                        incremental_dirs_inventory = dirs_path
                    else:
                        print(f"Warning: Incremental requested, but previous dirs file not found: {dirs_path}", file=sys.stderr)
            else:
                print("Warning: Incremental requested, but no complete prior snapshot found for this root.", file=sys.stderr)

        scanner = AtlasScanner(
            root=scan_root,
            max_depth=args.depth,
            max_entries=args.limit,
            exclude_globs=exclude_globs if exclude_globs else None,
            no_default_excludes=args.no_default_excludes,
            max_file_size=max_file_size,
            snapshot_id=None, # Will inject directly later once hash is computed
            enable_content_stats=(args.mode == "content"),
            incremental_inventory=incremental_inventory,
            incremental_dirs_inventory=incremental_dirs_inventory,
            previous_scan_config_hash=previous_scan_config_hash,
            current_scan_config_hash=short_hash
        )


        snapshot_id = f"snap_{machine_id}__{root_id}__{timestamp}__{short_hash}"
        scanner.snapshot_id = snapshot_id

        registry.create_snapshot(snapshot_id, machine_id, root_id, short_hash, "running")

        def _do_scan():
            # Set up correct directory structure based on Atlas Blaupause
            snapshot_dir = resolve_snapshot_dir(atlas_base, machine_id, root_id, snapshot_id)
            snapshot_dir.mkdir(parents=True, exist_ok=True)

            planned_outputs = plan_atlas_outputs(args.mode, scan_id=None)

            # Map the planned outputs to the full paths, but let planner just return file names
            planned_paths = {k: snapshot_dir / v for k, v in planned_outputs.items()}

            # For the registry, we'll store the relative path from the canonical atlas base
            # so the SQLite index references the files correctly regardless of CWD.
            registry_artifacts = {}
            for k, v in planned_paths.items():
                try:
                    registry_artifacts[k] = str(v.relative_to(atlas_base))
                except ValueError:
                    # Fallback to absolute if it's not under atlas_base
                    registry_artifacts[k] = str(v)

            print(f"Scanning: {scan_root} (Mode: {args.mode})")
            print("This may take a while depending on the filesystem...")

            inventory_path = planned_paths.get("inventory")
            dirs_path = planned_paths.get("dirs")

            def _progress_callback(files: int, dirs: int, bytes_total: int):
                registry.update_snapshot_progress(snapshot_id, files, dirs, bytes_total)

            result = scanner.scan(inventory_file=inventory_path, dirs_inventory_file=dirs_path, on_progress=_progress_callback)

            # Write core stats JSON (always)
            out_json = snapshot_dir / "snapshot_meta.json"
            with open(out_json, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2)

            # Render summary MD
            md_content = render_atlas_md(result)
            out_md = planned_paths["summary"]
            with open(out_md, "w", encoding="utf-8") as f:
                f.write(md_content)

            # Additional structural outputs
            write_mode_outputs(planned_outputs, result, snapshot_dir)

            # Write artifacts before updating the registry status to complete
            registry.update_snapshot_artifacts(snapshot_id, registry_artifacts)
            # Registry is canonical for CLI lifecycle — mark complete here.
            registry.update_snapshot_status(snapshot_id, "complete")

            print(f"Done. Outputs generated for mode '{args.mode}':")
            for k, v in registry_artifacts.items():
                print(f" - {k}: {v}")

            print(f"\nSummary preview:\n{md_content}")

        run_scan_lifecycle(
            scan_fn=_do_scan,
            mark_failed=lambda msg: registry.update_snapshot_status(snapshot_id, "failed", error_message=msg),
            is_still_running=lambda: (registry.get_snapshot(snapshot_id) or {}).get("status") == "running",
            label=f"cli-scan:{snapshot_id}",
        )
        return 0

    except Exception as e:
        print(f"Error during scan: {e}", file=sys.stderr)
        return 1
    finally:
        if 'registry' in locals() and registry:
            registry.close()

def _run_analyze_disk(snapshot_id: str) -> int:
    from merger.lenskit.atlas.registry import AtlasRegistry
    from merger.lenskit.atlas.paths import resolve_atlas_base_dir, resolve_artifact_ref, resolve_snapshot_dir

    registry_path = Path("atlas/registry/atlas_registry.sqlite").resolve()
    with AtlasRegistry(registry_path) as registry:
        snapshot = registry.get_snapshot(snapshot_id)
        if not snapshot:
            print(f"Error: Snapshot '{snapshot_id}' not found.", file=sys.stderr)
            return 1

        if snapshot['status'] != 'complete':
            print(f"Error: Snapshot '{snapshot_id}' is not complete.", file=sys.stderr)
            return 1

        root = registry.get_root(snapshot['root_id'])
        if not root:
            print(f"Error: Root '{snapshot['root_id']}' not found.", file=sys.stderr)
            return 1

    if not snapshot.get('inventory_ref'):
        print(f"Error: Snapshot '{snapshot_id}' has no inventory_ref. Cannot analyze disk.", file=sys.stderr)
        return 1

    base_dir = resolve_atlas_base_dir(registry_path)
    inv_path = resolve_artifact_ref(base_dir, snapshot['inventory_ref'])
    if not inv_path.exists():
        print(f"Error: Inventory file '{inv_path}' not found.", file=sys.stderr)
        return 1

    dirs_path = None
    if snapshot.get('dirs_ref'):
        d_path = resolve_artifact_ref(base_dir, snapshot['dirs_ref'])
        if d_path.exists():
            dirs_path = d_path

    largest_files = []
    oldest_files = []
    total_files = 0
    total_bytes = 0

    with open(inv_path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip(): continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue

            # Skip symlinks for strict file size counting if desired,
            # but usually they are 0 or small. We keep them but they won't make largest files.

            size = item.get("size_bytes", 0)
            if not isinstance(size, int) or size < 0:
                size = 0
            mtime = item.get("mtime")
            rel_path = item.get("rel_path", "")

            total_files += 1
            total_bytes += size

            largest_files.append({"path": rel_path, "size": size})
            if mtime:
                oldest_files.append({"path": rel_path, "mtime": mtime})

            # Keep only top N to save memory
            if len(largest_files) > 1000:
                largest_files.sort(key=lambda x: x["size"], reverse=True)
                largest_files = largest_files[:100]

            if len(oldest_files) > 1000:
                oldest_files.sort(key=lambda x: x["mtime"])
                oldest_files = oldest_files[:100]

    # Final sort
    largest_files.sort(key=lambda x: x["size"], reverse=True)
    largest_files = largest_files[:50]

    oldest_files.sort(key=lambda x: x["mtime"])
    oldest_files = oldest_files[:50]

    largest_dirs = []
    most_populated_dirs = []

    if dirs_path:
        with open(dirs_path, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip(): continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue

                size = item.get("subtree_total_bytes", item.get("recursive_bytes", 0))
                if not isinstance(size, int) or size < 0:
                    size = 0
                count = item.get("subtree_file_count", item.get("n_files", item.get("kept_file_count", 0)))
                if not isinstance(count, int) or count < 0:
                    count = 0
                rel_path = item.get("rel_path", "")

                largest_dirs.append({"path": rel_path, "size": size})
                most_populated_dirs.append({"path": rel_path, "count": count})

                if len(largest_dirs) > 1000:
                    largest_dirs.sort(key=lambda x: x["size"], reverse=True)
                    largest_dirs = largest_dirs[:100]
                if len(most_populated_dirs) > 1000:
                    most_populated_dirs.sort(key=lambda x: x["count"], reverse=True)
                    most_populated_dirs = most_populated_dirs[:100]

        largest_dirs.sort(key=lambda x: x["size"], reverse=True)
        largest_dirs = largest_dirs[:50]

        most_populated_dirs.sort(key=lambda x: x["count"], reverse=True)
        most_populated_dirs = most_populated_dirs[:50]

    report = {
        "snapshot_id": snapshot_id,
        "analyzed_at": datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat(),
        "total_files": total_files,
        "total_bytes": total_bytes,
        "largest_files": largest_files,
        "oldest_files": oldest_files,
        "largest_dirs": largest_dirs,
        "most_populated_dirs": most_populated_dirs
    }

    # Output to snapshot directory and update registry
    snapshot_dir = resolve_snapshot_dir(base_dir, snapshot['machine_id'], snapshot['root_id'], snapshot_id)
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    disk_path = snapshot_dir / "disk.json"

    fd, temp_path = tempfile.mkstemp(dir=str(snapshot_dir), prefix=".tmp_disk.json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, str(disk_path))
    except Exception:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        raise

    try:
        rel_disk = disk_path.relative_to(base_dir).as_posix()
    except ValueError:
        rel_disk = disk_path.as_posix()
    with AtlasRegistry(registry_path) as registry:
        registry.update_snapshot_artifacts(snapshot_id, {"disk": rel_disk})

    print(json.dumps(report, indent=2))

    return 0


def _run_analyze_backup_gap(source_snapshot_id: str, backup_snapshot_id: str) -> int:
    from merger.lenskit.atlas.diff import compute_snapshot_comparison


    registry_path = Path("atlas/registry/atlas_registry.sqlite").resolve()
    try:
        with AtlasRegistry(registry_path) as registry:
            source_snap_id = _resolve_snapshot_ref(source_snapshot_id, registry)
            backup_snap_id = _resolve_snapshot_ref(backup_snapshot_id, registry)

            comparison = compute_snapshot_comparison(registry, source_snap_id, backup_snap_id)

            # removed_files means in source (from_snap) but not in backup (to_snap) -> Need to be backed up
            # changed_files means in both but different (size/mtime) -> Need to be updated in backup
            # new_files means in backup (to_snap) but not in source (from_snap) -> Extraneous in backup

            missing_in_backup = comparison.get("removed_files", [])
            outdated_in_backup = comparison.get("changed_files", [])
            extraneous_in_backup = comparison.get("new_files", [])

            report = {
                "source_snapshot": source_snap_id,
                "backup_snapshot": backup_snap_id,
                "analyzed_at": datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat(),
                "summary": {
                    "missing_count": len(missing_in_backup),
                    "outdated_count": len(outdated_in_backup),
                    "extraneous_count": len(extraneous_in_backup)
                },
                "missing": missing_in_backup,
                "outdated": outdated_in_backup,
                "extraneous": extraneous_in_backup
            }

            print(json.dumps(report, indent=2))
            return 0
    except Exception as e:
        print(f"Error computing backup gap: {e}", file=sys.stderr)
        return 1

def _run_analyze_growth(source_snapshot_id: str, target_snapshot_id: str) -> int:
    from merger.lenskit.atlas.diff import _load_inventory_index
    from merger.lenskit.atlas.registry import AtlasRegistry
    from merger.lenskit.atlas.paths import resolve_atlas_base_dir, resolve_artifact_ref
    import datetime

    registry_path = Path("atlas/registry/atlas_registry.sqlite").resolve()
    try:
        with AtlasRegistry(registry_path) as registry:
            source_snap_id = _resolve_snapshot_ref(source_snapshot_id, registry)
            target_snap_id = _resolve_snapshot_ref(target_snapshot_id, registry)

            source_snap = registry.get_snapshot(source_snap_id)
            target_snap = registry.get_snapshot(target_snap_id)

            if not source_snap or not target_snap:
                print("Error: One or both snapshots could not be found.", file=sys.stderr)
                return 1
            if source_snap["status"] != "complete" or target_snap["status"] != "complete":
                print("Error: Snapshots must be complete.", file=sys.stderr)
                return 1

            atlas_base = resolve_atlas_base_dir(registry.db_path)

            source_inv_path = None
            if source_snap["inventory_ref"]:
                source_inv_path = resolve_artifact_ref(atlas_base, source_snap["inventory_ref"])

            target_inv_path = None
            if target_snap["inventory_ref"]:
                target_inv_path = resolve_artifact_ref(atlas_base, target_snap["inventory_ref"])

            if not source_inv_path or not source_inv_path.exists():
                print(f"Error: Inventory missing for source snapshot {source_snap_id}", file=sys.stderr)
                return 1
            if not target_inv_path or not target_inv_path.exists():
                print(f"Error: Inventory missing for target snapshot {target_snap_id}", file=sys.stderr)
                return 1

            source_files = _load_inventory_index(source_inv_path)
            target_files = _load_inventory_index(target_inv_path)

            def _coerce_nonnegative_size_bytes(value: object) -> int:
                if isinstance(value, bool):
                    return 0
                if isinstance(value, int):
                    return value if value >= 0 else 0
                if isinstance(value, str):
                    try:
                        parsed = int(value)
                        return parsed if parsed >= 0 else 0
                    except ValueError:
                        return 0
                return 0

            source_size = sum(_coerce_nonnegative_size_bytes(f.get("size_bytes", 0)) for f in source_files.values())
            target_size = sum(_coerce_nonnegative_size_bytes(f.get("size_bytes", 0)) for f in target_files.values())

            source_count = len(source_files)
            target_count = len(target_files)

            size_delta = target_size - source_size
            count_delta = target_count - source_count

            report = {
                "source_snapshot": source_snap_id,
                "target_snapshot": target_snap_id,
                "analyzed_at": datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat(),
                "metrics": {
                    "source_size_bytes": source_size,
                    "target_size_bytes": target_size,
                    "size_delta_bytes": size_delta,
                    "source_file_count": source_count,
                    "target_file_count": target_count,
                    "file_count_delta": count_delta
                },
                "data_basis": {
                    "source_machine": source_snap["machine_id"],
                    "source_root": source_snap["root_id"],
                    "target_machine": target_snap["machine_id"],
                    "target_root": target_snap["root_id"]
                },
                "limitations": [
                    "Does not track historical trends between these two snapshots.",
                    "Only compares exact file sizes and counts, not semantic file identity.",
                    "Does not account for file moves or renames."
                ]
            }

            print(json.dumps(report, indent=2))
            return 0
    except Exception as e:
        print(f"Error computing growth report: {e}", file=sys.stderr)
        return 1


def register_atlas_commands(subparsers) -> None:
    """Register the `atlas` subparser and its sub-subparsers.

    Single source of truth for Atlas CLI definitions. Both `cli/main.py`
    (lenskit entry point) and `cli/rlens.py` (rLens launcher) consume this
    registrar to prevent argparse drift.
    """
    atlas_parser = subparsers.add_parser("atlas", help="Atlas filesystem crawler")
    atlas_subparsers = atlas_parser.add_subparsers(dest="atlas_cmd", required=True, help="Atlas commands")

    atlas_scan_parser = atlas_subparsers.add_parser("scan", help="Scan a filesystem path")
    atlas_scan_parser.add_argument("path", help="The root path to scan")
    atlas_scan_parser.add_argument("--exclude", help="Comma-separated list of glob patterns to exclude")
    atlas_scan_parser.add_argument("--no-default-excludes", action="store_true", help="Do not use default system excludes")
    atlas_scan_parser.add_argument("--max-file-size", type=int, help="Maximum file size in MB to include in scan (default 50)")
    atlas_scan_parser.add_argument("--no-max-file-size", action="store_true", help="Remove file size limits for the scan")
    atlas_scan_parser.add_argument("--depth", type=int, default=6, help="Maximum depth to scan")
    atlas_scan_parser.add_argument("--limit", type=int, default=200000, help="Maximum number of entries to scan")
    atlas_scan_parser.add_argument("--mode", choices=["inventory", "topology", "content", "workspace"], default="inventory", help="The scan mode to execute")
    atlas_scan_parser.add_argument("--machine-id", help="Explicit machine ID for the registry (defaults to ATLAS_MACHINE_ID env var or hostname)")
    atlas_scan_parser.add_argument("--hostname", help="Explicit hostname for the registry (defaults to system hostname)")
    atlas_scan_parser.add_argument("--root-id", help="Explicit root ID for the registry")
    atlas_scan_parser.add_argument("--root-label", help="Explicit root label for the registry")
    atlas_scan_parser.add_argument("--incremental", action="store_true", help="Perform an incremental scan based on the latest snapshot")

    atlas_subparsers.add_parser("machine-health", help="List registered machines with health status and last seen info")
    atlas_subparsers.add_parser("machines", help="List registered machines")
    atlas_roots_parser = atlas_subparsers.add_parser("roots", help="List registered roots")
    atlas_roots_parser.add_argument("--group-by-label", action="store_true", help="Group output by root_label (human-readable text format)")
    atlas_subparsers.add_parser("snapshots", help="List registered snapshots")

    atlas_diff_parser = atlas_subparsers.add_parser("diff", help="Compute delta between two snapshots")
    atlas_diff_parser.add_argument("from_snapshot", help="The from snapshot ID or machine:root_path")
    atlas_diff_parser.add_argument("to_snapshot", help="The to snapshot ID or machine:root_path")

    atlas_history_parser = atlas_subparsers.add_parser("history", help="Show file history across snapshots")
    atlas_history_parser.add_argument("machine_id", help="The machine ID")
    atlas_history_parser.add_argument("root_id", help="The root ID")
    atlas_history_parser.add_argument("rel_path", help="The canonical relative path of the file")

    atlas_search_parser = atlas_subparsers.add_parser("search", help="Search the atlas registry")
    atlas_search_parser.add_argument("--query", help="General search query")
    atlas_search_parser.add_argument("--machine-id", help="Filter by machine ID")
    atlas_search_parser.add_argument("--root-id", help="Filter by root ID")
    atlas_search_parser.add_argument("--snapshot-id", help="Filter by snapshot ID")
    atlas_search_parser.add_argument("--path", help="Filter by path pattern")
    atlas_search_parser.add_argument("--name", help="Filter by name pattern")
    atlas_search_parser.add_argument("--ext", help="Filter by extension")
    atlas_search_parser.add_argument("--min-size", type=int, help="Filter by minimum size in bytes")
    atlas_search_parser.add_argument("--max-size", type=int, help="Filter by maximum size in bytes")
    atlas_search_parser.add_argument("--date-after", help="Filter by modified date after (ISO format)")
    atlas_search_parser.add_argument("--date-before", help="Filter by modified date before (ISO format)")
    atlas_search_parser.add_argument("--content-query", help="Filter by file content (full text search within matched text files)")

    atlas_analyze_parser = atlas_subparsers.add_parser("analyze", help="Run analysis on a snapshot")
    atlas_analyze_subparsers = atlas_analyze_parser.add_subparsers(dest="analyze_command", required=True)
    atlas_analyze_dups_parser = atlas_analyze_subparsers.add_parser("duplicates", help="Analyze duplicates in a snapshot")
    atlas_analyze_dups_parser.add_argument("snapshot_id", help="The snapshot ID to analyze")

    atlas_analyze_orphans_parser = atlas_analyze_subparsers.add_parser("orphans", help="Analyze orphans in a snapshot")
    atlas_analyze_orphans_parser.add_argument("snapshot_id", help="The snapshot ID to analyze")

    atlas_analyze_disk_parser = atlas_analyze_subparsers.add_parser("disk", help="Analyze disk hotspots and old/large files in a snapshot")
    atlas_analyze_disk_parser.add_argument("snapshot_id", help="The snapshot ID to analyze")

    atlas_analyze_backup_gap_parser = atlas_analyze_subparsers.add_parser("backup-gap", help="Compare two snapshots (source and backup) to find missing, outdated, and extraneous files")
    atlas_analyze_backup_gap_parser.add_argument("source_snapshot", help="The source snapshot ID or reference (machine:path)")
    atlas_analyze_backup_gap_parser.add_argument("backup_snapshot", help="The backup snapshot ID or reference (machine:path)")

    atlas_analyze_growth_parser = atlas_analyze_subparsers.add_parser("growth", help="Analyze cross-root growth and report epistemic boundaries")
    atlas_analyze_growth_parser.add_argument("source_snapshot", help="The source snapshot ID or reference (machine:path)")
    atlas_analyze_growth_parser.add_argument("target_snapshot", help="The target snapshot ID or reference (machine:path)")


# Map of atlas subcommand to the name of its handler function in this module.
# Resolved via getattr at dispatch time so test monkeypatches on module
# attributes (e.g. cmd_atlas.run_atlas_analyze = mock) still take effect.
_ATLAS_DISPATCH = {
    "scan": "run_atlas_scan",
    "machines": "run_atlas_machines",
    "machine-health": "run_atlas_machine_health",
    "roots": "run_atlas_roots",
    "snapshots": "run_atlas_snapshots",
    "diff": "run_atlas_diff",
    "history": "run_atlas_history",
    "search": "run_atlas_search",
    "analyze": "run_atlas_analyze",
}


def handle_atlas_command(args: argparse.Namespace) -> int:
    """Dispatch a parsed `atlas` subcommand to its handler.

    `atlas_cmd` is enforced as required by argparse, so an unknown value
    should never reach this function. We still guard against drift to fail
    loudly rather than silently no-op.
    """
    atlas_cmd = getattr(args, "atlas_cmd", None)
    handler_name = _ATLAS_DISPATCH.get(atlas_cmd)
    if handler_name is None:
        raise RuntimeError(f"Unexpected atlas command dispatch: {atlas_cmd!r}")
    import sys as _sys
    handler = getattr(_sys.modules[__name__], handler_name)
    return handler(args)
