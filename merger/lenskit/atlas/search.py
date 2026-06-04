import json
import sys
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
import fnmatch

from merger.lenskit.atlas.registry import AtlasRegistry
from merger.lenskit.atlas.paths import resolve_atlas_base_dir, resolve_artifact_ref, resolve_index_db_path

TEXT_DETECTION_MAX_BYTES = 20 * 1024 * 1024

def parse_iso_datetime(value: str) -> datetime:
    if value.endswith('Z'):
        value = value[:-1] + '+00:00'
    return datetime.fromisoformat(value)


def _content_match(root_value: str, item: Dict[str, Any], content_query_lower: str) -> Tuple[bool, Optional[str]]:
    """Confirm a content-query substring match against the live file and build a snippet.

    Returns (matched, snippet). This preserves the exact semantics of the
    original best-effort live-filesystem content search (case-insensitive
    substring on a single line, first match wins, snippet trimmed to 200 chars)
    while being reusable by both the legacy and index-backed search paths.
    """
    if not root_value:
        return False, None

    # Guard 1: skip declared symlinks
    if item.get('is_symlink'):
        return False, None

    root_path = Path(root_value).resolve()
    rel_path = item.get('rel_path', '')
    candidate_path = root_path / rel_path

    try:
        if candidate_path.is_symlink():
            return False, None
    except OSError:
        return False, None

    try:
        full_path = candidate_path.resolve(strict=False)
        full_path.relative_to(root_path)
    except (ValueError, OSError, RuntimeError):
        return False, None

    try:
        if not full_path.is_file() or full_path.is_symlink():
            return False, None
    except OSError:
        return False, None

    size = item.get('size_bytes', 0)
    if size > TEXT_DETECTION_MAX_BYTES:
        return False, None

    is_text_flag = item.get('is_text')
    if is_text_flag is False:
        return False, None
    if is_text_flag is None:
        from merger.lenskit.adapters.atlas import is_probably_text
        if not is_probably_text(full_path, size):
            return False, None

    try:
        with open(full_path, 'r', encoding='utf-8', errors='replace') as f_content:
            for line in f_content:
                if content_query_lower in line.lower():
                    snippet = line.strip()
                    if len(snippet) > 200:
                        snippet = snippet[:197] + "..."
                    return True, snippet
    except Exception:
        return False, None

    return False, None


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
               content_query: Optional[str] = None,
               all_snapshots: bool = False,
               use_index: bool = True) -> List[Dict[str, Any]]:

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

        if not snapshot_id and not all_snapshots:
            # Keep only the latest snapshot per root (DESC order => first wins).
            latest_snapshots = {}
            for s in snapshots:
                if s['root_id'] not in latest_snapshots:
                    latest_snapshots[s['root_id']] = s
            snapshots = list(latest_snapshots.values())

        # Parse date filters once (shared by both paths).
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

        # Normalize ext to match how it's stored (leading dot).
        if ext and not ext.startswith('.'):
            ext = f".{ext}"

        content_query_lower = content_query.lower() if content_query else None

        # Prefer the FTS index when it exists and covers every candidate snapshot.
        if use_index:
            index_results = self._try_index_search(
                snapshots, roots_cache, query, path_pattern, name_pattern, ext,
                min_size, max_size, after_dt, before_dt, content_query, content_query_lower,
            )
            if index_results is not None:
                return index_results

        return self._search_linear(
            snapshots, roots_cache, query, path_pattern, name_pattern, ext,
            min_size, max_size, after_dt, before_dt, content_query, content_query_lower,
        )

    # ------------------------------------------------------------------
    # Index-backed path
    # ------------------------------------------------------------------
    def _try_index_search(self, snapshots, roots_cache, query, path_pattern, name_pattern,
                          ext, min_size, max_size, after_dt, before_dt,
                          content_query, content_query_lower) -> Optional[List[Dict[str, Any]]]:
        index_path = resolve_index_db_path(self.registry_db_path)
        if not index_path.exists():
            return None

        from merger.lenskit.atlas.index import AtlasFTSIndex

        snapshot_ids = [s['snapshot_id'] for s in snapshots]
        snap_by_id = {s['snapshot_id']: s for s in snapshots}

        try:
            with AtlasFTSIndex(index_path) as idx:
                # The index can only answer authoritatively if it fully and
                # consistently covers all candidate snapshots; otherwise defer to
                # the linear fallback.
                if any(not idx.snapshot_coverage_ok(sid) for sid in snapshot_ids):
                    return None

                after_epoch = after_dt.timestamp() if after_dt else None
                before_epoch = before_dt.timestamp() if before_dt else None

                # For content queries, never restrict via FTS content candidates:
                # the FTS content column is frozen at index time and can be
                # stale if the live file mutates after indexing.  Using it as a
                # hard pre-filter would produce false negatives (the live
                # _content_match confirmation is never reached for excluded files).
                # Instead, all metadata-filtered candidates are live-scanned by
                # _content_match below, keeping FTS content as prepared structure
                # only (potential future accelerator, not a gate).
                rows = idx.query_metadata(
                    snapshot_ids, ext=ext, min_size=min_size, max_size=max_size,
                    after_epoch=after_epoch, before_epoch=before_epoch,
                )
        except Exception as e:
            print(f"[atlas-search] warning: index search failed, falling back to linear scan: {e}", file=sys.stderr)
            return None

        results: List[Dict[str, Any]] = []
        for row in rows:
            try:
                item = json.loads(row['raw_json'])
            except (json.JSONDecodeError, TypeError):
                continue

            if not self._passes_name_filters(item, query, path_pattern, name_pattern):
                continue

            if content_query:
                snap = snap_by_id.get(row['snapshot_id'])
                root = roots_cache.get(snap['root_id']) if snap else None
                root_val = root.get('root_value') if root else None
                if not root_val:
                    continue
                matched, snippet = _content_match(root_val, item, content_query_lower)
                if not matched:
                    continue
                if snippet:
                    item['content_snippet'] = snippet

            result_item = dict(item)
            result_item['machine_id'] = row['machine_id']
            result_item['root_id'] = row['root_id']
            result_item['snapshot_id'] = row['snapshot_id']
            results.append(result_item)

        return results

    @staticmethod
    def _passes_name_filters(item, query, path_pattern, name_pattern) -> bool:
        if path_pattern and not fnmatch.fnmatch(item.get('rel_path', ''), path_pattern):
            return False
        if name_pattern and not fnmatch.fnmatch(item.get('name', ''), name_pattern):
            return False
        if query:
            q_lower = query.lower()
            name_lower = item.get('name', '').lower()
            path_lower = item.get('rel_path', '').lower()
            if q_lower not in name_lower and q_lower not in path_lower:
                return False
        return True

    # ------------------------------------------------------------------
    # Legacy linear path (fallback when index is absent or incomplete)
    # ------------------------------------------------------------------
    def _search_linear(self, snapshots, roots_cache, query, path_pattern, name_pattern,
                       ext, min_size, max_size, after_dt, before_dt,
                       content_query, content_query_lower) -> List[Dict[str, Any]]:
        atlas_base = resolve_atlas_base_dir(self.registry_db_path)
        results: List[Dict[str, Any]] = []

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

                            if not self._passes_name_filters(item, query, path_pattern, name_pattern):
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

                            if content_query:
                                root = roots_cache.get(snap['root_id'])
                                if not root:
                                    continue
                                root_val = root.get('root_value')
                                if not root_val:
                                    continue
                                matched, snippet = _content_match(root_val, item, content_query_lower)
                                if not matched:
                                    continue
                                if snippet:
                                    item['content_snippet'] = snippet

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
