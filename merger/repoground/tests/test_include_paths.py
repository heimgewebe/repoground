
import pytest
from merger.repoground.core.merge import scan_repo

@pytest.fixture
def temp_repo(tmp_path):
    repo = tmp_path / "test-repo"
    repo.mkdir()

    (repo / "README.md").write_text("hello", encoding="utf-8")
    (repo / "src").mkdir()
    (repo / "src" / "main.py").write_text("print('hello')", encoding="utf-8")
    (repo / "docs").mkdir()
    (repo / "docs" / "manual.md").write_text("manual", encoding="utf-8")

    return repo

def test_scan_repo_include_paths_root(temp_repo):
    # Test "." as include path -> should include everything
    result = scan_repo(temp_repo, include_paths=["."])
    files = result["files"]
    paths = sorted([f.rel_path.as_posix() for f in files])

    assert "README.md" in paths
    assert "src/main.py" in paths
    assert "docs/manual.md" in paths

def test_scan_repo_include_paths_directory(temp_repo):
    # Test directory inclusion
    result = scan_repo(temp_repo, include_paths=["src"])
    files = result["files"]
    paths = sorted([f.rel_path.as_posix() for f in files])

    # README is force-included by critical logic usually, let's verify
    # scan_repo logic: if critical -> force_include. Else -> check include_paths.
    # README is critical.
    assert "README.md" in paths
    assert "src/main.py" in paths
    assert "docs/manual.md" not in paths

def test_scan_repo_include_paths_file(temp_repo):
    # Test file inclusion
    result = scan_repo(temp_repo, include_paths=["docs/manual.md"])
    files = result["files"]
    paths = sorted([f.rel_path.as_posix() for f in files])

    assert "docs/manual.md" in paths
    assert "README.md" in paths
    assert "src/main.py" not in paths

def test_scan_repo_include_paths_empty(temp_repo):
    # Test empty list -> should include nothing (except critical)
    result = scan_repo(temp_repo, include_paths=[])
    files = result["files"]
    paths = sorted([f.rel_path.as_posix() for f in files])

    # Critical files are always included
    assert "README.md" in paths
    assert "src/main.py" not in paths
    assert "docs/manual.md" not in paths

    # If we add a non-critical file to repo and exclude it, it should be gone
    (temp_repo / "other.txt").write_text("other")
    result = scan_repo(temp_repo, include_paths=[])
    paths = [f.rel_path.as_posix() for f in result["files"]]
    assert "other.txt" not in paths

def test_scan_repo_include_paths_normalization(temp_repo):
    # Test leading ./ and whitespace
    result = scan_repo(temp_repo, include_paths=[" ./src "])
    files = result["files"]
    paths = sorted([f.rel_path.as_posix() for f in files])

    assert "src/main.py" in paths
    assert "docs/manual.md" not in paths
