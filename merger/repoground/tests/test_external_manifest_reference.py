from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from merger.repoground.core import (
    external_manifest_reference as external_manifest_reference_module,
)
from merger.repoground.core.external_manifest_reference import (
    ExternalManifestReferenceError,
    build_external_manifest_reference,
    publication_manifest_path,
    publish_external_manifest_references,
    write_external_manifest_reference,
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


def test_builds_system_catalog_repobrief_manifest_reference(tmp_path: Path) -> None:
    bundle_path = write_bundle(tmp_path)
    out = (
        tmp_path
        / "external"
        / "repobrief"
        / "heimgewebe-katalog"
        / "main"
        / "manifest.json"
    )

    result = build_external_manifest_reference(
        bundle_path,
        repository="heimgewebe-katalog",
        ref="main",
        artifact_family="repobrief",
        output_path=out,
    )

    assert result["kind"] == "repobrief_bundle_manifest"
    assert result["bundleManifest"]["kind"] == "repolens.bundle.manifest"
    assert result["bundleManifest"]["version"] == "1.0"
    assert result["generatedAt"] == "2026-07-06T13:00:00Z"
    assert result["freshnessBasis"] == "bundle_manifest.created_at"
    assert result["repository"] == "heimgewebe-katalog"
    assert result["ref"] == "main"
    assert (
        result["bundleManifest"]["path"]
        == "../../../../bundle/heimgewebe_katalog_merge.bundle.manifest.json"
    )
    assert result["snapshotProvenance"]["repositories"][0]["git_commit"] == "d" * 40
    assert [row["role"] for row in result["artifacts"]] == [
        "agent_reading_pack",
        "canonical_md",
    ]
    assert "claim_truth" in result["doesNotEstablish"]
    assert "dump_generation_permission" in result["doesNotEstablish"]


def test_writes_manifest_reference_atomically(tmp_path: Path) -> None:
    bundle_path = write_bundle(tmp_path)
    out = (
        tmp_path
        / "external"
        / "lenskit"
        / "heimgewebe-katalog"
        / "main"
        / "manifest.json"
    )

    result = write_external_manifest_reference(
        bundle_path,
        out,
        repository="heimgewebe-katalog",
        ref="main",
        artifact_family="lenskit",
    )

    written = json.loads(out.read_text(encoding="utf-8"))
    assert written == result
    assert written["kind"] == "lenskit_bundle_manifest"


@pytest.mark.parametrize(
    ("repository", "ref"),
    [
        ("heimgewebe/heimgewebe-katalog", "main"),
        ("heimgewebe-katalog", "feature/x"),
        (" heimgewebe-katalog", "main"),
    ],
)
def test_rejects_registry_segments_with_slashes_or_whitespace(
    tmp_path: Path, repository: str, ref: str
) -> None:
    bundle_path = write_bundle(tmp_path)

    with pytest.raises(ExternalManifestReferenceError):
        build_external_manifest_reference(bundle_path, repository=repository, ref=ref)


def test_rejects_non_bundle_manifest(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps({"kind": "other", "created_at": "2026-07-06T13:00:00Z"}),
        encoding="utf-8",
    )

    with pytest.raises(
        ExternalManifestReferenceError, match="RepoGround v2 or documented legacy v1"
    ):
        build_external_manifest_reference(
            path, repository="heimgewebe-katalog", ref="main"
        )


def test_build_rejects_manifest_swapped_to_symlink_after_path_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle_path = write_bundle(tmp_path)
    outside = tmp_path / "outside.bundle.manifest.json"
    outside.write_bytes(bundle_path.read_bytes())
    original_guard = external_manifest_reference_module._require_inside_publication_root

    def swap_after_guard(path: Path, publication_root: Path | None) -> None:
        original_guard(path, publication_root)
        path.unlink()
        path.symlink_to(outside)

    monkeypatch.setattr(
        external_manifest_reference_module,
        "_require_inside_publication_root",
        swap_after_guard,
    )

    with pytest.raises(ExternalManifestReferenceError, match="existing regular file"):
        build_external_manifest_reference(
            bundle_path,
            repository="heimgewebe-katalog",
            ref="main",
            publication_root=tmp_path,
        )


def test_publication_manifest_path_uses_stable_external_layout(tmp_path: Path) -> None:
    path = publication_manifest_path(
        tmp_path / "published",
        repository="heimgewebe-katalog",
        ref="main",
        artifact_family="repobrief",
    )

    assert (
        path
        == tmp_path
        / "published"
        / "external"
        / "repobrief"
        / "heimgewebe-katalog"
        / "main"
        / "manifest.json"
    )


def test_publish_external_manifest_references_can_publish_one_family(
    tmp_path: Path,
) -> None:
    root = tmp_path / "published"
    bundle_path = write_bundle(root)

    result = publish_external_manifest_references(
        bundle_path,
        root,
        repository="heimgewebe-katalog",
        ref="main",
        artifact_families=["repobrief"],
    )

    assert [row["artifactFamily"] for row in result["published"]] == ["repobrief"]
    assert (
        root
        / "external"
        / "repobrief"
        / "heimgewebe-katalog"
        / "main"
        / "manifest.json"
    ).is_file()
    assert not (
        root / "external" / "lenskit" / "heimgewebe-katalog" / "main" / "manifest.json"
    ).exists()


def test_repobrief_cli_publishes_external_manifest_references(tmp_path: Path) -> None:
    from merger.repoground.cli.ground import main as repobrief_main

    root = tmp_path / "published"
    bundle_path = write_bundle(root)

    rc = repobrief_main(
        [
            "external-manifest",
            "publish",
            "--bundle-manifest",
            str(bundle_path),
            "--publication-root",
            str(root),
            "--repository",
            "heimgewebe-katalog",
            "--ref",
            "main",
        ]
    )

    assert rc == 0
    assert (
        root
        / "external"
        / "repobrief"
        / "heimgewebe-katalog"
        / "main"
        / "manifest.json"
    ).is_file()
    assert (
        root / "external" / "lenskit" / "heimgewebe-katalog" / "main" / "manifest.json"
    ).is_file()


def test_build_includes_linked_post_emit_health_sidecar(tmp_path: Path) -> None:
    bundle_path = write_bundle(tmp_path)
    sidecar = bundle_path.with_name("heimgewebe_katalog_merge.bundle_health.post.json")
    sidecar.write_text(
        '{"kind":"lenskit.post_emit_health","status":"pass"}\n', encoding="utf-8"
    )
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    bundle["links"]["post_emit_health_path"] = sidecar.name
    bundle_path.write_text(json.dumps(bundle), encoding="utf-8")

    result = build_external_manifest_reference(
        bundle_path,
        repository="heimgewebe-katalog",
        ref="main",
        artifact_family="repobrief",
    )

    row = next(
        artifact
        for artifact in result["artifacts"]
        if artifact["role"] == "post_emit_health"
    )
    assert row["path"] == "heimgewebe_katalog_merge.bundle_health.post.json"
    assert row["contentType"] == "application/json"
    assert row["bytes"] == sidecar.stat().st_size
    assert len(row["sha256"]) == 64


def test_publish_materializes_bundle_from_outside_publication_root(
    tmp_path: Path,
) -> None:
    bundle_path = write_bundle(tmp_path / "bundle-source")
    root = tmp_path / "published"

    result = publish_external_manifest_references(
        bundle_path,
        root,
        repository="heimgewebe-katalog",
        ref="main",
    )

    localized_manifest = Path(result["bundleManifest"])
    assert localized_manifest.is_file()
    assert localized_manifest.is_relative_to(root)
    assert localized_manifest != bundle_path
    assert (
        localized_manifest.parent.name
        == result["materialization"]["sourceManifestSha256"]
    )
    for family in ("lenskit", "repobrief"):
        manifest_path = (
            root / "external" / family / "heimgewebe-katalog" / "main" / "manifest.json"
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        resolved_bundle = (
            manifest_path.parent / manifest["bundleManifest"]["path"]
        ).resolve()
        assert resolved_bundle == localized_manifest
        assert (
            manifest["bundleManifest"]["sha256"]
            == hashlib.sha256(localized_manifest.read_bytes()).hexdigest()
        )
        for artifact in manifest["artifacts"]:
            resolved_artifact = (manifest_path.parent / artifact["path"]).resolve()
            assert resolved_artifact.is_relative_to(root)
            assert resolved_artifact.is_file()


def test_linked_sidecar_must_remain_inside_bundle_directory(tmp_path: Path) -> None:
    bundle_path = write_bundle(tmp_path)
    outside = tmp_path / "outside.bundle_health.post.json"
    outside.write_text("{}\n", encoding="utf-8")
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    bundle["links"]["post_emit_health_path"] = "../outside.bundle_health.post.json"
    bundle_path.write_text(json.dumps(bundle), encoding="utf-8")

    with pytest.raises(
        ExternalManifestReferenceError, match="inside the bundle directory"
    ):
        build_external_manifest_reference(
            bundle_path, repository="heimgewebe-katalog", ref="main"
        )


def test_external_manifest_refresh_rejects_output_outside_publication_root(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from merger.repoground.cli.ground import main as repobrief_main

    repo = tmp_path / "source"
    repo.mkdir()
    (repo / "README.md").write_text("# source\n", encoding="utf-8")
    publication_root = tmp_path / "published"
    outside = tmp_path / "legacy-output"

    rc = repobrief_main(
        [
            "external-manifest",
            "refresh",
            "--repo",
            str(repo),
            "--out",
            str(outside),
            "--publication-root",
            str(publication_root),
            "--repository",
            "source",
            "--ref",
            "main",
        ]
    )

    captured = capsys.readouterr()
    assert rc == 2
    assert "output directory must be inside publication_root" in captured.err
    assert not outside.exists()


def test_external_manifest_refresh_creates_portable_bundle_and_references(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from merger.repoground.cli.ground import main as repobrief_main

    repo = tmp_path / "source"
    repo.mkdir()
    (repo / "README.md").write_text("# source\n", encoding="utf-8")
    publication_root = tmp_path / "published"
    out = publication_root / "bundles" / "source" / "main" / "run-1"

    rc = repobrief_main(
        [
            "external-manifest",
            "refresh",
            "--repo",
            str(repo),
            "--out",
            str(out),
            "--publication-root",
            str(publication_root),
            "--repository",
            "source",
            "--ref",
            "main",
            "--profile",
            "agent-portable",
            "--redact-secrets",
        ]
    )

    captured = capsys.readouterr()
    result = json.loads(captured.out)
    source_bundle_manifest = Path(result["snapshot"]["bundle_manifest"])
    localized_bundle_manifest = Path(result["publication"]["bundleManifest"])
    assert rc == 0
    assert source_bundle_manifest.is_file()
    assert source_bundle_manifest.is_relative_to(publication_root)
    assert localized_bundle_manifest.is_file()
    localized_document = json.loads(localized_bundle_manifest.read_text(encoding="utf-8"))
    assert localized_document["kind"] == "repoground.bundle.manifest"
    assert localized_document["version"] == "2.0"
    assert localized_bundle_manifest.is_relative_to(publication_root)
    assert localized_bundle_manifest != source_bundle_manifest
    for family in ("lenskit", "repobrief"):
        manifest = (
            publication_root / "external" / family / "source" / "main" / "manifest.json"
        )
        assert manifest.is_file()
        published = json.loads(manifest.read_text(encoding="utf-8"))
        resolved_bundle = (
            manifest.parent / published["bundleManifest"]["path"]
        ).resolve()
        assert resolved_bundle == localized_bundle_manifest.resolve()
        for artifact in published["artifacts"]:
            resolved_artifact = (manifest.parent / artifact["path"]).resolve()
            assert resolved_artifact.is_relative_to(publication_root)
            assert resolved_artifact.is_file()


def test_external_manifest_refresh_rejects_symlink_escape_from_publication_root(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from merger.repoground.cli.ground import main as repobrief_main

    repo = tmp_path / "source"
    repo.mkdir()
    (repo / "README.md").write_text("# source\n", encoding="utf-8")
    publication_root = tmp_path / "published"
    publication_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    escaped = publication_root / "bundles"
    escaped.symlink_to(outside, target_is_directory=True)

    rc = repobrief_main(
        [
            "external-manifest",
            "refresh",
            "--repo",
            str(repo),
            "--out",
            str(escaped / "source" / "main" / "run-1"),
            "--publication-root",
            str(publication_root),
            "--repository",
            "source",
            "--ref",
            "main",
        ]
    )

    captured = capsys.readouterr()
    assert rc == 2
    assert "output directory must be inside publication_root" in captured.err
    assert list(outside.iterdir()) == []


def test_publish_rejects_tampered_artifact_before_external_manifest_write(
    tmp_path: Path,
) -> None:
    bundle_path = write_bundle(tmp_path / "source")
    root = tmp_path / "published"
    (bundle_path.parent / "heimgewebe_katalog_merge.md").write_text(
        "tampered\n", encoding="utf-8"
    )

    with pytest.raises(
        ExternalManifestReferenceError, match=r"(?:byte count|sha256) mismatch"
    ):
        publish_external_manifest_references(
            bundle_path,
            root,
            repository="heimgewebe-katalog",
            ref="main",
        )

    assert not (
        root
        / "external"
        / "repobrief"
        / "heimgewebe-katalog"
        / "main"
        / "manifest.json"
    ).exists()


def test_publish_rejects_artifact_traversal_before_materialization(
    tmp_path: Path,
) -> None:
    bundle_path = write_bundle(tmp_path / "source")
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    bundle["artifacts"][0]["path"] = "../outside.md"
    bundle_path.write_text(json.dumps(bundle), encoding="utf-8")

    with pytest.raises(
        ExternalManifestReferenceError, match="inside the bundle directory"
    ):
        publish_external_manifest_references(
            bundle_path,
            tmp_path / "published",
            repository="heimgewebe-katalog",
            ref="main",
        )


def test_publish_rejects_malformed_artifact_row_without_partial_output(
    tmp_path: Path,
) -> None:
    bundle_path = write_bundle(tmp_path / "source")
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    bundle["artifacts"].append({"role": "missing-integrity", "path": "missing.md"})
    bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
    root = tmp_path / "published"

    with pytest.raises(ExternalManifestReferenceError, match="does not exist"):
        publish_external_manifest_references(
            bundle_path,
            root,
            repository="heimgewebe-katalog",
            ref="main",
        )

    assert not (
        root
        / "external"
        / "repobrief"
        / "heimgewebe-katalog"
        / "main"
        / "manifest.json"
    ).exists()
    assert not (
        root / "external" / "lenskit" / "heimgewebe-katalog" / "main" / "manifest.json"
    ).exists()


def test_publish_prevalidates_all_families_before_materialization(
    tmp_path: Path,
) -> None:
    bundle_path = write_bundle(tmp_path / "source")
    root = tmp_path / "published"

    with pytest.raises(ExternalManifestReferenceError, match="artifact family"):
        publish_external_manifest_references(
            bundle_path,
            root,
            repository="heimgewebe-katalog",
            ref="main",
            artifact_families=["repobrief", "invalid"],
        )

    assert not root.exists()


def test_publish_normalizes_and_deduplicates_artifact_families(tmp_path: Path) -> None:
    bundle_path = write_bundle(tmp_path / "source")
    root = tmp_path / "published"

    result = publish_external_manifest_references(
        bundle_path,
        root,
        repository="heimgewebe-katalog",
        ref="main",
        artifact_families=[" RepoBrief ", "repobrief"],
    )

    assert [row["artifactFamily"] for row in result["published"]] == ["repobrief"]
    assert (
        root
        / "external"
        / "repobrief"
        / "heimgewebe-katalog"
        / "main"
        / "manifest.json"
    ).is_file()
    assert not (
        root / "external" / "lenskit" / "heimgewebe-katalog" / "main" / "manifest.json"
    ).exists()


def test_publish_rejects_noncanonical_uppercase_artifact_hash(tmp_path: Path) -> None:
    bundle_path = write_bundle(tmp_path / "source")
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    bundle["artifacts"][0]["sha256"] = bundle["artifacts"][0]["sha256"].upper()
    bundle_path.write_text(json.dumps(bundle), encoding="utf-8")

    with pytest.raises(ExternalManifestReferenceError, match="valid sha256 and bytes"):
        publish_external_manifest_references(
            bundle_path,
            tmp_path / "published",
            repository="heimgewebe-katalog",
            ref="main",
        )


def test_publish_reuses_identical_content_addressed_materialization(
    tmp_path: Path,
) -> None:
    bundle_path = write_bundle(tmp_path / "source")
    root = tmp_path / "published"

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

    assert first["bundleManifest"] == second["bundleManifest"]
    assert first["materialization"]["reused"] is False
    assert second["materialization"]["reused"] is True


def test_publish_rejects_artifact_path_colliding_with_manifest(
    tmp_path: Path,
) -> None:
    bundle_path = write_bundle(tmp_path / "source")
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    bundle["artifacts"][0]["path"] = bundle_path.name
    bundle_path.write_text(json.dumps(bundle), encoding="utf-8")

    with pytest.raises(ExternalManifestReferenceError, match="must not collide"):
        publish_external_manifest_references(
            bundle_path,
            tmp_path / "published",
            repository="heimgewebe-katalog",
            ref="main",
        )


def test_publish_rejects_symlinked_member_in_reused_materialization(
    tmp_path: Path,
) -> None:
    bundle_path = write_bundle(tmp_path / "source")
    root = tmp_path / "published"
    first = publish_external_manifest_references(
        bundle_path,
        root,
        repository="heimgewebe-katalog",
        ref="main",
    )
    localized_manifest = Path(first["bundleManifest"])
    localized_artifact = localized_manifest.parent / "heimgewebe_katalog_merge.md"
    outside = tmp_path / "outside.md"
    outside.write_bytes(localized_artifact.read_bytes())
    localized_artifact.unlink()
    localized_artifact.symlink_to(outside)

    with pytest.raises(ExternalManifestReferenceError, match="regular files"):
        publish_external_manifest_references(
            bundle_path,
            root,
            repository="heimgewebe-katalog",
            ref="main",
        )


def test_publish_rejects_unexpected_file_in_reused_materialization(
    tmp_path: Path,
) -> None:
    bundle_path = write_bundle(tmp_path / "source")
    root = tmp_path / "published"
    first = publish_external_manifest_references(
        bundle_path,
        root,
        repository="heimgewebe-katalog",
        ref="main",
    )
    localized_manifest = Path(first["bundleManifest"])
    (localized_manifest.parent / "unexpected.txt").write_text(
        "unexpected\n", encoding="utf-8"
    )

    with pytest.raises(ExternalManifestReferenceError, match="tree entries mismatch"):
        publish_external_manifest_references(
            bundle_path,
            root,
            repository="heimgewebe-katalog",
            ref="main",
        )


def test_localized_publication_survives_source_bundle_removal(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    bundle_path = write_bundle(source_root)
    root = tmp_path / "consumer"
    result = publish_external_manifest_references(
        bundle_path,
        root,
        repository="heimgewebe-katalog",
        ref="main",
        artifact_families=["repobrief"],
    )
    source_files = list(bundle_path.parent.iterdir())
    for path in source_files:
        path.unlink()
    bundle_path.parent.rmdir()

    external_manifest_path = (
        root
        / "external"
        / "repobrief"
        / "heimgewebe-katalog"
        / "main"
        / "manifest.json"
    )
    external_manifest = json.loads(external_manifest_path.read_text(encoding="utf-8"))
    localized_manifest = (
        external_manifest_path.parent / external_manifest["bundleManifest"]["path"]
    ).resolve()
    assert localized_manifest == Path(result["bundleManifest"])
    assert localized_manifest.is_file()
    for artifact in external_manifest["artifacts"]:
        resolved_artifact = (external_manifest_path.parent / artifact["path"]).resolve()
        assert resolved_artifact.is_file()
        assert resolved_artifact.stat().st_size == artifact["bytes"]
        assert (
            hashlib.sha256(resolved_artifact.read_bytes()).hexdigest()
            == artifact["sha256"]
        )
