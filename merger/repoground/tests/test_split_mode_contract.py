from pathlib import Path
import json

from merger.repoground.core.merge import write_reports_v2, FileInfo


def test_split_mode_contract_range_refs(tmp_path):
    """
    Enforces Phase 1 (Schwerpunkt D): Split-Mode-Vertrag explizit machen.
    When a file is split across multiple parts, only the canonical part
    (the first one) gets a fully bundle-backed content_range_ref.
    The test runs write_reports_v2 with a small split_size to force multiple parts.
    Then it checks the resulting chunk_index to verify range_ref assignment.
    """
    hub_path = tmp_path / "hub"
    hub_path.mkdir()
    merges_dir = tmp_path / "merges"
    merges_dir.mkdir()

    repo_dir = hub_path / "r1"
    repo_dir.mkdir()

    # We create multiple files to force a split reliably, making the chunks and parts deterministic
    fis = []
    for i in range(20):
        fname = f"test_{i}.py"
        fpath = repo_dir / fname
        content = f"def hello_{i}():\n    # " + "B" * 2000 + f"\n    print('This is file {i} filling up space to trigger a split reliably.')\n"
        fpath.write_text(content, encoding="utf-8")

        fi = FileInfo(
            root_label="r1",
            abs_path=fpath,
            rel_path=Path(fname),
            size=fpath.stat().st_size,
            is_text=True,
            md5=f"dummy_{i}",
            category="source",
            tags=[],
            ext=".py"
        )
        fis.append(fi)

    repo_summaries = [{"name": "r1", "root": repo_dir, "files": fis}]

    # Run merge with a split size to force multiple parts
    res = write_reports_v2(
        merges_dir=merges_dir,
        hub=hub_path,
        repo_summaries=repo_summaries,
        detail="dev",
        mode="single",
        max_bytes=10000,
        plan_only=False,
        output_mode="dual",
        split_size=20000  # Ensure we capture multiple files in the first part but spill over
    )

    assert len(res.md_parts) > 1, "Test needs to generate multiple markdown parts to test split mode contract"

    canonical_md_name = res.canonical_md.name if res.canonical_md else None

    assert canonical_md_name is not None
    assert res.chunk_index is not None

    # Check chunks
    with res.chunk_index.open() as f:
        lines = f.readlines()
        chunks = [json.loads(line) for line in lines]

    assert len(chunks) > 0

    # Verify that ONLY chunks referencing the canonical_md file have content_range_ref
    chunks_with_ref = 0
    chunks_without_ref = 0

    for c in chunks:
        if "content_range_ref" in c:
            chunks_with_ref += 1
            # If it has a ref, it MUST point to the canonical_md
            assert c["content_range_ref"]["file_path"] == canonical_md_name
        else:
            chunks_without_ref += 1

    # We should have both if the split worked correctly and files landed in different parts
    assert chunks_with_ref > 0, "No chunks had a content_range_ref. Expected some from the first part."
    assert chunks_without_ref > 0, "All chunks had a content_range_ref, meaning split mode contract is violated or didn't split properly."
