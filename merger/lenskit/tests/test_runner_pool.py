import pytest
from unittest.mock import MagicMock, patch
from merger.lenskit.service.runner import JobRunner
from merger.lenskit.service.jobstore import JobStore
from merger.lenskit.service.models import JobRequest, Job
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


def test_runner_combined_include_paths(mock_job_store, temp_hub):
    """
    Test that JobRunner correctly passes include_paths from include_paths_by_repo
    to scan_repo for each repository.
    """
    runner = JobRunner(mock_job_store)

    # Create Job
    req = JobRequest(
        hub=str(temp_hub),
        repos=["repoA", "repoB"],
        include_paths_by_repo={
            "repoA": ["fileA.txt"],
            "repoB": ["fileB.txt"]
        },
        mode="gesamt"
    )
    job = Job.create(req)
    job.hub_resolved = str(temp_hub)

    mock_job_store.get_job.return_value = job

    with patch("merger.lenskit.service.runner.scan_repo") as mock_scan, \
         patch("merger.lenskit.service.runner.write_reports_v2") as mock_write, \
         patch("merger.lenskit.service.runner.validate_source_dir"):

        # Mock write_reports_v2 return value
        mock_artifacts = MagicMock()
        mock_artifacts.get_all_paths.return_value = {}
        mock_write.return_value = mock_artifacts

        runner._run_job(job.id)

        # Verify scan_repo calls
        assert mock_scan.call_count == 2

        # Calls are not necessarily ordered by repo name unless sources are sorted.
        # _find_repos sorts by name. But here we passed explicit repos list.
        # JobRunner iterates over req.repos if provided, OR sorted iterdir.
        # Here req.repos is ["repoA", "repoB"].

        # Check call for repoA
        call_repoA = None
        call_repoB = None

        for call in mock_scan.call_args_list:
            args, kwargs = call
            src_path = args[0]
            if src_path.name == "repoA":
                call_repoA = kwargs
            elif src_path.name == "repoB":
                call_repoB = kwargs

        assert call_repoA is not None
        assert call_repoA["include_paths"] == ["fileA.txt"]

        assert call_repoB is not None
        assert call_repoB["include_paths"] == ["fileB.txt"]

def test_runner_key_mismatch_warning(mock_job_store, temp_hub):
    """
    Test that missing key in include_paths_by_repo generates a warning in job.warnings.
    """
    runner = JobRunner(mock_job_store)

    # Create Job
    req = JobRequest(
        hub=str(temp_hub),
        repos=["repoA", "repoB"],
        include_paths_by_repo={
            "repoA": ["fileA.txt"]
            # repoB missing
        },
        mode="gesamt",
        strict_include_paths_by_repo=False # Soft mode
    )
    job = Job.create(req)
    job.hub_resolved = str(temp_hub)

    mock_job_store.get_job.return_value = job

    with patch("merger.lenskit.service.runner.scan_repo") as mock_scan, \
         patch("merger.lenskit.service.runner.write_reports_v2") as mock_write, \
         patch("merger.lenskit.service.runner.validate_source_dir"):

        mock_artifacts = MagicMock()
        mock_artifacts.get_all_paths.return_value = {}
        mock_write.return_value = mock_artifacts

        runner._run_job(job.id)

        # Verify scan_repo calls
        assert mock_scan.call_count == 2

        # Verify Warnings
        # We expect a warning for repoB
        assert len(job.warnings) > 0
        warning_found = False
        for w in job.warnings:
            if "repoB" in w and "include_paths_by_repo has no entry" in w:
                warning_found = True
                break

        assert warning_found, f"Expected warning for repoB not found. Warnings: {job.warnings}"

def test_runner_empty_list_warning(mock_job_store, temp_hub):
    """
    Test that empty list in include_paths generates a warning.
    """
    runner = JobRunner(mock_job_store)

    req = JobRequest(
        hub=str(temp_hub),
        repos=["repoA"],
        include_paths_by_repo={
            "repoA": [] # Empty list -> Scan Nothing
        },
        mode="gesamt"
    )
    job = Job.create(req)
    job.hub_resolved = str(temp_hub)
    mock_job_store.get_job.return_value = job

    with patch("merger.lenskit.service.runner.scan_repo"), \
         patch("merger.lenskit.service.runner.write_reports_v2") as mock_write, \
         patch("merger.lenskit.service.runner.validate_source_dir"):

        mock_artifacts = MagicMock()
        mock_artifacts.get_all_paths.return_value = {}
        mock_write.return_value = mock_artifacts

        runner._run_job(job.id)

        assert len(job.warnings) > 0
        assert any("scan NOTHING" in w for w in job.warnings)
