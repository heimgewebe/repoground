from merger.lenskit.core.snapshot_provenance import repository_snapshot_provenance


def test_non_git_repo_has_explicit_unknown_freshness(tmp_path):
    result = repository_snapshot_provenance(tmp_path)
    assert result["provenance_status"] == "not_git_checkout"
    assert result["freshness_basis"] == "unknown"
    assert result["git_commit"] is None


def test_redaction_nulls_repo_root(tmp_path):
    result = repository_snapshot_provenance(tmp_path, redact=True)
    assert result["repo_root"] is None
