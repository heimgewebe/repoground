import json
from pathlib import Path
import pytest
from merger.repoground.core.federation import init_federation, add_bundle

def test_add_bundle_success(tmp_path: Path):
    index_path = tmp_path / "fed.json"
    init_federation("test-add-fed", index_path)

    bundle_path = tmp_path / "my_bundle"
    bundle_path.mkdir()

    updated_data = add_bundle(index_path, "repo-1", str(bundle_path))

    assert "bundles" in updated_data
    assert len(updated_data["bundles"]) == 1
    assert updated_data["bundles"][0]["repo_id"] == "repo-1"
    assert "my_bundle" in updated_data["bundles"][0]["bundle_path"]

    # Verify write
    with index_path.open() as f:
        read_data = json.load(f)
        assert read_data["bundles"][0]["repo_id"] == "repo-1"
        assert read_data["updated_at"] >= read_data["created_at"]

def test_add_bundle_duplicate_repo_id(tmp_path: Path):
    index_path = tmp_path / "fed.json"
    init_federation("test-dup-fed", index_path)

    b1_path = str(tmp_path / "b1")
    b2_path = str(tmp_path / "b2")

    add_bundle(index_path, "repo-1", b1_path)

    with pytest.raises(ValueError) as exc_info:
        add_bundle(index_path, "repo-1", b2_path)

    assert "already exists in federation index" in str(exc_info.value)

def test_add_bundle_index_not_found(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        add_bundle(tmp_path / "nonexistent.json", "repo-1", str(tmp_path / "b1"))

def test_add_bundle_preserves_opaque_uri_and_relative_paths(tmp_path: Path):
    index_path = tmp_path / "fed.json"
    init_federation("opaque-fed", index_path)

    uri = "https://example.org/bundles/repo-a"
    add_bundle(index_path, "repo-uri", uri)

    rel_path = "bundles/repo-b"
    add_bundle(index_path, "repo-rel", rel_path)

    with index_path.open() as f:
        read_data = json.load(f)

    bundles = read_data["bundles"]
    assert len(bundles) == 2

    # Verify URIs and relative paths are preserved exactly
    # They should be sorted alphabetically by repo_id (repo-rel before repo-uri)
    assert bundles[0]["repo_id"] == "repo-rel"
    assert bundles[0]["bundle_path"] == rel_path

    assert bundles[1]["repo_id"] == "repo-uri"
    assert bundles[1]["bundle_path"] == uri

def test_add_bundle_fails_without_schema(tmp_path: Path, monkeypatch):
    index_path = tmp_path / "fed.json"
    init_federation("schema-fail-fed", index_path)

    from merger.repoground.core import federation

    # Mock the schema loader to return None
    monkeypatch.setattr(federation, "load_federation_schema", lambda: None)

    with pytest.raises(RuntimeError) as exc_info:
        add_bundle(index_path, "repo-fail", "some-path")

    assert "Federation schema missing at expected path" in str(exc_info.value)

def test_add_bundle_fails_on_corrupt_existing_index(tmp_path: Path):
    index_path = tmp_path / "fed.json"
    init_federation("corrupt-fed", index_path)

    # Manually corrupt the file: insert a bundle missing a "repo_id"
    with index_path.open("r", encoding="utf-8") as f:
        fed_data = json.load(f)

    fed_data["bundles"].append({"bundle_path": "/some/path/without/repo_id"})

    with index_path.open("w", encoding="utf-8") as f:
        json.dump(fed_data, f)

    with pytest.raises(ValueError) as exc_info:
        add_bundle(index_path, "repo-new", "/bundles/repo-new")

    err_msg = str(exc_info.value)
    assert "Existing federation index is corrupt: schema validation failed" in err_msg
    assert "'repo_id' is a required property" in err_msg
