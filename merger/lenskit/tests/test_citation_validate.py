"""
Tests for merger.lenskit.core.citation_validate.

All tests use synthetic in-memory fixtures — no real dump required.
"""
import hashlib
import json
from pathlib import Path

from merger.lenskit.core.citation_validate import validate_bundle


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _make_bundle(
    tmp_path: Path,
    canonical_content: bytes,
    chunks: list,
    *,
    canonical_sha_override: str = None,
    chunk_index_sha_override: str = None,
) -> Path:
    """
    Write a minimal synthetic bundle into tmp_path and return the manifest path.

    Each item in `chunks` is a dict that will be written as a JSONL line.
    The caller is responsible for constructing valid or intentionally broken entries.
    """
    canonical_md_path = tmp_path / "merge.md"
    canonical_md_path.write_bytes(canonical_content)

    chunk_lines = "\n".join(json.dumps(c) for c in chunks) + "\n"
    chunk_index_bytes = chunk_lines.encode("utf-8")
    chunk_index_path = tmp_path / "chunk_index.jsonl"
    chunk_index_path.write_bytes(chunk_index_bytes)

    actual_canonical_sha = _sha256(canonical_content)
    actual_chunk_sha = _sha256(chunk_index_bytes)

    manifest = {
        "kind": "repolens.bundle.manifest",
        "version": "1.0",
        "run_id": "test-run-001",
        "created_at": "2026-05-13T00:00:00Z",
        "generator": {
            "name": "test",
            "version": "0.0.1",
            "config_sha256": "a" * 64,
        },
        "artifacts": [
            {
                "role": "canonical_md",
                "path": "merge.md",
                "content_type": "text/markdown",
                "bytes": len(canonical_content),
                "sha256": canonical_sha_override or actual_canonical_sha,
            },
            {
                "role": "chunk_index_jsonl",
                "path": "chunk_index.jsonl",
                "content_type": "application/x-ndjson",
                "bytes": len(chunk_index_bytes),
                "sha256": chunk_index_sha_override or actual_chunk_sha,
            },
        ],
        "links": [],
        "capabilities": [],
    }

    manifest_path = tmp_path / "bundle.manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path


def _make_chunk(canonical_content: bytes, canonical_md_rel: str, start: int, end: int) -> dict:
    """Build a valid chunk entry for the given byte range."""
    range_bytes = canonical_content[start:end]
    content_sha = _sha256(range_bytes)
    return {
        "chunk_id": f"chunk-{start}-{end}",
        "canonical_range": {
            "artifact_role": "canonical_md",
            "file_path": canonical_md_rel,
            "start_byte": start,
            "end_byte": end,
            "content_sha256": content_sha,
        },
    }


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_valid_bundle_reports_ok(tmp_path):
    content = b"Hello world this is canonical markdown content for testing purposes."
    chunk = _make_chunk(content, "merge.md", 0, 20)
    manifest_path = _make_bundle(tmp_path, content, [chunk])

    report = validate_bundle(str(manifest_path))

    assert report["status"] == "ok"
    assert report["error_kind"] == "ok"
    assert report["chunk_count"] == 1
    assert report["canonical_range_count"] == 1
    assert report["citation_id_count"] == 1
    assert report["canonical_range_hash_ok_count"] == 1
    assert report["citation_id_duplicate_count"] == 0
    assert len(report["errors"]) == 0
    assert len(report["sample_citation_ids"]) == 1
    assert report["canonical_md_actual_sha256"] == report["canonical_md_sha256"]
    assert report["chunk_index_actual_sha256"] == report["chunk_index_sha256"]


def test_valid_bundle_multiple_chunks(tmp_path):
    content = b"AAAA BBBB CCCC DDDD EEEE FFFF GGGG HHHH IIII JJJJ"
    chunks = [
        _make_chunk(content, "merge.md", 0, 5),
        _make_chunk(content, "merge.md", 5, 10),
        _make_chunk(content, "merge.md", 10, 15),
    ]
    manifest_path = _make_bundle(tmp_path, content, chunks)

    report = validate_bundle(str(manifest_path))

    assert report["status"] == "ok"
    assert report["chunk_count"] == 3
    assert report["citation_id_count"] == 3
    assert report["citation_id_duplicate_count"] == 0


def test_sample_citation_ids_capped_at_five(tmp_path):
    content = bytes(range(100))
    chunks = [_make_chunk(content, "merge.md", i, i + 10) for i in range(0, 70, 10)]
    manifest_path = _make_bundle(tmp_path, content, chunks)

    report = validate_bundle(str(manifest_path))

    assert report["status"] == "ok"
    assert len(report["sample_citation_ids"]) == 5


def test_source_range_and_content_range_ref_counted(tmp_path):
    content = b"Source and ref test content abcdefghijklmnop"
    chunk = _make_chunk(content, "merge.md", 0, 10)
    chunk["source_range"] = {"file_path": "original.py", "start_line": 1, "end_line": 5}
    chunk["content_range_ref"] = {"artifact_role": "chunk_index_jsonl", "start_byte": 0, "end_byte": 10}
    manifest_path = _make_bundle(tmp_path, content, [chunk])

    report = validate_bundle(str(manifest_path))

    assert report["status"] == "ok"
    assert report["source_range_count"] == 1
    assert report["content_range_ref_count"] == 1


# ---------------------------------------------------------------------------
# Hash mismatch
# ---------------------------------------------------------------------------

def test_canonical_md_sha_mismatch_fails(tmp_path):
    content = b"canonical content"
    chunk = _make_chunk(content, "merge.md", 0, 9)
    manifest_path = _make_bundle(tmp_path, content, [chunk], canonical_sha_override="b" * 64)

    report = validate_bundle(str(manifest_path))

    assert report["status"] == "fail"
    assert any("canonical_md SHA256 mismatch" in e for e in report["errors"])


def test_chunk_index_sha_mismatch_fails(tmp_path):
    content = b"canonical content"
    chunk = _make_chunk(content, "merge.md", 0, 9)
    manifest_path = _make_bundle(tmp_path, content, [chunk], chunk_index_sha_override="c" * 64)

    report = validate_bundle(str(manifest_path))

    assert report["status"] == "fail"
    assert any("chunk_index_jsonl SHA256 mismatch" in e for e in report["errors"])


def test_report_contains_actual_sha_on_manifest_mismatch(tmp_path):
    content = b"canonical content"
    chunk = _make_chunk(content, "merge.md", 0, 9)
    manifest_path = _make_bundle(tmp_path, content, [chunk], canonical_sha_override="b" * 64)

    report = validate_bundle(str(manifest_path))

    assert report["status"] == "fail"
    assert report["canonical_md_sha256"] == "b" * 64
    assert report["canonical_md_actual_sha256"] == _sha256(content)


def test_missing_manifest_sha256_fails(tmp_path):
    content = b"canonical content"
    chunk = _make_chunk(content, "merge.md", 0, 9)
    manifest_path = _make_bundle(tmp_path, content, [chunk])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for artifact in manifest["artifacts"]:
        if artifact.get("role") in ("canonical_md", "chunk_index_jsonl"):
            artifact.pop("sha256", None)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    report = validate_bundle(str(manifest_path))

    assert report["status"] == "fail"
    assert any("canonical_md sha256 is missing" in e for e in report["errors"])
    assert any("chunk_index_jsonl sha256 is missing" in e for e in report["errors"])


def test_range_content_sha_mismatch_fails(tmp_path):
    content = b"Hello world range test"
    chunk = _make_chunk(content, "merge.md", 0, 10)
    # corrupt the content_sha256 in the canonical_range
    chunk["canonical_range"]["content_sha256"] = "d" * 64
    manifest_path = _make_bundle(tmp_path, content, [chunk])

    report = validate_bundle(str(manifest_path))

    assert report["status"] == "fail"
    assert any("content SHA256 mismatch" in e for e in report["errors"])


# ---------------------------------------------------------------------------
# Byte range errors
# ---------------------------------------------------------------------------

def test_out_of_bounds_end_byte_fails(tmp_path):
    content = b"short"
    chunk = _make_chunk(content, "merge.md", 0, 3)
    chunk["canonical_range"]["end_byte"] = 999  # beyond file size
    # also fix content_sha256 to avoid hash mismatch masking this error
    chunk["canonical_range"]["content_sha256"] = "e" * 64
    manifest_path = _make_bundle(tmp_path, content, [chunk])

    report = validate_bundle(str(manifest_path))

    assert report["status"] == "fail"
    assert any("exceeds" in e or "end_byte" in e for e in report["errors"])


def test_empty_range_end_equals_start_fails(tmp_path):
    content = b"empty range test"
    chunk = _make_chunk(content, "merge.md", 5, 10)
    chunk["canonical_range"]["end_byte"] = 5  # equal to start_byte
    chunk["canonical_range"]["content_sha256"] = "f" * 64
    manifest_path = _make_bundle(tmp_path, content, [chunk])

    report = validate_bundle(str(manifest_path))

    assert report["status"] == "fail"
    assert any("end_byte must be > start_byte" in e for e in report["errors"])


def test_negative_start_byte_fails(tmp_path):
    content = b"negative byte test"
    chunk = _make_chunk(content, "merge.md", 0, 5)
    chunk["canonical_range"]["start_byte"] = -1
    chunk["canonical_range"]["content_sha256"] = "a" * 64
    manifest_path = _make_bundle(tmp_path, content, [chunk])

    report = validate_bundle(str(manifest_path))

    assert report["status"] == "fail"
    assert any("start_byte must be >= 0" in e for e in report["errors"])


# ---------------------------------------------------------------------------
# Bool byte offsets
# ---------------------------------------------------------------------------

def test_bool_start_byte_fails(tmp_path):
    content = b"bool test content"
    chunk = _make_chunk(content, "merge.md", 0, 5)
    chunk["canonical_range"]["start_byte"] = True  # bool is subclass of int in Python
    manifest_path = _make_bundle(tmp_path, content, [chunk])

    report = validate_bundle(str(manifest_path))

    assert report["status"] == "fail"
    assert any("start_byte must not be bool" in e for e in report["errors"])


def test_bool_end_byte_fails(tmp_path):
    content = b"bool test content"
    chunk = _make_chunk(content, "merge.md", 0, 5)
    chunk["canonical_range"]["end_byte"] = True
    manifest_path = _make_bundle(tmp_path, content, [chunk])

    report = validate_bundle(str(manifest_path))

    assert report["status"] == "fail"
    assert any("end_byte must not be bool" in e for e in report["errors"])


# ---------------------------------------------------------------------------
# Missing canonical_range
# ---------------------------------------------------------------------------

def test_missing_canonical_range_fails(tmp_path):
    content = b"no canonical range here"
    chunk = {
        "chunk_id": "chunk-no-range",
        "source_range": {"file_path": "src.py", "start_line": 1, "end_line": 3},
    }
    manifest_path = _make_bundle(tmp_path, content, [chunk])

    report = validate_bundle(str(manifest_path))

    assert report["status"] == "fail"
    assert any("missing 'canonical_range'" in e for e in report["errors"])


# ---------------------------------------------------------------------------
# Duplicate citation_id
# ---------------------------------------------------------------------------

def test_duplicate_citation_id_reported_as_error(tmp_path):
    content = b"duplicate range content test"
    # Two identical ranges → same citation_id
    chunk1 = _make_chunk(content, "merge.md", 0, 10)
    chunk2 = _make_chunk(content, "merge.md", 0, 10)
    chunk2["chunk_id"] = "chunk-dup"
    manifest_path = _make_bundle(tmp_path, content, [chunk1, chunk2])

    report = validate_bundle(str(manifest_path))

    assert report["status"] == "fail"
    assert report["citation_id_duplicate_count"] == 1
    assert any("duplicate citation_id" in e for e in report["errors"])


# ---------------------------------------------------------------------------
# Path traversal / unsafe paths
# ---------------------------------------------------------------------------

def test_path_traversal_in_canonical_md_path_fails(tmp_path):
    content = b"traversal test"
    chunk = _make_chunk(content, "merge.md", 0, 5)

    manifest = {
        "kind": "repolens.bundle.manifest",
        "version": "1.0",
        "run_id": "test-traversal",
        "created_at": "2026-05-13T00:00:00Z",
        "generator": {"name": "test", "version": "0", "config_sha256": "a" * 64},
        "artifacts": [
            {
                "role": "canonical_md",
                "path": "../evil.md",  # traversal attempt
                "content_type": "text/markdown",
                "bytes": len(content),
                "sha256": _sha256(content),
            },
            {
                "role": "chunk_index_jsonl",
                "path": "chunk_index.jsonl",
                "content_type": "application/x-ndjson",
                "bytes": 0,
                "sha256": _sha256(b""),
            },
        ],
        "links": [],
        "capabilities": [],
    }
    manifest_path = tmp_path / "bundle.manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    report = validate_bundle(str(manifest_path))

    assert report["status"] == "fail"
    assert any("traversal" in e or "forbidden" in e for e in report["errors"])


def test_absolute_canonical_md_path_fails(tmp_path):
    content = b"absolute path test"

    manifest = {
        "kind": "repolens.bundle.manifest",
        "version": "1.0",
        "run_id": "test-abs",
        "created_at": "2026-05-13T00:00:00Z",
        "generator": {"name": "test", "version": "0", "config_sha256": "a" * 64},
        "artifacts": [
            {
                "role": "canonical_md",
                "path": "/etc/passwd",  # absolute path
                "content_type": "text/markdown",
                "bytes": 0,
                "sha256": _sha256(b""),
            },
            {
                "role": "chunk_index_jsonl",
                "path": "chunk_index.jsonl",
                "content_type": "application/x-ndjson",
                "bytes": 0,
                "sha256": _sha256(b""),
            },
        ],
        "links": [],
        "capabilities": [],
    }
    manifest_path = tmp_path / "bundle.manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    report = validate_bundle(str(manifest_path))

    assert report["status"] == "fail"
    assert any("absolute" in e or "forbidden" in e for e in report["errors"])


def test_canonical_range_file_path_with_dot_slash_is_accepted(tmp_path):
    content = b"dot slash canonical path"
    chunk = _make_chunk(content, "./merge.md", 0, 10)
    manifest_path = _make_bundle(tmp_path, content, [chunk])

    report = validate_bundle(str(manifest_path))

    assert report["status"] == "ok"


def test_canonical_range_file_path_with_windows_drive_prefix_fails(tmp_path):
    content = b"windows drive path"
    for windows_path in ("C:merge.md", "C:/merge.md", r"C:\merge.md"):
        chunk = _make_chunk(content, windows_path, 0, 5)
        manifest_path = _make_bundle(tmp_path, content, [chunk])

        report = validate_bundle(str(manifest_path))

        assert report["status"] == "fail"
        assert any("Windows drive-prefixed paths are forbidden" in e for e in report["errors"])


def test_canonical_range_file_path_with_windows_root_prefix_fails(tmp_path):
    content = b"windows rooted path"
    chunk = _make_chunk(content, r"\merge.md", 0, 5)
    manifest_path = _make_bundle(tmp_path, content, [chunk])

    report = validate_bundle(str(manifest_path))

    assert report["status"] == "fail"
    assert any("Windows rooted paths are forbidden" in e for e in report["errors"])


def test_canonical_range_file_path_mismatch_does_not_increment_hash_or_citation_counts(tmp_path):
    content = b"path mismatch counter guard"
    chunk = _make_chunk(content, "different.md", 0, 10)
    manifest_path = _make_bundle(tmp_path, content, [chunk])

    report = validate_bundle(str(manifest_path))

    assert report["status"] == "fail"
    assert report["canonical_range_hash_ok_count"] == 0
    assert report["citation_id_count"] == 0


# ---------------------------------------------------------------------------
# Missing manifest / artifact roles
# ---------------------------------------------------------------------------

def test_manifest_not_found_fails():
    report = validate_bundle("/nonexistent/path/bundle.manifest.json")
    assert report["status"] == "fail"
    assert report["error_kind"] == "path_read_error"
    assert any("not found" in e for e in report["errors"])


def test_manifest_missing_canonical_md_role_fails(tmp_path):
    manifest = {
        "kind": "repolens.bundle.manifest",
        "version": "1.0",
        "run_id": "test-no-canonical",
        "created_at": "2026-05-13T00:00:00Z",
        "generator": {"name": "test", "version": "0", "config_sha256": "a" * 64},
        "artifacts": [
            {
                "role": "chunk_index_jsonl",
                "path": "chunk_index.jsonl",
                "content_type": "application/x-ndjson",
                "bytes": 0,
                "sha256": _sha256(b""),
            }
        ],
        "links": [],
        "capabilities": [],
    }
    manifest_path = tmp_path / "bundle.manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    report = validate_bundle(str(manifest_path))

    assert report["status"] == "fail"
    assert report["error_kind"] == "validation_error"
    assert any("canonical_md" in e for e in report["errors"])


def test_manifest_missing_chunk_index_role_fails(tmp_path):
    content = b"content"
    (tmp_path / "merge.md").write_bytes(content)

    manifest = {
        "kind": "repolens.bundle.manifest",
        "version": "1.0",
        "run_id": "test-no-chunk",
        "created_at": "2026-05-13T00:00:00Z",
        "generator": {"name": "test", "version": "0", "config_sha256": "a" * 64},
        "artifacts": [
            {
                "role": "canonical_md",
                "path": "merge.md",
                "content_type": "text/markdown",
                "bytes": len(content),
                "sha256": _sha256(content),
            }
        ],
        "links": [],
        "capabilities": [],
    }
    manifest_path = tmp_path / "bundle.manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    report = validate_bundle(str(manifest_path))

    assert report["status"] == "fail"
    assert any("chunk_index_jsonl" in e for e in report["errors"])


def test_manifest_artifact_entry_not_object_fails(tmp_path):
    manifest = {
        "kind": "repolens.bundle.manifest",
        "version": "1.0",
        "run_id": "test-bad-artifact-entry",
        "created_at": "2026-05-13T00:00:00Z",
        "generator": {"name": "test", "version": "0", "config_sha256": "a" * 64},
        "artifacts": ["not-an-object"],
        "links": [],
        "capabilities": [],
    }
    manifest_path = tmp_path / "bundle.manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    report = validate_bundle(str(manifest_path))

    assert report["status"] == "fail"
    assert report["error_kind"] == "validation_error"
    assert any("artifact at index 0 is not an object" in e for e in report["errors"])


# ---------------------------------------------------------------------------
# Report structure completeness
# ---------------------------------------------------------------------------

def test_report_has_all_required_keys(tmp_path):
    content = b"structure test"
    chunk = _make_chunk(content, "merge.md", 0, 7)
    manifest_path = _make_bundle(tmp_path, content, [chunk])

    report = validate_bundle(str(manifest_path))

    required_keys = {
        "status", "error_kind", "bundle_manifest_path", "bundle_run_id", "validation_run_id",
        "canonical_md_sha256", "chunk_index_sha256",
        "canonical_md_actual_sha256", "chunk_index_actual_sha256",
        "chunk_count", "canonical_range_count",
        "source_range_count", "content_range_ref_count", "citation_id_count",
        "citation_id_duplicate_count", "canonical_range_hash_ok_count",
        "errors", "warnings", "sample_citation_ids",
    }
    assert required_keys.issubset(report.keys())


def test_report_separates_bundle_run_id_and_validation_run_id(tmp_path):
    content = b"unique run id test"
    chunk = _make_chunk(content, "merge.md", 0, 6)
    manifest_path = _make_bundle(tmp_path, content, [chunk])

    r1 = validate_bundle(str(manifest_path))
    r2 = validate_bundle(str(manifest_path))

    assert r1["bundle_run_id"] == "test-run-001"
    assert r2["bundle_run_id"] == "test-run-001"
    assert r1["validation_run_id"] != r2["validation_run_id"]
