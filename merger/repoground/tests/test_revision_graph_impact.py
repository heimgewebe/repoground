"""Real Git commit and negative-gate tests for revision-bound graph impact."""
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from merger.repoground.core.delta_context import compile_revision_impact


class TestRevisionGraphImpact(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.git("init", "-q")
        self.write("mod.py", "def feature():\n    return 1\n")
        self.write("consumer.py", "from mod import feature\n\ndef invoke():\n    return feature()\n")
        self.write("tests/test_mod.py", "from mod import feature\n\ndef test_feature():\n    return feature()\n")
        self.write("compose.yml", "services:\n  api:\n    image: nginx\n")
        self.write("schemas/core.json", '{"type":"object"}\n')
        self.write("schemas/consumer.json", '{"$ref":"./core.json"}\n')
        self.write("untouched.py", "def untouched():\n    pass\n")
        self.git("add", ".")
        self.commit("base")
        self.base = self.git("rev-parse", "HEAD").strip()
        self.write("mod.py", "def feature():\n    return 2\n")
        self.write("compose.yml", "services:\n  api:\n    image: nginx\n  worker:\n    image: busybox\n")
        self.write("schemas/core.json", '{"type":"object","title":"Changed"}\n')
        self.git("add", ".")
        self.commit("head")
        self.head = self.git("rev-parse", "HEAD").strip()

    def write(self, path: str, content: str) -> None:
        target = self.root / path
        target.parent.mkdir(exist_ok=True, parents=True)
        target.write_text(content, encoding="utf-8")

    def git(self, *arguments: str) -> str:
        process = subprocess.run(
            ["git", "-C", str(self.root), *arguments],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            check=True, timeout=15, text=True,
        )
        return process.stdout

    def commit(self, message: str) -> None:
        self.git("-c", "user.name=RepoGround Test", "-c", "user.email=test@example.invalid",
                 "commit", "-qm", message)

    def report(self, **kwargs):
        return compile_revision_impact(
            repo_root=self.root, base_sha=self.base,
            head_sha=self.head, **kwargs,
        )

    def test_real_base_head_diff_and_precise_symbol_impacts(self):
        report = self.report()
        self.assertEqual("repobrief.revision_graph_impact", report["kind"])
        self.assertEqual((self.base, self.head),
                         (report["base_sha"], report["head_sha"]))
        self.assertEqual("bounded", report["status"])
        self.assertEqual(3, report["coverage"]["changed_files"])
        self.assertEqual(1, report["coverage"]["changed_symbols"])
        direct = report["directly_changed"]
        self.assertTrue(any(d.get("symbol_id") == "py:mod.py:function:feature"
                            and d["range_ref"] == "file:mod.py#L1-L2"
                            for d in direct))
        proven = report["potentially_affected"]
        self.assertTrue(any(p["source"]["path"] == "consumer.py"
                            and p["target_id"] == "py:mod.py:function:feature"
                            and p["relation"] == "calls" for p in proven))
        self.assertTrue(any(p["source"]["path"] == "schemas/consumer.json"
                            and p["target_id"] == "file:schemas/core.json"
                            and p["relation"] == "declares_contract" for p in proven))
        self.assertTrue(any(p["source"]["path"] == "tests/test_mod.py"
                            and p["relation"] == "tests" for p in proven))
        self.assertTrue(any(g["relation"] == "configures_service"
                            and g["source"]["path"] == "compose.yml"
                            for g in report["unresolved"]))
        self.assertEqual("tests/test_mod.py", report["expected_checks"][0]["path"])
        self.assertIn("test_sufficiency", report["does_not_establish"])
        self.assertEqual("derived_not_published",
                         report["source_provenance"]["manifest_identity"]["status"])
        self.assertFalse(report["source_provenance"]["manifest_identity"]["is_bundle_manifest"])
        self.assertRegex(report["diff_sha256"], r"^[0-9a-f]{64}$")

    def test_actual_git_diff_hash_and_repeated_byte_stability(self):
        left = self.report()
        right = self.report()
        self.assertEqual(json.dumps(left, sort_keys=True), json.dumps(right, sort_keys=True))
        real_diff = subprocess.check_output(
            ["git", "-C", str(self.root), "diff", "--no-ext-diff",
             "--no-textconv", "--no-color", "--unified=0",
             self.base, self.head, "--"],
            timeout=15,
        )
        import hashlib
        self.assertEqual(hashlib.sha256(real_diff).hexdigest(), left["diff_sha256"])

    def test_dirty_and_wrong_revision_rejected_without_mutation(self):
        self.write("untracked.txt", "untracked\n")
        with self.assertRaisesRegex(ValueError, "checkout_dirty"):
            self.report()
        (self.root / "untracked.txt").unlink()
        with self.assertRaisesRegex(ValueError, "checkout_head_not_requested"):
            compile_revision_impact(
                repo_root=self.root, base_sha=self.base, head_sha=self.base
            )
        self.assertEqual(self.head, self.git("rev-parse", "HEAD").strip())

    def test_changed_unreferenced_symbol_does_not_invent_dependents(self):
        original_head = self.head
        self.write("untouched.py", "def untouched():\n    return 99\n")
        self.git("add", "untouched.py")
        self.commit("unreferenced edit")
        next_head = self.git("rev-parse", "HEAD").strip()
        result = compile_revision_impact(
            repo_root=self.root, base_sha=original_head, head_sha=next_head,
        )
        self.assertTrue(any(
            row.get("symbol_id") == "py:untouched.py:function:untouched"
            for row in result["directly_changed"]
        ))
        self.assertEqual([], result["potentially_affected"])
        self.assertEqual([], result["expected_checks"])
        self.assertIn("complete_blast_radius", result["does_not_establish"])

    def test_tracked_dirty_change_is_rejected(self):
        self.write("mod.py", "def feature():\n    return 'unsaved'\n")
        with self.assertRaisesRegex(ValueError, "checkout_dirty_or_untracked"):
            self.report()

    def test_wrong_ancestor_and_malformed_sha_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "Git SHA"):
            compile_revision_impact(repo_root=self.root, base_sha="HEAD", head_sha=self.head)
        future = self.git(
            "-c", "user.name=RepoGround Test",
            "-c", "user.email=test@example.invalid",
            "commit-tree", self.head + "^{tree}", "-p", self.head,
            "-m", "future unreferenced commit",
        ).strip()
        with self.assertRaisesRegex(ValueError, "base_not_ancestor_of_head"):
            compile_revision_impact(repo_root=self.root, base_sha=future, head_sha=self.head)
        with self.assertRaisesRegex(ValueError, "max_items"):
            self.report(max_items=False)

    def test_bounded_impact_and_verified_report_contract(self):
        report = self.report(max_items=1)
        self.assertTrue(report["coverage"]["truncated"])
        self.assertEqual("truncated", report["status"])
        self.assertLessEqual(len(report["directly_changed"]), 1)
        self.assertLessEqual(len(report["potentially_affected"]), 1)
        self.assertEqual(2, len(self.report()["expected_checks"][0]["path"].split("/")))
        contract = (
            Path(__file__).parent.parent / "contracts" / "revision-graph-impact.v1.schema.json"
        )
        schema = json.loads(contract.read_text(encoding="utf-8"))
        self.assertEqual("repobrief.revision_graph_impact",
                         schema["properties"]["kind"]["const"])
        try:
            import jsonschema
        except ImportError:
            pass
        else:
            jsonschema.validate(report, schema)


if __name__ == "__main__":
    unittest.main()