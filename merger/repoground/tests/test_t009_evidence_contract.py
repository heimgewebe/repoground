from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).parents[3]
PROOFS = ROOT / "docs" / "proofs"
IMPLEMENTATION_COMMIT = "44013f1fdc75a584a618076bc03d50650a24c7dc"
IMPLEMENTATION_TREE = "e08503047d30eb2397e09d70cbafb850f3a5f9e5"


def _load(name: str) -> dict[str, object]:
    payload = json.loads((PROOFS / name).read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_object_exists(revision: str) -> bool:
    completed = subprocess.run(
        ["git", "cat-file", "-e", revision],
        cwd=ROOT,
        check=False,
        capture_output=True,
    )
    return completed.returncode == 0


def _git_blob_sha256(commit: str, path: str) -> str:
    completed = subprocess.run(
        ["git", "show", f"{commit}:{path}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return hashlib.sha256(completed.stdout).hexdigest()


def _checkout_is_shallow() -> bool:
    completed = subprocess.run(
        ["git", "rev-parse", "--is-shallow-repository"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip() == "true"


def test_t009_complexity_measurement_is_revision_bound_and_ratcheted() -> None:
    payload = _load("repoground-legacy-t009-complexity.measurement.json")
    assert payload["status"] == "pass"
    assert payload["binding"] == {
        "commit": IMPLEMENTATION_COMMIT,
        "source": "git_archive",
        "tree": IMPLEMENTATION_TREE,
        "worktree_dirty": False,
    }
    assert payload["complexity"]["observed_budget_dimensions"] == {
        "excess_total": 2395,
        "finding_count": 197,
        "max_complexity": 138,
    }
    contract = payload["measurement_contract"]
    assert contract["ruff_version"] == "ruff 0.15.13"
    assert contract["measurement_command"] == (
        "python3 scripts/ci/check_graph_maintainability.py --root . --format json"
    )

    measured_inputs = {
        "ruff_config_sha256": ROOT / contract["ruff_config_path"],
        "measurement_script_sha256": ROOT / contract["measurement_script_path"],
    }
    for hash_field, path in measured_inputs.items():
        assert contract[hash_field] == _sha256(path)

    if _git_object_exists(f"{IMPLEMENTATION_COMMIT}^{{commit}}"):
        assert contract["ruff_config_sha256"] == _git_blob_sha256(
            IMPLEMENTATION_COMMIT, "ruff-ci.toml"
        )
        assert contract["measurement_script_sha256"] == _git_blob_sha256(
            IMPLEMENTATION_COMMIT, "scripts/ci/check_graph_maintainability.py"
        )
    else:
        assert _checkout_is_shallow()


def test_t009_performance_comparison_covers_every_case_and_gate() -> None:
    payload = _load("repoground-legacy-t009-performance.comparison.json")
    assert payload["status"] == "pass"
    assert payload["failed_cases"] == []
    assert payload["gate"] == {
        "median_regression_pct_max": 5.0,
        "peak_memory_regression_pct_max": 5.0,
    }
    assert payload["bindings"]["after"] == {
        "commit": IMPLEMENTATION_COMMIT,
        "source": "clean_git_worktree",
        "tree": IMPLEMENTATION_TREE,
        "worktree_dirty": False,
    }
    assert set(payload["compared_cases"]) == {
        "atlas_scan",
        "bundle_write_archive",
        "bundle_write_dual",
        "retrieval_index_build",
        "retrieval_query",
        "service_app_import",
    }
    for name, result in payload["compared_cases"].items():
        assert result["status"] in {"pass", "skip"}, name


def test_t009_delivery_evidence_hashes_are_complete() -> None:
    payload = _load("repoground-legacy-t009-delivery.evidence.json")
    assert payload["status"] == "pass"
    assert payload["binding"]["implementation_commit"] == IMPLEMENTATION_COMMIT
    assert payload["binding"]["implementation_tree"] == IMPLEMENTATION_TREE
    assert payload["targeted_tests"]["tests_passed"] == 42
    assert payload["targeted_tests"]["tests_skipped"] == 0
    for record in payload["evidence_files"].values():
        assert _sha256(ROOT / record["path"]) == record["sha256"]


def test_t009_implementation_tree_binding_exists_or_checkout_is_shallow() -> None:
    if not _git_object_exists(f"{IMPLEMENTATION_COMMIT}^{{commit}}"):
        assert _checkout_is_shallow()
        return

    completed = subprocess.run(
        ["git", "rev-parse", f"{IMPLEMENTATION_COMMIT}^{{tree}}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert completed.stdout.strip() == IMPLEMENTATION_TREE
