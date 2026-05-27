import json
from pathlib import Path

import pytest

from merger.lenskit.core import merge
from merger.lenskit.core.merge import FileInfo, SKIP_DIRS, _BUILD_AND_CACHE_DIRS


def create_file_info(rel_path: str, category: str = "other", tags=None, content: str = "content") -> FileInfo:
    return FileInfo(
        root_label="test-repo",
        abs_path=Path("/tmp") / rel_path,
        rel_path=Path(rel_path),
        size=len(content),
        is_text=True,
        md5="md5sum",
        category=category,
        tags=tags or [],
        ext=Path(rel_path).suffix,
        content=content,
        inclusion_reason="normal",
    )


def test_path_filter_hard_include_excludes_critical_files():
    """
    path_filter wirkt als harter Include-Filter für Manifest und Content:
    - Nur matching paths werden aufgenommen
    - Auch "critical" files (README, workflows) fliegen raus, wenn sie nicht matchen
    """
    files = [
        create_file_info("docs/adr/001-decision.md", category="doc", tags=["adr"]),
        create_file_info("README.md", category="doc", tags=["ai-context"]),  # "critical"
        create_file_info(".github/workflows/main.yml", category="config", tags=["ci"]),  # "critical"
    ]

    report = "".join(
        merge.iter_report_blocks(
            files=files,
            level="max",
            max_file_bytes=0,
            sources=[Path("/tmp/test-repo")],
            plan_only=False,
            path_filter="docs/adr",
            meta_density="standard",
        )
    )

    # Positive: ADR-File wird wirklich gerendert (stabiler Marker: File-Block Path-Zeile)
    assert "**Path:** `docs/adr/001-decision.md`" in report

    # Negative: Nicht-matching "critical" files dürfen NICHT gerendert werden
    assert "**Path:** `README.md`" not in report
    assert "**Path:** `.github/workflows/main.yml`" not in report


def test_meta_density_min_gates_hotspots_and_reading_lenses_everywhere(monkeypatch):
    """
    meta_density='min' muss Hotspots (Plan) und Reading Lenses deaktivieren.
    Deterministisch via monkeypatch: build_hotspots liefert garantiert etwas,
    damit wir das Gate testen (nicht die Heuristik).
    """
    files = [
        create_file_info("src/main.py", category="source", tags=["entrypoint"]),
        create_file_info("docs/readme.md", category="doc"),
    ]

    def fake_build_hotspots(_processed_files, **kwargs):
        return ["### Hotspots (Einstiegspunkte)\n- fake\n"]

    monkeypatch.setattr(merge, "build_hotspots", fake_build_hotspots)

    report = "".join(
        merge.iter_report_blocks(
            files=files,
            level="max",
            max_file_bytes=0,
            sources=[Path("/tmp/test-repo")],
            plan_only=False,
            meta_density="min",
        )
    )

    # Content ist da
    assert "**Path:** `src/main.py`" in report

    # Gate muss greifen
    assert "Hotspots (Einstiegspunkte)" not in report
    assert "Reading Lenses" not in report


def test_meta_density_standard_allows_hotspots(monkeypatch):
    """
    Kontrolltest: meta_density='standard' darf Hotspots zulassen.
    Wieder deterministisch: build_hotspots wird gepatcht.
    """
    files = [create_file_info("src/main.py", category="source", tags=["entrypoint"])]

    def fake_build_hotspots(_processed_files, **kwargs):
        return ["### Hotspots (Einstiegspunkte)\n- fake\n"]

    monkeypatch.setattr(merge, "build_hotspots", fake_build_hotspots)

    report = "".join(
        merge.iter_report_blocks(
            files=files,
            level="max",
            max_file_bytes=0,
            sources=[Path("/tmp/test-repo")],
            plan_only=False,
            meta_density="standard",
        )
    )

    assert "Hotspots (Einstiegspunkte)" in report


def test_auto_warning_only_on_actual_auto_downgrade():
    """
    Auto-Warnung nur wenn auto -> standard wegen Filtern.
    Fälle:
    1) auto + filter -> Warnung
    2) standard + filter -> KEINE Warnung
    3) auto ohne filter -> KEINE Warnung
    """
    files = [create_file_info("test.txt")]

    # 1) Auto + Filter -> Warning
    report1 = "".join(
        merge.iter_report_blocks(
            files=files,
            level="max",
            max_file_bytes=0,
            sources=[],
            plan_only=False,
            path_filter="test",
            meta_density="auto",
        )
    )
    assert "⚠️ **Auto-Drosselung:**" in report1

    # 2) Standard + Filter -> No Warning
    report2 = "".join(
        merge.iter_report_blocks(
            files=files,
            level="max",
            max_file_bytes=0,
            sources=[],
            plan_only=False,
            path_filter="test",
            meta_density="standard",
        )
    )
    assert "⚠️ **Auto-Drosselung:**" not in report2

    # 3) Auto ohne Filter -> No Warning (auto resolves to full, no downgrade)
    report3 = "".join(
        merge.iter_report_blocks(
            files=files,
            level="max",
            max_file_bytes=0,
            sources=[],
            plan_only=False,
            meta_density="auto",
        )
    )
    assert "⚠️ **Auto-Drosselung:**" not in report3


# ── A2: Output Noise Hygiene tests ───────────────────────────────────────────

@pytest.mark.parametrize("rel_path", [
    ".pytest_cache/v/cache/lastfailed",
    ".mypy_cache/3.11/builtins.json",
    ".ruff_cache/0.1.0/CACHEDIR.TAG",
    ".cache/pip/wheels/something.whl",
    "__pycache__/module.cpython-311.pyc",
    "coverage/html/index.html",
    "node_modules/lodash/index.js",
])
def test_is_noise_file_returns_true_for_cache_paths(rel_path):
    fi = create_file_info(rel_path)
    assert merge.is_noise_file(fi), f"Expected is_noise_file=True for {rel_path}"


@pytest.mark.parametrize("rel_path", [
    ".github/workflows/ci.yml",
    ".github/CODEOWNERS",
    ".wgx/config.yml",
    ".wgx/agents/main.py",
    ".ai-context.yml",
    "src/main.py",
    "README.md",
])
def test_is_noise_file_returns_false_for_intentional_hidden_paths(rel_path):
    fi = create_file_info(rel_path)
    assert not merge.is_noise_file(fi), f"Expected is_noise_file=False for {rel_path}"


def test_is_noise_file_does_not_match_false_positives_with_substring_names():
    """
    Verify that is_noise_file() uses path-component matching, not substring matching.
    Paths like src/mycoverage/file.md should NOT be noise even though "coverage" is
    in _BUILD_AND_CACHE_DIRS, because "coverage" is not an actual directory component.
    """
    false_positives = [
        "src/mycoverage/report.md",  # contains "coverage" as substring but not as component
        "src/rebuild/tool.py",  # contains "build" as substring but not as component
        "src/distributions/file.txt",  # contains "dist" as substring but not as component
    ]
    for rel_path in false_positives:
        fi = create_file_info(rel_path)
        assert not merge.is_noise_file(fi), (
            f"Path {rel_path} should NOT be noise: "
            f"'coverage'/'build'/'dist' are substrings, not actual directory components"
        )


def test_build_and_cache_dirs_are_single_source_of_truth():
    """_BUILD_AND_CACHE_DIRS is the canonical set; SKIP_DIRS is derived from it."""
    assert _BUILD_AND_CACHE_DIRS <= SKIP_DIRS
    # SKIP_DIRS adds .git, .idea, .DS_Store (traversal-skip only, no is_noise_file semantic)


@pytest.mark.parametrize("dir_name", sorted(_BUILD_AND_CACHE_DIRS))
def test_every_build_and_cache_dir_is_noise_and_skipped(dir_name, tmp_path):
    """
    Property test: for EVERY entry in _BUILD_AND_CACHE_DIRS, both surfaces must agree:
      1. is_noise_file() returns True for a file under that directory
      2. scan_repo() skips that directory at traversal time (SKIP_DIRS coverage)

    This is the structural anti-drift guard: if a new entry is added to
    _BUILD_AND_CACHE_DIRS but, for any reason, one of the two consumers stops
    using it, this parametrized test fails for that specific entry.
    """
    # Part 1: is_noise_file must classify a file under <dir_name>/ as noise
    fi = create_file_info(f"{dir_name}/some_file.txt")
    assert merge.is_noise_file(fi), (
        f"is_noise_file must return True for path under '{dir_name}/' "
        f"(it is in _BUILD_AND_CACHE_DIRS but is_noise_file did not recognise it)"
    )

    # Part 2: scan_repo must skip <dir_name> at traversal time
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("def main(): pass")
    target = tmp_path / dir_name / "nested"
    target.mkdir(parents=True)
    (target / "noise_file.txt").write_text("noise payload")

    result = merge.scan_repo(tmp_path, include_hidden=True, calculate_md5=False)
    found_paths = {str(fi_.rel_path).replace("\\", "/") for fi_ in result["files"]}

    assert "src/main.py" in found_paths, "real source must survive scan_repo"
    assert not any(p.startswith(f"{dir_name}/") for p in found_paths), (
        f"scan_repo must skip '{dir_name}/' (it is in _BUILD_AND_CACHE_DIRS / SKIP_DIRS); "
        f"leaked paths: {sorted(p for p in found_paths if p.startswith(f'{dir_name}/'))}"
    )


def test_manifest_annotates_noise_files_that_bypass_traversal():
    """
    is_noise_file() annotates files as (noise) in the manifest.
    Primary protection is SKIP_DIRS at scan_repo() traversal time; this test covers
    belt-and-suspenders manifest annotation for files that are explicitly passed
    to iter_report_blocks() (e.g. in plan-only or test contexts).
    """
    files = [
        create_file_info(".pytest_cache/v/cache/lastfailed", content="{}"),
        create_file_info("src/main.py", content="# code"),
    ]
    report = "".join(
        merge.iter_report_blocks(
            files=files,
            level="max",
            max_file_bytes=100_000,
            sources=[Path("/tmp/test-repo")],
            plan_only=False,
            meta_density="standard",
        )
    )
    assert "(noise)" in report, "Expected (noise) annotation for cache file in manifest"


def test_scan_repo_excludes_cache_dirs(tmp_path):
    """
    scan_repo() must not return files from any cache/tool directory.
    This proves the real output surface (canonical_md, chunk_index) is clean:
    those surfaces are built from scan_repo() results, so if cache dirs are
    excluded here they cannot appear in any generated content.
    """
    # Create real directory structure with noise and signal files
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("def main(): pass")
    (tmp_path / ".pytest_cache" / "v" / "cache").mkdir(parents=True)
    (tmp_path / ".pytest_cache" / "v" / "cache" / "lastfailed").write_text("{}")
    (tmp_path / ".mypy_cache" / "3.11").mkdir(parents=True)
    (tmp_path / ".mypy_cache" / "3.11" / "builtins.json").write_text("{}")
    (tmp_path / ".ruff_cache").mkdir()
    (tmp_path / ".ruff_cache" / "CACHEDIR.TAG").write_text("Signature: 8a477f597d28d172789f06886806bc55")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "main.cpython-311.pyc").write_bytes(b"\x00")
    (tmp_path / ".cache").mkdir()
    (tmp_path / ".cache" / "pip_wheels").write_text("dummy")
    (tmp_path / "coverage").mkdir()
    (tmp_path / "coverage" / "lcov.info").write_text("TN:")

    result = merge.scan_repo(tmp_path, include_hidden=True)
    found_paths = {str(fi.rel_path).replace("\\", "/") for fi in result["files"]}

    assert "src/main.py" in found_paths, "Real source file must be present"
    for noise_path in (
        ".pytest_cache/v/cache/lastfailed",
        ".mypy_cache/3.11/builtins.json",
        ".ruff_cache/CACHEDIR.TAG",
        "__pycache__/main.cpython-311.pyc",
        ".cache/pip_wheels",
        "coverage/lcov.info",
    ):
        assert noise_path not in found_paths, f"Cache path must not appear in scan result: {noise_path}"


def test_scan_repo_preserves_intentional_hidden_paths(tmp_path):
    """
    scan_repo() with include_hidden=True must include .github/, .wgx/, and
    .ai-context.yml — these carry real CI/repo context and must not be
    broadly filtered by noise logic.
    """
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "ci.yml").write_text("on: push")
    (tmp_path / ".wgx").mkdir()
    (tmp_path / ".wgx" / "config.yml").write_text("agent: true")
    (tmp_path / ".ai-context.yml").write_text("role: repo")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("def main(): pass")

    result = merge.scan_repo(tmp_path, include_hidden=True)
    found_paths = {str(fi.rel_path).replace("\\", "/") for fi in result["files"]}

    assert ".github/workflows/ci.yml" in found_paths
    assert ".wgx/config.yml" in found_paths
    assert ".ai-context.yml" in found_paths


def test_noise_dirs_absent_from_generated_bundle_surfaces(tmp_path):
    """
    Integration test: bundle surfaces (canonical_md, chunk_index) generated via
    write_reports_v2() must not contain content from cache/noise dirs.

    This closes the A2 proof gap: not just 'scan_repo() is clean' but
    'the generated canonical markdown and chunk index are also clean'.

    Focuses on the two directories newly added by A2 (.cache, coverage),
    plus the existing ones.

    Direct assertions:
    - canonical_md: no noise dir content, no noise file paths (excepting source /coverage as user file)
    - chunk_index JSONL: no noise dir content, no noise dir names in file_path fields
    - Both surfaces: required source file and hidden context files present

    Hidden-context preservation (.github, .wgx, .ai-context.yml) is also proven
    here (not delegated to test_scan_repo_preserves_intentional_hidden_paths).
    """
    from merger.lenskit.core.merge import write_reports_v2, ExtrasConfig

    repo = tmp_path / "repo"
    out_dir = tmp_path / "out"
    repo.mkdir()
    out_dir.mkdir()

    # Real source file
    (repo / "src").mkdir()
    (repo / "src" / "main.py").write_text("def main(): pass\n", encoding="utf-8")

    # Intentional hidden context (must survive to output)
    (repo / ".github" / "workflows").mkdir(parents=True)
    (repo / ".github" / "workflows" / "ci.yml").write_text("name: ci\n", encoding="utf-8")
    (repo / ".wgx").mkdir()
    (repo / ".wgx" / "config.yml").write_text("agent: true\n", encoding="utf-8")
    (repo / ".ai-context.yml").write_text("role: repo\n", encoding="utf-8")

    # Noise dirs — A2-new entries get distinct sentinels for precise assertions
    sentinels = {
        ".cache": "LENSKIT_TEST_SENTINEL_DOTCACHE_SHOULD_NOT_APPEAR\n",
        "coverage": "LENSKIT_TEST_SENTINEL_COVERAGE_SHOULD_NOT_APPEAR\n",
    }
    (repo / ".cache").mkdir()
    (repo / ".cache" / "pip_wheels.txt").write_text(sentinels[".cache"], encoding="utf-8")
    (repo / "coverage").mkdir()
    (repo / "coverage" / "lcov.info").write_text(sentinels["coverage"], encoding="utf-8")

    summary = merge.scan_repo(repo, include_hidden=True, calculate_md5=True)
    artifacts = write_reports_v2(
        merges_dir=out_dir,
        hub=tmp_path,
        repo_summaries=[summary],
        detail="max",
        mode="gesamt",
        max_bytes=0,
        plan_only=False,
        output_mode="dual",
        extras=ExtrasConfig(json_sidecar=True, augment_sidecar=False),
    )

    md_text = artifacts.canonical_md.read_text(encoding="utf-8")
    chunk_text = artifacts.chunk_index.read_text(encoding="utf-8")

    # Extract paths from both surfaces
    md_file_paths = [
        line.split('path="', 1)[1].split('"', 1)[0]
        for line in md_text.splitlines()
        if "<!-- FILE_START path=" in line
    ]
    chunk_rows = [
        json.loads(line)
        for line in chunk_text.splitlines()
        if line.strip()
    ]
    chunk_file_paths = [
        row.get("source_range", {}).get("file_path", "")
        for row in chunk_rows
    ]

    # Assertion 1: Sentinel content absent from both surfaces (already proven by upstream scan_repo test)
    for dir_name, sentinel in sentinels.items():
        assert sentinel.strip() not in md_text, (
            f"A2 new noise dir '{dir_name}' content must not appear in canonical_md"
        )
        assert sentinel.strip() not in chunk_text, (
            f"A2 new noise dir '{dir_name}' content must not appear in chunk_index"
        )

    # Assertion 2: Noise dir names must not appear as actual path components (symmetric to is_noise_file logic)
    for dir_name in sentinels:
        # Check canonical_md: noise dirs must not be parent-directory components
        for p in md_file_paths:
            path_parts = p.split("/")
            parent_dirs = set(path_parts[:-1])  # all components except filename
            assert dir_name not in parent_dirs, (
                f"A2 new noise dir '{dir_name}' must not appear as actual component in canonical_md path: {p}"
            )
        # Check chunk_index: noise dirs must not be parent-directory components
        for p in chunk_file_paths:
            if p:  # skip empty strings
                path_parts = p.split("/")
                parent_dirs = set(path_parts[:-1])
                assert dir_name not in parent_dirs, (
                    f"A2 new noise dir '{dir_name}' must not appear as actual component in chunk_index path: {p}"
                )

    # Assertion 3: Noise filenames must not appear in paths
    noise_filenames = ["pip_wheels.txt", "lcov.info"]
    for filename in noise_filenames:
        assert not any(filename in p for p in md_file_paths), (
            f"Noise file '{filename}' must not appear in canonical_md paths: {md_file_paths}"
        )
        assert not any(filename in p for p in chunk_file_paths), (
            f"Noise file '{filename}' must not appear in chunk_index JSONL paths: {chunk_file_paths}"
        )

    # Assertion 4: Source file must be present
    assert any("src/main.py" in p for p in md_file_paths), (
        f"src/main.py must appear in canonical_md file paths: {md_file_paths}"
    )
    assert any("src/main.py" in p for p in chunk_file_paths), (
        f"src/main.py must appear in chunk_index JSONL paths: {chunk_file_paths}"
    )

    # Assertion 5: Hidden context must be present (direct proof, not deferred to scan_repo test)
    expected_hidden = [".github/workflows/ci.yml", ".wgx/config.yml", ".ai-context.yml"]
    for hidden_path in expected_hidden:
        assert any(hidden_path in p for p in md_file_paths), (
            f"Hidden context '{hidden_path}' must appear in canonical_md: {md_file_paths}"
        )
        assert any(hidden_path in p for p in chunk_file_paths), (
            f"Hidden context '{hidden_path}' must appear in chunk_index: {chunk_file_paths}"
        )
