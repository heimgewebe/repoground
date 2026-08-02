"""Record collection and relationship projection for decoded SCIP indexes."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from merger.repoground.core._scip_adapter_common import (
    RELATIONSHIP_FLAGS,
    _degradation,
    _document_context,
    _field,
    _occurrence_record,
    _record_identity,
    _symbol_key,
    _text,
)


def _relationship_flag(
    relationship: Mapping[str, Any], aliases: Sequence[str]
) -> bool | None:
    value = _field(relationship, *aliases)
    if value is None:
        return False
    return value if isinstance(value, bool) else None


def _relationship_source(
    source_symbol: str,
    *,
    path: str,
    definitions: Mapping[tuple[str | None, str], list[dict[str, Any]]],
    degradations: list[dict[str, Any]],
) -> dict[str, Any] | None:
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
        return None
    source = source_definitions[0]["source"]
    if source["path"] != path:
        degradations.append(
            _degradation(
                "relationship_source_definition_document_mismatch",
                "SCIP relationship source definition belongs to another document",
                document=path,
                symbol=source_symbol,
            )
        )
        return None
    return source


def _relationship_types(
    relationship: Mapping[str, Any],
    *,
    path: str,
    source_symbol: str,
    degradations: list[dict[str, Any]],
) -> list[str]:
    relations: list[str] = []
    invalid_flag = False
    for aliases, relation in RELATIONSHIP_FLAGS:
        enabled = _relationship_flag(relationship, aliases)
        if enabled is None:
            invalid_flag = True
        elif enabled:
            relations.append(relation)
    if invalid_flag:
        degradations.append(
            _degradation(
                "relationship_flag_invalid",
                "SCIP relationship flag is not boolean",
                document=path,
                symbol=source_symbol,
            )
        )
    if not relations:
        degradations.append(
            _degradation(
                "relationship_unsupported",
                "SCIP relationship has no supported true flag",
                document=path,
                symbol=source_symbol,
            )
        )
    return relations


def _project_relationship(
    relationship: Any,
    *,
    path: str,
    language: str,
    source_symbol: str,
    source: dict[str, Any],
    degradations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not isinstance(relationship, Mapping):
        degradations.append(
            _degradation(
                "relationship_not_object",
                "SCIP relationship is not an object",
                document=path,
                symbol=source_symbol,
            )
        )
        return []
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
        return []
    relations = _relationship_types(
        relationship,
        path=path,
        source_symbol=source_symbol,
        degradations=degradations,
    )
    return [
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
        for relation in relations
    ]


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
    if not relationships:
        return []
    source = _relationship_source(
        source_symbol,
        path=path,
        definitions=definitions,
        degradations=degradations,
    )
    if source is None:
        return []
    records: list[dict[str, Any]] = []
    for relationship in relationships:
        records.extend(
            _project_relationship(
                relationship,
                path=path,
                language=language,
                source_symbol=source_symbol,
                source=source,
                degradations=degradations,
            )
        )
    return records


def _document_occurrences(
    document: Mapping[str, Any],
    *,
    path: str,
    language: str,
    position_encoding: Any,
    definitions: dict[tuple[str | None, str], list[dict[str, Any]]],
    degradations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
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
        return []
    records: list[dict[str, Any]] = []
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
            definitions.setdefault(_symbol_key(record["symbol"], path), []).append(
                record
            )
    return records


def _collect_occurrences(
    raw_documents: list[Any],
    degradations: list[dict[str, Any]],
) -> tuple[
    list[tuple[Mapping[str, Any], str, str, Any]],
    list[dict[str, Any]],
    dict[tuple[str | None, str], list[dict[str, Any]]],
    set[str],
]:
    contexts: list[tuple[Mapping[str, Any], str, str, Any]] = []
    records: list[dict[str, Any]] = []
    definitions: dict[tuple[str | None, str], list[dict[str, Any]]] = {}
    languages: set[str] = set()
    for raw_document in raw_documents:
        context = _document_context(raw_document, degradations)
        if context is None:
            continue
        document, path, language, position_encoding = context
        contexts.append(context)
        languages.add(language)
        records.extend(
            _document_occurrences(
                document,
                path=path,
                language=language,
                position_encoding=position_encoding,
                definitions=definitions,
                degradations=degradations,
            )
        )
    return contexts, records, definitions, languages


def _collect_relationships(
    contexts: list[tuple[Mapping[str, Any], str, str, Any]],
    definitions: Mapping[tuple[str | None, str], list[dict[str, Any]]],
    degradations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for document, path, language, _ in contexts:
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
    return records


def _record_external_symbol_degradation(
    index: Mapping[str, Any], degradations: list[dict[str, Any]]
) -> None:
    external_symbols = _field(index, "externalSymbols", "external_symbols")
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


def _ordered_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique_records: dict[tuple[Any, ...], dict[str, Any]] = {}
    for record in records:
        unique_records.setdefault(_record_identity(record), record)
    return sorted(unique_records.values(), key=_record_identity)


def _ordered_degradations(
    degradations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return sorted(
        degradations,
        key=lambda item: (
            item["code"],
            item.get("document") or "",
            item.get("symbol") or "",
            item["message"],
        ),
    )
