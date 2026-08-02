"""Public normalization entry point for decoded SCIP index mappings."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from merger.repoground.core._scip_adapter_common import (
    AUTHORITY,
    CANONICALITY,
    DOES_NOT_ESTABLISH,
    KIND,
    VERSION,
    _commit,
    _degradation,
    _field,
    _normalized_path,
    _sha256,
    _source_metadata,
)
from merger.repoground.core._scip_adapter_records import (
    _collect_occurrences,
    _collect_relationships,
    _ordered_degradations,
    _ordered_records,
    _record_external_symbol_degradation,
)


def _sanitize_source_scalars(
    source: dict[str, Any], degradations: list[dict[str, Any]]
) -> None:
    for field in ("protocol_version", "text_document_encoding"):
        value = source.get(field)
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (str, int)):
            degradations.append(
                _degradation(
                    f"{field}_invalid",
                    f"SCIP {field} is not a string, integer, or null",
                )
            )
            source[field] = None


def _reject_boolean_position_encodings(
    raw_documents: list[Any], degradations: list[dict[str, Any]]
) -> list[Any]:
    accepted: list[Any] = []
    for raw_document in raw_documents:
        if not isinstance(raw_document, Mapping):
            accepted.append(raw_document)
            continue
        position_encoding = _field(
            raw_document, "positionEncoding", "position_encoding"
        )
        if not isinstance(position_encoding, bool):
            accepted.append(raw_document)
            continue
        path = _normalized_path(
            _field(raw_document, "relativePath", "relative_path")
        )
        degradations.append(
            _degradation(
                "position_encoding_unsupported",
                "SCIP document position encoding must not be boolean",
                document=path,
            )
        )
    return accepted


def normalize_scip_index(
    index: Mapping[str, Any],
    *,
    index_sha256: str,
    repository_commit: str,
) -> dict[str, Any]:
    """Normalize decoded SCIP JSON into an optional navigation artifact."""
    if not isinstance(index, Mapping):
        raise TypeError("index must be a mapping")
    degradations: list[dict[str, Any]] = []
    source = _source_metadata(
        index,
        index_sha256=_sha256(index_sha256, field="index_sha256"),
        repository_commit=_commit(repository_commit),
        degradations=degradations,
    )
    _sanitize_source_scalars(source, degradations)
    raw_documents = index.get("documents")
    if not isinstance(raw_documents, list):
        degradations.append(
            _degradation("documents_missing", "SCIP documents is not a list")
        )
        raw_documents = []
    raw_documents = _reject_boolean_position_encodings(raw_documents, degradations)
    contexts, records, definitions, languages = _collect_occurrences(
        raw_documents, degradations
    )
    records.extend(_collect_relationships(contexts, definitions, degradations))
    _record_external_symbol_degradation(index, degradations)
    ordered_records = _ordered_records(records)
    ordered_degradations = _ordered_degradations(degradations)
    return {
        "kind": KIND,
        "version": VERSION,
        "authority": AUTHORITY,
        "canonicality": CANONICALITY,
        "status": "degraded" if ordered_degradations else "available",
        "source": source,
        "languages": sorted(languages),
        "records": ordered_records,
        "record_count": len(ordered_records),
        "degradations": ordered_degradations,
        "consumer_enablement": {
            "requires_language_benchmark": True,
            "eligible_for_review": False,
            "default_promoted": False,
        },
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }
