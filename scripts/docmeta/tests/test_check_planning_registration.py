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

    def test_missing_evidence_does_not_register(self):
        self.write_file("docs/tasks/index.json", json.dumps({
            "tasks": [{"id": "T1", "missing_evidence": ["still open: `docs/blueprints/planned.md`, then ratchet"]}]
        }))
        self.write_file("docs/blueprints/planned.md", "---\nstatus: active\n---\nBody")
        findings = check_plan.run_checks()
        unregistered = [f for f in findings if f["code"] == "UNREGISTERED_PLANNING_ARTIFACT"]
        self.assertEqual(len(unregistered), 1)
        self.assertEqual(unregistered[0]["path"], "docs/blueprints/planned.md")

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

    # --- JSON scan report with baseline parameter should have loaded=false ---

    @patch('sys.stdout', new_callable=io.StringIO)
    def test_scan_json_baseline_parameter_loaded_is_false(self, mock_stdout):
        """Scan mode should report baseline.loaded=false even if --baseline is provided."""
        baseline_file = os.path.join(self.test_dir, "baseline.json")
        with open(baseline_file, "w") as f:
            json.dump({"schema": "lenskit.planning_registration_baseline.v1", "entries": []}, f)

        check_plan.main([
            "--format", "json",
            "--baseline", baseline_file,
        ])
        output = mock_stdout.getvalue()
        report = json.loads(output)
        self.assertFalse(
            report["baseline"]["loaded"],
            "Scan mode should report baseline.loaded=false even with --baseline argument"
        )

    # --- Inline comment in top-level frontmatter (status: archived # comment) ---

    def test_inline_comment_in_terminal_status(self):
        """status: archived # comment should be recognized as archived."""
        self.write_file(
            "docs/blueprints/archived-with-comment.md",
            "---\nstatus: archived # intentionally old\n---\nBody"
        )
        findings = check_plan.run_checks()
        # Archived should be excluded from planning checks
        self.assertEqual(
            [f for f in findings if "archived-with-comment" in f.get("path", "")],
            []
        )

    def test_inline_comment_in_doc_type(self):
        """doc_type: plan # temporary should be recognized as plan."""
        self.write_file(
            "docs/specs/test-plan.md",
            '---\nstatus: active\ndoc_type: plan # temporary spec\n---\nBody'
        )
        findings = check_plan.run_checks()
        unregistered = [f for f in findings if f["code"] == "UNREGISTERED_PLANNING_ARTIFACT"]
        paths = [f["path"] for f in unregistered]
        self.assertIn("docs/specs/test-plan.md", paths)

    # --- Inline comment at planning_registration: header ---

    def test_planning_registration_header_with_inline_comment(self):
        """planning_registration: # comment should be recognized as block start."""
        self.write_file(
            "docs/blueprints/exempt-with-header-comment.md",
            "---\nstatus: active\n"
            "planning_registration: # temporary exemption\n"
            "  status: exempt\n"
            "  reason: test\n"
            "  owner: ops\n"
            "  expires: 2999-12-31\n"
            "---\nBody"
        )
        findings = check_plan.run_checks()
        # Should be accepted as valid exemption, not raise invalid exception
        invalid = [f for f in findings if f["code"] == check_plan.CODE_INVALID_EXCEPTION]
        self.assertEqual(invalid, [], "Valid exemption with inline comment at header should not be invalid")

    # --- Mandatory 'tasks' field in docs/tasks/index.json ---

    def test_index_json_missing_tasks_field_is_control_error(self):
        """index.json without 'tasks' field should produce CONTROL_FILE_PARSE_ERROR."""
        self.write_file("docs/tasks/index.json", "{}")
        findings = check_plan.run_checks()
        parse_errors = [
            f for f in findings
            if f["code"] == "CONTROL_FILE_PARSE_ERROR" and "index.json" in f["path"]
        ]
        self.assertEqual(len(parse_errors), 1, "Missing 'tasks' field should produce exactly one parse error")
        self.assertIn("tasks", parse_errors[0]["reason"].lower())

    def test_index_json_tasks_not_list_is_control_error(self):
        """index.json with 'tasks' as non-list should produce CONTROL_FILE_PARSE_ERROR."""
        self.write_file("docs/tasks/index.json", '{"tasks": "not-a-list"}')
        findings = check_plan.run_checks()
        parse_errors = [
            f for f in findings
            if f["code"] == "CONTROL_FILE_PARSE_ERROR" and "index.json" in f["path"]
        ]
        self.assertEqual(len(parse_errors), 1)
        self.assertIn("list", parse_errors[0]["reason"].lower())


    # --- Inline comment stripping (unit) ---

    def test_strip_inline_comment_bare_value_with_comment(self):
        assert check_plan._strip_inline_comment("abc # comment") == "abc"

    def test_strip_inline_comment_quoted_value_with_comment(self):
        assert check_plan._strip_inline_comment('"abc" # comment') == "abc"

    def test_strip_inline_comment_single_quoted_value_with_comment(self):
        assert check_plan._strip_inline_comment("'abc' # comment") == "abc"

    def test_strip_inline_comment_hash_inside_double_quotes_preserved(self):
        assert check_plan._strip_inline_comment('"abc # not comment"') == "abc # not comment"

    def test_strip_inline_comment_hash_inside_single_quotes_preserved(self):
        assert check_plan._strip_inline_comment("'abc # not comment'") == "abc # not comment"

    def test_strip_inline_comment_hash_without_spaces_in_bare_value(self):
        assert check_plan._strip_inline_comment("ops#team") == "ops#team"

    def test_strip_inline_comment_nospace_hash_then_space_hash_comment(self):
        # First '#' has no preceding whitespace → not a comment; second has a space → comment.
        assert check_plan._strip_inline_comment("ops#team # inline comment") == "ops#team"

    def test_strip_inline_comment_nospace_hash_in_date(self):
        # '#' without preceding whitespace inside a date-like value → preserved verbatim.
        assert check_plan._strip_inline_comment("2099-12-31#no-space") == "2099-12-31#no-space"

    def test_strip_inline_comment_empty_value(self):
        assert check_plan._strip_inline_comment("") == ""

    def test_strip_inline_comment_leading_whitespace(self):
        assert check_plan._strip_inline_comment("  exempt  # note") == "exempt"

    # --- Inline comment integration: parse_planning_registration_block ---

    def test_block_inline_comment_after_quoted_expires_ignored(self):
        """'expires: "2099-12-31" # end' must parse as '2099-12-31', not trigger exempt_bad_date."""
        self.write_file(
            "docs/blueprints/inline-comment.md",
            "---\nstatus: active\n"
            "planning_registration:\n"
            "  status: exempt\n"
            '  reason: "temporary exception" # explanation\n'
            "  owner: ops\n"
            '  expires: "2099-12-31" # end of year\n'
            "---\nBody",
        )
        findings = check_plan.run_checks()
        invalid = [f for f in findings if f["code"] == check_plan.CODE_INVALID_EXCEPTION]
        assert invalid == [], f"Unexpected invalid exceptions: {invalid}"

    def test_block_hash_inside_quotes_preserved(self):
        """'#' inside quotes must remain part of the field value."""
        self.write_file(
            "docs/blueprints/hash-in-quotes.md",
            "---\nstatus: active\n"
            "planning_registration:\n"
            "  status: exempt\n"
            '  reason: "temporary # still reason"\n'
            '  owner: "ops#team"\n'
            '  expires: "2099-12-31"\n'
            "---\nBody",
        )
        findings = check_plan.run_checks()
        invalid = [f for f in findings if f["code"] == check_plan.CODE_INVALID_EXCEPTION]
        assert invalid == [], f"Unexpected invalid exceptions: {invalid}"

    def test_block_inline_comment_after_unquoted_value(self):
        """'owner: ops # team owner' must parse owner as 'ops'."""
        self.write_file(
            "docs/blueprints/unquoted-comment.md",
            "---\nstatus: active\n"
            "planning_registration:\n"
            "  status: exempt\n"
            "  reason: temporary\n"
            "  owner: ops # team owner\n"
            "  expires: 2099-12-31\n"
            "---\nBody",
        )
        findings = check_plan.run_checks()
        invalid = [f for f in findings if f["code"] == check_plan.CODE_INVALID_EXCEPTION]
        assert invalid == [], f"Unexpected invalid exceptions: {invalid}"

    def test_block_multiline_suggestion_mentions_single_line_only(self):
        """When an exemption is invalid, the suggestion must mention single-line-only."""
        self.write_file(
            "docs/blueprints/bad-exempt.md",
            "---\nstatus: active\n"
            "planning_registration:\n"
            "  status: exempt\n"
            "  reason: some reason\n"
            "  owner: ops\n"
            "  expires: not-a-date\n"
            "---\nBody",
        )
        findings = check_plan.run_checks()
        invalid = [f for f in findings if f["code"] == check_plan.CODE_INVALID_EXCEPTION]
        assert len(invalid) == 1
        assert "single-line scalar values only" in invalid[0]["suggestion"]

    # --- Block-scalar indicator detection ---

    def test_block_scalar_reason_is_invalid_exception(self):
        """reason: > must produce INVALID_PLANNING_EXCEPTION with exempt_unsupported_scalar."""
        self.write_file(
            "docs/blueprints/block-reason.md",
            "---\nstatus: active\n"
            "planning_registration:\n"
            "  status: exempt\n"
            "  reason: >\n"
            "    long reason text\n"
            "  owner: ops\n"
            "  expires: 2999-12-31\n"
            "---\nBody",
        )
        findings = check_plan.run_checks()
        invalid = [f for f in findings if f["code"] == check_plan.CODE_INVALID_EXCEPTION]
        assert len(invalid) == 1, f"Expected 1 invalid exception, got: {invalid}"
        assert invalid[0]["kind"] == "exempt_unsupported_scalar"
        assert "single-line scalar values only" in invalid[0]["suggestion"]

    def test_block_scalar_expires_is_invalid_exception(self):
        """expires: | must also trigger exempt_unsupported_scalar, not exempt_bad_date."""
        self.write_file(
            "docs/blueprints/block-expires.md",
            "---\nstatus: active\n"
            "planning_registration:\n"
            "  status: exempt\n"
            "  reason: temporary\n"
            "  owner: ops\n"
            "  expires: |\n"
            "    2999-12-31\n"
            "---\nBody",
        )
        findings = check_plan.run_checks()
        invalid = [f for f in findings if f["code"] == check_plan.CODE_INVALID_EXCEPTION]
        assert len(invalid) == 1
        assert invalid[0]["kind"] == "exempt_unsupported_scalar"

    def test_block_scalar_owner_is_invalid_exception(self):
        """owner: >- must trigger exempt_unsupported_scalar."""
        self.write_file(
            "docs/blueprints/block-owner.md",
            "---\nstatus: active\n"
            "planning_registration:\n"
            "  status: exempt\n"
            "  reason: temporary\n"
            "  owner: >-\n"
            "    ops\n"
            "  expires: 2999-12-31\n"
            "---\nBody",
        )
        findings = check_plan.run_checks()
        invalid = [f for f in findings if f["code"] == check_plan.CODE_INVALID_EXCEPTION]
        assert len(invalid) == 1
        assert invalid[0]["kind"] == "exempt_unsupported_scalar"

    def test_block_scalar_with_inline_comment_still_detected(self):
        """'> # comment' strips to '>' which must still be detected as unsupported scalar."""
        self.write_file(
            "docs/blueprints/block-with-comment.md",
            "---\nstatus: active\n"
            "planning_registration:\n"
            "  status: exempt\n"
            "  reason: > # fold scalar\n"
            "    long reason\n"
            "  owner: ops\n"
            "  expires: 2999-12-31\n"
            "---\nBody",
        )
        findings = check_plan.run_checks()
        invalid = [f for f in findings if f["code"] == check_plan.CODE_INVALID_EXCEPTION]
        assert len(invalid) == 1
        assert invalid[0]["kind"] == "exempt_unsupported_scalar"

    def test_block_scalar_does_not_enter_baseline(self):
        """build_baseline() must not include an exempt_unsupported_scalar finding."""
        self.write_file(
            "docs/blueprints/block-scalar.md",
            "---\nstatus: active\n"
            "planning_registration:\n"
            "  status: exempt\n"
            "  reason: >\n"
            "    long reason\n"
            "  owner: ops\n"
            "  expires: 2999-12-31\n"
            "---\nBody",
        )
        findings = check_plan.run_checks()
        baseline = check_plan.build_baseline(findings)
        assert baseline["entries"] == []


if __name__ == '__main__':
    unittest.main()
