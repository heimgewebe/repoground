import json

from merger.lenskit.cli.main import main


def _bundle_manifest_fixture() -> dict:
    return {
        "run_id": "run-cli-entry",
        "created_at": "2026-06-29T00:00:00Z",
        "artifacts": [
            {
                "role": "canonical_md",
                "path": "merge.md",
                "sha256": "a" * 64,
                "authority": "canonical_content",
                "canonicality": "content_source",
            },
            {
                "role": "agent_reading_pack",
                "path": "merge.agent_reading_pack.md",
                "sha256": "b" * 64,
                "authority": "navigation_index",
                "canonicality": "derived",
            },
        ],
    }


def test_cli_agent_entry_manifest_stdout(tmp_path, capsys):
    manifest_path = tmp_path / "bundle.bundle.manifest.json"
    manifest_path.write_text(json.dumps(_bundle_manifest_fixture()), encoding="utf-8")

    rc = main([
        "agent-entry",
        "manifest",
        "--bundle-manifest",
        str(manifest_path),
    ])

    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["kind"] == "lenskit.agent_entry_manifest"
    assert out["bundle_run_id"] == "run-cli-entry"
    assert out["authority"] == "navigation_index"
    assert out["canonicality"] == "derived"


def test_cli_agent_entry_manifest_out_file(tmp_path, capsys):
    manifest_path = tmp_path / "bundle.bundle.manifest.json"
    out_path = tmp_path / "entry.json"
    manifest_path.write_text(json.dumps(_bundle_manifest_fixture()), encoding="utf-8")

    rc = main([
        "agent-entry",
        "manifest",
        "--bundle-manifest",
        str(manifest_path),
        "--out",
        str(out_path),
    ])

    assert rc == 0
    assert capsys.readouterr().out == ""
    out = json.loads(out_path.read_text(encoding="utf-8"))
    assert out["kind"] == "lenskit.agent_entry_manifest"
    assert out["bundle_run_id"] == "run-cli-entry"


def test_cli_agent_entry_manifest_missing_input(capsys):
    rc = main([
        "agent-entry",
        "manifest",
        "--bundle-manifest",
        "does-not-exist.json",
    ])

    assert rc == 2
    assert "Could not read" in capsys.readouterr().err


def test_cli_agent_entry_manifest_invalid_json(tmp_path, capsys):
    manifest_path = tmp_path / "bundle.bundle.manifest.json"
    manifest_path.write_text("{invalid", encoding="utf-8")

    rc = main([
        "agent-entry",
        "manifest",
        "--bundle-manifest",
        str(manifest_path),
    ])

    assert rc == 2
    assert "Invalid JSON" in capsys.readouterr().err
