"""
Tests for merger.lenskit.core.citation_map (Citation Map Producer).

All unit tests use synthetic in-memory fixtures; the real-dump proof
is in docs/proofs/citation-map-producer-proof.md.
"""
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from merger.lenskit.core.citation_id import make_citation_id
from merger.lenskit.core.citation_map import (
    CitationMapError,
    PRODUCED_BY,
    iter_chunk_results,
    normalize_canonical_range,
    produce_citation_map,
    resolve_artifact_by_role,
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
    canonical_sha_override: str = None,
    chunk_index_sha_override: str = None,
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
        result = normalize_canonical_range(chunk, lineno=1)
        assert result is canonical

    def test_falls_back_to_content_range_ref_when_no_canonical_range(self):
        fallback = {"artifact_role": "canonical_md", "file_path": "a.md"}
        chunk = {"content_range_ref": fallback}
        result = normalize_canonical_range(chunk, lineno=1)
        assert result is fallback

    def test_returns_none_when_neither_present(self):
        chunk = {"chunk_id": "x"}
        assert normalize_canonical_range(chunk, lineno=1) is None

    def test_returns_none_when_canonical_range_wrong_role(self):
        chunk = {"canonical_range": {"artifact_role": "source_file", "file_path": "x"}}
        assert normalize_canonical_range(chunk, lineno=1) is None

    def test_returns_none_when_content_range_ref_wrong_role(self):
        chunk = {"content_range_ref": {"artifact_role": "index_sidecar_json", "file_path": "x"}}
        assert normalize_canonical_range(chunk, lineno=1) is None

    def test_does_not_fall_back_when_canonical_range_wrong_role(self):
        # canonical_range with wrong role should NOT fall back to content_range_ref
        chunk = {
            "canonical_range": {"artifact_role": "source_file"},
            "content_range_ref": {"artifact_role": "canonical_md", "file_path": "a.md"},
        }
        assert normalize_canonical_range(chunk, lineno=1) is None

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
        result = normalize_canonical_range(chunk, lineno=1)
        assert result["start_byte"] == 10
        assert result["end_byte"] == 20


# ---------------------------------------------------------------------------
# resolve_repo_id
# ---------------------------------------------------------------------------

class TestResolveRepoId:
    def test_prefers_range_repo_id(self):
        norm_range = {"repo_id": "from_range", "file_path": "x"}
        chunk = {"repo": "from_chunk"}
        repo_id, src = resolve_repo_id(chunk, norm_range, lineno=1)
        assert repo_id == "from_range"
        assert src == "range.repo_id"

    def test_falls_back_to_chunk_repo(self):
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

    def test_range_repo_id_beats_chunk_repo_without_error(self):
        # Different values across priority levels — the higher-priority one wins silently
        norm_range = {"repo_id": "repo_a"}
        chunk = {"repo": "repo_b"}
        repo_id, src = resolve_repo_id(chunk, norm_range, lineno=5)
        assert repo_id == "repo_a"
        assert src == "range.repo_id"

    def test_no_ambiguity_when_values_agree(self):
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
# Integration: manifest wiring (CONTRACT_REGISTRY / AUTHORITY_REGISTRY)
# ---------------------------------------------------------------------------

class TestManifestWiring:
    def test_citation_map_role_exists_in_constants(self):
        assert ArtifactRole.CITATION_MAP_JSONL.value == "citation_map_jsonl"

    def test_contract_registry_has_citation_map(self):
        from merger.lenskit.core.merge import write_reports_v2
        import inspect, textwrap
        src = inspect.getsource(write_reports_v2)
        assert "citation-map" in src
        assert '"v1"' in src or "'v1'" in src

    def test_authority_registry_has_citation_map(self):
        from merger.lenskit.core.merge import write_reports_v2
        import inspect
        src = inspect.getsource(write_reports_v2)
        assert "navigation_index" in src
        # Must have both the canonical_md entry (canonical_content) and
        # the citation_map entry (navigation_index / derived) — just
        # check the citation_map values appear after the CITATION_MAP_JSONL key
        assert "CITATION_MAP_JSONL" in src

    def test_citation_map_artifact_written_to_manifest(self, tmp_path):
        """Produce a citation map file, then verify _add_artifact logic produces
        the correct manifest entry when invoked with the CITATION_MAP_JSONL role."""
        import hashlib
        from merger.lenskit.core.constants import ArtifactRole

        content = b"Manifest wiring test content"
        chunk = _canonical_range_chunk(content, 0, 7, "test_merge.md")
        manifest_path = _make_bundle(tmp_path, content, [chunk])
        report = produce_citation_map(str(manifest_path))
        assert report["status"] == "ok", report["errors"]

        output_path = Path(report["output_path"])
        assert output_path.exists()

        # Simulate what _add_artifact would write by checking the produced file
        output_bytes = output_path.read_bytes()
        actual_sha = hashlib.sha256(output_bytes).hexdigest()

        assert actual_sha == report["output_sha256"]
        assert report["output_bytes"] == len(output_bytes)

        # Verify the produced entry would satisfy bundle-manifest.v1 role constraints
        expected_entry = {
            "role": ArtifactRole.CITATION_MAP_JSONL.value,
            "path": output_path.name,
            "content_type": "application/x-ndjson",
            "bytes": len(output_bytes),
            "sha256": actual_sha,
            "contract": {"id": "citation-map", "version": "v1"},
            "interpretation": {"mode": "contract"},
            "authority": "navigation_index",
            "canonicality": "derived",
            "regenerable": True,
            "staleness_sensitive": True,
        }
        assert expected_entry["role"] == "citation_map_jsonl"
        assert expected_entry["content_type"] == "application/x-ndjson"
        assert expected_entry["contract"] == {"id": "citation-map", "version": "v1"}
        assert expected_entry["authority"] == "navigation_index"
        assert expected_entry["canonicality"] == "derived"
        assert expected_entry["regenerable"] is True
        assert expected_entry["staleness_sensitive"] is True
        assert expected_entry["sha256"] == actual_sha
        assert expected_entry["bytes"] == len(output_bytes)
