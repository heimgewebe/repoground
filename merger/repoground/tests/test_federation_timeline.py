"""Public CLI keeps existing query commands and adds strict read-only projections."""
import json

from merger.repoground.cli.main import main
from merger.repoground.tests.test_federation_relations import commit, create_pair
from merger.repoground.tests.test_history_lens_temporal import create_repo


def test_revision_delta_path_and_events_cli(tmp_path, capsys):
    repo, shas = create_repo(tmp_path)
    common = ["--repo-root", str(repo), "--repo-id", "fixture"]
    assert main(["federation", "revision", *common, "--commit", shas[0]]) == 0
    assert json.loads(capsys.readouterr().out)["source_commit"] == shas[0]
    assert main(["federation", "delta", *common, "--base", shas[0], "--head", shas[2]]) == 0
    assert json.loads(capsys.readouterr().out)["changed_files_observed"] == 2
    assert main(["federation", "path-history", *common, "--commit", shas[2], "--path", "module.py"]) == 0
    assert len(json.loads(capsys.readouterr().out)["history"]) == 3
    records = [{"repo_id": "fixture", "commit": shas[2], "event_kind": "ci", "evidence_ref": "ci:fixture/1"}]
    assert main(["federation", "history-events", *common, "--commit", shas[2],
                 "--events-json", json.dumps(records)]) == 0
    assert len(json.loads(capsys.readouterr().out)["events"]) == 1
    assert main(["federation", "revision", *common, "--commit", "HEAD"]) == 1
    assert "full lowercase" in capsys.readouterr().err


def test_cross_repo_relation_cli_exact_two_commits(tmp_path, capsys):
    metarepo, meta_sha, service, service_sha = create_pair(tmp_path)
    status = main(["federation", "relations", "--metarepo-root", str(metarepo),
                   "--metarepo-commit", meta_sha,
                   "--target", f"service={service}@{service_sha}"])
    assert status == 0
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["source_commit"] == meta_sha
    assert parsed["relations"][0]["target"]["commit"] == service_sha
    assert parsed["relations"][0]["status"] == "identical_content"
    assert main(["federation", "relations", "--metarepo-root", str(metarepo),
                 "--metarepo-commit", meta_sha, "--target", "garbled"]) == 1
    assert "REPO_ID=" in capsys.readouterr().err


def test_relation_delta_cli_two_pinned_repositories(tmp_path, capsys):
    metarepo, meta_sha, target_repo, target_base = create_pair(tmp_path)
    (target_repo / "docs" / "ci" / "README.md").write_text(
        "later content\n", encoding="utf-8"
    )
    target_head = commit(target_repo)
    args = [
        "federation", "relation-delta",
        "--metarepo-root", str(metarepo),
        "--base-metarepo-commit", meta_sha,
        "--head-metarepo-commit", meta_sha,
        "--target-before", f"service={target_repo}@{target_base}",
        "--target-after", f"service={target_repo}@{target_head}",
    ]
    assert main(args) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["kind"] == "repoground.federation-evidence"
    assert output["status"] == "ok"
    assert output["relation_deltas"][0]["transition"] == "modified"
    assert output["relation_deltas"][0]["target_repo"] == "service"
    assert output["relation_deltas"][0]["after"]["target"]["commit"] == target_head
