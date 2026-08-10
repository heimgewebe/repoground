import json
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _load_goldset(name: str):
    path = _repo_root() / "docs" / "retrieval" / name
    return json.loads(path.read_text(encoding="utf-8"))


def test_review_queries_v2_preserves_v1_questions_and_path_targets():
    legacy = _load_goldset("review_queries.v1.json")
    explicit = _load_goldset("review_queries.v2.json")

    assert len(legacy) == len(explicit) == 20

    for old, new in zip(legacy, explicit, strict=True):
        assert new["query"] == old["query"]
        assert new["category"] == old["category"]
        assert new["filters"] == old["filters"]
        assert new["accept_criteria"] == old["accept_criteria"]
        assert "expected_patterns" not in new
        legacy_path_targets = [
            pattern for pattern in old["expected_patterns"] if "/" in pattern
        ]
        assert new["expected_paths"] == legacy_path_targets


def test_review_queries_v2_evidence_is_bound_to_expected_files():
    root = _repo_root()
    explicit = _load_goldset("review_queries.v2.json")

    for case in explicit:
        target_texts = []
        for relative in case["expected_paths"]:
            path = root / relative
            if path.is_file():
                target_texts.append(path.read_text(encoding="utf-8", errors="replace"))

        for evidence in case["expected_evidence"]:
            assert any(evidence in text for text in target_texts), (
                f"evidence {evidence!r} is absent from expected files for "
                f"{case['query']!r}"
            )


def test_benchmark_cli_uses_v2_goldset_as_canonical_default():
    script = (
        _repo_root() / "scripts" / "benchmarks" / "repoground_vs_grep_read.py"
    ).read_text(encoding="utf-8")

    assert 'default=Path("docs/retrieval/review_queries.v2.json")' in script
    assert 'default=Path("docs/retrieval/review_queries.v1.json")' not in script


def test_v5_default_promotion_does_not_rewrite_v4_contract():
    proofs = _repo_root() / "docs" / "proofs"
    v4 = (proofs / "repoground-vs-grep-read.v4-contract-proof.md").read_text(
        encoding="utf-8"
    )
    v5 = (proofs / "repoground-vs-grep-read.v5-contract-proof.md").read_text(
        encoding="utf-8"
    )

    assert "canonical CLI default remains `docs/retrieval/review_queries.v1.json`" in v4
    assert "report version is `v5`" in v5
    assert "CLI default: `docs/retrieval/review_queries.v2.json`" in v5
    assert "explicit legacy path: `docs/retrieval/review_queries.v1.json`" in v5
