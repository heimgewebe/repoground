from __future__ import annotations

import errno
import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from merger.repoground.core import bundle_generation as generation_mod
from merger.repoground.core import bundle_access
from merger.repoground.core import rooted_filesystem
from merger.repoground.core.bundle_generation import (
    BundleGenerationError,
    publish_bundle_generation,
    resolve_bundle_manifest_path,
)


@pytest.fixture(autouse=True)
def _reset_call_navigation_caches():
    bundle_access._clear_call_navigation_caches()
    yield
    bundle_access._clear_call_navigation_caches()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_basic_bundle(
    root: Path,
    *,
    canonical_bytes: bytes = b"# bundle\n",
    sidecar_bytes: bytes = b'{"status":"pass"}\n',
    run_id: str = "run-1",
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    canonical = root / "demo.md"
    sidecar = root / "demo.post_emit_health.json"
    agent_gate = root / "demo.agent_export_gate.json"
    canonical.write_bytes(canonical_bytes)
    sidecar.write_bytes(sidecar_bytes)
    agent_gate.write_bytes(b'{"status":"pass"}\n')
    manifest = {
        "kind": "repolens.bundle.manifest",
        "version": "1.0",
        "run_id": run_id,
        "created_at": "2026-07-16T00:00:00Z",
        "generator": {"name": "test", "version": "dev", "config_sha256": "a" * 64},
        "artifacts": [
            {
                "role": "canonical_md",
                "path": canonical.name,
                "content_type": "text/markdown",
                "bytes": len(canonical_bytes),
                "sha256": _sha(canonical_bytes),
            }
        ],
        "links": {
            "post_emit_health_path": sidecar.name,
            "agent_export_gate_path": agent_gate.name,
        },
        "capabilities": {},
    }
    manifest_path = root / "demo.bundle.manifest.json"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    return manifest_path


def _write_call_graph_bundle(
    root: Path,
    *,
    callee: str,
    run_id: str,
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    calls = [
        {
            "path": "pkg/a.py",
            "start_line": 10,
            "start_col": 0,
            "end_line": 10,
            "end_col": 8,
            "range_ref": "file:pkg/a.py#L10-L10",
            "callee_expression": callee,
            "simple_name": callee,
            "caller_scope": "symbol",
            "caller_symbol_id": "py:pkg:a.py:function:caller",
            "caller_qualified_name": "caller",
            "caller_kind": "function",
            "caller_start_line": 1,
            "caller_end_line": 20,
            "relation_type": "calls",
            "evidence_level": "S1",
            "resolution_status": "resolved",
            "resolution_reason": "test_fixture",
            "resolved_target_ids": ["py:pkg:target.py:function:target"],
            "candidate_target_ids": [],
        }
    ]
    graph = {
        "kind": "lenskit.python_call_graph",
        "version": "1.0",
        "run_id": run_id,
        "canonical_dump_index_sha256": "b" * 64,
        "language": "python",
        "evidence_model": {
            "S0": "unresolved or ambiguous static candidate",
            "S1": "one uniquely resolved local target",
        },
        "resolution_statuses": ["resolved", "candidate", "ambiguous", "unresolved"],
        "relation_types": ["calls", "constructs"],
        "call_count": len(calls),
        "resolution_counts": {"resolved": 1, "candidate": 0, "ambiguous": 0, "unresolved": 0},
        "evidence_counts": {"S0": 0, "S1": 1},
        "relation_counts": {"calls": 1, "constructs": 0},
        "calls": calls,
        "skipped_files_count": 0,
        "skipped_errors": [],
        "does_not_establish": list(bundle_access._CALL_GRAPH_REQUIRED_NONCLAIMS),
    }
    graph_bytes = json.dumps(graph, sort_keys=True).encode("utf-8")
    graph_path = root / "demo.python_call_graph.json"
    graph_path.write_bytes(graph_bytes)
    manifest = {
        "kind": "repolens.bundle.manifest",
        "version": "1.0",
        "run_id": run_id,
        "created_at": "2026-07-16T00:00:00Z",
        "generator": {"name": "test", "version": "dev", "config_sha256": "a" * 64},
        "artifacts": [
            {
                "role": "python_call_graph_json",
                "path": graph_path.name,
                "content_type": "application/json",
                "bytes": len(graph_bytes),
                "sha256": _sha(graph_bytes),
            }
        ],
        "links": {},
        "capabilities": {},
    }
    manifest_path = root / "demo.bundle.manifest.json"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    return manifest_path


def _write_nested_bundle(
    root: Path,
    *,
    canonical_bytes: bytes = b"# nested\n",
    run_id: str = "run-nested",
) -> tuple[Path, Path]:
    artifact_dir = root / "artifacts"
    manifest_dir = root / "snapshots"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    manifest_dir.mkdir(parents=True, exist_ok=True)
    canonical = artifact_dir / "demo.md"
    canonical.write_bytes(canonical_bytes)
    manifest = {
        "kind": "repolens.bundle.manifest",
        "version": "1.0",
        "run_id": run_id,
        "created_at": "2026-07-16T00:00:00Z",
        "generator": {"name": "test", "version": "dev", "config_sha256": "a" * 64},
        "artifacts": [
            {
                "role": "canonical_md",
                "path": "artifacts/demo.md",
                "content_type": "text/markdown",
                "bytes": len(canonical_bytes),
                "sha256": _sha(canonical_bytes),
            }
        ],
        "links": {},
        "capabilities": {},
    }
    manifest_path = manifest_dir / "demo.bundle.manifest.json"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    return manifest_path, canonical


def _pointer_payload(
    *,
    generation_id: str = "a" * 64,
    sha256: str = "b" * 64,
    manifest_path: str = "a" * 64 + "/demo.bundle.manifest.json",
) -> dict[str, str]:
    return {
        "kind": generation_mod.POINTER_KIND,
        "version": generation_mod.POINTER_VERSION,
        "generation_id": generation_id,
        "sha256": sha256,
        "manifest_path": manifest_path,
        "selection_rule": "read_pointer_once_then_verify_generation_manifest",
    }


def test_two_generations_switch_current_and_keep_old_generation_immutable(tmp_path: Path) -> None:
    manifest = _write_basic_bundle(tmp_path, canonical_bytes=b"first\n", run_id="run-1")
    first = publish_bundle_generation(manifest)
    first_canonical = first.generation_dir / "demo.md"

    manifest = _write_basic_bundle(tmp_path, canonical_bytes=b"second\n", run_id="run-2")
    second = publish_bundle_generation(manifest)

    assert first.generation_id != second.generation_id
    assert first_canonical.read_bytes() == b"first\n"
    assert (second.generation_dir / "demo.md").read_bytes() == b"second\n"
    assert (second.generation_dir / "demo.agent_export_gate.json").is_file()
    assert second.current_manifest_path.parent.name == "current"
    assert second.current_manifest_path.resolve() == second.resolved_manifest_path
    assert resolve_bundle_manifest_path(second.current_manifest_path) == second.resolved_manifest_path


def test_republishing_identical_bundle_reuses_verified_generation(tmp_path: Path) -> None:
    manifest = _write_basic_bundle(tmp_path)
    first = publish_bundle_generation(manifest)
    second = publish_bundle_generation(manifest)

    assert second.generation_id == first.generation_id
    assert first.reused is False
    assert second.reused is True


def test_generation_rejects_symlink_and_traversal_paths(tmp_path: Path) -> None:
    outside = tmp_path / "outside.md"
    outside.write_text("outside", encoding="utf-8")
    manifest = _write_basic_bundle(tmp_path / "bundle")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["artifacts"][0]["path"] = "../outside.md"
    manifest.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(BundleGenerationError, match="traversal|escapes"):
        publish_bundle_generation(manifest)

    symlink_root = tmp_path / "symlink"
    manifest = _write_basic_bundle(symlink_root)
    target = symlink_root / "target.md"
    target.write_text("target", encoding="utf-8")
    linked = symlink_root / "linked.md"
    linked.symlink_to(target)
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["artifacts"][0]["path"] = linked.name
    data["artifacts"][0]["bytes"] = target.stat().st_size
    data["artifacts"][0]["sha256"] = _sha(target.read_bytes())
    manifest.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(BundleGenerationError, match="regular file"):
        publish_bundle_generation(manifest)


def test_cache_access_via_current_manifest_sees_pointer_switch(tmp_path: Path) -> None:
    manifest = _write_call_graph_bundle(tmp_path, callee="target", run_id="run-1")
    first = publish_bundle_generation(manifest)
    current_manifest = first.current_manifest_path

    before = bundle_access.find_references(current_manifest, "target")
    assert before["status"] == "available"
    assert before["total_match_count"] == 1

    manifest = _write_call_graph_bundle(tmp_path, callee="renamed", run_id="run-2")
    publish_bundle_generation(manifest)

    after_old_query = bundle_access.find_references(current_manifest, "target")
    after_new_query = bundle_access.find_references(current_manifest, "renamed")
    assert after_old_query["status"] == "available"
    assert after_old_query["total_match_count"] == 0
    assert after_new_query["status"] == "available"
    assert after_new_query["total_match_count"] == 1


def test_current_reader_resolves_manifest_and_artifact_from_same_generation(tmp_path: Path) -> None:
    manifest = _write_basic_bundle(tmp_path, canonical_bytes=b"first\n", run_id="run-1")
    first = publish_bundle_generation(manifest)
    current_manifest = first.current_manifest_path

    manifest = _write_basic_bundle(tmp_path, canonical_bytes=b"second\n", run_id="run-2")
    second = publish_bundle_generation(manifest)
    flat_artifact = tmp_path / "demo.md"
    flat_artifact.write_bytes(b"mutated flat file\n")

    artifact = bundle_access.get_artifact(current_manifest, "canonical_md")["artifact"]
    assert Path(artifact["absolute_path"]).read_bytes() == b"second\n"
    assert str(second.generation_dir) in artifact["absolute_path"]


def test_failure_before_pointer_switch_leaves_old_current(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest = _write_basic_bundle(tmp_path, canonical_bytes=b"first\n", run_id="run-1")
    first = publish_bundle_generation(manifest)

    manifest = _write_basic_bundle(tmp_path, canonical_bytes=b"second\n", run_id="run-2")

    def fail_pointer(*_args: object, **_kwargs: object) -> tuple[Path, str]:
        raise BundleGenerationError("injected pointer failure")

    monkeypatch.setattr(generation_mod, "_publish_current_pointer", fail_pointer)
    with pytest.raises(BundleGenerationError, match="injected pointer failure"):
        publish_bundle_generation(manifest)

    assert first.current_manifest_path.resolve() == first.resolved_manifest_path
    assert (first.current_manifest_path.parent / "demo.md").read_bytes() == b"first\n"


def test_nested_manifest_relative_path_is_published_and_resolved(tmp_path: Path) -> None:
    manifest, canonical = _write_nested_bundle(tmp_path)

    result = publish_bundle_generation(manifest, output_root=tmp_path)

    assert result.current_manifest_path.resolve() == result.resolved_manifest_path
    assert result.resolved_manifest_path == result.generation_dir / "snapshots/demo.bundle.manifest.json"
    assert result.current_path_for(canonical) == result.current_pointer_path / "artifacts/demo.md"
    assert result.current_path_for(canonical).resolve() == result.generation_dir / "artifacts/demo.md"


def test_json_pointer_mode_returns_immutable_current_manifest_and_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest, canonical = _write_nested_bundle(tmp_path)

    def unsupported_symlink(*_args: object, **_kwargs: object) -> tuple[Path, str]:
        raise NotImplementedError("symlink unsupported")

    monkeypatch.setattr(generation_mod, "_write_current_symlink", unsupported_symlink)
    result = publish_bundle_generation(manifest, output_root=tmp_path)

    assert result.pointer_kind == "json_pointer"
    assert result.current_pointer_path.name == generation_mod.CURRENT_POINTER_JSON_NAME
    assert result.current_manifest_path == result.resolved_manifest_path
    assert result.current_manifest_path == result.generation_dir / "snapshots/demo.bundle.manifest.json"
    assert result.current_path_for(canonical) == result.generation_dir / "artifacts/demo.md"
    assert resolve_bundle_manifest_path(result.current_pointer_path) == result.current_manifest_path
    pointer = json.loads(result.current_pointer_path.read_text(encoding="utf-8"))
    assert pointer["manifest_path"] == f"{result.generation_id}/snapshots/demo.bundle.manifest.json"

    def fail_if_symlink_called(*_args: object, **_kwargs: object) -> tuple[Path, str]:
        raise AssertionError("sticky JSON lane must not retry symlink publication")

    monkeypatch.setattr(generation_mod, "_write_current_symlink", fail_if_symlink_called)
    manifest, _ = _write_nested_bundle(tmp_path, canonical_bytes=b"# changed\n", run_id="run-2")
    second = publish_bundle_generation(manifest, output_root=tmp_path)
    assert second.pointer_kind == "json_pointer"


def test_symlink_pointer_mode_is_sticky(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest = _write_basic_bundle(tmp_path, canonical_bytes=b"first\n", run_id="run-1")
    first = publish_bundle_generation(manifest)

    def fail_json_pointer(*_args: object, **_kwargs: object) -> tuple[Path, str]:
        raise AssertionError("sticky symlink lane must not publish current.json")

    monkeypatch.setattr(generation_mod, "_write_current_json_pointer", fail_json_pointer)
    manifest = _write_basic_bundle(tmp_path, canonical_bytes=b"second\n", run_id="run-2")
    second = publish_bundle_generation(manifest)

    assert first.pointer_kind == "relative_symlink"
    assert second.pointer_kind == "relative_symlink"
    assert os.readlink(second.current_pointer_path) == second.generation_id
    assert not (second.current_pointer_path.parent / generation_mod.CURRENT_POINTER_JSON_NAME).exists()


def test_conflicting_current_and_current_json_fail_closed(tmp_path: Path) -> None:
    manifest = _write_basic_bundle(tmp_path, canonical_bytes=b"first\n", run_id="run-1")
    first = publish_bundle_generation(manifest)
    (first.current_pointer_path.parent / generation_mod.CURRENT_POINTER_JSON_NAME).write_text(
        "{}",
        encoding="utf-8",
    )

    manifest = _write_basic_bundle(tmp_path, canonical_bytes=b"second\n", run_id="run-2")
    with pytest.raises(BundleGenerationError, match="conflicting current"):
        publish_bundle_generation(manifest)

    assert first.current_manifest_path.resolve() == first.resolved_manifest_path


def test_unexpected_current_type_fails_closed(tmp_path: Path) -> None:
    manifest = _write_basic_bundle(tmp_path)
    lane_root = generation_mod.generation_lane_root(tmp_path, "demo")
    lane_root.mkdir(parents=True)
    (lane_root / generation_mod.CURRENT_LINK_NAME).write_text("not-a-pointer", encoding="utf-8")

    with pytest.raises(BundleGenerationError, match="unexpected filesystem type"):
        publish_bundle_generation(manifest)


def test_symlink_failure_on_existing_current_keeps_old_pointer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = _write_basic_bundle(tmp_path, canonical_bytes=b"first\n", run_id="run-1")
    first = publish_bundle_generation(manifest)
    manifest = _write_basic_bundle(tmp_path, canonical_bytes=b"second\n", run_id="run-2")

    def fail_symlink(*_args: object, **_kwargs: object) -> None:
        raise OSError(errno.EOPNOTSUPP, "symlink disabled")

    monkeypatch.setattr(generation_mod.os, "symlink", fail_symlink)
    with pytest.raises(BundleGenerationError, match="sticky.*JSON fallback"):
        publish_bundle_generation(manifest)

    assert first.current_manifest_path.resolve() == first.resolved_manifest_path
    assert (first.current_manifest_path.parent / "demo.md").read_bytes() == b"first\n"


def test_current_json_resolver_rejects_traversal_and_symlink_pointer(tmp_path: Path) -> None:
    lane_root = tmp_path / ".repobrief-generations" / "demo"
    lane_root.mkdir(parents=True)
    pointer = lane_root / generation_mod.CURRENT_POINTER_JSON_NAME
    pointer.write_text(
        json.dumps(_pointer_payload(manifest_path="../evil.bundle.manifest.json")),
        encoding="utf-8",
    )
    with pytest.raises(BundleGenerationError, match="traversal"):
        resolve_bundle_manifest_path(pointer)

    pointer.unlink()
    target = tmp_path / "outside-current.json"
    target.write_text(json.dumps(_pointer_payload()), encoding="utf-8")
    pointer.symlink_to(target)
    with pytest.raises(BundleGenerationError, match="regular file"):
        resolve_bundle_manifest_path(pointer)


def test_current_json_resolver_rejects_manifest_hash_manipulation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest, _ = _write_nested_bundle(tmp_path)

    def unsupported_symlink(*_args: object, **_kwargs: object) -> tuple[Path, str]:
        raise NotImplementedError("symlink unsupported")

    monkeypatch.setattr(generation_mod, "_write_current_symlink", unsupported_symlink)
    result = publish_bundle_generation(manifest, output_root=tmp_path)
    pointer = json.loads(result.current_pointer_path.read_text(encoding="utf-8"))
    pointer["sha256"] = "0" * 64
    result.current_pointer_path.write_text(json.dumps(pointer), encoding="utf-8")

    with pytest.raises(BundleGenerationError, match="sha256 mismatch"):
        resolve_bundle_manifest_path(result.current_pointer_path)

def test_bundle_publication_uses_portable_darwin_create_only_rename(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = _write_basic_bundle(tmp_path, run_id="darwin-run")
    original_rename = os.rename
    loaded = []

    class FakeRenameAtx:
        argtypes = None
        restype = None

        def __call__(
            self, source_fd, source_name, destination_fd, destination_name, flags
        ):
            assert flags == rooted_filesystem._RENAME_EXCL
            original_rename(
                os.fsdecode(source_name),
                os.fsdecode(destination_name),
                src_dir_fd=source_fd,
                dst_dir_fd=destination_fd,
            )
            return 0

    monkeypatch.setattr(
        rooted_filesystem, "_rename_platform", lambda: "darwin"
    )
    monkeypatch.setattr(
        rooted_filesystem,
        "_load_libc_rename_function",
        lambda name: loaded.append(name) or FakeRenameAtx(),
    )

    result = publish_bundle_generation(manifest)

    assert loaded == ["renameatx_np"]
    assert result.generation_dir.is_dir()
    assert resolve_bundle_manifest_path(result.current_manifest_path).is_file()

def test_nested_artifact_directories_are_created_in_generation(tmp_path: Path) -> None:
    manifest, canonical = _write_nested_bundle(tmp_path)

    result = publish_bundle_generation(manifest, output_root=tmp_path)

    assert (result.generation_dir / "artifacts/demo.md").read_bytes() == canonical.read_bytes()


def test_post_emit_health_manifest_hash_binding_is_verified(tmp_path: Path) -> None:
    manifest = _write_basic_bundle(tmp_path)
    manifest_sha256 = _sha(manifest.read_bytes())
    health_path = tmp_path / "demo.post_emit_health.json"
    health_path.write_text(
        json.dumps(
            {
                "status": "pass",
                "bundle_manifest_sha256": manifest_sha256,
            }
        ),
        encoding="utf-8",
    )

    result = publish_bundle_generation(manifest)

    assert result.manifest_sha256 == manifest_sha256


def test_post_emit_health_manifest_hash_mismatch_blocks_pointer_switch(
    tmp_path: Path,
) -> None:
    manifest = _write_basic_bundle(tmp_path)
    health_path = tmp_path / "demo.post_emit_health.json"
    health_path.write_text(
        json.dumps(
            {
                "status": "pass",
                "bundle_manifest_sha256": "0" * 64,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(BundleGenerationError, match="does not match the final manifest"):
        publish_bundle_generation(manifest)

    assert not generation_mod.generation_lane_root(tmp_path, "demo").exists()


def test_removed_generation_before_pointer_switch_keeps_old_current(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_manifest = _write_basic_bundle(
        tmp_path, canonical_bytes=b"first\n", run_id="run-1"
    )
    first = publish_bundle_generation(first_manifest)
    second_manifest = _write_basic_bundle(
        tmp_path, canonical_bytes=b"second\n", run_id="run-2"
    )
    original_install = generation_mod._install_generation

    def install_then_remove(generations_root, generation_id, files):
        generation_dir, reused = original_install(generations_root, generation_id, files)
        rooted_filesystem.remove_tree(generation_dir)
        return generation_dir, reused

    monkeypatch.setattr(generation_mod, "_install_generation", install_then_remove)

    with pytest.raises(
        BundleGenerationError, match="generation changed while the current pointer"
    ):
        publish_bundle_generation(second_manifest)

    assert first.current_manifest_path.resolve() == first.resolved_manifest_path
    assert (first.current_manifest_path.parent / "demo.md").read_bytes() == b"first\n"


def _corrupt_after_pointer_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    original = generation_mod._publish_current_pointer

    def publish_then_corrupt(generations_root: Path, **kwargs):
        result = original(generations_root, **kwargs)
        (generations_root / kwargs["generation_id"] / "demo.md").write_bytes(
            b"corrupt-after-switch\n"
        )
        return result

    monkeypatch.setattr(generation_mod, "_publish_current_pointer", publish_then_corrupt)


def test_post_switch_mutation_rolls_back_relative_symlink_pointer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_manifest = _write_basic_bundle(
        tmp_path, canonical_bytes=b"first\n", run_id="run-1"
    )
    first = publish_bundle_generation(first_manifest)
    assert first.pointer_kind == "relative_symlink"
    second_manifest = _write_basic_bundle(
        tmp_path, canonical_bytes=b"second\n", run_id="run-2"
    )
    _corrupt_after_pointer_switch(monkeypatch)

    with pytest.raises(BundleGenerationError, match="previous pointer state was restored"):
        publish_bundle_generation(second_manifest)

    assert os.readlink(first.current_pointer_path) == first.generation_id
    assert (first.generation_dir / "demo.md").read_bytes() == b"first\n"
    assert resolve_bundle_manifest_path(first.current_manifest_path) == first.resolved_manifest_path


def test_post_switch_mutation_rolls_back_json_pointer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unsupported_symlink(*_args: object, **_kwargs: object):
        raise NotImplementedError("symlink unsupported")

    monkeypatch.setattr(generation_mod, "_write_current_symlink", unsupported_symlink)
    first_manifest = _write_basic_bundle(
        tmp_path, canonical_bytes=b"first\n", run_id="run-1"
    )
    first = publish_bundle_generation(first_manifest)
    assert first.pointer_kind == "json_pointer"
    first_pointer = json.loads(first.current_pointer_path.read_text(encoding="utf-8"))
    second_manifest = _write_basic_bundle(
        tmp_path, canonical_bytes=b"second\n", run_id="run-2"
    )
    _corrupt_after_pointer_switch(monkeypatch)

    with pytest.raises(BundleGenerationError, match="previous pointer state was restored"):
        publish_bundle_generation(second_manifest)

    restored = json.loads(first.current_pointer_path.read_text(encoding="utf-8"))
    assert restored == first_pointer
    assert restored["generation_id"] == first.generation_id
    assert (first.generation_dir / "demo.md").read_bytes() == b"first\n"
    assert resolve_bundle_manifest_path(first.current_pointer_path) == first.resolved_manifest_path


def test_pointer_failure_after_atomic_switch_restores_previous_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_manifest = _write_basic_bundle(
        tmp_path, canonical_bytes=b"first\n", run_id="run-1"
    )
    first = publish_bundle_generation(first_manifest)
    second_manifest = _write_basic_bundle(
        tmp_path, canonical_bytes=b"second\n", run_id="run-2"
    )
    original = generation_mod._publish_current_pointer

    def switch_then_fail(generations_root: Path, **kwargs):
        original(generations_root, **kwargs)
        raise BundleGenerationError("simulated failure after atomic switch")

    monkeypatch.setattr(generation_mod, "_publish_current_pointer", switch_then_fail)

    with pytest.raises(BundleGenerationError, match="simulated failure"):
        publish_bundle_generation(second_manifest)

    assert os.readlink(first.current_pointer_path) == first.generation_id
    assert (first.generation_dir / "demo.md").read_bytes() == b"first\n"


def test_parallel_publishers_share_one_serialized_generation_lane(tmp_path: Path) -> None:
    manifest = _write_basic_bundle(tmp_path, run_id="parallel-run")

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _index: publish_bundle_generation(manifest), range(4)))

    generation_ids = {result.generation_id for result in results}
    assert len(generation_ids) == 1
    assert sum(not result.reused for result in results) == 1
    assert sum(result.reused for result in results) == 3
    lane = generation_mod.generation_lane_root(tmp_path, "demo")
    assert os.readlink(lane / "current") == results[0].generation_id
    assert (results[0].generation_dir / "demo.md").read_bytes() == b"# bundle\n"


def test_oversized_post_emit_health_is_rejected_before_json_decode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = _write_basic_bundle(tmp_path)
    health = tmp_path / "demo.post_emit_health.json"
    health.write_bytes(b"x" * 65)
    monkeypatch.setattr(generation_mod, "_MAX_POST_EMIT_HEALTH_BYTES", 64)

    with pytest.raises(BundleGenerationError, match="exceeds maximum size 64"):
        publish_bundle_generation(manifest)

    assert not generation_mod.generation_lane_root(tmp_path, "demo").exists()


@pytest.mark.parametrize("pointer_mode", ["relative_symlink", "json_pointer"])
def test_first_post_switch_failure_removes_new_pointer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    pointer_mode: str,
) -> None:
    if pointer_mode == "json_pointer":
        def unsupported_symlink(*_args: object, **_kwargs: object):
            raise NotImplementedError("symlink unsupported")

        monkeypatch.setattr(
            generation_mod,
            "_write_current_symlink",
            unsupported_symlink,
        )
    manifest = _write_basic_bundle(tmp_path, run_id=f"first-{pointer_mode}")
    _corrupt_after_pointer_switch(monkeypatch)

    with pytest.raises(BundleGenerationError, match="previous pointer state was restored"):
        publish_bundle_generation(manifest)

    lane = generation_mod.generation_lane_root(tmp_path, "demo")
    assert not os.path.lexists(lane / "current")
    assert not (lane / "current.json").exists()


def test_lock_failure_is_exposed_as_bundle_generation_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = _write_basic_bundle(tmp_path)

    def fail_lock(*_args: object, **_kwargs: object):
        raise rooted_filesystem.RootedFilesystemError("simulated lock failure")

    monkeypatch.setattr(generation_mod, "exclusive_file_lock", fail_lock)

    with pytest.raises(BundleGenerationError, match="filesystem guard.*lock failure"):
        publish_bundle_generation(manifest)


def test_new_lane_uses_json_fallback_only_when_symlinks_are_unsupported(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = _write_basic_bundle(tmp_path, run_id="unsupported-symlink")

    def unsupported_symlink(*_args: object, **_kwargs: object) -> None:
        raise OSError(errno.EOPNOTSUPP, "symlink unsupported")

    monkeypatch.setattr(rooted_filesystem.os, "symlink", unsupported_symlink)

    result = publish_bundle_generation(manifest)

    assert result.pointer_kind == "json_pointer"
    assert result.current_pointer_path.name == generation_mod.CURRENT_POINTER_JSON_NAME
    assert resolve_bundle_manifest_path(result.current_pointer_path) == result.resolved_manifest_path


def test_new_lane_permission_failure_does_not_downgrade_to_json_pointer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = _write_basic_bundle(tmp_path, run_id="permission-denied")

    def denied_symlink(*_args: object, **_kwargs: object) -> None:
        raise OSError(errno.EACCES, "symlink denied")

    monkeypatch.setattr(rooted_filesystem.os, "symlink", denied_symlink)

    with pytest.raises(BundleGenerationError, match="descriptor-bound current symlink"):
        publish_bundle_generation(manifest)

    lane = generation_mod.generation_lane_root(tmp_path, "demo")
    assert not os.path.lexists(lane / generation_mod.CURRENT_LINK_NAME)
    assert not (lane / generation_mod.CURRENT_POINTER_JSON_NAME).exists()


def test_lane_directory_swap_after_pointer_switch_is_reported_as_failed_rollback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_manifest = _write_basic_bundle(
        tmp_path, canonical_bytes=b"first\n", run_id="lane-first"
    )
    first = publish_bundle_generation(first_manifest)
    second_manifest = _write_basic_bundle(
        tmp_path, canonical_bytes=b"second\n", run_id="lane-second"
    )
    lane = generation_mod.generation_lane_root(tmp_path, "demo")
    displaced = tmp_path / "displaced-generation-lane"
    original = generation_mod._publish_current_pointer

    def switch_then_swap_lane(generations_root: Path, **kwargs):
        result = original(generations_root, **kwargs)
        generations_root.rename(displaced)
        generations_root.mkdir()
        return result

    monkeypatch.setattr(
        generation_mod, "_publish_current_pointer", switch_then_swap_lane
    )

    with pytest.raises(BundleGenerationError, match="rollback also failed"):
        publish_bundle_generation(second_manifest)

    assert not os.path.lexists(lane / generation_mod.CURRENT_LINK_NAME)
    displaced_target = os.readlink(displaced / generation_mod.CURRENT_LINK_NAME)
    assert displaced_target != first.generation_id
    assert (displaced / displaced_target).is_dir()


def test_pre_switch_symlink_change_refuses_blind_overwrite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = publish_bundle_generation(
        _write_basic_bundle(
            tmp_path, canonical_bytes=b"first\n", run_id="snapshot-first"
        )
    )
    third = publish_bundle_generation(
        _write_basic_bundle(
            tmp_path, canonical_bytes=b"third\n", run_id="snapshot-third"
        )
    )
    lane = generation_mod.generation_lane_root(tmp_path, "demo")
    generation_mod._write_current_symlink(lane, first.generation_id)
    second_manifest = _write_basic_bundle(
        tmp_path, canonical_bytes=b"second\n", run_id="snapshot-second"
    )
    original_install = generation_mod._install_generation

    def install_then_change_pointer(*args, **kwargs):
        result = original_install(*args, **kwargs)
        generation_mod._write_current_symlink(lane, third.generation_id)
        return result

    monkeypatch.setattr(
        generation_mod, "_install_generation", install_then_change_pointer
    )

    with pytest.raises(BundleGenerationError, match="refusing blind overwrite"):
        publish_bundle_generation(second_manifest)

    assert os.readlink(lane / generation_mod.CURRENT_LINK_NAME) == third.generation_id


def test_pre_switch_json_change_refuses_blind_overwrite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unsupported_symlink(*_args: object, **_kwargs: object):
        raise NotImplementedError("symlink unsupported")

    monkeypatch.setattr(
        generation_mod, "_write_current_symlink", unsupported_symlink
    )
    first = publish_bundle_generation(
        _write_basic_bundle(
            tmp_path, canonical_bytes=b"first\n", run_id="json-snapshot-first"
        )
    )
    first_payload = first.current_pointer_path.read_bytes()
    third = publish_bundle_generation(
        _write_basic_bundle(
            tmp_path, canonical_bytes=b"third\n", run_id="json-snapshot-third"
        )
    )
    third_payload = third.current_pointer_path.read_bytes()
    generation_mod.atomic_write_bytes(first.current_pointer_path, first_payload)
    second_manifest = _write_basic_bundle(
        tmp_path, canonical_bytes=b"second\n", run_id="json-snapshot-second"
    )
    original_install = generation_mod._install_generation

    def install_then_change_pointer(*args, **kwargs):
        result = original_install(*args, **kwargs)
        generation_mod.atomic_write_bytes(first.current_pointer_path, third_payload)
        return result

    monkeypatch.setattr(
        generation_mod, "_install_generation", install_then_change_pointer
    )

    with pytest.raises(BundleGenerationError, match="refusing blind overwrite"):
        publish_bundle_generation(second_manifest)

    assert first.current_pointer_path.read_bytes() == third_payload
