"""Deterministic, provenance-bound adapter helpers for decoded SCIP indexes."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from merger.repoground.core.lens_facets import _normalize_path

KIND = "repoground.scip_symbol_relations"
VERSION = "1.0"
BENCHMARK_KIND = "repoground.scip_adapter_benchmark"
BENCHMARK_VERSION = "1.0"
AUTHORITY = "navigation_index"
CANONICALITY = "derived"

ROLE_BITS = (
    (0x1, "definition"),
    (0x2, "import"),
    (0x4, "write_access"),
    (0x8, "read_access"),
    (0x10, "generated"),
    (0x20, "test"),
    (0x40, "forward_definition"),
)
KNOWN_ROLE_MASK = sum(bit for bit, _ in ROLE_BITS)
RELATIONSHIP_FLAGS = (
    (("isReference", "is_reference"), "references_symbol"),
    (("isImplementation", "is_implementation"), "implements_symbol"),
    (("isTypeDefinition", "is_type_definition"), "type_definition"),
    (("isDefinition", "is_definition"), "definition_alias"),
)
SUPPORTED_POSITION_ENCODINGS = frozenset(
    {
        "UTF8CodeUnitOffsetFromLineStart",
        "UTF16CodeUnitOffsetFromLineStart",
        "UTF32CodeUnitOffsetFromLineStart",
        1,
        2,
        3,
    }
)
UNSPECIFIED_POSITION_ENCODINGS = frozenset({"UnspecifiedPositionEncoding", 0})
DOES_NOT_ESTABLISH = (
    "repository_truth",
    "index_completeness",
    "symbol_resolution_completeness",
    "runtime_behavior",
    "runtime_reachability",
    "call_graph_completeness",
    "dependency_completeness",
    "test_sufficiency",
    "review_priority",
    "change_impact",
    "consumer_enablement",
    "default_promotion",
)
BENCHMARK_DOES_NOT_ESTABLISH = (
    "repository_truth",
    "indexer_correctness_outside_the_goldset",
    "cross_repository_resolution",
    "runtime_behavior",
    "agent_quality_improvement",
    "consumer_enablement",
    "default_promotion",
)


class ScipAdapterError(ValueError):
    """Raised for unsafe or structurally unusable SCIP input."""


def _field(mapping: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in mapping:
            return mapping[name]
    return None


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned or "\x00" in cleaned:
        return None
    return cleaned


def _sha256(value: Any, *, field: str) -> str:
    cleaned = _text(value)
    if cleaned is None or len(cleaned) != 64 or any(
        character not in "0123456789abcdef" for character in cleaned
    ):
        raise ScipAdapterError(f"{field} must be a lowercase SHA-256 digest")
    return cleaned


def _commit(value: Any) -> str:
    cleaned = _text(value)
    if cleaned is None or len(cleaned) not in {40, 64} or any(
        character not in "0123456789abcdef" for character in cleaned
    ):
        raise ScipAdapterError(
            "repository_commit must be a lowercase 40- or 64-character digest"
        )
    return cleaned


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _degradation(
    code: str,
    message: str,
    *,
    document: str | None = None,
    symbol: str | None = None,
    count: int | None = None,
) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "document": document,
        "symbol": symbol,
        "count": count,
    }


def _sequence(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _normalized_path(value: Any) -> str:
    try:
        return _normalize_path(value)
    except (TypeError, ValueError) as exc:
        raise ScipAdapterError(f"unsafe SCIP document path: {value!r}") from exc


def _normalized_range(value: Any, position_encoding: Any) -> dict[str, Any] | None:
    if not isinstance(value, list) or len(value) not in {3, 4}:
        return None
    if any(
        isinstance(part, bool) or not isinstance(part, int) or part < 0
        for part in value
    ):
        return None
    if len(value) == 3:
        start_line, start_character, end_character = value
        end_line = start_line
    else:
        start_line, start_character, end_line, end_character = value
    if (end_line, end_character) < (start_line, start_character):
        return None
    return {
        "start_line": start_line + 1,
        "start_character": start_character,
        "end_line": end_line + 1,
        "end_character": end_character,
        "position_encoding": position_encoding,
    }


def _role_value(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _roles(value: int) -> tuple[list[str], int]:
    roles = [name for bit, name in ROLE_BITS if value & bit]
    return roles, value & ~KNOWN_ROLE_MASK


def _symbol_key(symbol: str, document: str) -> tuple[str | None, str]:
    return (document if symbol.startswith("local ") else None, symbol)


def _record_identity(record: Mapping[str, Any]) -> tuple[Any, ...]:
    source = record["source"]
    source_range = source["range"]
    return (
        record["language"],
        source["path"],
        source_range["start_line"],
        source_range["start_character"],
        source_range["end_line"],
        source_range["end_character"],
        record["record_type"],
        record["relation"],
        record["symbol"],
        record.get("target_symbol") or "",
        tuple(record["roles"]),
    )


def _validated_arguments(
    value: Any, degradations: list[dict[str, Any]]
) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return value
    degradations.append(
        _degradation(
            "indexer_arguments_invalid",
            "SCIP indexer arguments are not a string list",
        )
    )
    return []


def _source_metadata(
    index: Mapping[str, Any],
    *,
    index_sha256: str,
    repository_commit: str,
    degradations: list[dict[str, Any]],
) -> dict[str, Any]:
    metadata = index.get("metadata")
    if not isinstance(metadata, Mapping):
        degradations.append(
            _degradation("metadata_missing", "SCIP index metadata is missing")
        )
        metadata = {}
    tool_info = _field(metadata, "toolInfo", "tool_info")
    if not isinstance(tool_info, Mapping):
        degradations.append(
            _degradation("indexer_missing", "SCIP tool_info is missing")
        )
        tool_info = {}
    name = _text(tool_info.get("name"))
    version = _text(tool_info.get("version"))
    if name is None:
        degradations.append(
            _degradation("indexer_name_missing", "SCIP indexer name is missing")
        )
    if version is None:
        degradations.append(
            _degradation("indexer_version_missing", "SCIP indexer version is missing")
        )
    arguments_list = _validated_arguments(tool_info.get("arguments"), degradations)
    project_root_text = _text(_field(metadata, "projectRoot", "project_root"))
    if project_root_text is None:
        degradations.append(
            _degradation("project_root_missing", "SCIP project_root is missing")
        )
    protocol_version = metadata.get("version")
    if protocol_version is None:
        degradations.append(
            _degradation("protocol_version_missing", "SCIP protocol version is missing")
        )
    return {
        "format": "decoded_scip_protobuf_json",
        "protocol": "SCIP",
        "protocol_version": protocol_version,
        "index_sha256": index_sha256,
        "repository_commit": repository_commit,
        "indexer": {
            "name": name,
            "version": version,
            "arguments_sha256": _canonical_sha256(arguments_list),
        },
        "project_root_sha256": (
            hashlib.sha256(project_root_text.encode("utf-8")).hexdigest()
            if project_root_text is not None
            else None
        ),
        "text_document_encoding": _field(
            metadata, "textDocumentEncoding", "text_document_encoding"
        ),
    }


def _position_encoding(
    value: Any, *, path: str, degradations: list[dict[str, Any]]
) -> Any | None:
    if value in UNSPECIFIED_POSITION_ENCODINGS:
        degradations.append(
            _degradation(
                "position_encoding_unspecified",
                "SCIP document position encoding is ambiguous",
                document=path,
            )
        )
        return None
    if value in SUPPORTED_POSITION_ENCODINGS:
        return value
    degradations.append(
        _degradation(
            "position_encoding_unsupported",
            "SCIP document position encoding is missing or unsupported",
            document=path,
        )
    )
    return None


def _document_context(
    raw_document: Any,
    degradations: list[dict[str, Any]],
) -> tuple[Mapping[str, Any], str, str, Any] | None:
    if not isinstance(raw_document, Mapping):
        degradations.append(
            _degradation("document_not_object", "SCIP document is not an object")
        )
        return None
    path = _normalized_path(_field(raw_document, "relativePath", "relative_path"))
    language = _text(raw_document.get("language"))
    if language is None:
        degradations.append(
            _degradation(
                "document_language_missing",
                "SCIP document language is missing",
                document=path,
            )
        )
        return None
    position_encoding = _position_encoding(
        _field(raw_document, "positionEncoding", "position_encoding"),
        path=path,
        degradations=degradations,
    )
    if position_encoding is None:
        return None
    return raw_document, path, language.casefold(), position_encoding


def _occurrence_record(
    occurrence: Any,
    *,
    path: str,
    language: str,
    position_encoding: Any,
    degradations: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not isinstance(occurrence, Mapping):
        degradations.append(
            _degradation(
                "occurrence_not_object",
                "SCIP occurrence is not an object",
                document=path,
            )
        )
        return None
    symbol = _text(occurrence.get("symbol"))
    if symbol is None:
        degradations.append(
            _degradation(
                "occurrence_symbol_missing",
                "SCIP occurrence symbol is missing",
                document=path,
            )
        )
        return None
    source_range = _normalized_range(occurrence.get("range"), position_encoding)
    if source_range is None:
        degradations.append(
            _degradation(
                "occurrence_range_invalid",
                "SCIP occurrence range is invalid",
                document=path,
                symbol=symbol,
            )
        )
        return None
    raw_roles = _field(occurrence, "symbolRoles", "symbol_roles")
    role_value = _role_value(0 if raw_roles is None else raw_roles)
    if role_value is None:
        degradations.append(
            _degradation(
                "occurrence_roles_invalid",
                "SCIP occurrence symbolRoles is invalid",
                document=path,
                symbol=symbol,
            )
        )
        return None
    roles, unknown_bits = _roles(role_value)
    if unknown_bits:
        degradations.append(
            _degradation(
                "occurrence_roles_unknown_bits",
                f"SCIP occurrence has unknown role bits: {unknown_bits}",
                document=path,
                symbol=symbol,
            )
        )
    return {
        "record_type": "occurrence",
        "relation": "definition" if "definition" in roles else "reference",
        "language": language,
        "symbol": symbol,
        "target_symbol": None,
        "roles": roles,
        "source": {"path": path, "range": source_range},
        "source_rule": "scip_occurrence_symbol_roles",
    }
