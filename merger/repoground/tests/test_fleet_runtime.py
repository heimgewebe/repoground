from __future__ import annotations

import hashlib
import importlib.machinery
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest


ROOT = Path(__file__).resolve().parents[3]
PUBLISHER = ROOT / "scripts/ops/repoground-publish-fleet"
LEGACY_PUBLISHER = ROOT / "scripts/ops/rb-publish-fleet"
INSTALLER = ROOT / "scripts/ops/install_repoground_publish_fleet_runtime.sh"
LEGACY_INSTALLER = ROOT / "scripts/ops/install_rb_publish_fleet_runtime.sh"
SYSTEMKATALOG_INSTALLER = ROOT / "scripts/ops/install_systemkatalog_publish_runtime.sh"
SYSTEMKATALOG_PUBLISH = ROOT / "scripts/ops/repoground-publish-systemkatalog-main"
SYSTEMKATALOG_WATCH = (
    ROOT / "scripts/ops/repoground-publish-systemkatalog-main-if-changed"
)
LEGACY_SYSTEMKATALOG_PUBLISH = ROOT / "scripts/ops/repobrief-publish-systemkatalog-main"
LEGACY_SYSTEMKATALOG_WATCH = (
    ROOT / "scripts/ops/repobrief-publish-systemkatalog-main-if-changed"
)
UNIT_DIR = ROOT / "ops/systemd/repoground-fleet"


def load_publisher() -> ModuleType:
    module_name = "repoground_publish_fleet_test"
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


def write_historical_generation_symlink(
    candidate: Path,
    *,
    bundled: bool = False,
    target_hash: str = "a" * 64,
) -> tuple[Path, Path]:
    bundle_root = candidate / "bundle" if bundled else candidate
    generation = bundle_root / ".repobrief-generations" / "legacy-scope"
    target = generation / target_hash
    target.mkdir(parents=True)
    (target / "payload.txt").write_text("historical payload", encoding="utf-8")
    current = generation / "current"
    current.symlink_to(target_hash, target_is_directory=True)
    return current, target


def isolate_retention_roots(
    module: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> dict[str, Path]:
    roots = {
        "publication": tmp_path / "publication",
        "legacy": tmp_path / "legacy",
        "special": tmp_path / "special",
        "state": tmp_path / "state",
        "log": tmp_path / "log",
    }
    monkeypatch.setattr(module, "PUB_ROOT", roots["publication"])
    monkeypatch.setattr(module, "ARCHIVED_LEGACY_OUT_ROOT", roots["legacy"])
    monkeypatch.setattr(module, "ARCHIVED_SPECIAL_OUT_ROOT", roots["special"])
    monkeypatch.setattr(module, "STATE_ROOT", roots["state"])
    monkeypatch.setattr(module, "LOG_ROOT", roots["log"])
    return roots


def test_publisher_uses_only_canonical_active_environment_and_storage() -> None:
    text = PUBLISHER.read_text(encoding="utf-8")
    former_env_prefix = "R" + "B_"
    former_state = "/home/alex/.local/state/" + "repobrief-publish/fleet"
    former_log = "/home/alex/logs/" + "repobrief-publish"
    former_quarantine = "." + "rb-prune-quarantine"

    assert former_env_prefix not in text
    assert former_state not in text
    assert former_log not in text
    assert former_quarantine not in text
    assert "/home/alex/.local/state/repoground-publish/fleet" in text
    assert "/home/alex/logs/repoground-publish" in text
    assert ".repoground-prune-quarantine" in text
    assert "ARCHIVED_LEGACY_OUT_ROOT" in text
    assert "ARCHIVED_SPECIAL_OUT_ROOT" in text


def test_fingerprint_is_stable_and_covers_all_output_inputs() -> None:
    module = load_publisher()
    config = module.PublicationConfig(profile="full-max")
    first, identity = module.build_fingerprint(
        source_sha="a" * 40,
        generator_inputs_sha="b" * 40,
        publication_repository="heimgewebe__demo",
        config=config,
    )
    repeated, repeated_identity = module.build_fingerprint(
        source_sha="a" * 40,
        generator_inputs_sha="b" * 40,
        publication_repository="heimgewebe__demo",
        config=config,
    )
    source_changed, _ = module.build_fingerprint(
        source_sha="c" * 40,
        generator_inputs_sha="b" * 40,
        publication_repository="heimgewebe__demo",
        config=config,
    )
    tool_changed, _ = module.build_fingerprint(
        source_sha="a" * 40,
        generator_inputs_sha="d" * 40,
        publication_repository="heimgewebe__demo",
        config=config,
    )
    config_changed, _ = module.build_fingerprint(
        source_sha="a" * 40,
        generator_inputs_sha="b" * 40,
        publication_repository="heimgewebe__demo",
        config=module.PublicationConfig(profile="agent-portable"),
    )

    assert first == repeated
    assert identity == repeated_identity
    assert len(first) == 64
    namespace_changed, _ = module.build_fingerprint(
        source_sha="a" * 40,
        generator_inputs_sha="b" * 40,
        publication_repository="other__demo",
        config=config,
    )

    assert (
        len({first, source_changed, tool_changed, config_changed, namespace_changed})
        == 5
    )


def test_generator_inputs_sha_ignores_service_and_test_only_changes(
    tmp_path: Path,
) -> None:
    module = load_publisher()
    repo, _ = initialize_repository(tmp_path, "lenskit")
    tracked = {
        "merger/repoground/__init__.py": "",
        "merger/repoground/cli/__init__.py": "",
        "merger/repoground/cli/ground.py": "entrypoint\n",
        "merger/repoground/cli/cmd_ground.py": "command\n",
        "merger/repoground/core/merge.py": "generator v1\n",
        "merger/repoground/contracts/bundle.json": "{}\n",
        "merger/repoground/retrieval/query.py": "query v1\n",
        "merger/repoground/service/app.py": "service v1\n",
        "merger/repoground/tests/test_only.py": "test v1\n",
    }
    for relative, content in tracked.items():
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "generator baseline")
    baseline = module.generator_inputs_sha(repo)

    (repo / "merger/repoground/service/app.py").write_text(
        "service v2\n", encoding="utf-8"
    )
    (repo / "merger/repoground/tests/test_only.py").write_text(
        "test v2\n", encoding="utf-8"
    )
    git(repo, "add", ".")
    git(repo, "commit", "-m", "non-generator changes")
    assert module.generator_inputs_sha(repo) == baseline

    (repo / "merger/repoground/core/merge.py").write_text(
        "generator v2\n", encoding="utf-8"
    )
    git(repo, "add", ".")
    git(repo, "commit", "-m", "generator change")
    assert module.generator_inputs_sha(repo) != baseline


def test_version_dirs_accepts_only_declared_version_names(tmp_path: Path) -> None:
    module = load_publisher()
    group = tmp_path / "group"
    old = group / "20260714T100000Z"
    new = group / "20260714T110000Z-abcdef123456"
    old.mkdir(parents=True)
    new.mkdir()
    os.utime(old, (100, 100))
    os.utime(new, (200, 200))

    assert module.version_dirs(group) == [new, old]

    (group / "scratch").mkdir()
    with pytest.raises(RuntimeError, match="unexpected retention entries"):
        module.version_dirs(group)


def test_prune_group_is_dry_run_by_default_and_reports_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    roots = isolate_retention_roots(module, tmp_path, monkeypatch)
    group = roots["publication"] / "bundles" / "demo" / "main"
    versions = [
        write_version(group, f"20260714T10000{index}Z", bytes([index + 1]), index)[0]
        for index in range(5)
    ]

    report = module.prune_group(group, keep=3, apply=False, protected=set())

    assert len(report["would_remove"]) == 2
    assert report["would_remove_bytes"] > 0
    assert report["removed"] == []
    assert all(path.exists() for path in versions)
    assert not module.prune_transaction_root().exists()


def test_prune_group_keeps_newest_three_and_protected_older_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    roots = isolate_retention_roots(module, tmp_path, monkeypatch)
    group = roots["publication"] / "bundles" / "demo" / "main"
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
    transactions = sorted(module.prune_transaction_root().glob("*.json"))
    assert len(transactions) == 2
    assert all(
        json.loads(path.read_text())["state"] == "deleted" for path in transactions
    )


def test_current_prune_keeps_localized_hashes_for_history_protection_and_stable_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    roots = isolate_retention_roots(module, tmp_path, monkeypatch)
    publication_root = roots["publication"]
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
        publication_root
        / "external"
        / "repobrief"
        / "heimgewebe__demo"
        / "main"
        / "manifest.json"
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
        publication_root
        / "external"
        / "repobrief"
        / "heimgewebe__demo"
        / "main"
        / "manifest.json"
    )
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps({"bundleManifest": {"path": "../../../../missing.json"}}),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="target is unavailable"):
        module.stable_manifest_target(manifest)


def test_global_reachability_uses_only_canonical_owner_qualified_manifests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    publication_root = tmp_path / "publication"
    monkeypatch.setattr(module, "PUB_ROOT", publication_root)

    canonical_target = (
        publication_root
        / "bundles"
        / "heimgewebe__demo"
        / "main"
        / "version"
        / "manifest.json"
    )
    canonical_target.parent.mkdir(parents=True)
    canonical_target.write_text("{}", encoding="utf-8")
    canonical_manifest = (
        publication_root
        / "external"
        / "repobrief"
        / "heimgewebe__demo"
        / "main"
        / "manifest.json"
    )
    canonical_manifest.parent.mkdir(parents=True)
    canonical_manifest.write_text(
        json.dumps(
            {
                "bundleManifest": {
                    "path": os.path.relpath(canonical_target, canonical_manifest.parent)
                }
            }
        ),
        encoding="utf-8",
    )

    frozen_manifest = (
        publication_root / "external" / "repobrief" / "demo" / "main" / "manifest.json"
    )
    frozen_manifest.parent.mkdir(parents=True)
    frozen_manifest.write_text(
        json.dumps({"bundleManifest": {"path": "../../../../missing.json"}}),
        encoding="utf-8",
    )

    assert module.canonical_stable_manifest_paths() == [canonical_manifest]
    assert module.all_stable_manifest_targets() == {canonical_target.resolve()}


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
    service = (UNIT_DIR / "repoground-publish-fleet-watch.service").read_text(
        encoding="utf-8"
    )
    timer = (UNIT_DIR / "repoground-publish-fleet-watch.timer").read_text(
        encoding="utf-8"
    )

    assert "ExecStart=/home/alex/.local/bin/repoground-publish-fleet" in service
    assert "RepoGround fleet bundles" in service
    assert "--if-changed" in service
    assert "--retention 3" in service
    assert "--force" not in service
    assert "OnCalendar=hourly" in timer
    assert "OnBootSec=" not in timer
    assert "OnUnitActiveSec=" not in timer
    assert "RandomizedDelaySec=10min" in timer
    assert "Persistent=true" in timer
    assert sorted(path.name for path in UNIT_DIR.iterdir()) == [
        "repoground-publish-fleet-watch.service",
        "repoground-publish-fleet-watch.timer",
    ]


def _run_installer(tmp_path: Path) -> subprocess.CompletedProcess[str]:
    home = tmp_path / "home"
    fake_bin = tmp_path / "bin"
    home.mkdir(exist_ok=True)
    fake_bin.mkdir(exist_ok=True)
    systemctl = fake_bin / "systemctl"
    systemctl.write_text(
        "#!/bin/sh\nprintf '%s\n' \"$*\" >> \"$HOME/systemctl.log\"\n",
        encoding="utf-8",
    )
    systemctl.chmod(0o755)
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PATH"] = str(fake_bin) + os.pathsep + env["PATH"]
    return subprocess.run(
        [str(INSTALLER)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        check=False,
    )


def test_installer_atomically_migrates_state_and_starts_canonical_logs(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    old_state = home / ".local/state/repobrief-publish/fleet"
    old_log = home / "logs/repobrief-publish"
    old_state.mkdir(parents=True)
    old_log.mkdir(parents=True)
    (old_state / "marker.json").write_text("{}\n", encoding="utf-8")
    (old_log / "historical.log").write_text("old\n", encoding="utf-8")

    completed = _run_installer(tmp_path)

    new_state = home / ".local/state/repoground-publish/fleet"
    new_log = home / "logs/repoground-publish"
    assert completed.returncode == 0, completed.stderr
    assert not old_state.exists()
    assert (new_state / "marker.json").read_text(encoding="utf-8") == "{}\n"
    assert new_log.is_dir()
    assert (old_log / "historical.log").read_text(encoding="utf-8") == "old\n"
    assert (home / ".local/bin/repoground-publish-fleet").is_file()
    assert "PASS paused" in completed.stdout


def test_installer_refuses_dual_state_truth(tmp_path: Path) -> None:
    home = tmp_path / "home"
    old_state = home / ".local/state/repobrief-publish/fleet"
    new_state = home / ".local/state/repoground-publish/fleet"
    old_state.mkdir(parents=True)
    new_state.mkdir(parents=True)
    (old_state / "old").write_text("old", encoding="utf-8")
    (new_state / "new").write_text("new", encoding="utf-8")

    completed = _run_installer(tmp_path)

    assert completed.returncode == 1
    assert "refusing dual truth" in completed.stderr
    assert (old_state / "old").is_file()
    assert (new_state / "new").is_file()


def test_installer_defaults_to_paused_and_removes_duplicate_generators() -> None:
    text = INSTALLER.read_text(encoding="utf-8")

    assert "ENABLE=0" in text
    assert 'if [[ ${1:-} == "--enable" ]]' in text
    assert "rb-publish-fleet-daily.timer" in text
    assert "repobrief-publish-systemkatalog-main-watch.timer" in text
    assert "systemkatalog-repobrief-localize.path" in text
    assert "disable --now" in text
    assert "INSTALL-REPOGROUND-PUBLISH-FLEET-RUNTIME: PASS paused" in text


def test_systemkatalog_entrypoints_delegate_to_bounded_fleet_runtime() -> None:
    publish = SYSTEMKATALOG_PUBLISH.read_text(encoding="utf-8")
    assert "/home/alex/.local/bin/repoground-publish-fleet" in publish
    assert "--if-changed" in publish
    assert "--retention 3" in publish
    assert "--repo heimgewebe/systemkatalog" in publish
    assert "--force" not in publish

    watch = SYSTEMKATALOG_WATCH.read_text(encoding="utf-8")
    assert "is a compatibility alias" in watch
    assert 'exec "$(dirname "$0")/repoground-publish-systemkatalog-main"' in watch
    assert "repoground-publish-fleet" not in watch
    assert "--repo" not in watch

    assert not LEGACY_SYSTEMKATALOG_PUBLISH.exists()
    assert not LEGACY_SYSTEMKATALOG_WATCH.exists()

    compatibility = SYSTEMKATALOG_INSTALLER.read_text(encoding="utf-8")
    assert "install_repoground_publish_fleet_runtime.sh" in compatibility
    assert "systemkatalog-publish" not in compatibility


def test_legacy_fleet_and_installer_entrypoints_are_removed() -> None:
    assert not LEGACY_PUBLISHER.exists()
    assert not LEGACY_INSTALLER.exists()


def test_special_history_pruning_keeps_referenced_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    roots = isolate_retention_roots(module, tmp_path, monkeypatch)
    special_root = roots["special"]
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


def test_state_and_active_publication_targets_protect_old_versions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    roots = isolate_retention_roots(module, tmp_path, monkeypatch)
    group = roots["publication"] / "bundles" / "heimgewebe__demo" / "main"
    versions = [
        write_version(group, f"20260714T10000{index}Z", bytes([index + 1]), index)[0]
        for index in range(7)
    ]
    module.atomic_write_json(
        roots["state"] / "heimgewebe__demo__main.state.json",
        {
            "schema": module.STATE_SCHEMA,
            "publication_dir": str(versions[0]),
        },
    )
    active = module.create_active_publication_lease(
        repository="heimgewebe__demo",
        ref="main",
        fingerprint="a" * 64,
        publication_dir=versions[1],
    )

    report = module.prune_group(group, keep=3, apply=True, protected=set())

    assert versions[0].is_dir()
    assert versions[1].is_dir()
    assert not versions[2].exists()
    assert {str(versions[0]), str(versions[1])}.issubset(set(report["protected_old"]))
    module.clear_active_publication_lease(active)


def test_transaction_rechecks_protection_after_quarantine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    roots = isolate_retention_roots(module, tmp_path, monkeypatch)
    group = roots["publication"] / "bundles" / "demo" / "main"
    candidate, _ = write_version(group, "20260714T100000Z", b"payload", 1)
    snapshot = module.tree_snapshot(candidate)
    calls = 0

    def changing_protection(explicit: set[Path]) -> set[Path]:
        nonlocal calls
        calls += 1
        return {candidate.resolve()} if calls >= 3 else set(explicit)

    monkeypatch.setattr(module, "dynamic_protected_paths", changing_protection)
    result = module.transactional_prune(
        candidate,
        root=group,
        expected_snapshot=snapshot,
        removed_bytes=module.tree_bytes(candidate),
        protected=set(),
    )

    assert result["state"] == "retained_newly_protected"
    assert candidate.is_dir()
    transaction = next(module.prune_transaction_root().glob("*.json"))
    assert json.loads(transaction.read_text())["state"] == "restored_newly_protected"


def test_transaction_refuses_candidate_changed_after_planning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    roots = isolate_retention_roots(module, tmp_path, monkeypatch)
    group = roots["publication"] / "bundles" / "demo" / "main"
    candidate, _ = write_version(group, "20260714T100000Z", b"payload", 1)
    snapshot = module.tree_snapshot(candidate)
    (candidate / "repo_merge.md").write_text("changed", encoding="utf-8")

    with pytest.raises(RuntimeError, match="changed after planning"):
        module.transactional_prune(
            candidate,
            root=group,
            expected_snapshot=snapshot,
            removed_bytes=1,
            protected=set(),
        )

    assert candidate.is_dir()
    assert not module.prune_transaction_root().exists()


def test_transactional_delete_is_journaled_and_confined(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    roots = isolate_retention_roots(module, tmp_path, monkeypatch)
    group = roots["publication"] / "bundles" / "demo" / "main"
    candidate, _ = write_version(group, "20260714T100000Z", b"payload", 1)
    snapshot = module.tree_snapshot(candidate)

    result = module.transactional_prune(
        candidate,
        root=group,
        expected_snapshot=snapshot,
        removed_bytes=module.tree_bytes(candidate),
        protected=set(),
    )

    assert result["state"] == "deleted"
    assert not candidate.exists()
    transaction = next(module.prune_transaction_root().glob("*.json"))
    payload = json.loads(transaction.read_text())
    assert payload["state"] == "deleted"
    assert payload["source"] == str(candidate.resolve(strict=False))
    quarantine_path = Path(payload["quarantine"])
    assert quarantine_path.parent.parent.name == module.QUARANTINE_DIR_NAME
    assert module.PERSISTED_V1_QUARANTINE_DIR_NAME not in quarantine_path.parts

    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(RuntimeError, match="escapes managed roots"):
        module.transactional_prune(
            outside,
            root=outside.parent,
            expected_snapshot=module.tree_snapshot(outside),
            removed_bytes=0,
            protected=set(),
        )


def test_reconciliation_accepts_terminal_persisted_v1_quarantine_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    roots = isolate_retention_roots(module, tmp_path, monkeypatch)
    group = roots["publication"] / "bundles" / "demo" / "main"
    group.mkdir(parents=True)
    source = group / "20260714T100000Z"
    transaction_id = "a" * 32
    quarantine = (
        group
        / module.PERSISTED_V1_QUARANTINE_DIR_NAME
        / transaction_id
        / source.name
    )
    transaction = module.prune_transaction_root() / f"{transaction_id}.json"
    module.atomic_write_json(
        transaction,
        {
            "schema": module.PRUNE_TRANSACTION_SCHEMA,
            "transaction_id": transaction_id,
            "state": "deleted",
            "source": str(source.resolve(strict=False)),
            "quarantine": str(quarantine.resolve(strict=False)),
            "root": str(group.resolve()),
            "snapshot": {"device": 1, "inode": 2, "tree_sha256": "a" * 64},
            "removed_bytes": 1,
        },
    )

    reports = module.reconcile_prune_transactions(protected=set(), apply=True)

    assert reports == [{"transaction": str(transaction), "state": "deleted"}]
    assert json.loads(transaction.read_text(encoding="utf-8"))["quarantine"] == str(
        quarantine.resolve(strict=False)
    )


def test_reconciliation_finishes_persisted_v1_quarantine_after_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    roots = isolate_retention_roots(module, tmp_path, monkeypatch)
    group = roots["publication"] / "bundles" / "demo" / "main"
    source, _ = write_version(group, "20260714T100000Z", b"payload", 1)
    snapshot = module.tree_snapshot(source)
    removed_bytes = module.tree_bytes(source)
    transaction_id = "9" * 32
    quarantine = (
        group
        / module.PERSISTED_V1_QUARANTINE_DIR_NAME
        / transaction_id
        / source.name
    )
    quarantine.parent.mkdir(parents=True)
    os.replace(source, quarantine)
    transaction = module.prune_transaction_root() / f"{transaction_id}.json"
    module.atomic_write_json(
        transaction,
        {
            "schema": module.PRUNE_TRANSACTION_SCHEMA,
            "transaction_id": transaction_id,
            "state": "quarantined",
            "source": str(source.resolve(strict=False)),
            "quarantine": str(quarantine.resolve(strict=False)),
            "root": str(group.resolve()),
            "snapshot": snapshot,
            "removed_bytes": removed_bytes,
        },
    )

    assert module.version_dirs(group) == []
    reports = module.reconcile_prune_transactions(protected=set(), apply=True)

    assert reports[0]["applied"] == "delete"
    assert not source.exists()
    assert not quarantine.exists()
    assert not (group / module.PERSISTED_V1_QUARANTINE_DIR_NAME).exists()
    assert json.loads(transaction.read_text(encoding="utf-8"))["state"] == "deleted"


def test_reconciliation_restores_planned_move_that_became_protected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    roots = isolate_retention_roots(module, tmp_path, monkeypatch)
    group = roots["publication"] / "bundles" / "demo" / "main"
    source, _ = write_version(group, "20260714T100000Z", b"payload", 1)
    snapshot = module.tree_snapshot(source)
    transaction_id = "b" * 32
    quarantine = group / module.QUARANTINE_DIR_NAME / transaction_id / source.name
    quarantine.parent.mkdir(parents=True)
    os.replace(source, quarantine)
    module.atomic_write_json(
        module.prune_transaction_root() / f"{transaction_id}.json",
        {
            "schema": module.PRUNE_TRANSACTION_SCHEMA,
            "transaction_id": transaction_id,
            "state": "planned",
            "source": str(source.resolve(strict=False)),
            "quarantine": str(quarantine.resolve(strict=False)),
            "root": str(group.resolve()),
            "snapshot": snapshot,
            "removed_bytes": 1,
        },
    )

    reports = module.reconcile_prune_transactions(protected={source}, apply=True)

    assert reports[0]["applied"] == "restore"
    assert source.is_dir()
    assert not quarantine.exists()
    transaction = module.prune_transaction_root() / f"{transaction_id}.json"
    assert json.loads(transaction.read_text())["state"] == "restored"


def test_reconciliation_records_completed_delete_after_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    roots = isolate_retention_roots(module, tmp_path, monkeypatch)
    group = roots["publication"] / "bundles" / "demo" / "main"
    group.mkdir(parents=True)
    source = group / "20260714T100000Z"
    quarantine = group / module.QUARANTINE_DIR_NAME / ("c" * 32) / source.name
    module.atomic_write_json(
        module.prune_transaction_root() / f"{'c' * 32}.json",
        {
            "schema": module.PRUNE_TRANSACTION_SCHEMA,
            "transaction_id": "c" * 32,
            "state": "quarantined",
            "source": str(source.resolve(strict=False)),
            "quarantine": str(quarantine.resolve(strict=False)),
            "root": str(group.resolve()),
            "snapshot": {"device": 1, "inode": 2, "tree_sha256": "d" * 64},
            "removed_bytes": 1,
        },
    )

    reports = module.reconcile_prune_transactions(protected=set(), apply=True)

    assert reports[0]["applied"] == "record_deleted"
    transaction = module.prune_transaction_root() / f"{'c' * 32}.json"
    assert json.loads(transaction.read_text())["state"] == "deleted"


@pytest.mark.parametrize("bundled", [False, True])
def test_transactional_prune_accepts_only_bounded_historical_current_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bundled: bool
) -> None:
    module = load_publisher()
    roots = isolate_retention_roots(module, tmp_path, monkeypatch)
    group = roots["publication"] / "bundles" / "demo" / "main"
    candidate, _ = write_version(group, "20260714T100000Z", b"payload", 1)
    current, _ = write_historical_generation_symlink(candidate, bundled=bundled)

    snapshot = module.tree_snapshot(candidate)
    removed_bytes = module.tree_bytes(candidate)
    result = module.transactional_prune(
        candidate,
        root=group,
        expected_snapshot=snapshot,
        removed_bytes=removed_bytes,
        protected=set(),
    )

    assert result["state"] == "deleted"
    assert result["removed_bytes"] == removed_bytes
    assert not candidate.exists()
    assert not current.exists()


def test_historical_current_symlink_rejects_unsafe_targets_and_locations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    roots = isolate_retention_roots(module, tmp_path, monkeypatch)
    group = roots["publication"] / "bundles" / "demo" / "main"

    absolute, _ = write_version(group, "20260714T100001Z", b"absolute", 1)
    absolute_generation = absolute / ".repobrief-generations" / "legacy-scope"
    absolute_generation.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (absolute_generation / "current").symlink_to(
        outside, target_is_directory=True
    )

    escaping, _ = write_version(group, "20260714T100002Z", b"escaping", 2)
    escaping_generation = escaping / ".repobrief-generations" / "legacy-scope"
    escaping_generation.mkdir(parents=True)
    (escaping_generation / "current").symlink_to(
        f"../{'b' * 64}", target_is_directory=True
    )

    chained, _ = write_version(group, "20260714T100003Z", b"chained", 3)
    chained_generation = chained / ".repobrief-generations" / "legacy-scope"
    chained_generation.mkdir(parents=True)
    real_target = chained_generation / ("c" * 64 + "-real")
    real_target.mkdir()
    (chained_generation / ("c" * 64)).symlink_to(
        real_target.name, target_is_directory=True
    )
    (chained_generation / "current").symlink_to(
        "c" * 64, target_is_directory=True
    )

    misplaced, _ = write_version(group, "20260714T100004Z", b"misplaced", 4)
    misplaced_target = misplaced / ("d" * 64)
    misplaced_target.mkdir()
    (misplaced / "current").symlink_to(
        misplaced_target.name, target_is_directory=True
    )

    dangling, _ = write_version(group, "20260714T100005Z", b"dangling", 5)
    dangling_generation = dangling / ".repobrief-generations" / "legacy-scope"
    dangling_generation.mkdir(parents=True)
    (dangling_generation / "current").symlink_to(
        "e" * 64, target_is_directory=True
    )

    wrong_name, _ = write_version(group, "20260714T100006Z", b"wrong-name", 6)
    wrong_name_generation = (
        wrong_name / ".repobrief-generations" / "legacy-scope"
    )
    wrong_name_target = wrong_name_generation / ("f" * 64)
    wrong_name_target.mkdir(parents=True)
    (wrong_name_generation / "latest").symlink_to(
        wrong_name_target.name, target_is_directory=True
    )

    for candidate in (absolute, escaping, chained, misplaced, dangling, wrong_name):
        with pytest.raises(RuntimeError, match="contains .*symlink"):
            module.tree_bytes(candidate)
        with pytest.raises(RuntimeError, match="contains .*symlink"):
            module.tree_snapshot(candidate)
        assert candidate.is_dir()
    assert outside.is_dir()


def test_transaction_rejects_historical_current_target_swap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    roots = isolate_retention_roots(module, tmp_path, monkeypatch)
    group = roots["publication"] / "bundles" / "demo" / "main"
    candidate, _ = write_version(group, "20260714T100000Z", b"payload", 1)
    current, _ = write_historical_generation_symlink(candidate)
    replacement = current.parent / ("b" * 64)
    replacement.mkdir()
    (replacement / "payload.txt").write_text("replacement", encoding="utf-8")
    snapshot = module.tree_snapshot(candidate)
    removed_bytes = module.tree_bytes(candidate)

    current.unlink()
    current.symlink_to(replacement.name, target_is_directory=True)

    with pytest.raises(RuntimeError, match="changed after planning"):
        module.transactional_prune(
            candidate,
            root=group,
            expected_snapshot=snapshot,
            removed_bytes=removed_bytes,
            protected=set(),
        )

    assert candidate.is_dir()
    assert current.readlink() == Path("b" * 64)
    assert not module.prune_transaction_root().exists()


def test_transaction_rejects_substituted_historical_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    roots = isolate_retention_roots(module, tmp_path, monkeypatch)
    group = roots["publication"] / "bundles" / "demo" / "main"
    candidate, _ = write_version(group, "20260714T100000Z", b"payload", 1)
    current, _ = write_historical_generation_symlink(candidate)
    generation = current.parent
    snapshot = module.tree_snapshot(candidate)
    removed_bytes = module.tree_bytes(candidate)
    substitute = tmp_path / "substitute-generation"
    substitute.mkdir()
    substitute_target = substitute / ("a" * 64)
    substitute_target.mkdir()
    (substitute / "current").symlink_to(
        substitute_target.name, target_is_directory=True
    )

    shutil.rmtree(generation)
    generation.symlink_to(substitute, target_is_directory=True)

    with pytest.raises(RuntimeError, match="contains a symlink"):
        module.transactional_prune(
            candidate,
            root=group,
            expected_snapshot=snapshot,
            removed_bytes=removed_bytes,
            protected=set(),
        )

    assert candidate.is_dir()
    assert generation.is_symlink()
    assert substitute.is_dir()
    assert not module.prune_transaction_root().exists()


def test_retention_rejects_special_file_and_leaves_candidate_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    roots = isolate_retention_roots(module, tmp_path, monkeypatch)
    group = roots["publication"] / "bundles" / "demo" / "main"
    candidate, _ = write_version(group, "20260714T100000Z", b"payload", 1)
    fifo = candidate / "special.fifo"
    os.mkfifo(fifo)

    with pytest.raises(RuntimeError, match="non-regular file"):
        module.tree_bytes(candidate)
    with pytest.raises(RuntimeError, match="non-regular file"):
        module.tree_snapshot(candidate)

    assert candidate.is_dir()
    assert fifo.exists()
    assert not module.prune_transaction_root().exists()


def test_tree_snapshot_and_localized_groups_reject_ambiguous_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    roots = isolate_retention_roots(module, tmp_path, monkeypatch)
    group = roots["publication"] / "bundles" / "demo" / "main"
    candidate, _ = write_version(group, "20260714T100000Z", b"payload", 1)
    target = tmp_path / "target"
    target.mkdir()
    (candidate / "link").symlink_to(target, target_is_directory=True)
    with pytest.raises(RuntimeError, match="contains a symlink"):
        module.tree_snapshot(candidate)

    localized = roots["publication"] / "external" / "_bundles" / "demo" / "main"
    (localized / ("a" * 64)).mkdir(parents=True)
    (localized / "not-a-hash").mkdir()
    with pytest.raises(RuntimeError, match="unexpected localized bundle entries"):
        module.localized_hash_dirs(localized)


def test_legacy_layout_discovery_supports_both_known_shapes_and_rejects_mixing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    roots = isolate_retention_roots(module, tmp_path, monkeypatch)
    modern = roots["legacy"] / "heimgewebe__demo" / "main"
    direct = roots["legacy"] / "cabinet-main"
    write_version(modern, "20260714T100000Z", b"modern", 1)
    write_version(direct, "20260714T100000Z", b"direct", 1)

    assert module.legacy_version_groups() == [direct, modern]

    (direct / "main").mkdir()
    with pytest.raises(RuntimeError, match="mixed legacy layouts"):
        module.legacy_version_groups()


def test_reconciliation_rejects_forged_quarantine_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    roots = isolate_retention_roots(module, tmp_path, monkeypatch)
    group = roots["publication"] / "bundles" / "demo" / "main"
    forged, _ = write_version(group, "20260714T100000Z", b"forged", 1)
    transaction_id = "d" * 32
    source = group / "20260714T100001Z"
    module.atomic_write_json(
        module.prune_transaction_root() / f"{transaction_id}.json",
        {
            "schema": module.PRUNE_TRANSACTION_SCHEMA,
            "transaction_id": transaction_id,
            "state": "quarantined",
            "source": str(source.resolve(strict=False)),
            "quarantine": str(forged.resolve()),
            "root": str(group.resolve()),
            "snapshot": module.tree_snapshot(forged),
            "removed_bytes": module.tree_bytes(forged),
        },
    )

    with pytest.raises(RuntimeError, match="quarantine path mismatch"):
        module.reconcile_prune_transactions(protected=set(), apply=True)

    assert forged.is_dir()


@pytest.mark.parametrize(
    "directory_name_attribute",
    ["QUARANTINE_DIR_NAME", "PERSISTED_V1_QUARANTINE_DIR_NAME"],
)
def test_unjournaled_quarantine_entry_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    directory_name_attribute: str,
) -> None:
    module = load_publisher()
    roots = isolate_retention_roots(module, tmp_path, monkeypatch)
    group = roots["publication"] / "bundles" / "demo" / "main"
    write_version(group, "20260714T100000Z", b"payload", 1)
    directory_name = getattr(module, directory_name_attribute)
    orphan = group / directory_name / ("e" * 32) / "20260714T090000Z"
    orphan.mkdir(parents=True)

    with pytest.raises(RuntimeError, match="unexpected retention quarantine entries"):
        module.version_dirs(group)


def test_transaction_journal_rejects_unexpected_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    isolate_retention_roots(module, tmp_path, monkeypatch)
    transaction_root = module.prune_transaction_root()
    transaction_root.mkdir(parents=True)
    (transaction_root / "notes.txt").write_text("not a journal", encoding="utf-8")

    with pytest.raises(RuntimeError, match="unexpected retention transaction entries"):
        module.reconcile_prune_transactions(protected=set(), apply=False)


def test_regression_canonical_inputs_only() -> None:
    module = load_publisher()
    assert "merger/repoground/cli/ground.py" in module.GENERATOR_INPUT_PATHS
    assert "merger/repoground/cli/cmd_ground.py" in module.GENERATOR_INPUT_PATHS
    assert not any("lenskit" in path for path in module.GENERATOR_INPUT_PATHS)
    assert not any("repobrief" in path for path in module.GENERATOR_INPUT_PATHS)


def test_regression_discover_captures_repoground_without_lenskit_alias(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    repos_root = tmp_path / "repos"
    repos_root.mkdir()
    monkeypatch.setattr(module, "REPOS_ROOT", repos_root)

    repoground, _ = initialize_repository(repos_root, "repoground")
    git(
        repoground,
        "remote",
        "add",
        "origin",
        "git@github.com:heimgewebe/repoground.git",
    )
    lenskit, _ = initialize_repository(repos_root, "lenskit")
    git(
        lenskit,
        "remote",
        "add",
        "origin",
        "git@github.com:heimgewebe/lenskit.git",
    )

    entries = {entry.key: entry for entry in module.discover()}
    assert entries["heimgewebe/repoground"].path == repoground
    assert entries["heimgewebe/lenskit"].path == lenskit
    assert entries["heimgewebe/repoground"].path != entries["heimgewebe/lenskit"].path


def test_publication_state_separates_generator_commit_and_input_hash(
    tmp_path: Path,
) -> None:
    module = load_publisher()
    state_file = tmp_path / "heimgewebe__demo__main.state.json"
    publication_dir = tmp_path / "publication"
    publication_dir.mkdir()
    manifest = publication_dir / "demo_merge.bundle.manifest.json"
    manifest.write_text("{}\n", encoding="utf-8")
    source_sha = "a" * 40
    generator_inputs_sha = "b" * 64
    tool_sha = "d" * 40
    identity = {
        "source_sha": source_sha,
        "generator_inputs_sha": generator_inputs_sha,
    }

    module.write_state(
        state_file,
        fingerprint="c" * 64,
        identity=identity,
        tool_sha=tool_sha,
        repository="heimgewebe__demo",
        ref="main",
        publication_dir=publication_dir,
        manifest_path=str(manifest),
        publication_created_at="2026-07-14T10:00:00Z",
        previous_state=None,
        remote_sha=source_sha,
        remote_ref="origin/main",
        published_now=True,
    )

    data = json.loads(state_file.read_text(encoding="utf-8"))
    assert data["schema"] == module.STATE_SCHEMA
    assert data["repo_id"] == "heimgewebe__demo"
    assert data["stem"] == "heimgewebe__demo__main"
    assert data["created_at"] == "2026-07-14T10:00:00Z"
    assert data["created_at_basis"] == "external_manifest_generated_at"
    assert data["source_commit"] == source_sha
    assert data["generator_commit"] == tool_sha
    assert data["generator_commit_status"] == "recorded"
    assert data["generator_inputs_sha"] == generator_inputs_sha
    assert data["manifest_path"] == str(manifest)
    freshness = data["provenance"]["freshness"]
    assert freshness["status"] == "fresh_at_publication"
    assert freshness["remote_commit"] == source_sha
    assert freshness["live_recheck_required"] is True


def test_legacy_state_migration_uses_manifest_without_rebinding_generator(
    tmp_path: Path,
) -> None:
    module = load_publisher()
    publication_dir = tmp_path / "publication"
    publication_dir.mkdir()
    manifest = publication_dir / "demo_merge.bundle.manifest.json"
    manifest.write_text(
        json.dumps({"created_at": "2026-07-01T12:00:00Z"}) + "\n",
        encoding="utf-8",
    )
    source_sha = "a" * 40
    generator_inputs_sha = "b" * 64
    previous = {
        "schema": module.STATE_SCHEMA,
        "fingerprint": "c" * 64,
        "identity": {
            "source_sha": source_sha,
            "generator_inputs_sha": generator_inputs_sha,
        },
        "publication_dir": str(publication_dir),
        "updated_at": "2026-07-01T12:01:00Z",
    }
    state_file = tmp_path / "state.json"

    module.write_state(
        state_file,
        fingerprint="c" * 64,
        identity=previous["identity"],
        tool_sha="d" * 40,
        repository="heimgewebe__demo",
        ref="main",
        publication_dir=None,
        manifest_path=None,
        publication_created_at=None,
        previous_state=previous,
        remote_sha=source_sha,
        remote_ref="origin/main",
        published_now=False,
    )

    migrated = json.loads(state_file.read_text(encoding="utf-8"))
    assert migrated["created_at"] == "2026-07-01T12:00:00Z"
    assert migrated["created_at_basis"] == "bundle_manifest_created_at"
    assert migrated["manifest_path"] == str(manifest)
    assert migrated["generator_commit"] is None
    assert migrated["generator_commit_status"] == "unavailable_legacy_state"
    assert migrated["generator_inputs_sha"] == generator_inputs_sha
    assert migrated["provenance"]["freshness"]["status"] == "fresh"


def test_regression_canonical_unit_names_and_installer_cutover_order() -> None:
    units = sorted(path.name for path in UNIT_DIR.iterdir())
    assert units == [
        "repoground-publish-fleet-watch.service",
        "repoground-publish-fleet-watch.timer",
    ]

    installer = INSTALLER.read_text(encoding="utf-8")
    assert "rb-publish-fleet-watch.timer" in installer
    assert "rb-publish-fleet-watch.service" in installer
    assert "systemctl --user disable --now" in installer
    assert 'for unit in "${OLD_TIMERS[@]}" "${OLD_UNITS[@]}"' in installer
    assert 'rm -f -- "$UNIT_DIR/$unit"' in installer
    assert 'systemctl --user reset-failed "$unit"' in installer
    install_position = installer.index("ops/systemd/repoground-fleet")
    reload_position = installer.index("systemctl --user daemon-reload")
    enable_position = installer.index(
        "systemctl --user enable --now repoground-publish-fleet-watch.timer"
    )
    assert install_position < reload_position < enable_position


def test_missing_generator_inputs_fail_before_publication_and_write_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    roots = isolate_retention_roots(module, tmp_path, monkeypatch)
    monkeypatch.setattr(module, "LOCK_PATH", tmp_path / "fleet.lock")
    monkeypatch.setattr(module, "FLEET_LOG", roots["log"] / "fleet.log")
    entry = module.RepoEntry(
        key="heimgewebe/demo",
        owner="heimgewebe",
        repo="demo",
        path=tmp_path / "demo",
        remote="git@github.com:heimgewebe/demo.git",
    )
    monkeypatch.setattr(module, "discover", lambda: [entry])
    monkeypatch.setattr(
        module,
        "ensure_tool_worktree",
        lambda: (_ for _ in ()).throw(
            RuntimeError("missing required generator inputs: ['cmd_ground.py']")
        ),
    )
    monkeypatch.setattr(
        module,
        "publish",
        lambda *args, **kwargs: pytest.fail("publication must not start"),
    )

    assert module.main(["--repo", "heimgewebe/demo"]) == 1
    receipt = json.loads((roots["log"] / "fleet-last.json").read_text(encoding="utf-8"))
    assert receipt["status"] == "error"
    assert receipt["phase"] == "generator_preflight"
    assert "missing required generator inputs" in receipt["error"]
    assert not roots["publication"].exists()


def test_idempotent_second_run_does_not_publish_or_create_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_publisher()
    roots = isolate_retention_roots(module, tmp_path, monkeypatch)
    monkeypatch.setattr(module, "LOCK_PATH", tmp_path / "fleet.lock")
    monkeypatch.setattr(module, "FLEET_LOG", roots["log"] / "fleet.log")
    monkeypatch.setattr(
        module,
        "reconcile_prune_transactions",
        lambda *, protected, apply: {"status": "ok"},
    )
    publication_root = roots["publication"]
    entry = module.RepoEntry(
        key="heimgewebe/demo",
        owner="heimgewebe",
        repo="demo",
        path=tmp_path / "demo",
        remote="git@github.com:heimgewebe/demo.git",
    )
    source_sha = "a" * 40
    tool_sha = "d" * 40
    generator_inputs_sha = "b" * 64
    publish_calls: list[Path] = []

    def mock_publish(*args, **kwargs):
        out_dir = (
            publication_root
            / "bundles"
            / "heimgewebe__demo"
            / "main"
            / "20260714T100000Z"
        )
        out_dir.mkdir(parents=True, exist_ok=False)
        manifest = out_dir / "demo_merge.bundle.manifest.json"
        manifest.write_text("{}\n", encoding="utf-8")
        publish_calls.append(out_dir)
        data = {
            "publication": {
                "published": [
                    {"generatedAt": "2026-07-14T10:00:00Z"},
                    {"generatedAt": "2026-07-14T10:00:00Z"},
                ]
            }
        }
        return (
            data,
            out_dir,
            tmp_path / "fake-lease.json",
            str(manifest),
            "2026-07-14T10:00:00Z",
        )

    monkeypatch.setattr(module, "publish", mock_publish)
    monkeypatch.setattr(
        module,
        "ensure_tool_worktree",
        lambda: (tool_sha, generator_inputs_sha),
    )
    monkeypatch.setattr(
        module,
        "remote_head",
        lambda path: ("origin/main", "main", source_sha),
    )
    monkeypatch.setattr(module, "clear_active_publication_lease", lambda path: None)
    monkeypatch.setattr(module, "prune_current_group", lambda *args, **kwargs: {})
    monkeypatch.setattr(module, "discover", lambda: [entry])

    argv = ["--repo", "heimgewebe/demo"]
    assert module.main(argv) == 0
    state_file = roots["state"] / "heimgewebe__demo__main.state.json"
    first = json.loads(state_file.read_text(encoding="utf-8"))
    version_parent = publication_root / "bundles" / "heimgewebe__demo" / "main"
    assert [path.name for path in version_parent.iterdir()] == ["20260714T100000Z"]
    assert len(publish_calls) == 1

    assert module.main(argv) == 0
    second = json.loads(state_file.read_text(encoding="utf-8"))
    assert len(publish_calls) == 1
    assert [path.name for path in version_parent.iterdir()] == ["20260714T100000Z"]
    assert second["created_at"] == first["created_at"]
    assert second["generator_commit"] == first["generator_commit"] == tool_sha
    assert second["generator_inputs_sha"] == generator_inputs_sha
    assert second["manifest_path"] == first["manifest_path"]
    assert second["publication_dir"] == first["publication_dir"]
    assert second["provenance"]["freshness"]["status"] == "fresh"
    assert second["provenance"]["freshness"]["live_recheck_required"] is False
