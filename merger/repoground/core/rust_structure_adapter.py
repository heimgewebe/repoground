"""Capability-bound Rust structure adapter.

The default lane is a conservative source lexer for declarations, ``use``
dependencies and same-file calls.  It never presents those records as Rust
compiler truth.  A caller may additionally supply an already-normalized
RepoGround SCIP artifact, which is lifted as higher-confidence S1 evidence
without invoking rust-analyzer, downloading tools, or reading unbound state.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from merger.repoground.core.bounded_artifact_read import (
    read_stable_regular_file_bytes,
)
from merger.repoground.core.language_structure import make_record, source_range

ADAPTER_ID = "rust-static-structure"
ADAPTER_VERSION = "1.0"
SCIP_ADAPTER_ID = "rust-scip-structure"
SCIP_ADAPTER_VERSION = "1.0"
LANGUAGE = "rust"

_SKIP_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".venv",
        "venv",
        "node_modules",
        "target",
        "dist",
        "build",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".cache",
    }
)
_DECL_RE = re.compile(
    r"^[ \t]*(?:pub(?:\([^)]*\))?[ \t]+)?(?:async[ \t]+)?(?:unsafe[ \t]+)?"
    r"(?P<kind>fn|struct|enum|trait|type|const|static|mod)[ \t]+"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
)
_USE_RE = re.compile(
    r"^[ \t]*(?:pub[ \t]+)?use[ \t]+(?P<target>[^;]+);[ \t]*(?://.*)?$"
)
_MACRO_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_:]*![ \t]*(?:\(|\{|\[)")
_RAW_STRING_START_RE = re.compile(r'r(?P<hashes>#{0,255})"')
_SCIP_POSITION_ENCODINGS = frozenset(
    {
        "UTF8CodeUnitOffsetFromLineStart",
        "UTF16CodeUnitOffsetFromLineStart",
        "UTF32CodeUnitOffsetFromLineStart",
        1,
        2,
        3,
    }
)
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
_SCIP_ROLES = frozenset(
    {
        "definition",
        "import",
        "write_access",
        "read_access",
        "generated",
        "test",
        "forward_definition",
    }
)
_SCIP_SOURCE_RULES = frozenset(
    {"scip_occurrence_symbol_roles", "scip_symbol_information_relationship"}
)


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _iter_files(root: Path, *, max_files: int) -> tuple[list[Path], bool]:
    files: list[Path] = []
    for current, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in _SKIP_DIRS)
        for name in sorted(names):
            path = Path(current) / name
            if path.is_symlink() or path.suffix.lower() != ".rs":
                continue
            if len(files) >= max_files:
                return files, True
            files.append(path)
    return files, False


def _read(path: Path, *, max_file_bytes: int) -> tuple[str | None, str | None]:
    raw, _identity, failure, _detail = read_stable_regular_file_bytes(
        path,
        max_bytes=max_file_bytes,
    )
    if failure is not None or raw is None:
        if failure == "too_large":
            return None, "file_size_limit"
        return None, "source_read_failed"
    try:
        return raw.decode("utf-8"), None
    except UnicodeDecodeError:
        return None, "non_utf8_source"


def _mask_block_comment(
    line: str, output: list[str], index: int, block_depth: int
) -> tuple[int, int]:
    nested = line.find("/*", index)
    closing = line.find("*/", index)
    if closing < 0 and nested < 0:
        output[index:] = " " * (len(line) - index)
        return len(line), block_depth
    if nested >= 0 and (closing < 0 or nested < closing):
        output[index : nested + 2] = " " * (nested + 2 - index)
        return nested + 2, block_depth + 1
    output[index : closing + 2] = " " * (closing + 2 - index)
    return closing + 2, block_depth - 1


def _mask_quoted_string(line: str, output: list[str], index: int) -> int:
    start = index
    index += 1
    escaped = False
    while index < len(line):
        character = line[index]
        index += 1
        if character == '"' and not escaped:
            break
        escaped = character == "\\" and not escaped
        if character != "\\":
            escaped = False
    output[start:index] = " " * (index - start)
    return index


def _mask_character_literal(line: str, output: list[str], index: int) -> int:
    if line[index] != "'":
        return index + 1
    closing = line.find("'", index + 1, min(len(line), index + 8))
    if closing < 0:
        return index + 1
    output[index : closing + 1] = " " * (closing + 1 - index)
    return closing + 1


def _mask_rust_line(
    line: str, *, block_depth: int, raw_terminator: str | None
) -> tuple[str, int, str | None]:
    output = list(line)
    index = 0
    while index < len(line):
        if raw_terminator is not None:
            end = line.find(raw_terminator, index)
            stop = len(line) if end < 0 else end + len(raw_terminator)
            output[index:stop] = " " * (stop - index)
            index = stop
            if end >= 0:
                raw_terminator = None
            continue
        if block_depth:
            index, block_depth = _mask_block_comment(line, output, index, block_depth)
            continue
        if line.startswith("//", index):
            output[index:] = " " * (len(line) - index)
            break
        if line.startswith("/*", index):
            output[index : index + 2] = "  "
            block_depth = 1
            index += 2
            continue
        raw = _RAW_STRING_START_RE.match(line, index)
        if raw is not None:
            raw_terminator = '"' + raw.group("hashes")
            output[index : raw.end()] = " " * (raw.end() - index)
            index = raw.end()
            continue
        if line[index] == '"':
            index = _mask_quoted_string(line, output, index)
            continue
        index = _mask_character_literal(line, output, index)
    return "".join(output), block_depth, raw_terminator


def _masked_rust_lines(lines: list[str]) -> tuple[list[str], list[dict[str, Any]]]:
    """Mask comments and string/character literals without changing offsets."""
    masked_lines: list[str] = []
    degradations: list[dict[str, Any]] = []
    block_depth = 0
    raw_terminator: str | None = None
    for line in lines:
        masked, block_depth, raw_terminator = _mask_rust_line(
            line, block_depth=block_depth, raw_terminator=raw_terminator
        )
        masked_lines.append(masked)
    if block_depth:
        degradations.append(
            {"language": LANGUAGE, "reason": "unterminated_block_comment"}
        )
    if raw_terminator is not None:
        degradations.append({"language": LANGUAGE, "reason": "unterminated_raw_string"})
    return masked_lines, degradations


def _digest(value: object) -> str | None:
    if (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    ):
        return value
    return None


def _safe_repo_path(value: object) -> str | None:
    if (
        not isinstance(value, str)
        or not value
        or "\\" in value
        or "//" in value
        or re.match(r"^[A-Za-z]:", value) is not None
        or value[-1].isspace()
        or any(
            ord(character) < 32
            or 127 <= ord(character) <= 159
            or 0xD800 <= ord(character) <= 0xDFFF
            or ord(character) in {0x2028, 0x2029, 0xFEFF}
            for character in value
        )
    ):
        return None
    path = Path(value)
    if (
        path.is_absolute()
        or path.as_posix() != value
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        return None
    return path.as_posix()


def _scip_range(value: object) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    required = ("start_line", "end_line", "start_character", "end_character")
    if any(
        isinstance(value.get(field), bool) or not isinstance(value.get(field), int)
        for field in required
    ):
        return None
    start_line = int(value["start_line"])
    end_line = int(value["end_line"])
    start_character = int(value["start_character"])
    end_character = int(value["end_character"])
    position_encoding = value.get("position_encoding")
    if (
        start_line < 1
        or end_line < start_line
        or start_character < 0
        or end_character < 0
        or (start_line == end_line and end_character <= start_character)
        or isinstance(position_encoding, bool)
        or not isinstance(position_encoding, (str, int))
        or position_encoding not in _SCIP_POSITION_ENCODINGS
    ):
        return None
    return {
        "start_line": start_line,
        "end_line": end_line,
        "start_character": start_character,
        "end_character": end_character,
        "coordinate_basis": "scip_position_encoding_units",
        "position_encoding": position_encoding,
    }


def _optional_scip_scalar(value: object) -> bool:
    return value is None or (
        isinstance(value, (str, int)) and not isinstance(value, bool)
    )


def _normalized_scip_source_valid(source: object) -> bool:
    if not isinstance(source, Mapping) or set(source) != {
        "format",
        "protocol",
        "protocol_version",
        "index_sha256",
        "repository_commit",
        "indexer",
        "project_root_sha256",
        "text_document_encoding",
    }:
        return False
    indexer = source.get("indexer")
    project_root_sha256 = source.get("project_root_sha256")
    return (
        source.get("format") == "decoded_scip_protobuf_json"
        and source.get("protocol") == "SCIP"
        and _optional_scip_scalar(source.get("protocol_version"))
        and _digest(source.get("index_sha256")) is not None
        and isinstance(source.get("repository_commit"), str)
        and re.fullmatch(r"[a-f0-9]{40}(?:[a-f0-9]{24})?", source["repository_commit"])
        is not None
        and isinstance(indexer, Mapping)
        and set(indexer) == {"name", "version", "arguments_sha256"}
        and (
            indexer.get("name") is None
            or (isinstance(indexer.get("name"), str) and bool(indexer.get("name")))
        )
        and (
            indexer.get("version") is None
            or (
                isinstance(indexer.get("version"), str) and bool(indexer.get("version"))
            )
        )
        and _digest(indexer.get("arguments_sha256")) is not None
        and (project_root_sha256 is None or _digest(project_root_sha256) is not None)
        and _optional_scip_scalar(source.get("text_document_encoding"))
    )


def _normalized_scip_record_valid(item: object) -> bool:
    if not isinstance(item, Mapping) or set(item) != {
        "record_type",
        "relation",
        "language",
        "symbol",
        "target_symbol",
        "roles",
        "source",
        "source_rule",
    }:
        return False
    source = item.get("source")
    source_range_value = source.get("range") if isinstance(source, Mapping) else None
    roles = item.get("roles")
    target_symbol = item.get("target_symbol")
    record_type = item.get("record_type")
    relation = item.get("relation")
    source_rule = item.get("source_rule")
    return (
        isinstance(record_type, str)
        and record_type in {"occurrence", "relationship"}
        and isinstance(relation, str)
        and relation in _SCIP_RELATIONS
        and isinstance(item.get("language"), str)
        and bool(item.get("language"))
        and isinstance(item.get("symbol"), str)
        and bool(item.get("symbol"))
        and (
            target_symbol is None
            or (isinstance(target_symbol, str) and bool(target_symbol))
        )
        and isinstance(roles, list)
        and all(isinstance(role, str) and role in _SCIP_ROLES for role in roles)
        and len(roles) == len(set(roles))
        and isinstance(source, Mapping)
        and set(source) == {"path", "range"}
        and _safe_repo_path(source.get("path")) is not None
        and isinstance(source_range_value, Mapping)
        and set(source_range_value)
        == {
            "start_line",
            "end_line",
            "start_character",
            "end_character",
            "position_encoding",
        }
        and _scip_range(source_range_value) is not None
        and isinstance(source_rule, str)
        and source_rule in _SCIP_SOURCE_RULES
    )


def _normalized_scip_degradations_valid(value: object) -> bool:
    if not isinstance(value, list):
        return False
    for item in value:
        if not isinstance(item, Mapping) or set(item) != {
            "code",
            "message",
            "document",
            "symbol",
            "count",
        }:
            return False
        if not isinstance(item.get("code"), str) or not item.get("code"):
            return False
        if not isinstance(item.get("message"), str) or not item.get("message"):
            return False
        if item.get("document") is not None and not isinstance(
            item.get("document"), str
        ):
            return False
        if item.get("symbol") is not None and not isinstance(item.get("symbol"), str):
            return False
        count = item.get("count")
        if count is not None and (
            isinstance(count, bool) or not isinstance(count, int) or count < 0
        ):
            return False
    return True


def _normalized_scip_envelope_valid(artifact: Mapping[str, Any]) -> bool:
    if set(artifact) != {
        "kind",
        "version",
        "authority",
        "canonicality",
        "status",
        "source",
        "languages",
        "records",
        "record_count",
        "degradations",
        "consumer_enablement",
        "does_not_establish",
    }:
        return False
    records = artifact.get("records")
    languages = artifact.get("languages")
    degradations = artifact.get("degradations")
    enablement = artifact.get("consumer_enablement")
    does_not_establish = artifact.get("does_not_establish")
    record_count = artifact.get("record_count")
    return (
        artifact.get("kind") == "repoground.scip_symbol_relations"
        and artifact.get("version") == "1.0"
        and artifact.get("authority") == "navigation_index"
        and artifact.get("canonicality") == "derived"
        and isinstance(artifact.get("status"), str)
        and artifact.get("status") in {"available", "degraded"}
        and _normalized_scip_source_valid(artifact.get("source"))
        and isinstance(languages, list)
        and all(isinstance(language, str) and language for language in languages)
        and languages == sorted(set(languages))
        and isinstance(records, list)
        and isinstance(record_count, int)
        and not isinstance(record_count, bool)
        and record_count == len(records)
        and all(_normalized_scip_record_valid(item) for item in records)
        and {str(item.get("language")) for item in records} <= set(languages)
        and _normalized_scip_degradations_valid(degradations)
        and (artifact.get("status") == "degraded") == bool(degradations)
        and enablement
        == {
            "requires_language_benchmark": True,
            "eligible_for_review": False,
            "default_promoted": False,
        }
        and isinstance(does_not_establish, list)
        and len(does_not_establish) == 12
        and all(isinstance(item, str) and item for item in does_not_establish)
        and len(does_not_establish) == len(set(does_not_establish))
    )


def _normalized_scip_sha256(artifact: Mapping[str, Any]) -> str:
    payload = json.dumps(
        artifact,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _scip_records(
    artifact: Mapping[str, Any] | None,
    *,
    repository_commit: str,
    bundle_manifest: str,
    canonical_dump_index_sha256: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if artifact is None:
        return [], []
    source = artifact.get("source")
    index_sha256 = (
        _digest(source.get("index_sha256")) if isinstance(source, Mapping) else None
    )
    if not _normalized_scip_envelope_valid(artifact) or index_sha256 is None:
        return [], [{"language": LANGUAGE, "reason": "scip_contract_invalid"}]
    artifact_commit = (
        source.get("repository_commit") if isinstance(source, Mapping) else None
    )
    if artifact_commit != repository_commit:
        return [], [
            {
                "language": LANGUAGE,
                "reason": "scip_repository_commit_mismatch",
                "expected": repository_commit,
                "observed": artifact_commit,
            }
        ]
    raw_records = artifact["records"]
    normalized_artifact_sha256 = _normalized_scip_sha256(artifact)
    records: list[dict[str, Any]] = []
    for item in raw_records:
        if (
            not isinstance(item, Mapping)
            or str(item.get("language", "")).lower() != LANGUAGE
        ):
            continue
        item_source = item.get("source")
        if not isinstance(item_source, Mapping):
            continue
        path = _safe_repo_path(item_source.get("path"))
        range_value = _scip_range(item_source.get("range"))
        symbol = item.get("symbol")
        relation = item.get("relation")
        if not all(
            isinstance(value, str) and value for value in (path, symbol, relation)
        ):
            continue
        if range_value is None:
            continue
        records.append(
            make_record(
                language=LANGUAGE,
                adapter_id=SCIP_ADAPTER_ID,
                adapter_version=SCIP_ADAPTER_VERSION,
                record_type=str(item.get("record_type") or "relation"),
                relation=relation,
                symbol=symbol,
                target_symbol=item.get("target_symbol")
                if isinstance(item.get("target_symbol"), str)
                else None,
                symbol_kind=str(item.get("symbol_kind"))
                if item.get("symbol_kind") is not None
                else None,
                source_path=path,
                source_range_value=range_value,
                repository_commit=repository_commit,
                bundle_manifest=bundle_manifest,
                canonical_dump_index_sha256=canonical_dump_index_sha256,
                evidence_level="S1",
                confidence=0.98,
                basis="normalized_scip_symbol_relation",
                source_artifact={
                    "kind": "scip_symbol_relations",
                    "sha256": normalized_artifact_sha256,
                },
                uncertainty=[
                    "scip_indexer_semantics_apply",
                    "runtime_reachability_not_established",
                ],
            )
        )
    return records, []


def _validated_scan_root(
    repo_root: str | Path, *, max_files: int, max_file_bytes: int, max_records: int
) -> Path:
    root = Path(repo_root).resolve()
    if not root.is_dir():
        raise ValueError("repo_root must be an existing directory")
    for field, value in (
        ("max_files", max_files),
        ("max_file_bytes", max_file_bytes),
        ("max_records", max_records),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{field} must be a positive integer")
    return root


def _rust_declarations(
    lines: list[str],
) -> tuple[
    list[tuple[str, str, int, int, int]],
    dict[str, list[tuple[int, int, int]]],
]:
    declarations: list[tuple[str, str, int, int, int]] = []
    functions: dict[str, list[tuple[int, int, int]]] = {}
    for line_number, line in enumerate(lines, start=1):
        match = _DECL_RE.match(line)
        if match:
            name = match.group("name")
            kind = match.group("kind")
            start = match.start("name")
            end = match.end("name")
            declarations.append((kind, name, line_number, start, end))
            if kind == "fn":
                functions.setdefault(name, []).append((line_number, start, end))
    return declarations, functions


def _duplicate_function_degradations(
    functions: Mapping[str, list[tuple[int, int, int]]], *, path: str
) -> list[dict[str, Any]]:
    return [
        {
            "language": LANGUAGE,
            "path": path,
            "reason": "duplicate_function_definition",
            "symbol": name,
            "count": len(locations),
            "lines": [item[0] for item in sorted(locations)],
        }
        for name, locations in sorted(functions.items())
        if len(locations) > 1
    ]


def _rust_definition_records(
    declarations: list[tuple[str, str, int, int, int]],
    *,
    path: str,
    binding: Mapping[str, str],
) -> list[dict[str, Any]]:
    return [
        make_record(
            language=LANGUAGE,
            adapter_id=ADAPTER_ID,
            adapter_version=ADAPTER_VERSION,
            record_type="symbol",
            relation="definition",
            symbol=name,
            symbol_kind=kind,
            source_path=path,
            source_range_value=source_range(
                line=line_number, start_character=start, end_character=end
            ),
            evidence_level="S0",
            confidence=0.86 if kind == "fn" else 0.9,
            basis="static_rust_declaration_lexer",
            uncertainty=[
                "rust_parser_not_used",
                "macro_expansion_not_applied",
                "cfg_evaluation_not_applied",
            ],
            **binding,
        )
        for kind, name, line_number, start, end in declarations
    ]


def _rust_use_record(
    line: str, *, line_number: int, path: str, binding: Mapping[str, str]
) -> dict[str, Any] | None:
    use = _USE_RE.match(line)
    if use is None:
        return None
    target = use.group("target").strip()
    start = (
        use.start("target")
        + len(use.group("target"))
        - len(use.group("target").lstrip())
    )
    return make_record(
        language=LANGUAGE,
        adapter_id=ADAPTER_ID,
        adapter_version=ADAPTER_VERSION,
        record_type="relation",
        relation="dependency",
        symbol=path,
        target_symbol=target,
        symbol_kind="use_path",
        source_path=path,
        source_range_value=source_range(
            line=line_number,
            start_character=start,
            end_character=start + len(target),
        ),
        evidence_level="S0",
        confidence=0.82,
        basis="static_rust_use_declaration",
        uncertainty=[
            "use_path_not_resolved_to_filesystem_target",
            "cfg_evaluation_not_applied",
        ],
        **binding,
    )


def _rust_call_evidence(
    line: str,
    *,
    line_number: int,
    path: str,
    functions: Mapping[str, list[tuple[int, int, int]]],
    binding: Mapping[str, str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    records: list[dict[str, Any]] = []
    degradations: list[dict[str, Any]] = []
    for callee in sorted(functions):
        match = re.search(rf"(?<![A-Za-z0-9_]){re.escape(callee)}[ \t]*\(", line)
        if match is None:
            continue
        locations = functions[callee]
        if len(locations) != 1:
            degradations.append(
                {
                    "language": LANGUAGE,
                    "path": path,
                    "line": line_number,
                    "reason": "ambiguous_function_call_target",
                    "symbol": callee,
                    "candidate_lines": [item[0] for item in sorted(locations)],
                }
            )
            continue
        records.append(
            make_record(
                language=LANGUAGE,
                adapter_id=ADAPTER_ID,
                adapter_version=ADAPTER_VERSION,
                record_type="relation",
                relation="call",
                symbol=path,
                target_symbol=callee,
                symbol_kind="same_file_function_call",
                source_path=path,
                source_range_value=source_range(
                    line=line_number,
                    start_character=match.start(),
                    end_character=match.start() + len(callee),
                ),
                evidence_level="S0",
                confidence=0.7,
                basis="static_same_file_rust_call_lexer",
                uncertainty=[
                    "name_resolution_not_performed",
                    "method_dispatch_not_resolved",
                    "macro_expansion_not_applied",
                ],
                **binding,
            )
        )
    return records, degradations


def _rust_line_evidence(
    line: str,
    *,
    line_number: int,
    path: str,
    functions: Mapping[str, list[tuple[int, int, int]]],
    binding: Mapping[str, str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    records: list[dict[str, Any]] = []
    degradations: list[dict[str, Any]] = []
    macro = _MACRO_RE.search(line)
    if macro:
        degradations.append(
            {
                "language": LANGUAGE,
                "path": path,
                "line": line_number,
                "reason": "macro_invocation_not_expanded",
                "token": macro.group(0).strip(),
            }
        )
    use_record = _rust_use_record(
        line, line_number=line_number, path=path, binding=binding
    )
    if use_record is not None:
        records.append(use_record)
    if _DECL_RE.match(line) or macro:
        return records, degradations
    call_records, call_degradations = _rust_call_evidence(
        line,
        line_number=line_number,
        path=path,
        functions=functions,
        binding=binding,
    )
    records.extend(call_records)
    degradations.extend(call_degradations)
    return records, degradations


def _scan_rust_lines(
    lines: list[str], *, path: str, binding: Mapping[str, str]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    masked_lines, degradations = _masked_rust_lines(lines)
    degradations = [{**item, "path": path} for item in degradations]
    declarations, functions = _rust_declarations(masked_lines)
    degradations.extend(_duplicate_function_degradations(functions, path=path))
    records = _rust_definition_records(declarations, path=path, binding=binding)
    for line_number, line in enumerate(masked_lines, start=1):
        line_records, line_degradations = _rust_line_evidence(
            line,
            line_number=line_number,
            path=path,
            functions=functions,
            binding=binding,
        )
        records.extend(line_records)
        degradations.extend(line_degradations)
    return records, degradations


def scan_rust_repository(
    repo_root: str | Path,
    *,
    repository_commit: str,
    bundle_manifest: str,
    canonical_dump_index_sha256: str,
    scip_artifact: Mapping[str, Any] | None = None,
    max_files: int = 5000,
    max_file_bytes: int = 524_288,
    max_records: int = 50_000,
) -> dict[str, Any]:
    """Scan Rust source conservatively and optionally overlay bound SCIP evidence."""
    root = _validated_scan_root(
        repo_root,
        max_files=max_files,
        max_file_bytes=max_file_bytes,
        max_records=max_records,
    )
    files, files_truncated = _iter_files(root, max_files=max_files)
    records: list[dict[str, Any]] = []
    degradations: list[dict[str, Any]] = []
    candidate_files = len(files)
    scanned = 0
    binding = {
        "repository_commit": repository_commit,
        "bundle_manifest": bundle_manifest,
        "canonical_dump_index_sha256": canonical_dump_index_sha256,
    }

    for path in files:
        text, read_error = _read(path, max_file_bytes=max_file_bytes)
        rel = _relative(path, root)
        if read_error:
            degradations.append(
                {"language": LANGUAGE, "path": rel, "reason": read_error}
            )
            continue
        assert text is not None
        scanned += 1
        lines = text.splitlines()
        file_records, file_degradations = _scan_rust_lines(
            lines, path=rel, binding=binding
        )
        degradations.extend(file_degradations)
        remaining = max_records - len(records)
        records.extend(file_records[:remaining])
        if len(file_records) > remaining:
            degradations.append(
                {"language": LANGUAGE, "reason": "record_limit", "limit": max_records}
            )
            break

    scip_records, scip_degradations = _scip_records(
        scip_artifact,
        repository_commit=repository_commit,
        bundle_manifest=bundle_manifest,
        canonical_dump_index_sha256=canonical_dump_index_sha256,
    )
    remaining = max(0, max_records - len(records))
    if len(scip_records) > remaining:
        degradations.append(
            {"language": LANGUAGE, "reason": "record_limit", "limit": max_records}
        )
    accepted_scip_records = scip_records[:remaining]
    records.extend(accepted_scip_records)
    degradations.extend(scip_degradations)
    if candidate_files and scip_artifact is None:
        degradations.append(
            {
                "language": LANGUAGE,
                "reason": "scip_evidence_not_supplied",
                "detail": (
                    "Lexical S0 evidence is available; higher-confidence SCIP S1 evidence "
                    "remains opt-in and is never generated or downloaded automatically."
                ),
            }
        )
    if files_truncated:
        degradations.append(
            {"language": LANGUAGE, "reason": "file_limit", "limit": max_files}
        )
    records = sorted(
        records,
        key=lambda item: (
            str(item.get("source", {}).get("path")),
            int(item.get("source", {}).get("range", {}).get("start_line", 0)),
            -float(item.get("evidence", {}).get("confidence", 0.0)),
            str(item.get("relation")),
            str(item.get("symbol")),
        ),
    )[:max_records]
    status = "available" if not degradations else "degraded"
    return {
        "status": status,
        "records": records,
        "degradations": degradations,
        "summary": {
            "status": status,
            "adapter": {"id": ADAPTER_ID, "version": ADAPTER_VERSION},
            "scip_adapter": {"id": SCIP_ADAPTER_ID, "version": SCIP_ADAPTER_VERSION},
            "supported_files": ["*.rs"],
            "supported_symbols": [
                "fn",
                "struct",
                "enum",
                "trait",
                "type",
                "const",
                "static",
                "mod",
            ],
            "supported_relations": [
                "definition",
                "use dependency (unresolved path)",
                "same-file statically named function call",
                "normalized SCIP definition/reference/relationship when supplied",
            ],
            "range_basis": "1-based source line + Unicode character offsets; SCIP ranges preserved verbatim",
            "explicit_limits": [
                "macro expansion",
                "procedural macros",
                "cfg evaluation",
                "generated/include code",
                "trait/method dispatch",
                "cross-module name resolution in lexical lane",
                "duplicate same-file function names are not resolved for calls",
                "runtime reachability",
            ],
            "candidate_file_count": candidate_files,
            "scanned_file_count": scanned,
            "scip_record_count": len(accepted_scip_records),
            "record_count": len(records),
        },
    }


__all__ = [
    "ADAPTER_ID",
    "ADAPTER_VERSION",
    "SCIP_ADAPTER_ID",
    "SCIP_ADAPTER_VERSION",
    "scan_rust_repository",
]
