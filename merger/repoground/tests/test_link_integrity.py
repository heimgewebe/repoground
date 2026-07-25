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

def test_stable_hash_anchor(sample_file_info, tmp_path):
    """
    Test that files have a canonical SHA-256 path-identity anchor plus a unique legacy alias.
    """
    files = [sample_file_info]
    source = tmp_path / "my-repo"
    source.mkdir()
    (source / "src").mkdir()
    (source / "src/main.py").write_text("print('hello')")
    sample_file_info.abs_path = source / "src/main.py"

    # Calculate expected anchor
    fid = merge._stable_file_id(sample_file_info)
    human_stable = fid.replace("FILE:", "file-")

    report = merge.generate_report_content(
        files=files,
        level="dev",
        max_file_bytes=0,
        sources=[source],
        plan_only=False
    )

    ids, _ = parse_ids_and_fragments(report)

    repo_slug = merge._slug_token("my-repo")
    path_slug = merge._slug_token("src/main.py")
    legacy_alias = f"file-{repo_slug}-{path_slug}"
    assert human_stable in ids, "SHA-256 path-identity anchor missing"
    assert legacy_alias in ids, "unique legacy alias missing"

def test_path_sanitization_and_nfc(tmp_path):
    """Test NFC normalization is applied for file identity, and a valid anchor is produced."""
    nfd_name = "u\u0308ber.txt"
    nfc_name = "über.txt"

    fi = merge.FileInfo(
        root_label="repo",
        abs_path=tmp_path / nfc_name,
        rel_path=Path(nfd_name),  # Simulate NFD coming from OS
        size=10,
        is_text=True,
        md5="123",
        category="source",
        tags=[],
        ext=".txt"
    )

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

    # Verify that a hash-based anchor exists for this file
    fid = merge._stable_file_id(fi)
    expected_anchor = fid.replace("FILE:", "file-")
    assert expected_anchor in ids, f"Expected anchor '{expected_anchor}' not found in {ids}"

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
