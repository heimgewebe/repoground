from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
REPOGROUND_DOC = REPO_ROOT / "docs/architecture/repoground.md"
NAMING_DOC = REPO_ROOT / "docs/architecture/naming.md"
BUILD_SPEC = REPO_ROOT / "merger/repoground/repoground-build-spec.md"
CLI_BLUEPRINT = REPO_ROOT / "docs/blueprints/repoground-cli-operational-blueprint.md"
ROADMAP_INDEX = REPO_ROOT / "docs/roadmap.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_repoground_doc_defines_the_canonical_product_surface() -> None:
    text = _read(REPOGROUND_DOC)
    assert "RepoGround is the sole current product name" in text
    assert "heimgewebe/repoground" in text
    assert "merger.repoground" in text
    for command in (
        "repoground build", "repoground query", "repoground graph",
        "repoground ground", "repoground serve", "repoground mcp",
        "repoground service-client",
    ):
        assert command in text


def test_repoground_doc_preserves_authority_and_negative_semantics() -> None:
    text = _read(REPOGROUND_DOC)
    for expected in (
        "canonical content is the content authority",
        "Sidecars are navigation, diagnostic, evidence-index or cache surfaces",
        "A bundle is a snapshot at generation time",
        "does not by itself establish",
        "truth or correctness", "runtime behavior", "test sufficiency",
        "review or merge readiness",
    ):
        assert expected in text


def test_repoground_doc_separates_create_and_read_paths() -> None:
    compact = " ".join(_read(REPOGROUND_DOC).split())
    assert "create operations" in compact
    assert "read operations" in compact
    assert "must not refresh or mutate source state" in compact
    assert "must not silently regenerate it" in compact


def test_document_delegates_are_removed() -> None:
    removed = [
        REPO_ROOT / "docs/architecture" / ("repo" + "brief.md"),
        REPO_ROOT / "merger/repoground" / ("repo" + "Lens-spec.md"),
        REPO_ROOT / "docs/blueprints" / ("lens" + "kit-artifact-output-control-plane.md"),
    ]
    assert all(not path.exists() for path in removed)


def test_build_spec_preserves_versioned_data_contracts() -> None:
    text = _read(BUILD_SPEC)
    assert text.startswith("# REPOGROUND BUILD SPEC v2.4")
    assert "Normative Spezifikation für RepoGround 3.x" in text
    assert "RepoGround build erzeugt" in text
    assert "Persistierte Kennungen" in text
    assert "kein offenes TODO" in text


def test_naming_doc_defines_immediate_hard_cut() -> None:
    text = _read(NAMING_DOC)
    compact = " ".join(text.split())
    for expected in (
        "RepoGround build", "RepoGround query", "RepoGround graph",
        "RepoGround verify", "RepoGround service", "RepoGround MCP",
        "merger.repoground", "sole content authority",
        "there is no 30-day alias window",
        "not public product aliases",
        "repoground-naming-hard-cut.v1.json",
    ):
        assert expected in compact


def test_current_public_surfaces_do_not_restore_product_aliases() -> None:
    inventory = json.loads(
        (REPO_ROOT / "docs/architecture/repoground-3-migration-inventory.v1.json")
        .read_text(encoding="utf-8")
    )
    explanatory = {
        "docs/architecture/naming.md",
        "docs/architecture/repoground.md",
        "docs/architecture/repoground-3-migration.md",
        "merger/repoground/repoground-build-spec.md",
        "scripts/ops/repoground-publish-fleet",
        "scripts/ops/repoground-publication-policy",
    }
    current = {
        *inventory["current_public_documents"],
        "scripts/repoground", "scripts/repoground-launcher.sh",
        "scripts/repoground-mcp-stdio.py", "docs/systemd/repoground.service",
        "repoground/__init__.py", "repoground/__main__.py",
        "repoground/cli.py", "merger/repoground/__main__.py",
    } - explanatory
    retired = re.compile(r"\b(?:lenskit|repolens|rlens|repobrief)\b", re.IGNORECASE)
    findings = []
    for relative in sorted(current):
        content = (REPO_ROOT / relative).read_text(encoding="utf-8")
        for number, line in enumerate(content.splitlines(), start=1):
            if retired.search(line):
                findings.append(f"{relative}:{number}:{line.strip()}")
    assert findings == []


def test_cli_operational_blueprint_uses_canonical_commands() -> None:
    text = _read(CLI_BLUEPRINT)
    for expected in (
        "python -m merger.repoground service-client --help",
        "merger.repoground.cli.serve",
        "repoground service-client health",
        "command -v repoground",
    ):
        assert expected in text
    assert "repoground-client" not in text


def test_roadmap_registers_current_cli_blueprint() -> None:
    text = _read(ROADMAP_INDEX)
    assert "docs/blueprints/repoground-cli-operational-blueprint.md" in text
