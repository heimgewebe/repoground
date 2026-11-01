"""Regression goldset for time-comparable RepoGround agent studies.

Synthetic traces exercise the contract and must never become real evidence.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from merger.repoground.core import agent_study as study
from merger.repoground.cli import agent_study as cli

TASKSET = (
    Path(__file__).resolve().parents[3]
    / "docs/retrieval/repoground_agent_study_cases.v1.json"
)


def gold() -> dict:
    return json.loads(TASKSET.read_text(encoding="utf-8"))


def profile() -> dict:
    return {
        "provider": "test-provider", "model": "test-model-frozen",
        "sampling": {"temperature": 0}, "agent_version": "fixed-agent-v1",
        "runner_version": "trace-runner-v1", "host_class": "test-host",
        "cache_policy": "controlled", "tool_contract": "read-only-a-b-c-v1",
        "tool_names": {
            "git": ["git_search", "git_show"],
            "file": ["read_file"],
            "repoground": ["repoground_query", "repoground_find_symbol"],
        },
    }


def snap(g: dict) -> dict:
    return {
        name: {
            "source_commit": r["commit"],
            "generator_commit": "a" * 40,
            "manifest_path": f"/tmp/{name}.json",
            "manifest_sha256": "b" * 64,
            "health": "pass",
        }
        for name, r in g["repositories"].items()
    }


@pytest.fixture()
def planned(monkeypatch):
    g = gold()
    monkeypatch.setattr(study, "verify_sources", lambda *_args: {"test": 1})
    monkeypatch.setattr(study, "_check_snapshots", lambda _taskset, snapshots: snapshots)
    return study.create_plan(
        g, profile(), snap(g),
        run_id="synthetic-study-20261101", suite="pilot", repetitions=2,
        roots={},
    )


def sample_receipt(req: dict, case: dict, root: Path, *, duration_ms: int = 1500,
                   status: str = "success", use_repoground: bool | None = None) -> dict:
    tool = req["git_file_tool_names"][0]
    if use_repoground is None:
        use_repoground = req["condition"] == "repoground_mandatory"
    if use_repoground:
        tool = req["repoground_tool_names"][0]
    tool_evidence = {}
    if use_repoground:
        ref_name, manifest = next(iter(req["repoground"].items()))
        tool_evidence = {
            "repoground_evidence": {
                "repo": ref_name,
                "source_commit": manifest["source_commit"],
                "generator_commit": manifest["generator_commit"],
                "manifest_sha256": manifest["manifest_sha256"],
                "observed_status": "available",
                "freshness": "pinned_exact",
            }
        }
    paths = deepcopy(case["oracle"]["required_paths"])
    now = datetime(2026, 11, 1, 8, 0, tzinfo=timezone.utc)
    stamp = now.isoformat()
    later = (now + timedelta(milliseconds=duration_ms)).isoformat()
    trace_path = f"trace/{req['request_id']}.jsonl"
    file = root / trace_path
    file.parent.mkdir(parents=True, exist_ok=True)
    transcript = b'{"event":"real-runner-transcript-required","test_only":true}\n'
    file.write_bytes(transcript)
    citation = []
    if paths:
        first = paths[0]
        citation = [{"repo": first["repo"], "path": first["path"],
                     "start_line": 1, "end_line": 2,
                     "commit": req["repositories"][first["repo"]]["commit"]}]
    return {
        "kind": study.RECEIPT_KIND,
        "version": study.VERSION,
        "request_id": req["request_id"], "request_sha256": study.sha256_json(req),
        "condition": req["condition"],
        "session_id": req["session_id"], "workspace_id": req["workspace_id"],
        "runner": req["runner"], "execution_context": req["execution_context"], "status": status,
        "started_at": stamp, "ended_at": later, "duration_ms": duration_ms,
        "usage": {"source": "provider_reported", "input_tokens": 250,
                  "output_tokens": 80, "cached_input_tokens": 110},
        "tool_calls": [{
            "sequence": 1, "name": tool, "status": "success",
            "duration_ms": 200, "input_bytes": 25, "output_bytes": 150,
            **tool_evidence,
        }],
        "answer": {
            "outcome": case["oracle"]["outcome"],
            "reported_paths": paths, "citations": citation,
            "asserted_sufficient_evidence": case["oracle"]["outcome"] == "answer",
        },
        "trace": {"path": trace_path, "bytes": len(transcript),
                  "sha256": hashlib.sha256(transcript).hexdigest()},
        "resources": {"cpu_ms": None, "peak_rss_kib": None},
        "billed_cost": None, "error": None,
    }


def sample_data(plan: dict, root: Path) -> tuple[list[dict], list[dict]]:
    cases = {c["id"]: c for c in gold()["cases"]}
    receipts = []
    grades = []
    for req in plan["requests"]:
        duration = {
            "git_only": 2000,
            "repoground_mandatory": 2900,
            "repoground_selective": 1500,
        }[req["condition"]]
        receipt = sample_receipt(req, cases[req["case_id"]], root, duration_ms=duration)
        receipts.append(receipt)
        grades.append({
            "request_id": req["request_id"], "reviewer": "independent-test-reviewer",
            "receipt_sha256": study.sha256_json(receipt),
            "verdict": "correct", "citations_checked": True,
            "reviewed_at": "2026-11-01T08:00:00Z",
            "evidence_ref": "synthetic:test-only",
        })
    return receipts, grades


def test_frozen_cases_are_stratified_and_two_negatives():
    g = gold()
    details = study.taskset_valid(g)
    assert details["case_count"] == 12
    assert len({case["id"] for case in g["cases"]}) == 12
    assert {c["class"] for c in g["cases"]} == set(study.CLASSES)
    assert sum(c["oracle"]["outcome"] != "answer" for c in g["cases"]) >= 2
    assert len([c for c in g["cases"] if c["pilot"]]) == 6


@pytest.mark.parametrize("field", ["kind", "measurement_scope", "default_promoted"])
def test_frozen_goldset_rejects_identity_mutation(field):
    g = gold()
    g[field] = "wrong"
    with pytest.raises(study.AgentBenchmarkError):
        study.taskset_valid(g)


def test_goldset_source_paths_are_actual_git_blobs():
    roots = {name: Path("/home/alex/repos") / name for name in gold()["repositories"]}
    if not all(root.is_dir() for root in roots.values()):
        pytest.skip("host-specific source checkouts not present")
    for name in roots:
        sha = gold()["repositories"][name]["commit"]
        probe = subprocess.run(["git", "cat-file", "-e", f"{sha}^{{commit}}"],
                               cwd=roots[name], stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, check=False)
        if probe.returncode:
            pytest.skip("frozen Git source commits not materialized on test runner")
    result = study.verify_sources(gold(), roots)
    assert result == {"repoground": 9, "grabowski": 2, "commonthing": 2}


def test_balanced_order_and_no_shared_session_or_workspace(planned):
    requests = planned["requests"]
    assert len(requests) == 36
    assert len({r["session_id"] for r in requests}) == len(requests)
    assert len({r["workspace_id"] for r in requests}) == len(requests)
    for rep in (1, 2):
        sessions = [r for r in requests if r["repetition"] == rep]
        assert len(sessions) == 18
        assert {arm: sum(r["order"] == 1 and r["condition"] == arm for r in sessions)
                for arm in study.ARMS} == {arm: 2 for arm in study.ARMS}
    for request in requests:
        assert request["question"]
        assert "oracle" not in request
        assert "required_paths" not in str(request)
        assert request["condition"] in study.ARMS
        assert request["repoground"] is None if request["condition"] == "git_only" else request["repoground"] is not None


def test_protocol_key_stable_with_new_run_id_and_generator_change(monkeypatch, planned):
    g = gold()
    alt = snap(g)
    for x in alt.values():
        x["generator_commit"] = "c" * 40
    new = study.create_plan(g, profile(), alt, run_id="new-study-20261102",
                            suite="pilot", repetitions=2, roots={})
    assert new["protocol_key"] == planned["protocol_key"]
    assert new["study_sha256"] == planned["study_sha256"]
    altered = profile()
    altered["model"] = "different-model-v1"
    not_comparable = study.create_plan(g, altered, alt, run_id="new-study-20261103",
                                       suite="pilot", repetitions=2, roots={})
    assert not_comparable["protocol_key"] != planned["protocol_key"]


def test_mandatory_requires_actual_successful_repoground_call(planned, tmp_path):
    g = {c["id"]: c for c in gold()["cases"]}
    req = next(r for r in planned["requests"] if r["condition"] == "repoground_mandatory")
    rec = sample_receipt(req, g[req["case_id"]], tmp_path, use_repoground=False)
    assert "mandatory" in " ".join(study.validate_receipt(req, rec, trace_root=tmp_path))
    rec["tool_calls"][0]["name"] = req["repoground_tool_names"][0]
    ref_name, manifest = next(iter(req["repoground"].items()))
    rec["tool_calls"][0]["repoground_evidence"] = {
        "repo": ref_name, "source_commit": manifest["source_commit"],
        "generator_commit": manifest["generator_commit"],
        "manifest_sha256": manifest["manifest_sha256"],
        "observed_status": "available", "freshness": "pinned_exact",
    }
    assert study.validate_receipt(req, rec, trace_root=tmp_path) == []


def test_git_only_cannot_hide_mcp_tool_and_selective_may_skip(planned, tmp_path):
    g = {c["id"]: c for c in gold()["cases"]}
    baseline = next(r for r in planned["requests"] if r["condition"] == "git_only")
    receipt = sample_receipt(baseline, g[baseline["case_id"]], tmp_path)
    receipt["tool_calls"][0]["name"] = "repoground_query"
    assert "unauthorized" in " ".join(study.validate_receipt(baseline, receipt, trace_root=tmp_path))
    selective = next(r for r in planned["requests"] if r["condition"] == "repoground_selective")
    receipt = sample_receipt(selective, g[selective["case_id"]], tmp_path, use_repoground=False)
    assert study.validate_receipt(selective, receipt, trace_root=tmp_path) == []


@pytest.mark.parametrize("mutation", ["hash", "size", "session", "request", "model", "estimated", "timer", "symlink"])
def test_tampered_receipt_rejected(planned, tmp_path, mutation):
    g = {c["id"]: c for c in gold()["cases"]}
    req = planned["requests"][0]
    receipt = sample_receipt(req, g[req["case_id"]], tmp_path)
    if mutation == "hash":
        receipt["trace"]["sha256"] = "0" * 64
    elif mutation == "size":
        receipt["trace"]["bytes"] += 1
    elif mutation == "session":
        receipt["session_id"] = "reused-other-arm"
    elif mutation == "request":
        receipt["request_sha256"] = "1" * 64
    elif mutation == "model":
        receipt["runner"]["model"] = "another-model"
    elif mutation == "estimated":
        receipt["usage"]["source"] = "estimated"
    elif mutation == "timer":
        receipt["duration_ms"] += 2700
    elif mutation == "symlink":
        path = tmp_path / receipt["trace"]["path"]
        link = path.with_suffix(".linked")
        link.symlink_to(path)
        receipt["trace"]["path"] = link.relative_to(tmp_path).as_posix()
    assert study.validate_receipt(req, receipt, trace_root=tmp_path)


def test_evaluation_counts_missing_trials_and_never_calls_them_wins(planned, tmp_path):
    receipt, grades = sample_data(planned, tmp_path)
    report = study.evaluate(planned, gold(), receipt[:-1], grades[:-1],
                            trace_root=tmp_path, measurement_scope="real_runner_reported")
    assert report["planned_trials"] == 36
    assert report["valid_success_trials"] == 35
    assert report["complete_blocks"] == 11
    assert report["decision"]["status"] == "not_established"
    assert any(not r["valid"] for r in report["trials"])


def test_quality_is_not_inferred_from_paths_or_synthetic_fixture(planned, tmp_path):
    receipt, grades = sample_data(planned, tmp_path)
    no_grades = study.evaluate(planned, gold(), receipt, [], trace_root=tmp_path,
                               measurement_scope="real_runner_reported")
    assert no_grades["graded_trials"] == 0
    assert no_grades["complete_blocks"] == 0
    assert no_grades["decision"]["status"] == "not_established"
    fixture = study.evaluate(planned, gold(), receipt, grades, trace_root=tmp_path,
                             measurement_scope="synthetic_contract_fixture")
    assert fixture["complete_blocks"] == 12
    assert fixture["decision"]["status"] == "not_established"
    assert fixture["effects"]["selective_vs_git"]["duration_delta_ms_mean_of_task_means"] == -500


def test_outside_oracle_paths_and_negative_false_confidence_are_visible(planned, tmp_path):
    receipts, grades = sample_data(planned, tmp_path)
    r = next(x for x in receipts if "boundary-invented-symbol" in x["request_id"])
    r["answer"]["outcome"] = "answer"
    r["answer"]["asserted_sufficient_evidence"] = True
    r["answer"]["reported_paths"] = [{"repo": "repoground", "path": "merger/repoground/core/mcp_tools.py"}]
    review = next(g for g in grades if g["request_id"] == r["request_id"])
    review["receipt_sha256"] = study.sha256_json(r)
    result = study.evaluate(planned, gold(), receipts, grades, trace_root=tmp_path,
                            measurement_scope="synthetic_contract_fixture")
    score = next(x["score"] for x in result["trials"] if x["request_id"] == r["request_id"])
    assert score["negative_false_confidence"] is True
    assert score["unsupported_paths"] == 1
    assert score["quality_success"] is False


def test_plan_mutation_rejected_before_score(planned, tmp_path):
    receipt, grades = sample_data(planned, tmp_path)
    altered = deepcopy(planned)
    altered["requests"][0]["question"] = "Surprise"
    with pytest.raises(study.AgentBenchmarkError, match="drift"):
        study.evaluate(altered, gold(), receipt, grades, trace_root=tmp_path,
                       measurement_scope="synthetic_contract_fixture")


def test_pilot_never_proves_default_promotion_even_if_all_runs_were_correct(planned, tmp_path):
    receipts, grades = sample_data(planned, tmp_path)
    result = study.evaluate(planned, gold(), receipts, grades, trace_root=tmp_path,
                            measurement_scope="real_runner_reported")
    assert result["decision"]["status"] == "not_established"
    assert result["conditions"]["git_only"]["valid_success"] == 12
    assert result["conditions"]["repoground_selective"]["valid_success"] == 12
    assert result["conditions"]["repoground_mandatory"]["valid_success"] == 12
    assert result["decision"]["default_promoted"] is False


def test_history_groups_only_equivalent_protocols(planned, tmp_path):
    receipts, grades = sample_data(planned, tmp_path)
    a = study.evaluate(planned, gold(), receipts, grades, trace_root=tmp_path,
                       measurement_scope="synthetic_contract_fixture")
    b = deepcopy(a)
    b["run_id"] = "second-study-20261102"
    b["generator_commits"]["repoground"] = "d" * 40
    c = deepcopy(a)
    c["run_id"] = "different-model-20261103"
    c["protocol_key"] = "e" * 64
    result = study.history([a, b, c])
    assert result["total_runs"] == 3
    assert result["comparison_groups"] == 2
    assert any(len(group["runs"]) == 2 for group in result["groups"])


def test_cli_exports_machine_readable_contract(tmp_path):
    args = cli.build_parser().parse_args(["validate-taskset", "--taskset", str(TASKSET)])
    assert args.func(args) == 0
    target = tmp_path / "existing.json"
    cli._write_new(target, {"kind": "first"})
    with pytest.raises(study.AgentBenchmarkError, match="overwrite"):
        cli._write_new(target, {"kind": "second"})
    assert json.loads(target.read_text()) == {"kind": "first"}


def test_taskset_schema_draft7_matches_frozen_gold():
    jsonschema = pytest.importorskip("jsonschema")
    file = (
        Path(__file__).resolve().parents[1]
        / "contracts/agent-study-taskset.v1.schema.json"
    )
    schema = json.loads(file.read_text())
    jsonschema.Draft7Validator.check_schema(schema)
    jsonschema.validate(gold(), schema)


def test_live_receipt_schema_draft7_matches_synthetic_shape(planned, tmp_path):
    jsonschema = pytest.importorskip("jsonschema")
    file = (
        Path(__file__).resolve().parents[1]
        / "contracts/agent-study-receipt.v1.schema.json"
    )
    schema = json.loads(file.read_text())
    jsonschema.Draft7Validator.check_schema(schema)
    req = planned["requests"][0]
    case = {c["id"]: c for c in gold()["cases"]}[req["case_id"]]
    receipt = sample_receipt(req, case, tmp_path)
    assert study.validate_receipt(req, receipt, trace_root=tmp_path) == []
    jsonschema.validate(receipt, schema)


def test_report_schema_draft7_matches_generated_fixture(planned, tmp_path):
    jsonschema = pytest.importorskip("jsonschema")
    file = (
        Path(__file__).resolve().parents[1]
        / "contracts/agent-study-evaluation.v1.schema.json"
    )
    schema = json.loads(file.read_text())
    jsonschema.Draft7Validator.check_schema(schema)
    receipts, grades = sample_data(planned, tmp_path)
    report = study.evaluate(planned, gold(), receipts, grades, trace_root=tmp_path,
                            measurement_scope="synthetic_contract_fixture")
    jsonschema.validate(report, schema)

def test_manifest_identity_must_match_frozen_git_and_generator(tmp_path):
    """Hashing *some* published manifest does not prove its declared source."""
    taskset = gold()
    bindings = {}
    for name, source in taskset["repositories"].items():
        manifest = {
            "kind": "repoground.bundle.manifest",
            "generator": {"runtime": {"git_commit": "a" * 40, "git_dirty": False}},
            "snapshot_provenance": {"repositories": [{
                "git_commit": source["commit"],
                "git_dirty": False,
                "provenance_status": "present",
                "repo_remote": f"git@github.com:{source['slug']}.git",
            }]},
            "links": {
                "agent_export_gate_status": "pass",
                "bundle_surface_validation_status": "pass",
                "post_emit_health_path": f"{name}.health.json",
            },
        }
        (tmp_path / f"{name}.health.json").write_text(json.dumps({"status": "pass"}))
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        bindings[name] = {
            "source_commit": source["commit"],
            "generator_commit": "a" * 40,
            "manifest_path": str(path),
            "manifest_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "health": "pass",
        }
    assert len(study._check_snapshots(taskset, bindings)) == 3

    manifest_path = tmp_path / "repoground.json"
    original = json.loads(manifest_path.read_text())
    for field, value, expected in [
        ("git_commit", "b" * 40, "manifest source"),
        ("repo_remote", "git@github.com:wrong/repoground.git", "manifest source"),
    ]:
        changed = deepcopy(original)
        changed["snapshot_provenance"]["repositories"][0][field] = value
        manifest_path.write_text(json.dumps(changed), encoding="utf-8")
        bindings["repoground"]["manifest_sha256"] = hashlib.sha256(
            manifest_path.read_bytes()
        ).hexdigest()
        with pytest.raises(study.AgentBenchmarkError, match=expected):
            study._check_snapshots(taskset, bindings)

    original["generator"]["runtime"]["git_commit"] = "b" * 40
    manifest_path.write_text(json.dumps(original), encoding="utf-8")
    bindings["repoground"]["manifest_sha256"] = hashlib.sha256(
        manifest_path.read_bytes()
    ).hexdigest()
    with pytest.raises(study.AgentBenchmarkError, match="manifest generator"):
        study._check_snapshots(taskset, bindings)


@pytest.mark.parametrize("tamper", ["source", "generator", "health", "gate", "remote"])
def test_manifest_claims_must_be_bound_to_real_files(tmp_path, tamper):
    taskset = gold()
    items = {}
    paths = {}
    for name, repo in taskset["repositories"].items():
        directory = tmp_path / name
        directory.mkdir()
        sidecar = directory / "health.json"
        sidecar.write_text(json.dumps({"status": "pass"}) + "\n")
        obj = {
            "kind": "repoground.bundle.manifest",
            "generator": {"runtime": {"git_commit": "a" * 40, "git_dirty": False}},
            "snapshot_provenance": {"repositories": [{
                "git_commit": repo["commit"], "git_dirty": False, "provenance_status": "present",
                "repo_remote": f"git@github.com:{repo['slug']}.git",
            }]},
            "links": {
                "agent_export_gate_status": "pass",
                "bundle_surface_validation_status": "pass",
                "post_emit_health_path": "health.json",
            },
        }
        paths[name] = (obj, directory, sidecar)
        manifest_path = directory / "bundle.manifest.json"
        manifest_path.write_text(json.dumps(obj))
        items[name] = {
            "source_commit": repo["commit"],
            "generator_commit": "a" * 40, "manifest_path": str(manifest_path),
            "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            "health": "pass",
        }

    assert study._check_snapshots(taskset, items)["repoground"]["source_commit"] == (
        taskset["repositories"]["repoground"]["commit"]
    )
    data, directory, sidecar = paths["repoground"]
    if tamper == "source":
        data["snapshot_provenance"]["repositories"][0]["git_commit"] = "d" * 40
    elif tamper == "generator":
        data["generator"]["runtime"]["git_commit"] = "d" * 40
    elif tamper == "gate":
        data["links"]["agent_export_gate_status"] = "fail"
    elif tamper == "remote":
        data["snapshot_provenance"]["repositories"][0]["repo_remote"] = "git@github.com:unrelated/repo.git"
    elif tamper == "health":
        sidecar.write_text(json.dumps({"status": "fail"}))
    manifest_file = directory / "bundle.manifest.json"
    manifest_file.write_text(json.dumps(data))
    items["repoground"]["manifest_sha256"] = hashlib.sha256(manifest_file.read_bytes()).hexdigest()
    with pytest.raises(study.AgentBenchmarkError):
        study._check_snapshots(taskset, items)


def test_paired_tokens_tool_waste_and_per_class_are_in_report(planned, tmp_path):
    receipts, grades = sample_data(planned, tmp_path)
    result = study.evaluate(planned, gold(), receipts, grades, trace_root=tmp_path,
                            measurement_scope="synthetic_contract_fixture")
    assert result["effects"]["selective_vs_git"]["paired_metrics"]["input_tokens"]["mean_delta"] == 0
    assert result["effects"]["mandatory_vs_git"]["paired_metrics"]["tool_calls"]["mean_delta"] == 0
    assert result["conditions"]["repoground_mandatory"]["repoground_calls_total"] == 12
    assert result["conditions"]["git_only"]["repoground_calls_total"] == 0
    assert result["by_class"]["impact_tests"]["valid_success_trials"] == 12
    assert "Task classes" in study.report_markdown(result)


def test_serial_run_batch_skips_only_verified_existing_receipts(planned, tmp_path, monkeypatch):
    plan_path = tmp_path / "plan.json"
    study.write_json_atomic(plan_path, planned)
    trace_root = tmp_path / "traces"
    receipts = tmp_path / "receipts"
    cmd = tmp_path / "cmd.json"
    cmd.write_text(json.dumps(["unused-runner-path"]))
    cases = {c["id"]: c for c in gold()["cases"]}
    called = []

    def fake_runner(command, request, **kwargs):
        called.append(request["request_id"])
        return sample_receipt(request, cases[request["case_id"]], trace_root)

    monkeypatch.setattr(study, "execute_runner", fake_runner)
    args = cli.build_parser().parse_args([
        "run-batch", "--plan", str(plan_path),
        "--runner-command", str(cmd),
        "--trace-root", str(trace_root),
        "--receipts", str(receipts), "--max-runs", "2",
    ])
    assert cli.run_batch(args) == 0
    assert len(called) == 2
    assert cli.run_batch(args) == 0
    assert len(called) == 2  # Existing valid receipts are never re-run.
    damaged = next(receipts.glob("*.json"))
    item = study.load_json(damaged)
    item["trace"]["sha256"] = "f" * 64
    damaged.write_text(json.dumps(item))
    with pytest.raises(study.AgentBenchmarkError, match="existing invalid receipt"):
        cli.run_batch(args)
    assert len(called) == 2


def test_run_batch_persists_runner_failure_and_refuses_silent_retry(planned, tmp_path, monkeypatch):
    """A timeout or malformed agent result must not quietly become another trial."""
    plan_path = tmp_path / "plan.json"
    study.write_json_atomic(plan_path, planned)
    command = tmp_path / "command.json"
    command.write_text(json.dumps(["not-really-a-provider"]))
    trace_root = tmp_path / "traces"
    receipts = tmp_path / "receipts"
    calls = []

    def failed_runner(_command, request, **_kwargs):
        calls.append(request["request_id"])
        raise study.AgentBenchmarkError("runner timed out")

    monkeypatch.setattr(study, "execute_runner", failed_runner)
    args = cli.build_parser().parse_args([
        "run-batch", "--plan", str(plan_path), "--runner-command", str(command),
        "--trace-root", str(trace_root), "--receipts", str(receipts),
        "--max-runs", "1",
    ])
    request = planned["requests"][0]
    with pytest.raises(study.AgentBenchmarkError, match="runner timed out"):
        cli.run_batch(args)
    marker = receipts / ".attempts" / (request["request_id"] + ".json")
    assert marker.is_file()
    attempt = study.load_json(marker)
    assert attempt["status"] == "runner_failed_without_receipt"
    assert attempt["request_sha256"] == study.sha256_json(request)
    assert attempt["error_class"] == "AgentBenchmarkError"
    assert "usage" not in attempt and "input_tokens" not in attempt
    assert not list(receipts.glob("*.json"))

    with pytest.raises(study.AgentBenchmarkError, match="prior attempt exists"):
        cli.run_batch(args)
    assert calls == [request["request_id"]]


def test_started_attempt_without_receipt_stays_non_retryable(planned, tmp_path):
    """A killed process has unknown outcome; rerun may not erase this attempt."""
    request = planned["requests"][0]
    target = tmp_path / "receipts" / (request["request_id"] + ".json")
    marker = cli._reserve_attempt(request, target)
    assert study.load_json(marker)["status"] == "started"
    with pytest.raises(study.AgentBenchmarkError, match="prior attempt exists"):
        cli._reserve_attempt(request, target)
    assert not target.exists()


def test_valid_timeout_consumption_is_counted_without_quality_credit(planned, tmp_path):
    """Successful answers only for quality; failed provider work still costs."""
    receipts, _grades = sample_data(planned, tmp_path)
    baseline = [r for r in receipts if r["condition"] == "git_only"]
    assert len(baseline) == 12
    for item in baseline:
        item["billed_cost"] = {
            "source": "provider_billed", "currency": "USD", "amount": 1.0,
        }
    failed = baseline[0]
    failed["status"] = "timeout"
    failed["error"] = {"class": "RunnerTimeout", "message": "Provider timed out after usage"}
    failed["usage"]["input_tokens"] = 10250
    failed["billed_cost"]["amount"] = 12.0
    request = next(r for r in planned["requests"] if r["request_id"] == failed["request_id"])
    assert study.validate_receipt(request, failed, trace_root=tmp_path) == []

    evaluation = study.evaluate(
        planned, gold(), receipts, [], trace_root=tmp_path,
        measurement_scope="synthetic_contract_fixture",
    )
    arm = evaluation["conditions"]["git_only"]
    assert arm["planned"] == 12
    assert arm["valid_success"] == 11
    assert arm["failed_or_invalid"] == 1
    assert arm["resource_accounted_trials"] == 12
    assert arm["input_tokens_total"] == 13000
    assert arm["cost_billed_total"] == {"currency": "USD", "amount": 23.0}
    assert arm["tool_calls_total"] == 12
    assert arm["tool_time_ms_total"] == 2400
    assert evaluation["valid_success_trials"] == 35
    assert evaluation["decision"]["status"] == "not_established"
