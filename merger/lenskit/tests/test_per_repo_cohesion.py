import unittest
import tempfile
import shutil
import json
import sys
import os
from pathlib import Path

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))

from merger.lenskit.tests._test_constants import make_generator_info
from merger.lenskit.core.merge import write_reports_v2, ExtrasConfig, scan_repo
from merger.lenskit.core.citation_map import check_manifest_coherence_for_citation_map

# Bundle-level diagnostic/index artifacts produced alongside per-repo sidecars.
# Extend this tuple whenever a new bundle-scoped artifact suffix is introduced.
_BUNDLE_LEVEL_JSON_SUFFIXES = (
    ".dump_index.json",
    ".derived_index.json",
    ".retrieval_eval.json",
    ".bundle.manifest.json",
    ".output_health.json",
    ".graph_index.json",
)


def _is_bundle_level_json_artifact(path: Path) -> bool:
    return path.name.endswith(_BUNDLE_LEVEL_JSON_SUFFIXES)


class TestBundleLevelJsonFilter(unittest.TestCase):
    """Regression guard: ensures _is_bundle_level_json_artifact stays correct."""

    def test_known_bundle_suffixes_are_excluded(self):
        for suffix in _BUNDLE_LEVEL_JSON_SUFFIXES:
            self.assertTrue(
                _is_bundle_level_json_artifact(Path(f"artifact{suffix}")),
                f"Expected {suffix!r} to be classified as bundle-level",
            )

    def test_per_repo_sidecar_is_not_excluded(self):
        self.assertFalse(_is_bundle_level_json_artifact(Path("repoA-max-260505-0811_merge.json")))

    def test_graph_index_is_excluded(self):
        # Explicit regression guard: .graph_index.json was added after feedback.
        self.assertTrue(_is_bundle_level_json_artifact(Path("run-x.graph_index.json")))

    def test_output_health_is_excluded(self):
        # Explicit regression guard: .output_health.json was initially omitted.
        self.assertTrue(_is_bundle_level_json_artifact(Path("multi-max-260505-0811_merge.output_health.json")))


class TestPerRepoCohesion(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.hub = Path(self.test_dir) / "hub"
        self.hub.mkdir()

        # Setup repoA
        self.repoA = self.hub / "repoA"
        self.repoA.mkdir()
        (self.repoA / "fileA.txt").write_text("contentA", encoding="utf-8")

        # Setup repoB
        self.repoB = self.hub / "repoB"
        self.repoB.mkdir()
        (self.repoB / "fileB.txt").write_text("contentB", encoding="utf-8")

        self.merges_dir = Path(self.test_dir) / "merges"
        self.merges_dir.mkdir()

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_per_repo_artifact_cohesion(self):
        # Scan repos to get file infos
        summaryA = scan_repo(self.repoA)
        summaryB = scan_repo(self.repoB)

        repo_summaries = [summaryA, summaryB]

        extras = ExtrasConfig(json_sidecar=True)

        # Run write_reports_v2 in per-repo mode
        write_reports_v2(generator_info=make_generator_info(),
            merges_dir=self.merges_dir,
            hub=self.hub,
            repo_summaries=repo_summaries,
            detail="max",
            mode="pro-repo",
            max_bytes=1000,
            plan_only=False,
            output_mode="dual",
            extras=extras
        )

        # This test counts per-repo JSON sidecars only; bundle-level diagnostic/index artifacts are excluded.
        json_files = [p for p in self.merges_dir.glob("*.json")
                      if not _is_bundle_level_json_artifact(p)]
        # We expect 2 sidecars (one per repo).

        self.assertEqual(len(json_files), 2, f"Should have 2 JSON sidecars, found: {[p.name for p in json_files]}")

        sidecarA = None
        sidecarB = None

        # Identify which is which
        for jf in json_files:
            data = json.loads(jf.read_text(encoding="utf-8"))
            repos = data["meta"]["source_repos"]
            if "repoA" in repos:
                sidecarA = data
            elif "repoB" in repos:
                sidecarB = data

        self.assertIsNotNone(sidecarA, "repoA sidecar not found")
        self.assertIsNotNone(sidecarB, "repoB sidecar not found")

        # Check Cohesion for repoA
        # Artifacts should only contain repoA stuff
        for md_part in sidecarA["artifacts"]["md_parts_basenames"]:
            self.assertIn("repoA", md_part)
            self.assertNotIn("repoB", md_part)

        chunk_idx_A = sidecarA["artifacts"]["chunk_index_basename"]
        self.assertIsNotNone(chunk_idx_A)
        self.assertIn("repoA", chunk_idx_A)
        self.assertNotIn("repoB", chunk_idx_A)

        # Hardened check: Ensure no cross-contamination in the entire artifacts object
        artifacts_dump_A = json.dumps(sidecarA["artifacts"])
        self.assertNotIn("repoB", artifacts_dump_A)

        # Check Cohesion for repoB
        # Artifacts should only contain repoB stuff
        # This checks for LEAKAGE. If repoB sidecar references repoA md parts, this fails.
        for md_part in sidecarB["artifacts"]["md_parts_basenames"]:
            self.assertIn("repoB", md_part)
            self.assertNotIn("repoA", md_part)

        chunk_idx_B = sidecarB["artifacts"]["chunk_index_basename"]
        self.assertIsNotNone(chunk_idx_B)
        self.assertIn("repoB", chunk_idx_B)
        self.assertNotIn("repoA", chunk_idx_B)

        # Hardened check: Ensure no cross-contamination in the entire artifacts object
        artifacts_dump_B = json.dumps(sidecarB["artifacts"])
        self.assertNotIn("repoA", artifacts_dump_B)

    def test_pro_repo_multi_repo_skips_citation_map_for_incoherent_manifest(self):
        """Real Codex-P1 regression: pro-repo multi-repo aggregate must not crash and must skip citation map."""
        summaryA = scan_repo(self.repoA)
        summaryB = scan_repo(self.repoB)

        artifacts = write_reports_v2(
            generator_info=make_generator_info(),
            merges_dir=self.merges_dir,
            hub=self.hub,
            repo_summaries=[summaryA, summaryB],
            detail="max",
            mode="pro-repo",
            max_bytes=1000,
            plan_only=False,
            output_mode="dual",
            extras=ExtrasConfig(json_sidecar=True),
        )

        self.assertIsNotNone(artifacts.bundle_manifest)
        self.assertTrue(artifacts.bundle_manifest.exists())

        coherence = check_manifest_coherence_for_citation_map(artifacts.bundle_manifest)
        self.assertFalse(coherence.coherent)
        self.assertTrue(coherence.skip_allowed)
        self.assertEqual(coherence.reason, "range_file_path_mismatch")

        manifest = json.loads(artifacts.bundle_manifest.read_text(encoding="utf-8"))
        roles = [a.get("role") for a in manifest.get("artifacts", []) if isinstance(a, dict)]
        self.assertNotIn("citation_map_jsonl", roles)

        aggregate_citation_path = artifacts.bundle_manifest.with_name(
            artifacts.bundle_manifest.name.replace(
                ".bundle.manifest.json", ".citation_map.jsonl"
            )
        )
        self.assertFalse(aggregate_citation_path.exists())

if __name__ == '__main__':
    unittest.main()
