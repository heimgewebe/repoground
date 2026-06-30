import json

from merger.lenskit.cli.main import main


def _bundle_manifest(tmp_path):
    manifest = {
        "kind": "repolens.bundle.manifest",
        "version": "1.0",
        "run_id": "run-export-test",
        "created_at": "2026-06-29T00:00:00Z",
        "generator": {"name": "test", "version": "1", "config_sha256": "a" * 64},
        "artifacts": [],
        "links": {},
        "capabilities": {"redaction": False, "fts5_bm25": False},
    }
    path = tmp_path / "bundle.bundle.manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def test_cli_export_safety_report_stdout_local_private(tmp_path, capsys):
    manifest = _bundle_manifest(tmp_path)
    rc = main([
        "export-safety",
        "report",
        "--bundle-manifest",
        str(manifest),
        "--profile",
        "local-private",
    ])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["kind"] == "lenskit.export_safety_report"
    assert out["profile"] == "local-private"
    assert out["status"] == "pass"
    assert out["bundle_manifest_path"].endswith("bundle.bundle.manifest.json")


def test_cli_export_safety_report_out_file_agent_portable_fails(tmp_path, capsys):
    manifest = _bundle_manifest(tmp_path)
    out_path = tmp_path / "export_safety.json"
    rc = main([
        "export-safety",
        "report",
        "--bundle-manifest",
        str(manifest),
        "--profile",
        "agent-portable",
        "--out",
        str(out_path),
    ])
    assert rc == 1
    assert capsys.readouterr().out == ""
    out = json.loads(out_path.read_text(encoding="utf-8"))
    assert out["status"] == "fail"
    assert "redaction_required_but_not_observed" in out["errors"]
    assert out["input_observed"] == {
        "post_emit_health": False,
        "output_health": False,
        "agent_export_gate": False,
    }
