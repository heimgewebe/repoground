import json
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _load_goldset(name: str):
    path = _repo_root() / "docs" / "retrieval" / name
    return json.loads(path.read_text(encoding="utf-8"))


def test_review_queries_v2_is_lossless_split_of_v1():
    legacy = _load_goldset("review_queries.v1.json")
    explicit = _load_goldset("review_queries.v2.json")

    assert len(legacy) == len(explicit) == 20

    for old, new in zip(legacy, explicit, strict=True):
        assert new["query"] == old["query"]
        assert new["category"] == old["category"]
        assert new["filters"] == old["filters"]
        assert new["accept_criteria"] == old["accept_criteria"]
        assert "expected_patterns" not in new
        assert new["expected_paths"] + new["expected_evidence"] == old["expected_patterns"]


def test_benchmark_cli_keeps_canonical_v1_goldset_as_default():
    script = (
        _repo_root() / "scripts" / "benchmarks" / "repoground_vs_grep_read.py"
    ).read_text(encoding="utf-8")

    assert 'default=Path("docs/retrieval/review_queries.v1.json")' in script
    assert 'default=Path("docs/retrieval/review_queries.v2.json")' not in script
