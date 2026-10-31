"""Authenticated publisher batch may reuse revision graph work, never source trust."""
from __future__ import annotations

from pathlib import Path

import pytest

from merger.repoground.core import agent_evidence_pack as evidence
from merger.repoground.core import event_handoff
from merger.repoground.tests.test_agent_evidence_pack import (
    git,
    seeded_repo,
)


def test_same_revision_two_use_cases_share_only_graph_and_preserve_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, base, head = seeded_repo(tmp_path)
    kwargs = dict(repo_root=repo, base_revision=base, target_revision=head)
    # Compare complete existing output contracts, including per-use-case gaps.
    first_baseline = evidence.build_evidence_pack(**kwargs, use_case="explain-change")
    second_baseline = evidence.build_evidence_pack(**kwargs, use_case="find-related-tests")
    real_compile = evidence.compile_revision_impact
    calls = []

    def count_compile(**args):
        calls.append((args["base_sha"], args["head_sha"]))
        return real_compile(**args)

    monkeypatch.setattr(evidence, "compile_revision_impact", count_compile)
    with event_handoff.reuse_event_evidence_packs():
        first = evidence.build_evidence_pack(**kwargs, use_case="explain-change")
        second = evidence.build_evidence_pack(**kwargs, use_case="find-related-tests")
    assert first == first_baseline
    assert second == second_baseline
    assert len(calls) == 1

    # No global or cross-batch reuse, even for an identical source revision.
    with event_handoff.reuse_event_evidence_packs():
        again = evidence.build_evidence_pack(**kwargs, use_case="find-related-tests")
    assert again == second_baseline
    assert len(calls) == 2


def test_cached_structural_impact_rechecks_ignored_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, base, head = seeded_repo(tmp_path)
    kwargs = dict(repo_root=repo, base_revision=base, target_revision=head)
    real_compile = evidence.compile_revision_impact
    calls = []

    def count_compile(**args):
        calls.append(args)
        return real_compile(**args)

    monkeypatch.setattr(evidence, "compile_revision_impact", count_compile)
    with event_handoff.reuse_event_evidence_packs():
        before = evidence.build_evidence_pack(**kwargs, use_case="explain-change")
        assert before["structural_impact"]["status"] in {"bounded", "partial"}
        exclude = repo / ".git" / "info" / "exclude"
        exclude.write_text(exclude.read_text() + "\nshadow.py\n", encoding="utf-8")
        (repo / "shadow.py").write_text("def untracked(): return 1\n", encoding="utf-8")
        # Standard porcelain looks clean, but the graph source inventory differs.
        assert git(repo, "status", "--porcelain") == ""
        after = evidence.build_evidence_pack(**kwargs, use_case="find-related-tests")
    assert len(calls) == 1  # forbidden cached report, no false S1 recompilation
    assert after["structural_impact"]["status"] == "unavailable"
    assert after["structural_impact"]["gap"]["reason"] == "structural_revision_unavailable"
    assert "ignored_source_not_in_head" in after["structural_impact"]["gap"]["detail"]


def test_new_source_commit_never_reuses_old_revision_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, base, head = seeded_repo(tmp_path)
    real_compile = evidence.compile_revision_impact
    heads = []

    def count_compile(**args):
        heads.append(args["head_sha"])
        return real_compile(**args)

    monkeypatch.setattr(evidence, "compile_revision_impact", count_compile)
    with event_handoff.reuse_event_evidence_packs():
        first = evidence.build_evidence_pack(
            repo_root=repo, base_revision=base, target_revision=head,
        )
        assert first["structural_impact"]["status"] in {"bounded", "partial"}
        (repo / "new.py").write_text("def changed(): return 2\n", encoding="utf-8")
        git(repo, "add", "new.py")
        git(repo, "commit", "-qm", "different revision")
        next_head = git(repo, "rev-parse", "HEAD")
        second = evidence.build_evidence_pack(
            repo_root=repo, base_revision=head, target_revision=next_head,
            use_case="find-related-tests",
        )
    assert heads == [head, next_head]
    assert second["structural_impact"]["status"] in {"bounded", "partial"}
    assert second["structural_impact"]["source_provenance"]["source_commit"] == next_head


def test_failed_graph_is_not_cached_even_within_one_batch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, base, head = seeded_repo(tmp_path)
    real_compile = evidence.compile_revision_impact
    call_count = 0

    def fail_once(**args):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise ValueError("temporary_graph_unavailable")
        return real_compile(**args)

    monkeypatch.setattr(evidence, "compile_revision_impact", fail_once)
    with event_handoff.reuse_event_evidence_packs():
        first = evidence.build_evidence_pack(
            repo_root=repo, base_revision=base, target_revision=head,
        )
        second = evidence.build_evidence_pack(
            repo_root=repo, base_revision=base, target_revision=head,
            use_case="find-related-tests",
        )
    assert call_count == 2
    assert first["structural_impact"]["status"] == "unavailable"
    assert second["structural_impact"]["status"] in {"bounded", "partial"}
