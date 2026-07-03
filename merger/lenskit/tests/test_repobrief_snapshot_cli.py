import json
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
