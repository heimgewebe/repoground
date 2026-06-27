#!/usr/bin/env python3
"""Compare legacy and opt-in review retrieval on one explicit index."""

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
EPSILON = 1e-12


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative(path: Path, root: Path) -> str:
    resolved = path.resolve() if path.is_absolute() else (root / path).resolve()
    try:
        return resolved.relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError(f"path outside repo_root: {path}") from exc


def compare_baselines(
    legacy: dict[str, Any], review: dict[str, Any], *, k: int
) -> dict[str, Any]:
    recall_key = f"recall@{k}"
    lm = legacy["metrics"]
    rm = review["metrics"]
    rows = []
    recall_regressions = []
    mrr_regressions = []
    categories = sorted(
        set(legacy.get("categories", {})) | set(review.get("categories", {}))
    )
    for category in categories:
        old = legacy.get("categories", {}).get(category, {})
        new = review.get("categories", {}).get(category, {})
        old_recall = float(old.get(recall_key, 0.0))
        new_recall = float(new.get(recall_key, 0.0))
        old_mrr = float(old.get("MRR", 0.0))
        new_mrr = float(new.get("MRR", 0.0))
        recall_regression = new_recall + EPSILON < old_recall
        mrr_regression = new_mrr + EPSILON < old_mrr
        if recall_regression:
            recall_regressions.append(category)
        if mrr_regression:
            mrr_regressions.append(category)
        rows.append({
            "category": category,
            "legacy_recall": old_recall,
            "review_recall": new_recall,
            "delta_recall": new_recall - old_recall,
            "legacy_mrr": old_mrr,
            "review_mrr": new_mrr,
            "delta_mrr": new_mrr - old_mrr,
            "recall_regression": recall_regression,
            "mrr_regression": mrr_regression,
        })

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
        "legacy_expected_target_hits": int(lm["expected_target_hits"]),
        "review_expected_target_hits": int(rm["expected_target_hits"]),
        "expected_target_total": int(rm["expected_target_total"]),
    }
    gates = {
        "query_count_unchanged": lm["total_queries"] == rm["total_queries"],
        "aggregate_recall_improved": aggregate["delta_recall"] > EPSILON,
        "aggregate_mrr_improved": aggregate["delta_mrr"] > EPSILON,
        "expected_target_hits_improved": aggregate["review_expected_target_hits"]
        > aggregate["legacy_expected_target_hits"],
        "no_category_recall_regression": not recall_regressions,
        "no_category_mrr_regression": not mrr_regressions,
    }
    gates["passed"] = all(gates.values())
    return {
        "aggregate": aggregate,
        "categories": rows,
        "regressions": {"recall": recall_regressions, "mrr": mrr_regressions},
        "gates": gates,
    }


def run_audit(
    *,
    index: Path,
    goldset: Path,
    repo_root: Path,
    k: int,
    canonical: Path | None = None,
    chunk_index: Path | None = None,
) -> dict[str, Any]:
    if k < 1:
        raise ValueError("k must be at least 1")
    root = repo_root.resolve()
    index = index.resolve()
    goldset = goldset.resolve()
    if not index.is_file() or not goldset.is_file():
        raise ValueError("index and goldset must exist")

    records = [{
        "path": relative(goldset, root),
        "reason": "goldset_self_reference",
    }]
    records.extend(
        {"path": relative(Path(path), root), "reason": "proof_surface_self_reference"}
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

    snapshot = {
        "index_file": index.name,
        "index_sha256": file_hash(index),
        "goldset_file": goldset_path,
        "goldset_sha256": file_hash(goldset),
    }
    if canonical is not None:
        snapshot.update({
            "canonical_file": canonical.name,
            "canonical_sha256": file_hash(canonical.resolve()),
        })
    if chunk_index is not None:
        snapshot.update({
            "chunk_index_file": chunk_index.name,
            "chunk_index_sha256": file_hash(chunk_index.resolve()),
        })
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
    return {
        "schema": SCHEMA,
        "authority": "diagnostic_signal",
        "risk_class": "diagnostic",
        "source": {
            "commit": commit,
            "tracked_working_tree_clean": not dirty,
            "tracked_changes": dirty,
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
                "The declared pipelines were measured against this exact index "
                "and goldset under the listed exclusions."
            ],
            "does_not_prove": [
                "Passing does not prove general retrieval quality.",
                "A hit does not prove relevance or correctness.",
                "A miss does not prove repository absence.",
                "The snapshot does not prove current live-repository state.",
                "Passing does not promote review-intent to the default.",
            ],
            "requires_live_check": True,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, required=True)
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
