"""
Tests for merger.lenskit.core.citation_map (Citation Map Producer).

All unit tests use synthetic in-memory fixtures; the real-dump proof
is in docs/proofs/citation-map-producer-proof.md.
"""
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from merger.lenskit.core.citation_id import make_citation_id
from merger.lenskit.core.citation_map import (
    CitationMapError,
    PRODUCED_BY,
    byte_range_to_line_range,
    normalize_canonical_range,
    produce_citation_map,
    resolve_repo_id,
    verify_byte_range_hash,
)
from merger.lenskit.core.constants import ArtifactRole


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _make_bundle(
    tmp_path: Path,
    canonical_content: bytes,
    chunks: List[Dict[str, Any]],
    *,
    canonical_sha_override: Optional[str] = None,
    chunk_index_sha_override: Optional[str] = None,
    stem: str = "test_merge",
) -> Path:
    canonical_md_path = tmp_path / f"{stem}.md"
    canonical_md_path.write_bytes(canonical_content)

    chunk_lines = "\n".join(json.dumps(c) for c in chunks) + "\n"
    chunk_index_bytes = chunk_lines.encode("utf-8")
    chunk_index_path = tmp_path / f"{stem}.chunk_index.jsonl"
    chunk_index_path.write_bytes(chunk_index_bytes)

    actual_canonical_sha = _sha256(canonical_content)
    actual_chunk_sha = _sha256(chunk_index_bytes)

    manifest = {
        "kind": "repolens.bundle.manifest",
        "version": "1.0",
        "run_id": "test-run-001",
        "created_at": "2026-05-14T00:00:00Z",
        "generator": {
            "name": "test",
            "version": "0.0.1",
            "config_sha256": "a" * 64,
        },
        "artifacts": [
            {
                "role": "canonical_md",
                "path": f"{stem}.md",
                "content_type": "text/markdown",
                "bytes": len(canonical_content),
                "sha256": canonical_sha_override or actual_canonical_sha,
                "authority": "canonical_content",
                "canonicality": "content_source",
                "regenerable": True,
                "staleness_sensitive": False,
                "interpretation": {"mode": "role_only"},
            },
            {
                "role": "chunk_index_jsonl",
                "path": f"{stem}.chunk_index.jsonl",
                "content_type": "application/x-ndjson",
                "bytes": len(chunk_index_bytes),
                "sha256": chunk_index_sha_override or actual_chunk_sha,
                "authority": "retrieval_index",
                "canonicality": "derived",
                "regenerable": True,
                "staleness_sensitive": True,
                "interpretation": {"mode": "role_only"},
            },
        ],
        "links": {},
        "capabilities": {"fts5_bm25": False, "redaction": False},
    }

    manifest_path = tmp_path / f"{stem}.bundle.manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path


def _canonical_range_chunk(
    canonical_content: bytes,
    start_byte: int,
    end_byte: int,
    md_path: str,
    repo_id: str = "testrepo",
    chunk_id: str = "chunk001",
) -> Dict[str, Any]:
    content_sha = _sha256(canonical_content[start_byte:end_byte])
    return {
        "chunk_id": chunk_id,
        "repo": repo_id,
        "canonical_range": {
            "artifact_role": "canonical_md",
            "repo_id": repo_id,
            "file_path": md_path,
            "start_byte": start_byte,
            "end_byte": end_byte,
            "start_line": 1,
            "end_line": 2,
            "content_sha256": content_sha,
        },
    }


def _content_range_ref_chunk(
    canonical_content: bytes,
    start_byte: int,
    end_byte: int,
    md_path: str,
    repo_id: str = "testrepo",
    chunk_id: str = "chunk001",
) -> Dict[str, Any]:
    content_sha = _sha256(canonical_content[start_byte:end_byte])
    return {
        "chunk_id": chunk_id,
        "repo": repo_id,
        "content_range_ref": {
            "artifact_role": "canonical_md",
            "repo_id": repo_id,
            "file_path": md_path,
            "start_byte": start_byte,
            "end_byte": end_byte,
            "start_line": 1,
            "end_line": 2,
            "content_sha256": content_sha,
        },
    }


# ---------------------------------------------------------------------------
# normalize_canonical_range
# ---------------------------------------------------------------------------

class TestNormalizeCanonicalRange:
    def test_prefers_canonical_range_when_present(self):
        canonical = {"artifact_role": "canonical_md", "file_path": "a.md", "start_byte": 0, "end_byte": 10}
        fallback = {"artifact_role": "canonical_md", "file_path": "b.md", "start_byte": 0, "end_byte": 10}
        chunk = {"canonical_range": canonical, "content_range_ref": fallback}
        result = normalize_canonical_range(chunk)
        assert result is canonical

    def test_falls_back_to_content_range_ref_when_no_canonical_range(self):
        fallback = {"artifact_role": "canonical_md", "file_path": "a.md"}
        chunk = {"content_range_ref": fallback}
        result = normalize_canonical_range(chunk)
        assert result is fallback

    def test_returns_none_when_neither_present(self):
        chunk = {"chunk_id": "x"}
        assert normalize_canonical_range(chunk) is None

    def test_returns_none_when_canonical_range_wrong_role(self):
        chunk = {"canonical_range": {"artifact_role": "source_file", "file_path": "x"}}
        assert normalize_canonical_range(chunk) is None

    def test_returns_none_when_content_range_ref_wrong_role(self):
        chunk = {"content_range_ref": {"artifact_role": "index_sidecar_json", "file_path": "x"}}
        assert normalize_canonical_range(chunk) is None

    def test_does_not_fall_back_when_canonical_range_wrong_role(self):
        # canonical_range with wrong role should NOT fall back to content_range_ref
        chunk = {
            "canonical_range": {"artifact_role": "source_file"},
            "content_range_ref": {"artifact_role": "canonical_md", "file_path": "a.md"},
        }
        assert normalize_canonical_range(chunk) is None

    def test_content_range_ref_fallback_with_all_fields(self):
        crr = {
            "artifact_role": "canonical_md",
            "file_path": "merge.md",
            "start_byte": 10,
            "end_byte": 20,
            "start_line": 1,
            "end_line": 1,
            "content_sha256": "a" * 64,
        }
        chunk = {"content_range_ref": crr}
        result = normalize_canonical_range(chunk)
        assert result["start_byte"] == 10
        assert result["end_byte"] == 20


# ---------------------------------------------------------------------------
# resolve_repo_id
# ---------------------------------------------------------------------------

class TestResolveRepoId:
    def test_single_source_range_repo_id(self):
        norm_range = {"repo_id": "only_source", "file_path": "x"}
        chunk = {}
        repo_id, src = resolve_repo_id(chunk, norm_range, lineno=1)
        assert repo_id == "only_source"
        assert src == "range.repo_id"

    def test_falls_back_to_chunk_repo_when_range_absent(self):
        norm_range = {"file_path": "x"}
        chunk = {"repo": "from_chunk"}
        repo_id, src = resolve_repo_id(chunk, norm_range, lineno=1)
        assert repo_id == "from_chunk"
        assert src == "chunk.repo"

    def test_falls_back_to_search_keys_repo_id(self):
        norm_range = {"file_path": "x"}
        chunk = {"search_keys": {"repo_id": "from_sk"}}
        repo_id, src = resolve_repo_id(chunk, norm_range, lineno=1)
        assert repo_id == "from_sk"
        assert src == "search_keys.repo_id"

    def test_raises_when_no_source(self):
        norm_range = {"file_path": "x"}
        chunk = {}
        with pytest.raises(CitationMapError, match="no repo_id source"):
            resolve_repo_id(chunk, norm_range, lineno=1)

    def test_raises_on_conflicting_values(self):
        # Different values in different sources → hard error (H4)
        norm_range = {"repo_id": "repo_a"}
        chunk = {"repo": "repo_b"}
        with pytest.raises(CitationMapError, match="ambiguous repo_id"):
            resolve_repo_id(chunk, norm_range, lineno=5)

    def test_raises_on_conflict_range_vs_search_keys(self):
        norm_range = {"repo_id": "repo_x"}
        chunk = {"search_keys": {"repo_id": "repo_y"}}
        with pytest.raises(CitationMapError, match="ambiguous repo_id"):
            resolve_repo_id(chunk, norm_range, lineno=3)

    def test_no_error_when_all_sources_agree(self):
        # All present sources have the same value → ok, return highest-priority
        norm_range = {"repo_id": "lenskit"}
        chunk = {"repo": "lenskit", "search_keys": {"repo_id": "lenskit"}}
        repo_id, src = resolve_repo_id(chunk, norm_range, lineno=1)
        assert repo_id == "lenskit"
        assert src == "range.repo_id"

    def test_ignores_empty_string_sources(self):
        norm_range = {"repo_id": ""}
        chunk = {"repo": "lenskit"}
        repo_id, src = resolve_repo_id(chunk, norm_range, lineno=1)
        assert repo_id == "lenskit"
        assert src == "chunk.repo"

    def test_two_sources_same_value_no_conflict(self):
        norm_range = {"file_path": "x"}
        chunk = {"repo": "myrepo", "search_keys": {"repo_id": "myrepo"}}
        repo_id, src = resolve_repo_id(chunk, norm_range, lineno=1)
        assert repo_id == "myrepo"
        assert src == "chunk.repo"


# ---------------------------------------------------------------------------
# verify_byte_range_hash
# ---------------------------------------------------------------------------

class TestVerifyByteRangeHash:
    def test_valid_range(self):
        content = b"hello world"
        sha = _sha256(content[0:5])
        actual = verify_byte_range_hash(content, 0, 5, sha, lineno=1)
        assert actual == sha

    def test_mismatch_raises(self):
        content = b"hello world"
        with pytest.raises(CitationMapError, match="SHA256 mismatch"):
            verify_byte_range_hash(content, 0, 5, "a" * 64, lineno=1)

    def test_end_exceeds_size_raises(self):
        content = b"abc"
        sha = _sha256(content)
        with pytest.raises(CitationMapError, match="exceeds file size"):
            verify_byte_range_hash(content, 0, 100, sha, lineno=1)

    def test_end_lte_start_raises(self):
        content = b"abc"
        with pytest.raises(CitationMapError, match="end_byte"):
            verify_byte_range_hash(content, 5, 3, "a" * 64, lineno=1)

    def test_negative_start_raises(self):
        content = b"abc"
        with pytest.raises(CitationMapError, match="start_byte"):
            verify_byte_range_hash(content, -1, 2, "a" * 64, lineno=1)


# ---------------------------------------------------------------------------
# byte_range_to_line_range
# ---------------------------------------------------------------------------

class TestByteRangeToLineRange:
    def test_range_in_line_1(self):
        content = b"hello world"
        assert byte_range_to_line_range(content, 0, 5) == (1, 1)

    def test_range_in_line_2(self):
        content = b"line1\nhello world"
        # range starts at byte 6 ('h'), ends at byte 11 (exclusive)
        assert byte_range_to_line_range(content, 6, 11) == (2, 2)

    def test_range_spans_lines_2_and_3(self):
        content = b"line1\nline2\nline3"
        # range [6, 13): bytes 6-12 = "line2\nli"
        # start_byte=6 → line 2; last byte=12 ('i' in line3) → line 3
        assert byte_range_to_line_range(content, 6, 13) == (2, 3)

    def test_range_ends_on_newline_byte(self):
        # The '\n' byte terminates the line it belongs to; end_line is that line
        content = b"line1\nline2\n"
        # range [0, 6): last included byte = index 5 = '\n'
        # '\n' at 5 belongs to line 1
        assert byte_range_to_line_range(content, 0, 6) == (1, 1)

    def test_range_starts_after_newline_ends_on_next_newline(self):
        content = b"line1\nline2\nline3\n"
        # range [6, 12): bytes 6-11 = "line2\n", last byte 11 = '\n' → line 2
        assert byte_range_to_line_range(content, 6, 12) == (2, 2)

    def test_single_byte_range(self):
        content = b"x"
        assert byte_range_to_line_range(content, 0, 1) == (1, 1)

    def test_first_byte_of_second_line(self):
        content = b"\nfoo"
        # byte 0 = '\n' (line 1 terminator), byte 1 = 'f' (start of line 2)
        assert byte_range_to_line_range(content, 1, 2) == (2, 2)

    def test_whole_file_range(self):
        content = b"a\nb\nc"
        assert byte_range_to_line_range(content, 0, len(content)) == (1, 3)


# ---------------------------------------------------------------------------
# H5: input start_line/end_line are ignored; output is computed from bytes
# ---------------------------------------------------------------------------

class TestInputLineRangeIgnored:
    def test_missing_input_start_end_line_does_not_prevent_production(self, tmp_path):
        """Chunk with no start_line/end_line in range still produces a row."""
        content = b"Line one\nLine two\n"
        content_sha = _sha256(content[0:8])
        chunk = {
            "chunk_id": "c1",
            "repo": "testrepo",
            "canonical_range": {
                "artifact_role": "canonical_md",
                "repo_id": "testrepo",
                "file_path": "test_merge.md",
                "start_byte": 0,
                "end_byte": 8,
                "content_sha256": content_sha,
                # deliberately no start_line / end_line
            },
        }
        manifest_path = _make_bundle(tmp_path, content, [chunk])
        report = produce_citation_map(str(manifest_path))
        assert report["status"] == "ok", report["errors"]
        assert report["citation_map_row_count"] == 1
        row = report["sample_rows"][0]
        assert row["canonical_range"]["start_line"] == 1
        assert row["canonical_range"]["end_line"] == 1

    def test_wrong_input_line_numbers_are_not_passed_through(self, tmp_path):
        """Input start_line=99/end_line=99 must NOT appear in output."""
        content = b"Line one\nLine two\n"
        content_sha = _sha256(content[0:8])
        chunk = {
            "chunk_id": "c1",
            "repo": "testrepo",
            "canonical_range": {
                "artifact_role": "canonical_md",
                "repo_id": "testrepo",
                "file_path": "test_merge.md",
                "start_byte": 0,
                "end_byte": 8,
                "start_line": 99,  # wrong — must be ignored
                "end_line": 99,    # wrong — must be ignored
                "content_sha256": content_sha,
            },
        }
        manifest_path = _make_bundle(tmp_path, content, [chunk])
        report = produce_citation_map(str(manifest_path))
        assert report["status"] == "ok", report["errors"]
        row = report["sample_rows"][0]
        assert row["canonical_range"]["start_line"] != 99
        assert row["canonical_range"]["end_line"] != 99
        assert row["canonical_range"]["start_line"] == 1
        assert row["canonical_range"]["end_line"] == 1

    def test_output_line_numbers_match_byte_range_function(self, tmp_path):
        """Output start_line/end_line must equal byte_range_to_line_range result."""
        content = b"first\nsecond\nthird\n"
        # range in second line: bytes 6-11 = "second"
        start_byte, end_byte = 6, 12
        content_sha = _sha256(content[start_byte:end_byte])
        chunk = {
            "chunk_id": "c1",
            "repo": "testrepo",
            "canonical_range": {
                "artifact_role": "canonical_md",
                "repo_id": "testrepo",
                "file_path": "test_merge.md",
                "start_byte": start_byte,
                "end_byte": end_byte,
                "start_line": 1,   # wrong input — source-local
                "end_line": 1,     # wrong input — source-local
                "content_sha256": content_sha,
            },
        }
        manifest_path = _make_bundle(tmp_path, content, [chunk])
        report = produce_citation_map(str(manifest_path))
        assert report["status"] == "ok", report["errors"]
        row = report["sample_rows"][0]
        expected_start, expected_end = byte_range_to_line_range(content, start_byte, end_byte)
        assert row["canonical_range"]["start_line"] == expected_start
        assert row["canonical_range"]["end_line"] == expected_end


# ---------------------------------------------------------------------------
# snapshot derivation from manifest
# ---------------------------------------------------------------------------

class TestSnapshotFromManifest:
    def test_snapshot_fields_come_from_manifest(self, tmp_path):
        content = b"Hello snapshot world"
        chunk = _canonical_range_chunk(content, 0, 5, "test_merge.md")
        manifest_path = _make_bundle(tmp_path, content, [chunk])

        report = produce_citation_map(str(manifest_path))
        assert report["status"] == "ok", report["errors"]

        row = report["sample_rows"][0]
        snap = row["snapshot"]
        assert snap["run_id"] == "test-run-001"
        assert snap["canonical_md_path"] == "test_merge.md"
        assert snap["canonical_md_sha256"] == _sha256(content)

    def test_snapshot_source_is_bundle_manifest(self, tmp_path):
        content = b"snapshot source test"
        chunk = _canonical_range_chunk(content, 0, 5, "test_merge.md")
        manifest_path = _make_bundle(tmp_path, content, [chunk])
        report = produce_citation_map(str(manifest_path))
        assert report["snapshot_source"] == "bundle_manifest"


# ---------------------------------------------------------------------------
# make_citation_id is used
# ---------------------------------------------------------------------------

class TestCitationIdDerivation:
    def test_citation_id_matches_make_citation_id(self, tmp_path):
        content = b"Citation ID test content"
        chunk = _canonical_range_chunk(content, 0, 8, "test_merge.md")
        manifest_path = _make_bundle(tmp_path, content, [chunk])

        report = produce_citation_map(str(manifest_path))
        assert report["status"] == "ok", report["errors"]

        row = report["sample_rows"][0]
        canonical_sha = _sha256(content)
        slice_sha = _sha256(content[0:8])
        expected_cit_id = make_citation_id(canonical_sha, 0, 8, slice_sha)
        assert row["citation_id"] == expected_cit_id

    def test_citation_id_format(self, tmp_path):
        content = b"format test content here"
        chunk = _canonical_range_chunk(content, 0, 4, "test_merge.md")
        manifest_path = _make_bundle(tmp_path, content, [chunk])

        report = produce_citation_map(str(manifest_path))
        assert report["status"] == "ok", report["errors"]

        cit_id = report["sample_rows"][0]["citation_id"]
        assert cit_id.startswith("cit_")
        assert len(cit_id) == 20  # "cit_" + 16 hex chars


# ---------------------------------------------------------------------------
# Range normalisation: canonical_range preferred over content_range_ref
# ---------------------------------------------------------------------------

class TestRangeNormalisation:
    def test_canonical_range_preferred(self, tmp_path):
        content = b"ABCDEFGHIJ"
        canonical_sha = _sha256(content[0:5])
        fallback_sha = _sha256(content[5:10])
        chunk = {
            "chunk_id": "c1",
            "repo": "testrepo",
            "canonical_range": {
                "artifact_role": "canonical_md",
                "repo_id": "testrepo",
                "file_path": "test_merge.md",
                "start_byte": 0,
                "end_byte": 5,
                "start_line": 1,
                "end_line": 1,
                "content_sha256": canonical_sha,
            },
            "content_range_ref": {
                "artifact_role": "canonical_md",
                "repo_id": "testrepo",
                "file_path": "test_merge.md",
                "start_byte": 5,
                "end_byte": 10,
                "start_line": 2,
                "end_line": 2,
                "content_sha256": fallback_sha,
            },
        }
        manifest_path = _make_bundle(tmp_path, content, [chunk])
        report = produce_citation_map(str(manifest_path))
        assert report["status"] == "ok", report["errors"]
        row = report["sample_rows"][0]
        assert row["canonical_range"]["start_byte"] == 0
        assert row["canonical_range"]["end_byte"] == 5

    def test_content_range_ref_fallback(self, tmp_path):
        content = b"ABCDEFGHIJ"
        chunk = _content_range_ref_chunk(content, 2, 7, "test_merge.md")
        manifest_path = _make_bundle(tmp_path, content, [chunk])
        report = produce_citation_map(str(manifest_path))
        assert report["status"] == "ok", report["errors"]
        row = report["sample_rows"][0]
        assert row["canonical_range"]["start_byte"] == 2
        assert row["canonical_range"]["end_byte"] == 7

    def test_error_when_no_range(self, tmp_path):
        content = b"ABCDEFGHIJ"
        chunk = {"chunk_id": "c1", "repo": "testrepo"}
        manifest_path = _make_bundle(tmp_path, content, [chunk])
        report = produce_citation_map(str(manifest_path))
        assert report["status"] == "fail"
        assert any("no valid canonical range" in e for e in report["errors"])

    def test_error_when_canonical_range_wrong_role_no_fallback(self, tmp_path):
        content = b"ABCDEFGHIJ"
        chunk = {
            "chunk_id": "c1",
            "repo": "testrepo",
            "canonical_range": {"artifact_role": "source_file"},
        }
        manifest_path = _make_bundle(tmp_path, content, [chunk])
        report = produce_citation_map(str(manifest_path))
        assert report["status"] == "fail"


# ---------------------------------------------------------------------------
# Byte-range hash verification in producer
# ---------------------------------------------------------------------------

class TestProducerByteRangeVerification:
    def test_hash_mismatch_causes_error(self, tmp_path):
        content = b"Hello world test"
        bad_sha = "b" * 64
        chunk = {
            "chunk_id": "c1",
            "repo": "testrepo",
            "canonical_range": {
                "artifact_role": "canonical_md",
                "file_path": "test_merge.md",
                "start_byte": 0,
                "end_byte": 5,
                "start_line": 1,
                "end_line": 1,
                "content_sha256": bad_sha,
            },
        }
        manifest_path = _make_bundle(tmp_path, content, [chunk])
        report = produce_citation_map(str(manifest_path))
        assert report["status"] == "fail"
        assert any("SHA256 mismatch" in e for e in report["errors"])

    def test_valid_hash_produces_row(self, tmp_path):
        content = b"Hello world test"
        chunk = _canonical_range_chunk(content, 0, 5, "test_merge.md")
        manifest_path = _make_bundle(tmp_path, content, [chunk])
        report = produce_citation_map(str(manifest_path))
        assert report["status"] == "ok", report["errors"]
        assert report["citation_map_row_count"] == 1


# ---------------------------------------------------------------------------
# Integration: produce_citation_map correctness
# ---------------------------------------------------------------------------

class TestProduceCitationMap:
    def test_produces_valid_output_file(self, tmp_path):
        content = b"Line 1 content\nLine 2 content\n"
        chunks = [
            _canonical_range_chunk(content, 0, 14, "test_merge.md", chunk_id="c1"),
            _canonical_range_chunk(content, 15, 29, "test_merge.md", chunk_id="c2"),
        ]
        manifest_path = _make_bundle(tmp_path, content, chunks)
        report = produce_citation_map(str(manifest_path))

        assert report["status"] == "ok", report["errors"]
        assert report["chunk_count"] == 2
        assert report["citation_map_row_count"] == 2
        assert report["citation_id_count"] == 2
        assert report["citation_id_duplicate_count"] == 0

        output_path = Path(report["output_path"])
        assert output_path.exists()
        lines = [json.loads(l) for l in output_path.read_text().strip().splitlines()]
        assert len(lines) == 2
        for row in lines:
            assert "citation_id" in row
            assert "repo_id" in row
            assert "snapshot" in row
            assert "canonical_range" in row
            assert row["produced_by"] == PRODUCED_BY

    def test_no_duplicate_citation_ids(self, tmp_path):
        content = b"unique content abc"
        chunks = [
            _canonical_range_chunk(content, 0, 6, "test_merge.md", chunk_id="c1"),
            _canonical_range_chunk(content, 7, 14, "test_merge.md", chunk_id="c2"),
        ]
        manifest_path = _make_bundle(tmp_path, content, chunks)
        report = produce_citation_map(str(manifest_path))
        assert report["citation_id_duplicate_count"] == 0

    def test_sha256_mismatch_fails(self, tmp_path):
        content = b"some content"
        chunk = _canonical_range_chunk(content, 0, 4, "test_merge.md")
        manifest_path = _make_bundle(
            tmp_path, content, [chunk],
            canonical_sha_override="c" * 64,
        )
        report = produce_citation_map(str(manifest_path))
        assert report["status"] == "fail"
        assert any("SHA256 mismatch" in e for e in report["errors"])

    def test_missing_manifest_fails(self, tmp_path):
        report = produce_citation_map(str(tmp_path / "nonexistent.bundle.manifest.json"))
        assert report["status"] == "fail"
        assert report["error_kind"] == "path_read_error"

    def test_output_sha256_matches_file(self, tmp_path):
        content = b"sha256 output check"
        chunk = _canonical_range_chunk(content, 0, 6, "test_merge.md")
        manifest_path = _make_bundle(tmp_path, content, [chunk])
        report = produce_citation_map(str(manifest_path))
        assert report["status"] == "ok", report["errors"]

        output_path = Path(report["output_path"])
        actual_sha = _sha256(output_path.read_bytes())
        assert actual_sha == report["output_sha256"]

    def test_custom_output_path(self, tmp_path):
        content = b"custom output path test"
        chunk = _canonical_range_chunk(content, 0, 6, "test_merge.md")
        manifest_path = _make_bundle(tmp_path, content, [chunk])
        custom_output = str(tmp_path / "custom.citation_map.jsonl")
        report = produce_citation_map(str(manifest_path), custom_output)
        assert report["status"] == "ok", report["errors"]
        assert report["output_path"] == custom_output
        assert Path(custom_output).exists()

    def test_repo_id_source_reported(self, tmp_path):
        content = b"repo_id source test"
        chunk = _content_range_ref_chunk(content, 0, 5, "test_merge.md", repo_id="lenskit")
        manifest_path = _make_bundle(tmp_path, content, [chunk])
        report = produce_citation_map(str(manifest_path))
        assert report["status"] == "ok", report["errors"]
        assert report["repo_id_source"] == "range.repo_id"


# ---------------------------------------------------------------------------
# Integration: manifest wiring (MODULE-LEVEL registries, not inspect.getsource)
# ---------------------------------------------------------------------------

class TestManifestWiring:
    def test_citation_map_role_exists_in_constants(self):
        assert ArtifactRole.CITATION_MAP_JSONL.value == "citation_map_jsonl"

    def test_contract_registry_has_citation_map_entry(self):
        from merger.lenskit.core.merge import ARTIFACT_CONTRACT_REGISTRY
        entry = ARTIFACT_CONTRACT_REGISTRY[ArtifactRole.CITATION_MAP_JSONL]
        assert entry["id"] == "citation-map"
        assert entry["version"] == "v1"

    def test_authority_registry_has_citation_map_entry(self):
        from merger.lenskit.core.merge import ARTIFACT_AUTHORITY_REGISTRY
        entry = ARTIFACT_AUTHORITY_REGISTRY[ArtifactRole.CITATION_MAP_JSONL]
        assert entry["authority"] == "navigation_index"
        assert entry["canonicality"] == "derived"
        assert entry["regenerable"] is True
        assert entry["staleness_sensitive"] is True

    def test_citation_map_not_canonical_content(self):
        from merger.lenskit.core.merge import ARTIFACT_AUTHORITY_REGISTRY
        entry = ARTIFACT_AUTHORITY_REGISTRY[ArtifactRole.CITATION_MAP_JSONL]
        assert entry["authority"] != "canonical_content"
        assert entry["canonicality"] != "content_source"

    def test_citation_map_artifact_file_sha_and_bytes(self, tmp_path):
        """Produce a citation map and verify sha256 / bytes match the file on disk."""
        import hashlib

        content = b"Manifest wiring test content"
        chunk = _canonical_range_chunk(content, 0, 7, "test_merge.md")
        manifest_path = _make_bundle(tmp_path, content, [chunk])
        report = produce_citation_map(str(manifest_path))
        assert report["status"] == "ok", report["errors"]

        output_path = Path(report["output_path"])
        assert output_path.exists()

        output_bytes = output_path.read_bytes()
        actual_sha = hashlib.sha256(output_bytes).hexdigest()

        assert actual_sha == report["output_sha256"]
        assert report["output_bytes"] == len(output_bytes)


# ---------------------------------------------------------------------------
# A: Zero-row run writes empty artifact
# ---------------------------------------------------------------------------

class TestEmptyChunkIndex:
    def test_empty_chunk_index_writes_empty_file(self, tmp_path):
        content = b"some canonical content"
        manifest_path = _make_bundle(tmp_path, content, [])
        report = produce_citation_map(str(manifest_path))

        assert report["status"] == "ok", report["errors"]
        assert report["citation_map_row_count"] == 0
        assert report["chunk_count"] == 0
        assert report["output_bytes"] == 0
        assert report["output_sha256"] == _sha256(b"")
        assert report["output_path"] is not None
        assert Path(report["output_path"]).exists()
        assert Path(report["output_path"]).read_bytes() == b""

    def test_blank_lines_only_chunk_index_writes_empty_file(self, tmp_path):
        content = b"canonical content"
        # Build a manifest but then overwrite chunk_index with blank lines only
        manifest_path = _make_bundle(tmp_path, content, [])
        # Rewrite chunk_index with whitespace lines and update manifest SHA
        chunk_index_path = tmp_path / "test_merge.chunk_index.jsonl"
        blank_bytes = b"\n\n   \n"
        chunk_index_path.write_bytes(blank_bytes)

        # Update manifest so SHA matches
        manifest = json.loads((tmp_path / "test_merge.bundle.manifest.json").read_text())
        for art in manifest["artifacts"]:
            if art["role"] == "chunk_index_jsonl":
                art["sha256"] = _sha256(blank_bytes)
                art["bytes"] = len(blank_bytes)
        (tmp_path / "test_merge.bundle.manifest.json").write_text(json.dumps(manifest))

        report = produce_citation_map(str(manifest_path))

        assert report["status"] == "ok", report["errors"]
        assert report["citation_map_row_count"] == 0
        assert report["output_bytes"] == 0
        assert report["output_sha256"] == _sha256(b"")
        assert Path(report["output_path"]).read_bytes() == b""


# ---------------------------------------------------------------------------
# B: Stale output removed on fail rerun
# ---------------------------------------------------------------------------

class TestStaleOutputCleanup:
    def test_stale_output_removed_on_fail_rerun(self, tmp_path):
        content = b"Valid content for first run\nSecond line here\n"
        valid_chunk = _canonical_range_chunk(content, 0, 5, "test_merge.md", chunk_id="c1")

        # First run: success — output file is created
        manifest_path = _make_bundle(tmp_path, content, [valid_chunk])
        report1 = produce_citation_map(str(manifest_path))
        assert report1["status"] == "ok", report1["errors"]
        output_path = Path(report1["output_path"])
        assert output_path.exists()

        # Modify chunk_index to introduce an error (bad SHA), keeping manifest consistent
        bad_sha = "b" * 64
        invalid_chunk = {
            "chunk_id": "c2",
            "repo": "testrepo",
            "canonical_range": {
                "artifact_role": "canonical_md",
                "file_path": "test_merge.md",
                "start_byte": 6,
                "end_byte": 11,
                "content_sha256": bad_sha,
            },
        }
        chunk_lines = json.dumps(invalid_chunk) + "\n"
        chunk_index_bytes = chunk_lines.encode("utf-8")
        (tmp_path / "test_merge.chunk_index.jsonl").write_bytes(chunk_index_bytes)

        # Update manifest SHA to match new chunk_index
        manifest = json.loads((tmp_path / "test_merge.bundle.manifest.json").read_text())
        for art in manifest["artifacts"]:
            if art["role"] == "chunk_index_jsonl":
                art["sha256"] = _sha256(chunk_index_bytes)
                art["bytes"] = len(chunk_index_bytes)
        (tmp_path / "test_merge.bundle.manifest.json").write_text(json.dumps(manifest))

        # Second run: fail — stale output must be removed
        report2 = produce_citation_map(str(manifest_path))
        assert report2["status"] == "fail"
        assert report2["output_path"] is None
        assert report2["citation_map_row_count"] == 0
        assert not output_path.exists(), "Stale output from first run must be removed"


# ---------------------------------------------------------------------------
# B (extended): Stale cleanup on early failures (SHA mismatch, bad run_id)
# ---------------------------------------------------------------------------

class TestEarlyFailStaleCleanup:
    def test_canonical_md_sha_mismatch_removes_stale_output(self, tmp_path):
        content = b"First run content\nWith two lines\n"
        chunk = _canonical_range_chunk(content, 0, 5, "test_merge.md")
        manifest_path = _make_bundle(tmp_path, content, [chunk])

        # First run succeeds and writes output.
        report1 = produce_citation_map(str(manifest_path))
        assert report1["status"] == "ok", report1["errors"]
        stale_path = Path(report1["output_path"])
        assert stale_path.exists()

        # Tamper canonical_md bytes so its SHA no longer matches the manifest.
        (tmp_path / "test_merge.md").write_bytes(b"tampered")

        # Second run: SHA mismatch → fail; stale output must be removed.
        report2 = produce_citation_map(str(manifest_path))
        assert report2["status"] == "fail"
        assert any("SHA256 mismatch" in e for e in report2["errors"])
        assert report2["output_path"] is None
        assert not stale_path.exists(), "Stale output must be removed on canonical_md SHA mismatch"

    def test_chunk_index_sha_mismatch_removes_stale_output(self, tmp_path):
        content = b"Content for chunk index SHA test\n"
        chunk = _canonical_range_chunk(content, 0, 7, "test_merge.md")
        manifest_path = _make_bundle(tmp_path, content, [chunk])

        # First run succeeds.
        report1 = produce_citation_map(str(manifest_path))
        assert report1["status"] == "ok", report1["errors"]
        stale_path = Path(report1["output_path"])
        assert stale_path.exists()

        # Tamper chunk_index so its SHA no longer matches the manifest.
        (tmp_path / "test_merge.chunk_index.jsonl").write_bytes(b"tampered chunk index\n")

        # Second run: chunk_index SHA mismatch → fail; stale output must be removed.
        report2 = produce_citation_map(str(manifest_path))
        assert report2["status"] == "fail"
        assert any("SHA256 mismatch" in e for e in report2["errors"])
        assert report2["output_path"] is None
        assert not stale_path.exists(), "Stale output must be removed on chunk_index SHA mismatch"

    def test_cleanup_failure_reported_in_errors(self, tmp_path):
        from unittest.mock import patch as mock_patch

        content = b"Content for cleanup failure test\n"
        chunk = _canonical_range_chunk(content, 0, 7, "test_merge.md")
        manifest_path = _make_bundle(tmp_path, content, [chunk])

        # First run succeeds.
        report1 = produce_citation_map(str(manifest_path))
        assert report1["status"] == "ok", report1["errors"]

        # Tamper canonical_md to trigger SHA mismatch on second run.
        (tmp_path / "test_merge.md").write_bytes(b"tampered")

        # Simulate unlink permission failure.
        with mock_patch.object(Path, "unlink", side_effect=OSError("Permission denied (mocked)")):
            report2 = produce_citation_map(str(manifest_path))

        assert report2["status"] == "fail"
        assert report2["output_path"] is None
        assert any("Could not remove stale output" in e for e in report2["errors"])


# ---------------------------------------------------------------------------
# D: snapshot_source precision
# ---------------------------------------------------------------------------

class TestSnapshotSource:
    def test_snapshot_source_none_on_missing_manifest(self, tmp_path):
        report = produce_citation_map(str(tmp_path / "nonexistent.bundle.manifest.json"))
        assert report["status"] == "fail"
        assert report["snapshot_source"] is None

    def test_snapshot_source_bundle_manifest_on_success(self, tmp_path):
        content = b"snapshot source test"
        chunk = _canonical_range_chunk(content, 0, 7, "test_merge.md")
        manifest_path = _make_bundle(tmp_path, content, [chunk])
        report = produce_citation_map(str(manifest_path))
        assert report["status"] == "ok", report["errors"]
        assert report["snapshot_source"] == "bundle_manifest"


# ---------------------------------------------------------------------------
# Hardening: H1 — no partial output on errors
# ---------------------------------------------------------------------------

class TestNoPartialOutputOnErrors:
    def test_no_output_file_when_chunk_errors_exist(self, tmp_path):
        content = b"Valid and invalid chunks"
        valid_chunk = _canonical_range_chunk(content, 0, 5, "test_merge.md", chunk_id="c1")
        bad_sha = "b" * 64
        invalid_chunk = {
            "chunk_id": "c2",
            "repo": "testrepo",
            "canonical_range": {
                "artifact_role": "canonical_md",
                "file_path": "test_merge.md",
                "start_byte": 6,
                "end_byte": 11,
                "start_line": 1,
                "end_line": 1,
                "content_sha256": bad_sha,  # wrong hash → error
            },
        }
        manifest_path = _make_bundle(tmp_path, content, [valid_chunk, invalid_chunk])
        expected_output = tmp_path / "test_merge.citation_map.jsonl"

        report = produce_citation_map(str(manifest_path))

        assert report["status"] == "fail"
        assert not expected_output.exists(), "Partial output must not be written on failure"
        assert report["output_path"] is None
        assert report["output_sha256"] is None
        assert report["citation_map_row_count"] == 0, "No rows written means count must be 0"

    def test_no_output_on_duplicate_citation_id(self, tmp_path):
        content = b"Duplicate test content XYZ"
        # Two chunks with identical byte ranges → same citation_id → duplicate
        chunk_a = _canonical_range_chunk(content, 0, 5, "test_merge.md", chunk_id="c1")
        chunk_b = _canonical_range_chunk(content, 0, 5, "test_merge.md", chunk_id="c2")
        manifest_path = _make_bundle(tmp_path, content, [chunk_a, chunk_b])
        expected_output = tmp_path / "test_merge.citation_map.jsonl"

        report = produce_citation_map(str(manifest_path))

        assert report["status"] == "fail"
        assert any("duplicate" in e for e in report["errors"])
        assert not expected_output.exists()

    def test_output_path_is_none_on_fail(self, tmp_path):
        content = b"test"
        invalid_chunk = {"chunk_id": "c1", "repo": "r"}  # no range
        manifest_path = _make_bundle(tmp_path, content, [invalid_chunk])
        report = produce_citation_map(str(manifest_path))
        assert report["status"] == "fail"
        assert report["output_path"] is None


# ---------------------------------------------------------------------------
# Hardening: H2 — default output path safety
# ---------------------------------------------------------------------------

class TestDefaultOutputPathSafety:
    def test_standard_manifest_name_produces_correct_path(self, tmp_path):
        content = b"path safety test"
        chunk = _canonical_range_chunk(content, 0, 4, "test_merge.md")
        manifest_path = _make_bundle(tmp_path, content, [chunk])
        report = produce_citation_map(str(manifest_path))
        assert report["status"] == "ok", report["errors"]
        assert report["output_path"] == str(tmp_path / "test_merge.citation_map.jsonl")

    def test_non_standard_manifest_name_fails_safely(self, tmp_path):
        # Manifest doesn't end with .bundle.manifest.json → cannot derive safe output path
        content = b"path safety test"
        chunk = _canonical_range_chunk(content, 0, 4, "test_merge.md")
        manifest_path = _make_bundle(tmp_path, content, [chunk])

        # Rename manifest to a non-standard name
        bad_manifest = tmp_path / "manifest.json"
        manifest_path.rename(bad_manifest)

        # Also fix the manifest content to not reference the standard name
        # (re-write with all paths intact — the manifest content itself doesn't need to change
        # because _default_output_path checks the manifest file's own name)
        report = produce_citation_map(str(bad_manifest))
        assert report["status"] == "fail"
        assert any("cannot derive safe output path" in e.lower() or
                   "bundle.manifest.json" in e for e in report["errors"])
        # Must not create a file named "manifest.json" (collision)
        assert not (tmp_path / "manifest.json.citation_map.jsonl").exists()

    def test_output_does_not_collide_with_manifest(self, tmp_path):
        content = b"collision test"
        chunk = _canonical_range_chunk(content, 0, 4, "test_merge.md")
        manifest_path = _make_bundle(tmp_path, content, [chunk])
        # Explicitly pass manifest path as output → must fail
        report = produce_citation_map(str(manifest_path), str(manifest_path))
        assert report["status"] == "fail"
        assert any("collides" in e for e in report["errors"])

    def test_output_does_not_collide_with_canonical_md(self, tmp_path):
        content = b"collision test 2"
        chunk = _canonical_range_chunk(content, 0, 4, "test_merge.md")
        manifest_path = _make_bundle(tmp_path, content, [chunk])
        canonical_md = tmp_path / "test_merge.md"
        report = produce_citation_map(str(manifest_path), str(canonical_md))
        assert report["status"] == "fail"
        assert any("collides" in e for e in report["errors"])


# ---------------------------------------------------------------------------
# Hardening: H3 — run_id must be non-empty
# ---------------------------------------------------------------------------

class TestRunIdValidation:
    def _make_bundle_no_run_id(self, tmp_path, canonical_content, chunks, run_id_value):
        canonical_md_path = tmp_path / "test_merge.md"
        canonical_md_path.write_bytes(canonical_content)
        chunk_lines = "\n".join(json.dumps(c) for c in chunks) + "\n"
        chunk_index_bytes = chunk_lines.encode("utf-8")
        chunk_index_path = tmp_path / "test_merge.chunk_index.jsonl"
        chunk_index_path.write_bytes(chunk_index_bytes)
        manifest = {
            "kind": "repolens.bundle.manifest",
            "version": "1.0",
            "created_at": "2026-05-14T00:00:00Z",
            "generator": {"name": "test", "version": "0.0.1", "config_sha256": "a" * 64},
            "artifacts": [
                {
                    "role": "canonical_md",
                    "path": "test_merge.md",
                    "content_type": "text/markdown",
                    "bytes": len(canonical_content),
                    "sha256": _sha256(canonical_content),
                    "interpretation": {"mode": "role_only"},
                },
                {
                    "role": "chunk_index_jsonl",
                    "path": "test_merge.chunk_index.jsonl",
                    "content_type": "application/x-ndjson",
                    "bytes": len(chunk_index_bytes),
                    "sha256": _sha256(chunk_index_bytes),
                    "interpretation": {"mode": "role_only"},
                },
            ],
            "links": {},
            "capabilities": {},
        }
        if run_id_value is not None:
            manifest["run_id"] = run_id_value
        manifest_path = tmp_path / "test_merge.bundle.manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        return manifest_path

    def test_missing_run_id_fails(self, tmp_path):
        content = b"run_id test"
        chunk = _canonical_range_chunk(content, 0, 5, "test_merge.md")
        manifest_path = self._make_bundle_no_run_id(tmp_path, content, [chunk], None)
        report = produce_citation_map(str(manifest_path))
        assert report["status"] == "fail"
        assert any("run_id" in e for e in report["errors"])

    def test_empty_run_id_fails(self, tmp_path):
        content = b"run_id test"
        chunk = _canonical_range_chunk(content, 0, 5, "test_merge.md")
        manifest_path = self._make_bundle_no_run_id(tmp_path, content, [chunk], "")
        report = produce_citation_map(str(manifest_path))
        assert report["status"] == "fail"
        assert any("run_id" in e for e in report["errors"])

    def test_valid_run_id_succeeds(self, tmp_path):
        content = b"run_id valid test"
        chunk = _canonical_range_chunk(content, 0, 5, "test_merge.md")
        manifest_path = self._make_bundle_no_run_id(tmp_path, content, [chunk], "valid-run-123")
        report = produce_citation_map(str(manifest_path))
        assert report["status"] == "ok", report["errors"]


# ---------------------------------------------------------------------------
# Explicit --output protection before artifact resolution
# ---------------------------------------------------------------------------

class TestExplicitOutputProtectionBeforeArtifactResolution:
    def test_bad_run_id_does_not_delete_explicit_output(self, tmp_path):
        """Explicit --output must survive early fail before artifact paths are in protected_paths."""
        canonical_md = tmp_path / "test_merge.md"
        canonical_md.write_bytes(b"canonical content\n")
        chunk_index = tmp_path / "test_merge.chunk_index.jsonl"
        chunk_index.write_bytes(b"")

        manifest = {
            "run_id": "",  # triggers early fail before canonical_md is resolved
            "artifacts": [
                {
                    "role": "canonical_md",
                    "path": "test_merge.md",
                    "sha256": _sha256(b"canonical content\n"),
                },
                {
                    "role": "chunk_index_jsonl",
                    "path": "test_merge.chunk_index.jsonl",
                    "sha256": _sha256(b""),
                },
            ],
        }
        manifest_path = tmp_path / "test_merge.bundle.manifest.json"
        manifest_path.write_text(json.dumps(manifest))

        report = produce_citation_map(str(manifest_path), output_path_str=str(canonical_md))
        assert report["status"] == "fail"
        assert any("run_id" in e for e in report["errors"])
        assert canonical_md.exists(), (
            "Explicit --output must not be deleted before artifact protection is complete"
        )
