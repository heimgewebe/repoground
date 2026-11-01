"""Freeze exactly one source-revision-bound study cohort before publication GC.

No generator, publisher, production checkout, or prior measurement is changed.
The existing Codex adapter's private pinning code keeps all manifest roles,
including nested relative artifacts, and copies across device boundaries.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from merger.repoground.core import agent_study as study
from tools.agent_study_codex_runner import (
    _assert_pinned_manifests,
    _pin_bundle_manifest,
)


def freeze(taskset: dict, snapshots: dict, archive_root: Path) -> dict:
    study.taskset_valid(taskset)
    study._check_snapshots(taskset, snapshots)
    archive_root = archive_root.expanduser().absolute()
    if archive_root.is_symlink() or archive_root.exists():
        raise study.AgentBenchmarkError("study archive must be a new directory")
    if archive_root.parent.is_symlink() or not archive_root.parent.is_dir():
        raise study.AgentBenchmarkError("archive parent must be an existing ordinary directory")
    # The new archive must be private and independent of publisher retention.
    archive_root.mkdir(mode=0o700, exist_ok=False)
    frozen = {}
    pinned = {}
    for name, bound in sorted(snapshots.items()):
        if name not in taskset["repositories"]:
            raise study.AgentBenchmarkError("unknown study archive repository")
        manifest = _pin_bundle_manifest(bound, archive_root / name)
        pinned[name] = manifest
        frozen[name] = {**bound, "manifest_path": str(manifest)}
    _assert_pinned_manifests({"repoground": snapshots}, pinned)
    study._check_snapshots(taskset, frozen)
    # Re-read each original manifest and the archived bytes: we do not
    # silently label a rotated or tampered publication as immutable.
    for name, bound in snapshots.items():
        if not Path(bound["manifest_path"]).is_file():
            raise study.AgentBenchmarkError("publisher removed source while freezing")
        from hashlib import sha256
        if sha256(Path(bound["manifest_path"]).read_bytes()).hexdigest() != bound["manifest_sha256"]:
            raise study.AgentBenchmarkError("source manifest drift during freeze")
    payload = {
        "kind": "repoground.agent_study_frozen_snapshots",
        "version": 1,
        "taskset_sha256": study.sha256_json(taskset),
        "snapshots": frozen,
        "retention": "independent_private_source_bound_hardlinks",
        "does_not_establish": ["agent_quality", "future_source_immutability_against_same_uid_writes"],
    }
    result = archive_root / "frozen-index.json"
    with result.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")
    # A standard snapshots.json is directly consumable by the existing planner.
    with (archive_root / "snapshots.json").open("x", encoding="utf-8") as handle:
        json.dump(frozen, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")
    return payload


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Pin study manifests and their roles outside publisher GC")
    p.add_argument("--taskset", required=True)
    p.add_argument("--snapshots", required=True)
    p.add_argument("--out", required=True, help="New private archive root, never a publisher path")
    args = p.parse_args(argv)
    try:
        value = freeze(
            study.load_json(args.taskset), study.load_json(args.snapshots),
            Path(args.out),
        )
        print(json.dumps({
            "status": "frozen", "repos": len(value["snapshots"]),
            "snapshots": str(Path(args.out) / "snapshots.json"),
            "taskset_sha256": value["taskset_sha256"],
        }, sort_keys=True))
        return 0
    except (OSError, ValueError, study.AgentBenchmarkError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)[:350]}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())