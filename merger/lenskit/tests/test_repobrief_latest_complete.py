import hashlib
import json
import subprocess
from pathlib import Path

import jsonschema

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


def _manifest(tmp_path: Path, *, commit: str | None = None, health_status: str = "pass") -> Path:
    canonical = tmp_path / "demo.md"
    canonical.write_text("# demo\n", encoding="utf-8")
    output_health = tmp_path / "demo.output_health.json"
    output_health.write_text(
        json.dumps({"kind": "lenskit.output_health", "verdict": health_status}),
        encoding="utf-8",
    )
    manifest = tmp_path / "demo.bundle.manifest.json"
    data = {
        "kind": "repolens.bundle.manifest",
        "version": "1.0",
        "run_id": "run-1",
        "created_at": "2026-07-08T10:00:00Z",
        "artifacts": [
            {
                "role": "canonical_md",
                "path": canonical.name,
                "content_type": "text/markdown",
                "bytes": canonical.stat().st_size,
                "sha256": _sha(canonical),
            },
            {
                "role": "output_health",
                "path": output_health.name,
                "content_type": "application/json",
                "bytes": output_health.stat().st_size,
                "sha256": _sha(output_health),
            },
        ],
        "links": {},
        "capabilities": {"repobrief_profile": "agent-portable"},
        "snapshot_provenance": {
            "version": "v1",
            "repositories": [
                {
                    "name": "repo",
                    "repo_root": str(tmp_path / "repo"),
                    "repo_remote": None,
                    "git_commit": commit,
                    "git_dirty": False,
                    "git_branch": "main",
                    "provenance_status": "present" if commit else "producer_did_not_collect",
                    "freshness_basis": "git_commit" if commit else "unknown",
                }
            ],
            "does_not_establish": ["freshness_against_remote"],
        },
    }
    manifest.write_text(json.dumps(data, indent=2), encoding="utf-8")
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
    assert registry["freshness"]["status"] == "unknown"
    assert registry["freshness"]["reason"] == "live_repo_not_checked"
    assert registry["mutation_boundary"]["writes"] == ["latest_complete_registry"]
    assert registry["mutation_boundary"]["hidden_refresh_allowed"] is False


def test_latest_complete_registry_schema_accepts_emitted_registry(tmp_path):
    manifest = _manifest(tmp_path, commit="b" * 40)
    registry_path = tmp_path / "latest.json"
    result = write_latest_complete_registry(manifest, registry_path)
    schema = json.loads(
        Path("merger/lenskit/contracts/repobrief-latest-complete-registry.v1.schema.json").read_text(
            encoding="utf-8"
        )
    )

    assert result["status"] == "ok"
    jsonschema.validate(instance=json.loads(registry_path.read_text(encoding="utf-8")), schema=schema)


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

    rc = main([
        "repobrief",
        "latest-complete",
        "write",
        "--bundle-manifest",
        str(manifest),
        "--out",
        str(registry_path),
    ])

    write_out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert registry_path.exists()
    assert write_out["kind"] == "repobrief.latest_complete_registry_write"
    assert write_out["mutation_boundary"]["writes"] == ["latest_complete_registry"]

    rc = main([
        "repobrief",
        "latest-complete",
        "status",
        "--registry",
        str(registry_path),
        "--repo",
        str(repo),
    ])

    status_out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert status_out["kind"] == "repobrief.latest_complete_status"
    assert status_out["freshness"]["status"] == "fresh"
    assert status_out["mutation_boundary"]["writes"] == []


class _FakeArtifacts:
    def __init__(self, manifest: Path):
        self.bundle_manifest = manifest
        self.canonical_md = manifest.with_name("brief.md")
        self.canonical_md.write_text("# brief\n", encoding="utf-8")

    def get_all_paths(self):
        return [self.bundle_manifest, self.canonical_md]


def test_snapshot_create_can_explicitly_write_latest_complete_registry(monkeypatch, tmp_path, capsys):
    repo, commit = _git_repo(tmp_path)
    out = tmp_path / "briefs"
    registry_path = tmp_path / "latest" / "registry.json"

    def fake_scan_repo(*args, **kwargs):
        return {"name": "repo", "root": repo, "files": [], "total_files": 0, "total_bytes": 0, "ext_hist": {}}

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
    monkeypatch.setattr(
        cmd_repobrief,
        "finalize_snapshot_bundle",
        lambda manifest, profile: {
            "status": "pass",
            "errors": [],
            "profile_evaluation": {"status": "pass", "profile": profile},
            "control_paths": [],
            "refreshed_paths": [],
        },
    )

    rc = main([
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
    ])

    emitted = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert registry_path.exists()
    assert emitted["latest_complete_registry"]["status"] == "ok"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    assert registry["source"]["commit"] == commit
    assert registry["mutation_boundary"]["writes"] == ["latest_complete_registry"]


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

    rc = main([
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
    ])

    emitted = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert emitted["status"] == "fail"
    assert emitted["latest_complete_registry"] is None
    assert not registry_path.exists()
