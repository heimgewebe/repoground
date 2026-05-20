# -*- coding: utf-8 -*-
import unittest
import sys
import os
import unicodedata
import tempfile
import shutil
from pathlib import Path

# Add merger/ to sys.path so lenskit is importable
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from lenskit.core.merge import (
    _slug_token,
    classify_file_v2,
    _generate_run_id,
    make_output_filename,
    determine_inclusion_status,
    iter_report_blocks,
    FileInfo
)

class TestMergeCore(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_slug_token(self):
        self.assertEqual(_slug_token("Foo Bar"), "foo-bar")
        self.assertEqual(_slug_token("path/to/file.txt"), "path-to-file-txt")
        self.assertEqual(_slug_token("UPPERCASE"), "uppercase")
        self.assertEqual(_slug_token("mixed_CASE/123"), "mixed-case-123")

    def test_slug_token_nfc_normalization(self):
        """Ensure NFC and NFD strings result in the same slug."""
        # 'u' with diaeresis: \u00fc (NFC) vs \u0075\u0308 (NFD)
        nfc_str = "t\u00fcst" # tüst
        nfd_str = unicodedata.normalize("NFD", nfc_str)

        self.assertNotEqual(nfc_str, nfd_str) # Confirm raw strings differ
        self.assertEqual(_slug_token(nfc_str), _slug_token(nfd_str))

        # Check invariants: lowercase, no special chars, deterministic
        slug = _slug_token(nfc_str)
        self.assertRegex(slug, r"^[a-z0-9-]+$")
        # Assuming simple romanization or stripping, it should contain base chars
        # For "tüst" -> "t-st" (if non-alnum stripped) or "tust" (if normalized to ascii)
        # The current implementation strips non-alnum. NFC 'ü' is non-alnum in regex [^a-z0-9] unless locale dependent.
        # But crucially, it must be stable.

    def test_classify_file_v2(self):
        # Category: Source
        cat, tags = classify_file_v2(Path("src/main.py"), ".py")
        self.assertEqual(cat, "source")
        self.assertNotIn("script", tags)

        # Category: Config
        cat, tags = classify_file_v2(Path("package.json"), ".json")
        self.assertEqual(cat, "config")

        # Category: Doc
        cat, tags = classify_file_v2(Path("README.md"), ".md")
        self.assertEqual(cat, "doc")
        self.assertIn("ai-context", tags) # readme.md is strictly tagged as ai-context

        # Tag: CI
        cat, tags = classify_file_v2(Path(".github/workflows/test.yml"), ".yml")
        self.assertEqual(cat, "config")
        self.assertIn("ci", tags)

        # Tag: Script
        cat, tags = classify_file_v2(Path("scripts/deploy.sh"), ".sh")
        self.assertEqual(cat, "source")
        self.assertIn("script", tags)

    def test_generate_run_id(self):
        # Basic determinism
        rid1 = _generate_run_id(["repo1"], "dev", None, None, timestamp="250101-1200")
        rid2 = _generate_run_id(["repo1"], "dev", None, None, timestamp="250101-1200")
        self.assertEqual(rid1, rid2)
        self.assertIn("repo1", rid1)
        self.assertIn("dev", rid1)
        self.assertIn("250101-1200", rid1)

        # Multi-repo
        rid_multi = _generate_run_id(["repo1", "repo2"], "max", None, None, timestamp="250101-1200")
        self.assertIn("multi-", rid_multi)
        self.assertIn("max", rid_multi)

    def test_determine_inclusion_status(self):
        # Mock FileInfo
        fi = FileInfo(
            root_label="root",
            abs_path=Path("fake"),
            rel_path=Path("fake"),
            size=100,
            is_text=True,
            md5="abc",
            category="source",
            tags=[],
            ext=".py"
        )

        # Max profile -> full
        self.assertEqual(determine_inclusion_status(fi, "max", 0), "full")

        # Dev profile, source file -> full
        self.assertEqual(determine_inclusion_status(fi, "dev", 0), "full")

        # Dev profile, other file -> meta-only
        fi.category = "other"
        self.assertEqual(determine_inclusion_status(fi, "dev", 0), "meta-only")

        # Size limit (0 means unlimited)
        fi.size = 20000000
        self.assertEqual(determine_inclusion_status(fi, "max", 0), "full")

        # Binary file
        fi.is_text = False
        self.assertEqual(determine_inclusion_status(fi, "max", 0), "omitted")

    def test_unbound_local_error_regression(self):
        """
        Regression test for UnboundLocalError when text_files_count > 0.
        Ensures content_present/manifest_present/structure_present are always defined.
        """
        fi = FileInfo(
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

        # We need at least one text file to trigger the else-branch avoidance in legacy code
        files = [fi]
        sources = [Path("/tmp/test_repo")]

        # Should not raise UnboundLocalError
        iterator = iter_report_blocks(
            files=files,
            level="dev",
            max_file_bytes=1000,
            sources=sources,
            plan_only=False,
            debug=False
        )

        captured_meta = []
        try:
            # Consume only until @meta:end to avoid FS access (or full iteration)
            for block in iterator:
                captured_meta.append(block)
                if "@meta:end" in block:
                    break
        except UnboundLocalError:
            self.fail("iter_report_blocks raised UnboundLocalError! Fix is likely inactive or broken.")

        # Verify content correctness (flags present in YAML)
        full_output = "".join(captured_meta)
        if "# YAML support missing" not in full_output:
            self.assertRegex(full_output, r"content_present:\s*(true|True)")
            self.assertRegex(full_output, r"manifest_present:\s*(true|True)")
            self.assertRegex(full_output, r"structure_present:\s*(true|True)")

    def test_make_output_filename_optimization(self):
        """
        Verify that make_output_filename omits default 'full' mode block
        to produce cleaner filenames.
        """
        merges_dir = Path("/tmp/merges")

        # Case 1: Default mode (full) -> should NOT contain 'full'
        p1 = make_output_filename(
            merges_dir=merges_dir,
            repo_names=["myrepo"],
            detail="max",
            part_suffix="",
            path_filter=None,
            ext_filter=None,
            plan_only=False,
            code_only=False,
            timestamp="TS"
        )
        # Expected: myrepo-max-TS_merge.md (no 'full')
        self.assertEqual(p1.name, "myrepo-max-TS_merge.md")

        # Robust check: split by hyphen to ensure "full" is not present as a standalone token
        # This protects against false negatives if repo name was "fullstack"
        tokens = p1.stem.replace("_merge", "").split("-")
        self.assertNotIn("full", tokens)

        # Case 2: Plan-only mode -> MUST contain 'plan-only'
        p2 = make_output_filename(
            merges_dir=merges_dir,
            repo_names=["myrepo"],
            detail="dev",
            part_suffix="",
            path_filter=None,
            ext_filter=None,
            plan_only=True,
            code_only=False,
            timestamp="TS"
        )
        self.assertIn("plan-only", p2.name)
        # Expected: myrepo-plan-only-dev-TS_merge.md
        self.assertEqual(p2.name, "myrepo-plan-only-dev-TS_merge.md")

        # Case 3: Explicit Code-only -> MUST contain 'code-only'
        p3 = make_output_filename(
            merges_dir=merges_dir,
            repo_names=["myrepo"],
            detail="max",
            part_suffix="",
            path_filter=None,
            ext_filter=None,
            plan_only=False,
            code_only=True,
            timestamp="TS"
        )
        self.assertEqual(p3.name, "myrepo-code-only-max-TS_merge.md")

        # Case 4: Meta-None mode -> MUST contain 'none'
        # Note: meta_none overrides plan_only/code_only
        p4 = make_output_filename(
            merges_dir=merges_dir,
            repo_names=["myrepo"],
            detail="max",
            part_suffix="",
            path_filter=None,
            ext_filter=None,
            plan_only=False,
            code_only=False,
            timestamp="TS",
            meta_none=True
        )
        self.assertEqual(p4.name, "myrepo-none-max-TS_merge.md")

    def test_link_integrity_and_anchors(self):
        """
        Check that file blocks emit correct double anchors (HTML + Heading)
        and that fragment IDs are robust.
        """
        # Create a real file to avoid OSError
        dummy_path = Path(self.test_dir) / "my-file.txt"
        dummy_path.write_text("test content", encoding="utf-8")

        fi = FileInfo(
            root_label="my-repo",
            abs_path=dummy_path,
            rel_path=Path("src/My File.txt"), # Space in path
            size=100,
            is_text=True,
            md5="d41d8cd98f00b204e9800998ecf8427e",
            category="source",
            tags=[],
            ext=".txt",
            content="test content",
            inclusion_reason="normal"
        )

        files = [fi]
        sources = [Path(self.test_dir)]

        iterator = iter_report_blocks(
            files=files,
            level="max",
            max_file_bytes=1000,
            sources=sources,
            plan_only=False
        )

        full_report = "".join(list(iterator))

        # 1. Check for double anchors

        # Verify slug generation invariants
        slug_rel = _slug_token("src/My File.txt")
        slug_repo = _slug_token("my-repo")

        # Check invariants rather than hardcoded string
        self.assertRegex(slug_rel, r"^[a-z0-9-]+$")
        self.assertTrue(slug_rel.endswith("txt"))
        self.assertRegex(slug_repo, r"^[a-z0-9-]+$")

        base_anchor = f"file-{slug_repo}-{slug_rel}"
        # We know md5 prefix is d41d8c
        full_anchor = f"{base_anchor}-d41d8c"

        # Check for HTML anchor tag (primary robustness mechanism)
        self.assertIn(f'<a id="{full_anchor}"></a>', full_report)

        # Check for visible heading (Option A style)
        self.assertIn("#### src/My File.txt", full_report)

        # Check for alias anchor (legacy/backward compatibility)
        self.assertIn(f'<a id="{base_anchor}"></a>', full_report)

    def test_extras_config_from_csv(self):
        from lenskit.core.merge import ExtrasConfig

        # 1. Normal case
        csv = "health, delta_reports, json_sidecar"
        config, warnings = ExtrasConfig.from_csv(csv)
        self.assertTrue(config.health)
        self.assertTrue(config.delta_reports)
        self.assertTrue(config.json_sidecar)
        self.assertFalse(config.organism_index)
        self.assertEqual(len(warnings), 0)

        # 2. Deprecation case
        csv = "ai_heatmap, health"
        config, warnings = ExtrasConfig.from_csv(csv)
        self.assertTrue(config.heatmap) # ai_heatmap -> heatmap
        self.assertTrue(config.health)
        self.assertEqual(len(warnings), 1)
        self.assertIn("Deprecated", warnings[0])
        self.assertIn("ai_heatmap", warnings[0])

        # 3. Unknown extra case
        csv = "unknown_thing, health"
        config, warnings = ExtrasConfig.from_csv(csv)
        self.assertTrue(config.health)
        self.assertEqual(len(warnings), 1)
        self.assertIn("Unknown extra 'unknown_thing' ignored", warnings[0])

        # 4. None/Empty case
        config, warnings = ExtrasConfig.from_csv(None)
        self.assertFalse(config.health)
        self.assertEqual(len(warnings), 0)

        config, warnings = ExtrasConfig.from_csv("none")
        self.assertFalse(config.health)
        self.assertEqual(len(warnings), 0)

        config, warnings = ExtrasConfig.from_csv("")
        self.assertFalse(config.health)
        self.assertEqual(len(warnings), 0)

class TestScanRepoWorktreeExclusion(unittest.TestCase):

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        # Normal repo content
        (self.root / "merger" / "lenskit" / "core").mkdir(parents=True)
        (self.root / "merger" / "lenskit" / "core" / "merge.py").write_text("# merge")
        # .claude settings — must be included
        (self.root / ".claude").mkdir()
        (self.root / ".claude" / "settings.local.json").write_text("{}")
        # Worktree artefacts — must be excluded
        (self.root / ".claude" / "worktrees" / "foo" / "merger" / "lenskit" / "core").mkdir(parents=True)
        (self.root / ".claude" / "worktrees" / "foo" / "merger" / "lenskit" / "core" / "merge.py").write_text("# worktree copy")

    def tearDown(self):
        shutil.rmtree(self.root)

    def _collected_relpaths(self, **kwargs):
        from lenskit.core.merge import scan_repo
        result = scan_repo(self.root, extensions=[".py", ".json"], **kwargs)
        return {str(f.rel_path).replace("\\", "/") for f in result["files"]}

    def test_scan_repo_excludes_worktree_files(self):
        paths = self._collected_relpaths()
        self.assertIn("merger/lenskit/core/merge.py", paths)
        self.assertIn(".claude/settings.local.json", paths)
        worktree_hits = [p for p in paths if p.startswith(".claude/worktrees/")]
        self.assertEqual(worktree_hits, [], msg=f"Unexpected worktree paths: {worktree_hits}")

    def test_scan_repo_include_hidden_true_still_excludes_worktrees(self):
        paths = self._collected_relpaths(include_hidden=True)
        self.assertIn(".claude/settings.local.json", paths)
        worktree_hits = [p for p in paths if p.startswith(".claude/worktrees/")]
        self.assertEqual(worktree_hits, [], msg=f"include_hidden=True must not resurrect worktrees: {worktree_hits}")


class TestPrescanRepoWorktreeExclusion(unittest.TestCase):

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / "merger" / "lenskit" / "core").mkdir(parents=True)
        (self.root / "merger" / "lenskit" / "core" / "merge.py").write_text("# merge")
        (self.root / ".claude").mkdir()
        (self.root / ".claude" / "settings.local.json").write_text("{}")
        (self.root / ".claude" / "worktrees" / "foo" / "pkg").mkdir(parents=True)
        (self.root / ".claude" / "worktrees" / "foo" / "pkg" / "file.py").write_text("# wt")

    def tearDown(self):
        shutil.rmtree(self.root)

    def _tree_paths(self):
        from lenskit.core.merge import prescan_repo
        result = prescan_repo(self.root)
        paths = set()
        def _collect(node):
            for child in node.get("children", []):
                paths.add(child["path"])
                _collect(child)
        _collect(result["tree"])
        return paths

    def test_prescan_repo_excludes_worktree_subtree(self):
        paths = self._tree_paths()

        # Ensure the traversal is not vacuous: expected repo paths must be present
        self.assertIn("merger", paths, "Expected 'merger' in prescan tree")
        self.assertIn("merger/lenskit", paths, "Expected 'merger/lenskit' in prescan tree")
        self.assertIn("merger/lenskit/core", paths, "Expected 'merger/lenskit/core' in prescan tree")
        self.assertIn("merger/lenskit/core/merge.py", paths, "Expected 'merger/lenskit/core/merge.py' in prescan tree")
        self.assertIn(".claude", paths, "Expected '.claude' in prescan tree")
        self.assertIn(".claude/settings.local.json", paths, "Expected '.claude/settings.local.json' in prescan tree")

        # Worktree subtree must be absent
        worktree_hits = [p for p in paths if ".claude/worktrees" in p or p.startswith(".claude/worktrees")]
        self.assertEqual(worktree_hits, [], msg=f"prescan_repo must not include worktrees: {worktree_hits}")


class TestScanRepoCacheExclusion(unittest.TestCase):
    """Verify that local cache/tooling artifacts are excluded from scan output."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        # Normal repo content
        (self.root / "src").mkdir()
        (self.root / "src" / "app.py").write_text("# application code")

        # Cache directories that should be excluded
        (self.root / ".ruff_cache" / "0.15.13").mkdir(parents=True)
        (self.root / ".ruff_cache" / "0.15.13" / "cache.py").write_text("# ruff cache")
        (self.root / ".pytest_cache" / "v").mkdir(parents=True)
        (self.root / ".pytest_cache" / "v" / "cache.txt").write_text("pytest cache")
        (self.root / ".mypy_cache" / "3.11").mkdir(parents=True)
        (self.root / ".mypy_cache" / "3.11" / "cache.py").write_text("# mypy cache")
        (self.root / "__pycache__").mkdir()
        (self.root / "__pycache__" / "cache.py").write_text("# pycache")

    def tearDown(self):
        shutil.rmtree(self.root)

    def _collected_relpaths(self, **kwargs):
        from lenskit.core.merge import scan_repo
        result = scan_repo(self.root, extensions=[".py", ".txt"], **kwargs)
        return {str(f.rel_path).replace("\\", "/") for f in result["files"]}

    def test_scan_repo_excludes_ruff_cache(self):
        """scan_repo should exclude .ruff_cache directory."""
        paths = self._collected_relpaths()
        self.assertIn("src/app.py", paths, "Normal source files must be included")
        
        ruff_hits = [p for p in paths if ".ruff_cache" in p]
        self.assertEqual(ruff_hits, [], msg=f"scan_repo must exclude .ruff_cache: {ruff_hits}")

    def test_scan_repo_excludes_pytest_cache(self):
        """scan_repo should exclude .pytest_cache directory."""
        paths = self._collected_relpaths()
        pytest_hits = [p for p in paths if ".pytest_cache" in p]
        self.assertEqual(pytest_hits, [], msg=f"scan_repo must exclude .pytest_cache: {pytest_hits}")

    def test_scan_repo_excludes_mypy_cache(self):
        """scan_repo should exclude .mypy_cache directory."""
        paths = self._collected_relpaths()
        mypy_hits = [p for p in paths if ".mypy_cache" in p]
        self.assertEqual(mypy_hits, [], msg=f"scan_repo must exclude .mypy_cache: {mypy_hits}")

    def test_scan_repo_excludes_pycache(self):
        """scan_repo should exclude __pycache__ directory."""
        paths = self._collected_relpaths()
        pycache_hits = [p for p in paths if "__pycache__" in p]
        self.assertEqual(pycache_hits, [], msg=f"scan_repo must exclude __pycache__: {pycache_hits}")


class TestPrescanRepoCacheExclusion(unittest.TestCase):
    """Verify that prescan_repo excludes local cache/tooling artifacts."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        # Normal repo content
        (self.root / "src").mkdir()
        (self.root / "src" / "app.py").write_text("# application code")

        # Cache directories that should be excluded
        (self.root / ".ruff_cache" / "0.15.13").mkdir(parents=True)
        (self.root / ".ruff_cache" / "0.15.13" / "cache.py").write_text("# ruff cache")
        (self.root / ".pytest_cache" / "v").mkdir(parents=True)
        (self.root / ".pytest_cache" / "v" / "cache.txt").write_text("pytest cache")
        (self.root / ".mypy_cache" / "3.11").mkdir(parents=True)
        (self.root / ".mypy_cache" / "3.11" / "cache.py").write_text("# mypy cache")
        (self.root / "__pycache__").mkdir()
        (self.root / "__pycache__" / "cache.py").write_text("# pycache")

    def tearDown(self):
        shutil.rmtree(self.root)

    def _tree_paths(self):
        from lenskit.core.merge import prescan_repo
        result = prescan_repo(self.root)
        paths = set()
        def _collect(node):
            for child in node.get("children", []):
                paths.add(child["path"])
                _collect(child)
        _collect(result["tree"])
        return paths

    def test_prescan_repo_excludes_cache_dirs(self):
        """prescan_repo should exclude all cache directories."""
        paths = self._tree_paths()

        # Ensure traversal is not vacuous
        self.assertIn("src", paths, "Expected 'src' in prescan tree")
        self.assertIn("src/app.py", paths, "Expected 'src/app.py' in prescan tree")

        # Cache directories must be absent
        cache_names = [".ruff_cache", ".pytest_cache", ".mypy_cache", "__pycache__"]
        for cache_dir in cache_names:
            cache_hits = [p for p in paths if cache_dir in p or p.startswith(cache_dir)]
            self.assertEqual(cache_hits, [],
                           msg=f"prescan_repo must exclude {cache_dir}: {cache_hits}")


class TestReportArtifactCacheExclusion(unittest.TestCase):
    """Verify generated report content does not surface excluded cache directories."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / "src").mkdir()
        (self.root / "src" / "app.py").write_text("print('ok')\n")

        (self.root / ".ruff_cache" / "0.15.13").mkdir(parents=True)
        (self.root / ".ruff_cache" / "0.15.13" / "cache.py").write_text("# ruff cache")
        (self.root / ".pytest_cache" / "v").mkdir(parents=True)
        (self.root / ".pytest_cache" / "v" / "cache.txt").write_text("pytest cache")
        (self.root / ".mypy_cache" / "3.11").mkdir(parents=True)
        (self.root / ".mypy_cache" / "3.11" / "cache.py").write_text("# mypy cache")
        (self.root / "__pycache__").mkdir()
        (self.root / "__pycache__" / "cache.py").write_text("# pycache")

    def tearDown(self):
        shutil.rmtree(self.root)

    def test_iter_report_blocks_excludes_cache_paths(self):
        from lenskit.core.merge import scan_repo

        summary = scan_repo(self.root, extensions=[".py", ".txt"], include_hidden=True)
        report = "".join(
            iter_report_blocks(
                files=summary["files"],
                level="max",
                max_file_bytes=0,
                sources=[self.root],
                plan_only=False,
                debug=False,
            )
        )

        self.assertIn("src/app.py", report)
        self.assertNotIn(".ruff_cache", report)
        self.assertNotIn(".pytest_cache", report)
        self.assertNotIn(".mypy_cache", report)
        self.assertNotIn("__pycache__", report)


if __name__ == '__main__':
    unittest.main()
