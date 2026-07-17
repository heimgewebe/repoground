from __future__ import annotations

import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from merger.repoground.core import (
    external_manifest_generation as external_manifest_generation_module,
)
from merger.repoground.core.external_manifest_reference import (
    ExternalManifestReferenceError,
    publication_generation_pointer_path,
    publish_external_manifest_references,
    read_external_manifest_publication,
    recover_external_manifest_publication,
)


def write_bundle(tmp_path: Path) -> Path:
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    canonical_bytes = b"hello world\n"
    reading_pack_bytes = b"pack\n"
    (bundle_dir / "heimgewebe_katalog_merge.md").write_bytes(canonical_bytes)
    (bundle_dir / "heimgewebe_katalog_merge.agent_reading_pack.md").write_bytes(
        reading_pack_bytes
    )
    bundle = {
        "kind": "repolens.bundle.manifest",
        "version": "1.0",
        "run_id": "run-1",
        "created_at": "2026-07-06T13:00:00Z",
        "generator": {"name": "repobrief", "version": "dev", "config_sha256": "a" * 64},
        "artifacts": [
            {
                "role": "canonical_md",
                "path": "heimgewebe_katalog_merge.md",
                "content_type": "text/markdown",
                "bytes": len(canonical_bytes),
                "sha256": hashlib.sha256(canonical_bytes).hexdigest(),
            },
            {
                "role": "agent_reading_pack",
                "path": "heimgewebe_katalog_merge.agent_reading_pack.md",
                "content_type": "text/markdown",
                "bytes": len(reading_pack_bytes),
                "sha256": hashlib.sha256(reading_pack_bytes).hexdigest(),
            },
        ],
        "links": {},
        "capabilities": {},
        "snapshot_provenance": {
            "version": "v1",
            "repositories": [
                {
                    "name": "heimgewebe-katalog",
                    "repo_root": None,
                    "repo_remote": "git@github.com:heimgewebe/heimgewebe-katalog.git",
                    "git_commit": "d" * 40,
                    "git_dirty": False,
                    "git_branch": "main",
                    "provenance_status": "present",
                    "freshness_basis": "git_commit",
                }
            ],
            "does_not_establish": ["freshness_against_remote"],
        },
    }
    path = bundle_dir / "heimgewebe_katalog_merge.bundle.manifest.json"
    path.write_text(json.dumps(bundle), encoding="utf-8")
    return path


def write_bundle_variant(
    tmp_path: Path,
    *,
    canonical_bytes: bytes,
    created_at: str,
    run_id: str,
) -> Path:
    path = write_bundle(tmp_path)
    artifact_path = path.parent / "heimgewebe_katalog_merge.md"
    artifact_path.write_bytes(canonical_bytes)
    bundle = json.loads(path.read_text(encoding="utf-8"))
    bundle["run_id"] = run_id
    bundle["created_at"] = created_at
    canonical_row = next(
        row for row in bundle["artifacts"] if row["role"] == "canonical_md"
    )
    canonical_row["bytes"] = len(canonical_bytes)
    canonical_row["sha256"] = hashlib.sha256(canonical_bytes).hexdigest()
    path.write_text(json.dumps(bundle), encoding="utf-8")
    return path


def test_publish_commits_one_verified_generation_for_all_families(
    tmp_path: Path,
) -> None:
    root = tmp_path / "published"
    bundle_path = write_bundle(tmp_path / "source")

    result = publish_external_manifest_references(
        bundle_path,
        root,
        repository="heimgewebe-katalog",
        ref="main",
    )
    selection = read_external_manifest_publication(
        root,
        repository="heimgewebe-katalog",
        ref="main",
    )

    generation_id = result["generation"]["id"]
    assert result["status"] == "committed"
    assert selection["status"] == "committed"
    assert selection["generationId"] == generation_id
    assert Path(selection["pointerPath"]) == publication_generation_pointer_path(
        root,
        repository="heimgewebe-katalog",
        ref="main",
    )
    assert {row["artifactFamily"] for row in selection["published"]} == {
        "lenskit",
        "repobrief",
    }
    assert {row["generationId"] for row in selection["published"]} == {generation_id}
    descriptor = json.loads(
        Path(selection["descriptorPath"]).read_text(encoding="utf-8")
    )
    assert {row["generatedAt"] for row in selection["published"]} == {
        descriptor["generatedAt"]
    }
    assert {row["generationId"] for row in result["authoritativePublished"]} == {
        generation_id
    }
    for row in result["published"]:
        compatibility = json.loads(Path(row["path"]).read_text(encoding="utf-8"))
        binding = compatibility["publicationGeneration"]
        assert binding["id"] == generation_id
        assert binding["authoritative"] is False
        assert binding["selectionRule"] == (
            "read_pointer_once_then_verify_complete_generation"
        )


def test_publish_failure_between_family_writes_keeps_old_generation_authoritative(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "published"
    first_bundle = write_bundle_variant(
        tmp_path / "first",
        canonical_bytes=b"first generation\n",
        created_at="2026-07-06T13:00:00Z",
        run_id="run-first",
    )
    first = publish_external_manifest_references(
        first_bundle,
        root,
        repository="heimgewebe-katalog",
        ref="main",
    )
    second_bundle = write_bundle_variant(
        tmp_path / "second",
        canonical_bytes=b"second generation\n",
        created_at="2026-07-06T14:00:00Z",
        run_id="run-second",
    )

    original = external_manifest_generation_module._write_generation_manifest_file
    calls = 0

    def fail_between_family_writes(path: Path, data: dict[str, object]) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ExternalManifestReferenceError("injected between family writes")
        original(path, data)

    monkeypatch.setattr(
        external_manifest_generation_module,
        "_write_generation_manifest_file",
        fail_between_family_writes,
    )

    with pytest.raises(
        ExternalManifestReferenceError,
        match="injected between family writes",
    ):
        publish_external_manifest_references(
            second_bundle,
            root,
            repository="heimgewebe-katalog",
            ref="main",
        )

    selection = read_external_manifest_publication(
        root,
        repository="heimgewebe-katalog",
        ref="main",
    )
    assert selection["generationId"] == first["generation"]["id"]
    assert {row["generationId"] for row in selection["published"]} == {
        first["generation"]["id"]
    }


def test_publish_pointer_failure_keeps_old_generation_authoritative(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "published"
    first = publish_external_manifest_references(
        write_bundle_variant(
            tmp_path / "first",
            canonical_bytes=b"first\n",
            created_at="2026-07-06T13:00:00Z",
            run_id="run-first",
        ),
        root,
        repository="heimgewebe-katalog",
        ref="main",
    )

    def fail_pointer_write(path: Path, data: dict[str, object]) -> dict[str, object]:
        raise ExternalManifestReferenceError("injected pointer failure")

    monkeypatch.setattr(
        external_manifest_generation_module,
        "_write_generation_pointer",
        fail_pointer_write,
    )
    with pytest.raises(
        ExternalManifestReferenceError, match="injected pointer failure"
    ):
        publish_external_manifest_references(
            write_bundle_variant(
                tmp_path / "second",
                canonical_bytes=b"second\n",
                created_at="2026-07-06T14:00:00Z",
                run_id="run-second",
            ),
            root,
            repository="heimgewebe-katalog",
            ref="main",
        )

    selection = read_external_manifest_publication(
        root,
        repository="heimgewebe-katalog",
        ref="main",
    )
    assert selection["generationId"] == first["generation"]["id"]


def test_publish_after_pointer_failure_degrades_only_legacy_projection_and_recovers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "published"
    publish_external_manifest_references(
        write_bundle_variant(
            tmp_path / "first",
            canonical_bytes=b"first\n",
            created_at="2026-07-06T13:00:00Z",
            run_id="run-first",
        ),
        root,
        repository="heimgewebe-katalog",
        ref="main",
    )
    second_bundle = write_bundle_variant(
        tmp_path / "second",
        canonical_bytes=b"second\n",
        created_at="2026-07-06T14:00:00Z",
        run_id="run-second",
    )

    original = external_manifest_generation_module._write_compatibility_manifest
    calls = 0

    def fail_second_compatibility(
        path: Path,
        data: dict[str, object],
    ) -> dict[str, object]:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ExternalManifestReferenceError("injected compatibility failure")
        return original(path, data)

    monkeypatch.setattr(
        external_manifest_generation_module,
        "_write_compatibility_manifest",
        fail_second_compatibility,
    )
    result = publish_external_manifest_references(
        second_bundle,
        root,
        repository="heimgewebe-katalog",
        ref="main",
    )

    assert result["status"] == "committed_compatibility_degraded"
    assert result["compatibility"]["status"] == "degraded"
    assert len(result["compatibility"]["errors"]) == 1
    selection = read_external_manifest_publication(
        root,
        repository="heimgewebe-katalog",
        ref="main",
    )
    assert selection["generationId"] == result["generation"]["id"]
    assert {row["generationId"] for row in selection["published"]} == {
        result["generation"]["id"]
    }

    monkeypatch.setattr(
        external_manifest_generation_module,
        "_write_compatibility_manifest",
        original,
    )
    recovery = recover_external_manifest_publication(
        root,
        repository="heimgewebe-katalog",
        ref="main",
    )
    assert recovery["status"] == "recovered"
    assert recovery["generationId"] == result["generation"]["id"]
    for row in recovery["compatibility"]["published"]:
        stable_manifest = json.loads(Path(row["path"]).read_text(encoding="utf-8"))
        binding = stable_manifest["publicationGeneration"]
        assert binding["id"] == result["generation"]["id"]
        assert binding["authoritative"] is False


def test_publish_reports_uncertain_pointer_durability_but_readback_is_complete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "published"
    bundle_path = write_bundle(tmp_path / "source")
    original = external_manifest_generation_module._fsync_directory

    def fail_current_pointer_directory(path: Path) -> None:
        if "_current" in path.parts:
            raise OSError("injected current-pointer directory fsync failure")
        original(path)

    monkeypatch.setattr(
        external_manifest_generation_module,
        "_fsync_directory",
        fail_current_pointer_directory,
    )
    result = publish_external_manifest_references(
        bundle_path,
        root,
        repository="heimgewebe-katalog",
        ref="main",
    )

    assert result["status"] == "committed_durability_uncertain"
    assert result["generation"]["pointerDurability"] == (
        "uncertain_after_directory_fsync"
    )
    selection = read_external_manifest_publication(
        root,
        repository="heimgewebe-katalog",
        ref="main",
    )
    assert selection["generationId"] == result["generation"]["id"]
    assert {row["generationId"] for row in selection["published"]} == {
        result["generation"]["id"]
    }


def test_generation_reader_rejects_tampered_family_manifest(tmp_path: Path) -> None:
    root = tmp_path / "published"
    result = publish_external_manifest_references(
        write_bundle(tmp_path / "source"),
        root,
        repository="heimgewebe-katalog",
        ref="main",
    )
    family_path = Path(result["authoritativePublished"][0]["path"])
    manifest = json.loads(family_path.read_text(encoding="utf-8"))
    manifest["generatedAt"] = "tampered"
    family_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ExternalManifestReferenceError, match="integrity mismatch"):
        read_external_manifest_publication(
            root,
            repository="heimgewebe-katalog",
            ref="main",
        )


def test_generation_reader_rejects_symlinked_pointer(tmp_path: Path) -> None:
    root = tmp_path / "published"
    publish_external_manifest_references(
        write_bundle(tmp_path / "source"),
        root,
        repository="heimgewebe-katalog",
        ref="main",
    )
    pointer_path = publication_generation_pointer_path(
        root,
        repository="heimgewebe-katalog",
        ref="main",
    )
    outside = tmp_path / "outside-pointer.json"
    outside.write_bytes(pointer_path.read_bytes())
    pointer_path.unlink()
    pointer_path.symlink_to(outside)

    with pytest.raises(
        ExternalManifestReferenceError,
        match="existing regular file",
    ):
        read_external_manifest_publication(
            root,
            repository="heimgewebe-katalog",
            ref="main",
        )


def test_concurrent_publishers_are_serialized_by_lane_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "published"
    first_bundle = write_bundle_variant(
        tmp_path / "first",
        canonical_bytes=b"first concurrent generation\n",
        created_at="2026-07-06T13:00:00Z",
        run_id="run-first",
    )
    second_bundle = write_bundle_variant(
        tmp_path / "second",
        canonical_bytes=b"second concurrent generation\n",
        created_at="2026-07-06T14:00:00Z",
        run_id="run-second",
    )
    original = external_manifest_generation_module._write_generation_pointer
    first_entered = threading.Event()
    release_first = threading.Event()
    second_entered = threading.Event()
    counter_lock = threading.Lock()
    calls = 0

    def block_first_pointer(
        path: Path,
        data: dict[str, object],
    ) -> dict[str, object]:
        nonlocal calls
        with counter_lock:
            calls += 1
            call_number = calls
        if call_number == 1:
            first_entered.set()
            assert release_first.wait(timeout=5)
        else:
            second_entered.set()
        return original(path, data)

    monkeypatch.setattr(
        external_manifest_generation_module,
        "_write_generation_pointer",
        block_first_pointer,
    )

    def publish(path: Path) -> dict[str, object]:
        return publish_external_manifest_references(
            path,
            root,
            repository="heimgewebe-katalog",
            ref="main",
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(publish, first_bundle)
        assert first_entered.wait(timeout=5)
        second_future = executor.submit(publish, second_bundle)
        assert second_entered.wait(timeout=0.2) is False
        release_first.set()
        first_result = first_future.result(timeout=10)
        second_result = second_future.result(timeout=10)

    assert first_result["status"] == "committed"
    assert second_result["status"] == "committed"
    assert first_result["generation"]["id"] != second_result["generation"]["id"]
    selection = read_external_manifest_publication(
        root,
        repository="heimgewebe-katalog",
        ref="main",
    )
    assert selection["generationId"] == second_result["generation"]["id"]
    assert {row["generationId"] for row in selection["published"]} == {
        second_result["generation"]["id"]
    }


def test_republishing_identical_bundle_reuses_immutable_generation(
    tmp_path: Path,
) -> None:
    root = tmp_path / "published"
    bundle_path = write_bundle(tmp_path / "source")
    first = publish_external_manifest_references(
        bundle_path,
        root,
        repository="heimgewebe-katalog",
        ref="main",
    )
    second = publish_external_manifest_references(
        bundle_path,
        root,
        repository="heimgewebe-katalog",
        ref="main",
    )

    assert second["generation"]["id"] == first["generation"]["id"]
    assert first["generation"]["reused"] is False
    assert second["generation"]["reused"] is True


def test_same_bundle_publishers_serialize_before_materialization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "published"
    bundle_path = write_bundle(tmp_path / "source")
    original = external_manifest_generation_module.materialize_external_bundle
    first_entered = threading.Event()
    release_first = threading.Event()
    second_entered = threading.Event()
    counter_lock = threading.Lock()
    calls = 0

    def block_first_materialization(
        *args: object, **kwargs: object
    ) -> dict[str, object]:
        nonlocal calls
        with counter_lock:
            calls += 1
            call_number = calls
        if call_number == 1:
            first_entered.set()
            assert release_first.wait(timeout=5)
        else:
            second_entered.set()
        return original(*args, **kwargs)

    monkeypatch.setattr(
        external_manifest_generation_module,
        "materialize_external_bundle",
        block_first_materialization,
    )

    def publish() -> dict[str, object]:
        return publish_external_manifest_references(
            bundle_path,
            root,
            repository="heimgewebe-katalog",
            ref="main",
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(publish)
        assert first_entered.wait(timeout=5)
        second_future = executor.submit(publish)
        assert second_entered.wait(timeout=0.2) is False
        release_first.set()
        first_result = first_future.result(timeout=10)
        second_result = second_future.result(timeout=10)

    assert first_result["status"] == "committed"
    assert second_result["status"] == "committed"
    assert first_result["generation"]["id"] == second_result["generation"]["id"]
    assert first_result["materialization"]["reused"] is False
    assert second_result["materialization"]["reused"] is True
    assert first_result["generation"]["reused"] is False
    assert second_result["generation"]["reused"] is True


def test_generation_reader_rejects_pointer_descriptor_traversal(tmp_path: Path) -> None:
    root = tmp_path / "published"
    publish_external_manifest_references(
        write_bundle(tmp_path / "source"),
        root,
        repository="heimgewebe-katalog",
        ref="main",
    )
    pointer_path = publication_generation_pointer_path(
        root,
        repository="heimgewebe-katalog",
        ref="main",
    )
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    pointer["generationDescriptor"]["path"] = "../../../../outside.json"
    pointer_path.write_text(json.dumps(pointer), encoding="utf-8")

    with pytest.raises(
        ExternalManifestReferenceError,
        match="must stay inside publication_root",
    ):
        read_external_manifest_publication(
            root,
            repository="heimgewebe-katalog",
            ref="main",
        )


def test_generation_reader_rejects_pointer_family_metadata_mismatch(
    tmp_path: Path,
) -> None:
    root = tmp_path / "published"
    publish_external_manifest_references(
        write_bundle(tmp_path / "source"),
        root,
        repository="heimgewebe-katalog",
        ref="main",
    )
    pointer_path = publication_generation_pointer_path(
        root,
        repository="heimgewebe-katalog",
        ref="main",
    )
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    pointer["artifactFamilies"] = ["repobrief"]
    pointer_path.write_bytes(external_manifest_generation_module._json_bytes(pointer))

    with pytest.raises(
        ExternalManifestReferenceError,
        match="pointer and descriptor metadata mismatch",
    ):
        read_external_manifest_publication(
            root,
            repository="heimgewebe-katalog",
            ref="main",
        )


def test_generation_reader_rejects_rehashed_wrong_pointer_binding(
    tmp_path: Path,
) -> None:
    root = tmp_path / "published"
    publish_external_manifest_references(
        write_bundle(tmp_path / "source"),
        root,
        repository="heimgewebe-katalog",
        ref="main",
    )
    pointer_path = publication_generation_pointer_path(
        root,
        repository="heimgewebe-katalog",
        ref="main",
    )
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    descriptor_path = root / pointer["generationDescriptor"]["path"]
    descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
    family_row = descriptor["familyManifests"][0]
    family_path = descriptor_path.parent / family_row["path"]
    family_manifest = json.loads(family_path.read_text(encoding="utf-8"))
    family_manifest["publicationGeneration"]["pointerPath"] = "wrong-pointer.json"
    family_payload = external_manifest_generation_module._json_bytes(family_manifest)
    family_path.write_bytes(family_payload)
    family_row["bytes"] = len(family_payload)
    family_row["sha256"] = hashlib.sha256(family_payload).hexdigest()

    descriptor_payload = external_manifest_generation_module._json_bytes(descriptor)
    descriptor_path.write_bytes(descriptor_payload)
    pointer["generationDescriptor"]["bytes"] = len(descriptor_payload)
    pointer["generationDescriptor"]["sha256"] = hashlib.sha256(
        descriptor_payload
    ).hexdigest()
    pointer_path.write_bytes(external_manifest_generation_module._json_bytes(pointer))

    with pytest.raises(
        ExternalManifestReferenceError,
        match="generation manifest binding mismatch",
    ):
        read_external_manifest_publication(
            root,
            repository="heimgewebe-katalog",
            ref="main",
        )


def test_publish_reports_uncertain_compatibility_projection_truthfully(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "published"
    bundle_path = write_bundle(tmp_path / "source")
    original = external_manifest_generation_module._write_compatibility_manifest
    calls = 0

    def report_uncertain_compatibility(
        path: Path,
        data: dict[str, object],
    ) -> dict[str, object]:
        nonlocal calls
        calls += 1
        result = original(path, data)
        if calls == 1:
            return {**result, "durability": "uncertain_after_directory_fsync"}
        return result

    monkeypatch.setattr(
        external_manifest_generation_module,
        "_write_compatibility_manifest",
        report_uncertain_compatibility,
    )
    result = publish_external_manifest_references(
        bundle_path,
        root,
        repository="heimgewebe-katalog",
        ref="main",
    )

    assert result["status"] == "committed_compatibility_degraded"
    assert result["compatibility"]["status"] == "uncertain"
    assert result["compatibility"]["errors"] == []
    assert result["compatibility"]["uncertain"] == [
        {
            "artifactFamily": "lenskit",
            "durability": "uncertain_after_directory_fsync",
        }
    ]
    selection = read_external_manifest_publication(
        root,
        repository="heimgewebe-katalog",
        ref="main",
    )
    assert selection["generationId"] == result["generation"]["id"]


def test_generation_reader_rejects_rehashed_selection_rule_change(
    tmp_path: Path,
) -> None:
    root = tmp_path / "published"
    publish_external_manifest_references(
        write_bundle(tmp_path / "source"),
        root,
        repository="heimgewebe-katalog",
        ref="main",
    )
    pointer_path = publication_generation_pointer_path(
        root,
        repository="heimgewebe-katalog",
        ref="main",
    )
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    pointer["selectionRule"] = "select newest directory"
    pointer_path.write_bytes(external_manifest_generation_module._json_bytes(pointer))

    with pytest.raises(
        ExternalManifestReferenceError,
        match="generation pointer contract mismatch",
    ):
        read_external_manifest_publication(
            root,
            repository="heimgewebe-katalog",
            ref="main",
        )


def test_generation_reader_rejects_rehashed_family_source_mismatch(
    tmp_path: Path,
) -> None:
    root = tmp_path / "published"
    publish_external_manifest_references(
        write_bundle(tmp_path / "source"),
        root,
        repository="heimgewebe-katalog",
        ref="main",
    )
    pointer_path = publication_generation_pointer_path(
        root,
        repository="heimgewebe-katalog",
        ref="main",
    )
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    descriptor_path = root / pointer["generationDescriptor"]["path"]
    descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
    family_row = descriptor["familyManifests"][0]
    family_path = descriptor_path.parent / family_row["path"]
    family_manifest = json.loads(family_path.read_text(encoding="utf-8"))
    family_manifest["bundleManifest"]["sha256"] = "0" * 64
    family_payload = external_manifest_generation_module._json_bytes(family_manifest)
    family_path.write_bytes(family_payload)
    family_row["bytes"] = len(family_payload)
    family_row["sha256"] = hashlib.sha256(family_payload).hexdigest()

    descriptor_payload = external_manifest_generation_module._json_bytes(descriptor)
    descriptor_path.write_bytes(descriptor_payload)
    pointer["generationDescriptor"]["bytes"] = len(descriptor_payload)
    pointer["generationDescriptor"]["sha256"] = hashlib.sha256(
        descriptor_payload
    ).hexdigest()
    pointer_path.write_bytes(external_manifest_generation_module._json_bytes(pointer))

    with pytest.raises(
        ExternalManifestReferenceError,
        match="generation manifest binding mismatch",
    ):
        read_external_manifest_publication(
            root,
            repository="heimgewebe-katalog",
            ref="main",
        )
