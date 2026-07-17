from pathlib import Path
from merger.repoground.core.merge import write_reports_v2, FileInfo
from merger.repoground.core.range_resolver import resolve_range_ref

def test_range_propagation_to_canonical_md(tmp_path):
    hub_path = tmp_path / "hub"
    hub_path.mkdir()
    merges_dir = tmp_path / "merges"
    merges_dir.mkdir()

    repo_dir = hub_path / "r1"
    repo_dir.mkdir()
    f1 = repo_dir / "test.py"
    f1.write_text("def hello():\n    pass\n", encoding="utf-8")

    fi = FileInfo(
        root_label="r1",
        abs_path=f1,
        rel_path=Path("test.py"),
        size=f1.stat().st_size,
        is_text=True,
        md5="dummy",
        category="source",
        tags=[],
        ext=".py"
    )

    repo_summaries = [{"name": "r1", "root": repo_dir, "files": [fi]}]

    res = write_reports_v2(
        merges_dir=merges_dir,
        hub=hub_path,
        repo_summaries=repo_summaries,
        detail="dev",
        mode="single",
        max_bytes=10000,
        plan_only=False,
        output_mode="dual"
    )

    import json
    chunks = []
    with res.chunk_index.open() as f:
        for line in f:
            chunks.append(json.loads(line))

    assert len(chunks) == 1
    chunk = chunks[0]

    assert "content_range_ref" in chunk
    ref = chunk["content_range_ref"]
    assert ref["artifact_role"] == "canonical_md"
    assert ref["file_path"] == res.canonical_md.name

    # Use the official resolver to prove the contract is perfectly aligned with the manifest
    resolved = resolve_range_ref(res.bundle_manifest, ref)
    assert resolved["text"] == "def hello():\n    pass\n"

def test_range_propagation_split_mode(tmp_path):
    hub_path = tmp_path / "hub"
    hub_path.mkdir()
    merges_dir = tmp_path / "merges"
    merges_dir.mkdir()

    repo_dir = hub_path / "r1"
    repo_dir.mkdir()

    # We create multiple files to force a split
    fis = []
    for i in range(50):
        fname = f"test_{i}.py"
        fpath = repo_dir / fname
        content = f"def hello_{i}():\n    print('This is file {i} filling up space to trigger a split.')\n"
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

    res = write_reports_v2(
        merges_dir=merges_dir,
        hub=hub_path,
        repo_summaries=repo_summaries,
        detail="dev",
        mode="single",
        max_bytes=10000,
        plan_only=False,
        output_mode="dual",
        split_size=20000  # Make it large enough so Part 1 captures files, but small enough to split over multiple files
    )

    assert len(res.md_parts) > 1, f"Expected multiple MD parts, but got {len(res.md_parts)}"

    import json
    chunks = []
    with res.chunk_index.open() as f:
        for line in f:
            chunks.append(json.loads(line))

    assert len(chunks) == 50, f"Expected 50 chunks, but got {len(chunks)}"

    parts_map = {p.name: p for p in res.md_parts}

    # Check that chunks refer to valid, existing file paths and byte offsets are correct
    # And most importantly, check that the official resolver accepts it!
    with_ref = 0
    without_ref = 0

    for chunk in chunks:
        # We only expect content_range_ref if the chunk actually fell into the canonical_md part.
        # Otherwise, we expect it to fallback gracefully to derived_range_ref at query time (no content_range_ref in index).
        ref = chunk.get("content_range_ref")

        original_fpath = repo_dir / Path(chunk["path"]).name
        with original_fpath.open("rb") as f:
            original_bytes = f.read()
        expected_chunk_content = original_bytes[chunk["start_byte"]:chunk["end_byte"]]

        if ref:
            with_ref += 1
            assert ref["artifact_role"] == "canonical_md"
            file_path = ref["file_path"]
            assert file_path in parts_map, f"Chunk referenced MD part {file_path} not found in generated parts."

            # The hard truth: can the resolver find it?
            # This ensures we don't violate the Manifest contract.
            resolved = resolve_range_ref(res.bundle_manifest, ref)
            assert resolved["text"].encode("utf-8") == expected_chunk_content
        else:
            without_ref += 1
            # If it's not in the canonical part, it shouldn't have a content_range_ref
            # to prevent breaking the resolver.
            assert "content_range_ref" not in chunk, "Chunks outside canonical MD must not have a content_range_ref to avoid contract violations."

    # Guarantee that the test actually split things into both categories
    assert with_ref > 0, "Test failed to produce any canonical chunks with refs"
    assert without_ref > 0, "Test failed to produce any split overflow chunks without refs"
