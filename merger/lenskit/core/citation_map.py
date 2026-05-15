"""
Citation Map Producer for citation_map_jsonl.

Pure functions for loading manifests, normalising chunk-index ranges,
deriving citation identifiers, verifying byte-range hashes, and
writing NDJSON output.  IO is isolated to produce_citation_map().
"""
import hashlib
import json
import os
import re
import uuid
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple

from merger.lenskit.core.citation_id import make_citation_id
from merger.lenskit.core.path_security import resolve_secure_path


_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:")
_UNC_RE = re.compile(r"^\\\\")

PRODUCED_BY = "citation_map_producer/v1"


class CitationMapError(Exception):
    pass


# ---------------------------------------------------------------------------
# Path helpers (mirror citation_validate.py conventions)
# ---------------------------------------------------------------------------

def _normalize_relative_path(raw: str, label: str) -> str:
    if not isinstance(raw, str):
        raise ValueError(f"{label}: path must be a string")
    if raw.startswith("/"):
        raise ValueError(f"{label}: absolute paths are forbidden")
    if _UNC_RE.match(raw):
        raise ValueError(f"{label}: UNC paths are forbidden")
    if raw.startswith("\\"):
        raise ValueError(f"{label}: Windows rooted paths are forbidden")
    if _WINDOWS_DRIVE_RE.match(raw):
        raise ValueError(f"{label}: Windows drive-prefixed paths are forbidden")
    parts = raw.replace("\\", "/").split("/")
    if ".." in parts:
        raise ValueError(f"{label}: path traversal ('..') is forbidden")
    normalized = [p for p in parts if p not in ("", ".")]
    if not normalized:
        raise ValueError(f"{label}: path must not be empty")
    return "/".join(normalized)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for buf in iter(lambda: f.read(65536), b""):
            h.update(buf)
    return h.hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_bytes_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            delete=False,
            dir=str(path.parent),
            prefix=f".{path.name}.",
            suffix=".tmp",
        ) as tmp_file:
            tmp_file.write(data)
            tmp_file.flush()
            os.fsync(tmp_file.fileno())
            tmp_path = Path(tmp_file.name)
        os.replace(tmp_path, path)
    finally:
        if tmp_path is not None and tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Manifest helpers
# ---------------------------------------------------------------------------

def load_manifest(manifest_path: Path) -> Dict[str, Any]:
    """Load and parse a bundle manifest JSON file."""
    with manifest_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def resolve_artifact_by_role(
    manifest: Dict[str, Any],
    role: str,
    manifest_dir: Path,
) -> Tuple[Dict[str, Any], str, Path]:
    """
    Find artifact by role in manifest and resolve its absolute path.

    Returns (artifact_dict, normalized_rel_path, resolved_abs_path).
    Raises CitationMapError if the role is absent or the path is unsafe.
    """
    artifacts = manifest.get("artifacts", [])
    artifact = next(
        (a for a in artifacts if isinstance(a, dict) and a.get("role") == role),
        None,
    )
    if artifact is None:
        raise CitationMapError(f"Manifest has no artifact with role '{role}'")

    raw_path = artifact.get("path", "")
    try:
        rel_path = _normalize_relative_path(raw_path, f"{role}.path")
    except ValueError as e:
        raise CitationMapError(f"Artifact path rejected for role '{role}': {e}")

    try:
        abs_path = resolve_secure_path(manifest_dir, rel_path)
    except ValueError as e:
        raise CitationMapError(f"Cannot resolve artifact path for role '{role}': {e}")

    if not abs_path.exists():
        raise CitationMapError(
            f"Artifact file not found for role '{role}': {abs_path}"
        )

    return artifact, rel_path, abs_path


# ---------------------------------------------------------------------------
# Range normalisation
# ---------------------------------------------------------------------------

def normalize_canonical_range(
    chunk: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """
    Return the canonical range dict for a chunk, normalising legacy input.

    Priority:
      1. chunk["canonical_range"]  if artifact_role == "canonical_md"
      2. chunk["content_range_ref"] if artifact_role == "canonical_md"

    Returns None when no usable range is found.
    content_range_ref is legacy-input only; the output always calls the result
    canonical_range.
    """
    cr = chunk.get("canonical_range")
    if cr is not None:
        if isinstance(cr, dict) and cr.get("artifact_role") == "canonical_md":
            return cr
        # canonical_range present but wrong role — do not silently fall back
        return None

    crr = chunk.get("content_range_ref")
    if crr is not None and isinstance(crr, dict):
        if crr.get("artifact_role") == "canonical_md":
            return crr

    return None


# ---------------------------------------------------------------------------
# repo_id resolution
# ---------------------------------------------------------------------------

def _first_nonempty_str(value: Any) -> Optional[str]:
    if isinstance(value, str) and value:
        return value
    return None


def resolve_repo_id(
    chunk: Dict[str, Any],
    normalized_range: Dict[str, Any],
    lineno: int,
) -> Tuple[str, str]:
    """
    Resolve repo_id and return (repo_id, source_description).

    Collects all non-empty sources in priority order:
      1. normalized_range["repo_id"]
      2. chunk["repo"]
      3. chunk["search_keys"]["repo_id"]

    If all present sources agree on the same value, returns the highest-priority one.
    If any two sources disagree, raises CitationMapError (ambiguity is a hard error;
    derivation from filenames is forbidden).
    If no source has a value, raises CitationMapError.
    """
    candidates: List[Tuple[str, str]] = []  # (source_label, value)

    v = _first_nonempty_str(normalized_range.get("repo_id"))
    if v:
        candidates.append(("range.repo_id", v))

    v = _first_nonempty_str(chunk.get("repo"))
    if v:
        candidates.append(("chunk.repo", v))

    sk = chunk.get("search_keys")
    if isinstance(sk, dict):
        v = _first_nonempty_str(sk.get("repo_id"))
        if v:
            candidates.append(("search_keys.repo_id", v))

    if not candidates:
        raise CitationMapError(
            f"Line {lineno}: no repo_id source found in chunk "
            "(range.repo_id, chunk.repo, and search_keys.repo_id all absent or empty)"
        )

    unique_values = {val for _, val in candidates}
    if len(unique_values) > 1:
        raise CitationMapError(
            f"Line {lineno}: ambiguous repo_id — sources disagree: "
            + ", ".join(f"{src}={val!r}" for src, val in candidates)
        )

    return candidates[0][1], candidates[0][0]


# ---------------------------------------------------------------------------
# Byte-range verification
# ---------------------------------------------------------------------------

def byte_range_to_line_range(
    canonical_md_bytes: bytes,
    start_byte: int,
    end_byte: int,
) -> Tuple[int, int]:
    """
    Compute 1-based global line numbers for [start_byte, end_byte) within canonical_md.

    Counts b'\\n' bytes directly without decoding; does not allocate slices.
    Assumes 0 <= start_byte < end_byte <= len(canonical_md_bytes).

    start_line: line containing the byte at start_byte.
    end_line:   line containing the last included byte (end_byte - 1).
    A b'\\n' byte belongs to the line it terminates.
    """
    start_line = 1 + canonical_md_bytes.count(b"\n", 0, start_byte)
    end_line = 1 + canonical_md_bytes.count(b"\n", 0, end_byte - 1)
    return start_line, end_line


def verify_byte_range_hash(
    canonical_md_bytes: bytes,
    start_byte: int,
    end_byte: int,
    expected_sha256: str,
    lineno: int,
) -> str:
    """
    Verify the byte slice [start_byte, end_byte) against expected_sha256.

    Returns the actual SHA256 on success.
    Raises CitationMapError on bounds violation or hash mismatch.
    """
    file_size = len(canonical_md_bytes)
    if start_byte < 0:
        raise CitationMapError(
            f"Line {lineno}: start_byte={start_byte} must be >= 0"
        )
    if end_byte <= start_byte:
        raise CitationMapError(
            f"Line {lineno}: end_byte={end_byte} must be > start_byte={start_byte}"
        )
    if end_byte > file_size:
        raise CitationMapError(
            f"Line {lineno}: end_byte={end_byte} exceeds file size={file_size}"
        )
    actual_sha = _sha256_bytes(canonical_md_bytes[start_byte:end_byte])
    if actual_sha != expected_sha256:
        raise CitationMapError(
            f"Line {lineno}: byte-range SHA256 mismatch: "
            f"expected={expected_sha256!r} actual={actual_sha!r}"
        )
    return actual_sha


# ---------------------------------------------------------------------------
# Row iterator (pure — yields structured results, never writes)
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class _ChunkResult:
    row: Optional[Dict[str, Any]]
    error: Optional[str]
    repo_id_source: Optional[str]


def iter_chunk_results(
    chunk_index_path: Path,
    canonical_md_bytes: bytes,
    canonical_md_rel: str,
    canonical_md_sha256: str,
    run_id: str,
) -> Iterator[_ChunkResult]:
    """
    Yield one _ChunkResult per non-empty line of the chunk index.

    On success: result.row is a schema-valid citation map entry dict.
    On error:   result.row is None; result.error describes the problem.
    """
    snapshot = {
        "run_id": run_id,
        "canonical_md_path": canonical_md_rel,
        "canonical_md_sha256": canonical_md_sha256,
    }

    with chunk_index_path.open("r", encoding="utf-8") as f:
        for lineno, raw_line in enumerate(f, start=1):
            raw_line = raw_line.strip()
            if not raw_line:
                continue

            try:
                chunk = json.loads(raw_line)
            except json.JSONDecodeError as e:
                yield _ChunkResult(None, f"Line {lineno}: invalid JSON: {e}", None)
                continue

            if not isinstance(chunk, dict):
                yield _ChunkResult(
                    None, f"Line {lineno}: chunk must be a JSON object", None
                )
                continue

            # --- normalise range ---
            norm_range = normalize_canonical_range(chunk)
            if norm_range is None:
                yield _ChunkResult(
                    None,
                    f"Line {lineno}: no valid canonical range found "
                    "(need canonical_range or content_range_ref with artifact_role='canonical_md')",
                    None,
                )
                continue

            # --- resolve repo_id ---
            try:
                repo_id, repo_id_src = resolve_repo_id(chunk, norm_range, lineno)
            except CitationMapError as e:
                yield _ChunkResult(None, str(e), None)
                continue

            # --- validate range fields ---
            raw_fp = norm_range.get("file_path", "")
            try:
                norm_fp = _normalize_relative_path(raw_fp, "range.file_path")
            except ValueError as e:
                yield _ChunkResult(
                    None, f"Line {lineno}: range.file_path rejected: {e}", None
                )
                continue

            if norm_fp != canonical_md_rel:
                yield _ChunkResult(
                    None,
                    f"Line {lineno}: range.file_path {raw_fp!r} "
                    f"(normalized {norm_fp!r}) does not match "
                    f"manifest canonical_md path {canonical_md_rel!r}",
                    None,
                )
                continue

            start_byte = norm_range.get("start_byte")
            end_byte = norm_range.get("end_byte")
            content_sha256 = norm_range.get("content_sha256", "")

            _int_error: Optional[str] = None
            for name, val in (("start_byte", start_byte), ("end_byte", end_byte)):
                if isinstance(val, bool) or not isinstance(val, int):
                    _int_error = f"Line {lineno}: range.{name} must be an int"
                    break
            if _int_error:
                yield _ChunkResult(None, _int_error, None)
                continue

            if (
                not content_sha256
                or not isinstance(content_sha256, str)
                or not _SHA256_RE.fullmatch(content_sha256)
            ):
                yield _ChunkResult(
                    None,
                    f"Line {lineno}: range.content_sha256 is missing or invalid",
                    None,
                )
                continue

            # --- verify byte range hash ---
            try:
                actual_sha = verify_byte_range_hash(
                    canonical_md_bytes,
                    start_byte,
                    end_byte,
                    content_sha256,
                    lineno,
                )
            except CitationMapError as e:
                yield _ChunkResult(None, str(e), None)
                continue

            # --- compute canonical_md-global line numbers (H5) ---
            # Input start_line/end_line are ignored: they are source-file-local
            # from the generator. Output line numbers are always canonical_md-global.
            start_line, end_line = byte_range_to_line_range(
                canonical_md_bytes, start_byte, end_byte
            )

            # --- derive citation_id ---
            try:
                citation_id = make_citation_id(
                    canonical_md_sha256, start_byte, end_byte, actual_sha
                )
            except (ValueError, TypeError) as e:
                yield _ChunkResult(
                    None, f"Line {lineno}: make_citation_id failed: {e}", None
                )
                continue

            row: Dict[str, Any] = {
                "citation_id": citation_id,
                "repo_id": repo_id,
                "snapshot": snapshot,
                "canonical_range": {
                    "file_path": canonical_md_rel,
                    "start_byte": start_byte,
                    "end_byte": end_byte,
                    "start_line": start_line,
                    "end_line": end_line,
                    "content_sha256": actual_sha,
                },
                "produced_by": PRODUCED_BY,
            }

            chunk_id = chunk.get("chunk_id")
            if chunk_id is not None:
                row["chunk_id"] = str(chunk_id)

            yield _ChunkResult(row, None, repo_id_src)


# ---------------------------------------------------------------------------
# IO adapter
# ---------------------------------------------------------------------------

_MANIFEST_SUFFIX = ".bundle.manifest.json"
_OUTPUT_SUFFIX = ".citation_map.jsonl"


def _default_output_path(manifest_path: Path) -> Path:
    """
    Derive citation map output path from manifest path.

    Requires the manifest to end with '.bundle.manifest.json'.
    Raises CitationMapError if the suffix is missing (would silently produce
    the same filename and overwrite the manifest).
    """
    name = manifest_path.name
    if not name.endswith(_MANIFEST_SUFFIX):
        raise CitationMapError(
            f"Cannot derive safe output path: manifest filename {name!r} "
            f"does not end with '{_MANIFEST_SUFFIX}'. "
            "Pass --output explicitly."
        )
    stem = name[: -len(_MANIFEST_SUFFIX)]
    return manifest_path.parent / (stem + _OUTPUT_SUFFIX)


def _remove_stale_output(
    output_path: Optional[Path],
    protected_paths: Set[Path],
) -> Optional[str]:
    """
    Remove a stale citation_map_jsonl left by a prior run, if it exists and is
    not a protected input (manifest, canonical_md, chunk_index_jsonl).

    Returns None when there is nothing to do or removal succeeds.
    Returns an error string if removal fails — the caller includes it in errors[].
    """
    if output_path is None:
        return None
    try:
        resolved = output_path.resolve()
    except OSError:
        return None
    if resolved in protected_paths:
        return None
    try:
        output_path.unlink(missing_ok=True)
        return None
    except OSError as e:
        return f"Could not remove stale output {str(output_path)!r}: {e}"


def _fail_report(
    production_run_id: str,
    manifest_path_str: str,
    errors: List[str],
    *,
    bundle_run_id: Any = None,
    error_kind: str = "production_error",
    snapshot_source: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "status": "fail",
        "error_kind": error_kind,
        "bundle_manifest_path": manifest_path_str,
        "bundle_run_id": bundle_run_id,
        "production_run_id": production_run_id,
        "canonical_md_sha256": None,
        "chunk_index_sha256": None,
        "output_path": None,
        "output_sha256": None,
        "output_bytes": None,
        "chunk_count": 0,
        "valid_chunk_count": 0,
        "citation_map_row_count": 0,
        "citation_id_count": 0,
        "citation_id_duplicate_count": 0,
        "repo_id_source": None,
        "snapshot_source": snapshot_source,
        "errors": errors,
        "warnings": [],
        "sample_rows": [],
    }


@dataclass(frozen=True, slots=True)
class CitationMapCoherence:
    coherent: bool
    skip_allowed: bool
    reason: str


def check_manifest_coherence_for_citation_map(manifest_path: Path) -> CitationMapCoherence:
    """
    Validate whether manifest pairing is suitable for citation-map emission.

    Structured semantics:
      - coherent=True: run producer (hard failures still surface)
      - coherent=False + skip_allowed=True: known benign mismatch case
      - coherent=False + skip_allowed=False: hard defect, caller should fail

    In pro-repo/multi-repo aggregation, a provisional manifest may pair
    canonical_md from repoA with chunk_index_jsonl from repoB. This must be a
    deliberate skip, not a failure. Other defects (invalid JSON, unsafe paths,
    missing artifacts) are hard errors and must not be silently downgraded.
    """
    manifest_dir = manifest_path.parent

    try:
        manifest = load_manifest(manifest_path)
    except (json.JSONDecodeError, OSError):
        return CitationMapCoherence(False, False, "invalid_manifest")

    canonical_md_artifact = next(
        (
            a
            for a in manifest.get("artifacts", [])
            if isinstance(a, dict) and a.get("role") == "canonical_md"
        ),
        None,
    )
    if canonical_md_artifact is None:
        return CitationMapCoherence(False, False, "missing_canonical_md_artifact")

    chunk_index_artifact = next(
        (
            a
            for a in manifest.get("artifacts", [])
            if isinstance(a, dict) and a.get("role") == "chunk_index_jsonl"
        ),
        None,
    )
    if chunk_index_artifact is None:
        return CitationMapCoherence(False, False, "missing_chunk_index_artifact")

    canonical_md_raw = canonical_md_artifact.get("path")
    if not isinstance(canonical_md_raw, str) or not canonical_md_raw:
        return CitationMapCoherence(False, False, "invalid_canonical_md_path")

    try:
        canonical_md_rel = _normalize_relative_path(canonical_md_raw, "canonical_md.path")
    except ValueError:
        return CitationMapCoherence(False, False, "unsafe_canonical_md_path")

    chunk_index_raw = chunk_index_artifact.get("path", "")
    if not isinstance(chunk_index_raw, str) or not chunk_index_raw:
        return CitationMapCoherence(False, False, "invalid_chunk_index_path")

    try:
        chunk_index_rel = _normalize_relative_path(chunk_index_raw, "chunk_index_jsonl.path")
    except ValueError:
        return CitationMapCoherence(False, False, "unsafe_chunk_index_path")

    try:
        chunk_index_abs = resolve_secure_path(manifest_dir, chunk_index_rel)
    except ValueError:
        return CitationMapCoherence(False, False, "unsafe_chunk_index_path")

    if not chunk_index_abs.exists() or not chunk_index_abs.is_file():
        return CitationMapCoherence(False, False, "missing_chunk_index_file")

    saw_nonempty_line = False
    try:
        with chunk_index_abs.open("r", encoding="utf-8") as f:
            for lineno, line in enumerate(f, start=1):
                if not line.strip():
                    continue
                saw_nonempty_line = True
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    return CitationMapCoherence(False, False, "invalid_chunk_index_json")

                normalized_range = normalize_canonical_range(chunk)
                if normalized_range is None:
                    return CitationMapCoherence(False, False, "missing_or_invalid_canonical_range")

                chunk_file_raw = normalized_range.get("file_path")
                if not isinstance(chunk_file_raw, str) or not chunk_file_raw:
                    return CitationMapCoherence(False, False, "missing_range_file_path")

                try:
                    chunk_file_rel = _normalize_relative_path(chunk_file_raw, f"range.file_path line {lineno}")
                except ValueError:
                    return CitationMapCoherence(False, False, "unsafe_range_file_path")

                if chunk_file_rel != canonical_md_rel:
                    return CitationMapCoherence(False, True, "range_file_path_mismatch")
    except OSError:
        return CitationMapCoherence(False, False, "unreadable_chunk_index")

    if not saw_nonempty_line:
        return CitationMapCoherence(True, False, "coherent_empty_chunk_index")

    return CitationMapCoherence(True, False, "coherent")


def is_manifest_coherent_for_citation_map(manifest_path: Path) -> bool:
    """Compatibility wrapper around check_manifest_coherence_for_citation_map."""
    return check_manifest_coherence_for_citation_map(manifest_path).coherent


def produce_citation_map(
    manifest_path_str: str,
    output_path_str: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Produce a citation_map_jsonl from a bundle manifest and return a report dict.

    The output NDJSON file is written adjacent to the manifest unless
    output_path_str is given.  Each line is a schema-valid citation map entry.
    An empty chunk index writes an empty file (0 bytes) with status=ok.
    """
    production_run_id = str(uuid.uuid4())
    errors: List[str] = []
    warnings: List[str] = []

    chunk_count = 0
    valid_chunk_count = 0
    citation_id_duplicate_count = 0
    seen_citation_ids: Dict[str, int] = {}
    sample_rows: List[Dict[str, Any]] = []
    repo_id_source: Optional[str] = None

    # --- resolve manifest path ---
    manifest_path = Path(manifest_path_str)
    if not manifest_path.is_absolute():
        manifest_path = Path.cwd() / manifest_path
    manifest_path = manifest_path.resolve()
    bundle_manifest_path_str = str(manifest_path)

    # --- determine output path as early as possible ---
    # This allows stale-output cleanup even for pre-iteration failures (SHA mismatch,
    # bad run_id, etc.).  output_path stays None only when the manifest suffix check
    # fails; that error is surfaced at the normal location below.
    output_path: Optional[Path] = None
    if output_path_str:
        p = Path(output_path_str)
        output_path = p if p.is_absolute() else Path.cwd() / p
    elif manifest_path.name.endswith(_MANIFEST_SUFFIX):
        stem = manifest_path.name[: -len(_MANIFEST_SUFFIX)]
        output_path = manifest_path.parent / (stem + _OUTPUT_SUFFIX)

    # Explicit --output paths may coincide with input artifacts not yet in
    # protected_paths. Skip early-fail cleanup for explicit paths until both
    # canonical_md and chunk_index_jsonl are resolved and protected.
    output_path_is_explicit = output_path_str is not None

    # protected_paths grows as artifacts are resolved; at minimum contains the manifest.
    protected_paths: Set[Path] = {manifest_path.resolve()}

    if not manifest_path.exists() or not manifest_path.is_file():
        _s = _remove_stale_output(output_path, protected_paths) if not output_path_is_explicit else None
        return _fail_report(
            production_run_id,
            bundle_manifest_path_str,
            [f"Manifest not found or not a file: {manifest_path}"] + ([_s] if _s else []),
            error_kind="path_read_error",
        )

    manifest_dir = manifest_path.parent

    # --- load manifest ---
    try:
        manifest = load_manifest(manifest_path)
    except (json.JSONDecodeError, OSError) as e:
        _s = _remove_stale_output(output_path, protected_paths) if not output_path_is_explicit else None
        return _fail_report(
            production_run_id,
            bundle_manifest_path_str,
            [f"Cannot load manifest: {e}"] + ([_s] if _s else []),
            error_kind="path_read_error",
        )

    bundle_run_id = manifest.get("run_id")

    # H3: run_id must be a non-empty string — an empty snapshot.run_id is invalid.
    if not isinstance(bundle_run_id, str) or not bundle_run_id:
        _s = _remove_stale_output(output_path, protected_paths) if not output_path_is_explicit else None
        return _fail_report(
            production_run_id,
            bundle_manifest_path_str,
            [
                f"Manifest 'run_id' is missing or empty: {bundle_run_id!r}. "
                "A non-empty run_id is required for snapshot identity."
            ] + ([_s] if _s else []),
            bundle_run_id=bundle_run_id,
        )

    # --- resolve canonical_md ---
    try:
        canonical_md_art, canonical_md_rel, canonical_md_path = (
            resolve_artifact_by_role(manifest, "canonical_md", manifest_dir)
        )
    except CitationMapError as e:
        _s = _remove_stale_output(output_path, protected_paths) if not output_path_is_explicit else None
        return _fail_report(
            production_run_id,
            bundle_manifest_path_str,
            [str(e)] + ([_s] if _s else []),
            bundle_run_id=bundle_run_id,
            error_kind="path_read_error",
        )

    canonical_md_manifest_sha = canonical_md_art.get("sha256", "")
    protected_paths.add(canonical_md_path.resolve())

    # --- resolve chunk_index_jsonl ---
    try:
        chunk_index_art, chunk_index_rel, chunk_index_path = (
            resolve_artifact_by_role(manifest, "chunk_index_jsonl", manifest_dir)
        )
    except CitationMapError as e:
        _s = _remove_stale_output(output_path, protected_paths) if not output_path_is_explicit else None
        return _fail_report(
            production_run_id,
            bundle_manifest_path_str,
            [str(e)] + ([_s] if _s else []),
            bundle_run_id=bundle_run_id,
            error_kind="path_read_error",
        )

    chunk_index_manifest_sha = chunk_index_art.get("sha256", "")
    protected_paths.add(chunk_index_path.resolve())

    # --- verify SHAs ---
    try:
        actual_canonical_sha = _sha256_file(canonical_md_path)
    except OSError as e:
        _s = _remove_stale_output(output_path, protected_paths)
        return _fail_report(
            production_run_id,
            bundle_manifest_path_str,
            [f"Cannot read canonical_md: {e}"] + ([_s] if _s else []),
            bundle_run_id=bundle_run_id,
            error_kind="path_read_error",
        )

    if actual_canonical_sha != canonical_md_manifest_sha:
        _s = _remove_stale_output(output_path, protected_paths)
        return _fail_report(
            production_run_id,
            bundle_manifest_path_str,
            [
                f"canonical_md SHA256 mismatch: "
                f"manifest={canonical_md_manifest_sha!r} actual={actual_canonical_sha!r}"
            ] + ([_s] if _s else []),
            bundle_run_id=bundle_run_id,
        )

    try:
        actual_chunk_sha = _sha256_file(chunk_index_path)
    except OSError as e:
        _s = _remove_stale_output(output_path, protected_paths)
        return _fail_report(
            production_run_id,
            bundle_manifest_path_str,
            [f"Cannot read chunk_index_jsonl: {e}"] + ([_s] if _s else []),
            bundle_run_id=bundle_run_id,
            error_kind="path_read_error",
        )

    if actual_chunk_sha != chunk_index_manifest_sha:
        _s = _remove_stale_output(output_path, protected_paths)
        return _fail_report(
            production_run_id,
            bundle_manifest_path_str,
            [
                f"chunk_index_jsonl SHA256 mismatch: "
                f"manifest={chunk_index_manifest_sha!r} actual={actual_chunk_sha!r}"
            ] + ([_s] if _s else []),
            bundle_run_id=bundle_run_id,
        )

    # --- read canonical_md bytes ---
    try:
        canonical_md_bytes = canonical_md_path.read_bytes()
    except OSError as e:
        _s = _remove_stale_output(output_path, protected_paths)
        return _fail_report(
            production_run_id,
            bundle_manifest_path_str,
            [f"Cannot read canonical_md bytes: {e}"] + ([_s] if _s else []),
            bundle_run_id=bundle_run_id,
            error_kind="path_read_error",
        )

    # If output_path is still None, the manifest filename lacks the required suffix.
    if output_path is None:
        return _fail_report(
            production_run_id,
            bundle_manifest_path_str,
            [
                f"Cannot derive safe output path: manifest filename {manifest_path.name!r} "
                f"does not end with '{_MANIFEST_SUFFIX}'. Pass --output explicitly."
            ],
            bundle_run_id=bundle_run_id,
        )

    # H2: output path must not collide with any input artifact.
    output_path_resolved = output_path.resolve()
    if output_path_resolved in protected_paths:
        return _fail_report(
            production_run_id,
            bundle_manifest_path_str,
            [
                f"Output path {str(output_path)!r} collides with an input artifact "
                "(manifest, canonical_md, or chunk_index_jsonl). "
                "Pass --output to specify a safe destination."
            ],
            bundle_run_id=bundle_run_id,
        )

    # --- iterate rows and collect ---
    output_lines: List[str] = []

    for result in iter_chunk_results(
        chunk_index_path,
        canonical_md_bytes,
        canonical_md_rel,
        actual_canonical_sha,
        bundle_run_id or "",
    ):
        chunk_count += 1

        if result.error is not None:
            errors.append(result.error)
            continue

        row = result.row

        # Track repo_id_source from first valid chunk
        if repo_id_source is None and result.repo_id_source is not None:
            repo_id_source = result.repo_id_source

        citation_id = row["citation_id"]

        if citation_id in seen_citation_ids:
            citation_id_duplicate_count += 1
            errors.append(
                f"duplicate citation_id {citation_id!r} "
                f"(first at row {seen_citation_ids[citation_id]})"
            )
            continue

        seen_citation_ids[citation_id] = valid_chunk_count + 1
        valid_chunk_count += 1

        if len(sample_rows) < 3:
            sample_rows.append(row)

        output_lines.append(json.dumps(row, ensure_ascii=False))

    citation_id_count = len(seen_citation_ids)

    # --- write output or clean up stale file ---
    output_sha256: Optional[str] = None
    output_bytes_count: Optional[int] = None
    written_output_path: Optional[str] = None

    if errors:
        status = "fail"
        # Remove any stale output from a prior successful run at the same path.
        # output_path is safe (collision check above ensures it is not a protected input).
        _s = _remove_stale_output(output_path, protected_paths)
        if _s:
            errors.append(_s)
    else:
        status = "ok"
        # A: Always write, even when there are no rows (empty chunk index → empty file).
        ndjson_bytes = (
            ("\n".join(output_lines) + "\n").encode("utf-8") if output_lines else b""
        )
        try:
            _write_bytes_atomic(output_path, ndjson_bytes)
        except OSError as e:
            return _fail_report(
                production_run_id,
                bundle_manifest_path_str,
                [f"Cannot write output: {e}"],
                bundle_run_id=bundle_run_id,
                error_kind="path_read_error",
            )
        output_sha256 = _sha256_bytes(ndjson_bytes)
        output_bytes_count = len(ndjson_bytes)
        written_output_path = str(output_path)

    return {
        "status": status,
        "error_kind": "ok" if status == "ok" else "production_error",
        "bundle_manifest_path": bundle_manifest_path_str,
        "bundle_run_id": bundle_run_id,
        "production_run_id": production_run_id,
        "canonical_md_sha256": actual_canonical_sha,
        "chunk_index_sha256": actual_chunk_sha,
        "output_path": written_output_path,
        "output_sha256": output_sha256,
        "output_bytes": output_bytes_count,
        "chunk_count": chunk_count,
        "valid_chunk_count": valid_chunk_count,
        "citation_map_row_count": len(output_lines) if status == "ok" else 0,
        "citation_id_count": citation_id_count,
        "citation_id_duplicate_count": citation_id_duplicate_count,
        "repo_id_source": repo_id_source,
        "snapshot_source": "bundle_manifest",
        "errors": errors,
        "warnings": warnings,
        "sample_rows": sample_rows,
    }
