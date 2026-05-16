import hashlib
import json
import sqlite3
from pathlib import Path

from merger.lenskit.cli.main import main


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _make_sqlite(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    try:
        c = conn.cursor()
        c.execute("CREATE TABLE chunks (chunk_id TEXT PRIMARY KEY, content TEXT)")
        c.execute("CREATE VIRTUAL TABLE chunks_fts USING fts5(chunk_id UNINDEXED, content, path_tokens)")
        c.execute("INSERT INTO chunks VALUES ('c1', 'hello')")
        c.execute("INSERT INTO chunks_fts VALUES ('c1', 'hello', 'x')")
        conn.commit()
    finally:
        conn.close()


def _make_bundle(root: Path, *, health_warning: bool = False) -> Path:
    root.mkdir(parents=True, exist_ok=True)

    canonical_md = b"# cli\n"
    canonical_md_path = root / "merge.md"
    canonical_md_path.write_bytes(canonical_md)

    chunk_path = root / "chunk_index.jsonl"
    chunk_path.write_text(json.dumps({"chunk_id": "c1"}) + "\n", encoding="utf-8")

    sidecar = {
        "meta": {"contract": "repolens-agent", "contract_version": "v2"},
        "coverage": {"included_text_files": 1, "total_text_files": 1, "coverage_pct": 100.0},
        "files": [{"path": "src/a.py", "included": True, "sha256": _sha256_bytes(b"print('a')")}],
    }
    sidecar_path = root / "index.sidecar.json"
    _write_json(sidecar_path, sidecar)

    dump_index_path = root / "bundle.dump_index.json"
    _write_json(
        dump_index_path,
        {
            "contract": "dump-index",
            "contract_version": "v1",
            "artifacts": {
                "canonical_md": {"path": canonical_md_path.name, "role": "canonical_md"},
                "chunk_index_jsonl": {"path": chunk_path.name, "role": "chunk_index_jsonl"},
            },
        },
    )

    sqlite_path = root / "bundle.index.sqlite"
    _make_sqlite(sqlite_path)

    health_path = root / "bundle.output_health.json"
    _write_json(
        health_path,
        {
            "kind": "lenskit.output_health",
            "version": "1.0",
            "run_id": "r1",
            "created_at": "2026-05-16T00:00:00Z",
            "stem": root.name,
            "checks": {
                "range_ref_resolution_ok": True,
                "sqlite_checks_required": True,
                "fts_content_non_empty": True,
            },
            "warnings": ["warn"] if health_warning else [],
            "errors": [],
            "verdict": "warn" if health_warning else "pass",
        },
    )

    artifacts = []
    for role, path, ctype in [
        ("canonical_md", canonical_md_path, "text/markdown"),
        ("chunk_index_jsonl", chunk_path, "application/x-ndjson"),
        ("index_sidecar_json", sidecar_path, "application/json"),
        ("dump_index_json", dump_index_path, "application/json"),
        ("sqlite_index", sqlite_path, "application/octet-stream"),
        ("output_health", health_path, "application/json"),
    ]:
        data = path.read_bytes()
        artifacts.append(
            {
                "role": role,
                "path": path.name,
                "content_type": ctype,
                "bytes": len(data),
                "sha256": _sha256_bytes(data),
            }
        )

    manifest = {
        "kind": "repolens.bundle.manifest",
        "version": "1.0",
        "run_id": "cli-run",
        "created_at": "2026-05-16T00:00:00Z",
        "generator": {"name": "test", "version": "0.1", "config_sha256": "a" * 64},
        "artifacts": artifacts,
        "links": {},
        "capabilities": {"fts5_bm25": True, "redaction": False},
    }
    manifest_path = root / "bundle.bundle.manifest.json"
    _write_json(manifest_path, manifest)
    return manifest_path


def test_cli_parity_compare_json_exit_0_on_green(tmp_path, capsys):
    left = _make_bundle(tmp_path / "left")
    right = _make_bundle(tmp_path / "right")

    rc = main(["parity", "compare", str(left), str(right), "--json"])

    assert rc == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["content_parity_pass"] is True
    assert payload["diagnostic_parity_pass"] is True
    assert isinstance(payload["compared_artifacts"], list)


def test_cli_parity_compare_exit_1_on_diagnostic_fail(tmp_path, capsys):
    left = _make_bundle(tmp_path / "left")
    right = _make_bundle(tmp_path / "right", health_warning=True)

    rc = main(["parity", "compare", str(left), str(right), "--json"])

    assert rc == 1
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["content_parity_pass"] is True
    assert payload["diagnostic_parity_pass"] is False


def test_cli_parity_compare_exit_2_on_missing_manifest(tmp_path, capsys):
    missing = tmp_path / "missing.bundle.manifest.json"
    other = _make_bundle(tmp_path / "other")

    rc = main(["parity", "compare", str(missing), str(other), "--json"])

    assert rc == 2
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["status"] == "fail"
    assert payload["error_kind"] == "path_read_error"


def test_cli_parity_compare_exit_2_on_path_traversal_artifact(tmp_path, capsys):
    left = _make_bundle(tmp_path / "left")
    right = _make_bundle(tmp_path / "right")

    left_manifest = json.loads(left.read_text(encoding="utf-8"))
    for artifact in left_manifest["artifacts"]:
        if artifact.get("role") == "canonical_md":
            artifact["path"] = "../escape.md"
            break
    left.write_text(json.dumps(left_manifest, indent=2), encoding="utf-8")

    rc = main(["parity", "compare", str(left), str(right), "--json"])

    assert rc == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "fail"
    assert payload["error_kind"] == "path_read_error"
