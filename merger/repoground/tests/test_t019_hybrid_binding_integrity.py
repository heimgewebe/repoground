from __future__ import annotations

import json
from pathlib import Path

import pytest

from merger.repoground.retrieval import hybrid_activation

ROOT = Path(__file__).resolve().parents[3]
ROUTING_EVIDENCE = ROOT / "docs/retrieval/task-profile-routing-evidence.v1.json"
COMMIT = "cfd341b00c6a36125a014dbfa54cf78c8215da75"
SHA = "a" * 64


def _write_manifest(
    path: Path,
    *,
    commit: str = COMMIT,
    repositories: list[dict[str, object]] | None = None,
) -> None:
    if repositories is None:
        repositories = [
            {
                "name": "repoground",
                "repo_root": None,
                "repo_remote": "https://github.com/heimgewebe/repoground.git",
                "git_commit": commit,
                "git_dirty": False,
                "git_branch": "main",
                "provenance_status": "present",
                "freshness_basis": "git_commit",
            }
        ]
    path.write_text(
        json.dumps(
            {
                "snapshot_provenance": {
                    "version": "v1",
                    "repositories": repositories,
                    "does_not_establish": ["freshness_against_remote"],
                }
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def _valid_binding_inputs(tmp_path: Path) -> dict[str, object]:
    index = tmp_path / "index.sqlite"
    manifest = tmp_path / "bundle.manifest.json"
    index.write_bytes(b"index")
    _write_manifest(manifest)
    policy = {
        "model_name": "local-fixture-model",
        "dimensions": 8,
        "provider": "local",
        "similarity_metric": "cosine",
        "fallback_behavior": "ignore",
    }
    model = {
        "model_name": "local-fixture-model",
        "model_revision": "fixture-v1",
        "model_artifact_sha256": SHA,
        "tokenizer_sha256": "b" * 64,
    }
    activation = hybrid_activation.resolve_profile_activation(
        ROUTING_EVIDENCE,
        task_profile="review",
        explicit_opt_in=True,
    )
    return {
        "activation": activation,
        "embedding_policy": policy,
        "model_binding": model,
        "index_path": index,
        "index_sha256": hybrid_activation.file_sha256(index),
        "bundle_manifest_path": manifest,
        "bundle_manifest_sha256": hybrid_activation.file_sha256(manifest),
        "repository_commit": COMMIT,
        "routing_evidence_path": ROUTING_EVIDENCE,
    }


def test_binding_rejects_index_digest_mismatch(tmp_path: Path) -> None:
    inputs = _valid_binding_inputs(tmp_path)
    inputs["index_sha256"] = "0" * 64

    binding = hybrid_activation.build_hybrid_route_binding(**inputs)

    assert binding["status"] == "invalid"
    assert "index_sha256 must match index_path contents" in binding["errors"]


def test_binding_rejects_manifest_digest_mismatch(tmp_path: Path) -> None:
    inputs = _valid_binding_inputs(tmp_path)
    inputs["bundle_manifest_sha256"] = "1" * 64

    binding = hybrid_activation.build_hybrid_route_binding(**inputs)

    assert binding["status"] == "invalid"
    assert (
        "bundle_manifest_sha256 must match bundle_manifest_path contents"
        in binding["errors"]
    )


def test_binding_rejects_missing_index_file(tmp_path: Path) -> None:
    inputs = _valid_binding_inputs(tmp_path)
    inputs["index_path"] = tmp_path / "missing-index.sqlite"

    binding = hybrid_activation.build_hybrid_route_binding(**inputs)

    assert binding["status"] == "invalid"
    assert "index_path must reference a readable regular file" in binding["errors"]


def test_binding_rejects_unreadable_manifest_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    inputs = _valid_binding_inputs(tmp_path)
    manifest = Path(inputs["bundle_manifest_path"])
    real_read_bytes = Path.read_bytes

    def unreadable_manifest(path: Path) -> bytes:
        if path == manifest:
            raise PermissionError("fixture: unreadable manifest")
        return real_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", unreadable_manifest)

    binding = hybrid_activation.build_hybrid_route_binding(**inputs)

    assert binding["status"] == "invalid"
    assert (
        "bundle_manifest_path must reference a readable regular file"
        in binding["errors"]
    )


@pytest.mark.parametrize(
    "repository_commit",
    [
        "z" * 40,
        "A" * 40,
        "0" * 39,
        "0" * 41,
    ],
)
def test_binding_rejects_noncanonical_repository_commit(
    tmp_path: Path, repository_commit: str
) -> None:
    inputs = _valid_binding_inputs(tmp_path)
    inputs["repository_commit"] = repository_commit

    binding = hybrid_activation.build_hybrid_route_binding(**inputs)

    assert binding["status"] == "invalid"
    assert (
        "repository_commit must be a 40-character lowercase hexadecimal commit"
        in binding["errors"]
    )


def test_binding_rejects_manifest_commit_mismatch(tmp_path: Path) -> None:
    inputs = _valid_binding_inputs(tmp_path)
    manifest = Path(inputs["bundle_manifest_path"])
    _write_manifest(manifest, commit="d" * 40)
    inputs["bundle_manifest_sha256"] = hybrid_activation.file_sha256(manifest)

    binding = hybrid_activation.build_hybrid_route_binding(**inputs)

    assert binding["status"] == "invalid"
    assert (
        "repository_commit must match bundle_manifest snapshot provenance git_commit"
        in binding["errors"]
    )


def test_binding_rejects_missing_manifest_provenance(tmp_path: Path) -> None:
    inputs = _valid_binding_inputs(tmp_path)
    manifest = Path(inputs["bundle_manifest_path"])
    manifest.write_text("{}", encoding="utf-8")
    inputs["bundle_manifest_sha256"] = hybrid_activation.file_sha256(manifest)

    binding = hybrid_activation.build_hybrid_route_binding(**inputs)

    assert binding["status"] == "invalid"
    assert (
        "bundle_manifest snapshot_provenance must record repository provenance"
        in binding["errors"]
    )


def test_binding_rejects_ambiguous_multi_repository_manifest(tmp_path: Path) -> None:
    inputs = _valid_binding_inputs(tmp_path)
    manifest = Path(inputs["bundle_manifest_path"])
    repositories = [
        {
            "name": "repoground",
            "git_commit": COMMIT,
            "provenance_status": "present",
        },
        {
            "name": "other",
            "git_commit": "d" * 40,
            "provenance_status": "present",
        },
    ]
    _write_manifest(manifest, repositories=repositories)
    inputs["bundle_manifest_sha256"] = hybrid_activation.file_sha256(manifest)

    binding = hybrid_activation.build_hybrid_route_binding(**inputs)

    assert binding["status"] == "invalid"
    assert (
        "repository_commit binding requires exactly one present repository in "
        "bundle_manifest snapshot_provenance"
        in binding["errors"]
    )


def test_binding_records_manifest_commit_boundary_without_live_git_probe(
    tmp_path: Path,
) -> None:
    inputs = _valid_binding_inputs(tmp_path)
    manifest = Path(inputs["bundle_manifest_path"])
    historical_commit = "d" * 40
    _write_manifest(manifest, commit=historical_commit)
    inputs["bundle_manifest_sha256"] = hybrid_activation.file_sha256(manifest)
    inputs["repository_commit"] = historical_commit

    binding = hybrid_activation.build_hybrid_route_binding(**inputs)

    assert binding["status"] == "bound"
    assert binding["repository_commit_binding"] == {
        "source": "bundle_manifest.snapshot_provenance",
        "repository_name": "repoground",
        "provenance_status": "present",
        "git_commit": historical_commit,
    }
    assert "current_repository_git_object_presence" in binding["does_not_establish"]
    assert "freshness_against_remote" in binding["does_not_establish"]
