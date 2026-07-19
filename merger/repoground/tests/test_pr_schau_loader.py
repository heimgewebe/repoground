import json
import tempfile
from pathlib import Path

import pytest

from merger.repoground.core import pr_schau_bundle
from merger.repoground.core.extractor import generate_review_bundle
from merger.repoground.core.pr_schau_bundle import load_pr_schau_bundle, PRSchauBundleError
from merger.repoground.tests._test_constants import TEST_ARTIFACT_SHA256


def _write_schema_gate_bundle(bundle_dir: Path) -> None:
    (bundle_dir / "review.md").write_text("Review", encoding="utf-8")
    data = {
        "kind": "repolens.pr_schau.bundle",
        "version": "1.0",
        "meta": {"repo": "x", "generated_at": "2023-01-01T00:00:00Z", "generator": {"name": "x"}},
        "completeness": {"is_complete": True, "policy": "split", "parts": ["review.md"], "primary_part": "review.md"},
        "artifacts": [{"role": "canonical_md", "basename": "review.md", "sha256": TEST_ARTIFACT_SHA256, "mime": "text/markdown"}],
    }
    (bundle_dir / "bundle.json").write_text(json.dumps(data), encoding="utf-8")


def test_loader_accepts_generated_bundle_basic():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        hub = tmp / "hub"
        hub.mkdir()

        old_repo = tmp / "old"
        old_repo.mkdir()
        (old_repo / "README.md").write_text("Old", encoding="utf-8")

        new_repo = tmp / "new"
        new_repo.mkdir()
        (new_repo / "README.md").write_text("New", encoding="utf-8")
        (new_repo / "contracts" / "x").mkdir(parents=True, exist_ok=True)
        (new_repo / "contracts" / "x" / "c.schema.json").write_text('{"a":1}', encoding="utf-8")

        generate_review_bundle(old_repo, new_repo, "repo1", hub)

        prdir = hub / ".repoground" / "pr-schau" / "repo1"
        # Find the timestamp folder
        ts_folders = list(prdir.iterdir())
        assert len(ts_folders) == 1
        bundle_dir = ts_folders[0]

        data, base = load_pr_schau_bundle(bundle_dir, verify_level="basic")
        assert base == bundle_dir
        assert data["kind"] == "repolens.pr_schau.bundle"
        assert data["version"] == "1.0"


def test_loader_accepts_generated_bundle_full():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        hub = tmp / "hub"
        hub.mkdir()

        old_repo = tmp / "old"
        old_repo.mkdir()
        (old_repo / "a.txt").write_text("A", encoding="utf-8")

        new_repo = tmp / "new"
        new_repo.mkdir()
        (new_repo / "a.txt").write_text("B", encoding="utf-8")

        generate_review_bundle(old_repo, new_repo, "repo2", hub)

        prdir = hub / ".repoground" / "pr-schau" / "repo2"
        # Find the timestamp folder
        ts_folders = list(prdir.iterdir())
        assert len(ts_folders) == 1
        bundle_dir = ts_folders[0]

        data, _ = load_pr_schau_bundle(bundle_dir, verify_level="full")
        assert data["completeness"]["primary_part"] == "review.md"


def test_loader_rejects_legacy_flat_bundle():
    with tempfile.TemporaryDirectory() as tmp_dir:
        d = Path(tmp_dir)
        # Craft a legacy-like flat bundle.json
        legacy = {
            "kind": "repolens.pr_schau.bundle",
            "version": 1,
            "repo": "x",
            "created_at": "2023-01-01T00:00:00Z",
            "generator": {"name": "old"},
        }
        (d / "bundle.json").write_text(json.dumps(legacy), encoding="utf-8")

        with pytest.raises(PRSchauBundleError):
            load_pr_schau_bundle(d, strict=True, verify_level="none")


def test_loader_rejects_missing_parts():
    with tempfile.TemporaryDirectory() as tmp_dir:
        d = Path(tmp_dir)
        bad = {
            "kind": "repolens.pr_schau.bundle",
            "version": "1.0",
            "meta": {"repo": "x", "generated_at": "2023-01-01T00:00:00Z", "generator": {"name": "x"}},
            "completeness": {"is_complete": True, "policy": "split", "parts": ["review.md"], "primary_part": "review.md"},
            "artifacts": [{"role": "canonical_md", "basename": "review.md", "sha256": TEST_ARTIFACT_SHA256, "mime": "text/markdown"}],
        }
        (d / "bundle.json").write_text(json.dumps(bad), encoding="utf-8")

        with pytest.raises(PRSchauBundleError):
            load_pr_schau_bundle(d, verify_level="basic")


def test_loader_rejects_missing_schema_for_basic(monkeypatch, tmp_path):
    _write_schema_gate_bundle(tmp_path)
    monkeypatch.setattr(pr_schau_bundle, "SCHEMA_PATH", tmp_path / "missing.schema.json")

    with pytest.raises(PRSchauBundleError, match="Schema file not found"):
        load_pr_schau_bundle(tmp_path, verify_level="basic")


def test_loader_rejects_invalid_schema_json_for_basic(monkeypatch, tmp_path):
    _write_schema_gate_bundle(tmp_path)
    bad_schema = tmp_path / "bad.schema.json"
    bad_schema.write_text("{", encoding="utf-8")
    monkeypatch.setattr(pr_schau_bundle, "SCHEMA_PATH", bad_schema)

    with pytest.raises(PRSchauBundleError, match="Invalid schema JSON"):
        load_pr_schau_bundle(tmp_path, verify_level="basic")


def test_loader_rejects_missing_jsonschema_dependency(monkeypatch, tmp_path):
    _write_schema_gate_bundle(tmp_path)
    monkeypatch.setattr(pr_schau_bundle, "jsonschema", None)

    with pytest.raises(PRSchauBundleError, match="jsonschema dependency unavailable"):
        load_pr_schau_bundle(tmp_path, verify_level="basic")


def test_bundle_artifact_bytes_correctness():
    """
    Verify that the fixpoint logic in `generate_review_bundle` correctly sets the `bytes` field
    of the self-referencing `bundle.json` artifact entry.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        hub = tmp / "hub"
        hub.mkdir()

        old_repo = tmp / "old"
        old_repo.mkdir()
        (old_repo / "README.md").write_text("Old Content", encoding="utf-8")

        new_repo = tmp / "new"
        new_repo.mkdir()
        (new_repo / "README.md").write_text("New Content", encoding="utf-8")

        generate_review_bundle(old_repo, new_repo, "fixpoint-repo", hub)

        prdir = hub / ".repoground" / "pr-schau" / "fixpoint-repo"
        # Find the timestamp folder
        ts_folders = list(prdir.iterdir())
        assert len(ts_folders) == 1
        bundle_dir = ts_folders[0]
        bundle_json_path = bundle_dir / "bundle.json"

        assert bundle_json_path.exists()

        # Load bundle.json
        data = json.loads(bundle_json_path.read_text(encoding="utf-8"))
        actual_size = bundle_json_path.stat().st_size

        # Find self-artifact
        self_artifact = next(
            (a for a in data.get("artifacts", [])
             if a.get("role") == "index_json" and a.get("basename") == "bundle.json"),
            None
        )

        assert self_artifact is not None, "Self-artifact entry for bundle.json missing"
        recorded_size = self_artifact.get("bytes")

        assert recorded_size > 0, "Recorded bytes should be > 0"
        assert recorded_size == actual_size, f"Recorded bytes ({recorded_size}) does not match actual file size ({actual_size})"
