from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[3]
PROOFS = ROOT / "docs" / "proofs"
IMPLEMENTATION_COMMIT = "44013f1fdc75a584a618076bc03d50650a24c7dc"
IMPLEMENTATION_TREE = "e08503047d30eb2397e09d70cbafb850f3a5f9e5"
EVIDENCE_COMMIT = "8b07a47a0407e56af7ef9550c39bbc699f263436"
EVIDENCE_TREE = "5d072c1f251423af248c70b20e9d8761e4b79805"
PR_BASE_COMMIT = "2afc2836fa1a49a593c7b57eda43086844e8fb2b"
CORRECTIVE_IMPLEMENTATION_COMMIT = "684fd3aa8f0b99f6b743386e233d09b997144310"
CORRECTIVE_IMPLEMENTATION_TREE = "457e8af17214a216035a9b3a704ef4c746c9ced2"
MERGED_DEFECT_COMMIT = "c91d640bce2b14c4a78a64e83169d56c818fa662"
MERGED_DEFECT_TREE = "36113af31c4cb6ba381302b8fcef61a024049336"

# Exact expected counts for fail-closed evidence validation
EXPECTED_EVIDENCE_FILE_COUNT = 4
EXPECTED_MEASURED_CASES = {
    "atlas_scan",
    "bundle_write_archive",
    "bundle_write_dual",
    "retrieval_index_build",
    "retrieval_query",
    "service_app_import",
}
EXPECTED_DOES_NOT_ESTABLISH_COUNT = 5


EXPECTED_EVIDENCE_FILES = {
    "repoground-legacy-t009-complexity.measurement.json",
    "repoground-legacy-t009-performance.after.json",
    "repoground-legacy-t009-performance.before.json",
    "repoground-legacy-t009-performance.comparison.json",
}
RECEIPT_SECTIONS = ("complexity", "performance", "ruff", "targeted_tests")
CORRECTIVE_EVIDENCE_FILES = {
    "repoground-legacy-t009-complexity.corrective-v2.measurement.json",
    "repoground-legacy-t009-differential.corrective-v2.json",
    "repoground-legacy-t009-performance.corrective-v2.after.json",
    "repoground-legacy-t009-performance.corrective-v2.before.json",
    "repoground-legacy-t009-performance.corrective-v2.comparison.json",
}
CORRECTIVE_RECEIPT_SECTIONS = (
    "broad_tests",
    "complexity",
    "differential",
    "performance",
)


def _validate_delivery_evidence_shape(payload: dict[str, object]) -> None:
    evidence_files = payload.get("evidence_files")
    assert isinstance(evidence_files, dict)
    assert set(evidence_files) == EXPECTED_EVIDENCE_FILES
    for name, record in evidence_files.items():
        assert isinstance(record, dict), name
        assert set(record) == {"path", "sha256"}, name
        assert isinstance(record["path"], str) and record["path"], name
        assert isinstance(record["sha256"], str) and len(record["sha256"]) == 64, name
    for section in RECEIPT_SECTIONS:
        section_payload = payload.get(section)
        assert isinstance(section_payload, dict), section
        receipt = section_payload.get("lifecycle_receipt_sha256")
        assert isinstance(receipt, str) and len(receipt) == 64, section


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


def _assert_git_object_available_or_fail_closed(revision: str) -> None:
    """Fail-closed: if the historical blob is inaccessible and checkout is not
    shallow, the test must fail rather than silently skip validation.

    In shallow clones, pytest.skip with explicit reason instead of PASS.
    """
    if not _git_object_exists(revision):
        if _checkout_is_shallow():
            pytest.skip(
                f"historical object {revision} unavailable in shallow clone"
            )
        raise AssertionError(
            f"Historical object {revision} is inaccessible in a non-shallow checkout. "
            "This suggests the test environment is incomplete."
        )


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

    commit_ref = f"{IMPLEMENTATION_COMMIT}^{{commit}}"
    _assert_git_object_available_or_fail_closed(commit_ref)
    if _git_object_exists(commit_ref):
        assert contract["ruff_config_sha256"] == _git_blob_sha256(
            IMPLEMENTATION_COMMIT, "ruff-ci.toml"
        )
        assert contract["measurement_script_sha256"] == _git_blob_sha256(
            IMPLEMENTATION_COMMIT, "scripts/ci/check_graph_maintainability.py"
        )


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
    assert set(payload["compared_cases"]) == EXPECTED_MEASURED_CASES
    for name, result in payload["compared_cases"].items():
        assert result["status"] in {"pass", "skip"}, name


def test_t009_delivery_evidence_hashes_are_complete() -> None:
    payload = _load("repoground-legacy-t009-delivery.evidence.json")
    assert payload["status"] == "pass"
    assert payload["binding"]["implementation_commit"] == IMPLEMENTATION_COMMIT
    assert payload["binding"]["implementation_tree"] == IMPLEMENTATION_TREE
    assert payload["targeted_tests"]["tests_passed"] == 42
    assert payload["targeted_tests"]["tests_skipped"] == 0
    assert "delivery_status" not in payload

    _validate_delivery_evidence_shape(payload)

    _assert_git_object_available_or_fail_closed(f"{EVIDENCE_COMMIT}^{{commit}}")
    parent = subprocess.run(
        ["git", "rev-parse", f"{EVIDENCE_COMMIT}^"],
        cwd=ROOT, check=True, capture_output=True, text=True,
    ).stdout.strip()
    tree = subprocess.run(
        ["git", "rev-parse", f"{EVIDENCE_COMMIT}^{{tree}}"],
        cwd=ROOT, check=True, capture_output=True, text=True,
    ).stdout.strip()
    assert parent == IMPLEMENTATION_COMMIT
    assert tree == EVIDENCE_TREE
    for name, record in payload["evidence_files"].items():
        assert _git_blob_sha256(EVIDENCE_COMMIT, record["path"]) == record["sha256"], name

    assert set(payload["complexity"]) >= {
        "excess_total", "finding_count", "max_complexity", "status",
        "job", "lifecycle_receipt_sha256",
    }
    assert len(payload["does_not_establish"]) == EXPECTED_DOES_NOT_ESTABLISH_COUNT

def test_t009_implementation_tree_binding_exists_or_checkout_is_shallow() -> None:
    commit_ref = f"{IMPLEMENTATION_COMMIT}^{{commit}}"
    _assert_git_object_available_or_fail_closed(commit_ref)
    completed = subprocess.run(
        ["git", "rev-parse", f"{IMPLEMENTATION_COMMIT}^{{tree}}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert completed.stdout.strip() == IMPLEMENTATION_TREE


def test_t009_revision_differential_contract() -> None:
    from scripts.ci.compare_report_renderer_revisions import compare_revisions

    result = compare_revisions(ROOT, PR_BASE_COMMIT, ROOT)
    assert result["base"]["commit"] == PR_BASE_COMMIT
    assert result["target"]["commit"] != PR_BASE_COMMIT or result["target"]["dirty"]
    assert result["base"]["module_sha256"] != result["target"]["module_sha256"]
    assert result["unapproved_differences"] == {}
    assert set(result["scenarios"]) == set(result["comparisons"])


def test_t009_revision_differential_rejects_identical_revision() -> None:
    from scripts.ci.compare_report_renderer_revisions import DifferentialError, compare_revisions

    with pytest.raises(DifferentialError, match="distinct revisions"):
        compare_revisions(ROOT, PR_BASE_COMMIT, ROOT, target_revision=PR_BASE_COMMIT)

def test_t009_delivery_evidence_rejects_missing_or_extra_file() -> None:
    payload = _load("repoground-legacy-t009-delivery.evidence.json")
    evidence_files = payload["evidence_files"]
    assert isinstance(evidence_files, dict)
    removed_name = next(iter(evidence_files))
    removed = evidence_files.pop(removed_name)
    with pytest.raises(AssertionError):
        _validate_delivery_evidence_shape(payload)
    evidence_files[removed_name] = removed
    evidence_files["unexpected.json"] = {"path": "unexpected.json", "sha256": "0" * 64}
    with pytest.raises(AssertionError):
        _validate_delivery_evidence_shape(payload)


def test_t009_delivery_evidence_rejects_missing_receipt_reference() -> None:
    payload = _load("repoground-legacy-t009-delivery.evidence.json")
    complexity = payload["complexity"]
    assert isinstance(complexity, dict)
    complexity.pop("lifecycle_receipt_sha256")
    with pytest.raises(AssertionError):
        _validate_delivery_evidence_shape(payload)

def _validate_corrective_evidence_shape(payload: dict[str, object]) -> None:
    assert payload["kind"] == "repoground.corrective_delivery_evidence"
    assert payload["version"] == "2.1"
    assert payload["status"] == "pending"
    assert payload["verification_status"] == "pass"
    assert payload["delivery_status"] == "pending"
    evidence_files = payload["evidence_files"]
    assert isinstance(evidence_files, dict)
    assert set(evidence_files) == CORRECTIVE_EVIDENCE_FILES
    for name, record in evidence_files.items():
        assert isinstance(record, dict), name
        assert set(record) == {"path", "sha256"}, name
        assert record["path"] == f"docs/proofs/{name}", name
        digest = record["sha256"]
        assert isinstance(digest, str) and len(digest) == 64, name
        assert digest != "0" * 64, name
    for section in CORRECTIVE_RECEIPT_SECTIONS:
        section_payload = payload[section]
        assert isinstance(section_payload, dict), section
        assert section_payload["status"] == "pass", section
        receipt = section_payload["lifecycle_receipt_sha256"]
        assert isinstance(receipt, str) and len(receipt) == 64, section
        assert receipt != "0" * 64, section


def test_t009_corrective_v2_evidence_is_revision_bound_and_pending() -> None:
    payload = _load("repoground-legacy-t009-delivery.evidence-v2.json")
    _validate_corrective_evidence_shape(payload)
    assert payload["binding"] == {
        "evidence_parent_commit": CORRECTIVE_IMPLEMENTATION_COMMIT,
        "implementation_commit": CORRECTIVE_IMPLEMENTATION_COMMIT,
        "implementation_tree": CORRECTIVE_IMPLEMENTATION_TREE,
        "merged_defect_commit": MERGED_DEFECT_COMMIT,
        "merged_defect_tree": MERGED_DEFECT_TREE,
        "pr_base_commit": PR_BASE_COMMIT,
        "pr_number": 1098,
        "worktree_dirty_when_measured": False,
    }
    assert payload["final_validation"]["status"] == "pending"
    assert payload["final_delivery"]["status"] == "pending"


def test_t009_corrective_v2_artifacts_match_hashes_and_bindings() -> None:
    payload = _load("repoground-legacy-t009-delivery.evidence-v2.json")
    evidence_files = payload["evidence_files"]
    assert isinstance(evidence_files, dict)
    for name, record in evidence_files.items():
        assert isinstance(record, dict), name
        assert _sha256(ROOT / record["path"]) == record["sha256"], name

    complexity = _load(
        "repoground-legacy-t009-complexity.corrective-v2.measurement.json"
    )
    assert complexity["status"] == "pass"
    assert complexity["binding"] == {
        "commit": CORRECTIVE_IMPLEMENTATION_COMMIT,
        "source": "clean_git_worktree",
        "tree": CORRECTIVE_IMPLEMENTATION_TREE,
        "worktree_dirty": False,
    }
    assert complexity["complexity"]["observed_budget_dimensions"] == {
        "excess_total": 2395,
        "finding_count": 197,
        "max_complexity": 138,
    }

    differential = _load("repoground-legacy-t009-differential.corrective-v2.json")
    assert differential["base"]["commit"] == PR_BASE_COMMIT
    assert differential["target"] == {
        "commit": CORRECTIVE_IMPLEMENTATION_COMMIT,
        "dirty": False,
        "module_sha256": "516ff69f982473396dd2cd9358a152a8f693bb77576f1a4b983521c3cb5c4708",
        "tree": CORRECTIVE_IMPLEMENTATION_TREE,
        "worktree_diff_sha256": None,
    }
    assert differential["unapproved_differences"] == {}

    comparison = _load(
        "repoground-legacy-t009-performance.corrective-v2.comparison.json"
    )
    assert comparison["status"] == "pass"
    assert comparison["failed_cases"] == []
    assert comparison["bindings"]["before"] == {
        "commit": MERGED_DEFECT_COMMIT,
        "source": "clean_git_worktree",
        "tree": MERGED_DEFECT_TREE,
        "worktree_dirty": False,
    }
    assert comparison["bindings"]["after"] == {
        "commit": CORRECTIVE_IMPLEMENTATION_COMMIT,
        "source": "clean_git_worktree",
        "tree": CORRECTIVE_IMPLEMENTATION_TREE,
        "worktree_dirty": False,
    }
    assert comparison["gate"] == {
        "median_regression_pct_max": 5.0,
        "peak_memory_regression_pct_max": 5.0,
    }
    for name, result in comparison["compared_cases"].items():
        assert result["status"] in {"pass", "skip"}, name


def test_t009_corrective_v2_rejects_missing_evidence_or_receipt() -> None:
    payload = _load("repoground-legacy-t009-delivery.evidence-v2.json")
    evidence_files = payload["evidence_files"]
    assert isinstance(evidence_files, dict)
    removed_name = next(iter(evidence_files))
    removed_record = evidence_files.pop(removed_name)
    with pytest.raises(AssertionError):
        _validate_corrective_evidence_shape(payload)
    evidence_files[removed_name] = removed_record
    complexity = payload["complexity"]
    assert isinstance(complexity, dict)
    complexity["lifecycle_receipt_sha256"] = "0" * 64
    with pytest.raises(AssertionError):
        _validate_corrective_evidence_shape(payload)
