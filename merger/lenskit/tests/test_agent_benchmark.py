from __future__ import annotations

import copy
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pytest
from jsonschema import Draft7Validator

from merger.lenskit.core.agent_benchmark import (
    AgentBenchmarkError,
    build_run_requests,
    evaluate_paired_runs,
    execute_runner,
    require_valid_taskset,
    score_receipt,
    sha256_bytes,
    sha256_json,
    validate_receipt,
    validate_taskset,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
TASKSET_PATH = REPO_ROOT / "docs/retrieval/repobrief_agent_benchmark_taskset.v1.json"
CONTRACT_ROOT = REPO_ROOT / "merger/lenskit/contracts"
SCHEMA_PATHS = {
    "taskset": CONTRACT_ROOT / "agent-benchmark-taskset.v1.schema.json",
    "request": CONTRACT_ROOT / "agent-benchmark-run-request.v1.schema.json",
    "receipt": CONTRACT_ROOT / "agent-benchmark-run-receipt.v1.schema.json",
    "evaluation": CONTRACT_ROOT / "agent-benchmark-evaluation.v1.schema.json",
}
RUNNER = {
    "provider": "fixture-provider",
    "model": "fixture-model",
    "sampling": {"temperature": 0},
}
BINDINGS = {
    repository_id: {
        "manifest": f"/bench/{repository_id}.bundle.manifest.json",
        "manifest_sha256": (str(index + 1) * 64)[:64],
        "mcp_command": ["python", "repobrief-mcp-stdio.py", "--bundle-root", "/bench"],
    }
    for index, repository_id in enumerate(("lenskit", "grabowski", "weltgewebe"))
}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _taskset() -> dict:
    return _load(TASKSET_PATH)


def _schema(name: str) -> dict:
    return _load(SCHEMA_PATHS[name])


def _cases(taskset: dict) -> dict[str, dict]:
    return {case["id"]: case for case in taskset["cases"]}


def _planned_requests(taskset: dict) -> list[dict]:
    return build_run_requests(
        taskset,
        runner=RUNNER,
        manifest_bindings=BINDINGS,
        repetitions=2,
    )


def _receipt(
    request: dict,
    case: dict,
    *,
    duration_ms: int = 100,
    input_tokens: int = 100,
    output_tokens: int = 20,
    tool_bytes: int = 200,
    answer_override: dict | None = None,
) -> dict:
    condition = request["condition"]
    expectation = case["expectations"][condition]
    transcript_text = json.dumps(
        {
            "request_id": request["request_id"],
            "condition": condition,
            "messages": [],
        },
        sort_keys=True,
    )
    answer = {
        "text": "synthetic contract fixture",
        "outcome": expectation["outcome"],
        "reported_paths": expectation["required_paths"],
        "reported_symbols": expectation["required_symbols"],
        "citations": expectation["required_citations"],
        "claims": expectation["required_claims"],
        "asserted_sufficient_evidence": expectation["outcome"] == "answer",
    }
    if answer_override:
        answer.update(answer_override)
    tool_name = "read_file" if condition == "baseline" else "ask_context"
    return {
        "kind": "repobrief.agent_benchmark_run_receipt",
        "version": "1.0",
        "request_id": request["request_id"],
        "request_sha256": sha256_json(request),
        "status": "success",
        "provider": {
            "name": request["runner"]["provider"],
            "model": request["runner"]["model"],
            "sampling": request["runner"]["sampling"],
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "token_source": "provider_reported",
        },
        "started_at": "2026-07-13T09:00:00Z",
        "ended_at": "2026-07-13T09:00:01Z",
        "duration_ms": duration_ms,
        "exit_code": 0,
        "tool_calls": [
            {
                "sequence": 1,
                "name": tool_name,
                "status": "success",
                "duration_ms": min(duration_ms, 50),
                "input_bytes": tool_bytes // 2,
                "output_bytes": tool_bytes - tool_bytes // 2,
            }
        ],
        "answer": answer,
        "transcript": {
            "storage": "inline",
            "sha256": sha256_bytes(transcript_text.encode("utf-8")),
            "bytes": len(transcript_text.encode("utf-8")),
            "inline": transcript_text,
            "artifact": None,
        },
        "error": None,
        "does_not_establish": ["real_agent_usefulness", "default_promotion"],
    }


def _requests_and_receipts(
    *, treatment_factor: float = 0.5
) -> tuple[dict, list[dict], list[dict]]:
    taskset = _taskset()
    requests = _planned_requests(taskset)
    cases = _cases(taskset)
    receipts = []
    for request in requests:
        treatment = request["condition"] == "treatment"
        factor = treatment_factor if treatment else 1.0
        receipts.append(
            _receipt(
                request,
                cases[request["case_id"]],
                duration_ms=int(1000 * factor),
                input_tokens=int(1000 * factor),
                output_tokens=int(200 * factor),
                tool_bytes=int(2000 * factor),
            )
        )
    return taskset, requests, receipts


def test_contract_schemas_are_valid_draft7() -> None:
    for path in SCHEMA_PATHS.values():
        Draft7Validator.check_schema(_load(path))


def test_frozen_taskset_matches_schema_and_semantic_contract() -> None:
    taskset = _taskset()
    Draft7Validator(_schema("taskset")).validate(taskset)
    assert validate_taskset(taskset) == []
    assert len(taskset["cases"]) == 24
    assert Counter(case["category"] for case in taskset["cases"]) == {
        "navigation": 8,
        "structural": 8,
        "grounding_freshness": 8,
    }
    negative = sum(
        1
        for case in taskset["cases"]
        if any(
            case["expectations"][condition]["outcome"] != "answer"
            for condition in ("baseline", "treatment")
        )
    )
    assert negative >= 6
    assert taskset["default_promoted"] is False


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        (lambda taskset: taskset["cases"].pop(), "exactly 24 cases"),
        (
            lambda taskset: taskset["cases"][0].update(
                {"id": taskset["cases"][1]["id"]}
            ),
            "case ids must be unique",
        ),
        (
            lambda taskset: taskset["tool_policy"]["baseline"].append("ask_context"),
            "baseline tool policy must not expose RepoBrief tools",
        ),
        (
            lambda taskset: taskset["cases"][0]["expectations"]["baseline"][
                "required_paths"
            ].append("../outside.py"),
            "non-canonical repository path",
        ),
    ],
)
def test_taskset_semantic_validation_rejects_manipulation(mutation, expected: str) -> None:
    taskset = _taskset()
    mutation(taskset)
    assert any(expected in error for error in validate_taskset(taskset))
    with pytest.raises(AgentBenchmarkError, match=expected):
        require_valid_taskset(taskset)


def test_pair_plan_is_deterministic_balanced_and_isolated() -> None:
    taskset = _taskset()
    first = _planned_requests(taskset)
    second = _planned_requests(taskset)
    assert first == second
    assert len(first) == 96
    assert len({item["request_id"] for item in first}) == 96
    assert len({item["session_id"] for item in first}) == 96
    assert len({item["workspace_id"] for item in first}) == 96

    orders: dict[int, Counter] = defaultdict(Counter)
    for request in first:
        if request["order"] == 1:
            orders[request["repetition"]][request["condition"]] += 1
        if request["condition"] == "baseline":
            assert request["repobrief"] is None
            assert "ask_context" not in request["allowed_tools"]
        else:
            assert request["repobrief"] is not None
            assert "ask_context" in request["allowed_tools"]
        Draft7Validator(_schema("request")).validate(request)
    assert orders[1] == {"baseline": 12, "treatment": 12}
    assert orders[2] == {"baseline": 12, "treatment": 12}


def test_pair_plan_rejects_non_frozen_repetition_count() -> None:
    taskset = _taskset()
    with pytest.raises(AgentBenchmarkError, match="requires exactly 2 repetitions"):
        build_run_requests(
            taskset,
            runner=RUNNER,
            manifest_bindings=BINDINGS,
            repetitions=1,
        )


def test_pair_plan_requires_treatment_manifest_binding() -> None:
    taskset = _taskset()
    incomplete = dict(BINDINGS)
    incomplete.pop("grabowski")
    with pytest.raises(AgentBenchmarkError, match="missing RepoBrief manifest binding"):
        build_run_requests(
            taskset,
            runner=RUNNER,
            manifest_bindings=incomplete,
            repetitions=2,
        )


def test_valid_receipt_matches_schema_and_exact_request() -> None:
    taskset = _taskset()
    request = _planned_requests(taskset)[0]
    receipt = _receipt(request, _cases(taskset)[request["case_id"]])
    Draft7Validator(_schema("receipt")).validate(receipt)
    assert validate_receipt(request, receipt) == []
    score = score_receipt(
        _cases(taskset)[request["case_id"]], request["condition"], request, receipt
    )
    assert score["valid"] is True
    assert score["success"] is True


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (
            lambda receipt: receipt["provider"].update({"token_source": "estimated"}),
            "tokens are not provider-reported",
        ),
        (
            lambda receipt: receipt["tool_calls"][0].update({"name": "ask_context"}),
            "disallowed tool call",
        ),
        (
            lambda receipt: receipt["transcript"].update({"sha256": "0" * 64}),
            "transcript SHA-256 mismatch",
        ),
        (
            lambda receipt: receipt["provider"].update({"input_tokens": 999999}),
            "exceeds input_tokens budget",
        ),
    ],
)
def test_receipt_validation_rejects_untrusted_evidence(mutate, expected: str) -> None:
    taskset = _taskset()
    request = _planned_requests(taskset)[0]
    receipt = _receipt(request, _cases(taskset)[request["case_id"]])
    mutate(receipt)
    assert any(expected in error for error in validate_receipt(request, receipt))


def test_artifact_transcript_cannot_escape_root(tmp_path: Path) -> None:
    taskset = _taskset()
    request = _planned_requests(taskset)[0]
    receipt = _receipt(request, _cases(taskset)[request["case_id"]])
    receipt["transcript"].update(
        {"storage": "artifact", "inline": None, "artifact": "../outside.json"}
    )
    errors = validate_receipt(request, receipt, transcript_root=tmp_path)
    assert "transcript artifact is missing or outside transcript_root" in errors


def test_non_answer_case_detects_false_confidence() -> None:
    taskset = _taskset()
    case = _cases(taskset)["grounding-head-mismatch"]
    request = next(
        item
        for item in _planned_requests(taskset)
        if item["case_id"] == case["id"] and item["condition"] == "treatment"
    )
    receipt = _receipt(
        request,
        case,
        answer_override={
            "outcome": "answer",
            "claims": ["snapshot_fresh"],
            "asserted_sufficient_evidence": True,
        },
    )
    score = score_receipt(case, "treatment", request, receipt)
    assert score["valid"] is True
    assert score["success"] is False
    assert score["false_confidence"] is True


def test_synthetic_fixtures_can_never_establish_usefulness() -> None:
    taskset, requests, receipts = _requests_and_receipts(treatment_factor=0.5)
    result = evaluate_paired_runs(
        taskset,
        requests,
        receipts,
        measurement_scope="synthetic_contract_fixture",
    )
    Draft7Validator(_schema("evaluation")).validate(result)
    assert result["decision"]["status"] == "synthetic_only"
    assert result["decision"]["default_promoted"] is False
    assert {item["classification"] for item in result["classes"]} == {
        "synthetic_only"
    }


def test_real_paired_evaluation_requires_reproduced_direction() -> None:
    taskset, requests, receipts = _requests_and_receipts(treatment_factor=0.5)
    result = evaluate_paired_runs(
        taskset,
        requests,
        receipts,
        measurement_scope="real_paired_agent_runs",
    )
    assert result["decision"]["status"] == "useful_class"
    assert result["decision"]["useful_classes"] == [
        "grounding_freshness",
        "navigation",
        "structural",
    ]
    assert all(item["classification"] == "useful" for item in result["classes"])
    assert result["decision"]["default_promoted"] is False


def test_quality_regression_blocks_benefit_despite_efficiency_gain() -> None:
    taskset, requests, receipts = _requests_and_receipts(treatment_factor=0.1)
    cases = _cases(taskset)
    target_ids = {
        request["request_id"]
        for request in requests
        if request["case_id"] == "nav-lenskit-mcp-startup"
        and request["condition"] == "treatment"
    }
    receipt_by_id = {receipt["request_id"]: receipt for receipt in receipts}
    for request in requests:
        if request["request_id"] in target_ids:
            receipt_by_id[request["request_id"]] = _receipt(
                request,
                cases[request["case_id"]],
                duration_ms=10,
                input_tokens=10,
                output_tokens=2,
                tool_bytes=20,
                answer_override={
                    "outcome": "abstain",
                    "reported_paths": [],
                    "claims": [],
                    "asserted_sufficient_evidence": False,
                },
            )
    result = evaluate_paired_runs(
        taskset,
        requests,
        list(receipt_by_id.values()),
        measurement_scope="real_paired_agent_runs",
    )
    navigation = next(
        item for item in result["classes"] if item["category"] == "navigation"
    )
    assert navigation["classification"] == "harmful"
    assert result["decision"]["status"] == "harmful"
    assert result["decision"]["default_promoted"] is False


def test_reused_session_or_workspace_invalidates_pair() -> None:
    taskset, requests, _receipts = _requests_and_receipts(treatment_factor=0.5)
    mutated_requests = copy.deepcopy(requests)
    by_pair: dict[str, list[dict]] = defaultdict(list)
    for request in mutated_requests:
        by_pair[request["pair_id"]].append(request)
    first_pair = next(iter(by_pair.values()))
    first_pair[1]["session_id"] = first_pair[0]["session_id"]
    first_pair[1]["workspace_id"] = first_pair[0]["workspace_id"]

    cases = _cases(taskset)
    mutated_receipts = [
        _receipt(request, cases[request["case_id"]]) for request in mutated_requests
    ]
    result = evaluate_paired_runs(
        taskset,
        mutated_requests,
        mutated_receipts,
        measurement_scope="real_paired_agent_runs",
    )
    assert result["invalid_run_count"] >= 2
    assert result["decision"]["status"] == "insufficient_evidence"


def test_entire_missing_pair_remains_visible_and_invalid() -> None:
    taskset, requests, receipts = _requests_and_receipts(treatment_factor=0.5)
    missing_pair = requests[0]["pair_id"]
    filtered_requests = [request for request in requests if request["pair_id"] != missing_pair]
    valid_request_ids = {request["request_id"] for request in filtered_requests}
    filtered_receipts = [
        receipt for receipt in receipts if receipt["request_id"] in valid_request_ids
    ]
    result = evaluate_paired_runs(
        taskset,
        filtered_requests,
        filtered_receipts,
        measurement_scope="real_paired_agent_runs",
    )
    assert len(result["cases"]) == 48
    assert result["run_count"] == 96
    assert result["invalid_run_count"] >= 2
    assert result["decision"]["status"] == "insufficient_evidence"


def test_request_manipulation_invalidates_matching_receipt() -> None:
    taskset, requests, receipts = _requests_and_receipts(treatment_factor=0.5)
    mutated_requests = copy.deepcopy(requests)
    target = mutated_requests[0]
    target["prompt"] = "post-hoc prompt"
    cases = _cases(taskset)
    receipt_by_id = {receipt["request_id"]: receipt for receipt in receipts}
    receipt_by_id[target["request_id"]] = _receipt(
        target,
        cases[target["case_id"]],
    )
    result = evaluate_paired_runs(
        taskset,
        mutated_requests,
        list(receipt_by_id.values()),
        measurement_scope="real_paired_agent_runs",
    )
    affected = next(
        item
        for item in result["cases"]
        if item["case_id"] == target["case_id"]
        and item["repetition"] == target["repetition"]
    )
    condition_score = affected[target["condition"]]
    assert condition_score["valid"] is False
    assert "request prompt does not match frozen case" in condition_score["invalid_reasons"]
    assert result["decision"]["status"] == "insufficient_evidence"


def test_execute_runner_accepts_one_json_object_without_shell(tmp_path: Path) -> None:
    runner = tmp_path / "runner.py"
    runner.write_text(
        "import json, sys\n"
        "request = json.load(sys.stdin)\n"
        "json.dump({'seen': request['request_id']}, sys.stdout)\n",
        encoding="utf-8",
    )
    request = {"request_id": "demo"}
    result = execute_runner(
        [sys.executable, str(runner)],
        request,
        timeout_seconds=5,
        max_stdout_bytes=1024,
    )
    assert result == {"seen": "demo"}


def test_execute_runner_rejects_oversized_or_invalid_output(tmp_path: Path) -> None:
    oversized = tmp_path / "oversized.py"
    oversized.write_text("print('x' * 1000)\n", encoding="utf-8")
    with pytest.raises(AgentBenchmarkError, match="stdout exceeds"):
        execute_runner(
            [sys.executable, str(oversized)],
            {"request_id": "demo"},
            timeout_seconds=5,
            max_stdout_bytes=32,
        )

    invalid = tmp_path / "invalid.py"
    invalid.write_text("print('not-json')\n", encoding="utf-8")
    with pytest.raises(AgentBenchmarkError, match="not one UTF-8 JSON object"):
        execute_runner(
            [sys.executable, str(invalid)],
            {"request_id": "demo"},
            timeout_seconds=5,
            max_stdout_bytes=1024,
        )

def test_receipt_rejects_invalid_status_and_timestamps() -> None:
    taskset = _taskset()
    request = build_run_requests(
        taskset,
        runner=RUNNER,
        manifest_bindings=BINDINGS,
        repetitions=2,
    )[0]
    case = _cases(taskset)[request["case_id"]]

    invalid_status = _receipt(request, case)
    invalid_status["status"] = "unknown"
    assert "receipt status is invalid" in validate_receipt(request, invalid_status)

    invalid_time = _receipt(request, case)
    invalid_time["started_at"] = "not-a-date"
    invalid_time["ended_at"] = "2026-07-13T09:00:00"
    errors = validate_receipt(request, invalid_time)
    assert "receipt started_at is not a timezone-aware date-time" in errors
    assert "receipt ended_at is not a timezone-aware date-time" in errors

    reversed_time = _receipt(request, case)
    reversed_time["started_at"] = "2026-07-13T09:00:02Z"
    reversed_time["ended_at"] = "2026-07-13T09:00:01Z"
    assert "receipt ended_at precedes started_at" in validate_receipt(
        request, reversed_time
    )


def test_transcript_content_is_nonempty_and_bounded(tmp_path: Path) -> None:
    taskset = _taskset()
    request = build_run_requests(
        taskset,
        runner=RUNNER,
        manifest_bindings=BINDINGS,
        repetitions=2,
    )[0]
    case = _cases(taskset)[request["case_id"]]

    empty = _receipt(request, case)
    empty["transcript"].update(
        {"inline": "", "bytes": 0, "sha256": sha256_bytes(b"")}
    )
    assert "transcript must not be empty" in validate_receipt(request, empty)

    oversized_path = tmp_path / "oversized-transcript.json"
    with oversized_path.open("wb") as handle:
        handle.truncate(16 * 1024 * 1024 + 1)
    oversized = _receipt(request, case)
    oversized["transcript"].update(
        {
            "storage": "artifact",
            "inline": None,
            "artifact": oversized_path.name,
            "bytes": 16 * 1024 * 1024 + 1,
            "sha256": "0" * 64,
        }
    )
    assert "transcript exceeds configured limit" in validate_receipt(
        request, oversized, transcript_root=tmp_path
    )
