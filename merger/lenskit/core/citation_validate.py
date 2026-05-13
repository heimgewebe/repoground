import hashlib
import json
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List

from merger.lenskit.core.citation_id import make_citation_id
from merger.lenskit.core.path_security import resolve_secure_path

_CIT_RE = re.compile(r"^cit_[a-f0-9]{16}$")
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:")
_UNC_RE = re.compile(r"^\\\\")


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
    normalized_parts = [part for part in parts if part not in ("", ".")]
    if not normalized_parts:
        raise ValueError(f"{label}: path must not be empty")
    return "/".join(normalized_parts)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _fail_report(
    validation_run_id: str,
    errors: List[str],
    *,
    bundle_manifest_path: str = "",
    bundle_run_id: Any = None,
    canonical_md_sha256: Any = None,
    chunk_index_sha256: Any = None,
    canonical_md_actual_sha256: Any = None,
    chunk_index_actual_sha256: Any = None,
    error_kind: str = "validation_error",
) -> Dict[str, Any]:
    return {
        "status": "fail",
        "error_kind": error_kind,
        "bundle_manifest_path": bundle_manifest_path,
        "bundle_run_id": bundle_run_id,
        "validation_run_id": validation_run_id,
        "canonical_md_sha256": canonical_md_sha256,
        "chunk_index_sha256": chunk_index_sha256,
        "canonical_md_actual_sha256": canonical_md_actual_sha256,
        "chunk_index_actual_sha256": chunk_index_actual_sha256,
        "chunk_count": 0,
        "canonical_range_count": 0,
        "source_range_count": 0,
        "content_range_ref_count": 0,
        "citation_id_count": 0,
        "citation_id_duplicate_count": 0,
        "canonical_range_hash_ok_count": 0,
        "errors": errors,
        "warnings": [],
        "sample_citation_ids": [],
    }


def validate_bundle(manifest_path_str: str) -> Dict[str, Any]:
    """
    Validate citation readiness of a bundle manifest.

    Reads the manifest, resolves canonical_md and chunk_index_jsonl artifacts,
    verifies SHA256 hashes, and for every chunk checks canonical_range validity
    and derives the citation_id via make_citation_id(). Nothing is written.

    Returns a structured report dict.
    """
    validation_run_id = str(uuid.uuid4())
    errors: List[str] = []
    warnings: List[str] = []
    sample_citation_ids: List[str] = []

    chunk_count = 0
    canonical_range_count = 0
    source_range_count = 0
    content_range_ref_count = 0
    citation_id_count = 0
    citation_id_duplicate_count = 0
    canonical_range_hash_ok_count = 0
    seen_citation_ids: Dict[str, int] = {}

    # --- resolve manifest path ---
    manifest_path = Path(manifest_path_str)
    if not manifest_path.is_absolute():
        manifest_path = Path.cwd() / manifest_path
    manifest_path = manifest_path.resolve()
    bundle_manifest_path = str(manifest_path)

    if not manifest_path.exists():
        return _fail_report(
            validation_run_id,
            [f"Manifest not found: {manifest_path}"],
            bundle_manifest_path=bundle_manifest_path,
            error_kind="path_read_error",
        )
    if not manifest_path.is_file():
        return _fail_report(
            validation_run_id,
            [f"Manifest path is not a file: {manifest_path}"],
            bundle_manifest_path=bundle_manifest_path,
            error_kind="path_read_error",
        )

    manifest_dir = manifest_path.parent

    # --- load manifest ---
    try:
        with manifest_path.open("r", encoding="utf-8") as f:
            manifest = json.load(f)
    except json.JSONDecodeError as e:
        return _fail_report(
            validation_run_id,
            [f"Manifest is not valid JSON: {e}"],
            bundle_manifest_path=bundle_manifest_path,
            error_kind="path_read_error",
        )
    except OSError as e:
        return _fail_report(
            validation_run_id,
            [f"Cannot read manifest: {e}"],
            bundle_manifest_path=bundle_manifest_path,
            error_kind="path_read_error",
        )

    bundle_run_id = manifest.get("run_id")

    artifacts = manifest.get("artifacts", [])
    if not isinstance(artifacts, list):
        return _fail_report(
            validation_run_id,
            ["Manifest 'artifacts' field is not a list"],
            bundle_manifest_path=bundle_manifest_path,
            bundle_run_id=bundle_run_id,
        )

    canonical_md_artifact = None
    chunk_index_artifact = None
    for index, art in enumerate(artifacts):
        if not isinstance(art, dict):
            return _fail_report(
                validation_run_id,
                [f"Manifest artifact at index {index} is not an object"],
                bundle_manifest_path=bundle_manifest_path,
                bundle_run_id=bundle_run_id,
            )
        role = art.get("role", "")
        if role == "canonical_md" and canonical_md_artifact is None:
            canonical_md_artifact = art
        elif role == "chunk_index_jsonl" and chunk_index_artifact is None:
            chunk_index_artifact = art

    if canonical_md_artifact is None:
        return _fail_report(
            validation_run_id,
            ["Manifest has no artifact with role 'canonical_md'"],
            bundle_manifest_path=bundle_manifest_path,
            bundle_run_id=bundle_run_id,
        )
    if chunk_index_artifact is None:
        return _fail_report(
            validation_run_id,
            ["Manifest has no artifact with role 'chunk_index_jsonl'"],
            bundle_manifest_path=bundle_manifest_path,
            bundle_run_id=bundle_run_id,
        )

    canonical_md_rel_raw = canonical_md_artifact.get("path", "")
    chunk_index_rel_raw = chunk_index_artifact.get("path", "")
    canonical_md_manifest_sha = canonical_md_artifact.get("sha256", "")
    chunk_index_manifest_sha = chunk_index_artifact.get("sha256", "")
    actual_canonical_sha = None
    actual_chunk_sha = None

    try:
        canonical_md_rel = _normalize_relative_path(canonical_md_rel_raw, "canonical_md path")
        canonical_md_path = resolve_secure_path(manifest_dir, canonical_md_rel)
    except ValueError as e:
        return _fail_report(
            validation_run_id,
            [f"canonical_md path rejected: {e}"],
            bundle_manifest_path=bundle_manifest_path,
            bundle_run_id=bundle_run_id,
            canonical_md_sha256=canonical_md_manifest_sha,
            chunk_index_sha256=chunk_index_manifest_sha,
            error_kind="path_read_error",
        )

    try:
        chunk_index_rel = _normalize_relative_path(
            chunk_index_rel_raw, "chunk_index_jsonl path"
        )
        chunk_index_path = resolve_secure_path(manifest_dir, chunk_index_rel)
    except ValueError as e:
        return _fail_report(
            validation_run_id,
            [f"chunk_index_jsonl path rejected: {e}"],
            bundle_manifest_path=bundle_manifest_path,
            bundle_run_id=bundle_run_id,
            canonical_md_sha256=canonical_md_manifest_sha,
            chunk_index_sha256=chunk_index_manifest_sha,
            error_kind="path_read_error",
        )

    if not canonical_md_path.exists():
        return _fail_report(
            validation_run_id,
            [f"canonical_md file not found: {canonical_md_path}"],
            bundle_manifest_path=bundle_manifest_path,
            bundle_run_id=bundle_run_id,
            canonical_md_sha256=canonical_md_manifest_sha,
            chunk_index_sha256=chunk_index_manifest_sha,
            error_kind="path_read_error",
        )
    if not chunk_index_path.exists():
        return _fail_report(
            validation_run_id,
            [f"chunk_index_jsonl file not found: {chunk_index_path}"],
            bundle_manifest_path=bundle_manifest_path,
            bundle_run_id=bundle_run_id,
            canonical_md_sha256=canonical_md_manifest_sha,
            chunk_index_sha256=chunk_index_manifest_sha,
            error_kind="path_read_error",
        )

    # --- verify manifest SHAs ---
    try:
        actual_canonical_sha = _sha256_file(canonical_md_path)
    except OSError as e:
        return _fail_report(
            validation_run_id,
            [f"Cannot read canonical_md: {e}"],
            bundle_manifest_path=bundle_manifest_path,
            bundle_run_id=bundle_run_id,
            canonical_md_sha256=canonical_md_manifest_sha,
            chunk_index_sha256=chunk_index_manifest_sha,
            error_kind="path_read_error",
        )
    if not canonical_md_manifest_sha:
        errors.append("canonical_md sha256 is missing in manifest")
    elif not isinstance(canonical_md_manifest_sha, str) or not _SHA256_RE.fullmatch(
        canonical_md_manifest_sha
    ):
        errors.append(
            "canonical_md sha256 must be a 64-char lowercase hex string in manifest"
        )
    elif actual_canonical_sha != canonical_md_manifest_sha:
        errors.append(
            f"canonical_md SHA256 mismatch: manifest={canonical_md_manifest_sha!r} "
            f"actual={actual_canonical_sha!r}"
        )

    try:
        actual_chunk_sha = _sha256_file(chunk_index_path)
    except OSError as e:
        return _fail_report(
            validation_run_id,
            [f"Cannot read chunk_index_jsonl: {e}"],
            bundle_manifest_path=bundle_manifest_path,
            bundle_run_id=bundle_run_id,
            canonical_md_sha256=canonical_md_manifest_sha,
            chunk_index_sha256=chunk_index_manifest_sha,
            canonical_md_actual_sha256=actual_canonical_sha,
            error_kind="path_read_error",
        )
    if not chunk_index_manifest_sha:
        errors.append("chunk_index_jsonl sha256 is missing in manifest")
    elif not isinstance(chunk_index_manifest_sha, str) or not _SHA256_RE.fullmatch(
        chunk_index_manifest_sha
    ):
        errors.append(
            "chunk_index_jsonl sha256 must be a 64-char lowercase hex string in manifest"
        )
    elif actual_chunk_sha != chunk_index_manifest_sha:
        errors.append(
            f"chunk_index_jsonl SHA256 mismatch: manifest={chunk_index_manifest_sha!r} "
            f"actual={actual_chunk_sha!r}"
        )

    canonical_md_sha = actual_canonical_sha

    # --- read canonical_md bytes ---
    try:
        with canonical_md_path.open("rb") as f:
            canonical_md_bytes = f.read()
    except OSError as e:
        return _fail_report(
            validation_run_id,
            [f"Cannot read canonical_md: {e}"],
            bundle_manifest_path=bundle_manifest_path,
            bundle_run_id=bundle_run_id,
            canonical_md_sha256=canonical_md_manifest_sha,
            chunk_index_sha256=chunk_index_manifest_sha,
            canonical_md_actual_sha256=actual_canonical_sha,
            chunk_index_actual_sha256=actual_chunk_sha,
            error_kind="path_read_error",
        )

    canonical_md_file_size = len(canonical_md_bytes)

    # --- process chunk_index_jsonl line by line ---
    try:
        with chunk_index_path.open("r", encoding="utf-8") as f:
            lines = f.readlines()
    except OSError as e:
        return _fail_report(
            validation_run_id,
            [f"Cannot read chunk_index_jsonl: {e}"],
            bundle_manifest_path=bundle_manifest_path,
            bundle_run_id=bundle_run_id,
            canonical_md_sha256=canonical_md_manifest_sha,
            chunk_index_sha256=chunk_index_manifest_sha,
            canonical_md_actual_sha256=actual_canonical_sha,
            chunk_index_actual_sha256=actual_chunk_sha,
            error_kind="path_read_error",
        )

    for lineno, raw_line in enumerate(lines, start=1):
        raw_line = raw_line.strip()
        if not raw_line:
            continue

        chunk_count += 1

        try:
            chunk = json.loads(raw_line)
        except json.JSONDecodeError as e:
            errors.append(f"Line {lineno}: invalid JSON: {e}")
            continue

        if not isinstance(chunk, dict):
            errors.append(f"Line {lineno}: chunk must be a JSON object")
            continue

        if chunk.get("chunk_id") is None:
            errors.append(f"Line {lineno}: missing 'chunk_id'")

        # source_range: soft check only
        source_range = chunk.get("source_range")
        if source_range is not None:
            source_range_count += 1
            if not isinstance(source_range, dict):
                warnings.append(f"Line {lineno}: 'source_range' is not an object")

        # content_range_ref: report only
        if chunk.get("content_range_ref") is not None:
            content_range_ref_count += 1

        # canonical_range: mandatory
        cr = chunk.get("canonical_range")
        if cr is None:
            errors.append(f"Line {lineno}: missing 'canonical_range'")
            continue

        if not isinstance(cr, dict):
            errors.append(f"Line {lineno}: 'canonical_range' must be an object")
            continue

        canonical_range_count += 1

        art_role = cr.get("artifact_role")
        if art_role != "canonical_md":
            errors.append(
                f"Line {lineno}: canonical_range.artifact_role must be 'canonical_md', "
                f"got {art_role!r}"
            )

        cr_file_path_raw = cr.get("file_path", "")
        try:
            cr_file_path = _normalize_relative_path(
                cr_file_path_raw, "canonical_range.file_path"
            )
        except ValueError as e:
            errors.append(f"Line {lineno}: canonical_range.file_path rejected: {e}")
            continue

        if cr_file_path != canonical_md_rel:
            errors.append(
                f"Line {lineno}: canonical_range.file_path {cr_file_path_raw!r} "
                f"(normalized {cr_file_path!r}) does not match "
                f"manifest canonical_md path {canonical_md_rel_raw!r} "
                f"(normalized {canonical_md_rel!r})"
            )
            continue

        start_byte = cr.get("start_byte")
        end_byte = cr.get("end_byte")

        byte_ok = True
        if isinstance(start_byte, bool):
            errors.append(f"Line {lineno}: canonical_range.start_byte must not be bool")
            byte_ok = False
        elif not isinstance(start_byte, int):
            errors.append(f"Line {lineno}: canonical_range.start_byte must be an int")
            byte_ok = False

        if isinstance(end_byte, bool):
            errors.append(f"Line {lineno}: canonical_range.end_byte must not be bool")
            byte_ok = False
        elif not isinstance(end_byte, int):
            errors.append(f"Line {lineno}: canonical_range.end_byte must be an int")
            byte_ok = False

        if not byte_ok:
            continue

        if start_byte < 0:
            errors.append(
                f"Line {lineno}: canonical_range.start_byte must be >= 0, got {start_byte}"
            )
            continue

        if end_byte <= start_byte:
            errors.append(
                f"Line {lineno}: canonical_range.end_byte must be > start_byte "
                f"(start={start_byte}, end={end_byte})"
            )
            continue

        if end_byte > canonical_md_file_size:
            errors.append(
                f"Line {lineno}: canonical_range end_byte={end_byte} exceeds "
                f"file size={canonical_md_file_size}"
            )
            continue

        range_bytes = canonical_md_bytes[start_byte:end_byte]
        actual_range_sha = _sha256_bytes(range_bytes)

        cr_content_sha = cr.get("content_sha256", "")
        if not cr_content_sha:
            errors.append(f"Line {lineno}: canonical_range.content_sha256 is missing")
            continue

        if not isinstance(cr_content_sha, str) or not _SHA256_RE.fullmatch(cr_content_sha):
            errors.append(
                f"Line {lineno}: canonical_range.content_sha256 is not a valid "
                f"64-char lowercase hex string"
            )
            continue

        if actual_range_sha != cr_content_sha:
            errors.append(
                f"Line {lineno}: canonical_range content SHA256 mismatch: "
                f"expected={cr_content_sha!r} actual={actual_range_sha!r}"
            )
            continue

        canonical_range_hash_ok_count += 1

        try:
            cit_id = make_citation_id(canonical_md_sha, start_byte, end_byte, actual_range_sha)
        except (ValueError, TypeError) as e:
            errors.append(f"Line {lineno}: make_citation_id failed: {e}")
            continue

        if not _CIT_RE.fullmatch(cit_id):
            errors.append(
                f"Line {lineno}: derived citation_id has invalid format: {cit_id!r}"
            )
            continue

        citation_id_count += 1

        if cit_id in seen_citation_ids:
            citation_id_duplicate_count += 1
            errors.append(
                f"Line {lineno}: duplicate citation_id {cit_id!r} "
                f"(first seen at line {seen_citation_ids[cit_id]})"
            )
        else:
            seen_citation_ids[cit_id] = lineno
            if len(sample_citation_ids) < 5:
                sample_citation_ids.append(cit_id)

    status = "ok" if not errors else "fail"
    return {
        "status": status,
        "error_kind": "ok" if status == "ok" else "validation_error",
        "bundle_manifest_path": bundle_manifest_path,
        "bundle_run_id": bundle_run_id,
        "validation_run_id": validation_run_id,
        "canonical_md_sha256": canonical_md_manifest_sha,
        "chunk_index_sha256": chunk_index_manifest_sha,
        "canonical_md_actual_sha256": actual_canonical_sha,
        "chunk_index_actual_sha256": actual_chunk_sha,
        "chunk_count": chunk_count,
        "canonical_range_count": canonical_range_count,
        "source_range_count": source_range_count,
        "content_range_ref_count": content_range_ref_count,
        "citation_id_count": citation_id_count,
        "citation_id_duplicate_count": citation_id_duplicate_count,
        "canonical_range_hash_ok_count": canonical_range_hash_ok_count,
        "errors": errors,
        "warnings": warnings,
        "sample_citation_ids": sample_citation_ids,
    }
