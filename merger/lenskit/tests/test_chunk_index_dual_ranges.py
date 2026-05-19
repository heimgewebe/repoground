"""
Integration tests for chunk_index dual-range fields.

Tests verify that generate_chunk_artifacts (via write_reports_v2) emits:
  - legacy content_range_ref  (for chunks in canonical_md)
  - canonical_range            (for chunks in canonical_md, with computed line numbers)
  - source_range               (for ALL chunks, always with status)

All tests operate against real write_reports_v2 output, not a re-implemented
proxy of the production logic.
"""

import hashlib
import json

import pytest

from merger.lenskit.tests._test_constants import make_generator_info
from merger.lenskit.core.merge import write_reports_v2, scan_repo, ExtrasConfig


# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------

@pytest.fixture()
def dual_range_artifacts(tmp_path):
    """
    Run write_reports_v2 in dual mode over a small repository and return
    (artifacts, chunks, canonical_md_bytes).
    """
    hub = tmp_path / "hub"
    hub.mkdir()
    repo_root = hub / "testrepo"
    repo_root.mkdir()

    (repo_root / "src").mkdir()
    (repo_root / "src" / "hello.py").write_text(
        "def hello():\n    return 42\n\ndef world():\n    return 0\n",
        encoding="utf-8",
    )

    merges_dir = tmp_path / "merges"
    merges_dir.mkdir()

    summary = scan_repo(repo_root, calculate_md5=True)
    extras = ExtrasConfig(json_sidecar=False)

    artifacts = write_reports_v2(
        merges_dir=merges_dir,
        hub=hub,
        repo_summaries=[summary],
        detail="max",
        mode="gesamt",
        max_bytes=0,
        plan_only=False,
        output_mode="dual",
        extras=extras,
        redact_secrets=False,
        generator_info=make_generator_info(),
    )

    assert artifacts.chunk_index and artifacts.chunk_index.exists(), (
        "chunk_index not produced"
    )
    assert artifacts.canonical_md and artifacts.canonical_md.exists(), (
        "canonical_md not produced"
    )

    with artifacts.chunk_index.open(encoding="utf-8") as f:
        chunks = [json.loads(line) for line in f if line.strip()]

    canonical_md_bytes = artifacts.canonical_md.read_bytes()

    return artifacts, chunks, canonical_md_bytes


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_content_range_ref_legacy_still_present(dual_range_artifacts):
    """Legacy content_range_ref must be emitted for chunks in canonical_md."""
    _, chunks, _ = dual_range_artifacts
    assert len(chunks) > 0, "no chunks produced"
    chunks_with_ref = [c for c in chunks if "content_range_ref" in c]
    assert len(chunks_with_ref) > 0, (
        "at least one chunk must have content_range_ref"
    )


def test_chunk_index_emits_canonical_range_from_content_range_ref(dual_range_artifacts):
    """Every chunk that has content_range_ref must also have canonical_range."""
    _, chunks, _ = dual_range_artifacts
    for c in chunks:
        if "content_range_ref" in c:
            assert "canonical_range" in c, (
                f"chunk {c.get('chunk_id')} has content_range_ref but no canonical_range"
            )


def test_canonical_range_count_equals_content_range_ref_count(dual_range_artifacts):
    """canonical_range count must equal content_range_ref count."""
    _, chunks, _ = dual_range_artifacts
    n_ref = sum(1 for c in chunks if "content_range_ref" in c)
    n_cr = sum(1 for c in chunks if "canonical_range" in c)
    assert n_ref == n_cr, (
        f"canonical_range count ({n_cr}) != content_range_ref count ({n_ref})"
    )


def test_canonical_range_hash_roundtrip(dual_range_artifacts):
    """canonical_range.content_sha256 must match actual canonical_md bytes at [start:end]."""
    _, chunks, canonical_md_bytes = dual_range_artifacts
    for c in chunks:
        if "canonical_range" not in c:
            continue
        cr = c["canonical_range"]
        actual_bytes = canonical_md_bytes[cr["start_byte"]:cr["end_byte"]]
        expected_sha = hashlib.sha256(actual_bytes).hexdigest()
        assert cr["content_sha256"] == expected_sha, (
            f"canonical_range.content_sha256 roundtrip failed for chunk {c.get('chunk_id')}"
        )


def test_content_range_ref_is_canonical_consistent(dual_range_artifacts):
    """
    content_range_ref must carry canonical-md-local line numbers and hash,
    not source-file-local values.  It must agree with canonical_range on all
    positional fields and the SHA256 must roundtrip against canonical_md bytes.
    """
    _, chunks, canonical_md_bytes = dual_range_artifacts
    chunks_with_both = [c for c in chunks if "content_range_ref" in c and "canonical_range" in c]
    assert len(chunks_with_both) > 0, "need at least one chunk with both fields for this test"

    for c in chunks_with_both:
        crr = c["content_range_ref"]
        cr = c["canonical_range"]

        assert crr["start_line"] == cr["start_line"], (
            f"content_range_ref.start_line ({crr['start_line']}) != "
            f"canonical_range.start_line ({cr['start_line']}) for chunk {c.get('chunk_id')}"
        )
        assert crr["end_line"] == cr["end_line"], (
            f"content_range_ref.end_line ({crr['end_line']}) != "
            f"canonical_range.end_line ({cr['end_line']}) for chunk {c.get('chunk_id')}"
        )
        assert crr["content_sha256"] == cr["content_sha256"], (
            f"content_range_ref.content_sha256 != canonical_range.content_sha256 "
            f"for chunk {c.get('chunk_id')}"
        )

        # SHA256 must also roundtrip against the actual canonical_md bytes
        actual_bytes = canonical_md_bytes[crr["start_byte"]:crr["end_byte"]]
        expected_sha = hashlib.sha256(actual_bytes).hexdigest()
        assert crr["content_sha256"] == expected_sha, (
            f"content_range_ref.content_sha256 roundtrip failed for chunk {c.get('chunk_id')}"
        )


def test_canonical_range_lines_are_canonical_md_lines(dual_range_artifacts):
    """
    canonical_range start_line/end_line must be computed from canonical_md byte
    positions, not copied from source-file line numbers.
    """
    _, chunks, canonical_md_bytes = dual_range_artifacts
    for c in chunks:
        if "canonical_range" not in c:
            continue
        cr = c["canonical_range"]
        abs_start = cr["start_byte"]
        abs_end = cr["end_byte"]
        expected_start_line = canonical_md_bytes.count(b"\n", 0, abs_start) + 1
        # end_byte is exclusive; clamp to abs_start to handle zero-length chunks
        expected_end_line = canonical_md_bytes.count(b"\n", 0, max(abs_start, abs_end - 1)) + 1
        assert cr["start_line"] == expected_start_line, (
            f"canonical_range.start_line mismatch for chunk {c.get('chunk_id')}: "
            f"expected {expected_start_line}, got {cr['start_line']}"
        )
        assert cr["end_line"] == expected_end_line, (
            f"canonical_range.end_line mismatch for chunk {c.get('chunk_id')}: "
            f"expected {expected_end_line}, got {cr['end_line']}"
        )


def test_source_range_declared_has_hash_for_non_redacted_content(dual_range_artifacts):
    """Non-redacted chunks must have source_range.status == 'declared' with content_sha256."""
    _, chunks, _ = dual_range_artifacts
    assert len(chunks) > 0, "no chunks produced"
    for c in chunks:
        sr = c["source_range"]
        assert sr["status"] == "declared", (
            f"expected status='declared', got '{sr['status']}'"
        )
        assert "content_sha256" in sr, (
            "source_range must carry content_sha256 when status is 'declared'"
        )
        # Coordinates must be present for declared ranges
        for field in ("start_byte", "end_byte", "start_line", "end_line"):
            assert field in sr, f"source_range.{field} missing for 'declared' chunk"


def test_source_range_unavailable_when_redacted(tmp_path):
    """
    Redacted chunks must have source_range.status == 'unavailable' and no content_sha256.

    The test writes a file whose content matches a known Redactor pattern and
    verifies both that the canonical_md was actually redacted (proving the
    redaction path was taken) and that source_range reflects this.
    """
    hub = tmp_path / "hub"
    hub.mkdir()
    repo_root = hub / "testrepo"
    repo_root.mkdir()

    # Build key name and value dynamically to avoid triggering static secret scanners.
    # The value must match the Redactor api_key pattern: [\w-]{20,}
    secret_key = "api" + "_" + "key"
    secret_value = "A" * 22  # 22 word chars, satisfies [\w-]{20,}
    (repo_root / "config.py").write_text(
        f'{secret_key} = "{secret_value}"\ndef setup(): pass\n',
        encoding="utf-8",
    )

    merges_dir = tmp_path / "merges"
    merges_dir.mkdir()

    summary = scan_repo(repo_root, calculate_md5=True)
    extras = ExtrasConfig(json_sidecar=False)

    artifacts = write_reports_v2(
        merges_dir=merges_dir,
        hub=hub,
        repo_summaries=[summary],
        detail="max",
        mode="gesamt",
        max_bytes=0,
        plan_only=False,
        output_mode="dual",
        extras=extras,
        redact_secrets=True,
        generator_info=make_generator_info(),
    )

    assert artifacts.canonical_md and artifacts.canonical_md.exists()
    assert artifacts.chunk_index and artifacts.chunk_index.exists()

    # Verify the canonical_md actually contains the redaction marker (proves the
    # redaction path was truly taken, not just assumed).
    canonical_text = artifacts.canonical_md.read_text(encoding="utf-8")
    assert secret_value not in canonical_text, "secret leaked into canonical_md"
    assert "[REDACTED]" in canonical_text, "redaction marker missing from canonical_md"

    with artifacts.chunk_index.open(encoding="utf-8") as f:
        chunks = [json.loads(line) for line in f if line.strip()]

    assert len(chunks) > 0, "no chunks produced"
    for c in chunks:
        sr = c["source_range"]
        assert sr["status"] == "unavailable", (
            f"expected status='unavailable' for redacted chunk, got '{sr['status']}'"
        )
        assert "content_sha256" not in sr, (
            "redacted source_range must NOT carry content_sha256"
        )


def test_citation_map_jsonl_emitted(dual_range_artifacts):
    """Dual-range bundle runs must emit citation_map_jsonl alongside the manifest."""
    artifacts, _, _ = dual_range_artifacts
    assert artifacts.bundle_manifest is not None
    manifest = json.loads(artifacts.bundle_manifest.read_text(encoding="utf-8"))
    roles = {artifact["role"] for artifact in manifest["artifacts"]}
    assert "citation_map_jsonl" in roles

    merges_dir = artifacts.chunk_index.parent
    citation_files = list(merges_dir.rglob("*.citation_map.jsonl"))
    assert len(citation_files) == 1, (
        f"citation_map_jsonl must be emitted exactly once; found: {citation_files}"
    )
    assert citation_files[0].exists()
