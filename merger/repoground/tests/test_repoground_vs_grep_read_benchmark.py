import importlib.util
import json
import sys
from pathlib import Path

from merger.repoground.retrieval import index_db


VISIBLE_SOURCE = "def widget():\n    return 'widget'\n"


def _benchmark_module():
    root = Path(__file__).resolve().parents[3]
    path = root / "scripts/benchmarks/repoground_vs_grep_read.py"
    spec = importlib.util.spec_from_file_location("repoground_vs_grep_read", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fixture_index(tmp_path, *, indexed_content=VISIBLE_SOURCE):
    root = tmp_path / "repo"
    source = root / "src/widget.py"
    source.parent.mkdir(parents=True)
    source.write_text(VISIBLE_SOURCE, encoding="utf-8")
    dump = tmp_path / "dump.json"
    chunks = tmp_path / "chunks.jsonl"
    index = tmp_path / "fixture.index.sqlite"
    dump.write_text("{}", encoding="utf-8")
    chunks.write_text(json.dumps({
        "chunk_id": "widget", "repo_id": "fixture", "path": "src/widget.py",
        "content": indexed_content, "start_line": 1, "end_line": 2,
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

    assert report["version"] == "v4"
    assert report["status"] == "inconclusive"
    assert len(report["cases"]) == 20
    assert report["acceptance"]["same_question_set"] is True
    assert report["acceptance"]["same_k"] == 1
    configuration = report["configuration"]
    assert configuration["legacy_expected_pattern_contract"] == "all=>path"
    assert configuration["default_question_contract"] == "expected_patterns"
    assert configuration["opt_in_question_contract"] == "expected_paths+expected_evidence"
    assert configuration["source_evidence_scoring"] == "condition_visible_payload"
    assert configuration["evidence_path_binding"] == "matched_expected_paths_only"
    assert configuration["repoground_visible_payload"] == "selected_index_chunk_content"
    assert configuration["grep_read_token_selection"] == "deduped_nonframing_query_terms"
    assert configuration["grep_read_path_ranking"] == (
        "distinct_query_term_matches_desc_then_path_term_matches_desc_then_path"
    )
    assert configuration["benchmark_leakage_exclusion_globs"]
    assert set(report["inputs"]) >= {
        "benchmark_script_sha256", "index_sha256", "questions_sha256", "repo_tree_sha256",
    }
    assert report["inputs"]["repo_root"] == "."
    assert report["inputs"]["index_path"] == index.name
    assert report["inputs"]["absolute_paths_persisted"] is False
    assert str(tmp_path) not in json.dumps(report["inputs"])
    for case in report["cases"]:
        assert case["k"] == 1
        for condition in ("repoground", "grep_read"):
            measurement = case[condition]
            assert set(measurement) >= {
                "runtime_ms", "tool_calls", "process_calls", "response_bytes",
                "token_proxy", "source_index_freshness", "false_confidence",
            }
        assert case["grep_read"]["search_engine"] in {"ripgrep", "python_utf8_substring"}
        assert case["repoground"]["compaction"]["pass"] is True
        assert case["repoground"]["false_confidence"] is False
    assert report["aggregates"]["repoground"]["compaction"]["aggregate_pass"] is True


def test_legacy_expected_patterns_preserve_root_level_path_targets():
    module = _benchmark_module()
    paths, evidence = module._expected_contract({
        "expected_patterns": ["missing.py", "README", "src/widget.py"],
    })
    assert paths == ["missing.py", "README", "src/widget.py"]
    assert evidence == []


def test_benchmark_separates_locator_and_source_evidence_targets(tmp_path):
    module = _benchmark_module()
    root, index, questions = _fixture_index(tmp_path)
    questions.write_text(json.dumps([
        {
            "query": "widget", "category": "fixture",
            "expected_paths": ["src/widget.py"], "expected_evidence": ["def widget"],
        }
        for _ in range(20)
    ]), encoding="utf-8")
    report = module.run(index, root, questions, k=1)

    for condition in ("repoground", "grep_read"):
        targets = report["cases"][0][condition]["expected_targets"]
        assert targets["paths"]["found"] == ["src/widget.py"]
        assert targets["source_evidence"]["found"] == ["def widget"]
        assert targets["source_evidence"]["missing"] == []
        assert report["cases"][0][condition]["false_confidence"] is False


def test_source_evidence_cannot_use_text_outside_condition_payload(tmp_path):
    module = _benchmark_module()
    root, index, questions = _fixture_index(tmp_path, indexed_content="widget implementation")
    questions.write_text(json.dumps([
        {
            "query": "widget", "category": "fixture",
            "expected_paths": ["src/widget.py"], "expected_evidence": ["def widget"],
        }
        for _ in range(20)
    ]), encoding="utf-8")
    report = module.run(index, root, questions, k=1)

    repo_targets = report["cases"][0]["repoground"]["expected_targets"]
    grep_targets = report["cases"][0]["grep_read"]["expected_targets"]
    assert repo_targets["source_evidence"]["missing"] == ["def widget"]
    assert report["cases"][0]["repoground"]["false_confidence"] is True
    assert grep_targets["source_evidence"]["found"] == ["def widget"]


def test_source_evidence_cannot_leak_from_unrelated_visible_path():
    module = _benchmark_module()
    targets = module._expected_targets(
        ["src/widget.py", "src/unrelated.py"],
        [
            ("src/widget.py", "widget implementation"),
            ("src/unrelated.py", "def widget(): pass"),
        ],
        ["src/widget.py"],
        ["def widget"],
    )

    assert targets["paths"]["found"] == ["src/widget.py"]
    assert targets["source_evidence"]["found"] == []
    assert targets["source_evidence"]["missing"] == ["def widget"]


def test_benchmark_marks_missing_source_evidence_as_false_confidence(tmp_path):
    module = _benchmark_module()
    root, index, questions = _fixture_index(tmp_path)
    questions.write_text(json.dumps([
        {
            "query": "widget", "category": "fixture",
            "expected_paths": ["src/widget.py"], "expected_evidence": ["def missing_widget"],
        }
        for _ in range(20)
    ]), encoding="utf-8")
    report = module.run(index, root, questions, k=1)

    for condition in ("repoground", "grep_read"):
        targets = report["cases"][0][condition]["expected_targets"]
        assert targets["paths"]["missing"] == []
        assert targets["source_evidence"]["missing"] == ["def missing_widget"]
        assert report["cases"][0][condition]["false_confidence"] is True
        assert report["aggregates"][condition]["false_confidence_cases"] == 20


def test_benchmark_defines_false_confidence_for_missing_targets_or_stale_sources(tmp_path):
    module = _benchmark_module()
    root, index, questions = _fixture_index(tmp_path)
    questions.write_text(json.dumps([
        {"query": "widget", "expected_paths": ["src/widget.py", "missing.py"], "expected_evidence": []}
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
    monkeypatch.setattr(module, "_compact_repoground_response", lambda result, freshness: {"unnecessary": "x" * 50_000})
    report = module.run(index, root, questions, k=1)
    assert report["status"] == "fail"
    assert report["acceptance"]["failure_reasons"] == ["compaction_below_60_percent"]
    assert report["aggregates"]["repoground"]["compaction"]["all_cases_pass"] is False


def test_benchmark_recommends_only_a_named_safe_benefit(monkeypatch, tmp_path):
    module = _benchmark_module()
    root, index, questions = _fixture_index(tmp_path)

    def empty_grep_read(_root, question, k, *, excluded_paths=None):
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
        {
            "query": "widget", "category": "fixture",
            "expected_paths": ["src/widget.py", "missing.py"], "expected_evidence": [],
        }
        for _ in range(20)
    ]), encoding="utf-8")

    def perfect_grep_read(_root, question, k, *, excluded_paths=None):
        return {
            "query": question, "k": k, "status": "available",
            "paths": ["src/widget.py", "missing.py"], "reads": [],
        }, 1, 0

    monkeypatch.setattr(module, "_grep_read", perfect_grep_read)
    report = module.run(index, root, questions, k=1)
    assert report["status"] == "fail"
    assert report["acceptance"]["failure_reasons"] == ["quality_or_freshness_regression"]


def test_benchmark_uses_python_fallback_without_ripgrep(monkeypatch, tmp_path):
    module = _benchmark_module()
    root, _, _ = _fixture_index(tmp_path)
    monkeypatch.setattr(module.shutil, "which", lambda _name: None)
    result, process_calls, read_calls = module._grep_read(root, "widget", 1)
    assert result["search_engine"] == "python_utf8_substring"
    assert result["paths"] == ["src/widget.py"]
    assert result["reads"] == [{
        "path": "src/widget.py", "bytes_read": len(VISIBLE_SOURCE.encode("utf-8")),
        "content": VISIBLE_SOURCE,
    }]
    assert process_calls == 0
    assert read_calls == 1


def test_grep_read_ranks_all_meaningful_terms_instead_of_first_instruction_word(
    monkeypatch, tmp_path
):
    module = _benchmark_module()
    root = tmp_path / "repo"
    target = root / "src/agent_reading_pack.py"
    target.parent.mkdir(parents=True)
    target.write_text("agent reading pack producer tests\n", encoding="utf-8")
    for ordinal in range(12):
        decoy = root / "docs" / f"find-{ordinal:02d}.md"
        decoy.parent.mkdir(parents=True, exist_ok=True)
        decoy.write_text("find only\n", encoding="utf-8")

    monkeypatch.setattr(module.shutil, "which", lambda _name: None)
    result, process_calls, read_calls = module._grep_read(
        root, "Find the Agent Reading Pack producer and its primary tests", 1
    )

    assert result["query_terms"] == ["agent", "reading", "pack", "producer", "tests"]
    assert result["paths"] == ["src/agent_reading_pack.py"]
    assert process_calls == 0
    assert read_calls == 1


def test_benchmark_excludes_self_measurement_artifacts_from_both_conditions(
    monkeypatch, tmp_path
):
    module = _benchmark_module()
    root, index, questions = _fixture_index(tmp_path)
    leak_question = root / "docs/retrieval/review_queries.v1.json"
    leak_question.parent.mkdir(parents=True)
    leak_question.write_text("widget\n", encoding="utf-8")
    leak_proof = root / "docs/proofs/repoground-vs-grep-read.v2.json"
    leak_proof.parent.mkdir(parents=True)
    leak_proof.write_text("widget\n", encoding="utf-8")

    seen_exclusions = []
    real_execute = module._execute_review_query

    def capture_execute(*args, **kwargs):
        seen_exclusions.extend(kwargs.get("excluded_paths") or [])
        return real_execute(*args, **kwargs)

    monkeypatch.setattr(module, "_execute_review_query", capture_execute)
    monkeypatch.setattr(module.shutil, "which", lambda _name: None)
    report = module.run(index, root, questions, k=1)

    expected_exclusions = {
        "docs/retrieval/review_queries.v1.json",
        "docs/proofs/repoground-vs-grep-read.v2.json",
    }
    assert expected_exclusions <= set(seen_exclusions)
    assert expected_exclusions <= set(report["inputs"]["benchmark_excluded_paths"])
    assert report["cases"][0]["grep_read"]["paths"] == ["src/widget.py"]
    assert not expected_exclusions.intersection(report["cases"][0]["repoground"]["paths"])
