"""Frozen longitudinal study bundles survive publisher rotation (synthetic only)."""
from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from merger.repoground.core import agent_study as study
from tools.agent_study_freeze_snapshots import freeze

TASKSET = Path(__file__).resolve().parents[1] / "docs/retrieval/repoground_agent_study_cases.v1.json"


class StudySnapshotFreezeTest(unittest.TestCase):
    def test_archived_snapshot_roles_and_hashes_survive_publisher_cleanup(self):
        taskset = json.loads(TASKSET.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            published = root / "publisher"
            published.mkdir()
            snapshots = {}
            for name, entry in taskset["repositories"].items():
                source = published / name
                (source / "artifacts").mkdir(parents=True)
                role = source / "artifacts" / "reader.md"
                role.write_text("immutable bytes: " + name, encoding="utf-8")
                health = source / "post-health.json"
                health.write_text(json.dumps({"status": "pass"}), encoding="utf-8")
                manifest = source / "snapshot.bundle.manifest.json"
                raw = json.dumps({
                    "kind": "repoground.bundle.manifest",
                    "generator": {"runtime": {
                        "git_commit": "a" * 40, "git_dirty": False,
                    }},
                    "snapshot_provenance": {"repositories": [{
                        "repo_remote": "https://github.com/" + entry["slug"] + ".git",
                        "git_commit": entry["commit"],
                        "git_dirty": False,
                        "provenance_status": "present",
                    }]},
                    "links": {
                        "post_emit_health_path": health.name,
                        "agent_export_gate_status": "pass",
                        "bundle_surface_validation_status": "pass",
                    },
                    "artifacts": [{"path": "artifacts/reader.md",
                                   "sha256": hashlib.sha256(role.read_bytes()).hexdigest()}],
                }, sort_keys=True).encode("utf-8")
                manifest.write_bytes(raw)
                snapshots[name] = {
                    "source_commit": entry["commit"], "generator_commit": "a" * 40,
                    "health": "pass", "manifest_path": str(manifest),
                    "manifest_sha256": hashlib.sha256(raw).hexdigest(),
                }
            archive = root / "study-freeze"
            frozen = freeze(taskset, snapshots, archive)
            self.assertEqual(set(frozen["snapshots"]), set(taskset["repositories"]))
            self.assertEqual(
                json.loads((archive / "frozen-index.json").read_text())["taskset_sha256"],
                study.sha256_json(taskset),
            )
            for name, value in frozen["snapshots"].items():
                path = Path(value["manifest_path"])
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),
                                 snapshots[name]["manifest_sha256"])
                self.assertEqual(
                    (path.parent / "artifacts" / "reader.md").read_text(),
                    "immutable bytes: " + name,
                )
            shutil.rmtree(published)
            self.assertEqual(study._check_snapshots(
                taskset, json.loads((archive / "snapshots.json").read_text()),
            ), study._check_snapshots(taskset, frozen["snapshots"]))
            with self.assertRaisesRegex(study.AgentBenchmarkError, "new directory"):
                freeze(taskset, frozen["snapshots"], archive)

    def test_missing_manifest_rejects_before_creating_archive(self):
        taskset = json.loads(TASKSET.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            snapshots = {name: {
                "source_commit": entry["commit"], "generator_commit": "a" * 40,
                "manifest_path": str(root / "missing.manifest.json"),
                "manifest_sha256": "b" * 64, "health": "pass",
            } for name, entry in taskset["repositories"].items()}
            archive = root / "must-not-create"
            with self.assertRaisesRegex(study.AgentBenchmarkError, "unavailable"):
                freeze(taskset, snapshots, archive)
            self.assertFalse(archive.exists())


if __name__ == "__main__":
    unittest.main()
