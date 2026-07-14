import hashlib
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import jsonschema
import pytest

from merger.lenskit.cli.main import main
from merger.lenskit.cli import cmd_repobrief
from merger.lenskit.core import repobrief_latest_complete as latest_complete
from merger.lenskit.core.repobrief_latest_complete import (
    LatestCompletePublicationError,
    build_latest_complete_registry,
    latest_complete_status,
    write_latest_complete_registry,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _git_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "Test User")
    (repo / "README.md").write_text("first\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "first")
    return repo, _git(repo, "rev-parse", "HEAD")


def _make_latest_complete_eligible(
    manifest: Path,
    *,
    profile: str = "agent-portable",
    output_status: str = "pass",
    post_status: str = "pass",
    surface_status: str = "pass",
    gate_status: str = "pass",
    export_status: str = "pass",
) -> None:
    data = json.loads(manifest.read_text(encoding="utf-8"))
    stem = manifest.name.removesuffix(".bundle.manifest.json")
    sidecars = {
        "output_health": (
            manifest.with_name(f"{stem}.output_health.json"),
            {"kind": "lenskit.output_health", "verdict": output_status},
        ),
        "post_emit_health": (
            manifest.with_name(f"{stem}.post_emit_health.json"),
            {"kind": "lenskit.post_emit_health", "status": post_status},
        ),
        "bundle_surface_validation": (
            manifest.with_name(f"{stem}.bundle_surface_validation.json"),
            {"kind": "lenskit.bundle_surface_validation", "status": surface_status},
        ),
        "agent_export_gate": (
            manifest.with_name(f"{stem}.agent_export_gate.json"),
            {"kind": "lenskit.agent_export_gate", "status": gate_status},
        ),
        "export_safety_report": (
            manifest.with_name(f"{stem}.export_safety_report.json"),
            {"kind": "lenskit.export_safety_report", "status": export_status},
        ),
    }
    for _, (path, document) in sidecars.items():
        path.write_text(json.dumps(document), encoding="utf-8")

    artifacts = data.setdefault("artifacts", [])
    output_path = sidecars["output_health"][0]
    artifacts[:] = [
        artifact
        for artifact in artifacts
        if not (isinstance(artifact, dict) and artifact.get("role") == "output_health")
    ]
    artifacts.append(
        {
            "role": "output_health",
            "path": output_path.name,
            "content_type": "application/json",
            "bytes": output_path.stat().st_size,
            "sha256": _sha(output_path),
        }
    )
    links = data.setdefault("links", {})
    links.update(
        {
            "post_emit_health_path": sidecars["post_emit_health"][0].name,
            "bundle_surface_validation_path": sidecars["bundle_surface_validation"][
                0
            ].name,
            "agent_export_gate_path": sidecars["agent_export_gate"][0].name,
            "agent_export_gate_status": gate_status,
            "export_safety_report_path": sidecars["export_safety_report"][0].name,
            "export_safety_report_status": export_status,
        }
    )
    capabilities = data.setdefault("capabilities", {})
    capabilities["repobrief_profile"] = profile
    capabilities["repobrief_profile_evaluation"] = {
        "status": "pass",
        "profile": profile,
    }
    manifest.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _manifest(
    tmp_path: Path,
    *,
    commit: str | None = None,
    health_status: str = "pass",
    created_at: str = "2026-07-08T10:00:00Z",
    run_id: str = "run-1",
    repo_name: str = "repo",
    repo_remote: str | None = None,
) -> Path:
    canonical = tmp_path / "demo.md"
    canonical.write_text("# demo\n", encoding="utf-8")
    manifest = tmp_path / "demo.bundle.manifest.json"
    data = {
        "kind": "repolens.bundle.manifest",
        "version": "1.0",
        "run_id": run_id,
        "created_at": created_at,
        "artifacts": [
            {
                "role": "canonical_md",
                "path": canonical.name,
                "content_type": "text/markdown",
                "bytes": canonical.stat().st_size,
                "sha256": _sha(canonical),
            },
        ],
        "links": {},
        "capabilities": {},
        "snapshot_provenance": {
            "version": "v1",
            "repositories": [
                {
                    "name": repo_name,
                    "repo_root": str(tmp_path / "repo"),
                    "repo_remote": repo_remote,
                    "git_commit": commit,
                    "git_dirty": False,
                    "git_branch": "main",
                    "provenance_status": "present"
                    if commit
                    else "producer_did_not_collect",
                    "freshness_basis": "git_commit" if commit else "unknown",
                }
            ],
            "does_not_establish": ["freshness_against_remote"],
        },
    }
    manifest.write_text(json.dumps(data, indent=2), encoding="utf-8")
    _make_latest_complete_eligible(manifest, output_status=health_status)
    return manifest


def test_build_latest_complete_registry_records_manifest_source_and_health(tmp_path):
    manifest = _manifest(tmp_path, commit="a" * 40)
    registry_path = tmp_path / "latest.json"

    registry = build_latest_complete_registry(
        manifest,
        registry_path=registry_path,
        checked_at="2026-07-08T11:00:00Z",
    )

    assert registry["kind"] == "repobrief.latest_complete_registry"
    assert registry["bundle"]["stem"] == "demo"
    assert registry["bundle"]["manifest_path"] == "demo.bundle.manifest.json"
    assert registry["bundle"]["manifest_sha256"] == _sha(manifest)
    assert registry["bundle"]["generated_at"] == "2026-07-08T10:00:00Z"
    assert registry["source"]["commit"] == "a" * 40
    assert registry["source"]["commit_status"] == "single_repo_commit"
    assert registry["health"]["status"] == "pass"
    assert registry["health"]["signals"]["output_health"]["status"] == "pass"
    assert registry["eligibility"]["status"] == "pass"
    assert registry["version"] == "v2"
    assert registry["bundle"]["manifest_capture"] == "single_read_bytes_sha256_bound"
    assert registry["bundle"]["manifest_bytes"] == manifest.stat().st_size
    assert registry["selection"]["basis"] == "generated_at_fail_closed_ties_v2"
    assert registry["publication"]["directory_fsync_required"] is True
    assert registry["publication"]["uncertain_after_replace_reported"] is True
    assert registry["freshness"]["status"] == "unknown"
    assert registry["freshness"]["reason"] == "live_repo_not_checked"
    assert registry["mutation_boundary"]["writes"] == [
        "latest_complete_registry_parent_directory",
        "latest_complete_registry_temporary_file",
        "latest_complete_registry",
    ]
    assert registry["mutation_boundary"]["hidden_refresh_allowed"] is False


def test_latest_complete_registry_schema_accepts_emitted_registry(tmp_path):
    manifest = _manifest(tmp_path, commit="b" * 40)
    registry_path = tmp_path / "latest.json"
    result = write_latest_complete_registry(manifest, registry_path)
    schema = json.loads(
        Path(
            "merger/lenskit/contracts/repobrief-latest-complete-registry.v2.schema.json"
        ).read_text(encoding="utf-8")
    )

    assert result["status"] == "ok"
    assert result["publication_result"] == "published"
    jsonschema.validate(
        instance=json.loads(registry_path.read_text(encoding="utf-8")), schema=schema
    )


def test_v2_schema_rejects_contradictory_root_identity(tmp_path):
    manifest = _manifest(tmp_path, commit="b" * 40)
    registry = build_latest_complete_registry(
        manifest,
        registry_path=tmp_path / "latest.json",
        checked_at="2026-07-08T11:00:00Z",
    )
    repository = registry["source"]["repositories"][0]
    repository["source_identity_basis"] = "repo_root_sha256"
    repository["repo_root_recorded"] = False
    repository["repo_root_sha256"] = None
    schema = json.loads(
        Path(
            "merger/lenskit/contracts/repobrief-latest-complete-registry.v2.schema.json"
        ).read_text(encoding="utf-8")
    )

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=registry, schema=schema)


def test_latest_complete_status_detects_head_drift_without_writing(tmp_path):
    repo, first_commit = _git_repo(tmp_path)
    manifest = _manifest(tmp_path, commit=first_commit)
    registry_path = tmp_path / "latest.json"
    write_latest_complete_registry(manifest, registry_path)

    before_files = {path.name for path in tmp_path.iterdir()}
    before_registry_hash = _sha(registry_path)
    before_manifest_hash = _sha(manifest)
    fresh = latest_complete_status(
        registry_path,
        repo=repo,
        checked_at="2026-07-08T11:00:00Z",
    )

    assert fresh["freshness"]["status"] == "fresh"
    assert fresh["freshness"]["head_drift"] is False
    assert fresh["manifest_hash"]["status"] == "match"
    assert fresh["mutation_boundary"]["writes"] == []
    assert fresh["mutation_boundary"]["hidden_refresh_allowed"] is False
    assert {path.name for path in tmp_path.iterdir()} == before_files
    assert _sha(registry_path) == before_registry_hash
    assert _sha(manifest) == before_manifest_hash

    (repo / "README.md").write_text("second\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "second")

    stale = latest_complete_status(
        registry_path,
        repo=repo,
        checked_at="2026-07-08T11:05:00Z",
    )

    assert stale["status"] == "ok"
    assert stale["freshness"]["status"] == "stale"
    assert stale["freshness"]["reason"] == "head_drift"
    assert stale["freshness"]["snapshot_commit"] == first_commit
    assert stale["freshness"]["live_head"] != first_commit
    assert stale["freshness"]["head_drift"] is True
    assert _sha(registry_path) == before_registry_hash


def test_latest_complete_status_without_repo_is_unknown_not_failure(tmp_path):
    manifest = _manifest(tmp_path, commit="c" * 40)
    registry_path = tmp_path / "latest.json"
    write_latest_complete_registry(manifest, registry_path)

    status = latest_complete_status(registry_path)

    assert status["status"] == "ok"
    assert status["freshness"]["status"] == "unknown"
    assert status["freshness"]["reason"] == "live_repo_not_provided"
    assert status["mutation_boundary"]["writes"] == []


def test_latest_complete_cli_write_and_status(tmp_path, capsys):
    repo, commit = _git_repo(tmp_path)
    manifest = _manifest(tmp_path, commit=commit)
    registry_path = tmp_path / "latest.json"

    rc = main(
        [
            "repobrief",
            "latest-complete",
            "write",
            "--bundle-manifest",
            str(manifest),
            "--out",
            str(registry_path),
        ]
    )

    write_out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert registry_path.exists()
    assert write_out["kind"] == "repobrief.latest_complete_registry_write"
    assert write_out["mutation_boundary"]["writes"] == [
        "latest_complete_registry_parent_directory",
        "latest_complete_registry_temporary_file",
        "latest_complete_registry",
    ]
    assert write_out["persistent_lock_artifact"] is False
    assert write_out["transaction"]["phase"] == "readback_verified"

    rc = main(
        [
            "repobrief",
            "latest-complete",
            "status",
            "--registry",
            str(registry_path),
            "--repo",
            str(repo),
        ]
    )

    status_out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert status_out["kind"] == "repobrief.latest_complete_status"
    assert status_out["freshness"]["status"] == "fresh"
    assert status_out["mutation_boundary"]["writes"] == []


def test_write_is_monotone_and_idempotent(tmp_path):
    older_dir = tmp_path / "older"
    newer_dir = tmp_path / "newer"
    older_dir.mkdir()
    newer_dir.mkdir()
    older = _manifest(
        older_dir,
        commit="1" * 40,
        created_at="2026-07-08T10:00:00Z",
        run_id="run-old",
        repo_remote="https://example.invalid/repo.git",
    )
    newer = _manifest(
        newer_dir,
        commit="2" * 40,
        created_at="2026-07-08T11:00:00Z",
        run_id="run-new",
        repo_remote="https://example.invalid/repo.git",
    )
    registry_path = tmp_path / "latest.json"

    first = write_latest_complete_registry(newer, registry_path)
    first_hash = _sha(registry_path)
    older_result = write_latest_complete_registry(older, registry_path)
    same_result = write_latest_complete_registry(newer, registry_path)

    assert first["publication_result"] == "published"
    assert older_result["publication_result"] == "unchanged"
    assert older_result["reason"] == "candidate_older_than_published"
    assert older_result["publication_state"] == "unchanged_existing"
    assert older_result["transaction"]["phase"] == "selection_verified"
    assert older_result["transaction"]["directory_identity"] == "match"
    assert same_result["publication_result"] == "unchanged"
    assert same_result["reason"] == "candidate_already_published_durability_revalidated"
    assert same_result["publication_state"] == "durability_revalidated"
    assert same_result["transaction"]["phase"] == "durability_revalidated"
    assert _sha(registry_path) == first_hash
    assert (
        json.loads(registry_path.read_text(encoding="utf-8"))["bundle"]["run_id"]
        == "run-new"
    )


def test_identical_retry_allows_new_publication_reference_time(tmp_path):
    manifest = _manifest(
        tmp_path,
        commit="3" * 40,
        repo_remote="https://example.invalid/repo.git",
    )
    registry_path = tmp_path / "latest.json"
    first = write_latest_complete_registry(
        manifest, registry_path, checked_at="2026-07-08T11:00:00Z"
    )
    before = registry_path.read_bytes()

    second = write_latest_complete_registry(
        manifest, registry_path, checked_at="2026-07-08T12:00:00Z"
    )

    assert first["publication_result"] == "published"
    assert second["publication_result"] == "unchanged"
    assert second["publication_state"] == "durability_revalidated"
    assert second["transaction"]["phase"] == "durability_revalidated"
    assert second["transaction"]["replace_performed"] is False
    assert second["mutation_boundary"]["observed_writes"] == []
    assert registry_path.read_bytes() == before


def test_same_manifest_v2_tampering_fails_stable_identity_check(tmp_path):
    manifest = _manifest(
        tmp_path,
        commit="3" * 40,
        repo_remote="https://example.invalid/repo.git",
    )
    registry_path = tmp_path / "latest.json"
    write_latest_complete_registry(
        manifest, registry_path, checked_at="2026-07-08T11:00:00Z"
    )
    tampered = json.loads(registry_path.read_text(encoding="utf-8"))
    tampered["health"]["status"] = "warn"
    registry_path.write_text(
        json.dumps(tampered, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    before = registry_path.read_bytes()

    with pytest.raises(
        LatestCompletePublicationError, match="stable identity"
    ) as caught:
        write_latest_complete_registry(
            manifest, registry_path, checked_at="2026-07-08T11:05:00Z"
        )

    assert caught.value.receipt["publication_state"] == "failed_before_replace"
    assert caught.value.receipt["transaction"]["replace_performed"] is False
    assert caught.value.receipt["mutation_boundary"]["observed_writes"] == []
    assert registry_path.read_bytes() == before


def test_older_candidate_rechecks_directory_identity_before_unchanged_result(
    monkeypatch, tmp_path
):
    older_dir = tmp_path / "older-identity"
    newer_dir = tmp_path / "newer-identity"
    older_dir.mkdir()
    newer_dir.mkdir()
    older = _manifest(
        older_dir,
        commit="4" * 40,
        created_at="2026-07-08T10:00:00Z",
        repo_remote="https://example.invalid/repo.git",
    )
    newer = _manifest(
        newer_dir,
        commit="5" * 40,
        created_at="2026-07-08T11:00:00Z",
        repo_remote="https://example.invalid/repo.git",
    )
    registry_path = tmp_path / "latest.json"
    write_latest_complete_registry(
        newer, registry_path, checked_at="2026-07-08T12:00:00Z"
    )
    real_assert_identity = latest_complete._assert_directory_identity
    calls = 0

    def fail_second_identity(path: Path, directory_fd: int) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated directory identity change before result")
        real_assert_identity(path, directory_fd)

    monkeypatch.setattr(
        latest_complete, "_assert_directory_identity", fail_second_identity
    )

    with pytest.raises(LatestCompletePublicationError) as caught:
        write_latest_complete_registry(
            older, registry_path, checked_at="2026-07-08T12:00:00Z"
        )

    receipt = caught.value.receipt
    assert receipt["error"]["code"] == "directory_identity_changed_before_result"
    assert receipt["publication_state"] == "failed_before_replace"
    assert receipt["transaction"]["replace_performed"] is False
    assert receipt["transaction"]["directory_identity"] == "failed"
    assert receipt["mutation_boundary"]["observed_writes"] == []


def test_concurrent_writers_publish_the_newest_candidate(tmp_path):
    older_dir = tmp_path / "older-concurrent"
    newer_dir = tmp_path / "newer-concurrent"
    older_dir.mkdir()
    newer_dir.mkdir()
    older = _manifest(
        older_dir,
        commit="a" * 40,
        created_at="2026-07-08T10:00:00Z",
        run_id="run-old",
        repo_remote="https://example.invalid/repo.git",
    )
    newer = _manifest(
        newer_dir,
        commit="b" * 40,
        created_at="2026-07-08T11:00:00Z",
        run_id="run-new",
        repo_remote="https://example.invalid/repo.git",
    )
    registry_path = tmp_path / "latest.json"
    script = (
        "from merger.lenskit.core.repobrief_latest_complete import "
        "write_latest_complete_registry; "
        "import sys; write_latest_complete_registry(sys.argv[1], sys.argv[2])"
    )
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", script, str(manifest), str(registry_path)],
            cwd=Path.cwd(),
        )
        for manifest in (older, newer)
    ]

    returncodes = [process.wait(timeout=20) for process in processes]

    assert returncodes == [0, 0]
    published = json.loads(registry_path.read_text(encoding="utf-8"))
    assert published["bundle"]["run_id"] == "run-new"
    assert published["source"]["commit"] == "b" * 40


def test_write_rejects_equal_timestamp_with_different_manifest(tmp_path):
    first_dir = tmp_path / "first-tie"
    second_dir = tmp_path / "second-tie"
    first_dir.mkdir()
    second_dir.mkdir()
    first = _manifest(
        first_dir,
        commit="c" * 40,
        run_id="run-first",
        repo_remote="https://example.invalid/repo.git",
    )
    second = _manifest(
        second_dir,
        commit="d" * 40,
        run_id="run-second",
        repo_remote="https://example.invalid/repo.git",
    )
    registry_path = tmp_path / "latest.json"
    write_latest_complete_registry(first, registry_path)
    before = registry_path.read_bytes()

    with pytest.raises(ValueError, match="generated_at collision"):
        write_latest_complete_registry(second, registry_path)

    assert registry_path.read_bytes() == before


def test_write_rejects_future_timestamp_without_creating_target_directory(tmp_path):
    manifest = _manifest(
        tmp_path,
        commit="e" * 40,
        created_at="2026-07-08T12:10:01Z",
    )
    target_dir = tmp_path / "missing-target"
    registry_path = target_dir / "latest.json"

    with pytest.raises(ValueError, match="generated_at_not_future"):
        write_latest_complete_registry(
            manifest,
            registry_path,
            checked_at="2026-07-08T12:00:00Z",
        )

    assert not target_dir.exists()


def test_write_uses_directory_lock_without_persistent_lock_artifact(tmp_path):
    manifest = _manifest(tmp_path, commit="f" * 40)
    registry_path = tmp_path / "latest.json"
    external = tmp_path / "external.lock"
    external.write_text("sentinel\n", encoding="utf-8")
    legacy_lock_path = tmp_path / ".latest.json.lock"
    legacy_lock_path.symlink_to(external)

    result = write_latest_complete_registry(manifest, registry_path)

    assert result["persistent_lock_artifact"] is False
    assert registry_path.exists()
    assert legacy_lock_path.is_symlink()
    assert external.read_text(encoding="utf-8") == "sentinel\n"


def test_write_rejects_incomplete_candidate_without_replacing_registry(tmp_path):
    valid_dir = tmp_path / "valid"
    invalid_dir = tmp_path / "invalid"
    valid_dir.mkdir()
    invalid_dir.mkdir()
    valid = _manifest(valid_dir, commit="3" * 40)
    invalid = _manifest(
        invalid_dir,
        commit="4" * 40,
        created_at="2026-07-08T12:00:00Z",
    )
    invalid_data = json.loads(invalid.read_text(encoding="utf-8"))
    post_path = invalid.parent / invalid_data["links"]["post_emit_health_path"]
    post_path.write_text(
        json.dumps({"kind": "lenskit.post_emit_health", "status": "fail"}),
        encoding="utf-8",
    )
    registry_path = tmp_path / "latest.json"
    write_latest_complete_registry(valid, registry_path)
    before = registry_path.read_bytes()

    with pytest.raises(ValueError, match="post_emit_health"):
        write_latest_complete_registry(invalid, registry_path)

    assert registry_path.read_bytes() == before


def test_write_rejects_source_lane_mismatch(tmp_path):
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    first_dir.mkdir()
    second_dir.mkdir()
    first = _manifest(first_dir, commit="5" * 40, repo_name="alpha")
    second = _manifest(
        second_dir,
        commit="6" * 40,
        repo_name="beta",
        created_at="2026-07-08T12:00:00Z",
    )
    registry_path = tmp_path / "latest.json"
    write_latest_complete_registry(first, registry_path)
    before = registry_path.read_bytes()

    with pytest.raises(ValueError, match="source lane mismatch"):
        write_latest_complete_registry(second, registry_path)

    assert registry_path.read_bytes() == before


def test_write_fsyncs_file_and_directory(monkeypatch, tmp_path):
    manifest = _manifest(tmp_path, commit="7" * 40)
    registry_path = tmp_path / "latest.json"
    observed_modes: list[int] = []
    real_fsync = os.fsync

    def recording_fsync(fd: int) -> None:
        observed_modes.append(os.fstat(fd).st_mode)
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", recording_fsync)
    write_latest_complete_registry(manifest, registry_path)

    assert any(stat.S_ISREG(mode) for mode in observed_modes)
    assert any(stat.S_ISDIR(mode) for mode in observed_modes)


def test_write_rejects_symlink_target(tmp_path):
    manifest = _manifest(tmp_path, commit="8" * 40)
    actual = tmp_path / "actual.json"
    actual.write_text("sentinel\n", encoding="utf-8")
    link = tmp_path / "latest.json"
    link.symlink_to(actual)

    with pytest.raises(ValueError, match="must not be a symlink"):
        write_latest_complete_registry(manifest, link)

    assert actual.read_text(encoding="utf-8") == "sentinel\n"


def test_status_warns_when_published_sidecar_drifts(tmp_path):
    manifest = _manifest(tmp_path, commit="9" * 40)
    registry_path = tmp_path / "latest.json"
    write_latest_complete_registry(manifest, registry_path)
    data = json.loads(manifest.read_text(encoding="utf-8"))
    output_path = manifest.parent / next(
        artifact["path"]
        for artifact in data["artifacts"]
        if artifact.get("role") == "output_health"
    )
    output_path.write_text(
        json.dumps({"kind": "lenskit.output_health", "verdict": "warn"}),
        encoding="utf-8",
    )

    status_result = latest_complete_status(registry_path)

    assert status_result["status"] == "warn"
    assert status_result["eligibility"]["sidecar_hash_drift"] == ["output_health"]


def _as_legacy_v1(registry: dict) -> dict:
    legacy = json.loads(json.dumps(registry))
    legacy["version"] = "v1"
    legacy["bundle"].pop("manifest_bytes", None)
    legacy["bundle"].pop("manifest_capture", None)
    legacy["selection"]["basis"] = "generated_at_fail_closed_ties_v1"
    legacy["selection"].pop("registry_version", None)
    legacy["publication"] = {
        "serialization": "advisory_file_lock",
        "atomic_replace": True,
        "file_fsync": True,
        "directory_fsync": True,
        "readback_verified": True,
    }
    for repository in legacy["source"]["repositories"]:
        repository.pop("repo_remote_sanitized", None)
        repository.pop("repo_root_sha256", None)
        repository.pop("source_identity_basis", None)
    return legacy


def test_manifest_parse_and_hash_share_one_byte_capture(monkeypatch, tmp_path):
    manifest = _manifest(tmp_path, commit="a" * 40)
    expected_payload = manifest.read_bytes()
    real_read_bytes = Path.read_bytes
    manifest_reads = 0

    def recording_read_bytes(path: Path) -> bytes:
        nonlocal manifest_reads
        payload = real_read_bytes(path)
        if path == manifest:
            manifest_reads += 1
        return payload

    monkeypatch.setattr(Path, "read_bytes", recording_read_bytes)

    registry = build_latest_complete_registry(
        manifest,
        registry_path=tmp_path / "latest.json",
        checked_at="2026-07-08T11:00:00Z",
    )

    assert manifest_reads == 1
    assert registry["bundle"]["manifest_sha256"] == hashlib.sha256(
        expected_payload
    ).hexdigest()
    assert registry["bundle"]["manifest_bytes"] == len(expected_payload)


def test_same_repo_name_without_remote_uses_hashed_root_identity(tmp_path):
    first_dir = tmp_path / "root-a"
    second_dir = tmp_path / "root-b"
    first_dir.mkdir()
    second_dir.mkdir()
    first = _manifest(first_dir, commit="1" * 40, repo_name="repo")
    second = _manifest(
        second_dir,
        commit="2" * 40,
        repo_name="repo",
        created_at="2026-07-08T11:00:00Z",
    )
    registry_path = tmp_path / "latest.json"

    write_latest_complete_registry(
        first, registry_path, checked_at="2026-07-08T12:00:00Z"
    )

    with pytest.raises(ValueError, match="source lane mismatch"):
        write_latest_complete_registry(
            second, registry_path, checked_at="2026-07-08T12:00:00Z"
        )


def test_remote_credentials_are_removed_from_registry_identity(tmp_path):
    manifest = _manifest(
        tmp_path,
        commit="2" * 40,
        repo_remote=(
            "https://deploy-user:super-secret@example.invalid/repo.git/"
            "?access_token=also-secret#fragment"
        ),
    )

    registry = build_latest_complete_registry(
        manifest,
        registry_path=tmp_path / "latest.json",
        checked_at="2026-07-08T11:00:00Z",
    )

    repository = registry["source"]["repositories"][0]
    serialized = json.dumps(registry, sort_keys=True)
    assert repository["repo_remote"] == "https://example.invalid/repo.git"
    assert repository["repo_remote_sanitized"] is True
    assert registry["selection"]["source_lane"] == [
        ["repo", "remote:https://example.invalid/repo.git"]
    ]
    assert "super-secret" not in serialized
    assert "also-secret" not in serialized
    assert "deploy-user" not in serialized


def test_local_file_remote_falls_back_to_absolute_root_identity(tmp_path):
    manifest = _manifest(
        tmp_path,
        commit="2" * 40,
        repo_remote=f"file://{tmp_path}",
    )

    registry = build_latest_complete_registry(
        manifest,
        registry_path=tmp_path / "latest.json",
        checked_at="2026-07-08T11:00:00Z",
    )

    repository = registry["source"]["repositories"][0]
    assert repository["repo_remote"] is None
    assert repository["repo_remote_sanitized"] is False
    assert repository["source_identity_basis"] == "repo_root_sha256"
    assert registry["selection"]["source_lane"][0][1].startswith(
        "root-sha256:"
    )


def test_malformed_recorded_remote_falls_back_to_bound_root_hash():
    root_sha256 = "a" * 64
    lane = latest_complete._source_lane(
        {
            "repositories": [
                {
                    "name": "repo",
                    "repo_remote": "file:///tmp/not-a-global-identity",
                    "repo_root_sha256": root_sha256,
                }
            ]
        }
    )

    assert lane == [["repo", f"root-sha256:{root_sha256}"]]
    assert "remote:None" not in json.dumps(lane)


def test_malformed_recorded_remote_without_root_is_not_a_lane():
    lane = latest_complete._source_lane(
        {
            "repositories": [
                {
                    "name": "repo",
                    "repo_remote": "file:///tmp/not-a-global-identity",
                    "repo_root_sha256": None,
                }
            ]
        }
    )

    assert lane == []


def test_relative_repo_root_without_remote_is_not_an_identity(tmp_path):
    manifest = _manifest(tmp_path, commit="2" * 40, repo_name="repo")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["snapshot_provenance"]["repositories"][0]["repo_root"] = "relative/repo"
    manifest.write_text(json.dumps(data, indent=2), encoding="utf-8")

    with pytest.raises(ValueError, match="source_lane_unambiguous"):
        build_latest_complete_registry(
            manifest,
            registry_path=tmp_path / "latest.json",
            checked_at="2026-07-08T11:00:00Z",
        )


def test_valid_remote_bound_v1_registry_migrates_to_v2(tmp_path):
    manifest = _manifest(
        tmp_path,
        commit="3" * 40,
        repo_remote="https://example.invalid/repo.git",
    )
    registry_path = tmp_path / "latest.json"
    candidate = build_latest_complete_registry(
        manifest,
        registry_path=registry_path,
        checked_at="2026-07-08T11:00:00Z",
    )
    registry_path.write_text(
        json.dumps(_as_legacy_v1(candidate), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    result = write_latest_complete_registry(
        manifest, registry_path, checked_at="2026-07-08T11:00:00Z"
    )

    assert result["publication_result"] == "published"
    assert result["reason"] == "legacy_registry_migrated"
    assert result["existing_registry_version"] == "v1"
    assert json.loads(registry_path.read_text(encoding="utf-8"))["version"] == "v2"


def test_legacy_v1_future_clock_cannot_block_valid_candidate(tmp_path):
    manifest = _manifest(
        tmp_path,
        commit="4" * 40,
        repo_remote="https://example.invalid/repo.git",
    )
    registry_path = tmp_path / "latest.json"
    legacy = _as_legacy_v1(
        build_latest_complete_registry(
            manifest,
            registry_path=registry_path,
            checked_at="2026-07-08T11:00:00Z",
        )
    )
    legacy["updated_at"] = "2099-01-01T00:00:00Z"
    legacy["bundle"]["generated_at"] = "2099-01-01T00:00:00Z"
    registry_path.write_text(
        json.dumps(legacy, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    result = write_latest_complete_registry(
        manifest, registry_path, checked_at="2026-07-08T11:00:00Z"
    )

    assert result["publication_result"] == "published"
    assert result["reason"] == "legacy_registry_future_bundle_clock_replaced"
    assert result["existing_future_clock_fields"] == [
        "updated_at",
        "bundle.generated_at",
    ]
    migrated = json.loads(registry_path.read_text(encoding="utf-8"))
    assert migrated["version"] == "v2"
    assert migrated["bundle"]["generated_at"] == "2026-07-08T10:00:00Z"



def test_legacy_v1_future_updated_at_does_not_downgrade_newer_bundle(tmp_path):
    legacy_dir = tmp_path / "legacy"
    candidate_dir = tmp_path / "candidate"
    legacy_dir.mkdir()
    candidate_dir.mkdir()
    legacy_manifest = _manifest(
        legacy_dir,
        commit="4" * 40,
        repo_remote="https://example.invalid/repo.git",
        created_at="2026-07-08T11:00:00Z",
        run_id="newer-legacy",
    )
    candidate_manifest = _manifest(
        candidate_dir,
        commit="5" * 40,
        repo_remote="https://example.invalid/repo.git",
        created_at="2026-07-08T10:00:00Z",
        run_id="older-candidate",
    )
    registry_path = tmp_path / "latest.json"
    legacy = _as_legacy_v1(
        build_latest_complete_registry(
            legacy_manifest,
            registry_path=registry_path,
            checked_at="2026-07-08T12:00:00Z",
        )
    )
    legacy["updated_at"] = "2099-01-01T00:00:00Z"
    registry_path.write_text(
        json.dumps(legacy, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    before = registry_path.read_bytes()

    result = write_latest_complete_registry(
        candidate_manifest, registry_path, checked_at="2026-07-08T12:00:00Z"
    )

    assert result["publication_result"] == "unchanged"
    assert result["reason"] == "candidate_older_than_published"
    assert result["existing_registry_version"] == "v1"
    assert result["existing_future_clock_fields"] == ["updated_at"]
    assert result["mutation_boundary"]["observed_writes"] == []
    assert registry_path.read_bytes() == before


def test_v2_future_clock_still_fails_closed(tmp_path):
    manifest = _manifest(
        tmp_path,
        commit="d" * 40,
        repo_remote="https://example.invalid/repo.git",
    )
    registry_path = tmp_path / "latest.json"
    write_latest_complete_registry(
        manifest, registry_path, checked_at="2026-07-08T11:00:00Z"
    )
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["updated_at"] = "2099-01-01T00:00:00Z"
    registry["bundle"]["generated_at"] = "2099-01-01T00:00:00Z"
    registry["selection"]["generated_at"] = "2099-01-01T00:00:00Z"
    registry["selection"]["order_key"] = ["2099-01-01T00:00:00.000000Z"]
    registry_path.write_text(
        json.dumps(registry, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    before = registry_path.read_bytes()

    with pytest.raises(LatestCompletePublicationError, match="implausibly future") as caught:
        write_latest_complete_registry(
            manifest, registry_path, checked_at="2026-07-08T11:00:00Z"
        )

    assert caught.value.receipt["publication_state"] == "failed_before_replace"
    assert caught.value.receipt["transaction"]["replace_performed"] is False
    assert caught.value.receipt["mutation_boundary"]["observed_writes"] == []
    assert registry_path.read_bytes() == before

def test_legacy_v1_without_remote_identity_fails_closed(tmp_path):
    manifest = _manifest(tmp_path, commit="5" * 40)
    registry_path = tmp_path / "latest.json"
    legacy = _as_legacy_v1(
        build_latest_complete_registry(
            manifest,
            registry_path=registry_path,
            checked_at="2026-07-08T11:00:00Z",
        )
    )
    registry_path.write_text(
        json.dumps(legacy, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    with pytest.raises(ValueError, match="ambiguous without a non-local repo_remote"):
        write_latest_complete_registry(
            manifest, registry_path, checked_at="2026-07-08T11:00:00Z"
        )



def test_write_reports_new_parent_directory_as_observed_write(tmp_path):
    manifest = _manifest(tmp_path, commit="e" * 40)
    registry_path = tmp_path / "new-publication-lane" / "latest.json"

    result = write_latest_complete_registry(
        manifest, registry_path, checked_at="2026-07-08T11:00:00Z"
    )

    assert result["target_directory_created"] is True
    assert result["target_directories_created"] == [
        str(registry_path.parent)
    ]
    assert result["mutation_boundary"]["observed_writes"] == [
        "latest_complete_registry_parent_directory",
        "latest_complete_registry_temporary_file",
        "latest_complete_registry",
    ]
    assert registry_path.exists()


def test_concurrent_parent_creation_is_not_claimed_by_writer(monkeypatch, tmp_path):
    manifest = _manifest(tmp_path, commit="e" * 40)
    parent = tmp_path / "concurrently-created"
    registry_path = parent / "latest.json"
    real_mkdir = latest_complete.os.mkdir
    injected = False

    def concurrent_mkdir(path, mode=0o777):
        nonlocal injected
        if Path(path) == parent and not injected:
            injected = True
            real_mkdir(path, mode)
            raise FileExistsError(str(path))
        return real_mkdir(path, mode)

    monkeypatch.setattr(latest_complete.os, "mkdir", concurrent_mkdir)

    result = write_latest_complete_registry(
        manifest, registry_path, checked_at="2026-07-08T11:00:00Z"
    )

    assert injected is True
    assert result["target_directory_created"] is False
    assert result["target_directories_created"] == []
    assert result["mutation_boundary"]["observed_writes"] == [
        "latest_complete_registry_temporary_file",
        "latest_complete_registry",
    ]
    assert registry_path.exists()


def test_partial_parent_creation_failure_reports_exact_created_paths(
    monkeypatch, tmp_path
):
    manifest = _manifest(tmp_path, commit="e" * 40)
    first = tmp_path / "partial-parent"
    second = first / "blocked-child"
    registry_path = second / "latest.json"
    real_mkdir = latest_complete.os.mkdir

    def fail_second_mkdir(path, mode=0o777):
        if Path(path) == second:
            raise PermissionError("simulated child directory creation failure")
        return real_mkdir(path, mode)

    monkeypatch.setattr(latest_complete.os, "mkdir", fail_second_mkdir)

    with pytest.raises(LatestCompletePublicationError) as caught:
        write_latest_complete_registry(
            manifest, registry_path, checked_at="2026-07-08T11:00:00Z"
        )

    receipt = caught.value.receipt
    assert receipt["publication_state"] == "failed_before_replace"
    assert receipt["error"]["code"] == "target_directory_prepare_failed"
    assert receipt["target_directory_created"] is True
    assert receipt["target_directories_created"] == [str(first)]
    assert receipt["mutation_boundary"]["observed_writes"] == [
        "latest_complete_registry_parent_directory"
    ]
    assert first.is_dir()
    assert not second.exists()
    assert not registry_path.exists()


def test_directory_identity_change_before_replace_fails_without_registry(
    monkeypatch, tmp_path
):
    manifest = _manifest(tmp_path, commit="f" * 40)
    registry_path = tmp_path / "latest.json"

    def fail_pre_replace_identity(path: Path, directory_fd: int) -> None:
        raise OSError("simulated directory identity change before replace")

    monkeypatch.setattr(
        latest_complete, "_assert_directory_identity", fail_pre_replace_identity
    )

    with pytest.raises(LatestCompletePublicationError) as caught:
        write_latest_complete_registry(
            manifest, registry_path, checked_at="2026-07-08T11:00:00Z"
        )

    receipt = caught.value.receipt
    assert receipt["publication_state"] == "failed_before_replace"
    assert receipt["error"]["code"] == "directory_identity_changed_before_replace"
    assert receipt["transaction"]["replace_performed"] is False
    assert receipt["transaction"]["directory_identity"] == "failed"
    assert receipt["mutation_boundary"]["observed_writes"] == []
    assert not registry_path.exists()



def test_temp_create_failure_does_not_claim_write_or_fsync(
    monkeypatch, tmp_path
):
    manifest = _manifest(tmp_path, commit="6" * 40)
    registry_path = tmp_path / "latest.json"

    def fail_temp_create(directory_fd: int, target_name: str):
        raise OSError("simulated temporary file creation failure")

    monkeypatch.setattr(latest_complete, "_open_unique_temp", fail_temp_create)

    with pytest.raises(LatestCompletePublicationError) as caught:
        write_latest_complete_registry(
            manifest, registry_path, checked_at="2026-07-08T11:00:00Z"
        )

    receipt = caught.value.receipt
    assert receipt["error"]["code"] == "temp_create_failed"
    assert receipt["transaction"]["temporary_file_created"] is False
    assert receipt["transaction"]["temporary_file_write"] == "not_reached"
    assert receipt["transaction"]["file_fsync"] == "not_reached"
    assert receipt["mutation_boundary"]["observed_writes"] == []
    assert not registry_path.exists()

def test_atomic_replace_failure_reports_removed_temp_mutation(
    monkeypatch, tmp_path
):
    manifest = _manifest(tmp_path, commit="6" * 40)
    registry_path = tmp_path / "latest.json"

    def fail_replace(*args, **kwargs):
        raise OSError("simulated atomic replace failure")

    monkeypatch.setattr(latest_complete.os, "replace", fail_replace)

    with pytest.raises(LatestCompletePublicationError) as caught:
        write_latest_complete_registry(
            manifest, registry_path, checked_at="2026-07-08T11:00:00Z"
        )

    receipt = caught.value.receipt
    assert receipt["publication_state"] == "failed_before_replace"
    assert receipt["error"]["code"] == "atomic_replace_failed"
    assert receipt["transaction"]["temporary_file_created"] is True
    assert receipt["transaction"]["temporary_file_cleanup"] == "removed"
    assert receipt["mutation_boundary"]["observed_writes"] == [
        "latest_complete_registry_temporary_file"
    ]
    assert not registry_path.exists()
    assert not list(tmp_path.glob(".latest.json.*.tmp"))


def test_temp_cleanup_failure_is_explicit_and_recoverable(monkeypatch, tmp_path):
    manifest = _manifest(tmp_path, commit="7" * 40)
    registry_path = tmp_path / "latest.json"
    real_unlink = latest_complete.os.unlink

    def fail_replace(*args, **kwargs):
        raise OSError("simulated atomic replace failure")

    def fail_unlink(*args, **kwargs):
        raise OSError("simulated temporary cleanup failure")

    monkeypatch.setattr(latest_complete.os, "replace", fail_replace)
    monkeypatch.setattr(latest_complete.os, "unlink", fail_unlink)

    with pytest.raises(LatestCompletePublicationError) as caught:
        write_latest_complete_registry(
            manifest, registry_path, checked_at="2026-07-08T11:00:00Z"
        )

    receipt = caught.value.receipt
    temp_name = receipt["transaction"]["temporary_file_name"]
    assert receipt["publication_result"] == "not_published"
    assert receipt["publication_state"] == "failed_before_replace_with_temp_artifact"
    assert receipt["transaction"]["temporary_file_cleanup"] == "failed"
    assert receipt["recovery"]["required"] is True
    assert isinstance(temp_name, str) and temp_name.endswith(".tmp")
    assert receipt["mutation_boundary"]["observed_writes"] == [
        "latest_complete_registry_temporary_file"
    ]
    assert (tmp_path / temp_name).exists()
    assert not registry_path.exists()

    monkeypatch.setattr(latest_complete.os, "unlink", real_unlink)
    (tmp_path / temp_name).unlink()

def test_directory_fsync_failure_reports_uncertain_and_retry_recovers(
    monkeypatch, tmp_path
):
    manifest = _manifest(tmp_path, commit="6" * 40)
    registry_path = tmp_path / "latest.json"
    real_fsync_directory = latest_complete._fsync_locked_directory

    def fail_directory_fsync(directory_fd: int) -> None:
        raise OSError("simulated directory fsync failure")

    monkeypatch.setattr(latest_complete, "_fsync_locked_directory", fail_directory_fsync)

    with pytest.raises(LatestCompletePublicationError) as caught:
        write_latest_complete_registry(
            manifest, registry_path, checked_at="2026-07-08T11:00:00Z"
        )

    receipt = caught.value.receipt
    assert receipt["publication_state"] == "uncertain_after_replace"
    assert receipt["error"]["code"] == "directory_fsync_failed_after_replace"
    assert receipt["transaction"]["replace_performed"] is True
    assert receipt["transaction"]["target"]["matches_expected"] is True
    assert receipt["recovery"]["required"] is True
    assert registry_path.exists()

    monkeypatch.setattr(latest_complete, "_fsync_locked_directory", real_fsync_directory)
    recovered = write_latest_complete_registry(
        manifest, registry_path, checked_at="2026-07-08T11:00:00Z"
    )

    assert recovered["publication_result"] == "unchanged"
    assert recovered["transaction"]["phase"] == "durability_revalidated"
    assert recovered["recovery"]["required"] is False



def test_directory_identity_change_after_replace_is_structured(
    monkeypatch, tmp_path
):
    manifest = _manifest(tmp_path, commit="a" * 40)
    registry_path = tmp_path / "latest.json"
    real_assert_identity = latest_complete._assert_directory_identity
    calls = 0

    def fail_post_replace_identity(path: Path, directory_fd: int) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated directory identity change")
        real_assert_identity(path, directory_fd)

    monkeypatch.setattr(
        latest_complete, "_assert_directory_identity", fail_post_replace_identity
    )

    with pytest.raises(LatestCompletePublicationError) as caught:
        write_latest_complete_registry(
            manifest, registry_path, checked_at="2026-07-08T11:00:00Z"
        )

    receipt = caught.value.receipt
    assert receipt["publication_state"] == "uncertain_after_replace"
    assert receipt["error"]["code"] == "directory_identity_changed_after_replace"
    assert receipt["transaction"]["atomic_replace"] == "pass"
    assert receipt["transaction"]["directory_fsync"] == "pass"
    assert receipt["transaction"]["directory_identity"] == "failed"
    assert receipt["transaction"]["replace_performed"] is True
    assert registry_path.exists()


def test_revalidation_failure_does_not_claim_a_second_replace(
    monkeypatch, tmp_path
):
    manifest = _manifest(tmp_path, commit="b" * 40)
    registry_path = tmp_path / "latest.json"
    write_latest_complete_registry(
        manifest, registry_path, checked_at="2026-07-08T11:00:00Z"
    )

    def fail_directory_fsync(directory_fd: int) -> None:
        raise OSError("simulated revalidation fsync failure")

    monkeypatch.setattr(latest_complete, "_fsync_locked_directory", fail_directory_fsync)

    with pytest.raises(LatestCompletePublicationError) as caught:
        write_latest_complete_registry(
            manifest, registry_path, checked_at="2026-07-08T11:00:00Z"
        )

    receipt = caught.value.receipt
    assert receipt["publication_result"] == "uncertain"
    assert receipt["publication_state"] == "durability_unconfirmed"
    assert receipt["transaction"]["replace_performed"] is False
    assert receipt["mutation_boundary"]["observed_writes"] == []


def test_status_manifest_hash_and_parse_share_one_capture(monkeypatch, tmp_path):
    manifest = _manifest(tmp_path, commit="c" * 40)
    registry_path = tmp_path / "latest.json"
    write_latest_complete_registry(
        manifest, registry_path, checked_at="2026-07-08T11:00:00Z"
    )
    real_read_bytes = Path.read_bytes
    manifest_reads = 0

    def recording_read_bytes(path: Path) -> bytes:
        nonlocal manifest_reads
        payload = real_read_bytes(path)
        if path == manifest:
            manifest_reads += 1
        return payload

    monkeypatch.setattr(Path, "read_bytes", recording_read_bytes)

    status = latest_complete_status(
        registry_path, checked_at="2026-07-08T11:00:00Z"
    )

    assert status["manifest_hash"]["status"] == "match"
    assert status["eligibility"]["observed"]["status"] == "pass"
    assert manifest_reads == 1

def test_latest_complete_cli_emits_json_validation_error(tmp_path, capsys):
    manifest = _manifest(
        tmp_path,
        commit="7" * 40,
        created_at="2099-01-01T00:00:00Z",
    )
    registry_path = tmp_path / "missing" / "latest.json"

    rc = main(
        [
            "repobrief",
            "latest-complete",
            "write",
            "--bundle-manifest",
            str(manifest),
            "--out",
            str(registry_path),
        ]
    )

    captured = capsys.readouterr()
    error = json.loads(captured.err)
    assert rc == 2
    assert captured.out == ""
    assert error["status"] == "error"
    assert error["publication_state"] == "failed_before_replace"
    assert error["error"]["code"] == "validation_failed"
    assert error["mutation_boundary"]["observed_writes"] == []
    assert not registry_path.parent.exists()


def test_multi_repo_source_lane_requires_identity_for_every_repository(tmp_path):
    manifest = _manifest(
        tmp_path,
        commit="8" * 40,
        repo_remote="https://example.invalid/primary.git",
    )
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["snapshot_provenance"]["repositories"].append(
        {
            "name": "secondary",
            "repo_root": None,
            "repo_remote": None,
            "git_commit": "8" * 40,
            "git_dirty": False,
            "git_branch": "main",
            "provenance_status": "present",
            "freshness_basis": "git_commit",
        }
    )
    manifest.write_text(json.dumps(data, indent=2), encoding="utf-8")

    with pytest.raises(ValueError, match="source_lane_unambiguous"):
        build_latest_complete_registry(
            manifest,
            registry_path=tmp_path / "latest.json",
            checked_at="2026-07-08T11:00:00Z",
        )


def test_latest_complete_cli_reports_uncertain_after_replace(
    monkeypatch, tmp_path, capsys
):
    manifest = _manifest(tmp_path, commit="9" * 40)
    registry_path = tmp_path / "latest.json"

    def fail_directory_fsync(directory_fd: int) -> None:
        raise OSError("simulated directory fsync failure")

    monkeypatch.setattr(latest_complete, "_fsync_locked_directory", fail_directory_fsync)

    rc = main(
        [
            "repobrief",
            "latest-complete",
            "write",
            "--bundle-manifest",
            str(manifest),
            "--out",
            str(registry_path),
        ]
    )

    captured = capsys.readouterr()
    error = json.loads(captured.err)
    assert rc == 1
    assert captured.out == ""
    assert error["status"] == "error"
    assert error["publication_state"] == "uncertain_after_replace"
    assert error["publication_result"] == "uncertain"
    assert error["error"]["code"] == "directory_fsync_failed_after_replace"
    assert error["transaction"]["replace_performed"] is True
    assert error["transaction"]["target"]["matches_expected"] is True
    assert error["recovery"]["required"] is True
    assert registry_path.exists()


def test_latest_complete_cli_reports_unresolvable_output_path_as_json(
    tmp_path, capsys
):
    manifest = _manifest(tmp_path, commit="f" * 40)
    loop = tmp_path / "loop"
    loop.symlink_to(loop.name)
    registry_path = loop / "latest.json"

    rc = main(
        [
            "repobrief",
            "latest-complete",
            "write",
            "--bundle-manifest",
            str(manifest),
            "--out",
            str(registry_path),
        ]
    )

    captured = capsys.readouterr()
    error = json.loads(captured.err)
    assert rc == 2
    assert captured.out == ""
    assert error["status"] == "error"
    assert error["publication_state"] == "failed_before_replace"
    assert error["error"]["code"] == "validation_failed"
    assert "cannot be resolved safely" in error["error"]["message"]
    assert error["target_directory_created"] is False
    assert error["target_directories_created"] == []
    assert error["mutation_boundary"]["observed_writes"] == []


class _FakeArtifacts:
    def __init__(self, manifest: Path):
        self.bundle_manifest = manifest
        self.canonical_md = manifest.with_name("brief.md")
        self.canonical_md.write_text("# brief\n", encoding="utf-8")

    def get_all_paths(self):
        return [self.bundle_manifest, self.canonical_md]


def test_snapshot_create_can_explicitly_write_latest_complete_registry(
    monkeypatch, tmp_path, capsys
):
    repo, commit = _git_repo(tmp_path)
    out = tmp_path / "briefs"
    registry_path = tmp_path / "latest" / "registry.json"

    def fake_scan_repo(*args, **kwargs):
        return {
            "name": "repo",
            "root": repo,
            "files": [],
            "total_files": 0,
            "total_bytes": 0,
            "ext_hist": {},
        }

    def fake_write_reports_v2(*args, **kwargs):
        manifest = out / "repo_merge.bundle.manifest.json"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(
            json.dumps(
                {
                    "kind": "repolens.bundle.manifest",
                    "version": "1.0",
                    "run_id": "run-1",
                    "created_at": "2026-07-08T10:00:00Z",
                    "artifacts": [],
                    "links": {},
                    "capabilities": {},
                    "snapshot_provenance": {
                        "version": "v1",
                        "repositories": [
                            {
                                "name": "repo",
                                "repo_root": str(repo),
                                "repo_remote": None,
                                "git_commit": commit,
                                "git_dirty": False,
                                "git_branch": "main",
                                "provenance_status": "present",
                                "freshness_basis": "git_commit",
                            }
                        ],
                    },
                }
            ),
            encoding="utf-8",
        )
        return _FakeArtifacts(manifest)

    monkeypatch.setattr(cmd_repobrief, "scan_repo", fake_scan_repo)
    monkeypatch.setattr(cmd_repobrief, "write_reports_v2", fake_write_reports_v2)

    def fake_finalize(manifest, profile):
        _make_latest_complete_eligible(manifest, profile=profile)
        return {
            "status": "pass",
            "errors": [],
            "profile_evaluation": {"status": "pass", "profile": profile},
            "control_paths": [],
            "refreshed_paths": [],
        }

    monkeypatch.setattr(cmd_repobrief, "finalize_snapshot_bundle", fake_finalize)

    rc = main(
        [
            "repobrief",
            "snapshot",
            "create",
            "--repo",
            str(repo),
            "--out",
            str(out),
            "--profile",
            "agent-portable",
            "--latest-complete-registry",
            str(registry_path),
        ]
    )

    emitted = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert registry_path.exists()
    assert emitted["latest_complete_registry"]["status"] == "ok"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    assert registry["source"]["commit"] == commit
    assert registry["mutation_boundary"]["writes"] == [
        "latest_complete_registry_parent_directory",
        "latest_complete_registry_temporary_file",
        "latest_complete_registry",
    ]


def test_snapshot_create_does_not_advance_latest_registry_when_finalization_fails(
    monkeypatch, tmp_path, capsys
):
    repo, _ = _git_repo(tmp_path)
    out = tmp_path / "briefs"
    registry_path = tmp_path / "latest" / "registry.json"

    def fake_scan_repo(*args, **kwargs):
        return {
            "name": "repo",
            "root": repo,
            "files": [],
            "total_files": 0,
            "total_bytes": 0,
            "ext_hist": {},
        }

    def fake_write_reports_v2(*args, **kwargs):
        manifest = out / "repo_merge.bundle.manifest.json"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(
            json.dumps(
                {
                    "kind": "repolens.bundle.manifest",
                    "artifacts": [],
                    "links": {},
                    "capabilities": {},
                }
            ),
            encoding="utf-8",
        )
        return _FakeArtifacts(manifest)

    monkeypatch.setattr(cmd_repobrief, "scan_repo", fake_scan_repo)
    monkeypatch.setattr(cmd_repobrief, "write_reports_v2", fake_write_reports_v2)
    monkeypatch.setattr(
        cmd_repobrief,
        "finalize_snapshot_bundle",
        lambda manifest, profile: {
            "status": "fail",
            "errors": ["agent_export_gate:fail"],
            "profile_evaluation": {"status": "pass", "profile": profile},
            "control_paths": [],
            "refreshed_paths": [],
        },
    )

    rc = main(
        [
            "repobrief",
            "snapshot",
            "create",
            "--repo",
            str(repo),
            "--out",
            str(out),
            "--profile",
            "agent-portable",
            "--latest-complete-registry",
            str(registry_path),
        ]
    )

    emitted = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert emitted["status"] == "fail"
    assert emitted["latest_complete_registry"] is None
    assert not registry_path.exists()
