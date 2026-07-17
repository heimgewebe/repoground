from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from merger.repoground.core import external_manifest_generation
from merger.repoground.core import external_manifest_reference
from merger.repoground.core import rooted_filesystem
from merger.repoground.core.external_manifest_reference import (
    ExternalManifestReferenceError,
    publication_generation_pointer_path,
    publish_external_manifest_references,
    read_external_manifest_publication,
)


def write_bundle(root: Path) -> Path:
    bundle_dir = root / "bundle"
    bundle_dir.mkdir(parents=True)
    artifact = b"trusted artifact\n"
    (bundle_dir / "artifact.md").write_bytes(artifact)
    manifest = {
        "kind": "repolens.bundle.manifest",
        "version": "1.0",
        "run_id": "dirfd-run",
        "created_at": "2026-07-15T03:00:00Z",
        "generator": {
            "name": "repobrief",
            "version": "dev",
            "config_sha256": "a" * 64,
        },
        "artifacts": [
            {
                "role": "canonical_md",
                "path": "artifact.md",
                "content_type": "text/markdown",
                "bytes": len(artifact),
                "sha256": hashlib.sha256(artifact).hexdigest(),
            }
        ],
        "links": {},
        "capabilities": {},
        "snapshot_provenance": {
            "version": "v1",
            "repositories": [],
            "does_not_establish": ["freshness_against_remote"],
        },
    }
    path = bundle_dir / "bundle.manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def test_publish_rejects_symlinked_publication_root_component(tmp_path: Path) -> None:
    bundle = write_bundle(tmp_path / "source")
    outside = tmp_path / "outside"
    outside.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(outside, target_is_directory=True)

    with pytest.raises(
        ExternalManifestReferenceError,
        match="trusted directory identity|trusted real directory",
    ):
        publish_external_manifest_references(
            bundle,
            linked / "publication",
            repository="sample",
            ref="main",
        )

    assert list(outside.iterdir()) == []


def test_publish_fails_closed_when_root_identity_changes_before_pointer_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = write_bundle(tmp_path / "source")
    root = tmp_path / "publication"
    moved = tmp_path / "publication-before-swap"
    original = external_manifest_generation._write_generation_pointer
    swapped = False

    def swap_root_then_write(path: Path, data: dict[str, object]) -> dict[str, object]:
        nonlocal swapped
        if not swapped:
            swapped = True
            root.rename(moved)
            root.mkdir()
        return original(path, data)

    monkeypatch.setattr(
        external_manifest_generation,
        "_write_generation_pointer",
        swap_root_then_write,
    )

    with pytest.raises(ExternalManifestReferenceError, match="trusted"):
        publish_external_manifest_references(
            bundle,
            root,
            repository="sample",
            ref="main",
        )

    current_pointer = publication_generation_pointer_path(
        root,
        repository="sample",
        ref="main",
    )
    moved_pointer = publication_generation_pointer_path(
        moved,
        repository="sample",
        ref="main",
    )
    assert not current_pointer.exists()
    assert moved_pointer.is_file()


def test_publish_rejects_source_parent_replacement_before_materialization_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = write_bundle(tmp_path / "source")
    source_dir = bundle.parent
    moved_source = tmp_path / "source-bundle-before-swap"
    publication = tmp_path / "publication"
    original = external_manifest_reference.copy_verified_file
    swapped = False

    def swap_source_then_copy(*args: object, **kwargs: object) -> None:
        nonlocal swapped
        if not swapped:
            swapped = True
            source_dir.rename(moved_source)
            source_dir.mkdir()
        original(*args, **kwargs)

    monkeypatch.setattr(
        external_manifest_reference,
        "copy_verified_file",
        swap_source_then_copy,
    )

    with pytest.raises(ExternalManifestReferenceError, match="source|trusted"):
        publish_external_manifest_references(
            bundle,
            publication,
            repository="sample",
            ref="main",
        )

    assert not publication_generation_pointer_path(
        publication,
        repository="sample",
        ref="main",
    ).exists()


def test_pointer_parent_swap_is_detected_and_not_exposed_as_current(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = write_bundle(tmp_path / "source")
    root = tmp_path / "publication"
    pointer_parent = root / "external" / "_current" / "sample" / "main"
    moved_parent = root / "external" / "_current" / "sample" / "main-before-swap"
    original = rooted_filesystem._write_all
    swapped = False

    def swap_pointer_parent(fd: int, payload: bytes) -> None:
        nonlocal swapped
        if not swapped and b"external_manifest_generation_pointer" in payload:
            swapped = True
            pointer_parent.rename(moved_parent)
            pointer_parent.mkdir()
        original(fd, payload)

    monkeypatch.setattr(rooted_filesystem, "_write_all", swap_pointer_parent)

    with pytest.raises(
        ExternalManifestReferenceError, match="trusted descriptors|identity"
    ):
        publish_external_manifest_references(
            bundle,
            root,
            repository="sample",
            ref="main",
        )

    assert not (pointer_parent / "generation.json").exists()
    assert (moved_parent / "generation.json").is_file()


def test_reader_rejects_root_replacement_during_readback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = write_bundle(tmp_path / "source")
    root = tmp_path / "publication"
    publish_external_manifest_references(
        bundle,
        root,
        repository="sample",
        ref="main",
    )
    moved = tmp_path / "publication-before-read-swap"
    original = external_manifest_generation._read_json_regular_file
    swapped = False

    def swap_root_then_read(
        path: Path, label: str
    ) -> tuple[dict[str, object], int, str]:
        nonlocal swapped
        if not swapped:
            swapped = True
            root.rename(moved)
            root.mkdir()
        return original(path, label)

    monkeypatch.setattr(
        external_manifest_generation,
        "_read_json_regular_file",
        swap_root_then_read,
    )

    with pytest.raises(
        ExternalManifestReferenceError, match="stable identity|trusted root identity"
    ):
        read_external_manifest_publication(
            root,
            repository="sample",
            ref="main",
        )


def test_unsupported_platform_fails_closed_end_to_end(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = write_bundle(tmp_path / "source")
    root = tmp_path / "publication"
    monkeypatch.setattr(
        rooted_filesystem,
        "_required_primitives_supported",
        lambda: False,
    )

    with pytest.raises(
        ExternalManifestReferenceError, match="unsupported|trusted directory identity"
    ):
        publish_external_manifest_references(
            bundle,
            root,
            repository="sample",
            ref="main",
        )

    assert not root.exists()


def test_successful_publication_reports_dirfd_binding(tmp_path: Path) -> None:
    result = publish_external_manifest_references(
        write_bundle(tmp_path / "source"),
        tmp_path / "publication",
        repository="sample",
        ref="main",
    )

    assert result["status"] == "committed"
    assert result["generation"]["filesystemBinding"] == "trusted_dirfd_openat"
