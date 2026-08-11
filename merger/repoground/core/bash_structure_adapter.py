"""Conservative, offline Bash structure adapter.

This is intentionally not a shell interpreter.  It recognizes only a small
static subset and records every dynamic construct it declines to resolve.
"""

from __future__ import annotations

import os
import re
import shlex
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from merger.repoground.core.bounded_artifact_read import (
    read_stable_regular_file_bytes,
)
from merger.repoground.core.language_structure import make_record, source_range

ADAPTER_ID = "bash-static-structure"
ADAPTER_VERSION = "1.0"
LANGUAGE = "bash"

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
_FUNCTION_RE = re.compile(
    r"^(?P<indent>[ \t]*)(?:(?:function)[ \t]+)?"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)[ \t]*(?:\(\))?[ \t]*\{"
)
_SIMPLE_COMMAND_RE = re.compile(r"^[ \t]*(?P<name>[A-Za-z_][A-Za-z0-9_]*)\b")
_SHELL_KEYWORDS = frozenset(
    {
        "if",
        "then",
        "else",
        "elif",
        "fi",
        "for",
        "while",
        "until",
        "do",
        "done",
        "case",
        "esac",
        "select",
        "time",
        "coproc",
        "function",
        "source",
        "local",
        "declare",
        "typeset",
        "readonly",
        "export",
        "return",
        "exit",
        "printf",
        "echo",
    }
)


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _is_candidate(path: Path, first_line: str) -> tuple[bool, list[str]]:
    suffix = path.suffix.lower()
    if suffix in {".bash", ".bats"}:
        return True, []
    if suffix != ".sh":
        return False, []
    if "bash" in first_line.lower():
        return True, []
    return True, ["shell_dialect_not_proven_bash"]


def _iter_files(root: Path, *, max_files: int) -> tuple[list[Path], bool]:
    files: list[Path] = []
    truncated = False
    for current, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in _SKIP_DIRS)
        for name in sorted(names):
            path = Path(current) / name
            if path.is_symlink() or path.suffix.lower() not in {
                ".sh",
                ".bash",
                ".bats",
            }:
                continue
            if len(files) >= max_files:
                truncated = True
                return files, truncated
            files.append(path)
    return files, truncated


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


def _source_dependency(line: str) -> tuple[str | None, str | None]:
    stripped = line.strip()
    if not (stripped.startswith("source ") or stripped.startswith(". ")):
        return None, None
    try:
        tokens = shlex.split(stripped, posix=True)
    except ValueError:
        return None, "source_parse_failed"
    if len(tokens) < 2 or tokens[0] not in {"source", "."}:
        return None, "source_parse_failed"
    target = tokens[1]
    if any(marker in target for marker in ("$", "`", "*", "?", "[", "]", "{")):
        return None, "dynamic_source_target"
    return target, None


def _dynamic_reason(line: str) -> str | None:
    if "eval " in line or line.lstrip().startswith("eval\t"):
        return "eval_not_resolved"
    if "${!" in line:
        return "indirect_parameter_expansion_not_resolved"
    if "$(" in line or "`" in line:
        return "command_substitution_not_resolved"
    return None


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


def _function_locations(lines: list[str]) -> dict[str, list[tuple[int, int, int]]]:
    definitions: dict[str, list[tuple[int, int, int]]] = {}
    for line_number, line in enumerate(lines, start=1):
        match = _FUNCTION_RE.match(line)
        if match:
            definitions.setdefault(match.group("name"), []).append(
                (line_number, match.start("name"), match.end("name"))
            )
    return definitions


def _definition_evidence(
    definitions: Mapping[str, list[tuple[int, int, int]]],
    *,
    path: str,
    uncertainty: list[str],
    binding: Mapping[str, str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    records: list[dict[str, Any]] = []
    degradations: list[dict[str, Any]] = []
    for name in sorted(definitions):
        locations = sorted(definitions[name])
        if len(locations) > 1:
            degradations.append(
                {
                    "language": LANGUAGE,
                    "path": path,
                    "reason": "duplicate_function_definition",
                    "symbol": name,
                    "count": len(locations),
                    "lines": [item[0] for item in locations],
                }
            )
        for line_number, start, end in locations:
            records.append(
                make_record(
                    language=LANGUAGE,
                    adapter_id=ADAPTER_ID,
                    adapter_version=ADAPTER_VERSION,
                    record_type="symbol",
                    relation="definition",
                    symbol=name,
                    symbol_kind="function",
                    source_path=path,
                    source_range_value=source_range(
                        line=line_number, start_character=start, end_character=end
                    ),
                    evidence_level="S0",
                    confidence=0.9,
                    basis="static_bash_function_declaration",
                    uncertainty=uncertainty,
                    **binding,
                )
            )
    return records, degradations


def _line_evidence(
    line: str,
    *,
    line_number: int,
    path: str,
    definitions: Mapping[str, list[tuple[int, int, int]]],
    uncertainty: list[str],
    binding: Mapping[str, str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    records: list[dict[str, Any]] = []
    degradations: list[dict[str, Any]] = []
    dynamic_reason = _dynamic_reason(line)
    if dynamic_reason:
        degradations.append(
            {
                "language": LANGUAGE,
                "path": path,
                "line": line_number,
                "reason": dynamic_reason,
            }
        )
    target, source_error = _source_dependency(line)
    if source_error:
        degradations.append(
            {
                "language": LANGUAGE,
                "path": path,
                "line": line_number,
                "reason": source_error,
            }
        )
    elif target is not None:
        start = max(0, line.find(target))
        records.append(
            make_record(
                language=LANGUAGE,
                adapter_id=ADAPTER_ID,
                adapter_version=ADAPTER_VERSION,
                record_type="relation",
                relation="dependency",
                symbol=path,
                target_symbol=target,
                symbol_kind="source_file",
                source_path=path,
                source_range_value=source_range(
                    line=line_number,
                    start_character=start,
                    end_character=start + len(target),
                ),
                evidence_level="S0",
                confidence=0.85,
                basis="literal_bash_source_dependency",
                uncertainty=uncertainty,
                **binding,
            )
        )
    if _FUNCTION_RE.match(line) or dynamic_reason:
        return records, degradations
    command = _SIMPLE_COMMAND_RE.match(line)
    if command is None:
        return records, degradations
    callee = command.group("name")
    locations = definitions.get(callee)
    if callee in _SHELL_KEYWORDS or not locations:
        return records, degradations
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
        return records, degradations
    records.append(
        make_record(
            language=LANGUAGE,
            adapter_id=ADAPTER_ID,
            adapter_version=ADAPTER_VERSION,
            record_type="relation",
            relation="call",
            symbol=path,
            target_symbol=callee,
            symbol_kind="local_function_call",
            source_path=path,
            source_range_value=source_range(
                line=line_number,
                start_character=command.start("name"),
                end_character=command.end("name"),
            ),
            evidence_level="S0",
            confidence=0.8,
            basis="static_same_file_bash_function_call",
            uncertainty=[*uncertainty, "shell_runtime_dispatch_not_evaluated"],
            **binding,
        )
    )
    return records, degradations


def _scan_bash_lines(
    lines: list[str],
    *,
    path: str,
    uncertainty: list[str],
    binding: Mapping[str, str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    definitions = _function_locations(lines)
    records, degradations = _definition_evidence(
        definitions, path=path, uncertainty=uncertainty, binding=binding
    )
    for line_number, line in enumerate(lines, start=1):
        line_records, line_degradations = _line_evidence(
            line,
            line_number=line_number,
            path=path,
            definitions=definitions,
            uncertainty=uncertainty,
            binding=binding,
        )
        records.extend(line_records)
        degradations.extend(line_degradations)
    return records, degradations


def scan_bash_repository(
    repo_root: str | Path,
    *,
    repository_commit: str,
    bundle_manifest: str,
    canonical_dump_index_sha256: str,
    max_files: int = 5000,
    max_file_bytes: int = 524_288,
    max_records: int = 50_000,
) -> dict[str, Any]:
    """Scan the bound repository using a deterministic static Bash subset."""
    root = _validated_scan_root(
        repo_root,
        max_files=max_files,
        max_file_bytes=max_file_bytes,
        max_records=max_records,
    )
    files, files_truncated = _iter_files(root, max_files=max_files)
    records: list[dict[str, Any]] = []
    degradations: list[dict[str, Any]] = []
    scanned = 0
    candidate_files = 0
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
        lines = text.splitlines()
        first_line = lines[0] if lines else ""
        supported, file_uncertainty = _is_candidate(path, first_line)
        if not supported:
            continue
        candidate_files += 1
        scanned += 1
        file_records, file_degradations = _scan_bash_lines(
            lines, path=rel, uncertainty=file_uncertainty, binding=binding
        )
        degradations.extend(file_degradations)
        remaining = max_records - len(records)
        records.extend(file_records[:remaining])
        if len(file_records) > remaining:
            degradations.append(
                {"language": LANGUAGE, "reason": "record_limit", "limit": max_records}
            )
            break

    if files_truncated:
        degradations.append(
            {"language": LANGUAGE, "reason": "file_limit", "limit": max_files}
        )
    status = "available" if not degradations else "degraded"
    return {
        "status": status,
        "records": records,
        "degradations": degradations,
        "summary": {
            "status": status,
            "adapter": {"id": ADAPTER_ID, "version": ADAPTER_VERSION},
            "supported_files": [
                "*.bash",
                "*.bats",
                "*.sh (Bash shebang preferred; otherwise dialect uncertainty is explicit)",
            ],
            "supported_symbols": ["function"],
            "supported_relations": [
                "definition",
                "same-file static function call",
                "literal source/. dependency",
            ],
            "range_basis": "1-based source line + Unicode character offsets",
            "explicit_limits": [
                "eval",
                "indirect parameter expansion",
                "command substitution",
                "dynamic source targets",
                "runtime PATH/alias/function mutation",
                "duplicate same-file function names are not resolved for calls",
                "generated code",
            ],
            "candidate_file_count": candidate_files,
            "scanned_file_count": scanned,
            "record_count": len(records),
        },
    }


__all__ = ["ADAPTER_ID", "ADAPTER_VERSION", "scan_bash_repository"]
