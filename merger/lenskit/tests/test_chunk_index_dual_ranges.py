"""
Tests for dual-range emission in chunk_index_jsonl:
  canonical_range and source_range alongside legacy content_range_ref.
"""
import json
import hashlib
from pathlib import Path

from merger.lenskit.core.merge import write_reports_v2, FileInfo


def _run_single_file_dual(tmp_path, content="def hello():\n    pass\n", fname="test.py"):
    hub_path = tmp_path / "hub"
    hub_path.mkdir()
    merges_dir = tmp_path / "merges"
    merges_dir.mkdir()

    repo_dir = hub_path / "r1"
    repo_dir.mkdir()
    fpath = repo_dir / fname
    fpath.write_text(content, encoding="utf-8")

    fi = FileInfo(
        root_label="r1",
        abs_path=fpath,
        rel_path=Path(fname),
        size=fpath.stat().st_size,
        is_text=True,
        md5="dummy",
        category="source",
        tags=[],
        ext=Path(fname).suffix
    )

    res = write_reports_v2(
        merges_dir=merges_dir,
        hub=hub_path,
        repo_summaries=[{"name": "r1", "root": repo_dir, "files": [fi]}],
        detail="dev",
        mode="single",
        max_bytes=10000,
        plan_only=False,
        output_mode="dual"
    )

    chunks = []
    with res.chunk_index.open() as f:
        for line in f:
            chunks.append(json.loads(line))

    return res, chunks


def test_content_range_ref_legacy_still_present(tmp_path):
    """content_range_ref must still be present after dual-range addition."""
    _, chunks = _run_single_file_dual(tmp_path)
    assert len(chunks) == 1
    chunk = chunks[0]
    assert "content_range_ref" in chunk
    ref = chunk["content_range_ref"]
    assert ref["artifact_role"] == "canonical_md"
    assert "file_path" in ref
    assert "start_byte" in ref
    assert "end_byte" in ref
    assert "content_sha256" in ref


def test_chunk_index_emits_canonical_range_from_content_range_ref(tmp_path):
    """canonical_range must be present when content_range_ref references canonical_md."""
    _, chunks = _run_single_file_dual(tmp_path)
    assert len(chunks) == 1
    chunk = chunks[0]

    assert "canonical_range" in chunk, "canonical_range missing when content_range_ref present"
    cr = chunk["canonical_range"]
    crr = chunk["content_range_ref"]

    assert cr["artifact_role"] == "canonical_md"
    assert cr["file_path"] == crr["file_path"]
    assert cr["start_byte"] == crr["start_byte"]
    assert cr["end_byte"] == crr["end_byte"]
    assert cr["start_line"] == crr["start_line"]
    assert cr["end_line"] == crr["end_line"]
    assert cr["content_sha256"] == crr["content_sha256"]
    # canonical_range must not carry repo_id
    assert "repo_id" not in cr


def test_chunk_index_emits_source_range_declared_from_existing_source_fields(tmp_path):
    """source_range must be present with status=declared and correct fields."""
    _, chunks = _run_single_file_dual(tmp_path)
    assert len(chunks) == 1
    chunk = chunks[0]

    assert "source_range" in chunk, "source_range missing"
    sr = chunk["source_range"]

    assert sr["file_path"] == chunk["path"]
    assert sr["start_byte"] == chunk["start_byte"]
    assert sr["end_byte"] == chunk["end_byte"]
    assert sr["start_line"] == chunk["start_line"]
    assert sr["end_line"] == chunk["end_line"]
    assert "content_sha256" in sr
    assert sr["status"] == "declared"


def test_source_range_status_required_when_source_range_present(tmp_path):
    """Every source_range object must carry a status field."""
    _, chunks = _run_single_file_dual(tmp_path)
    for chunk in chunks:
        if "source_range" in chunk:
            assert "status" in chunk["source_range"], (
                f"source_range missing status in chunk {chunk.get('chunk_id')}"
            )


def test_canonical_range_hash_roundtrip(tmp_path):
    """canonical_range.content_sha256 must match the bytes at [start_byte:end_byte] in canonical_md."""
    res, chunks = _run_single_file_dual(tmp_path)
    assert len(chunks) == 1
    chunk = chunks[0]

    assert "canonical_range" in chunk
    cr = chunk["canonical_range"]

    # Locate the canonical_md file
    canonical_path = res.canonical_md
    assert canonical_path is not None and canonical_path.exists()

    content_bytes = canonical_path.read_bytes()
    extracted = content_bytes[cr["start_byte"]:cr["end_byte"]]
    actual_sha = hashlib.sha256(extracted).hexdigest()

    assert actual_sha == cr["content_sha256"], (
        f"Hash mismatch: expected {cr['content_sha256']}, got {actual_sha}"
    )


def test_source_range_hash_roundtrip(tmp_path):
    """source_range.content_sha256 must match the bytes at [start_byte:end_byte] in the source file."""
    content = "def hello():\n    pass\n"
    _, chunks = _run_single_file_dual(tmp_path, content=content, fname="test.py")
    assert len(chunks) == 1
    chunk = chunks[0]

    assert "source_range" in chunk
    sr = chunk["source_range"]

    # The source file content as originally read
    source_bytes = content.encode("utf-8")
    extracted = source_bytes[sr["start_byte"]:sr["end_byte"]]
    actual_sha = hashlib.sha256(extracted).hexdigest()

    assert actual_sha == sr["content_sha256"], (
        f"source_range hash mismatch: expected {sr['content_sha256']}, got {actual_sha}"
    )


def test_split_mode_no_canonical_range_for_overflow_chunks(tmp_path):
    """Chunks in split overflow parts must not receive canonical_range."""
    hub_path = tmp_path / "hub"
    hub_path.mkdir()
    merges_dir = tmp_path / "merges"
    merges_dir.mkdir()

    repo_dir = hub_path / "r1"
    repo_dir.mkdir()

    fis = []
    for i in range(50):
        fname = f"test_{i}.py"
        fpath = repo_dir / fname
        fpath.write_text(
            f"def hello_{i}():\n    print('file {i} filler for split test')\n",
            encoding="utf-8"
        )
        fis.append(FileInfo(
            root_label="r1",
            abs_path=fpath,
            rel_path=Path(fname),
            size=fpath.stat().st_size,
            is_text=True,
            md5=f"dummy_{i}",
            category="source",
            tags=[],
            ext=".py"
        ))

    res = write_reports_v2(
        merges_dir=merges_dir,
        hub=hub_path,
        repo_summaries=[{"name": "r1", "root": repo_dir, "files": fis}],
        detail="dev",
        mode="single",
        max_bytes=10000,
        plan_only=False,
        output_mode="dual",
        split_size=20000
    )

    assert len(res.md_parts) > 1, "Test requires a split to produce overflow chunks"

    chunks = []
    with res.chunk_index.open() as f:
        for line in f:
            chunks.append(json.loads(line))

    overflow = [c for c in chunks if "content_range_ref" not in c]
    assert len(overflow) > 0, "Test requires at least one overflow chunk"

    for chunk in overflow:
        assert "canonical_range" not in chunk, (
            f"canonical_range must not be present on overflow chunk {chunk.get('chunk_id')}"
        )
        # source_range must still be present even for overflow chunks
        assert "source_range" in chunk, (
            f"source_range must be present on all chunks, including overflow {chunk.get('chunk_id')}"
        )
        assert chunk["source_range"]["status"] == "declared"
