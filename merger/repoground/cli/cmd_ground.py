from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable, Optional

from merger.repoground.core.merge import ExtrasConfig, parse_human_size, scan_repo, write_reports_v2
from merger.repoground.core.snapshot_profiles import (
    evaluate_profile,
    present_roles_from_manifest,
    profile_level,
    profile_names,
    profile_output_mode_plan,
    profile_policy,
    profile_excluded_roles,
    profile_export_semantics,
)

DOES_NOT_ESTABLISH = [
    "truth",
    "correctness",
    "completeness",
    "runtime_behavior",
    "test_sufficiency",
    "regression_absence",
    "repo_understood",
    "claims_true",
    "forensic_ready",
]


def _json_write_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            delete=False,
            dir=str(path.parent),
            prefix=f".{path.name}.",
            suffix=".tmp",
        ) as tmp_file:
            json.dump(data, tmp_file, indent=2, sort_keys=True)
            tmp_file.write("\n")
            tmp_file.flush()
            os.fsync(tmp_file.fileno())
            tmp_path = Path(tmp_file.name)
        os.replace(tmp_path, path)
    finally:
        if tmp_path is not None and tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                # Best-effort cleanup must not hide the primary write result.
                pass


def mark_bundle_manifest_profile(
    bundle_manifest: Path | None,
    profile: str,
    output_plan: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if bundle_manifest is None:
        return None
    data = json.loads(bundle_manifest.read_text(encoding="utf-8"))
    capabilities = data.setdefault("capabilities", {})
    if not isinstance(capabilities, dict):
        capabilities = {}
        data["capabilities"] = capabilities
    evaluation = evaluate_profile(profile, present_roles_from_manifest(data))
    capabilities["repobrief_profile"] = profile
    capabilities["repobrief_snapshot_create"] = True
    capabilities["repobrief_profile_policy"] = profile_policy(profile)
    if output_plan is not None:
        capabilities["repobrief_output_plan"] = output_plan
    capabilities["repobrief_profile_evaluation"] = evaluation
    _json_write_atomic(bundle_manifest, data)
    return evaluation



def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _add_manifest_artifact(
    bundle_manifest: Path,
    artifact_path: Path,
    role: str,
    content_type: str,
    extra: dict[str, Any] | None = None,
) -> None:
    data = json.loads(bundle_manifest.read_text(encoding="utf-8"))
    artifacts = data.setdefault("artifacts", [])
    if not isinstance(artifacts, list):
        artifacts = []
        data["artifacts"] = artifacts
    previous = next(
        (
            dict(artifact)
            for artifact in artifacts
            if isinstance(artifact, dict) and artifact.get("role") == role
        ),
        {},
    )
    artifacts[:] = [
        artifact
        for artifact in artifacts
        if not (isinstance(artifact, dict) and artifact.get("role") == role)
    ]
    entry = {
        **previous,
        "path": artifact_path.name,
        "role": role,
        "content_type": content_type,
        "bytes": artifact_path.stat().st_size,
        "sha256": _sha256_file(artifact_path),
    }
    if extra:
        entry.update(extra)
    artifacts.append(entry)
    artifacts.sort(key=lambda a: (str(a.get("role", "")), str(a.get("path", ""))))
    _json_write_atomic(bundle_manifest, data)


def _export_safety_requirement(profile: str) -> str:
    return str(profile_policy(profile)["artifact_rules"].get("export_safety_report", "optional"))


def should_emit_export_safety_report(profile: str) -> bool:
    return _export_safety_requirement(profile) in {"required", "recommended"}


def resolve_snapshot_redaction(
    profile: str, requested: bool | None
) -> tuple[bool, str, bool]:
    required = bool(
        profile_policy(profile)["export_semantics"].get("redaction_required")
    )
    if requested is None:
        return required, "profile_required_default" if required else "profile_default", required
    if required and requested is False:
        raise ValueError(
            f"profile {profile} requires secret redaction; "
            "--no-redact-secrets is not permitted"
        )
    return bool(requested), "explicit", required


def emit_export_safety_report(bundle_manifest: Path | None, profile: str) -> Path | None:
    if bundle_manifest is None or not should_emit_export_safety_report(profile):
        return None
    from merger.repoground.core.export_safety_report import build_export_safety_report_from_bundle_manifest

    report = build_export_safety_report_from_bundle_manifest(
        bundle_manifest,
        profile=profile,
    )
    out = bundle_manifest.with_name(
        bundle_manifest.name.replace(".bundle.manifest.json", ".export_safety_report.json")
    )
    _json_write_atomic(out, report)
    _add_manifest_artifact(
        bundle_manifest,
        out,
        "export_safety_report",
        "application/json",
        extra={
            "contract": {"id": "export-safety-report", "version": "v1"},
            "interpretation": {"mode": "contract"},
            "authority": "diagnostic_signal",
            "canonicality": "diagnostic",
            "risk_class": "diagnostic",
            "regenerable": True,
            "staleness_sensitive": True,
        },
    )
    return out



def emit_snapshot_plan_report(
    bundle_manifest: Path | None,
    profile: str,
    output_plan: dict[str, Any],
) -> Path | None:
    if bundle_manifest is None:
        return None
    report = {
        "kind": "repobrief.snapshot_plan",
        "version": "v1",
        "command": "repobrief snapshot create",
        "profile": profile,
        "output_plan": output_plan,
        "mutation_boundary": {
            "writes": ["brief_bundle_artifacts"],
            "does_not_mutate": ["git", "pull_requests", "patches", "source_working_tree"],
            "read_paths_do_not_refresh": True,
        },
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }
    out = bundle_manifest.with_name(
        bundle_manifest.name.replace(".bundle.manifest.json", ".snapshot_plan.json")
    )
    _json_write_atomic(out, report)
    _add_manifest_artifact(
        bundle_manifest,
        out,
        "snapshot_plan_json",
        "application/json",
        extra={
            "contract": {"id": "repobrief.snapshot_plan", "version": "v1"},
            "interpretation": {"mode": "contract"},
            "authority": "diagnostic_signal",
            "canonicality": "diagnostic",
            "risk_class": "diagnostic",
            "regenerable": True,
            "staleness_sensitive": True,
        },
    )
    return out


def _set_manifest_links(bundle_manifest: Path, **updates: Any) -> None:
    data = json.loads(bundle_manifest.read_text(encoding="utf-8"))
    links = data.setdefault("links", {})
    if not isinstance(links, dict):
        links = {}
        data["links"] = links
    for key, value in updates.items():
        if value is None:
            links.pop(key, None)
        else:
            links[key] = value
    _json_write_atomic(bundle_manifest, data)


def _linked_surface_claim_requirement(
    bundle_manifest: Path,
) -> tuple[bool, str | None]:
    data = json.loads(bundle_manifest.read_text(encoding="utf-8"))
    links = data.get("links")
    if not isinstance(links, dict):
        return False, None
    raw_path = links.get("bundle_surface_validation_path")
    if not isinstance(raw_path, str) or not raw_path:
        return False, None
    candidate = (bundle_manifest.parent / raw_path).resolve()
    try:
        candidate.relative_to(bundle_manifest.parent.resolve())
    except ValueError:
        return False, "bundle_surface_validation_path_escapes_bundle"
    try:
        report = json.loads(candidate.read_text(encoding="utf-8"))
    except OSError:
        return False, "bundle_surface_validation_unreadable"
    except json.JSONDecodeError:
        return False, "bundle_surface_validation_invalid_json"
    if not isinstance(report, dict):
        return False, "bundle_surface_validation_not_object"
    requirement = report.get("require_claim_evidence_map")
    if not isinstance(requirement, bool):
        return False, "bundle_surface_claim_requirement_missing"
    return requirement, None


def _persist_post_health(bundle_manifest: Path) -> tuple[Path, dict[str, Any]]:
    from merger.repoground.core.post_emit_health import write_post_emit_health

    path, report = write_post_emit_health(str(bundle_manifest))
    _set_manifest_links(bundle_manifest, post_emit_health_path=path.name)
    return path, report


def _persist_agent_export_gate(
    bundle_manifest: Path,
    profile: str,
    *,
    required: bool,
) -> tuple[Path | None, dict[str, Any]]:
    if not required:
        return None, {"status": "not_required"}

    from merger.repoground.core.agent_export_gate import write_agent_export_gate

    path, report = write_agent_export_gate(bundle_manifest, profile=profile)
    _set_manifest_links(
        bundle_manifest,
        agent_export_gate_path=path.name,
        agent_export_gate_status=report.get("status"),
    )
    return path, report


def _persist_export_safety(
    bundle_manifest: Path,
    profile: str,
) -> tuple[Path | None, dict[str, Any]]:
    path = emit_export_safety_report(bundle_manifest, profile)
    if path is None:
        return None, {"status": "not_emitted"}

    report = json.loads(path.read_text(encoding="utf-8"))
    _set_manifest_links(
        bundle_manifest,
        export_safety_report_path=path.name,
        export_safety_report_status=report.get("status"),
    )
    return path, report


def _persist_surface_validation(
    bundle_manifest: Path,
    *,
    require_claim_evidence_map: bool,
) -> tuple[Path, dict[str, Any]]:
    from merger.repoground.core.bundle_surface_validate import (
        write_bundle_surface_validation,
    )

    path, report = write_bundle_surface_validation(
        bundle_manifest,
        require_claim_evidence_map=require_claim_evidence_map,
    )
    _set_manifest_links(
        bundle_manifest,
        bundle_surface_validation_path=path.name,
        bundle_surface_validation_status=report.get("status"),
    )
    return path, report


def _manifest_artifact_count(bundle_manifest: Path) -> int:
    data = json.loads(bundle_manifest.read_text(encoding="utf-8"))
    artifacts = data.get("artifacts")
    return len(artifacts) if isinstance(artifacts, list) else 0


def _finalization_errors(
    *,
    final_manifest_sha: str,
    manifest_sha_at_final_health: str,
    artifact_count: int,
    post_report: dict[str, Any],
    gate_report: dict[str, Any],
    gate_required: bool,
    export_path: Path | None,
    export_report: dict[str, Any],
    surface_report: dict[str, Any],
    profile_evaluation: dict[str, Any] | None,
) -> list[str]:
    errors: list[str] = []
    if final_manifest_sha != manifest_sha_at_final_health:
        errors.append("manifest_mutated_after_final_health")
    if post_report.get("status") != "pass":
        errors.append(f"post_emit_health:{post_report.get('status')}")
    if post_report.get("artifact_count_checked") != artifact_count:
        errors.append(
            "post_emit_health_artifact_count_mismatch:"
            f"{post_report.get('artifact_count_checked')}!={artifact_count}"
        )
    if gate_required and gate_report.get("status") != "pass":
        errors.append(f"agent_export_gate:{gate_report.get('status')}")
    if export_path is not None and export_report.get("status") != "pass":
        errors.append(f"export_safety_report:{export_report.get('status')}")
    if surface_report.get("status") not in {"pass", "warn"}:
        errors.append(f"bundle_surface_validation:{surface_report.get('status')}")
    if (
        not isinstance(profile_evaluation, dict)
        or profile_evaluation.get("status") == "fail"
    ):
        status = (
            profile_evaluation.get("status")
            if isinstance(profile_evaluation, dict)
            else "missing"
        )
        errors.append(f"profile_evaluation:{status}")
    return errors


def finalize_snapshot_bundle(
    bundle_manifest: Path | None,
    profile: str,
) -> dict[str, Any]:
    if bundle_manifest is None:
        return {
            "status": "fail",
            "errors": ["bundle_manifest_missing"],
            "phases": 0,
            "control_paths": [],
            "refreshed_paths": [],
        }

    semantics = profile_export_semantics(profile)
    gate_required = semantics["agent_export_gate_required"]
    require_claim_map, claim_requirement_error = (
        _linked_surface_claim_requirement(bundle_manifest)
    )
    if claim_requirement_error is not None:
        return {
            "status": "fail",
            "errors": [claim_requirement_error],
            "phases": 0,
            "control_paths": [],
            "refreshed_paths": [],
        }
    refreshed_paths = refresh_entry(bundle_manifest)
    mark_bundle_manifest_profile(bundle_manifest, profile)

    # Phase 1 establishes every control surface after the content artifacts are
    # fixed. The second phase can therefore validate the complete artifact set.
    post_path, _ = _persist_post_health(bundle_manifest)
    gate_path, _ = _persist_agent_export_gate(
        bundle_manifest, profile, required=gate_required
    )
    export_path, _ = _persist_export_safety(bundle_manifest, profile)
    surface_path, _ = _persist_surface_validation(
        bundle_manifest, require_claim_evidence_map=require_claim_map
    )
    mark_bundle_manifest_profile(bundle_manifest, profile)

    # Phase 2 is authoritative. Later control refreshes may rewrite sidecars, but
    # they must not alter the manifest that the final health pass inspected.
    manifest_sha_at_final_health = hashlib.sha256(
        bundle_manifest.read_bytes()
    ).hexdigest()
    _, post_report = _persist_post_health(bundle_manifest)
    _, gate_report = _persist_agent_export_gate(
        bundle_manifest, profile, required=gate_required
    )
    export_path, export_report = _persist_export_safety(bundle_manifest, profile)
    _, surface_report = _persist_surface_validation(
        bundle_manifest, require_claim_evidence_map=require_claim_map
    )
    profile_evaluation = mark_bundle_manifest_profile(bundle_manifest, profile)
    final_manifest_sha = hashlib.sha256(bundle_manifest.read_bytes()).hexdigest()
    artifact_count = _manifest_artifact_count(bundle_manifest)
    errors = _finalization_errors(
        final_manifest_sha=final_manifest_sha,
        manifest_sha_at_final_health=manifest_sha_at_final_health,
        artifact_count=artifact_count,
        post_report=post_report,
        gate_report=gate_report,
        gate_required=gate_required,
        export_path=export_path,
        export_report=export_report,
        surface_report=surface_report,
        profile_evaluation=profile_evaluation,
    )
    control_paths = [post_path, surface_path]
    if gate_path is not None:
        control_paths.append(gate_path)
    if export_path is not None:
        control_paths.append(export_path)

    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "phases": 2,
        "manifest_sha256_at_final_health": manifest_sha_at_final_health,
        "final_manifest_sha256": final_manifest_sha,
        "manifest_artifact_count": artifact_count,
        "post_emit_health_artifact_count": post_report.get(
            "artifact_count_checked"
        ),
        "post_emit_health_status": post_report.get("status"),
        "agent_export_gate_status": gate_report.get("status"),
        "export_safety_status": export_report.get("status"),
        "bundle_surface_validation_status": surface_report.get("status"),
        "profile_evaluation": profile_evaluation,
        "control_paths": [str(path) for path in control_paths],
        "refreshed_paths": [str(path) for path in refreshed_paths],
    }


def parse_extensions(values: Iterable[str] | None) -> list[str] | None:
    if not values:
        return None
    result: list[str] = []
    for value in values:
        for item in str(value).split(","):
            item = item.strip().lower()
            if not item:
                continue
            if not item.startswith("."):
                item = f".{item}"
            result.append(item)
    return sorted(set(result)) or None


def register_ground_command_groups(ground_parser: argparse.ArgumentParser) -> None:
    ground_subparsers = ground_parser.add_subparsers(
        dest="ground_cmd",
        required=True,
        help="RepoGround ground command groups",
    )
    snapshot_parser = ground_subparsers.add_parser("snapshot", help="RepoGround snapshot commands")
    snapshot_subparsers = snapshot_parser.add_subparsers(
        dest="snapshot_cmd",
        required=True,
        help="Snapshot commands",
    )
    create_parser = snapshot_subparsers.add_parser("create", help="Explicitly create a RepoGround snapshot")
    create_parser.add_argument("--repo", required=True, help="Repository path to snapshot")
    create_parser.add_argument("--out", required=True, help="Output directory for RepoGround bundle artifacts")
    create_parser.add_argument(
        "--profile",
        choices=sorted(profile_names()),
        default="agent-portable",
        help="RepoGround snapshot profile label to record in the manifest",
    )
    create_parser.add_argument(
        "--mode",
        choices=["gesamt", "pro-repo"],
        default="gesamt",
        help="Existing renderer mode passed through to the deterministic generator",
    )
    create_parser.add_argument("--max-bytes", default="0")
    create_parser.add_argument("--split-size", default="25MB")
    create_parser.add_argument("--path-filter")
    create_parser.add_argument("--ext", action="append")
    create_parser.add_argument("--output-mode", choices=["archive", "retrieval", "dual"])
    create_redaction = create_parser.add_mutually_exclusive_group()
    create_redaction.add_argument(
        "--redact-secrets", action="store_true", dest="redact_secrets"
    )
    create_redaction.add_argument(
        "--no-redact-secrets", action="store_false", dest="redact_secrets"
    )
    create_parser.add_argument("--no-include-hidden", action="store_false", dest="include_hidden")
    create_parser.add_argument(
        "--latest-complete-registry",
        help="Explicitly write/update a RepoGround latest-complete registry JSON for this created snapshot",
    )
    create_parser.set_defaults(include_hidden=True, redact_secrets=None)

    status_parser = snapshot_subparsers.add_parser("status", help="Read status for an existing RepoGround snapshot")
    status_parser.add_argument("--bundle-manifest", required=True, help="Path to a RepoGround bundle manifest")
    check_parser = snapshot_subparsers.add_parser("check", help="Read-only snapshot check summary")
    check_parser.add_argument("--bundle-manifest", required=True, help="Path to a RepoGround bundle manifest")
    check_parser.add_argument("--task-profile", default="basic_repo_question", help="Required-reading task profile")

    preflight_parser = ground_subparsers.add_parser("preflight", help="Run RepoGround consumption preflight")
    preflight_parser.add_argument("--bundle-manifest", required=True, help="Path to a RepoGround bundle manifest")
    preflight_parser.add_argument("--task-profile", default="basic_repo_question", help="Required-reading task profile")

    artifact_parser = ground_subparsers.add_parser("artifact", help="RepoGround artifact read-only commands")
    artifact_subparsers = artifact_parser.add_subparsers(
        dest="artifact_cmd",
        required=True,
        help="Artifact commands",
    )
    get_parser = artifact_subparsers.add_parser("get", help="Read artifact metadata by role")
    get_parser.add_argument("--bundle-manifest", required=True, help="Path to a RepoGround bundle manifest")
    get_parser.add_argument("--role", required=True, help="Artifact role to resolve")
    get_parser.add_argument("--path-only", action="store_true", help="Print only the resolved artifact path")
    list_parser = artifact_subparsers.add_parser("list", help="List artifact metadata")
    list_parser.add_argument("--bundle-manifest", required=True, help="Path to a RepoGround bundle manifest")
    list_parser.add_argument("--roles-only", action="store_true", help="Print only artifact roles")
    reading_parser = ground_subparsers.add_parser("required-reading", help="RepoGround required-reading commands")
    reading_subparsers = reading_parser.add_subparsers(dest="required_reading_cmd", required=True, help="Required-reading commands")
    resolve_parser = reading_subparsers.add_parser("resolve", help="Resolve required reading from a bundle manifest")
    resolve_parser.add_argument("--bundle-manifest", required=True, help="Path to a RepoGround bundle manifest")
    resolve_parser.add_argument("--task-profile", required=True, help="Required-reading task profile")

    query_parser = ground_subparsers.add_parser(
        "query",
        help="Run a read-only resolved evidence query against an existing RepoGround bundle",
    )
    query_parser.add_argument("--bundle-manifest", required=True, help="Path to a RepoGround bundle manifest")
    query_parser.add_argument("--q", default="", help="Search query text")
    query_parser.add_argument("--k", type=int, default=10, help="Maximum resolved hits")
    query_parser.add_argument("--repo", help="Filter by repo_id")
    query_parser.add_argument("--path", help="Filter by path substring")
    query_parser.add_argument("--ext", help="Filter by file extension")
    query_parser.add_argument("--layer", help="Filter by layer")
    query_parser.add_argument("--artifact-type", help="Filter by artifact_type")
    query_parser.add_argument(
        "--raw-index-result",
        action="store_true",
        help="Disable resolved evidence and return only the bounded raw index result",
    )
    query_parser.add_argument(
        "--no-project-sources",
        action="store_true",
        help="Do not add the compact source citation projection",
    )

    ask_parser = ground_subparsers.add_parser(
        "ask",
        help="Build a read-only RepoGround ask context pack from an existing snapshot",
    )
    ask_parser.add_argument("--bundle-manifest", required=True, help="Path to a RepoGround bundle manifest")
    ask_parser.add_argument("--q", required=True, help="Question or task query")
    ask_parser.add_argument("--task-profile", default="basic_repo_question", help="Required-reading task profile")
    ask_parser.add_argument("--context-budget", type=int, default=8000, help="Maximum context token budget")
    ask_parser.add_argument("--answer-budget", type=int, default=1200, help="Maximum downstream answer token budget")
    ask_parser.add_argument("--k", type=int, default=5, help="Maximum retrieval hits")
    ask_parser.add_argument("--emit", choices=["json", "text"], default="json", help="Output format")
    ask_parser.add_argument("--strict", action="store_true", help="Treat warn status as exit code 1")

    ask_eval_parser = ground_subparsers.add_parser(
        "ask-eval",
        help="Evaluate RepoGround ask context packs against a legacy-compatible gold-query set",
    )
    ask_eval_parser.add_argument("--bundle-manifest", required=True, help="Path to a RepoGround bundle manifest")
    ask_eval_parser.add_argument("--goldset", required=True, help="Path to a legacy repobrief ask-goldset JSON contract")
    ask_eval_parser.add_argument("--baseline", help="Optional previous eval JSON or metrics JSON for promotion gating")
    ask_eval_parser.add_argument("--k", type=int, default=5, help="Maximum retrieval hits per query")
    ask_eval_parser.add_argument("--context-budget", type=int, default=8000, help="Maximum context token budget")
    ask_eval_parser.add_argument("--strict", action="store_true", help="Treat warn status as exit code 1")

    symbol_parser = ground_subparsers.add_parser(
        "symbol",
        help="Read-only Python symbol-index consumer commands",
    )
    symbol_subparsers = symbol_parser.add_subparsers(
        dest="symbol_cmd",
        required=True,
        help="Symbol commands",
    )
    symbol_search_parser = symbol_subparsers.add_parser(
        "search",
        help="Search an existing python_symbol_index_json artifact without importing target code",
    )
    symbol_search_parser.add_argument("--bundle-manifest", required=True, help="Path to a RepoGround bundle manifest")
    symbol_search_parser.add_argument("--q", default="", help="Search text over name, qualified name, module, path and kind")
    symbol_search_parser.add_argument("--k", type=int, default=25, help="Maximum symbol hits")
    symbol_search_parser.add_argument("--kind", choices=["class", "function", "async_function"], help="Filter by symbol kind")
    symbol_search_parser.add_argument("--path", help="Filter by source path substring")

    context_parser = ground_subparsers.add_parser(
        "context",
        help="Compile bounded RepoGround context plans for a task and token budget",
    )
    context_subparsers = context_parser.add_subparsers(
        dest="context_cmd",
        required=True,
        help="Context commands",
    )
    context_compile = context_subparsers.add_parser(
        "compile",
        help="Select ordered context from existing bundle artifacts without refreshing them",
    )
    context_compile.add_argument("--bundle-manifest", required=True, help="Path to a RepoGround bundle manifest")
    context_compile.add_argument("--task", required=True, help="Natural-language task description")
    context_compile.add_argument("--task-profile", default="basic_repo_question", help="Required-reading task profile")
    context_compile.add_argument("--query", help="Optional retrieval/symbol query; defaults to --task")
    context_compile.add_argument("--context-budget", type=int, default=8000, help="Token budget for selected context")
    context_compile.add_argument("--signal-k", type=int, default=10, help="Maximum retrieval/symbol signal hits")
    context_compile.add_argument("--bytes-per-token", type=float, default=4.0, help="Byte divisor used for rough token estimate")
    context_compile.add_argument("--strict", action="store_true", help="Treat warn status as exit code 1")

    delta_context_parser = ground_subparsers.add_parser(
        "delta-context",
        help="Compile bounded PR/revision delta context without emitting a review verdict",
    )
    delta_context_subparsers = delta_context_parser.add_subparsers(
        dest="delta_context_cmd",
        required=True,
        help="Delta-context commands",
    )
    delta_context_compile = delta_context_subparsers.add_parser(
        "compile",
        help="Read a unified diff and optional bundle signals into review context",
    )
    delta_context_compile.add_argument("--diff", required=True, help="Path to a unified git diff")
    delta_context_compile.add_argument("--bundle-manifest", help="Optional existing RepoGround bundle manifest")
    delta_context_compile.add_argument("--task", default="Review pull request delta", help="Natural-language review task")
    delta_context_compile.add_argument("--context-budget", type=int, default=8000, help="Token budget for selected context")
    delta_context_compile.add_argument("--signal-k", type=int, default=10, help="Maximum symbol/relation/citation hints")
    delta_context_compile.add_argument("--context-window-lines", type=int, default=20, help="Lines around each changed hunk to report")
    delta_context_compile.add_argument("--bytes-per-token", type=float, default=4.0, help="Byte divisor used for rough token estimate")
    delta_context_compile.add_argument("--strict", action="store_true", help="Treat warn status as exit code 1")

    review_coverage_parser = ground_subparsers.add_parser(
        "review-coverage",
        help="Measure proof-of-reading citation coverage for delta reviews",
    )
    review_coverage_subparsers = review_coverage_parser.add_subparsers(
        dest="review_coverage_cmd",
        required=True,
        help="Review-coverage commands",
    )
    review_coverage_compile = review_coverage_subparsers.add_parser(
        "compile",
        help="Compare a delta-context report with citations in a review artifact",
    )
    review_coverage_compile.add_argument("--delta-context", required=True, help="Path to a RepoGround delta-context JSON report")
    review_coverage_compile.add_argument("--review", required=True, help="Path to review text or JSON")
    review_coverage_compile.add_argument("--min-range-coverage", type=float, default=0.6, help="Advisory minimum covered relevant range ratio")
    review_coverage_compile.add_argument("--policy-name", default="advisory", help="Label for the advisory threshold policy")

    external_parser = ground_subparsers.add_parser(
        "external-manifest",
        help="Write bounded external manifest references from existing bundle manifests",
    )
    external_subparsers = external_parser.add_subparsers(
        dest="external_manifest_cmd",
        required=True,
        help="External manifest commands",
    )
    external_write_parser = external_subparsers.add_parser(
        "write",
        help="Write an external manifest reference without refreshing the source snapshot",
    )
    external_write_parser.add_argument("--bundle-manifest", required=True, help="Path to a RepoGround bundle manifest")
    external_write_parser.add_argument("--out", required=True, help="Output manifest path")
    external_write_parser.add_argument("--repository", required=True, help="Registry repository segment, for example heimgewebe-katalog")
    external_write_parser.add_argument("--ref", required=True, help="Registry ref segment, for example main")
    external_write_parser.add_argument(
        "--artifact-family",
        choices=["repobrief", "lenskit"],
        default="repobrief",
        help="External artifact family to advertise",
    )

    external_publish_parser = external_subparsers.add_parser(
        "publish",
        help="Publish external manifest references under a stable publication root",
    )
    external_publish_parser.add_argument("--bundle-manifest", required=True, help="Path to a RepoGround bundle manifest")
    external_publish_parser.add_argument("--publication-root", required=True, help="Root directory for published external manifests")
    external_publish_parser.add_argument("--repository", required=True, help="Registry repository segment, for example heimgewebe-katalog")
    external_publish_parser.add_argument("--ref", required=True, help="Registry ref segment, for example main")
    external_publish_parser.add_argument(
        "--artifact-family",
        choices=["repobrief", "lenskit"],
        action="append",
        dest="artifact_families",
        help="Artifact family to publish; repeatable; defaults to both",
    )

    external_refresh_parser = external_subparsers.add_parser(
        "refresh",
        help="Create a RepoGround snapshot and publish external manifest references",
    )
    external_refresh_parser.add_argument("--repo", required=True, help="Repository path to snapshot")
    external_refresh_parser.add_argument("--out", required=True, help="Output directory for RepoGround bundle artifacts")
    external_refresh_parser.add_argument("--publication-root", required=True, help="Root directory for published external manifests")
    external_refresh_parser.add_argument("--repository", required=True, help="Registry repository segment, for example heimgewebe-katalog")
    external_refresh_parser.add_argument("--ref", required=True, help="Registry ref segment, for example main")
    external_refresh_parser.add_argument("--artifact-family", choices=["repobrief", "lenskit"], action="append", dest="artifact_families")
    external_refresh_parser.add_argument("--profile", choices=sorted(profile_names()), default="agent-portable")
    external_refresh_parser.add_argument("--mode", choices=["gesamt", "pro-repo"], default="gesamt")
    external_refresh_parser.add_argument("--max-bytes", default="0")
    external_refresh_parser.add_argument("--split-size", default="25MB")
    external_refresh_parser.add_argument("--path-filter")
    external_refresh_parser.add_argument("--ext", action="append")
    external_refresh_parser.add_argument("--output-mode", choices=["archive", "retrieval", "dual"])
    refresh_redaction = external_refresh_parser.add_mutually_exclusive_group()
    refresh_redaction.add_argument(
        "--redact-secrets", action="store_true", dest="redact_secrets"
    )
    refresh_redaction.add_argument(
        "--no-redact-secrets", action="store_false", dest="redact_secrets"
    )
    external_refresh_parser.add_argument("--no-include-hidden", action="store_false", dest="include_hidden")
    external_refresh_parser.set_defaults(include_hidden=True, redact_secrets=None)

    latest_parser = ground_subparsers.add_parser(
        "latest-complete",
        help="Read or explicitly write the latest-complete RepoGround registry",
    )
    latest_subparsers = latest_parser.add_subparsers(
        dest="latest_complete_cmd",
        required=True,
        help="Latest-complete registry commands",
    )
    latest_write = latest_subparsers.add_parser(
        "write",
        help="Explicitly write a latest-complete registry from an existing bundle manifest",
    )
    latest_write.add_argument("--bundle-manifest", required=True, help="Path to a RepoGround bundle manifest")
    latest_write.add_argument("--out", required=True, help="Output path for the latest-complete registry JSON")
    latest_status = latest_subparsers.add_parser(
        "status",
        help="Read-only freshness status for an existing latest-complete registry",
    )
    latest_status.add_argument("--registry", required=True, help="Path to latest-complete registry JSON")
    latest_status.add_argument("--repo", help="Optional local repo path for explicit HEAD drift comparison")

    workbench_eval_parser = ground_subparsers.add_parser(
        "workbench-eval",
        help="Compare fixed navigation targets in the reading pack and read-only workbench",
    )
    workbench_eval_parser.add_argument("--config", required=True, help="Read-only adapter config JSON")
    workbench_eval_parser.add_argument("--snapshot-id", required=True, help="Registered snapshot id")
    workbench_eval_parser.add_argument("--goldset", required=True, help="Fixed usefulness goldset JSON")
    workbench_eval_parser.add_argument("--k", type=int, default=10, help="Maximum query and symbol hits")

    adapter_parser = ground_subparsers.add_parser(
        "adapter",
        help="Protocol-neutral read-only access to explicitly registered bundles",
    )
    adapter_subparsers = adapter_parser.add_subparsers(
        dest="adapter_cmd",
        required=True,
        help="Read-only adapter commands",
    )
    adapter_list = adapter_subparsers.add_parser(
        "list",
        help="List snapshots explicitly registered in an adapter config",
    )
    adapter_list.add_argument("--config", required=True, help="Adapter config JSON")
    adapter_call = adapter_subparsers.add_parser(
        "call",
        help="Dispatch one JSON request without creating or refreshing snapshots",
    )
    adapter_call.add_argument("--config", required=True, help="Adapter config JSON")
    adapter_call.add_argument(
        "--request",
        required=True,
        help="Request JSON path, or '-' to read one JSON object from stdin",
    )

    patch_eval_parser = ground_subparsers.add_parser(
        "patch-evaluation",
        help="Read-only consumption of external Patch Evaluation Sidecar artifacts",
    )
    patch_eval_subparsers = patch_eval_parser.add_subparsers(
        dest="patch_evaluation_cmd",
        required=True,
        help="Patch-evaluation commands",
    )
    pe_validate_parser = patch_eval_subparsers.add_parser(
        "validate",
        help="Validate an external patch-evaluation artifact against the v1 schema (read-only)",
    )
    pe_validate_parser.add_argument("path", help="Path to a patch-evaluation.v1 artifact")
    pe_validate_parser.add_argument(
        "--summary",
        action="store_true",
        help="Also print the bounded external-evidence summary",
    )


def register_legacy_repobrief_command(subparsers: argparse._SubParsersAction) -> None:
    ground_parser = subparsers.add_parser(
        "repobrief",
        help="Deprecated RepoBrief compatibility command; use RepoGround ground",
    )
    register_ground_command_groups(ground_parser)

def run_ground(args: argparse.Namespace) -> int:
    if args.ground_cmd == "snapshot" and args.snapshot_cmd == "create":
        return run_snapshot_create(args)
    if args.ground_cmd == "snapshot" and args.snapshot_cmd == "check":
        return run_snapshot_check(args)
    if args.ground_cmd == "snapshot" and args.snapshot_cmd == "status":
        return run_snapshot_status(args)
    if args.ground_cmd == "preflight":
        return run_preflight(args)
    if args.ground_cmd == "artifact" and args.artifact_cmd == "get":
        return run_artifact_get(args)
    if args.ground_cmd == "artifact" and args.artifact_cmd == "list":
        return run_artifact_list(args)
    if args.ground_cmd == "required-reading" and args.required_reading_cmd == "resolve":
        return run_required_reading_resolve(args)
    if args.ground_cmd == "query":
        return run_query_existing_index(args)
    if args.ground_cmd == "ask":
        return run_ask(args)
    if args.ground_cmd == "ask-eval":
        return run_ask_eval(args)
    if args.ground_cmd == "symbol" and args.symbol_cmd == "search":
        return run_symbol_search(args)
    if args.ground_cmd == "context" and args.context_cmd == "compile":
        return run_context_compile(args)
    if args.ground_cmd == "delta-context" and args.delta_context_cmd == "compile":
        return run_delta_context_compile(args)
    if args.ground_cmd == "review-coverage" and args.review_coverage_cmd == "compile":
        return run_review_coverage_compile(args)
    if args.ground_cmd == "external-manifest" and args.external_manifest_cmd == "write":
        return run_external_manifest_write(args)
    if args.ground_cmd == "external-manifest" and args.external_manifest_cmd == "publish":
        return run_external_manifest_publish(args)
    if args.ground_cmd == "external-manifest" and args.external_manifest_cmd == "refresh":
        return run_external_manifest_refresh(args)
    if args.ground_cmd == "latest-complete" and args.latest_complete_cmd == "write":
        return run_latest_complete_write(args)
    if args.ground_cmd == "latest-complete" and args.latest_complete_cmd == "status":
        return run_latest_complete_status(args)
    if args.ground_cmd == "workbench-eval":
        return run_workbench_eval(args)
    if args.ground_cmd == "adapter":
        return run_readonly_adapter(args)
    if args.ground_cmd == "patch-evaluation" and args.patch_evaluation_cmd == "validate":
        return run_patch_evaluation_validate(args)
    print("Unsupported RepoGround ground command", file=sys.stderr)
    return 2


def run_external_manifest_write(args: argparse.Namespace) -> int:
    from merger.repoground.core.external_manifest_reference import (
        ExternalManifestReferenceError,
        write_external_manifest_reference,
    )

    try:
        result = write_external_manifest_reference(
            args.bundle_manifest,
            args.out,
            repository=args.repository,
            ref=args.ref,
            artifact_family=args.artifact_family,
        )
    except ExternalManifestReferenceError as exc:
        print("repoground ground external-manifest write: " + str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def run_external_manifest_publish(args: argparse.Namespace) -> int:
    from merger.repoground.core.external_manifest_reference import (
        ExternalManifestReferenceError,
        publish_external_manifest_references,
    )

    try:
        result = publish_external_manifest_references(
            args.bundle_manifest,
            args.publication_root,
            repository=args.repository,
            ref=args.ref,
            artifact_families=args.artifact_families,
        )
    except ExternalManifestReferenceError as exc:
        print("repobrief external-manifest publish: " + str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0

def run_external_manifest_refresh(args: argparse.Namespace) -> int:
    import contextlib
    import io

    repo_path = Path(args.repo).expanduser().resolve()
    out_path = Path(args.out).expanduser().resolve()
    publication_root = Path(args.publication_root).expanduser().resolve()
    if publication_root == repo_path or repo_path in publication_root.parents:
        print("repobrief external-manifest refresh: publication root must not be inside the source repo", file=sys.stderr)
        return 2
    if out_path != publication_root and publication_root not in out_path.parents:
        print(
            "repobrief external-manifest refresh: output directory must be inside "
            "publication_root for portable external publication",
            file=sys.stderr,
        )
        return 2

    from merger.repoground.core.external_manifest_reference import (
        ExternalManifestReferenceError,
        publication_manifest_path,
        publish_external_manifest_references,
    )

    try:
        for family in (args.artifact_families or ["lenskit", "repobrief"]):
            publication_manifest_path(
                publication_root,
                repository=args.repository,
                ref=args.ref,
                artifact_family=family,
            )
    except (ExternalManifestReferenceError, OSError, ValueError) as exc:
        print("repobrief external-manifest refresh: " + str(exc), file=sys.stderr)
        return 2

    snapshot_args = argparse.Namespace(
        repo=args.repo, out=str(out_path), profile=args.profile, mode=args.mode,
        max_bytes=args.max_bytes, split_size=args.split_size, path_filter=args.path_filter,
        ext=args.ext, output_mode=args.output_mode, redact_secrets=args.redact_secrets,
        include_hidden=args.include_hidden,
        latest_complete_registry=None,
    )
    snapshot_stdout = io.StringIO()
    with contextlib.redirect_stdout(snapshot_stdout):
        snapshot_rc = run_snapshot_create(snapshot_args)
    if snapshot_rc != 0:
        print(snapshot_stdout.getvalue(), file=sys.stderr, end="")
        return snapshot_rc
    snapshot_result = json.loads(snapshot_stdout.getvalue())
    bundle_manifest = snapshot_result.get("bundle_manifest")
    if not isinstance(bundle_manifest, str) or not bundle_manifest:
        print("repobrief external-manifest refresh: missing bundle_manifest", file=sys.stderr)
        return 1
    try:
        from merger.repoground.core.bundle_generation import (
            BundleGenerationError,
            resolve_bundle_manifest_path,
        )

        publish_source_manifest = resolve_bundle_manifest_path(bundle_manifest)
        publication = publish_external_manifest_references(
            publish_source_manifest, publication_root,
            repository=args.repository, ref=args.ref, artifact_families=args.artifact_families,
        )
    except (
        BundleGenerationError,
        ExternalManifestReferenceError,
        OSError,
        ValueError,
    ) as exc:
        print("repobrief external-manifest refresh: " + str(exc), file=sys.stderr)
        return 2
    print(json.dumps({
        "status": "ok",
        "command": "repobrief external-manifest refresh",
        "snapshot": snapshot_result,
        "publication": publication,
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }, indent=2, sort_keys=True))
    return 0


def _best_effort_display_path(value: str | Path) -> str:
    path = Path(value).expanduser()
    try:
        return str(path.resolve())
    except (OSError, RuntimeError):
        return str(path)


def _latest_complete_error_document(exc: ValueError, *, out: str) -> dict[str, Any]:
    receipt = getattr(exc, "receipt", None)
    if isinstance(receipt, dict):
        return receipt
    return {
        "kind": "repobrief.latest_complete_registry_write",
        "version": "v2",
        "status": "error",
        "publication_result": "not_published",
        "publication_state": "failed_before_replace",
        "registry_path": _best_effort_display_path(out),
        "serialization_resource": _best_effort_display_path(Path(out).parent),
        "target_directory_created": False,
        "target_directories_created": [],
        "error": {
            "code": "validation_failed",
            "phase": "preflight",
            "message": str(exc),
        },
        "transaction": {
            "replace_performed": False,
            "temporary_file_write": "not_reached",
            "file_fsync": "not_reached",
            "atomic_replace": "not_reached",
            "directory_fsync": "not_reached",
            "readback": "unavailable",
            "directory_identity": "not_reached",
            "temporary_file_created": False,
            "temporary_file_cleanup": "not_required",
            "temporary_file_name": None,
            "target": None,
        },
        "recovery": {
            "required": False,
            "action": "fix the validation error and retry",
            "automatic_rollback_claimed": False,
        },
        "mutation_boundary": {
            "writes": [
                "latest_complete_registry_parent_directory",
                "latest_complete_registry_temporary_file",
                "latest_complete_registry",
            ],
            "observed_writes": [],
            "does_not_mutate": [
                "git",
                "pull_requests",
                "patches",
                "source_working_tree",
                "brief_bundle_artifacts",
            ],
            "read_paths_do_not_refresh": True,
            "hidden_refresh_allowed": False,
        },
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }


def run_latest_complete_write(args: argparse.Namespace) -> int:
    from merger.repoground.core.latest_complete import write_latest_complete_registry

    try:
        result = write_latest_complete_registry(args.bundle_manifest, args.out)
    except ValueError as exc:
        error_document = _latest_complete_error_document(exc, out=args.out)
        print(json.dumps(error_document, indent=2, sort_keys=True), file=sys.stderr)
        return 1 if error_document.get("publication_result") == "uncertain" else 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def run_latest_complete_status(args: argparse.Namespace) -> int:
    from merger.repoground.core.latest_complete import latest_complete_status

    try:
        result = latest_complete_status(args.registry, repo=args.repo)
    except ValueError as exc:
        print("repobrief latest-complete status: " + str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("status") in {"ok", "warn"} else 1


def run_workbench_eval(args: argparse.Namespace) -> int:
    from merger.repoground.core.workbench_usefulness import (
        evaluate_workbench_usefulness,
    )

    try:
        result = evaluate_workbench_usefulness(
            args.config,
            snapshot_id=args.snapshot_id,
            goldset_path=args.goldset,
            k=args.k,
        )
    except ValueError as exc:
        print("repobrief workbench-eval: " + str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("status") == "pass" else 1


def run_readonly_adapter(args: argparse.Namespace) -> int:
    from merger.repoground.core.readonly_adapter import (
        RepoGroundReadonlyAdapter,
        RepoGroundReadonlyAdapterError,
    )

    try:
        adapter = RepoGroundReadonlyAdapter.from_config(args.config)
        if args.adapter_cmd == "list":
            result = adapter.snapshot_list()
        else:
            if args.request == "-":
                request = json.load(sys.stdin)
            else:
                request = json.loads(
                    Path(args.request).expanduser().resolve().read_text(encoding="utf-8")
                )
            result = adapter.dispatch(request)
    except (RepoGroundReadonlyAdapterError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        print("repobrief adapter: " + str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("status") in {"available", "pass", "warn"} else 1


def run_patch_evaluation_validate(args: argparse.Namespace) -> int:
    from merger.repoground.core.patch_evaluation import (
        load_patch_evaluation,
        summarize_patch_evaluation,
        validate_patch_evaluation,
    )

    try:
        data = load_patch_evaluation(args.path)
    except ValueError as exc:
        print("repobrief patch-evaluation validate: " + str(exc), file=sys.stderr)
        return 2
    report = validate_patch_evaluation(data)
    if getattr(args, "summary", False):
        report = {"validation": report, "summary": summarize_patch_evaluation(data)}
    print(json.dumps(report, indent=2, sort_keys=True))
    status = report.get("validation", report).get("status")
    return 0 if status in {"pass", "warn"} else 1


def run_snapshot_check(args: argparse.Namespace) -> int:
    from merger.repoground.core.bundle_access import snapshot_check

    try:
        result = snapshot_check(args.bundle_manifest, args.task_profile)
    except ValueError as exc:
        print("repobrief snapshot check: " + str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("status") in {"pass", "warn"} else 1


def run_snapshot_status(args: argparse.Namespace) -> int:
    from merger.repoground.core.bundle_access import snapshot_status

    try:
        result = snapshot_status(args.bundle_manifest)
    except ValueError as exc:
        print("repobrief snapshot status: " + str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def run_artifact_get(args: argparse.Namespace) -> int:
    from merger.repoground.core.bundle_access import get_artifact

    try:
        result = get_artifact(args.bundle_manifest, args.role)
    except ValueError as exc:
        print("repobrief artifact get: " + str(exc), file=sys.stderr)
        return 2
    if args.path_only:
        artifact = result.get("artifact") if isinstance(result, dict) else None
        if not isinstance(artifact, dict) or not artifact.get("absolute_path"):
            return 1
        print(artifact["absolute_path"])
        return 0
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("status") == "available" else 1

def run_artifact_list(args: argparse.Namespace) -> int:
    from merger.repoground.core.bundle_access import list_artifacts

    try:
        result = list_artifacts(args.bundle_manifest)
    except ValueError as exc:
        print("repobrief artifact list: " + str(exc), file=sys.stderr)
        return 2
    if args.roles_only:
        for role in result.get("roles", []):
            print(role)
        return 0
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0

def run_required_reading_resolve(args: argparse.Namespace) -> int:
    from merger.repoground.core.bundle_access import resolve_required_reading_for_bundle

    try:
        result = resolve_required_reading_for_bundle(args.bundle_manifest, args.task_profile)
    except ValueError as exc:
        print("repobrief required-reading resolve: " + str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("status") in {"pass", "warn"} else 1

def run_query_existing_index(args: argparse.Namespace) -> int:
    from merger.repoground.core.bundle_access import query_existing_index

    filters = {
        "repo": args.repo,
        "path": args.path,
        "ext": args.ext,
        "layer": args.layer,
        "artifact_type": getattr(args, "artifact_type", None),
    }
    try:
        result = query_existing_index(
            args.bundle_manifest,
            args.q,
            k=args.k,
            filters=filters,
            resolve_evidence=not args.raw_index_result,
            project_sources=not args.raw_index_result and not args.no_project_sources,
        )
    except ValueError as exc:
        print("repobrief query: " + str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("status") == "available" else 1


def run_ask(args: argparse.Namespace) -> int:
    from merger.repoground.core.ask_context import (
        build_ask_context_pack,
        render_ask_context_pack_text,
    )

    try:
        result = build_ask_context_pack(
            args.bundle_manifest,
            query=args.q,
            task_profile=args.task_profile,
            max_context_tokens=args.context_budget,
            max_answer_tokens=args.answer_budget,
            k=args.k,
        )
    except ValueError as exc:
        print("repobrief ask: " + str(exc), file=sys.stderr)
        return 2
    if args.emit == "text":
        print(render_ask_context_pack_text(result), end="")
    else:
        print(json.dumps(result, indent=2, sort_keys=True))
    status = result.get("required_reading", {}).get("status")
    if status == "fail":
        return 1
    if status == "warn" and args.strict:
        return 1
    return 0


def run_ask_eval(args: argparse.Namespace) -> int:
    from merger.repoground.core.ask_evaluation import evaluate_ask_goldset

    try:
        result = evaluate_ask_goldset(
            args.bundle_manifest,
            args.goldset,
            k=args.k,
            max_context_tokens=args.context_budget,
            baseline_path=args.baseline,
        )
    except ValueError as exc:
        print("repobrief ask-eval: " + str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    status = result.get("status")
    if status == "fail":
        return 1
    if status == "warn" and args.strict:
        return 1
    return 0


def run_symbol_search(args: argparse.Namespace) -> int:
    from merger.repoground.core.bundle_access import search_symbol_index

    try:
        result = search_symbol_index(
            args.bundle_manifest,
            args.q,
            k=args.k,
            kind=args.kind,
            path=args.path,
        )
    except ValueError as exc:
        print("repobrief symbol search: " + str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("status") == "available" else 1


def run_review_coverage_compile(args: argparse.Namespace) -> int:
    from merger.repoground.core.review_coverage import compile_review_coverage

    result = compile_review_coverage(
        delta_context_path=args.delta_context,
        review_path=args.review,
        min_range_coverage=args.min_range_coverage,
        policy_name=args.policy_name,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 1 if result.get("status") == "invalid" else 0


def run_delta_context_compile(args: argparse.Namespace) -> int:
    from merger.repoground.core.delta_context import compile_delta_context

    result = compile_delta_context(
        diff_path=args.diff,
        bundle_manifest=args.bundle_manifest,
        task=args.task,
        context_budget_tokens=args.context_budget,
        signal_k=args.signal_k,
        context_window_lines=args.context_window_lines,
        bytes_per_token=args.bytes_per_token,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    status = result.get("status")
    if status == "pass":
        return 0
    if status == "warn":
        return 1 if args.strict else 0
    if status in {"fail", "invalid"}:
        return 1
    return 2


def run_context_compile(args: argparse.Namespace) -> int:
    from merger.repoground.core.context_compiler import compile_context_plan

    result = compile_context_plan(
        args.bundle_manifest,
        task=args.task,
        task_profile=args.task_profile,
        context_budget_tokens=args.context_budget,
        query=args.query,
        signal_k=args.signal_k,
        bytes_per_token=args.bytes_per_token,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    status = result.get("status")
    if status == "pass":
        return 0
    if status == "warn":
        return 1 if args.strict else 0
    if status in {"fail", "invalid"}:
        return 1
    return 2


def run_preflight(args: argparse.Namespace) -> int:
    from merger.repoground.core.snapshot_preflight import run_consumption_preflight

    try:
        result = run_consumption_preflight(args.bundle_manifest, args.task_profile)
    except ValueError as exc:
        print("repobrief preflight: " + str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("status") in {"pass", "warn"} else 1


def build_snapshot_create_result(args: argparse.Namespace) -> dict[str, Any]:
    profile = args.profile
    repo = Path(args.repo).expanduser().resolve()
    out = Path(args.out).expanduser().resolve()

    if not repo.exists() or not repo.is_dir():
        raise ValueError(f"repo is not a directory: {repo}")
    if out == repo or repo in out.parents:
        raise ValueError("bad output path")

    redact_secrets, redaction_source, redaction_required = resolve_snapshot_redaction(
        profile, getattr(args, "redact_secrets", None)
    )
    output_plan = profile_output_mode_plan(profile, args.output_mode)
    output_mode = output_plan["selected_output_mode"]
    conflicts = tuple(output_plan["conflicts"])
    if conflicts:
        raise ValueError(
            f"profile {profile} excludes artifacts produced by output mode {output_mode}: "
            + ", ".join(conflicts)
        )

    out.mkdir(parents=True, exist_ok=True)
    max_bytes = parse_human_size(args.max_bytes)
    split_size = parse_human_size(args.split_size)
    ext_filter = parse_extensions(args.ext)
    extras = ExtrasConfig(json_sidecar=True, augment_sidecar=True)

    summary = scan_repo(
        repo,
        extensions=ext_filter,
        path_contains=args.path_filter,
        max_bytes=max_bytes,
        include_paths=None,
        calculate_md5=True,
        include_hidden=args.include_hidden,
    )
    generator_info = {
        "name": "repobrief",
        "version": os.getenv("REPOGROUND_VERSION") or os.getenv("RLENS_VERSION", "dev"),
        "platform": getattr(args, "platform", "cli"),
        "repobrief_output_plan": output_plan,
    }
    artifacts = write_reports_v2(
        out,
        repo.parent,
        [summary],
        profile_level(profile),
        args.mode,
        max_bytes,
        False,
        False,
        split_size,
        debug=False,
        path_filter=args.path_filter,
        ext_filter=ext_filter,
        extras=extras,
        output_mode=output_mode,
        redact_secrets=redact_secrets,
        include_hidden=args.include_hidden,
        generator_info=generator_info,
        # Snapshot finalization still mutates the manifest and adds control files;
        # publish exactly once below after that complete file set is known.
        publish_generation=False,
    )
    dropped_profile_paths = enforce_profile_exclusions(artifacts.bundle_manifest, profile)
    snapshot_plan_path = emit_snapshot_plan_report(
        artifacts.bundle_manifest, profile, output_plan
    )
    finalization = finalize_snapshot_bundle(artifacts.bundle_manifest, profile)
    profile_evaluation = finalization.get("profile_evaluation")
    artifact_paths = [
        path
        for path in artifacts.get_all_paths()
        if path not in dropped_profile_paths
    ]
    if snapshot_plan_path is not None and snapshot_plan_path not in artifact_paths:
        artifact_paths.append(snapshot_plan_path)
    for raw_path in finalization.get("control_paths", []):
        path = Path(raw_path)
        if path not in artifact_paths:
            artifact_paths.append(path)

    published_bundle_manifest = artifacts.bundle_manifest
    bundle_generation_result = None
    if artifacts.bundle_manifest is not None and finalization.get("status") == "pass":
        from merger.repoground.core.bundle_generation import publish_bundle_generation

        bundle_generation_result = publish_bundle_generation(
            artifacts.bundle_manifest,
            output_root=out,
            extra_paths=artifact_paths,
        )
        published_bundle_manifest = bundle_generation_result.current_manifest_path
        if published_bundle_manifest not in artifact_paths:
            artifact_paths.append(published_bundle_manifest)

    latest_registry_result = None
    latest_registry_arg = getattr(args, "latest_complete_registry", None)
    if (
        latest_registry_arg
        and published_bundle_manifest is not None
        and finalization.get("status") == "pass"
    ):
        from merger.repoground.core.latest_complete import (
            write_latest_complete_registry,
        )

        latest_registry_result = write_latest_complete_registry(
            published_bundle_manifest,
            latest_registry_arg,
        )

    return {
        "status": "ok" if finalization.get("status") == "pass" else "fail",
        "command": "repobrief snapshot create",
        "profile": profile,
        "output_mode": output_mode,
        "output_plan": output_plan,
        "redaction": {
            "enabled": redact_secrets,
            "required": redaction_required,
            "source": redaction_source,
        },
        "repo": str(repo),
        "out": str(out),
        "bundle_manifest": str(published_bundle_manifest) if published_bundle_manifest else None,
        "profile_evaluation": profile_evaluation,
        "snapshot_plan_report": str(snapshot_plan_path) if snapshot_plan_path else None,
        "export_safety_report": next(
            (
                path
                for path in finalization.get("control_paths", [])
                if path.endswith(".export_safety_report.json")
            ),
            None,
        ),
        "finalization": finalization,
        "bundle_generation": (
            bundle_generation_result.as_dict()
            if bundle_generation_result is not None
            else None
        ),
        "latest_complete_registry": latest_registry_result,
        "refreshed_agent_entrypoints": finalization.get("refreshed_paths", []),
        "removed_profile_excluded_artifacts": [str(path) for path in dropped_profile_paths],
        "artifacts": [str(path) for path in artifact_paths],
        "mutation_boundary": {
            "writes": ["brief_bundle_artifacts"],
            "does_not_mutate": ["git", "pull_requests", "patches", "source_working_tree"],
            "read_paths_do_not_refresh": True,
        },
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }


def run_snapshot_create(args: argparse.Namespace) -> int:
    try:
        result = build_snapshot_create_result(args)
    except ValueError as exc:
        receipt = getattr(exc, "receipt", None)
        if isinstance(receipt, dict):
            print(json.dumps(receipt, indent=2, sort_keys=True), file=sys.stderr)
            return 1 if receipt.get("publication_result") == "uncertain" else 2
        print(f"repobrief snapshot create: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("status") == "ok" else 1


def _drop_manifest_role(bundle_manifest: Path, role: str) -> list[Path]:
    data = json.loads(bundle_manifest.read_text(encoding="utf-8"))
    artifacts = data.get("artifacts", [])
    if not isinstance(artifacts, list):
        return []
    kept = []
    dropped: list[Path] = []
    root = bundle_manifest.parent.resolve()
    for artifact in artifacts:
        if not isinstance(artifact, dict) or artifact.get("role") != role:
            kept.append(artifact)
            continue
        raw_path = artifact.get("path")
        if isinstance(raw_path, str) and raw_path:
            candidate = (bundle_manifest.parent / raw_path).resolve()
            try:
                candidate.relative_to(root)
            except ValueError:
                pass
            else:
                dropped.append(candidate)
    data["artifacts"] = kept
    if role == "sqlite_index":
        capabilities = data.setdefault("capabilities", {})
        if isinstance(capabilities, dict) and not any(
            isinstance(a, dict) and a.get("role") == "sqlite_index" for a in kept
        ):
            capabilities["fts5_bm25"] = False
    _json_write_atomic(bundle_manifest, data)
    for path in dropped:
        try:
            path.unlink()
        except FileNotFoundError:
            # Already absent is acceptable during profile-surface cleanup.
            pass
    return dropped


def enforce_profile_exclusions(bundle_manifest: Path | None, profile: str) -> list[Path]:
    if bundle_manifest is None:
        return []
    dropped: list[Path] = []
    for role in profile_excluded_roles(profile):
        dropped.extend(_drop_manifest_role(bundle_manifest, role))
    return dropped


def refresh_entry(bundle_manifest: Path | None) -> list[Path]:
    if bundle_manifest is None:
        return []
    import importlib

    refreshed: list[Path] = []
    base = "merger.repoground.core."
    pack_mod = importlib.import_module(base + "agent_" + "reading_pack")
    entry_mod = importlib.import_module(base + "agent_" + "entry_manifest")
    pack_fn = getattr(pack_mod, "produce_" + "agent_" + "reading_pack")
    entry_fn = getattr(entry_mod, "produce_" + "agent_" + "entry_manifest")

    pack_report = pack_fn(str(bundle_manifest))
    if pack_report.get("status") == "ok":
        pack_path = Path(pack_report["output_path"])
        _add_manifest_artifact(bundle_manifest, pack_path, "agent_reading_pack", "text/markdown")
        refreshed.append(pack_path)

    entry_report = entry_fn(str(bundle_manifest))
    if entry_report.get("status") == "ok":
        entry_path = Path(entry_report["output_path"])
        _add_manifest_artifact(bundle_manifest, entry_path, "agent_entry_manifest", "application/json")
        refreshed.append(entry_path)

    return refreshed


# Bounded callable aliases for source compatibility.
register_repobrief_command_groups = register_ground_command_groups
register_repobrief_commands = register_legacy_repobrief_command
run_repobrief = run_ground
