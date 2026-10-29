"""Real Git evidence through the existing CLI/MCP change-pack compiler."""
import hashlib
import json
import os

import pytest

from merger.repoground.core import agent_evidence_pack, history_lens
from merger.repoground.core.agent_evidence_pack import (
    MAX_DIFF_BYTES, _bounded_git, build_evidence_pack, render_evidence_markdown,
)
from merger.repoground.core.delta_context import compile_revision_impact
from merger.repoground.core.revision_graph_impact import _git as revision_git
from merger.repoground.tests.test_agent_evidence_pack import (
    git, isolate_global_git_config as isolate_global_git_config, manifest, seeded_repo,
)


def test_real_commits_keep_bundle_and_structural_identities_separate(tmp_path):
    repo, base, head = seeded_repo(tmp_path)
    bundled = manifest(tmp_path, base)
    data = json.loads(bundled.read_text())
    data["generator"] = {"runtime": {"git_commit": base, "git_dirty": False}}
    bundled.write_text(json.dumps(data), encoding="utf-8")
    manifest_bytes = bundled.read_bytes()
    kwargs = dict(repo_root=repo, base_revision=base, target_revision=head,
                  bundle_manifest=bundled, context_budget_tokens=4000)
    pack = build_evidence_pack(**kwargs)
    assert pack["revision"]["worktree"] == "clean"
    assert build_evidence_pack(**kwargs) == pack
    raw = compile_revision_impact(repo_root=repo, base_sha=base, head_sha=head)
    structural = pack["structural_impact"]
    assert structural["status"] in {"bounded", "partial"}
    assert structural["source_provenance"] == raw["source_provenance"]
    assert structural["source_provenance"]["source_commit"] == head
    identity = structural["source_provenance"]["manifest_identity"]
    assert identity["is_bundle_manifest"] is False
    assert identity["status"] == "derived_not_published"
    bundle = pack["bundle"]
    assert bundle["source_commit"] == bundle["generator_commit"] == base
    assert bundle["generator_dirty"] is False
    assert bundle["run_id"] == "seeded"
    assert bundle["manifest_filename"] == bundled.name
    assert bundle["manifest_sha256"] == hashlib.sha256(manifest_bytes).hexdigest()
    encoded = json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    assert structural["derived_source_report_sha256"] == hashlib.sha256(encoded).hexdigest()
    assert structural["revision"] == {key: raw[key] for key in ("base_sha", "head_sha", "diff_sha256", "diff_bytes")}
    assert structural["revision"]["diff_sha256"] != pack["revision"]["diff_sha256"]
    assert any(row["category"] == "directly_changed" and row["evidence"].get("symbol_id") == "py:alpha.py:function:old"
               for row in structural["context"])
    assert all(row["evidence"] in raw[row["category"]] for row in structural["context"])
    markdown = render_evidence_markdown(pack)
    assert structural["revision"]["diff_sha256"] in markdown
    assert structural["derived_source_report_sha256"] in markdown
    assert bundle["manifest_sha256"] in markdown
    assert bundled.read_bytes() == manifest_bytes
    assert git(repo, "rev-parse", "HEAD") == head
    assert not (repo / ".git/index.lock").exists()


@pytest.mark.parametrize("state", ["dirty", "historical"])
def test_unproven_checkout_keeps_git_diff_and_reports_s0(tmp_path, monkeypatch, state):
    repo, base, head = seeded_repo(tmp_path)
    if state == "dirty":
        (repo / "untracked.txt").write_text("local work\n")
    else:
        git(repo, "switch", "--detach", "-q", base)
    checkout = git(repo, "rev-parse", "HEAD")
    before = (repo / "alpha.py").read_bytes()
    def forbidden_compile(*args, **kwargs):
        pytest.fail("Structural compilation ran without proven checkout preconditions")
    monkeypatch.setattr(agent_evidence_pack, "compile_revision_impact", forbidden_compile)
    pack = build_evidence_pack(repo_root=repo, base_revision=base, target_revision=head)
    structural = pack["structural_impact"]
    reason = "structural_worktree_not_clean" if state == "dirty" else "structural_target_not_checked_out"
    assert structural["status"] == "unavailable"
    assert structural["context"] == []
    assert structural["gap"]["reason"] == reason
    assert structural["gap"]["evidence_level"] == "S0"
    assert reason in {row["code"] for row in pack["gaps"]}
    assert [row["path"] for row in pack["changed_files"]] == ["alpha.py"]
    assert git(repo, "rev-parse", "HEAD") == checkout
    assert (repo / "alpha.py").read_bytes() == before


@pytest.mark.parametrize("operation", ["rename", "delete"])
def test_tiny_budget_keeps_rename_or_deletion_s0_summary(tmp_path, operation):
    repo, _, _ = seeded_repo(tmp_path)
    (repo / "schemas").mkdir()
    (repo / "schemas/core.json").write_text('{"type":"object"}\n')
    (repo / "schemas/consumer.json").write_text('{"$ref":"./core.json"}\n')
    git(repo, "add", "schemas")
    git(repo, "commit", "-qm", "referenced schema")
    base = git(repo, "rev-parse", "HEAD")
    if operation == "rename":
        git(repo, "mv", "schemas/core.json", "schemas/renamed.json")
        reason = "renamed_away_file_incoming_relations_not_analyzed"
    else:
        git(repo, "rm", "schemas/core.json")
        reason = "deleted_file_incoming_relations_not_analyzed"
    git(repo, "commit", "-qm", "remove old target")
    head = git(repo, "rev-parse", "HEAD")
    raw = compile_revision_impact(repo_root=repo, base_sha=base, head_sha=head)
    assert any(row["reason"] == reason and row["evidence_level"] == "S0" for row in raw["gaps"])
    for budget in (1, 96):
        pack = build_evidence_pack(repo_root=repo, base_revision=base, target_revision=head,
                                   context_budget_tokens=budget)
        assert pack["revision"]["worktree"] == "clean"
        structural, selection = pack["structural_impact"], pack["context_selection"]
        hard = selection["hard_budgets"]
        assert structural["status"] == "partial"
        assert structural["reported_gap_reason_counts"][reason] == 1
        assert structural["coverage"] == raw["coverage"]
        assert structural["display_omitted_count"] == selection["omitted_structural_count"]
        assert selection["scope"] == "hint_and_structural_detail_rows"
        assert 0 <= hard["used_tokens"] <= hard["tokens"] <= budget
        assert 0 <= hard["used_bytes"] <= hard["bytes"] <= budget * 4
        displayed_bytes = sum(len(json.dumps(rows, ensure_ascii=False, sort_keys=True,
                                             separators=(",", ":")).encode())
                              for rows in (pack["hints"], structural["context"]))
        assert displayed_bytes <= budget * 4
        if budget == 1:
            assert pack["hints"] == structural["context"] == []
            assert structural["display_omitted_count"] > 0
            assert "context_budget_omitted_candidates" in {row["code"] for row in pack["gaps"]}


@pytest.mark.parametrize("driver", ["clean", "process"])
def test_direct_revision_compiler_does_not_execute_filters(tmp_path, monkeypatch, driver):
    repo, base, _ = seeded_repo(tmp_path)
    (repo / ".gitattributes").write_text("alpha.py filter=probe\n")
    git(repo, "add", ".gitattributes")
    git(repo, "commit", "-qm", "declare filter")
    head = git(repo, "rev-parse", "HEAD")
    marker, program = tmp_path / "filter-ran", tmp_path / "filter"
    program.write_text('#!/bin/sh\nprintf invoked > "$PROBE_MARKER"\nexit 1\n')
    program.chmod(0o700)
    monkeypatch.setenv("PROBE_MARKER", str(marker))
    git(repo, "config", f"filter.probe.{driver}", str(program))
    stat = (repo / "alpha.py").stat()
    os.utime(repo / "alpha.py", ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
    index = (repo / ".git/index").read_bytes()
    with pytest.raises(ValueError, match="executable_git_filter_configured"):
        compile_revision_impact(repo_root=repo, base_sha=base, head_sha=head)
    assert not marker.exists()
    assert (repo / ".git/index").read_bytes() == index
    assert not (repo / ".git/index.lock").exists()


def test_direct_revision_uses_real_objects_and_ignores_inherited_git_overrides(tmp_path, monkeypatch):
    repo, base, target = seeded_repo(tmp_path)
    tree = git(repo, "rev-parse", f"{target}^{{tree}}")
    git(repo, "switch", "--detach", "-q", base)
    (repo / "beta.py").write_text("value = 5\n")
    git(repo, "add", "beta.py")
    git(repo, "commit", "-qm", "replacement")
    replacement = git(repo, "rev-parse", "HEAD")
    git(repo, "switch", "--detach", "-q", target)
    git(repo, "replace", target, replacement)
    assert git(repo, "diff", "--name-only", base, target) == "beta.py"
    trace = tmp_path / "forbidden-trace.json"
    with monkeypatch.context() as patch:
        patch.setenv("GIT_NO_REPLACE_OBJECTS", "0")
        patch.setenv("GIT_TRACE2_EVENT", str(trace))
        patch.setenv("GIT_OBJECT_DIRECTORY", str(tmp_path / "nonexistent-objects"))
        report = compile_revision_impact(repo_root=repo, base_sha=base, head_sha=target)
    assert report["source_provenance"]["source_commit"] == target
    assert report["source_provenance"]["source_tree"] == tree
    assert {row["path"] for row in report["directly_changed"]} == {"alpha.py"}
    assert not trace.exists()
    assert git(repo, "replace", "-l") == target


def test_shared_reader_retains_distinct_evidence_caps(tmp_path):
    repo, _, _ = seeded_repo(tmp_path)
    payload = b"x" * 2_000_001
    (repo / "large.txt").write_bytes(payload)
    git(repo, "add", "large.txt")
    git(repo, "commit", "-qm", "large blob")
    blob = git(repo, "rev-parse", "HEAD:large.txt")
    with pytest.raises(ValueError, match="bounded read limit"):
        history_lens._git_read(repo, "cat-file", "blob", blob)
    with pytest.raises(ValueError, match="budget is invalid"):
        history_lens._git_read(repo, "cat-file", "blob", blob, max_bytes=2_000_001)
    assert revision_git(repo, ["cat-file", "blob", blob]) == payload
    assert revision_git(repo, ["cat-file", "blob", blob], max_bytes=8_000_000) == payload
    with pytest.raises(ValueError, match="budget is invalid"):
        history_lens._bounded_git_read(repo, "cat-file", "blob", blob, max_bytes=8_000_001)
    output, problem = _bounded_git(repo, ["cat-file", "blob", blob], max_bytes=MAX_DIFF_BYTES)
    assert output is None and problem == "git_output_limit"
