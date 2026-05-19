import json
import sys
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime
import fnmatch

TEXT_DETECTION_MAX_BYTES = 20 * 1024 * 1024

from merger.lenskit.atlas.registry import AtlasRegistry
from merger.lenskit.atlas.paths import resolve_atlas_base_dir, resolve_artifact_ref

def parse_iso_datetime(value: str) -> datetime:
    if value.endswith('Z'):
        value = value[:-1] + '+00:00'
    return datetime.fromisoformat(value)

class AtlasSearch:
    def __init__(self, registry_db_path: Path):
        self.registry_db_path = registry_db_path

    def search(self,
               query: Optional[str] = None,
               machine_id: Optional[str] = None,
               root_id: Optional[str] = None,
               snapshot_id: Optional[str] = None,
               path_pattern: Optional[str] = None,
               name_pattern: Optional[str] = None,
               ext: Optional[str] = None,
               min_size: Optional[int] = None,
               max_size: Optional[int] = None,
               date_after: Optional[str] = None,
               date_before: Optional[str] = None,
               content_query: Optional[str] = None) -> List[Dict[str, Any]]:

        # Open registry to find the appropriate snapshots
        try:
            with AtlasRegistry(self.registry_db_path) as registry:
                snapshots = registry.list_complete_snapshots(
                    machine_id=machine_id,
                    root_id=root_id,
                    snapshot_id=snapshot_id
                )
                roots_cache = {r['root_id']: r for r in registry.list_roots()}
        except Exception as e:
            print(f"[atlas-search] warning: failed to connect to registry {self.registry_db_path}: {e}", file=sys.stderr)
            return []

        if not snapshot_id:
            # Keep only the latest snapshot per root
            # Since order is DESC, the first one encountered per root is the latest
            latest_snapshots = {}
            for s in snapshots:
                if s['root_id'] not in latest_snapshots:
                    latest_snapshots[s['root_id']] = s
            snapshots = list(latest_snapshots.values())

        atlas_base = resolve_atlas_base_dir(self.registry_db_path)
        results = []

        # Parse date filters once
        after_dt = None
        before_dt = None
        try:
            if date_after:
                after_dt = parse_iso_datetime(date_after)
            if date_before:
                before_dt = parse_iso_datetime(date_before)
        except Exception as e:
            print(f"[atlas-search] warning: invalid date filter format: {e}", file=sys.stderr)
            return []

        # If ext doesn't start with '.', add it to match how it's stored
        if ext and not ext.startswith('.'):
            ext = f".{ext}"

        content_query_lower = content_query.lower() if content_query else None

        for snap in snapshots:
            inv_ref = snap.get("inventory_ref")
            if not inv_ref:
                continue

            inv_path = resolve_artifact_ref(atlas_base, inv_ref)
            if not inv_path.exists():
                print(f"[atlas-search] warning: inventory reference not found: {inv_path}", file=sys.stderr)
                continue

            try:
                with open(inv_path, 'r', encoding='utf-8') as f:
                    for line_idx, line in enumerate(f, start=1):
                        if not line.strip():
                            continue

                        try:
                            item = json.loads(line)

                            # Apply filters
                            if path_pattern and not fnmatch.fnmatch(item.get('rel_path', ''), path_pattern):
                                continue

                            if name_pattern and not fnmatch.fnmatch(item.get('name', ''), name_pattern):
                                continue

                            if ext and item.get('ext', '') != ext:
                                continue

                            size = item.get('size_bytes', 0)
                            if min_size is not None and size < min_size:
                                continue

                            if max_size is not None and size > max_size:
                                continue

                            if after_dt or before_dt:
                                mtime = item.get('mtime', '')
                                if not mtime:
                                    continue
                                try:
                                    mtime_dt = parse_iso_datetime(mtime)
                                except Exception:
                                    print(f"[atlas-search] warning: invalid timestamp format '{mtime}' in {inv_path}:{line_idx}", file=sys.stderr)
                                    continue

                                if after_dt and mtime_dt < after_dt:
                                    continue
                                if before_dt and mtime_dt > before_dt:
                                    continue

                            # Basic content/query match (search in name or path if query provided)
                            if query:
                                q_lower = query.lower()
                                name_lower = item.get('name', '').lower()
                                path_lower = item.get('rel_path', '').lower()
                                if q_lower not in name_lower and q_lower not in path_lower:
                                    continue

                            if content_query:
                                root = roots_cache.get(snap['root_id'])
                                if not root:
                                    continue
                                root_val = root.get('root_value')
                                if not root_val:
                                    continue

                                # Guard 1: Skip if inventory explicitly says it's a symlink
                                if item.get('is_symlink'):
                                    continue

                                # Safe path resolution to prevent traversal
                                root_path = Path(root_val).resolve()
                                rel_path = item.get('rel_path', '')

                                # Guard 2: Form candidate path and check it before resolve
                                candidate_path = root_path / rel_path

                                try:
                                    if candidate_path.is_symlink():
                                        continue
                                except OSError:
                                    # Defensively handle file system access errors
                                    continue

                                try:
                                    # strict=False because it might be a broken symlink or deleted file
                                    full_path = candidate_path.resolve(strict=False)
                                    # Must be strictly within root
                                    full_path.relative_to(root_path)
                                except (ValueError, OSError, RuntimeError):
                                    # Escaped the root directory or file system error
                                    continue

                                # Guard 3: Ensure the resolved file actually exists and didn't become a symlink mid-flight
                                try:
                                    if not full_path.is_file() or full_path.is_symlink():
                                        continue
                                except OSError:
                                    continue

                                # Apply limits
                                size = item.get('size_bytes', 0)
                                if size > TEXT_DETECTION_MAX_BYTES:
                                    continue

                                # Verify text
                                is_text_flag = item.get('is_text')
                                if is_text_flag is False:
                                    continue

                                if is_text_flag is None:
                                    # Heuristic
                                    from merger.lenskit.adapters.atlas import is_probably_text
                                    if not is_probably_text(full_path, size):
                                        continue

                                # Read content and check for query iteratively (line-by-line)
                                try:
                                    matched = False
                                    snippet = ""
                                    with open(full_path, 'r', encoding='utf-8', errors='replace') as f_content:
                                        for line in f_content:
                                            if content_query_lower in line.lower():
                                                matched = True
                                                snippet = line.strip()
                                                if len(snippet) > 200:
                                                    snippet = snippet[:197] + "..."
                                                break
                                    if not matched:
                                        continue

                                    if snippet:
                                        item['content_snippet'] = snippet
                                except Exception:
                                    # Ignore files we cannot read for content search
                                    continue

                            # Enrich result with snapshot context
                            result_item = dict(item)
                            result_item['machine_id'] = snap['machine_id']
                            result_item['root_id'] = snap['root_id']
                            result_item['snapshot_id'] = snap['snapshot_id']

                            results.append(result_item)

                        except (json.JSONDecodeError, KeyError, TypeError) as e:
                            print(f"[atlas-search] warning: invalid inventory record in {inv_path} at line {line_idx}: {e}", file=sys.stderr)
            except (OSError, UnicodeDecodeError) as e:
                print(f"[atlas-search] warning: failed to read inventory {inv_path}: {e}", file=sys.stderr)

        return results
