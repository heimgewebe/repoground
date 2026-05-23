"""
CLI tests for `lenskit bundle-health post`.
"""
import hashlib
import json
from pathlib import Path

from merger.lenskit.cli.main import main


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


_CANONICAL = b"# repo\n\n## file: a.py\nx = 1\n"


def _make_bundle(tmp_path: Path, *, include_pack: bool = True) -> Path:
    (tmp_path / "demo.md").write_bytes(_CANONICAL)
    chunk = {"chunk_id": "c0", "path": "a.py"}
    chunk_bytes = (json.dumps(chunk) + "\n").encode("utf-8")
    (tmp_path / "demo.chunk_index.jsonl").write_bytes(chunk_bytes)

    artifacts = [
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
    ]
    if include_pack:
        pack_bytes = b"# pack\nNAVIGATION, NOT TRUTH\n"
        (tmp_path / "demo.agent_reading_pack.md").write_bytes(pack_bytes)
        artifacts.append({
            "role": "agent_reading_pack", "path": "demo.agent_reading_pack.md",
            "content_type": "text/markdown", "bytes": len(pack_bytes),
            "sha256": _sha256(pack_bytes),
            "authority": "navigation_index", "canonicality": "derived",
        })

    manifest = {
        "kind": "repolens.bundle.manifest", "version": "1.0", "run_id": "cli-bh-run",
        "created_at": "2026-05-20T00:00:00Z",
        "generator": {"name": "test", "version": "1.0", "config_sha256": "a" * 64},
        "artifacts": artifacts, "links": {},
        "capabilities": {"fts5_bm25": False, "redaction": False},
    }
    manifest_path = tmp_path / "demo.bundle.manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest_path


def test_bundle_health_post_cli_json(tmp_path, capsys):
    manifest = _make_bundle(tmp_path)
    rc = main(["bundle-health", "post", str(manifest), "--json"])
    assert rc == 0
    report = json.loads(capsys.readouterr().out)
    assert report["kind"] == "lenskit.post_emit_health"
    assert report["status"] == "pass"
    assert report["evidence_level"] == "navigable"
    # Default invocation has no side effects: no artifact file is written.
    assert not (tmp_path / "demo.bundle_health.post.json").exists()


def test_bundle_health_post_cli_human_ok(tmp_path, capsys):
    manifest = _make_bundle(tmp_path)
    rc = main(["bundle-health", "post", str(manifest)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Post-emit Bundle Health: PASS" in out
    assert "does not imply post_emit_health.status=pass" in out


def test_bundle_health_post_cli_emit_artifact(tmp_path, capsys):
    manifest = _make_bundle(tmp_path)
    manifest_before = manifest.read_text(encoding="utf-8")

    rc = main(["bundle-health", "post", str(manifest), "--emit-artifact", "--json"])
    assert rc == 0

    out_file = tmp_path / "demo.bundle_health.post.json"
    assert out_file.exists()
    written = json.loads(out_file.read_text(encoding="utf-8"))
    assert written["status"] == "pass"
    # Explicit persistence must not mutate the manifest (no registration).
    assert manifest.read_text(encoding="utf-8") == manifest_before


def test_bundle_health_post_cli_blocked_missing_pack(tmp_path, capsys):
    manifest = _make_bundle(tmp_path, include_pack=False)
    rc = main(["bundle-health", "post", str(manifest), "--json"])
    assert rc == 2
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "blocked"


def test_bundle_health_post_cli_fail_hash_mismatch(tmp_path, capsys):
    manifest = _make_bundle(tmp_path)
    (tmp_path / "demo.md").write_bytes(_CANONICAL + b"DRIFT\n")
    rc = main(["bundle-health", "post", str(manifest), "--json"])
    assert rc == 1
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "fail"
    assert report["hash_mismatch_count"] >= 1
