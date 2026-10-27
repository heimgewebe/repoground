"""Deterministic read-only change pack regression and failure boundaries."""
import hashlib
import json
import subprocess
from pathlib import Path

from merger.repoground.cli.main import main
from merger.repoground.core.agent_evidence_pack import (
    build_evidence_pack, render_evidence_markdown,
)


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def seeded_repo(tmp_path: Path) -> tuple[Path, str, str]:
    repo = tmp_path / "source"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "Fixture")
    git(repo, "config", "user.email", "fixture@example.invalid")
    (repo / "alpha.py").write_text("def old():\n    return 1\n", encoding="utf-8")
    git(repo, "add", "alpha.py")
    git(repo, "commit", "-qm", "base")
    base = git(repo, "rev-parse", "HEAD")
    (repo / "alpha.py").write_text("def old():\n    return 2\n", encoding="utf-8")
    git(repo, "add", "alpha.py")
    git(repo, "commit", "-qm", "change")
    head = git(repo, "rev-parse", "HEAD")
    return repo, base, head


def manifest(tmp_path: Path, commit: str) -> Path:
    bundle = tmp_path / "existing.bundle.manifest.json"
    bundle.write_text(
        json.dumps({
            "kind": "repolens.bundle.manifest", "run_id": "seeded",
            "artifacts": [],
            "snapshot_provenance": {
                "version": "v1",
                "repositories": [{"git_commit": commit}],
            },
        }),
        encoding="utf-8",
    )
    return bundle


def test_repeated_same_git_and_bundle_are_byte_identical(tmp_path):
    repo, base, head = seeded_repo(tmp_path)
    bundled = manifest(tmp_path, base)
    untouched = git(repo, "status", "--porcelain")
    first = build_evidence_pack(
        repo_root=repo, base_revision=base, target_revision=head,
        bundle_manifest=bundled,
    )
    second = build_evidence_pack(
        repo_root=repo, base_revision=base, target_revision=head,
        bundle_manifest=bundled,
    )
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert first["kind"] == "repoground.agent_change_evidence"
    assert first["status"] in {"pass", "warn"}
    assert first["revision"]["base"] == base
    assert first["revision"]["target"] == head
    assert first["revision"]["worktree"] == "clean"
    assert first["bundle"]["source_commit"] == base
    assert first["changed_files"][0]["path"] == "alpha.py"
    assert first["changed_files"][0]["ranges"]
    assert first["changed_files"][0]["claim_level"] == "direct_git_diff"
    assert all(h["claim_level"] == "bundle_navigation_hint_not_verified_impact" for h in first["hints"])
    assert git(repo, "status", "--porcelain") == untouched
    assert not list(tmp_path.rglob("current.json"))
    assert "No review verdict" in render_evidence_markdown(first)


def test_git_diff_sha_and_invalid_expected_sha_are_fail_closed(tmp_path):
    repo, base, head = seeded_repo(tmp_path)
    diff = subprocess.run(
        ["git", "-C", str(repo), "diff", "--no-ext-diff", "--no-textconv",
         "--no-renames", "--unified=3", base, head, "--"],
        capture_output=True, check=True,
    ).stdout
    digest = hashlib.sha256(diff).hexdigest()
    yes = build_evidence_pack(
        repo_root=repo, base_revision=base, target_revision=head,
        expected_diff_sha256=digest,
    )
    assert yes["revision"]["diff_sha256"] == digest
    no = build_evidence_pack(
        repo_root=repo, base_revision=base, target_revision=head,
        expected_diff_sha256="0" * 64,
    )
    assert no["status"] == "invalid"
    assert no["reason"] == "diff_sha256_mismatch"


def test_no_bundle_no_fake_tests_and_no_implicit_snapshot(tmp_path):
    repo, base, head = seeded_repo(tmp_path)
    result = build_evidence_pack(
        repo_root=repo, base_revision=base, target_revision=head,
        use_case="find-related-tests",
    )
    assert result["bundle"]["status"] == "unavailable"
    assert "no_bundle_supplied" in {gap["code"] for gap in result["gaps"]}
    assert result["mutation_boundary"]["writes"] == []
    assert "test_sufficiency" in result["does_not_establish"]
    assert all(h["claim_level"] != "verified_test_coverage" for h in result["hints"])


def test_revisions_and_input_failures_not_interpreted_as_review(tmp_path):
    repo, base, head = seeded_repo(tmp_path)
    bad = build_evidence_pack(
        repo_root=repo, base_revision="--upload-pack", target_revision=head,
    )
    assert bad["status"] == "invalid"
    assert bad["reason"] == "base_must_be_exact_commit_sha"
    missing = build_evidence_pack(
        repo_root=repo, base_revision="0" * 40, target_revision=head,
    )
    assert missing["status"] == "invalid"
    assert missing["reason"] == "unavailable_commit"
    dirty = repo / "untracked"
    dirty.write_text("not part of commit", encoding="utf-8")
    status = build_evidence_pack(
        repo_root=repo, base_revision=base, target_revision=head,
        use_case="cross-repo-impact",
    )
    assert status["status"] == "warn"
    assert status["revision"]["worktree"] == "dirty"
    assert "worktree_dirty" in {gap["code"] for gap in status["gaps"]}


def test_cli_json_and_markdown_share_core_digest(tmp_path, capsys):
    repo, base, head = seeded_repo(tmp_path)
    common = ["agent-evidence", "--repo-root", str(repo), "--base", base, "--target", head]
    assert main(common + ["--emit", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert main(common + ["--emit", "markdown"]) == 0
    rendered = capsys.readouterr().out
    assert payload["response_sha256"] in rendered
    assert payload["revision"]["diff_sha256"] in rendered


def test_related_test_candidates_require_tracked_exact_file_at_target(tmp_path):
    repo, _first, last = seeded_repo(tmp_path)
    (repo / "tests").mkdir()
    (repo / "tests" / "test_alpha.py").write_text(
        "def test_alpha():\n    assert True\n", encoding="utf-8",
    )
    (repo / "tests" / "test_unrelated.py").write_text(
        "def test_unrelated():\n    assert True\n", encoding="utf-8",
    )
    git(repo, "add", "tests")
    git(repo, "commit", "-qm", "add tracked tests")
    base = git(repo, "rev-parse", "HEAD")
    (repo / "alpha.py").write_text(
        "def old():\n    return 3\n", encoding="utf-8",
    )
    git(repo, "add", "alpha.py")
    git(repo, "commit", "-qm", "change implementation again")
    head = git(repo, "rev-parse", "HEAD")
    pack = build_evidence_pack(
        repo_root=repo, base_revision=base, target_revision=head,
        use_case="find-related-tests",
    )
    assert pack["test_candidates"] == [{
        "path": "tests/test_alpha.py",
        "source_path": "alpha.py",
        "candidate_reason": "exact_module_basename_match",
        "verified_fact": "test_path_tracked_at_target_commit",
        "claim_level": "name_candidate_not_verified_coverage",
    }]
    assert "test_coverage_unverified" in {g["code"] for g in pack["gaps"]}
    assert "test_unrelated.py" not in render_evidence_markdown(pack)
    assert pack["revision"]["target"] == head
    assert git(repo, "status", "--porcelain") == ""


def test_contract_impact_reports_only_direct_changed_contract_paths(tmp_path):
    repo, base, head = seeded_repo(tmp_path)
    (repo / "contracts").mkdir()
    (repo / "contracts" / "api.schema.json").write_text(
        '{"type":"object"}', encoding="utf-8",
    )
    git(repo, "add", "contracts/api.schema.json")
    git(repo, "commit", "-qm", "add contract")
    target = git(repo, "rev-parse", "HEAD")
    report = build_evidence_pack(
        repo_root=repo, base_revision=head, target_revision=target,
        use_case="contract-impact",
    )
    assert report["changed_contracts"] == [{
        "path": "contracts/api.schema.json", "claim_level": "direct_git_diff",
    }]
    assert "contract_consumer_relations_unverified" in {
        g["code"] for g in report["gaps"]
    }
    assert report["change_status_counts"]["added"] == 1
    assert all("verified_contract_consumer" not in hint.values() for hint in report["hints"])

def test_mixed_git_quoted_paths_never_silently_omits_changes(tmp_path):
    repo, _base, _head = seeded_repo(tmp_path)
    quoted_name = "line\nbreak.py"
    (repo / quoted_name).write_text("value=1\n", encoding="utf-8")
    git(repo, "add", quoted_name)
    git(repo, "commit", "-qm", "introduce unusual tracked filename")
    base = git(repo, "rev-parse", "HEAD")
    (repo / quoted_name).write_text("value=2\n", encoding="utf-8")
    (repo / "alpha.py").write_text("def old():\n    return 3\n", encoding="utf-8")
    git(repo, "add", quoted_name, "alpha.py")
    git(repo, "commit", "-qm", "change ordinary and quoted filenames")
    head = git(repo, "rev-parse", "HEAD")
    result = build_evidence_pack(
        repo_root=repo, base_revision=base, target_revision=head
    )
    assert result["status"] == "invalid"
    assert result["reason"] == "diff_paths_unresolved"
    assert result["changed_files"] == []
    assert result["mutation_boundary"]["writes"] == []
    assert git(repo, "status", "--porcelain") == ""


def test_git_color_always_does_not_corrupt_parsed_diff(tmp_path):
    repo, base, head = seeded_repo(tmp_path)
    git(repo, "config", "color.ui", "always")
    result = build_evidence_pack(
        repo_root=repo, base_revision=base, target_revision=head
    )
    assert result["status"] in {"pass", "warn"}
    assert result["changed_files"][0]["path"] == "alpha.py"
    assert result["revision"]["diff_sha256"]
    assert result["revision"]["worktree"] == "clean"


def test_selected_symbol_and_relation_hints_retain_safe_navigation_paths(tmp_path, monkeypatch):
    from merger.repoground.core import agent_evidence_pack

    repo, base, head = seeded_repo(tmp_path)
    selected = [
        {"source": "python_symbol_index_json", "symbol": {"path": "pkg/symbol.py"}},
        {"source": "relation_cards_jsonl",
         "source_path": "src/alpha.py", "target_path": "tests/test_alpha.py"},
        {"source": "relation_cards_jsonl",
         "source_path": "../unsafe.py", "target_path": "src/safe.py"},
        {"source": "python_symbol_index_json", "symbol": {"path": "/private/key"}},
        {"source": "relation_cards_jsonl",
         "source_path": "../unsafe.py", "target_path": "/private/key"},
        {"source": "resolved_evidence", "path": "docs/proof.md",
         "source_range": {"start_line": 4, "end_line": 9}},
    ]
    monkeypatch.setattr(
        agent_evidence_pack, "compile_delta_context",
        lambda **_kwargs: {
            "status": "pass",
            "review_context": selected,
            "omitted_context": [],
            "signal_quality": "complete_or_not_requested",
        },
    )
    pack = build_evidence_pack(
        repo_root=repo, base_revision=base, target_revision=head,
        bundle_manifest=manifest(tmp_path, base), context_budget_tokens=4000,
    )
    assert [(h["source"], h["path"]) for h in pack["hints"]] == [
        ("python_symbol_index_json", "pkg/symbol.py"),
        ("relation_cards_jsonl", "src/alpha.py"),
        ("relation_cards_jsonl", "src/safe.py"),
        ("resolved_evidence", "docs/proof.md"),
    ]
    assert pack["hints"][-1]["range"] == {"start_line": 4, "end_line": 9}
    assert all(h["claim_level"] == "bundle_navigation_hint_not_verified_impact"
               for h in pack["hints"])


def test_more_than_sixteen_separate_hunks_reports_range_display_limit(tmp_path):
    repo, _base, _head = seeded_repo(tmp_path)
    rows = [f"value_{i:03d} = 0\n" for i in range(240)]
    (repo / "spaced.py").write_text("".join(rows), encoding="utf-8")
    git(repo, "add", "spaced.py")
    git(repo, "commit", "-qm", "long initial source")
    base = git(repo, "rev-parse", "HEAD")
    for offset in range(0, 240, 12):
        rows[offset] = f"value_{offset:03d} = 1\n"
    (repo / "spaced.py").write_text("".join(rows), encoding="utf-8")
    git(repo, "add", "spaced.py")
    git(repo, "commit", "-qm", "twenty separated small hunks")
    head = git(repo, "rev-parse", "HEAD")
    pack = build_evidence_pack(
        repo_root=repo, base_revision=base, target_revision=head,
        context_budget_tokens=4000,
    )
    assert pack["changed_file_count"] == 1
    assert pack["changed_files"][0]["path"] == "spaced.py"
    assert len(pack["changed_files"][0]["ranges"]) == 16
    assert pack["limits"]["max_hunks_per_file"] == 16
    assert "hunk_range_display_limit" in {gap["code"] for gap in pack["gaps"]}
    assert pack["status"] == "warn"


def test_request_pinned_manifest_identity_survives_selected_symlink_retarget(tmp_path, monkeypatch):
    from merger.repoground.core import agent_evidence_pack
    from merger.repoground.core.manifest_snapshot import (
        capture_manifest_snapshot, use_manifest_binding,
    )

    repo, base, head = seeded_repo(tmp_path)
    gen_a, gen_b = tmp_path / "generation-a", tmp_path / "generation-b"
    gen_a.mkdir()
    gen_b.mkdir()
    manifest_a, manifest_b = manifest(gen_a, base), manifest(gen_b, head)
    selected = tmp_path / "current.bundle.manifest.json"
    selected.symlink_to(manifest_a)
    binding = capture_manifest_snapshot(selected).binding
    original_git = agent_evidence_pack._read_git_delta

    def switch_generation_during_diff(*args, **kwargs):
        selected.unlink()
        selected.symlink_to(manifest_b)
        return original_git(*args, **kwargs)

    monkeypatch.setattr(
        agent_evidence_pack, "_read_git_delta", switch_generation_during_diff
    )
    with use_manifest_binding(binding):
        result = agent_evidence_pack.build_evidence_pack(
            repo_root=repo, base_revision=base, target_revision=head,
            bundle_manifest=selected,
        )
    assert selected.resolve() == manifest_b.resolve()
    assert result["status"] in {"pass", "warn"}
    assert result["bundle"]["source_commit"] == base
    assert result["bundle"]["manifest_sha256"] == hashlib.sha256(
        manifest_a.read_bytes()
    ).hexdigest()
    assert result["bundle"]["manifest_sha256"] != hashlib.sha256(
        manifest_b.read_bytes()
    ).hexdigest()
    assert result["changed_files"][0]["path"] == "alpha.py"
    assert result["mutation_boundary"]["writes"] == []


def test_direct_cli_pins_initial_manifest_generation_without_outer_binding(
    tmp_path, monkeypatch,
):
    """Direct core/CLI callers must not mix two generations on a pointer race."""
    from merger.repoground.core import agent_evidence_pack

    repo, base, head = seeded_repo(tmp_path)
    gen_a, gen_b = tmp_path / "direct-generation-a", tmp_path / "direct-generation-b"
    gen_a.mkdir()
    gen_b.mkdir()
    manifest_a = manifest(gen_a, base)
    manifest_b = manifest(gen_b, head)
    selected = tmp_path / "direct.bundle.manifest.json"
    selected.symlink_to(manifest_a)
    original_git = agent_evidence_pack._read_git_delta

    def switch_pointer_after_request_begins(*args, **kwargs):
        selected.unlink()
        selected.symlink_to(manifest_b)
        return original_git(*args, **kwargs)

    monkeypatch.setattr(
        agent_evidence_pack, "_read_git_delta",
        switch_pointer_after_request_begins,
    )
    # No external use_manifest_binding context: this matches normal CLI use.
    pack = agent_evidence_pack.build_evidence_pack(
        repo_root=repo,
        base_revision=base,
        target_revision=head,
        bundle_manifest=selected,
    )
    assert selected.resolve() == manifest_b.resolve()
    assert pack["status"] in {"warn", "pass"}
    assert pack["bundle"]["source_commit"] == base
    assert pack["bundle"]["manifest_sha256"] == hashlib.sha256(
        manifest_a.read_bytes()
    ).hexdigest()
    assert pack["bundle"]["manifest_sha256"] != hashlib.sha256(
        manifest_b.read_bytes()
    ).hexdigest()
    assert pack["changed_files"][0]["path"] == "alpha.py"


def test_configured_ignore_submodules_all_does_not_hide_gitlink_changes(tmp_path):
    """A configured ignoreSubmodules=all must not erase committed gitlinks."""
    repo, _base, first = seeded_repo(tmp_path)
    # Index cacheinfo creates a Git *gitlink* (mode 160000) without a network
    # clone or nested repository; only committed tree objects are inspected.
    git(repo, "update-index", "--add", "--cacheinfo",
        "160000," + "1" * 40 + ",vendor")
    git(repo, "commit", "-qm", "record first dependency revision")
    base = git(repo, "rev-parse", "HEAD")
    (repo / "alpha.py").write_text("def old():\n    return 3\n", encoding="utf-8")
    git(repo, "add", "alpha.py")
    git(repo, "update-index", "--add", "--cacheinfo",
        "160000," + "2" * 40 + ",vendor")
    git(repo, "commit", "-qm", "update code and dependency revision")
    target = git(repo, "rev-parse", "HEAD")
    git(repo, "config", "diff.ignoreSubmodules", "all")

    # Both the human-readable delta and the NUL-safe inventory must
    # explicitly override this checkout-local setting.
    report = build_evidence_pack(
        repo_root=repo, base_revision=base, target_revision=target
    )
    assert report["status"] in {"warn", "pass"}
    assert report["changed_file_count"] == 2
    assert {item["path"] for item in report["changed_files"]} == {
        "alpha.py", "vendor",
    }
    assert all(item["claim_level"] == "direct_git_diff"
               for item in report["changed_files"])
    expected = subprocess.run(
        ["git", "-C", str(repo), "diff", "--no-ext-diff", "--no-textconv",
         "--no-renames", "--no-color", "--ignore-submodules=none",
         "--unified=3", base, target, "--"],
        check=True, capture_output=True,
    ).stdout
    assert report["revision"]["diff_sha256"] == hashlib.sha256(expected).hexdigest()
    assert not {gap["code"] for gap in report["gaps"]}.intersection({
        "diff_paths_unresolved", "empty_or_truncated_diff",
    })
    assert git(repo, "status", "--porcelain") == ""
