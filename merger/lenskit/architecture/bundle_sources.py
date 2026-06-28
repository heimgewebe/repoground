from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .entrypoints import generate_entrypoints_document
from .import_graph import generate_import_graph_document


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


def ensure_bundle_graph_sources(
    *,
    base_path: Path,
    repo_summaries: Sequence[Mapping[str, Any]] | None,
    run_id: str,
    canonical_dump_index_sha256: str,
    generated_at: str,
) -> BundleGraphSources:
    """Create bundle-bound graph sources when identity is unambiguous.

    Existing source pairs remain authoritative inputs for backwards compatibility.
    A partial pair is left untouched so the compiler can fail closed. Automatic
    production is deliberately limited to one repository because the current
    Graph Index key space addresses files by path only and cannot distinguish
    identical paths from multiple repositories.
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
    repo_root = Path(summary["root"])
    repo_name = str(summary["name"])

    graph = generate_import_graph_document(
        repo_root,
        run_id,
        canonical_dump_index_sha256,
    )
    graph["generated_at"] = generated_at
    for node in graph.get("nodes", []):
        if node.get("kind") == "file":
            node["repo"] = repo_name

    entrypoints = generate_entrypoints_document(
        repo_root,
        run_id,
        canonical_dump_index_sha256,
    )

    _write_json_atomic(graph_path, graph)
    _write_json_atomic(entrypoints_path, entrypoints)
    return BundleGraphSources(graph_path, entrypoints_path, "produced")
