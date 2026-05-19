import unittest
import tempfile
import shutil
import yaml
import json
from pathlib import Path

# Legacy path setup removed - handled by pytest.ini pythonpath=.
# sys.path.append(os.path.abspath("merger/repoLens"))

from merger.lenskit.adapters.metarepo import sync_from_metarepo
from merger.lenskit.core.merge import HealthCollector

class TestMetarepoSync(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.hub = self.test_dir / "hub"
        self.hub.mkdir()

        # Setup metarepo
        self.metarepo = self.hub / "metarepo"
        self.metarepo.mkdir()
        (self.metarepo / "sync").mkdir()

        # Setup target repo
        self.target = self.hub / "target-repo"
        self.target.mkdir()
        (self.target / ".git").mkdir() # Mark as valid repo

        # Create source file
        self.src_file = self.metarepo / "config.yml"
        self.src_file.write_text("# managed-by: metarepo-sync\nkey: value", encoding="utf-8")

        # Create manifest
        manifest = {
            "version": 1,
            "managed_marker": "managed-by: metarepo-sync",
            "entries": [
                {
                    "id": "config-test",
                    "source": "config.yml",
                    "targets": ["config.yml"],
                    "mode": "copy"
                }
            ]
        }
        with (self.metarepo / "sync/metarepo-sync.yml").open("w") as f:
            yaml.dump(manifest, f)

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_sync_dry_run(self):
        report = sync_from_metarepo(self.hub, mode="dry_run")

        self.assertEqual(report["status"], "ok")
        repo_res = report["repos"]["target-repo"]
        self.assertEqual(repo_res["status"], "ok") # Implicit from shape check passing

        summary = repo_res["summary"]
        self.assertEqual(summary["add"], 1)
        self.assertEqual(summary["update"], 0)

        # Verify file not created
        self.assertFalse((self.target / "config.yml").exists())

        # Verify report written
        out_report = self.target / ".gewebe/out/sync.report.json"
        self.assertTrue(out_report.exists())

    def test_sync_apply_update_backup(self):
        # 1. Create file first (dry run would ADD)
        (self.target / "config.yml").write_text("# managed-by: metarepo-sync\nold: value", encoding="utf-8")

        # 2. Run apply
        report = sync_from_metarepo(self.hub, mode="apply")

        summary = report["repos"]["target-repo"]["summary"]
        self.assertEqual(summary["update"], 1)

        # 3. Verify content updated
        content = (self.target / "config.yml").read_text(encoding="utf-8")
        self.assertIn("key: value", content)

        # 4. Verify backup created
        backups = list(self.target.glob("config.yml.bak.*"))
        self.assertEqual(len(backups), 1)

    def test_sync_blocked_no_marker(self):
        # Create user file without marker
        (self.target / "config.yml").write_text("user: custom", encoding="utf-8")

        report = sync_from_metarepo(self.hub, mode="dry_run")
        summary = report["repos"]["target-repo"]["summary"]
        self.assertEqual(summary["blocked"], 1)

        details = report["repos"]["target-repo"]["details"][0]
        self.assertEqual(details["action"], "BLOCKED")

    def test_health_collector_warn_on_error(self):
        # Manually create an error report
        err_report = {
            "status": "error",
            "mode": "apply",
            "summary": {"add": 0, "update": 0, "skip": 0, "blocked": 0, "error": 1},
            "details": []
        }
        out_dir = self.target / ".gewebe/out"
        out_dir.mkdir(parents=True)
        with (out_dir / "sync.report.json").open("w") as f:
            json.dump(err_report, f)

        # Analyze
        hc = HealthCollector(hub_path=self.hub)
        health = hc.analyze_repo("target-repo", [])

        self.assertEqual(health.meta_sync_status, "warn")

if __name__ == '__main__':
    unittest.main()
