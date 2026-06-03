import io
import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

import scripts.docmeta.check_planning_registration as check_plan


class TestCheckPlanningRegistration(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.old_repo_root = check_plan.REPO_ROOT
        check_plan.REPO_ROOT = self.test_dir

        os.makedirs(os.path.join(self.test_dir, "docs/tasks"))
        os.makedirs(os.path.join(self.test_dir, "docs/blueprints"))
        os.makedirs(os.path.join(self.test_dir, "docs/roadmap"))

        self.write_file("docs/tasks/index.json", '{"tasks":[]}')
        self.write_file("docs/tasks/board.md", "# Board")
        self.write_file("docs/roadmap.md", "# Roadmap")

    def tearDown(self):
        check_plan.REPO_ROOT = self.old_repo_root
        shutil.rmtree(self.test_dir)

    def write_file(self, rel_path, content):
        full_path = os.path.join(self.test_dir, rel_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)

    # --- Registration ---

    def test_blueprint_registered_via_index_evidence(self):
        self.write_file("docs/tasks/index.json", json.dumps({
            "tasks": [{"id": "T1", "evidence": ["docs/blueprints/active-bp.md"]}]
        }))
        self.write_file("docs/blueprints/active-bp.md", "---\nstatus: active\n---\nBody")
        findings = check_plan.run_checks()
        self.assertEqual([f for f in findings if f["code"] == "UNREGISTERED_PLANNING_ARTIFACT"], [])

    def test_blueprint_registered_via_board(self):
        self.write_file("docs/tasks/board.md", "| T1 | docs/blueprints/active-bp.md |")
        self.write_file("docs/blueprints/active-bp.md", "---\nstatus: active\n---\nBody")
        findings = check_plan.run_checks()
        self.assertEqual([f for f in findings if f["code"] == "UNREGISTERED_PLANNING_ARTIFACT"], [])

    def test_blueprint_registered_via_roadmap_relative_link(self):
        self.write_file("docs/roadmap.md", "See [Blueprint](blueprints/active-bp.md) for details.")
        self.write_file("docs/blueprints/active-bp.md", "---\nstatus: active\n---\nBody")
        findings = check_plan.run_checks()
        self.assertEqual([f for f in findings if f["code"] == "UNREGISTERED_PLANNING_ARTIFACT"], [])

    def test_blueprint_registered_via_roadmap_free_path_backticks(self):
        self.write_file("docs/roadmap.md", "# Roadmap\nSee `docs/blueprints/active-bp.md` for details.")
        self.write_file("docs/blueprints/active-bp.md", "---\nstatus: active\n---\nBody")
        findings = check_plan.run_checks()
        self.assertEqual([f for f in findings if f["code"] == "UNREGISTERED_PLANNING_ARTIFACT"], [])

    def test_master_roadmap_registered_via_top_level_roadmap_index(self):
        self.write_file("docs/roadmap.md", "`docs/roadmap/lenskit-master-roadmap.md`")
        self.write_file("docs/roadmap/lenskit-master-roadmap.md", "# Master Roadmap")
        findings = check_plan.run_checks()
        self.assertEqual(
            [f for f in findings if f["path"] == "docs/roadmap/lenskit-master-roadmap.md"],
            [],
        )

    # --- Normalization ---

    def test_board_path_with_backticks_and_trailing_comma(self):
        self.write_file("docs/tasks/board.md", "| T1 | `docs/blueprints/active-bp.md`, |")
        self.write_file("docs/blueprints/active-bp.md", "---\nstatus: active\n---\nBody")
        findings = check_plan.run_checks()
        self.assertEqual([f for f in findings if f["code"] == "UNREGISTERED_PLANNING_ARTIFACT"], [])

    def test_missing_evidence_with_backticks_and_trailing_comma(self):
        self.write_file("docs/tasks/index.json", json.dumps({
            "tasks": [{"id": "T1", "missing_evidence": ["still open: `docs/blueprints/planned.md`, then ratchet"]}]
        }))
        self.write_file("docs/blueprints/planned.md", "---\nstatus: active\n---\nBody")
        findings = check_plan.run_checks()
        self.assertEqual([f for f in findings if f["code"] == "UNREGISTERED_PLANNING_ARTIFACT"], [])

    def test_scripts_path_extraction_supported(self):
        self.write_file("docs/tasks/board.md", "scripts/docmeta/check_planning_registration.py")
        refs, _ = check_plan.get_registered_paths()
        self.assertIn("scripts/docmeta/check_planning_registration.py", refs)

    # --- Finding format ---

    def test_active_blueprint_unregistered_is_reported(self):
        self.write_file("docs/blueprints/unregistered.md", "---\nstatus: active\n---\nBody")
        findings = check_plan.run_checks()
        unregistered = [f for f in findings if f["code"] == "UNREGISTERED_PLANNING_ARTIFACT"]
        self.assertEqual(len(unregistered), 1)
        f = unregistered[0]
        self.assertIn("code", f)
        self.assertIn("path", f)
        self.assertIn("reason", f)
        self.assertIn("suggestion", f)
        self.assertIn("source", f)
        self.assertEqual(f["source"], "planning-registration")
        self.assertEqual(f["path"], "docs/blueprints/unregistered.md")

    # --- Exclusions ---

    def test_generated_dir_is_ignored(self):
        self.write_file("docs/_generated/foo.md", "---\nstatus: active\n---\nBody")
        findings = check_plan.run_checks()
        self.assertEqual([f for f in findings if "docs/_generated" in f.get("path", "")], [])

    def test_proofs_dir_is_ignored(self):
        self.write_file("docs/proofs/foo.md", "---\nstatus: active\n---\nBody")
        findings = check_plan.run_checks()
        self.assertEqual([f for f in findings if "docs/proofs" in f.get("path", "")], [])

    def test_runbooks_dir_is_ignored(self):
        self.write_file("docs/runbooks/foo.md", "---\nstatus: active\n---\nBody")
        findings = check_plan.run_checks()
        self.assertEqual([f for f in findings if "docs/runbooks" in f.get("path", "")], [])

    def test_reference_dir_is_ignored(self):
        self.write_file("docs/reference/foo.md", "---\nstatus: active\n---\nBody")
        findings = check_plan.run_checks()
        self.assertEqual([f for f in findings if "docs/reference" in f.get("path", "")], [])

    def test_adr_dir_is_ignored(self):
        self.write_file("docs/adr/foo.md", "---\nstatus: active\n---\nBody")
        findings = check_plan.run_checks()
        self.assertEqual([f for f in findings if "docs/adr" in f.get("path", "")], [])

    def test_claims_dir_is_ignored(self):
        self.write_file("docs/claims/foo.md", "---\nstatus: active\n---\nBody")
        findings = check_plan.run_checks()
        self.assertEqual([f for f in findings if "docs/claims" in f.get("path", "")], [])

    # --- Specs ---

    def test_spec_with_planning_doc_type_is_reported(self):
        self.write_file("docs/specs/myplan.md", "---\ndoc_type: plan\nstatus: active\n---\nBody")
        findings = check_plan.run_checks()
        unregistered = [f for f in findings if f["code"] == "UNREGISTERED_PLANNING_ARTIFACT"]
        paths = [f["path"] for f in unregistered]
        self.assertIn("docs/specs/myplan.md", paths)

    def test_spec_with_spec_doc_type_is_ignored(self):
        self.write_file("docs/specs/myspec.md", "---\ndoc_type: spec\nstatus: draft\n---\nBody")
        findings = check_plan.run_checks()
        self.assertEqual([f for f in findings if "docs/specs/myspec.md" in f.get("path", "")], [])

    def test_spec_with_quoted_planning_doc_type_is_reported(self):
        self.write_file('docs/specs/myplan2.md', '---\ndoc_type: "plan"\nstatus: "active"\n---\nBody')
        findings = check_plan.run_checks()
        unregistered = [f for f in findings if f["code"] == "UNREGISTERED_PLANNING_ARTIFACT"]
        paths = [f["path"] for f in unregistered]
        self.assertIn("docs/specs/myplan2.md", paths)

    # --- Terminal statuses ---

    def test_deprecated_blueprint_is_ignored(self):
        self.write_file("docs/blueprints/old.md", "---\nstatus: deprecated\n---\nBody")
        findings = check_plan.run_checks()
        self.assertEqual([f for f in findings if "docs/blueprints/old.md" in f.get("path", "")], [])

    def test_superseded_blueprint_is_ignored(self):
        self.write_file("docs/blueprints/old.md", "---\nstatus: superseded\n---\nBody")
        findings = check_plan.run_checks()
        self.assertEqual([f for f in findings if "docs/blueprints/old.md" in f.get("path", "")], [])

    def test_archived_blueprint_is_ignored(self):
        self.write_file("docs/blueprints/old.md", "---\nstatus: archived\n---\nBody")
        findings = check_plan.run_checks()
        self.assertEqual([f for f in findings if "docs/blueprints/old.md" in f.get("path", "")], [])

    def test_deferred_blueprint_is_ignored(self):
        self.write_file("docs/blueprints/old.md", "---\nstatus: deferred\n---\nBody")
        findings = check_plan.run_checks()
        self.assertEqual([f for f in findings if "docs/blueprints/old.md" in f.get("path", "")], [])

    # --- Control files ---

    def test_broken_index_json_produces_parse_error(self):
        self.write_file("docs/tasks/index.json", "{invalid json")
        findings = check_plan.run_checks()
        self.assertTrue(any(f["code"] == "CONTROL_FILE_PARSE_ERROR" for f in findings))

    def test_missing_index_json_produces_control_file_missing(self):
        os.remove(os.path.join(self.test_dir, "docs/tasks/index.json"))
        findings = check_plan.run_checks()
        self.assertTrue(any(f["code"] == "CONTROL_FILE_MISSING" and "index.json" in f["path"] for f in findings))

    # --- CLI ---

    @patch('sys.stderr', new_callable=io.StringIO)
    def test_default_mode_exits_zero_with_findings(self, mock_stderr):
        self.write_file("docs/blueprints/unregistered.md", "---\nstatus: active\n---\nBody")
        exit_code = check_plan.main([])
        self.assertEqual(exit_code, 0)
        self.assertIn("Report-only mode: findings do not fail CI", mock_stderr.getvalue())

    @patch('sys.stderr', new_callable=io.StringIO)
    def test_strict_mode_exits_one_with_findings(self, mock_stderr):
        self.write_file("docs/blueprints/unregistered.md", "---\nstatus: active\n---\nBody")
        exit_code = check_plan.main(["--strict"])
        self.assertEqual(exit_code, 1)

    @patch('sys.stderr', new_callable=io.StringIO)
    def test_report_only_hint_on_stderr(self, mock_stderr):
        self.write_file("docs/blueprints/unregistered.md", "---\nstatus: active\n---\nBody")
        check_plan.main([])
        self.assertIn("Report-only mode: findings do not fail CI", mock_stderr.getvalue())


if __name__ == '__main__':
    unittest.main()
