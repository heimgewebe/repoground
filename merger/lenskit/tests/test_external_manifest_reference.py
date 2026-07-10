from __future__ import annotations

import json
from pathlib import Path

import pytest

from merger.lenskit.core.external_manifest_reference import (
    ExternalManifestReferenceError,
    build_external_manifest_reference,
    publication_manifest_path,
    publish_external_manifest_references,
    write_external_manifest_reference,
)


def write_bundle(tmp_path: Path) -> Path:
    bundle = {
        "kind": "repolens.bundle.manifest",
        "version": "1.0",
        "run_id": "run-1",
        "created_at": "2026-07-06T13:00:00Z",
        "generator": {"name": "repobrief", "version": "dev", "config_sha256": "a" * 64},
        "artifacts": [
            {
                "role": "canonical_md",
                "path": "cabinet_merge.md",
                "content_type": "text/markdown",
                "bytes": 12,
                "sha256": "b" * 64,
            },
            {
                "role": "agent_reading_pack",
                "path": "cabinet_merge.agent_reading_pack.md",
                "content_type": "text/markdown",
                "bytes": 5,
                "sha256": "c" * 64,
            },
        ],
        "links": {},
        "capabilities": {},
        "snapshot_provenance": {
            "version": "v1",
            "repositories": [
                {
                    "name": "cabinet",
                    "repo_root": None,
                    "repo_remote": "git@github.com:heimgewebe/cabinet.git",
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
    path = tmp_path / "bundle" / "cabinet_merge.bundle.manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(bundle), encoding="utf-8")
    return path


def test_builds_cabinet_compatible_repobrief_manifest_reference(tmp_path: Path) -> None:
    bundle_path = write_bundle(tmp_path)
    out = tmp_path / "external" / "repobrief" / "cabinet" / "main" / "manifest.json"

    result = build_external_manifest_reference(
        bundle_path,
        repository="cabinet",
        ref="main",
        artifact_family="repobrief",
        output_path=out,
    )

    assert result["kind"] == "repobrief_bundle_manifest"
    assert result["generatedAt"] == "2026-07-06T13:00:00Z"
    assert result["freshnessBasis"] == "bundle_manifest.created_at"
    assert result["repository"] == "cabinet"
    assert result["ref"] == "main"
    assert result["bundleManifest"]["path"] == "../../../../bundle/cabinet_merge.bundle.manifest.json"
    assert result["snapshotProvenance"]["repositories"][0]["git_commit"] == "d" * 40
    assert [row["role"] for row in result["artifacts"]] == ["agent_reading_pack", "canonical_md"]
    assert "claim_truth" in result["doesNotEstablish"]
    assert "dump_generation_permission" in result["doesNotEstablish"]


def test_writes_manifest_reference_atomically(tmp_path: Path) -> None:
    bundle_path = write_bundle(tmp_path)
    out = tmp_path / "external" / "lenskit" / "cabinet" / "main" / "manifest.json"

    result = write_external_manifest_reference(
        bundle_path,
        out,
        repository="cabinet",
        ref="main",
        artifact_family="lenskit",
    )

    written = json.loads(out.read_text(encoding="utf-8"))
    assert written == result
    assert written["kind"] == "lenskit_bundle_manifest"


@pytest.mark.parametrize(
    ("repository", "ref"),
    [("heimgewebe/cabinet", "main"), ("cabinet", "feature/x"), (" cabinet", "main")],
)
def test_rejects_registry_segments_with_slashes_or_whitespace(tmp_path: Path, repository: str, ref: str) -> None:
    bundle_path = write_bundle(tmp_path)

    with pytest.raises(ExternalManifestReferenceError):
        build_external_manifest_reference(bundle_path, repository=repository, ref=ref)


def test_rejects_non_bundle_manifest(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"kind": "other", "created_at": "2026-07-06T13:00:00Z"}), encoding="utf-8")

    with pytest.raises(ExternalManifestReferenceError, match="repolens.bundle.manifest"):
        build_external_manifest_reference(path, repository="cabinet", ref="main")

def test_publication_manifest_path_uses_stable_external_layout(tmp_path: Path) -> None:
    path = publication_manifest_path(
        tmp_path / "published",
        repository="cabinet",
        ref="main",
        artifact_family="repobrief",
    )

    assert path == tmp_path / "published" / "external" / "repobrief" / "cabinet" / "main" / "manifest.json"


def test_publish_external_manifest_references_can_publish_one_family(tmp_path: Path) -> None:
    root = tmp_path / "published"
    bundle_path = write_bundle(root)

    result = publish_external_manifest_references(
        bundle_path,
        root,
        repository="cabinet",
        ref="main",
        artifact_families=["repobrief"],
    )

    assert [row["artifactFamily"] for row in result["published"]] == ["repobrief"]
    assert (root / "external" / "repobrief" / "cabinet" / "main" / "manifest.json").is_file()
    assert not (root / "external" / "lenskit" / "cabinet" / "main" / "manifest.json").exists()


def test_repobrief_cli_publishes_external_manifest_references(tmp_path: Path) -> None:
    from merger.lenskit.cli.repobrief import main as repobrief_main

    root = tmp_path / "published"
    bundle_path = write_bundle(root)

    rc = repobrief_main([
        "external-manifest",
        "publish",
        "--bundle-manifest",
        str(bundle_path),
        "--publication-root",
        str(root),
        "--repository",
        "cabinet",
        "--ref",
        "main",
    ])

    assert rc == 0
    assert (root / "external" / "repobrief" / "cabinet" / "main" / "manifest.json").is_file()
    assert (root / "external" / "lenskit" / "cabinet" / "main" / "manifest.json").is_file()


def test_build_includes_linked_post_emit_health_sidecar(tmp_path: Path) -> None:
    bundle_path = write_bundle(tmp_path)
    sidecar = bundle_path.with_name("cabinet_merge.bundle_health.post.json")
    sidecar.write_text('{"kind":"lenskit.post_emit_health","status":"pass"}\n', encoding="utf-8")
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    bundle["links"]["post_emit_health_path"] = sidecar.name
    bundle_path.write_text(json.dumps(bundle), encoding="utf-8")

    result = build_external_manifest_reference(
        bundle_path,
        repository="cabinet",
        ref="main",
        artifact_family="repobrief",
    )

    row = next(artifact for artifact in result["artifacts"] if artifact["role"] == "post_emit_health")
    assert row["path"] == "cabinet_merge.bundle_health.post.json"
    assert row["contentType"] == "application/json"
    assert row["bytes"] == sidecar.stat().st_size
    assert len(row["sha256"]) == 64


def test_publish_rejects_bundle_manifest_outside_publication_root(tmp_path: Path) -> None:
    bundle_path = write_bundle(tmp_path / "bundle-source")
    root = tmp_path / "published"

    with pytest.raises(ExternalManifestReferenceError, match="inside publication_root"):
        publish_external_manifest_references(
            bundle_path,
            root,
            repository="cabinet",
            ref="main",
        )


def test_linked_sidecar_must_remain_inside_bundle_directory(tmp_path: Path) -> None:
    bundle_path = write_bundle(tmp_path)
    outside = tmp_path / "outside.bundle_health.post.json"
    outside.write_text("{}\n", encoding="utf-8")
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    bundle["links"]["post_emit_health_path"] = "../outside.bundle_health.post.json"
    bundle_path.write_text(json.dumps(bundle), encoding="utf-8")

    with pytest.raises(ExternalManifestReferenceError, match="inside the bundle directory"):
        build_external_manifest_reference(bundle_path, repository="cabinet", ref="main")


def test_external_manifest_refresh_rejects_output_outside_publication_root(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from merger.lenskit.cli.repobrief import main as repobrief_main

    repo = tmp_path / "source"
    repo.mkdir()
    (repo / "README.md").write_text("# source\n", encoding="utf-8")
    publication_root = tmp_path / "published"
    outside = tmp_path / "legacy-output"

    rc = repobrief_main([
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
    ])

    captured = capsys.readouterr()
    assert rc == 2
    assert "output directory must be inside publication_root" in captured.err
    assert not outside.exists()


def test_external_manifest_refresh_creates_portable_bundle_and_references(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from merger.lenskit.cli.repobrief import main as repobrief_main

    repo = tmp_path / "source"
    repo.mkdir()
    (repo / "README.md").write_text("# source\n", encoding="utf-8")
    publication_root = tmp_path / "published"
    out = publication_root / "bundles" / "source" / "main" / "run-1"

    rc = repobrief_main([
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
    ])

    captured = capsys.readouterr()
    result = json.loads(captured.out)
    bundle_manifest = Path(result["snapshot"]["bundle_manifest"])
    assert rc == 0
    assert bundle_manifest.is_file()
    assert bundle_manifest.is_relative_to(publication_root)
    for family in ("lenskit", "repobrief"):
        manifest = publication_root / "external" / family / "source" / "main" / "manifest.json"
        assert manifest.is_file()
        published = json.loads(manifest.read_text(encoding="utf-8"))
        resolved_bundle = (manifest.parent / published["bundleManifest"]["path"]).resolve()
        assert resolved_bundle == bundle_manifest.resolve()


def test_external_manifest_refresh_rejects_symlink_escape_from_publication_root(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from merger.lenskit.cli.repobrief import main as repobrief_main

    repo = tmp_path / "source"
    repo.mkdir()
    (repo / "README.md").write_text("# source\n", encoding="utf-8")
    publication_root = tmp_path / "published"
    publication_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    escaped = publication_root / "bundles"
    escaped.symlink_to(outside, target_is_directory=True)

    rc = repobrief_main([
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
    ])

    captured = capsys.readouterr()
    assert rc == 2
    assert "output directory must be inside publication_root" in captured.err
    assert list(outside.iterdir()) == []
