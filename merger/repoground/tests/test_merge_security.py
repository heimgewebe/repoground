# -*- coding: utf-8 -*-
import unittest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch

from merger.repoground.core.merge import scan_repo

class TestMergeSecurity(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_scan_repo_containment_guard(self):
        """
        Test that scan_repo correctly excludes files outside the repo root.
        """
        # Create a repo structure
        repo_root = Path(self.test_dir) / "repo"
        repo_root.mkdir()

        # Safe file
        (repo_root / "safe.txt").write_text("ok")

        outside_path = Path(self.test_dir) / "outside"
        outside_path.mkdir()
        (outside_path / "evil.txt").write_text("evil")

        # Mock os.walk to yield the repo root AND an outside path
        # effectively simulating a traversal escape
        # Patch where it is used (in merger.repoground.core.merge)
        with patch("merger.repoground.core.merge.os.walk") as mock_walk:
            mock_walk.return_value = [
                (str(repo_root), [], ["safe.txt"]),
                (str(outside_path), [], ["evil.txt"])
            ]

            result = scan_repo(repo_root)
            files = result["files"]

            # safe.txt should be present
            self.assertTrue(any(f.rel_path.name == "safe.txt" for f in files), "Safe file missing")

            # evil.txt should be ABSENT because outside_path is not inside repo_root
            # The new commonpath guard should catch this.
            evil_present = any(f.rel_path.name == "evil.txt" for f in files)
            self.assertFalse(evil_present, "Guard failed: Outside file included!")

if __name__ == '__main__':
    unittest.main()
