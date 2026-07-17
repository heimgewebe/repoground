import unittest
import tempfile
import shutil
from pathlib import Path
import sys
import os

# Add parent directory to path to import merge_core
# We need to add 'merger' which is ../.. from tests/
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from merger.repoground.core.merge import HealthCollector, scan_repo, iter_report_blocks, EPISTEMIC_HUMILITY_WARNING

class TestSemanticsV2(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.root = Path(self.test_dir)
        self.repo_path = self.root / "test-repo"
        self.repo_path.mkdir()

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def create_dummy_file(self, path, content=""):
        p = self.repo_path / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return p

    def test_critical_files_inclusion_logic(self):
        """Test that critical files are force-included despite filters."""
        self.create_dummy_file("README.md", "# Test")
        self.create_dummy_file(".ai-context.yml", "context: test")
        self.create_dummy_file("src/main.py", "print('hello')")

        # Scan with path filter that excludes everything
        # path_filter="docs" matches nothing here
        summary = scan_repo(self.repo_path, path_contains="docs")

        files = summary["files"]
        rel_paths = [f.rel_path.as_posix() for f in files]

        # README and ai-context must be present
        self.assertIn("README.md", rel_paths)
        self.assertIn(".ai-context.yml", rel_paths)

        # main.py should be excluded
        self.assertNotIn("src/main.py", rel_paths)

        # Check inclusion_reason
        for f in files:
            if f.rel_path.name == "README.md":
                self.assertEqual(f.inclusion_reason, "force_include")

    def test_partial_merge_health_semantics(self):
        """Test 1: Partial-Merge with existing .ai-context.yml -> No CRITICAL."""
        self.create_dummy_file(".ai-context.yml", "context: test")
        self.create_dummy_file("README.md", "# Readme") # Need readme to avoid critical
        self.create_dummy_file(".wgx/profile.yml", "profile: test")
        self.create_dummy_file(".github/workflows/guard.yml", "ci: test")
        self.create_dummy_file("contracts/test.json", "{}")

        # Run scan with path filter that excludes sources but Force Includes criticals
        summary = scan_repo(self.repo_path, path_contains="src") # src doesn't exist
        files = summary["files"]

        # Because of force include, critical files should be present
        collector = HealthCollector()
        health = collector.analyze_repo("test-repo", files)

        # Should not be critical because critical files are forced in
        self.assertNotEqual(health.status, "critical", f"Status is {health.status}, warnings: {health.warnings}")
        self.assertTrue(health.has_ai_context)
        # Ensure we don't have the old warning
        for w in health.warnings:
            self.assertNotIn("No AI context files found", w)

    def test_schema_json_as_contract(self):
        """Test 3: Repo with *.schema.json counts as Contract."""
        self.create_dummy_file("foo.schema.json", "{}")
        self.create_dummy_file("README.md", "README")

        summary = scan_repo(self.repo_path)
        files = summary["files"]

        collector = HealthCollector()
        health = collector.analyze_repo("test-repo", files)

        self.assertTrue(health.has_contracts, "Schema json should be detected as contract")

    def test_epistemic_humility_warning(self):
        """Test that non-max profiles get the humility warning."""
        self.create_dummy_file("README.md", "# Readme")

        summary = scan_repo(self.repo_path)
        files = summary["files"]

        # 1. Test MAX profile -> No warning
        blocks_max = list(iter_report_blocks(files, "max", 0, [self.repo_path], False))
        header_max = blocks_max[0]
        self.assertNotIn(EPISTEMIC_HUMILITY_WARNING, header_max)

        # 2. Test SUMMARY profile -> Warning present
        blocks_sum = list(iter_report_blocks(files, "summary", 0, [self.repo_path], False))
        header_sum = blocks_sum[0]
        self.assertIn(EPISTEMIC_HUMILITY_WARNING, header_sum)

        # 3. Test Filter active -> Warning present (even if max?)
        # Wait, the code says: allows_negative_claims = (level in ("max",)) and not path_filter and not ext_filter
        # So filters should trigger warning even in max.
        blocks_filter = list(iter_report_blocks(files, "max", 0, [self.repo_path], False, path_filter="src"))
        header_filter = blocks_filter[0]
        self.assertIn(EPISTEMIC_HUMILITY_WARNING, header_filter)

if __name__ == '__main__':
    unittest.main()
