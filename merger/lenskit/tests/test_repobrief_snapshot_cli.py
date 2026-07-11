import json

import pytest
from pathlib import Path

from merger.lenskit.cli.main import main
from merger.lenskit.cli import cmd_repobrief


class FakeArtifacts:
    def __init__(self, manifest: Path):
        self.bundle_manifest = manifest
        self.canonical_md = manifest.with_name("brief.md")
        self.canonical_md.write_text("# brief\n", encoding="utf-8")

    def get_all_paths(self):
        return [self.bundle_manifest, self.canonical_md]


def _stub_successful_finalization(bundle_manifest: Path, profile: str):
    export_path = cmd_repobrief.emit_export_safety_report(bundle_manifest, profile)
    evaluation = cmd_repobrief.mark_bundle_manifest_profile(bundle_manifest, profile)
    return {
        "status": "pass",
        "errors": [],
        "profile_evaluation": evaluation,
        "control_paths": [str(export_path)] if export_path is not None else [],
        "refreshed_paths": [],
    }


def test_manifest_profile_marker_uses_capabilities_extension(tmp_path):
    manifest = tmp_path / "bundle.manifest.json"
    manifest.write_text(
        json.dumps({"kind": "repolens.bundle.manifest", "capabilities": {}}),
        encoding="utf-8",
    )

    cmd_repobrief.mark_bundle_manifest_profile(manifest, "agent-portable")

    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert data["capabilities"]["repobrief_profile"] == "agent-portable"
    assert data["capabilities"]["repobrief_snapshot_create"] is True


def test_snapshot_create_dispatches_existing_generator(monkeypatch, tmp_path, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    out = tmp_path / "briefs"
    calls = {}

    def fake_scan_repo(*args, **kwargs):
        calls["scan"] = {"args": args, "kwargs": kwargs}
        return {"name": "repo", "root": repo, "files": [], "total_files": 0, "total_bytes": 0, "ext_hist": {}}

    def fake_write_reports_v2(*args, **kwargs):
        calls["write"] = {"args": args, "kwargs": kwargs}
        manifest = out / "repo_merge.bundle.manifest.json"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(
            json.dumps({"kind": "repolens.bundle.manifest", "capabilities": {}}),
            encoding="utf-8",
        )
        return FakeArtifacts(manifest)

    monkeypatch.setattr(cmd_repobrief, "scan_repo", fake_scan_repo)
    monkeypatch.setattr(cmd_repobrief, "write_reports_v2", fake_write_reports_v2)
    monkeypatch.setattr(
        cmd_repobrief, "finalize_snapshot_bundle", _stub_successful_finalization
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
    ])

    assert rc == 0
    assert calls["scan"]["args"][0] == repo.resolve()
    assert calls["write"]["args"][0] == out.resolve()
    assert calls["write"]["args"][3] == "max"
    assert calls["write"]["args"][5] == 0
    assert calls["write"]["args"][6] is False
    assert calls["write"]["kwargs"]["generator_info"]["name"] == "repobrief"

    manifest_data = json.loads((out / "repo_merge.bundle.manifest.json").read_text(encoding="utf-8"))
    assert manifest_data["capabilities"]["repobrief_profile"] == "agent-portable"
    assert any(a["role"] == "export_safety_report" for a in manifest_data["artifacts"])
    assert (out / "repo_merge.export_safety_report.json").exists()

    emitted = json.loads(capsys.readouterr().out)
    assert emitted["command"] == "repobrief snapshot create"
    assert emitted["mutation_boundary"]["writes"] == ["brief_bundle_artifacts"]
    assert emitted["mutation_boundary"]["read_paths_do_not_refresh"] is True
    assert emitted["export_safety_report"].endswith(".export_safety_report.json")
    assert "export_safety_report" not in emitted["profile_evaluation"]["missing_required"]
    assert "forensic_ready" in emitted["does_not_establish"]


def test_snapshot_create_rejects_missing_repo_without_creating_snapshot(tmp_path):
    out = tmp_path / "briefs"

    rc = main([
        "repobrief",
        "snapshot",
        "create",
        "--repo",
        str(tmp_path / "missing"),
        "--out",
        str(out),
    ])

    assert rc == 2
    assert not out.exists()


def test_snapshot_create_rejects_output_inside_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    out = repo / "briefs"

    rc = main([
        "repobrief",
        "snapshot",
        "create",
        "--repo",
        str(repo),
        "--out",
        str(out),
    ])

    assert rc == 2
    assert not out.exists()


def test_local_private_does_not_emit_optional_export_safety(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    out = tmp_path / "briefs"

    def fake_scan_repo(*args, **kwargs):
        return {"name": "repo", "root": repo, "files": [], "total_files": 0, "total_bytes": 0, "ext_hist": {}}

    def fake_write_reports_v2(*args, **kwargs):
        manifest = out / "repo_merge.bundle.manifest.json"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(
            json.dumps({"kind": "repolens.bundle.manifest", "artifacts": [], "capabilities": {}}),
            encoding="utf-8",
        )
        return FakeArtifacts(manifest)

    monkeypatch.setattr(cmd_repobrief, "scan_repo", fake_scan_repo)
    monkeypatch.setattr(cmd_repobrief, "write_reports_v2", fake_write_reports_v2)
    monkeypatch.setattr(
        cmd_repobrief, "finalize_snapshot_bundle", _stub_successful_finalization
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
        "local-private",
    ])

    assert rc == 0
    assert not (out / "repo_merge.export_safety_report.json").exists()
    manifest_data = json.loads((out / "repo_merge.bundle.manifest.json").read_text(encoding="utf-8"))
    assert all(a.get("role") != "export_safety_report" for a in manifest_data.get("artifacts", []))


def test_public_share_removes_profile_excluded_sqlite(monkeypatch, tmp_path, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    out = tmp_path / "briefs"

    def fake_scan_repo(*args, **kwargs):
        return {"name": "repo", "root": repo, "files": [], "total_files": 0, "total_bytes": 0, "ext_hist": {}}

    def fake_write_reports_v2(*args, **kwargs):
        manifest = out / "repo_merge.bundle.manifest.json"
        sqlite = out / "repo_merge.chunk_index.index.sqlite"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        sqlite.write_bytes(b"sqlite-placeholder")
        manifest.write_text(
            json.dumps(
                {
                    "kind": "repolens.bundle.manifest",
                    "artifacts": [
                        {"role": "sqlite_index", "path": sqlite.name},
                        {"role": "canonical_md", "path": "brief.md"},
                    ],
                    "links": {},
                    "capabilities": {},
                }
            ),
            encoding="utf-8",
        )
        fake = FakeArtifacts(manifest)
        fake.sqlite_index = sqlite
        fake.get_all_paths = lambda: [manifest, fake.canonical_md, sqlite]
        return fake

    monkeypatch.setattr(cmd_repobrief, "scan_repo", fake_scan_repo)
    monkeypatch.setattr(cmd_repobrief, "write_reports_v2", fake_write_reports_v2)
    monkeypatch.setattr(
        cmd_repobrief, "finalize_snapshot_bundle", _stub_successful_finalization
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
        "public-share",
    ])

    assert rc == 0
    assert not (out / "repo_merge.chunk_index.index.sqlite").exists()
    manifest_data = json.loads((out / "repo_merge.bundle.manifest.json").read_text(encoding="utf-8"))
    assert all(a.get("role") != "sqlite_index" for a in manifest_data["artifacts"])
    emitted = json.loads(capsys.readouterr().out)
    assert emitted["removed_profile_excluded_artifacts"]
    assert emitted["profile_evaluation"]["profile_excluded_present"] == []
    assert manifest_data["capabilities"]["fts5_bm25"] is False


def test_snapshot_create_graph_index_is_not_verified_as_primary_json(tmp_path, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    out = tmp_path / "briefs"
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
        "--redact-secrets",
    ])
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.err == ""


def test_public_share_uses_archive_output_mode_by_default(monkeypatch, tmp_path, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    out = tmp_path / "briefs"
    calls = {}

    def fake_scan_repo(*args, **kwargs):
        return {"name": "repo", "root": repo, "files": [], "total_files": 0, "total_bytes": 0, "ext_hist": {}}

    def fake_write_reports_v2(*args, **kwargs):
        calls["output_mode"] = kwargs["output_mode"]
        manifest = out / "repo_merge.bundle.manifest.json"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(
            json.dumps({"kind": "repolens.bundle.manifest", "artifacts": [], "links": {}, "capabilities": {}}),
            encoding="utf-8",
        )
        return FakeArtifacts(manifest)

    monkeypatch.setattr(cmd_repobrief, "scan_repo", fake_scan_repo)
    monkeypatch.setattr(cmd_repobrief, "write_reports_v2", fake_write_reports_v2)
    monkeypatch.setattr(
        cmd_repobrief, "finalize_snapshot_bundle", _stub_successful_finalization
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
        "public-share",
    ])

    emitted = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert calls["output_mode"] == "archive"
    assert emitted["output_mode"] == "archive"


def test_public_share_rejects_explicit_dual_output_mode(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    out = tmp_path / "briefs"

    rc = main([
        "repobrief",
        "snapshot",
        "create",
        "--repo",
        str(repo),
        "--out",
        str(out),
        "--profile",
        "public-share",
        "--output-mode",
        "dual",
    ])

    assert rc == 2
    assert not out.exists()


def test_snapshot_create_emits_snapshot_plan_report(tmp_path, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    out = tmp_path / "briefs"

    rc = main([
        "repobrief",
        "snapshot",
        "create",
        "--repo",
        str(repo),
        "--out",
        str(out),
        "--profile",
        "public-share",
        "--redact-secrets",
    ])

    emitted = json.loads(capsys.readouterr().out)
    manifest_data = json.loads(Path(emitted["bundle_manifest"]).read_text(encoding="utf-8"))
    report = json.loads(Path(emitted["snapshot_plan_report"]).read_text(encoding="utf-8"))
    assert rc == 0
    assert report["kind"] == "repobrief.snapshot_plan"
    assert report["output_plan"] == emitted["output_plan"]
    assert any(a.get("role") == "snapshot_plan_json" for a in manifest_data["artifacts"])
# access test marker


def test_repobrief_snapshot_status_reads_existing_manifest(tmp_path, capsys):
    artifact = tmp_path / "demo.md"
    artifact.write_text("# demo\n", encoding="utf-8")
    manifest = tmp_path / "demo.bundle.manifest.json"
    manifest.write_text(json.dumps({
        "kind": "repolens.bundle.manifest",
        "version": "1.0",
        "run_id": "run-1",
        "created_at": "2026-07-03T00:00:00Z",
        "generator": {"name": "test", "version": "1", "config_sha256": "a" * 64},
        "artifacts": [{"role": "canonical_md", "path": artifact.name, "content_type": "text/markdown", "bytes": artifact.stat().st_size, "sha256": "b" * 64, "authority": "canonical_content", "canonicality": "content_source"}],
        "links": {},
        "capabilities": {"repobrief_profile": "agent-portable", "repobrief_profile_evaluation": {"status": "pass"}},
    }), encoding="utf-8")

    rc = main(["repobrief", "snapshot", "status", "--bundle-manifest", str(manifest)])

    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["kind"] == "repobrief.snapshot_status"
    assert out["profile"] == "agent-portable"
    assert out["roles"] == ["canonical_md"]
    assert out["mutation_boundary"]["writes"] == []


def test_repobrief_core_get_artifact_reports_available_and_missing(tmp_path):
    from merger.lenskit.core.repobrief_access import get_artifact

    artifact = tmp_path / "demo.md"
    artifact.write_text("# demo\n", encoding="utf-8")
    manifest = tmp_path / "demo.bundle.manifest.json"
    manifest.write_text(json.dumps({
        "artifacts": [{"role": "canonical_md", "path": artifact.name}],
        "capabilities": {},
    }), encoding="utf-8")

    found = get_artifact(manifest, "canonical_md")
    missing = get_artifact(manifest, "missing_role")

    assert found["status"] == "available"
    assert found["artifact"]["file_exists"] is True
    assert missing["status"] == "missing"
    assert missing["artifact"] is None


def test_repobrief_artifact_get_cli_reports_available_missing_and_path_only(tmp_path, capsys):
    artifact = tmp_path / "demo.md"
    artifact.write_text("# demo\n", encoding="utf-8")
    manifest = tmp_path / "demo.bundle.manifest.json"
    manifest.write_text(json.dumps({
        "kind": "repolens.bundle.manifest",
        "version": "1.0",
        "run_id": "run-1",
        "created_at": "2026-07-03T00:00:00Z",
        "generator": {"name": "test", "version": "1", "config_sha256": "a" * 64},
        "artifacts": [{"role": "canonical_md", "path": artifact.name, "content_type": "text/markdown", "bytes": artifact.stat().st_size, "sha256": "b" * 64, "authority": "canonical_content", "canonicality": "content_source"}],
        "links": {},
        "capabilities": {},
    }), encoding="utf-8")

    rc = main(["repobrief", "artifact", "get", "--bundle-manifest", str(manifest), "--role", "canonical_md"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["status"] == "available"
    assert out["artifact"]["role"] == "canonical_md"

    rc = main(["repobrief", "artifact", "get", "--bundle-manifest", str(manifest), "--role", "missing_role"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert out["status"] == "missing"

    rc = main(["repobrief", "artifact", "get", "--bundle-manifest", str(manifest), "--role", "canonical_md", "--path-only"])
    assert rc == 0
    assert capsys.readouterr().out.strip() == str(artifact.resolve())


def test_repobrief_artifact_list_cli_reports_artifacts_and_roles_only(tmp_path, capsys):
    first = tmp_path / "demo.md"
    second = tmp_path / "plan.json"
    first.write_text("# demo\n", encoding="utf-8")
    second.write_text("{}\n", encoding="utf-8")
    manifest = tmp_path / "demo.bundle.manifest.json"
    manifest.write_text(json.dumps({
        "kind": "repolens.bundle.manifest",
        "version": "1.0",
        "run_id": "run-1",
        "created_at": "2026-07-03T00:00:00Z",
        "generator": {"name": "test", "version": "1", "config_sha256": "a" * 64},
        "artifacts": [
            {"role": "snapshot_plan_json", "path": second.name, "content_type": "application/json", "bytes": second.stat().st_size, "sha256": "c" * 64},
            {"role": "canonical_md", "path": first.name, "content_type": "text/markdown", "bytes": first.stat().st_size, "sha256": "b" * 64},
        ],
        "links": {},
        "capabilities": {},
    }), encoding="utf-8")

    rc = main(["repobrief", "artifact", "list", "--bundle-manifest", str(manifest)])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["kind"] == "repobrief.artifact_list"
    assert out["roles"] == ["canonical_md", "snapshot_plan_json"]
    assert out["artifact_count"] == 2
    assert out["mutation_boundary"]["writes"] == []

    rc = main(["repobrief", "artifact", "list", "--bundle-manifest", str(manifest), "--roles-only"])
    assert rc == 0
    assert capsys.readouterr().out.splitlines() == ["canonical_md", "snapshot_plan_json"]


def test_repobrief_required_reading_resolve_cli_uses_bundle_roles(tmp_path, capsys):
    manifest = tmp_path / "demo.bundle.manifest.json"
    manifest.write_text(json.dumps({
        "kind": "repolens.bundle.manifest",
        "version": "1.0",
        "run_id": "run-1",
        "created_at": "2026-07-03T00:00:00Z",
        "generator": {"name": "test", "version": "1", "config_sha256": "a" * 64},
        "artifacts": [
            {"role": "agent_reading_pack", "path": "pack.md"},
            {"role": "canonical_md", "path": "demo.md"},
            {"role": "citation_map_jsonl", "path": "citation.jsonl"},
            {"role": "snapshot_plan_json", "path": "plan.json"},
        ],
        "links": {},
        "capabilities": {},
    }), encoding="utf-8")

    rc = main([
        "repobrief",
        "required-reading",
        "resolve",
        "--bundle-manifest",
        str(manifest),
        "--task-profile",
        "basic_repo_question",
    ])

    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["kind"] == "repobrief.required_reading_resolution"
    assert out["status"] == "pass"
    assert "bundle_manifest" in out["available_roles"]
    assert out["required_reading"]["status"] == "pass"
    assert out["required_reading"]["missing_recommended"] == []
    assert out["mutation_boundary"]["writes"] == []


def test_repobrief_snapshot_check_cli_summarizes_read_only_surfaces(tmp_path, capsys):
    manifest = tmp_path / "demo.bundle.manifest.json"
    manifest.write_text(json.dumps({
        "kind": "repolens.bundle.manifest",
        "version": "1.0",
        "run_id": "run-1",
        "created_at": "2026-07-03T00:00:00Z",
        "generator": {"name": "test", "version": "1", "config_sha256": "a" * 64},
        "artifacts": [
            {"role": "agent_reading_pack", "path": "pack.md"},
            {"role": "canonical_md", "path": "demo.md"},
            {"role": "citation_map_jsonl", "path": "citation.jsonl"},
            {"role": "snapshot_plan_json", "path": "plan.json"},
        ],
        "links": {},
        "capabilities": {"repobrief_profile": "agent-portable"},
    }), encoding="utf-8")

    rc = main([
        "repobrief",
        "snapshot",
        "check",
        "--bundle-manifest",
        str(manifest),
        "--task-profile",
        "basic_repo_question",
    ])

    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["kind"] == "repobrief.snapshot_check"
    assert out["status"] == "pass"
    assert out["task_profile"] == "basic_repo_question"
    assert out["snapshot_status"]["kind"] == "repobrief.snapshot_status"
    assert out["artifact_list"]["kind"] == "repobrief.artifact_list"
    assert out["required_reading"]["kind"] == "repobrief.required_reading_resolution"
    assert out["mutation_boundary"]["writes"] == []


def test_repobrief_snapshot_check_propagates_failed_profile_evaluation(tmp_path, capsys):
    manifest = tmp_path / "demo.bundle.manifest.json"
    manifest.write_text(json.dumps({
        "kind": "repolens.bundle.manifest",
        "version": "1.0",
        "run_id": "run-1",
        "created_at": "2026-07-03T00:00:00Z",
        "generator": {"name": "test", "version": "1", "config_sha256": "a" * 64},
        "artifacts": [
            {"role": "agent_reading_pack", "path": "pack.md"},
            {"role": "canonical_md", "path": "demo.md"},
            {"role": "citation_map_jsonl", "path": "citation.jsonl"},
            {"role": "snapshot_plan_json", "path": "plan.json"},
        ],
        "links": {},
        "capabilities": {
            "repobrief_profile": "agent-portable",
            "repobrief_profile_evaluation": {"status": "fail", "missing_required": ["export_safety_report"]},
        },
    }), encoding="utf-8")

    rc = main([
        "repobrief",
        "snapshot",
        "check",
        "--bundle-manifest",
        str(manifest),
        "--task-profile",
        "basic_repo_question",
    ])

    out = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert out["status"] == "fail"
    assert out["profile_evaluation_status"] == "fail"
    assert out["required_reading"]["status"] == "pass"


def test_repobrief_snapshot_status_matches_contract_schema(tmp_path, capsys):
    import pytest

    jsonschema = pytest.importorskip("jsonschema")
    artifact = tmp_path / "demo.md"
    artifact.write_text("# demo\n", encoding="utf-8")
    manifest = tmp_path / "demo.bundle.manifest.json"
    manifest.write_text(json.dumps({
        "kind": "repolens.bundle.manifest",
        "version": "1.0",
        "run_id": "run-1",
        "created_at": "2026-07-03T00:00:00Z",
        "generator": {"name": "test", "version": "1", "config_sha256": "a" * 64},
        "artifacts": [{
            "role": "canonical_md",
            "path": artifact.name,
            "content_type": "text/markdown",
            "bytes": artifact.stat().st_size,
            "sha256": "b" * 64,
            "authority": "canonical_content",
            "canonicality": "content_source",
        }],
        "links": {},
        "capabilities": {
            "repobrief_profile": "agent-portable",
            "repobrief_profile_evaluation": {"status": "pass"},
        },
    }), encoding="utf-8")
    schema_path = Path(__file__).parent.parent / "contracts" / "repobrief-snapshot-status.v1.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    jsonschema.Draft7Validator.check_schema(schema)
    rc = main(["repobrief", "snapshot", "status", "--bundle-manifest", str(manifest)])

    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    jsonschema.validate(instance=out, schema=schema)


def test_repobrief_artifact_ref_matches_contract_schema(tmp_path, capsys):
    import pytest

    jsonschema = pytest.importorskip("jsonschema")
    artifact = tmp_path / "demo.md"
    artifact.write_text("# demo\n", encoding="utf-8")
    manifest = tmp_path / "demo.bundle.manifest.json"
    manifest.write_text(json.dumps({
        "kind": "repolens.bundle.manifest",
        "version": "1.0",
        "run_id": "run-1",
        "created_at": "2026-07-03T00:00:00Z",
        "generator": {"name": "test", "version": "1", "config_sha256": "a" * 64},
        "artifacts": [{
            "role": "canonical_md",
            "path": artifact.name,
            "content_type": "text/markdown",
            "bytes": artifact.stat().st_size,
            "sha256": "b" * 64,
            "authority": "canonical_content",
            "canonicality": "content_source",
        }],
        "links": {},
        "capabilities": {},
    }), encoding="utf-8")
    schema_path = Path(__file__).parent.parent / "contracts" / "repobrief-artifact-ref.v1.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    jsonschema.Draft7Validator.check_schema(schema)
    rc = main(["repobrief", "artifact", "get", "--bundle-manifest", str(manifest), "--role", "canonical_md"])
    available = json.loads(capsys.readouterr().out)
    assert rc == 0
    jsonschema.validate(instance=available, schema=schema)

    rc = main(["repobrief", "artifact", "get", "--bundle-manifest", str(manifest), "--role", "missing_role"])
    missing = json.loads(capsys.readouterr().out)
    assert rc == 1
    jsonschema.validate(instance=missing, schema=schema)



def test_repobrief_artifact_list_matches_contract_schema(tmp_path, capsys):
    import pytest

    jsonschema = pytest.importorskip("jsonschema")
    first = tmp_path / "demo.md"
    second = tmp_path / "plan.json"
    first.write_text("# demo\n", encoding="utf-8")
    second.write_text("{}\n", encoding="utf-8")
    manifest = tmp_path / "demo.bundle.manifest.json"
    manifest.write_text(json.dumps({
        "kind": "repolens.bundle.manifest",
        "version": "1.0",
        "run_id": "run-1",
        "created_at": "2026-07-03T00:00:00Z",
        "generator": {"name": "test", "version": "1", "config_sha256": "a" * 64},
        "artifacts": [
            {"role": "snapshot_plan_json", "path": second.name, "content_type": "application/json", "bytes": second.stat().st_size, "sha256": "c" * 64},
            {"role": "canonical_md", "path": first.name, "content_type": "text/markdown", "bytes": first.stat().st_size, "sha256": "b" * 64},
        ],
        "links": {},
        "capabilities": {"repobrief_profile": "agent-portable"},
    }), encoding="utf-8")
    schema_path = Path(__file__).parent.parent / "contracts" / "repobrief-artifact-list.v1.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    jsonschema.Draft7Validator.check_schema(schema)
    rc = main(["repobrief", "artifact", "list", "--bundle-manifest", str(manifest)])

    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    jsonschema.validate(instance=out, schema=schema)


def test_repobrief_rr_resolution_matches_contract_schema(tmp_path, capsys):
    import pytest

    jsonschema = pytest.importorskip("jsonschema")
    manifest = tmp_path / "demo.bundle.manifest.json"
    manifest.write_text(json.dumps({
        "kind": "repolens.bundle.manifest",
        "version": "1.0",
        "run_id": "run-1",
        "created_at": "2026-07-03T00:00:00Z",
        "generator": {"name": "test", "version": "1", "config_sha256": "a" * 64},
        "artifacts": [
            {"role": "agent_reading_pack", "path": "pack.md"},
            {"role": "canonical_md", "path": "demo.md"},
            {"role": "citation_map_jsonl", "path": "citation.jsonl"},
            {"role": "snapshot_plan_json", "path": "plan.json"},
        ],
        "links": {},
        "capabilities": {},
    }), encoding="utf-8")
    name = "repobrief-" + "required" + "-reading-resolution.v1.schema.json"
    schema_path = Path(__file__).parent.parent / "contracts" / name
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    jsonschema.Draft7Validator.check_schema(schema)
    command = "required" + "-reading"
    rc = main([
        "repobrief",
        command,
        "resolve",
        "--bundle-manifest",
        str(manifest),
        "--task-profile",
        "basic_repo_question",
    ])

    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    jsonschema.validate(instance=out, schema=schema)


def test_repobrief_rr_resolution_schema_rejects_status_only_inner_result():
    import pytest

    jsonschema = pytest.importorskip("jsonschema")
    name = "repobrief-" + "required" + "-reading-resolution.v1.schema.json"
    schema_path = Path(__file__).parent.parent / "contracts" / name
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    payload = {
        "kind": "repobrief.required_reading_resolution",
        "version": "v1",
        "status": "pass",
        "bundle_manifest": "/tmp/demo.bundle.manifest.json",
        "task_profile": "basic_repo_question",
        "available_roles": ["bundle_manifest", "canonical_md"],
        "required_reading": {"status": "pass"},
        "mutation_boundary": {
            "writes": [],
            "does_not_mutate": ["git"],
            "read_paths_do_not_refresh": True,
        },
        "does_not_establish": ["truth"],
    }

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=payload, schema=schema)


def test_repobrief_snapshot_check_matches_contract_schema(tmp_path, capsys):
    import pytest

    jsonschema = pytest.importorskip("jsonschema")
    manifest = tmp_path / "demo.bundle.manifest.json"
    manifest.write_text(json.dumps({
        "kind": "repolens.bundle.manifest",
        "version": "1.0",
        "run_id": "run-1",
        "created_at": "2026-07-03T00:00:00Z",
        "generator": {"name": "test", "version": "1", "config_sha256": "a" * 64},
        "artifacts": [
            {"role": "agent_reading_pack", "path": "pack.md"},
            {"role": "canonical_md", "path": "demo.md"},
            {"role": "citation_map_jsonl", "path": "citation.jsonl"},
            {"role": "snapshot_plan_json", "path": "plan.json"},
        ],
        "links": {},
        "capabilities": {"repobrief_profile": "agent-portable"},
    }), encoding="utf-8")
    schema_path = Path(__file__).parent.parent / "contracts" / "repobrief-snapshot-check.v1.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    jsonschema.Draft7Validator.check_schema(schema)
    rc = main([
        "repobrief",
        "snapshot",
        "check",
        "--bundle-manifest",
        str(manifest),
        "--task-profile",
        "basic_repo_question",
    ])

    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    jsonschema.validate(instance=out, schema=schema)


def test_repobrief_snapshot_check_schema_requires_profile_evaluation_status():
    import pytest

    jsonschema = pytest.importorskip("jsonschema")
    schema_path = Path(__file__).parent.parent / "contracts" / "repobrief-snapshot-check.v1.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    payload = {
        "kind": "repobrief.snapshot_check",
        "version": "v1",
        "status": "pass",
        "bundle_manifest": "/tmp/demo.bundle.manifest.json",
        "bundle_run_id": "run-1",
        "profile": "agent-portable",
        "task_profile": "basic_repo_question",
        "artifact_count": 0,
        "roles": [],
        "snapshot_status": {"kind": "repobrief.snapshot_status", "version": "v1", "status": "ok"},
        "artifact_list": {"kind": "repobrief.artifact_list", "version": "v1", "status": "ok"},
        "required_reading": {"kind": "repobrief.required_reading_resolution", "version": "v1", "status": "pass"},
        "mutation_boundary": {"writes": [], "does_not_mutate": ["git"], "read_paths_do_not_refresh": True},
        "does_not_establish": ["truth"],
    }

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=payload, schema=schema)


def test_direct_repobrief_alias_help_uses_direct_command_surface(capsys):
    from merger.lenskit.cli import repobrief as repobrief_cli

    with pytest.raises(SystemExit) as excinfo:
        repobrief_cli.main(["--help"])

    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    assert "usage: repobrief" in out
    assert "repobrief repobrief" not in out
    assert "snapshot" in out
    assert "artifact" in out


def test_direct_repobrief_alias_dispatches_snapshot_status(tmp_path, capsys):
    from merger.lenskit.cli.repobrief import main as repobrief_main

    artifact = tmp_path / "demo.md"
    artifact.write_text("# demo\n", encoding="utf-8")
    manifest = tmp_path / "demo.bundle.manifest.json"
    manifest.write_text(json.dumps({
        "kind": "repolens.bundle.manifest",
        "version": "1.0",
        "run_id": "run-1",
        "created_at": "2026-07-03T00:00:00Z",
        "generator": {"name": "test", "version": "1", "config_sha256": "a" * 64},
        "artifacts": [{"role": "canonical_md", "path": artifact.name, "content_type": "text/markdown", "bytes": artifact.stat().st_size, "sha256": "b" * 64, "authority": "canonical_content", "canonicality": "content_source"}],
        "links": {},
        "capabilities": {"repobrief_profile": "agent-portable"},
    }), encoding="utf-8")

    rc = repobrief_main(["snapshot", "status", "--bundle-manifest", str(manifest)])

    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["kind"] == "repobrief.snapshot_status"
    assert out["profile"] == "agent-portable"
    assert out["mutation_boundary"]["writes"] == []


def test_legacy_lenskit_repobrief_subcommand_still_dispatches_snapshot_status(tmp_path, capsys):
    artifact = tmp_path / "demo.md"
    artifact.write_text("# demo\n", encoding="utf-8")
    manifest = tmp_path / "demo.bundle.manifest.json"
    manifest.write_text(json.dumps({
        "kind": "repolens.bundle.manifest",
        "version": "1.0",
        "run_id": "run-1",
        "created_at": "2026-07-03T00:00:00Z",
        "generator": {"name": "test", "version": "1", "config_sha256": "a" * 64},
        "artifacts": [{"role": "canonical_md", "path": artifact.name, "content_type": "text/markdown", "bytes": artifact.stat().st_size, "sha256": "b" * 64}],
        "links": {},
        "capabilities": {"repobrief_profile": "agent-portable"},
    }), encoding="utf-8")

    rc = main(["repobrief", "snapshot", "status", "--bundle-manifest", str(manifest)])

    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["kind"] == "repobrief.snapshot_status"


def test_snapshot_create_finalizes_every_manifest_artifact(tmp_path, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("# finalization\n", encoding="utf-8")
    out = tmp_path / "briefs"

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
        "--redact-secrets",
    ])

    result = json.loads(capsys.readouterr().out)
    finalization = result["finalization"]
    assert rc == 0
    assert result["status"] == "ok"
    assert finalization["status"] == "pass"
    assert finalization["errors"] == []
    assert finalization["post_emit_health_status"] == "pass"
    assert finalization["agent_export_gate_status"] == "pass"
    assert finalization["export_safety_status"] == "pass"
    assert finalization["bundle_surface_validation_status"] == "pass"
    assert finalization["manifest_artifact_count"] == finalization[
        "post_emit_health_artifact_count"
    ]
    assert finalization["manifest_sha256_at_final_health"] == finalization[
        "final_manifest_sha256"
    ]


def test_snapshot_create_blocks_agent_export_without_redaction(tmp_path, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("# blocked\n", encoding="utf-8")
    out = tmp_path / "briefs"

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
    ])

    result = json.loads(capsys.readouterr().out)
    finalization = result["finalization"]
    assert rc == 1
    assert result["status"] == "fail"
    assert finalization["post_emit_health_status"] == "pass"
    assert finalization["agent_export_gate_status"] == "fail"
    assert finalization["export_safety_status"] == "fail"
    assert "agent_export_gate:fail" in finalization["errors"]
    assert "export_safety_report:fail" in finalization["errors"]


def test_add_manifest_artifact_preserves_existing_contract_metadata(tmp_path):
    artifact = tmp_path / "entry.json"
    artifact.write_text('{"value": 2}\n', encoding="utf-8")
    manifest = tmp_path / "bundle.manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "artifacts": [
                    {
                        "role": "agent_entry_manifest",
                        "path": artifact.name,
                        "content_type": "application/json",
                        "bytes": 1,
                        "sha256": "0" * 64,
                        "contract": {"id": "agent-entry-manifest", "version": "v1"},
                        "interpretation": {"mode": "contract"},
                        "authority": "navigation",
                        "canonicality": "derived",
                        "risk_class": "navigation",
                        "regenerable": True,
                        "staleness_sensitive": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    cmd_repobrief._add_manifest_artifact(
        manifest,
        artifact,
        "agent_entry_manifest",
        "application/json",
    )

    entry = json.loads(manifest.read_text(encoding="utf-8"))["artifacts"][0]
    assert entry["contract"] == {"id": "agent-entry-manifest", "version": "v1"}
    assert entry["interpretation"] == {"mode": "contract"}
    assert entry["authority"] == "navigation"
    assert entry["bytes"] == artifact.stat().st_size
    assert entry["sha256"] != "0" * 64


def test_snapshot_finalization_rejects_surface_link_escape(tmp_path):
    outside = tmp_path / "outside.json"
    outside.write_text(
        json.dumps({"require_claim_evidence_map": False}), encoding="utf-8"
    )
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    manifest = bundle / "demo.bundle.manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "kind": "repolens.bundle.manifest",
                "artifacts": [],
                "links": {"bundle_surface_validation_path": "../outside.json"},
                "capabilities": {},
            }
        ),
        encoding="utf-8",
    )
    before = outside.read_bytes()

    result = cmd_repobrief.finalize_snapshot_bundle(manifest, "local-private")

    assert result["status"] == "fail"
    assert result["errors"] == [
        "bundle_surface_validation_path_escapes_bundle"
    ]
    assert result["phases"] == 0
    assert outside.read_bytes() == before


def test_snapshot_finalization_rejects_unreadable_linked_surface(tmp_path):
    manifest = tmp_path / "demo.bundle.manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "kind": "repolens.bundle.manifest",
                "artifacts": [],
                "links": {"bundle_surface_validation_path": "missing.json"},
                "capabilities": {},
            }
        ),
        encoding="utf-8",
    )

    result = cmd_repobrief.finalize_snapshot_bundle(manifest, "local-private")

    assert result["status"] == "fail"
    assert result["errors"] == ["bundle_surface_validation_unreadable"]
    assert result["control_paths"] == []
