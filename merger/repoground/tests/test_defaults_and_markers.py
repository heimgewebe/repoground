
import unittest
import tempfile
from pathlib import Path
from merger.repoground.frontends.pythonista import repolens
from merger.repoground.service.models import JobRequest
from merger.repoground.core import merge

class TestDefaultsAndMarkers(unittest.TestCase):
    def test_default_extras_minimal(self):
        """
        Verify that DEFAULT_EXTRAS is set to minimal configuration:
        json_sidecar and augment_sidecar only.
        """
        defaults = repolens.DEFAULT_EXTRAS
        self.assertIn("json_sidecar", defaults)
        self.assertIn("augment_sidecar", defaults)
        self.assertNotIn("health", defaults)
        self.assertNotIn("organism_index", defaults)
        self.assertNotIn("fleet_panorama", defaults)
        self.assertNotIn("heatmap", defaults)
        self.assertNotIn("ai_heatmap", defaults)

    def test_service_defaults_match(self):
        """
        Verify that service defaults match frontend defaults.
        """
        req = JobRequest()
        def normalize(s):
            return sorted([x.strip() for x in (s or "").split(',') if x.strip()])

        service_defaults = normalize(req.extras)
        frontend_defaults = normalize(repolens.DEFAULT_EXTRAS)

        self.assertEqual(service_defaults, frontend_defaults,
                         f"Service defaults {service_defaults} do not match frontend {frontend_defaults}")

    def test_start_of_content_marker_robust(self):
        """
        Verify that the generated report contains the <!-- START_OF_CONTENT --> marker
        before the first file content, using a real scan.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)

            # Create a dummy repo structure
            repo_dir = tmp_path / "test_repo"
            repo_dir.mkdir()
            (repo_dir / "foo.py").write_text("print('hello')", encoding="utf-8")

            # Scan repo
            scan_result = merge.scan_repo(repo_dir)
            files = scan_result["files"]

            # Generate blocks (plan_only=False)
            iterator = merge.iter_report_blocks(
                files=files,
                level="max",
                max_file_bytes=0,
                sources=[repo_dir],
                plan_only=False,
                code_only=False,
                debug=False
            )

            report_content = "".join(iterator)

            # Check for marker
            self.assertIn("<!-- START_OF_CONTENT -->", report_content)

            # Ensure it appears before the Content Header
            marker_pos = report_content.find("<!-- START_OF_CONTENT -->")
            header_pos = report_content.find("## 📄 Content")

            self.assertNotEqual(marker_pos, -1, "Marker not found")
            self.assertNotEqual(header_pos, -1, "Content Header not found")
            self.assertLess(marker_pos, header_pos, "Marker should appear before Content Header")

    def test_start_of_content_marker_absent_in_plan_only(self):
        """
        Verify that the generated report DOES NOT contain the marker in plan-only mode.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            repo_dir = tmp_path / "test_repo"
            repo_dir.mkdir()
            (repo_dir / "foo.py").write_text("print('hello')", encoding="utf-8")

            scan_result = merge.scan_repo(repo_dir)
            files = scan_result["files"]

            iterator = merge.iter_report_blocks(
                files=files,
                level="max",
                max_file_bytes=0,
                sources=[repo_dir],
                plan_only=True,
                code_only=False,
                debug=False
            )

            report_content = "".join(iterator)

            self.assertNotIn("<!-- START_OF_CONTENT -->", report_content)

if __name__ == "__main__":
    unittest.main()
