import hashlib
import json
from pathlib import Path

import pytest

from scripts.proofs import review_intent_router_audit as audit
from scripts.proofs.review_intent_router_audit import compare_baselines


def _baseline(*, recall, mrr, target_hits, category_recall, category_mrr):
    targets = [
        {"found": index < target_hits}
        for index in range(4)
    ]
    return {
        "metrics": {
            "total_queries": 2,
            "recall@10": recall,
            "MRR": mrr,
            "zero_hit_ratio": 0.5,
            "expected_target_total": 4,
            "expected_target_hits": target_hits,
        },
        "categories": {
            "sample": {
                "total_queries": 2,
                "hits": 1,
                "misses": 1,
                "recall@10": category_recall,
                "MRR": category_mrr,
            }
        },
        "queries": [
            {
                "category": "sample",
                "expected_targets": targets,
            }
        ],
    }


def test_compare_baselines_passes_on_gain_without_category_regression():
    legacy = _baseline(
        recall=50.0,
        mrr=0.25,
        target_hits=1,
        category_recall=50.0,
        category_mrr=0.25,
    )
    review = _baseline(
        recall=100.0,
        mrr=0.5,
        target_hits=3,
        category_recall=100.0,
        category_mrr=0.5,
    )

    comparison = compare_baselines(legacy, review, k=10)

    assert comparison["gates"]["passed"] is True
    assert comparison["regressions"] == {
        "recall": [],
        "mrr": [],
        "target_recall": [],
    }
    assert comparison["aggregate"]["delta_recall"] == 50.0
    assert comparison["aggregate"]["legacy_expected_target_recall"] == 25.0
    assert comparison["aggregate"]["review_expected_target_recall"] == 75.0
    assert comparison["categories"][0]["delta_mrr"] == 0.25
    assert comparison["categories"][0]["delta_target_recall"] == 50.0


def test_compare_baselines_fails_closed_on_category_mrr_regression():
    legacy = _baseline(
        recall=50.0,
        mrr=0.25,
        target_hits=1,
        category_recall=100.0,
        category_mrr=1.0,
    )
    review = _baseline(
        recall=100.0,
        mrr=0.5,
        target_hits=3,
        category_recall=100.0,
        category_mrr=0.5,
    )

    comparison = compare_baselines(legacy, review, k=10)

    assert comparison["gates"]["passed"] is False
    assert comparison["gates"]["no_category_recall_regression"] is True
    assert comparison["gates"]["no_category_mrr_regression"] is False
    assert comparison["regressions"]["mrr"] == ["sample"]


def _write_manifest(tmp_path: Path, *, git_commit: str = "head") -> Path:
    artifacts = []
    for role, name, content in (
        ("canonical_md", "bundle.md", b"canonical\n"),
        ("chunk_index_jsonl", "bundle.chunk_index.jsonl", b"{}\n"),
        ("sqlite_index", "bundle.sqlite", b"sqlite-placeholder"),
    ):
        path = tmp_path / name
        path.write_bytes(content)
        artifacts.append(
            {
                "role": role,
                "path": name,
                "bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        )
    manifest = tmp_path / "bundle.manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "kind": "repolens.bundle.manifest",
                "version": "1.0",
                "run_id": "fixture",
                "generator": {
                    "runtime": {
                        "git_commit": git_commit,
                        "git_dirty": False,
                    }
                },
                "artifacts": artifacts,
            }
        ),
        encoding="utf-8",
    )
    return manifest


def test_manifest_bundle_rejects_hash_mismatch(tmp_path):
    manifest = _write_manifest(tmp_path)
    (tmp_path / "bundle.md").write_text("tampered\n", encoding="utf-8")

    with pytest.raises(ValueError, match="sha256 mismatch for role canonical_md"):
        audit._load_manifest_bundle(manifest)


def test_optional_artifact_must_match_manifest_path(tmp_path):
    expected = tmp_path / "expected.sqlite"
    supplied = tmp_path / "unrelated.sqlite"

    with pytest.raises(ValueError, match="index does not match"):
        audit._assert_optional_artifact(
            supplied,
            expected=expected,
            label="index",
        )


def test_run_audit_rejects_manifest_commit_mismatch(tmp_path, monkeypatch):
    goldset = tmp_path / "goldset.json"
    goldset.write_text("[]", encoding="utf-8")
    paths = {
        "canonical_md": tmp_path / "bundle.md",
        "chunk_index_jsonl": tmp_path / "bundle.jsonl",
        "sqlite_index": tmp_path / "bundle.sqlite",
    }
    monkeypatch.setattr(
        audit,
        "_load_manifest_bundle",
        lambda _path: ({"run_id": "fixture"}, paths, "other-commit"),
    )
    monkeypatch.setattr(audit, "_git_state", lambda _root: ("head-commit", []))

    with pytest.raises(ValueError, match="git_commit does not match"):
        audit.run_audit(
            manifest=tmp_path / "bundle.manifest.json",
            goldset=goldset,
            repo_root=tmp_path,
            k=10,
        )
