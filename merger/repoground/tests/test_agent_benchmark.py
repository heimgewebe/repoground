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
    validate_evaluation_derivations,
    validate_evaluation_evidence,
    validate_receipt,
    validate_taskset,
)

from merger.repoground.core.agent_benchmark_evaluation import (
    _class_result,
    _exposure,
    _grounding_exposure,
    _navigation_exposure,
)
from merger.repoground.core.agent_benchmark_requests import (
    pair_request_errors,
    validate_request,
)
from merger.repoground.core.bounded_artifact_read import MAX_REGISTERED_ARTIFACT_BYTES
from merger.repoground.core.language_structure_access import load_language_structure_artifact

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
        "mcp_command": [
            "python",
            "-m",
            "merger.repoground",
            "mcp",
            "--bundle-root",
            "/bench",
        ],
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
    if condition == "baseline":
        tool_name = "read_file"
    elif case["category"] == "grounding_freshness":
        tool_name = "live_freshness"
    else:
        tool_name = "ask_context"
    result = {
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
    if condition == "treatment":
        if case["category"] == "grounding_freshness":
            evidence_call = {
                "sequence": 1,
                "tool": "live_freshness",
                "freshness_status": "fresh",
                "resolved_range_count": None,
                "context_bytes_used": None,
                "grounding_status": None,
            }
        else:
            evidence_call = {
                "sequence": 1,
                "tool": "ask_context",
                "freshness_status": "fresh",
                "resolved_range_count": 1,
                "context_bytes_used": max(1, tool_bytes - tool_bytes // 2),
                "grounding_status": None,
            }
        result["repoground_evidence"] = {
            "target_commit": request["repository"]["commit"],
            "bundle_commit": request["repository"]["commit"],
            "calls": [evidence_call],
        }
    return result


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
def test_taskset_semantic_validation_rejects_manipulation(
    mutation, expected: str
) -> None:
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


def test_codex_cli_live_contract_is_bound_into_requests() -> None:
    runner = {
        "execution_contract": "grabowski-codex-cli-live-v1",
        "provider": "openai-codex-cli",
        "model": "gpt-6-astra",
        "sampling": {"reasoning_effort": "medium"},
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
                "model": "wrong-claude-model",
                "sampling": {},
            },
            "requires model claude-haiku-4-5-20251001",
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
                "execution_contract": "grabowski-codex-cli-live-v1",
                "provider": "fixture-provider",
                "model": "gpt-6-astra",
                "sampling": {"reasoning_effort": "medium"},
            },
            "requires provider openai-codex-cli",
        ),
        (
            {
                "execution_contract": "grabowski-codex-cli-live-v1",
                "provider": "openai-codex-cli",
                "model": "gpt-5",
                "sampling": {"reasoning_effort": "medium"},
            },
            "requires model gpt-6-astra",
        ),
        (
            {
                "execution_contract": "grabowski-codex-cli-live-v1",
                "provider": "openai-codex-cli",
                "model": "gpt-6-astra",
                "sampling": {},
            },
            "requires sampling",
        ),
        (
            {
                "provider": "openai-codex-cli",
                "model": "gpt-6-astra",
                "sampling": {"reasoning_effort": "medium"},
            },
            "requires runner contract grabowski-codex-cli-live-v1",
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


@pytest.mark.parametrize(
    ("runner", "expected"),
    [
        (
            {
                "execution_contract": "grabowski-claude-code-live-v1",
                "provider": "fixture-provider",
                "model": "claude-haiku-4-5-20251001",
                "sampling": {},
            },
            "requires provider anthropic-claude-code",
        ),
        (
            {
                "execution_contract": "grabowski-claude-code-live-v1",
                "provider": "anthropic-claude-code",
                "model": "wrong-claude-model",
                "sampling": {},
            },
            "requires model claude-haiku-4-5-20251001",
        ),
        (
            {
                "execution_contract": "grabowski-codex-cli-live-v1",
                "provider": "openai-codex-cli",
                "model": "gpt-6-astra",
                "sampling": {},
            },
            "requires sampling",
        ),
    ],
)
def test_validate_request_rejects_forged_live_runner_identity(
    runner: dict, expected: str
) -> None:
    taskset = _taskset()
    request = copy.deepcopy(_planned_requests(taskset)[0])
    request["runner"] = runner

    assert any(expected in error for error in validate_request(taskset, request))


def test_pair_plan_requires_treatment_manifest_binding() -> None:
    taskset = _taskset()
    incomplete = dict(BINDINGS)
    incomplete.pop("grabowski")
    with pytest.raises(
        AgentBenchmarkError, match="missing RepoGround manifest binding"
    ):
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
    assert {item["classification"] for item in result["classes"]} == {"synthetic_only"}


def test_live_baseline_without_repoground_binding_remains_valid() -> None:
    taskset = _taskset()
    runner = {
        "execution_contract": "grabowski-claude-code-live-v1",
        "provider": "anthropic-claude-code",
        "model": "claude-haiku-4-5-20251001",
        "sampling": {},
    }
    requests = build_run_requests(
        taskset,
        runner=runner,
        manifest_bindings=BINDINGS,
        repetitions=2,
    )
    request = next(
        item
        for item in requests
        if item["case_id"] == "nav-lenskit-mcp-startup"
        and item["condition"] == "baseline"
    )
    case = _cases(taskset)[request["case_id"]]
    receipt = _receipt(request, case)

    assert request["repobrief"] is None
    assert "repoground_evidence" not in receipt
    assert validate_receipt(request, receipt) == []


def test_historical_treatment_without_normalized_evidence_is_valid_but_not_exposed() -> None:
    taskset = _taskset()
    request = next(
        item
        for item in _planned_requests(taskset)
        if item["case_id"] == "nav-lenskit-mcp-startup"
        and item["condition"] == "treatment"
    )
    case = _cases(taskset)[request["case_id"]]
    receipt = _receipt(request, case)
    receipt.pop("repoground_evidence")
    assert validate_receipt(request, receipt) == []
    score = score_receipt(case, "treatment", request, receipt)
    assert score["valid"] is True
    assert score["exposure"] == {
        "status": "not_exposed",
        "reason": "normalized_repoground_evidence_missing",
    }


def test_exposure_rejects_forged_live_runner_identity() -> None:
    taskset = _taskset()
    request = next(
        item
        for item in _planned_requests(taskset)
        if item["case_id"] == "nav-lenskit-mcp-startup"
        and item["condition"] == "treatment"
    )
    case = _cases(taskset)[request["case_id"]]
    receipt = _receipt(request, case)
    request = copy.deepcopy(request)
    request["runner"] = {
        "execution_contract": "grabowski-claude-code-live-v1",
        "provider": "fixture-provider",
        "model": "fixture-model",
        "sampling": {},
    }

    assert _exposure(case, "treatment", request, receipt) == {
        "status": "not_exposed",
        "reason": "runner_configuration_invalid",
    }


def test_generic_runner_evidence_is_valid_but_not_revision_bound_exposure() -> None:
    taskset = _taskset()
    request = next(
        item
        for item in _planned_requests(taskset)
        if item["case_id"] == "nav-lenskit-mcp-startup"
        and item["condition"] == "treatment"
    )
    case = _cases(taskset)[request["case_id"]]
    receipt = _receipt(request, case)

    assert request["runner"].get("execution_contract") is None
    assert validate_receipt(request, receipt) == []
    score = score_receipt(case, "treatment", request, receipt)
    assert score["valid"] is True
    assert score["exposure"] == {
        "status": "not_exposed",
        "reason": "runner_contract_not_revision_bound",
    }


def test_navigation_exposure_requires_bundle_commit_to_match_target() -> None:
    taskset = _taskset()
    request = next(
        item
        for item in _planned_requests(taskset)
        if item["case_id"] == "nav-lenskit-mcp-startup"
        and item["condition"] == "treatment"
    )
    case = _cases(taskset)[request["case_id"]]
    receipt = _receipt(request, case)
    evidence = receipt["repoground_evidence"]
    evidence["bundle_commit"] = "1" * 40
    calls = [dict(item) for item in evidence["calls"]]
    assert _navigation_exposure(evidence, calls) == {
        "status": "not_exposed",
        "reason": "bundle_commit_does_not_match_target",
    }


def test_navigation_exposure_requires_resolved_bytes_on_one_fresh_ask_call() -> None:
    taskset = _taskset()
    request = next(
        item
        for item in _planned_requests(taskset)
        if item["case_id"] == "nav-lenskit-mcp-startup"
        and item["condition"] == "treatment"
    )
    case = _cases(taskset)[request["case_id"]]
    receipt = _receipt(request, case)
    evidence = receipt["repoground_evidence"]
    calls = [dict(item) for item in evidence["calls"]]
    assert _navigation_exposure(evidence, calls) == {
        "status": "exposed",
        "reason": "ask_context_resolved_evidence",
    }

    calls[0]["resolved_range_count"] = 0
    calls[0]["context_bytes_used"] = 0
    assert _navigation_exposure(evidence, calls) == {
        "status": "not_exposed",
        "reason": "ask_context_no_resolved_ranges",
    }


def test_navigation_exposure_rejects_zero_context_bytes() -> None:
    taskset = _taskset()
    request = next(
        item
        for item in _planned_requests(taskset)
        if item["case_id"] == "nav-lenskit-mcp-startup"
        and item["condition"] == "treatment"
    )
    case = _cases(taskset)[request["case_id"]]
    receipt = _receipt(request, case)
    evidence = receipt["repoground_evidence"]
    calls = [dict(item) for item in evidence["calls"]]
    calls[0]["resolved_range_count"] = 1
    calls[0]["context_bytes_used"] = 0

    assert _navigation_exposure(evidence, calls) == {
        "status": "not_exposed",
        "reason": "ask_context_zero_context_bytes",
    }


def test_navigation_exposure_requires_evidence_on_same_ask_call() -> None:
    taskset = _taskset()
    request = next(
        item
        for item in _planned_requests(taskset)
        if item["case_id"] == "nav-lenskit-mcp-startup"
        and item["condition"] == "treatment"
    )
    case = _cases(taskset)[request["case_id"]]
    receipt = _receipt(request, case)
    evidence = receipt["repoground_evidence"]
    first = dict(evidence["calls"][0])
    first.update(
        {
            "freshness_status": "fresh",
            "resolved_range_count": 1,
            "context_bytes_used": 0,
        }
    )
    second = dict(first)
    second.update(
        {
            "sequence": 2,
            "resolved_range_count": 0,
            "context_bytes_used": 321,
        }
    )

    assert _navigation_exposure(evidence, [first, second]) == {
        "status": "not_exposed",
        "reason": "ask_context_evidence_split_across_calls",
    }


def test_grounding_exposure_accepts_stale_freshness_signal() -> None:
    taskset = _taskset()
    request = next(
        item
        for item in _planned_requests(taskset)
        if item["case_id"] == "grounding-head-mismatch"
        and item["condition"] == "treatment"
    )
    case = _cases(taskset)[request["case_id"]]
    receipt = _receipt(request, case)
    calls = [dict(item) for item in receipt["repoground_evidence"]["calls"]]
    calls[0]["freshness_status"] = "stale"
    assert _grounding_exposure(calls) == {
        "status": "exposed",
        "reason": "live_freshness_signal",
    }


def test_repoground_evidence_is_bound_to_request_target_and_tool_call() -> None:
    taskset = _taskset()
    request = next(
        item
        for item in _planned_requests(taskset)
        if item["case_id"] == "nav-lenskit-mcp-startup"
        and item["condition"] == "treatment"
    )
    case = _cases(taskset)[request["case_id"]]
    receipt = _receipt(request, case)
    receipt["repoground_evidence"]["target_commit"] = "0" * 40
    assert (
        "receipt RepoGround evidence target_commit does not match request"
        in validate_receipt(request, receipt)
    )

    receipt = _receipt(request, case)
    receipt["repoground_evidence"]["bundle_commit"] = "not-a-commit"
    assert (
        "receipt RepoGround evidence bundle_commit is invalid"
        in validate_receipt(request, receipt)
    )

    receipt = _receipt(request, case)
    receipt["repoground_evidence"]["calls"][0]["sequence"] = 2
    assert (
        "receipt RepoGround evidence call does not match tool_calls"
        in validate_receipt(request, receipt)
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("resolved_range_count", "not-an-int"),
        ("resolved_range_count", []),
        ("resolved_range_count", {}),
        ("context_bytes_used", "not-an-int"),
        ("context_bytes_used", []),
        ("context_bytes_used", {}),
    ],
)
def test_invalid_exposure_counters_do_not_abort_public_evaluation(
    field: str, value
) -> None:
    taskset, requests, receipts = _requests_and_receipts()
    target_request = next(
        item
        for item in requests
        if item["case_id"] == "nav-lenskit-mcp-startup"
        and item["condition"] == "treatment"
        and item["repetition"] == 1
    )
    target_receipt = next(
        item for item in receipts if item["request_id"] == target_request["request_id"]
    )
    target_receipt["repoground_evidence"]["calls"][0][field] = value

    result = evaluate_paired_runs(
        taskset,
        requests,
        receipts,
        measurement_scope="real_paired_agent_runs",
    )
    pair = next(
        item
        for item in result["cases"]
        if item["case_id"] == target_request["case_id"]
        and item["repetition"] == target_request["repetition"]
    )
    score = pair["treatment"]
    assert score["valid"] is False
    assert score["exposure"] == {
        "status": "not_exposed",
        "reason": "invalid_receipt",
    }
    assert score["invalid_reasons"]
    assert result["invalid_run_count"] >= 1


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("duration_ms",), "not-an-int"),
        (("provider", "input_tokens"), "not-an-int"),
        (("provider", "output_tokens"), []),
        (("tool_calls", 0, "input_bytes"), "not-an-int"),
        (("tool_calls", 0, "output_bytes"), {}),
    ],
)
def test_invalid_numeric_receipt_fields_do_not_abort_public_evaluation(
    path: tuple, value
) -> None:
    taskset, requests, receipts = _requests_and_receipts()
    target_request = next(
        item
        for item in requests
        if item["case_id"] == "nav-lenskit-mcp-startup"
        and item["condition"] == "treatment"
        and item["repetition"] == 1
    )
    target_receipt = next(
        item for item in receipts if item["request_id"] == target_request["request_id"]
    )
    current = target_receipt
    for key in path[:-1]:
        current = current[key]
    current[path[-1]] = value

    result = evaluate_paired_runs(
        taskset,
        requests,
        receipts,
        measurement_scope="real_paired_agent_runs",
    )
    pair = next(
        item
        for item in result["cases"]
        if item["case_id"] == target_request["case_id"]
        and item["repetition"] == target_request["repetition"]
    )
    score = pair["treatment"]
    assert score["valid"] is False
    assert score["exposure"] == {
        "status": "not_exposed",
        "reason": "invalid_receipt",
    }
    assert score["invalid_reasons"]
    assert result["invalid_run_count"] >= 1


def test_explicit_null_repoground_evidence_is_rejected() -> None:
    taskset = _taskset()
    treatment = next(
        item
        for item in _planned_requests(taskset)
        if item["case_id"] == "nav-lenskit-mcp-startup"
        and item["condition"] == "treatment"
    )
    treatment_receipt = _receipt(
        treatment, _cases(taskset)[treatment["case_id"]]
    )
    treatment_receipt["repoground_evidence"] = None
    assert (
        "receipt RepoGround evidence must be an object"
        in validate_receipt(treatment, treatment_receipt)
    )

    baseline = next(
        item
        for item in _planned_requests(taskset)
        if item["case_id"] == "nav-lenskit-mcp-startup"
        and item["condition"] == "baseline"
    )
    baseline_receipt = _receipt(baseline, _cases(taskset)[baseline["case_id"]])
    baseline_receipt["repoground_evidence"] = None
    assert (
        "baseline receipt must not contain RepoGround evidence"
        in validate_receipt(baseline, baseline_receipt)
    )


def test_ask_context_evidence_cannot_exceed_bound_tool_output() -> None:
    taskset = _taskset()
    request = next(
        item
        for item in _planned_requests(taskset)
        if item["case_id"] == "nav-lenskit-mcp-startup"
        and item["condition"] == "treatment"
    )
    receipt = _receipt(request, _cases(taskset)[request["case_id"]])
    receipt["tool_calls"][0]["output_bytes"] = 0
    assert (
        "receipt RepoGround ask_context context bytes exceed bound tool output"
        in validate_receipt(request, receipt)
    )


def test_live_grounding_evidence_bundle_commit_must_match_bound_manifest(
    tmp_path: Path,
) -> None:
    taskset = _taskset()
    request = next(
        item
        for item in _planned_requests(taskset)
        if item["case_id"] == "grounding-head-mismatch"
        and item["condition"] == "treatment"
    )
    case = _cases(taskset)[request["case_id"]]
    receipt = _receipt(request, case)
    stale_commit = "1" * 40
    manifest = {
        "kind": "repoground.bundle.manifest",
        "version": "2.0",
        "snapshot_provenance": {
            "repositories": [{"git_commit": stale_commit}],
        },
    }
    manifest_raw = json.dumps(
        manifest, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    manifest_path = tmp_path / "grounding.bundle.manifest.json"
    manifest_path.write_bytes(manifest_raw)
    request["repobrief"]["manifest"] = str(manifest_path)
    request["repobrief"]["manifest_sha256"] = sha256_bytes(manifest_raw)
    request["runner"] = {
        "execution_contract": "grabowski-claude-code-live-v1",
        "provider": "anthropic-claude-code",
        "model": "claude-haiku-4-5-20251001",
        "sampling": {},
    }
    receipt["provider"].update(
        {
            "name": "anthropic-claude-code",
            "model": "claude-haiku-4-5-20251001",
            "sampling": {},
        }
    )
    receipt["request_sha256"] = sha256_json(request)
    receipt["repoground_evidence"]["bundle_commit"] = stale_commit
    receipt["repoground_evidence"]["calls"][0]["freshness_status"] = "stale"
    payload = {
        "kind": "repobrief.live_freshness",
        "version": "v1",
        "status": "stale",
        "bundle_manifest": str(manifest_path),
        "snapshot_provenance": {"git_commit": stale_commit},
    }
    _bind_transcript(
        receipt,
        tmp_path,
        "grounding-live-freshness.jsonl",
        [
            {
                "type": "assistant",
                "message": {
                    "content": [{
                        "type": "tool_use",
                        "id": "tool-1",
                        "name": "mcp__repobrief__live_freshness",
                        "input": {},
                    }]
                },
            },
            {
                "type": "user",
                "message": {
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": "tool-1",
                        "content": json.dumps(
                            {"structuredContent": payload}, sort_keys=True
                        ),
                        "is_error": False,
                    }]
                },
            },
        ],
    )
    receipt["tool_calls"][0]["output_bytes"] = 1000

    assert validate_receipt(request, receipt, transcript_root=tmp_path) == []
    assert score_receipt(
        case, "treatment", request, receipt, transcript_root=tmp_path
    )["exposure"] == {
        "status": "exposed",
        "reason": "live_freshness_signal",
    }

    receipt["repoground_evidence"]["bundle_commit"] = "2" * 40
    assert (
        "receipt RepoGround evidence bundle_commit does not match bound manifest"
        in validate_receipt(request, receipt, transcript_root=tmp_path)
    )


def _bind_live_manifest(
    request: dict,
    receipt: dict,
    tmp_path: Path,
    *,
    execution_contract: str,
    provider: str,
    model: str,
    sampling: dict,
    bundle_commit: str,
) -> None:
    manifest = {
        "kind": "repoground.bundle.manifest",
        "version": "2.0",
        "snapshot_provenance": {
            "repositories": [{"git_commit": bundle_commit}],
        },
    }
    raw = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    path = tmp_path / f"{execution_contract}.bundle.manifest.json"
    path.write_bytes(raw)
    request["repobrief"]["manifest"] = str(path)
    request["repobrief"]["manifest_sha256"] = sha256_bytes(raw)
    request["runner"] = {
        "execution_contract": execution_contract,
        "provider": provider,
        "model": model,
        "sampling": sampling,
    }
    receipt["provider"].update(
        {"name": provider, "model": model, "sampling": sampling}
    )
    receipt["request_sha256"] = sha256_json(request)
    receipt["repoground_evidence"]["bundle_commit"] = bundle_commit


def _not_comparable_live_freshness(manifest_path: str) -> dict:
    return {
        "kind": "repobrief.live_freshness",
        "version": "v1",
        "status": "not_comparable",
        "reason": "repo_root_not_configured",
        "bundle_manifest": manifest_path,
        "repo_root": None,
        "read_only_git_probe": False,
        "implicit_refresh": False,
        "does_not_establish": [
            "freshness_against_remote",
            "remote_branch_state",
            "pull_request_diff_current",
            "runtime_correctness",
            "repo_understood",
            "merge_readiness",
        ],
    }


def _ask_context_payload(manifest_sha256: str, manifest_path: str) -> dict:
    return {
        "kind": "repobrief.mcp.read_only_frontdoor",
        "version": "v1",
        "tool": "ask_context",
        "status": "ok",
        "context_pack": {
            "kind": "repobrief.ask_context_pack",
            "version": "1.0",
            "snapshot_ref": {
                "manifest_sha256": manifest_sha256,
                "git_commit": None,
                "freshness_status": "fresh",
            },
            "freshness": {"status": "fresh"},
            "resolved_ranges": [{"path": "src/example.py", "status": "resolved"}],
            "budget": {"context_bytes_used": 321},
        },
        "live_freshness": _not_comparable_live_freshness(manifest_path),
    }


def _bind_transcript(receipt: dict, tmp_path: Path, name: str, events: list[dict]) -> None:
    raw = b"".join(
        json.dumps(event, sort_keys=True).encode("utf-8") + b"\n"
        for event in events
    )
    path = tmp_path / name
    path.write_bytes(raw)
    receipt["transcript"] = {
        "storage": "artifact",
        "sha256": sha256_bytes(raw),
        "bytes": len(raw),
        "inline": None,
        "artifact": name,
    }


@pytest.mark.parametrize("runner_kind", ["claude", "codex"])
def test_live_transcript_accepts_documented_repoground_server_alias(
    tmp_path: Path, runner_kind: str
) -> None:
    taskset = _taskset()
    request = next(
        item
        for item in _planned_requests(taskset)
        if item["case_id"] == "nav-lenskit-mcp-startup"
        and item["condition"] == "treatment"
    )
    case = _cases(taskset)[request["case_id"]]
    receipt = _receipt(request, case)
    commit = request["repository"]["commit"]
    if runner_kind == "claude":
        _bind_live_manifest(
            request,
            receipt,
            tmp_path,
            execution_contract="grabowski-claude-code-live-v1",
            provider="anthropic-claude-code",
            model="claude-haiku-4-5-20251001",
            sampling={},
            bundle_commit=commit,
        )
    else:
        _bind_live_manifest(
            request,
            receipt,
            tmp_path,
            execution_contract="grabowski-codex-cli-live-v1",
            provider="openai-codex-cli",
            model="gpt-6-astra",
            sampling={"reasoning_effort": "medium"},
            bundle_commit=commit,
        )
    payload = _ask_context_payload(
        request["repobrief"]["manifest_sha256"],
        request["repobrief"]["manifest"],
    )
    if runner_kind == "claude":
        events = [
            {
                "type": "assistant",
                "message": {
                    "content": [{
                        "type": "tool_use",
                        "id": "tool-1",
                        "name": "mcp__repoground__ask_context",
                        "input": {"query": "example"},
                    }]
                },
            },
            {
                "type": "user",
                "message": {
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": "tool-1",
                        "content": json.dumps(
                            {"structuredContent": payload}, sort_keys=True
                        ),
                        "is_error": False,
                    }]
                },
            },
        ]
    else:
        events = [{
            "type": "item.completed",
            "item": {
                "type": "mcp_tool_call",
                "server": "repoground",
                "tool": "ask_context",
                "arguments": {"query": "example"},
                "result": {"structured_content": payload},
                "error": None,
                "status": "completed",
            },
        }]
    _bind_transcript(
        receipt,
        tmp_path,
        f"{runner_kind}-repoground-alias.jsonl",
        events,
    )
    receipt["tool_calls"][0]["output_bytes"] = 1000
    receipt["repoground_evidence"]["calls"][0].update(
        {
            "freshness_status": "fresh",
            "resolved_range_count": 1,
            "context_bytes_used": 321,
        }
    )

    assert validate_receipt(request, receipt, transcript_root=tmp_path) == []


def test_live_claude_evidence_must_match_bound_transcript(tmp_path: Path) -> None:
    taskset = _taskset()
    request = next(
        item
        for item in _planned_requests(taskset)
        if item["case_id"] == "nav-lenskit-mcp-startup"
        and item["condition"] == "treatment"
    )
    case = _cases(taskset)[request["case_id"]]
    receipt = _receipt(request, case)
    commit = request["repository"]["commit"]
    _bind_live_manifest(
        request,
        receipt,
        tmp_path,
        execution_contract="grabowski-claude-code-live-v1",
        provider="anthropic-claude-code",
        model="claude-haiku-4-5-20251001",
        sampling={},
        bundle_commit=commit,
    )
    payload = _ask_context_payload(
        request["repobrief"]["manifest_sha256"],
        request["repobrief"]["manifest"],
    )
    events = [
        {
            "type": "assistant",
            "message": {
                "content": [{
                    "type": "tool_use",
                    "id": "tool-1",
                    "name": "mcp__repobrief__ask_context",
                    "input": {"query": "example"},
                }]
            },
        },
        {
            "type": "user",
            "message": {
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": "tool-1",
                    "content": json.dumps(
                        {"structuredContent": payload}, sort_keys=True
                    ),
                    "is_error": False,
                }]
            },
        },
    ]
    _bind_transcript(receipt, tmp_path, "claude.jsonl", events)
    receipt["tool_calls"][0]["output_bytes"] = 1000
    receipt["repoground_evidence"]["calls"][0].update(
        {
            "freshness_status": "fresh",
            "resolved_range_count": 1,
            "context_bytes_used": 321,
        }
    )
    assert validate_receipt(request, receipt, transcript_root=tmp_path) == []

    missing_frontdoor_freshness = copy.deepcopy(payload)
    missing_frontdoor_freshness.pop("live_freshness")
    missing_freshness_events = copy.deepcopy(events)
    missing_freshness_events[1]["message"]["content"][0]["content"] = json.dumps(
        {"structuredContent": missing_frontdoor_freshness}, sort_keys=True
    )
    missing_freshness = copy.deepcopy(receipt)
    _bind_transcript(
        missing_freshness,
        tmp_path,
        "claude-missing-frontdoor-freshness.jsonl",
        missing_freshness_events,
    )
    assert (
        "receipt RepoGround evidence is not supported by bound transcript"
        in validate_receipt(request, missing_freshness, transcript_root=tmp_path)
    )

    wrong_live_payload = copy.deepcopy(payload)
    wrong_live_payload["live_freshness"]["bundle_manifest"] = str(
        tmp_path / "other.bundle.manifest.json"
    )
    wrong_live_events = copy.deepcopy(events)
    wrong_live_events[1]["message"]["content"][0]["content"] = json.dumps(
        {"structuredContent": wrong_live_payload}, sort_keys=True
    )
    wrong_live = copy.deepcopy(receipt)
    _bind_transcript(
        wrong_live,
        tmp_path,
        "claude-wrong-live-manifest.jsonl",
        wrong_live_events,
    )
    assert (
        "receipt RepoGround evidence is not supported by bound transcript"
        in validate_receipt(request, wrong_live, transcript_root=tmp_path)
    )

    wrong_payload = _ask_context_payload(
        "0" * 64,
        request["repobrief"]["manifest"],
    )
    wrong_events = copy.deepcopy(events)
    wrong_events[1]["message"]["content"][0]["content"] = json.dumps(
        {"structuredContent": wrong_payload}, sort_keys=True
    )
    wrong_manifest = copy.deepcopy(receipt)
    _bind_transcript(
        wrong_manifest,
        tmp_path,
        "claude-wrong-manifest.jsonl",
        wrong_events,
    )
    assert (
        "receipt RepoGround evidence is not supported by bound transcript"
        in validate_receipt(request, wrong_manifest, transcript_root=tmp_path)
    )

    missing = json.loads(json.dumps(receipt))
    missing.pop("repoground_evidence")
    assert (
        "receipt RepoGround evidence is required by bound transcript"
        in validate_receipt(request, missing, transcript_root=tmp_path)
    )

    receipt["repoground_evidence"]["calls"][0]["resolved_range_count"] = 999
    assert (
        "receipt RepoGround evidence does not match bound transcript"
        in validate_receipt(request, receipt, transcript_root=tmp_path)
    )


def test_live_ask_context_counts_only_semantically_resolved_ranges(
    tmp_path: Path,
) -> None:
    taskset = _taskset()
    request = next(
        item
        for item in _planned_requests(taskset)
        if item["case_id"] == "nav-lenskit-mcp-startup"
        and item["condition"] == "treatment"
    )
    case = _cases(taskset)[request["case_id"]]
    receipt = _receipt(request, case)
    commit = request["repository"]["commit"]
    _bind_live_manifest(
        request,
        receipt,
        tmp_path,
        execution_contract="grabowski-claude-code-live-v1",
        provider="anthropic-claude-code",
        model="claude-haiku-4-5-20251001",
        sampling={},
        bundle_commit=commit,
    )
    payload = _ask_context_payload(
        request["repobrief"]["manifest_sha256"],
        request["repobrief"]["manifest"],
    )
    payload["context_pack"]["resolved_ranges"] = [
        {"path": "src/missing.py", "status": "missing"}
    ]
    events = [
        {
            "type": "assistant",
            "message": {
                "content": [{
                    "type": "tool_use",
                    "id": "tool-1",
                    "name": "mcp__repobrief__ask_context",
                    "input": {"query": "example"},
                }]
            },
        },
        {
            "type": "user",
            "message": {
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": "tool-1",
                    "content": json.dumps(
                        {"structuredContent": payload}, sort_keys=True
                    ),
                    "is_error": False,
                }]
            },
        },
    ]
    _bind_transcript(receipt, tmp_path, "claude-unresolved.jsonl", events)
    receipt["tool_calls"][0]["output_bytes"] = 1000
    receipt["repoground_evidence"]["calls"][0].update(
        {
            "freshness_status": "fresh",
            "resolved_range_count": 0,
            "context_bytes_used": 321,
        }
    )

    assert validate_receipt(request, receipt, transcript_root=tmp_path) == []
    assert score_receipt(
        case, "treatment", request, receipt, transcript_root=tmp_path
    )["exposure"] == {
        "status": "not_exposed",
        "reason": "ask_context_no_resolved_ranges",
    }


def test_live_freshness_not_comparable_uses_bound_manifest_commit(
    tmp_path: Path,
) -> None:
    taskset = _taskset()
    request = next(
        item
        for item in _planned_requests(taskset)
        if item["case_id"] == "grounding-head-mismatch"
        and item["condition"] == "treatment"
    )
    case = _cases(taskset)[request["case_id"]]
    receipt = _receipt(request, case)
    commit = request["repository"]["commit"]
    _bind_live_manifest(
        request,
        receipt,
        tmp_path,
        execution_contract="grabowski-claude-code-live-v1",
        provider="anthropic-claude-code",
        model="claude-haiku-4-5-20251001",
        sampling={},
        bundle_commit=commit,
    )
    payload = _not_comparable_live_freshness(
        request["repobrief"]["manifest"]
    )
    events = [
        {
            "type": "assistant",
            "message": {
                "content": [{
                    "type": "tool_use",
                    "id": "tool-1",
                    "name": "mcp__repobrief__live_freshness",
                    "input": {},
                }]
            },
        },
        {
            "type": "user",
            "message": {
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": "tool-1",
                    "content": json.dumps(
                        {"structuredContent": payload}, sort_keys=True
                    ),
                    "is_error": False,
                }]
            },
        },
    ]
    _bind_transcript(receipt, tmp_path, "claude-not-comparable.jsonl", events)
    receipt["tool_calls"][0]["output_bytes"] = 1000
    receipt["repoground_evidence"]["bundle_commit"] = commit
    receipt["repoground_evidence"]["calls"][0].update(
        {
            "freshness_status": "not_comparable",
            "resolved_range_count": None,
            "context_bytes_used": None,
            "grounding_status": None,
        }
    )

    assert validate_receipt(request, receipt, transcript_root=tmp_path) == []
    assert score_receipt(
        case, "treatment", request, receipt, transcript_root=tmp_path
    )["exposure"] == {
        "status": "exposed",
        "reason": "live_freshness_signal",
    }


def test_live_freshness_fresh_requires_snapshot_provenance(
    tmp_path: Path,
) -> None:
    taskset = _taskset()
    request = next(
        item
        for item in _planned_requests(taskset)
        if item["case_id"] == "grounding-head-mismatch"
        and item["condition"] == "treatment"
    )
    case = _cases(taskset)[request["case_id"]]
    receipt = _receipt(request, case)
    commit = request["repository"]["commit"]
    _bind_live_manifest(
        request,
        receipt,
        tmp_path,
        execution_contract="grabowski-claude-code-live-v1",
        provider="anthropic-claude-code",
        model="claude-haiku-4-5-20251001",
        sampling={},
        bundle_commit=commit,
    )
    payload = {
        "kind": "repobrief.live_freshness",
        "version": "v1",
        "status": "fresh",
        "reason": "invalid_fixture_missing_snapshot",
        "bundle_manifest": str(request["repobrief"]["manifest"]),
        "repo_root": "/tmp/repo",
        "snapshot_provenance": None,
    }
    events = [
        {
            "type": "assistant",
            "message": {
                "content": [{
                    "type": "tool_use",
                    "id": "tool-1",
                    "name": "mcp__repobrief__live_freshness",
                    "input": {},
                }]
            },
        },
        {
            "type": "user",
            "message": {
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": "tool-1",
                    "content": json.dumps(
                        {"structuredContent": payload}, sort_keys=True
                    ),
                    "is_error": False,
                }]
            },
        },
    ]
    _bind_transcript(receipt, tmp_path, "claude-fresh-without-snapshot.jsonl", events)
    receipt["tool_calls"][0]["output_bytes"] = 1000
    receipt["repoground_evidence"]["bundle_commit"] = commit
    receipt["repoground_evidence"]["calls"][0].update(
        {
            "freshness_status": "fresh",
            "resolved_range_count": None,
            "context_bytes_used": None,
            "grounding_status": None,
        }
    )

    assert (
        "receipt RepoGround evidence is not supported by bound transcript"
        in validate_receipt(request, receipt, transcript_root=tmp_path)
    )


def test_live_grounding_verify_uses_production_verdict_shape(
    tmp_path: Path,
) -> None:
    taskset = _taskset()
    request = next(
        item
        for item in _planned_requests(taskset)
        if item["case_id"] == "grounding-head-mismatch"
        and item["condition"] == "treatment"
    )
    case = _cases(taskset)[request["case_id"]]
    receipt = _receipt(request, case)
    commit = request["repository"]["commit"]
    _bind_live_manifest(
        request,
        receipt,
        tmp_path,
        execution_contract="grabowski-claude-code-live-v1",
        provider="anthropic-claude-code",
        model="claude-haiku-4-5-20251001",
        sampling={},
        bundle_commit=commit,
    )
    payload = {
        "kind": "repobrief.mcp.read_only_frontdoor",
        "version": "v1",
        "tool": "grounding_verify",
        "status": "pass",
        "verdict": {
            "kind": "repobrief.answer_grounding_verdict",
            "version": "1.0",
            "status": "pass",
            "snapshot_ref": {
                "manifest_path": str(request["repobrief"]["manifest"]),
                "freshness_status": "fresh",
            },
        },
        "live_freshness": _not_comparable_live_freshness(
            request["repobrief"]["manifest"]
        ),
    }
    events = [
        {
            "type": "assistant",
            "message": {
                "content": [{
                    "type": "tool_use",
                    "id": "tool-1",
                    "name": "mcp__repobrief__grounding_verify",
                    "input": {"declaration": {}},
                }]
            },
        },
        {
            "type": "user",
            "message": {
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": "tool-1",
                    "content": json.dumps(
                        {"structuredContent": payload}, sort_keys=True
                    ),
                    "is_error": False,
                }]
            },
        },
    ]
    _bind_transcript(receipt, tmp_path, "claude-grounding-verify.jsonl", events)
    receipt["tool_calls"][0].update(
        {"name": "grounding_verify", "output_bytes": 1000}
    )
    receipt["repoground_evidence"]["bundle_commit"] = commit
    receipt["repoground_evidence"]["calls"][0].update(
        {
            "tool": "grounding_verify",
            "freshness_status": "fresh",
            "resolved_range_count": None,
            "context_bytes_used": None,
            "grounding_status": "pass",
        }
    )

    assert validate_receipt(request, receipt, transcript_root=tmp_path) == []


def test_live_codex_evidence_must_match_bound_transcript(tmp_path: Path) -> None:
    taskset = _taskset()
    request = next(
        item
        for item in _planned_requests(taskset)
        if item["case_id"] == "nav-lenskit-mcp-startup"
        and item["condition"] == "treatment"
    )
    case = _cases(taskset)[request["case_id"]]
    receipt = _receipt(request, case)
    commit = request["repository"]["commit"]
    _bind_live_manifest(
        request,
        receipt,
        tmp_path,
        execution_contract="grabowski-codex-cli-live-v1",
        provider="openai-codex-cli",
        model="gpt-6-astra",
        sampling={"reasoning_effort": "medium"},
        bundle_commit=commit,
    )
    payload = _ask_context_payload(
        request["repobrief"]["manifest_sha256"],
        request["repobrief"]["manifest"],
    )
    events = [{
        "type": "item.completed",
        "item": {
            "type": "mcp_tool_call",
            "server": "repobrief",
            "tool": "ask_context",
            "arguments": {"query": "example"},
            "result": {"structured_content": payload},
            "error": None,
            "status": "completed",
        },
    }]
    _bind_transcript(receipt, tmp_path, "codex.jsonl", events)
    receipt["tool_calls"][0]["output_bytes"] = 1000
    receipt["repoground_evidence"]["calls"][0].update(
        {
            "freshness_status": "fresh",
            "resolved_range_count": 1,
            "context_bytes_used": 321,
        }
    )
    assert validate_receipt(request, receipt, transcript_root=tmp_path) == []

    missing = json.loads(json.dumps(receipt))
    missing.pop("repoground_evidence")
    assert (
        "receipt RepoGround evidence is required by bound transcript"
        in validate_receipt(request, missing, transcript_root=tmp_path)
    )

    receipt["repoground_evidence"]["calls"][0]["freshness_status"] = "stale"
    assert (
        "receipt RepoGround evidence does not match bound transcript"
        in validate_receipt(request, receipt, transcript_root=tmp_path)
    )


def test_exposed_harm_precedes_incomplete_exposure() -> None:
    thresholds = _taskset()["thresholds"]

    def score(*, success: bool, exposure: str, duration_ms: int = 100) -> dict:
        return {
            "success": success,
            "false_confidence": False,
            "duration_ms": duration_ms,
            "tool_call_count": 1,
            "input_tokens": 100,
            "output_tokens": 20,
            "tool_bytes": 100,
            "exposure": {"status": exposure, "reason": "fixture"},
        }

    result = _class_result(
        [
            {
                "pair_valid": True,
                "baseline": score(success=True, exposure="not_applicable"),
                "treatment": score(
                    success=False,
                    exposure="exposed",
                    duration_ms=10,
                ),
            },
            {
                "pair_valid": True,
                "baseline": score(success=True, exposure="not_applicable"),
                "treatment": score(success=True, exposure="not_exposed"),
            },
        ],
        thresholds=thresholds,
        measurement_scope="real_paired_agent_runs",
    )
    assert result["valid_pair_count"] == 2
    assert result["exposed_pair_count"] == 1
    assert result["classification"] == "harmful"


def test_exposed_reproduced_efficiency_direction_can_be_useful() -> None:
    thresholds = _taskset()["thresholds"]

    def score(*, duration_ms: int, exposure: str) -> dict:
        return {
            "success": True,
            "false_confidence": False,
            "duration_ms": duration_ms,
            "tool_call_count": 1,
            "input_tokens": 100,
            "output_tokens": 20,
            "tool_bytes": 100,
            "exposure": {"status": exposure, "reason": "fixture"},
        }

    result = _class_result(
        [
            {
                "repetition": repetition,
                "pair_valid": True,
                "baseline": score(
                    duration_ms=100,
                    exposure="not_applicable",
                ),
                "treatment": score(
                    duration_ms=50,
                    exposure="exposed",
                ),
            }
            for repetition in (1, 2)
        ],
        thresholds=thresholds,
        measurement_scope="real_paired_agent_runs",
    )

    assert result["valid_pair_count"] == 2
    assert result["exposed_pair_count"] == 2
    assert result["classification"] == "useful"


def test_real_pair_without_treatment_exposure_is_not_utility_evidence() -> None:
    taskset = _taskset()
    requests = [
        item
        for item in _planned_requests(taskset)
        if item["case_id"] == "nav-lenskit-mcp-startup"
        and item["repetition"] == 1
    ]
    case = _cases(taskset)["nav-lenskit-mcp-startup"]
    receipts = [_receipt(request, case) for request in requests]
    treatment = next(
        receipt
        for receipt, request in zip(receipts, requests, strict=True)
        if request["condition"] == "treatment"
    )
    treatment["repoground_evidence"]["calls"][0]["resolved_range_count"] = 0
    treatment["repoground_evidence"]["calls"][0]["context_bytes_used"] = 0
    result = evaluate_paired_runs(
        taskset,
        requests,
        receipts,
        measurement_scope="real_paired_agent_runs",
    )
    navigation = next(
        item for item in result["classes"] if item["category"] == "navigation"
    )
    assert navigation["valid_pair_count"] == 1
    assert navigation["exposed_pair_count"] == 0
    assert navigation["classification"] == "insufficient_evidence"


def test_real_paired_evaluation_generic_runner_is_insufficient_evidence() -> None:
    taskset, requests, receipts = _requests_and_receipts(treatment_factor=0.5)
    result = evaluate_paired_runs(
        taskset,
        requests,
        receipts,
        measurement_scope="real_paired_agent_runs",
    )

    assert result["decision"]["status"] == "insufficient_evidence"
    assert result["decision"]["useful_classes"] == []
    assert all(item["exposed_pair_count"] == 0 for item in result["classes"])
    assert all(
        item["classification"] == "insufficient_evidence"
        for item in result["classes"]
    )
    assert result["decision"]["default_promoted"] is False


def test_generic_runner_bad_quality_cannot_establish_harm() -> None:
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
    assert navigation["exposed_pair_count"] == 0
    assert navigation["classification"] == "insufficient_evidence"
    assert result["decision"]["status"] == "insufficient_evidence"
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
    filtered_requests = [
        request for request in requests if request["pair_id"] != missing_pair
    ]
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
    assert (
        "request prompt does not match frozen case"
        in condition_score["invalid_reasons"]
    )
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


def _component_treatment_execution_setup(tmp_path: Path) -> tuple[dict, Path]:
    _taskset_value, requests, bindings = _component_requests(tmp_path)
    treatment = next(item for item in requests if item["condition"] == "treatment")
    repository_id = treatment["repository"]["id"]
    artifact = (
        Path(bindings[repository_id]["manifest"]).parent
        / treatment["component_delta"]["artifact"]
    )
    return treatment, artifact


def _marker_runner(tmp_path: Path) -> tuple[list[str], Path]:
    marker = tmp_path / "runner-started.txt"
    runner = tmp_path / "marker-runner.py"
    runner.write_text(
        "import json, sys\n"
        "from pathlib import Path\n"
        "Path(sys.argv[1]).write_text('started', encoding='utf-8')\n"
        "request = json.load(sys.stdin)\n"
        "print(json.dumps({'request_id': request['request_id']}))\n",
        encoding="utf-8",
    )
    return [sys.executable, str(runner), str(marker)], marker


def test_execute_runner_rechecks_unchanged_component_artifact_before_start(
    tmp_path: Path,
) -> None:
    treatment, _artifact = _component_treatment_execution_setup(tmp_path)
    command, marker = _marker_runner(tmp_path)

    result = execute_runner(
        command, treatment, timeout_seconds=5, max_stdout_bytes=1024
    )

    assert result == {"request_id": treatment["request_id"]}
    assert marker.read_text(encoding="utf-8") == "started"


def test_execute_runner_rejects_malformed_component_delta_binding_before_start(
    tmp_path: Path,
) -> None:
    treatment, _artifact = _component_treatment_execution_setup(tmp_path)
    treatment["component_delta"] = None
    command, marker = _marker_runner(tmp_path)

    with pytest.raises(AgentBenchmarkError, match="execution binding is invalid"):
        execute_runner(command, treatment, timeout_seconds=5, max_stdout_bytes=1024)

    assert not marker.exists()


def test_execute_runner_rejects_changed_component_artifact_before_start(
    tmp_path: Path,
) -> None:
    treatment, artifact = _component_treatment_execution_setup(tmp_path)
    artifact.write_text("tampered-after-plan", encoding="utf-8")
    command, marker = _marker_runner(tmp_path)

    with pytest.raises(AgentBenchmarkError, match="artifact SHA-256 mismatch"):
        execute_runner(command, treatment, timeout_seconds=5, max_stdout_bytes=1024)

    assert not marker.exists()


def test_execute_runner_rejects_deleted_component_artifact_before_start(
    tmp_path: Path,
) -> None:
    treatment, artifact = _component_treatment_execution_setup(tmp_path)
    artifact.unlink()
    command, marker = _marker_runner(tmp_path)

    with pytest.raises(AgentBenchmarkError):
        execute_runner(command, treatment, timeout_seconds=5, max_stdout_bytes=1024)

    assert not marker.exists()


def test_execute_runner_rejects_component_artifact_symlink_before_start(
    tmp_path: Path,
) -> None:
    treatment, artifact = _component_treatment_execution_setup(tmp_path)
    target = artifact.with_name("symlink-target.json")
    target.write_bytes(artifact.read_bytes())
    artifact.unlink()
    artifact.symlink_to(target.name)
    command, marker = _marker_runner(tmp_path)

    with pytest.raises(AgentBenchmarkError):
        execute_runner(command, treatment, timeout_seconds=5, max_stdout_bytes=1024)

    assert not marker.exists()


def test_execute_runner_rejects_component_artifact_root_escape_before_start(
    tmp_path: Path,
) -> None:
    treatment, _artifact = _component_treatment_execution_setup(tmp_path)
    treatment["component_delta"]["artifact"] = "../outside.json"
    command, marker = _marker_runner(tmp_path)

    with pytest.raises(AgentBenchmarkError):
        execute_runner(command, treatment, timeout_seconds=5, max_stdout_bytes=1024)

    assert not marker.exists()


def test_execute_runner_rejects_component_artifact_sha_tamper_before_start(
    tmp_path: Path,
) -> None:
    treatment, _artifact = _component_treatment_execution_setup(tmp_path)
    treatment["component_delta"]["artifact_sha256"] = "0" * 64
    command, marker = _marker_runner(tmp_path)

    with pytest.raises(AgentBenchmarkError, match="artifact SHA-256 mismatch"):
        execute_runner(command, treatment, timeout_seconds=5, max_stdout_bytes=1024)

    assert not marker.exists()


def test_execute_runner_rejects_baseline_manifest_that_reintroduces_component(
    tmp_path: Path,
) -> None:
    _taskset_value, requests, bindings = _component_requests(tmp_path)
    baseline = next(item for item in requests if item["condition"] == "baseline")
    treatment = next(item for item in requests if item["condition"] == "treatment")
    repository_id = treatment["repository"]["id"]
    binding = bindings[repository_id]
    baseline_manifest = Path(binding["baseline_manifest"])
    treatment_raw = Path(binding["manifest"]).read_bytes()
    baseline_manifest.write_bytes(treatment_raw)
    baseline["repobrief"]["manifest_sha256"] = sha256_bytes(treatment_raw)
    command, marker = _marker_runner(tmp_path)

    with pytest.raises(AgentBenchmarkError, match="still registers language_structure_json"):
        execute_runner(command, baseline, timeout_seconds=5, max_stdout_bytes=1024)

    assert not marker.exists()


def test_execute_runner_component_delta_baseline_does_not_read_artifact(
    tmp_path: Path,
) -> None:
    _taskset_value, requests, bindings = _component_requests(tmp_path)
    baseline = next(item for item in requests if item["condition"] == "baseline")
    treatment = next(item for item in requests if item["condition"] == "treatment")
    repository_id = treatment["repository"]["id"]
    artifact = (
        Path(bindings[repository_id]["manifest"]).parent
        / treatment["component_delta"]["artifact"]
    )
    artifact.unlink()
    command, marker = _marker_runner(tmp_path)

    result = execute_runner(command, baseline, timeout_seconds=5, max_stdout_bytes=1024)

    assert result == {"request_id": baseline["request_id"]}
    assert marker.read_text(encoding="utf-8") == "started"


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
    empty["transcript"].update({"inline": "", "bytes": 0, "sha256": sha256_bytes(b"")})
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


def _component_taskset(*, source_revision: str = COMPONENT_REVISION) -> dict:
    taskset = copy.deepcopy(_taskset())
    taskset["comparison"] = {
        "mode": "component_delta",
        "component": "language_structure_json",
        "source_revision": source_revision,
    }
    taskset["tool_policy"]["baseline"] = copy.deepcopy(
        taskset["tool_policy"]["treatment"]
    )
    for case in taskset["cases"]:
        case["expectations"]["baseline"] = copy.deepcopy(
            case["expectations"]["treatment"]
        )
    return taskset


def _language_structure_fixture(
    *, repository_id: str, repository_commit: str, manifest_name: str
) -> dict:
    def summary(adapter_id: str) -> dict:
        value = {
            "status": "available",
            "adapter": {"id": adapter_id, "version": "1.0"},
            "supported_files": [],
            "supported_symbols": [],
            "supported_relations": [],
            "range_basis": "fixture",
            "explicit_limits": [],
            "candidate_file_count": 0,
            "scanned_file_count": 0,
            "record_count": 0,
        }
        if adapter_id == "rust-static-structure":
            value["scip_adapter"] = {"id": "rust-scip-structure", "version": "1.0"}
            value["scip_record_count"] = 0
        return value

    return {
        "kind": "repoground.language_structure",
        "version": "1.0",
        "authority": "navigation_index",
        "canonicality": "derived",
        "risk_class": "navigation",
        "run_id": f"fixture-{repository_id}",
        "status": "available",
        "source": {
            "repository_root_name": repository_id,
            "repository_commit": repository_commit,
            "bundle_manifest": manifest_name,
            "canonical_dump_index_sha256": "d" * 64,
            "network_used": False,
            "secrets_read": False,
            "workspace_state_used_beyond_bound_source": False,
        },
        "languages": {
            "bash": summary("bash-static-structure"),
            "rust": summary("rust-static-structure"),
        },
        "records": [],
        "record_count": 0,
        "degradations": [],
        "truncation": None,
        "promotion": {
            "default_promoted": False,
            "status": "keep_optional",
            "reason": "contract fixture",
        },
        "does_not_establish": [
            "repository_truth",
            "complete_symbol_index",
            "complete_call_graph",
            "complete_dependency_graph",
            "runtime_behavior",
            "dynamic_dispatch_resolution",
            "macro_expansion",
            "generated_code_coverage",
            "python_ast_equivalence",
            "test_sufficiency",
            "default_promotion",
        ],
    }


def _component_bindings(
    tmp_path: Path, *, source_revision: str = COMPONENT_REVISION
) -> dict[str, dict]:
    bindings: dict[str, dict] = {}
    for repository in _taskset()["repositories"]:
        repository_id = repository["id"]
        root = tmp_path / repository_id
        root.mkdir(parents=True)
        manifest = root / f"{repository_id}.bundle.manifest.json"
        baseline_manifest = root / f"{repository_id}.baseline.bundle.manifest.json"
        artifact = root / "language_structure.json"
        artifact_raw = (
            json.dumps(
                _language_structure_fixture(
                    repository_id=repository_id,
                    repository_commit=repository["commit"],
                    manifest_name=manifest.name,
                ),
                sort_keys=True,
            )
            + "\n"
        ).encode()
        artifact.write_bytes(artifact_raw)
        artifact_sha256 = sha256_bytes(artifact_raw)
        manifest_document = {
            "kind": "repoground.bundle.manifest",
            "version": "2.0",
            "run_id": f"fixture-{repository_id}",
            "created_at": "2026-08-15T00:00:00Z",
            "generator": {
                "name": "repoground",
                "version": "fixture",
                "config_sha256": "c" * 64,
                "runtime": {
                    "module": "merger.repoground.core.bundle",
                    "python_version": "3.11",
                    "git_commit": source_revision,
                    "git_dirty": False,
                },
            },
            "artifacts": [
                {
                    "role": "language_structure_json",
                    "path": artifact.name,
                    "content_type": "application/json",
                    "bytes": len(artifact_raw),
                    "sha256": artifact_sha256,
                    "contract": {"id": "language-structure", "version": "v1"},
                    "interpretation": {"mode": "contract"},
                    "authority": "navigation_index",
                    "canonicality": "derived",
                    "risk_class": "navigation",
                    "regenerable": True,
                    "staleness_sensitive": True,
                }
            ],
            "links": {"canonical_dump_index_sha256": "d" * 64},
            "capabilities": {},
            "snapshot_provenance": {
                "repositories": [{"git_commit": repository["commit"]}]
            },
        }
        manifest_raw = (json.dumps(manifest_document, sort_keys=True) + "\n").encode()
        manifest.write_bytes(manifest_raw)
        baseline_manifest_document = copy.deepcopy(manifest_document)
        baseline_manifest_document["artifacts"] = []
        baseline_manifest_raw = (
            json.dumps(baseline_manifest_document, sort_keys=True) + "\n"
        ).encode()
        baseline_manifest.write_bytes(baseline_manifest_raw)
        bindings[repository_id] = {
            "manifest": str(manifest),
            "manifest_sha256": sha256_bytes(manifest_raw),
            "baseline_manifest": str(baseline_manifest),
            "baseline_manifest_sha256": sha256_bytes(baseline_manifest_raw),
            "mcp_command": ["python", "-m", "merger.repoground.mcp_server"],
            "components": {
                "language_structure_json": {
                    "source_revision": source_revision,
                    "artifact": artifact.name,
                    "artifact_sha256": artifact_sha256,
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


def test_live_component_delta_baseline_validates_repoground_transcript(
    tmp_path: Path,
) -> None:
    taskset = _component_taskset()
    bindings = _component_bindings(tmp_path)
    runner = {
        "execution_contract": "grabowski-claude-code-live-v1",
        "provider": "anthropic-claude-code",
        "model": "claude-haiku-4-5-20251001",
        "sampling": {},
    }
    requests = build_run_requests(
        taskset,
        runner=runner,
        manifest_bindings=bindings,
        repetitions=2,
    )
    request = next(
        item
        for item in requests
        if item["case_id"] == "nav-lenskit-mcp-startup"
        and item["condition"] == "baseline"
    )
    case = _cases(taskset)[request["case_id"]]
    receipt = _receipt(request, case)
    receipt["tool_calls"][0]["name"] = "ask_context"
    receipt["tool_calls"][0]["output_bytes"] = 1000
    payload = _ask_context_payload(
        request["repobrief"]["manifest_sha256"],
        request["repobrief"]["manifest"],
    )
    events = [
        {
            "type": "assistant",
            "message": {
                "content": [{
                    "type": "tool_use",
                    "id": "tool-1",
                    "name": "mcp__repobrief__ask_context",
                    "input": {"query": "example"},
                }]
            },
        },
        {
            "type": "user",
            "message": {
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": "tool-1",
                    "content": json.dumps(
                        {"structuredContent": payload}, sort_keys=True
                    ),
                    "is_error": False,
                }]
            },
        },
    ]
    _bind_transcript(receipt, tmp_path, "component-baseline.jsonl", events)

    assert "repoground_evidence" not in receipt
    assert validate_receipt(request, receipt, transcript_root=tmp_path) == []
    assert score_receipt(
        case, "baseline", request, receipt, transcript_root=tmp_path
    )["exposure"] == {
        "status": "not_applicable",
        "reason": "baseline_condition",
    }

    wrong_payload = copy.deepcopy(payload)
    wrong_payload["context_pack"]["snapshot_ref"]["manifest_sha256"] = "0" * 64
    wrong_events = copy.deepcopy(events)
    wrong_events[1]["message"]["content"][0]["content"] = json.dumps(
        {"structuredContent": wrong_payload}, sort_keys=True
    )
    wrong = copy.deepcopy(receipt)
    _bind_transcript(
        wrong,
        tmp_path,
        "component-baseline-wrong-manifest.jsonl",
        wrong_events,
    )
    assert (
        "baseline RepoGround tool call is not supported by bound transcript"
        in validate_receipt(request, wrong, transcript_root=tmp_path)
    )


def test_complete_evaluation_contract_rejects_incomplete_objects(
    tmp_path: Path,
) -> None:
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
    incomplete["cases"][0]["treatment"].pop("exposure")
    assert validate_evaluation(incomplete)
    incomplete = copy.deepcopy(evaluation)
    incomplete["classes"][0].pop("exposed_pair_count")
    assert validate_evaluation(incomplete)
    incomplete = copy.deepcopy(evaluation)
    incomplete["classes"][0]["efficiency"].pop("duration")
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
        if tool
        not in {
            "ask_context",
            "repobrief_resource_read",
            "grounding_verify",
            "live_freshness",
        }
    ]
    mutations.append(missing_repoground)
    for mutated in mutations:
        assert validate_taskset(mutated)


def test_evaluation_derivations_are_recomputed_from_case_scores(
    tmp_path: Path,
) -> None:
    taskset, requests, _bindings = _component_requests(tmp_path)
    cases = _cases(taskset)
    receipts = [_receipt(request, cases[request["case_id"]]) for request in requests]
    evaluation = evaluate_paired_runs(
        taskset, requests, receipts, measurement_scope="real_paired_agent_runs"
    )

    assert validate_evaluation(evaluation) == []
    assert validate_evaluation_derivations(evaluation) == []

    legacy_v1 = copy.deepcopy(evaluation)
    legacy_v1.pop("thresholds")
    assert validate_evaluation(legacy_v1) == []
    assert validate_evaluation_derivations(legacy_v1)

    forged_class = copy.deepcopy(evaluation)
    forged_class["classes"][0]["classification"] = "useful"
    assert validate_evaluation_derivations(forged_class)

    forged_decision = copy.deepcopy(evaluation)
    forged_decision["decision"]["status"] = "useful_class"
    forged_decision["decision"]["useful_classes"] = [
        forged_decision["classes"][0]["category"]
    ]
    assert validate_evaluation_derivations(forged_decision)


def test_evaluation_is_bound_to_requests_receipts_and_transcripts(
    tmp_path: Path,
) -> None:
    taskset, requests, _bindings = _component_requests(tmp_path)
    cases = _cases(taskset)
    receipts = [_receipt(request, cases[request["case_id"]]) for request in requests]
    evaluation = evaluate_paired_runs(
        taskset, requests, receipts, measurement_scope="real_paired_agent_runs"
    )

    assert validate_evaluation_evidence(evaluation, taskset, requests, receipts) == []
    assert evaluation["evidence"]["taskset_sha256"] == sha256_json(taskset)
    assert len(evaluation["evidence"]["transcripts"]) == len(receipts)

    forged_evaluation = copy.deepcopy(evaluation)
    forged_evaluation["cases"][0]["baseline"]["success"] = not forged_evaluation["cases"][0][
        "baseline"
    ]["success"]
    assert validate_evaluation_evidence(
        forged_evaluation, taskset, requests, receipts
    )

    changed_receipts = copy.deepcopy(receipts)
    changed_receipts[0]["duration_ms"] += 1
    assert validate_evaluation_evidence(
        evaluation, taskset, requests, changed_receipts
    )

    changed_requests = copy.deepcopy(requests)
    changed_requests[0]["budgets"]["max_tool_calls"] += 1
    assert validate_evaluation_evidence(
        evaluation, taskset, changed_requests, receipts
    )


def test_explicit_empty_comparison_contract_fails_semantic_validation() -> None:
    taskset = copy.deepcopy(_taskset())
    taskset["comparison"] = {}

    assert "comparison contract is invalid" in validate_taskset(taskset)


def test_component_delta_requires_identical_grading_expectations() -> None:
    taskset = _component_taskset()
    baseline = taskset["cases"][0]["expectations"]["baseline"]
    treatment = taskset["cases"][0]["expectations"]["treatment"]
    baseline["outcome"] = "abstain" if treatment["outcome"] != "abstain" else "answer"

    errors = validate_taskset(taskset)

    assert any(
        "component_delta expectations must be identical" in error for error in errors
    )
    with pytest.raises(
        AgentBenchmarkError, match="component_delta expectations must be identical"
    ):
        build_run_requests(taskset, runner=RUNNER, manifest_bindings={}, repetitions=2)


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
            "isolation",
        ):
            assert baseline[field] == treatment[field]
        assert baseline["repobrief"]["mcp_command"] == treatment["repobrief"]["mcp_command"]
        repository_id = treatment["repository"]["id"]
        binding = bindings[repository_id]
        assert baseline["repobrief"] == {
            "manifest": binding["baseline_manifest"],
            "manifest_sha256": binding["baseline_manifest_sha256"],
            "mcp_command": binding["mcp_command"],
        }
        assert treatment["repobrief"] == {
            "manifest": binding["manifest"],
            "manifest_sha256": binding["manifest_sha256"],
            "mcp_command": binding["mcp_command"],
        }
        expected = binding["components"]["language_structure_json"]
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


def _rewrite_component_fixture(
    binding: dict,
    *,
    mutate_artifact=None,
    mutate_manifest=None,
) -> None:
    manifest_path = Path(binding["manifest"])
    component = binding["components"]["language_structure_json"]
    artifact_path = manifest_path.parent / component["artifact"]
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    if mutate_artifact is not None:
        mutate_artifact(artifact)
    artifact_raw = (json.dumps(artifact, sort_keys=True) + "\n").encode()
    artifact_path.write_bytes(artifact_raw)
    component["artifact_sha256"] = sha256_bytes(artifact_raw)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    registered = next(
        item
        for item in manifest.get("artifacts", [])
        if item.get("role") == "language_structure_json"
    )
    registered["sha256"] = component["artifact_sha256"]
    if mutate_manifest is not None:
        mutate_manifest(manifest)
    manifest_raw = (json.dumps(manifest, sort_keys=True) + "\n").encode()
    manifest_path.write_bytes(manifest_raw)
    binding["manifest_sha256"] = sha256_bytes(manifest_raw)


def test_component_delta_requires_exact_component_free_baseline_manifest(
    tmp_path: Path,
) -> None:
    taskset = _component_taskset()
    bindings = _component_bindings(tmp_path / "missing")
    repository_id = taskset["repositories"][0]["id"]
    bindings[repository_id].pop("baseline_manifest")
    bindings[repository_id].pop("baseline_manifest_sha256")
    with pytest.raises(AgentBenchmarkError, match="component-free baseline manifest"):
        build_run_requests(
            taskset, runner=RUNNER, manifest_bindings=bindings, repetitions=2
        )

    bindings = _component_bindings(tmp_path / "leak")
    binding = bindings[repository_id]
    baseline_path = Path(binding["baseline_manifest"])
    treatment_raw = Path(binding["manifest"]).read_bytes()
    baseline_path.write_bytes(treatment_raw)
    binding["baseline_manifest_sha256"] = sha256_bytes(treatment_raw)
    with pytest.raises(AgentBenchmarkError, match="still registers language_structure_json"):
        build_run_requests(
            taskset, runner=RUNNER, manifest_bindings=bindings, repetitions=2
        )

    bindings = _component_bindings(tmp_path / "unrelated")
    binding = bindings[repository_id]
    baseline_path = Path(binding["baseline_manifest"])
    baseline_document = json.loads(baseline_path.read_text(encoding="utf-8"))
    baseline_document["run_id"] = "unrelated-change"
    baseline_raw = (json.dumps(baseline_document, sort_keys=True) + "\n").encode()
    baseline_path.write_bytes(baseline_raw)
    binding["baseline_manifest_sha256"] = sha256_bytes(baseline_raw)
    with pytest.raises(AgentBenchmarkError, match="differ beyond language_structure_json"):
        build_run_requests(
            taskset, runner=RUNNER, manifest_bindings=bindings, repetitions=2
        )


def test_component_delta_baseline_is_missing_through_production_loader(
    tmp_path: Path,
) -> None:
    bindings = _component_bindings(tmp_path)
    binding = next(iter(bindings.values()))

    loaded = load_language_structure_artifact(Path(binding["baseline_manifest"]))

    assert loaded["status"] == "missing"
    assert loaded["reason"] == "language_structure_not_registered"


def test_component_delta_requires_manifest_registration_and_component_contract(
    tmp_path: Path,
) -> None:
    taskset = _component_taskset()
    bindings = _component_bindings(tmp_path)
    repository_id = taskset["repositories"][0]["id"]
    binding = bindings[repository_id]
    manifest_path = Path(binding["manifest"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"] = []
    manifest_raw = (json.dumps(manifest, sort_keys=True) + "\n").encode()
    manifest_path.write_bytes(manifest_raw)
    binding["manifest_sha256"] = sha256_bytes(manifest_raw)
    with pytest.raises(
        AgentBenchmarkError, match="exactly one language_structure_json"
    ):
        build_run_requests(
            taskset, runner=RUNNER, manifest_bindings=bindings, repetitions=2
        )

    bindings = _component_bindings(tmp_path / "contract")
    repository_id = taskset["repositories"][0]["id"]
    binding = bindings[repository_id]
    _rewrite_component_fixture(
        binding,
        mutate_manifest=lambda value: value["artifacts"][0].update(
            contract={"id": "wrong-contract", "version": "v1"}
        ),
    )
    with pytest.raises(AgentBenchmarkError, match="contract mismatch"):
        build_run_requests(
            taskset, runner=RUNNER, manifest_bindings=bindings, repetitions=2
        )


def test_component_delta_requires_schema_valid_revision_bound_component(
    tmp_path: Path,
) -> None:
    taskset = _component_taskset()
    bindings = _component_bindings(tmp_path / "revision")
    repository_id = taskset["repositories"][0]["id"]
    binding = bindings[repository_id]
    _rewrite_component_fixture(
        binding,
        mutate_artifact=lambda value: value["source"].update(
            repository_commit="f" * 40
        ),
    )
    with pytest.raises(AgentBenchmarkError, match="provenance mismatch"):
        build_run_requests(
            taskset, runner=RUNNER, manifest_bindings=bindings, repetitions=2
        )

    bindings = _component_bindings(tmp_path / "schema")
    repository_id = taskset["repositories"][0]["id"]
    binding = bindings[repository_id]
    _rewrite_component_fixture(
        binding, mutate_artifact=lambda value: value.pop("source")
    )
    with pytest.raises(AgentBenchmarkError, match="contract invalid"):
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
        "merger.repoground.core.agent_benchmark_components.read_stable_regular_file_bytes",
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
    assert all(
        len(item["artifact_sha256"]) == 64 for item in comparison["treatment_artifacts"]
    )

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
