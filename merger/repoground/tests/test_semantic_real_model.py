from __future__ import annotations

import re
from pathlib import Path

import pytest

from scripts.ci.run_semantic_real_model_integration import (
    EXPECTED_MODEL_TREE_SHA256,
    EXPECTED_SENTENCE_TRANSFORMERS_VERSION,
    EXPECTED_TORCH_VERSION,
    FIXTURE_DIMENSIONS,
    FIXTURE_VOCAB,
    _require_dependency_target,
    _require_loopback_only_network,
    canonical_tree_sha256,
)

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github/workflows/semantic-lock.yml"
WRAPPER = ROOT / "scripts/ci/run_semantic_real_model_integration.sh"
RUNNER = ROOT / "scripts/ci/run_semantic_real_model_integration.py"


def test_real_model_fixture_identity_is_explicit() -> None:
    assert EXPECTED_SENTENCE_TRANSFORMERS_VERSION == "5.6.0"
    assert EXPECTED_TORCH_VERSION == "2.13.0+cpu"
    assert FIXTURE_DIMENSIONS == 8
    assert len(FIXTURE_VOCAB) == len(set(FIXTURE_VOCAB))
    assert re.fullmatch(r"[0-9a-f]{64}", EXPECTED_MODEL_TREE_SHA256)


def test_canonical_model_tree_hash_is_path_and_content_bound(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    for root in (first, second):
        (root / "module").mkdir(parents=True)
        (root / "module" / "config.json").write_text(
            '{"dimensions":8}\n', encoding="utf-8"
        )
        (root / "modules.json").write_text("[]\n", encoding="utf-8")

    first_hash = canonical_tree_sha256(first)
    assert first_hash == canonical_tree_sha256(second)

    (first / "module" / "config.json").chmod(0o600)
    (second / "module" / "config.json").chmod(0o444)
    assert canonical_tree_sha256(first) == first_hash
    assert canonical_tree_sha256(second) == first_hash
    (second / "module" / "config.json").chmod(0o600)

    (second / "module" / "config.json").write_text(
        '{"dimensions":9}\n', encoding="utf-8"
    )
    assert canonical_tree_sha256(second) != first_hash

    (second / "module" / "config.json").write_text(
        '{"dimensions":8}\n', encoding="utf-8"
    )
    (second / "renamed.json").write_text(
        (second / "modules.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (second / "modules.json").unlink()
    assert canonical_tree_sha256(second) != first_hash

    symlinked = tmp_path / "symlinked"
    symlinked.mkdir()
    (symlinked / "payload.json").write_text("{}\n", encoding="utf-8")
    (symlinked / "external.json").symlink_to(second / "module" / "config.json")
    with pytest.raises(RuntimeError, match="model tree contains symlink"):
        canonical_tree_sha256(symlinked)


def test_dependency_target_rejects_relative_links_and_files(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    assert _require_dependency_target(target) == target.resolve()

    with pytest.raises(RuntimeError, match="absolute path"):
        _require_dependency_target(Path("relative-target"))

    file_target = tmp_path / "file"
    file_target.write_text("not a directory\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="real directory"):
        _require_dependency_target(file_target)

    link_target = tmp_path / "link"
    link_target.symlink_to(target, target_is_directory=True)
    with pytest.raises(RuntimeError, match="symlink components"):
        _require_dependency_target(link_target)

    real_parent = tmp_path / "real-parent"
    nested_target = real_parent / "target"
    nested_target.mkdir(parents=True)
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(real_parent, target_is_directory=True)
    with pytest.raises(RuntimeError, match="symlink components"):
        _require_dependency_target(linked_parent / "target")


def test_network_observation_requires_only_loopback(tmp_path: Path) -> None:
    interface_root = tmp_path / "net"
    interface_root.mkdir()
    (interface_root / "lo").mkdir()
    assert _require_loopback_only_network(interface_root) == ["lo"]

    (interface_root / "eth0").mkdir()
    with pytest.raises(RuntimeError, match="loopback-only"):
        _require_loopback_only_network(interface_root)

    link_root = tmp_path / "net-link"
    link_root.symlink_to(interface_root, target_is_directory=True)
    with pytest.raises(RuntimeError, match="real directory"):
        _require_loopback_only_network(link_root)


def test_semantic_workflow_wires_unique_cleanup_target() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "scripts/ci/run_semantic_real_model_integration.sh" in workflow
    assert "scripts/ci/run_semantic_real_model_integration.py" in workflow
    assert workflow.count(
        "docs/release/repoground-semantic-platforms.v1.json"
    ) == 2
    assert workflow.count("merger/repoground/retrieval/query_core.py") == 2
    assert "docs/proofs/repoground-semantic-real-model-integration-v1-proof.md" not in workflow
    assert "docs/retrieval/semantic-reranking.md" not in workflow
    assert "docs/release/semantic-extension-platforms.v1.json" not in workflow
    assert 'target=""' in workflow
    assert "mktemp -d" in workflow
    assert '".semantic-real-model-target.XXXXXX"' in workflow
    assert "RUNNER_TEMP" not in workflow
    assert "GITHUB_WORKSPACE" not in workflow
    assert "trap cleanup EXIT" in workflow
    assert 'chmod -R a+rX -- "$target"' in workflow
    assert '--verify-install "$target"' in workflow


def test_semantic_wrapper_hardens_container_and_import_roots() -> None:
    wrapper = WRAPPER.read_text(encoding="utf-8")

    assert "--network none" in wrapper
    assert "--read-only" in wrapper
    assert "--cap-drop ALL" in wrapper
    assert "--security-opt no-new-privileges" in wrapper
    assert 'sandbox_uid=65532' in wrapper
    assert 'sandbox_gid=65532' in wrapper
    assert '--user "$sandbox_uid:$sandbox_gid"' in wrapper
    assert '$(id -u):$(id -g)' not in wrapper
    assert "PYTHONPATH=/semantic-target:/work" in wrapper
    assert "PYTHONSAFEPATH=1" in wrapper
    assert wrapper.count("python3 -I -S") == 3
    assert "python3 -P" not in wrapper
    assert "python -P -S scripts/ci/run_semantic_real_model_integration.py" in wrapper
    assert "HF_HUB_OFFLINE=1" in wrapper
    assert "TRANSFORMERS_OFFLINE=1" in wrapper
    assert ":/work:ro" in wrapper
    assert ":/semantic-target:ro" in wrapper
    assert "docs/release/repoground-semantic-platforms.v1.json" in wrapper
    assert "@sha256:" in wrapper
    assert "mcr.microsoft.com/playwright/python:v1.61.0-noble" not in wrapper
    assert '--volume "$runtime_work:/work:ro"' in wrapper
    assert '--volume "$repo_root:/work:ro"' not in wrapper


def test_semantic_wrapper_classifies_archive_entries_and_cleans_up() -> None:
    wrapper = WRAPPER.read_text(encoding="utf-8")

    assert '"archive", "--format=tar", "HEAD"' in wrapper
    assert "def _archive_member_kind" in wrapper
    assert "member.issym()" in wrapper
    assert "member.islnk()" in wrapper
    assert "member.ischr()" in wrapper
    assert "member.isblk()" in wrapper
    assert "member.isfifo()" in wrapper
    assert "runtime archive contains unsafe" in wrapper
    assert 'destination.chmod(0o444)' in wrapper
    assert 'directory.chmod(0o555)' in wrapper
    assert 'status=$?' in wrapper
    assert 'chmod -R u+rwX -- "$runtime_root"' in wrapper
    assert 'exit "$status"' in wrapper


def test_semantic_runner_hardens_offline_execution() -> None:
    runner = RUNNER.read_text(encoding="utf-8")

    assert "local_files_only=True" in runner
    assert "deny_python_network" in runner
    assert "_require_loopback_only_network" in runner
    assert "_require_explicit_import_roots" in runner
    assert "os.umask(0o077)" in runner
    assert "sys.path.insert" not in runner
    assert "ignore_cleanup_errors=True" not in runner
    assert '"downloaded": False' in runner
    assert EXPECTED_MODEL_TREE_SHA256 in runner
