from pathlib import Path

import pytest

from merger.lenskit.core import merge
from merger.lenskit.core.merge import FileInfo, NOISE_DIR_SEGMENTS, SKIP_DIRS


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


def test_noise_dir_segments_aligned_with_skip_dirs():
    """NOISE_DIR_SEGMENTS must cover all cache/tool dirs in SKIP_DIRS."""
    # Strip trailing slash from NOISE_DIR_SEGMENTS for comparison
    noise_set = {seg.rstrip("/") for seg in NOISE_DIR_SEGMENTS}
    cache_dirs_in_skip = {
        d for d in SKIP_DIRS
        if d in {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".cache", "coverage",
                 "node_modules", "dist", "build", "target", "venv", ".venv"}
    }
    missing = cache_dirs_in_skip - noise_set
    assert not missing, f"SKIP_DIRS cache entries missing from NOISE_DIR_SEGMENTS: {missing}"


def test_noise_manifest_label_contains_noise_annotation():
    """Files under noise paths should get (noise) label in manifest output."""
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
