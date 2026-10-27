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
