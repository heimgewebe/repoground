import copy
from pathlib import Path

from merger.repoground.core.system_relation_context import (
    project_system_relation_context,
)
from merger.repoground.core.system_relation_producer import (
    collect_system_relation_evidence,
)
from merger.repoground.tests.git_fixture import commit_fixture

OTHER_COMMIT = "e" * 40


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _result(root: Path) -> dict:
    _write(
        root / ".github" / "workflows" / "reuse.yml",
        "name: reuse\non:\n  workflow_call:\njobs: {}\n",
    )
    _write(
        root / ".github" / "workflows" / "caller.yml",
        "name: caller\njobs:\n  delegated:\n    uses: ./.github/workflows/reuse.yml\n",
    )
    commit = commit_fixture(root)
    return collect_system_relation_evidence(
        root,
        repository_identity="example/repository",
        repository_commit=commit,
    )


def test_projects_only_relevant_records_after_commit_and_digest_revalidation(tmp_path):
    producer_result = _result(tmp_path)

    context = project_system_relation_context(
        producer_result,
        repository_commit=producer_result["repository"]["commit"],
        target_paths={".github/workflows/reuse.yml"},
    )

    assert context["status"] == "available"
    assert context["relevant_record_count"] == 1
    assert context["records"][0]["relation"] == "references_workflow"
    assert context["records"][0]["target"]["identity"] == ".github/workflows/reuse.yml"
    assert context["binding"] == {
        "expected_repository_commit": producer_result["repository"]["commit"],
        "observed_repository_commit": producer_result["repository"]["commit"],
        "expected_evidence_sha256": producer_result["evidence_sha256"],
        "observed_evidence_sha256": producer_result["evidence_sha256"],
    }


def test_commit_mismatch_blocks_without_projecting_records(tmp_path):
    producer_result = _result(tmp_path)

    context = project_system_relation_context(
        producer_result,
        repository_commit=OTHER_COMMIT,
        target_paths={".github/workflows/caller.yml"},
    )

    assert context["status"] == "blocked"
    assert context["reason"] == "repository_commit_mismatch"
    assert context["records"] == []


def test_revision_binding_mismatch_blocks_without_projecting_records(tmp_path):
    producer_result = _result(tmp_path)
    tampered = copy.deepcopy(producer_result)
    tampered["revision_binding"]["verified"] = False

    context = project_system_relation_context(
        tampered,
        repository_commit=producer_result["repository"]["commit"],
        target_paths={".github/workflows/caller.yml"},
    )

    assert context["status"] == "blocked"
    assert context["reason"] == "revision_binding_incompatible"
    assert context["records"] == []


def test_digest_mismatch_blocks_without_projecting_records(tmp_path):
    producer_result = _result(tmp_path)
    tampered = copy.deepcopy(producer_result)
    tampered["evidence"]["producer"]["version"] = "tampered"

    context = project_system_relation_context(
        tampered,
        repository_commit=producer_result["repository"]["commit"],
        target_paths={".github/workflows/caller.yml"},
    )

    assert context["status"] == "blocked"
    assert context["reason"] == "evidence_digest_mismatch"
    assert context["records"] == []


def test_overlay_mismatch_blocks_after_raw_evidence_revalidation(tmp_path):
    producer_result = _result(tmp_path)
    tampered = copy.deepcopy(producer_result)
    tampered["overlay"]["records"] = []
    tampered["overlay"]["record_count"] = 0

    context = project_system_relation_context(
        tampered,
        repository_commit=producer_result["repository"]["commit"],
        target_paths={".github/workflows/caller.yml"},
    )

    assert context["status"] == "blocked"
    assert context["reason"] == "overlay_revalidation_mismatch"
    assert context["records"] == []


def test_missing_optional_evidence_is_visible_without_false_activation():
    context = project_system_relation_context(
        None,
        repository_commit=OTHER_COMMIT,
        target_paths={"pyproject.toml"},
    )

    assert context["status"] == "missing"
    assert context["reason"] == "system_relation_evidence_missing"
    assert context["records"] == []
    assert context["relevant_record_count"] == 0
