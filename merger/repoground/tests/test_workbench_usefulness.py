from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from merger.repoground.cli.main import main
from merger.repoground.core.workbench_usefulness import (
    _baseline_guardrails_visible,
    evaluate_workbench_usefulness,
)
from merger.repoground.tests.test_readonly_adapter import _adapter

ROOT = Path(__file__).resolve().parents[3]
SCHEMA = ROOT / "merger/repoground/contracts/repobrief-workbench-usefulness-goldset.v1.schema.json"


def _goldset(tmp_path: Path) -> Path:
    questions = []
    for ordinal in range(5):
        questions.append(
            {
                "id": f"demo-{ordinal}",
                "query": "hello",
                "symbol_query": "hello_adapter",
                "expected_paths": ["brief.md", "src/demo.py"],
                "expected_symbols": ["hello_adapter"],
            }
        )
    path = tmp_path / "goldset.json"
    path.write_text(
        json.dumps(
            {
                "kind": "repobrief.workbench_usefulness_goldset",
                "version": "1.0",
                "questions": questions,
                "does_not_establish": ["agent_quality_improvement"],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_baseline_guardrail_detection_accepts_human_and_machine_terms() -> None:
    text = (
        "This does not prove repo understanding, test_sufficiency, "
        "or merge readiness."
    )
    assert _baseline_guardrails_visible(text) is True


def test_repository_goldset_matches_schema() -> None:
    goldset = ROOT / "docs/retrieval/workbench_usefulness_goldset.v1.json"
    jsonschema.validate(
        json.loads(goldset.read_text(encoding="utf-8")),
        json.loads(SCHEMA.read_text(encoding="utf-8")),
    )


# Retired product names. ``kind`` (e.g. "repobrief.workbench_usefulness_goldset")
# is a deliberate, separately-checked versioned data id exception (see
# docs/contracts/repoground-naming-hard-cut.v1.json) and is intentionally not
# scanned here; every other question field describes a live class/file/CLI
# surface and must track the current name.
RETIRED_PRODUCT_TERMS = ("lenskit", "repobrief", "repolens", "rlens")
_NAMING_SCAN_FIELDS = (
    "query",
    "symbol_query",
    "symbol_path_filter",
    "expected_paths",
    "expected_symbols",
)


def test_repository_goldset_questions_do_not_describe_retired_products_as_current() -> None:
    goldset = json.loads(
        (ROOT / "docs/retrieval/workbench_usefulness_goldset.v1.json").read_text(encoding="utf-8")
    )

    offenders: list[str] = []
    for question in goldset["questions"]:
        for field in _NAMING_SCAN_FIELDS:
            value = question.get(field)
            texts = value if isinstance(value, list) else [value]
            for text in texts:
                if not isinstance(text, str):
                    continue
                lowered = text.casefold()
                for term in RETIRED_PRODUCT_TERMS:
                    if term in lowered:
                        offenders.append(
                            f"question {question.get('id')!r} field {field!r}: {text!r} contains {term!r}"
                        )

    assert offenders == [], "retired product name found in active goldset question: " + "; ".join(offenders)


def test_eval_measures_navigation_advantage_without_default_promotion(tmp_path: Path) -> None:
    _adapter_instance, _bundle, config = _adapter(tmp_path)
    result = evaluate_workbench_usefulness(
        config,
        snapshot_id="demo",
        goldset_path=_goldset(tmp_path),
        k=5,
    )

    assert result["status"] == "pass"
    assert result["comparison"]["baseline"]["target_recall"] < 1.0
    assert result["comparison"]["workbench"]["target_recall"] == 1.0
    assert result["comparison"]["target_recall_advantage"] >= 0.20
    assert result["decision"]["navigation_utility_established_for_goldset"] is True
    assert result["decision"]["workbench_default_promoted"] is False
    assert result["dimensions"]["false_confidence_risk"]["guardrail_omission_rate"] == 0.0
    assert result["dimensions"]["false_confidence_risk"]["behavioral_false_confidence"].startswith("not_measured")
    assert result["dimensions"]["missing_evidence_visibility"]["workbench_report_visibility_rate"] == 1.0
    assert result["dimensions"]["agent_answer_compliance"]["structured_context_compliance_rate"] == 1.0
    assert result["dimensions"]["agent_answer_compliance"]["natural_language_answer_compliance"].startswith("not_measured")
    assert result["false_confidence_measurement"]["status"] == "proxy_only"
    assert result["answer_compliance_measurement"]["status"] == "structured_context_only"
    assert "agent_quality_improvement" in result["does_not_establish"]


def test_eval_rejects_too_small_goldset(tmp_path: Path) -> None:
    _adapter_instance, _bundle, config = _adapter(tmp_path)
    goldset = _goldset(tmp_path)
    data = json.loads(goldset.read_text(encoding="utf-8"))
    data["questions"] = data["questions"][:4]
    goldset.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValueError, match="at least five questions"):
        evaluate_workbench_usefulness(
            config,
            snapshot_id="demo",
            goldset_path=goldset,
        )


def test_eval_cli_emits_reproducible_report(tmp_path: Path, capsys) -> None:
    _adapter_instance, _bundle, config = _adapter(tmp_path)
    goldset = _goldset(tmp_path)

    rc = main(
        [
            "ground",
            "workbench-eval",
            "--config",
            str(config),
            "--snapshot-id",
            "demo",
            "--goldset",
            str(goldset),
            "--k",
            "5",
        ]
    )

    assert rc == 0
    result = json.loads(capsys.readouterr().out)
    assert result["kind"] == "repobrief.workbench_usefulness_eval"
    assert result["goldset"]["question_count"] == 5
