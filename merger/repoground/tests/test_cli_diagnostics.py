from __future__ import annotations

import json
from pathlib import Path

import pytest

from merger.repoground.cli import cmd_diagnostics
from merger.repoground.cli.main import main
from merger.repoground.core import answer_grounding_delta
from merger.repoground.retrieval import diagnostics_json, eval_diagnostics_integration


def _write_json(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _write_bundle_manifest(path: Path) -> Path:
    return _write_json(
        path,
        {
            "kind": "repolens.bundle.manifest",
            "version": "1.0",
            "run_id": "diagnostics-test",
            "artifacts": [],
            "links": {},
            "capabilities": {},
        },
    )


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
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    manifest = _write_bundle_manifest(bundle_dir / "bundle.manifest.json")
    bundle_link = tmp_path / "bundle-link"
    bundle_link.symlink_to(bundle_dir, target_is_directory=True)
    citation_map = tmp_path / "citations.jsonl"
    citation_map.write_text(
        json.dumps({"citation_id": "cit_0000000000000001"}) + "\n",
        encoding="utf-8",
    )
    seen = {}
    manifest_reads = 0
    real_read_input_payload = cmd_diagnostics._read_input_payload

    def tracked_read_input_payload(path_value):
        nonlocal manifest_reads
        anchored_path, payload = real_read_input_payload(path_value)
        if anchored_path == manifest:
            manifest_reads += 1
        return anchored_path, payload

    def fake_check(
        value,
        *,
        new_bundle_manifest,
        new_bundle_manifest_data,
        new_citation_map,
        new_citation_entries,
    ):
        seen.update(
            value=value,
            manifest=new_bundle_manifest,
            manifest_data=new_bundle_manifest_data,
            citation_map=new_citation_map,
            citation_entries=new_citation_entries,
        )
        return {"kind": "repobrief.answer_grounding_delta_verdict", "status": "valid"}

    monkeypatch.setattr(
        answer_grounding_delta, "check_answer_grounding_delta", fake_check
    )
    monkeypatch.setattr(
        cmd_diagnostics,
        "_read_input_payload",
        tracked_read_input_payload,
    )
    monkeypatch.chdir(tmp_path)

    code, result = _run(
        capsys,
        [
            "answer-delta",
            "--old-declaration",
            str(declaration),
            "--new-bundle-manifest",
            str(Path(bundle_link.name) / manifest.name),
            "--new-citation-map",
            str(citation_map),
        ],
    )

    assert code == 0
    assert result["status"] == "valid"
    assert manifest_reads == 1
    assert seen == {
        "value": {"used_citations": []},
        "manifest": manifest,
        "manifest_data": {
            "kind": "repolens.bundle.manifest",
            "version": "1.0",
            "run_id": "diagnostics-test",
            "artifacts": [],
            "links": {},
            "capabilities": {},
        },
        "citation_map": str(citation_map),
        "citation_entries": {
            "cit_0000000000000001": {"citation_id": "cit_0000000000000001"}
        },
    }


def test_answer_delta_requires_citation_map_for_declared_citations(
    tmp_path,
    capsys,
):
    declaration = _write_json(
        tmp_path / "declaration.json",
        {"used_citations": [{"citation_id": "cit_0000000000000001"}]},
    )

    code = main(
        [
            "diagnostics",
            "answer-delta",
            "--old-declaration",
            str(declaration),
            "--new-bundle-manifest",
            "not-read.bundle.manifest.json",
        ]
    )
    captured = capsys.readouterr()

    assert code == 2
    assert captured.out == ""
    assert (
        "--new-citation-map is required when old declaration "
        "used_citations is non-empty"
    ) in captured.err
    assert "Traceback" not in captured.err


@pytest.mark.parametrize("declaration", [{}, {"used_citations": []}])
def test_answer_delta_allows_empty_or_missing_citations_without_map(
    tmp_path,
    capsys,
    declaration,
):
    declaration_path = _write_json(tmp_path / "declaration.json", declaration)
    manifest = _write_bundle_manifest(tmp_path / "bundle.manifest.json")

    code, result = _run(
        capsys,
        [
            "answer-delta",
            "--old-declaration",
            str(declaration_path),
            "--new-bundle-manifest",
            str(manifest),
        ],
    )

    assert code == 0
    assert result["status"] == "not_comparable"


def test_answer_delta_manifest_rejects_symbolic_link_without_traceback(
    tmp_path,
    capsys,
):
    declaration = _write_json(tmp_path / "declaration.json", {})
    target = _write_bundle_manifest(tmp_path / "bundle.manifest.json")
    link = tmp_path / "bundle-link.manifest.json"
    link.symlink_to(target)

    code = main(
        [
            "diagnostics",
            "answer-delta",
            "--old-declaration",
            str(declaration),
            "--new-bundle-manifest",
            str(link),
        ]
    )
    captured = capsys.readouterr()

    assert code == 2
    assert captured.out == ""
    assert "refusing symbolic-link input" in captured.err
    assert "Traceback" not in captured.err


def test_answer_delta_manifest_rejects_non_finite_json_without_traceback(
    tmp_path,
    capsys,
):
    declaration = _write_json(tmp_path / "declaration.json", {})
    manifest = tmp_path / "bundle.manifest.json"
    manifest.write_text(
        '{"kind":"repolens.bundle.manifest","diagnostic_value":NaN}',
        encoding="utf-8",
    )

    code = main(
        [
            "diagnostics",
            "answer-delta",
            "--old-declaration",
            str(declaration),
            "--new-bundle-manifest",
            str(manifest),
        ]
    )
    captured = capsys.readouterr()

    assert code == 2
    assert captured.out == ""
    assert "non-finite JSON constant 'NaN'" in captured.err
    assert "Traceback" not in captured.err


def test_answer_delta_manifest_rejects_oversized_input_without_traceback(
    tmp_path,
    capsys,
):
    declaration = _write_json(tmp_path / "declaration.json", {})
    manifest = tmp_path / "bundle.manifest.json"
    manifest.write_bytes(b"x" * (cmd_diagnostics._MAX_JSON_BYTES + 1))

    code = main(
        [
            "diagnostics",
            "answer-delta",
            "--old-declaration",
            str(declaration),
            "--new-bundle-manifest",
            str(manifest),
        ]
    )
    captured = capsys.readouterr()

    assert code == 2
    assert captured.out == ""
    assert f"input exceeds {cmd_diagnostics._MAX_JSON_BYTES} bytes" in captured.err
    assert "Traceback" not in captured.err


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


def test_json_input_recursion_errors_exit_two_without_traceback(
    tmp_path,
    capsys,
    monkeypatch,
):
    records = tmp_path / "records.json"
    records.write_text("[]", encoding="utf-8")

    def raise_recursion_error(*_args, **_kwargs):
        raise RecursionError("forced recursion limit")

    monkeypatch.setattr(diagnostics_json.json, "loads", raise_recursion_error)

    code = main(
        [
            "diagnostics",
            "history-lens",
            "--records",
            str(records),
        ]
    )
    captured = capsys.readouterr()

    assert code == 2
    assert captured.out == ""
    assert "exceeds the supported JSON nesting depth" in captured.err
    assert "Traceback" not in captured.err


def test_json_inputs_reject_nesting_beyond_deterministic_limit_without_traceback(
    tmp_path,
    capsys,
):
    records = tmp_path / "records.json"
    nesting_depth = diagnostics_json.MAX_JSON_NESTING_DEPTH + 1
    records.write_text(
        "[" * nesting_depth + "0" + "]" * nesting_depth,
        encoding="utf-8",
    )

    code = main(
        [
            "diagnostics",
            "history-lens",
            "--records",
            str(records),
        ]
    )
    captured = capsys.readouterr()

    assert code == 2
    assert captured.out == ""
    assert captured.err.startswith("Error: ")
    assert "exceeds the supported JSON nesting depth" in captured.err
    assert "Traceback" not in captured.err


def test_json_nesting_ignores_brackets_in_escaped_strings(tmp_path, capsys):
    bracket_count = diagnostics_json.MAX_JSON_NESTING_DEPTH + 1
    bracket_text = 'escaped backslash and quote: \\" ' + "[{" * bracket_count
    records = _write_json(
        tmp_path / "records.json",
        [{"commit": "a" * 40, "path": "src/a.py", "author": bracket_text}],
    )

    code, result = _run(
        capsys,
        ["history-lens", "--records", str(records), "--profile", "summary"],
    )

    assert code == 0
    assert result["kind"] == "repobrief.history_lens"


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_json_inputs_reject_non_finite_constants_without_traceback(
    tmp_path,
    capsys,
    constant,
):
    records = tmp_path / "records.json"
    records.write_text(f'[{{"diagnostic_value": {constant}}}]', encoding="utf-8")

    code = main(
        [
            "diagnostics",
            "history-lens",
            "--records",
            str(records),
        ]
    )
    captured = capsys.readouterr()

    assert code == 2
    assert captured.out == ""
    assert f"non-finite JSON constant {constant!r}" in captured.err
    assert "Traceback" not in captured.err


def test_history_lens_rejects_non_object_records_without_traceback(tmp_path, capsys):
    records = _write_json(tmp_path / "records.json", [1])

    code = main(
        [
            "diagnostics",
            "history-lens",
            "--records",
            str(records),
        ]
    )
    captured = capsys.readouterr()

    assert code == 2
    assert captured.out == ""
    assert "records[0] must be JSON dict, got int" in captured.err
    assert "Traceback" not in captured.err


def test_eval_report_rejects_non_object_details_without_traceback(tmp_path, capsys):
    eval_results = _write_json(
        tmp_path / "eval.json",
        {"metrics": {}, "details": [1]},
    )

    code = main(
        [
            "diagnostics",
            "eval-report",
            "--eval-results",
            str(eval_results),
        ]
    )
    captured = capsys.readouterr()

    assert code == 2
    assert captured.out == ""
    assert "Expected retrieval_eval['details'][0] to be an object" in captured.err
    assert "Traceback" not in captured.err


def test_eval_report_rejects_non_object_index_records_without_traceback(
    tmp_path, capsys
):
    eval_results = _write_json(
        tmp_path / "eval.json",
        {
            "metrics": {"recall@10": 0.0},
            "details": [
                {
                    "query": "session authority",
                    "expected": ["src/auth/session.py"],
                    "is_relevant": False,
                    "found_count": 0,
                    "top_results": [],
                }
            ],
        },
    )
    index = tmp_path / "chunk-index.jsonl"
    index.write_text("[]\n", encoding="utf-8")

    code = main(
        [
            "diagnostics",
            "eval-report",
            "--eval-results",
            str(eval_results),
            "--index",
            str(index),
        ]
    )
    captured = capsys.readouterr()

    assert code == 2
    assert captured.out == ""
    assert "chunk index line 1 must be a JSON object" in captured.err
    assert "Traceback" not in captured.err


@pytest.mark.parametrize(
    ("field", "value", "expected_error"),
    [
        ("query", 7, "['query'] to be a string"),
        ("expected", "src/auth/session.py", "['expected'] to be a list of strings"),
        ("expected", [7], "['expected'][0] to be a string"),
        ("expected", [""], "['expected'][0] to be a non-empty string"),
        ("expected", ["   "], "['expected'][0] to be a non-empty string"),
        ("is_relevant", "false", "['is_relevant'] to be a boolean"),
        ("found_count", "0", "['found_count'] to be an integer"),
        ("found_count", True, "['found_count'] to be an integer"),
        ("found_count", -1, "['found_count'] to be non-negative"),
        (
            "top_results",
            "src/auth/session.py",
            "['top_results'] to be a list of strings",
        ),
        ("top_results", [7], "['top_results'][0] to be a string"),
        ("top_results", [""], "['top_results'][0] to be a non-empty string"),
        ("top_results", ["   "], "['top_results'][0] to be a non-empty string"),
    ],
)
def test_eval_report_rejects_invalid_detail_field_types_without_traceback(
    tmp_path,
    capsys,
    field,
    value,
    expected_error,
):
    detail = {
        "query": "session authority",
        "expected": ["src/auth/session.py"],
        "is_relevant": False,
        "found_count": 0,
        "top_results": [],
    }
    detail[field] = value
    eval_results = _write_json(
        tmp_path / "eval.json",
        {"metrics": {"recall@10": 0.0}, "details": [detail]},
    )

    code = main(
        [
            "diagnostics",
            "eval-report",
            "--eval-results",
            str(eval_results),
        ]
    )
    captured = capsys.readouterr()

    assert code == 2
    assert captured.out == ""
    assert expected_error in captured.err
    assert "Traceback" not in captured.err


@pytest.mark.parametrize(
    ("citation_line", "expected_error"),
    [
        ("[]", "citation map line 1 must be a JSON object"),
        (
            json.dumps({"citation_id": 7}),
            "citation map line 1 field 'citation_id' must be a non-empty string",
        ),
        (
            json.dumps({}),
            "citation map line 1 field 'citation_id' must be a non-empty string",
        ),
        (
            json.dumps({"citation_id": ""}),
            "citation map line 1 field 'citation_id' must be a non-empty string",
        ),
        (
            "\n".join(
                [
                    json.dumps({"citation_id": "duplicate"}),
                    json.dumps({"citation_id": "duplicate"}),
                ]
            ),
            "citation map line 2 duplicates citation_id 'duplicate'",
        ),
        ("{", "citation map line 1 must be valid JSON"),
    ],
)
def test_answer_delta_rejects_invalid_citation_map_records_without_traceback(
    tmp_path,
    capsys,
    citation_line,
    expected_error,
):
    declaration = _write_json(
        tmp_path / "declaration.json",
        {"used_citations": [{"citation_id": "cit_0000000000000001"}]},
    )
    citation_map = tmp_path / "citations.jsonl"
    citation_map.write_text(citation_line + "\n", encoding="utf-8")

    code = main(
        [
            "diagnostics",
            "answer-delta",
            "--old-declaration",
            str(declaration),
            "--new-bundle-manifest",
            "bundle.manifest.json",
            "--new-citation-map",
            str(citation_map),
        ]
    )
    captured = capsys.readouterr()

    assert code == 2
    assert captured.out == ""
    assert expected_error in captured.err
    assert "Traceback" not in captured.err


def test_answer_delta_rejects_non_finite_jsonl_without_traceback(
    tmp_path,
    capsys,
):
    declaration = _write_json(tmp_path / "declaration.json", {"used_citations": []})
    citation_map = tmp_path / "citations.jsonl"
    citation_line = '{"citation_id":"cit-1","diagnostic_value":NaN}'
    citation_map.write_text(citation_line + "\n", encoding="utf-8")

    code = main(
        [
            "diagnostics",
            "answer-delta",
            "--old-declaration",
            str(declaration),
            "--new-bundle-manifest",
            "bundle.manifest.json",
            "--new-citation-map",
            str(citation_map),
        ]
    )
    captured = capsys.readouterr()

    assert code == 2
    assert captured.out == ""
    assert "non-finite JSON constant 'NaN'" in captured.err
    assert "Traceback" not in captured.err


def test_answer_delta_rejects_jsonl_beyond_deterministic_limit_without_traceback(
    tmp_path,
    capsys,
):
    declaration = _write_json(tmp_path / "declaration.json", {"used_citations": []})
    citation_map = tmp_path / "citations.jsonl"
    array_depth = diagnostics_json.MAX_JSON_NESTING_DEPTH
    citation_line = (
        '{"citation_id":"cit-1","nested":'
        + "[" * array_depth
        + "0"
        + "]" * array_depth
        + "}"
    )
    citation_map.write_text(citation_line + "\n", encoding="utf-8")

    code = main(
        [
            "diagnostics",
            "answer-delta",
            "--old-declaration",
            str(declaration),
            "--new-bundle-manifest",
            "bundle.manifest.json",
            "--new-citation-map",
            str(citation_map),
        ]
    )
    captured = capsys.readouterr()

    assert code == 2
    assert captured.out == ""
    assert "citation map line 1 exceeds the supported JSON nesting depth" in captured.err
    assert "Traceback" not in captured.err


def test_answer_delta_jsonl_recursion_errors_exit_two_without_traceback(
    tmp_path,
    capsys,
    monkeypatch,
):
    declaration = _write_json(tmp_path / "declaration.json", {"used_citations": []})
    manifest = _write_json(
        tmp_path / "bundle.manifest.json",
        {
            "kind": "repolens.bundle.manifest",
            "version": "1.0",
            "run_id": "strict-json-test",
            "artifacts": [],
            "links": {},
            "capabilities": {},
        },
    )
    citation_map = tmp_path / "citations.jsonl"
    citation_line = '{"citation_id":"cit-1"}'
    citation_map.write_text(citation_line + "\n", encoding="utf-8")
    real_json_loads = diagnostics_json.json.loads

    def raise_for_citation_line(document, *args, **kwargs):
        if document == citation_line:
            raise RecursionError("forced citation-map recursion limit")
        return real_json_loads(document, *args, **kwargs)

    monkeypatch.setattr(diagnostics_json.json, "loads", raise_for_citation_line)

    code = main(
        [
            "diagnostics",
            "answer-delta",
            "--old-declaration",
            str(declaration),
            "--new-bundle-manifest",
            str(manifest),
            "--new-citation-map",
            str(citation_map),
        ]
    )
    captured = capsys.readouterr()

    assert code == 2
    assert captured.out == ""
    assert "citation map line 1 exceeds the supported JSON nesting depth" in captured.err
    assert "Traceback" not in captured.err


@pytest.mark.parametrize(
    ("declaration", "expected_error"),
    [
        (
            {"used_citations": {}, "used_ranges": [{"range_ref": {}}]},
            "old declaration field 'used_citations' must be a JSON list",
        ),
        (
            {"used_ranges": {}},
            "old declaration field 'used_ranges' must be a JSON list",
        ),
        (
            {"used_citations": [1]},
            "old declaration used_citations[0] must be JSON dict, got int",
        ),
        (
            {"used_ranges": [1]},
            "old declaration used_ranges[0] must be JSON dict, got int",
        ),
        (
            {"used_citations": [{}]},
            "old declaration used_citations[0] field 'citation_id' must be a non-empty string",
        ),
        (
            {"used_citations": [{"citation_id": 7}]},
            "old declaration used_citations[0] field 'citation_id' must be a non-empty string",
        ),
        (
            {"used_citations": [{"citation_id": ""}]},
            "old declaration used_citations[0] field 'citation_id' must be a non-empty string",
        ),
        (
            {"used_ranges": [{}]},
            "old declaration used_ranges[0] field 'range_ref' must be a JSON object",
        ),
        (
            {"used_ranges": [{"range_ref": []}]},
            "old declaration used_ranges[0] field 'range_ref' must be a JSON object",
        ),
    ],
)
def test_answer_delta_rejects_malformed_declaration_evidence_without_traceback(
    tmp_path,
    capsys,
    declaration,
    expected_error,
):
    declaration_path = _write_json(tmp_path / "declaration.json", declaration)

    code = main(
        [
            "diagnostics",
            "answer-delta",
            "--old-declaration",
            str(declaration_path),
            "--new-bundle-manifest",
            "bundle.manifest.json",
        ]
    )
    captured = capsys.readouterr()

    assert code == 2
    assert captured.out == ""
    assert expected_error in captured.err
    assert "Traceback" not in captured.err


@pytest.mark.parametrize(
    ("index_record", "expected_error"),
    [
        ({"chunk_id": "c1"}, "chunk index line 1 field 'path' is required"),
        (
            {"chunk_id": "c1", "path": ""},
            "chunk index line 1 field 'path' must be a non-empty string",
        ),
        (
            {"chunk_id": "c1", "path": "   "},
            "chunk index line 1 field 'path' must be a non-empty string",
        ),
        (
            {"path": "src/a.py"},
            "chunk index line 1 field 'chunk_id' or 'id' is required",
        ),
        (
            {"chunk_id": "", "path": "src/a.py"},
            "chunk index line 1 field 'chunk_id' must be a non-empty string",
        ),
        (
            {"chunk_id": "   ", "path": "src/a.py"},
            "chunk index line 1 field 'chunk_id' must be a non-empty string",
        ),
        (
            {"id": "", "path": "src/a.py"},
            "chunk index line 1 field 'id' must be a non-empty string",
        ),
        (
            {"chunk_id": "c1", "id": "legacy-c1", "path": "src/a.py"},
            "chunk index line 1 fields 'chunk_id' and 'id' must match",
        ),
        (
            {"chunk_id": 7, "path": "src/a.py"},
            "chunk index line 1 field 'chunk_id' must be a string",
        ),
        (
            {"chunk_id": "c1", "path": 7},
            "chunk index line 1 field 'path' must be a string",
        ),
    ],
)
def test_eval_report_rejects_invalid_index_identifiers_without_traceback(
    tmp_path,
    capsys,
    index_record,
    expected_error,
):
    eval_results = _write_json(
        tmp_path / "eval.json",
        {
            "metrics": {"recall@10": 0.0},
            "details": [
                {
                    "query": "session authority",
                    "expected": ["src/a.py"],
                    "is_relevant": False,
                    "found_count": 0,
                    "top_results": [],
                }
            ],
        },
    )
    index = tmp_path / "chunk-index.jsonl"
    index.write_text(json.dumps(index_record) + "\n", encoding="utf-8")

    code = main(
        [
            "diagnostics",
            "eval-report",
            "--eval-results",
            str(eval_results),
            "--index",
            str(index),
        ]
    )
    captured = capsys.readouterr()

    assert code == 2
    assert captured.out == ""
    assert expected_error in captured.err
    assert "Traceback" not in captured.err


@pytest.mark.parametrize(
    ("citation_lines", "expected_error"),
    [
        ([[]], "citation map line 1 must be a JSON object"),
        ([{}], "citation map line 1 field 'citation_id' is required"),
        ([{"citation_id": 7}], "citation map line 1 field 'citation_id' must be a string"),
        (
            [{"citation_id": ""}],
            "citation map line 1 field 'citation_id' must be a non-empty string",
        ),
        (
            [{"citation_id": "   "}],
            "citation map line 1 field 'citation_id' must be a non-empty string",
        ),
        (
            [{"citation_id": "cit-1"}, {"citation_id": "cit-1"}],
            "citation map line 2 duplicates citation_id 'cit-1'",
        ),
        (
            [{"citation_id": "cit-1", "chunk_id": ""}],
            "citation map line 1 field 'chunk_id' must be a non-empty string",
        ),
        (
            [{"citation_id": "cit-1", "chunk_id": "   "}],
            "citation map line 1 field 'chunk_id' must be a non-empty string",
        ),
        (
            [{"citation_id": "cit-1", "chunk_id": 7}],
            "citation map line 1 field 'chunk_id' must be a string",
        ),
    ],
)
def test_eval_report_rejects_invalid_citation_identifiers_without_traceback(
    tmp_path,
    capsys,
    citation_lines,
    expected_error,
):
    eval_results = _write_json(
        tmp_path / "eval.json",
        {
            "metrics": {"recall@10": 0.0},
            "details": [
                {
                    "query": "session authority",
                    "expected": ["src/a.py"],
                    "is_relevant": False,
                    "found_count": 0,
                    "top_results": [],
                }
            ],
        },
    )
    index = tmp_path / "chunk-index.jsonl"
    index.write_text(
        json.dumps({"chunk_id": "c1", "path": "src/a.py"}) + "\n",
        encoding="utf-8",
    )
    citation = tmp_path / "citation-map.jsonl"
    citation.write_text(
        "\n".join(json.dumps(record) for record in citation_lines) + "\n",
        encoding="utf-8",
    )

    code = main(
        [
            "diagnostics",
            "eval-report",
            "--eval-results",
            str(eval_results),
            "--index",
            str(index),
            "--citation",
            str(citation),
        ]
    )
    captured = capsys.readouterr()

    assert code == 2
    assert captured.out == ""
    assert expected_error in captured.err
    assert "Traceback" not in captured.err


def test_eval_report_accepts_legacy_index_id(tmp_path, capsys):
    eval_results = _write_json(
        tmp_path / "eval.json",
        {
            "metrics": {"recall@10": 0.0},
            "details": [
                {
                    "query": "session authority",
                    "expected": ["src/a.py"],
                    "is_relevant": False,
                    "found_count": 0,
                    "top_results": [],
                }
            ],
        },
    )
    index = tmp_path / "chunk-index.jsonl"
    index.write_text(
        json.dumps({"id": "legacy-c1", "path": "src/a.py"}) + "\n",
        encoding="utf-8",
    )

    code, report = _run(
        capsys,
        [
            "eval-report",
            "--eval-results",
            str(eval_results),
            "--index",
            str(index),
        ],
    )

    assert code == 0
    assert (
        report["diagnostics_report"]["diagnostics"][0]["primary_diagnosis"]
        == "target_exists_not_in_top_k"
    )


def test_eval_report_rejects_duplicate_chunk_identifiers_without_traceback(
    tmp_path, capsys
):
    eval_results = _write_json(
        tmp_path / "eval.json",
        {
            "metrics": {"recall@10": 0.0},
            "details": [
                {
                    "query": "session authority",
                    "expected": ["src/a.py"],
                    "is_relevant": False,
                    "found_count": 0,
                    "top_results": [],
                }
            ],
        },
    )
    index = tmp_path / "chunk-index.jsonl"
    index.write_text(
        "\n".join(
            [
                json.dumps({"chunk_id": "c1", "path": "src/a.py"}),
                json.dumps({"id": "c1", "path": "src/b.py"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    code = main(
        [
            "diagnostics",
            "eval-report",
            "--eval-results",
            str(eval_results),
            "--index",
            str(index),
        ]
    )
    captured = capsys.readouterr()

    assert code == 2
    assert captured.out == ""
    assert "chunk index line 2 duplicates chunk identifier 'c1'" in captured.err
    assert "Traceback" not in captured.err


@pytest.mark.parametrize(
    ("artifact_option", "filename", "valid_prefix", "expected_error"),
    [
        (
            "--index",
            "chunk-index.jsonl",
            "",
            "chunk index line 1 must be valid JSON",
        ),
        (
            "--citation",
            "citation-map.jsonl",
            json.dumps({"chunk_id": "c1", "path": "src/a.py"}) + "\n",
            "citation map line 1 must be valid JSON",
        ),
    ],
)
def test_eval_report_rejects_invalid_jsonl_without_traceback(
    tmp_path,
    capsys,
    artifact_option,
    filename,
    valid_prefix,
    expected_error,
):
    eval_results = _write_json(
        tmp_path / "eval.json",
        {
            "metrics": {"recall@10": 0.0},
            "details": [
                {
                    "query": "session authority",
                    "expected": ["src/a.py"],
                    "is_relevant": False,
                    "found_count": 0,
                    "top_results": [],
                }
            ],
        },
    )
    artifact = tmp_path / filename
    artifact.write_text("{\n", encoding="utf-8")
    args = ["eval-report", "--eval-results", str(eval_results)]
    if artifact_option == "--citation":
        index = tmp_path / "chunk-index.jsonl"
        index.write_text(valid_prefix, encoding="utf-8")
        args.extend(["--index", str(index)])
    args.extend([artifact_option, str(artifact)])

    code = main(["diagnostics", *args])
    captured = capsys.readouterr()

    assert code == 2
    assert captured.out == ""
    assert expected_error in captured.err
    assert "Traceback" not in captured.err


@pytest.mark.parametrize(
    ("artifact_option", "filename"),
    [
        ("--index", "chunk-index.jsonl"),
        ("--citation", "citation-map.jsonl"),
    ],
)
def test_eval_report_rejects_non_finite_jsonl_constants_without_traceback(
    tmp_path,
    capsys,
    artifact_option,
    filename,
):
    eval_results = _write_json(
        tmp_path / "eval.json",
        {
            "metrics": {"recall@10": 0.0},
            "details": [
                {
                    "query": "session authority",
                    "expected": ["src/a.py"],
                    "is_relevant": False,
                    "found_count": 0,
                    "top_results": [],
                }
            ],
        },
    )
    artifact = tmp_path / filename
    args = ["eval-report", "--eval-results", str(eval_results)]
    if artifact_option == "--index":
        artifact.write_text(
            '{"chunk_id":"c1","path":"src/a.py","diagnostic_value":NaN}\n',
            encoding="utf-8",
        )
    else:
        index = tmp_path / "chunk-index.jsonl"
        index.write_text(
            json.dumps({"chunk_id": "c1", "path": "src/a.py"}) + "\n",
            encoding="utf-8",
        )
        artifact.write_text(
            '{"citation_id":"cit-1","chunk_id":"c1","diagnostic_value":NaN}\n',
            encoding="utf-8",
        )
        args.extend(["--index", str(index)])
    args.extend([artifact_option, str(artifact)])

    code = main(["diagnostics", *args])
    captured = capsys.readouterr()

    assert code == 2
    assert captured.out == ""
    assert "non-finite JSON constant 'NaN'" in captured.err
    assert "Traceback" not in captured.err
