from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

CURRENT_ENTRY_DOCS = (
    ROOT / "README.md",
    ROOT / "docs/GETTING_STARTED.md",
    ROOT / "docs/usage/repoground-mcp-stdio.md",
    ROOT / "docs/architecture/repoground.md",
    ROOT / "docs/architecture/repoground-mcp-boundary.md",
)

REMOVED_DEBRIS = (
    ROOT / ".github/workflows/validate-merges.yml",
    ROOT / "benchmark_sse.py",
    ROOT / "benchmark_sse_concurrent.py",
    ROOT / "data/.gitkeep",
    ROOT / "mock_hub/metarepo/sync/metarepo-sync.yml",
    ROOT / "merger/repoground/validate_merge_meta.py",
)

REMOVED_LEGACY_RELEASE_SURFACES = (
    ROOT / "scripts/release/verify_repobrief_release_candidate.py",
    ROOT / "docs/release/semantic-extension-platforms.v1.json",
)

_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


def _local_link_targets(path: Path) -> list[Path]:
    targets: list[Path] = []
    for match in _LINK_RE.finditer(path.read_text(encoding="utf-8")):
        raw_target = match.group(1).split("#", 1)[0].strip()
        if not raw_target or "://" in raw_target or raw_target.startswith(("#", "mailto:")):
            continue
        targets.append((path.parent / raw_target).resolve())
    return targets


def test_current_entry_document_links_resolve() -> None:
    missing = [
        f"{source.relative_to(ROOT)} -> {target}"
        for source in CURRENT_ENTRY_DOCS
        for target in _local_link_targets(source)
        if not target.exists()
    ]
    assert missing == []


def test_high_confidence_debris_is_absent() -> None:
    assert [str(path.relative_to(ROOT)) for path in REMOVED_DEBRIS if path.exists()] == []


def test_release_surface_is_repoground_only() -> None:
    assert [
        str(path.relative_to(ROOT))
        for path in REMOVED_LEGACY_RELEASE_SURFACES
        if path.exists()
    ] == []
    assert list((ROOT / "requirements").glob("repobrief-*")) == []

    verifier = (ROOT / "scripts/release/verify_release_candidate.py").read_text(
        encoding="utf-8"
    )
    assert "LEGACY_CONTRACT" not in verifier
    assert "verify_legacy_release_candidate" not in verifier

    # Contract deletion is governed separately: legacy schemas remain protected
    # compatibility artifacts but are no longer part of the canonical verifier.
    assert (
        ROOT
        / "merger/repoground/contracts/repobrief-release-candidate.v1.schema.json"
    ).is_file()
    assert (
        ROOT
        / "merger/repoground/contracts/repobrief-semantic-platforms.v1.schema.json"
    ).is_file()

    licensing = (ROOT / "docs/release/licensing.md").read_text(encoding="utf-8")
    assert "LicenseRef-RepoGround-All-Rights-Reserved" in licensing
    assert "LicenseRef-RepoBrief-All-Rights-Reserved" not in licensing
