import unittest
import os
import tempfile
import shutil
import json
from unittest.mock import patch
import io

import scripts.docmeta.check_planning_registration as check_plan

class TestCheckPlanningRegistration(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.old_repo_root = check_plan.REPO_ROOT
        check_plan.REPO_ROOT = self.test_dir

        # Setup basic expected structure
        os.makedirs(os.path.join(self.test_dir, "docs/tasks"))
        os.makedirs(os.path.join(self.test_dir, "docs/blueprints"))

        self.write_file("docs/tasks/index.json", '{"tasks":[]}')
        self.write_file("docs/tasks/board.md", "# Board")
        self.write_file("docs/roadmap.md", "# Roadmap")

    def tearDown(self):
        check_plan.REPO_ROOT = self.old_repo_root
        shutil.rmtree(self.test_dir)

    def write_file(self, rel_path, content):
        full_path = os.path.join(self.test_dir, rel_path)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)

    def test_registered_path_with_trailing_punctuation_passes(self):
        self.write_file("docs/tasks/board.md", "| T1 | `docs/blueprints/active-bp.md`, |")
        self.write_file("docs/blueprints/active-bp.md", "---\nid: active\nstatus: active\n---\nBody")

        findings = check_plan.run_checks()
        unregistered = [f for f in findings if f["code"] == "UNREGISTERED_PLANNING_ARTIFACT"]
        self.assertEqual(unregistered, [])

    def test_missing_evidence_path_with_punctuation_is_normalized(self):
        self.write_file("docs/tasks/index.json", json.dumps({
            "tasks": [{
                "id": "T1",
                "missing_evidence": ["still open: `docs/blueprints/planned.md`, then ratchet"]
            }]
        }))
        self.write_file("docs/blueprints/planned.md", "---\nid: planned\nstatus: active\n---\nBody")

        findings = check_plan.run_checks()
        unregistered = [f for f in findings if f["code"] == "UNREGISTERED_PLANNING_ARTIFACT"]
        self.assertEqual(unregistered, [])

    def test_active_blueprint_without_registration_is_reported(self):
        self.write_file("docs/blueprints/unregistered.md", "---\nid: unreg\nstatus: active\n---\nBody")

        findings = check_plan.run_checks()
        unregistered = [f for f in findings if f["code"] == "UNREGISTERED_PLANNING_ARTIFACT"]
        self.assertEqual(len(unregistered), 1)
        self.assertEqual(unregistered[0]["file"], "docs/blueprints/unregistered.md")

    @patch('sys.stderr', new_callable=io.StringIO)
    def test_main_modes(self, mock_stderr):
        self.write_file("docs/blueprints/unregistered.md", "---\nid: unreg\nstatus: active\n---\nBody")

        exit_code = check_plan.main([])
        self.assertEqual(exit_code, 0)
        self.assertIn("Report-only mode: findings do not fail CI", mock_stderr.getvalue())

        exit_code = check_plan.main(["--strict"])
        self.assertEqual(exit_code, 1)

if __name__ == '__main__':
    unittest.main()
