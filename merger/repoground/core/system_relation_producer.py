"""Conservative revision-bound producer for static repository relations.

The producer intentionally supports only a small set of declarations whose
meaning can be established from repository text without executing code:

* root ``pyproject.toml`` first-level ``[tool.NAME]`` tables declare config contracts;
* ``*.schema.json`` files with a top-level literal ``$id`` declare schema contracts;
* local GitHub workflow ``uses: ./.github/workflows/...`` entries reference an
  existing workflow file in the same commit.

Candidates and file bytes are read from the Git object database of the requested
commit, never from the mutable working tree. Everything dynamic or ambiguous is
omitted rather than inferred. The result is deterministic and suitable for
``system_relation_overlay`` normalization, but it is not runtime truth and does
not establish config effects, schema conformance or workflow execution.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import select
import subprocess
import time
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 compatibility
    try:
        import tomli as tomllib
    except ModuleNotFoundError:
        tomllib = None

from merger.repoground.core.system_relation_overlay import (
    MAX_EVIDENCE_RECORDS,
    normalize_system_relation_evidence,
)
from merger.repoground.core.yaml_compat import ensure_pyyaml_collections_abc_compat

try:
    import yaml
except ModuleNotFoundError:
    yaml = None

KIND = "repoground.system_relation_producer_result"
VERSION = "1.0"
EVIDENCE_KIND = "repoground.system_relation_evidence"
EVIDENCE_VERSION = "1.0"
PRODUCER_NAME = "repoground.system_relation_producer"
PRODUCER_VERSION = "1.0"

DEFAULT_MAX_FILES = 512
DEFAULT_MAX_FILE_BYTES = 1_048_576
DEFAULT_MAX_TOTAL_BYTES = 8_388_608
DEFAULT_MAX_CANDIDATE_INDEX_BYTES = 4_194_304
_GIT_TIMEOUT_SECONDS = 10
_SUPPORTED_RELATIONS = (
    "declares_config",
    "declares_schema",
    "references_workflow",
)
_SUPPORTED_SOURCES = (
    "root pyproject.toml first-level [tool.NAME] tables",
    "tracked *.schema.json with a top-level literal $id",
    "tracked .github/workflows/*.yml|*.yaml static local reusable-workflow references",
)
_DOES_NOT_ESTABLISH = (
    "repository_truth_beyond_requested_commit",
    "complete_repository_relation_coverage",
    "runtime_config_effect",
    "schema_conformance",
    "schema_validation_execution",
    "workflow_execution",
    "workflow_validity",
    "runtime_behavior",
    "runtime_correctness",
    "default_activation",
)
_SENSITIVE_PARTS = frozenset(
    {
        ".env",
        "secret",
        "secrets",
        "credential",
        "credentials",
        "private-key",
        "private_key",
        "tokens",
    }
)
_TOOL_TABLE_RE = re.compile(
    r"^(?P<prefix>\s*)\[tool\.(?P<name>[A-Za-z0-9_-]+)\]\s*(?:#.*)?$"
)


class SystemRelationProducerError(ValueError):
    """Raised when the producer request or revision source is unsafe."""


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _commit(value: Any) -> str:
    if not isinstance(value, str):
        raise SystemRelationProducerError("repository_commit must be a string")
    commit = value.strip()
    if len(commit) not in {40, 64} or any(
        character not in "0123456789abcdef" for character in commit
    ):
        raise SystemRelationProducerError(
            "repository_commit must be a lowercase 40- or 64-character digest"
        )
    return commit


def _repository_identity(value: Any) -> str:
    if not isinstance(value, str):
        raise SystemRelationProducerError("repository_identity must be a string")
    identity = value.strip()
    if not identity or len(identity) > 4096 or "\x00" in identity:
        raise SystemRelationProducerError(
            "repository_identity must be non-empty and bounded"
        )
    return identity


def _positive_int(value: Any, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise SystemRelationProducerError(f"{field} must be an integer >= 1")
    return value


def _git_environment() -> dict[str, str]:
    environment = dict(os.environ)
    environment.update(
        {
            "GIT_NO_LAZY_FETCH": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_ASKPASS": "/bin/false",
        }
    )
    return environment


def _git_stdout(
    root: Path,
    arguments: list[str],
    *,
    operation: str,
) -> bytes:
    command = [
        "git",
        "-c",
        "core.pager=cat",
        "-c",
        "core.hooksPath=/dev/null",
        "-c",
        "diff.external=",
        "-c",
        "protocol.file.allow=never",
        "-C",
        str(root),
        *arguments,
    ]
    try:
        completed = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=_GIT_TIMEOUT_SECONDS,
            env=_git_environment(),
        )
    except FileNotFoundError as exc:
        raise SystemRelationProducerError("git executable is unavailable") from exc
    except subprocess.TimeoutExpired as exc:
        raise SystemRelationProducerError(
            f"git {operation} exceeded the bounded timeout"
        ) from exc
    if completed.returncode != 0:
        raise SystemRelationProducerError(f"git {operation} failed")
    return completed.stdout


def _git_stdout_bounded(
    root: Path,
    arguments: list[str],
    *,
    operation: str,
    max_bytes: int,
) -> bytes:
    command = [
        "git",
        "-c",
        "core.pager=cat",
        "-c",
        "core.hooksPath=/dev/null",
        "-c",
        "diff.external=",
        "-c",
        "protocol.file.allow=never",
        "-C",
        str(root),
        *arguments,
    ]
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=_git_environment(),
        )
    except FileNotFoundError as exc:
        raise SystemRelationProducerError("git executable is unavailable") from exc

    deadline = time.monotonic() + _GIT_TIMEOUT_SECONDS
    chunks: list[bytes] = []
    size = 0
    try:
        assert process.stdout is not None
        while True:
            remaining_seconds = deadline - time.monotonic()
            if remaining_seconds <= 0:
                raise subprocess.TimeoutExpired(command, _GIT_TIMEOUT_SECONDS)
            ready, _, _ = select.select(
                [process.stdout], [], [], remaining_seconds
            )
            if not ready:
                raise subprocess.TimeoutExpired(command, _GIT_TIMEOUT_SECONDS)
            chunk = os.read(
                process.stdout.fileno(),
                min(65_536, max_bytes - size + 1),
            )
            if not chunk:
                break
            size += len(chunk)
            if size > max_bytes:
                raise SystemRelationProducerError(
                    f"git {operation} exceeds max_bytes={max_bytes}"
                )
            chunks.append(chunk)
        remaining_seconds = max(0.001, deadline - time.monotonic())
        returncode = process.wait(timeout=remaining_seconds)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        process.wait()
        raise SystemRelationProducerError(
            f"git {operation} exceeded the bounded timeout"
        ) from exc
    except BaseException:
        process.kill()
        process.wait()
        raise
    if returncode != 0:
        raise SystemRelationProducerError(f"git {operation} failed")
    return b"".join(chunks)

def _verify_revision_source(root: Path, commit: str) -> None:
    raw_root = _git_stdout(
        root,
        ["rev-parse", "--show-toplevel"],
        operation="repository-root verification",
    )
    try:
        observed_root = Path(raw_root.decode("utf-8").strip()).resolve(strict=True)
    except (UnicodeDecodeError, OSError) as exc:
        raise SystemRelationProducerError("git repository root is invalid") from exc
    if observed_root != root:
        raise SystemRelationProducerError(
            "repository_root must be the Git repository toplevel"
        )
    object_type = _git_stdout(
        root,
        ["cat-file", "-t", commit],
        operation="commit verification",
    ).strip()
    if object_type != b"commit":
        raise SystemRelationProducerError(
            "repository_commit must identify a local Git commit object"
        )


def _safe_repo_path(relative: str) -> bool:
    parsed = PurePosixPath(relative)
    return bool(
        relative
        and not relative.startswith("/")
        and "\\" not in relative
        and "//" not in relative
        and all(part not in {"", ".", ".."} for part in parsed.parts)
    )


def _sensitive_path(relative: str) -> bool:
    for raw_part in PurePosixPath(relative).parts:
        part = raw_part.casefold()
        stem = part.rsplit(".", 1)[0]
        if part in _SENSITIVE_PARTS or stem in _SENSITIVE_PARTS:
            return True
        if "credential" in part or "private_key" in part or "private-key" in part:
            return True
    return False


def _candidate_kind(relative: str) -> str | None:
    path = PurePosixPath(relative)
    if relative == "pyproject.toml":
        return "pyproject"
    if path.name.endswith(".schema.json"):
        return "schema"
    parts = path.parts
    if (
        len(parts) == 3
        and parts[:2] == (".github", "workflows")
        and path.suffix.casefold() in {".yml", ".yaml"}
    ):
        return "workflow"
    return None


def _omission(
    path: str,
    reason: str,
    *,
    line: int | None = None,
    detail: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {"path": path, "reason": reason}
    if line is not None:
        result["line"] = line
    if detail is not None:
        result["detail"] = detail[:512]
    return result


def _parse_git_candidate(
    raw_entry: bytes,
) -> tuple[tuple[str, str, int, str] | None, dict[str, Any] | None]:
    try:
        metadata, raw_path = raw_entry.split(b"\t", 1)
        mode, object_type, object_id, raw_size = metadata.split()
    except ValueError:
        raise SystemRelationProducerError(
            "git candidate index contained an invalid entry"
        ) from None

    path_fingerprint = hashlib.sha256(raw_path).hexdigest()[:16]
    try:
        relative = raw_path.decode("utf-8")
    except UnicodeDecodeError:
        return None, _omission(
            f"<non-utf8-path:{path_fingerprint}>",
            "non_utf8_path_omitted",
        )
    if not _safe_repo_path(relative):
        return None, _omission(relative, "unsafe_path_omitted")

    candidate_kind = _candidate_kind(relative)
    if candidate_kind is None:
        return None, None
    if _sensitive_path(relative):
        return None, _omission(relative, "sensitive_path_omitted")
    if object_type != b"blob" or mode == b"120000":
        return None, _omission(relative, "non_regular_file_omitted")
    try:
        size = int(raw_size)
        object_id_text = object_id.decode("ascii")
    except (ValueError, UnicodeDecodeError):
        return None, _omission(relative, "git_metadata_invalid")
    return (relative, object_id_text, size, candidate_kind), None


def _git_candidates(
    root: Path,
    *,
    commit: str,
    max_candidate_index_bytes: int,
) -> tuple[
    list[tuple[str, str, int, str]],
    list[dict[str, Any]],
    set[str],
    int,
]:
    payload = _git_stdout_bounded(
        root,
        ["ls-tree", "-r", "-z", "--long", commit],
        operation="candidate enumeration",
        max_bytes=max_candidate_index_bytes,
    )

    candidates: list[tuple[str, str, int, str]] = []
    omissions: list[dict[str, Any]] = []
    available_paths: set[str] = set()
    for raw_entry in payload.split(b"\x00"):
        if not raw_entry:
            continue
        candidate, omission = _parse_git_candidate(raw_entry)
        if omission is not None:
            omissions.append(omission)
        if candidate is not None:
            candidates.append(candidate)
            available_paths.add(candidate[0])

    candidates.sort(key=lambda item: item[0])
    omissions.sort(key=_omission_order)
    return candidates, omissions, available_paths, len(payload)


def _git_blob(root: Path, object_id: str) -> bytes:
    return _git_stdout(
        root,
        ["cat-file", "blob", object_id],
        operation="blob read",
    )


def _line_range(
    line_number: int,
    line: str,
    *,
    start_character: int = 0,
) -> dict[str, int]:
    end_character = len(line.rstrip("\r\n"))
    return {
        "start_line": line_number,
        "start_character": start_character,
        "end_line": line_number,
        "end_character": end_character,
    }


def _raw_record(
    *,
    relation: str,
    subject_kind: str,
    subject_identity: str,
    target_kind: str,
    target_identity: str,
    path: str,
    source_kind: str,
    source_range: Mapping[str, int],
    evidence_class: str,
    contract_identity: Mapping[str, str] | None,
) -> dict[str, Any]:
    return {
        "relation": relation,
        "subject": {"kind": subject_kind, "identity": subject_identity},
        "target": {"kind": target_kind, "identity": target_identity},
        "source": {
            "path": path,
            "kind": source_kind,
            "range": dict(source_range),
        },
        "evidence_class": evidence_class,
        "contract_identity": (
            dict(contract_identity) if contract_identity is not None else None
        ),
    }


def _scan_pyproject(
    text: str,
    *,
    relative: str,
    repository_identity: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if tomllib is None:
        return [], [_omission(relative, "toml_parser_unavailable")]
    try:
        parsed = tomllib.loads(text)
    except (tomllib.TOMLDecodeError, ValueError) as exc:
        return [], [_omission(relative, "invalid_toml", detail=str(exc))]
    tool_table = parsed.get("tool") if isinstance(parsed, Mapping) else None
    if not isinstance(tool_table, Mapping):
        return [], []

    records: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for line_number, line in enumerate(text.splitlines(), start=1):
        match = _TOOL_TABLE_RE.match(line)
        if match is None:
            continue
        name = match.group("name")
        if name in seen_names or name not in tool_table:
            continue
        seen_names.add(name)
        contract_id = f"pyproject.tool.{name}"
        records.append(
            _raw_record(
                relation="declares_config",
                subject_kind="repository",
                subject_identity=repository_identity,
                target_kind="config_contract",
                target_identity=contract_id,
                path=relative,
                source_kind="manifest",
                source_range=_line_range(
                    line_number,
                    line,
                    start_character=len(match.group("prefix")),
                ),
                evidence_class="config_declaration",
                contract_identity={
                    "kind": "config",
                    "id": contract_id,
                    "version": "unversioned",
                },
            )
        )
    return records, []


def _json_depths_by_offset(text: str) -> list[int]:
    depths: list[int] = [0] * len(text)
    depth = 0
    in_string = False
    escaped = False
    for index, character in enumerate(text):
        depths[index] = depth
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
        else:
            if character == '"':
                in_string = True
            elif character in "{[":
                depth += 1
            elif character in "}]":
                depth = max(0, depth - 1)
    return depths


def _top_level_json_key_range(
    text: str,
    *,
    key: str,
    expected_value: str,
) -> dict[str, int] | None:
    depths = _json_depths_by_offset(text)
    pattern = re.compile(
        rf'"{re.escape(key)}"\s*:\s*(?P<value>"(?:\\.|[^"\\])*")'
    )
    for match in pattern.finditer(text):
        if match.start() >= len(depths) or depths[match.start()] != 1:
            continue
        try:
            observed = json.loads(match.group("value"))
        except json.JSONDecodeError:
            continue
        if observed != expected_value:
            continue
        line_number = text.count("\n", 0, match.start()) + 1
        line_start = text.rfind("\n", 0, match.start()) + 1
        line_end = text.find("\n", match.start())
        if line_end < 0:
            line_end = len(text)
        line = text[line_start:line_end]
        return _line_range(
            line_number,
            line,
            start_character=match.start() - line_start,
        )
    return None


class _JSONObjectPairs(list):
    pass


def _scan_schema(
    text: str,
    *,
    relative: str,
    repository_identity: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    try:
        parsed = json.loads(text, object_pairs_hook=_JSONObjectPairs)
    except json.JSONDecodeError as exc:
        return [], [_omission(relative, "invalid_json_schema", detail=str(exc))]
    if not isinstance(parsed, _JSONObjectPairs):
        return [], [_omission(relative, "schema_root_not_object")]

    schema_ids = [value for key, value in parsed if key == "$id"]
    if len(schema_ids) > 1:
        return [], [_omission(relative, "schema_id_ambiguous_duplicate")]
    if not schema_ids or not isinstance(schema_ids[0], str) or not schema_ids[0].strip():
        return [], [_omission(relative, "schema_id_missing_or_nonliteral")]
    schema_id = schema_ids[0].strip()
    source_range = _top_level_json_key_range(
        text,
        key="$id",
        expected_value=schema_id,
    )
    if source_range is None:
        return [], [_omission(relative, "schema_id_range_unresolved")]
    record = _raw_record(
        relation="declares_schema",
        subject_kind="repository",
        subject_identity=repository_identity,
        target_kind="schema_contract",
        target_identity=schema_id,
        path=relative,
        source_kind="schema_file",
        source_range=source_range,
        evidence_class="schema_declaration",
        contract_identity={
            "kind": "schema",
            "id": schema_id,
            "version": "unversioned",
        },
    )
    return [record], []

def _workflow_target(value: str) -> str | None:
    if not value.startswith("./.github/workflows/"):
        return None
    relative = value[2:]
    path = PurePosixPath(relative)
    if (
        path.suffix.casefold() not in {".yml", ".yaml"}
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        return None
    return path.as_posix()


def _yaml_mapping_entries(node: Any, key: str) -> list[tuple[Any, Any]]:
    if getattr(node, "id", None) != "mapping":
        return []
    return [
        (key_node, value_node)
        for key_node, value_node in node.value
        if getattr(key_node, "id", None) == "scalar"
        and key_node.value == key
    ]


def _workflow_job_uses_entry(
    job_node: Any,
    *,
    relative: str,
) -> tuple[tuple[int, int, str] | None, dict[str, Any] | None]:
    uses_entries = _yaml_mapping_entries(job_node, "uses")
    if len(uses_entries) > 1:
        line = uses_entries[0][0].start_mark.line + 1
        return None, _omission(
            relative, "duplicate_workflow_uses_key", line=line
        )
    if not uses_entries:
        return None, None
    key_node, value_node = uses_entries[0]
    line = key_node.start_mark.line + 1
    if (
        getattr(value_node, "id", None) != "scalar"
        or value_node.start_mark.line != key_node.start_mark.line
        or getattr(value_node, "style", None) in {"|", ">"}
    ):
        return None, _omission(
            relative, "ambiguous_workflow_reference", line=line
        )
    return (
        line,
        key_node.start_mark.column,
        str(value_node.value).strip(),
    ), None


def _workflow_uses_entries(
    text: str,
    *,
    relative: str,
) -> tuple[list[tuple[int, int, str]], list[dict[str, Any]]]:
    if yaml is None:
        return [], [_omission(relative, "yaml_parser_unavailable")]
    ensure_pyyaml_collections_abc_compat()
    try:
        document = yaml.compose(text)
    except yaml.YAMLError as exc:
        return [], [_omission(relative, "invalid_workflow_yaml", detail=str(exc))]
    if document is None:
        return [], []

    jobs_entries = _yaml_mapping_entries(document, "jobs")
    if len(jobs_entries) > 1:
        return [], [_omission(relative, "duplicate_workflow_jobs_key")]
    if not jobs_entries:
        return [], []
    jobs_node = jobs_entries[0][1]
    if getattr(jobs_node, "id", None) != "mapping":
        return [], [_omission(relative, "workflow_jobs_not_mapping")]

    entries: list[tuple[int, int, str]] = []
    omissions: list[dict[str, Any]] = []
    for _job_key, job_node in jobs_node.value:
        entry, omission = _workflow_job_uses_entry(
            job_node, relative=relative
        )
        if entry is not None:
            entries.append(entry)
        if omission is not None:
            omissions.append(omission)
    entries.sort()
    omissions.sort(key=_omission_order)
    return entries, omissions


def _scan_workflow(
    text: str,
    *,
    relative: str,
    available_paths: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    records: list[dict[str, Any]] = []
    entries, omissions = _workflow_uses_entries(text, relative=relative)
    lines = text.splitlines()
    for line_number, start_character, value in entries:
        if "${{" in value:
            omissions.append(
                _omission(relative, "dynamic_workflow_reference", line=line_number)
            )
            continue
        target = _workflow_target(value)
        if target is None:
            if ".github/workflows" in value:
                omissions.append(
                    _omission(relative, "unsupported_workflow_reference", line=line_number)
                )
            continue
        if target not in available_paths:
            omissions.append(
                _omission(
                    relative,
                    "workflow_target_missing",
                    line=line_number,
                    detail=target,
                )
            )
            continue
        line = lines[line_number - 1]
        records.append(
            _raw_record(
                relation="references_workflow",
                subject_kind="workflow",
                subject_identity=relative,
                target_kind="workflow",
                target_identity=target,
                path=relative,
                source_kind="workflow",
                source_range=_line_range(
                    line_number,
                    line,
                    start_character=start_character,
                ),
                evidence_class="workflow_reference",
                contract_identity=None,
            )
        )
    omissions.sort(key=_omission_order)
    return records, omissions

def _record_order(record: Mapping[str, Any]) -> bytes:
    return _canonical_bytes(record)


def _omission_order(item: Mapping[str, Any]) -> tuple[str, str, int, str]:
    return (
        str(item.get("path", "")),
        str(item.get("reason", "")),
        int(item.get("line", 0) or 0),
        str(item.get("detail", "")),
    )



def _candidate_text(
    root: Path,
    candidate: tuple[str, str, int, str],
    *,
    scanned_bytes: int,
    max_file_bytes: int,
    max_total_bytes: int,
) -> tuple[str | None, dict[str, Any] | None, int]:
    relative, object_id, size, _candidate_kind_value = candidate
    if size > max_file_bytes:
        return None, _omission(relative, "file_too_large", detail=str(size)), 0
    if scanned_bytes + size > max_total_bytes:
        return (
            None,
            _omission(relative, "total_byte_budget_exhausted", detail=str(size)),
            0,
        )
    try:
        payload = _git_blob(root, object_id)
    except SystemRelationProducerError:
        return None, _omission(relative, "git_blob_read_failed"), 0
    bytes_read = len(payload)
    if bytes_read != size:
        return None, _omission(relative, "git_blob_size_mismatch"), bytes_read
    try:
        return payload.decode("utf-8"), None, bytes_read
    except UnicodeDecodeError:
        return None, _omission(relative, "invalid_utf8"), bytes_read

def _scan_candidate_text(
    text: str,
    candidate: tuple[str, str, int, str],
    *,
    repository_identity: str,
    available_paths: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    relative, _object_id, _size, candidate_kind = candidate
    if candidate_kind == "pyproject":
        return _scan_pyproject(
            text,
            relative=relative,
            repository_identity=repository_identity,
        )
    if candidate_kind == "schema":
        return _scan_schema(
            text,
            relative=relative,
            repository_identity=repository_identity,
        )
    return _scan_workflow(
        text,
        relative=relative,
        available_paths=available_paths,
    )

def _extend_records_bounded(
    records: list[dict[str, Any]],
    found: list[dict[str, Any]],
    *,
    relative: str,
    omissions: list[dict[str, Any]],
) -> bool:
    remaining = MAX_EVIDENCE_RECORDS - len(records)
    if len(found) <= remaining:
        records.extend(found)
        return False
    records.extend(found[:remaining])
    omissions.append(
        _omission(
            relative,
            "record_budget_exhausted",
            detail=f"omitted_record_count={len(found) - remaining}",
        )
    )
    return True


def collect_system_relation_evidence(
    repository_root: str | Path,
    *,
    repository_identity: str,
    repository_commit: str,
    max_files: int = DEFAULT_MAX_FILES,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
    max_candidate_index_bytes: int = DEFAULT_MAX_CANDIDATE_INDEX_BYTES,
) -> dict[str, Any]:
    """Collect bounded static relation evidence from one exact Git commit."""
    identity = _repository_identity(repository_identity)
    commit = _commit(repository_commit)
    max_files = _positive_int(max_files, field="max_files")
    max_file_bytes = _positive_int(max_file_bytes, field="max_file_bytes")
    max_total_bytes = _positive_int(max_total_bytes, field="max_total_bytes")
    max_candidate_index_bytes = _positive_int(
        max_candidate_index_bytes,
        field="max_candidate_index_bytes",
    )

    root = Path(repository_root).expanduser()
    try:
        root = root.resolve(strict=True)
    except OSError as exc:
        raise SystemRelationProducerError(
            f"repository_root must resolve to an existing directory: {exc}"
        ) from exc
    if not root.is_dir():
        raise SystemRelationProducerError("repository_root must be a directory")

    _verify_revision_source(root, commit)
    candidates, omissions, available_paths, candidate_index_bytes = _git_candidates(
        root,
        commit=commit,
        max_candidate_index_bytes=max_candidate_index_bytes,
    )
    records: list[dict[str, Any]] = []
    scanned_files = 0
    scanned_bytes = 0
    considered_candidates = 0

    for index, candidate in enumerate(candidates):
        relative = candidate[0]
        if index >= max_files:
            remaining = len(candidates) - index
            omissions.append(
                _omission(
                    relative,
                    "file_budget_exhausted",
                    detail=(
                        f"remaining_candidate_count={remaining}"
                        if remaining > 1
                        else None
                    ),
                )
            )
            break
        considered_candidates += 1
        text, omission, bytes_read = _candidate_text(
            root,
            candidate,
            scanned_bytes=scanned_bytes,
            max_file_bytes=max_file_bytes,
            max_total_bytes=max_total_bytes,
        )
        if bytes_read or text is not None:
            scanned_files += 1
        scanned_bytes += bytes_read
        if omission is not None:
            omissions.append(omission)
            continue
        assert text is not None
        found, skipped = _scan_candidate_text(
            text,
            candidate,
            repository_identity=identity,
            available_paths=available_paths,
        )
        omissions.extend(skipped)
        if _extend_records_bounded(
            records,
            found,
            relative=relative,
            omissions=omissions,
        ):
            break

    records.sort(key=_record_order)
    omissions.sort(key=_omission_order)
    evidence = {
        "kind": EVIDENCE_KIND,
        "version": EVIDENCE_VERSION,
        "producer": {"name": PRODUCER_NAME, "version": PRODUCER_VERSION},
        "records": records,
    }
    evidence_sha256 = _canonical_sha256(evidence)
    overlay = normalize_system_relation_evidence(
        evidence,
        evidence_sha256=evidence_sha256,
        repository_commit=commit,
    )
    revision_binding = {
        "mode": "git_commit_object",
        "repository_commit": commit,
        "verified": True,
    }
    return {
        "kind": KIND,
        "version": VERSION,
        "repository": {"identity": identity, "commit": commit},
        "revision_binding": revision_binding,
        "producer_contract": {
            "supported_sources": list(_SUPPORTED_SOURCES),
            "supported_relations": list(_SUPPORTED_RELATIONS),
            "dynamic_or_ambiguous_references": "omitted_with_reason",
            "repository_source": "git_object_database",
            "working_tree_reads": False,
            "network_access": False,
            "secret_file_scanning": False,
        },
        "evidence_sha256": evidence_sha256,
        "evidence": evidence,
        "overlay": overlay,
        "omissions": omissions,
        "scan": {
            "candidate_count": len(candidates),
            "considered_candidate_count": considered_candidates,
            "scanned_file_count": scanned_files,
            "scanned_bytes": scanned_bytes,
            "candidate_index_bytes": candidate_index_bytes,
            "limits": {
                "max_files": max_files,
                "max_file_bytes": max_file_bytes,
                "max_total_bytes": max_total_bytes,
                "max_candidate_index_bytes": max_candidate_index_bytes,
                "max_records": MAX_EVIDENCE_RECORDS,
            },
        },
        "absence_semantics": (
            "Missing records mean only that this bounded producer did not establish "
            "a supported static relation in the requested commit; they do not establish absence."
        ),
        "does_not_establish": list(_DOES_NOT_ESTABLISH),
    }


__all__ = [
    "SystemRelationProducerError",
    "collect_system_relation_evidence",
]
