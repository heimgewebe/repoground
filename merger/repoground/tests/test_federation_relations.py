"""Cross-repository Fleet declarations checked against exact Git object IDs."""
from pathlib import Path
import subprocess

from merger.repoground.core.federation import fleet_relation_delta, fleet_revision_relations


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


def make_repo(root: Path) -> Path:
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "user.name", "RepoGround fixture")
    git(root, "config", "user.email", "fixture@localhost")
    return root


def commit(repo: Path) -> str:
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "fixture revision")
    return git(repo, "rev-parse", "HEAD")


def create_pair(tmp_path):
    metarepo = make_repo(tmp_path / "metarepo")
    service = make_repo(tmp_path / "service")
    (metarepo / "fleet").mkdir()
    (metarepo / "fleet" / "repos.yml").write_text(
        "repos:\n  - name: metarepo\n  - name: service\nstatic:\n  include:\n    - name: related\n      status: related\n",
        encoding="utf-8",
    )
    (metarepo / "fleet" / "repo-metadata.yml").write_text(
        "schema_version: 1\nrepositories:\n  service:\n    domain: local\n    scope: config\n",
        encoding="utf-8",
    )
    (metarepo / "sync").mkdir()
    (metarepo / "sync" / "metarepo-sync.yml").write_text(
        "entries:\n  - id: ci-doc\n    source: docs/ci/README.md\n    targets:\n      - docs/ci/README.md\n    mode: copy\n",
        encoding="utf-8",
    )
    for repo in (metarepo, service):
        (repo / "docs" / "ci").mkdir(parents=True)
        (repo / "docs" / "ci" / "README.md").write_text("same content\n", encoding="utf-8")
    meta_sha = commit(metarepo)
    service_sha = commit(service)
    return metarepo, meta_sha, service, service_sha


def test_two_sha_copy_relation_is_bilateral_and_deterministic(tmp_path):
    metarepo, meta_sha, service, service_sha = create_pair(tmp_path)
    args = (metarepo, meta_sha, {"service": (service, service_sha)})
    result = fleet_revision_relations(*args)
    assert result == fleet_revision_relations(*args)
    assert result["status"] == "ok"
    kinds = [x["relation_type"] for x in result["relations"]]
    assert kinds == ["declared_copy_target", "fleet_core", "fleet_metadata"]
    copy = result["relations"][0]
    assert copy["status"] == "identical_content"
    assert copy["source"]["commit"] == meta_sha
    assert copy["target"]["commit"] == service_sha
    assert copy["source"]["sha256"] == copy["target"]["sha256"]
    assert copy["source"]["path"] == copy["target"]["path"] == "docs/ci/README.md"
    assert copy["source"]["blob_oid"]
    assert copy["target"]["blob_oid"]
    assert copy["declaration"]["path"] == "sync/metarepo-sync.yml"
    assert copy["asserts_runtime_dependency"] is False
    member = result["relations"][1]
    assert member["source"]["line_start"] == 3
    assert member["target"]["source_type"] == "commit_identity_only"


def test_detects_divergence_without_fabricating_successful_sync(tmp_path):
    metarepo, meta_sha, service, old_sha = create_pair(tmp_path)
    (service / "docs" / "ci" / "README.md").write_text("changed target\n", encoding="utf-8")
    new_sha = commit(service)
    result = fleet_revision_relations(metarepo, meta_sha, {"service": (service, new_sha)})
    divergent = next(x for x in result["relations"] if x["relation_type"] == "declared_copy_target")
    assert divergent["status"] == "diverged_at_revisions"
    assert divergent["source"]["sha256"] != divergent["target"]["sha256"]
    old = fleet_revision_relations(metarepo, meta_sha, {"service": (service, old_sha)})
    assert old["relations"][0]["status"] == "identical_content"


def test_related_fleet_false_and_missing_targets_not_promoted(tmp_path):
    metarepo, meta_sha, service, sha = create_pair(tmp_path)
    related = fleet_revision_relations(metarepo, meta_sha, {"related": (service, sha)})
    member = next(x for x in related["relations"] if x["relation_type"] == "fleet_related")
    assert member["asserts_runtime_dependency"] is False
    unknown = fleet_revision_relations(metarepo, meta_sha, {"unknown": (service, sha)})
    assert unknown["relations"] == []
    assert "target_not_listed_in_authoritative_fleet:unknown" in unknown["gaps"]
    metadata_file = metarepo / "fleet" / "repo-metadata.yml"
    metadata_file.write_text(
        "schema_version: 1\nrepositories:\n  service:\n    fleet: false\n", encoding="utf-8"
    )
    new_meta_sha = commit(metarepo)
    collision = fleet_revision_relations(metarepo, new_meta_sha, {"service": (service, sha)})
    assert collision["status"] == "partial"
    assert "metadata_fleet_false:service" in collision["gaps"]
    assert next(x for x in collision["relations"] if x["relation_type"] == "fleet_core")["status"] == "conflicting_declarations"


def test_unsafe_manifest_source_path_is_never_read_from_disk(tmp_path):
    metarepo, meta_sha, service, sha = create_pair(tmp_path)
    (metarepo / "sync" / "metarepo-sync.yml").write_text(
        "entries:\n  - id: unsafe\n    source: ../../secret.txt\n    targets: [docs/ci/README.md]\n",
        encoding="utf-8",
    )
    new_meta_sha = commit(metarepo)
    result = fleet_revision_relations(metarepo, new_meta_sha, {"service": (service, sha)})
    assert not any(r["relation_type"] == "declared_copy_target" for r in result["relations"])
    assert "sync_source_unavailable:unsafe" in result["gaps"]


def test_relation_delta_reports_digest_change_not_unrelated_membership(tmp_path):
    metarepo, meta_sha, service, before_service = create_pair(tmp_path)
    content = service / "docs" / "ci" / "README.md"
    content.write_text("changed target\n", encoding="utf-8")
    after_service = commit(service)
    before = {"service": (service, before_service)}
    after = {"service": (service, after_service)}
    result = fleet_relation_delta(metarepo, meta_sha, meta_sha, before, after)
    assert result["status"] == "ok"
    assert result["base_commit"] == result["head_commit"] == meta_sha
    assert len(result["relation_deltas"]) == 1
    delta = result["relation_deltas"][0]
    assert delta["transition"] == "modified"
    assert delta["relation_type"] == "declared_copy_target"
    assert delta["before"]["status"] == "identical_content"
    assert delta["after"]["status"] == "diverged_at_revisions"
    assert delta["before"]["target"]["commit"] == before_service
    assert delta["after"]["target"]["commit"] == after_service
    assert result["unchanged_relations_count"] == 2
    assert result == fleet_relation_delta(metarepo, meta_sha, meta_sha, before, after)

    # Editing the normative manifest for an *unrelated* repository should not
    # manufacture a material change to the observed service relationship.
    fleet_file = metarepo / "fleet" / "repos.yml"
    fleet_file.write_text(fleet_file.read_text().replace("static:\n", "  - name: unrelated\nstatic:\n"), encoding="utf-8")
    newer_meta = commit(metarepo)
    unrelated = fleet_relation_delta(metarepo, meta_sha, newer_meta, before, before)
    assert unrelated["status"] == "ok"
    assert unrelated["relation_deltas"] == []
    assert unrelated["unchanged_relations_count"] == 3


def test_relation_removed_only_after_valid_authoritative_membership_read(tmp_path):
    metarepo, old_meta, service, target_sha = create_pair(tmp_path)
    fleet_file = metarepo / "fleet" / "repos.yml"
    fleet_file.write_text("repos:\n  - name: metarepo\n", encoding="utf-8")
    new_meta = commit(metarepo)
    before = {"service": (service, target_sha)}
    removed = fleet_relation_delta(metarepo, old_meta, new_meta, before, before)
    assert removed["status"] == "ok"
    assert {x["transition"] for x in removed["relation_deltas"]} == {"removed"}
    assert {x["relation_type"] for x in removed["relation_deltas"]} == {
        "fleet_core", "fleet_metadata", "declared_copy_target"
    }
    assert all(x["after"] is None for x in removed["relation_deltas"])
    try:
        fleet_relation_delta(metarepo, old_meta, new_meta, before, {})
    except ValueError as exc:
        assert "identical named target" in str(exc)
    else:
        raise AssertionError("mismatched target IDs accepted")


def test_malformed_yaml_is_rejected_and_unavailable_fleet_remains_explicit(tmp_path):
    metarepo, sha, service, target = create_pair(tmp_path)
    fleet_file = metarepo / "fleet" / "repos.yml"
    fleet_file.write_text("!!python/object/apply:os.system ['id']\n", encoding="utf-8")
    malicious_sha = commit(metarepo)
    try:
        fleet_revision_relations(metarepo, malicious_sha, {"service": (service, target)})
    except ValueError as exc:
        assert "invalid YAML" in str(exc)
    else:
        raise AssertionError("unsafe YAML tag was accepted")
    fleet_file.unlink()
    missing_sha = commit(metarepo)
    unavailable = fleet_revision_relations(metarepo, missing_sha, {"service": (service, target)})
    assert unavailable["status"] == "unavailable"
    assert unavailable["source_commit"] == missing_sha
    assert unavailable["observation_time"] is None
    assert unavailable["authoritative_membership_source"] == "fleet/repos.yml"
    unknown = fleet_relation_delta(metarepo, sha, missing_sha,
                                   {"service": (service, target)}, {"service": (service, target)})
    assert unknown["status"] == "partial"
    assert unknown["relation_deltas"] == []
    assert "relation_delta_requires_two_complete_source_views" in unknown["gaps"]


def test_unreadable_existing_target_blob_is_not_a_removed_relation(tmp_path):
    metarepo, source_sha, service, old_target_sha = create_pair(tmp_path)
    target_file = service / "docs" / "ci" / "README.md"
    # The target still has a Git tree blob OID, but exceeds the reader cap.
    target_file.write_text("x" * 250_001, encoding="utf-8")
    new_target_sha = commit(service)

    view = fleet_revision_relations(metarepo, source_sha, {
        "service": (service, new_target_sha),
    })
    assert view["status"] == "partial"
    assert "sync_target_unavailable:ci-doc:docs/ci/README.md" in view["gaps"]
    assert not any(row["relation_type"] == "declared_copy_target" for row in view["relations"])
    assert any(row["relation_type"] == "fleet_core" for row in view["relations"])

    delta = fleet_relation_delta(
        metarepo, source_sha, source_sha,
        {"service": (service, old_target_sha)},
        {"service": (service, new_target_sha)},
    )
    assert delta["status"] == "partial"
    assert delta["relation_deltas"] == []
    assert "after:sync_target_unavailable:ci-doc:docs/ci/README.md" in delta["gaps"]
    assert "relation_delta_requires_two_complete_source_views" in delta["gaps"]


def test_sync_targets_capped_cannot_fabricate_relation_removal(tmp_path):
    metarepo, old_sha, service, target_sha = create_pair(tmp_path)
    manifest = metarepo / "sync" / "metarepo-sync.yml"
    entries = [f"      - docs/ci/unused-{i}.md\n" for i in range(8)]
    entries.append("      - docs/ci/README.md\n")
    manifest.write_text(
        "entries:\n  - id: ci-doc\n    source: docs/ci/README.md\n"
        "    targets:\n" + "".join(entries),
        encoding="utf-8",
    )
    after_sha = commit(metarepo)
    result = fleet_relation_delta(metarepo, old_sha, after_sha,
                                  {"service": (service, target_sha)},
                                  {"service": (service, target_sha)})
    assert result["status"] == "partial"
    assert result["relation_deltas"] == []
    assert "after:sync_targets_capped:ci-doc" in result["gaps"]


def test_unreadable_existing_optional_metadata_is_explicit_partial(tmp_path):
    metarepo, old_meta_sha, service, target_sha = create_pair(tmp_path)
    metadata = metarepo / "fleet" / "repo-metadata.yml"
    metadata.write_text("schema_version: 1\n" + "#" + "x" * 250_000, encoding="utf-8")
    unreadable_sha = commit(metarepo)
    observation = fleet_revision_relations(metarepo, unreadable_sha, {
        "service": (service, target_sha),
    })
    assert observation["status"] == "partial"
    assert "fleet_metadata_unavailable" in observation["gaps"]
    comparison = fleet_relation_delta(metarepo, old_meta_sha, unreadable_sha,
                                      {"service": (service, target_sha)},
                                      {"service": (service, target_sha)})
    assert comparison["status"] == "partial"
    assert comparison["relation_deltas"] == []
    assert "after:fleet_metadata_unavailable" in comparison["gaps"]


def test_reindented_metadata_declaration_preserves_same_relation(tmp_path):
    metarepo, original_sha, service, target_sha = create_pair(tmp_path)
    metadata = metarepo / "fleet" / "repo-metadata.yml"
    metadata.write_text(
        'schema_version: 1\nrepositories:\n    "service":\n'
        '      domain: local\n      scope: config\n',
        encoding="utf-8",
    )
    new_sha = commit(metarepo)
    before = fleet_revision_relations(metarepo, original_sha, {
        "service": (service, target_sha),
    })
    after = fleet_revision_relations(metarepo, new_sha, {
        "service": (service, target_sha),
    })
    assert before["status"] == after["status"] == "ok"
    assert any(row["relation_type"] == "fleet_metadata" for row in after["relations"])
    compared = fleet_relation_delta(metarepo, original_sha, new_sha,
                                    {"service": (service, target_sha)},
                                    {"service": (service, target_sha)})
    assert compared["status"] == "ok"
    assert compared["relation_deltas"] == []
    assert compared["unchanged_relations_count"] == 3


def test_valid_flow_yaml_without_unique_metadata_line_is_partial_not_removed(tmp_path):
    metarepo, original_sha, service, target_sha = create_pair(tmp_path)
    metadata = metarepo / "fleet" / "repo-metadata.yml"
    metadata.write_text(
        "schema_version: 1\nrepositories: {service: {domain: local, scope: config}}\n",
        encoding="utf-8",
    )
    changed_sha = commit(metarepo)
    current = fleet_revision_relations(metarepo, changed_sha, {
        "service": (service, target_sha),
    })
    assert current["status"] == "partial"
    assert "fleet_metadata_declaration_unresolved:service" in current["gaps"]
    compared = fleet_relation_delta(metarepo, original_sha, changed_sha,
                                    {"service": (service, target_sha)},
                                    {"service": (service, target_sha)})
    assert compared["status"] == "partial"
    assert compared["relation_deltas"] == []
    assert "after:fleet_metadata_declaration_unresolved:service" in compared["gaps"]


def test_null_and_empty_non_mapping_metadata_preserve_fleet_evidence(tmp_path):
    metarepo, _, service, service_sha = create_pair(tmp_path)
    metadata = metarepo / "fleet" / "repo-metadata.yml"
    for annotation in ("", " []", " false"):
        metadata.write_text(
            "schema_version: 1\nrepositories:\n  service:" + annotation + "\n",
            encoding="utf-8",
        )
        meta_sha = commit(metarepo)
        targets = {"service": (service, service_sha)}
        result = fleet_revision_relations(metarepo, meta_sha, targets)
        assert "invalid_metadata:service" in result["gaps"]
        assert any(
            relation["relation_type"] == "fleet_core"
            for relation in result["relations"]
        )
        delta = fleet_relation_delta(metarepo, meta_sha, meta_sha, targets, targets)
        assert delta["status"] == "partial"
