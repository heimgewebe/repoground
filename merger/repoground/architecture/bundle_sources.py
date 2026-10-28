from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .entrypoints import generate_entrypoints_document
from .import_graph import (
    _HARD_MAX_GRAPH_FILES, _HARD_MAX_GRAPH_SOURCE_BYTES,
    _graph_inventory_language, generate_import_graph_document,
)
from .relationship_projection import generate_relationship_document


class BundleGraphSourceError(RuntimeError):
    """Graph source production failed before coherent artifacts were published."""


@dataclass(frozen=True)
class BundleGraphSources:
    graph_path: Path
    entrypoints_path: Path
    status: str
    reason: str | None = None
    relationships_path: Path | None = None

    @property
    def produced(self) -> bool:
        return self.status == "produced"


_MAX_CHUNK_INDEX_BYTES = 256 * 1024 * 1024
_HEX = frozenset("0123456789abcdef")


@dataclass(frozen=True)
class _SourceChunk:
    start_byte: int
    end_byte: int
    sha256: str
    blob_sha1: str


def _is_digest(value: Any, length: int) -> bool:
    return isinstance(value, str) and len(value) == length and not set(value).difference(_HEX)


def _normalised_source_bytes(data: bytes) -> bytes:
    """Exactly the UTF-8/replacement/universal-newline view of read_smart_content."""
    text = data.decode("utf-8", errors="replace")
    return text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")


def _contact_hash_matches(item: Mapping[str, Any], digest: str) -> bool:
    canonical, inline = item.get("canonical_range"), item.get("content")
    if canonical is not None and (
        not isinstance(canonical, Mapping) or canonical.get("content_sha256") != digest
    ):
        return False
    if inline is not None and (
        not isinstance(inline, str) or hashlib.sha256(inline.encode("utf-8")).hexdigest() != digest
    ):
        return False
    if item.get("sha256", digest) != digest or item.get("content_sha256", digest) != digest:
        return False
    return canonical is not None or inline is not None


def _source_chunk(item: Mapping[str, Any], path: str, repo_name: str) -> _SourceChunk:
    source = item["source_range"]
    start, end = source.get("start_byte"), source.get("end_byte")
    digest, blob = source.get("content_sha256"), source.get("git_blob_sha1")
    if not (
        source.get("status") == "declared"
        and source.get("file_path") == path and source.get("repo_id") == repo_name
        and source.get("git_blob_sha1_basis") == "source_worktree_file_content"
        and type(start) is int and type(end) is int
        and 0 <= start < end <= _HARD_MAX_GRAPH_SOURCE_BYTES
        and _is_digest(digest, 64) and _is_digest(blob, 40)
    ):
        raise BundleGraphSourceError(f"source contact binding is incomplete or invalid: {path!r}")
    if not _contact_hash_matches(item, digest):
        raise BundleGraphSourceError(f"source contact differs from bundle content: {path!r}")
    return _SourceChunk(start, end, digest, blob)


def _chunk_rows(chunk_index_path: Path):
    remaining = _MAX_CHUNK_INDEX_BYTES
    line_number = 0
    try:
        with chunk_index_path.open("rb") as handle:
            while True:
                raw_line = handle.readline(remaining + 1)
                if not raw_line:
                    break
                if len(raw_line) > remaining:
                    raise BundleGraphSourceError("chunk index exceeds bounded source-contact limit")
                remaining -= len(raw_line)
                line_number += 1
                if not raw_line.strip():
                    continue
                try:
                    item = json.loads(raw_line.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise BundleGraphSourceError(
                        f"invalid chunk index JSON at line {line_number}"
                    ) from exc
                if not isinstance(item, Mapping):
                    raise BundleGraphSourceError(f"invalid chunk index record at line {line_number}")
                yield item
    except OSError as exc:
        raise BundleGraphSourceError(f"chunk index is unreadable: {chunk_index_path}") from exc


def _read_source_buffer(source: Path, limit: int) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        with os.fdopen(os.open(source, flags), "rb") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
                raise BundleGraphSourceError(f"selected source exceeds regular-file byte limit: {source}")
            data = handle.read(limit + 1)
    except OSError as exc:
        raise BundleGraphSourceError(f"selected source cannot be read safely: {source}") from exc
    if len(data) > limit:
        raise BundleGraphSourceError(f"selected source grew beyond byte limit: {source}")
    return data


def _verify_source_buffer(path: str, data: bytes, chunks: Sequence[_SourceChunk]) -> None:
    if not chunks:
        raise BundleGraphSourceError(f"source contact is missing: {path!r}")
    header = f"blob {len(data)}\0".encode("utf-8")
    blob = hashlib.sha1(header + data, usedforsecurity=False).hexdigest()
    normalized = _normalised_source_bytes(data)
    view = memoryview(normalized)
    cursor = 0
    for chunk in sorted(chunks, key=lambda item: item.start_byte):
        if chunk.blob_sha1 != blob or chunk.start_byte != cursor or chunk.end_byte > len(normalized):
            raise BundleGraphSourceError(f"source bytes or complete chunk coverage changed: {path!r}")
        if hashlib.sha256(view[chunk.start_byte:chunk.end_byte]).hexdigest() != chunk.sha256:
            raise BundleGraphSourceError(f"source chunk content changed: {path!r}")
        cursor = chunk.end_byte
    if cursor != len(normalized):
        raise BundleGraphSourceError(f"source contact does not cover the complete file: {path!r}")


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            delete=False,
            dir=str(path.parent),
            prefix=f".{path.name}.",
            suffix=".tmp",
        ) as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
            tmp_path = Path(handle.name)
        os.replace(tmp_path, path)
    finally:
        if tmp_path is not None and tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


def _supported_graph_source(path: Path, suffixes: frozenset[str] | None) -> bool:
    if suffixes is None:
        return _graph_inventory_language(path) is not None
    return path.suffix.lower() in suffixes


def _write_graph_source_set(documents: Sequence[tuple[Path, Mapping[str, Any]]]) -> None:
    written: list[Path] = []
    try:
        for path, document in documents:
            _write_json_atomic(path, document)
            written.append(path)
    except Exception:
        for path in written:
            path.unlink(missing_ok=True)
        raise


def _eligible_source_paths(
    chunk_index_path: Path, repo_name: str, *,
    suffixes: frozenset[str] | None = None,
    source_ranges: dict[str, list[_SourceChunk]] | None = None,
) -> tuple[str, ...]:
    """Select full-contact sources and capture their byte bindings in one pass."""
    eligibility: dict[str, bool] = {}
    for item in _chunk_rows(chunk_index_path):
        if (item.get("repo") or item.get("repo_id")) != repo_name:
            continue
        raw_path = item.get("path") or item.get("source_file")
        if not isinstance(raw_path, str):
            continue
        rel_path = Path(raw_path)
        if not _supported_graph_source(rel_path, suffixes) or rel_path.name.lower().endswith(".graph.json"):
            continue
        if rel_path.is_absolute() or ".." in rel_path.parts:
            raise BundleGraphSourceError(f"unsafe chunk source path: {raw_path!r}")
        normalized = rel_path.as_posix()
        source_range = item.get("source_range")
        full_contact = (
            item.get("source_status", "full") == "full"
            and not bool(item.get("truncated", False))
            and isinstance(source_range, Mapping) and source_range.get("status") == "declared"
        )
        eligibility[normalized] = eligibility.get(normalized, True) and full_contact
        if source_ranges is not None and full_contact:
            source_ranges.setdefault(normalized, []).append(_source_chunk(item, normalized, repo_name))
    return tuple(sorted(path for path, allowed in eligibility.items() if allowed))


def _eligible_python_paths(chunk_index_path: Path, repo_name: str) -> tuple[str, ...]:
    """Return full-contact Python paths from the retrieval source surface."""

    return _eligible_source_paths(
        chunk_index_path,
        repo_name,
        suffixes=frozenset({".py"}),
    )


def _eligible_graph_paths(
    chunk_index_path: Path, repo_name: str, *,
    source_ranges: dict[str, list[_SourceChunk]] | None = None,
) -> tuple[str, ...]:
    """Return full-contact paths supported by the architecture inventory."""
    return _eligible_source_paths(chunk_index_path, repo_name, source_ranges=source_ranges)


def _materialize_selected_source_tree(
    repo_root: Path, selected_paths: Sequence[str], destination_root: Path, *,
    source_ranges: Mapping[str, Sequence[_SourceChunk]],
) -> None:
    if len(selected_paths) > _HARD_MAX_GRAPH_FILES:
        raise BundleGraphSourceError("selected source file limit exceeded")
    resolved_root = repo_root.resolve()
    remaining = _HARD_MAX_GRAPH_SOURCE_BYTES
    for raw_path in selected_paths:
        rel_path = Path(raw_path)
        source = (repo_root / rel_path).resolve()
        try:
            source.relative_to(resolved_root)
        except ValueError as exc:
            raise BundleGraphSourceError(f"selected source escapes repository root: {raw_path!r}") from exc
        data = _read_source_buffer(source, remaining)
        _verify_source_buffer(raw_path, data, source_ranges.get(raw_path, ()))
        remaining -= len(data)
        destination = destination_root / rel_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)


def _existing_graph_sources(
    graph_path: Path, entrypoints_path: Path, relationships_path: Path,
) -> BundleGraphSources | None:
    graph_exists = graph_path.exists()
    entrypoints_exist = entrypoints_path.exists()
    if graph_exists and entrypoints_exist:
        return BundleGraphSources(
            graph_path, entrypoints_path, "existing",
            "caller-supplied graph pair; relationship projection unavailable",
        )
    if graph_exists or entrypoints_exist:
        return BundleGraphSources(
            graph_path, entrypoints_path, "partial",
            "exactly one graph source artifact exists",
        )
    if relationships_path.exists():
        return BundleGraphSources(
            graph_path, entrypoints_path, "partial",
            "relationship source exists without a coherent graph source pair",
        )
    return None


def ensure_bundle_graph_sources(
    *,
    base_path: Path,
    chunk_index_path: Path,
    repo_summaries: Sequence[Mapping[str, Any]] | None,
    run_id: str,
    canonical_dump_index_sha256: str,
    generated_at: str,
    source_roots: Sequence[str] | None = None,
) -> BundleGraphSources:
    """Create a coherent source pair from the bundle retrieval surface.

    Existing source pairs remain caller-supplied inputs for backwards
    compatibility. A partial pair is left untouched so the compiler can fail
    closed. Automatic production is limited to one repository because the
    current Graph Index key space addresses files by path only.
    """

    graph_path = base_path.with_suffix(".architecture_graph.json")
    entrypoints_path = base_path.with_suffix(".entrypoints.json")
    relationships_path = base_path.with_suffix(".relationship_projection.json")
    existing = _existing_graph_sources(graph_path, entrypoints_path, relationships_path)
    if existing is not None:
        return existing

    summaries = list(repo_summaries or ())
    if not summaries:
        return BundleGraphSources(
            graph_path,
            entrypoints_path,
            "skipped",
            "repository context unavailable",
        )
    if len(summaries) != 1:
        return BundleGraphSources(
            graph_path,
            entrypoints_path,
            "skipped",
            "multi-repo graph identity is out of scope",
        )

    summary = summaries[0]
    try:
        repo_root = Path(summary["root"])
        repo_name = str(summary["name"])
        explicit_source_roots = tuple(
            source_roots
            if source_roots is not None
            else summary.get("source_roots", ())
        )
        source_ranges: dict[str, list[_SourceChunk]] = {}
        selected_paths = _eligible_graph_paths(chunk_index_path, repo_name, source_ranges=source_ranges)
        with tempfile.TemporaryDirectory(prefix="lenskit-graph-sources-") as tmp:
            selected_root = Path(tmp)
            _materialize_selected_source_tree(
                repo_root,
                selected_paths,
                selected_root,
                source_ranges=source_ranges,
            )
            graph = generate_import_graph_document(
                selected_root,
                run_id,
                canonical_dump_index_sha256,
                source_roots=explicit_source_roots,
            )
            entrypoints = generate_entrypoints_document(
                selected_root,
                run_id,
                canonical_dump_index_sha256,
            )
            relationships = generate_relationship_document(
                selected_root, run_id, canonical_dump_index_sha256,
                architecture_graph=graph,
            )

        graph["generated_at"] = generated_at
        for node in graph.get("nodes", []):
            if node.get("kind") == "file":
                node["repo"] = repo_name

        _write_graph_source_set((
            (graph_path, graph),
            (entrypoints_path, entrypoints),
            (relationships_path, relationships),
        ))
    except BundleGraphSourceError:
        raise
    except Exception as exc:
        raise BundleGraphSourceError(
            f"failed to produce bundle-bound graph sources: {exc}"
        ) from exc

    reason = None if selected_paths else "no eligible full-contact graph sources"
    return BundleGraphSources(
        graph_path, entrypoints_path, "produced", reason,
        relationships_path=relationships_path,
    )
