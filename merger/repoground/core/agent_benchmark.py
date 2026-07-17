"""Public orchestration surface for paired RepoGround agent benchmarks.

The benchmark prepares and validates real runner evidence. It does not provide
an LLM, model credentials, token estimation, or a synthetic usefulness claim.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from typing import Any

from merger.repoground.core.agent_benchmark_common import (
    AgentBenchmarkError,
    DOES_NOT_ESTABLISH,
    MAX_JSON_BYTES,
    MAX_RUNNER_STDERR_BYTES,
    REQUEST_KIND,
    VERSION,
    canonical_json,
    is_repository_relative_path,
    list_value,
    load_json,
    mapping_value,
    require_valid_taskset,
    sha256_bytes,
    sha256_json,
    validate_taskset,
    write_json_atomic,
)
from merger.repoground.core.agent_benchmark_evaluation import score_receipt
from merger.repoground.core.agent_benchmark_integrity import evaluate_paired_runs
from merger.repoground.core.agent_benchmark_policy import BENCHMARK_REPETITIONS
from merger.repoground.core.agent_benchmark_receipts import validate_receipt


CLAUDE_CODE_LIVE_CONTRACT = "grabowski-claude-code-live-v1"
CLAUDE_CODE_PROVIDER = "anthropic-claude-code"


def _validate_runner_configuration(runner: Mapping[str, Any]) -> None:
    provider = runner.get("provider")
    model = runner.get("model")
    if not isinstance(provider, str) or not provider:
        raise AgentBenchmarkError("runner provider and model are required")
    if not isinstance(model, str) or not model:
        raise AgentBenchmarkError("runner provider and model are required")

    sampling_value = runner.get("sampling")
    sampling = mapping_value(sampling_value)
    execution_contract = runner.get("execution_contract")
    if execution_contract is not None and execution_contract != CLAUDE_CODE_LIVE_CONTRACT:
        raise AgentBenchmarkError(
            f"unsupported runner execution contract: {execution_contract}"
        )
    if provider == "anthropic":
        raise AgentBenchmarkError(
            "ambiguous provider anthropic is not executable; use anthropic-claude-code"
        )
    if execution_contract == CLAUDE_CODE_LIVE_CONTRACT and provider != CLAUDE_CODE_PROVIDER:
        raise AgentBenchmarkError(
            f"runner contract {CLAUDE_CODE_LIVE_CONTRACT} requires provider "
            f"{CLAUDE_CODE_PROVIDER}"
        )
    if provider == CLAUDE_CODE_PROVIDER and (
        not isinstance(sampling_value, Mapping) or sampling
    ):
        raise AgentBenchmarkError(
            "provider anthropic-claude-code requires an explicit empty sampling object"
        )


def _repository_map(taskset: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item["id"]): dict(item)
        for item in list_value(taskset.get("repositories"))
        if isinstance(item, Mapping) and isinstance(item.get("id"), str)
    }


def _request_identity(
    *, taskset_id: str, case_id: str, repetition: int, condition: str
) -> tuple[str, str, str, str]:
    pair_id = f"{taskset_id}:{case_id}:r{repetition}"
    request_id = f"{pair_id}:{condition}"
    return (
        pair_id,
        request_id,
        f"session:{request_id}",
        f"workspace:{request_id}",
    )


def _condition_order(case_index: int, repetition: int) -> tuple[str, str]:
    baseline_first = (case_index + repetition - 1) % 2 == 0
    return (
        ("baseline", "treatment")
        if baseline_first
        else ("treatment", "baseline")
    )


def _repobrief_binding(
    condition: str,
    repository_id: str,
    manifest_bindings: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any] | None:
    if condition == "baseline":
        return None
    binding = manifest_bindings.get(repository_id)
    if not isinstance(binding, Mapping):
        raise AgentBenchmarkError(
            f"missing RepoGround manifest binding for {repository_id}"
        )
    return {
        "manifest": str(binding["manifest"]),
        "manifest_sha256": str(binding["manifest_sha256"]),
        "mcp_command": list(binding["mcp_command"]),
    }


def _build_request(
    *,
    taskset: Mapping[str, Any],
    taskset_hash: str,
    repository: Mapping[str, Any],
    case: Mapping[str, Any],
    condition: str,
    order: int,
    repetition: int,
    runner: Mapping[str, Any],
    manifest_bindings: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    case_id = str(case["id"])
    repository_id = str(case["repository_id"])
    pair_id, request_id, session_id, workspace_id = _request_identity(
        taskset_id=str(taskset["id"]),
        case_id=case_id,
        repetition=repetition,
        condition=condition,
    )
    return {
        "kind": REQUEST_KIND,
        "version": VERSION,
        "request_id": request_id,
        "pair_id": pair_id,
        "case_id": case_id,
        "condition": condition,
        "order": order,
        "repetition": repetition,
        "taskset_id": str(taskset["id"]),
        "taskset_sha256": taskset_hash,
        "repository": {
            "id": str(repository["id"]),
            "repository": str(repository["repository"]),
            "commit": str(repository["commit"]),
        },
        "session_id": session_id,
        "workspace_id": workspace_id,
        "prompt": str(case["prompt"]),
        "allowed_tools": list(mapping_value(taskset["tool_policy"])[condition]),
        "budgets": dict(mapping_value(taskset["budgets"])),
        "runner": {
            "provider": str(runner["provider"]),
            "model": str(runner["model"]),
            "sampling": dict(mapping_value(runner.get("sampling"))),
            **(
                {"execution_contract": str(runner["execution_contract"])}
                if runner.get("execution_contract") is not None
                else {}
            ),
        },
        "repobrief": _repobrief_binding(
            condition, repository_id, manifest_bindings
        ),
        "isolation": {
            "fresh_session": True,
            "fresh_workspace": True,
            "cross_condition_reuse_allowed": False,
        },
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }


def build_run_requests(
    taskset: Mapping[str, Any],
    *,
    runner: Mapping[str, Any],
    manifest_bindings: Mapping[str, Mapping[str, Any]],
    repetitions: int = BENCHMARK_REPETITIONS,
) -> list[dict[str, Any]]:
    """Build isolated and deterministically balanced paired run requests."""

    require_valid_taskset(taskset)
    if repetitions != BENCHMARK_REPETITIONS:
        raise AgentBenchmarkError(
            f"benchmark v1 requires exactly {BENCHMARK_REPETITIONS} repetitions"
        )
    _validate_runner_configuration(runner)
    repositories = _repository_map(taskset)
    taskset_hash = sha256_json(taskset)
    requests: list[dict[str, Any]] = []
    for repetition in range(1, BENCHMARK_REPETITIONS + 1):
        for case_index, raw_case in enumerate(list_value(taskset.get("cases"))):
            case = mapping_value(raw_case)
            repository = repositories[str(case["repository_id"])]
            for order, condition in enumerate(
                _condition_order(case_index, repetition), start=1
            ):
                requests.append(
                    _build_request(
                        taskset=taskset,
                        taskset_hash=taskset_hash,
                        repository=repository,
                        case=case,
                        condition=condition,
                        order=order,
                        repetition=repetition,
                        runner=runner,
                        manifest_bindings=manifest_bindings,
                    )
                )
    return requests


def _read_runner_output(
    stdout_file, stderr_file, *, max_stdout_bytes: int
) -> tuple[bytes, bytes]:
    stdout_file.seek(0)
    raw = stdout_file.read(max_stdout_bytes + 1)
    stderr_file.seek(0)
    stderr = stderr_file.read(MAX_RUNNER_STDERR_BYTES + 1)
    if len(raw) > max_stdout_bytes:
        raise AgentBenchmarkError("runner stdout exceeds configured limit")
    if len(stderr) > MAX_RUNNER_STDERR_BYTES:
        raise AgentBenchmarkError("runner stderr exceeds configured limit")
    return raw, stderr


def _decode_runner_output(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AgentBenchmarkError("runner stdout is not one UTF-8 JSON object") from exc
    if not isinstance(value, dict):
        raise AgentBenchmarkError("runner stdout must be one JSON object")
    return value


def execute_runner(
    command: Sequence[str],
    request: Mapping[str, Any],
    *,
    timeout_seconds: int,
    max_stdout_bytes: int = MAX_JSON_BYTES,
) -> dict[str, Any]:
    """Execute one explicit runner command with JSON stdin and bounded outputs."""

    if not command or any(not isinstance(item, str) or not item for item in command):
        raise AgentBenchmarkError("runner command must be a non-empty string array")
    if timeout_seconds < 1:
        raise AgentBenchmarkError("runner timeout must be positive")
    request_bytes = (canonical_json(request) + "\n").encode("utf-8")
    with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
        try:
            process = subprocess.Popen(
                list(command),
                stdin=subprocess.PIPE,
                stdout=stdout_file,
                stderr=stderr_file,
                shell=False,
                env=os.environ.copy(),
            )
            process.communicate(request_bytes, timeout=timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            process.kill()
            process.wait()
            raise AgentBenchmarkError("runner timed out") from exc
        except OSError as exc:
            raise AgentBenchmarkError("runner could not be started") from exc
        raw, stderr = _read_runner_output(
            stdout_file, stderr_file, max_stdout_bytes=max_stdout_bytes
        )
    if process.returncode != 0:
        detail = stderr.decode("utf-8", errors="replace").strip()
        raise AgentBenchmarkError(
            f"runner exited with {process.returncode}: {detail[:1000]}"
        )
    return _decode_runner_output(raw)


__all__ = [
    "AgentBenchmarkError",
    "DOES_NOT_ESTABLISH",
    "build_run_requests",
    "canonical_json",
    "evaluate_paired_runs",
    "execute_runner",
    "is_repository_relative_path",
    "load_json",
    "require_valid_taskset",
    "score_receipt",
    "sha256_bytes",
    "sha256_json",
    "validate_receipt",
    "validate_taskset",
    "write_json_atomic",
]
