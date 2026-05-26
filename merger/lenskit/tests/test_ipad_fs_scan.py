import unittest
import json
import os
import shutil
import tempfile
import unicodedata
import contextlib
from unittest.mock import patch, MagicMock
from merger.lenskit.frontends.pythonista.ipad_fs_scan import iPadFSScanner

# Helper to create robust mock entries
def create_mock_entry(name, is_file=True, size=100, mtime=1234567890):
    entry = MagicMock()
    entry.name = name
    entry.is_file.return_value = is_file
    entry.is_dir.return_value = not is_file
    entry.path = f"/mock/{name}"
    stat_mock = MagicMock()
    stat_mock.st_size = size
    stat_mock.st_mtime = mtime
    entry.stat.return_value = stat_mock
    return entry

class TestiPadFSScanner(unittest.TestCase):
    def setUp(self):
        # Create a temporary directory structure for testing
        self.test_dir = tempfile.mkdtemp()
        self.output_dir = os.path.join(self.test_dir, "output")
        os.makedirs(self.output_dir)

        # Structure:
        # root/
        #   file1.txt
        #   sub/
        #     file2.log
        #   excluded/
        #     file3.txt
        #   node_modules/
        #     lib.js
        #   ._test.txt  (AppleDouble noise)

        self.root_path = os.path.join(self.test_dir, "root")
        os.makedirs(os.path.join(self.root_path, "sub"))
        os.makedirs(os.path.join(self.root_path, "excluded"))
        os.makedirs(os.path.join(self.root_path, "node_modules"))

        with open(os.path.join(self.root_path, "file1.txt"), "w") as f:
            f.write("content")

        with open(os.path.join(self.root_path, "sub", "file2.log"), "w") as f:
            f.write("log content")

        with open(os.path.join(self.root_path, "excluded", "file3.txt"), "w") as f:
            f.write("ignored")

        with open(os.path.join(self.root_path, "node_modules", "lib.js"), "w") as f:
            f.write("library")

        # Create AppleDouble noise file
        with open(os.path.join(self.root_path, "._test.txt"), "w") as f:
            f.write("resource fork")

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_basic_scan(self):
        roots = [{
            "root_id": "test_root",
            "label": "Test Root",
            "source": "test",
            "path": self.root_path
        }]

        # Uses default excludes which should now include ._*
        scanner = iPadFSScanner(
            roots=roots,
            output_dir=self.output_dir,
            excludes=["excluded", "node_modules", "._*"]
        )

        result = scanner.scan()

        # Verify Top Level Schema
        self.assertEqual(result["schema"], "ipad.fs.index/v1")
        self.assertEqual(len(result["roots"]), 1)

        root = result["roots"][0]
        self.assertEqual(root["root_id"], "test_root")
        self.assertEqual(root["summary"]["status"], "ok")

        # Verify Tree Structure
        tree = root["tree"]
        self.assertEqual(tree["path"], "root")
        self.assertEqual(tree["type"], "dir")

        # Verify Root Relpath Determinism
        self.assertEqual(tree.get("relpath"), "")
        self.assertEqual(tree.get("segments"), [])

        # Check Children (file1.txt, sub) - sorted by name
        children = tree["children"]
        # Expected: file1.txt, sub.
        # Excluded: excluded, node_modules, ._test.txt
        names = [c["path"] for c in children]
        self.assertIn("file1.txt", names)
        self.assertIn("sub", names)
        self.assertNotIn("excluded", names)
        self.assertNotIn("node_modules", names)
        self.assertNotIn("._test.txt", names)

        # Check that os_name is preserved
        file1_node = next(c for c in children if c["path"] == "file1.txt")
        self.assertEqual(file1_node["os_name"], "file1.txt")

        # Check Subdirectory
        sub_node = next(c for c in children if c["path"] == "sub")
        self.assertEqual(sub_node["type"], "dir")
        self.assertEqual(sub_node["relpath"], "sub")
        self.assertEqual(sub_node["segments"], ["sub"])

        self.assertEqual(sub_node["children_count"], 1)
        file2_node = sub_node["children"][0]
        self.assertEqual(file2_node["path"], "file2.log")
        self.assertEqual(file2_node["relpath"], "sub/file2.log")
        self.assertEqual(file2_node["segments"], ["sub", "file2.log"])

    def test_depth_limit(self):
        roots = [{
            "root_id": "test_root",
            "label": "Test Root",
            "source": "test",
            "path": self.root_path
        }]

        scanner = iPadFSScanner(
            roots=roots,
            output_dir=self.output_dir,
            max_depth=0
        )

        result = scanner.scan()
        root = result["roots"][0]
        tree = root["tree"]

        self.assertEqual(tree["status"], "out_of_scope")
        self.assertEqual(tree["reason"], "Max depth reached")
        self.assertEqual(root["summary"]["status"], "incomplete")

        # Test max depth 1
        scanner = iPadFSScanner(
            roots=roots,
            output_dir=self.output_dir,
            max_depth=1,
            excludes=["excluded", "node_modules", "._*"]
        )
        result = scanner.scan()
        root = result["roots"][0]
        tree = root["tree"]

        sub_node = next(c for c in tree["children"] if c["path"] == "sub")
        self.assertEqual(sub_node["status"], "out_of_scope")
        self.assertNotIn("children", sub_node)
        self.assertEqual(root["summary"]["status"], "incomplete")

        self.assertEqual(root["summary"]["dirs"], 1)
        self.assertEqual(root["summary"]["dirs_skipped"], 1)

    def test_unicode_normalization(self):
        # Create a file with NFD name
        nfd_name = unicodedata.normalize("NFD", "u\u0308ber.txt") # ü broken down
        nfc_name = unicodedata.normalize("NFC", "u\u0308ber.txt") # ü combined

        file_path = os.path.join(self.root_path, nfd_name)
        with open(file_path, "w") as f:
            f.write("unicode test")

        roots = [{
            "root_id": "test_root",
            "label": "Test Root",
            "source": "test",
            "path": self.root_path
        }]

        scanner = iPadFSScanner(
            roots=roots,
            output_dir=self.output_dir,
            excludes=["excluded", "node_modules", "._*"]
        )

        result = scanner.scan()
        tree = result["roots"][0]["tree"]

        # Find the unicode file
        # The scanner normalizes to NFC, so we should find NFC name
        children_paths = [c["path"] for c in tree["children"]]

        if nfd_name != nfc_name:
            # If the FS supports distinct NFD/NFC, or if we can write NFD,
            # we expect the output to be NFC.
            self.assertIn(nfc_name, children_paths)

            # Check segments
            file_node = next(c for c in tree["children"] if c["path"] == nfc_name)
            self.assertEqual(file_node["path"], nfc_name)
            self.assertEqual(file_node["segments"], [nfc_name])

            # relpath check
            self.assertEqual(file_node["relpath"], nfc_name)
        else:
            # If system auto-normalizes on creation (like some macOS/iOS versions),
            # then just verify we see the file.
            self.assertIn(nfc_name, children_paths)

    def test_collision_handling(self):
        """
        Simulate a directory containing two files that normalize to the same NFC string.
        Use a robust FakeScandir to avoid flaky mocks.
        """
        roots = [{
            "root_id": "test_root",
            "label": "Test Root",
            "source": "test",
            "path": self.root_path
        }]

        scanner = iPadFSScanner(
            roots=roots,
            output_dir=self.output_dir
        )

        name1 = "\u00C5"       # NFC form (Angstrom)
        name2 = "A\u030A"      # NFD form (A + Ring)
        normalized_target = unicodedata.normalize("NFC", name1)

        mock_entries = [
            create_mock_entry(name1),
            create_mock_entry(name2)
        ]

        @contextlib.contextmanager
        def fake_scandir(path):
            # Check if we are scanning the root path we intend to mock
            # We compare string representations to handle Path vs str
            if str(path) == str(self.root_path):
                yield iter(mock_entries)
            else:
                # Fallback or empty? Since we only expect root scan in this test,
                # we can return empty or fallback. Fallback is safer for unexpected recursion.
                # However, original_scandir might fail if path doesn't exist.
                # Since we are in a tempdir, let's return empty if it's a subdir we don't care about.
                yield iter([])

        with patch('os.scandir', side_effect=fake_scandir):
            result = scanner.scan()

            tree = result["roots"][0]["tree"]
            children = tree["children"]

            self.assertEqual(len(children), 2)

            node1 = children[0]
            node2 = children[1]

            # Check they have same path but different os_names
            self.assertEqual(node1["path"], normalized_target)
            self.assertEqual(node2["path"], normalized_target)

            os_names = sorted([node1["os_name"], node2["os_name"]])
            expected_os_names = sorted([name1, name2])
            self.assertEqual(os_names, expected_os_names)

            # Check collision markers
            self.assertTrue(node1.get("collision"))
            self.assertTrue(node2.get("collision"))
            self.assertEqual(node1["collision_key"], normalized_target)

    def test_exclude_filters_both_variants(self):
        """
        Verify that excluding the canonical (NFC) name excludes both NFC and NFD variants,
        preventing them from appearing in the output or causing collisions.
        """
        roots = [{
            "root_id": "test_root",
            "label": "Test Root",
            "source": "test",
            "path": self.root_path
        }]

        # Exclude "Å" (NFC form). Since the scanner normalizes before filtering,
        # this should match both "Å" (NFC) and "A" + ring (NFD).
        scanner = iPadFSScanner(
            roots=roots,
            output_dir=self.output_dir,
            excludes=["\u00C5"]
        )

        name1 = "\u00C5"       # NFC form
        name2 = "A\u030A"      # NFD form

        mock_entries = [
            create_mock_entry(name1),
            create_mock_entry(name2)
        ]

        @contextlib.contextmanager
        def fake_scandir(path):
            # Only mock the root path
            if str(path) == str(self.root_path):
                yield iter(mock_entries)
            else:
                yield iter([])

        with patch('os.scandir', side_effect=fake_scandir):
            result = scanner.scan()

            tree = result["roots"][0]["tree"]
            children = tree["children"]

            # Expect 0 children because both map to the excluded NFC key
            self.assertEqual(len(children), 0)

    def test_non_existent_root(self):
        roots = [{
            "root_id": "ghost",
            "label": "Ghost",
            "source": "test",
            "path": "/path/to/nothing"
        }]

        scanner = iPadFSScanner(roots=roots, output_dir=self.output_dir)
        result = scanner.scan()

        root = result["roots"][0]
        self.assertEqual(root["summary"]["status"], "not_found")
        self.assertEqual(len(result["errors"]), 1)
        self.assertEqual(result["errors"][0]["kind"], "not_found")

    def test_json_serialization(self):
        roots = [{
            "root_id": "test_root",
            "label": "Test Root",
            "source": "test",
            "path": self.root_path
        }]
        scanner = iPadFSScanner(roots=roots, output_dir=self.output_dir)
        result = scanner.scan()
        outfile = scanner.write_output(result)

        with open(outfile, 'r') as f:
            loaded = json.load(f)

        self.assertEqual(loaded["schema"], "ipad.fs.index/v1")

    def test_max_entries_limit(self):
        roots = [{
            "root_id": "test_root",
            "label": "Test Root",
            "source": "test",
            "path": self.root_path
        }]

        scanner = iPadFSScanner(
            roots=roots,
            output_dir=self.output_dir,
            max_entries=1
        )

        result = scanner.scan()
        root = result["roots"][0]

        self.assertEqual(root["summary"]["status"], "incomplete")
        self.assertGreaterEqual(scanner.entry_count, 1)

if __name__ == "__main__":
    unittest.main()
