import pytest
from pathlib import Path
from merger.repoground.core.federation import init_federation, add_bundle, inspect_federation

def test_inspect_federation_empty(tmp_path: Path):
    index_path = tmp_path / "fed.json"
    init_federation("test-inspect-fed", index_path)

    summary = inspect_federation(index_path)
    assert summary["federation_id"] == "test-inspect-fed"
    assert summary["bundle_count"] == 0
    assert summary["repo_ids"] == []
    assert summary["updated_at"] is not None

def test_inspect_federation_with_bundles(tmp_path: Path):
    index_path = tmp_path / "fed.json"
    init_federation("test-inspect-fed", index_path)

    add_bundle(index_path, "repo-1", str(tmp_path / "b1"))
    add_bundle(index_path, "repo-2", str(tmp_path / "b2"))

    summary = inspect_federation(index_path)
    assert summary["federation_id"] == "test-inspect-fed"
    assert summary["bundle_count"] == 2
    assert "repo-1" in summary["repo_ids"]
    assert "repo-2" in summary["repo_ids"]

def test_inspect_federation_not_found(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        inspect_federation(tmp_path / "nonexistent.json")
