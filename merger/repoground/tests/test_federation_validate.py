import json
import pytest
from pathlib import Path
from merger.repoground.core.federation import init_federation, add_bundle, validate_federation

def test_validate_federation_valid_empty(tmp_path: Path):
    index_path = tmp_path / "fed.json"
    init_federation("valid-empty-fed", index_path)

    assert validate_federation(index_path) is True

def test_validate_federation_valid_with_bundles(tmp_path: Path):
    index_path = tmp_path / "fed.json"
    init_federation("valid-bundles-fed", index_path)
    add_bundle(index_path, "repo-1", str(tmp_path / "b1"))
    add_bundle(index_path, "repo-2", str(tmp_path / "b2"))

    assert validate_federation(index_path) is True

def test_validate_federation_missing_repo_id(tmp_path: Path):
    index_path = tmp_path / "fed.json"
    init_federation("invalid-fed", index_path)

    with index_path.open() as f:
        data = json.load(f)

    # Force invalid bundle (missing repo_id)
    data["bundles"].append({"bundle_path": str(tmp_path / "b1")})

    with index_path.open("w") as f:
        json.dump(data, f)

    with pytest.raises(ValueError) as exc_info:
        validate_federation(index_path)

    assert "Schema validation failed" in str(exc_info.value)

def test_validate_federation_duplicate_repo_ids(tmp_path: Path):
    index_path = tmp_path / "fed.json"
    init_federation("invalid-fed", index_path)

    with index_path.open() as f:
        data = json.load(f)

    # Force invalid bundle (duplicate repo_id)
    data["bundles"].append({"repo_id": "r1", "bundle_path": str(tmp_path / "b1")})
    data["bundles"].append({"repo_id": "r1", "bundle_path": str(tmp_path / "b2")})

    with index_path.open("w") as f:
        json.dump(data, f)

    with pytest.raises(ValueError) as exc_info:
        validate_federation(index_path)

    assert "Duplicate 'repo_id'" in str(exc_info.value)

def test_validate_federation_not_found(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        validate_federation(tmp_path / "nonexistent.json")
