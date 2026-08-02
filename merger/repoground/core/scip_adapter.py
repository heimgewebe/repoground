"""Deterministic, provenance-bound adapter for decoded SCIP indexes.

The adapter consumes an already decoded SCIP Protobuf JSON mapping. It does not
run an indexer, decode protobuf bytes, read repository files, resolve symbols, or
promote external index data into repository truth. The output is an optional
navigation artifact with explicit degradation and consumer-promotion boundaries.
"""
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
POSITION_ENCODINGS = frozenset(
    {
        "UnspecifiedPositionEncoding",
        "UTF8CodeUnitOffsetFromLineStart",
        "UTF16CodeUnitOffsetFromLineStart",
        "UTF32CodeUnitOffsetFromLineStart",
        0,
        1,
        2,
        3,
    }
)
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
    if isinstance(value, list):
        return value
    return []


def _normalized_path(value: Any) -> str:
    try:
        return _normalize_path(value)
    except (TypeError, ValueError) as exc:
        raise ScipAdapterError(f"unsafe SCIP document path: {value!r}") from exc


def _normalized_range(value: Any, position_encoding: Any) -> dict[str, Any] | None:
    if not isinstance(value, list) or len(value) not in {3, 4}:
        return None
    if any(isinstance(part, bool) or not isinstance(part, int) or part < 0 for part in value):
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


def _record_sort_key(record: Mapping[str, Any]) -> tuple[Any, ...]:
    return _record_identity(record)


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
    arguments = tool_info.get("arguments")
    if arguments is None:
        arguments_list: list[str] = []
    elif isinstance(arguments, list) and all(isinstance(item, str) for item in arguments):
        arguments_list = arguments
    else:
        degradations.append(
            _degradation(
                "indexer_arguments_invalid",
                "SCIP indexer arguments are not a string list",
            )
        )
        arguments_list = []
    project_root = _field(metadata, "projectRoot", "project_root")
    project_root_text = _text(project_root)
    if project_root_text is None:
        degradations.append(
            _degradation("project_root_missing", "SCIP project_root is missing")
        )
    protocol_version = metadata.get("version")
    if protocol_version is None:
        degradations.append(
            _degradation("protocol_version_missing", "SCIP protocol version is missing")
        )
    text_encoding = _field(metadata, "textDocumentEncoding", "text_document_encoding")
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
        "text_document_encoding": text_encoding,
    }


def _document_context(
    raw_document: Any,
    degradations: list[dict[str, Any]],
) -> tuple[Mapping[str, Any], str, str, Any] | None:
    if not isinstance(raw_document, Mapping):
        degradations.append(
            _degradation("document_not_object", "SCIP document is not an object")
        )
        return None
    raw_path = _field(raw_document, "relativePath", "relative_path")
    path = _normalized_path(raw_path)
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
    language = language.casefold()
    position_encoding = _field(raw_document, "positionEncoding", "position_encoding")
    if position_encoding not in POSITION_ENCODINGS:
        degradations.append(
            _degradation(
                "position_encoding_unsupported",
                "SCIP document position encoding is missing or unsupported",
                document=path,
            )
        )
        return None
    return raw_document, path, language, position_encoding


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
    raw_role_value = _field(occurrence, "symbolRoles", "symbol_roles")
    role_value = _role_value(0 if raw_role_value is None else raw_role_value)
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


def _relationship_flag(
    relationship: Mapping[str, Any], aliases: Sequence[str]
) -> bool | None:
    value = _field(relationship, *aliases)
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    return None


def _relationship_records(
    raw_symbol: Any,
    *,
    path: str,
    language: str,
    definitions: Mapping[tuple[str | None, str], list[dict[str, Any]]],
    degradations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not isinstance(raw_symbol, Mapping):
        degradations.append(
            _degradation(
                "symbol_information_not_object",
                "SCIP SymbolInformation is not an object",
                document=path,
            )
        )
        return []
    source_symbol = _text(raw_symbol.get("symbol"))
    if source_symbol is None:
        degradations.append(
            _degradation(
                "symbol_information_symbol_missing",
                "SCIP SymbolInformation symbol is missing",
                document=path,
            )
        )
        return []
    relationships = raw_symbol.get("relationships")
    if relationships is None:
        return []
    if not isinstance(relationships, list):
        degradations.append(
            _degradation(
                "relationships_invalid",
                "SCIP relationships is not a list",
                document=path,
                symbol=source_symbol,
            )
        )
        return []
    source_definitions = definitions.get(_symbol_key(source_symbol, path), [])
    if len(source_definitions) != 1:
        code = (
            "relationship_source_definition_missing"
            if not source_definitions
            else "relationship_source_definition_ambiguous"
        )
        degradations.append(
            _degradation(
                code,
                "SCIP relationship source does not have one exact definition occurrence",
                document=path,
                symbol=source_symbol,
                count=len(source_definitions),
            )
        )
        return []
    source = source_definitions[0]["source"]
    records: list[dict[str, Any]] = []
    for relationship in relationships:
        if not isinstance(relationship, Mapping):
            degradations.append(
                _degradation(
                    "relationship_not_object",
                    "SCIP relationship is not an object",
                    document=path,
                    symbol=source_symbol,
                )
            )
            continue
        target_symbol = _text(relationship.get("symbol"))
        if target_symbol is None:
            degradations.append(
                _degradation(
                    "relationship_target_missing",
                    "SCIP relationship target symbol is missing",
                    document=path,
                    symbol=source_symbol,
                )
            )
            continue
        emitted = False
        invalid_flag = False
        for aliases, relation in RELATIONSHIP_FLAGS:
            enabled = _relationship_flag(relationship, aliases)
            if enabled is None:
                invalid_flag = True
                continue
            if not enabled:
                continue
            emitted = True
            records.append(
                {
                    "record_type": "relationship",
                    "relation": relation,
                    "language": language,
                    "symbol": source_symbol,
                    "target_symbol": target_symbol,
                    "roles": [],
                    "source": source,
                    "source_rule": "scip_symbol_information_relationship",
                }
            )
        if invalid_flag:
            degradations.append(
                _degradation(
                    "relationship_flag_invalid",
                    "SCIP relationship flag is not boolean",
                    document=path,
                    symbol=source_symbol,
                )
            )
        if not emitted:
            degradations.append(
                _degradation(
                    "relationship_unsupported",
                    "SCIP relationship has no supported true flag",
                    document=path,
                    symbol=source_symbol,
                )
            )
    return records


def normalize_scip_index(
    index: Mapping[str, Any],
    *,
    index_sha256: str,
    repository_commit: str,
) -> dict[str, Any]:
    """Normalize decoded SCIP JSON into an optional navigation artifact."""
    if not isinstance(index, Mapping):
        raise TypeError("index must be a mapping")
    digest = _sha256(index_sha256, field="index_sha256")
    commit = _commit(repository_commit)
    degradations: list[dict[str, Any]] = []
    source = _source_metadata(
        index,
        index_sha256=digest,
        repository_commit=commit,
        degradations=degradations,
    )
    raw_documents = index.get("documents")
    if not isinstance(raw_documents, list):
        degradations.append(
            _degradation("documents_missing", "SCIP documents is not a list")
        )
        raw_documents = []

    document_contexts: list[tuple[Mapping[str, Any], str, str, Any]] = []
    records: list[dict[str, Any]] = []
    definitions: dict[tuple[str | None, str], list[dict[str, Any]]] = {}
    languages: set[str] = set()

    for raw_document in raw_documents:
        context = _document_context(raw_document, degradations)
        if context is None:
            continue
        document, path, language, position_encoding = context
        document_contexts.append(context)
        languages.add(language)
        raw_occurrences = document.get("occurrences")
        if raw_occurrences is None:
            raw_occurrences = []
        if not isinstance(raw_occurrences, list):
            degradations.append(
                _degradation(
                    "occurrences_invalid",
                    "SCIP occurrences is not a list",
                    document=path,
                )
            )
            continue
        for occurrence in raw_occurrences:
            record = _occurrence_record(
                occurrence,
                path=path,
                language=language,
                position_encoding=position_encoding,
                degradations=degradations,
            )
            if record is None:
                continue
            records.append(record)
            if record["relation"] == "definition":
                definitions.setdefault(
                    _symbol_key(record["symbol"], path), []
                ).append(record)

    for document, path, language, _ in document_contexts:
        raw_symbols = document.get("symbols")
        if raw_symbols is None:
            raw_symbols = []
        if not isinstance(raw_symbols, list):
            degradations.append(
                _degradation(
                    "symbol_information_invalid",
                    "SCIP symbols is not a list",
                    document=path,
                )
            )
            continue
        for raw_symbol in raw_symbols:
            records.extend(
                _relationship_records(
                    raw_symbol,
                    path=path,
                    language=language,
                    definitions=definitions,
                    degradations=degradations,
                )
            )

    external_symbols = index.get("externalSymbols")
    if external_symbols is None:
        external_symbols = index.get("external_symbols")
    if isinstance(external_symbols, list) and external_symbols:
        degradations.append(
            _degradation(
                "external_symbols_not_projected",
                "external symbols lack repository-range evidence and are not projected",
                count=len(external_symbols),
            )
        )
    elif external_symbols is not None and not isinstance(external_symbols, list):
        degradations.append(
            _degradation(
                "external_symbols_invalid",
                "SCIP external_symbols is not a list",
            )
        )

    unique_records: dict[tuple[Any, ...], dict[str, Any]] = {}
    for record in records:
        unique_records.setdefault(_record_identity(record), record)
    ordered_records = sorted(unique_records.values(), key=_record_sort_key)
    ordered_degradations = sorted(
        degradations,
        key=lambda item: (
            item["code"],
            item.get("document") or "",
            item.get("symbol") or "",
            item["message"],
        ),
    )
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


def benchmark_identity(record: Mapping[str, Any]) -> dict[str, Any]:
    """Return the stable, goldset-facing identity of one adapter record."""
    source = record["source"]
    source_range = source["range"]
    return {
        "record_type": record["record_type"],
        "relation": record["relation"],
        "symbol": record["symbol"],
        "target_symbol": record.get("target_symbol"),
        "path": source["path"],
        "start_line": source_range["start_line"],
    }


def _metric(numerator: int, denominator: int) -> float:
    return 1.0 if denominator == 0 else numerator / denominator


def _identity_key(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _threshold(value: Any, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be numeric")
    result = float(value)
    if result < 0.0 or result > 1.0:
        raise ValueError(f"{field} must be between 0 and 1")
    return result


def evaluate_scip_adapter(
    artifact: Mapping[str, Any],
    expected_by_language: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    minimum_precision: float = 0.97,
    minimum_recall: float = 0.95,
) -> dict[str, Any]:
    """Evaluate fixed per-language navigation identities without promoting them."""
    if artifact.get("kind") != KIND or artifact.get("version") != VERSION:
        raise ValueError("artifact is not a SCIP symbol-relations v1 artifact")
    if not isinstance(expected_by_language, Mapping):
        raise TypeError("expected_by_language must be a mapping")
    precision_threshold = _threshold(
        minimum_precision, field="minimum_precision"
    )
    recall_threshold = _threshold(minimum_recall, field="minimum_recall")
    actual_by_language: dict[str, set[str]] = {}
    for record in _sequence(artifact.get("records")):
        if not isinstance(record, Mapping):
            raise ValueError("artifact record is not an object")
        language = _text(record.get("language"))
        if language is None:
            raise ValueError("artifact record language is missing")
        actual_by_language.setdefault(language.casefold(), set()).add(
            _identity_key(benchmark_identity(record))
        )

    expected_sets: dict[str, set[str]] = {}
    for raw_language, expected in expected_by_language.items():
        language = _text(raw_language)
        if language is None:
            raise ValueError("goldset language is invalid")
        if not isinstance(expected, Sequence) or isinstance(expected, (str, bytes)):
            raise ValueError("goldset language entries must be a sequence")
        identities: set[str] = set()
        for item in expected:
            if not isinstance(item, Mapping):
                raise ValueError("goldset identity must be an object")
            identities.add(_identity_key(item))
        expected_sets[language.casefold()] = identities

    languages = sorted(set(actual_by_language) | set(expected_sets))
    per_language: dict[str, Any] = {}
    eligible_languages: list[str] = []
    unbenchmarked_languages: list[str] = []
    failed_languages: list[str] = []
    for language in languages:
        actual = actual_by_language.get(language, set())
        expected = expected_sets.get(language)
        if expected is None or not expected:
            unbenchmarked_languages.append(language)
            per_language[language] = {
                "status": "unbenchmarked",
                "true_positive": 0,
                "false_positive": len(actual),
                "false_negative": 0,
                "precision": 0.0 if actual else 1.0,
                "recall": 0.0,
                "passed": False,
            }
            continue
        true_positive = len(actual & expected)
        false_positive = len(actual - expected)
        false_negative = len(expected - actual)
        precision = _metric(true_positive, true_positive + false_positive)
        recall = _metric(true_positive, true_positive + false_negative)
        passed = precision >= precision_threshold and recall >= recall_threshold
        if passed:
            eligible_languages.append(language)
        else:
            failed_languages.append(language)
        per_language[language] = {
            "status": "pass" if passed else "fail",
            "true_positive": true_positive,
            "false_positive": false_positive,
            "false_negative": false_negative,
            "precision": precision,
            "recall": recall,
            "passed": passed,
        }

    status = "fail" if failed_languages else "warn" if unbenchmarked_languages else "pass"
    return {
        "kind": BENCHMARK_KIND,
        "version": BENCHMARK_VERSION,
        "status": status,
        "artifact_source": {
            "index_sha256": artifact.get("source", {}).get("index_sha256"),
            "repository_commit": artifact.get("source", {}).get("repository_commit"),
        },
        "thresholds": {
            "minimum_precision": precision_threshold,
            "minimum_recall": recall_threshold,
        },
        "per_language": per_language,
        "eligible_languages": eligible_languages,
        "unbenchmarked_languages": unbenchmarked_languages,
        "failed_languages": failed_languages,
        "consumer_enablement": {
            "eligible_for_review": status == "pass" and bool(eligible_languages),
            "default_promoted": False,
        },
        "does_not_establish": list(BENCHMARK_DOES_NOT_ESTABLISH),
    }
