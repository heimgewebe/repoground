import pytest
from unittest.mock import patch
from merger.repoground.core.merge import scan_repo

def get_file_info(files, filename):
    """
    Helper to find a file in the scan result list.
    Fails the test immediately if the file is not found.
    """
    for f in files:
        if f.rel_path.name == filename:
            return f
    pytest.fail(f"File '{filename}' not found in scan results")

def test_scan_repo_skips_hashing_when_calculate_md5_false(tmp_path):
    """
    Regression Test:
    Ensures that when calculate_md5=False, the actual hashing function `compute_md5`
    is not called, and the resulting FileInfo objects have empty MD5 fields.
    This tests the semantic behavior rather than the implementation detail (ThreadPool).
    """
    # Setup: Create a dummy file so scan_repo has something to do
    (tmp_path / "file.txt").write_text("content")

    # Patch compute_md5 where scan_repo uses it
    with patch("merger.repoground.core.merge.compute_md5") as mock_compute:
        result = scan_repo(tmp_path, calculate_md5=False)

        # Assertion 1: Hashing function should NOT be called
        mock_compute.assert_not_called()

        # Assertion 2: FileInfo for file.txt should have empty MD5
        fi = get_file_info(result["files"], "file.txt")
        assert fi.md5 == ""

def test_scan_repo_performs_hashing_when_calculate_md5_true(tmp_path):
    """
    Control Test:
    Ensures that when calculate_md5=True (default), the hashing function
    is called and the result is populated.
    """
    # Setup: Create a dummy file
    (tmp_path / "file.txt").write_text("content")

    # Patch compute_md5 to return a specific hash
    with patch("merger.repoground.core.merge.compute_md5", return_value="deadbeef") as mock_compute:
        result = scan_repo(tmp_path, calculate_md5=True)

        # Assertion 1: Hashing function SHOULD be called
        mock_compute.assert_called()

        # Assertion 2: FileInfo for file.txt should have the computed MD5
        fi = get_file_info(result["files"], "file.txt")
        assert fi.md5 == "deadbeef"
