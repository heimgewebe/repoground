"""Revision-bound, conservative S2 change projection over existing S1 Flake evidence.

This is a read-only comparison of immutable Git objects, not a Nix evaluator.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .flake_input_relations import flake_revision_relations
from .history_lens import git_revision_delta

KIND = "repoground.flake-relation-delta"
VERSION = "1"


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    ).encode("utf-8")


def _identity(row: dict[str, Any]) -> dict[str, Any]:
    """Stable logical identity, independent of provenance revision and source line."""
    def endpoint(obj: dict[str, Any]) -> dict[str, Any]:
        return {
            key: obj[key] for key in ("repo_id", "path", "symbol")
            if key in obj
        }

    return {
        "relation_type": row["relation_type"],
        "source": endpoint(row["source"]),
        "target": endpoint(row["target"]),
    }


def _material(row: dict[str, Any], source_repo: str) -> dict[str, Any]:
    """Exclude only revision and line movement, retaining changed blob/pin identity."""
    def endpoint(obj: dict[str, Any]) -> dict[str, Any]:
        return {
            key: value for key, value in obj.items()
            if key not in {"line_start", "line_end"}
            and not (key == "commit" and obj.get("repo_id") == source_repo)
        }

    return {
        "relation_type": row["relation_type"],
        "direction": row.get("direction"),
        "evidence_level": row.get("evidence_level"),
        "resolution_status": row.get("resolution_status"),
        "source": endpoint(row["source"]),
        "target": endpoint(row["target"]),
        "supporting_evidence": [
            endpoint(item) for item in row.get("supporting_evidence", [])
        ],
        "asserts_runtime_dependency": row.get("asserts_runtime_dependency"),
    }


def _indexed(rows: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], list[str]]:
    by_key: dict[str, dict[str, Any]] = {}
    ambiguous: set[str] = set()
    for row in rows:
        key = _canonical(_identity(row)).decode("utf-8")
        if key in by_key:
            ambiguous.add(key)
        else:
            by_key[key] = row
    for key in ambiguous:
        by_key.pop(key, None)
    return by_key, sorted(ambiguous)


def _format_pin_targets(
    targets: dict[str, tuple[str | Path, str]],
) -> list[dict[str, str]]:
    return [
        {"repo_id": repo, "commit": commit}
        for repo, (_, commit) in sorted(targets.items())
    ]


def flake_relation_delta(
    source_root: str | Path,
    base_commit: str,
    head_commit: str,
    *,
    source_repo: str,
    targets_before: dict[str, tuple[str | Path, str]],
    targets_after: dict[str, tuple[str | Path, str]],
) -> dict[str, Any]:
    """Compare exact S1 relationships and Git file deltas, preserving unknowns.

    An edge absent from an incomplete head projection is *unverified*, not removed.
    An edge newly present after an incomplete base is *newly_verified*, not added.
    No source-to-runtime transition, causal impact, or implicit Nix activation is inferred.
    """
    before = flake_revision_relations(
        source_root, base_commit, source_repo=source_repo, targets=targets_before,
    )
    after = flake_revision_relations(
        source_root, head_commit, source_repo=source_repo, targets=targets_after,
    )
    git_delta = git_revision_delta(
        Path(source_root), source_repo.replace("/", "__"),
        before["source_commit"], after["source_commit"],
    )
    old, old_duplicates = _indexed(before["relations"])
    new, new_duplicates = _indexed(after["relations"])
    duplicates = sorted(set(old_duplicates + new_duplicates))
    changes: list[dict[str, Any]] = []
    for key in sorted(set(old) | set(new)):
        previous, current = old.get(key), new.get(key)
        if previous is None:
            transition = "newly_verified" if before["gaps"] or old_duplicates else "added"
        elif current is None:
            transition = (
                "unverified" if after["gaps"] or new_duplicates
                or git_delta["status"] != "ok" else "removed"
            )
        elif _material(previous, source_repo) != _material(current, source_repo):
            transition = "changed"
        else:
            continue
        changes.append({
            "transition": transition,
            "relation_identity": _identity(previous or current),
            "before": previous,
            "after": current,
            "basis": "s1_relation_git_blob_and_pinned_input_comparison",
            "direct_or_inferred": "direct_declaration_evidence",
            "asserts_runtime_change": False,
        })
    gaps = (
        ["base:" + item for item in before["gaps"]]
        + ["head:" + item for item in after["gaps"]]
        + ["git_delta:" + item for item in git_delta["gaps"]]
        + (["ambiguous_relation_identity"] if duplicates else [])
    )
    result: dict[str, Any] = {
        "kind": KIND,
        "version": VERSION,
        "source_repo": source_repo,
        "base_commit": before["source_commit"],
        "head_commit": after["source_commit"],
        "target_pins_before": _format_pin_targets(targets_before),
        "target_pins_after": _format_pin_targets(targets_after),
        "s1_evidence_sha256_before": before["evidence_sha256"],
        "s1_evidence_sha256_after": after["evidence_sha256"],
        "git_delta_status": git_delta["status"],
        "direct_source_file_changes": git_delta["file_changes"],
        "source_revision_time": git_delta.get("source_revision_time"),
        "changes": changes,
        "base_gaps": before["gaps"],
        "head_gaps": after["gaps"],
        "gaps": sorted(set(gaps)),
        "status": "partial" if gaps else "ok",
        "duplicate_relation_identifiers": duplicates,
        "transitive_impacts": [],
        "does_not_establish": [
            "runtime_deployment", "active_generation", "running_service",
            "causality", "transitive_impact", "complete_nix_evaluation",
        ],
    }
    result["evidence_sha256"] = hashlib.sha256(_canonical(result)).hexdigest()
    return result