"""
Core implementation of SQLite schema and index builder.
"""

import sqlite3
import json
import hashlib
import datetime
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from ..core.range_resolver import resolve_range_ref
from ..core.constants import ArtifactRole

logger = logging.getLogger(__name__)

INDEX_SCHEMA_VERSION = "v1"

_JSONSCHEMA_UNAVAILABLE_MARKERS = (
    "jsonschema is unavailable",
    "no module named 'jsonschema'",
    "no module named jsonschema",
)


def _is_jsonschema_unavailable_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    if isinstance(exc, (ImportError, ModuleNotFoundError)):
        return "jsonschema" in msg
    return isinstance(exc, RuntimeError) and any(m in msg for m in _JSONSCHEMA_UNAVAILABLE_MARKERS)


def _resolve_canonical_range_ref_without_schema(manifest_path: Path, ref: Dict[str, Any]) -> Dict[str, Any]:
    """
    Resolve a canonical_md range_ref without jsonschema dependency.
    Used only as a fallback for retrieval hydration when jsonschema is unavailable.
    """
    role = ref.get("artifact_role")
    if role != ArtifactRole.CANONICAL_MD.value:
        raise ValueError(f"Fallback resolver only supports artifact_role='{ArtifactRole.CANONICAL_MD.value}', got: {role!r}")

    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")

    with manifest_path.open("r", encoding="utf-8") as f:
        manifest = json.load(f)

    target_path_str = None
    if manifest.get("contract") == "dump-index":
        artifact = (manifest.get("artifacts") or {}).get(ArtifactRole.CANONICAL_MD.value)
        if isinstance(artifact, dict):
            target_path_str = artifact.get("path")
    elif manifest.get("kind") == "repolens.bundle.manifest":
        for artifact in manifest.get("artifacts", []):
            if artifact.get("role") == ArtifactRole.CANONICAL_MD.value:
                target_path_str = artifact.get("path")
                break
    else:
        raise ValueError("Unsupported manifest format for fallback resolver")

    if not target_path_str:
        raise ValueError("Artifact with role 'canonical_md' not found in manifest")
    if Path(target_path_str).is_absolute():
        raise ValueError("Artifact path must be relative")

    ref_file_path = ref.get("file_path")
    if ref_file_path and ref_file_path != target_path_str:
        raise ValueError(f"file_path mismatch: ref={ref_file_path} manifest={target_path_str}")

    base_dir = manifest_path.parent.resolve()
    target_path = (base_dir / target_path_str).resolve()
    try:
        target_path.relative_to(base_dir)
    except ValueError:
        raise ValueError(f"Artifact path '{target_path_str}' attempts to escape the manifest directory")
    if not target_path.exists():
        raise FileNotFoundError(f"Resolved artifact file not found: {target_path}")

    start_byte = ref.get("start_byte")
    end_byte = ref.get("end_byte")
    expected_sha256 = ref.get("content_sha256")
    if not isinstance(start_byte, int) or not isinstance(end_byte, int):
        raise ValueError("range_ref must include integer start_byte/end_byte")
    if not isinstance(expected_sha256, str) or len(expected_sha256) != 64:
        raise ValueError("range_ref must include a 64-char content_sha256")

    file_size = target_path.stat().st_size
    if start_byte < 0 or end_byte > file_size or start_byte > end_byte:
        raise ValueError(f"Range [{start_byte}:{end_byte}] is out of bounds for file size {file_size}")

    with target_path.open("rb") as f:
        f.seek(start_byte)
        content_bytes = f.read(end_byte - start_byte)

    actual_sha256 = hashlib.sha256(content_bytes).hexdigest()
    if actual_sha256 != expected_sha256:
        raise ValueError(f"Hash mismatch. Expected: {expected_sha256}, Actual: {actual_sha256}")

    try:
        text = content_bytes.decode("utf-8")
    except UnicodeDecodeError as e:
        raise ValueError(f"Extracted range could not be decoded as UTF-8: {e}")

    return {
        "text": text,
        "sha256": actual_sha256,
        "bytes": len(content_bytes),
        "lines": [ref.get("start_line", -1), ref.get("end_line", -1)],
        "provenance": {
            "run_id": manifest.get("run_id"),
            "artifact_role": ArtifactRole.CANONICAL_MD.value,
        },
    }

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

    conn = sqlite3.connect(str(db_path))
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
            "fts_hydrated_from_range_ref": 0,
            "fts_hydrated_without_jsonschema": 0,
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

                # FTS Content: prefer inline content, fall back to content_range_ref
                content_text = chunk.get("content") or ""
                if not content_text:
                    raw_ref = chunk.get("content_range_ref")
                    if raw_ref is not None:
                        # raw_ref may already be a dict or a JSON string (stored either way)
                        if isinstance(raw_ref, str):
                            try:
                                raw_ref = json.loads(raw_ref)
                            except json.JSONDecodeError as e:
                                raise RuntimeError(
                                    f"FTS hydration failed for chunk '{cid}': invalid content_range_ref JSON"
                                ) from e
                        if not isinstance(raw_ref, dict):
                            raise RuntimeError(
                                f"FTS hydration failed for chunk '{cid}': content_range_ref must be an object"
                            )
                        try:
                            try:
                                resolved = resolve_range_ref(dump_path, raw_ref)
                            except Exception as e:
                                if _is_jsonschema_unavailable_error(e):
                                    resolved = _resolve_canonical_range_ref_without_schema(dump_path, raw_ref)
                                    stats["fts_hydrated_without_jsonschema"] += 1
                                else:
                                    raise
                            content_text = resolved["text"]
                            stats["fts_hydrated_from_range_ref"] += 1
                        except Exception as e:
                            raise RuntimeError(
                                f"FTS hydration failed for chunk '{cid}': {e}"
                            ) from e
                    else:
                        logger.debug(
                            "Chunk '%s' has no inline content and no content_range_ref; FTS content will be empty.",
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
    finally:
        conn.close()

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
