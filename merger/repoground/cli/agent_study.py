"""CLI for reproducible three-arm longitudinal agent studies.

Reuses the existing agent_benchmark.execute_runner JSON-stdio subprocess boundary.
Never invokes a provider implicitly and never manufactures a real-run receipt.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from merger.repoground.core import agent_study as study


def _load_array(path: str | Path) -> list[dict[str, Any]]:
    p = Path(path)
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise study.AgentBenchmarkError(f"unable to read JSON array: {p}") from exc
    if not isinstance(obj, list) or not all(isinstance(x, dict) for x in obj):
        raise study.AgentBenchmarkError(f"{p}: expected array of JSON objects")
    return obj


def _load_receipts(folder: str | Path) -> list[dict[str, Any]]:
    root = Path(folder)
    if not root.is_dir():
        raise study.AgentBenchmarkError(f"receipt folder unavailable: {root}")
    return [study.load_json(p) for p in sorted(root.glob("*.json"))]


def _write_new(path: str | Path, content: dict[str, Any]) -> None:
    p = Path(path)
    if p.exists() or p.is_symlink():
        raise study.AgentBenchmarkError(f"refusing overwrite: {p}")
    p.parent.mkdir(parents=True, exist_ok=True)
    study.write_json_atomic(p, content)


def _load_argv(path: str | Path) -> list[str]:
    try:
        values = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise study.AgentBenchmarkError("runner command JSON unavailable") from exc
    if not isinstance(values, list) or not values or any(
        not isinstance(x, str) or not x for x in values
    ):
        raise study.AgentBenchmarkError("runner command must be a non-empty JSON argv array")
    return values


def _print(value: dict[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2))


def validate_taskset(args: argparse.Namespace) -> int:
    taskset = study.load_json(args.taskset)
    details = study.taskset_valid(taskset)
    if args.roots:
        details["verified_git_gold_paths"] = study.verify_sources(taskset, study.load_json(args.roots))
    _print({"status": "valid", **details})
    return 0


def plan(args: argparse.Namespace) -> int:
    result = study.create_plan(
        study.load_json(args.taskset),
        study.load_json(args.profile),
        study.load_json(args.snapshots),
        run_id=args.run_id, suite=args.suite, repetitions=args.repetitions,
        roots=study.load_json(args.roots),
    )
    root = Path(args.out).expanduser()
    if root.exists() or root.is_symlink():
        raise study.AgentBenchmarkError("plan output must be a new directory")
    root.mkdir(parents=True, exist_ok=False)
    (root / "requests").mkdir()
    for request in result["requests"]:
        _write_new(root / "requests" / (request["request_id"] + ".json"), request)
    _write_new(root / "plan.json", result)
    _print({"status": "planned", "plan": str(root / "plan.json"),
            "trials": len(result["requests"]), "study_sha256": result["study_sha256"],
            "protocol_key": result["protocol_key"], "suite": args.suite,
            "repetitions": args.repetitions})
    return 0


def _reserve_attempt(request: dict[str, Any], target: Path) -> Path:
    """Persist the decision to launch *before* the external model can run.

    A missing receipt with an existing attempt remains an explicit failed or
    unknown execution. A batch resume must never silently redo that trial.
    """
    identifier = request.get("request_id")
    if not isinstance(identifier, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{1,200}", identifier) is None:
        raise study.AgentBenchmarkError("unsafe request id for durable attempt")
    if target.exists() or target.is_symlink():
        raise study.AgentBenchmarkError(f"existing receipt cannot be overwritten: {target.name}")
    parent = target.parent
    if parent.is_symlink():
        raise study.AgentBenchmarkError("receipt directory must not be symlinked")
    parent.mkdir(parents=True, exist_ok=True)
    ledger = parent / ".attempts"
    if ledger.is_symlink():
        raise study.AgentBenchmarkError("attempt ledger must not be symlinked")
    ledger.mkdir(mode=0o700, exist_ok=True)
    marker = ledger / (identifier + ".json")
    record = {
        "kind": "repoground.agent_study_attempt",
        "version": "1.0",
        "request_id": identifier,
        "request_sha256": study.sha256_json(request),
        "status": "started",
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    content = (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(marker, flags, 0o600)
    except FileExistsError as exc:
        raise study.AgentBenchmarkError(
            f"prior attempt exists, no automatic re-execution: {identifier}"
        ) from exc
    with os.fdopen(fd, "wb") as output:
        output.write(content)
        output.flush()
        os.fsync(output.fileno())
    return marker


def _finish_attempt(marker: Path, request: dict[str, Any], status: str,
                    *, receipt_sha256: str | None = None,
                    error_class: str | None = None) -> None:
    """Write a terminal observation without manufacturing provider usage."""
    study.write_json_atomic(marker, {
        "kind": "repoground.agent_study_attempt",
        "version": "1.0",
        "request_id": request["request_id"],
        "request_sha256": study.sha256_json(request),
        "status": status,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "receipt_sha256": receipt_sha256,
        "error_class": error_class,
        "does_not_establish": ["provider_usage", "answer_correctness", "automatic_retry_authority"],
    })


def _execute_attempt(request: dict[str, Any], command: list[str],
                     target: Path, trace_root: str | Path,
                     timeout_seconds: int) -> list[str]:
    marker = _reserve_attempt(request, target)
    try:
        receipt = study.execute_runner(
            command, request,
            timeout_seconds=timeout_seconds,
            max_stdout_bytes=16 * 1024 * 1024,
        )
    except Exception as exc:
        _finish_attempt(marker, request, "runner_failed_without_receipt",
                        error_class=type(exc).__name__)
        raise
    errors = study.validate_receipt(request, receipt, trace_root=trace_root)
    _write_new(target, receipt)
    _finish_attempt(marker, request, "invalid_receipt" if errors else "receipt_written",
                    receipt_sha256=study.sha256_json(receipt))
    return errors


def run(args: argparse.Namespace) -> int:
    request = study.load_json(args.request)
    command = _load_argv(args.runner_command)
    # The runner must write its own durable trace into trace_root and provide a
    # provider-reported, matching request SHA; the wrapper cannot forge that.
    errors = _execute_attempt(request, command, Path(args.out), args.trace_root, args.timeout_seconds)
    _print({"status": "valid" if not errors else "invalid",
            "request_id": request["request_id"], "receipt": str(args.out),
            "errors": errors})
    return 0 if not errors else 2


def run_batch(args: argparse.Namespace) -> int:
    """Execute only missing requests, in the pre-registered order, without retrying invalid runs."""
    plan_obj = study.load_json(args.plan)
    command = _load_argv(args.runner_command)
    root = Path(args.receipts)
    if root.is_symlink():
        raise study.AgentBenchmarkError("receipt directory must not be symlinked")
    root.mkdir(parents=True, exist_ok=True)
    _limit = args.max_runs if args.max_runs is not None else len(plan_obj["requests"])
    if type(_limit) is not int or not 1 <= _limit <= 144:
        raise study.AgentBenchmarkError("max-runs must be an integer between 1 and 144")
    outcomes = []
    for request in plan_obj["requests"][:_limit]:
        target = root / (request["request_id"] + ".json")
        if target.exists() or target.is_symlink():
            previous = study.load_json(target)
            errors = study.validate_receipt(request, previous, trace_root=args.trace_root)
            if errors:
                raise study.AgentBenchmarkError(
                    f"existing invalid receipt must be inspected, not overwritten: {target.name}: {errors}"
                )
            outcomes.append({"request_id": request["request_id"], "status": "existing_verified"})
            continue
        errors = _execute_attempt(request, command, target, args.trace_root, args.timeout_seconds)
        outcomes.append({"request_id": request["request_id"],
                         "status": "valid" if not errors else "invalid"})
        if errors:
            _print({"status": "invalid", "request_id": request["request_id"],
                    "receipt": str(target), "errors": errors,
                    "completed": len(outcomes)})
            return 2
    _print({"status": "batch_complete", "trials_verified": len(outcomes),
            "new": sum(item["status"] == "valid" for item in outcomes),
            "existing_verified": sum(item["status"] == "existing_verified" for item in outcomes),
            "receipts": str(root)})
    return 0


def validate_receipt(args: argparse.Namespace) -> int:
    req = study.load_json(args.request)
    data = study.load_json(args.receipt)
    errors = study.validate_receipt(req, data, trace_root=args.trace_root)
    _print({"status": "valid" if not errors else "invalid", "errors": errors})
    return 0 if not errors else 2


def evaluate(args: argparse.Namespace) -> int:
    plan_obj = study.load_json(args.plan)
    taskset = study.load_json(args.taskset)
    receipts = _load_receipts(args.receipts)
    grades = _load_array(args.grades) if args.grades else []
    result = study.evaluate(
        plan_obj, taskset, receipts, grades,
        trace_root=args.trace_root, measurement_scope=args.measurement_scope,
    )
    _write_new(args.out, result)
    if args.markdown:
        markdown = Path(args.markdown)
        if markdown.exists() or markdown.is_symlink():
            raise study.AgentBenchmarkError("refusing Markdown report overwrite")
        markdown.parent.mkdir(parents=True, exist_ok=True)
        markdown.write_text(study.report_markdown(result), encoding="utf-8")
    _print({"status": "evaluated", "report": str(args.out),
            "planned": result["planned_trials"],
            "valid_success": result["valid_success_trials"],
            "complete_blocks": result["complete_blocks"],
            "decision": result["decision"]["status"]})
    return 0


def trend(args: argparse.Namespace) -> int:
    root = Path(args.reports)
    if not root.is_dir():
        raise study.AgentBenchmarkError("report directory unavailable")
    files = sorted(root.glob("*.json"))
    report = study.history([study.load_json(path) for path in files])
    _write_new(args.out, report)
    _print({"status": "grouped_by_exact_protocol", "reports": len(files),
            "groups": report["comparison_groups"], "out": str(args.out)})
    return 0


def _write_private_review(path: str | Path, record: Any) -> None:
    """Write each reviewer artifact once, never silently replace prior grades."""
    target = Path(path).expanduser()
    if target.is_symlink() or target.exists():
        raise study.AgentBenchmarkError("refusing overwrite of blinded review artifact")
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if target.parent.is_symlink():
        raise study.AgentBenchmarkError("review artifact directory may not be symlinked")
    content = (json.dumps(
        record, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    ) + "\n").encode("utf-8")
    fd = os.open(
        target, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    with os.fdopen(fd, "wb") as output:
        output.write(content)
        output.flush()
        os.fsync(output.fileno())


def _checked_review_inputs(args: argparse.Namespace) -> tuple[
    dict[str, Any], dict[str, Any], dict[str, dict[str, Any]],
]:
    plan = study.load_json(args.plan)
    taskset = study.load_json(args.taskset)
    study._validate_study_plan(plan, taskset, "real_runner_reported")
    known = {req["request_id"]: req for req in plan["requests"]}
    supplied = _load_receipts(args.receipts)
    if len({x.get("request_id") for x in supplied}) != len(supplied):
        raise study.AgentBenchmarkError("duplicate reviewer input receipt")
    if any(x.get("request_id") not in known for x in supplied):
        raise study.AgentBenchmarkError("unexpected receipt outside planned cohort")
    return plan, taskset, {x["request_id"]: x for x in supplied}


def review_export(args: argparse.Namespace) -> int:
    """Create an arm-blinded source pack and an isolated private lookup key.

    No score or human-grade record is generated by this exporter.
    """
    packet_path = Path(args.out).expanduser().resolve(strict=False)
    key_path = Path(args.mapping_out).expanduser().resolve(strict=False)
    if (
        packet_path == key_path
        or key_path.is_relative_to(packet_path.parent)
        or packet_path.is_relative_to(key_path.parent)
    ):
        raise study.AgentBenchmarkError("private arm mapping must be in another directory")
    plan, taskset, receipts = _checked_review_inputs(args)
    cases = {case["id"]: case for case in taskset["cases"]}
    packet: list[dict[str, Any]] = []
    key: list[dict[str, Any]] = []
    missing = invalid = no_text = 0
    for req in plan["requests"]:
        rec = receipts.get(req["request_id"])
        if rec is None:
            missing += 1
            continue
        if study.validate_receipt(req, rec, trace_root=args.trace_root):
            invalid += 1
            continue
        answer = rec["answer"]
        if (
            not isinstance(answer.get("explanation"), str)
            or not answer["explanation"].strip()
        ):
            no_text += 1
            continue
        review_id = secrets.token_hex(16)
        case = cases[req["case_id"]]
        packet.append({
            "blind_id": review_id,
            "case_id": req["case_id"],
            "question": req["question"],
            "repositories": req["repositories"],
            "oracle": case["oracle"],
            "answer": answer,
        })
        key.append({
            "blind_id": review_id,
            "request_id": req["request_id"],
            "receipt_sha256": study.sha256_json(rec),
            "answer_sha256": study.sha256_json(answer),
        })
    secrets.SystemRandom().shuffle(packet)
    review_packet = {
        "kind": "repoground.blind_review_packet", "version": 1,
        "run_id": plan["run_id"], "protocol_key": plan["protocol_key"],
        "cases": packet,
        "does_not_establish": ["independent_grade", "correctness", "treatment_effect"],
    }
    private_map = {
        "kind": "repoground.blind_review_mapping", "version": 1,
        "run_id": plan["run_id"], "protocol_key": plan["protocol_key"],
        "plan_sha256": study.sha256_json(plan),
        "packet_sha256": study.sha256_json(review_packet),
        "entries": key,
    }
    # Never make a mapping accessible inside the public reviewer directory.
    _write_private_review(args.mapping_out, private_map)
    _write_private_review(args.out, review_packet)
    _print({
        "status": "blind_pack_exported", "reviewable": len(packet),
        "missing": missing, "invalid": invalid, "without_answer_text": no_text,
        "out": str(args.out), "private_mapping": str(args.mapping_out),
    })
    return 0


def review_import(args: argparse.Namespace) -> int:
    """Re-bind supplied independent judgments to their real v2 receipts."""
    plan, taskset, receipts = _checked_review_inputs(args)
    mapping = study.load_json(args.mapping)
    packet = study.load_json(args.packet)
    if (
        mapping.get("kind") != "repoground.blind_review_mapping"
        or mapping.get("version") != 1
        or packet.get("kind") != "repoground.blind_review_packet"
        or packet.get("version") != 1
        or mapping.get("packet_sha256") != study.sha256_json(packet)
        or mapping.get("plan_sha256") != study.sha256_json(plan)
        or mapping.get("protocol_key") != plan["protocol_key"]
        or packet.get("protocol_key") != plan["protocol_key"]
        or mapping.get("run_id") != plan["run_id"]
        or packet.get("run_id") != plan["run_id"]
    ):
        raise study.AgentBenchmarkError("review packet or private mapping digest/identity mismatch")
    cards = packet.get("cases")
    entries = mapping.get("entries")
    if not isinstance(cards, list) or not isinstance(entries, list):
        raise study.AgentBenchmarkError("review packet/mapping records invalid")
    by_id = {x.get("blind_id"): x for x in entries if isinstance(x, dict)}
    cards_by_id = {x.get("blind_id"): x for x in cards if isinstance(x, dict)}
    if (
        len(by_id) != len(entries) or len(cards_by_id) != len(cards)
        or set(by_id) != set(cards_by_id)
    ):
        raise study.AgentBenchmarkError("review card and private mapping inventories differ")
    requests = {req["request_id"]: req for req in plan["requests"]}
    if len({x.get("request_id") for x in entries}) != len(entries):
        raise study.AgentBenchmarkError("duplicate real request identity in private mapping")
    for blind_id, entry in by_id.items():
        req = requests.get(entry.get("request_id"))
        rec = receipts.get(entry.get("request_id"))
        if req is None or rec is None or study.validate_receipt(req, rec, trace_root=args.trace_root):
            raise study.AgentBenchmarkError("review mapping references missing or invalid receipt")
        if (
            entry.get("receipt_sha256") != study.sha256_json(rec)
            or entry.get("answer_sha256") != study.sha256_json(rec["answer"])
            or cards_by_id[blind_id].get("answer") != rec["answer"]
            or cards_by_id[blind_id].get("question") != req["question"]
            or cards_by_id[blind_id].get("case_id") != req["case_id"]
            or cards_by_id[blind_id].get("repositories") != req["repositories"]
            or cards_by_id[blind_id].get("oracle") != next(
                case["oracle"] for case in taskset["cases"] if case["id"] == req["case_id"]
            )
        ):
            raise study.AgentBenchmarkError("review card differs from actual bound answer/receipt")
    blind_grades = _load_array(args.grades)
    if any(set(g) != {
        "blind_id", "verdict", "citations_checked", "reviewer",
        "reviewed_at", "evidence_ref",
    } for g in blind_grades):
        raise study.AgentBenchmarkError("review grade schema must not contain source arm")
    if len({g["blind_id"] for g in blind_grades}) != len(blind_grades):
        raise study.AgentBenchmarkError("duplicate blind reviewer grade")
    if any(g["blind_id"] not in by_id for g in blind_grades):
        raise study.AgentBenchmarkError("review grade references unknown blinded answer")
    unblinded = [
        {
            "request_id": by_id[grade["blind_id"]]["request_id"],
            "receipt_sha256": by_id[grade["blind_id"]]["receipt_sha256"],
            **{k: grade[k] for k in (
                "verdict", "citations_checked", "reviewer", "reviewed_at", "evidence_ref",
            )},
        }
        for grade in blind_grades
    ]
    study._grade_index(unblinded, requests, receipts)
    # Existing evaluate --grades consumes this plain array, not a wrapper.
    _write_private_review(args.out, unblinded)
    _print({"status": "bound_independent_grades", "count": len(unblinded),
            "out": str(args.out)})
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Plan, capture, audit and compare RepoGround A/B/C studies over time."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    test = commands.add_parser("validate-taskset", help="Validate frozen gold cases and optional Git source blobs.")
    test.add_argument("--taskset", required=True)
    test.add_argument("--roots", help="JSON map of repo id to local Git checkout root.")
    test.set_defaults(func=validate_taskset)
    p = commands.add_parser("plan", help="Freeze protocol, manifests, order, source and isolated run requests.")
    p.add_argument("--taskset", required=True)
    p.add_argument("--profile", required=True)
    p.add_argument("--snapshots", required=True)
    p.add_argument("--roots", required=True)
    p.add_argument("--run-id", required=True)
    p.add_argument("--suite", choices=("pilot", "full"), default="pilot")
    p.add_argument("--repetitions", type=int, choices=(1, 2), default=2)
    p.add_argument("--out", required=True)
    p.set_defaults(func=plan)
    r = commands.add_parser("run", help="Run one instrumented external agent with JSON stdin and one receipt.")
    r.add_argument("--request", required=True)
    r.add_argument("--runner-command", required=True, help="JSON argv list, never a shell command.")
    r.add_argument("--trace-root", required=True)
    r.add_argument("--timeout-seconds", type=int, default=300)
    r.add_argument("--out", required=True)
    r.set_defaults(func=run)
    batch = commands.add_parser("run-batch", help="Run planned tasks serially, skipping only verified existing receipts.")
    batch.add_argument("--plan", required=True)
    batch.add_argument("--runner-command", required=True)
    batch.add_argument("--trace-root", required=True)
    batch.add_argument("--receipts", required=True)
    batch.add_argument("--timeout-seconds", type=int, default=300)
    batch.add_argument("--max-runs", type=int, help="Optional first N trials; no retry on errors.")
    batch.set_defaults(func=run_batch)
    v = commands.add_parser("validate-receipt", help="Check one raw result and transcript digest.")
    v.add_argument("--request", required=True)
    v.add_argument("--receipt", required=True)
    v.add_argument("--trace-root", required=True)
    v.set_defaults(func=validate_receipt)
    e = commands.add_parser("evaluate", help="Evaluate every planned run, invalids and independent grades.")
    e.add_argument("--taskset", required=True)
    e.add_argument("--plan", required=True)
    e.add_argument("--receipts", required=True)
    e.add_argument("--trace-root", required=True)
    e.add_argument("--grades", help="External source-reviewed answer verdicts; absent grades are unknown.")
    e.add_argument("--measurement-scope", required=True,
                   choices=("synthetic_contract_fixture", "real_runner_reported"))
    e.add_argument("--out", required=True)
    e.add_argument("--markdown")
    e.set_defaults(func=evaluate)
    reviews = commands.add_parser("review-export", help="Export condition-blinded real model explanations; keep private map separate.")
    reviews.add_argument("--plan", required=True)
    reviews.add_argument("--taskset", required=True)
    reviews.add_argument("--receipts", required=True)
    reviews.add_argument("--trace-root", required=True)
    reviews.add_argument("--out", required=True, help="Share only this blinded JSON file with an independent reviewer.")
    reviews.add_argument("--mapping-out", required=True, help="Secret arm-to-answer map in a separate private directory.")
    reviews.set_defaults(func=review_export)
    reviewed = commands.add_parser("review-import", help="Bind actual independent blinded grades to verified receipts.")
    reviewed.add_argument("--plan", required=True)
    reviewed.add_argument("--taskset", required=True)
    reviewed.add_argument("--receipts", required=True)
    reviewed.add_argument("--trace-root", required=True)
    reviewed.add_argument("--packet", required=True)
    reviewed.add_argument("--mapping", required=True)
    reviewed.add_argument("--grades", required=True, help="Reviewer-supplied verdicts with blind_id; never generated by CLI.")
    reviewed.add_argument("--out", required=True)
    reviewed.set_defaults(func=review_import)
    t = commands.add_parser("trend", help="Separate incompatible protocols in a versioned report history.")
    t.add_argument("--reports", required=True)
    t.add_argument("--out", required=True)
    t.set_defaults(func=trend)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except (study.AgentBenchmarkError, FileNotFoundError, PermissionError) as exc:
        _print({"status": "error", "error": str(exc)})
        return 2


if __name__ == "__main__":
    sys.exit(main())