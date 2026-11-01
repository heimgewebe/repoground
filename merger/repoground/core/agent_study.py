"""Longitudinal three-arm agent study built on the existing JSON-stdio runner.

This is a *measurement* boundary. It neither provides an LLM nor infers answer
correctness from token matches. Synthetic receipts cannot establish utility.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import itertools
import math
from pathlib import Path, PurePosixPath
import random
import re
import statistics
from typing import Any, Mapping, Sequence

from merger.repoground.core.agent_benchmark import (
    AgentBenchmarkError,
    execute_runner,
    load_json,
    sha256_json,
    write_json_atomic,
)

VERSION = "1.0"
TASKSET_KIND = "repoground.agent_study_taskset"
PLAN_KIND = "repoground.agent_study_plan"
REQUEST_KIND = "repoground.agent_study_request"
RECEIPT_KIND = "repoground.agent_study_receipt"
REPORT_KIND = "repoground.agent_study_report"
ARMS = ("git_only", "repoground_mandatory", "repoground_selective")
CLASSES = ("known_target", "reverse_relations", "impact_tests", "boundary")
SHA40 = re.compile(r"[0-9a-f]{40}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
SLUG = re.compile(r"[a-z0-9][a-z0-9-]{2,79}\Z")
MAX_TRIALS = 144
MAX_TRACE = 32 * 1024 * 1024
MAX_CALLS = 160
PERMUTATIONS = tuple(itertools.permutations(ARMS))
DECISION_LIMITS = {
    "minimum_complete_tasks": 12,
    "minimum_repetitions": 2,
    "maximum_incorrect_delta": 0,
    "maximum_false_confidence_delta": 0,
}


def _need(predicate: bool, message: str) -> None:
    if not predicate:
        raise AgentBenchmarkError(message)


def _object(value: Any, label: str) -> dict[str, Any]:
    _need(isinstance(value, dict), f"{label}: expected JSON object")
    return value


def _iso(value: Any, label: str) -> datetime:
    _need(isinstance(value, str) and len(value) <= 40, f"{label}: ISO timestamp required")
    try:
        date = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AgentBenchmarkError(f"{label}: invalid ISO timestamp") from exc
    _need(date.tzinfo is not None and date.utcoffset() is not None, f"{label}: timezone required")
    return date.astimezone(timezone.utc)


def _nonnegative(value: Any, label: str) -> int:
    _need(type(value) is int and value >= 0, f"{label}: nonnegative integer required")
    return value


def _path(value: Any, label: str) -> str:
    _need(isinstance(value, str) and 0 < len(value) <= 400, f"{label}: bounded path required")
    _need(
        value == PurePosixPath(value).as_posix()
        and not value.startswith(("/", "-", "\\"))
        and "\\" not in value
        and not any(part in (".", "..", "") for part in value.split("/"))
        and not any(ord(char) < 32 for char in value),
        f"{label}: unsafe repository path",
    )
    return value


def _ref(value: Any, repositories: Mapping[str, Any], label: str) -> tuple[str, str]:
    item = _object(value, label)
    _need(set(item) == {"repo", "path"}, f"{label}: expected repo/path only")
    repo = item["repo"]
    _need(repo in repositories, f"{label}: unknown repository")
    return str(repo), _path(item["path"], label)


def taskset_valid(taskset: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the *frozen* oracle; a new oracle revision is a new study."""
    _need(taskset.get("kind") == TASKSET_KIND and taskset.get("version") == VERSION, "taskset kind/version mismatch")
    _need(taskset.get("measurement_scope") == "frozen_three_arm_agent_study", "taskset scope mismatch")
    _need(taskset.get("default_promoted") is False, "promotion cannot be the taskset default")
    _need(isinstance(taskset.get("id"), str) and SLUG.fullmatch(taskset["id"]), "bad taskset id")
    repositories = _object(taskset.get("repositories"), "repositories")
    _need(len(repositories) >= 2, "need multiple repositories")
    for name, raw in repositories.items():
        _need(isinstance(name, str) and SLUG.fullmatch(name), "bad repository id")
        r = _object(raw, f"repository {name}")
        _need(isinstance(r.get("slug"), str) and r["slug"].count("/") == 1, "repository slug required")
        _need(isinstance(r.get("commit"), str) and SHA40.fullmatch(r["commit"]), "frozen 40-hex commit required")
    cases = taskset.get("cases")
    _need(isinstance(cases, list) and len(cases) == 12, "v1 requires 12 frozen cases")
    ids: set[str] = set()
    classes: Counter[str] = Counter()
    negative = 0
    for raw in cases:
        case = _object(raw, "case")
        cid = case.get("id")
        _need(isinstance(cid, str) and SLUG.fullmatch(cid) and cid not in ids, "case id missing/duplicate/invalid")
        ids.add(cid)
        cls = case.get("class")
        _need(cls in CLASSES, f"{cid}: unknown task class")
        classes[cls] += 1
        _need(isinstance(case.get("pilot"), bool), f"{cid}: pilot flag required")
        question = case.get("question")
        _need(isinstance(question, str) and 12 <= len(question) <= 1200, f"{cid}: question required")
        scope = case.get("repositories")
        _need(isinstance(scope, list) and scope and len(scope) == len(set(scope)) and all(r in repositories for r in scope), f"{cid}: repository scope invalid")
        expectation = _object(case.get("oracle"), f"{cid}.oracle")
        _need(expectation.get("outcome") in ("answer", "abstain", "unavailable"), f"{cid}: unknown outcome")
        needed = expectation.get("required_paths")
        allowed = expectation.get("allowed_paths")
        _need(isinstance(needed, list) and isinstance(allowed, list), f"{cid}: required/allowed paths required")
        req = [_ref(x, repositories, cid) for x in needed]
        all_paths = [_ref(x, repositories, cid) for x in allowed]
        _need(len(set(req)) == len(req) and len(set(all_paths)) == len(all_paths), f"{cid}: duplicate gold paths")
        _need(set(req).issubset(all_paths), f"{cid}: required_paths not in allowed_paths")
        _need(all(r in scope for r, _ in all_paths), f"{cid}: gold paths outside case scope")
        if expectation["outcome"] != "answer":
            negative += 1
            _need(not req, f"{cid}: negative case cannot require exact answer paths")
        else:
            _need(bool(req), f"{cid}: answer case must have required paths")
        _need(isinstance(expectation.get("rationale"), str) and len(expectation["rationale"]) >= 12, f"{cid}: independent oracle rationale required")
    _need(all(classes[cls] == 3 for cls in CLASSES), "v1 requires three tasks in each of four classes")
    _need(negative >= 2, "v1 requires at least two unknown/unavailable controls")
    _need(sum(bool(c["pilot"]) for c in cases) == 6, "v1 requires exactly six pilot cases")
    _need(set(taskset.get("arms", [])) == set(ARMS) and len(taskset["arms"]) == 3, "all three arms are required")
    return {"taskset_id": taskset["id"], "taskset_sha256": sha256_json(taskset), "case_count": len(cases)}


def _profile(profile: Mapping[str, Any]) -> dict[str, Any]:
    required = ("provider", "model", "sampling", "agent_version", "runner_version",
                "host_class", "cache_policy", "tool_contract", "tool_names")
    for field in required:
        _need(field in profile, f"profile: missing {field}")
    for name in ("provider", "model", "agent_version", "runner_version", "host_class", "cache_policy", "tool_contract"):
        _need(isinstance(profile[name], str) and 0 < len(profile[name]) <= 160, f"profile.{name}: bounded string required")
    _need(profile["cache_policy"] in ("cold", "warm", "controlled"), "cache_policy must be explicit")
    _need(isinstance(profile["sampling"], dict), "sampling config must be object")
    names = _object(profile["tool_names"], "tool_names")
    _need(all(x in names for x in ("git", "file", "repoground")), "tool_names needs git/file/repoground")
    for key, values in names.items():
        _need(key in ("git", "file", "repoground") and isinstance(values, list) and
              bool(values) and len(set(values)) == len(values) and
              all(isinstance(v, str) and re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_.-]{1,100}", v) for v in values),
              f"tool_names.{key} invalid")
    _need(not (set(names["git"]) | set(names["file"])) & set(names["repoground"]), "RepoGround tools overlap Git/file")
    return dict(profile)


def verify_sources(taskset: Mapping[str, Any], roots: Mapping[str, Any]) -> dict[str, int]:
    """Read Git blobs at pinned *commit*, not the mutable working-tree files."""
    import subprocess

    counts: dict[str, int] = {}
    for name, info in taskset["repositories"].items():
        root = Path(str(roots.get(name, ""))).expanduser().resolve()
        _need(root.is_dir(), f"{name}: source checkout not found")
        p = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=root,
                           capture_output=True, timeout=15, check=False)
        _need(p.returncode == 0 and Path(p.stdout.decode().strip()).resolve() == root,
              f"{name}: root must be canonical Git checkout")
        refs = {
            entry["path"] for case in taskset["cases"]
            for entry in case["oracle"]["allowed_paths"] if entry["repo"] == name
        }
        for path in sorted(refs):
            result = subprocess.run(["git", "cat-file", "-e", f'{info["commit"]}:{path}'],
                                    cwd=root, capture_output=True, timeout=15, check=False)
            _need(result.returncode == 0, f"{name}:{info['commit']}:{path}: unverified gold path")
        counts[name] = len(refs)
    return counts


def _check_snapshots(taskset: Mapping[str, Any], snapshots: Mapping[str, Any]) -> dict[str, Any]:
    result = {}
    for name, source in taskset["repositories"].items():
        rec = _object(snapshots.get(name), f"snapshot {name}")
        _need(rec.get("source_commit") == source["commit"], f"{name}: snapshot source SHA drift")
        _need(isinstance(rec.get("generator_commit"), str) and SHA40.fullmatch(rec["generator_commit"]), f"{name}: generator SHA invalid")
        _need(isinstance(rec.get("manifest_sha256"), str) and SHA256.fullmatch(rec["manifest_sha256"]), f"{name}: manifest SHA invalid")
        _need(rec.get("health") == "pass", f"{name}: unhealthy snapshot")
        manifest_path = rec.get("manifest_path")
        _need(isinstance(manifest_path, str) and manifest_path.startswith("/"), f"{name}: absolute manifest path required")
        p = Path(manifest_path)
        _need(p.is_file() and not p.is_symlink() and p.stat().st_size <= 16 * 1024 * 1024, f"{name}: manifest file unavailable")
        _need(hashlib.sha256(p.read_bytes()).hexdigest() == rec["manifest_sha256"], f"{name}: manifest bytes mismatch")
        # The input JSON can claim an arbitrary source SHA while hashing an
        # unrelated *real* manifest. Cross-check the manifest's own provenance.
        manifest = load_json(p)
        _need(manifest.get("kind") == "repoground.bundle.manifest", f"{name}: wrong manifest kind")
        generator = _object(manifest.get("generator"), f"{name}.manifest.generator")
        runtime = _object(generator.get("runtime"), f"{name}.manifest.generator.runtime")
        _need(
            runtime.get("git_commit") == rec["generator_commit"]
            and runtime.get("git_dirty") is False,
            f"{name}: manifest generator identity mismatch",
        )
        provenance = _object(manifest.get("snapshot_provenance"), f"{name}.snapshot_provenance")
        source_repositories = provenance.get("repositories")
        _need(
            isinstance(source_repositories, list) and len(source_repositories) == 1,
            f"{name}: expected exactly one bound snapshot source",
        )
        observed = _object(source_repositories[0], f"{name}.snapshot_source")
        remote = observed.get("repo_remote")
        expected_slug = source["slug"]
        _need(
            observed.get("git_commit") == source["commit"]
            and observed.get("git_dirty") is False
            and observed.get("provenance_status") == "present"
            and isinstance(remote, str)
            and (remote.endswith(expected_slug) or remote.endswith(expected_slug + ".git")),
            f"{name}: manifest source commit/remote/cleanliness mismatch",
        )
        links = _object(manifest.get("links"), f"{name}.manifest.links")
        _need(links.get("agent_export_gate_status") == "pass"
              and links.get("bundle_surface_validation_status") == "pass",
              f"{name}: agent/export bundle checks are not green")
        health_ref = _path(links.get("post_emit_health_path"), f"{name}.post_emit_health_path")
        _need("/" not in health_ref, f"{name}: health sidecar must be beside its manifest")
        health_path = p.parent / health_ref
        _need(health_path.is_file() and not health_path.is_symlink(),
              f"{name}: actual post-emission health sidecar unavailable")
        _need(load_json(health_path).get("status") == "pass",
              f"{name}: actual post-emission health failed")
        result[name] = {
            "source_commit": source["commit"],
            "generator_commit": rec["generator_commit"],
            "manifest_path": str(p.resolve()),
            "manifest_sha256": rec["manifest_sha256"],
            "health": "pass",
        }
    return result


def _case_selection(taskset: Mapping[str, Any], suite: str) -> list[dict[str, Any]]:
    _need(suite in ("pilot", "full"), "unknown suite")
    return [c for c in taskset["cases"] if suite == "full" or c["pilot"]]


def create_plan(taskset: Mapping[str, Any], profile: Mapping[str, Any],
                snapshots: Mapping[str, Any], *, run_id: str, suite: str,
                repetitions: int, roots: Mapping[str, Any]) -> dict[str, Any]:
    taskset_valid(taskset)
    p = _profile(profile)
    _need(SLUG.fullmatch(run_id) is not None, "run_id must be a stable distinct slug")
    _need(type(repetitions) is int and repetitions in (1, 2), "repetitions must be one (diagnostic) or two")
    verified_paths = verify_sources(taskset, roots)
    bindings = _check_snapshots(taskset, snapshots)
    cases = _case_selection(taskset, suite)
    _need(len(cases) * repetitions * len(ARMS) <= MAX_TRIALS, "too many planned trials")
    comparable = {
        "protocol_version": VERSION, "taskset_sha256": sha256_json(taskset),
        "suite": suite, "repetitions": repetitions,
        "repositories": {k: v["commit"] for k, v in taskset["repositories"].items()},
        "model": p["model"], "provider": p["provider"], "sampling": p["sampling"],
        "agent_version": p["agent_version"], "runner_version": p["runner_version"],
        "host_class": p["host_class"], "cache_policy": p["cache_policy"],
        "tool_contract": p["tool_contract"], "tool_names": p["tool_names"],
    }
    protocol_key = sha256_json(comparable)
    runs = []
    for rep in range(1, repetitions + 1):
        for idx, case in enumerate(cases):
            permutation = PERMUTATIONS[(idx + (rep - 1) * 3) % len(PERMUTATIONS)]
            for order, arm in enumerate(permutation, 1):
                run_key = f"{run_id}--{case['id']}--r{rep}--{arm}"
                _need(len(run_key) <= 200, "long request identifier")
                token = hashlib.sha256(run_key.encode()).hexdigest()[:20]
                request = {
                    "kind": REQUEST_KIND, "version": VERSION,
                    "request_id": run_key, "run_id": run_id, "study_sha256": sha256_json(taskset),
                    "protocol_key": protocol_key, "case_id": case["id"],
                    "case_class": case["class"], "question": case["question"],
                    "repositories": {k: taskset["repositories"][k] for k in case["repositories"]},
                    "condition": arm, "order": order, "repetition": rep,
                    "session_id": f"session-{token}",
                    "workspace_id": f"workspace-{token}",
                    "runner": {"provider": p["provider"], "model": p["model"],
                               "sampling": p["sampling"], "runner_version": p["runner_version"]},
                    "tools_allowed": sorted(p["tool_names"]["git"] + p["tool_names"]["file"] +
                                            ([] if arm == "git_only" else p["tool_names"]["repoground"])),
                    "git_file_tool_names": sorted(p["tool_names"]["git"] + p["tool_names"]["file"]),
                    "repoground_tool_names": [] if arm == "git_only" else sorted(p["tool_names"]["repoground"]),
                    "repoground": None if arm == "git_only" else
                        {key: bindings[key] for key in case["repositories"]},
                    "isolation": {"fresh_session": True, "fresh_workspace": True,
                                  "no_prior_arm_transcripts": True, "disable_unlisted_plugins": True},
                }
                runs.append(request)
    return {
        "kind": PLAN_KIND, "version": VERSION, "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "suite": suite, "repetitions": repetitions,
        "measurement_scope": "planned_no_live_evidence",
        "study_sha256": sha256_json(taskset), "protocol_key": protocol_key,
        "comparison_dimensions": comparable, "profile": p,
        "snapshot_bindings": bindings, "source_verification": verified_paths,
        "requests": runs,
        "does_not_establish": ["real_agent_runs", "answer_correctness", "runtime_usefulness"],
    }


def _trace(receipt: Mapping[str, Any], trace_root: Path) -> None:
    trace = _object(receipt.get("trace"), "trace")
    rel = _path(trace.get("path"), "trace.path")
    _need(isinstance(trace.get("sha256"), str) and SHA256.fullmatch(trace["sha256"]), "trace digest required")
    length = _nonnegative(trace.get("bytes"), "trace.bytes")
    _need(0 < length <= MAX_TRACE, "trace byte count out of bounds")
    root = trace_root.resolve(strict=True)
    path = root / rel
    _need(not path.is_symlink() and path.is_file() and path.resolve().is_relative_to(root),
          "trace path missing, symlinked or escapes trace root")
    _need(path.stat().st_size == length, "trace size mismatch")
    with path.open("rb") as handle:
        sha = hashlib.file_digest(handle, "sha256").hexdigest()
    _need(sha == trace["sha256"], "trace hash mismatch")


def validate_receipt(request: Mapping[str, Any], receipt: Mapping[str, Any],
                     *, trace_root: str | Path) -> list[str]:
    try:
        _need(receipt.get("kind") == RECEIPT_KIND and receipt.get("version") == VERSION, "receipt kind/version mismatch")
        _need(receipt.get("request_id") == request["request_id"], "request id mismatch")
        _need(receipt.get("request_sha256") == sha256_json(request), "request bytes/digest mismatch")
        _need(receipt.get("condition") == request["condition"], "condition mismatch")
        _need(receipt.get("session_id") == request["session_id"], "session mismatch")
        _need(receipt.get("workspace_id") == request["workspace_id"], "workspace mismatch")
        _need(receipt.get("runner") == request["runner"], "provider/model/sampling/runner identity mismatch")
        _need(receipt.get("status") in ("success", "failed", "timeout"), "invalid run status")
        duration = _nonnegative(receipt.get("duration_ms"), "duration_ms")
        start = _iso(receipt.get("started_at"), "started_at")
        end = _iso(receipt.get("ended_at"), "ended_at")
        _need(end >= start and abs((end - start).total_seconds() * 1000 - duration) <= 2000,
              "timestamp/duration mismatch")
        usage = _object(receipt.get("usage"), "usage")
        _need(usage.get("source") == "provider_reported", "provider-reported usage required; estimates prohibited")
        _nonnegative(usage.get("input_tokens"), "input_tokens")
        _nonnegative(usage.get("output_tokens"), "output_tokens")
        if usage.get("cached_input_tokens") is not None:
            _need(_nonnegative(usage["cached_input_tokens"], "cached_input_tokens") <= usage["input_tokens"],
                  "cached tokens cannot exceed input")
        calls = receipt.get("tool_calls")
        _need(isinstance(calls, list) and len(calls) <= MAX_CALLS, "tool_calls invalid or too long")
        declared_repo_tools = set(request.get("repoground_tool_names", []))
        direct_tools = set(request.get("git_file_tool_names", []))
        _need(bool(direct_tools) and not direct_tools.intersection(declared_repo_tools),
              "run request has missing or overlapping tool inventory")
        _need(set(request["tools_allowed"]) == direct_tools.union(declared_repo_tools),
              "run request allowlist is inconsistent")
        if request["condition"] == "git_only":
            _need(not declared_repo_tools and request["repoground"] is None,
                  "baseline must not expose RepoGround")
        else:
            _need(bool(declared_repo_tools) and isinstance(request["repoground"], dict),
                  "treatment needs source-bound RepoGround tools")
        repoground_success = 0
        for i, call in enumerate(calls):
            c = _object(call, "tool call")
            _need(c.get("sequence") == i + 1, "tool-call sequence gap")
            name = c.get("name")
            _need(isinstance(name, str) and name in request["tools_allowed"], f"unauthorized tool {name}")
            _need(c.get("status") in ("success", "failed", "blocked", "timeout"), "tool-call status invalid")
            for field in ("duration_ms", "input_bytes", "output_bytes"):
                _nonnegative(c.get(field), f"tool.{field}")
            if name in declared_repo_tools and c["status"] == "success":
                repoground_success += 1
        if request["condition"] == "repoground_mandatory" and receipt["status"] == "success":
            _need(repoground_success >= 1, "mandatory condition had no successful RepoGround call")
        if receipt["status"] == "success":
            _need(receipt.get("error") is None, "successful run carries error")
        else:
            err = _object(receipt.get("error"), "error")
            _need(isinstance(err.get("class"), str) and err["class"], "failed run error class required")
        answer = _object(receipt.get("answer"), "answer")
        _need(answer.get("outcome") in ("answer", "abstain", "unavailable"), "answer.outcome invalid")
        _need(isinstance(answer.get("asserted_sufficient_evidence"), bool), "answer confidence required")
        paths = answer.get("reported_paths")
        _need(isinstance(paths, list), "answer.reported_paths must be array")
        got = [_ref(v, request["repositories"], "reported path") for v in paths]
        _need(len(got) == len(set(got)), "duplicate reported path")
        citation = answer.get("citations")
        _need(isinstance(citation, list), "citations required (may be empty)")
        for ref in citation:
            obj = _object(ref, "citation")
            rp = _ref({"repo": obj.get("repo"), "path": obj.get("path")}, request["repositories"], "citation")
            _need(obj.get("commit") == request["repositories"][rp[0]]["commit"], "citation revision mismatch")
            _need(_nonnegative(obj.get("start_line"), "start_line") >= 1 and
                  _nonnegative(obj.get("end_line"), "end_line") >= obj["start_line"], "citation lines invalid")
        cost = receipt.get("billed_cost")
        if cost is not None:
            c = _object(cost, "billed_cost")
            _need(c.get("source") == "provider_billed" and c.get("currency") in ("USD", "EUR"),
                  "cost must be provider-billed; no rate-card estimate")
            amount = c.get("amount")
            _need(type(amount) in (int, float) and math.isfinite(amount) and amount >= 0,
                  "billed cost amount invalid")
        resources = receipt.get("resources")
        if resources is not None:
            rec = _object(resources, "resources")
            for key in ("peak_rss_kib", "cpu_ms"):
                if rec.get(key) is not None:
                    _nonnegative(rec[key], key)
        _trace(receipt, Path(trace_root))
        return []
    except (AgentBenchmarkError, OSError, ValueError, TypeError, KeyError) as exc:
        return [str(exc)]


def _score(case: Mapping[str, Any], receipt: Mapping[str, Any], grade: Mapping[str, Any] | None) -> dict[str, Any]:
    oracle = case["oracle"]
    paths = {(x["repo"], x["path"]) for x in receipt["answer"]["reported_paths"]}
    expected = {(x["repo"], x["path"]) for x in oracle["required_paths"]}
    allowed = {(x["repo"], x["path"]) for x in oracle["allowed_paths"]}
    missing = len(expected - paths)
    false_paths = len(paths - allowed)
    outcome_ok = receipt["answer"]["outcome"] == oracle["outcome"]
    negative_false_confidence = oracle["outcome"] != "answer" and (
        receipt["answer"]["outcome"] == "answer" or receipt["answer"]["asserted_sufficient_evidence"]
    )
    result = {
        "path_recall": None if not expected else round((len(expected) - missing) / len(expected), 6),
        "missing_gold_paths": missing,
        "unsupported_paths": false_paths,
        "expected_outcome": oracle["outcome"], "outcome_match": outcome_ok,
        "negative_false_confidence": negative_false_confidence,
        "human_grade": None, "human_verified_citations": None,
        "quality_success": None,
    }
    if grade is not None:
        result["human_grade"] = grade["verdict"]
        result["human_verified_citations"] = grade["citations_checked"]
        result["quality_success"] = bool(
            grade["verdict"] == "correct"
            and grade["citations_checked"] is True
            and not missing and not false_paths and outcome_ok and not negative_false_confidence
        )
    return result


def _grade_index(grades: Sequence[Mapping[str, Any]], requests: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    known = set(requests)
    out = {}
    for value in grades:
        g = _object(value, "grade")
        rid = g.get("request_id")
        _need(rid in known and rid not in out, "grade references unknown or duplicate request")
        _need(g.get("verdict") in ("correct", "partial", "incorrect", "uncertain"), "invalid blinded review verdict")
        _need(type(g.get("citations_checked")) is bool, "citation review boolean required")
        _need(isinstance(g.get("reviewer"), str) and 2 <= len(g["reviewer"]) <= 120, "independent reviewer id required")
        _need(isinstance(g.get("evidence_ref"), str) and len(g["evidence_ref"]) >= 8, "review evidence pointer required")
        _iso(g.get("reviewed_at"), "grade.reviewed_at")
        out[rid] = g
    return out


def _median(values: Sequence[float]) -> float | None:
    return round(statistics.median(values), 4) if values else None


def _mean(values: Sequence[float]) -> float | None:
    return round(statistics.fmean(values), 4) if values else None


def _percentile(values: Sequence[float], fraction: float) -> float | None:
    if not values:
        return None
    data = sorted(values)
    position = (len(data) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    return round(data[lower] + (data[upper] - data[lower]) * (position - lower), 4)


def _bootstrap_delta(per_task: Mapping[str, Sequence[float]], protocol_key: str) -> list[float] | None:
    """Cluster bootstrap over *tasks*, not pseudo-independent repeated sessions."""
    if len(per_task) < 4:
        return None
    tasks = sorted(per_task)
    means = [statistics.fmean(per_task[t]) for t in tasks]
    randomizer = random.Random(int(protocol_key[:16], 16))
    draws = [statistics.fmean(randomizer.choices(means, k=len(means))) for _ in range(3000)]
    return [_percentile(draws, 0.025), _percentile(draws, 0.975)]


def evaluate(plan: Mapping[str, Any], taskset: Mapping[str, Any],
             receipts: Sequence[Mapping[str, Any]], grades: Sequence[Mapping[str, Any]],
             *, trace_root: str | Path, measurement_scope: str) -> dict[str, Any]:
    taskset_valid(taskset)
    _need(plan.get("kind") == PLAN_KIND and plan.get("version") == VERSION, "invalid study plan")
    _need(plan.get("study_sha256") == sha256_json(taskset), "taskset drift relative to plan")
    _need(plan.get("protocol_key") == sha256_json(plan.get("comparison_dimensions")), "protocol comparison digest mismatch")
    _need(measurement_scope in ("synthetic_contract_fixture", "real_runner_reported"), "invalid measurement scope")
    _need(plan.get("suite") in ("pilot", "full") and plan.get("repetitions") in (1, 2), "plan suite/repetitions invalid")
    expected_cases = {c["id"]: c for c in _case_selection(taskset, plan["suite"])}
    expected_tuples = {
        (case_id, rep, arm)
        for case_id in expected_cases
        for rep in range(1, plan["repetitions"] + 1)
        for arm in ARMS
    }
    _need(isinstance(plan.get("requests"), list) and len(plan["requests"]) <= MAX_TRIALS, "invalid planned requests")
    _need(
        {(r.get("case_id"), r.get("repetition"), r.get("condition")) for r in plan["requests"]} == expected_tuples,
        "plan has missing or unplanned task×repetition×arm combinations",
    )
    _need(len({r["session_id"] for r in plan["requests"]}) == len(plan["requests"])
          and len({r["workspace_id"] for r in plan["requests"]}) == len(plan["requests"]),
          "reused session/workspace across arms",
    )
    for req in plan["requests"]:
        case = expected_cases[req["case_id"]]
        _need(req.get("study_sha256") == plan["study_sha256"]
              and req.get("protocol_key") == plan["protocol_key"]
              and req.get("run_id") == plan["run_id"]
              and req.get("question") == case["question"], "plan request task/protocol drift")
        _need(req.get("repositories") == {k: taskset["repositories"][k] for k in case["repositories"]},
              "plan request source revision drift")
        _need(req.get("runner") == {k: plan["profile"][k] for k in ("provider", "model", "sampling", "runner_version")},
              "plan runner identity drift")
        tools = plan["profile"]["tool_names"]
        wanted_direct = sorted(tools["git"] + tools["file"])
        wanted_rg = [] if req["condition"] == "git_only" else sorted(tools["repoground"])
        _need(req.get("git_file_tool_names") == wanted_direct
              and req.get("repoground_tool_names") == wanted_rg
              and req.get("tools_allowed") == sorted(wanted_direct + wanted_rg),
              "plan request tool contract drift")
        _need(req.get("repoground") == (None if req["condition"] == "git_only" else
              {key: plan["snapshot_bindings"][key] for key in case["repositories"]}),
              "plan request snapshot binding drift")
    for rep in range(1, plan["repetitions"] + 1):
        for idx, case in enumerate(expected_cases.values()):
            got = sorted(
                (r["order"], r["condition"]) for r in plan["requests"]
                if r["case_id"] == case["id"] and r["repetition"] == rep
            )
            expected_order = sorted(enumerate(PERMUTATIONS[(idx + (rep - 1) * 3) % 6], 1))
            _need(got == expected_order, "plan treatment order manipulated")
    expected = {r["request_id"]: r for r in plan["requests"]}
    _need(len(expected) == len(plan["requests"]), "duplicate plan request IDs")
    supplied: dict[str, Mapping[str, Any]] = {}
    extras: list[str] = []
    for item in receipts:
        rid = item.get("request_id")
        if rid not in expected or rid in supplied:
            extras.append(str(rid))
        else:
            supplied[rid] = item
    grades_by_id = _grade_index(grades, expected)
    cases = {c["id"]: c for c in taskset["cases"]}
    rows = []
    for request in plan["requests"]:
        rid = request["request_id"]
        receipt = supplied.get(rid)
        errors = ["missing_receipt"] if receipt is None else validate_receipt(request, receipt, trace_root=trace_root)
        record = {
            "request_id": rid, "case_id": request["case_id"], "class": request["case_class"],
            "condition": request["condition"], "repetition": request["repetition"],
            "order": request["order"], "valid": not errors, "errors": errors,
            "status": "missing" if receipt is None else receipt.get("status", "unknown"),
            "metrics": None, "score": None,
        }
        if not errors and receipt is not None:
            calls = receipt["tool_calls"]
            record["metrics"] = {
                "duration_ms": receipt["duration_ms"],
                "input_tokens": receipt["usage"]["input_tokens"],
                "output_tokens": receipt["usage"]["output_tokens"],
                "cached_input_tokens": receipt["usage"].get("cached_input_tokens"),
                "tool_calls": len(calls),
                "tool_failures": sum(x["status"] != "success" for x in calls),
                "tool_input_bytes": sum(x["input_bytes"] for x in calls),
                "tool_output_bytes": sum(x["output_bytes"] for x in calls),
                "tool_duration_ms": sum(x["duration_ms"] for x in calls),
                "repoground_calls": sum(x["name"] in request.get("repoground_tool_names", []) for x in calls),
                "repoground_failures": sum(
                    x["name"] in request.get("repoground_tool_names", []) and x["status"] != "success"
                    for x in calls
                ),
                "tool_breakdown": [
                    {"name": x["name"], "status": x["status"], "duration_ms": x["duration_ms"],
                     "bytes": x["input_bytes"] + x["output_bytes"]}
                    for x in calls
                ],
                "billed_cost": receipt.get("billed_cost"),
                "peak_rss_kib": (receipt.get("resources") or {}).get("peak_rss_kib"),
                "cpu_ms": (receipt.get("resources") or {}).get("cpu_ms"),
            }
            record["score"] = _score(cases[request["case_id"]], receipt, grades_by_id.get(rid))
        rows.append(record)

    by_arm = {}
    for arm in ARMS:
        subset = [x for x in rows if x["condition"] == arm]
        valid = [x for x in subset if x["valid"] and x["status"] == "success"]
        by_arm[arm] = {
            "planned": len(subset), "valid_success": len(valid),
            "failed_or_invalid": len(subset) - len(valid),
            "grades_complete": len([x for x in valid if x["score"]["human_grade"] is not None]),
            "quality_correct": len([x for x in valid if x["score"]["quality_success"] is True]),
            "unsupported_paths": sum(x["score"]["unsupported_paths"] for x in valid),
            "negative_false_confidence": sum(x["score"]["negative_false_confidence"] for x in valid),
            "duration_ms": {
                "mean": _mean([x["metrics"]["duration_ms"] for x in valid]),
                "median": _median([x["metrics"]["duration_ms"] for x in valid]),
                "p95": _percentile([x["metrics"]["duration_ms"] for x in valid], 0.95),
            },
            "input_tokens_total": sum(x["metrics"]["input_tokens"] for x in valid),
            "output_tokens_total": sum(x["metrics"]["output_tokens"] for x in valid),
            "tool_calls_total": sum(x["metrics"]["tool_calls"] for x in valid),
            "tool_failures_total": sum(x["metrics"]["tool_failures"] for x in valid),
            "repoground_calls_total": sum(x["metrics"]["repoground_calls"] for x in valid),
            "repoground_failures_total": sum(x["metrics"]["repoground_failures"] for x in valid),
            "tool_bytes_total": sum(x["metrics"]["tool_input_bytes"] + x["metrics"]["tool_output_bytes"] for x in valid),
            "tool_time_ms_total": sum(x["metrics"]["tool_duration_ms"] for x in valid),
            "cached_input_tokens_total": (
                sum(x["metrics"]["cached_input_tokens"] for x in valid)
                if valid and all(x["metrics"]["cached_input_tokens"] is not None for x in valid)
                else None
            ),
            "tool_breakdown": [],
            "cost_billed_total": None,  # Only report same-currency billed costs when ALL are known.
        }
        tool_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in valid:
            for call in item["metrics"]["tool_breakdown"]:
                tool_groups[call["name"]].append(call)
        by_arm[arm]["tool_breakdown"] = [
            {"name": name, "calls": len(group),
             "failures": sum(x["status"] != "success" for x in group),
             "duration_ms_sum": sum(x["duration_ms"] for x in group),
             "bytes_sum": sum(x["bytes"] for x in group)}
            for name, group in sorted(tool_groups.items())
        ]
        costs = [x["metrics"]["billed_cost"] for x in valid]
        if valid and all(isinstance(c, dict) and c["currency"] == costs[0]["currency"] for c in costs):
            by_arm[arm]["cost_billed_total"] = {
                "currency": costs[0]["currency"],
                "amount": round(sum(c["amount"] for c in costs), 6),
            }

    grouped: dict[tuple[str, int], dict[str, Any]] = defaultdict(dict)
    for row in rows:
        grouped[(row["case_id"], row["repetition"])][row["condition"]] = row
    blocks = []
    deltas: dict[str, dict[str, list[float]]] = {
        name: defaultdict(list) for name in ("mandatory_vs_git", "selective_vs_git", "selective_vs_mandatory")
    }
    comparisons = [
        ("mandatory_vs_git", "repoground_mandatory", "git_only"),
        ("selective_vs_git", "repoground_selective", "git_only"),
        ("selective_vs_mandatory", "repoground_selective", "repoground_mandatory"),
    ]
    delta_metrics = ("duration_ms", "input_tokens", "output_tokens", "tool_calls",
                     "tool_failures", "tool_input_bytes", "tool_output_bytes", "repoground_calls")
    metric_deltas: dict[str, dict[str, dict[str, list[float]]]] = {
        name: {metric: defaultdict(list) for metric in delta_metrics}
        for name, _, _ in comparisons
    }
    for (case_id, rep), group in sorted(grouped.items()):
        complete = len(group) == 3 and all(
            group[a]["valid"] and group[a]["status"] == "success" and
            group[a]["score"]["human_grade"] is not None and
            group[a]["score"]["human_grade"] != "uncertain" for a in ARMS
        )
        blocks.append({
            "case_id": case_id, "repetition": rep, "complete": complete,
            "reasons": [] if complete else [
                a for a in ARMS if a not in group or not group[a]["valid"] or
                group[a]["status"] != "success" or
                group[a]["score"] is None or group[a]["score"]["human_grade"] in (None, "uncertain")
            ],
        })
        if not complete:
            continue
        for label, treatment, baseline in comparisons:
            # Per-case within-block differences; exclude between-case scaling.
            delta = group[treatment]["metrics"]["duration_ms"] - group[baseline]["metrics"]["duration_ms"]
            deltas[label][case_id].append(delta)
            for metric in delta_metrics:
                metric_deltas[label][metric][case_id].append(
                    group[treatment]["metrics"][metric] - group[baseline]["metrics"][metric]
                )

    effects = {}
    for label, cases_with_deltas in deltas.items():
        cases_mean = [statistics.fmean(v) for _, v in sorted(cases_with_deltas.items())]
        effects[label] = {
            "complete_tasks": len(cases_mean),
            "paired_blocks": sum(len(x) for x in cases_with_deltas.values()),
            "duration_delta_ms_mean_of_task_means": _mean(cases_mean),
            "duration_delta_ms_median_of_task_means": _median(cases_mean),
            "duration_delta_ms_bootstrap_95ci": _bootstrap_delta(cases_with_deltas, plan["protocol_key"]),
            "tasks_faster": sum(x < 0 for x in cases_mean),
            "tasks_slower": sum(x > 0 for x in cases_mean),
            "tasks_equal": sum(x == 0 for x in cases_mean),
            "paired_metrics": {
                metric: {
                    "mean_delta": _mean([
                        statistics.fmean(values)
                        for _, values in sorted(task_deltas.items())
                    ]),
                    "median_delta": _median([
                        statistics.fmean(values)
                        for _, values in sorted(task_deltas.items())
                    ]),
                    "bootstrap_95ci": _bootstrap_delta(task_deltas, plan["protocol_key"]),
                }
                for metric, task_deltas in metric_deltas[label].items()
            },
        }

    by_class = {}
    for task_class in CLASSES:
        klass = [x for x in rows if x["class"] == task_class]
        complete_ids = {
            x["case_id"] for x in blocks if x["complete"]
            and cases[x["case_id"]]["class"] == task_class
        }
        by_class[task_class] = {
            "planned_trials": len(klass),
            "valid_success_trials": sum(x["valid"] and x["status"] == "success" for x in klass),
            "complete_tasks": len(complete_ids),
            "condition_summaries": {
                arm: {
                    "valid_success": sum(x["condition"] == arm and x["valid"]
                                         and x["status"] == "success" for x in klass),
                    "human_correct": sum(x["condition"] == arm and x["score"] is not None
                                         and x["score"]["quality_success"] is True for x in klass),
                    "median_duration_ms": _median([
                        x["metrics"]["duration_ms"] for x in klass
                        if x["condition"] == arm and x["valid"] and x["status"] == "success"
                    ]),
                }
                for arm in ARMS
            },
            "paired_duration_ms": {
                label: _mean([
                    statistics.fmean(values) for case_id, values in sorted(deltas[label].items())
                    if cases[case_id]["class"] == task_class
                ])
                for label, _, _ in comparisons
            },
        }

    valid_all = len(extras) == 0 and all(x["valid"] and x["status"] == "success" for x in rows)
    grades_complete = valid_all and all(x["score"]["human_grade"] not in (None, "uncertain") for x in rows)
    full = plan["suite"] == "full" and plan["repetitions"] >= DECISION_LIMITS["minimum_repetitions"]
    decision = "not_established"
    if (measurement_scope == "real_runner_reported" and full and valid_all and grades_complete
            and len({x["case_id"] for x in rows}) >= DECISION_LIMITS["minimum_complete_tasks"]):
        base = by_arm["git_only"]
        select = by_arm["repoground_selective"]
        # Quality gate prevents a fast but less accurate condition from winning.
        if (select["quality_correct"] >= base["quality_correct"]
            and select["unsupported_paths"] <= base["unsupported_paths"]
            and select["negative_false_confidence"] <= base["negative_false_confidence"]
            and effects["selective_vs_git"]["duration_delta_ms_bootstrap_95ci"] is not None
            and effects["selective_vs_git"]["duration_delta_ms_bootstrap_95ci"][1] < 0):
            decision = "selective_benefit_candidate"
        else:
            decision = "no_selective_benefit_established"
    return {
        "kind": REPORT_KIND, "version": VERSION,
        "run_id": plan["run_id"], "created_at": datetime.now(timezone.utc).isoformat(),
        "measurement_scope": measurement_scope,
        "taskset_sha256": plan["study_sha256"], "protocol_key": plan["protocol_key"],
        "suite": plan["suite"], "repetitions": plan["repetitions"],
        "generator_commits": {k: v["generator_commit"] for k, v in plan["snapshot_bindings"].items()},
        "planned_trials": len(rows), "supplied_trials": len(supplied), "unexpected_or_duplicate_ids": extras,
        "valid_success_trials": sum(x["valid"] and x["status"] == "success" for x in rows),
        "graded_trials": sum(x["score"] is not None and x["score"]["human_grade"] is not None for x in rows),
        "complete_blocks": sum(x["complete"] for x in blocks),
        "blocks": blocks, "conditions": by_arm, "effects": effects, "by_class": by_class,
        "trials": rows,
        "decision": {"status": decision, "default_promoted": False,
                     "quality_review_complete": grades_complete,
                     "limits": DECISION_LIMITS,
                     "does_not_establish": ["causal_usefulness_without_design_checks", "automatic_rollout_authority"]},
    }


def history(reports: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Expose comparability, never pool distinct Git revisions/model/hardware."""
    _need(bool(reports), "at least one report required")
    ids: set[str] = set()
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for report in reports:
        _need(report.get("kind") == REPORT_KIND and report.get("version") == VERSION, "invalid report kind/version")
        run_id = report.get("run_id")
        _need(isinstance(run_id, str) and run_id not in ids, "duplicate history run id")
        ids.add(run_id)
        _iso(report.get("created_at"), "report timestamp")
        protocol = report.get("protocol_key")
        _need(isinstance(protocol, str) and SHA256.fullmatch(protocol), "invalid protocol_key")
        effect = _object(report.get("effects"), "effects").get("selective_vs_git")
        _need(isinstance(effect, dict), "missing primary comparison")
        groups[protocol].append({
            "run_id": run_id,
            "created_at": report["created_at"],
            "scope": report["measurement_scope"],
            "generator_commits": report.get("generator_commits"),
            "decision": report.get("decision", {}).get("status"),
            "complete_tasks": effect.get("complete_tasks"),
            "delta_ms": effect.get("duration_delta_ms_mean_of_task_means"),
            "ci_95": effect.get("duration_delta_ms_bootstrap_95ci"),
            "quality_review_complete": report.get("decision", {}).get("quality_review_complete"),
        })
    return {
        "kind": "repoground.agent_study_history", "version": VERSION,
        "total_runs": len(ids), "comparison_groups": len(groups),
        "groups": [
            {"protocol_key": key, "runs": sorted(value, key=lambda x: (x["created_at"], x["run_id"])),
             "cross_run_causal_claim": False}
            for key, value in sorted(groups.items())
        ],
        "note": "Only the same protocol_key is structurally comparable. Even then time-period drift and sampling remain.",
    }


def report_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        f"# RepoGround Agent Study: {report['run_id']}",
        "",
        f"Protocol: {report['protocol_key']}  ",
        f"Taskset: {report['taskset_sha256']}  ",
        f"Scope: {report['measurement_scope']}  ",
        f"Decision: **{report['decision']['status']}**",
        "",
        "| Condition | Valid / planned | Human-correct | Median ms | P95 ms | Input tokens | Tool calls |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for arm in ARMS:
        d = report["conditions"][arm]
        lines.append(f"| {arm} | {d['valid_success']}/{d['planned']} | "
                     f"{d['quality_correct']}/{d['grades_complete']} | "
                     f"{d['duration_ms']['median']} | {d['duration_ms']['p95']} | "
                     f"{d['input_tokens_total']} | {d['tool_calls_total']} |")
    lines.extend(["", f"Complete matched task×repetition blocks: {report['complete_blocks']}.",
                  "Unknown review, missing trace or failed runs are not silently discarded.",
                  "", "## Task classes",
                  "| Class | Valid / planned | Complete tasks | C−A mean duration ms |",
                  "|---|---:|---:|---:|"])
    for name, item in report["by_class"].items():
        lines.append(f"| {name} | {item['valid_success_trials']}/{item['planned_trials']} "
                     f"| {item['complete_tasks']} | {item['paired_duration_ms']['selective_vs_git']} |")
    lines.extend([

                  "An arm comparison is descriptive unless the pre-registered quality and repeated-measure conditions hold.",
                  "Historical 20-pair experiments use another protocol and are not pooled.", ""])
    for key, d in report["effects"].items():
        lines.append(f"- {key}: mean paired task delta {d['duration_delta_ms_mean_of_task_means']} ms, "
                     f"bootstrap task-cluster 95% CI {d['duration_delta_ms_bootstrap_95ci']}, "
                     f"task count {d['complete_tasks']}.")
    return "\n".join(lines) + "\n"


__all__ = [
    "ARMS", "CLASSES", "VERSION", "taskset_valid", "verify_sources", "create_plan",
    "validate_receipt", "evaluate", "history", "report_markdown", "execute_runner",
    "sha256_json", "load_json", "write_json_atomic", "AgentBenchmarkError",
]
