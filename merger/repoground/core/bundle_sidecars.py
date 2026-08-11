"""Deterministic emission of bundle sidecar navigation artifacts.

A sidecar is a secondary artifact written next to the bundle manifest: symbol
index, call graph, optional language structure, lens/concept/relation cards and
PR delta evidence. Each writer is pure with respect to the merge run: it
receives the manifest path and the data it needs, writes at most one file and
returns its path or ``None``.

The module depends only on :mod:`merger.repoground.core.artifact_io` and on the
individual producers, never on :mod:`merger.repoground.core.merge`, so the
bundle pipeline can import it without an import cycle.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from .artifact_io import (
    compute_file_sha256,
    is_sha256_digest,
    write_json_lines,
    write_text_atomic,
)
from .snapshot_provenance import repository_snapshot_provenance

_MANIFEST_SUFFIX = ".bundle.manifest.json"


def sidecar_path(base_manifest_path: Path, suffix: str) -> Path:
    """Return a sidecar path derived from one canonical bundle manifest name.

    Refuse malformed bases instead of letting ``str.replace`` return the
    original path and allowing a secondary artifact to overwrite its manifest.
    """

    if not base_manifest_path.name.endswith(_MANIFEST_SUFFIX):
        raise ValueError(
            "sidecar base must end with "
            f"{_MANIFEST_SUFFIX!r}: {base_manifest_path.name!r}"
        )
    stem = base_manifest_path.name[: -len(_MANIFEST_SUFFIX)]
    return base_manifest_path.with_name(f"{stem}{suffix}")


def _single_repo_root(
    repo_summaries: List[Dict[str, Any]],
    final_dump_index: Optional[Path],
) -> Optional[Path]:
    """Return the repository root for single-repo bundles with a dump index."""

    if len(repo_summaries) != 1:
        return None
    if final_dump_index is None or not final_dump_index.exists():
        return None
    repo_root = repo_summaries[0].get("root")
    if repo_root is None:
        return None
    return Path(repo_root)


def _write_provenance_document(
    *,
    base_manifest_path: Path,
    suffix: str,
    document: Dict[str, Any],
) -> Path:
    out_path = sidecar_path(base_manifest_path, suffix)
    write_text_atomic(
        out_path,
        json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
    )
    return out_path


def write_python_symbol_index_json(
    *,
    base_manifest_path: Path,
    repo_summaries: List[Dict[str, Any]],
    final_dump_index: Optional[Path],
    run_id: str,
) -> Optional[Path]:
    """Emit Python Symbol Index v1 for single-repo bundles as navigation only."""

    repo_root = _single_repo_root(repo_summaries, final_dump_index)
    if repo_root is None:
        return None
    canonical_sha = compute_file_sha256(final_dump_index)
    if not is_sha256_digest(canonical_sha):
        return None
    from merger.repoground.architecture.symbol_index import (
        generate_symbol_index_document,
    )

    return _write_provenance_document(
        base_manifest_path=base_manifest_path,
        suffix=".python_symbol_index.json",
        document=generate_symbol_index_document(repo_root, run_id, canonical_sha),
    )


def write_python_call_graph_json(
    *,
    base_manifest_path: Path,
    repo_summaries: List[Dict[str, Any]],
    final_dump_index: Optional[Path],
    run_id: str,
) -> Optional[Path]:
    """Emit Python Call Graph v1 for one repository as navigation only."""

    repo_root = _single_repo_root(repo_summaries, final_dump_index)
    if repo_root is None:
        return None
    canonical_sha = compute_file_sha256(final_dump_index)
    if not is_sha256_digest(canonical_sha):
        return None
    from merger.repoground.architecture.call_graph import generate_call_graph_document

    return _write_provenance_document(
        base_manifest_path=base_manifest_path,
        suffix=".python_call_graph.json",
        document=generate_call_graph_document(repo_root, run_id, canonical_sha),
    )


def write_language_structure_json(
    *,
    base_manifest_path: Path,
    repo_summaries: List[Dict[str, Any]],
    final_dump_index: Optional[Path],
    run_id: str,
) -> Optional[Path]:
    """Emit bounded Rust/Bash navigation evidence for one bound Git repository."""

    repo_root = _single_repo_root(repo_summaries, final_dump_index)
    if repo_root is None:
        return None
    canonical_sha = compute_file_sha256(final_dump_index)
    if not is_sha256_digest(canonical_sha):
        return None
    provenance = repository_snapshot_provenance(repo_root)
    repository_commit = provenance.get("git_commit")
    if (
        provenance.get("provenance_status") != "present"
        or provenance.get("git_dirty") is not False
        or provenance.get("freshness_basis") != "git_commit"
        or not isinstance(repository_commit, str)
    ):
        # Every language hit is required to carry an exact repository revision.
        # An unbound or dirty checkout therefore produces no structural sidecar
        # instead of records whose commit freshness cannot be evaluated.
        return None
    from .language_structure import build_language_structure_document

    document = build_language_structure_document(
        repo_root,
        repository_commit=repository_commit,
        bundle_manifest=base_manifest_path.name,
        canonical_dump_index_sha256=canonical_sha,
        run_id=run_id,
    )
    summaries = document.get("languages")
    if isinstance(summaries, dict) and not any(
        isinstance(value, dict) and int(value.get("candidate_file_count", 0)) > 0
        for value in summaries.values()
    ):
        return None
    return _write_provenance_document(
        base_manifest_path=base_manifest_path,
        suffix=".language_structure.json",
        document=document,
    )


def write_lens_cards_jsonl(
    *,
    base_manifest_path: Path,
    repo_summaries: List[Dict[str, Any]],
) -> Optional[Path]:
    """Emit Lens Cards v1 as deterministic JSONL navigation."""

    from .lens_cards import produce_lens_cards

    paths: List[str] = []
    for summary in repo_summaries:
        for fi in summary.get("files", []):
            if getattr(fi, "is_text", False):
                paths.append(fi.rel_path.as_posix())
    if not paths:
        return None
    cards = produce_lens_cards(paths)
    if not cards:
        return None
    out_path = sidecar_path(base_manifest_path, ".lens_cards.jsonl")
    write_json_lines(out_path, cards)
    return out_path


def write_concept_cards_jsonl(*, base_manifest_path: Path) -> Optional[Path]:
    """Emit built-in Concept Cards v1 as deterministic JSONL navigation."""

    from .concept_cards import produce_default_concept_cards

    cards = produce_default_concept_cards()
    if not cards:
        return None
    out_path = sidecar_path(base_manifest_path, ".concept_cards.jsonl")
    write_json_lines(out_path, cards)
    return out_path


def write_relation_cards_jsonl(
    *,
    base_manifest_path: Path,
    graph_path: Optional[Path],
) -> Optional[Path]:
    """Emit Relation Cards v1 as deterministic JSONL navigation."""

    if graph_path is None or not graph_path.exists():
        return None
    from .relation_cards import produce_relation_cards

    graph_data = json.loads(graph_path.read_text(encoding="utf-8"))
    cards = produce_relation_cards(graph_data)
    if not cards:
        return None
    out_path = sidecar_path(base_manifest_path, ".relation_cards.jsonl")
    write_json_lines(out_path, cards)
    return out_path


def write_delta_json(
    *,
    base_manifest_path: Path,
    source_delta: Dict[str, Any],
) -> Path:
    """Emit the validated PR Schau delta source as bundle diagnostic JSON."""

    return _write_provenance_document(
        base_manifest_path=base_manifest_path,
        suffix=".delta.json",
        document=source_delta,
    )


def write_pr_delta_cards_jsonl(
    *,
    base_manifest_path: Path,
    cards: List[Dict[str, Any]],
) -> Optional[Path]:
    """Emit PR Delta Cards v1 after the changed-set source was validated."""

    if not cards:
        return None
    out_path = sidecar_path(base_manifest_path, ".pr_delta_cards.jsonl")
    write_json_lines(out_path, cards)
    return out_path
