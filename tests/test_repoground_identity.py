from __future__ import annotations

import ast
import json
import re
from collections import Counter
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_canonical_package_and_product_help() -> None:
    import merger.repoground  # noqa: F401

    result = _run("-m", "merger.repoground", "--help")
    assert result.returncode == 0, result.stderr
    assert "RepoGround" in result.stdout
    assert "build" in result.stdout
    assert "serve" in result.stdout
    assert "mcp" in result.stdout


def test_build_help_uses_repoground_identity() -> None:
    result = _run("-m", "merger.repoground", "build", "--help")
    assert result.returncode == 0, result.stderr
    assert "RepoGround build" in result.stdout


def test_legacy_namespace_is_not_packaged() -> None:
    assert not (ROOT / "merger" / "lenskit" / "__init__.py").exists()


def test_release_identity_is_3() -> None:
    assert (ROOT / "RELEASE_VERSION").read_text(encoding="utf-8").strip() == "3.0.0"


def test_public_identity_files_do_not_restore_retired_brands() -> None:
    public_files = [
        ROOT / "README.md",
        ROOT / "docs" / "GETTING_STARTED.md",
        ROOT / "docs" / "FAQ.md",
        ROOT / "docs" / "glossary.md",
    ]
    retired = ("Lenskit", "repoLens", "RepoBrief", "rLens")
    for path in public_files:
        text = path.read_text(encoding="utf-8")
        for token in retired:
            assert token not in text, f"{token!r} restored in {path.relative_to(ROOT)}"


def _migration_inventory() -> dict[str, object]:
    path = ROOT / "docs" / "architecture" / "repoground-3-migration-inventory.v1.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _allowed_legacy_path(relative: str, inventory: dict[str, object]) -> bool:
    legacy = inventory["legacy_policy"]
    assert isinstance(legacy, dict)
    prefixes = legacy["allowed_path_prefixes"]
    exact = legacy["allowed_exact_files"]
    assert isinstance(prefixes, list)
    assert isinstance(exact, list)
    return relative in exact or any(relative.startswith(prefix) for prefix in prefixes)


def test_migration_inventory_is_explicit_and_unique() -> None:
    inventory = _migration_inventory()
    assert inventory["kind"] == "repoground.migration_inventory"
    assert inventory["canonical"] == {
        "product": "RepoGround",
        "repository_target": "heimgewebe/repoground",
        "python_namespace": "merger.repoground",
        "command": "repoground",
    }
    consumers = inventory["external_consumers"]
    assert isinstance(consumers, list)
    names = [item["repository"] for item in consumers]
    assert len(names) == len(set(names))
    assert {item["repository"] for item in consumers if item["blocking"]} >= {
        "grabowski",
        "bureau",
        "systemkatalog",
        "schauwerk",
        "metarepo",
        "infra",
        "heim-pc",
    }


def test_current_public_documents_use_only_allowlisted_legacy_vocabulary() -> None:
    inventory = _migration_inventory()
    retired = tuple(inventory["legacy_policy"]["retired_product_names"])
    public = inventory["current_public_documents"]
    assert isinstance(public, list)
    for relative in public:
        path = ROOT / relative
        assert path.is_file(), relative
        text = path.read_text(encoding="utf-8")
        hits = [token for token in retired if token in text]
        if hits:
            assert _allowed_legacy_path(relative, inventory), (
                f"retired names {hits!r} appear outside the migration allowlist in {relative}"
            )


def test_active_repoground_modules_do_not_import_legacy_namespace() -> None:
    import_pattern = re.compile(
        r"^\s*(?:from|import)\s+(?:merger\.)?lenskit(?:\.|\s|$)",
        re.MULTILINE,
    )
    violations: list[str] = []
    implementation = ROOT / "merger" / "repoground"
    for path in implementation.rglob("*.py"):
        relative = path.relative_to(ROOT).as_posix()
        if "/tests/" in f"/{relative}/":
            continue
        if import_pattern.search(path.read_text(encoding="utf-8")):
            violations.append(relative)
    assert violations == []


def test_legacy_allowlist_paths_are_scoped_to_known_categories() -> None:
    inventory = _migration_inventory()
    legacy = inventory["legacy_policy"]
    prefixes = legacy["allowed_path_prefixes"]
    assert "README.md" not in prefixes
    assert "docs/" not in prefixes
    assert "merger/repoground/" not in prefixes
    assert legacy["persisted_2_x_identifiers_reinterpreted"] is False

def test_active_python_strings_have_only_documented_legacy_identity_values() -> None:
    tokens = ("Lenskit", "RepoBrief", "rLens", "repoLens")
    compatibility_modules = {
        "merger/repoground/cli/repobrief.py",
        "merger/repoground/cli/repobrief_mcp_stdio.py",
        "merger/repoground/cli/rlens.py",
        "merger/repoground/frontends/pythonista/repolens.py",
        "merger/repoground/frontends/pythonista/repolens_helpers.py",
        "merger/repoground/frontends/pythonista/repolens_utils.py",
    }
    observed: Counter[tuple[str, str]] = Counter()
    implementation = ROOT / "merger" / "repoground"
    for path in implementation.rglob("*.py"):
        relative = path.relative_to(ROOT).as_posix()
        if (
            "/tests/" in f"/{relative}/"
            or relative in compatibility_modules
            or relative == "merger/repoground/core/naming_audit.py"
        ):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            if any(token in node.value for token in tokens):
                observed[(relative, node.value)] += 1

    expected = Counter(
        {
            (
                "merger/repoground/core/merge.py",
                "# repoLens Report",
            ): 1,
            (
                "merger/repoground/adapters/sources.py",
                "repoLens.sources_refresh",
            ): 1,
        }
    )
    assert observed == expected
