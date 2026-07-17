import pytest
import re
from pathlib import Path
from merger.repoground.core import merge

# Regex to find <a id="...">
ID_REGEX = re.compile(r'<a\s+id="([^"]+)"></a>')
# Regex to find href="#..."
HREF_REGEX = re.compile(r'href="#([^"]+)"')
# Regex to find [text](#fragment)
MARKDOWN_LINK_REGEX = re.compile(r'\[.*?\]\(#([^)]+)\)')

def parse_ids_and_fragments(content: str):
    """Parses all anchor IDs and link fragments from markdown content."""
    ids = set(ID_REGEX.findall(content))
    fragments = set()
    fragments.update(HREF_REGEX.findall(content))
    fragments.update(MARKDOWN_LINK_REGEX.findall(content))
    return ids, fragments

@pytest.fixture
def sample_file_info():
    """Creates a sample FileInfo object."""
    return merge.FileInfo(
        root_label="my-repo",
        abs_path=Path("/tmp/my-repo/src/main.py"),
        rel_path=Path("src/main.py"),
        size=1024,
        is_text=True,
        md5="d41d8cd98f00b204e9800998ecf8427e",
        category="source",
        tags=["script"],
        ext=".py"
    )

def test_link_integrity_all_fragments_resolve(sample_file_info, tmp_path):
    """
    Test that every internal link (#fragment) in the generated report
    resolves to an explicit <a id="..."> anchor.
    """
    files = [sample_file_info]
    # Create dummy source
    source = tmp_path / "my-repo"
    source.mkdir()
    (source / "src").mkdir()
    (source / "src/main.py").write_text("print('hello')")
    sample_file_info.abs_path = source / "src/main.py"

    report = merge.generate_report_content(
        files=files,
        level="dev",
        max_file_bytes=0,
        sources=[source],
        plan_only=False
    )

    ids, fragments = parse_ids_and_fragments(report)

    # Check that required structural anchors exist
    assert "manifest" in ids
    assert "index" in ids

    # Check that fragments resolve
    missing = []
    for frag in fragments:
        if frag not in ids:
            missing.append(frag)

    assert not missing, f"Found missing anchor targets: {missing}"

def test_no_duplicate_ids(sample_file_info, tmp_path):
    """
    Test that generated IDs are unique.
    """
    files = [sample_file_info]
    # Create dummy source
    source = tmp_path / "my-repo"
    source.mkdir()
    (source / "src").mkdir()
    (source / "src/main.py").write_text("print('hello')")
    sample_file_info.abs_path = source / "src/main.py"

    report = merge.generate_report_content(
        files=files,
        level="dev",
        max_file_bytes=0,
        sources=[source],
        plan_only=False
    )

    all_ids = ID_REGEX.findall(report)

    duplicates = set()
    seen = set()
    for i in all_ids:
        if i in seen:
            duplicates.add(i)
        seen.add(i)

    assert not duplicates, f"Found duplicate anchor IDs: {duplicates}"

def test_double_anchoring_strategy(sample_file_info, tmp_path):
    """
    Test that files have both human-stable (hash) and path-stable anchors.
    """
    files = [sample_file_info]
    source = tmp_path / "my-repo"
    source.mkdir()
    (source / "src").mkdir()
    (source / "src/main.py").write_text("print('hello')")
    sample_file_info.abs_path = source / "src/main.py"

    # Calculate expected IDs
    fid = merge._stable_file_id(sample_file_info)
    human_stable = fid.replace("FILE:", "file-")

    repo_slug = merge._slug_token("my-repo")
    path_slug = merge._slug_token("src/main.py")
    path_stable = f"file-{repo_slug}-{path_slug}"

    report = merge.generate_report_content(
        files=files,
        level="dev",
        max_file_bytes=0,
        sources=[source],
        plan_only=False
    )

    ids, _ = parse_ids_and_fragments(report)

    assert human_stable in ids, "Human-stable anchor missing"
    assert path_stable in ids, "Path-stable anchor missing"

def test_path_sanitization_and_nfc(tmp_path):
    """Test NFC normalization and path sanitization in anchors."""
    # Use a file with unicode characters to verify normalization behavior
    # NFD input 'u\u0308ber.txt' (u + ¨) should be normalized to NFC 'über.txt' (ü)
    nfd_name = "u\u0308ber.txt"
    nfc_name = "über.txt"

    fi = merge.FileInfo(
        root_label="repo",
        abs_path=tmp_path / nfc_name,
        rel_path=Path(nfd_name), # Simulate NFD coming from OS
        size=10,
        is_text=True,
        md5="123",
        category="source",
        tags=[],
        ext=".txt"
    )

    # We create a dummy source with the NFD filename
    nfd_source = tmp_path / "nfd_repo"
    nfd_source.mkdir()
    (nfd_source / nfd_name).write_text("content")

    fi.abs_path = nfd_source / nfd_name

    report = merge.generate_report_content(
        files=[fi],
        level="dev",
        max_file_bytes=0,
        sources=[nfd_source],
        plan_only=False
    )

    ids, _ = parse_ids_and_fragments(report)

    # Verify we have an anchor derived from the file.
    # Logic: NFD 'u¨ber' -> NFC 'über' -> _slug_token lowercases & strips non-ascii -> 'ber-txt'
    # This confirms the ID generation pipeline handles unicode inputs without crashing
    # and performs the expected sanitization steps.

    expected_slug = "file-repo-ber-txt"
    assert expected_slug in ids, f"Expected sanitized unicode anchor '{expected_slug}' not found in {ids}"

def test_backlinks_exist(sample_file_info, tmp_path):
    files = [sample_file_info]
    source = tmp_path / "my-repo"
    source.mkdir()
    (source / "src").mkdir()
    (source / "src/main.py").write_text("print('hello')")
    sample_file_info.abs_path = source / "src/main.py"

    report = merge.generate_report_content(
        files=files,
        level="dev",
        max_file_bytes=0,
        sources=[source],
        plan_only=False
    )

    assert "[↑ Manifest](#manifest)" in report
    assert "[↑ Index](#index)" in report
