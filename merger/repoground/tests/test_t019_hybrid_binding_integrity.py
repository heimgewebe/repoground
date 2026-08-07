from __future__ import annotations

from pathlib import Path

import pytest

from merger.repoground.retrieval import hybrid_activation

ROOT = Path(__file__).resolve().parents[3]
ROUTING_EVIDENCE = ROOT / "docs/retrieval/task-profile-routing-evidence.v1.json"
COMMIT = "cfd341b00c6a36125a014dbfa54cf78c8215da75"
SHA = "a" * 64


def _valid_binding_inputs(tmp_path: Path) -> dict[str, object]:
    index = tmp_path / "index.sqlite"
    manifest = tmp_path / "bundle.manifest.json"
    index.write_bytes(b"index")
    manifest.write_text("{}", encoding="utf-8")
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
    real_file_sha256 = hybrid_activation.file_sha256

    def unreadable_manifest(path: str | Path) -> str:
        if Path(path) == manifest:
            raise PermissionError("fixture: unreadable manifest")
        return real_file_sha256(path)

    monkeypatch.setattr(hybrid_activation, "file_sha256", unreadable_manifest)

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
