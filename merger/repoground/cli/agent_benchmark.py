"""CLI for the deterministic RepoGround agent benchmark harness."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from merger.repoground.core.agent_benchmark import (
    AgentBenchmarkError,
    build_run_requests,
    evaluate_paired_runs,
    execute_runner,
    load_json,
    require_valid_taskset,
    sha256_json,
    validate_receipt,
    write_json_atomic,
)


def _load_array(path: str | Path) -> list[dict[str, Any]]:
    candidate = Path(path).expanduser().resolve()
    try:
        value = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AgentBenchmarkError(f"cannot read JSON array: {candidate}") from exc
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise AgentBenchmarkError(f"JSON document must be an array of objects: {candidate}")
    return value


def _load_object_files(directory: str | Path) -> list[dict[str, Any]]:
    root = Path(directory).expanduser().resolve()
    if not root.is_dir():
        raise AgentBenchmarkError(f"not a directory: {root}")
    values: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.json")):
        values.append(load_json(path))
    return values


def _command_array(path: str | Path) -> list[str]:
    candidate = Path(path).expanduser().resolve()
    try:
        value = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AgentBenchmarkError(f"cannot read runner command: {candidate}") from exc
    if not isinstance(value, list) or not value or not all(
        isinstance(item, str) and item for item in value
    ):
        raise AgentBenchmarkError("runner command must be a non-empty JSON string array")
    return value


def _emit(value: Any) -> None:
    json.dump(value, sys.stdout, ensure_ascii=False, indent=2, sort_keys=True)
    sys.stdout.write("\n")


def _validate_taskset(args: argparse.Namespace) -> int:
    taskset = load_json(args.taskset)
    require_valid_taskset(taskset)
    _emit(
        {
            "status": "valid",
            "taskset_id": taskset["id"],
            "taskset_sha256": sha256_json(taskset),
            "case_count": len(taskset["cases"]),
            "default_promoted": False,
        }
    )
    return 0


def _plan(args: argparse.Namespace) -> int:
    taskset = load_json(args.taskset)
    runner = load_json(args.runner)
    bindings = load_json(args.manifest_bindings)
    requests = build_run_requests(
        taskset,
        runner=runner,
        manifest_bindings=bindings,
        repetitions=args.repetitions,
    )
    output = Path(args.out).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    request_dir = output / "requests"
    request_dir.mkdir(parents=True, exist_ok=True)
    for request in requests:
        filename = request["request_id"].replace(":", "__") + ".json"
        write_json_atomic(request_dir / filename, request)
    plan = {
        "kind": "repobrief.agent_benchmark_plan",
        "version": "1.0",
        "taskset_id": taskset["id"],
        "taskset_sha256": sha256_json(taskset),
        "repetitions": args.repetitions,
        "request_count": len(requests),
        "requests": [
            {
                "request_id": request["request_id"],
                "pair_id": request["pair_id"],
                "case_id": request["case_id"],
                "condition": request["condition"],
                "repetition": request["repetition"],
                "order": request["order"],
            }
            for request in requests
        ],
        "default_promoted": False,
        "does_not_establish": [
            "runner_availability",
            "real_agent_usefulness",
            "default_promotion",
        ],
    }
    write_json_atomic(output / "plan.json", plan)
    _emit({"status": "planned", "output": str(output), **plan})
    return 0


def _run(args: argparse.Namespace) -> int:
    request = load_json(args.request)
    command = _command_array(args.runner_command)
    receipt = execute_runner(
        command,
        request,
        timeout_seconds=args.timeout_seconds,
        max_stdout_bytes=args.max_stdout_bytes,
    )
    errors = validate_receipt(
        request,
        receipt,
        transcript_root=args.transcript_root,
    )
    write_json_atomic(args.out, receipt)
    _emit(
        {
            "status": "valid" if not errors else "invalid",
            "request_id": request.get("request_id"),
            "receipt": str(Path(args.out).expanduser().resolve()),
            "errors": errors,
        }
    )
    return 0 if not errors else 2


def _validate_receipt(args: argparse.Namespace) -> int:
    request = load_json(args.request)
    receipt = load_json(args.receipt)
    errors = validate_receipt(
        request,
        receipt,
        transcript_root=args.transcript_root,
    )
    _emit(
        {
            "status": "valid" if not errors else "invalid",
            "request_id": request.get("request_id"),
            "errors": errors,
        }
    )
    return 0 if not errors else 2


def _evaluate(args: argparse.Namespace) -> int:
    taskset = load_json(args.taskset)
    requests = _load_object_files(args.requests)
    receipts = _load_object_files(args.receipts)
    result = evaluate_paired_runs(
        taskset,
        requests,
        receipts,
        measurement_scope=args.measurement_scope,
        transcript_root=args.transcript_root,
    )
    write_json_atomic(args.out, result)
    _emit(result)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare, validate and evaluate paired RepoGround agent benchmarks."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_taskset = subparsers.add_parser(
        "validate-taskset", help="Validate the frozen taskset and print its digest."
    )
    validate_taskset.add_argument("--taskset", required=True)
    validate_taskset.set_defaults(handler=_validate_taskset)

    plan = subparsers.add_parser(
        "plan", help="Create balanced isolated baseline/treatment requests."
    )
    plan.add_argument("--taskset", required=True)
    plan.add_argument("--runner", required=True, help="Runner provider/model JSON object.")
    plan.add_argument(
        "--manifest-bindings",
        required=True,
        help="Repository-id to manifest/hash/MCP-command mapping.",
    )
    plan.add_argument("--repetitions", type=int, default=2)
    plan.add_argument("--out", required=True)
    plan.set_defaults(handler=_plan)

    run = subparsers.add_parser("run", help="Run one explicit external agent runner.")
    run.add_argument("--request", required=True)
    run.add_argument(
        "--runner-command",
        required=True,
        help="JSON file containing a command argument array; no shell string is accepted.",
    )
    run.add_argument("--transcript-root")
    run.add_argument("--timeout-seconds", type=int, default=300)
    run.add_argument("--max-stdout-bytes", type=int, default=16 * 1024 * 1024)
    run.add_argument("--out", required=True)
    run.set_defaults(handler=_run)

    validate_receipt = subparsers.add_parser(
        "validate-receipt", help="Validate a receipt against its exact request."
    )
    validate_receipt.add_argument("--request", required=True)
    validate_receipt.add_argument("--receipt", required=True)
    validate_receipt.add_argument("--transcript-root")
    validate_receipt.set_defaults(handler=_validate_receipt)

    evaluate = subparsers.add_parser(
        "evaluate", help="Evaluate paired requests and receipts against the frozen taskset."
    )
    evaluate.add_argument("--taskset", required=True)
    evaluate.add_argument("--requests", required=True)
    evaluate.add_argument("--receipts", required=True)
    evaluate.add_argument("--transcript-root")
    evaluate.add_argument(
        "--measurement-scope",
        choices=["synthetic_contract_fixture", "real_paired_agent_runs"],
        required=True,
    )
    evaluate.add_argument("--out", required=True)
    evaluate.set_defaults(handler=_evaluate)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except AgentBenchmarkError as exc:
        _emit({"status": "error", "error": str(exc)})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
