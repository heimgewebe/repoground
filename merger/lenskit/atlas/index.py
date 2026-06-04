"""
Atlas FTS Index (Phase 4 — Suchschicht).

This module implements the global, snapshot-aware search index for Atlas as
specified in the Atlas Blaupause (Phase 4) and ``docs/architecture/atlas-fts-integration.md``.
It replaces the previous best-effort approach of linearly scanning every
``inventory.jsonl`` from the live filesystem on each search.

The four architectural decisions from the design doc are resolved here as
follows (see ADR-009):

1. Index cut (global vs. per-snapshot): **global** index at
   ``atlas/indexes/fts.sqlite``. Every row references its origin via
   ``machine_id``/``root_id``/``snapshot_id`` so cross-machine queries are
   native.
2. Write path (inline vs. derive): **derive**. The index is built as a
   post-snapshot derivation step (after artifacts are written, once the
   snapshot is marked complete) and can be fully rebuilt from the registry via
   ``atlas index rebuild``.
3. Deletion / tombstone model: **hard delete keyed by snapshot_id**. Reindexing
   a snapshot first removes its rows (idempotent). Validity against the registry
   is enforced by rebuild; superseded snapshots simply stop being "latest".
4. Default query semantics (latest-only vs. historical): **latest-only** by
   default. The newest indexed snapshot per (machine_id, root_id) wins; callers
   opt into historical search via ``all_snapshots=True`` or an explicit
   ``snapshot_id``.

Content search note: the FTS ``content`` column is populated opportunistically
from **live files at index time** (not from snapshot artifacts). It is therefore
a live-at-index-time cache, not a snapshot-canonical derivation: re-running
``atlas index rebuild`` reads current live content, not the historical content
at snapshot creation. This column is **not used as a filter** in the active
search path. Content queries use only SQLite metadata filtering (``ext``,
``size_bytes``, ``mtime_epoch``, scope) and then always reach ``_content_match``
for live-file confirmation. This avoids false negatives from freshness gaps
(live files mutated after indexing). Future activation of ``fts_content_candidates``
as a narrowing gate would require an immutable content source (e.g. stored in
the snapshot artifact) or an explicit freshness guard.
"""

import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from merger.lenskit.atlas.paths import resolve_artifact_ref

INDEX_SCHEMA_VERSION = "atlas-fts-v1"

# Mirror of the content read budget used by search/content enrichment.
TEXT_DETECTION_MAX_BYTES = 20 * 1024 * 1024


def _ascii_path_tokens(text: str) -> str:
    """Whitespace-join the ASCII alphanumeric runs of `text` for the auxiliary
    ``path_tokens`` FTS column.

    NOTE: This is a deliberately conservative ASCII approximation, NOT a faithful
    reproduction of the FTS5 ``unicode61`` tokenizer (which treats accented and
    other Unicode letters as token characters). It is only used to populate the
    auxiliary ``path_tokens`` column; the safety-critical content-search
    narrowing does NOT rely on it (see ``_safe_prefix_tokens`` /
    ``fts_content_candidates``).
    """
    return " ".join(t for t in re.split(r"[^0-9A-Za-z]+", text) if t)


def _safe_prefix_tokens(query: str) -> Optional[List[str]]:
    """Tokens guaranteed to *begin* a complete FTS token in any document that
    contains ``query`` as a (case-insensitive) substring — suitable for a
    conservative FTS prefix-narrowing ``MATCH``.

    Returns ``None`` when the query cannot be safely narrowed; the caller MUST
    then live-scan every metadata-filtered candidate (never silently drop hits).

    Safety model (ADR-009 / ``docs/architecture/atlas-fts-integration.md`` §3.1):

    * **ASCII only.** The FTS5 ``unicode61`` tokenizer treats Unicode letters as
      token characters, so an ASCII split would misplace token boundaries and
      could drop real hits (e.g. ``Müller`` indexes as one token, but an ASCII
      split yields ``M`` / ``ller``). Any non-ASCII character => ``None``.
    * **Left-bounded runs only.** An alphanumeric run that is preceded *within
      the query* by a non-alphanumeric character necessarily begins a token in
      any matching document, so the prefix query ``run*`` is a guaranteed
      superset. The first run (touching the query start) may be the *suffix* of
      a larger document token, and FTS5 has no suffix search — so it is never
      used. Substring matches like ``oob`` ⊂ ``foobar`` therefore yield no safe
      token and fall back to a full live scan.
    * If no run qualifies (single word, or only a leading run), return ``None``.
    """
    if not query or not query.isascii():
        return None
    runs = list(re.finditer(r"[0-9A-Za-z]+", query))
    if not runs:
        return None
    safe = [m.group() for m in runs if m.start() > 0]
    return safe or None


class AtlasFTSIndex:
    """Global Atlas search index backed by SQLite + FTS5."""

    def __init__(self, index_db_path: Path):
        self.index_db_path = index_db_path
        self.index_db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.index_db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_db()

    def close(self) -> None:
        if self.conn:
            self.conn.close()
            self.conn = None

    def __enter__(self) -> "AtlasFTSIndex":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def _init_db(self) -> None:
        with self.conn:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS index_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT
                );

                -- One row per indexed snapshot. created_at drives latest-only
                -- resolution; has_content records whether FTS content is present.
                CREATE TABLE IF NOT EXISTS indexed_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    machine_id TEXT NOT NULL,
                    root_id TEXT NOT NULL,
                    created_at TEXT,
                    has_content INTEGER NOT NULL DEFAULT 0,
                    file_count INTEGER NOT NULL DEFAULT 0
                );

                -- One row per file observation. machine_id/root_id are
                -- denormalized for fast indexed scope filtering. raw_json
                -- preserves the full inventory record so results are byte-for-byte
                -- equivalent to the legacy linear search output.
                CREATE TABLE IF NOT EXISTS files (
                    file_uid INTEGER PRIMARY KEY,
                    snapshot_id TEXT NOT NULL,
                    machine_id TEXT NOT NULL,
                    root_id TEXT NOT NULL,
                    rel_path TEXT NOT NULL,
                    name TEXT,
                    ext TEXT,
                    size_bytes INTEGER NOT NULL DEFAULT 0,
                    mtime TEXT,
                    mtime_epoch REAL,
                    is_symlink INTEGER,
                    is_text INTEGER,
                    raw_json TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_files_snapshot ON files(snapshot_id);
                CREATE INDEX IF NOT EXISTS idx_files_scope ON files(machine_id, root_id);
                CREATE INDEX IF NOT EXISTS idx_files_ext ON files(ext);
                CREATE INDEX IF NOT EXISTS idx_files_size ON files(size_bytes);

                -- FTS table; rowid is kept in lockstep with files.file_uid for
                -- cheap joins. Both the content and path_tokens columns are stored.
                CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(
                    content,
                    path_tokens
                );
                """
            )
            self.conn.execute(
                "INSERT OR REPLACE INTO index_meta (key, value) VALUES ('schema_version', ?)",
                (INDEX_SCHEMA_VERSION,),
            )

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------
    def _next_file_uid(self) -> int:
        row = self.conn.execute("SELECT COALESCE(MAX(file_uid), 0) AS m FROM files").fetchone()
        return int(row["m"]) + 1

    def remove_snapshot(self, snapshot_id: str) -> None:
        """Hard-delete all index rows for a snapshot (idempotent)."""
        with self.conn:
            uids = [
                r["file_uid"]
                for r in self.conn.execute(
                    "SELECT file_uid FROM files WHERE snapshot_id = ?", (snapshot_id,)
                )
            ]
            self.conn.executemany(
                "DELETE FROM files_fts WHERE rowid = ?", [(u,) for u in uids]
            )
            self.conn.execute("DELETE FROM files WHERE snapshot_id = ?", (snapshot_id,))
            self.conn.execute(
                "DELETE FROM indexed_snapshots WHERE snapshot_id = ?", (snapshot_id,)
            )

    def index_snapshot(
        self,
        snapshot: Dict[str, Any],
        atlas_base: Path,
        root_value: Optional[str] = None,
        index_content: bool = False,
    ) -> Dict[str, int]:
        """Index (or re-index) a single complete snapshot.

        Args:
            snapshot: registry snapshot row (dict) — must carry snapshot_id,
                machine_id, root_id, created_at and inventory_ref.
            atlas_base: canonical atlas base directory for artifact resolution.
            root_value: absolute path of the root, required only when
                ``index_content`` is True (to read live files).
            index_content: when True, read text files and store their content
                in the FTS index (content-mode snapshots).

        Returns a small stats dict.
        """
        snapshot_id = snapshot["snapshot_id"]
        machine_id = snapshot["machine_id"]
        root_id = snapshot["root_id"]
        created_at = snapshot.get("created_at")

        inv_ref = snapshot.get("inventory_ref")
        stats = {"files_indexed": 0, "content_indexed": 0, "skipped": 0}
        if not inv_ref:
            # Snapshots without an inventory (e.g. topology-only) carry no
            # file-level rows; record them so latest-resolution stays correct.
            self.remove_snapshot(snapshot_id)
            with self.conn:
                self.conn.execute(
                    """INSERT OR REPLACE INTO indexed_snapshots
                       (snapshot_id, machine_id, root_id, created_at, has_content, file_count)
                       VALUES (?, ?, ?, ?, 0, 0)""",
                    (snapshot_id, machine_id, root_id, created_at),
                )
            return stats

        inv_path = resolve_artifact_ref(atlas_base, inv_ref)
        if not inv_path.exists():
            print(
                f"[atlas-index] warning: inventory reference not found for {snapshot_id}: {inv_path}",
                file=sys.stderr,
            )
            self.remove_snapshot(snapshot_id)
            return stats

        root_path: Optional[Path] = None
        if index_content and root_value:
            try:
                root_path = Path(root_value).resolve()
            except OSError:
                root_path = None

        # Re-index is idempotent: clear existing rows first.
        self.remove_snapshot(snapshot_id)

        next_uid = self._next_file_uid()
        file_batch: List[tuple] = []
        fts_batch: List[tuple] = []
        any_content = False
        BATCH = 1000

        def _flush() -> None:
            if file_batch:
                self.conn.executemany(
                    """INSERT INTO files
                       (file_uid, snapshot_id, machine_id, root_id, rel_path, name, ext,
                        size_bytes, mtime, mtime_epoch, is_symlink, is_text, raw_json)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    file_batch,
                )
            if fts_batch:
                self.conn.executemany(
                    "INSERT INTO files_fts (rowid, content, path_tokens) VALUES (?, ?, ?)",
                    fts_batch,
                )
            file_batch.clear()
            fts_batch.clear()

        with self.conn:
            try:
                with open(inv_path, "r", encoding="utf-8") as f:
                    for line_idx, line in enumerate(f, start=1):
                        if not line.strip():
                            continue
                        try:
                            item = json.loads(line)
                        except json.JSONDecodeError:
                            stats["skipped"] += 1
                            print(
                                f"[atlas-index] warning: invalid inventory record in {inv_path}:{line_idx}",
                                file=sys.stderr,
                            )
                            continue
                        if not isinstance(item, dict):
                            stats["skipped"] += 1
                            continue

                        rel_path = item.get("rel_path", "")
                        if not rel_path:
                            stats["skipped"] += 1
                            continue
                        name = item.get("name", "")
                        ext = item.get("ext", "")
                        size_bytes = item.get("size_bytes", 0) or 0
                        mtime = item.get("mtime")
                        mtime_epoch = _safe_epoch(mtime)
                        is_symlink = _to_int_bool(item.get("is_symlink"))
                        is_text = _to_int_bool(item.get("is_text"))

                        uid = next_uid
                        next_uid += 1

                        file_batch.append(
                            (
                                uid,
                                snapshot_id,
                                machine_id,
                                root_id,
                                rel_path,
                                name,
                                ext,
                                size_bytes,
                                mtime,
                                mtime_epoch,
                                is_symlink,
                                is_text,
                                json.dumps(item, ensure_ascii=False),
                            )
                        )

                        content_text = ""
                        if (
                            index_content
                            and root_path is not None
                            and item.get("is_text") is not False
                            and not item.get("is_symlink")
                            and size_bytes <= TEXT_DETECTION_MAX_BYTES
                        ):
                            content_text = _read_text_safely(root_path, rel_path, size_bytes)
                            if content_text:
                                any_content = True
                                stats["content_indexed"] += 1

                        fts_batch.append(
                            (uid, content_text, _ascii_path_tokens(rel_path))
                        )
                        stats["files_indexed"] += 1

                        if len(file_batch) >= BATCH:
                            _flush()
                _flush()
            except (OSError, UnicodeDecodeError) as e:
                print(
                    f"[atlas-index] warning: failed to read inventory {inv_path}: {e}",
                    file=sys.stderr,
                )
                self.remove_snapshot(snapshot_id)
                return stats

            self.conn.execute(
                """INSERT OR REPLACE INTO indexed_snapshots
                   (snapshot_id, machine_id, root_id, created_at, has_content, file_count)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    snapshot_id,
                    machine_id,
                    root_id,
                    created_at,
                    1 if any_content else 0,
                    stats["files_indexed"],
                ),
            )
        return stats

    def rebuild_from_registry(self, registry, atlas_base: Path) -> Dict[str, int]:
        """Drop and rebuild the entire index from the registry's complete snapshots."""
        with self.conn:
            self.conn.execute("DELETE FROM files_fts")
            self.conn.execute("DELETE FROM files")
            self.conn.execute("DELETE FROM indexed_snapshots")

        roots = {r["root_id"]: r for r in registry.list_roots()}
        snapshots = registry.list_complete_snapshots()
        totals = {"snapshots": 0, "files_indexed": 0, "content_indexed": 0}
        for snap in snapshots:
            root = roots.get(snap["root_id"], {})
            index_content = bool(snap.get("content_ref"))
            stats = self.index_snapshot(
                snap,
                atlas_base,
                root_value=root.get("root_value"),
                index_content=index_content,
            )
            totals["snapshots"] += 1
            totals["files_indexed"] += stats["files_indexed"]
            totals["content_indexed"] += stats["content_indexed"]
        return totals

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------
    def is_snapshot_indexed(self, snapshot_id: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM indexed_snapshots WHERE snapshot_id = ?", (snapshot_id,)
        ).fetchone()
        return row is not None

    def snapshot_coverage_ok(self, snapshot_id: str) -> bool:
        """Cheap integrity check that a snapshot's index rows are self-consistent.

        Verifies three conditions:

        1. The snapshot is registered in ``indexed_snapshots``.
        2. The recorded ``file_count`` matches the actual number of ``files`` rows
           (catches a truncated or partially-written ``files`` table).
        3. Every ``files`` row has a matching ``files_fts`` row (catches a
           truncated ``files_fts`` table where the FTS virtual table was not
           fully populated, which would silently degrade path-token queries).

        If any condition fails the search layer falls back to the linear inventory
        scan for this snapshot.
        """
        row = self.conn.execute(
            "SELECT file_count FROM indexed_snapshots WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchone()
        if row is None:
            return False
        actual = self.conn.execute(
            "SELECT COUNT(*) AS c FROM files WHERE snapshot_id = ?", (snapshot_id,)
        ).fetchone()["c"]
        if actual != row["file_count"]:
            return False
        # Verify the FTS virtual table is in sync with the files table.
        fts_actual = self.conn.execute(
            "SELECT COUNT(*) AS c FROM files_fts fts "
            "JOIN files f ON f.file_uid = fts.rowid "
            "WHERE f.snapshot_id = ?",
            (snapshot_id,),
        ).fetchone()["c"]
        return fts_actual == actual

    def snapshot_has_content(self, snapshot_id: str) -> bool:
        row = self.conn.execute(
            "SELECT has_content FROM indexed_snapshots WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchone()
        return bool(row and row["has_content"])

    def latest_snapshot_ids(
        self,
        machine_id: Optional[str] = None,
        root_id: Optional[str] = None,
    ) -> List[str]:
        """Return the newest indexed snapshot per (machine_id, root_id)."""
        query = "SELECT snapshot_id, machine_id, root_id, created_at FROM indexed_snapshots"
        clauses = []
        params: List[Any] = []
        if machine_id:
            clauses.append("machine_id = ?")
            params.append(machine_id)
        if root_id:
            clauses.append("root_id = ?")
            params.append(root_id)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        # DESC ordering means the first row seen per scope is the latest.
        query += " ORDER BY created_at DESC, snapshot_id DESC"
        latest: Dict[tuple, str] = {}
        for row in self.conn.execute(query, params):
            key = (row["machine_id"], row["root_id"])
            if key not in latest:
                latest[key] = row["snapshot_id"]
        return list(latest.values())

    def fts_content_candidates(self, snapshot_ids: Iterable[str], content_query: str) -> Optional[List[int]]:
        """Conservatively narrow content-search candidates via FTS.

        CURRENTLY UNUSED by AtlasSearch because live-file freshness can diverge
        from indexed content (files mutate after indexing). Kept as a primitive
        for potential future immutable-snapshot or write-once-mode work where
        content staleness cannot occur.

        Return semantics (informational — see ADR-009):

        * ``None``  -> the query cannot be safely narrowed (subtoken substrings
          like ``oob`` ⊂ ``foobar``, Unicode queries, punctuation/operator-like
          queries). If this primitive were used, the caller would need to
          live-scan all candidates.
        * ``[]``    -> the query *is* safely narrowable and no document contains
          the required prefix tokens.
        * ``[uid…]``-> a conservative superset of the true matches.

        The live confirmation in ``_content_match`` would always be the truth
        source if this primitive were used as a filter gate.
        """
        snapshot_ids = list(snapshot_ids)
        if not snapshot_ids:
            return []

        safe_tokens = _safe_prefix_tokens(content_query)
        if not safe_tokens:
            # Not safely narrowable -> force a full live scan (no dropped hits).
            return None

        placeholders = ",".join("?" for _ in snapshot_ids)
        # Each left-bounded token begins a token in any matching document, so a
        # prefix query is a safe superset. AND-join (implicit) across tokens;
        # double-quote to avoid FTS operator interpretation (e.g. OR/NEAR).
        match = " ".join(f'"{t}"*' for t in safe_tokens)
        sql = (
            f"SELECT f.file_uid FROM files_fts fts "
            f"JOIN files f ON f.file_uid = fts.rowid "
            f"WHERE files_fts MATCH ? AND f.snapshot_id IN ({placeholders})"
        )
        try:
            rows = self.conn.execute(sql, [match, *snapshot_ids]).fetchall()
        except sqlite3.OperationalError:
            # Any unexpected MATCH parse issue -> conservative live scan.
            return None
        return [r["file_uid"] for r in rows]

    def query_metadata(
        self,
        snapshot_ids: List[str],
        ext: Optional[str] = None,
        min_size: Optional[int] = None,
        max_size: Optional[int] = None,
        after_epoch: Optional[float] = None,
        before_epoch: Optional[float] = None,
        restrict_uids: Optional[Iterable[int]] = None,
    ) -> List[sqlite3.Row]:
        """Fetch candidate file rows for the given snapshots using indexed SQL filters.

        Results are returned newest-snapshot-first, mirroring the registry's
        ``created_at DESC`` semantics used by the legacy linear search path:
        ``indexed_snapshots.created_at DESC``, with ``snapshot_id DESC`` as a
        deterministic tie-breaker (for equal/absent timestamps), then
        ``file_uid ASC`` within each snapshot.

        NOTE: ordering is by ``created_at``, NOT by lexicographic
        ``snapshot_id``. Snapshot ids have the form
        ``snap_{machine}__{root}__{timestamp}__{hash}`` — the timestamp is in
        the middle, so lexicographic order would sort by machine/root first, not
        chronologically. The ``created_at`` join makes "newest first" correct
        and keeps the output a reproducible contract across runs, vacuums, and
        SQLite versions.
        """
        if not snapshot_ids:
            return []
        placeholders = ",".join("?" for _ in snapshot_ids)
        # Join indexed_snapshots so we can order by created_at; select only the
        # files columns so the returned row shape is unchanged for callers.
        sql = (
            f"SELECT f.* FROM files f "
            f"JOIN indexed_snapshots s ON s.snapshot_id = f.snapshot_id "
            f"WHERE f.snapshot_id IN ({placeholders})"
        )
        params: List[Any] = list(snapshot_ids)

        if ext:
            sql += " AND f.ext = ?"
            params.append(ext)
        if min_size is not None:
            sql += " AND f.size_bytes >= ?"
            params.append(min_size)
        if max_size is not None:
            sql += " AND f.size_bytes <= ?"
            params.append(max_size)
        if after_epoch is not None:
            sql += " AND f.mtime_epoch IS NOT NULL AND f.mtime_epoch >= ?"
            params.append(after_epoch)
        if before_epoch is not None:
            sql += " AND f.mtime_epoch IS NOT NULL AND f.mtime_epoch <= ?"
            params.append(before_epoch)

        restrict_list = None if restrict_uids is None else list(restrict_uids)
        if restrict_list is not None:
            if not restrict_list:
                return []
            uid_placeholders = ",".join("?" for _ in restrict_list)
            sql += f" AND f.file_uid IN ({uid_placeholders})"
            params.extend(restrict_list)

        sql += " ORDER BY s.created_at DESC, f.snapshot_id DESC, f.file_uid ASC"
        return self.conn.execute(sql, params).fetchall()

    def stats(self) -> Dict[str, Any]:
        snap_count = self.conn.execute(
            "SELECT COUNT(*) AS c FROM indexed_snapshots"
        ).fetchone()["c"]
        file_count = self.conn.execute("SELECT COUNT(*) AS c FROM files").fetchone()["c"]
        content_snaps = self.conn.execute(
            "SELECT COUNT(*) AS c FROM indexed_snapshots WHERE has_content = 1"
        ).fetchone()["c"]
        return {
            "schema_version": INDEX_SCHEMA_VERSION,
            "indexed_snapshots": snap_count,
            "indexed_files": file_count,
            "content_snapshots": content_snaps,
        }


def _to_int_bool(value: Any) -> Optional[int]:
    if value is None:
        return None
    return 1 if value else 0


def _safe_epoch(mtime: Optional[str]) -> Optional[float]:
    if not mtime:
        return None
    try:
        from merger.lenskit.atlas.search import parse_iso_datetime

        return parse_iso_datetime(mtime).timestamp()
    except Exception:
        return None


def _read_text_safely(root_path: Path, rel_path: str, size_bytes: int) -> str:
    """Read a text file under root_path with traversal/symlink guards. Best-effort."""
    candidate = root_path / rel_path
    try:
        if candidate.is_symlink():
            return ""
        full = candidate.resolve(strict=False)
        full.relative_to(root_path)
        if not full.is_file() or full.is_symlink():
            return ""
        if full.stat().st_size > TEXT_DETECTION_MAX_BYTES:
            return ""
        with open(full, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except (OSError, ValueError, RuntimeError):
        return ""
