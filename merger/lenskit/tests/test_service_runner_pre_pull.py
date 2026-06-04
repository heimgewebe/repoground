"""Runner integration for the pre-pull preflight.

``pre_pull_repo`` is patched out (its own git semantics are covered by
test_repo_sync.py); these tests verify that the runner *orchestrates* it
correctly: ordering before scan, hard-fail vs warn-and-continue, and the
self-repo restart warning (without any auto-restart).
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from unittest.mock import MagicMock, patch

from merger.lenskit.service.runner import JobRunner, ARTIFACT_PATH_FIELDS
from merger.lenskit.service.jobstore import JobStore
from merger.lenskit.service.models import JobRequest, Job
from merger.lenskit.service.repo_sync import PrePullResult, PrePullStatus


def _fake_artifacts() -> MagicMock:
    """A write_reports_v2 return value that lets the runner finish cleanly."""
    art = MagicMock()
    art.get_all_paths.return_value = []
    art.get_primary_path.return_value = None
    art.index_json = None
    art.canonical_md = None
    art.md_parts = []
    art.other = []
    for attr in ARTIFACT_PATH_FIELDS:
        setattr(art, attr, None)
    return art


@pytest.fixture
def mock_job_store():
    store = MagicMock(spec=JobStore)
    store.get_job = MagicMock()
    store.update_job = MagicMock()
    store.append_log_line = MagicMock()
    return store


@pytest.fixture
def temp_hub():
    with tempfile.TemporaryDirectory() as tmp:
        hub = Path(tmp)
        (hub / "repoA").mkdir()
        (hub / "repoB").mkdir()
        yield hub


def _make_job(temp_hub: Path, repos, **req_kwargs) -> Job:
    req = JobRequest(hub=str(temp_hub), repos=repos, mode="gesamt", **req_kwargs)
    job = Job.create(req)
    job.hub_resolved = str(temp_hub)
    return job


def _ok(name: str) -> PrePullResult:
    return PrePullResult(repo=name, path=name, status=PrePullStatus.UP_TO_DATE, message="ok")


def _patches():
    """Common runner patches; scan/write are stubbed, validation is a no-op."""
    p_scan = patch("merger.lenskit.service.runner.scan_repo")
    p_write = patch("merger.lenskit.service.runner.write_reports_v2")
    p_validate = patch("merger.lenskit.service.runner.validate_source_dir")
    return p_scan, p_write, p_validate


def test_pre_pull_true_calls_pre_pull_before_scan(mock_job_store, temp_hub):
    runner = JobRunner(mock_job_store)
    job = _make_job(temp_hub, ["repoA", "repoB"], pre_pull=True)
    mock_job_store.get_job.return_value = job

    p_scan, p_write, p_validate = _patches()
    with p_scan as mock_scan, p_write as mock_write, p_validate, \
         patch("merger.lenskit.service.runner.pre_pull_repo") as mock_pre, \
         patch("merger.lenskit.service.runner.is_self_repo", return_value=False):

        mock_write.return_value = _fake_artifacts()

        # Each pre_pull_repo call must happen before any scan_repo call.
        def _pre(src):
            assert mock_scan.call_count == 0, "pre_pull must run before scan"
            return _ok(src.name)

        mock_pre.side_effect = _pre

        runner._run_job(job.id)

        assert mock_pre.call_count == 2
        assert mock_scan.call_count == 2
        assert job.status == "succeeded"


def test_pre_pull_false_skips_pre_pull(mock_job_store, temp_hub):
    runner = JobRunner(mock_job_store)
    job = _make_job(temp_hub, ["repoA"], pre_pull=False)
    mock_job_store.get_job.return_value = job

    p_scan, p_write, p_validate = _patches()
    with p_scan as mock_scan, p_write as mock_write, p_validate, \
         patch("merger.lenskit.service.runner.pre_pull_repo") as mock_pre:

        mock_write.return_value = _fake_artifacts()

        runner._run_job(job.id)

        mock_pre.assert_not_called()
        assert mock_scan.call_count == 1
        assert job.status == "succeeded"


def test_pre_pull_hard_fail_prevents_scan(mock_job_store, temp_hub):
    runner = JobRunner(mock_job_store)
    job = _make_job(temp_hub, ["repoA"], pre_pull=True)
    mock_job_store.get_job.return_value = job

    p_scan, p_write, p_validate = _patches()
    with p_scan as mock_scan, p_write, p_validate, \
         patch("merger.lenskit.service.runner.pre_pull_repo") as mock_pre, \
         patch("merger.lenskit.service.runner.is_self_repo", return_value=False):

        mock_pre.return_value = PrePullResult(
            repo="repoA", path="repoA", status=PrePullStatus.DIRTY,
            message="has uncommitted tracked changes",
        )

        runner._run_job(job.id)

        mock_scan.assert_not_called()
        assert job.status == "failed"
        assert "Pre-pull failed" in (job.error or "")
        assert "dirty" in (job.error or "")


def test_pre_pull_diverged_hard_fail(mock_job_store, temp_hub):
    runner = JobRunner(mock_job_store)
    job = _make_job(temp_hub, ["repoA"], pre_pull=True)
    mock_job_store.get_job.return_value = job

    p_scan, p_write, p_validate = _patches()
    with p_scan as mock_scan, p_write, p_validate, \
         patch("merger.lenskit.service.runner.pre_pull_repo") as mock_pre, \
         patch("merger.lenskit.service.runner.is_self_repo", return_value=False):

        mock_pre.return_value = PrePullResult(
            repo="repoA", path="repoA", status=PrePullStatus.DIVERGED, message="diverged",
        )

        runner._run_job(job.id)

        mock_scan.assert_not_called()
        assert job.status == "failed"


def test_pre_pull_warn_status_continues_scan(mock_job_store, temp_hub):
    runner = JobRunner(mock_job_store)
    job = _make_job(temp_hub, ["repoA"], pre_pull=True)
    mock_job_store.get_job.return_value = job

    p_scan, p_write, p_validate = _patches()
    with p_scan as mock_scan, p_write as mock_write, p_validate, \
         patch("merger.lenskit.service.runner.pre_pull_repo") as mock_pre, \
         patch("merger.lenskit.service.runner.is_self_repo", return_value=False):

        mock_write.return_value = _fake_artifacts()
        mock_pre.return_value = PrePullResult(
            repo="repoA", path="repoA", status=PrePullStatus.SKIPPED_NO_UPSTREAM,
            message="no upstream tracking branch",
        )

        runner._run_job(job.id)

        # Warn-and-continue: scan still runs, job succeeds, warning recorded.
        assert mock_scan.call_count == 1
        assert job.status == "succeeded"
        assert any("skipped_no_upstream" in w for w in job.warnings)


def test_pre_pull_self_repo_emits_restart_warning_no_autorestart(mock_job_store, temp_hub):
    runner = JobRunner(mock_job_store)
    job = _make_job(temp_hub, ["repoA"], pre_pull=True)
    mock_job_store.get_job.return_value = job

    p_scan, p_write, p_validate = _patches()
    with p_scan as mock_scan, p_write as mock_write, p_validate, \
         patch("merger.lenskit.service.runner.pre_pull_repo") as mock_pre, \
         patch("merger.lenskit.service.runner.is_self_repo", return_value=True), \
         patch("subprocess.run") as mock_subprocess, \
         patch("os.system") as mock_os_system:

        mock_write.return_value = _fake_artifacts()
        mock_pre.return_value = PrePullResult(
            repo="repoA", path="repoA", status=PrePullStatus.FAST_FORWARDED,
            changed=True, message="fast-forwarded",
        )

        runner._run_job(job.id)

        # Job continues (no auto-restart that would kill it).
        assert job.status == "succeeded"
        assert mock_scan.call_count == 1
        # A visible restart warning lands in job.warnings.
        restart_warnings = [w for w in job.warnings if "Restart" in w and "rlens.service" in w]
        assert restart_warnings, f"expected restart warning, got {job.warnings}"
        assert "does not reload modules automatically" in restart_warnings[0]
        # No service automation was invoked.
        mock_os_system.assert_not_called()
        for call in mock_subprocess.call_args_list:
            args = " ".join(str(a) for a in call.args) + " ".join(str(v) for v in call.kwargs.values())
            assert "systemctl" not in args
