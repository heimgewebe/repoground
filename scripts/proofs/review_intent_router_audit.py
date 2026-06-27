#!/usr/bin/env python3
"""Compare legacy and opt-in review retrieval on one manifest-bound bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from merger.lenskit.retrieval.eval_core import do_eval
from merger.lenskit.retrieval.review_eval import build_review_retrieval_baseline

SCHEMA = "lenskit.review_intent_router_audit.v1"
PROOF_PATHS = (
    "docs/proofs/review-intent-router-v1-target-proof.md",
    "docs/proofs/review-intent-router-v1-audit.json",
    "scripts/proofs/review_intent_router_audit.py",
)
REQUIRED_BUNDLE_ROLES = ("canonical_md", "chunk_index_jsonl", "sqlite_index")
EPSILON = 1e-12


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative(path: Path, root: Path) -> str:
    resolved = path.resolve() if path.is_absolute() else (root / path).resolve()
    try:
        return resolved.relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError(f"path outside repo_root: {path}") from exc


def _git_state(root: Path) -> tuple[str, list[str]]:
    commit = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=no"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.splitlines()
    return commit, dirty


def _load_manifest_bundle(
    manifest_path: Path,
) -> tuple[dict[str, Any], dict[str, Path], str]:
    manifest_path = manifest_path.resolve()
    if not manifest_path.is_file():
        raise ValueError(f"bundle manifest does not exist: {manifest_path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid bundle manifest: {manifest_path}") from exc
    if manifest.get("kind") != "repolens.bundle.manifest":
        raise ValueError("manifest kind must be repolens.bundle.manifest")

    role_entries: dict[str, dict[str, Any]] = {}
    for entry in manifest.get("artifacts", []):
        if not isinstance(entry, dict):
            continue
        role = entry.get("role")
        if role in REQUIRED_BUNDLE_ROLES:
            if role in role_entries:
                raise ValueError(f"bundle manifest contains duplicate role: {role}")
            role_entries[role] = entry
    missing = [role for role in REQUIRED_BUNDLE_ROLES if role not in role_entries]
    if missing:
        raise ValueError(f"bundle manifest is missing required roles: {missing}")

    bundle_dir = manifest_path.parent.resolve()
    resolved: dict[str, Path] = {}
    for role in REQUIRED_BUNDLE_ROLES:
        entry = role_entries[role]
        raw_path = entry.get("path")
        expected_sha = entry.get("sha256")
        expected_bytes = entry.get("bytes")
        if not isinstance(raw_path, str) or not raw_path:
            raise ValueError(f"manifest role {role} has no artifact path")
        artifact_path = (bundle_dir / raw_path).resolve()
        try:
            artifact_path.relative_to(bundle_dir)
        except ValueError as exc:
            raise ValueError(
                f"manifest artifact escapes bundle directory: {raw_path}"
            ) from exc
        if not artifact_path.is_file():
            raise ValueError(
                f"manifest artifact does not exist for role {role}: {raw_path}"
            )
        if not isinstance(expected_sha, str) or file_hash(artifact_path) != expected_sha:
            raise ValueError(f"manifest sha256 mismatch for role {role}")
        if (
            not isinstance(expected_bytes, int)
            or artifact_path.stat().st_size != expected_bytes
        ):
            raise ValueError(f"manifest byte-size mismatch for role {role}")
        resolved[role] = artifact_path

    runtime = ((manifest.get("generator") or {}).get("runtime") or {})
    source_commit = runtime.get("git_commit")
    if not isinstance(source_commit, str) or not source_commit:
        raise ValueError("bundle manifest has no generator runtime git_commit")
    if runtime.get("git_dirty") is not False:
        raise ValueError("bundle manifest was not generated from a clean tracked tree")
    return manifest, resolved, source_commit


def _assert_optional_artifact(
    supplied: Path | None,
    *,
    expected: Path,
    label: str,
) -> Path:
    if supplied is None:
        return expected
    if supplied.resolve() != expected.resolve():
        raise ValueError(f"{label} does not match the bundle manifest")
    return expected


def _target_stats_by_category(
    baseline: dict[str, Any],
) -> dict[str, dict[str, int]]:
    stats: dict[str, dict[str, int]] = {}
    for query in baseline.get("queries", []):
        category = query.get("category") or "uncategorized"
        row = stats.setdefault(category, {"total": 0, "hits": 0})
        targets = query.get("expected_targets", []) or []
        row["total"] += len(targets)
        row["hits"] += sum(1 for target in targets if target.get("found") is True)
    return stats


def _rate(hits: int, total: int) -> float:
    return (hits / total) * 100.0 if total else 0.0


def compare_baselines(
    legacy: dict[str, Any], review: dict[str, Any], *, k: int
) -> dict[str, Any]:
    recall_key = f"recall@{k}"
    lm = legacy["metrics"]
    rm = review["metrics"]
    legacy_targets = _target_stats_by_category(legacy)
    review_targets = _target_stats_by_category(review)
    rows = []
    recall_regressions = []
    mrr_regressions = []
    target_recall_regressions = []
    categories = sorted(
        set(legacy.get("categories", {}))
        | set(review.get("categories", {}))
        | set(legacy_targets)
        | set(review_targets)
    )
    for category in categories:
        old = legacy.get("categories", {}).get(category, {})
        new = review.get("categories", {}).get(category, {})
        old_recall = float(old.get(recall_key, 0.0))
        new_recall = float(new.get(recall_key, 0.0))
        old_mrr = float(old.get("MRR", 0.0))
        new_mrr = float(new.get("MRR", 0.0))
        old_target = legacy_targets.get(category, {"total": 0, "hits": 0})
        new_target = review_targets.get(category, {"total": 0, "hits": 0})
        old_target_recall = _rate(old_target["hits"], old_target["total"])
        new_target_recall = _rate(new_target["hits"], new_target["total"])
        recall_regression = new_recall + EPSILON < old_recall
        mrr_regression = new_mrr + EPSILON < old_mrr
        target_recall_regression = (
            new_target_recall + EPSILON < old_target_recall
        )
        if recall_regression:
            recall_regressions.append(category)
        if mrr_regression:
            mrr_regressions.append(category)
        if target_recall_regression:
            target_recall_regressions.append(category)
        rows.append(
            {
                "category": category,
                "legacy_recall": old_recall,
                "review_recall": new_recall,
                "delta_recall": new_recall - old_recall,
                "legacy_mrr": old_mrr,
                "review_mrr": new_mrr,
                "delta_mrr": new_mrr - old_mrr,
                "legacy_target_hits": old_target["hits"],
                "review_target_hits": new_target["hits"],
                "target_total": new_target["total"],
                "legacy_target_recall": old_target_recall,
                "review_target_recall": new_target_recall,
                "delta_target_recall": new_target_recall - old_target_recall,
                "recall_regression": recall_regression,
                "mrr_regression": mrr_regression,
                "target_recall_regression": target_recall_regression,
            }
        )

    legacy_target_total = int(lm["expected_target_total"])
    review_target_total = int(rm["expected_target_total"])
    legacy_target_hits = int(lm["expected_target_hits"])
    review_target_hits = int(rm["expected_target_hits"])
    legacy_target_recall = _rate(legacy_target_hits, legacy_target_total)
    review_target_recall = _rate(review_target_hits, review_target_total)
    aggregate = {
        "total_queries": int(rm["total_queries"]),
        "legacy_recall": float(lm[recall_key]),
        "review_recall": float(rm[recall_key]),
        "delta_recall": float(rm[recall_key]) - float(lm[recall_key]),
        "legacy_mrr": float(lm["MRR"]),
        "review_mrr": float(rm["MRR"]),
        "delta_mrr": float(rm["MRR"]) - float(lm["MRR"]),
        "legacy_zero_hit_ratio": float(lm["zero_hit_ratio"]),
        "review_zero_hit_ratio": float(rm["zero_hit_ratio"]),
        "legacy_expected_target_hits": legacy_target_hits,
        "review_expected_target_hits": review_target_hits,
        "legacy_expected_target_total": legacy_target_total,
        "review_expected_target_total": review_target_total,
        "legacy_expected_target_recall": legacy_target_recall,
        "review_expected_target_recall": review_target_recall,
        "delta_expected_target_recall": (
            review_target_recall - legacy_target_recall
        ),
    }
    gates = {
        "query_count_unchanged": lm["total_queries"] == rm["total_queries"],
        "expected_target_total_unchanged": (
            legacy_target_total == review_target_total
        ),
        "aggregate_recall_improved": aggregate["delta_recall"] > EPSILON,
        "aggregate_mrr_improved": aggregate["delta_mrr"] > EPSILON,
        "expected_target_hits_improved": (
            review_target_hits > legacy_target_hits
        ),
        "expected_target_recall_improved": (
            aggregate["delta_expected_target_recall"] > EPSILON
        ),
        "no_category_recall_regression": not recall_regressions,
        "no_category_mrr_regression": not mrr_regressions,
        "no_category_target_recall_regression": (
            not target_recall_regressions
        ),
    }
    gates["passed"] = all(gates.values())
    return {
        "aggregate": aggregate,
        "categories": rows,
        "regressions": {
            "recall": recall_regressions,
            "mrr": mrr_regressions,
            "target_recall": target_recall_regressions,
        },
        "gates": gates,
    }


def run_audit(
    *,
    manifest: Path,
    goldset: Path,
    repo_root: Path,
    k: int,
    index: Path | None = None,
    canonical: Path | None = None,
    chunk_index: Path | None = None,
) -> dict[str, Any]:
    if k < 1:
        raise ValueError("k must be at least 1")
    root = repo_root.resolve()
    goldset = goldset.resolve()
    if not goldset.is_file():
        raise ValueError("goldset must exist")

    manifest_data, bundle_paths, manifest_commit = _load_manifest_bundle(manifest)
    index = _assert_optional_artifact(
        index, expected=bundle_paths["sqlite_index"], label="index"
    )
    canonical = _assert_optional_artifact(
        canonical, expected=bundle_paths["canonical_md"], label="canonical"
    )
    chunk_index = _assert_optional_artifact(
        chunk_index,
        expected=bundle_paths["chunk_index_jsonl"],
        label="chunk index",
    )
    commit, dirty = _git_state(root)
    if dirty:
        raise ValueError("audit requires a clean tracked working tree")
    if manifest_commit != commit:
        raise ValueError(
            "bundle generator git_commit does not match the audited repository HEAD"
        )

    records = [
        {
            "path": relative(goldset, root),
            "reason": "goldset_self_reference",
        }
    ]
    records.extend(
        {
            "path": relative(Path(path), root),
            "reason": "proof_surface_self_reference",
        }
        for path in PROOF_PATHS
    )
    records = list({row["path"]: row for row in records}.values())
    records.sort(key=lambda row: row["path"])
    excluded = [row["path"] for row in records]

    legacy_eval = do_eval(
        index, goldset, k, is_json_mode=True, excluded_paths=excluded
    )
    review_eval = do_eval(
        index,
        goldset,
        k,
        is_json_mode=True,
        excluded_paths=excluded,
        review_intent=True,
    )
    if legacy_eval is None or review_eval is None:
        raise RuntimeError("evaluation produced no result")
    goldset_path = relative(goldset, root)
    legacy = build_review_retrieval_baseline(
        legacy_eval, k=k, goldset_path=goldset_path, path_exclusions=records
    )
    review = build_review_retrieval_baseline(
        review_eval, k=k, goldset_path=goldset_path, path_exclusions=records
    )

    manifest_path = manifest.resolve()
    snapshot = {
        "manifest_file": manifest_path.name,
        "manifest_sha256": file_hash(manifest_path),
        "run_id": manifest_data.get("run_id"),
        "generator_git_commit": manifest_commit,
        "index_file": index.name,
        "index_sha256": file_hash(index),
        "goldset_file": goldset_path,
        "goldset_sha256": file_hash(goldset),
        "canonical_file": canonical.name,
        "canonical_sha256": file_hash(canonical),
        "chunk_index_file": chunk_index.name,
        "chunk_index_sha256": file_hash(chunk_index),
        "manifest_binding_verified": True,
    }
    return {
        "schema": SCHEMA,
        "authority": "diagnostic_signal",
        "risk_class": "diagnostic",
        "source": {
            "commit": commit,
            "tracked_working_tree_clean": True,
            "tracked_changes": [],
            "manifest_commit_matches_head": True,
        },
        "snapshot": snapshot,
        "measurement": {
            "k": k,
            "excluded_paths": records,
            "legacy": legacy["metrics"],
            "review_intent": review["metrics"],
            "review_intent_conditions": review.get("measurement_conditions"),
        },
        "comparison": compare_baselines(legacy, review, k=k),
        "default_promoted": False,
        "claim_boundaries": {
            "proves": [
                "The declared pipelines were measured against artifacts whose paths, "
                "sizes, hashes, and generator commit match this bundle manifest."
            ],
            "does_not_prove": [
                "Passing does not prove general retrieval quality.",
                "A hit does not prove relevance or correctness.",
                "A miss does not prove repository absence.",
                "The snapshot does not prove current live-repository state after the audited commit.",
                "Passing does not promote review-intent to the default.",
            ],
            "requires_live_check": True,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--index", type=Path)
    parser.add_argument(
        "--goldset",
        type=Path,
        default=Path("docs/retrieval/review_queries.v1.json"),
    )
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/proofs/review-intent-router-v1-audit.json"),
    )
    parser.add_argument("--canonical", type=Path)
    parser.add_argument("--chunk-index", type=Path)
    parser.add_argument("--k", type=int, default=10)
    args = parser.parse_args()

    report = run_audit(
        manifest=args.manifest,
        index=args.index,
        goldset=args.goldset,
        repo_root=args.repo_root,
        k=args.k,
        canonical=args.canonical,
        chunk_index=args.chunk_index,
    )
    output = args.output
    if not output.is_absolute():
        output = args.repo_root / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(output)
    return 0 if report["comparison"]["gates"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
