from __future__ import annotations

import hashlib
import json
import re
import runpy
import socket
from pathlib import Path

import pytest

from merger.repoground.retrieval import query_core
from scripts.ci import run_semantic_real_model_integration as semantic_runner
from scripts.ci.run_semantic_real_model_integration import (
    EXPECTED_FIXTURE_VOCAB_SHA256,
    EXPECTED_MODEL_TREE_SHA256,
    FIXTURE_DIMENSIONS,
    FIXTURE_VOCAB,
    SEMANTIC_TARGET_ID,
    _compiler_image,
    _fixture_vocab_sha256,
    _locked_runtime_versions,
    _require_dependency_target,
    _require_loopback_only_network,
    canonical_tree_sha256,
    deny_python_network,
)

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github/workflows/semantic-lock.yml"
WRAPPER = ROOT / "scripts/ci/run_semantic_real_model_integration.sh"
RUNNER = ROOT / "scripts/ci/run_semantic_real_model_integration.py"


def test_real_model_fixture_identity_is_explicit() -> None:
    sentence_transformers_version, torch_version = _locked_runtime_versions()
    assert sentence_transformers_version == "5.6.0"
    assert torch_version == "2.13.0+cpu"
    assert SEMANTIC_TARGET_ID == "cpython-312-linux-x86_64"
    assert FIXTURE_DIMENSIONS == 8
    assert len(FIXTURE_VOCAB) == len(set(FIXTURE_VOCAB))
    assert EXPECTED_FIXTURE_VOCAB_SHA256 == _fixture_vocab_sha256()
    assert re.fullmatch(r"[0-9a-f]{64}", EXPECTED_FIXTURE_VOCAB_SHA256)
    assert re.fullmatch(r"[0-9a-f]{64}", EXPECTED_MODEL_TREE_SHA256)
    assert "@sha256:" in _compiler_image()


def test_runner_import_does_not_require_platform_contract(tmp_path: Path) -> None:
    probe = tmp_path / "scripts/ci/run_semantic_real_model_integration.py"
    probe.parent.mkdir(parents=True)
    probe.write_text(RUNNER.read_text(encoding="utf-8"), encoding="utf-8")

    namespace = runpy.run_path(str(probe), run_name="repoground_semantic_lazy_probe")

    assert "_semantic_platform_contract" in namespace
    assert not (tmp_path / "docs/release/repoground-semantic-platforms.v1.json").exists()


def test_semantic_platform_contract_is_lazy_and_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    contract = {
        "supported_targets": [
            {
                "id": SEMANTIC_TARGET_ID,
                "root_pins": {
                    "sentence-transformers": "5.6.0",
                    "torch": "2.13.0+cpu",
                },
            }
        ],
        "compiler": {"image": "example.invalid/compiler@sha256:" + "a" * 64},
    }
    calls: list[str] = []

    def fake_loader() -> dict[str, object]:
        calls.append("load")
        return contract

    semantic_runner._semantic_platform_contract.cache_clear()
    semantic_runner._locked_runtime_versions.cache_clear()
    monkeypatch.setattr(semantic_runner, "_load_semantic_platform_contract", fake_loader)
    try:
        assert calls == []
        assert semantic_runner._semantic_platform_contract() is contract
        assert semantic_runner._semantic_platform_contract() is contract
        assert calls == ["load"]
        assert semantic_runner._locked_runtime_versions() == ("5.6.0", "2.13.0+cpu")
        assert calls == ["load"]

        def fail_if_versions_are_recomputed(_contract: dict[str, object]) -> tuple[str, str]:
            raise AssertionError("locked runtime versions cache was bypassed")

        monkeypatch.setattr(
            semantic_runner,
            "_locked_root_versions",
            fail_if_versions_are_recomputed,
        )
        assert semantic_runner._locked_runtime_versions() == ("5.6.0", "2.13.0+cpu")
    finally:
        semantic_runner._semantic_platform_contract.cache_clear()
        semantic_runner._locked_runtime_versions.cache_clear()


def test_semantic_platform_contract_errors_include_path(tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"
    with pytest.raises(RuntimeError, match=re.escape(str(missing))):
        semantic_runner._load_semantic_platform_contract(missing)

    invalid = tmp_path / "invalid.json"
    invalid.write_text("{not-json", encoding="utf-8")
    with pytest.raises(RuntimeError, match=re.escape(str(invalid))):
        semantic_runner._load_semantic_platform_contract(invalid)

    wrong_type = tmp_path / "wrong-type.json"
    wrong_type.write_text("[]", encoding="utf-8")
    with pytest.raises(RuntimeError, match=r"must be a JSON object, got list"):
        semantic_runner._load_semantic_platform_contract(wrong_type)


def test_compiler_image_can_be_validated_without_contract_io() -> None:
    image = "example.invalid/compiler@sha256:" + "b" * 64
    assert _compiler_image({"compiler": {"image": image}}) == image
    with pytest.raises(RuntimeError, match="digest-pinned compiler image"):
        _compiler_image({"compiler": {"image": "example.invalid/compiler:latest"}})


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
    # macOS commonly exposes pytest's temp root through /var -> /private/var.
    # Resolve only the host-provided base so the test still creates and rejects
    # the symlinks that belong to the fixture itself.
    tmp_path = tmp_path.resolve(strict=True)
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




def test_direct_dimension_validation_diagnostics_are_exact() -> None:
    class FixtureModel:
        def encode(self, value: object) -> object:
            vector = [1.0] * FIXTURE_DIMENSIONS
            if isinstance(value, str):
                return vector
            assert isinstance(value, list)
            return [vector[:] for _ in value]

    diagnostics: dict[str, object] = {
        "enabled": True,
        "dimension_validation": "pending",
    }
    query_embedding, document_embeddings = query_core._validated_semantic_embeddings(
        semantic_model=FixtureModel(),
        query_text="query",
        candidate_texts=["first", "second"],
        expected_dimensions=FIXTURE_DIMENSIONS,
        semantic_diagnostics=diagnostics,
    )

    assert query_embedding is not None
    assert document_embeddings is not None
    assert diagnostics == {
        "enabled": True,
        "dimension_validation": "pass",
        "actual_query_dimensions": FIXTURE_DIMENSIONS,
        "actual_document_dimensions": FIXTURE_DIMENSIONS,
    }
    assert "expected_dimensions" not in diagnostics


def test_integration_report_hashes_actual_fixture_vocab(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    changed_vocab = ("changed", "fixture")
    monkeypatch.setattr(semantic_runner, "FIXTURE_VOCAB", changed_vocab)
    monkeypatch.setattr(semantic_runner, "FIXTURE_DIMENSIONS", len(changed_vocab))
    expected_actual_hash = hashlib.sha256(
        json.dumps(changed_vocab, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    report = semantic_runner._integration_report(
        runtime={
            "sentence_transformers_version": "5.6.0",
            "torch_version": "2.13.0+cpu",
            "numpy_version": "2.5.1",
        },
        model={
            "tree_sha256": EXPECTED_MODEL_TREE_SHA256,
            "repeat_tree_sha256": EXPECTED_MODEL_TREE_SHA256,
            "files": [],
        },
        outputs={},
        diagnostics={},
        scores=[],
        network_interfaces=["lo"],
    )

    assert report["model"]["dimensions"] == len(changed_vocab)
    assert report["model"]["vocab_sha256"] == expected_actual_hash
    assert report["model"]["vocab_sha256"] != EXPECTED_FIXTURE_VOCAB_SHA256


def test_python_network_guard_blocks_socket_calls() -> None:
    with deny_python_network():
        with pytest.raises(RuntimeError, match="network access is forbidden"):
            socket.getaddrinfo("example.invalid", 443)
        with pytest.raises(RuntimeError, match="network access is forbidden"):
            socket.create_connection(("example.invalid", 443))

        client = socket.socket()
        try:
            with pytest.raises(RuntimeError, match="network access is forbidden"):
                client.connect(("127.0.0.1", 9))
        finally:
            client.close()

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
    cleanup_chmod = 'chmod -R u+rwX -- "$target" 2>/dev/null || true'
    cleanup_rm = 'rm -rf -- "$target"'
    assert cleanup_chmod in workflow
    assert workflow.index(cleanup_chmod) < workflow.index(cleanup_rm)
    assert '--verify-install "$target"' in workflow


def test_semantic_wrapper_hardens_container_and_import_roots() -> None:
    wrapper = WRAPPER.read_text(encoding="utf-8")

    assert "--network none" in wrapper
    assert "--read-only" in wrapper
    assert "--cap-drop ALL" in wrapper
    assert "--security-opt no-new-privileges" in wrapper
    # Regression guard: do not silently disable the host's LSM/seccomp sandboxing.
    assert "apparmor=unconfined" not in wrapper
    assert "seccomp=unconfined" not in wrapper
    assert "--pids-limit 256" in wrapper
    assert "--memory 2g" in wrapper
    assert "--memory-swap 2g" in wrapper
    assert 'sandbox_uid=65532' in wrapper
    assert 'sandbox_gid=65532' in wrapper
    assert '--user "$sandbox_uid:$sandbox_gid"' in wrapper
    assert '$(id -u):$(id -g)' not in wrapper
    assert "PYTHONPATH=/semantic-target:/work" in wrapper
    assert "PYTHONSAFEPATH=1" in wrapper
    assert "PYTHONNOUSERSITE=1" in wrapper
    assert wrapper.count("python3 -I -S") == 3
    assert "python3 -P" not in wrapper
    assert "python -P -S scripts/ci/run_semantic_real_model_integration.py" in wrapper
    assert "HF_HUB_OFFLINE=1" in wrapper
    assert "TRANSFORMERS_OFFLINE=1" in wrapper
    assert ":/work:ro" in wrapper
    assert ":/semantic-target:ro" in wrapper
    assert "--compiler-image" in wrapper
    assert "docs/release/repoground-semantic-platforms.v1.json" not in wrapper
    assert "@sha256:" not in wrapper
    assert "mcr.microsoft.com/playwright/python:v1.61.0-noble" not in wrapper
    assert '--volume "$runtime_work:/work:ro"' in wrapper
    assert '--volume "$repo_root:/work:ro"' not in wrapper


def test_semantic_wrapper_classifies_archive_entries_and_cleans_up() -> None:
    wrapper = WRAPPER.read_text(encoding="utf-8")

    assert '"archive", "--format=tar", "HEAD"' in wrapper
    assert "tempfile.TemporaryFile()" in wrapper
    assert "stdout=archive" in wrapper
    assert "archive.seek(0)" in wrapper
    assert "io.BytesIO" not in wrapper
    assert "stdout=subprocess.PIPE" not in wrapper
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
    assert 'trap - EXIT HUP INT TERM' in wrapper
    assert "trap 'handle_signal 129' HUP" in wrapper
    assert "trap 'handle_signal 130' INT" in wrapper
    assert "trap 'handle_signal 143' TERM" in wrapper
    assert 'cleanup "$1"' in wrapper
    assert 'handle_signal() {\n  exit "$1"' not in wrapper
    assert 'chmod -R u+rwX -- "$runtime_root"' in wrapper
    assert 'exit "$status"' in wrapper


def test_semantic_runner_hardens_offline_execution() -> None:
    runner = RUNNER.read_text(encoding="utf-8")

    assert "local_files_only=True" in runner
    assert "deny_python_network" in runner
    assert "_require_loopback_only_network" in runner
    assert "_require_explicit_import_roots" in runner
    assert "os.umask(0o077)" in runner
    assert '"PYTHONNOUSERSITE": "1"' in runner
    assert "_load_semantic_platform_contract" in runner
    assert "_semantic_platform_contract" in runner
    assert "_locked_root_versions" in runner
    assert "_locked_runtime_versions" in runner
    assert "EXPECTED_SENTENCE_TRANSFORMERS_VERSION, EXPECTED_TORCH_VERSION =" not in runner
    assert "sys.path.insert" not in runner
    assert "ignore_cleanup_errors=True" not in runner
    assert '"downloaded": False' in runner
    assert EXPECTED_MODEL_TREE_SHA256 in runner
