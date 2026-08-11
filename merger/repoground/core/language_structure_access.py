"""Integrity-bound read access for optional Rust/Bash structure evidence."""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Mapping

from merger.repoground.core.bounded_artifact_read import (
    declared_artifact_integrity,
    read_stable_regular_file_bytes,
)
from merger.repoground.core.manifest_snapshot import resolve_manifest_path

ROLE = "language_structure_json"
CONTRACT = {"id": "language-structure", "version": "v1"}
MAX_MANIFEST_BYTES = 8 * 1024 * 1024
MAX_LANGUAGE_STRUCTURE_BYTES = 64 * 1024 * 1024
_COMMIT_RE = re.compile(r"^[a-f0-9]{40}(?:[a-f0-9]{24})?$")
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_RECORD_ID_RE = re.compile(r"^[a-f0-9]{24}$")
_ADAPTERS = {
    ("bash", "bash-static-structure", "1.0", "S0"),
    ("rust", "rust-static-structure", "1.0", "S0"),
    ("rust", "rust-scip-structure", "1.0", "S1"),
}
_STATIC_RELATIONS = frozenset({"definition", "call", "dependency"})
_SCIP_RELATIONS = frozenset(
    {
        "definition",
        "reference",
        "references_symbol",
        "implements_symbol",
        "type_definition",
        "definition_alias",
    }
)
_DOES_NOT_ESTABLISH = frozenset(
    {
        "repository_truth",
        "complete_symbol_index",
        "complete_call_graph",
        "complete_dependency_graph",
        "runtime_behavior",
        "dynamic_dispatch_resolution",
        "macro_expansion",
        "generated_code_coverage",
        "python_ast_equivalence",
        "test_sufficiency",
        "default_promotion",
    }
)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _result(
    status: str,
    *,
    manifest_path: Path,
    reason: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": status,
        "role": ROLE,
        "bundle_manifest": str(manifest_path),
    }
    if reason is not None:
        result["reason"] = reason
    result.update(extra)
    return result


def _stable_bytes(path: Path, *, max_bytes: int) -> tuple[bytes | None, str | None]:
    raw, _identity, failure, detail = read_stable_regular_file_bytes(
        path, max_bytes=max_bytes
    )
    if failure is not None:
        return None, f"{failure}: {detail}" if detail else failure
    return raw, None


def _manifest_document(raw: bytes) -> dict[str, Any] | None:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _safe_artifact_path(
    manifest_path: Path, artifact: Mapping[str, Any]
) -> Path | None:
    raw = artifact.get("path")
    if (
        not isinstance(raw, str)
        or not raw
        or Path(raw).is_absolute()
        or Path(raw).name != raw
    ):
        return None
    return manifest_path.parent / raw


def _metadata_valid(artifact: Mapping[str, Any]) -> bool:
    return (
        artifact.get("role") == ROLE
        and artifact.get("content_type") == "application/json"
        and artifact.get("contract") == CONTRACT
        and artifact.get("interpretation") == {"mode": "contract"}
        and artifact.get("authority") == "navigation_index"
        and artifact.get("canonicality") == "derived"
        and artifact.get("risk_class") == "navigation"
        and artifact.get("regenerable") is True
        and artifact.get("staleness_sensitive") is True
    )


def _expected_repository_commit(manifest: Mapping[str, Any]) -> str | None:
    provenance = manifest.get("snapshot_provenance")
    repositories = (
        provenance.get("repositories") if isinstance(provenance, Mapping) else None
    )
    if not isinstance(repositories, list) or len(repositories) != 1:
        return None
    row = repositories[0]
    commit = row.get("git_commit") if isinstance(row, Mapping) else None
    return commit if isinstance(commit, str) and commit else None


def _safe_source_path(value: Any) -> bool:
    if (
        not isinstance(value, str)
        or not value
        or "\\" in value
        or "//" in value
        or re.match(r"^[A-Za-z]:", value) is not None
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        return False
    path = Path(value)
    return (
        not path.is_absolute()
        and path.as_posix() == value
        and all(part not in {"", ".", ".."} for part in path.parts)
    )


def _record_semantics_valid(record: Mapping[str, Any], *, scip: bool) -> bool:
    relation = record.get("relation")
    record_type = record.get("record_type")
    target_symbol = record.get("target_symbol")
    if scip:
        return (
            record_type in {"occurrence", "relationship"}
            and relation in _SCIP_RELATIONS
            and (
                target_symbol is None
                or (isinstance(target_symbol, str) and bool(target_symbol))
            )
        )
    if relation not in _STATIC_RELATIONS:
        return False
    if relation == "definition":
        return record_type == "symbol" and target_symbol is None
    return (
        record_type == "relation"
        and isinstance(target_symbol, str)
        and bool(target_symbol)
    )


def _expected_record_id(record: Mapping[str, Any]) -> str | None:
    source = record.get("source")
    adapter = record.get("adapter")
    provenance = record.get("provenance")
    if not all(isinstance(item, Mapping) for item in (source, adapter, provenance)):
        return None
    identity = {
        "language": record.get("language"),
        "adapter_id": adapter.get("id"),
        "adapter_version": adapter.get("version"),
        "record_type": record.get("record_type"),
        "relation": record.get("relation"),
        "symbol": record.get("symbol"),
        "target_symbol": record.get("target_symbol"),
        "source_path": source.get("path"),
        "source_range": source.get("range"),
        "repository_commit": provenance.get("repository_commit"),
    }
    encoded = json.dumps(
        identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:24]


def _valid_range(value: Any, *, scip: bool) -> bool:
    if not isinstance(value, Mapping):
        return False
    start_line = value.get("start_line")
    end_line = value.get("end_line")
    start_character = value.get("start_character")
    end_character = value.get("end_character")
    return (
        isinstance(start_line, int)
        and not isinstance(start_line, bool)
        and start_line >= 1
        and isinstance(end_line, int)
        and not isinstance(end_line, bool)
        and end_line >= start_line
        and isinstance(start_character, int)
        and not isinstance(start_character, bool)
        and start_character >= 0
        and isinstance(end_character, int)
        and not isinstance(end_character, bool)
        and (end_line > start_line or end_character > start_character)
        and (
            (
                scip
                and value.get("coordinate_basis") == "scip_position_encoding_units"
                and isinstance(value.get("position_encoding"), (str, int))
                and not isinstance(value.get("position_encoding"), bool)
            )
            or (
                not scip
                and value.get("coordinate_basis")
                == "source_lines_1_based_unicode_characters"
            )
        )
    )


def _valid_record(
    record: Any,
    *,
    repository_commit: str,
    bundle_manifest: str,
    dump_sha256: str,
) -> bool:
    if not isinstance(record, Mapping):
        return False
    adapter = record.get("adapter")
    evidence = record.get("evidence")
    provenance = record.get("provenance")
    source = record.get("source")
    if not all(
        isinstance(item, Mapping) for item in (adapter, evidence, provenance, source)
    ):
        return False
    adapter_key = (
        record.get("language"),
        adapter.get("id"),
        adapter.get("version"),
        evidence.get("level"),
    )
    confidence = evidence.get("confidence")
    uncertainty = record.get("uncertainty")
    source_artifact = provenance.get("source_artifact")
    scip_source_valid = (
        isinstance(source_artifact, Mapping)
        and source_artifact.get("kind") == "scip_symbol_relations"
        and isinstance(source_artifact.get("sha256"), str)
        and _SHA256_RE.fullmatch(source_artifact["sha256"]) is not None
    )
    scip = adapter.get("id") == "rust-scip-structure"
    return (
        isinstance(record.get("id"), str)
        and _RECORD_ID_RE.fullmatch(record["id"]) is not None
        and record.get("id") == _expected_record_id(record)
        and adapter_key in _ADAPTERS
        and _record_semantics_valid(record, scip=scip)
        and isinstance(record.get("symbol"), str)
        and bool(record.get("symbol"))
        and _safe_source_path(source.get("path"))
        and _valid_range(source.get("range"), scip=scip)
        and isinstance(confidence, (int, float))
        and not isinstance(confidence, bool)
        and math.isfinite(float(confidence))
        and 0.0 <= float(confidence) <= 1.0
        and isinstance(evidence.get("basis"), str)
        and bool(evidence.get("basis"))
        and provenance.get("repository_commit") == repository_commit
        and provenance.get("bundle_manifest") == bundle_manifest
        and provenance.get("bundle_manifest_sha256") is None
        and provenance.get("canonical_dump_index_sha256") == dump_sha256
        and (scip_source_valid if scip else source_artifact is None)
        and isinstance(uncertainty, list)
        and all(isinstance(item, str) and item for item in uncertainty)
        and uncertainty == sorted(set(uncertainty))
    )


def _valid_degradation(item: Any) -> bool:
    if not isinstance(item, Mapping):
        return False
    language = item.get("language")
    reason = item.get("reason")
    path = item.get("path")
    line = item.get("line")
    return (
        language in {"bash", "rust", "mixed"}
        and isinstance(reason, str)
        and bool(reason)
        and (path is None or _safe_source_path(path))
        and (
            line is None
            or (isinstance(line, int) and not isinstance(line, bool) and line >= 1)
        )
    )


def _valid_summary(
    language: str,
    summary: Any,
    *,
    records: list[Any],
) -> bool:
    if not isinstance(summary, Mapping):
        return False
    adapter = summary.get("adapter")
    expected_adapter = {
        "bash": {"id": "bash-static-structure", "version": "1.0"},
        "rust": {"id": "rust-static-structure", "version": "1.0"},
    }[language]
    expected_records = [
        record
        for record in records
        if isinstance(record, Mapping) and record.get("language") == language
    ]
    counts = {
        field: summary.get(field)
        for field in ("candidate_file_count", "scanned_file_count", "record_count")
    }
    if (
        summary.get("status") not in {"available", "degraded"}
        or adapter != expected_adapter
        or any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0
            for value in counts.values()
        )
        or int(counts["scanned_file_count"]) > int(counts["candidate_file_count"])
        or counts["record_count"] != len(expected_records)
        or not all(
            isinstance(summary.get(field), list)
            and all(isinstance(item, str) and item for item in summary[field])
            for field in (
                "supported_files",
                "supported_symbols",
                "supported_relations",
                "explicit_limits",
            )
        )
        or not isinstance(summary.get("range_basis"), str)
        or not summary.get("range_basis")
    ):
        return False
    if language == "bash":
        return "scip_adapter" not in summary and "scip_record_count" not in summary
    scip_count = summary.get("scip_record_count")
    return (
        summary.get("scip_adapter") == {"id": "rust-scip-structure", "version": "1.0"}
        and isinstance(scip_count, int)
        and not isinstance(scip_count, bool)
        and scip_count >= 0
        and scip_count
        == sum(
            1
            for record in expected_records
            if isinstance(record.get("adapter"), Mapping)
            and record["adapter"].get("id") == "rust-scip-structure"
        )
    )


def _document_valid(
    document: Mapping[str, Any],
    *,
    run_id: Any,
    repository_commit: str,
    bundle_manifest: str,
    dump_sha256: str,
) -> bool:
    source = document.get("source")
    languages = document.get("languages")
    records = document.get("records")
    degradations = document.get("degradations")
    promotion = document.get("promotion")
    does_not_establish = document.get("does_not_establish")
    if not (
        document.get("kind") == "repoground.language_structure"
        and document.get("version") == "1.0"
        and document.get("authority") == "navigation_index"
        and document.get("canonicality") == "derived"
        and document.get("risk_class") == "navigation"
        and document.get("run_id") == run_id
        and document.get("status") in {"available", "degraded"}
        and isinstance(source, Mapping)
        and isinstance(source.get("repository_root_name"), str)
        and bool(source.get("repository_root_name"))
        and source.get("repository_commit") == repository_commit
        and source.get("bundle_manifest") == bundle_manifest
        and source.get("canonical_dump_index_sha256") == dump_sha256
        and source.get("network_used") is False
        and source.get("secrets_read") is False
        and source.get("workspace_state_used_beyond_bound_source") is False
        and isinstance(languages, Mapping)
        and set(languages) == {"bash", "rust"}
        and isinstance(records, list)
        and document.get("record_count") == len(records)
        and isinstance(degradations, list)
        and all(_valid_degradation(item) for item in degradations)
        and isinstance(promotion, Mapping)
        and promotion.get("default_promoted") is False
        and promotion.get("status") == "keep_optional"
        and isinstance(promotion.get("reason"), str)
        and bool(promotion.get("reason"))
        and isinstance(does_not_establish, list)
        and all(isinstance(item, str) for item in does_not_establish)
        and set(does_not_establish) == _DOES_NOT_ESTABLISH
    ):
        return False
    if not all(
        _valid_summary(language, languages.get(language), records=records)
        for language in ("bash", "rust")
    ):
        return False
    expected_status = (
        "degraded"
        if degradations
        or any(
            languages[language].get("status") == "degraded" for language in languages
        )
        else "available"
    )
    if document.get("status") != expected_status:
        return False
    if not all(
        _valid_record(
            record,
            repository_commit=repository_commit,
            bundle_manifest=bundle_manifest,
            dump_sha256=dump_sha256,
        )
        for record in records
    ):
        return False
    ids = [record.get("id") for record in records]
    return len(ids) == len(set(ids))


def _load_manifest_snapshot(
    manifest_path: Path,
) -> tuple[bytes | None, str | None, dict[str, Any] | None, str | None]:
    raw, error = _stable_bytes(manifest_path, max_bytes=MAX_MANIFEST_BYTES)
    if raw is None:
        return None, None, None, error or "manifest_unreadable"
    digest = _sha256(raw)
    document = _manifest_document(raw)
    if document is None:
        return raw, digest, None, "manifest_invalid_json"
    return raw, digest, document, None


def _registered_artifact(
    manifest: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    artifacts = [
        item
        for item in manifest.get("artifacts", [])
        if isinstance(item, Mapping) and item.get("role") == ROLE
    ]
    if not artifacts:
        return None, "language_structure_not_registered"
    if len(artifacts) != 1:
        return None, "language_structure_role_ambiguous"
    artifact = dict(artifacts[0])
    if not _metadata_valid(artifact):
        return artifact, "language_structure_manifest_contract_invalid"
    return artifact, None


def _load_artifact_bytes(
    manifest_path: Path, artifact: Mapping[str, Any]
) -> tuple[bytes | None, int | None, str | None, str | None]:
    declared_bytes, declared_sha, integrity_error = declared_artifact_integrity(
        artifact, max_bytes=MAX_LANGUAGE_STRUCTURE_BYTES
    )
    if integrity_error is not None or declared_bytes is None or declared_sha is None:
        reason = f"language_structure_{integrity_error or 'integrity_unavailable'}"
        return None, declared_bytes, declared_sha, reason
    artifact_path = _safe_artifact_path(manifest_path, artifact)
    if artifact_path is None:
        return None, declared_bytes, declared_sha, "language_structure_path_invalid"
    raw, artifact_error = _stable_bytes(
        artifact_path, max_bytes=MAX_LANGUAGE_STRUCTURE_BYTES
    )
    if raw is None:
        return (
            None,
            declared_bytes,
            declared_sha,
            artifact_error or "language_structure_unreadable",
        )
    if len(raw) != declared_bytes or _sha256(raw) != declared_sha:
        return (
            None,
            declared_bytes,
            declared_sha,
            "language_structure_integrity_mismatch",
        )
    return raw, declared_bytes, declared_sha, None


def load_language_structure_artifact(
    bundle_manifest: str | Path,
) -> dict[str, Any]:
    """Read one language sidecar only when manifest, bytes and identities agree."""
    manifest_path = resolve_manifest_path(bundle_manifest)
    manifest_raw, manifest_sha256, manifest, manifest_error = _load_manifest_snapshot(
        manifest_path
    )
    if manifest_error is not None or manifest_raw is None or manifest_sha256 is None:
        return _result(
            "blocked",
            manifest_path=manifest_path,
            reason=manifest_error or "manifest_unreadable",
        )
    if manifest is None:
        return _result(
            "blocked",
            manifest_path=manifest_path,
            reason="manifest_invalid_json",
            manifest_sha256=manifest_sha256,
        )
    artifact, artifact_error = _registered_artifact(manifest)
    if artifact is None:
        return _result(
            "missing"
            if artifact_error == "language_structure_not_registered"
            else "blocked",
            manifest_path=manifest_path,
            reason=artifact_error,
            manifest_sha256=manifest_sha256,
        )
    if artifact_error is not None:
        return _result(
            "blocked",
            manifest_path=manifest_path,
            reason=artifact_error,
            manifest_sha256=manifest_sha256,
            artifact=artifact,
        )
    raw, declared_bytes, declared_sha, artifact_error = _load_artifact_bytes(
        manifest_path, artifact
    )
    if artifact_error is not None or raw is None:
        return _result(
            "blocked",
            manifest_path=manifest_path,
            reason=artifact_error or "language_structure_unreadable",
            manifest_sha256=manifest_sha256,
            artifact=artifact,
        )
    manifest_after, manifest_after_error = _stable_bytes(
        manifest_path, max_bytes=MAX_MANIFEST_BYTES
    )
    if (
        manifest_after is None
        or manifest_after_error is not None
        or _sha256(manifest_after) != manifest_sha256
    ):
        return _result(
            "blocked",
            manifest_path=manifest_path,
            reason="bundle_manifest_changed_during_language_structure_read",
            manifest_sha256=manifest_sha256,
            artifact=artifact,
        )
    document = _manifest_document(raw)
    if document is None:
        return _result(
            "blocked",
            manifest_path=manifest_path,
            reason="language_structure_invalid_json",
            manifest_sha256=manifest_sha256,
            artifact=artifact,
        )
    links = manifest.get("links")
    expected_dump = (
        links.get("canonical_dump_index_sha256") if isinstance(links, Mapping) else None
    )
    expected_commit = _expected_repository_commit(manifest)
    identity_ok = (
        isinstance(expected_dump, str)
        and _SHA256_RE.fullmatch(expected_dump) is not None
        and isinstance(expected_commit, str)
        and _COMMIT_RE.fullmatch(expected_commit) is not None
        and _document_valid(
            document,
            run_id=manifest.get("run_id"),
            repository_commit=expected_commit,
            bundle_manifest=manifest_path.name,
            dump_sha256=expected_dump,
        )
    )
    if not identity_ok:
        return _result(
            "blocked",
            manifest_path=manifest_path,
            reason="language_structure_bundle_identity_mismatch",
            manifest_sha256=manifest_sha256,
            artifact=artifact,
        )
    return _result(
        "available",
        manifest_path=manifest_path,
        manifest_sha256=manifest_sha256,
        artifact=artifact,
        content_json=document,
        content_sha256=declared_sha,
        content_bytes=declared_bytes,
    )


__all__ = [
    "CONTRACT",
    "MAX_LANGUAGE_STRUCTURE_BYTES",
    "ROLE",
    "load_language_structure_artifact",
]
