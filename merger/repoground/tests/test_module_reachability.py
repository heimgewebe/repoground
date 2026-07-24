from __future__ import annotations

import json
from pathlib import Path

from merger.repoground.architecture.module_reachability import (
    NON_DOCUMENTATION_EVIDENCE,
    PRODUCTION_EVIDENCE,
    evaluate_reachability_policy,
    measure_module_reachability,
)
from scripts.ci.check_module_reachability import validate_policy

ROOT = Path(__file__).resolve().parents[3]
POLICY = ROOT / "config/repoground-module-reachability.v1.json"


def _policy() -> dict:
    return json.loads(POLICY.read_text(encoding="utf-8"))


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


#: The synthetic fixtures declare package markers that no fixture imports;
#: they are not the subject of these unit tests.
_FIXTURE_PACKAGES = {"merger", "merger.repoground", "merger.repoground.core"}


def _project(root: Path) -> None:
    _write(root / "merger/__init__.py", "")
    _write(root / "merger/repoground/__init__.py", "")


def _unproven(measurement: dict) -> list[str]:
    return [
        module
        for module in measurement["unproven"]
        if module not in _FIXTURE_PACKAGES
    ]


def test_real_repository_has_evidence_for_every_production_module() -> None:
    measurement = measure_module_reachability(ROOT)

    assert evaluate_reachability_policy(measurement, _policy()) == []
    assert measurement["unproven"] == []
    assert measurement["unparsed_files"] == []
    assert measurement["module_count"] > 100


def test_policy_records_no_unreviewed_exceptions() -> None:
    policy = _policy()

    assert policy["allowed_unproven"] == []
    assert policy["allowed_documentation_only"] == []
    assert policy["require_non_documentation_evidence"] is True
    assert policy["require_production_evidence"] is True
    assert "not a dead module" in policy["removal_policy"]
    # Test-only modules are declared, never silently counted as production use.
    assert policy["allowed_test_only"] == sorted(policy["allowed_test_only"])
    assert measure_module_reachability(ROOT)["test_only"] == sorted(
        policy["allowed_test_only"]
    )


def test_policy_identity_and_roots_are_fail_closed() -> None:
    assert validate_policy(_policy()) == []
    assert [item["code"] for item in validate_policy([])] == [
        "module_reachability_policy_invalid"
    ]
    assert [item["code"] for item in validate_policy({})] == [
        "module_reachability_policy_identity_invalid",
        "module_reachability_policy_invalid",
    ]
    assert [
        item["code"] for item in validate_policy(_policy() | {"package_roots": []})
    ] == ["module_reachability_policy_invalid"]


def test_static_import_and_main_block_count_as_evidence(tmp_path: Path) -> None:
    _project(tmp_path)
    _write(tmp_path / "merger/repoground/used.py", "VALUE = 1\n")
    _write(
        tmp_path / "merger/repoground/consumer.py",
        "from merger.repoground.used import VALUE\n",
    )
    _write(
        tmp_path / "merger/repoground/runnable.py",
        "def main():\n    return 0\n\n\nif __name__ == '__main__':\n    main()\n",
    )

    by_module = {
        record["module"]: record
        for record in measure_module_reachability(tmp_path)["modules"]
    }

    assert by_module["merger.repoground.used"]["evidence"] == ["static_import_product"]
    assert by_module["merger.repoground.runnable"]["evidence"] == ["module_main_block"]


def test_relative_import_resolves_to_the_imported_module(tmp_path: Path) -> None:
    _project(tmp_path)
    _write(tmp_path / "merger/repoground/core/__init__.py", "")
    _write(tmp_path / "merger/repoground/core/leaf.py", "VALUE = 1\n")
    _write(tmp_path / "merger/repoground/core/consumer.py", "from .leaf import VALUE\n")

    measurement = measure_module_reachability(tmp_path)

    # The importer itself stays unproven; only the imported leaf gains evidence.
    assert _unproven(measurement) == ["merger.repoground.core.consumer"]


def test_dynamic_and_runtime_references_count_as_evidence(tmp_path: Path) -> None:
    _project(tmp_path)
    _write(tmp_path / "merger/repoground/plugin.py", "VALUE = 1\n")
    _write(tmp_path / "merger/repoground/launched.py", "VALUE = 1\n")
    _write(
        tmp_path / "merger/repoground/loader.py",
        "import importlib\n\nloaded = importlib.import_module('merger.repoground.plugin')\n",
    )
    _write(
        tmp_path / "scripts/run.sh",
        "#!/bin/sh\npython -m merger.repoground.launched\n",
    )

    by_module = {
        record["module"]: record
        for record in measure_module_reachability(tmp_path)["modules"]
    }

    assert by_module["merger.repoground.plugin"]["evidence"] == [
        "dynamic_string_reference"
    ]
    assert by_module["merger.repoground.launched"]["evidence"] == [
        "runtime_surface_reference"
    ]


def test_plain_product_string_does_not_count_as_dynamic_import(tmp_path: Path) -> None:
    _project(tmp_path)
    _write(tmp_path / "merger/repoground/orphan.py", "VALUE = 1\n")
    _write(
        tmp_path / "merger/repoground/narrator.py",
        "MESSAGE = 'merger.repoground.orphan'\n",
    )

    assert _unproven(measure_module_reachability(tmp_path)) == [
        "merger.repoground.narrator",
        "merger.repoground.orphan",
    ]


def test_non_equal_main_comparison_does_not_count_as_entrypoint(tmp_path: Path) -> None:
    _project(tmp_path)
    _write(
        tmp_path / "merger/repoground/not_runnable.py",
        "if __name__ != '__main__':\n    VALUE = 1\n",
    )

    assert _unproven(measure_module_reachability(tmp_path)) == [
        "merger.repoground.not_runnable"
    ]


def test_unbound_importlib_name_does_not_count_as_dynamic_import(
    tmp_path: Path,
) -> None:
    _project(tmp_path)
    _write(tmp_path / "merger/repoground/plugin.py", "VALUE = 1\n")
    _write(
        tmp_path / "merger/repoground/broken_loader.py",
        "loaded = importlib.import_module('merger.repoground.plugin')\n",
    )

    assert "merger.repoground.plugin" in _unproven(
        measure_module_reachability(tmp_path)
    )


def test_non_runnable_bare_import_does_not_claim_package_sibling(
    tmp_path: Path,
) -> None:
    _project(tmp_path)
    _write(tmp_path / "merger/repoground/core/__init__.py", "")
    _write(tmp_path / "merger/repoground/core/utils.py", "VALUE = 1\n")
    _write(
        tmp_path / "merger/repoground/core/consumer.py",
        "from utils import VALUE\n",
    )

    assert "merger.repoground.core.utils" in _unproven(
        measure_module_reachability(tmp_path)
    )


def test_script_style_sibling_import_resolves_only_to_existing_module(
    tmp_path: Path,
) -> None:
    _project(tmp_path)
    _write(tmp_path / "merger/repoground/frontends/__init__.py", "")
    _write(tmp_path / "merger/repoground/frontends/pythonista/__init__.py", "")
    _write(
        tmp_path / "merger/repoground/frontends/pythonista/build_utils.py",
        "VALUE = 1\n",
    )
    _write(
        tmp_path / "merger/repoground/frontends/pythonista/build.py",
        "from build_utils import VALUE\n\nif __name__ == '__main__':\n    print(VALUE)\n",
    )

    by_module = {
        record["module"]: record
        for record in measure_module_reachability(tmp_path)["modules"]
    }

    assert by_module[
        "merger.repoground.frontends.pythonista.build_utils"
    ]["evidence"] == ["static_import_product"]


def test_recorded_baselines_do_not_count_as_runtime_evidence(tmp_path: Path) -> None:
    """A path listed in a measurement artifact is not a consumer."""

    _project(tmp_path)
    _write(tmp_path / "merger/repoground/orphan.py", "VALUE = 1\n")
    _write(
        tmp_path / "config/some-baseline.v1.json",
        json.dumps({"findings": [{"path": "merger/repoground/orphan.py"}]}),
    )
    _write(
        tmp_path / "docs/proofs/some-proof.measurement.json",
        json.dumps({"module": "merger.repoground.orphan"}),
    )

    measurement = measure_module_reachability(tmp_path)

    assert _unproven(measurement) == ["merger.repoground.orphan"]


def test_documentation_alone_is_reachable_but_flagged(tmp_path: Path) -> None:
    _project(tmp_path)
    _write(tmp_path / "merger/repoground/documented.py", "VALUE = 1\n")
    _write(
        tmp_path / "docs/usage.md",
        "Run `python -m merger.repoground.documented` manually.\n",
    )

    measurement = measure_module_reachability(tmp_path)

    assert _unproven(measurement) == []
    assert measurement["documentation_only"] == ["merger.repoground.documented"]
    assert "module_reachability_documentation_only" in {
        item["code"]
        for item in evaluate_reachability_policy(
            measurement, {"require_non_documentation_evidence": True}
        )
    }
    assert "documented_invocation" not in NON_DOCUMENTATION_EVIDENCE


def test_unparsed_product_source_fails_but_broken_fixture_does_not(tmp_path: Path) -> None:
    _project(tmp_path)
    _write(tmp_path / "merger/repoground/tests/fixtures/broken.py", "def (\n")

    measurement = measure_module_reachability(tmp_path)
    assert measurement["unparsed_files"] == []
    assert measurement["unparsed_non_product_files"] == [
        "merger/repoground/tests/fixtures/broken.py"
    ]

    _write(tmp_path / "merger/repoground/damaged.py", "def (\n")
    measurement = measure_module_reachability(tmp_path)

    assert measurement["unparsed_files"] == ["merger/repoground/damaged.py"]
    assert "module_reachability_unparsed_sources" in {
        item["code"] for item in evaluate_reachability_policy(measurement, {})
    }


def test_a_test_import_alone_is_not_production_evidence(tmp_path: Path) -> None:
    _project(tmp_path)
    _write(tmp_path / "merger/repoground/exercised.py", "VALUE = 1\n")
    _write(
        tmp_path / "merger/repoground/tests/test_exercised.py",
        "from merger.repoground.exercised import VALUE\n",
    )

    measurement = measure_module_reachability(tmp_path)
    by_module = {record["module"]: record for record in measurement["modules"]}
    record = by_module["merger.repoground.exercised"]

    assert record["evidence"] == ["static_import_test"]
    assert record["has_non_documentation_evidence"] is True
    assert record["has_production_evidence"] is False
    assert "static_import_test" not in PRODUCTION_EVIDENCE
    # A package above a test-imported module inherits the test class, not the
    # production class.
    assert by_module["merger.repoground"]["evidence"] == [
        "package_of_test_referenced_module"
    ]
    # Undeclared, it fails; it is never reported as unproven or dead.
    assert measurement["unproven"] == []
    assert measurement["test_only"] == [
        "merger",
        "merger.repoground",
        "merger.repoground.exercised",
    ]
    assert [
        item["code"]
        for item in evaluate_reachability_policy(measurement, {"allowed_unproven": []})
    ] == ["module_reachability_test_only"] * 3
    assert (
        evaluate_reachability_policy(
            measurement, {"allowed_test_only": measurement["test_only"]}
        )
        == []
    )


def test_a_test_string_is_not_a_production_dynamic_reference(tmp_path: Path) -> None:
    _project(tmp_path)
    _write(tmp_path / "merger/repoground/plugin.py", "VALUE = 1\n")
    _write(
        tmp_path / "merger/repoground/tests/test_plugin.py",
        "import importlib\n\n\n"
        "def test_loads():\n"
        "    importlib.import_module('merger.repoground.plugin')\n",
    )

    by_module = {
        record["module"]: record
        for record in measure_module_reachability(tmp_path)["modules"]
    }

    assert by_module["merger.repoground.plugin"]["evidence"] == [
        "dynamic_string_reference_test"
    ]
    assert by_module["merger.repoground.plugin"]["has_production_evidence"] is False


def test_a_longer_dotted_name_does_not_credit_its_prefix(tmp_path: Path) -> None:
    """Corpus matching is token-exact, so a longer name is not a consumer."""

    _project(tmp_path)
    _write(tmp_path / "merger/repoground/lonely.py", "VALUE = 1\n")
    _write(
        tmp_path / "scripts/run.sh",
        "#!/bin/sh\npython -m merger.repoground.lonely_extra\n",
    )
    _write(tmp_path / "docs/usage.md", "See `merger/repoground/lonely.py.bak`.\n")

    assert _unproven(measure_module_reachability(tmp_path)) == [
        "merger.repoground.lonely"
    ]


def test_stale_allowlist_entries_are_rejected() -> None:
    measurement = {
        "unproven": [],
        "documentation_only": [],
        "test_only": [],
        "unparsed_files": [],
    }
    policy = {
        "allowed_unproven": ["merger.repoground.gone"],
        "allowed_documentation_only": ["merger.repoground.also_gone"],
        "allowed_test_only": ["merger.repoground.gone_too"],
    }

    assert [item["code"] for item in evaluate_reachability_policy(measurement, policy)] == [
        "module_reachability_allowlist_stale",
        "module_reachability_documentation_allowlist_stale",
        "module_reachability_test_only_allowlist_stale",
    ]


def test_lint_workflow_runs_the_reachability_check() -> None:
    workflow = (ROOT / ".github/workflows/lint.yml").read_text(encoding="utf-8")

    assert "scripts/ci/check_module_reachability.py" in workflow
