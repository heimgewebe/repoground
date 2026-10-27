"""Cross-repository Fleet declarations checked against exact Git object IDs."""
from pathlib import Path
import subprocess

from merger.repoground.core.federation import fleet_revision_relations


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