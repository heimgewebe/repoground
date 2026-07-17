# -*- coding: utf-8 -*-
import unittest
import sys
import os
from pathlib import Path

# Add merger/ to sys.path so lenskit is importable
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from merger.repoground.core.merge import (
    iter_report_blocks,
    generate_json_sidecar,
    FileInfo,
)

class TestMetaNone(unittest.TestCase):

    def setUp(self):
        self.fi = FileInfo(
            root_label="test_repo",
            abs_path=Path("/tmp/test.txt"),
            rel_path=Path("test.txt"),
            size=100,
            is_text=True,
            md5="abc",
            category="source",
            tags=[],
            ext=".txt",
            content="hello",
            inclusion_reason="normal"
        )
        # Ensure roles are computed or None
        self.fi.roles = None
        self.files = [self.fi]
        self.sources = [Path("/tmp/test_repo")]

    def test_meta_none_markdown_output(self):
        """Verify markdown output for meta: none."""
        iterator = iter_report_blocks(
            files=self.files,
            level="max",
            max_file_bytes=0,
            sources=self.sources,
            plan_only=False,
            meta_none=True  # ENABLE meta: none
        )

        output = "".join(list(iterator))

        # 1. Check for warning
        self.assertIn("**Meta-Mode:** `none` (Interpretation disabled)", output)

        # 2. Check absence of Epistemic Charter
        self.assertNotIn("## Epistemic Reading Charter", output)

        # 3. Check absence of Epistemic Declaration
        self.assertNotIn("## Epistemic Declaration", output)

        # 4. Check absence of Reading Lenses
        self.assertNotIn("## Reading Lenses", output)

        # 5. Check absence of Epistemic Status
        self.assertNotIn("## Epistemic Status", output)

        # 6. Check presence of content (raw view)
        self.assertIn("## 📄 Content", output)

        # 7. Check @meta block entries
        # Note: YAML output might vary slightly depending on lib, but keys should be present.
        if "# YAML support missing" not in output:
            self.assertRegex(output, r"mode:\s*none")
            self.assertRegex(output, r"warning:\s*interpretation_disabled")

    def test_meta_none_json_sidecar(self):
        """Verify JSON sidecar for meta: none."""
        json_data = generate_json_sidecar(
            files=self.files,
            level="max",
            max_file_bytes=0,
            sources=self.sources,
            plan_only=False,
            meta_none=True
        )

        meta = json_data["meta"]

        # 1. Check mode and warning
        self.assertEqual(meta.get("mode"), "none")
        self.assertEqual(meta.get("warning"), "interpretation_disabled")

        # 2. Check epistemic charter is absent in meta
        self.assertNotIn("epistemic_charter", meta)
        self.assertNotIn("epistemic_declaration", meta)

        # 3. Check reading lenses disabled
        self.assertFalse(json_data["reading_policy"]["lenses_applied"])

    def test_meta_full_no_nulls(self):
        """Verify that meta_none=False results in absent mode/warning keys, not nulls."""
        json_data = generate_json_sidecar(
            files=self.files,
            level="max",
            max_file_bytes=0,
            sources=self.sources,
            plan_only=False,
            meta_none=False
        )
        meta = json_data["meta"]

        # Keys should be absent
        self.assertNotIn("mode", meta)
        self.assertNotIn("warning", meta)

    def test_meta_none_vs_full_structure(self):
        """Verify that meta: none preserves structure/content compared to full."""
        # Run with meta: full (default)
        iter_full = iter_report_blocks(
            files=self.files,
            level="max",
            max_file_bytes=0,
            sources=self.sources,
            plan_only=False,
            meta_none=False
        )
        full_output = "".join(list(iter_full))

        # Run with meta: none
        iter_none = iter_report_blocks(
            files=self.files,
            level="max",
            max_file_bytes=0,
            sources=self.sources,
            plan_only=False,
            meta_none=True
        )
        none_output = "".join(list(iter_none))

        # Both should have content, manifest, structure
        self.assertIn("## 📄 Content", full_output)
        self.assertIn("## 📄 Content", none_output)

        self.assertIn("## 🧾 Manifest", full_output)
        self.assertIn("## 🧾 Manifest", none_output)

        # But headers differ
        self.assertIn("## Epistemic Declaration", full_output)
        self.assertNotIn("## Epistemic Declaration", none_output)

if __name__ == '__main__':
    unittest.main()
