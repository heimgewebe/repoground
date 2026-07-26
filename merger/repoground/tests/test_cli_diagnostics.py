from __future__ import annotations

import json
from pathlib import Path

import pytest

from merger.repoground.core import answer_grounding_delta
from merger.repoground.retrieval import eval_diagnostics_integration
from merger.repoground.cli.main import main


def _write_json(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _run(capsys, args: list[str]) -> tuple[int, dict]:
    code = main(["diagnostics", *args])
    captured = capsys.readouterr()
    assert captured.err == ""
    return code, json.loads(captured.out)


def _range(content_hash: str = "a" * 64) -> dict:
    return {
        "file_path": "demo.md",
        "start_byte": 0,
        "end_byte": 12,
        "start_line": 1,
        "end_line": 2,
        "content_sha256": content_hash,
    }


def test_diagnostics_help_is_forwarded_to_the_lazy_parser(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main(["diagnostics", "--help"])

    captured = capsys.readouterr()
    assert exc_info.value.code == 0
    assert "answer-delta" in captured.out
    assert captured.err == ""


def test_history_lens_is_available_as_explicit_cli(tmp_path, capsys):
    records = _write_json(
        tmp_path / "records.json",
        [
            {"commit": "a" * 40, "path": "src/a.py", "author": "Ada"},
            {"commit": "b" * 40, "path": "src/a.py", "author": "Bob"},
        ],
    )

    code, result = _run(
        capsys,
        ["history-lens", "--records", str(records), "--profile", "summary"],
    )

    assert code == 0
    assert result["kind"] == "repobrief.history_lens"
    assert result["canonical_content_truth"] is False
    assert result["file_churn"] == [
        {"commit_count": 2, "navigation_only": True, "path": "src/a.py"}
    ]


def test_memory_build_and_recall_are_available_as_explicit_cli(tmp_path, capsys):
    citations = [
        {
            "citation_id": "cit_0000000000000001",
            "source_range": _range(),
        }
    ]
    citations_path = _write_json(tmp_path / "citations.json", citations)

    code, record = _run(
        capsys,
        [
            "memory-build",
            "--claim-text",
            "Claims require fresh citations.",
            "--citations",
            str(citations_path),
            "--snapshot-stem",
            "demo-snapshot",
            "--snapshot-hash",
            "b" * 64,
            "--freshness-status",
            "fresh",
        ],
    )
    assert code == 0
    assert record["kind"] == "repobrief.agent_memory_claim"

    record_path = _write_json(tmp_path / "memory.json", record)
    code, recall = _run(
        capsys,
        [
            "memory-check",
            "--memory-record",
            str(record_path),
            "--current-citations",
            str(citations_path),
            "--current-snapshot-hash",
            "b" * 64,
            "--current-freshness-status",
            "fresh",
        ],
    )

    assert code == 0
    assert recall["status"] == "usable"
    assert recall["usable_as_source_backed_memory"] is True
    assert recall["memory_is_source_truth"] is False


def test_audit_plan_and_finding_adapter_are_available_as_explicit_cli(tmp_path, capsys):
    code, plan = _run(
        capsys,
        [
            "audit-plan",
            "--changed-path",
            "src/auth/session.py",
            "--review-query",
            "permission boundary",
        ],
    )
    assert code == 0
    assert plan["version"] == "audit_lane_plan.v1"
    assert plan["authority"] == "navigation_index"

    citation_id = "cit_0000000000000001"
    plan_path = _write_json(tmp_path / "plan.json", plan)
    candidates_path = _write_json(
        tmp_path / "candidates.json",
        [
            {
                "lane_id": plan["lanes"][0]["id"],
                "claim": "The authority boundary needs independent verification.",
                "citation_ids": [citation_id],
            }
        ],
    )
    citation_ids_path = _write_json(tmp_path / "citation-ids.json", [citation_id])

    code, findings = _run(
        capsys,
        [
            "audit-findings",
            "--plan",
            str(plan_path),
            "--candidates",
            str(candidates_path),
            "--reviewed-revision",
            "c" * 40,
            "--current-revision",
            "c" * 40,
            "--citation-ids",
            str(citation_ids_path),
        ],
    )

    assert code == 0
    assert findings["version"] == "audit_finding_set.v2"
    assert findings["revision_fresh"] is True
    assert findings["findings"][0]["state"] == "candidate"


def test_answer_delta_cli_delegates_to_read_only_domain_surface(
    tmp_path, capsys, monkeypatch
):
    declaration = _write_json(tmp_path / "declaration.json", {"used_citations": []})
    seen = {}

    def fake_check(value, *, new_bundle_manifest, new_citation_map):
        seen.update(
            value=value,
            manifest=new_bundle_manifest,
            citation_map=new_citation_map,
        )
        return {"kind": "repobrief.answer_grounding_delta_verdict", "status": "valid"}

    monkeypatch.setattr(
        answer_grounding_delta, "check_answer_grounding_delta", fake_check
    )

    code, result = _run(
        capsys,
        [
            "answer-delta",
            "--old-declaration",
            str(declaration),
            "--new-bundle-manifest",
            "bundle.manifest.json",
            "--new-citation-map",
            "citations.jsonl",
        ],
    )

    assert code == 0
    assert result["status"] == "valid"
    assert seen == {
        "value": {"used_citations": []},
        "manifest": "bundle.manifest.json",
        "citation_map": "citations.jsonl",
    }


def test_eval_report_cli_delegates_without_changing_metrics(
    tmp_path, capsys, monkeypatch
):
    eval_results = _write_json(
        tmp_path / "eval.json",
        {"metrics": {"recall@10": 50.0}, "details": []},
    )
    seen = {}

    def fake_integrate(value, *, index_path, canonical_path, citation_path):
        seen.update(
            value=value,
            index_path=index_path,
            canonical_path=canonical_path,
            citation_path=citation_path,
        )
        return {"eval_results": value, "diagnostics_report": {"status": "diagnostic"}}

    monkeypatch.setattr(
        eval_diagnostics_integration,
        "integrate_diagnostics_with_eval_results",
        fake_integrate,
    )

    code, result = _run(
        capsys,
        [
            "eval-report",
            "--eval-results",
            str(eval_results),
            "--index",
            "chunk-index.jsonl",
        ],
    )

    assert code == 0
    assert result["eval_results"]["metrics"]["recall@10"] == 50.0
    assert seen["index_path"] == Path("chunk-index.jsonl")
    assert seen["canonical_path"] is None
    assert seen["citation_path"] is None


def test_json_inputs_reject_symbolic_links(tmp_path, capsys):
    target = _write_json(tmp_path / "records.json", [])
    link = tmp_path / "records-link.json"
    link.symlink_to(target)

    code = main(
        [
            "diagnostics",
            "history-lens",
            "--records",
            str(link),
        ]
    )
    captured = capsys.readouterr()

    assert code == 2
    assert captured.out == ""
    assert "refusing symbolic-link input" in captured.err
