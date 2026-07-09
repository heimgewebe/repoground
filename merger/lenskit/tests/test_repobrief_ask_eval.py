import json
from pathlib import Path

from merger.lenskit.cli.main import main
from merger.lenskit.core.repobrief_ask import build_ask_context_pack
from merger.lenskit.core.repobrief_ask_eval import evaluate_ask_goldset
from merger.lenskit.tests.test_repobrief_ask_cli import _complete_basic_bundle


def _write_goldset(path: Path, *, expected_paths=None, expected_citation_ids=None) -> Path:
    path.write_text(
        json.dumps({
            "kind": "repobrief.ask_goldset",
            "version": "1.0",
            "queries": [
                {
                    "id": "q1",
                    "query": "hello",
                    "task_profile": "basic_repo_question",
                    "expected_paths": expected_paths if expected_paths is not None else ["brief.md"],
                    "expected_citation_ids": expected_citation_ids if expected_citation_ids is not None else [],
                }
            ],
            "does_not_establish": [
                "answer_correctness",
                "repo_understood",
                "retrieval_quality_sufficient",
                "default_promotion_safe",
            ],
        }),
        encoding="utf-8",
    )
    return path


def test_ask_context_pack_carries_citation_id_for_eval(tmp_path):
    bundle = _complete_basic_bundle(tmp_path)

    pack = build_ask_context_pack(bundle["manifest"], query="hello")

    assert pack["retrieval_hits"][0]["citation_id"].startswith("cit_")


def test_evaluate_ask_goldset_reports_core_metrics_and_miss_taxonomy(tmp_path):
    bundle = _complete_basic_bundle(tmp_path)
    goldset = _write_goldset(tmp_path / "ask_goldset.json")

    report = evaluate_ask_goldset(bundle["manifest"], goldset)

    assert report["kind"] == "repobrief.ask_eval"
    assert report["status"] == "warn"  # pass results, but no baseline for promotion decision
    assert report["metrics"]["query_count"] == 1
    assert report["metrics"]["expected_path_recall"] == 1.0
    assert report["metrics"]["required_reading_coverage"] == 1.0
    assert report["metrics"]["mrr_at_k"] == 1.0
    assert report["miss_taxonomy"]["missing_expected_path"] == 0
    assert report["promotion_gate"]["status"] == "warn"
    assert report["promotion_gate"]["requires_no_central_query_regression"] is True
    assert report["promotion_gate"]["requires_documented_measurement_advantage"] is True
    assert "retrieval_quality_sufficient" in report["does_not_establish"]


def test_evaluate_ask_goldset_reports_citation_coverage(tmp_path):
    bundle = _complete_basic_bundle(tmp_path)
    citation_id = build_ask_context_pack(bundle["manifest"], query="hello")["retrieval_hits"][0]["citation_id"]
    goldset = _write_goldset(tmp_path / "ask_goldset.json", expected_citation_ids=[citation_id])

    report = evaluate_ask_goldset(bundle["manifest"], goldset)

    assert report["metrics"]["citation_coverage"] == 1.0
    assert report["miss_taxonomy"]["missing_expected_citation"] == 0


def test_evaluate_ask_goldset_fails_missing_expected_path(tmp_path):
    bundle = _complete_basic_bundle(tmp_path)
    goldset = _write_goldset(tmp_path / "ask_goldset.json", expected_paths=["missing.md"])

    report = evaluate_ask_goldset(bundle["manifest"], goldset)

    assert report["status"] == "fail"
    assert report["metrics"]["expected_path_recall"] == 0.0
    assert report["miss_taxonomy"]["missing_expected_path"] == 1
    assert report["results"][0]["missing_paths"] == ["missing.md"]


def test_evaluate_ask_goldset_promotion_gate_with_baseline_advantage(tmp_path):
    bundle = _complete_basic_bundle(tmp_path)
    goldset = _write_goldset(tmp_path / "ask_goldset.json")
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps({
            "metrics": {
                "expected_path_recall": 0.5,
                "citation_coverage": 0.0,
                "required_reading_coverage": 1.0,
                "mrr_at_k": 0.5,
            }
        }),
        encoding="utf-8",
    )

    report = evaluate_ask_goldset(bundle["manifest"], goldset, baseline_path=baseline)

    assert report["status"] == "pass"
    assert report["promotion_gate"]["status"] == "pass"
    assert report["promotion_gate"]["eligible"] is True
    assert report["promotion_gate"]["measurement_advantage"] > 0


def test_repobrief_ask_eval_cli_emits_report(tmp_path, capsys):
    bundle = _complete_basic_bundle(tmp_path)
    goldset = _write_goldset(tmp_path / "ask_goldset.json")

    rc = main([
        "repobrief",
        "ask-eval",
        "--bundle-manifest",
        str(bundle["manifest"]),
        "--goldset",
        str(goldset),
    ])

    captured = capsys.readouterr()
    assert rc == 0
    report = json.loads(captured.out)
    assert report["kind"] == "repobrief.ask_eval"
    assert report["metrics"]["expected_path_recall"] == 1.0
