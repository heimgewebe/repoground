"""
Core implementation of SQLite schema and index builder.
"""

import sqlite3
import json
import hashlib
import datetime
import logging
import re
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

INDEX_SCHEMA_VERSION = "v1"


def _parse_range_like_ref(raw_ref: Any, *, field_name: str, chunk_id: str) -> Dict[str, Any]:
    """Normalize a canonical/content range payload into dict form for hydration."""
    if isinstance(raw_ref, str):
        try:
            raw_ref = json.loads(raw_ref)
        except json.JSONDecodeError as e:
            raise RuntimeError(
                f"FTS hydration failed for chunk '{chunk_id}': invalid {field_name} JSON"
            ) from e
    if not isinstance(raw_ref, dict):
        raise RuntimeError(
            f"FTS hydration failed for chunk '{chunk_id}': {field_name} must be an object"
        )
    return raw_ref


def _resolve_dump_artifact_path(
    dump_path: Path,
    dump_manifest: Dict[str, Any],
    ref: Dict[str, Any],
) -> Path:
    """Resolve a dump_index artifact path and enforce relative-path boundaries."""
    artifacts = dump_manifest.get("artifacts", {})
    role = ref.get("artifact_role")
    if not isinstance(role, str) or not role:
        raise RuntimeError("range-like ref must include a non-empty artifact_role")

    target_path_str = None
    if isinstance(artifacts, dict):
        artifact_entry = artifacts.get(role)
        if isinstance(artifact_entry, dict):
            target_path_str = artifact_entry.get("path")
        if not target_path_str:
            for artifact in artifacts.values():
                if isinstance(artifact, dict) and artifact.get("role") == role:
                    target_path_str = artifact.get("path")
                    break
    elif isinstance(artifacts, list):
        for artifact in artifacts:
            if isinstance(artifact, dict) and artifact.get("role") == role:
                target_path_str = artifact.get("path")
                break

    if not isinstance(target_path_str, str) or not target_path_str:
        raise RuntimeError(f"Artifact with role '{role}' not found in dump_index")

    def _norm_rel_path(value: Any, *, field_name: str) -> str:
        if not isinstance(value, str) or not value:
            raise RuntimeError(f"{field_name} must be a non-empty string")
        if Path(value).is_absolute():
            raise RuntimeError(f"{field_name} must be a relative path, got: {value!r}")
        value_posix = value.replace("\\", "/")
        if value_posix.startswith("//"):
            raise RuntimeError(f"{field_name} must be a relative path, got: {value!r}")
        if re.match(r"^[A-Za-z]:", value_posix):
            raise RuntimeError(f"{field_name} must not contain a Windows drive prefix: {value!r}")
        if value_posix.startswith("./"):
            value_posix = value_posix[2:]
        if ".." in Path(value_posix).parts:
            raise RuntimeError(f"{field_name} must not contain parent directory segments: {value!r}")
        return Path(value_posix).as_posix()

    normalized_target_path = _norm_rel_path(target_path_str, field_name="manifest artifact path")
    ref_file_path = ref.get("file_path")
    if ref_file_path is not None:
        normalized_ref_file_path = _norm_rel_path(ref_file_path, field_name="ref file_path")
        if normalized_ref_file_path != normalized_target_path:
            raise RuntimeError(
                f"file_path mismatch: ref={normalized_ref_file_path} manifest={normalized_target_path}"
            )

    base_dir = dump_path.parent.resolve()
    target_path = (base_dir / normalized_target_path).resolve()
    try:
        target_path.relative_to(base_dir)
    except ValueError as e:
        raise RuntimeError(
            f"Artifact path '{target_path_str}' attempts to escape the dump_index directory"
        ) from e
    return target_path


def _hydrate_text_from_range_like_ref(
    dump_path: Path,
    dump_manifest: Dict[str, Any],
    raw_ref: Any,
    *,
    field_name: str,
    chunk_id: str,
) -> str:
    """Extract UTF-8 text for a byte range and verify its declared SHA256."""
    ref = _parse_range_like_ref(raw_ref, field_name=field_name, chunk_id=chunk_id)
    target_path = _resolve_dump_artifact_path(dump_path, dump_manifest, ref)
    if not target_path.exists():
        raise RuntimeError(
            f"FTS hydration failed for chunk '{chunk_id}': resolved artifact file not found: {target_path}"
        )

    start_byte = ref.get("start_byte")
    end_byte = ref.get("end_byte")
    expected_sha256 = ref.get("content_sha256")
    if (
        not isinstance(start_byte, int)
        or isinstance(start_byte, bool)
        or not isinstance(end_byte, int)
        or isinstance(end_byte, bool)
    ):
        raise RuntimeError(
            f"FTS hydration failed for chunk '{chunk_id}': {field_name} must include integer start_byte/end_byte"
        )
    if not isinstance(expected_sha256, str) or not expected_sha256:
        raise RuntimeError(
            f"FTS hydration failed for chunk '{chunk_id}': {field_name} must include content_sha256"
        )

    file_size = target_path.stat().st_size
    if start_byte < 0 or end_byte > file_size or start_byte > end_byte:
        raise RuntimeError(
            f"FTS hydration failed for chunk '{chunk_id}': range [{start_byte}:{end_byte}] is out of bounds for file size {file_size}"
        )
    if start_byte == end_byte:
        raise RuntimeError(
            f"FTS hydration failed for chunk '{chunk_id}': empty range [{start_byte}:{end_byte}] — a citation range must cover at least one byte"
        )

    with target_path.open("rb") as f:
        f.seek(start_byte)
        content_bytes = f.read(end_byte - start_byte)

    actual_sha256 = hashlib.sha256(content_bytes).hexdigest()
    if actual_sha256 != expected_sha256:
        raise RuntimeError(
            f"FTS hydration failed for chunk '{chunk_id}': hash mismatch. Expected: {expected_sha256}, Actual: {actual_sha256}"
        )

    try:
        return content_bytes.decode("utf-8")
    except UnicodeDecodeError as e:
        raise RuntimeError(
            f"FTS hydration failed for chunk '{chunk_id}': extracted range could not be decoded as UTF-8: {e}"
        ) from e


def _hydrate_text_from_legacy_source_file_ref(
    dump_path: Path,
    raw_ref: Any,
    *,
    field_name: str,
    chunk_id: str,
) -> str:
    """Hydrate via legacy range_resolver path for source_file refs only."""
    ref = _parse_range_like_ref(raw_ref, field_name=field_name, chunk_id=chunk_id)
    from ..core.range_resolver import resolve_range_ref

    resolved = resolve_range_ref(dump_path, ref)
    text = resolved.get("text")
    if not isinstance(text, str):
        raise RuntimeError(
            f"FTS hydration failed for chunk '{chunk_id}': legacy source_file resolution did not return text"
        )
    return text

def _compute_file_sha256(path: Path) -> str:
    """Compute SHA256 of a file."""
    h = hashlib.sha256()
    try:
        with path.open("rb") as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return "ERROR"

def create_schema(conn: sqlite3.Connection) -> None:
    """Create the SQLite schema for retrieval."""
    c = conn.cursor()

    # 1. Meta Table
    c.execute("""
        CREATE TABLE IF NOT EXISTS index_meta (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    # 2. Chunks Table (Structured Data)
    c.execute("""
        CREATE TABLE IF NOT EXISTS chunks (
            chunk_id TEXT PRIMARY KEY,
            repo_id TEXT,
            path TEXT,
            path_norm TEXT,
            layer TEXT,
            artifact_type TEXT,
            start_byte INTEGER,
            end_byte INTEGER,
            start_line INTEGER,
            end_line INTEGER,
            content_sha256 TEXT,
            size_bytes INTEGER,
            language TEXT,
            content_range_ref TEXT,
            source_file TEXT
        )
    """)

    # 3. FTS Table (Full Text Search)
    # Using separate content table pattern (manual sync)
    c.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
            chunk_id UNINDEXED,
            content,
            path_tokens
        )
    """)

    # Indices
    c.execute("CREATE INDEX IF NOT EXISTS idx_chunks_repo ON chunks(repo_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_chunks_path ON chunks(path_norm)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_chunks_layer ON chunks(layer)")

    conn.commit()

def build_index(dump_path: Path, chunk_path: Path, db_path: Path, config_payload: Optional[Dict[str, Any]] = None) -> None:
    """
    Builds the SQLite index from artifacts.
    """
    if db_path.exists():
        try:
            db_path.unlink()
        except OSError as e:
            raise RuntimeError(f"Could not remove existing DB {db_path}: {e}")

    dump_manifest = json.loads(dump_path.read_text(encoding="utf-8"))
    conn = sqlite3.connect(str(db_path))
    build_succeeded = False
    try:
        create_schema(conn)
        c = conn.cursor()

        # Diagnostics counters
        stats = {
            "total_lines": 0,
            "empty_lines": 0,
            "invalid_json_lines": 0,
            "missing_chunk_id_lines": 0,
            "ingested_chunks_count": 0,
            "fts_hydrated_from_canonical_range": 0,
            "fts_hydrated_from_range_ref": 0,
        }

        # 2. Ingest Chunks
        batch_size = 500
        batch_chunks = []
        batch_fts = []

        with chunk_path.open("r", encoding="utf-8") as f:
            for line in f:
                stats["total_lines"] += 1
                if not line.strip():
                    stats["empty_lines"] += 1
                    continue
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    stats["invalid_json_lines"] += 1
                    continue

                cid = chunk.get("chunk_id")
                if not cid:
                    stats["missing_chunk_id_lines"] += 1
                    continue

                repo = chunk.get("repo") or chunk.get("repo_id") or "unknown"
                path = chunk.get("path", "")
                path_norm = path.lower().replace("\\", "/")

                layer = chunk.get("layer", "unknown")
                atype = chunk.get("artifact_type", "unknown")

                sb = chunk.get("start_byte", 0)
                eb = chunk.get("end_byte", 0)
                sl = chunk.get("start_line", 0)
                el = chunk.get("end_line", 0)

                sha = chunk.get("sha256") or chunk.get("content_sha256") or ""
                size = chunk.get("size") or chunk.get("size_bytes") or 0
                lang = chunk.get("language", "")

                # FTS Content: prefer inline content, otherwise hydrate from canonical bundle ranges.
                content_text = chunk.get("content") or ""
                if not content_text:
                    # canonical_range is authoritative when present: it is a hash-verified pointer
                    # into canonical_md and will raise hard on any error.
                    # content_range_ref is used only as a backward-compatible fallback when
                    # canonical_range is absent — never as a silent alternative to a broken one.
                    raw_canonical_range = chunk.get("canonical_range")
                    if raw_canonical_range is not None:
                        try:
                            content_text = _hydrate_text_from_range_like_ref(
                                dump_path,
                                dump_manifest,
                                raw_canonical_range,
                                field_name="canonical_range",
                                chunk_id=cid,
                            )
                        except RuntimeError as e:
                            msg = str(e)
                            if msg.startswith("FTS hydration failed for chunk "):
                                raise RuntimeError(msg) from e
                            raise RuntimeError(
                                f"FTS hydration failed for chunk '{cid}' via canonical_range: {msg}"
                            ) from e
                        stats["fts_hydrated_from_canonical_range"] += 1
                    else:
                        raw_content_range_ref = chunk.get("content_range_ref")
                        if raw_content_range_ref is not None:
                            try:
                                parsed_ref = _parse_range_like_ref(
                                    raw_content_range_ref,
                                    field_name="content_range_ref",
                                    chunk_id=cid,
                                )
                                if parsed_ref.get("artifact_role") == "source_file":
                                    content_text = _hydrate_text_from_legacy_source_file_ref(
                                        dump_path,
                                        parsed_ref,
                                        field_name="content_range_ref",
                                        chunk_id=cid,
                                    )
                                else:
                                    content_text = _hydrate_text_from_range_like_ref(
                                        dump_path,
                                        dump_manifest,
                                        parsed_ref,
                                        field_name="content_range_ref",
                                        chunk_id=cid,
                                    )
                            except (RuntimeError, ValueError, FileNotFoundError) as e:
                                msg = str(e)
                                if msg.startswith("FTS hydration failed for chunk "):
                                    raise RuntimeError(msg) from e
                                raise RuntimeError(
                                    f"FTS hydration failed for chunk '{cid}' via content_range_ref: {msg}"
                                ) from e
                            stats["fts_hydrated_from_range_ref"] += 1
                    if not content_text:
                        logger.debug(
                            "Chunk '%s' has no inline content and no canonical/content range ref; FTS content will be empty.",
                            cid,
                        )

                # Path tokens: split by common delimiters
                path_tokens = path_norm.replace("/", " ").replace(".", " ").replace("_", " ").replace("-", " ")

                batch_chunks.append((
                    cid, repo, path, path_norm, layer, atype,
                    sb, eb, sl, el, sha, size, lang,
                    json.dumps(chunk.get("content_range_ref")) if chunk.get("content_range_ref") else None,
                    chunk.get("source_file", path)
                ))

                batch_fts.append((
                    cid, content_text, path_tokens
                ))

                stats["ingested_chunks_count"] += 1

                if len(batch_chunks) >= batch_size:
                    c.executemany("""
                        INSERT INTO chunks (chunk_id, repo_id, path, path_norm, layer, artifact_type,
                                          start_byte, end_byte, start_line, end_line, content_sha256, size_bytes, language, content_range_ref, source_file)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, batch_chunks)

                    c.executemany("""
                        INSERT INTO chunks_fts (chunk_id, content, path_tokens)
                        VALUES (?, ?, ?)
                    """, batch_fts)

                    batch_chunks = []
                    batch_fts = []

        # Final batch
        if batch_chunks:
            c.executemany("""
                INSERT INTO chunks (chunk_id, repo_id, path, path_norm, layer, artifact_type,
                                  start_byte, end_byte, start_line, end_line, content_sha256, size_bytes, language, content_range_ref, source_file)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, batch_chunks)

            c.executemany("""
                INSERT INTO chunks_fts (chunk_id, content, path_tokens)
                VALUES (?, ?, ?)
            """, batch_fts)

        # 1. Metadata (written last to include stats)
        dump_sha = _compute_file_sha256(dump_path)
        chunk_sha = _compute_file_sha256(chunk_path)

        # Try to extract config_sha256 and version from config_payload if passed,
        # or leave empty. Often config_payload is just {"cli_args": ...} right now,
        # but we can try to find config_sha256. If not available in payload, we
        # might default to empty string, but the caller should supply it.
        config_sha256 = (config_payload or {}).get("config_sha256", "")
        lenskit_version = (config_payload or {}).get("lenskit_version", "unknown")

        # Use real UTC timestamp
        now_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()

        meta_items = [
            ("schema_version", INDEX_SCHEMA_VERSION),
            ("canonical_dump_index_sha256", dump_sha),
            ("chunk_index_sha256", chunk_sha),
            ("created_at", now_utc),
            ("config_json", json.dumps(config_payload or {})),
            ("config_sha256", config_sha256),
            ("lenskit_version", lenskit_version)
        ]

        # Add stats to meta
        for k, v in stats.items():
            meta_items.append((f"ingest.{k}", str(v)))

        c.executemany("INSERT OR REPLACE INTO index_meta (key, value) VALUES (?, ?)", meta_items)

        conn.commit()
        build_succeeded = True
    finally:
        conn.close()
        if not build_succeeded and db_path.exists():
            try:
                db_path.unlink()
            except OSError:
                logger.warning("Could not remove partial DB after failed build: %s", db_path, exc_info=True)

    # Emit warning if issues found
    if stats["invalid_json_lines"] > 0 or stats["missing_chunk_id_lines"] > 0:
        logger.warning(
            "Index ingest had issues (invalid_json=%d, missing_id=%d). Total lines: %d",
            stats["invalid_json_lines"],
            stats["missing_chunk_id_lines"],
            stats["total_lines"],
        )

def verify_index(db_path: Path, dump_path: Path, chunk_path: Path) -> bool:
    """
    Verifies if the index is fresh and matches the artifacts.
    Returns True if valid, False if stale/invalid.
    """
    if not db_path.exists():
        return False

    try:
        conn = sqlite3.connect(str(db_path))
        try:
            c = conn.cursor()

            row_dump = c.execute("SELECT value FROM index_meta WHERE key='canonical_dump_index_sha256'").fetchone()
            if not row_dump: # fallback for older schemas if any
                row_dump = c.execute("SELECT value FROM index_meta WHERE key='dump_sha256'").fetchone()

            row_chunk = c.execute("SELECT value FROM index_meta WHERE key='chunk_index_sha256'").fetchone()
        finally:
            conn.close()

        if not row_dump or not row_chunk:
            return False

        stored_dump = row_dump[0]
        stored_chunk = row_chunk[0]

        current_dump = _compute_file_sha256(dump_path)
        if current_dump != stored_dump:
            return False

        current_chunk = _compute_file_sha256(chunk_path)
        if current_chunk != stored_chunk:
            return False

        return True

    except Exception:
        return False
