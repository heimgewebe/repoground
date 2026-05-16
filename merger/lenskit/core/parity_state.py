"""Build canonical parity gate state from real bundle manifests.

This module translates two real output bundles (or explicit bundle-manifest
paths) into the flat state mapping consumed by
``merger.lenskit.core.parity_gates.evaluate_parity_gates``.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any, Mapping

from merger.lenskit.core.path_security import resolve_secure_path

try:
    import jsonschema
except ImportError:  # pragma: no cover
    jsonschema = None


class ParityInputError(ValueError):
    """Raised when parity input paths or required artifacts are invalid."""


@dataclass(frozen=True)
class ParityStateBuild:
    state: dict[str, object]
    compared_artifacts: list[str]
    left_stem: str
    right_stem: str


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise ParityInputError(f"missing file: {path}") from e
    except json.JSONDecodeError as e:
        raise ParityInputError(f"invalid json in {path}: {e}") from e
    except OSError as e:
        raise ParityInputError(f"cannot read {path}: {e}") from e

    if not isinstance(data, dict):
        raise ParityInputError(f"expected JSON object in {path}")
    return data


def _normalize_relative_path(raw: str, label: str) -> str:
    if not isinstance(raw, str):
        raise ParityInputError(f"{label}: path must be a string")
    if raw.startswith("/"):
        raise ParityInputError(f"{label}: absolute paths are forbidden")
    if raw.startswith("\\"):
        raise ParityInputError(f"{label}: rooted Windows/UNC paths are forbidden")
    if PureWindowsPath(raw).drive:
        raise ParityInputError(f"{label}: Windows drive paths are forbidden")
    parts = raw.replace("\\", "/").split("/")
    if ".." in parts:
        raise ParityInputError(f"{label}: path traversal ('..') is forbidden")
    normalized = [p for p in parts if p not in ("", ".")]
    if not normalized:
        raise ParityInputError(f"{label}: path must not be empty")
    return "/".join(normalized)


def _resolve_manifest_artifact_path(manifest_path: Path, role: str, rel_raw: Any) -> Path:
    rel = _normalize_relative_path(rel_raw, f"{role}.path")
    try:
        return resolve_secure_path(manifest_path.parent, rel)
    except ValueError as e:
        raise ParityInputError(f"{role}.path rejected: {e}") from e


def _resolve_manifest_path(path_like: str | Path) -> Path:
    p = Path(path_like)
    if p.is_dir():
        candidates = sorted(p.glob("*.bundle.manifest.json"))
        if len(candidates) != 1:
            raise ParityInputError(
                f"expected exactly one *.bundle.manifest.json in {p}, found {len(candidates)}"
            )
        return candidates[0]
    if not p.exists():
        raise ParityInputError(f"manifest path does not exist: {p}")
    return p


def _artifact_map(manifest: Mapping[str, Any], manifest_path: Path) -> dict[str, dict[str, Any]]:
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        raise ParityInputError(f"manifest artifacts must be a list: {manifest_path}")

    out: dict[str, dict[str, Any]] = {}
    for entry in artifacts:
        if not isinstance(entry, dict):
            continue
        role = entry.get("role")
        if isinstance(role, str):
            if role in out:
                raise ParityInputError(
                    f"duplicate artifact role in manifest {manifest_path}: {role}"
                )
            out[role] = entry
    return out


def _artifact_path(manifest_path: Path, artifacts: Mapping[str, dict[str, Any]], role: str) -> Path | None:
    entry = artifacts.get(role)
    if not entry:
        return None
    rel = entry.get("path")
    if not isinstance(rel, str) or not rel.strip():
        raise ParityInputError(f"{role}.path is missing or invalid")
    return _resolve_manifest_artifact_path(manifest_path, role, rel)


def _verify_manifest_hash_bytes(
    manifest_path: Path,
    manifest: Mapping[str, Any],
    artifacts: Mapping[str, dict[str, Any]],
) -> bool:
    entries = manifest.get("artifacts")
    if not isinstance(entries, list):
        return False

    for entry in entries:
        if not isinstance(entry, dict):
            return False
        rel = entry.get("path")
        sha = entry.get("sha256")
        expected_bytes = entry.get("bytes")
        role = entry.get("role")
        if not isinstance(rel, str) or not isinstance(sha, str) or not isinstance(expected_bytes, int):
            return False
        role_label = role if isinstance(role, str) else "artifact"
        p = _resolve_manifest_artifact_path(manifest_path, role_label, rel)
        if not p.exists() or not p.is_file():
            return False
        if p.stat().st_size != expected_bytes:
            return False
        if _sha256_file(p) != sha:
            return False

    links = manifest.get("links")
    if isinstance(links, dict):
        expected_dump_sha = links.get("canonical_dump_index_sha256")
        if isinstance(expected_dump_sha, str):
            dump_path = _artifact_path(manifest_path, artifacts, "dump_index_json")
            if not dump_path or not dump_path.exists():
                return False
            if _sha256_file(dump_path) != expected_dump_sha:
                return False

    return True


def _read_sidecar(manifest_path: Path, artifacts: Mapping[str, dict[str, Any]]) -> dict[str, Any] | None:
    p = _artifact_path(manifest_path, artifacts, "index_sidecar_json")
    if p is None:
        return None
    data = _read_json(p)
    return data


def _source_paths_and_hashes(sidecar: Mapping[str, Any] | None) -> tuple[set[str] | None, dict[str, str] | None]:
    if not sidecar:
        return None, None
    files = sidecar.get("files")
    if not isinstance(files, list):
        return None, None

    paths: set[str] = set()
    hashes: dict[str, str] = {}
    for item in files:
        if not isinstance(item, dict):
            continue
        if item.get("included") is not True:
            continue
        path = item.get("path")
        if not isinstance(path, str):
            continue
        paths.add(path)
        sha = item.get("sha256")
        if isinstance(sha, str):
            hashes[path] = sha
    return paths, hashes


def _source_coverage_tuple(sidecar: Mapping[str, Any] | None) -> tuple[int, int] | None:
    if not sidecar:
        return None
    coverage = sidecar.get("coverage")
    if not isinstance(coverage, dict):
        return None
    included = coverage.get("included_text_files")
    total = coverage.get("total_text_files")
    if not isinstance(included, int) or not isinstance(total, int):
        return None
    return included, total


def _read_health(manifest_path: Path, artifacts: Mapping[str, dict[str, Any]]) -> dict[str, Any] | None:
    p = _artifact_path(manifest_path, artifacts, "output_health")
    if p is None:
        return None
    return _read_json(p)


def _health_check_bool(health: Mapping[str, Any] | None, key: str) -> bool:
    if not health:
        return False
    checks = health.get("checks")
    if not isinstance(checks, dict):
        return False
    return checks.get(key) is True


def _fts_signature(sqlite_path: Path) -> tuple[int, str]:
    h = hashlib.sha256()
    with sqlite3.connect(str(sqlite_path)) as conn:
        cur = conn.execute("SELECT chunk_id, content FROM chunks_fts ORDER BY chunk_id")
        count = 0
        for chunk_id, content in cur.fetchall():
            left = "" if chunk_id is None else str(chunk_id)
            right = "" if content is None else str(content)
            h.update(left.encode("utf-8"))
            h.update(b"\x00")
            h.update(right.encode("utf-8"))
            h.update(b"\n")
            count += 1
    return count, h.hexdigest()


def _jsonl_valid(path: Path) -> bool:
    try:
        with path.open("r", encoding="utf-8") as f:
            has_line = False
            for raw in f:
                line = raw.strip()
                if not line:
                    continue
                has_line = True
                obj = json.loads(line)
                if not isinstance(obj, dict):
                    return False
            return has_line
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False


def _validate_citation_map(
    manifest_path: Path,
    manifest_json: Mapping[str, Any],
    artifacts: Mapping[str, dict[str, Any]],
) -> bool:
    from merger.lenskit.core.citation_validate import validate_bundle

    citation_path = _artifact_path(manifest_path, artifacts, "citation_map_jsonl")
    if citation_path is None or not citation_path.exists():
        return False

    # Reuse existing canonical citation validator for bundle consistency first.
    bundle_report = validate_bundle(str(manifest_path))
    if bundle_report.get("status") != "ok":
        return False

    if jsonschema is None:
        return False

    schema_path = Path(__file__).parent.parent / "contracts" / "citation-map.v1.schema.json"
    schema = _read_json(schema_path)

    canonical_artifact = artifacts.get("canonical_md")
    if not isinstance(canonical_artifact, dict):
        return False
    canonical_rel_raw = canonical_artifact.get("path")
    canonical_sha = canonical_artifact.get("sha256")
    if not isinstance(canonical_rel_raw, str) or not isinstance(canonical_sha, str):
        return False
    canonical_rel = _normalize_relative_path(canonical_rel_raw, "canonical_md.path")

    seen_ids: set[str] = set()
    try:
        with citation_path.open("r", encoding="utf-8") as f:
            has_row = False
            for raw in f:
                line = raw.strip()
                if not line:
                    continue
                has_row = True
                row = json.loads(line)
                if not isinstance(row, dict):
                    return False
                jsonschema.validate(instance=row, schema=schema)

                citation_id = row.get("citation_id")
                if not isinstance(citation_id, str):
                    return False
                if citation_id in seen_ids:
                    return False
                seen_ids.add(citation_id)

                snapshot = row.get("snapshot")
                canonical_range = row.get("canonical_range")
                if not isinstance(snapshot, dict) or not isinstance(canonical_range, dict):
                    return False

                if snapshot.get("canonical_md_path") != canonical_rel:
                    return False
                if snapshot.get("canonical_md_sha256") != canonical_sha:
                    return False
                if canonical_range.get("file_path") != canonical_rel:
                    return False

            return has_row
    except (OSError, UnicodeError, json.JSONDecodeError, jsonschema.ValidationError):
        return False


def _stem(manifest_path: Path, health: Mapping[str, Any] | None) -> str:
    if health:
        stem = health.get("stem")
        if isinstance(stem, str) and stem.strip():
            return stem
    name = manifest_path.name
    return name.replace(".bundle.manifest.json", "")


def build_parity_state(left_manifest: str | Path, right_manifest: str | Path) -> ParityStateBuild:
    """Build parity-gate state from two real bundle manifests."""
    left_manifest_path = _resolve_manifest_path(left_manifest)
    right_manifest_path = _resolve_manifest_path(right_manifest)

    left_manifest_json = _read_json(left_manifest_path)
    right_manifest_json = _read_json(right_manifest_path)

    left_artifacts = _artifact_map(left_manifest_json, left_manifest_path)
    right_artifacts = _artifact_map(right_manifest_json, right_manifest_path)

    left_sidecar = _read_sidecar(left_manifest_path, left_artifacts)
    right_sidecar = _read_sidecar(right_manifest_path, right_artifacts)
    left_health = _read_health(left_manifest_path, left_artifacts)
    right_health = _read_health(right_manifest_path, right_artifacts)

    left_paths, left_hashes = _source_paths_and_hashes(left_sidecar)
    right_paths, right_hashes = _source_paths_and_hashes(right_sidecar)

    source_paths_equal = (
        left_paths is not None and right_paths is not None and left_paths == right_paths
    )

    source_sha256_equal = False
    if source_paths_equal and left_paths is not None and left_hashes is not None and right_hashes is not None:
        source_sha256_equal = all(
            path in left_hashes and path in right_hashes and left_hashes[path] == right_hashes[path]
            for path in left_paths
        )

    source_chunk_coverage_equal = False
    left_cov = _source_coverage_tuple(left_sidecar)
    right_cov = _source_coverage_tuple(right_sidecar)
    if left_cov is not None and right_cov is not None:
        source_chunk_coverage_equal = left_cov == right_cov

    left_sqlite = _artifact_path(left_manifest_path, left_artifacts, "sqlite_index")
    right_sqlite = _artifact_path(right_manifest_path, right_artifacts, "sqlite_index")
    if left_sqlite and right_sqlite and left_sqlite.exists() and right_sqlite.exists():
        try:
            left_sig = _fts_signature(left_sqlite)
            right_sig = _fts_signature(right_sqlite)
            fts_logically_equal = left_sig == right_sig
        except sqlite3.Error:
            fts_logically_equal = False
    elif (left_sqlite is None or not left_sqlite.exists()) and (right_sqlite is None or not right_sqlite.exists()):
        fts_logically_equal = True
    else:
        fts_logically_equal = False

    output_health_verdict_pass = (
        bool(left_health)
        and bool(right_health)
        and left_health.get("verdict") == "pass"
        and right_health.get("verdict") == "pass"
    )
    range_ref_resolution_ok = (
        _health_check_bool(left_health, "range_ref_resolution_ok")
        and _health_check_bool(right_health, "range_ref_resolution_ok")
    )

    no_health_errors = (
        bool(left_health)
        and bool(right_health)
        and isinstance(left_health.get("errors"), list)
        and isinstance(right_health.get("errors"), list)
        and len(left_health.get("errors", [])) == 0
        and len(right_health.get("errors", [])) == 0
    )
    no_health_warnings = (
        bool(left_health)
        and bool(right_health)
        and isinstance(left_health.get("warnings"), list)
        and isinstance(right_health.get("warnings"), list)
        and len(left_health.get("warnings", [])) == 0
        and len(right_health.get("warnings", [])) == 0
    )

    manifest_hash_bytes_consistent = (
        _verify_manifest_hash_bytes(left_manifest_path, left_manifest_json, left_artifacts)
        and _verify_manifest_hash_bytes(right_manifest_path, right_manifest_json, right_artifacts)
    )

    left_retrieval_manifested = "retrieval_eval_json" in left_artifacts
    right_retrieval_manifested = "retrieval_eval_json" in right_artifacts
    retrieval_eval_json_expected = left_retrieval_manifested or right_retrieval_manifested
    retrieval_eval_json_manifested = left_retrieval_manifested and right_retrieval_manifested

    left_citation_manifested = "citation_map_jsonl" in left_artifacts
    right_citation_manifested = "citation_map_jsonl" in right_artifacts
    citation_map_jsonl_expected = left_citation_manifested or right_citation_manifested

    citation_map_jsonl_valid = False
    if left_citation_manifested and right_citation_manifested:
        citation_map_jsonl_valid = (
            _validate_citation_map(left_manifest_path, left_manifest_json, left_artifacts)
            and _validate_citation_map(right_manifest_path, right_manifest_json, right_artifacts)
        )

    left_sqlite_required = _health_check_bool(left_health, "sqlite_checks_required")
    right_sqlite_required = _health_check_bool(right_health, "sqlite_checks_required")
    fts_non_empty_expected = left_sqlite_required or right_sqlite_required
    fts_non_empty = (
        _health_check_bool(left_health, "fts_content_non_empty")
        and _health_check_bool(right_health, "fts_content_non_empty")
    )

    state: dict[str, object] = {
        "source_paths_equal": source_paths_equal,
        "source_sha256_equal": source_sha256_equal,
        "source_chunk_coverage_equal": source_chunk_coverage_equal,
        "fts_logically_equal": fts_logically_equal,
        "output_health_verdict_pass": output_health_verdict_pass,
        "range_ref_resolution_ok": range_ref_resolution_ok,
        "no_health_errors": no_health_errors,
        "no_health_warnings": no_health_warnings,
        "manifest_hash_bytes_consistent": manifest_hash_bytes_consistent,
        "retrieval_eval_json_expected": retrieval_eval_json_expected,
        "retrieval_eval_json_manifested": retrieval_eval_json_manifested,
        "citation_map_jsonl_expected": citation_map_jsonl_expected,
        "citation_map_jsonl_valid": citation_map_jsonl_valid,
        "fts_non_empty_expected": fts_non_empty_expected,
        "fts_non_empty": fts_non_empty,
    }

    compared_artifacts = sorted(set(left_artifacts.keys()) & set(right_artifacts.keys()))
    return ParityStateBuild(
        state=state,
        compared_artifacts=compared_artifacts,
        left_stem=_stem(left_manifest_path, left_health),
        right_stem=_stem(right_manifest_path, right_health),
    )
