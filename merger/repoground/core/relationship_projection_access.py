"""Manifest-bound reads of the existing optional relationship projection."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

try:
    import fastjsonschema
except ImportError:  # Optional fallback for non-locked minimal environments.
    fastjsonschema = None

from merger.repoground.architecture.graph_source_validation import (
    GraphIndexCompilationError,
    validate_document,
)
from merger.repoground.architecture.relationship_projection import NONCLAIMS, _edge, _source
from merger.repoground.core import artifact_source_access
from merger.repoground.core.bounded_artifact_read import (
    LoadedArtifactSource,
    declared_artifact_integrity,
)
from merger.repoground.core.bundle_roles import resolve_unique_artifact
from merger.repoground.core.manifest_snapshot import resolve_manifest_path

ROLE = "relationship_projection_json"
CONTRACT = {"id": "relationship_projection", "version": "v1"}
SCHEMA = "relationship_projection.v1.schema.json"
LoadResult = tuple[
    dict[str, Any] | None,
    dict[str, Any] | None,
    LoadedArtifactSource | None,
    dict[str, Any] | None,
]


def _reject(code: str, message: str) -> None:
    raise GraphIndexCompilationError(code, message, source=ROLE)


def _error_result(
    artifact: dict[str, Any] | None, code: str, message: str,
    *, status: str = "blocked",
) -> LoadResult:
    return None, artifact, None, {
        "status": status, "error_code": f"{ROLE}_{code}", "error": message,
    }


def _require_integrity(record: dict[str, Any], label: str) -> str:
    size, digest, failure = declared_artifact_integrity(record)
    if failure is not None or size is None or digest is None:
        _reject(
            "integrity_unavailable",
            f"{label} requires declared bytes and sha256 ({failure or 'missing pair'})",
        )
    assert digest is not None
    return digest


def _validate_projection_schema(document: Any) -> dict[str, Any]:
    """Validate the same tracked Draft-07 schema with a compiled hot path.

    The locked production runtime has fastjsonschema. Keep legacy jsonschema
    validation as a functional fallback for minimal source-only environments.
    Neither path may apply schema defaults or refresh any artifact.
    """
    if fastjsonschema is None:
        return validate_document(document, SCHEMA, ROLE)
    path = Path(__file__).parent.parent / "contracts" / SCHEMA
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
        validate = fastjsonschema.compile(
            schema, use_default=False, use_formats=False,
        )
    except (OSError, UnicodeError, json.JSONDecodeError,
            fastjsonschema.JsonSchemaDefinitionException) as exc:
        _reject("schema_unavailable", f"{ROLE} schema is unavailable: {exc}")
    try:
        validate(document)
    except fastjsonschema.JsonSchemaValueException as exc:
        _reject("invalid_schema", f"{ROLE} does not satisfy {SCHEMA}: {exc}")
    return document


def _validate_manifest_binding(
    document: dict[str, Any], source: LoadedArtifactSource, manifest_path: Path,
) -> None:
    record, _, failure = resolve_unique_artifact(manifest_path, source.manifest, ROLE)
    if failure is not None or record is None:
        _reject("registration_invalid", failure or "missing registration")
    assert record is not None
    expected = {
        "content_type": "application/json",
        "contract": CONTRACT,
        "interpretation": {"mode": "contract"},
        "authority": "navigation_index",
        "canonicality": "derived",
        "risk_class": "navigation",
    }
    if (
        any(record.get(key) != value for key, value in expected.items())
        or record.get("regenerable") is not True
        or record.get("staleness_sensitive") is not True
    ):
        _reject("manifest_contract_invalid", "relationship role metadata mismatch")
    _require_integrity(record, ROLE)
    dump, _, failure = resolve_unique_artifact(
        manifest_path, source.manifest, "dump_index_json",
    )
    if failure is not None or dump is None:
        _reject("canonical_binding_invalid", "one valid dump_index_json is required")
    assert dump is not None
    digest = _require_integrity(dump, "dump_index_json")
    if document["run_id"] != source.manifest.get("run_id"):
        _reject("run_id_mismatch", "relationship run_id differs from bundle run_id")
    if document["canonical_dump_index_sha256"] != digest:
        _reject("canonical_binding_mismatch", "relationship hash differs from dump index")
    links = source.manifest.get("links")
    if links is not None and not isinstance(links, dict):
        _reject("canonical_binding_invalid", "manifest links must be an object")
    if (
        isinstance(links, dict) and "canonical_dump_index_sha256" in links
        and links["canonical_dump_index_sha256"] != digest
    ):
        _reject("canonical_binding_mismatch", "manifest dump hash is contradictory")


def _validate_semantics(document: dict[str, Any]) -> None:
    relations: Counter[str] = Counter()
    resolutions: Counter[str] = Counter()
    identifiers: set[str] = set()
    for position, edge in enumerate(document["edges"]):
        evidence = edge["source"]
        if edge["resolution_status"] == "resolved" and edge["evidence_level"] != "S1":
            _reject("evidence_promotion_invalid", "resolved navigation requires S1 evidence")
        expected = _edge(
            edge["relation"], edge["src"], edge["dst"],
            _source(evidence["path"], evidence["start_line"], evidence["end_line"]),
            edge["resolution_status"], edge["evidence_level"], edge["origin_artifact"],
            candidates=edge.get("candidate_target_ids"),
        )
        if edge != expected:
            _reject("edge_noncanonical", f"edge {position} has inconsistent source or ID")
        if edge["id"] in identifiers:
            _reject("duplicate_edge_id", f"duplicate edge ID at position {position}")
        if edge["src"].startswith("file:") and edge["src"] != f"file:{evidence['path']}":
            _reject("source_binding_mismatch", f"edge {position} source path differs")
        identifiers.add(edge["id"])
        relations[edge["relation"]] += 1
        resolutions[edge["resolution_status"]] += 1
    coverage = document["coverage"]
    emitted = len(document["edges"])
    if (
        coverage["emitted_edges"] != emitted or coverage["total_edges"] < emitted
        or coverage["truncated"] != (coverage["total_edges"] > emitted)
        or coverage["relation_counts"] != dict(relations)
        or coverage["resolution_counts"] != dict(resolutions)
    ):
        _reject("coverage_mismatch", "coverage does not match emitted edges")
    if not set(NONCLAIMS).issubset(document["does_not_establish"]):
        _reject("nonclaims_incomplete", "required relationship nonclaims are missing")


def load_relationship_projection_source(bundle_manifest: str | Path) -> LoadResult:
    """Validate the registered bytes; never refresh or scan a source checkout."""
    try:
        manifest_path = resolve_manifest_path(bundle_manifest)
        source, artifact, failure, detail = (
            artifact_source_access._read_registered_artifact_source(manifest_path, ROLE)
        )
    except (OSError, RuntimeError, ValueError) as exc:
        return _error_result(None, "source_unavailable", str(exc))
    if failure is not None:
        return _error_result(
            artifact, failure, detail or failure,
            status="unavailable" if failure == "missing" else "blocked",
        )
    assert source is not None
    try:
        document = json.loads(source.raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return _error_result(artifact, "invalid_json", str(exc))
    try:
        document = _validate_projection_schema(document)
        _validate_manifest_binding(document, source, manifest_path)
        _validate_semantics(document)
    except GraphIndexCompilationError as exc:
        return _error_result(artifact, exc.code, str(exc))
    except ValueError as exc:
        return _error_result(artifact, "semantic_invalid", str(exc))
    if not artifact_source_access._artifact_source_is_current(
        source.fingerprint, verify_content=True,
    ):
        return _error_result(artifact, "source_changed", "source changed during validation")
    return document, artifact, source, None


def read_structure_neighborhood(
    bundle_manifest: str | Path, *, target_id: str, max_items: int = 50,
) -> dict[str, Any]:
    """Use the existing bounded neighborhood compiler on one verified bundle."""
    from merger.repoground.core.agent_impact_context import compile_structure_neighborhood

    if not isinstance(target_id, str) or not target_id.strip() or len(target_id) > 4096:
        raise ValueError("target_id must be a bounded non-empty string")
    if isinstance(max_items, bool) or not isinstance(max_items, int) or not 1 <= max_items <= 200:
        raise ValueError("max_items must be between 1 and 200")
    document, artifact, source, error = load_relationship_projection_source(bundle_manifest)
    if error is not None:
        return error
    assert source is not None and document is not None
    result = compile_structure_neighborhood(
        symbol_id=target_id, relationship_projection=document, max_items=max_items,
    )
    if not artifact_source_access._artifact_source_is_current(
        source.fingerprint, verify_content=True,
    ):
        return _error_result(artifact, "source_changed", "source changed during query")[3]
    provenance = source.manifest.get("snapshot_provenance", {})
    repositories = provenance.get("repositories", []) if isinstance(provenance, dict) else []
    commits = sorted({
        row["git_commit"] for row in repositories
        if isinstance(row, dict) and isinstance(row.get("git_commit"), str)
        and re.fullmatch(r"[0-9a-f]{40}", row["git_commit"])
    }) if isinstance(repositories, list) else []
    generator = source.manifest.get("generator", {})
    runtime = generator.get("runtime", {}) if isinstance(generator, dict) else {}
    result["status"] = "available"
    result["bundle_identity"] = {
        "manifest_path": source.fingerprint.manifest_path,
        "manifest_sha256": source.fingerprint.manifest_sha256,
        "run_id": source.manifest.get("run_id"),
        "source_commit": commits[0] if len(commits) == 1 else None,
        "source_commit_binding": "unique" if len(commits) == 1 else "unknown_or_ambiguous",
        "generator_commit": runtime.get("git_commit") if isinstance(runtime, dict) else None,
        "artifact_sha256": source.fingerprint.artifact_sha256,
    }
    result["artifact"] = artifact
    result["implicit_refresh"] = False
    return result
