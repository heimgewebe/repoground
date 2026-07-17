from __future__ import annotations

import json
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
REPOGROUND_DOC = REPO_ROOT / "docs/architecture/repoground.md"
LEGACY_REPOBRIEF_DOC = REPO_ROOT / "docs/architecture/repobrief.md"
NAMING_DOC = REPO_ROOT / "docs/architecture/naming.md"
BUILD_SPEC = REPO_ROOT / "merger/repoground/repoground-build-spec.md"
LEGACY_BUILD_SPEC = REPO_ROOT / "merger/repoground/repoLens-spec.md"
CLI_BLUEPRINT = REPO_ROOT / "docs/blueprints/repoground-cli-operational-blueprint.md"
LEGACY_ARTIFACT_BLUEPRINT = (
    REPO_ROOT / "docs/blueprints/lenskit-artifact-output-control-plane.md"
)
ROADMAP_INDEX = REPO_ROOT / "docs/roadmap.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_repoground_doc_defines_the_canonical_product_surface() -> None:
    text = _read(REPOGROUND_DOC)

    assert "RepoGround is the sole current product name" in text
    assert "heimgewebe/repoground" in text
    assert "merger.repoground" in text
    for command in (
        "repoground build",
        "repoground query",
        "repoground graph",
        "repoground ground",
        "repoground serve",
        "repoground mcp",
        "repoground service-client",
    ):
        assert command in text

    for forbidden in (
        "RepoBrief is the public system name",
        "The public system name is RepoBrief",
        "historical repository and Python package name remains `lenskit`",
        "no package rename",
    ):
        assert forbidden not in text


def test_repoground_doc_preserves_authority_and_negative_semantics() -> None:
    text = _read(REPOGROUND_DOC)

    assert "canonical content is the content authority" in text
    assert "Sidecars are navigation, diagnostic, evidence-index or cache surfaces" in text
    assert "A bundle is a snapshot at generation time" in text
    assert "A successful RepoGround operation or valid artifact does not by itself establish" in text
    for boundary in (
        "truth or correctness",
        "completeness",
        "runtime behavior",
        "test sufficiency",
        "regression absence",
        "repository understanding",
        "review or merge readiness",
    ):
        assert boundary in text


def test_repoground_doc_separates_create_and_read_paths() -> None:
    text = _read(REPOGROUND_DOC)

    compact = " ".join(text.split())
    assert "create operations" in compact
    assert "read operations" in compact
    assert "must not refresh or mutate source state" in compact
    assert "must not silently regenerate it" in compact


def test_legacy_architecture_and_build_spec_paths_are_only_delegates() -> None:
    architecture = _read(LEGACY_REPOBRIEF_DOC)
    assert "The current product architecture now lives at" in architecture
    assert "repoground.md" in architecture
    assert "not a second product definition" in architecture
    assert "RepoBrief is the public system name" not in architecture

    build = _read(LEGACY_BUILD_SPEC)
    assert "The normative build/report specification now lives at" in build
    assert "repoground-build-spec.md" in build
    assert "not a second specification" in build


def test_build_spec_uses_repoground_product_and_preserves_versioned_contract() -> None:
    text = _read(BUILD_SPEC)

    assert text.startswith("# REPOGROUND BUILD SPEC v2.4")
    assert "Normative Spezifikation für RepoGround 3.x" in text
    assert "RepoGround build erzeugt" in text
    assert "repolens-report" in text
    assert "Persistierte Kennungen" in text
    assert "kein offenes TODO" in text


def test_naming_doc_defines_repoground_product_and_compatibility_boundaries() -> None:
    text = _read(NAMING_DOC)

    for expected in (
        "RepoGround build",
        "RepoGround query",
        "RepoGround graph",
        "RepoGround verify",
        "RepoGround service",
        "RepoGround MCP",
        "merger.repoground",
        "sole content authority",
    ):
        assert expected in text

    for legacy in ("Lenskit", "repoLens", "rLens", "RepoBrief"):
        assert legacy in text
    assert "retired product names" in text
    assert "does not create a second implementation" in text
    assert "does not silently reinterpret stored bundles" in text


def test_current_repoground_surfaces_do_not_reintroduce_retired_product_names() -> None:
    inventory = json.loads(
        (REPO_ROOT / "docs/architecture/repoground-3-migration-inventory.v1.json")
        .read_text(encoding="utf-8")
    )
    explanatory_surfaces = {
        "docs/architecture/naming.md",
        "docs/architecture/repoground.md",
        "docs/architecture/repoground-3-migration.md",
        "merger/repoground/repoground-build-spec.md",
        "scripts/ops/repoground-publish-fleet",
        "scripts/ops/repoground-publication-policy",
    }
    current_surfaces = {
        *inventory["current_public_documents"],
        "scripts/repoground",
        "scripts/repoground-launcher.sh",
        "scripts/repoground-mcp-stdio.py",
        "docs/systemd/repoground.service",
        "repoground/__init__.py",
        "repoground/__main__.py",
        "repoground/cli.py",
        "merger/repoground/__main__.py",
        "scripts/ops/repoground-publish-fleet",
        "scripts/ops/repoground-publication-policy",
    } - explanatory_surfaces
    retired = re.compile(r"\b(?:lenskit|repolens|rlens|repobrief)\b", re.IGNORECASE)
    findings: list[str] = []
    for relative in sorted(current_surfaces):
        content = (REPO_ROOT / relative).read_text(encoding="utf-8")
        for number, line in enumerate(content.splitlines(), start=1):
            if retired.search(line):
                findings.append(f"{relative}:{number}:{line.strip()}")
    assert findings == []


def test_cli_operational_blueprint_uses_real_repoground_commands() -> None:
    text = _read(CLI_BLUEPRINT)

    for expected in (
        "python -m merger.repoground service-client --help",
        "python -m merger.repoground rlens-client --help",
        "merger.repoground.cli.serve",
        "repoground service-client health",
    ):
        assert expected in text
    for forbidden in ("repoground-client", "cli.repoground"):
        assert forbidden not in text
    assert "command -v repoground" in text
    assert "kein dauerhafter Repository-Contract" in text


def test_moved_artifact_blueprint_is_terminal_and_points_to_canonical_path() -> None:
    text = _read(LEGACY_ARTIFACT_BLUEPRINT)

    assert text.startswith("---\nstatus: superseded\n")
    assert (
        "superseded_by: docs/blueprints/repoground-artifact-output-control-plane.md"
        in text
    )
    assert "not a second blueprint" in text


def test_roadmap_registers_current_cli_blueprint() -> None:
    text = _read(ROADMAP_INDEX)

    assert "docs/blueprints/repoground-cli-operational-blueprint.md" in text
    assert "docs/blueprints/lenskit-cli-operational-blueprint.md" not in text
