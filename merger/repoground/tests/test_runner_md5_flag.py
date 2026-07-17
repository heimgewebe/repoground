
import pytest
from unittest.mock import MagicMock, patch
from merger.repoground.service.runner import JobRunner
from merger.repoground.service.jobstore import JobStore
from merger.repoground.service.models import JobRequest, Job
from pathlib import Path
import tempfile

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

def test_runner_passes_calculate_md5_false_for_plan_only(mock_job_store, temp_hub):
    runner = JobRunner(mock_job_store)

    req = JobRequest(
        hub=str(temp_hub),
        repos=["repoA"],
        mode="gesamt",
        plan_only=True
    )
    job = Job.create(req)
    job.hub_resolved = str(temp_hub)

    mock_job_store.get_job.return_value = job

    with patch("merger.repoground.service.runner.scan_repo") as mock_scan, \
         patch("merger.repoground.service.runner.write_reports_v2") as mock_write, \
         patch("merger.repoground.service.runner.validate_source_dir"):

        mock_artifacts = MagicMock()
        mock_artifacts.get_all_paths.return_value = {}
        mock_write.return_value = mock_artifacts

        runner._run_job(job.id)

        assert mock_scan.call_count == 1
        args, kwargs = mock_scan.call_args

        # Verify calculate_md5 is False
        assert kwargs.get("calculate_md5") is False

def test_runner_passes_calculate_md5_true_by_default(mock_job_store, temp_hub):
    runner = JobRunner(mock_job_store)

    req = JobRequest(
        hub=str(temp_hub),
        repos=["repoA"],
        mode="gesamt",
        plan_only=False
    )
    job = Job.create(req)
    job.hub_resolved = str(temp_hub)

    mock_job_store.get_job.return_value = job

    with patch("merger.repoground.service.runner.scan_repo") as mock_scan, \
         patch("merger.repoground.service.runner.write_reports_v2") as mock_write, \
         patch("merger.repoground.service.runner.validate_source_dir"):

        mock_artifacts = MagicMock()
        mock_artifacts.get_all_paths.return_value = {}
        mock_write.return_value = mock_artifacts

        runner._run_job(job.id)

        assert mock_scan.call_count == 1
        args, kwargs = mock_scan.call_args

        # Verify calculate_md5 is True
        assert kwargs.get("calculate_md5") is True

def test_runner_consistent_flag_multiple_repos(mock_job_store, temp_hub):
    """
    Ensure the flag is consistently applied across multiple repositories in a single job.
    """
    runner = JobRunner(mock_job_store)

    req = JobRequest(
        hub=str(temp_hub),
        repos=["repoA", "repoB"],
        mode="gesamt",
        plan_only=True
    )
    job = Job.create(req)
    job.hub_resolved = str(temp_hub)

    mock_job_store.get_job.return_value = job

    with patch("merger.repoground.service.runner.scan_repo") as mock_scan, \
         patch("merger.repoground.service.runner.write_reports_v2") as mock_write, \
         patch("merger.repoground.service.runner.validate_source_dir"):

        mock_artifacts = MagicMock()
        mock_artifacts.get_all_paths.return_value = {}
        mock_write.return_value = mock_artifacts

        runner._run_job(job.id)

        assert mock_scan.call_count == 2

        # Verify both calls have calculate_md5=False
        for call in mock_scan.call_args_list:
            args, kwargs = call
            assert kwargs.get("calculate_md5") is False
