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
from merger.lenskit.core.repobrief_latest_complete import (
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
    assert registry["selection"]["basis"] == "generated_at_fail_closed_ties_v1"
    assert registry["publication"]["directory_fsync"] is True
    assert registry["freshness"]["status"] == "unknown"
    assert registry["freshness"]["reason"] == "live_repo_not_checked"
    assert registry["mutation_boundary"]["writes"] == [
        "latest_complete_registry",
        "latest_complete_registry_lock",
    ]
    assert registry["mutation_boundary"]["hidden_refresh_allowed"] is False


def test_latest_complete_registry_schema_accepts_emitted_registry(tmp_path):
    manifest = _manifest(tmp_path, commit="b" * 40)
    registry_path = tmp_path / "latest.json"
    result = write_latest_complete_registry(manifest, registry_path)
    schema = json.loads(
        Path(
            "merger/lenskit/contracts/repobrief-latest-complete-registry.v1.schema.json"
        ).read_text(encoding="utf-8")
    )

    assert result["status"] == "ok"
    assert result["publication_result"] == "published"
    jsonschema.validate(
        instance=json.loads(registry_path.read_text(encoding="utf-8")), schema=schema
    )


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
        "latest_complete_registry",
        "latest_complete_registry_lock",
    ]

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
    )
    newer = _manifest(
        newer_dir,
        commit="2" * 40,
        created_at="2026-07-08T11:00:00Z",
        run_id="run-new",
    )
    registry_path = tmp_path / "latest.json"

    first = write_latest_complete_registry(newer, registry_path)
    first_hash = _sha(registry_path)
    older_result = write_latest_complete_registry(older, registry_path)
    same_result = write_latest_complete_registry(newer, registry_path)

    assert first["publication_result"] == "published"
    assert older_result["publication_result"] == "unchanged"
    assert older_result["reason"] == "candidate_older_than_published"
    assert same_result["publication_result"] == "unchanged"
    assert same_result["reason"] == "candidate_already_published"
    assert _sha(registry_path) == first_hash
    assert (
        json.loads(registry_path.read_text(encoding="utf-8"))["bundle"]["run_id"]
        == "run-new"
    )


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
    )
    newer = _manifest(
        newer_dir,
        commit="b" * 40,
        created_at="2026-07-08T11:00:00Z",
        run_id="run-new",
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
    first = _manifest(first_dir, commit="c" * 40, run_id="run-first")
    second = _manifest(second_dir, commit="d" * 40, run_id="run-second")
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


def test_write_rejects_symlink_lock(tmp_path):
    manifest = _manifest(tmp_path, commit="f" * 40)
    registry_path = tmp_path / "latest.json"
    external = tmp_path / "external.lock"
    external.write_text("sentinel\n", encoding="utf-8")
    lock_path = tmp_path / ".latest.json.lock"
    lock_path.symlink_to(external)

    with pytest.raises(ValueError, match="lock cannot be opened safely"):
        write_latest_complete_registry(manifest, registry_path)

    assert not registry_path.exists()
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
        "latest_complete_registry",
        "latest_complete_registry_lock",
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
