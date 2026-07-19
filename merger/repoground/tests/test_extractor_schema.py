import json
import tempfile
import pytest
from typing import Dict, Any
from pathlib import Path
from merger.repoground.core.extractor import generate_review_bundle, _compute_sha256

# Path to the schema file
SCHEMA_PATH = Path(__file__).parents[1] / "contracts" / "pr-schau.v1.schema.json"

LEGACY_TOP_LEVEL_KEYS = {
    # Historical/legacy flat bundle keys that must never reappear as top-level fields in v1
    "repo",
    "source",
    "created_at",
    "hub_rel",
    "old_tree_hint",
    "new_tree_hint",
    "note",
}

def assert_not_legacy_flat_bundle(bundle_data: Dict[str, Any]) -> None:
    """
    Regression guard: ensure we don't slip back into the legacy flat bundle format.
    """
    # v1 requires nested meta/completeness/artifacts. If these exist, legacy keys must not.
    for k in LEGACY_TOP_LEVEL_KEYS:
        assert k not in bundle_data, f"Legacy top-level key '{k}' must not exist in v1 bundle"

    # v1 version is a string constant "1.0"
    assert isinstance(bundle_data.get("version"), str), "v1 bundle 'version' must be a string"
    assert bundle_data.get("version") == "1.0", "v1 bundle 'version' must be '1.0'"

@pytest.fixture
def schema():
    if not SCHEMA_PATH.exists():
        pytest.skip(f"Schema file not found at {SCHEMA_PATH}")
    with open(SCHEMA_PATH, "r") as f:
        return json.load(f)

def test_generate_review_bundle_output_schema(schema):
    """
    Test that generate_review_bundle produces a bundle.json that complies with pr-schau.v1.schema.json.
    """
    try:
        import jsonschema
    except ImportError:
        pytest.skip("jsonschema not installed")

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        hub_dir = tmp_path / "hub"
        hub_dir.mkdir()

        # Create dummy old and new repos
        old_repo = tmp_path / "old_repo"
        old_repo.mkdir()
        (old_repo / "file1.txt").write_text("content1")

        new_repo = tmp_path / "new_repo"
        new_repo.mkdir()
        (new_repo / "file1.txt").write_text("content1_modified")
        (new_repo / "file2.txt").write_text("content2")

        repo_name = "test-repo"

        # Run generator
        generate_review_bundle(old_repo, new_repo, repo_name, hub_dir)

        # Check output structure
        pr_schau_dir = hub_dir / ".repoground" / "pr-schau" / repo_name
        assert pr_schau_dir.exists()

        # Find the timestamp folder (should be only one)
        ts_folders = list(pr_schau_dir.iterdir())
        assert len(ts_folders) == 1
        bundle_dir = ts_folders[0]

        bundle_json_path = bundle_dir / "bundle.json"
        assert bundle_json_path.exists()

        with open(bundle_json_path, "r") as f:
            bundle_data = json.load(f)

        # Validate against schema
        jsonschema.validate(instance=bundle_data, schema=schema)

        # Regression guard: ensure not legacy flat format
        assert_not_legacy_flat_bundle(bundle_data)

        # Additional checks for values
        assert bundle_data["kind"] == "repolens.pr_schau.bundle"
        assert bundle_data["version"] == "1.0"
        assert bundle_data["meta"]["repo"] == repo_name
        assert bundle_data["completeness"]["is_complete"] is True
        assert bundle_data["completeness"]["primary_part"] == "review.md"
        assert "review.md" in bundle_data["completeness"]["parts"]

        # Verify SHA256 matches
        artifacts = bundle_data["artifacts"]
        review_md_artifact = next(a for a in artifacts if a["role"] == "canonical_md")
        expected_sha = _compute_sha256(bundle_dir / "review.md")
        assert review_md_artifact["sha256"] == expected_sha

def test_generate_review_bundle_splitting(schema):
    """
    Test that generate_review_bundle splits content when it exceeds 200KB.
    """
    try:
        import jsonschema
    except ImportError:
        pytest.skip("jsonschema not installed")

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        hub_dir = tmp_path / "hub"
        hub_dir.mkdir()

        old_repo = tmp_path / "old_repo"
        old_repo.mkdir()

        new_repo = tmp_path / "new_repo"
        new_repo.mkdir()

        # Create multiple files that collectively exceed 200KB but individually are < 200KB
        # 2 files of 150KB each = 300KB total > 200KB limit
        content1 = "A" * (150 * 1024)
        content2 = "B" * (150 * 1024)

        (new_repo / "file1.txt").write_text(content1)
        (new_repo / "file2.txt").write_text(content2)

        repo_name = "test-split-repo"

        # Run generator
        generate_review_bundle(old_repo, new_repo, repo_name, hub_dir)

        pr_schau_dir = hub_dir / ".repoground" / "pr-schau" / repo_name
        assert pr_schau_dir.exists()
        bundle_dir = list(pr_schau_dir.iterdir())[0]
        bundle_json_path = bundle_dir / "bundle.json"

        with open(bundle_json_path, "r") as f:
            bundle_data = json.load(f)

        parts = bundle_data["completeness"]["parts"]
        assert len(parts) >= 2, f"Should have split into at least 2 parts, got {len(parts)}"
        assert "review.md" in parts
        assert "review_part2.md" in parts

        assert (bundle_dir / "review.md").exists()
        assert (bundle_dir / "review_part2.md").exists()

        # Verify schema compliance for split bundle
        jsonschema.validate(instance=bundle_data, schema=schema)

        # Regression guard: ensure not legacy flat format
        assert_not_legacy_flat_bundle(bundle_data)

if __name__ == "__main__":
    pytest.main([__file__])
