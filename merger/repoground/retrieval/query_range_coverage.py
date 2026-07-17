import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


_RANGE_REF_V1_REQUIRED_KEYS = (
    "artifact_role",
    "repo_id",
    "file_path",
    "start_byte",
    "end_byte",
    "start_line",
    "end_line",
    "content_sha256",
)

_RANGE_REF_V2_REQUIRED_KEYS = (
    "range_ref_version",
    "artifact_role",
    "artifact_path",
    "artifact_byte_start",
    "artifact_byte_end",
    "artifact_line_start",
    "artifact_line_end",
    "source_file_path",
    "source_line_start",
    "source_line_end",
    "content_sha256",
    "range_content_sha256",
)

_DOES_NOT_ESTABLISH = [
    "truth",
    "answer_correctness",
    "retrieval_completeness",
    "repository_understanding",
    "runtime_behavior",
    "test_sufficiency",
    "regression_absence",
    "that every query result is citation-ready",
]


def _is_int_not_bool(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _range_ref_error(ref: Any) -> Optional[str]:
    if not isinstance(ref, dict):
        return "range ref is not an object"
    if ref.get("range_ref_version") == "2":
        return _range_ref_v2_error(ref)
    return _range_ref_v1_error(ref)


def _range_ref_v1_error(ref: Dict[str, Any]) -> Optional[str]:
    missing = [key for key in _RANGE_REF_V1_REQUIRED_KEYS if key not in ref]
    if missing:
        return "range ref missing required keys: " + ", ".join(missing)

    for key in ("artifact_role", "repo_id", "file_path", "content_sha256"):
        if not isinstance(ref.get(key), str) or not ref.get(key):
            return f"range ref field {key!r} must be a non-empty string"

    return _validate_range_numbers(
        ref,
        start_byte_key="start_byte",
        end_byte_key="end_byte",
        start_line_key="start_line",
        end_line_key="end_line",
    )


def _range_ref_v2_error(ref: Dict[str, Any]) -> Optional[str]:
    missing = [key for key in _RANGE_REF_V2_REQUIRED_KEYS if key not in ref]
    if missing:
        return "range ref v2 missing required keys: " + ", ".join(missing)

    for key in (
        "range_ref_version",
        "artifact_role",
        "artifact_path",
        "source_file_path",
        "content_sha256",
        "range_content_sha256",
    ):
        if not isinstance(ref.get(key), str) or not ref.get(key):
            return f"range ref v2 field {key!r} must be a non-empty string"

    return _validate_range_numbers(
        ref,
        start_byte_key="artifact_byte_start",
        end_byte_key="artifact_byte_end",
        start_line_key="artifact_line_start",
        end_line_key="artifact_line_end",
    ) or _validate_range_numbers(
        ref,
        start_byte_key="source_line_start",
        end_byte_key="source_line_end",
        start_line_key="source_line_start",
        end_line_key="source_line_end",
        line_only=True,
    )


def _validate_range_numbers(
    ref: Dict[str, Any],
    *,
    start_byte_key: str,
    end_byte_key: str,
    start_line_key: str,
    end_line_key: str,
    line_only: bool = False,
) -> Optional[str]:
    for key in (start_line_key, end_line_key):
        if not _is_int_not_bool(ref.get(key)):
            return f"range ref field {key!r} must be an integer"
    if ref[start_line_key] < 1:
        return f"range ref {start_line_key} must be >= 1"
    if ref[end_line_key] < ref[start_line_key]:
        return f"range ref {end_line_key} must be >= {start_line_key}"

    if line_only:
        return None

    for key in (start_byte_key, end_byte_key):
        if not _is_int_not_bool(ref.get(key)):
            return f"range ref field {key!r} must be an integer"
    if ref[start_byte_key] < 0:
        return f"range ref {start_byte_key} must be >= 0"
    if ref[end_byte_key] <= ref[start_byte_key]:
        return f"range ref {end_byte_key} must be > {start_byte_key}"
    return None


def _canonical_range_key(ref: Dict[str, Any]) -> Tuple[str, int, int, str]:
    if ref.get("range_ref_version") == "2":
        return (
            str(ref.get("artifact_path") or ref.get("file_path") or ""),
            int(ref.get("artifact_byte_start", ref.get("start_byte", -1))),
            int(ref.get("artifact_byte_end", ref.get("end_byte", -1))),
            str(ref.get("range_content_sha256") or ref.get("content_sha256") or ""),
        )
    return (
        str(ref.get("file_path", "")),
        int(ref.get("start_byte", -1)),
        int(ref.get("end_byte", -1)),
        str(ref.get("content_sha256", "")),
    )


def _classify_hit(hit: Dict[str, Any]) -> Tuple[str, Optional[str], Optional[str]]:
    explicit_ref = hit.get("range_ref")
    if explicit_ref is not None:
        error = _range_ref_error(explicit_ref)
        if error:
            return "malformed", "range_ref", error
        if explicit_ref.get("artifact_role") == "canonical_md":
            return "canonical_explicit", "range_ref", None
        return "explicit_noncanonical", "range_ref", None

    derived_ref = hit.get("derived_range_ref")
    if derived_ref is not None:
        error = _range_ref_error(derived_ref)
        if error:
            return "malformed", "derived_range_ref", error
        if derived_ref.get("artifact_role") != "source_file":
            return (
                "malformed",
                "derived_range_ref",
                "derived range ref must use artifact_role='source_file'",
            )
        return "derived_source", "derived_range_ref", None

    return "unresolved", None, None


def _load_citation_rows(
    citation_map_jsonl: Path,
) -> Tuple[Dict[str, List[Dict[str, Any]]], Dict[Tuple[str, int, int, str], List[Dict[str, Any]]], List[str]]:
    by_chunk: Dict[str, List[Dict[str, Any]]] = {}
    by_range: Dict[Tuple[str, int, int, str], List[Dict[str, Any]]] = {}
    warnings: List[str] = []

    if not citation_map_jsonl.exists():
        warnings.append(f"citation_map_jsonl not found: {citation_map_jsonl}")
        return by_chunk, by_range, warnings

    for lineno, raw_line in enumerate(
        citation_map_jsonl.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            warnings.append(f"line {lineno}: invalid JSON: {exc.msg}")
            continue

        citation_id = row.get("citation_id")
        if not isinstance(citation_id, str) or not citation_id:
            warnings.append(f"line {lineno}: missing citation_id")
            continue

        chunk_id = row.get("chunk_id")
        if isinstance(chunk_id, str) and chunk_id:
            by_chunk.setdefault(chunk_id, []).append(row)

        canonical_range = row.get("canonical_range")
        if isinstance(canonical_range, dict):
            key = _canonical_range_key(canonical_range)
            if key[1] >= 0 and key[2] > key[1] and key[3]:
                by_range.setdefault(key, []).append(row)
            else:
                warnings.append(f"line {lineno}: malformed canonical_range")

    return by_chunk, by_range, warnings


def _merge_candidate(
    candidates: Dict[str, Dict[str, Any]], row: Dict[str, Any], reason: str
) -> None:
    citation_id = row.get("citation_id")
    if not isinstance(citation_id, str) or not citation_id:
        return

    current = candidates.setdefault(
        citation_id,
        {
            "citation_id": citation_id,
            "match_reasons": [],
        },
    )
    if reason not in current["match_reasons"]:
        current["match_reasons"].append(reason)


def _citation_candidates_for_hit(
    hit: Dict[str, Any],
    by_chunk: Dict[str, List[Dict[str, Any]]],
    by_range: Dict[Tuple[str, int, int, str], List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    candidates: Dict[str, Dict[str, Any]] = {}

    chunk_id = hit.get("chunk_id")
    if isinstance(chunk_id, str):
        for row in by_chunk.get(chunk_id, []):
            _merge_candidate(candidates, row, "chunk_id")

    explicit_ref = hit.get("range_ref")
    if (
        isinstance(explicit_ref, dict)
        and explicit_ref.get("artifact_role") == "canonical_md"
        and _range_ref_error(explicit_ref) is None
    ):
        for row in by_range.get(_canonical_range_key(explicit_ref), []):
            _merge_candidate(candidates, row, "canonical_range")

    return sorted(candidates.values(), key=lambda item: item["citation_id"])


def build_query_range_coverage_report(
    query_result: Dict[str, Any],
    *,
    citation_map_jsonl: Optional[Path] = None,
) -> Dict[str, Any]:
    """Build a diagnostic coverage report for per-hit query range evidence.

    The report is deliberately narrower than an answer-quality or retrieval-quality
    verdict. It only classifies the range-reference surface already present on query
    hits and optionally proposes citation-id candidates from a citation map.
    """
    hits = query_result.get("results", [])
    if not isinstance(hits, list):
        hits = []

    by_chunk: Dict[str, List[Dict[str, Any]]] = {}
    by_range: Dict[Tuple[str, int, int, str], List[Dict[str, Any]]] = {}
    warnings: List[str] = []
    citation_map_status = "not_provided"

    if citation_map_jsonl is not None:
        by_chunk, by_range, warnings = _load_citation_rows(citation_map_jsonl)
        citation_map_status = "loaded" if not warnings else "loaded_with_warnings"
        if warnings and not by_chunk and not by_range:
            citation_map_status = "unusable"

    counts = {
        "hits_with_explicit_range_ref": 0,
        "hits_with_explicit_canonical_md_range_ref": 0,
        "hits_with_derived_range_ref": 0,
        "unresolved_hits": 0,
        "malformed_hits": 0,
        "citation_id_candidate_hits": 0,
    }
    status_counts: Dict[str, int] = {}
    per_hit: List[Dict[str, Any]] = []

    for idx, raw_hit in enumerate(hits):
        hit = raw_hit if isinstance(raw_hit, dict) else {}
        status, ref_kind, error = _classify_hit(hit)
        status_counts[status] = status_counts.get(status, 0) + 1

        if status in {"canonical_explicit", "explicit_noncanonical"}:
            counts["hits_with_explicit_range_ref"] += 1
        if status == "canonical_explicit":
            counts["hits_with_explicit_canonical_md_range_ref"] += 1
        if status == "derived_source":
            counts["hits_with_derived_range_ref"] += 1
        if status == "unresolved":
            counts["unresolved_hits"] += 1
        if status == "malformed":
            counts["malformed_hits"] += 1

        candidates = _citation_candidates_for_hit(hit, by_chunk, by_range)
        if candidates:
            counts["citation_id_candidate_hits"] += 1

        item = {
            "hit_index": idx,
            "chunk_id": hit.get("chunk_id"),
            "path": hit.get("path"),
            "range": hit.get("range"),
            "status": status,
            "range_ref_kind": ref_kind,
        }
        if error:
            item["error"] = error
        if candidates:
            item["citation_id_candidates"] = candidates
        per_hit.append(item)

    total_hits = len(hits)

    def ratio(value: int) -> float:
        return round(value / total_hits, 6) if total_hits else 0.0

    report = {
        "kind": "lenskit.query_range_coverage_report",
        "version": "1.0",
        "total_hits": total_hits,
        "counts": counts,
        "status_counts": status_counts,
        "coverage": {
            "explicit_range_ref_ratio": ratio(counts["hits_with_explicit_range_ref"]),
            "explicit_canonical_md_ratio": ratio(
                counts["hits_with_explicit_canonical_md_range_ref"]
            ),
            "derived_range_ref_ratio": ratio(counts["hits_with_derived_range_ref"]),
            "unresolved_ratio": ratio(counts["unresolved_hits"]),
            "malformed_ratio": ratio(counts["malformed_hits"]),
            "citation_id_candidate_ratio": ratio(
                counts["citation_id_candidate_hits"]
            ),
        },
        "per_hit": per_hit,
        "citation_map": {
            "status": citation_map_status,
            "path": str(citation_map_jsonl) if citation_map_jsonl is not None else None,
            "warnings": warnings,
        },
        "diagnostic_semantics": {
            "authority": "query_result_surface",
            "canonical_preference": "explicit canonical_md range_ref",
            "derived_range_ref_policy": "fallback context, not canonical citation",
            "does_not_establish": list(_DOES_NOT_ESTABLISH),
        },
    }
    return report
