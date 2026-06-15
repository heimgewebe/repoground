"""
Output Health writer for Lenskit bundles.

Computes a machine-readable diagnostic health report for an output bundle and
writes it as ``<stem>.output_health.json``.

Design contract:
- Checks primary artifacts (manifest, canonical_md, chunk_index, sqlite_index).
- NO self-hash circularity: output_health.json does NOT verify its own SHA256.
- The bundle manifest is updated by the caller AFTER this module writes the file.
- Blocking checks failing → verdict "fail".
- Non-blocking warnings only → verdict "warn".
- No errors and no warnings → verdict "pass".
"""

from __future__ import annotations

import hashlib
import importlib
import json
import logging
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .clock import now_utc

from .dependency_diagnostics import jsonschema_dependency


def _probe_jsonschema_available() -> bool:
    try:
        importlib.import_module("jsonschema")
    except ImportError:
        return False
    return True


_JSONSCHEMA_AVAILABLE = _probe_jsonschema_available()

logger = logging.getLogger(__name__)


def _sha256_file(path: Path) -> Optional[str]:
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
        return None


def _chunk_index_stats(chunk_index_path: Optional[Path]) -> Tuple[int, int, int, int]:
    """
    Validate chunk_index.jsonl and return (chunk_count, invalid_json_count, missing_id_count, empty_line_count).
    
    A valid chunk line must be:
    - non-empty
    - valid JSON
    - object-form JSON
    - contains a non-empty chunk identifier in 'chunk_id' or 'id'
    """
    if not chunk_index_path or not chunk_index_path.exists():
        return 0, 0, 0, 0
    
    chunk_count = 0
    invalid_json_count = 0
    missing_id_count = 0
    empty_line_count = 0
    
    try:
        with chunk_index_path.open("r", encoding="utf-8") as f:
            for line in f:
                line_stripped = line.rstrip("\n\r")
                if not line_stripped:
                    empty_line_count += 1
                    continue
                
                try:
                    obj = json.loads(line_stripped)
                    if not isinstance(obj, dict):
                        invalid_json_count += 1
                        continue
                    
                    # A chunk is valid when either chunk_id or id is present and non-empty.
                    has_valid_id = False
                    for key in ("chunk_id", "id"):
                        cid = obj.get(key)
                        if isinstance(cid, str) and cid.strip():
                            has_valid_id = True
                            break

                    if not has_valid_id:
                        missing_id_count += 1
                        continue
                    
                    chunk_count += 1
                except json.JSONDecodeError:
                    invalid_json_count += 1
    except UnicodeError:
        # Treat decode failures as invalid line input to avoid hard crashes on corrupt JSONL.
        invalid_json_count += 1
    except OSError:
        pass
    
    return chunk_count, invalid_json_count, missing_id_count, empty_line_count


def _check_file_hash(path: Optional[Path], expected_sha256: Optional[str]) -> Tuple[str, Optional[str]]:
    """
    Returns (status, actual_sha256).
    status is one of: ok, missing_file, missing_expected_hash, hash_mismatch, read_error.
    """
    if not path or not path.exists():
        return "missing_file", None
    actual = _sha256_file(path)
    if actual is None:
        return "read_error", None
    if not expected_sha256:
        return "missing_expected_hash", actual
    if actual != expected_sha256:
        return "hash_mismatch", actual
    return "ok", actual


def _sqlite_checks(
    sqlite_path: Path,
    chunk_count: int,
) -> Tuple[Dict[str, Any], List[str]]:
    """
    Run all required SQLite checks and return a partial check dict.
    Returns dict with keys:
        sqlite_row_count, sqlite_row_count_matches_chunk_count,
        sqlite_fts_row_count, sqlite_fts_row_count_matches_chunk_count,
        fts_content_non_empty, fts_empty_row_count
    plus optional errors list.
    """
    result: Dict[str, Any] = {
        "sqlite_row_count": None,
        "sqlite_row_count_matches_chunk_count": None,
        "sqlite_fts_row_count": None,
        "sqlite_fts_row_count_matches_chunk_count": None,
        "fts_content_non_empty": None,
        "fts_empty_row_count": None,
    }
    errors: List[str] = []
    try:
        conn = sqlite3.connect(str(sqlite_path))
        try:
            c = conn.cursor()
            row_count = c.execute("SELECT count(*) FROM chunks").fetchone()[0]
            result["sqlite_row_count"] = row_count

            fts_count = c.execute("SELECT count(*) FROM chunks_fts").fetchone()[0]
            result["sqlite_fts_row_count"] = fts_count
            result["sqlite_fts_row_count_matches_chunk_count"] = fts_count == chunk_count

            fts_stats = c.execute(
                "SELECT avg(length(content)), max(length(content)) FROM chunks_fts"
            ).fetchone()
            avg_len = fts_stats[0] or 0
            max_len = fts_stats[1] or 0

            empty_count = c.execute(
                "SELECT count(*) FROM chunks_fts WHERE content IS NULL OR length(content) = 0"
            ).fetchone()[0]
            result["fts_empty_row_count"] = empty_count
            result["fts_content_non_empty"] = (
                avg_len > 0 and max_len > 0 and empty_count == 0
            )
        finally:
            conn.close()
    except Exception as e:
        errors.append(f"SQLite check failed: {e}")
    return result, errors


_JSONSCHEMA_UNAVAILABLE_MARKERS = (
    "jsonschema is unavailable",
    "no module named 'jsonschema'",
    "no module named jsonschema",
)


def _is_jsonschema_unavailable_error(exc: Exception) -> bool:
    """Return True when exc signals that jsonschema is not installed, not a data error.

    Covers three cases that all mean the same thing (dependency missing):
    - RuntimeError raised by range_resolver._require_jsonschema()
    - ImportError / ModuleNotFoundError if the import itself propagates out
    """
    msg = str(exc).lower()
    if isinstance(exc, (ImportError, ModuleNotFoundError)):
        return "jsonschema" in msg
    return isinstance(exc, RuntimeError) and any(m in msg for m in _JSONSCHEMA_UNAVAILABLE_MARKERS)


def _range_ref_validation(mode: str, reason: str) -> Dict[str, str]:
    return {"mode": mode, "engine": "range_resolver", "reason": reason}


def _range_ref_check(
    dump_index_path: Optional[Path],
    chunk_index_path: Optional[Path],
) -> Tuple[Optional[bool], List[str], str, Dict[str, str]]:
    """
    Find one chunk with canonical_range (or legacy content_range_ref) and attempt
    resolution.

    Returns (ok, messages, status, validation) where:
      ok=True,  status="ok"               — at least one ref resolved successfully
      ok=False, status="fail"             — real semantic / structural failure
      ok=None,  status="environment_error"— jsonschema not installed; check not executable
      ok=None,  status="no_range_ref"     — no range reference found (inline-only bundle)
      ok=None,  status="unavailable"      — required input file missing

    messages go to errors when ok=False, to warnings otherwise.
    """
    not_applicable = _range_ref_validation(
        "skipped_unavailable", "check_not_applicable"
    )
    if not chunk_index_path or not chunk_index_path.exists():
        return None, ["chunk_index not available for range_ref check"], "unavailable", not_applicable
    if not dump_index_path or not dump_index_path.exists():
        return None, ["dump_index not available for range_ref check"], "unavailable", not_applicable

    sample_ref = None
    try:
        with chunk_index_path.open("r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(chunk, dict):
                    continue
                raw_ref = chunk.get("canonical_range")
                if raw_ref is None:
                    raw_ref = chunk.get("content_range_ref")
                if raw_ref is not None:
                    if isinstance(raw_ref, str):
                        try:
                            raw_ref = json.loads(raw_ref)
                        except json.JSONDecodeError as e:
                            return (
                                False,
                                [f"invalid range reference JSON string: {e}"],
                                "fail",
                                _range_ref_validation(
                                    "structural_precheck", "malformed_range_ref"
                                ),
                            )
                    if not isinstance(raw_ref, dict):
                        return (
                            False,
                            [f"range reference must be an object, got {type(raw_ref).__name__}"],
                            "fail",
                            _range_ref_validation(
                                "structural_precheck", "malformed_range_ref"
                            ),
                        )
                    sample_ref = raw_ref
                    break
    except (OSError, UnicodeError) as e:
        return None, [f"Could not read chunk_index: {e}"], "unavailable", not_applicable

    if sample_ref is None:
        # No range_ref present in any chunk; this is normal for inline-only bundles
        # but should be flagged as a non-blocking issue
        return None, ["no range reference found; range_ref check skipped"], "no_range_ref", not_applicable

    try:
        from .range_resolver import resolve_range_ref
        resolve_range_ref(dump_index_path, sample_ref)
        return True, [], "ok", _range_ref_validation("jsonschema", "available")
    except Exception as e:
        if _is_jsonschema_unavailable_error(e):
            # jsonschema is an optional runtime dependency; its absence means the check
            # cannot be executed — this is epistemic emptiness, not proof of broken data.
            return (
                None,
                ["range_ref schema validation skipped: jsonschema unavailable"],
                "environment_error",
                _range_ref_validation(
                    "skipped_unavailable", "dependency_unavailable"
                ),
            )
        if "schema file not found" in str(e).lower():
            return (
                False,
                [f"range_ref resolution failed: {e}"],
                "fail",
                _range_ref_validation("skipped_unavailable", "schema_missing"),
            )
        return (
            False,
            [f"range_ref resolution failed: {e}"],
            "fail",
            _range_ref_validation("jsonschema", "available"),
        )


def compute_output_health(
    *,
    run_id: str,
    stem: str,
    primary_manifest_path: Optional[Path],
    canonical_md_path: Optional[Path],
    chunk_index_path: Optional[Path],
    dump_index_path: Optional[Path],
    sqlite_index_path: Optional[Path],
    redact_secrets: bool,
    canonical_md_required: bool = True,
    chunk_index_required: bool = True,
    sqlite_index_required: Optional[bool] = None,
    # Expected hashes from dump_index / bundle manifest for cross-checking
    expected_canonical_md_sha256: Optional[str] = None,
    expected_chunk_index_sha256: Optional[str] = None,
    # Optional diagnostics
    retrieval_eval_path: Optional[Path] = None,
    retrieval_eval_sha256: Optional[str] = None,
    # Agent reading pack (navigation entry-point). Non-blocking in v1.
    agent_reading_pack_path: Optional[Path] = None,
    agent_reading_pack_expected: bool = False,
    excluded_noise: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Compute the output health report.  Does NOT write to disk.
    Returns a dict conforming to output-health.v1.schema.json.
    
    Note: primary_manifest_path is the dump_index or primary artifact manifest,
    NOT the final bundle manifest (which is written after health is computed).
    This avoids self-referential circularity: output_health.json does not verify
    its own SHA256 or its own entry in the final bundle manifest.
    """
    warnings: List[str] = []
    errors: List[str] = []
    checks: Dict[str, Any] = {}

    if sqlite_index_required is None:
        # Backward-compatible fallback: if callers do not provide an explicit
        # expectation, require SQLite checks only when a SQLite path is present.
        sqlite_index_required = sqlite_index_path is not None

    # ── manifest_present ────────────────────────────────────────────────────
    # In this implementation, this checks the primary manifest (dump_index), not the final
    # bundle manifest (which is written after health is computed).
    # This avoids: output_health.json checking its own entry.
    manifest_present = bool(primary_manifest_path and primary_manifest_path.exists())
    checks["manifest_present"] = manifest_present
    if not manifest_present:
        errors.append("primary artifact manifest is missing")

    # ── canonical_md_hash_ok ────────────────────────────────────────────────
    checks["canonical_md_required"] = bool(canonical_md_required)
    if canonical_md_required:
        canonical_status, _ = _check_file_hash(canonical_md_path, expected_canonical_md_sha256)
        checks["canonical_md_hash_ok"] = canonical_status == "ok"
        if canonical_status == "missing_file":
            errors.append("canonical_md hash check failed: file missing")
        elif canonical_status == "missing_expected_hash":
            errors.append("canonical_md hash check failed: expected sha256 missing")
        elif canonical_status == "hash_mismatch":
            errors.append("canonical_md hash check failed: hash mismatch")
        elif canonical_status == "read_error":
            errors.append("canonical_md hash check failed: could not read file")
    else:
        checks["canonical_md_hash_ok"] = None

    # ── chunk_index_hash_ok ─────────────────────────────────────────────────
    checks["chunk_index_required"] = bool(chunk_index_required)
    if chunk_index_required:
        chunk_status, _ = _check_file_hash(chunk_index_path, expected_chunk_index_sha256)
        checks["chunk_index_hash_ok"] = chunk_status == "ok"
        if chunk_status == "missing_file":
            errors.append("chunk_index hash check failed: file missing")
        elif chunk_status == "missing_expected_hash":
            errors.append("chunk_index hash check failed: expected sha256 missing")
        elif chunk_status == "hash_mismatch":
            errors.append("chunk_index hash check failed: hash mismatch")
        elif chunk_status == "read_error":
            errors.append("chunk_index hash check failed: could not read file")
    else:
        checks["chunk_index_hash_ok"] = None

    # ── chunk_count ─────────────────────────────────────────────────────────
    chunk_count, chunk_invalid_json_count, chunk_missing_id_count, chunk_empty_line_count = _chunk_index_stats(
        chunk_index_path
    )
    checks["chunk_count"] = chunk_count
    checks["chunk_invalid_json_line_count"] = chunk_invalid_json_count
    checks["chunk_missing_id_line_count"] = chunk_missing_id_count
    checks["chunk_empty_line_count"] = chunk_empty_line_count
    
    # Chunk validation errors are blocking
    if chunk_index_required and chunk_invalid_json_count > 0:
        errors.append(
            f"chunk_index.jsonl has {chunk_invalid_json_count} invalid or non-object JSON line(s)"
        )
    if chunk_index_required and chunk_missing_id_count > 0:
        errors.append(f"chunk_index.jsonl has {chunk_missing_id_count} line(s) missing valid id/chunk_id")
    if chunk_index_required and chunk_count == 0 and chunk_index_path and chunk_index_path.exists():
        errors.append("chunk_index.jsonl has no valid chunk entries")

    # ── sqlite ──────────────────────────────────────────────────────────────
    sqlite_checks_required = bool(sqlite_index_required)
    sqlite_present = bool(sqlite_index_path and sqlite_index_path.exists())
    checks["sqlite_present"] = sqlite_present
    checks["sqlite_checks_required"] = sqlite_checks_required

    if sqlite_present:
        sq, sq_errors = _sqlite_checks(sqlite_index_path, chunk_count)
        checks.update(sq)
        if sq_errors:
            errors.extend(sq_errors)
        else:
            # Row count match check
            sqlite_row_count = sq.get("sqlite_row_count")
            if sqlite_row_count is not None:
                row_match = sqlite_row_count == chunk_count
                checks["sqlite_row_count_matches_chunk_count"] = row_match
                if not row_match:
                    errors.append(
                        f"SQLite row count ({sqlite_row_count}) != chunk count ({chunk_count})"
                    )

            # FTS row count BLOCKING check
            sqlite_fts_row_count = sq.get("sqlite_fts_row_count")
            if sqlite_fts_row_count is not None:
                fts_row_match = sqlite_fts_row_count == chunk_count
                if not fts_row_match:
                    errors.append(
                        f"SQLite FTS row count ({sqlite_fts_row_count}) != chunk count ({chunk_count})"
                    )

            # FTS content check
            fts_ok = sq.get("fts_content_non_empty")
            if fts_ok is False:
                errors.append(
                    "SQLite FTS content is empty (fts_content_non_empty=false)"
                )
    else:
        checks["sqlite_row_count"] = None
        checks["sqlite_row_count_matches_chunk_count"] = None
        checks["sqlite_fts_row_count"] = None
        checks["sqlite_fts_row_count_matches_chunk_count"] = None
        checks["fts_content_non_empty"] = None
        checks["fts_empty_row_count"] = None
        if sqlite_checks_required:
            errors.append("sqlite_index expected but file is missing")

    # ── range_ref_resolution_ok ─────────────────────────────────────────────
    if chunk_index_required:
        rr_ok, rr_msgs, rr_status, rr_validation = _range_ref_check(
            dump_index_path, chunk_index_path
        )
        checks["range_ref_resolution_ok"] = rr_ok
        checks["range_ref_resolution_status"] = rr_status
        checks["range_ref_resolution"] = {
            "status": rr_status,
            "required": True,
            "reason": rr_msgs[0] if rr_msgs else "range_ref validation completed",
            "validation": rr_validation,
        }
        if rr_ok is False:
            errors.extend(rr_msgs)
        else:
            # ok=None covers: no_range_ref, environment_error, unavailable — all non-blocking
            warnings.extend(rr_msgs)
    else:
        checks["range_ref_resolution_ok"] = None
        checks["range_ref_resolution_status"] = "skipped"
        checks["range_ref_resolution"] = {
            "status": "skipped",
            "required": False,
            "reason": "chunk_index not required; range_ref check not applicable",
            "validation": {
                "mode": "skipped_unavailable",
                "engine": "range_resolver",
                "reason": "check_not_applicable",
            },
        }

    # ── non-blocking optional checks ────────────────────────────────────────
    checks["sample_query_content_hit"] = {
        "status": "skipped",
        "required": False,
        "reason": "stable sample query is introduced in a later work package",
    }

    # agent_reading_pack is a navigation entry-point produced after this health
    # report in the pipeline, so the in-pipeline call leaves the path unset
    # (status "skipped"). A post-hoc validator that owns the full bundle can pass
    # the path to assert presence. Non-blocking in v1 (warn-only when expected),
    # per output-optimierung Arbeitspaket C/D.
    if agent_reading_pack_path is not None:
        if agent_reading_pack_path.is_file():
            checks["agent_pack_present"] = {
                "status": "pass",
                "required": bool(agent_reading_pack_expected),
                "reason": f"agent_reading_pack present: {agent_reading_pack_path.name}",
            }
        elif agent_reading_pack_path.exists():
            # Path exists but is not a regular file (e.g. a directory): never pass.
            _status = "fail" if agent_reading_pack_expected else "warning"
            checks["agent_pack_present"] = {
                "status": _status,
                "required": bool(agent_reading_pack_expected),
                "reason": f"agent_reading_pack path is not a regular file: {agent_reading_pack_path.name}",
            }
            if agent_reading_pack_expected:
                warnings.append(
                    f"agent_reading_pack path is not a regular file: {agent_reading_pack_path.name}"
                )
        elif agent_reading_pack_expected:
            checks["agent_pack_present"] = {
                "status": "warning",
                "required": True,
                "reason": "agent_reading_pack expected but file is missing",
            }
            warnings.append("agent_reading_pack expected but file is missing")
        else:
            checks["agent_pack_present"] = {
                "status": "skipped",
                "required": False,
                "reason": "agent_reading_pack absent (not expected)",
            }
    else:
        checks["agent_pack_present"] = {
            "status": "skipped",
            "required": False,
            "reason": "agent_reading_pack path not provided to health check",
        }

    checks["redaction_status_explicit"] = True
    checks["redact_secrets_enabled"] = bool(redact_secrets)

    noise_count = 0
    noise_samples: List[str] = []
    noise_patterns: List[str] = []
    noise_truncated = False
    diagnostic_available = isinstance(excluded_noise, dict)
    if diagnostic_available:
        noise_count = int(excluded_noise.get("count", 0) or 0)
        noise_samples = [
            str(sample)
            for sample in (excluded_noise.get("samples") or [])
            if isinstance(sample, str)
        ][:20]
        noise_patterns = [
            str(pattern)
            for pattern in (excluded_noise.get("patterns") or [])
            if isinstance(pattern, str)
        ]
        noise_truncated = bool(excluded_noise.get("count_truncated"))
    checks["excluded_noise"] = {
        "count": noise_count,
        "samples": noise_samples,
        "patterns": noise_patterns,
        "count_truncated": noise_truncated,
    }
    checks["noise_hygiene"] = {
        "available": diagnostic_available,
        "excluded_noise_count": noise_count,
        "excluded_noise_samples": noise_samples,
        "patterns": noise_patterns,
    }

    # ── diagnostic_artifacts ────────────────────────────────────────────────
    diagnostic_artifacts: Dict[str, Any] = {}
    if retrieval_eval_path and retrieval_eval_path.exists():
        actual_sha = _sha256_file(retrieval_eval_path)
        ok = True
        if retrieval_eval_sha256 and actual_sha != retrieval_eval_sha256:
            ok = False
            warnings.append("retrieval_eval_json hash mismatch (not blocking)")
        diagnostic_artifacts["retrieval_eval_json"] = {
            "path": retrieval_eval_path.name,
            "hash_ok": ok,
            "sha256": actual_sha,
        }

    # ── verdict ─────────────────────────────────────────────────────────────
    if errors:
        verdict = "fail"
    elif warnings:
        verdict = "warn"
    else:
        verdict = "pass"

    # Format created_at timestamp
    ts = now_utc()
    if isinstance(ts, str):
        created_at = ts if ts.endswith("Z") else ts + "Z"
    else:
        # Fallback if now_utc returns a datetime object
        created_at = ts.strftime("%Y-%m-%dT%H:%M:%SZ")

    return {
        "kind": "lenskit.output_health",
        "version": "1.0",
        "run_id": run_id,
        "created_at": created_at,
        "stem": stem,
        "checks": checks,
        "diagnostic_artifacts": diagnostic_artifacts,
        "warnings": warnings,
        "errors": errors,
        "dependencies": jsonschema_dependency(
            available=_JSONSCHEMA_AVAILABLE,
            required_for=["range_ref_schema"],
        ),
        "verdict": verdict,
    }


def write_output_health(
    output_path: Path,
    **kwargs: Any,
) -> Path:
    """
    Compute and write the output health report to output_path.
    output_path must be the full destination file path, for example *.output_health.json;
    it is written exactly as provided.
    
    Note: Pass primary_manifest_path (dump_index), NOT the final bundle manifest.
    This prevents self-referential circularity during health computation.

    Returns the path to the written file.
    """
    health = compute_output_health(**kwargs)
    output_path.write_text(json.dumps(health, indent=2), encoding="utf-8")
    logger.debug("Output health written to %s (verdict=%s)", output_path, health["verdict"])
    return output_path
