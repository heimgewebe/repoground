"""Tests for the read-only Patch Evaluation artifact consumer/validator (v1).

The consumer is a court clerk, not a judge: it checks form, records evidence,
and pins authority to ``external_evaluation_evidence``. These tests exercise the
fail-closed schema validation, the mandatory non-claim enforcement, the strict
``additionalProperties`` boundary, and the read-only guarantee (no shell, Git,
patch, worktree, or secret usage anywhere in the module).
"""
import argparse
import json
from pathlib import Path

import pytest

from merger.lenskit.core import patch_evaluation as pe

_EXAMPLE_PATH = (
    Path(__file__).resolve().parent.parent
    / "contracts"
    / "examples"
    / "patch-evaluation.v1.json"
)

_REQUIRED_NON_CLAIMS = [
    "correctness",
    "test_sufficiency",
    "security_correctness",
    "runtime_behavior_outside_evaluated_commands",
    "merge_authorization",
    "merge_readiness",
    "regression_absence",
    "repo_understood",
    "claims_true",
]


def _minimal_artifact():
    return {
        "kind": "repobrief.patch_evaluation",
        "version": "v1",
        "authority": "external_evaluation_evidence",
        "producer": {"name": "sidecar", "version": "0.1.0"},
        "created_at": "2026-07-06T12:00:00Z",
        "input": {},
        "repobrief_context": {},
        "workspace": {"isolated": True},
        "patch": {"applied": True},
        "command_policy": {},
        "commands_run": [],
        "environment": {},
        "status": "incomplete",
        "does_not_establish": list(_REQUIRED_NON_CLAIMS),
    }


def _status(report):
    return report["status"]


# 1. A valid minimal artifact (and the shipped example) validates.
def test_minimal_artifact_validates():
    report = pe.validate_patch_evaluation(_minimal_artifact())
    assert _status(report) == "pass"


def test_example_fixture_validates():
    data = pe.load_patch_evaluation(_EXAMPLE_PATH)
    report = pe.validate_patch_evaluation(data)
    assert _status(report) == "pass"


# 2. Missing a mandatory non-claim fails.
def test_missing_mandatory_non_claim_fails():
    art = _minimal_artifact()
    art["does_not_establish"] = [c for c in _REQUIRED_NON_CLAIMS if c != "merge_authorization"]
    report = pe.validate_patch_evaluation(art)
    assert _status(report) == "fail"


# 3. An unknown root field fails (additionalProperties: false).
def test_unknown_root_field_fails():
    art = _minimal_artifact()
    art["surprise"] = True
    report = pe.validate_patch_evaluation(art)
    assert _status(report) == "fail"


# 4. An unknown top-level status fails.
def test_unknown_top_level_status_fails():
    art = _minimal_artifact()
    art["status"] = "approved"
    report = pe.validate_patch_evaluation(art)
    assert _status(report) == "fail"


# 5. An unknown command status fails.
def test_unknown_command_status_fails():
    art = _minimal_artifact()
    art["commands_run"] = [{"command": "python -m pytest", "status": "greenish"}]
    report = pe.validate_patch_evaluation(art)
    assert _status(report) == "fail"


# 6. The consumer reports authority as external evidence.
def test_consumer_marks_authority_external_evidence():
    art = _minimal_artifact()
    summary = pe.summarize_patch_evaluation(art)
    assert summary["authority"] == "external_evaluation_evidence"
    report = pe.validate_patch_evaluation(art)
    assert report["authority"] == "external_evaluation_evidence"
    # Even a 'passed' declared status must not upgrade the authority.
    art["status"] = "passed"
    assert pe.summarize_patch_evaluation(art)["authority"] == "external_evaluation_evidence"


# 7. The consumer surfaces does_not_establish.
def test_consumer_outputs_does_not_establish():
    art = _minimal_artifact()
    summary = pe.summarize_patch_evaluation(art)
    assert summary["does_not_establish"] == list(_REQUIRED_NON_CLAIMS)
    # Consuming adds no authority of its own.
    assert "merge_readiness" in summary["consumer_does_not_establish"]
    assert "merge_authorization" in summary["consumer_does_not_establish"]


# 8. The consumer does not mutate: no shell, Git, patch-apply, worktree, or write
#    surface anywhere in the module (checked via AST, so the boundary described in
#    the docstring does not create false positives).
def test_consumer_module_has_no_mutation_surface():
    import ast

    tree = ast.parse(Path(pe.__file__).read_text(encoding="utf-8"))

    imported_roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".")[0])

    forbidden_imports = {
        "subprocess",
        "shutil",
        "socket",
        "requests",
        "urllib",
        "urllib3",
        "httpx",
        "git",
        "pygit2",
        "os",
    }
    assert imported_roots & forbidden_imports == set(), (
        f"consumer imports forbidden mutation/shell/network modules: "
        f"{sorted(imported_roots & forbidden_imports)}"
    )

    # No call to a mutating/executing attribute or builtin.
    forbidden_attrs = {
        "system", "popen", "Popen", "run", "call", "check_output", "check_call",
        "rmtree", "unlink", "mkdir", "rename", "replace", "remove",
        "write_text", "write_bytes", "write",
    }
    forbidden_builtins = {"open", "exec", "eval", "compile", "__import__"}
    bad: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr in forbidden_attrs:
                bad.append(func.attr)
            elif isinstance(func, ast.Name) and func.id in forbidden_builtins:
                bad.append(func.id)
    assert bad == [], f"consumer module calls forbidden mutation surface: {sorted(set(bad))}"


def test_load_accepts_mapping_without_filesystem_access(tmp_path, monkeypatch):
    # A Mapping input must be returned as a plain dict without any file read.
    def _boom(*args, **kwargs):  # pragma: no cover - only fails if called
        raise AssertionError("load must not touch the filesystem for a Mapping input")

    monkeypatch.setattr(Path, "read_text", _boom)
    loaded = pe.load_patch_evaluation(_minimal_artifact())
    assert loaded["kind"] == "repobrief.patch_evaluation"
    assert isinstance(loaded, dict)


def test_diagnostics_flags_missing_non_claims_and_isolation():
    art = _minimal_artifact()
    art["does_not_establish"] = [c for c in _REQUIRED_NON_CLAIMS if c != "regression_absence"]
    art["workspace"] = {"isolated": False}
    diag = pe.patch_evaluation_diagnostics(art)
    assert "regression_absence" in diag["missing_non_claims"]
    classes = {d["class"] for d in diag["degradations"]}
    assert "missing_non_claims" in classes
    assert "workspace_not_isolated" in classes


def test_diagnostics_tolerates_malformed_non_claim_members():
    art = _minimal_artifact()
    art["does_not_establish"] = [{"not": "hashable"}, 7, "correctness"]

    diag = pe.patch_evaluation_diagnostics(art)  # must not raise

    assert "correctness" not in diag["missing_non_claims"]
    assert "merge_readiness" in diag["missing_non_claims"]
    classes = {d["class"] for d in diag["degradations"]}
    assert "missing_non_claims" in classes


# Regression (Codex P2): the summary path must tolerate malformed scalar context
# fields instead of raising TypeError from list(scalar). The --summary CLI flag
# summarizes regardless of the validation verdict, so a schema-invalid artifact
# must still yield the failing validation JSON, never a traceback.
def test_summary_tolerates_malformed_scalar_context_fields():
    art = _minimal_artifact()
    art["repobrief_context"] = {
        "citations": 123,            # scalar int -> would raise list(int)
        "cited_ranges": "cit-oops",  # scalar str -> would splat into chars
        "workbench_outputs": None,   # null
    }
    art["does_not_establish"] = 99   # scalar int -> would raise list(int)

    summary = pe.summarize_patch_evaluation(art)  # must not raise
    assert summary["referenced_citations"] == []
    assert summary["referenced_ranges"] == []
    assert summary["referenced_workbench_outputs"] == []
    assert summary["does_not_establish"] == []
    assert summary["authority"] == "external_evaluation_evidence"


def test_cli_summary_on_malformed_artifact_returns_validation_json_not_traceback(tmp_path, capsys):
    from merger.lenskit.cli import cmd_repobrief

    art = _minimal_artifact()
    art["repobrief_context"] = {"citations": 7}  # invalid scalar; schema will also reject
    path = tmp_path / "malformed.json"
    path.write_text(json.dumps(art), encoding="utf-8")

    args = argparse.Namespace(path=str(path), summary=True)
    rc = cmd_repobrief.run_patch_evaluation_validate(args)  # must not raise

    assert rc == 1  # schema-invalid -> validation fails
    out = json.loads(capsys.readouterr().out)  # well-formed JSON, no traceback
    assert out["validation"]["status"] == "fail"
    assert out["summary"]["authority"] == "external_evaluation_evidence"


def test_load_rejects_non_object(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    with pytest.raises(ValueError):
        pe.load_patch_evaluation(bad)
