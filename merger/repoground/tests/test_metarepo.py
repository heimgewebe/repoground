import yaml
from typing import Any
from pathlib import Path
from unittest.mock import patch

from merger.repoground.adapters.metarepo import (
    load_manifest,
    sync_from_metarepo,
    MANIFEST_REL_PATH,
    HASH_COMPUTATION_ERROR,
)


def test_metarepo_sync_parallel(tmp_path: Path) -> None:
    """
    Test that sync_from_metarepo correctly synchronizes files across multiple repositories
    using the parallel implementation.
    """
    hub_path = tmp_path / "hub"
    hub_path.mkdir()

    # Create metarepo
    metarepo = hub_path / "metarepo"
    metarepo.mkdir()
    (metarepo / "sync").mkdir()

    # Create a source file
    source_content = '{"foo": "bar"}' * 100
    source_file = metarepo / "shared_config.json"
    source_file.write_text(source_content, encoding="utf-8")

    # Create manifest
    manifest = {
        "version": 1,
        "entries": [
            {
                "id": "config",
                "source": "shared_config.json",
                "targets": ["config.json"],
                "mode": "copy",
            }
        ],
    }

    with (metarepo / MANIFEST_REL_PATH).open("w", encoding="utf-8") as f:
        yaml.dump(manifest, f)

    # Create repos
    num_repos = 20
    for i in range(num_repos):
        repo_path = hub_path / f"repo_{i}"
        repo_path.mkdir()
        (repo_path / ".git").mkdir()  # Mark as repo

    # Run sync
    report = sync_from_metarepo(hub_path, mode="apply")

    assert report["status"] == "ok"
    assert report["aggregate_summary"]["add"] == num_repos
    assert report["aggregate_summary"]["error"] == 0

    # Verify deterministic ordering
    repo_keys = list(report["repos"].keys())
    assert repo_keys == sorted(repo_keys)

    # Verify files
    for i in range(num_repos):
        repo_path = hub_path / f"repo_{i}"
        target_file = repo_path / "config.json"
        assert target_file.exists()
        assert target_file.read_text(encoding="utf-8") == source_content


def test_metarepo_sync_update_flow(tmp_path: Path) -> None:
    """
    Test that updates work correctly with hash checks.
    """
    hub_path = tmp_path / "hub"
    hub_path.mkdir()

    # Create metarepo
    metarepo = hub_path / "metarepo"
    metarepo.mkdir()
    (metarepo / "sync").mkdir()

    source_file = metarepo / "v1.txt"
    source_content_v1 = "v1\n# managed-by: metarepo-sync"
    source_file.write_text(source_content_v1, encoding="utf-8")

    manifest = {
        "version": 1,
        "entries": [
            {
                "id": "v1",
                "source": "v1.txt",
                "targets": ["v1.txt"],
                "mode": "copy",
            }
        ],
    }

    with (metarepo / MANIFEST_REL_PATH).open("w", encoding="utf-8") as f:
        yaml.dump(manifest, f)

    repo_path = hub_path / "repo1"
    repo_path.mkdir()
    (repo_path / ".git").mkdir()

    # First sync (ADD)
    report = sync_from_metarepo(hub_path, mode="apply")
    assert report["status"] == "ok"
    assert report["aggregate_summary"]["add"] == 1
    assert (repo_path / "v1.txt").read_text(encoding="utf-8") == source_content_v1

    # Second sync (SKIP)
    report = sync_from_metarepo(hub_path, mode="apply")
    assert report["status"] == "ok"
    assert report["aggregate_summary"]["skip"] == 1

    # Update source file
    source_content_v2 = "v2\n# managed-by: metarepo-sync"
    source_file.write_text(source_content_v2, encoding="utf-8")

    # Sync (UPDATE)
    report = sync_from_metarepo(hub_path, mode="apply")
    assert report["status"] == "ok"
    assert report["aggregate_summary"]["update"] == 1
    assert (repo_path / "v1.txt").read_text(encoding="utf-8") == source_content_v2


def test_metarepo_sync_error_handling(tmp_path: Path) -> None:
    """
    Test that sync errors in individual repositories are correctly aggregated
    and result in an overall error status, while still producing deterministic output.
    """
    hub_path = tmp_path / "hub"
    hub_path.mkdir()

    # Create metarepo
    metarepo = hub_path / "metarepo"
    metarepo.mkdir()
    (metarepo / "sync").mkdir()

    # Minimal manifest; content doesn't matter because we patch sync_repo below
    manifest = {"version": 1, "entries": []}
    with (metarepo / MANIFEST_REL_PATH).open("w", encoding="utf-8") as f:
        yaml.dump(manifest, f)

    # Create two repos
    repo1 = hub_path / "repo1"
    repo1.mkdir()
    (repo1 / ".git").mkdir()

    repo2 = hub_path / "repo2"
    repo2.mkdir()
    (repo2 / ".git").mkdir()

    # Mock sync_repo to fail for repo1 and succeed for repo2
    def side_effect(repo_root: Path, *args: Any, **kwargs: Any) -> dict:
        if repo_root.name == "repo1":
            raise RuntimeError("Simulated sync failure")
        return {
            "status": "ok",
            "summary": {"add": 0, "update": 0, "skip": 1, "blocked": 0, "error": 0},
            "details": [],
        }

    with patch("merger.repoground.adapters.metarepo.sync_repo", side_effect=side_effect):
        report = sync_from_metarepo(hub_path, mode="apply")

    assert report["status"] == "error"
    assert report["aggregate_summary"]["error"] == 1

    assert report["repos"]["repo1"]["status"] == "error"
    assert "Simulated sync failure" in report["repos"]["repo1"]["details"][0]["reason"]

    assert report["repos"]["repo2"]["status"] == "ok"

    # Deterministic ordering
    repo_keys = list(report["repos"].keys())
    assert repo_keys == sorted(repo_keys)


def test_source_hash_error(tmp_path: Path) -> None:
    """
    Test that a hash computation error on the source file results in an ERROR action
    and error status for the repository.
    """
    hub_path = tmp_path / "hub"
    hub_path.mkdir()

    metarepo = hub_path / "metarepo"
    metarepo.mkdir()
    (metarepo / "sync").mkdir()

    # Create source file
    source_file = metarepo / "bad_hash.txt"
    source_file.write_text("content", encoding="utf-8")

    manifest = {
        "version": 1,
        "entries": [
            {
                "id": "bad_hash",
                "source": "bad_hash.txt",
                "targets": ["target.txt"],
                "mode": "copy",
            }
        ],
    }
    with (metarepo / MANIFEST_REL_PATH).open("w", encoding="utf-8") as f:
        yaml.dump(manifest, f)

    repo_path = hub_path / "repo1"
    repo_path.mkdir()
    (repo_path / ".git").mkdir()

    # Patch compute_file_hash to return HASH_COMPUTATION_ERROR for source
    with patch("merger.repoground.adapters.metarepo.compute_file_hash") as mock_hash:
        def side_effect(path: Path) -> str:
            if path.name == "bad_hash.txt":
                return HASH_COMPUTATION_ERROR
            return "a" * 64

        mock_hash.side_effect = side_effect
        report = sync_from_metarepo(hub_path, mode="apply")

    assert report["status"] == "error"
    assert report["aggregate_summary"]["error"] == 1

    repo_report = report["repos"]["repo1"]
    assert repo_report["status"] == "error"
    assert repo_report["summary"]["error"] == 1

    details = repo_report["details"][0]
    assert details["action"] == "ERROR"
    assert details["reason"] == "source_hash_failed"


def test_target_hash_error(tmp_path: Path) -> None:
    """
    Test that a hash computation error on the target file results in an ERROR action
    and error status for the repository.
    """
    hub_path = tmp_path / "hub"
    hub_path.mkdir()

    metarepo = hub_path / "metarepo"
    metarepo.mkdir()
    (metarepo / "sync").mkdir()

    source_file = metarepo / "good.txt"
    source_file.write_text("content", encoding="utf-8")

    manifest = {
        "version": 1,
        "entries": [
            {
                "id": "good",
                "source": "good.txt",
                "targets": ["target.txt"],
                "mode": "copy",
            }
        ],
    }
    with (metarepo / MANIFEST_REL_PATH).open("w", encoding="utf-8") as f:
        yaml.dump(manifest, f)

    repo_path = hub_path / "repo1"
    repo_path.mkdir()
    (repo_path / ".git").mkdir()

    # Create target file
    target_file = repo_path / "target.txt"
    target_file.write_text("existing content", encoding="utf-8")

    # Patch compute_file_hash to return HASH_COMPUTATION_ERROR for target
    with patch("merger.repoground.adapters.metarepo.compute_file_hash") as mock_hash:
        def side_effect(path: Path) -> str:
            if path.name == "target.txt":
                return HASH_COMPUTATION_ERROR
            return "b" * 64  # For source file

        mock_hash.side_effect = side_effect
        report = sync_from_metarepo(hub_path, mode="apply")

    assert report["status"] == "error"
    assert report["aggregate_summary"]["error"] == 1

    repo_report = report["repos"]["repo1"]
    assert repo_report["status"] == "error"
    assert repo_report["summary"]["error"] == 1

    details = repo_report["details"][0]
    assert details["action"] == "ERROR"
    assert details["reason"] == "target_hash_failed"


def test_load_manifest_returns_none_when_manifest_missing(tmp_path: Path) -> None:
    """
    Test that load_manifest returns None when the manifest file is missing.
    """
    assert load_manifest(tmp_path) is None


def test_load_manifest_returns_none_when_manifest_yaml_invalid(tmp_path: Path) -> None:
    """
    Test that load_manifest returns None when the manifest contains invalid YAML.
    """
    metarepo_path = tmp_path / "metarepo"
    metarepo_path.mkdir()
    manifest_file = metarepo_path / MANIFEST_REL_PATH
    manifest_file.parent.mkdir(parents=True, exist_ok=True)
    # Clearly invalid: unclosed list
    manifest_file.write_text("entries: [ unclosed list", encoding="utf-8")

    assert load_manifest(metarepo_path) is None


def test_load_manifest_returns_data_for_valid_manifest(tmp_path: Path) -> None:
    """
    Test that load_manifest returns parsed data for a valid manifest file.
    """
    metarepo_path = tmp_path / "metarepo"
    metarepo_path.mkdir()
    manifest_file = metarepo_path / MANIFEST_REL_PATH
    manifest_file.parent.mkdir(parents=True, exist_ok=True)

    manifest_data = {
        "version": 1,
        "entries": [{"id": "test", "source": "src.txt", "targets": ["tgt.txt"]}]
    }
    with manifest_file.open("w", encoding="utf-8") as f:
        yaml.dump(manifest_data, f)

    loaded = load_manifest(metarepo_path)
    assert loaded == manifest_data
