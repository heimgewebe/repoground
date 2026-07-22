from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .entrypoints import generate_entrypoints_document
from .import_graph import generate_import_graph_document


_GRAPH_SOURCE_SUFFIXES = frozenset(
    {
        ".js", ".json", ".jsx", ".md", ".py", ".rs", ".sql",
        ".svelte", ".toml", ".ts", ".tsx", ".yaml", ".yml",
    }
)


class BundleGraphSourceError(RuntimeError):
    """Graph source production failed before a coherent pair was published."""


@dataclass(frozen=True)
class BundleGraphSources:
    graph_path: Path
    entrypoints_path: Path
    status: str
    reason: str | None = None

    @property
    def produced(self) -> bool:
        return self.status == "produced"


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


def _eligible_source_paths(
    chunk_index_path: Path,
    repo_name: str,
    *,
    suffixes: frozenset[str],
) -> tuple[str, ...]:
    """Return full-contact source paths for the requested bounded suffix set."""

    eligibility: dict[str, bool] = {}
    try:
        with chunk_index_path.open(encoding="utf-8") as handle:
            for line_number, raw_line in enumerate(handle, start=1):
                if not raw_line.strip():
                    continue
                try:
                    item = json.loads(raw_line)
                except json.JSONDecodeError as exc:
                    raise BundleGraphSourceError(
                        f"invalid chunk index JSON at line {line_number}"
                    ) from exc
                if not isinstance(item, Mapping):
                    raise BundleGraphSourceError(
                        f"invalid chunk index record at line {line_number}"
                    )

                item_repo = item.get("repo") or item.get("repo_id")
                if item_repo != repo_name:
                    continue
                raw_path = item.get("path") or item.get("source_file")
                if not isinstance(raw_path, str):
                    continue

                rel_path = Path(raw_path)
                if (
                    rel_path.suffix.lower() not in suffixes
                    or rel_path.name.lower().endswith(".graph.json")
                ):
                    continue
                if rel_path.is_absolute() or ".." in rel_path.parts:
                    raise BundleGraphSourceError(
                        f"unsafe chunk source path: {raw_path!r}"
                    )
                normalized = rel_path.as_posix()
                source_range = item.get("source_range")
                source_declared = (
                    isinstance(source_range, Mapping)
                    and source_range.get("status") == "declared"
                )
                full_contact = (
                    item.get("source_status", "full") == "full"
                    and not bool(item.get("truncated", False))
                    and source_declared
                )
                eligibility[normalized] = eligibility.get(normalized, True) and full_contact
    except OSError as exc:
        raise BundleGraphSourceError(
            f"chunk index is unreadable: {chunk_index_path}"
        ) from exc

    return tuple(sorted(path for path, allowed in eligibility.items() if allowed))


def _eligible_python_paths(chunk_index_path: Path, repo_name: str) -> tuple[str, ...]:
    """Return full-contact Python paths from the retrieval source surface."""

    return _eligible_source_paths(
        chunk_index_path,
        repo_name,
        suffixes=frozenset({".py"}),
    )


def _eligible_graph_paths(chunk_index_path: Path, repo_name: str) -> tuple[str, ...]:
    """Return full-contact paths supported by the architecture inventory."""

    return _eligible_source_paths(
        chunk_index_path,
        repo_name,
        suffixes=_GRAPH_SOURCE_SUFFIXES,
    )


def _materialize_selected_source_tree(
    repo_root: Path,
    selected_paths: Sequence[str],
    destination_root: Path,
) -> None:
    resolved_root = repo_root.resolve()
    for raw_path in selected_paths:
        rel_path = Path(raw_path)
        source = (repo_root / rel_path).resolve()
        try:
            source.relative_to(resolved_root)
        except ValueError as exc:
            raise BundleGraphSourceError(
                f"selected source escapes repository root: {raw_path!r}"
            ) from exc
        if not source.is_file():
            raise BundleGraphSourceError(
                f"selected source file does not exist: {raw_path!r}"
            )
        destination = destination_root / rel_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)


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
    graph_exists = graph_path.exists()
    entrypoints_exist = entrypoints_path.exists()

    if graph_exists and entrypoints_exist:
        return BundleGraphSources(graph_path, entrypoints_path, "existing")
    if graph_exists or entrypoints_exist:
        return BundleGraphSources(
            graph_path,
            entrypoints_path,
            "partial",
            "exactly one graph source artifact exists",
        )

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
        selected_paths = _eligible_graph_paths(chunk_index_path, repo_name)
        with tempfile.TemporaryDirectory(prefix="lenskit-graph-sources-") as tmp:
            selected_root = Path(tmp)
            _materialize_selected_source_tree(
                repo_root,
                selected_paths,
                selected_root,
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

        graph["generated_at"] = generated_at
        for node in graph.get("nodes", []):
            if node.get("kind") == "file":
                node["repo"] = repo_name

        _write_json_atomic(graph_path, graph)
        _write_json_atomic(entrypoints_path, entrypoints)
    except BundleGraphSourceError:
        graph_path.unlink(missing_ok=True)
        entrypoints_path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        graph_path.unlink(missing_ok=True)
        entrypoints_path.unlink(missing_ok=True)
        raise BundleGraphSourceError(
            f"failed to produce bundle-bound graph sources: {exc}"
        ) from exc

    reason = None if selected_paths else "no eligible full-contact graph sources"
    return BundleGraphSources(graph_path, entrypoints_path, "produced", reason)
