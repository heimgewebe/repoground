"""
CLI tests for `lenskit agent-pack produce`.
"""
import hashlib
import json
from pathlib import Path

from merger.lenskit.cli.main import main


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


_CANONICAL = b"# repo\n\n## file: a.py\nx = 1\n"


def _make_bundle(tmp_path: Path) -> Path:
    (tmp_path / "demo.md").write_bytes(_CANONICAL)
    start = _CANONICAL.index(b"x = 1")
    end = len(_CANONICAL)
    chunk = {
        "chunk_id": "c0",
        "path": "a.py",
        "search_keys": {"repo_id": "demo"},
        "canonical_range": {
            "artifact_role": "canonical_md",
            "file_path": "demo.md",
            "start_byte": start,
            "end_byte": end,
            "content_sha256": _sha256(_CANONICAL[start:end]),
        },
    }
    chunk_bytes = (json.dumps(chunk) + "\n").encode("utf-8")
    (tmp_path / "demo.chunk_index.jsonl").write_bytes(chunk_bytes)

    manifest = {
        "kind": "repolens.bundle.manifest",
        "version": "1.0",
        "run_id": "cli-pack-run",
        "created_at": "2026-05-20T00:00:00Z",
        "generator": {"name": "test", "version": "1.0", "config_sha256": "a" * 64},
        "artifacts": [
            {
                "role": "canonical_md", "path": "demo.md", "content_type": "text/markdown",
                "bytes": len(_CANONICAL), "sha256": _sha256(_CANONICAL),
                "authority": "canonical_content", "canonicality": "content_source",
            },
            {
                "role": "chunk_index_jsonl", "path": "demo.chunk_index.jsonl",
                "content_type": "application/x-ndjson", "bytes": len(chunk_bytes),
                "sha256": _sha256(chunk_bytes),
                "authority": "retrieval_index", "canonicality": "derived",
            },
        ],
        "links": {},
        "capabilities": {"fts5_bm25": False, "redaction": False},
    }
    manifest_path = tmp_path / "demo.bundle.manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest_path


def test_cli_agent_pack_json_ok(tmp_path, capsys):
    manifest = _make_bundle(tmp_path)
    rc = main(["agent-pack", "produce", str(manifest), "--json"])
    assert rc == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "ok"
    assert Path(report["output_path"]).exists()


def test_cli_agent_pack_human_ok(tmp_path, capsys):
    manifest = _make_bundle(tmp_path)
    rc = main(["agent-pack", "produce", str(manifest)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Agent Reading Pack: OK" in out


def test_cli_agent_pack_missing_manifest_returns_2(tmp_path, capsys):
    rc = main(["agent-pack", "produce", str(tmp_path / "missing.bundle.manifest.json"), "--json"])
    assert rc == 2
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "fail"
    assert report["error_kind"] == "path_read_error"


def test_cli_agent_pack_explicit_output(tmp_path, capsys):
    manifest = _make_bundle(tmp_path)
    out = tmp_path / "custom_pack.md"
    rc = main(["agent-pack", "produce", str(manifest), "--output", str(out), "--json"])
    assert rc == 0
    assert out.exists()
