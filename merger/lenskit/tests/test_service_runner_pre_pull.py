"""Runner integration for the two-phase pre-pull preflight.

The git semantics live in test_repo_sync.py; here ``plan_pre_pull_repos`` and
``apply_pre_pull_plans`` are patched so we can assert the runner's *orchestration*:
effective-pre-pull (plan_only gate), plan-before-apply-before-scan ordering,
plan hard-fail aborting before any apply, warn-and-continue, and the self-repo
restart warning firing only on an actual fast-forward (never auto-restart).
"""
from __future__ import annotations

import tempfile
import json
from pathlib import Path

import pytest
from unittest.mock import MagicMock, patch

from merger.lenskit.service.runner import JobRunner, ARTIFACT_PATH_FIELDS
from merger.lenskit.service.jobstore import JobStore
from merger.lenskit.service.models import JobRequest, Job
from merger.lenskit.service.repo_sync import PrePullPlan, PrePullResult, PrePullStatus


def _fake_artifacts() -> MagicMock:
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


def _plan(name: str, status: str, **kw) -> PrePullPlan:
    if "message" not in kw:
        kw["message"] = status
    return PrePullPlan(repo=name, path=str(Path("/hub") / name), status=status, **kw)


def _result(name: str, status: str, **kw) -> PrePullResult:
    if "message" not in kw:
        kw["message"] = status
    return PrePullResult(repo=name, path=str(Path("/hub") / name), status=status, **kw)


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


def _patched(*, plan=None, apply=None, self_repo=False):
    """Context managers for scan/write/validate + plan/apply/is_self_repo."""
    cms = {
        "scan": patch("merger.lenskit.service.runner.scan_repo"),
        "write": patch("merger.lenskit.service.runner.write_reports_v2"),
        "validate": patch("merger.lenskit.service.runner.validate_source_dir"),
        "plan": patch("merger.lenskit.service.runner.plan_pre_pull_repos"),
        "apply": patch("merger.lenskit.service.runner.apply_pre_pull_plans"),
        "self": patch("merger.lenskit.service.runner.is_self_repo", return_value=self_repo),
    }
    return cms


def test_plan_only_skips_pre_pull_even_if_requested(mock_job_store, temp_hub):
    runner = JobRunner(mock_job_store)
    job = _make_job(temp_hub, ["repoA"], pre_pull=True, plan_only=True)
    mock_job_store.get_job.return_value = job
    cms = _patched()
    with cms["scan"] as scan, cms["write"] as write, cms["validate"], \
         cms["plan"] as plan, cms["apply"] as apply, cms["self"]:
        write.return_value = _fake_artifacts()
        runner._run_job(job.id)
        plan.assert_not_called()
        apply.assert_not_called()
        assert scan.call_count == 1
        assert job.status == "succeeded"


def test_pre_pull_false_skips_pre_pull(mock_job_store, temp_hub):
    runner = JobRunner(mock_job_store)
    job = _make_job(temp_hub, ["repoA"], pre_pull=False)
    mock_job_store.get_job.return_value = job
    cms = _patched()
    with cms["scan"] as scan, cms["write"] as write, cms["validate"], \
         cms["plan"] as plan, cms["apply"] as apply, cms["self"]:
        write.return_value = _fake_artifacts()
        runner._run_job(job.id)
        plan.assert_not_called()
        apply.assert_not_called()
        assert scan.call_count == 1
        assert job.status == "succeeded"


def test_pre_pull_plan_runs_before_scan(mock_job_store, temp_hub):
    runner = JobRunner(mock_job_store)
    job = _make_job(temp_hub, ["repoA", "repoB"], pre_pull=True)
    mock_job_store.get_job.return_value = job
    cms = _patched()
    with cms["scan"] as scan, cms["write"] as write, cms["validate"], \
         cms["plan"] as plan, cms["apply"] as apply, cms["self"]:
        write.return_value = _fake_artifacts()

        def _plan_fn(sources, *a, **k):
            assert scan.call_count == 0, "plan must run before scan"
            return [_plan("repoA", PrePullStatus.UP_TO_DATE), _plan("repoB", PrePullStatus.UP_TO_DATE)]

        plan.side_effect = _plan_fn
        apply.return_value = [_result("repoA", PrePullStatus.UP_TO_DATE), _result("repoB", PrePullStatus.UP_TO_DATE)]

        runner._run_job(job.id)
        assert plan.call_count == 1
        assert scan.call_count == 2
        assert job.status == "succeeded"


def test_pre_pull_apply_runs_before_scan(mock_job_store, temp_hub):
    runner = JobRunner(mock_job_store)
    job = _make_job(temp_hub, ["repoA"], pre_pull=True)
    mock_job_store.get_job.return_value = job
    cms = _patched()
    with cms["scan"] as scan, cms["write"] as write, cms["validate"], \
         cms["plan"] as plan, cms["apply"] as apply, cms["self"]:
        write.return_value = _fake_artifacts()
        plan.return_value = [_plan("repoA", PrePullStatus.PLANNED_FAST_FORWARD, needs_apply=True)]

        def _apply_fn(plans, *a, **k):
            assert scan.call_count == 0, "apply must run before scan"
            return [_result("repoA", PrePullStatus.FAST_FORWARDED, changed=True)]

        apply.side_effect = _apply_fn
        runner._run_job(job.id)
        assert apply.call_count == 1
        assert scan.call_count == 1
        assert job.status == "succeeded"


def test_pre_pull_plan_hard_fail_prevents_apply_and_scan(mock_job_store, temp_hub):
    runner = JobRunner(mock_job_store)
    job = _make_job(temp_hub, ["repoA", "repoB"], pre_pull=True)
    mock_job_store.get_job.return_value = job
    cms = _patched()
    with cms["scan"] as scan, cms["write"], cms["validate"], \
         cms["plan"] as plan, cms["apply"] as apply, cms["self"]:
        # repoA could fast-forward, but repoB is dirty → abort before ANY apply.
        plan.return_value = [
            _plan("repoA", PrePullStatus.PLANNED_FAST_FORWARD, needs_apply=True),
            _plan("repoB", PrePullStatus.DIRTY),
        ]
        runner._run_job(job.id)
        apply.assert_not_called()
        scan.assert_not_called()
        assert job.status == "failed"
        assert "Pre-pull plan failed" in (job.error or "")
        assert "no repo HEADs or working trees were fast-forwarded" in (job.error or "")


def test_pre_pull_untracked_overwrite_prevents_apply_and_scan(mock_job_store, temp_hub):
    """An untracked-overwrite plan hard-fail aborts before any apply or scan."""
    runner = JobRunner(mock_job_store)
    job = _make_job(temp_hub, ["repoA", "repoB"], pre_pull=True)
    mock_job_store.get_job.return_value = job
    cms = _patched()
    with cms["scan"] as scan, cms["write"], cms["validate"], \
         cms["plan"] as plan, cms["apply"] as apply, cms["self"]:
        plan.return_value = [
            _plan("repoA", PrePullStatus.PLANNED_FAST_FORWARD, needs_apply=True),
            _plan("repoB", PrePullStatus.UNTRACKED_WOULD_BE_OVERWRITTEN),
        ]
        runner._run_job(job.id)
        apply.assert_not_called()
        scan.assert_not_called()
        assert job.status == "failed"
        assert "Pre-pull plan failed" in (job.error or "")


def test_pre_pull_warn_status_allows_apply_for_other_repo(mock_job_store, temp_hub):
    runner = JobRunner(mock_job_store)
    job = _make_job(temp_hub, ["repoA", "repoB"], pre_pull=True)
    mock_job_store.get_job.return_value = job
    cms = _patched()
    with cms["scan"] as scan, cms["write"] as write, cms["validate"], \
         cms["plan"] as plan, cms["apply"] as apply, cms["self"]:
        write.return_value = _fake_artifacts()
        plan.return_value = [
            _plan("repoA", PrePullStatus.SKIPPED_NO_UPSTREAM),
            _plan("repoB", PrePullStatus.PLANNED_FAST_FORWARD, needs_apply=True),
        ]
        apply.return_value = [
            _result("repoA", PrePullStatus.SKIPPED_NO_UPSTREAM),
            _result("repoB", PrePullStatus.FAST_FORWARDED, changed=True),
        ]
        runner._run_job(job.id)
        apply.assert_called_once()
        assert scan.call_count == 2
        assert job.status == "succeeded"
        assert any("skipped_no_upstream" in w for w in job.warnings)


def test_self_repo_fast_forwarded_emits_restart_warning(mock_job_store, temp_hub):
    runner = JobRunner(mock_job_store)
    job = _make_job(temp_hub, ["repoA"], pre_pull=True)
    mock_job_store.get_job.return_value = job
    cms = _patched(self_repo=True)
    with cms["scan"] as scan, cms["write"] as write, cms["validate"], \
         cms["plan"] as plan, cms["apply"] as apply, cms["self"], \
         patch("subprocess.run") as subproc, patch("os.system") as ossystem:
        write.return_value = _fake_artifacts()
        plan.return_value = [_plan("repoA", PrePullStatus.PLANNED_FAST_FORWARD, needs_apply=True)]
        apply.return_value = [_result("repoA", PrePullStatus.FAST_FORWARDED, changed=True)]

        runner._run_job(job.id)

        assert job.status == "succeeded"
        assert scan.call_count == 1
        restart = [w for w in job.warnings if "Restart" in w and "rlens.service" in w]
        assert restart, f"expected restart warning, got {job.warnings}"
        assert "does not reload modules automatically" in restart[0]
        ossystem.assert_not_called()
        for call in subproc.call_args_list:
            blob = " ".join(str(a) for a in call.args) + " ".join(str(v) for v in call.kwargs.values())
            assert "systemctl" not in blob


def test_self_repo_up_to_date_does_not_emit_restart_warning(mock_job_store, temp_hub):
    runner = JobRunner(mock_job_store)
    job = _make_job(temp_hub, ["repoA"], pre_pull=True)
    mock_job_store.get_job.return_value = job
    cms = _patched(self_repo=True)
    with cms["scan"] as scan, cms["write"] as write, cms["validate"], \
         cms["plan"] as plan, cms["apply"] as apply, cms["self"]:
        write.return_value = _fake_artifacts()
        plan.return_value = [_plan("repoA", PrePullStatus.UP_TO_DATE)]
        apply.return_value = [_result("repoA", PrePullStatus.UP_TO_DATE)]

        runner._run_job(job.id)

        assert job.status == "succeeded"
        assert scan.call_count == 1
        assert not any("Restart" in w for w in job.warnings), f"unexpected restart warning: {job.warnings}"

def test_pre_pull_report_written_on_success(mock_job_store, temp_hub):
    runner = JobRunner(mock_job_store)
    job = _make_job(temp_hub, ["repoA", "repoB"], pre_pull=True)
    mock_job_store.get_job.return_value = job
    cms = _patched()
    with cms["scan"] as scan, cms["write"] as write, cms["validate"], \
         cms["plan"] as plan, cms["apply"] as apply, cms["self"]:
        write.return_value = _fake_artifacts()

        plan.return_value = [
            _plan("repoA", PrePullStatus.PLANNED_FAST_FORWARD, needs_apply=True),
            _plan("repoB", PrePullStatus.LOCAL_AHEAD)
        ]
        apply.return_value = [
            _result("repoA", PrePullStatus.FAST_FORWARDED, changed=True),
            _result("repoB", PrePullStatus.LOCAL_AHEAD)
        ]

        runner._run_job(job.id)

        assert job.status == "succeeded"

        added_artifacts = mock_job_store.add_artifact.call_args_list
        assert len(added_artifacts) == 1
        art = added_artifacts[0][0][0]
        assert "pre_pull_report" in art.paths

        report_file = Path(art.merges_dir) / art.paths["pre_pull_report"]
        assert report_file.exists()

        with open(report_file) as f:
            report = json.load(f)

        assert report["schema"] == "lenskit.pre_pull_report.v1"
        assert report["summary"]["repos_total"] == 2
        assert report["summary"]["fast_forwarded"] == 1
        assert report["summary"]["warnings"] == 1

        log_lines = [call[0][1] for call in mock_job_store.append_log_line.call_args_list]
        assert any("Pre-pull report: effective=true, repos=2, fast_forwarded=1, up_to_date=0, warnings=1, hard_failures=0" in line for line in log_lines)


def test_pre_pull_report_written_on_plan_hard_fail(mock_job_store, temp_hub):
    runner = JobRunner(mock_job_store)
    job = _make_job(temp_hub, ["repoA", "repoB"], pre_pull=True)
    mock_job_store.get_job.return_value = job
    cms = _patched()
    with cms["scan"] as scan, cms["write"] as write, cms["validate"], \
         cms["plan"] as plan, cms["apply"] as apply, cms["self"]:
        plan.return_value = [
            _plan("repoA", PrePullStatus.PLANNED_FAST_FORWARD, needs_apply=True),
            _plan("repoB", PrePullStatus.UNTRACKED_WOULD_BE_OVERWRITTEN, message="local untracked path would be overwritten by upstream"),
        ]

        runner._run_job(job.id)

        assert job.status == "failed"
        assert job.artifact_ids
        art = mock_job_store.add_artifact.call_args_list[0][0][0]
        assert "pre_pull_report" in art.paths
        report_file = Path(art.merges_dir) / art.paths["pre_pull_report"]
        assert report_file.exists()

        log_lines = [call[0][1] for call in mock_job_store.append_log_line.call_args_list]
        assert any("Pre-pull report: effective=true" in line and "hard_failures=1" in line for line in log_lines)
        assert any("repoB: untracked_would_be_overwritten" in line and "local untracked path would be overwritten by upstream" in line for line in log_lines)


def test_pre_pull_report_redacts_credentials(mock_job_store, temp_hub):
    runner = JobRunner(mock_job_store)
    job = _make_job(temp_hub, ["repoA"], pre_pull=True)
    mock_job_store.get_job.return_value = job
    cms = _patched()
    with cms["scan"] as scan, cms["write"] as write, cms["validate"], \
         cms["plan"] as plan, cms["apply"] as apply, cms["self"]:
        write.return_value = _fake_artifacts()

        raw_secret = "secret-token-123"
        stderr = f"fatal: could not read from https://{raw_secret}@host/repo.git"

        plan.return_value = [
            _plan("repoA", PrePullStatus.PLANNED_FAST_FORWARD, needs_apply=True, stderr=stderr)
        ]
        apply.return_value = [
            _result("repoA", PrePullStatus.FAST_FORWARDED, changed=True, stderr=stderr)
        ]

        runner._run_job(job.id)

        added_artifacts = mock_job_store.add_artifact.call_args_list
        assert len(added_artifacts) == 1
        art = added_artifacts[0][0][0]

        report_file = Path(art.merges_dir) / art.paths["pre_pull_report"]
        with open(report_file) as f:
            blob = f.read()

        assert raw_secret not in blob
        assert "[REDACTED]" in blob


def test_pre_pull_report_skipped_for_plan_only(mock_job_store, temp_hub):
    runner = JobRunner(mock_job_store)
    job = _make_job(temp_hub, ["repoA"], pre_pull=True, plan_only=True)
    mock_job_store.get_job.return_value = job
    cms = _patched()
    with cms["scan"] as scan, cms["write"] as write, cms["validate"], \
         cms["plan"] as plan, cms["apply"] as apply, cms["self"]:
        write.return_value = _fake_artifacts()

        runner._run_job(job.id)

        plan.assert_not_called()
        apply.assert_not_called()
        assert job.status == "succeeded"

        art = mock_job_store.add_artifact.call_args_list[0][0][0]
        assert "pre_pull_report" not in art.paths


def test_pre_pull_report_skipped_for_disabled(mock_job_store, temp_hub):
    runner = JobRunner(mock_job_store)
    job = _make_job(temp_hub, ["repoA"], pre_pull=False)
    mock_job_store.get_job.return_value = job
    cms = _patched()
    with cms["scan"] as scan, cms["write"] as write, cms["validate"], \
         cms["plan"] as plan, cms["apply"] as apply, cms["self"]:
        write.return_value = _fake_artifacts()

        runner._run_job(job.id)

        plan.assert_not_called()
        apply.assert_not_called()
        assert job.status == "succeeded"

        art = mock_job_store.add_artifact.call_args_list[0][0][0]
        assert "pre_pull_report" not in art.paths
