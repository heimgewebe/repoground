"""
CLI tests for `lenskit citation validate`.

Uses the same synthetic fixture helpers as test_citation_validate.py.
"""
import hashlib
import json
from pathlib import Path

from merger.repoground.cli.main import main
from merger.repoground.core.merge import FileInfo, write_reports_v2
from merger.repoground.tests._test_constants import make_generator_info


# ---------------------------------------------------------------------------
# Helpers (duplicated locally to keep tests self-contained)
# ---------------------------------------------------------------------------

def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _make_bundle(tmp_path: Path, canonical_content: bytes, chunks: list) -> Path:
    canonical_md_path = tmp_path / "merge.md"
    canonical_md_path.write_bytes(canonical_content)

    chunk_lines = "\n".join(json.dumps(c) for c in chunks) + "\n"
    chunk_index_bytes = chunk_lines.encode("utf-8")
    (tmp_path / "chunk_index.jsonl").write_bytes(chunk_index_bytes)

    manifest = {
        "kind": "repolens.bundle.manifest",
        "version": "1.0",
        "run_id": "cli-test-run",
        "created_at": "2026-05-13T00:00:00Z",
        "generator": {"name": "test", "version": "0.0.1", "config_sha256": "a" * 64},
        "artifacts": [
            {
                "role": "canonical_md",
                "path": "merge.md",
                "content_type": "text/markdown",
                "bytes": len(canonical_content),
                "sha256": _sha256(canonical_content),
            },
            {
                "role": "chunk_index_jsonl",
                "path": "chunk_index.jsonl",
                "content_type": "application/x-ndjson",
                "bytes": len(chunk_index_bytes),
                "sha256": _sha256(chunk_index_bytes),
            },
        ],
        "links": [],
        "capabilities": [],
    }
    manifest_path = tmp_path / "bundle.manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path


def _make_chunk(canonical_content: bytes, start: int, end: int) -> dict:
    range_bytes = canonical_content[start:end]
    content_sha = _sha256(range_bytes)
    return {
        "chunk_id": f"chunk-{start}-{end}",
        "canonical_range": {
            "artifact_role": "canonical_md",
            "file_path": "merge.md",
            "start_byte": start,
            "end_byte": end,
            "content_sha256": content_sha,
        },
    }


def _make_generated_bundle(tmp_path: Path) -> Path:
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    source_file = src_dir / "file1.txt"
    source_file.write_text("Hello World", encoding="utf-8")

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    hub_dir = tmp_path / "hub"
    hub_dir.mkdir()

    file_info = FileInfo(
        root_label="test-repo",
        abs_path=source_file,
        rel_path=Path("file1.txt"),
        size=11,
        is_text=True,
        md5="test",
        category="docs",
        tags=[],
        ext=".txt",
        skipped=False,
    )

    repo_summary = {
        "name": "test-repo",
        "path": str(src_dir),
        "root": src_dir,
        "files": [file_info],
        "source_files": [file_info],
    }

    artifacts = write_reports_v2(
        merges_dir=out_dir,
        hub=hub_dir,
        repo_summaries=[repo_summary],
        detail="test",
        mode="gesamt",
        max_bytes=1000,
        plan_only=False,
        code_only=False,
        output_mode="dual",
        generator_info=make_generator_info(),
    )

    assert artifacts.bundle_manifest is not None
    assert artifacts.bundle_manifest.exists()
    return artifacts.bundle_manifest


# ---------------------------------------------------------------------------
# CLI: --json output and exit code 0 on valid fixture
# ---------------------------------------------------------------------------

def test_cli_json_output_exit_0_on_valid_bundle(tmp_path, capsys):
    content = b"CLI test canonical content abcdefghij"
    chunks = [_make_chunk(content, 0, 10), _make_chunk(content, 10, 20)]
    manifest_path = _make_bundle(tmp_path, content, chunks)

    rc = main(["citation", "validate", "--json", str(manifest_path)])

    assert rc == 0
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert report["status"] == "ok"
    assert report["error_kind"] == "ok"
    assert report["chunk_count"] == 2
    assert report["citation_id_count"] == 2
    assert report["canonical_md_actual_sha256"] == report["canonical_md_sha256"]
    assert report["chunk_index_actual_sha256"] == report["chunk_index_sha256"]
    assert isinstance(report["errors"], list)
    assert len(report["errors"]) == 0


def test_cli_json_output_exit_0_on_generated_bundle(tmp_path, capsys):
    manifest_path = _make_generated_bundle(tmp_path)

    rc = main(["citation", "validate", "--json", str(manifest_path)])

    assert rc == 0
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert report["status"] == "ok"
    assert report["citation_id_count"] > 0
    assert report["canonical_md_actual_sha256"] == report["canonical_md_sha256"]
    assert report["chunk_index_actual_sha256"] == report["chunk_index_sha256"]


# ---------------------------------------------------------------------------
# CLI: exit code 1 on invalid fixture (hash mismatch)
# ---------------------------------------------------------------------------

def test_cli_exit_1_on_invalid_bundle(tmp_path, capsys):
    content = b"Invalid bundle test content"
    chunk = _make_chunk(content, 0, 10)
    # corrupt the content_sha256
    chunk["canonical_range"]["content_sha256"] = "b" * 64
    manifest_path = _make_bundle(tmp_path, content, [chunk])

    rc = main(["citation", "validate", "--json", str(manifest_path)])

    assert rc == 1
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert report["status"] == "fail"
    assert report["error_kind"] == "validation_error"
    assert len(report["errors"]) > 0


# ---------------------------------------------------------------------------
# CLI: exit code 2 on missing manifest path
# ---------------------------------------------------------------------------

def test_cli_exit_2_on_missing_manifest(tmp_path, capsys):
    rc = main(
        ["citation", "validate", "--json", str(tmp_path / "nonexistent.manifest.json")]
    )
    assert rc == 2
    captured = capsys.readouterr()
    assert captured.out.strip()
    report = json.loads(captured.out)
    assert report["status"] == "fail"
    assert report["error_kind"] == "path_read_error"


def test_cli_exit_2_on_manifest_path_directory(tmp_path, capsys):
    manifest_dir = tmp_path / "manifest_dir"
    manifest_dir.mkdir()

    rc = main(["citation", "validate", "--json", str(manifest_dir)])

    assert rc == 2
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert report["status"] == "fail"
    assert report["error_kind"] == "path_read_error"


def test_cli_exit_2_on_missing_canonical_md_artifact_file(tmp_path, capsys):
    content = b"missing canonical md file"
    chunk = _make_chunk(content, 0, 7)
    manifest_path = _make_bundle(tmp_path, content, [chunk])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for artifact in manifest["artifacts"]:
        if artifact["role"] == "canonical_md":
            artifact["path"] = "missing-merge.md"
            break
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    rc = main(["citation", "validate", "--json", str(manifest_path)])

    assert rc == 2
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert report["status"] == "fail"
    assert report["error_kind"] == "path_read_error"


def test_cli_exit_2_on_missing_chunk_index_artifact_file(tmp_path, capsys):
    content = b"missing chunk index file"
    chunk = _make_chunk(content, 0, 7)
    manifest_path = _make_bundle(tmp_path, content, [chunk])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for artifact in manifest["artifacts"]:
        if artifact["role"] == "chunk_index_jsonl":
            artifact["path"] = "missing-chunk-index.jsonl"
            break
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    rc = main(["citation", "validate", "--json", str(manifest_path)])

    assert rc == 2
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert report["status"] == "fail"
    assert report["error_kind"] == "path_read_error"


# ---------------------------------------------------------------------------
# CLI: human-readable output (no --json)
# ---------------------------------------------------------------------------

def test_cli_human_output_shows_status(tmp_path, capsys):
    content = b"Human readable output test content xyz"
    chunk = _make_chunk(content, 0, 15)
    manifest_path = _make_bundle(tmp_path, content, [chunk])

    rc = main(["citation", "validate", str(manifest_path)])

    assert rc == 0
    captured = capsys.readouterr()
    assert "Citation Readiness: OK" in captured.out
    assert "citation_id_count" in captured.out


def test_cli_human_output_shows_errors_on_fail(tmp_path, capsys):
    content = b"error output test"
    chunk = {
        "chunk_id": "no-range",
        # no canonical_range
    }
    manifest_path = _make_bundle(tmp_path, content, [chunk])

    rc = main(["citation", "validate", str(manifest_path)])

    assert rc == 1
    captured = capsys.readouterr()
    assert "Citation Readiness: FAIL" in captured.out
    assert "[error]" in captured.out
