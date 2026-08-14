from __future__ import annotations

import copy
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pytest
from jsonschema import Draft7Validator

from merger.repoground.core.agent_benchmark import (
    AgentBenchmarkError,
    build_run_requests,
    evaluate_paired_runs,
    execute_runner,
    require_valid_taskset,
    score_receipt,
    sha256_bytes,
    sha256_json,
    validate_evaluation,
    validate_receipt,
    validate_taskset,
)

from merger.repoground.core.agent_benchmark_requests import pair_request_errors
from merger.repoground.core.bounded_artifact_read import MAX_REGISTERED_ARTIFACT_BYTES

REPO_ROOT = Path(__file__).resolve().parents[3]
TASKSET_PATH = REPO_ROOT / "docs/retrieval/repobrief_agent_benchmark_taskset.v1.json"
CONTRACT_ROOT = REPO_ROOT / "merger/repoground/contracts"
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
        "mcp_command": ["python", "-m", "merger.repoground", "mcp", "--bundle-root", "/bench"],
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
            "baseline tool policy must not expose RepoGround tools",
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


def test_claude_code_live_contract_is_bound_into_requests() -> None:
    runner = {
        "execution_contract": "grabowski-claude-code-live-v1",
        "provider": "anthropic-claude-code",
        "model": "claude-haiku-4-5-20251001",
        "sampling": {},
    }

    requests = build_run_requests(
        _taskset(),
        runner=runner,
        manifest_bindings=BINDINGS,
        repetitions=2,
    )

    assert requests
    assert all(request["runner"] == runner for request in requests)
    Draft7Validator(_schema("request")).validate(requests[0])


@pytest.mark.parametrize(
    ("runner", "expected"),
    [
        (
            {
                "provider": "anthropic",
                "model": "claude-haiku-4-5-20251001",
                "sampling": {},
            },
            "ambiguous provider anthropic",
        ),
        (
            {
                "execution_contract": "grabowski-claude-code-live-v1",
                "provider": "fixture-provider",
                "model": "fixture-model",
                "sampling": {},
            },
            "requires provider anthropic-claude-code",
        ),
        (
            {
                "execution_contract": "grabowski-claude-code-live-v1",
                "provider": "anthropic-claude-code",
                "model": "claude-haiku-4-5-20251001",
                "sampling": {"temperature": 0},
            },
            "requires an explicit empty sampling object",
        ),
        (
            {
                "execution_contract": "grabowski-claude-code-live-v1",
                "provider": "anthropic-claude-code",
                "model": "claude-haiku-4-5-20251001",
            },
            "requires an explicit empty sampling object",
        ),
        (
            {
                "execution_contract": "grabowski-claude-code-live-v1",
                "provider": "anthropic-claude-code",
                "model": "claude-haiku-4-5-20251001",
                "sampling": [],
            },
            "requires an explicit empty sampling object",
        ),
        (
            {
                "execution_contract": "unknown-live-contract",
                "provider": "fixture-provider",
                "model": "fixture-model",
                "sampling": {},
            },
            "unsupported runner execution contract",
        ),
    ],
)
def test_runner_contract_rejects_non_executable_configuration(
    runner: dict, expected: str
) -> None:
    with pytest.raises(AgentBenchmarkError, match=expected):
        build_run_requests(
            _taskset(),
            runner=runner,
            manifest_bindings=BINDINGS,
            repetitions=2,
        )


def test_pair_plan_requires_treatment_manifest_binding() -> None:
    taskset = _taskset()
    incomplete = dict(BINDINGS)
    incomplete.pop("grabowski")
    with pytest.raises(AgentBenchmarkError, match="missing RepoGround manifest binding"):
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


def test_execute_runner_rechecks_component_artifact_after_planning(tmp_path: Path) -> None:
    _taskset_value, requests, bindings = _component_requests(tmp_path)
    treatment = next(item for item in requests if item["condition"] == "treatment")
    repository_id = treatment["repository"]["id"]
    artifact = Path(bindings[repository_id]["manifest"]).parent / treatment["component_delta"]["artifact"]
    artifact.write_text("tampered-after-plan", encoding="utf-8")
    with pytest.raises(AgentBenchmarkError, match="artifact SHA-256 mismatch"):
        execute_runner(
            [sys.executable, "-c", "raise SystemExit('runner must not start')"],
            treatment,
            timeout_seconds=5,
            max_stdout_bytes=1024,
        )


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


COMPONENT_REVISION = "a" * 40


def _component_taskset() -> dict:
    taskset = copy.deepcopy(_taskset())
    taskset["comparison"] = {
        "mode": "component_delta",
        "component": "language_structure_json",
        "source_revision": COMPONENT_REVISION,
    }
    taskset["tool_policy"]["baseline"] = copy.deepcopy(
        taskset["tool_policy"]["treatment"]
    )
    return taskset


def _component_bindings(tmp_path: Path) -> dict[str, dict]:
    bindings: dict[str, dict] = {}
    for repository in _taskset()["repositories"]:
        repository_id = repository["id"]
        root = tmp_path / repository_id
        root.mkdir(parents=True)
        manifest = root / f"{repository_id}.bundle.manifest.json"
        manifest_raw = (json.dumps({"repository_id": repository_id}) + "\n").encode()
        manifest.write_bytes(manifest_raw)
        artifact = root / "language_structure.json"
        artifact_raw = (json.dumps({"repository_id": repository_id, "component": "language_structure_json"}) + "\n").encode()
        artifact.write_bytes(artifact_raw)
        bindings[repository_id] = {
            "manifest": str(manifest),
            "manifest_sha256": sha256_bytes(manifest_raw),
            "mcp_command": ["python", "-m", "merger.repoground.mcp_server"],
            "components": {
                "language_structure_json": {
                    "source_revision": COMPONENT_REVISION,
                    "artifact": artifact.name,
                    "artifact_sha256": sha256_bytes(artifact_raw),
                }
            },
        }
    return bindings


def _component_requests(tmp_path: Path) -> tuple[dict, list[dict], dict[str, dict]]:
    taskset = _component_taskset()
    bindings = _component_bindings(tmp_path)
    requests = build_run_requests(
        taskset, runner=RUNNER, manifest_bindings=bindings, repetitions=2
    )
    return taskset, requests, bindings


def test_complete_evaluation_contract_rejects_incomplete_objects(tmp_path: Path) -> None:
    taskset, requests, _bindings = _component_requests(tmp_path)
    cases = _cases(taskset)
    receipts = [_receipt(request, cases[request["case_id"]]) for request in requests]
    evaluation = evaluate_paired_runs(
        taskset, requests, receipts, measurement_scope="real_paired_agent_runs"
    )
    assert validate_evaluation(evaluation) == []
    Draft7Validator(_schema("evaluation")).validate(evaluation)

    incomplete = copy.deepcopy(evaluation)
    incomplete["cases"][0]["baseline"].pop("duration_ms")
    assert validate_evaluation(incomplete)
    incomplete = copy.deepcopy(evaluation)
    incomplete["decision"].pop("reason")
    assert validate_evaluation(incomplete)
    incomplete = copy.deepcopy(evaluation)
    incomplete.pop("does_not_establish")
    assert validate_evaluation(incomplete)


def test_component_delta_taskset_contract_is_fail_closed() -> None:
    taskset = _component_taskset()
    Draft7Validator(_schema("taskset")).validate(taskset)
    assert validate_taskset(taskset) == []

    mutations = []
    unknown_mode = copy.deepcopy(taskset)
    unknown_mode["comparison"]["mode"] = "unknown"
    mutations.append(unknown_mode)
    invalid_component = copy.deepcopy(taskset)
    invalid_component["comparison"]["component"] = "A"
    mutations.append(invalid_component)
    one_character_component = copy.deepcopy(taskset)
    one_character_component["comparison"]["component"] = "a"
    mutations.append(one_character_component)
    invalid_revision = copy.deepcopy(taskset)
    invalid_revision["comparison"]["source_revision"] = "a" * 39
    mutations.append(invalid_revision)
    split_tools = copy.deepcopy(taskset)
    split_tools["tool_policy"]["baseline"] = ["glob", "grep", "read_file", "search"]
    mutations.append(split_tools)
    missing_repoground = copy.deepcopy(taskset)
    missing_repoground["tool_policy"]["baseline"] = [
        tool
        for tool in missing_repoground["tool_policy"]["baseline"]
        if tool not in {"ask_context", "repobrief_resource_read", "grounding_verify", "live_freshness"}
    ]
    mutations.append(missing_repoground)
    for mutated in mutations:
        assert validate_taskset(mutated)


def test_component_delta_requests_differ_only_by_bound_artifact(tmp_path: Path) -> None:
    taskset, requests, bindings = _component_requests(tmp_path)
    schema = Draft7Validator(_schema("request"))
    by_pair: dict[str, list[dict]] = defaultdict(list)
    for request in requests:
        schema.validate(request)
        by_pair[request["pair_id"]].append(request)
    assert by_pair
    for pair in by_pair.values():
        assert pair_request_errors(taskset, pair) == []
        baseline = next(item for item in pair if item["condition"] == "baseline")
        treatment = next(item for item in pair if item["condition"] == "treatment")
        for field in (
            "repository",
            "runner",
            "prompt",
            "allowed_tools",
            "budgets",
            "repobrief",
            "isolation",
        ):
            assert baseline[field] == treatment[field]
        repository_id = treatment["repository"]["id"]
        expected = bindings[repository_id]["components"]["language_structure_json"]
        assert baseline["component_delta"] == {
            "component": "language_structure_json",
            "source_revision": COMPONENT_REVISION,
            "artifact": None,
            "artifact_sha256": None,
        }
        assert treatment["component_delta"] == {
            "component": "language_structure_json",
            "source_revision": COMPONENT_REVISION,
            "artifact": expected["artifact"],
            "artifact_sha256": expected["artifact_sha256"],
        }


@pytest.mark.parametrize(
    "mutation",
    [
        "components_missing",
        "component_missing",
        "artifact_missing",
        "sha_missing",
        "revision_mismatch",
        "sha_invalid",
        "file_missing",
        "path_escape",
        "sha_mismatch",
    ],
)
def test_component_delta_artifact_binding_fails_closed(
    tmp_path: Path, mutation: str
) -> None:
    taskset = _component_taskset()
    bindings = _component_bindings(tmp_path)
    repository_id = taskset["repositories"][0]["id"]
    binding = bindings[repository_id]
    component = binding["components"]["language_structure_json"]
    if mutation == "components_missing":
        binding.pop("components")
    elif mutation == "component_missing":
        binding["components"].pop("language_structure_json")
    elif mutation == "artifact_missing":
        component.pop("artifact")
    elif mutation == "sha_missing":
        component.pop("artifact_sha256")
    elif mutation == "revision_mismatch":
        component["source_revision"] = "b" * 40
    elif mutation == "sha_invalid":
        component["artifact_sha256"] = "z" * 64
    elif mutation == "file_missing":
        (Path(binding["manifest"]).parent / component["artifact"]).unlink()
    elif mutation == "path_escape":
        component["artifact"] = "../outside.json"
    elif mutation == "sha_mismatch":
        component["artifact_sha256"] = "f" * 64
    with pytest.raises(AgentBenchmarkError):
        build_run_requests(
            taskset, runner=RUNNER, manifest_bindings=bindings, repetitions=2
        )


def test_component_delta_artifact_size_and_stability_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    taskset = _component_taskset()
    bindings = _component_bindings(tmp_path / "large")
    repository_id = taskset["repositories"][0]["id"]
    binding = bindings[repository_id]
    component = binding["components"]["language_structure_json"]
    artifact = Path(binding["manifest"]).parent / component["artifact"]
    with artifact.open("wb") as handle:
        handle.truncate(MAX_REGISTERED_ARTIFACT_BYTES + 1)
    with pytest.raises(AgentBenchmarkError, match="too_large"):
        build_run_requests(
            taskset, runner=RUNNER, manifest_bindings=bindings, repetitions=2
        )

    stable_bindings = _component_bindings(tmp_path / "unstable")
    monkeypatch.setattr(
        "merger.repoground.core.agent_benchmark.read_stable_regular_file_bytes",
        lambda *_args, **_kwargs: (None, None, "source_changed", "changed"),
    )
    with pytest.raises(AgentBenchmarkError, match="source_changed"):
        build_run_requests(
            taskset, runner=RUNNER, manifest_bindings=stable_bindings, repetitions=2
        )


def _set_nested_value(target: dict, path: tuple[str, ...], value) -> None:
    current = target
    for key in path[:-1]:
        current = current[key]
    current[path[-1]] = value


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("repository", "commit"), "f" * 40),
        (("runner", "model"), "other"),
        (("prompt",), "changed prompt"),
        (("allowed_tools",), []),
        (("budgets", "max_tool_calls"), 999),
        (("repobrief", "manifest"), "other.manifest.json"),
        (("repobrief", "manifest_sha256"), "f" * 64),
        (("repobrief", "mcp_command"), ["other"]),
        (("component_delta", "component"), "other_component"),
        (("component_delta", "source_revision"), "b" * 40),
        (("component_delta", "artifact"), None),
    ],
)
def test_component_delta_pair_isolation_rejects_forbidden_difference(
    tmp_path: Path, path: tuple[str, ...], value
) -> None:
    taskset, requests, _bindings = _component_requests(tmp_path)
    pair_id = requests[0]["pair_id"]
    pair = [item for item in requests if item["pair_id"] == pair_id]
    assert pair_request_errors(taskset, pair) == []
    mutated = copy.deepcopy(pair)
    treatment = next(item for item in mutated if item["condition"] == "treatment")
    _set_nested_value(treatment, path, value)
    assert pair_request_errors(taskset, mutated)


def test_component_delta_pair_isolation_rejects_baseline_artifact(
    tmp_path: Path,
) -> None:
    taskset, requests, _bindings = _component_requests(tmp_path)
    pair_id = requests[0]["pair_id"]
    mutated = copy.deepcopy([item for item in requests if item["pair_id"] == pair_id])
    baseline = next(item for item in mutated if item["condition"] == "baseline")
    baseline["component_delta"]["artifact"] = "unexpected.json"
    baseline["component_delta"]["artifact_sha256"] = "f" * 64
    assert pair_request_errors(taskset, mutated)


def test_component_delta_evaluation_binds_repository_artifacts_and_complete_pairs(
    tmp_path: Path,
) -> None:
    taskset, requests, _bindings = _component_requests(tmp_path)
    cases = _cases(taskset)
    receipts = [_receipt(request, cases[request["case_id"]]) for request in requests]
    result = evaluate_paired_runs(
        taskset, requests, receipts, measurement_scope="real_paired_agent_runs"
    )
    Draft7Validator(_schema("evaluation")).validate(result)
    comparison = result["comparison"]
    assert comparison["pair_isolation_verified"] is True
    assert comparison["mode"] == "component_delta"
    assert comparison["component"] == "language_structure_json"
    assert comparison["source_revision"] == COMPONENT_REVISION
    assert {item["repository_id"] for item in comparison["treatment_artifacts"]} == {
        item["id"] for item in taskset["repositories"]
    }
    assert all(len(item["artifact_sha256"]) == 64 for item in comparison["treatment_artifacts"])

    missing_pair = requests[0]["pair_id"]
    filtered_requests = [item for item in requests if item["pair_id"] != missing_pair]
    allowed_request_ids = {item["request_id"] for item in filtered_requests}
    filtered_receipts = [
        item for item in receipts if item["request_id"] in allowed_request_ids
    ]
    incomplete = evaluate_paired_runs(
        taskset,
        filtered_requests,
        filtered_receipts,
        measurement_scope="real_paired_agent_runs",
    )
    assert incomplete["comparison"]["pair_isolation_verified"] is False


    baseline_only_requests = [
        item for item in requests if item["condition"] == "baseline"
    ]
    baseline_request_ids = {item["request_id"] for item in baseline_only_requests}
    baseline_only_receipts = [
        item for item in receipts if item["request_id"] in baseline_request_ids
    ]
    baseline_only = evaluate_paired_runs(
        taskset,
        baseline_only_requests,
        baseline_only_receipts,
        measurement_scope="real_paired_agent_runs",
    )
    Draft7Validator(_schema("evaluation")).validate(baseline_only)
    assert baseline_only["comparison"]["treatment_artifacts"] == []
    assert baseline_only["comparison"]["pair_isolation_verified"] is False
