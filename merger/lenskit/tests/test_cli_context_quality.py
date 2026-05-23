"""
CLI tests for `lenskit context-quality inspect`.
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
        "kind": "repolens.bundle.manifest", "version": "1.0", "run_id": "cli-cq-run",
        "created_at": "2026-05-20T00:00:00Z",
        "generator": {"name": "test", "version": "1.0", "config_sha256": "a" * 64},
        "artifacts": artifacts, "links": {},
        "capabilities": {"fts5_bm25": False, "redaction": False},
    }
    manifest_path = tmp_path / "demo.bundle.manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest_path


def test_context_quality_cli_json(tmp_path, capsys):
    manifest = _make_bundle(tmp_path)
    rc = main(["context-quality", "inspect", str(manifest), "--json"])
    assert rc == 0
    report = json.loads(capsys.readouterr().out)
    assert report["kind"] == "lenskit.context_quality"
    assert report["authority"] == "diagnostic_signal"
    assert report["risk_class"] == "diagnostic"
    assert report["projection_status"] in {"complete", "degraded"}
    # Default JSON invocation writes no artifact.
    assert not (tmp_path / "demo.context_quality.json").exists()


def test_context_quality_cli_human_states_diagnostic_only(tmp_path, capsys):
    manifest = _make_bundle(tmp_path)
    rc = main(["context-quality", "inspect", str(manifest)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Context Quality (diagnostic projection):" in out
    assert "diagnostic projection only" in out
    assert "NOT repository understanding" in out
    assert "NOT answer safety" in out
    # No file written by default.
    assert not (tmp_path / "demo.context_quality.json").exists()


def test_context_quality_cli_emit_artifact_does_not_mutate_manifest(tmp_path, capsys):
    manifest = _make_bundle(tmp_path)
    manifest_before = manifest.read_text(encoding="utf-8")

    rc = main(["context-quality", "inspect", str(manifest), "--emit-artifact", "--json"])
    assert rc == 0

    out_file = tmp_path / "demo.context_quality.json"
    assert out_file.exists()
    written = json.loads(out_file.read_text(encoding="utf-8"))
    assert written["kind"] == "lenskit.context_quality"
    # Explicit persistence must not mutate or register anything in the manifest.
    assert manifest.read_text(encoding="utf-8") == manifest_before


def test_context_quality_cli_emit_artifact_unregistered_note(tmp_path, capsys):
    manifest = _make_bundle(tmp_path)
    rc = main(["context-quality", "inspect", str(manifest), "--emit-artifact"])
    assert rc == 0
    out = capsys.readouterr().out
    assert (tmp_path / "demo.context_quality.json").exists()
    assert "written artifact is unregistered; manifest not mutated" in out


def test_context_quality_cli_output_path(tmp_path, capsys):
    manifest = _make_bundle(tmp_path)
    manifest_before = manifest.read_text(encoding="utf-8")
    target = tmp_path / "out" / "cq.json"

    rc = main(["context-quality", "inspect", str(manifest), "--output", str(target)])
    assert rc == 0
    assert target.exists()
    written = json.loads(target.read_text(encoding="utf-8"))
    assert written["kind"] == "lenskit.context_quality"
    # --output implies emission but still never mutates the manifest.
    assert manifest.read_text(encoding="utf-8") == manifest_before


def test_context_quality_cli_blocked_missing_manifest(tmp_path, capsys):
    rc = main(["context-quality", "inspect", str(tmp_path / "nope.bundle.manifest.json"), "--json"])
    assert rc == 2
    report = json.loads(capsys.readouterr().out)
    assert report["projection_status"] == "blocked"
