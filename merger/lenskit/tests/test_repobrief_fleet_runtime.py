from __future__ import annotations

import hashlib
import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest


ROOT = Path(__file__).resolve().parents[3]
PUBLISHER = ROOT / "scripts/ops/rb-publish-fleet"
INSTALLER = ROOT / "scripts/ops/install_rb_publish_fleet_runtime.sh"
SYSTEMKATALOG_INSTALLER = ROOT / "scripts/ops/install_systemkatalog_publish_runtime.sh"
SYSTEMKATALOG_PUBLISH = ROOT / "scripts/ops/repobrief-publish-systemkatalog-main"
SYSTEMKATALOG_WATCH = (
    ROOT / "scripts/ops/repobrief-publish-systemkatalog-main-if-changed"
)
UNIT_DIR = ROOT / "ops/systemd/repobrief-fleet"


def load_publisher() -> ModuleType:
    module_name = "rb_publish_fleet_test"
    loader = importlib.machinery.SourceFileLoader(module_name, str(PUBLISHER))
    spec = importlib.util.spec_from_loader(module_name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    loader.exec_module(module)
    return module


def git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(
            f"git command failed rc={completed.returncode}: {args!r}\n{completed.stdout}"
        )
    return completed.stdout.strip()


def initialize_repository(tmp_path: Path, name: str = "repo") -> tuple[Path, str]:
    repo = tmp_path / name
    repo.mkdir()
    completed = subprocess.run(
        ["git", "-C", str(repo), "init", "--initial-branch=main"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if completed.returncode != 0:
        git(repo, "init")
        git(repo, "checkout", "-b", "main")
    git(repo, "config", "user.name", "RepoBrief Test")
    git(repo, "config", "user.email", "repobrief-test@example.invalid")
    (repo / ".gitignore").write_text("ignored.txt\n__pycache__/\n", encoding="utf-8")
    (repo / "tracked.txt").write_text("clean\n", encoding="utf-8")
    git(repo, "add", ".gitignore", "tracked.txt")
    git(repo, "commit", "-m", "initial")
    return repo, git(repo, "rev-parse", "HEAD")


def write_version(
    group: Path, name: str, payload: bytes, mtime: int
) -> tuple[Path, str]:
    version = group / name
    version.mkdir(parents=True)
    manifest = version / "repo_merge.bundle.manifest.json"
    manifest.write_bytes(payload)
    artifact = version / "repo_merge.md"
    artifact.write_bytes(payload * 2)
    os.utime(version, (mtime, mtime))
    digest = hashlib.sha256(payload).hexdigest()
    return version, digest


def test_fingerprint_is_stable_and_covers_all_output_inputs() -> None:
    module = load_publisher()
    config = module.PublicationConfig(profile="full-max")
    first, identity = module.build_fingerprint(
        source_sha="a" * 40,
        tool_tree_sha="b" * 40,
        publication_repository="heimgewebe__demo",
        config=config,
    )
    repeated, repeated_identity = module.build_fingerprint(
        source_sha="a" * 40,
        tool_tree_sha="b" * 40,
        publication_repository="heimgewebe__demo",
        config=config,
    )
    source_changed, _ = module.build_fingerprint(
        source_sha="c" * 40,
        tool_tree_sha="b" * 40,
        publication_repository="heimgewebe__demo",
        config=config,
    )
    tool_changed, _ = module.build_fingerprint(
        source_sha="a" * 40,
        tool_tree_sha="d" * 40,
        publication_repository="heimgewebe__demo",
        config=config,
    )
    config_changed, _ = module.build_fingerprint(
        source_sha="a" * 40,
        tool_tree_sha="b" * 40,
        publication_repository="heimgewebe__demo",
        config=module.PublicationConfig(profile="agent-portable"),
    )

    assert first == repeated
    assert identity == repeated_identity
    assert len(first) == 64
    namespace_changed, _ = module.build_fingerprint(
        source_sha="a" * 40,
        tool_tree_sha="b" * 40,
        publication_repository="other__demo",
        config=config,
    )

    assert len({first, source_changed, tool_changed, config_changed, namespace_changed}) == 5


def test_version_dirs_accepts_old_and_fingerprinted_names_only(tmp_path: Path) -> None:
    module = load_publisher()
    group = tmp_path / "group"
    old = group / "20260714T100000Z"
    new = group / "20260714T110000Z-abcdef123456"
    ignored = group / "scratch"
    old.mkdir(parents=True)
    new.mkdir()
    ignored.mkdir()
    (group / "20260714T120000Z-deadbeef0000").symlink_to(new, target_is_directory=True)
    os.utime(old, (100, 100))
    os.utime(new, (200, 200))

    assert module.version_dirs(group) == [new, old]


def test_prune_group_is_dry_run_by_default_and_reports_bytes(tmp_path: Path) -> None:
    module = load_publisher()
    group = tmp_path / "group"
    versions = [
        write_version(group, f"20260714T10000{index}Z", bytes([index + 1]), index)[0]
        for index in range(5)
    ]

    report = module.prune_group(group, keep=3, apply=False, protected=set())

    assert len(report["would_remove"]) == 2
    assert report["would_remove_bytes"] > 0
    assert report["removed"] == []
    assert all(path.exists() for path in versions)


def test_prune_group_keeps_newest_three_and_protected_older_version(
    tmp_path: Path,
) -> None:
    module = load_publisher()
    group = tmp_path / "group"
    versions = [
        write_version(group, f"20260714T10000{index}Z", bytes([index + 1]), index)[0]
        for index in range(6)
    ]
    protected_file = versions[1] / "repo_merge.md"

    report = module.prune_group(
        group,
        keep=3,
        apply=True,
        protected={protected_file.resolve()},
    )

    assert set(module.version_dirs(group)) == {
        versions[5],
        versions[4],
        versions[3],
        versions[1],
    }
    assert str(versions[1]) in report["protected_old"]
    assert report["removed_bytes"] > 0


def test_current_prune_keeps_localized_hashes_for_history_protection_and_stable_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    publication_root = tmp_path / "publication"
    monkeypatch.setattr(module, "PUB_ROOT", publication_root)
    group = publication_root / "bundles" / "heimgewebe__demo" / "main"
    versions_and_hashes = [
        write_version(
            group,
            f"20260714T10000{index}Z",
            f"manifest-{index}".encode(),
            index,
        )
        for index in range(5)
    ]
    protected_version, protected_hash = versions_and_hashes[0]
    stable_version, stable_hash = versions_and_hashes[1]
    stable_target = stable_version / "repo_merge.bundle.manifest.json"
    newest_hashes = {digest for _, digest in versions_and_hashes[-3:]}
    stable_manifest = (
        publication_root / "external" / "repobrief" / "heimgewebe__demo" / "main" / "manifest.json"
    )
    stable_manifest.parent.mkdir(parents=True)
    stable_manifest.write_text(
        json.dumps(
            {
                "bundleManifest": {
                    "path": os.path.relpath(stable_target, stable_manifest.parent)
                }
            }
        ),
        encoding="utf-8",
    )
    localized = publication_root / "external" / "_bundles" / "heimgewebe__demo" / "main"
    unused_hash = "e" * 64
    for digest in newest_hashes | {protected_hash, stable_hash, unused_hash}:
        candidate = localized / digest
        candidate.mkdir(parents=True)
        (candidate / "artifact").write_text(digest, encoding="utf-8")

    report = module.prune_current_group(
        group,
        repository="heimgewebe__demo",
        ref="main",
        keep=3,
        apply=True,
        protected={(protected_version / "repo_merge.md").resolve()},
    )

    assert protected_version.is_dir()
    assert stable_version.is_dir()
    assert (localized / protected_hash).is_dir()
    assert (localized / stable_hash).is_dir()
    assert all((localized / digest).is_dir() for digest in newest_hashes)
    assert str(stable_target) in report["stable_manifest_targets"]
    assert not (localized / unused_hash).exists()
    assert str(localized / unused_hash) in report["localized_removed"]


def test_stable_manifest_target_is_fail_closed_for_missing_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    publication_root = tmp_path / "publication"
    monkeypatch.setattr(module, "PUB_ROOT", publication_root)
    manifest = (
        publication_root / "external" / "repobrief" / "heimgewebe__demo" / "main" / "manifest.json"
    )
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps({"bundleManifest": {"path": "../../../../missing.json"}}),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="target is unavailable"):
        module.stable_manifest_target(manifest)


def test_managed_worktree_accepts_only_clean_detached_expected_repository(
    tmp_path: Path,
) -> None:
    module = load_publisher()
    repo, sha = initialize_repository(tmp_path)
    worktree = tmp_path / "managed"
    git(repo, "worktree", "add", "--detach", str(worktree), sha)

    module.assert_managed_worktree_clean(worktree, repo)
    module.prepare_managed_worktree(worktree, expected_repo=repo, target=sha)

    assert git(worktree, "rev-parse", "HEAD") == sha
    detached = subprocess.run(
        ["git", "-C", str(worktree), "symbolic-ref", "--quiet", "HEAD"],
        check=False,
    )
    assert detached.returncode != 0


def test_managed_worktree_refuses_dirty_untracked_and_ignored_content(
    tmp_path: Path,
) -> None:
    module = load_publisher()
    repo, sha = initialize_repository(tmp_path)
    worktree = tmp_path / "managed"
    git(repo, "worktree", "add", "--detach", str(worktree), sha)
    tracked = worktree / "tracked.txt"
    tracked.write_text("foreign change\n", encoding="utf-8")
    untracked = worktree / "untracked.txt"
    untracked.write_text("preserve me\n", encoding="utf-8")
    ignored = worktree / "ignored.txt"
    ignored.write_text("preserve me too\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="not clean; refusing reset or cleanup"):
        module.prepare_managed_worktree(worktree, expected_repo=repo, target=sha)

    assert tracked.read_text(encoding="utf-8") == "foreign change\n"
    assert untracked.read_text(encoding="utf-8") == "preserve me\n"
    assert ignored.read_text(encoding="utf-8") == "preserve me too\n"


def test_managed_worktree_refuses_attached_foreign_or_non_worktree_paths(
    tmp_path: Path,
) -> None:
    module = load_publisher()
    repo, sha = initialize_repository(tmp_path, "repo-a")
    attached = tmp_path / "attached"
    git(repo, "worktree", "add", "-b", "managed-branch", str(attached), sha)
    with pytest.raises(RuntimeError, match="attached to a branch"):
        module.assert_managed_worktree_clean(attached, repo)

    foreign_repo, foreign_sha = initialize_repository(tmp_path, "repo-b")
    foreign = tmp_path / "foreign"
    git(foreign_repo, "worktree", "add", "--detach", str(foreign), foreign_sha)
    with pytest.raises(RuntimeError, match="belongs to another repository"):
        module.assert_managed_worktree_clean(foreign, repo)

    ordinary = tmp_path / "ordinary"
    ordinary.mkdir()
    sentinel = ordinary / "sentinel.txt"
    sentinel.write_text("must survive\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="not the expected worktree root"):
        module.prepare_managed_worktree(ordinary, expected_repo=repo, target=sha)
    assert sentinel.read_text(encoding="utf-8") == "must survive\n"


def test_remove_tree_is_confined_to_managed_root_and_rejects_symlinks(
    tmp_path: Path,
) -> None:
    module = load_publisher()
    root = tmp_path / "root"
    removable = root / "group" / "version"
    removable.mkdir(parents=True)
    (removable / "artifact").write_text("data", encoding="utf-8")
    module.remove_tree(removable, apply=True, root=root)
    assert not removable.exists()

    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(RuntimeError, match="outside managed root"):
        module.remove_tree(outside, apply=True, root=root)
    assert outside.is_dir()

    symlink_target = tmp_path / "symlink-target"
    symlink_target.mkdir()
    link = root / "link"
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(symlink_target, target_is_directory=True)
    with pytest.raises(RuntimeError, match="non-directory or symlink"):
        module.remove_tree(link, apply=True, root=root)
    assert symlink_target.is_dir()


def test_retention_bounds_are_fail_closed() -> None:
    module = load_publisher()
    assert module.validate_retention(1) == 1
    assert module.validate_retention(3) == 3
    assert module.validate_retention(10) == 10
    with pytest.raises(ValueError):
        module.validate_retention(0)
    with pytest.raises(ValueError):
        module.validate_retention(11)


def test_unscoped_force_is_rejected_before_repository_discovery() -> None:
    completed = subprocess.run(
        [sys.executable, str(PUBLISHER), "--force"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert completed.returncode == 2
    assert "--force is disabled" in completed.stderr


def test_targeted_force_requires_repo_and_reason() -> None:
    completed = subprocess.run(
        [sys.executable, str(PUBLISHER), "--force-republish"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert completed.returncode == 2
    assert "requires at least one --repo and a non-empty --reason" in completed.stderr


def test_runtime_has_one_hourly_changed_only_timer_and_no_force_fallback() -> None:
    service = (UNIT_DIR / "rb-publish-fleet-watch.service").read_text(encoding="utf-8")
    timer = (UNIT_DIR / "rb-publish-fleet-watch.timer").read_text(encoding="utf-8")

    assert "--if-changed" in service
    assert "--retention 3" in service
    assert "--force" not in service
    assert "OnUnitActiveSec=1h" in timer
    assert "RandomizedDelaySec=10min" in timer
    assert sorted(path.name for path in UNIT_DIR.iterdir()) == [
        "rb-publish-fleet-watch.service",
        "rb-publish-fleet-watch.timer",
    ]


def test_installer_defaults_to_paused_and_removes_duplicate_generators() -> None:
    text = INSTALLER.read_text(encoding="utf-8")

    assert "ENABLE=0" in text
    assert 'if [[ ${1:-} == "--enable" ]]' in text
    assert "rb-publish-fleet-daily.timer" in text
    assert "repobrief-publish-systemkatalog-main-watch.timer" in text
    assert "systemkatalog-repobrief-localize.path" in text
    assert "disable --now" in text
    assert "INSTALL-RB-PUBLISH-FLEET-RUNTIME: PASS paused" in text


def test_systemkatalog_entrypoints_delegate_to_bounded_fleet_runtime() -> None:
    for path in (SYSTEMKATALOG_PUBLISH, SYSTEMKATALOG_WATCH):
        text = path.read_text(encoding="utf-8")
        assert "/home/alex/.local/bin/rb-publish-fleet" in text
        assert "--if-changed" in text
        assert "--retention 3" in text
        assert "--repo heimgewebe/systemkatalog" in text
        assert "--force" not in text

    compatibility = SYSTEMKATALOG_INSTALLER.read_text(encoding="utf-8")
    assert "install_rb_publish_fleet_runtime.sh" in compatibility
    assert "systemkatalog-publish" not in compatibility


def test_special_history_pruning_keeps_referenced_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    special_root = tmp_path / "repobrief-auto"
    monkeypatch.setattr(module, "SPECIAL_OUT_ROOT", special_root)
    group = special_root / "systemkatalog-main"
    versions = [
        write_version(group, f"20260714T10000{index}Z", bytes([index + 1]), index)[0]
        for index in range(6)
    ]

    reports = module.prune_all_special(
        keep=3,
        apply=True,
        protected={(versions[1] / "repo_merge.md").resolve()},
    )

    assert len(reports) == 1
    assert set(module.version_dirs(group)) == {
        versions[5],
        versions[4],
        versions[3],
        versions[1],
    }
    assert str(versions[1]) in reports[0]["protected_old"]


def test_state_identity_does_not_trust_legacy_source_only_marker(
    tmp_path: Path,
) -> None:
    module = load_publisher()
    module.STATE_ROOT = tmp_path
    entry = module.RepoEntry(
        key="heimgewebe/demo",
        owner="heimgewebe",
        repo="demo",
        path=tmp_path / "demo",
        remote="git@github.com:heimgewebe/demo.git",
    )

    path = module.state_path(entry, "main")

    assert path == tmp_path / "heimgewebe__demo__main.state.json"
    assert not path.name.endswith(".last-sha")
