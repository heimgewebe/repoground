"""Deterministic build, test, schema and artifact relation overlay.

The adapter consumes an already collected, digest-bound evidence document. It does
not scan repositories, run builds or tests, validate schemas, materialize artifacts,
or promote derived navigation evidence into repository truth.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from merger.repoground.core.lens_facets import _normalize_path

KIND = "repoground.system_relation_overlay"
VERSION = "1.0"
SOURCE_KIND = "repoground.system_relation_evidence"
SOURCE_VERSION = "1.0"
AUTHORITY = "navigation_index"
CANONICALITY = "derived"
RISK_CLASS = "navigation"

ENDPOINT_KINDS = frozenset(
    {
        "repository",
        "package",
        "build_target",
        "package_target",
        "test",
        "test_target",
        "validator",
        "schema_contract",
        "artifact_producer",
        "artifact_consumer",
        "artifact_contract",
        "workflow",
    }
)

EVIDENCE_PROFILES = {
    "manifest_declaration": ("S1", "declared"),
    "workflow_declaration": ("S1", "declared"),
    "explicit_test_registration": ("S1", "declared"),
    "test_import_or_reference": ("S0", "referenced"),
    "test_naming_heuristic": ("S0", "heuristic"),
    "schema_validation_call": ("S1", "declared"),
    "artifact_declaration": ("S1", "declared"),
}

SOURCE_KINDS_BY_EVIDENCE = {
    "manifest_declaration": frozenset({"manifest"}),
    "workflow_declaration": frozenset({"workflow"}),
    "explicit_test_registration": frozenset(
        {"manifest", "workflow", "test_registry"}
    ),
    "test_import_or_reference": frozenset({"source_file"}),
    "test_naming_heuristic": frozenset({"source_file"}),
    "schema_validation_call": frozenset({"source_file"}),
    "artifact_declaration": frozenset(
        {"manifest", "workflow", "source_file", "artifact_contract"}
    ),
}

RELATION_RULES = {
    "build_target": {
        "evidence": frozenset({"manifest_declaration", "workflow_declaration"}),
        "contract_kind": None,
    },
    "package_target": {
        "evidence": frozenset({"manifest_declaration", "workflow_declaration"}),
        "contract_kind": None,
    },
    "test_registration": {
        "evidence": frozenset(
            {
                "explicit_test_registration",
                "test_import_or_reference",
                "test_naming_heuristic",
            }
        ),
        "contract_kind": None,
    },
    "validates_schema": {
        "evidence": frozenset({"schema_validation_call"}),
        "contract_kind": "schema",
    },
    "produces_artifact": {
        "evidence": frozenset({"artifact_declaration"}),
        "contract_kind": "artifact",
    },
    "consumes_artifact": {
        "evidence": frozenset({"artifact_declaration"}),
        "contract_kind": "artifact",
    },
}

DOES_NOT_ESTABLISH = (
    "repository_truth",
    "build_execution",
    "build_success",
    "package_publishability",
    "test_execution",
    "test_collection",
    "test_sufficiency",
    "schema_validation_success",
    "schema_conformance",
    "artifact_materialization",
    "artifact_freshness",
    "runtime_behavior",
    "runtime_correctness",
    "relation_completeness",
    "default_promotion",
)

ABSENCE_SEMANTICS = (
    "A missing record means only that this evidence document did not establish "
    "the relation. It is not evidence that the relation is absent."
)


class SystemRelationOverlayError(ValueError):
    """Raised when relation evidence cannot be normalized safely."""


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _text(value: Any, *, label: str, maximum: int = 4096) -> str:
    if not isinstance(value, str):
        raise SystemRelationOverlayError(f"{label} must be a string")
    cleaned = value.strip()
    if not cleaned or len(cleaned) > maximum or "\x00" in cleaned:
        raise SystemRelationOverlayError(f"{label} must be non-empty and bounded")
    return cleaned


def _sha256(value: Any, *, label: str) -> str:
    cleaned = _text(value, label=label, maximum=64)
    if len(cleaned) != 64 or any(character not in "0123456789abcdef" for character in cleaned):
        raise SystemRelationOverlayError(
            f"{label} must be a lowercase SHA-256 digest"
        )
    return cleaned


def _commit(value: Any) -> str:
    cleaned = _text(value, label="repository_commit", maximum=64)
    if len(cleaned) not in {40, 64} or any(
        character not in "0123456789abcdef" for character in cleaned
    ):
        raise SystemRelationOverlayError(
            "repository_commit must be a lowercase 40- or 64-character digest"
        )
    return cleaned


def _exact_mapping(value: Any, *, label: str, keys: set[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SystemRelationOverlayError(f"{label} must be an object")
    observed = set(value)
    if observed != keys:
        raise SystemRelationOverlayError(
            f"{label} fields must be exactly {sorted(keys)!r}; observed {sorted(observed)!r}"
        )
    return value


def _path(value: Any) -> str:
    try:
        return _normalize_path(value)
    except (TypeError, ValueError) as exc:
        raise SystemRelationOverlayError(
            f"source.path is not a safe repository-relative path: {value!r}"
        ) from exc


def _integer(value: Any, *, label: str, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise SystemRelationOverlayError(f"{label} must be an integer >= {minimum}")
    return value


def _source_range(value: Any) -> dict[str, int]:
    mapping = _exact_mapping(
        value,
        label="source.range",
        keys={"start_line", "start_character", "end_line", "end_character"},
    )
    normalized = {
        "start_line": _integer(mapping["start_line"], label="start_line", minimum=1),
        "start_character": _integer(
            mapping["start_character"], label="start_character", minimum=0
        ),
        "end_line": _integer(mapping["end_line"], label="end_line", minimum=1),
        "end_character": _integer(
            mapping["end_character"], label="end_character", minimum=0
        ),
    }
    if (normalized["end_line"], normalized["end_character"]) < (
        normalized["start_line"],
        normalized["start_character"],
    ):
        raise SystemRelationOverlayError("source.range end precedes its start")
    return normalized


def _endpoint(value: Any, *, label: str) -> dict[str, str]:
    mapping = _exact_mapping(value, label=label, keys={"kind", "identity"})
    kind = _text(mapping["kind"], label=f"{label}.kind", maximum=64)
    if kind not in ENDPOINT_KINDS:
        raise SystemRelationOverlayError(f"unsupported {label}.kind: {kind!r}")
    return {
        "kind": kind,
        "identity": _text(mapping["identity"], label=f"{label}.identity"),
    }


def _contract_identity(value: Any, *, expected_kind: str | None) -> dict[str, str] | None:
    if expected_kind is None:
        if value is not None:
            raise SystemRelationOverlayError(
                "contract_identity must be null for build, package and test relations"
            )
        return None
    mapping = _exact_mapping(
        value,
        label="contract_identity",
        keys={"kind", "id", "version"},
    )
    kind = _text(mapping["kind"], label="contract_identity.kind", maximum=32)
    if kind != expected_kind:
        raise SystemRelationOverlayError(
            f"contract_identity.kind must be {expected_kind!r}"
        )
    return {
        "kind": kind,
        "id": _text(mapping["id"], label="contract_identity.id"),
        "version": _text(
            mapping["version"], label="contract_identity.version", maximum=128
        ),
    }


def _source(value: Any, *, evidence_class: str) -> dict[str, Any]:
    mapping = _exact_mapping(
        value,
        label="source",
        keys={"path", "kind", "range"},
    )
    source_kind = _text(mapping["kind"], label="source.kind", maximum=64)
    allowed = SOURCE_KINDS_BY_EVIDENCE[evidence_class]
    if source_kind not in allowed:
        raise SystemRelationOverlayError(
            f"source.kind {source_kind!r} is incompatible with evidence_class "
            f"{evidence_class!r}; expected one of {sorted(allowed)!r}"
        )
    return {
        "path": _path(mapping["path"]),
        "kind": source_kind,
        "range": _source_range(mapping["range"]),
    }


def _normalize_record(value: Any, *, index: int) -> dict[str, Any]:
    mapping = _exact_mapping(
        value,
        label=f"records[{index}]",
        keys={
            "relation",
            "subject",
            "target",
            "source",
            "evidence_class",
            "contract_identity",
        },
    )
    relation = _text(mapping["relation"], label="relation", maximum=64)
    rule = RELATION_RULES.get(relation)
    if rule is None:
        raise SystemRelationOverlayError(f"unsupported relation: {relation!r}")
    evidence_class = _text(
        mapping["evidence_class"], label="evidence_class", maximum=64
    )
    if evidence_class not in rule["evidence"]:
        raise SystemRelationOverlayError(
            f"evidence_class {evidence_class!r} is incompatible with relation {relation!r}"
        )
    evidence_level, evidence_strength = EVIDENCE_PROFILES[evidence_class]
    record = {
        "relation": relation,
        "subject": _endpoint(mapping["subject"], label="subject"),
        "target": _endpoint(mapping["target"], label="target"),
        "source": _source(mapping["source"], evidence_class=evidence_class),
        "evidence": {
            "class": evidence_class,
            "level": evidence_level,
            "strength": evidence_strength,
        },
        "contract_identity": _contract_identity(
            mapping["contract_identity"], expected_kind=rule["contract_kind"]
        ),
    }
    return {"record_id_sha256": _canonical_sha256(record), **record}


def _record_order(record: Mapping[str, Any]) -> tuple[Any, ...]:
    source_range = record["source"]["range"]
    contract = record["contract_identity"] or {"kind": "", "id": "", "version": ""}
    return (
        record["relation"],
        record["subject"]["kind"],
        record["subject"]["identity"],
        record["target"]["kind"],
        record["target"]["identity"],
        record["source"]["path"],
        source_range["start_line"],
        source_range["start_character"],
        source_range["end_line"],
        source_range["end_character"],
        record["evidence"]["class"],
        contract["kind"],
        contract["id"],
        contract["version"],
        record["record_id_sha256"],
    )


def _producer(value: Any) -> dict[str, str]:
    mapping = _exact_mapping(value, label="producer", keys={"name", "version"})
    return {
        "name": _text(mapping["name"], label="producer.name", maximum=256),
        "version": _text(mapping["version"], label="producer.version", maximum=128),
    }


def normalize_system_relation_evidence(
    evidence: Mapping[str, Any],
    *,
    evidence_sha256: str,
    repository_commit: str,
) -> dict[str, Any]:
    """Normalize typed repository evidence into a derived relation overlay."""
    mapping = _exact_mapping(
        evidence,
        label="evidence",
        keys={"kind", "version", "producer", "records"},
    )
    if mapping["kind"] != SOURCE_KIND:
        raise SystemRelationOverlayError(f"evidence.kind must be {SOURCE_KIND!r}")
    if mapping["version"] != SOURCE_VERSION:
        raise SystemRelationOverlayError(f"evidence.version must be {SOURCE_VERSION!r}")
    records_value = mapping["records"]
    if not isinstance(records_value, list):
        raise SystemRelationOverlayError("evidence.records must be a list")

    unique: dict[str, dict[str, Any]] = {}
    duplicate_count = 0
    for index, raw_record in enumerate(records_value):
        record = _normalize_record(raw_record, index=index)
        record_id = record["record_id_sha256"]
        if record_id in unique:
            duplicate_count += 1
            continue
        unique[record_id] = record

    records = sorted(unique.values(), key=_record_order)
    degradations: list[dict[str, Any]] = []
    if duplicate_count:
        degradations.append(
            {
                "code": "duplicate_records_deduplicated",
                "message": "Exact duplicate relation records were removed deterministically.",
                "count": duplicate_count,
            }
        )
    if not records:
        degradations.append(
            {
                "code": "records_empty",
                "message": "The evidence document established no relation records.",
                "count": 0,
            }
        )

    return {
        "kind": KIND,
        "version": VERSION,
        "authority": AUTHORITY,
        "canonicality": CANONICALITY,
        "risk_class": RISK_CLASS,
        "status": "degraded" if degradations else "available",
        "source": {
            "format": "repoground_system_relation_evidence_v1",
            "evidence_sha256": _sha256(
                evidence_sha256, label="evidence_sha256"
            ),
            "repository_commit": _commit(repository_commit),
            "producer": _producer(mapping["producer"]),
        },
        "relation_kinds": sorted({record["relation"] for record in records}),
        "evidence_classes": sorted(
            {record["evidence"]["class"] for record in records}
        ),
        "records": records,
        "record_count": len(records),
        "degradations": degradations,
        "consumer_enablement": {
            "eligible_for_review": False,
            "default_promoted": False,
        },
        "absence_semantics": ABSENCE_SEMANTICS,
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }


__all__ = [
    "SystemRelationOverlayError",
    "normalize_system_relation_evidence",
]
