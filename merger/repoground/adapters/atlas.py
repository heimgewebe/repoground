import os
import logging
import time
import json
import hashlib
from pathlib import Path
from typing import List, Dict, Any, Optional, Pattern, Union, Tuple, Callable
from datetime import datetime, timezone
import fnmatch
import re
import mimetypes

# Attempt to import is_probably_text from core to avoid duplication
try:
    from ..core.merge import is_probably_text
except ImportError:
    # Fallback implementation if core is not accessible
    # Configurable text detection limit (aligned with core's 20MB)
    TEXT_DETECTION_MAX_BYTES = 20 * 1024 * 1024

    def is_probably_text(path: Path, size: int) -> bool:
        TEXT_EXTENSIONS = {
            ".md", ".txt", ".py", ".rs", ".ts", ".js", ".json", ".yml", ".yaml",
            ".sh", ".html", ".css", ".xml", ".csv", ".log", ".lock", ".gitignore",
            ".toml", ".ini", ".conf", ".dockerfile", "dockerfile", ".bat", ".cmd"
        }
        if path.suffix.lower() in TEXT_EXTENSIONS or path.name.lower() in TEXT_EXTENSIONS:
            return True
        if size > TEXT_DETECTION_MAX_BYTES:
            return False
        try:
            with path.open("rb") as f:
                chunk = f.read(4096)
                if not chunk:
                    return True
                return b"\x00" not in chunk
        except OSError:
            return False

def detect_mime_type(path: Path) -> Optional[str]:
    """
    Best-effort MIME type detection.

    Uses `mimetypes.guess_type`, whose results may vary depending on platform and
    configuration. Falls back to a small set of magic-byte checks and a simple
    text/binary heuristic.

    This implementation is intentionally heuristic and only partially hardened.
    It should be treated as a best-effort classification rather than a fully
    reliable or reproducible MIME identification.
    """
    mime_type, _ = mimetypes.guess_type(str(path))

    # If mimetypes can't guess or returns a generic type, check magic bytes
    if not mime_type or mime_type == 'application/octet-stream':
        try:
            with path.open('rb') as f:
                head = f.read(512)

            if not head:
                return "inode/x-empty"

            # Basic magic byte signatures
            if head.startswith(b'%PDF-'):
                return 'application/pdf'
            elif head.startswith(b'\x89PNG\r\n\x1a\n'):
                return 'image/png'
            elif head.startswith(b'\xff\xd8\xff'):
                return 'image/jpeg'
            elif head.startswith(b'GIF87a') or head.startswith(b'GIF89a'):
                return 'image/gif'
            elif head.startswith(b'PK\x03\x04'):
                return 'application/zip'
            elif head.startswith(b'\x1f\x8b\x08'):
                return 'application/gzip'
            elif head.startswith(b'Rar!\x1a\x07\x00') or head.startswith(b'Rar!\x1a\x07\x01\x00'):
                return 'application/x-rar-compressed'
            elif head.startswith(b'\x00\x00\x00\x18ftyp') or head.startswith(b'\x00\x00\x00 ftyp'):
                return 'video/mp4'
            elif b'ftypmp42' in head[:16] or b'ftypisom' in head[:16]:
                return 'video/mp4'
            elif head.startswith(b'\x1aE\xdf\xa3'):
                return 'video/webm'

            # If we still don't know, use the null byte heuristic for text vs binary
            if b'\x00' in head:
                return 'application/octet-stream'
            else:
                return 'text/plain'
        except OSError:
            return None

    return mime_type


TEXT_MIME_ALLOWLIST = {
    "application/json",
    "application/xml",
    "application/javascript",
    "image/svg+xml"
}

def count_lines(path: Path, size: int, encoding: Optional[str] = None) -> Optional[int]:
    """
    Best-effort line count detection.

    Reads the file line-by-line to avoid loading large files into memory.
    Skips files larger than 20MB to prevent heavy I/O.
    Uses the provided encoding, or falls back to utf-8.
    """
    if size > 20 * 1024 * 1024:
        return None

    enc = encoding if encoding else "utf-8"
    try:
        count = 0
        with path.open("r", encoding=enc, errors="replace") as f:
            for _ in f:
                count += 1
        return count
    except OSError:
        return None


def detect_encoding(path: Path) -> Optional[str]:
    """
    Best-effort encoding detection.

    Reads the first 4096 bytes and attempts to decode it using a few common encodings.
    """
    try:
        with path.open("rb") as f:
            chunk = f.read(4096)

        if not chunk:
            return "utf-8"  # Empty files are technically valid utf-8

        # Try a few common encodings in order of likelihood
        for enc in ["utf-8", "utf-16", "windows-1252", "iso-8859-1"]:
            try:
                chunk.decode(enc)
                return enc
            except UnicodeDecodeError:
                continue

        return None  # Couldn't reliably detect
    except OSError:
        return None


logger = logging.getLogger(__name__)


def allocated_bytes_from_stat(stat_result: os.stat_result) -> int:
    """Return filesystem blocks in bytes, falling back to apparent size.

    POSIX ``st_blocks`` is defined in 512-byte units and reflects allocated
    storage for sparse files.  Platforms without that field retain the legacy
    apparent-size semantics rather than reporting a fabricated zero.
    """
    blocks = getattr(stat_result, "st_blocks", None)
    if isinstance(blocks, int) and blocks >= 0:
        return blocks * 512
    return max(0, int(stat_result.st_size))


# Heuristic threshold (in files) for the file-count-based progress gate.
# The scanner fires on_progress when this many *new* files have been seen
# since the last emit, even if the time-based 1-second gate has not elapsed.
# This prevents false ``is_stalled`` flags on large directories where a
# single os.walk() iteration takes > 60 s.
#
# The value 1000 is a pragmatic heuristic — large enough to avoid IO storms,
# small enough to keep stall detection responsive on big monorepos.  It is
# deliberately NOT configurable in this version; a future PR may promote it
# to a tunable if real-world usage demands it.
_PROGRESS_FILE_COUNT_THRESHOLD = 1000

class AtlasScanner:
    DEFAULT_ATLAS_EXCLUDES = (
        "proc/**",
        "sys/**",
        "dev/**",
        "run/**",
        "tmp/**",
        "var/tmp/**",
        "var/run/**",
        "lost+found/**",
        "**/core",
        "**/core.[0-9]*",
        "**/*.core"
    )

    WORKSPACE_SIGNALS = (
        ".ai-context.yml",
        "pyproject.toml",
        "requirements.txt",
        "package.json",
        "compose.yml",
        "docker-compose.yml",
        "README.md"
    )

    @staticmethod
    def _load_jsonl_inventory_map(source: Optional[Union[Dict[str, Any], Path]], inventory_label: str, entry_label: str) -> Dict[str, Any]:
        result = {}
        if not source:
            return result
        if isinstance(source, Path):
            try:
                with source.open("r", encoding="utf-8") as f:
                    for line_idx, line in enumerate(f, start=1):
                        if not line.strip():
                            continue
                        try:
                            item = json.loads(line)
                            rel_path = item.get("rel_path")
                            if not isinstance(rel_path, str):
                                raise TypeError(f"rel_path must be string, got {type(rel_path).__name__}")
                            result[rel_path] = item
                        except (json.JSONDecodeError, KeyError, TypeError) as e:
                            logger.warning("Malformed %s at %s:%d. Error: %s - %s. Skipping.", entry_label, source, line_idx, type(e).__name__, e)
            except OSError as e:
                logger.warning("Failed to load %s from %s: %s", inventory_label, source, e)
        elif isinstance(source, dict):
            result = source
        return result

    def __init__(self, root: Path, max_depth: int = 6, max_entries: int = 200000,
                 exclude_globs: List[str] = None, inventory_strict: bool = False,
                 no_default_excludes: bool = False, max_file_size: Optional[int] = 50 * 1024 * 1024,
                 snapshot_id: Optional[str] = None, compare_to_snapshot_id: Optional[str] = None,
                 enable_content_stats: bool = False,
                 incremental_inventory: Optional[Union[Dict[str, Any], Path]] = None,
                 incremental_dirs_inventory: Optional[Union[Dict[str, Any], Path]] = None,
                 previous_scan_config_hash: Optional[str] = None,
                 current_scan_config_hash: Optional[str] = None):
        self.root = root
        self.max_depth = max_depth
        self.max_entries = max_entries
        self.inventory_strict = inventory_strict

        if max_file_size is not None and max_file_size <= 0:
            raise ValueError("max_file_size must be a positive integer or None.")
        self.max_file_size = max_file_size
        self.snapshot_id = snapshot_id
        self.compare_to_snapshot_id = compare_to_snapshot_id
        self.enable_content_stats = enable_content_stats
        self.previous_scan_config_hash = previous_scan_config_hash
        self.current_scan_config_hash = current_scan_config_hash

        # If the scan configuration has changed, we must ignore content analysis from the previous inventory
        self.config_changed = False
        if self.previous_scan_config_hash and self.current_scan_config_hash:
            if self.previous_scan_config_hash != self.current_scan_config_hash:
                self.config_changed = True

        self.incremental_inventory = self._load_jsonl_inventory_map(incremental_inventory, "incremental inventory", "incremental inventory")
        self.incremental_dirs_inventory = self._load_jsonl_inventory_map(incremental_dirs_inventory, "incremental dirs inventory", "incremental dirs")

        if self.inventory_strict:
            # Minimal excludes for strict inventory: git directories, venv directories, and
            # .claude/worktrees (agent runtime checkouts). Runtime checkouts are never canonical
            # repository content and must be excluded even in strict mode.
            default_excludes = ["**/.git", "**/.venv", "**/.claude/worktrees/**"]
        else:
            # .claude/worktrees contains agent runtime checkouts; must not be treated as repository content.
            default_excludes = ["**/.git", "**/node_modules", "**/.venv", "**/__pycache__", "**/.cache", "atlas/**", "**/.pytest_cache", "**/.claude/worktrees/**"]

        self.exclude_globs = list(exclude_globs) if exclude_globs is not None else list(default_excludes)
        if not no_default_excludes:
            self.exclude_globs.extend(self.DEFAULT_ATLAS_EXCLUDES)

        self._exclude_patterns = self._build_exclude_patterns(self.exclude_globs)
        self._exclude_regex = self._compile_exclude_regex(self._exclude_patterns)
        # ── Stats: final result counters ──
        # total_files / total_dirs / total_bytes are *result* fields: they
        # hold definitive totals only after scan() returns.  During the scan
        # they accumulate incrementally and are forwarded to the on_progress
        # callback as "files_seen / dirs_seen / bytes_seen" in the caller's
        # persistence layer (registry or JSON).
        self.stats = {
            "total_files": 0,     # result: definitive file count after scan completes
            "total_dirs": 0,      # result: definitive directory count after scan completes
            "total_bytes": 0,     # compatibility: apparent/logical byte sum
            "total_allocated_bytes": 0,  # filesystem blocks, or apparent-size fallback
            "sparse_files_count": 0,
            "sparse_apparent_bytes": 0,
            "sparse_allocated_bytes": 0,
            "allocation_basis": "st_blocks_512_or_apparent_fallback",
            "start_time": None,
            "end_time": None,
            "duration_seconds": 0,
            "extensions": {},
            "top_dirs": [],  # List of {"path": str, "bytes": int}
            "repo_nodes": [], # List of paths that look like git repos
            "workspaces": [], # List of {"workspace_id": str, "root_path": str, ...}
            # Placeholders for higher-level processing or specific scan modes
            "hotspots": {},
            "topology": {},
            "delta": {},
            "incremental": {
                "reused_files_count": 0,
                "skipped_analysis_count": 0,
                "heuristic_subtree_matches": 0
            },
            "active_excludes": self.exclude_globs,
            "truncated": {
                "max_entries": self.max_entries,
                "hit": False,
                "files_seen": 0,
                "dirs_seen": 0,
                "depth_limit_hit": False,
                "reason": None
            }
        }
        self.tree = {} # Nested dict structure representing the tree

    @staticmethod
    def _build_exclude_patterns(globs: List[str]) -> List[str]:
        patterns = []
        seen = set()
        for glob in globs:
            # Normalize globs
            normalized = str(glob).replace("\\", "/")

            # Generate base candidates (original + root-stripped if starts with **/)
            candidates_set = {normalized}
            if normalized.startswith("**/"):
                candidates_set.add(normalized[3:])

            # For each candidate, ensure we have both base and "/**" version
            expanded_candidates = set()
            for cand in candidates_set:
                expanded_candidates.add(cand)
                if cand.endswith("/**"):
                    expanded_candidates.add(cand[:-3])
                else:
                    expanded_candidates.add(f"{cand}/**")

            for candidate in sorted(expanded_candidates):
                if candidate and candidate not in seen:
                    seen.add(candidate)
                    patterns.append(candidate)
        return patterns

    @staticmethod
    def _compile_exclude_regex(patterns: List[str]) -> Pattern:
        if not patterns:
            return re.compile(r"(?!x)x") # Matches nothing

        # Check if filesystem is case-insensitive to determine regex flags
        is_case_insensitive = os.path.normcase("A") == os.path.normcase("a")
        flags = re.IGNORECASE if is_case_insensitive else 0

        regex_parts = []
        for pat in patterns:
            # Ensure pattern uses forward slashes (already done in _build_exclude_patterns, but explicitly safe)
            if os.sep != "/":
                pat = pat.replace(os.sep, "/")

            # fnmatch.translate converts glob to regex (e.g., *.txt -> (?s:.*\.txt)\Z)
            # We join them with OR
            regex_parts.append(fnmatch.translate(pat))

        combined = "|".join(regex_parts)
        return re.compile(combined, flags)

    def _is_excluded(self, path: Union[Path, str]) -> bool:
        """
        Checks if a path is excluded based on glob patterns.

        Args:
            path: Path object or relative path string.
                  If string, it MUST be relative to root and use POSIX separators (/)
                  unless it contains backslashes which will be normalized.
        """
        # Check against globs
        # We match relative path from root
        if isinstance(path, Path):
            try:
                rel_path = path.relative_to(self.root)
            except ValueError:
                return True # Should not happen if walking from root
            str_path = rel_path.as_posix()
        else:
            # Assume string is already relative path. Ensure POSIX slashes.
            # Conditional replacement: only replace if backslash is present
            str_path = path if "\\" not in path else path.replace("\\", "/")

            # Guardrails for string inputs to enforce relative semantics
            # Reject absolute POSIX paths (start with /)
            if str_path.startswith("/"):
                # Special check: UNC paths normalized to //server/share should be rejected too
                # startswith("/") covers "//" as well
                return True

            # Reject drive letters (e.g. C:/)
            if len(str_path) >= 2 and str_path[1] == ":" and str_path[0].isalpha():
                return True

            # Reject traversal attempts
            if str_path == ".." or str_path.startswith("../") or str_path.endswith("/..") or "/../" in str_path:
                return True

        if self._exclude_regex.fullmatch(str_path):
            return True
        return False

    def scan(self, inventory_file: Optional[Path] = None, dirs_inventory_file: Optional[Path] = None, previous_inventory_file: Optional[Path] = None, on_progress: Optional[Callable[[int, int, int], None]] = None) -> Dict[str, Any]:
        """
        Scans the directory structure.

        Args:
            inventory_file: Optional path to write a JSONL inventory of all files.
            dirs_inventory_file: Optional path to write a JSONL inventory of all directories.
            on_progress: Optional callback(files_seen, dirs_seen, bytes_seen) called
                periodically during the scan (throttled to ≤1 call/sec, or every
                1000 new files — whichever comes first).
                The three int arguments are running counters that correspond
                to ``total_files``, ``total_dirs``, ``total_bytes`` in the
                final stats dict.  Callers should persist them under
                ``files_seen`` / ``dirs_seen`` / ``bytes_seen`` to clearly
                distinguish in-progress counters from final result totals.
                The callback MUST NOT raise; any exception is silently caught
                to avoid aborting the scan.
        """
        if inventory_file and not self.snapshot_id:
            raise ValueError("Inventory emission requires a snapshot_id to satisfy the atlas-inventory.v1 schema contract.")

        self.stats["start_time"] = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        start_ts = time.time()
        last_progress_ts = start_ts  # throttle progress callbacks
        last_progress_files = 0  # file-count gate for progress in large dirs

        current_entries = 0
        depth_limit_hit = False

        # Prepare inventory writers
        inv_f = None
        dirs_inv_f = None
        try:
            if inventory_file:
                inv_f = inventory_file.open("w", encoding="utf-8")
            if dirs_inventory_file:
                dirs_inv_f = dirs_inventory_file.open("w", encoding="utf-8")
        except OSError as e:
            logger.error("Failed to open inventory files: %s", e)

        dir_sizes = {} # path -> apparent size
        dir_allocated_sizes = {} # path -> allocated size
        dir_file_counts = {}
        dir_depths = {}
        dir_signal_counts = {}
        large_files = []
        text_files_count = 0
        binary_files_count = 0

        # For topology we keep track of nodes
        topology_nodes = {}

        # Directory aggregates for directory rollup statistics
        # path -> { 'n_files': int, 'n_dirs': int, 'bytes': int, 'max_descendant_mtime': str, 'mtime': str }
        # Only collect if we actually need them (writing dirs file).
        # Note: These aggregates are strictly for producing the dirs.jsonl artifact, NOT for performing subtree skipping yet.
        collect_dir_aggregates = bool(dirs_inventory_file)
        dir_aggregates: Dict[str, Dict[str, Any]] = {} if collect_dir_aggregates else None

        try:
            for root, dirs, files in os.walk(self.root, topdown=True, followlinks=False):
                current_root = Path(root)

                # Calculate relative path string once
                try:
                    rel_path_obj = current_root.relative_to(self.root)
                except ValueError:
                    # Should not happen
                    dirs[:] = []
                    continue

                rel_path_str = rel_path_obj.as_posix()

                # Check exclusions for current root (prune traversal)
                if self._is_excluded(rel_path_str):
                    dirs[:] = []
                    continue

                depth = len(rel_path_obj.parts) if rel_path_str != "." else 0

                if depth > self.max_depth:
                    dirs[:] = []
                    depth_limit_hit = True
                    continue

                # Check for .git to mark repo node
                has_git = False
                if ".git" in dirs:
                    has_git = True
                    self.stats["repo_nodes"].append(rel_path_str)
                    # Don't recurse into .git
                    dirs.remove(".git")

                # Detect workspace signals
                workspace_signals = []
                workspace_kind = "unknown"

                if has_git:
                    workspace_signals.append(".git")

                for sig in self.WORKSPACE_SIGNALS:
                    if sig in dirs or sig in files:
                        workspace_signals.append(sig)

                # Check for .wgx/ (can be a directory)
                if ".wgx" in dirs:
                    workspace_signals.append(".wgx")

                if workspace_signals:
                    if ".git" in workspace_signals:
                        workspace_kind = "git_repo"
                    elif "package.json" in workspace_signals:
                        workspace_kind = "node_project"
                    elif "pyproject.toml" in workspace_signals or "requirements.txt" in workspace_signals:
                        workspace_kind = "python_project"
                    elif "compose.yml" in workspace_signals or "docker-compose.yml" in workspace_signals:
                        workspace_kind = "compose_stack"
                    elif len(workspace_signals) == 1 and workspace_signals[0] == "README.md":
                        workspace_kind = "docs_space"
                    else:
                        workspace_kind = "mixed_workspace"

                    # confidence heuristic: more signals = higher confidence
                    confidence = min(len(workspace_signals) * 0.25, 1.0)
                    if ".git" in workspace_signals or ".ai-context.yml" in workspace_signals:
                        confidence = max(confidence, 0.9)

                    # Simple hash for deterministic ID
                    try:
                        h = hashlib.md5(rel_path_str.encode('utf-8'), usedforsecurity=False).hexdigest()[:8]
                    except TypeError:
                        h = hashlib.md5(rel_path_str.encode('utf-8')).hexdigest()[:8]  # nosec B303
                    workspace_id = f"ws_{h}"
                    self.stats["workspaces"].append({
                        "workspace_id": workspace_id,
                        "root_path": rel_path_str,
                        "workspace_kind": workspace_kind,
                        "signals": workspace_signals,
                        "confidence": round(confidence, 2),
                        "tags": [workspace_kind]
                    })

                # Pre-calculate prefix for children
                prefix = "" if rel_path_str == "." else rel_path_str + "/"

                # Filter dirs in-place (Pruning)
                # We must check if the dir ITSELF is excluded to prune it from walk
                kept_dirs = []
                for d in dirs:
                    # Construct relative path string for child directory
                    d_rel = prefix + d

                    if self._is_excluded(d_rel):
                        continue
                    kept_dirs.append(d)
                dirs[:] = kept_dirs

                dir_bytes = 0
                dir_allocated_bytes = 0

                # Filter files for this directory
                # Store Tuple[str, str] -> (filename, relative_path)
                kept_files: List[Tuple[str, str]] = []
                for f in files:
                    # Construct relative path string for file
                    f_rel = prefix + f

                    if not self._is_excluded(f_rel):
                        kept_files.append((f, f_rel))

                dir_mtime = datetime.fromtimestamp(current_root.stat().st_mtime, timezone.utc).isoformat().replace('+00:00', 'Z')

                # Note: Subtree skipping based on mtime/counts is currently disabled.
                # It is not robust enough against silent descendant changes without a stronger tree hash.

                # Track for topology
                topology_nodes[rel_path_str] = {
                    "path": rel_path_str,
                    "depth": depth,
                    "dirs": [prefix + d for d in dirs]
                }

                dir_file_counts[rel_path_str] = len(kept_files)
                dir_depths[rel_path_str] = depth
                dir_signal_counts[rel_path_str] = len(workspace_signals)

                need_fingerprint = collect_dir_aggregates or (self.incremental_dirs_inventory and not self.config_changed)
                direct_children_fingerprint = None

                if need_fingerprint:
                    # Calculate deterministic fingerprint of direct children (names and types)
                    children_signatures = []
                    for f, _ in kept_files:
                        children_signatures.append(f"F:{f}")
                    for d in dirs:
                        children_signatures.append(f"D:{d}")
                    children_signatures.sort()
                    # Use canonical JSON serialization to prevent delimiter ambiguity if filename contains '|'
                    children_signatures_json = json.dumps(
                        children_signatures,
                        ensure_ascii=False,
                        separators=(",", ":")
                    )
                    # Handle possible invalid utf-8 sequences in filenames using surrogateescape
                    fingerprint_data = children_signatures_json.encode('utf-8', errors='surrogateescape')
                    direct_children_fingerprint = hashlib.md5(fingerprint_data, usedforsecurity=False).hexdigest() # nosec B303

                # Heuristic subtree candidate detection.
                # We intentionally DO NOT prune traversal (no `dirs[:] = []`) here.
                # mtime + counts + direct_children_fingerprint cannot guarantee
                # that deeper descendants have not changed (POSIX directory mtime is recursively blind).
                # This is purely for diagnostic and analytical purposes.
                if self.incremental_dirs_inventory and not self.config_changed and direct_children_fingerprint is not None:
                    prev_dir = self.incremental_dirs_inventory.get(rel_path_str)
                    if prev_dir:
                        if (prev_dir.get("mtime") == dir_mtime and
                            prev_dir.get("n_files") == len(kept_files) and
                            prev_dir.get("n_dirs") == len(dirs) and
                            prev_dir.get("direct_children_fingerprint") == direct_children_fingerprint):

                            self.stats["incremental"]["heuristic_subtree_matches"] += 1

                if collect_dir_aggregates:
                    dir_aggregates[rel_path_str] = {
                        "rel_path": rel_path_str,
                        "depth": depth,
                        "n_files": len(kept_files), # direct children
                        "n_dirs": len(dirs), # direct children
                        "mtime": dir_mtime,
                        "subtree_file_count": len(kept_files),
                        "subtree_dir_count": len(dirs), # Will accumulate (counts descendants without self)
                        "subtree_total_bytes": 0, # Apparent bytes; will accumulate
                        "subtree_allocated_bytes": 0, # Allocated blocks; will accumulate
                        "max_descendant_mtime": dir_mtime,
                        "direct_children_fingerprint": direct_children_fingerprint,
                        "direct_file_signatures": [], # Will hold stable file signatures for hashing
                        "child_dir_hashes": [], # Will accumulate child dir recursive hashes
                        "recursive_hash": None # Will be computed bottom-up
                    }

                self.stats["truncated"]["dirs_seen"] += 1

                for f, f_rel in kept_files:
                    f_path = current_root / f
                    # Exclusion check already done

                    current_entries += 1
                    self.stats["truncated"]["files_seen"] = current_entries

                    if current_entries > self.max_entries:
                        self.stats["truncated"]["hit"] = True
                        self.stats["truncated"]["reason"] = "max_entries"
                        # Reset files_seen to max_entries to reflect "stop at limit" contract
                        self.stats["truncated"]["files_seen"] = self.max_entries
                        break

                    try:
                        stat = f_path.stat()
                        size = stat.st_size
                        allocated_size = allocated_bytes_from_stat(stat)
                        is_sparse = size > allocated_size

                        is_huge = self.max_file_size is not None and size > self.max_file_size

                        mtime = stat.st_mtime
                        ext = f_path.suffix.lower()
                        is_sym = f_path.is_symlink()
                        inode = stat.st_ino
                        device = stat.st_dev

                        mtime_iso = datetime.fromtimestamp(mtime, timezone.utc).isoformat().replace('+00:00', 'Z')

                        self.stats["total_files"] += 1
                        self.stats["total_bytes"] += size
                        self.stats["total_allocated_bytes"] += allocated_size
                        if is_sparse:
                            self.stats["sparse_files_count"] += 1
                            self.stats["sparse_apparent_bytes"] += size
                            self.stats["sparse_allocated_bytes"] += allocated_size
                        self.stats["extensions"][ext] = self.stats["extensions"].get(ext, 0) + 1

                        dir_bytes += size
                        dir_allocated_bytes += allocated_size

                        # Update aggregate max mtime
                        if collect_dir_aggregates and mtime_iso > dir_aggregates[rel_path_str]["max_descendant_mtime"]:
                            dir_aggregates[rel_path_str]["max_descendant_mtime"] = mtime_iso

                        is_txt = None
                        mime_type = None
                        encoding = None
                        line_count = None

                        # Incremental reuse heuristic
                        prev_entry = self.incremental_inventory.get(f_rel)
                        is_reused = False
                        file_hash = None
                        if prev_entry and prev_entry.get("size_bytes") == size:
                            # If size matches but mtime changed, or we just want to be sure, we can selectively hash
                            # Here, if mtime matches, we assume reuse.
                            if prev_entry.get("mtime") == mtime_iso:
                                is_reused = True
                            else:
                                # Selective Hash for disambiguation (if size matches but mtime changed, maybe it was just touched)
                                # Only hash if file is < 1MB to avoid heavy IO
                                if not is_huge and size < 1024 * 1024 and "quick_hash" in prev_entry:
                                    try:
                                        with f_path.open("rb") as hf:
                                            # Read first and last 4KB
                                            hf.seek(0)
                                            head = hf.read(4096)
                                            if size > 4096:
                                                hf.seek(-min(4096, size - 4096), 2)
                                                tail = hf.read(4096)
                                            else:
                                                tail = b""
                                            file_hash = hashlib.md5(head + tail, usedforsecurity=False).hexdigest() # nosec B303
                                        if file_hash == prev_entry["quick_hash"]:
                                            is_reused = True
                                    except OSError:
                                        pass

                            if is_reused:
                                self.stats["incremental"]["reused_files_count"] += 1
                                if not self.config_changed:
                                    if "is_text" in prev_entry:
                                        is_txt = prev_entry["is_text"]
                                        self.stats["incremental"]["skipped_analysis_count"] += 1
                                    if self.enable_content_stats and not is_huge:
                                        if "mime_type" in prev_entry:
                                            mime_type = prev_entry["mime_type"]
                                        if "encoding" in prev_entry:
                                            encoding = prev_entry["encoding"]
                                        if "line_count" in prev_entry:
                                            line_count = prev_entry["line_count"]
                                if not is_huge and "quick_hash" in prev_entry and not file_hash:
                                    file_hash = prev_entry["quick_hash"]

                        if self.enable_content_stats and not is_huge:
                            # 1. Determine or reuse MIME type
                            if not is_reused or mime_type is None or self.config_changed:
                                mime_type = detect_mime_type(f_path)

                            # 2. Determine or reuse is_text
                            if not is_reused or is_txt is None or self.config_changed:
                                is_txt = is_probably_text(f_path, size)

                            # 3. Restrict text properties based on MIME
                            if mime_type:
                                is_text_mime = mime_type.startswith("text/") or mime_type in TEXT_MIME_ALLOWLIST
                                if not is_text_mime:
                                    is_txt = False
                                    encoding = None
                                    line_count = None

                            if is_txt:
                                text_files_count += 1
                                # 4. Detect encoding only if it's considered text
                                if not is_reused or encoding is None or self.config_changed:
                                    encoding = detect_encoding(f_path)
                                # 5. Detect line count only if it's considered text
                                if not is_reused or line_count is None or self.config_changed:
                                    line_count = count_lines(f_path, size, encoding=encoding)
                            else:
                                binary_files_count += 1

                            if size > 10 * 1024 * 1024: # 10MB
                                large_files.append({"path": f_rel, "size": size})

                        # Conditionally generate quick_hash for small files if not reused and not yet computed
                        if not is_huge and not file_hash and size < 1024 * 1024 and size > 0 and not is_sym:
                            try:
                                with f_path.open("rb") as hf:
                                    hf.seek(0)
                                    head = hf.read(4096)
                                    if size > 4096:
                                        hf.seek(-min(4096, size - 4096), 2)
                                        tail = hf.read(4096)
                                    else:
                                        tail = b""
                                    file_hash = hashlib.md5(head + tail, usedforsecurity=False).hexdigest() # nosec B303
                            except OSError:
                                pass

                        # Update parent dir aggregate with file signature
                        if collect_dir_aggregates:
                            # Use canonical JSON serialization for stable file signatures
                            sig_dict = {
                                "path": f_rel,
                                "size": size,
                                "mtime": mtime_iso
                            }

                            h = file_hash
                            if not h and prev_entry and "quick_hash" in prev_entry:
                                h = prev_entry["quick_hash"]

                            if h:
                                sig_dict["quick_hash"] = h

                            file_sig = json.dumps(sig_dict, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
                            dir_aggregates[rel_path_str]["direct_file_signatures"].append(file_sig)

                        # Inventory Output
                        if inv_f:
                            # Use reused relative path string
                            entry = {
                                "rel_path": f_rel,
                                "name": f,
                                "ext": ext,
                                "size_bytes": size,
                                "allocated_size_bytes": allocated_size,
                                "is_sparse": is_sparse,
                                "mtime": mtime_iso,
                                "is_symlink": is_sym,
                                "inode": inode,
                                "device": device
                            }

                            if file_hash:
                                entry["quick_hash"] = file_hash

                            if self.snapshot_id:
                                entry["snapshot_id"] = self.snapshot_id
                            if is_huge:
                                entry["is_huge"] = True
                            if self.enable_content_stats and not is_huge:
                                if is_txt is not None:
                                    entry["is_text"] = is_txt
                                if mime_type is not None:
                                    entry["mime_type"] = mime_type
                                if encoding is not None:
                                    entry["encoding"] = encoding
                                if line_count is not None:
                                    entry["line_count"] = line_count
                            inv_f.write(json.dumps(entry, ensure_ascii=True, sort_keys=True) + "\n")

                    except OSError:
                        continue

                if self.stats["truncated"]["hit"]:
                    break

                self.stats["total_dirs"] += 1
                dir_sizes[rel_path_str] = dir_bytes
                dir_allocated_sizes[rel_path_str] = dir_allocated_bytes
                if collect_dir_aggregates:
                    dir_aggregates[rel_path_str]["subtree_total_bytes"] += dir_bytes
                    dir_aggregates[rel_path_str]["subtree_allocated_bytes"] += dir_allocated_bytes

                # Fire progress callback (throttled: at most once per second OR
                # every _PROGRESS_FILE_COUNT_THRESHOLD new files, whichever
                # comes first).  The file-count gate prevents false stalls on
                # directories with many entries where a single os.walk()
                # iteration takes > 60s.
                if on_progress is not None:
                    now_ts = time.time()
                    files_delta = self.stats["total_files"] - last_progress_files
                    if (now_ts - last_progress_ts >= 1.0) or (files_delta >= _PROGRESS_FILE_COUNT_THRESHOLD):
                        last_progress_ts = now_ts
                        last_progress_files = self.stats["total_files"]
                        try:
                            on_progress(
                                self.stats["total_files"],
                                self.stats["total_dirs"],
                                self.stats["total_bytes"]
                            )
                        except Exception:
                            pass  # never let progress callback abort the scan

        finally:
            if inv_f:
                inv_f.close()

            # Process aggregates bottom-up
            if collect_dir_aggregates and dir_aggregates:
                # Sort paths by depth descending so we process leaves first
                sorted_dirs_by_depth = sorted(dir_aggregates.keys(), key=lambda p: dir_aggregates[p]["depth"], reverse=True)

                for p in sorted_dirs_by_depth:
                    current_agg = dir_aggregates[p]

                    # 1. Compute bottom-up recursive_hash for THIS directory
                    dir_hash_components = []

                    # A) Direct file signatures (sorted for stability)
                    sorted_files = sorted(current_agg["direct_file_signatures"])
                    for fsig in sorted_files:
                        dir_hash_components.append(f"F:{fsig}")

                    # B) Child directory hashes (sorted for stability)
                    sorted_child_hashes = sorted(current_agg["child_dir_hashes"])
                    for dsig in sorted_child_hashes:
                        dir_hash_components.append(f"D:{dsig}")

                    # C) Direct properties of this directory (optional, but good for tracking structural identity)
                    dir_hash_components.append(f"R:{current_agg['rel_path']}")
                    if current_agg["direct_children_fingerprint"]:
                        dir_hash_components.append(f"FP:{current_agg['direct_children_fingerprint']}")

                    # Produce hash
                    hash_input = json.dumps(dir_hash_components, ensure_ascii=False, separators=(",", ":")).encode("utf-8", errors="surrogateescape")
                    recursive_hash = hashlib.md5(hash_input, usedforsecurity=False).hexdigest() # nosec B303

                    current_agg["recursive_hash"] = recursive_hash

                    # 2. Bubble up to parent
                    if p != ".":
                        parent_path = str(Path(p).parent)
                        if parent_path == ".":
                            parent_path = "." # ensure consistent key
                        else:
                            parent_path = parent_path.replace("\\", "/") # POSIX sanity

                        if parent_path in dir_aggregates:
                            parent_agg = dir_aggregates[parent_path]
                            child_agg = current_agg

                            parent_agg["subtree_file_count"] += child_agg["subtree_file_count"]
                            parent_agg["subtree_dir_count"] += child_agg.get("subtree_dir_count", child_agg.get("n_dirs", 0))
                            parent_agg["subtree_total_bytes"] += child_agg["subtree_total_bytes"]
                            parent_agg["subtree_allocated_bytes"] += child_agg["subtree_allocated_bytes"]
                            if child_agg["max_descendant_mtime"] > parent_agg["max_descendant_mtime"]:
                                parent_agg["max_descendant_mtime"] = child_agg["max_descendant_mtime"]

                            # Propagate the child's recursive hash to the parent so it can compute its own
                            child_sig_dict = {
                                "path": p,
                                "recursive_hash": recursive_hash
                            }
                            child_sig = json.dumps(child_sig_dict, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
                            parent_agg["child_dir_hashes"].append(child_sig)

                # Clean up internal hashing fields before output
                for p in dir_aggregates:
                    del dir_aggregates[p]["direct_file_signatures"]
                    del dir_aggregates[p]["child_dir_hashes"]

            # Write dir inventory if requested
            if dirs_inv_f:
                try:
                    for p in sorted(dir_aggregates.keys()):
                        dirs_inv_f.write(json.dumps(dir_aggregates[p], ensure_ascii=True, sort_keys=True) + "\n")
                finally:
                    dirs_inv_f.close()

        # Update stats
        if depth_limit_hit:
             self.stats["truncated"]["depth_limit_hit"] = True
             if not self.stats["truncated"]["hit"]:
                 self.stats["truncated"]["hit"] = True
                 self.stats["truncated"]["reason"] = "max_depth"

        # Calculate Duration
        self.stats["end_time"] = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        self.stats["duration_seconds"] = time.time() - start_ts

        # Find Top Dirs (Hotspots) - simplistic aggregation
        all_paths = sorted(dir_sizes.keys(), key=lambda p: len(Path(p).parts), reverse=True)
        recursive_sizes = dir_sizes.copy()
        recursive_allocated_sizes = dir_allocated_sizes.copy()

        for p_str in all_paths:
            if p_str == ".":
                continue
            p = Path(p_str)
            parent = str(p.parent)
            if parent == ".":
                pass

            if parent in recursive_sizes:
                recursive_sizes[parent] += recursive_sizes[p_str]
                recursive_allocated_sizes[parent] += recursive_allocated_sizes[p_str]

        sorted_dirs = sorted(recursive_sizes.items(), key=lambda x: x[1], reverse=True)
        self.stats["top_dirs"] = [
            {
                "path": path,
                "bytes": apparent_bytes,
                "allocated_bytes": recursive_allocated_sizes.get(path, apparent_bytes),
            }
            for path, apparent_bytes in sorted_dirs[:50]
        ]

        # Enhanced Hotspots
        highest_file_density = sorted(dir_file_counts.items(), key=lambda x: x[1], reverse=True)[:50]
        deepest_paths = sorted(dir_depths.items(), key=lambda x: x[1], reverse=True)[:50]
        highest_signal_density = sorted(dir_signal_counts.items(), key=lambda x: x[1], reverse=True)[:50]

        self.stats["hotspots"] = {
            "top_dirs": self.stats["top_dirs"],
            "highest_file_density": [{"path": p, "count": c} for p, c in highest_file_density if c > 0],
            "deepest_paths": [{"path": p, "depth": d} for p, d in deepest_paths],
            "highest_signal_density": [{"path": p, "signals": s} for p, s in highest_signal_density if s > 0]
        }

        # Enhanced Content Metadata
        self.stats["content"] = {
            "text_files_count": text_files_count,
            "binary_files_count": binary_files_count,
            "large_files": sorted(large_files, key=lambda x: x["size"], reverse=True)[:100],
            "extensions": dict(sorted(self.stats["extensions"].items(), key=lambda x: x[1], reverse=True)[:50])
        }

        # Topology tree construction
        # We only need a reduced topology, so we can pass the nodes directly or build a fast hierarchy.
        # Nodes are passed so `planner.py` can serialize it efficiently without writing the entire inventory.
        self.stats["topology"] = {
            "root_path": str(self.root),
            "nodes": topology_nodes
        }

        # Snapshot Output Structure
        if self.snapshot_id:
             self.stats["snapshot"] = {
                 "snapshot_id": self.snapshot_id,
                 "created_at": self.stats["end_time"],
                 "root_descriptor": str(self.root),
                 "file_count": self.stats["total_files"],
                 "directory_count": self.stats["total_dirs"],
                 "workspace_count": len(self.stats.get("workspaces", []))
             }

        # Calculate Delta if requested
        if self.compare_to_snapshot_id:
            if not previous_inventory_file or not previous_inventory_file.exists():
                logger.warning("Delta requested but previous inventory missing; skipping delta")
            elif not inventory_file or not inventory_file.exists():
                logger.warning("Delta requested but current inventory missing; skipping delta")
            else:
                delta = {
                    "compare_to_snapshot_id": self.compare_to_snapshot_id,
                    "new_files": [],
                    "removed_files": [],
                    "changed_files": []
                }
                try:
                    prev_inv = {}
                    with previous_inventory_file.open("r", encoding="utf-8") as f:
                        for line in f:
                            entry = json.loads(line)
                            prev_inv[entry["rel_path"]] = entry

                    curr_inv = {}
                    with inventory_file.open("r", encoding="utf-8") as f:
                        for line in f:
                            entry = json.loads(line)
                            curr_inv[entry["rel_path"]] = entry

                    for path, curr_entry in curr_inv.items():
                        if path not in prev_inv:
                            delta["new_files"].append(path)
                        elif prev_inv[path]["size_bytes"] != curr_entry["size_bytes"] or prev_inv[path]["mtime"] != curr_entry["mtime"]:
                            delta["changed_files"].append(path)

                    for path in prev_inv:
                        if path not in curr_inv:
                            delta["removed_files"].append(path)

                    delta["new_files"].sort()
                    delta["changed_files"].sort()
                    delta["removed_files"].sort()

                except Exception as e:
                    logger.exception("Failed to calculate delta")
                    delta["error"] = str(e)

                self.stats["delta"] = delta

        # Add inventory metadata to stats if file was generated
        if inventory_file:
            self.stats["inventory_file"] = str(inventory_file.resolve())
        if dirs_inventory_file:
            self.stats["dirs_inventory_file"] = str(dirs_inventory_file.resolve())

        self.stats["inventory_strict"] = self.inventory_strict

        return {
            "root": str(self.root),
            "stats": self.stats,
        }

    def merge_folder(self, folder_rel_path: str, output_file: Path,
                     recursive: bool = False, max_files: int = 1000, max_bytes: int = 10 * 1024 * 1024) -> Dict[str, Any]:
        """
        Situative Folder Merge: Merges all text files in a specific folder into one file.

        Args:
            folder_rel_path: Relative path to folder to merge.
            output_file: Path to write merged content.
            recursive: Whether to include subdirectories.
            max_files: Safety limit for number of files.
            max_bytes: Safety limit for total merged size.
        """
        target_dir = (self.root / folder_rel_path).resolve()

        try:
            target_dir.relative_to(self.root.resolve())
        except ValueError:
             raise ValueError(f"Target folder {folder_rel_path} is outside of root directory.")

        if not target_dir.exists() or not target_dir.is_dir():
            raise ValueError(f"Folder not found: {folder_rel_path}")

        files_merged = []
        files_skipped = []
        total_merged_bytes = 0
        file_count = 0

        # Gather candidates
        candidates = []
        if recursive:
            for root, dirs, files in os.walk(target_dir):
                # Apply same excludes? Or raw merge?
                # User said "situative folder merge... roh...".
                # Usually explicit merge implies "I want this folder".
                # But we should probably respect excludes to avoid merging .git etc.

                # Exclude directories from traversal
                # Similar logic to scan() pruning
                current_root = Path(root)
                if self._is_excluded(current_root):
                    dirs[:] = []
                    continue

                kept_dirs = []
                for d in dirs:
                    d_path = current_root / d
                    if not self._is_excluded(d_path):
                        kept_dirs.append(d)
                dirs[:] = kept_dirs

                for f in files:
                    candidates.append(Path(root) / f)
        else:
            for item in target_dir.iterdir():
                if item.is_file():
                    candidates.append(item)

        # Deterministic sort
        # Sort by relative path to target_dir for stability
        candidates.sort(key=lambda p: str(p.relative_to(target_dir)).lower())

        limit_hit_reason = None

        with output_file.open("w", encoding="utf-8") as out:
            out.write(f"# Atlas Folder Merge: {folder_rel_path}\n")
            out.write(f"# Generated: {datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')}\n")
            out.write(f"# Recursive: {recursive}\n\n")

            for f_path in candidates:
                # Check exclusion again for the file path
                if self._is_excluded(f_path):
                    continue

                if file_count >= max_files:
                    limit_hit_reason = "max_files"
                    break

                if total_merged_bytes >= max_bytes:
                    limit_hit_reason = "max_bytes"
                    break

                rel_path = f_path.relative_to(self.root).as_posix()
                try:
                    size = f_path.stat().st_size
                    if is_probably_text(f_path, size):
                        out.write(f"===== FILE: {rel_path} =====\n")
                        try:
                            content = f_path.read_text(encoding="utf-8", errors="replace")
                            out.write(content)
                            total_merged_bytes += len(content.encode("utf-8")) # Rough estimate
                        except Exception as e:
                            out.write(f"[Error reading file: {e}]\n")
                        out.write("\n\n")
                        files_merged.append(rel_path)
                        file_count += 1
                    else:
                        files_skipped.append({"path": rel_path, "reason": "binary/non-text"})
                except OSError as e:
                    files_skipped.append({"path": rel_path, "reason": f"fs_error: {e}"})

            if limit_hit_reason:
                out.write(f"\n===== MERGE TRUNCATED: {limit_hit_reason} reached =====\n")

            if files_skipped:
                out.write("\n===== SKIPPED FILES =====\n")
                for item in files_skipped:
                    out.write(f"- {item['path']} ({item['reason']})\n")

        return {
            "merged": files_merged,
            "skipped": files_skipped,
            "output_file": str(output_file),
            "truncated": limit_hit_reason
        }

def render_atlas_md(atlas_data: Dict[str, Any]) -> str:
    stats = atlas_data["stats"]
    root = atlas_data.get("root", "Unknown")

    lines = []
    lines.append(f"# 🗺️ Atlas: {root}")
    lines.append(f"Generated: {stats.get('end_time')} (Duration: {stats.get('duration_seconds'):.2f}s)")
    lines.append("")

    if stats.get("inventory_file"):
        lines.append(f"**Inventory (Files):** `{Path(stats.get('inventory_file')).name}`")
    if stats.get("dirs_inventory_file"):
        lines.append(f"**Inventory (Dirs):** `{Path(stats.get('dirs_inventory_file')).name}`")

    if stats.get("inventory_strict"):
        lines.append("**Mode:** Strict Inventory (minimal excludes).")
    lines.append("")

    # Truncation Warning
    trunc = stats.get("truncated", {})
    if trunc.get("hit"):
        lines.append(f"⚠️ **SCAN TRUNCATED**: {trunc.get('reason')}")
        lines.append(f"  - Files seen: {trunc.get('files_seen')}")
        lines.append(f"  - Limit: {trunc.get('max_entries')}")
        if trunc.get("depth_limit_hit"):
            lines.append("  - Depth limit hit: Yes")
        lines.append("")

    # Transparency on Excludes
    if stats.get("active_excludes"):
        lines.append("**Active Excludes:**")
        for ex in sorted(stats["active_excludes"]):
            lines.append(f"- `{ex}`")
        lines.append("")

    lines.append("## 📊 Overview")
    lines.append(f"- **Total Directories:** {stats.get('total_dirs')}")
    lines.append(f"- **Total Files:** {stats.get('total_files')}")
    lines.append(f"- **Logical Size:** {stats.get('total_bytes', 0) / (1024*1024):.2f} MB")
    lines.append(f"- **Allocated Size:** {stats.get('total_allocated_bytes', stats.get('total_bytes', 0)) / (1024*1024):.2f} MB")
    lines.append(f"- **Sparse Files:** {stats.get('sparse_files_count', 0)}")
    lines.append("")

    lines.append("## 📁 Top Folders (Hotspots)")
    lines.append("| Path | Logical (MB) | Allocated (MB) |")
    lines.append("|---|---:|---:|")
    for d in stats.get("top_dirs", [])[:20]:
        apparent_mb = d['bytes'] / (1024*1024)
        allocated_mb = d.get('allocated_bytes', d['bytes']) / (1024*1024)
        lines.append(f"| `{d['path']}` | {apparent_mb:.2f} | {allocated_mb:.2f} |")
    lines.append("")

    lines.append("## 🏷️ File Types")
    lines.append("| Extension | Count |")
    lines.append("|---|---|")
    # Sort extensions by count
    sorted_exts = sorted(stats.get("extensions", {}).items(), key=lambda x: x[1], reverse=True)
    for ext, count in sorted_exts[:20]:
        lines.append(f"| `{ext or '(no ext)'}` | {count} |")
    lines.append("")

    lines.append("## 📍 Git Repositories")
    repos = stats.get("repo_nodes", [])
    if repos:
        for r in sorted(repos):
            lines.append(f"- `{r}`")
    else:
        lines.append("_No git repositories found in scan scope._")

    return "\n".join(lines)
