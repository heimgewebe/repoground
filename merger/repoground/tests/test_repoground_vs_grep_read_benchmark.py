import importlib.util
import json
import sys
from pathlib import Path

from merger.repoground.retrieval import index_db


def _benchmark_module():
    root = Path(__file__).resolve().parents[3]
    path = root / "scripts/benchmarks/repoground_vs_grep_read.py"
    spec = importlib.util.spec_from_file_location("repoground_vs_grep_read", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fixture_index(tmp_path):
    root = tmp_path / "repo"
    source = root / "src/widget.py"
    source.parent.mkdir(parents=True)
    source.write_text("def widget():\n    return 'widget'\n", encoding="utf-8")
    dump = tmp_path / "dump.json"
    chunks = tmp_path / "chunks.jsonl"
    index = tmp_path / "fixture.index.sqlite"
    dump.write_text("{}", encoding="utf-8")
    chunks.write_text(json.dumps({
        "chunk_id": "widget", "repo_id": "fixture", "path": "src/widget.py",
        "content": "widget implementation", "start_line": 1, "end_line": 2,
        "layer": "core", "artifact_type": "code", "content_sha256": "a" * 64,
    }) + "\n", encoding="utf-8")
    index_db.build_index(dump, chunks, index)
    questions = tmp_path / "questions.json"
    questions.write_text(json.dumps([
        {"query": "widget", "category": "fixture", "expected_patterns": ["src/widget.py"]}
        for _ in range(20)
    ]), encoding="utf-8")
    return root, index, questions


def test_benchmark_writes_per_case_and_aggregate_measurements_with_input_hashes(tmp_path):
    module = _benchmark_module()
    root, index, questions = _fixture_index(tmp_path)

    report = module.run(index, root, questions, k=1)

    assert report["status"] == "inconclusive"
    assert len(report["cases"]) == 20
    assert report["acceptance"]["same_question_set"] is True
    assert report["acceptance"]["same_k"] == 1
    assert set(report["inputs"]) >= {"index_sha256", "questions_sha256", "repo_tree_sha256"}
    for case in report["cases"]:
        assert case["k"] == 1
        for condition in ("repoground", "grep_read"):
            measurement = case[condition]
            assert set(measurement) >= {
                "runtime_ms", "tool_calls", "process_calls", "response_bytes",
                "token_proxy", "source_index_freshness", "false_confidence",
            }
        assert case["repoground"]["compaction"]["pass"] is True
        assert case["repoground"]["false_confidence"] is False
    assert report["aggregates"]["repoground"]["compaction"]["aggregate_pass"] is True


def test_benchmark_defines_false_confidence_for_missing_targets_or_stale_sources(tmp_path):
    module = _benchmark_module()
    root, index, questions = _fixture_index(tmp_path)
    questions.write_text(json.dumps([
        {"query": "widget", "expected_patterns": ["src/widget.py", "missing.py"]}
        for _ in range(20)
    ]), encoding="utf-8")

    report = module.run(index, root, questions, k=1)

    assert report["cases"][0]["repoground"]["useful_displayed"] is True
    assert report["cases"][0]["repoground"]["false_confidence"] is True
    assert report["aggregates"]["repoground"]["false_confidence_cases"] == 20


def test_benchmark_cli_writes_a_local_hashed_report(monkeypatch, tmp_path):
    module = _benchmark_module()
    root, index, questions = _fixture_index(tmp_path)
    output = tmp_path / "reports" / "measurement.json"
    monkeypatch.setattr(sys, "argv", [
        "repoground_vs_grep_read.py", "--index", str(index), "--repo-root", str(root),
        "--questions", str(questions), "--k", "1", "--out", str(output),
    ])

    assert module.main() == 0
    persisted = json.loads(output.read_text(encoding="utf-8"))
    assert persisted["status"] == "inconclusive"
    assert persisted["inputs"]["index_sha256"]
    assert persisted["aggregates"]["repoground"]["compaction"]["all_cases_pass"] is True


def test_benchmark_fails_closed_when_compaction_requirement_is_not_met(monkeypatch, tmp_path):
    module = _benchmark_module()
    root, index, questions = _fixture_index(tmp_path)
    monkeypatch.setattr(
        module,
        "_compact_repoground_response",
        lambda result, freshness: {"unnecessary": "x" * 50_000},
    )

    report = module.run(index, root, questions, k=1)

    assert report["status"] == "fail"
    assert report["acceptance"]["failure_reasons"] == ["compaction_below_60_percent"]
    assert report["aggregates"]["repoground"]["compaction"]["all_cases_pass"] is False


def test_benchmark_recommends_only_a_named_safe_benefit(monkeypatch, tmp_path):
    module = _benchmark_module()
    root, index, questions = _fixture_index(tmp_path)

    def empty_grep_read(_root, question, k):
        return {"query": question, "k": k, "status": "available", "paths": [], "reads": []}, 1, 0

    monkeypatch.setattr(module, "_grep_read", empty_grep_read)
    report = module.run(index, root, questions, k=1)

    assert report["status"] == "pass"
    assert report["acceptance"]["recommended_categories"] == ["fixture"]
    assert report["acceptance"]["preference_recommendation"] == "repoground"
    assert report["category_decisions"]["fixture"]["evidence_safe"] is True
    assert report["category_decisions"]["fixture"]["measurable_benefit"] is True


def test_benchmark_fails_on_quality_regression(monkeypatch, tmp_path):
    module = _benchmark_module()
    root, index, questions = _fixture_index(tmp_path)
    (root / "missing.py").write_text("# baseline-only target\n", encoding="utf-8")
    questions.write_text(json.dumps([
        {"query": "widget", "category": "fixture", "expected_patterns": ["src/widget.py", "missing.py"]}
        for _ in range(20)
    ]), encoding="utf-8")

    def perfect_grep_read(_root, question, k):
        return {
            "query": question, "k": k, "status": "available",
            "paths": ["src/widget.py", "missing.py"], "reads": [],
        }, 1, 0

    monkeypatch.setattr(module, "_grep_read", perfect_grep_read)
    report = module.run(index, root, questions, k=1)

    assert report["status"] == "fail"
    assert report["acceptance"]["failure_reasons"] == ["quality_or_freshness_regression"]
