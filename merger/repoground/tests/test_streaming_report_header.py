from merger.repoground.tests._test_constants import make_generator_info

from pathlib import Path
from merger.repoground.core import merge

def create_dummy_file_info(base_dir, rel_path="file.txt", content="content"):
    """
    Robust helper to create a FileInfo with a real file backing it.

    Args:
        base_dir: The root directory where the file should be created.
        rel_path: Relative path (string or Path) from base_dir.
        content: Text content to write to the file.

    Returns:
        FileInfo object populated with correct paths and stats.
    """
    fpath = base_dir / rel_path
    # Ensure parent dirs exist
    fpath.parent.mkdir(parents=True, exist_ok=True)
    fpath.write_text(content, encoding="utf-8")

    # Instantiate FileInfo with all fields matching current signature
    return merge.FileInfo(
        root_label=base_dir.name,
        abs_path=fpath,
        rel_path=Path(rel_path),
        size=len(content.encode('utf-8')),
        is_text=True,
        md5="0" * 32, # Valid-looking MD5
        category="source",
        tags=[],
        ext=fpath.suffix,
        skipped=False,
        reason=None,
        content=None, # Content typically read on demand
        inclusion_reason="normal"
    )

def test_iter_report_blocks_first_block_contains_report_title(tmp_path):
    """Ensure the first block yielded by iter_report_blocks contains the report title."""
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    fi = create_dummy_file_info(repo_dir, "file.txt")

    # Call iter_report_blocks with explicit keyword arguments matching signature
    iterator = merge.iter_report_blocks(
        files=[fi],
        level="max",
        max_file_bytes=0,
        sources=[repo_dir],
        plan_only=False
    )

    # Get the first block
    first_block = next(iterator)

    # Check strict header contract: the report title must appear in the first block
    # We search lines to handle BOM or potential mode markers gracefully
    lines = first_block.splitlines()
    found = False
    for line in lines:
        if line.lstrip('\ufeff').startswith("# RepoGround Report"):
            found = True
            break

    assert found, f"Report title not found in first block:\n{first_block}"

def test_write_reports_v2_single_file_enforces_part_1_1_header(tmp_path):
    """Ensure write_reports_v2 in single-file mode enforces 'Part 1/1' header."""
    # Setup directories
    merges_dir = tmp_path / "merges"
    merges_dir.mkdir()
    hub = tmp_path / "hub"
    hub.mkdir()

    repo_dir = hub / "test-repo"
    repo_dir.mkdir()

    # Create dummy file info located INSIDE the repo_dir
    fi = create_dummy_file_info(repo_dir, "README.md", "# Hi")

    repo_summary = {
        "name": "test-repo",
        "root": repo_dir,
        "files": [fi]
    }

    # We use plan_only=True to focus on header generation logic in the writer
    artifacts = merge.write_reports_v2(generator_info=make_generator_info(),
        merges_dir=merges_dir,
        hub=hub,
        repo_summaries=[repo_summary],
        detail="summary",
        mode="single",
        max_bytes=0,
        plan_only=True,
        split_size=0, # Single file mode
        path_filter=None
    )

    # Find the markdown file
    md_path = artifacts.canonical_md
    assert md_path is not None
    assert md_path.exists()

    content = md_path.read_text(encoding="utf-8")
    lines = content.splitlines()

    # Look for the header line
    header_found = False
    for line in lines:
        # Strict exact match for the enforced single-part header
        if line.lstrip('\ufeff').strip() == "# RepoGround Report (Part 1/1)":
            header_found = True
            break

    assert header_found, f"Header '# RepoGround Report (Part 1/1)' not found in:\n{content[:500]}"
