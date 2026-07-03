from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable, Optional

from merger.lenskit.core.merge import ExtrasConfig, parse_human_size, scan_repo, write_reports_v2
from merger.lenskit.core.repobrief_profiles import (
    evaluate_profile,
    present_roles_from_manifest,
    profile_level,
    profile_names,
    profile_output_mode_plan,
    profile_policy,
    profile_excluded_roles,
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


def _add_manifest_artifact(bundle_manifest: Path, artifact_path: Path, role: str, content_type: str) -> None:
    data = json.loads(bundle_manifest.read_text(encoding="utf-8"))
    artifacts = data.setdefault("artifacts", [])
    if not isinstance(artifacts, list):
        artifacts = []
        data["artifacts"] = artifacts
    artifacts[:] = [a for a in artifacts if not (isinstance(a, dict) and a.get("role") == role)]
    artifacts.append({
        "path": artifact_path.name,
        "role": role,
        "content_type": content_type,
        "bytes": artifact_path.stat().st_size,
        "sha256": _sha256_file(artifact_path),
    })
    artifacts.sort(key=lambda a: (str(a.get("role", "")), str(a.get("path", ""))))
    _json_write_atomic(bundle_manifest, data)


def _export_safety_requirement(profile: str) -> str:
    return str(profile_policy(profile)["artifact_rules"].get("export_safety_report", "optional"))


def should_emit_export_safety_report(profile: str) -> bool:
    return _export_safety_requirement(profile) in {"required", "recommended"}


def emit_export_safety_report(bundle_manifest: Path | None, profile: str) -> Path | None:
    if bundle_manifest is None or not should_emit_export_safety_report(profile):
        return None
    from merger.lenskit.core.export_safety_report import build_export_safety_report_from_bundle_manifest

    report = build_export_safety_report_from_bundle_manifest(
        bundle_manifest,
        profile=profile,
        agent_facing=True if profile in {"agent-portable", "full-max", "pr-review", "ci-artifact"} else None,
        public_facing=True if profile == "public-share" else None,
    )
    out = bundle_manifest.with_name(
        bundle_manifest.name.replace(".bundle.manifest.json", ".export_safety_report.json")
    )
    _json_write_atomic(out, report)
    _add_manifest_artifact(bundle_manifest, out, "export_safety_report", "application/json")
    return out

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


def register_repobrief_commands(subparsers: argparse._SubParsersAction) -> None:
    repobrief_parser = subparsers.add_parser(
        "repobrief",
        help="RepoBrief explicit snapshot and read-access commands",
    )
    repobrief_subparsers = repobrief_parser.add_subparsers(
        dest="repobrief_cmd",
        required=True,
        help="RepoBrief command groups",
    )
    snapshot_parser = repobrief_subparsers.add_parser("snapshot", help="Brief Snapshot commands")
    snapshot_subparsers = snapshot_parser.add_subparsers(
        dest="snapshot_cmd",
        required=True,
        help="Snapshot commands",
    )
    create_parser = snapshot_subparsers.add_parser("create", help="Explicitly create a Brief Snapshot")
    create_parser.add_argument("--repo", required=True, help="Repository path to snapshot")
    create_parser.add_argument("--out", required=True, help="Output directory for Brief Bundle artifacts")
    create_parser.add_argument(
        "--profile",
        choices=sorted(profile_names()),
        default="agent-portable",
        help="RepoBrief snapshot profile label to record in the manifest",
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
    create_parser.add_argument("--redact-secrets", action="store_true")
    create_parser.add_argument("--no-include-hidden", action="store_false", dest="include_hidden")
    create_parser.set_defaults(include_hidden=True)


def run_repobrief(args: argparse.Namespace) -> int:
    if args.repobrief_cmd == "snapshot" and args.snapshot_cmd == "create":
        return run_snapshot_create(args)
    print("Unsupported RepoBrief command", file=sys.stderr)
    return 2


def run_snapshot_create(args: argparse.Namespace) -> int:
    profile = args.profile
    repo = Path(args.repo).expanduser().resolve()
    out = Path(args.out).expanduser().resolve()

    if not repo.exists() or not repo.is_dir():
        print(f"repobrief snapshot create: repo is not a directory: {repo}", file=sys.stderr)
        return 2
    if out == repo or repo in out.parents:
        print("bad output path", file=sys.stderr)
        return 2

    output_plan = profile_output_mode_plan(profile, args.output_mode)
    output_mode = output_plan["selected_output_mode"]
    conflicts = tuple(output_plan["conflicts"])
    if conflicts:
        print(
            f"repobrief snapshot create: profile {profile} excludes artifacts produced by output mode {output_mode}: "
            + ", ".join(conflicts),
            file=sys.stderr,
        )
        return 2

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
        "version": os.getenv("RLENS_VERSION", "dev"),
        "platform": "cli",
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
        redact_secrets=args.redact_secrets,
        include_hidden=args.include_hidden,
        generator_info=generator_info,
    )
    dropped_profile_paths = enforce_profile_exclusions(artifacts.bundle_manifest, profile)
    export_safety_path = emit_export_safety_report(artifacts.bundle_manifest, profile)
    refreshed_paths = refresh_entry(artifacts.bundle_manifest)
    profile_evaluation = mark_bundle_manifest_profile(artifacts.bundle_manifest, profile, output_plan)
    artifact_paths = [path for path in artifacts.get_all_paths() if path not in dropped_profile_paths]
    if export_safety_path is not None and export_safety_path not in artifact_paths:
        artifact_paths.append(export_safety_path)

    result = {
        "status": "ok",
        "command": "repobrief snapshot create",
        "profile": profile,
        "output_mode": output_mode,
        "output_plan": output_plan,
        "repo": str(repo),
        "out": str(out),
        "bundle_manifest": str(artifacts.bundle_manifest) if artifacts.bundle_manifest else None,
        "profile_evaluation": profile_evaluation,
        "export_safety_report": str(export_safety_path) if export_safety_path else None,
        "refreshed_agent_entrypoints": [str(path) for path in refreshed_paths],
        "removed_profile_excluded_artifacts": [str(path) for path in dropped_profile_paths],
        "artifacts": [str(path) for path in artifact_paths],
        "mutation_boundary": {
            "writes": ["brief_bundle_artifacts"],
            "does_not_mutate": ["git", "pull_requests", "patches", "source_working_tree"],
            "read_paths_do_not_refresh": True,
        },
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


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
    base = "merger.lenskit.core."
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
