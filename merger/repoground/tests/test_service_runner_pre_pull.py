"""Runner integration for the two-phase pre-pull preflight.

The git semantics live in test_repo_sync.py; here ``plan_pre_pull_repos`` and
``apply_pre_pull_plans`` are patched so we can assert the runner's *orchestration*:
effective-pre-pull (plan_only gate), plan-before-apply-before-scan ordering,
plan hard-fail aborting before any apply, warn-and-continue, and the self-repo
restart warning firing only on an actual fast-forward (never auto-restart).
"""
from __future__ import annotations
import logging

import tempfile
import json
from pathlib import Path

import pytest
from unittest.mock import MagicMock, patch

import jsonschema

from merger.repoground.service.runner import JobRunner, ARTIFACT_PATH_FIELDS
from merger.repoground.service.jobstore import JobStore
from merger.repoground.service.models import JobRequest, Job
from merger.repoground.service.repo_sync import PrePullPlan, PrePullResult, PrePullStatus
from merger.repoground.service.source_acquisition import RemoteSnapshotResult, RemoteRefResolution, SourceStatus

_SOURCE_ACQ_SCHEMA_PATH = (
    Path(__file__).resolve().parents[1]
    / "contracts"
    / "source-acquisition-report.v1.schema.json"
)


def _load_source_acquisition_schema() -> dict:
    return json.loads(_SOURCE_ACQ_SCHEMA_PATH.read_text(encoding="utf-8"))


# Canonical sentinel credentials. If any of these survive verbatim in a report,
# redaction failed — the weaker "'secret' not in blob OR '[REDACTED]' in blob"
# could pass while a real token still leaked, so we assert the exact values absent.
_CREDENTIAL_SENTINELS = (
    "rlens-user",
    "rlens-password-123",
    "ghp_testtoken_123456",
    "secret-token-abc",
)


def _assert_no_raw_credentials(report: dict, *extra_sentinels: str) -> None:
    blob = json.dumps(report)
    for value in (*_CREDENTIAL_SENTINELS, *extra_sentinels):
        assert value not in blob, f"raw credential leaked into report: {value!r}"


def _assert_source_acquisition_report_valid(report: dict) -> None:
    """Validate a written report against the v1 contract and its hard invariants."""
    schema = _load_source_acquisition_schema()
    jsonschema.Draft7Validator.check_schema(schema)
    jsonschema.validate(report, schema)
    assert report["schema"] == "lenskit.source_acquisition_report.v1"
    # No known raw credential value may survive anywhere in the report.
    _assert_no_raw_credentials(report)
    for repo in report["repos"]:
        # remote_snapshot never mutates the local repo.
        assert repo["local_repo_mutated"] is False
        assert isinstance(repo["local_repo_mutated"], bool)


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
        "scan": patch("merger.repoground.service.runner.scan_repo"),
        "write": patch("merger.repoground.service.runner.write_reports_v2"),
        "validate": patch("merger.repoground.service.runner.validate_source_dir"),
        "plan": patch("merger.repoground.service.runner.plan_pre_pull_repos"),
        "apply": patch("merger.repoground.service.runner.apply_pre_pull_plans"),
        "self": patch("merger.repoground.service.runner.is_self_repo", return_value=self_repo),
        "materialize": patch("merger.repoground.service.runner.materialize_remote_snapshot"),
        "resolve_ref": patch("merger.repoground.service.runner.resolve_remote_ref"),
    }
    return cms


def _snap_result(repo, snapshot_path, *, status=SourceStatus.SNAPSHOT_CREATED, warnings=None):
    return RemoteSnapshotResult(
        repo=repo,
        original_path=str(Path("/hub") / repo),
        snapshot_path=snapshot_path,
        source_mode="remote_snapshot",
        status=status,
        remote_ref_policy="default_branch",
        requested_remote_ref=None,
        resolved_ref="origin/main",
        resolved_commit="deadbeef" * 5,
        remote_url_redacted="https://[REDACTED]@host/repo.git",
        local_repo_mutated=False,
        message="ok",
        warnings=warnings or [],
    )


# ---------------------------------------------------------------------------
# remote_snapshot source acquisition
# ---------------------------------------------------------------------------


def test_remote_snapshot_scans_snapshot_and_skips_pre_pull(mock_job_store, temp_hub):
    runner = JobRunner(mock_job_store)
    snap = temp_hub / "snap-repoA"
    snap.mkdir()
    job = _make_job(temp_hub, ["repoA"], repo_source_mode="remote_snapshot", pre_pull=False,
                    remote_ref_policy="default_branch")
    mock_job_store.get_job.return_value = job
    cms = _patched()
    with cms["scan"] as scan, cms["write"] as write, cms["validate"], \
         cms["plan"] as plan, cms["apply"] as apply, cms["self"], \
         cms["materialize"] as materialize, cms["resolve_ref"], \
         patch("merger.repoground.service.runner.get_security_config") as mock_sec:
        mock_sec.return_value.validate_path.side_effect = lambda x: x
        write.return_value = _fake_artifacts()
        materialize.return_value = _snap_result("repoA", str(snap))

        runner._run_job(job.id)

        assert job.status == "succeeded"
        # No pre-pull plan/apply for remote_snapshot.
        plan.assert_not_called()
        apply.assert_not_called()
        materialize.assert_called_once()
        # Scan runs against the materialized snapshot path, not the local repo.
        assert scan.call_count == 1
        assert str(scan.call_args[0][0]) == str(snap)

        # Source acquisition report registered with original-path provenance.
        art = mock_job_store.add_artifact.call_args_list[0][0][0]
        assert "source_acquisition_report" in art.paths
        report_file = Path(art.merges_dir) / art.paths["source_acquisition_report"]
        report = json.loads(report_file.read_text())
        assert report["schema"] == "lenskit.source_acquisition_report.v1"
        assert report["mode"] == "remote_snapshot"
        # Provenance carried through verbatim, original_path distinct from scan_path.
        assert report["repos"][0]["original_path"] == str(Path("/hub") / "repoA")
        assert report["repos"][0]["scan_path"] == str(snap)
        assert report["repos"][0]["original_path"] != report["repos"][0]["scan_path"]
        assert report["repos"][0]["local_repo_mutated"] is False
        # Success report validates against the v1 contract.
        _assert_source_acquisition_report_valid(report)


def test_remote_snapshot_plan_only_dry_plan(mock_job_store, temp_hub):
    runner = JobRunner(mock_job_store)
    job = _make_job(temp_hub, ["repoA"], repo_source_mode="remote_snapshot", pre_pull=False,
                    plan_only=True, remote_ref_policy="default_branch")
    mock_job_store.get_job.return_value = job
    cms = _patched()
    with cms["scan"] as scan, cms["write"] as write, cms["validate"], \
         cms["plan"] as plan, cms["apply"] as apply, cms["self"], \
         cms["materialize"] as materialize, cms["resolve_ref"] as resolve_ref, \
         patch("merger.repoground.service.runner.get_security_config") as mock_sec:
        mock_sec.return_value.validate_path.side_effect = lambda x: x
        resolve_ref.return_value = RemoteRefResolution(
            repo="repoA", repo_path=str(temp_hub / "repoA"), policy="default_branch",
            requested_remote_ref=None, resolved_ref="origin/main", resolved_commit="cafe" * 10,
            status=SourceStatus.RESOLVED, message="ok",
            remote_url_redacted="https://[REDACTED]@host/repo.git",
        )

        runner._run_job(job.id)

        assert job.status == "succeeded"
        # Dry-plan: ref resolution only, no materialization, no scan, no bundle write.
        resolve_ref.assert_called_once()
        materialize.assert_not_called()
        scan.assert_not_called()
        write.assert_not_called()
        plan.assert_not_called()
        apply.assert_not_called()

        art = mock_job_store.add_artifact.call_args_list[0][0][0]
        assert "source_acquisition_report" in art.paths
        report = json.loads((Path(art.merges_dir) / art.paths["source_acquisition_report"]).read_text())
        assert report["repos"][0]["status"] == SourceStatus.PLANNED
        assert report["repos"][0]["resolved_ref"] == "origin/main"
        # Plan-only report validates against the v1 contract.
        assert report["plan_only"] is True
        _assert_source_acquisition_report_valid(report)


def test_remote_snapshot_failure_fails_job_and_writes_report(mock_job_store, temp_hub):
    runner = JobRunner(mock_job_store)
    job = _make_job(temp_hub, ["repoA"], repo_source_mode="remote_snapshot", pre_pull=False,
                    remote_ref_policy="upstream")
    mock_job_store.get_job.return_value = job
    cms = _patched()
    with cms["scan"] as scan, cms["write"], cms["validate"], \
         cms["plan"], cms["apply"], cms["self"], \
         cms["materialize"] as materialize, cms["resolve_ref"], \
         patch("merger.repoground.service.runner.get_security_config") as mock_sec:
        mock_sec.return_value.validate_path.side_effect = lambda x: x
        materialize.return_value = _snap_result("repoA", None, status=SourceStatus.MISSING_REF)

        runner._run_job(job.id)

        assert job.status == "failed"
        assert "Source acquisition failed" in (job.error or "")
        scan.assert_not_called()
        art = mock_job_store.add_artifact.call_args_list[0][0][0]
        assert "source_acquisition_report" in art.paths
        report = json.loads((Path(art.merges_dir) / art.paths["source_acquisition_report"]).read_text())
        # Failure report still validates against the v1 contract.
        assert report["repos"][0]["status"] == SourceStatus.MISSING_REF
        _assert_source_acquisition_report_valid(report)


def test_remote_snapshot_report_redacts_credentials(mock_job_store, temp_hub):
    # The report writer routes message/stderr through _safe_text (credential
    # redaction). A result carrying raw userinfo must never leak it into the report.
    runner = JobRunner(mock_job_store)
    job = _make_job(temp_hub, ["repoA"], repo_source_mode="remote_snapshot", pre_pull=False,
                    remote_ref_policy="upstream")
    mock_job_store.get_job.return_value = job
    cms = _patched()
    with cms["scan"], cms["write"], cms["validate"], \
         cms["plan"], cms["apply"], cms["self"], \
         cms["materialize"] as materialize, cms["resolve_ref"], \
         patch("merger.repoground.service.runner.get_security_config") as mock_sec:
        mock_sec.return_value.validate_path.side_effect = lambda x: x
        raw_secret = "secret-token-abc"
        leaky = _snap_result("repoA", None, status=SourceStatus.FETCH_FAILED)
        leaky.message = f"fetch failed for https://rlens-user:{raw_secret}@host/repo.git"
        leaky.stderr = f"fatal: authentication failed for https://{raw_secret}@host/repo.git"
        materialize.return_value = leaky

        runner._run_job(job.id)

        art = mock_job_store.add_artifact.call_args_list[0][0][0]
        report = json.loads((Path(art.merges_dir) / art.paths["source_acquisition_report"]).read_text())
        # The raw token and userinfo are gone; the redaction marker is present.
        _assert_no_raw_credentials(report, raw_secret)
        blob = json.dumps(report)
        assert "[REDACTED]" in blob
        _assert_source_acquisition_report_valid(report)


def test_remote_snapshot_report_registered_when_canceled_during_scan(mock_job_store, temp_hub):
    runner = JobRunner(mock_job_store)
    job = _make_job(temp_hub, ["repoA", "repoB"], repo_source_mode="remote_snapshot", pre_pull=False)

    get_job_calls = {"count": 0}
    def mock_get_job(jid):
        get_job_calls["count"] += 1
        if get_job_calls["count"] > 1:
            job.status = "canceled"
        return job

    mock_job_store.get_job.side_effect = mock_get_job

    cms = _patched()
    with cms["scan"], cms["write"], cms["validate"], \
         cms["plan"], cms["apply"], cms["self"], \
         cms["materialize"] as materialize, cms["resolve_ref"], \
         patch("merger.repoground.service.runner.get_security_config") as mock_sec:

        mock_sec.return_value.validate_path.side_effect = lambda x: x
        materialize.side_effect = [
            _snap_result("repoA", str(temp_hub / "snap-repoA")),
            _snap_result("repoB", str(temp_hub / "snap-repoB")),
        ]

        runner._run_job(job.id)

        assert job.status == "canceled"
        assert materialize.call_count == 2

        added_artifacts = mock_job_store.add_artifact.call_args_list
        assert len(added_artifacts) == 1
        art = added_artifacts[0][0][0]
        assert "source_acquisition_report" in art.paths


def test_plan_only_skips_pre_pull_even_if_requested(mock_job_store, temp_hub):
    runner = JobRunner(mock_job_store)
    job = _make_job(temp_hub, ["repoA"], pre_pull=True, plan_only=True)
    mock_job_store.get_job.return_value = job
    cms = _patched()
    with cms["scan"] as scan, cms["write"] as write, cms["validate"], \
         cms["plan"] as plan, cms["apply"] as apply, cms["self"], \
         patch("merger.repoground.service.runner.get_security_config") as mock_sec:
        mock_sec.return_value.validate_path.side_effect = lambda x: x
        write.return_value = _fake_artifacts()
        runner._run_job(job.id)
        plan.assert_not_called()
        apply.assert_not_called()
        assert scan.call_count == 1
        assert job.status == "succeeded"


def test_final_artifact_has_resolved_repo_names(mock_job_store, temp_hub):
    runner = JobRunner(mock_job_store)
    # Implicit job (no specific repos requested)
    job = _make_job(temp_hub, [], pre_pull=True, plan_only=True)
    mock_job_store.get_job.return_value = job
    cms = _patched()
    with cms["scan"], cms["write"] as write, cms["validate"], \
         cms["plan"], cms["apply"], cms["self"], \
         patch("merger.repoground.service.runner.get_security_config") as mock_sec, \
         patch("merger.repoground.adapters.security.validate_source_dir", side_effect=lambda x: x):
        mock_sec.return_value.validate_path.side_effect = lambda x: x
        write.return_value = _fake_artifacts()
        runner._run_job(job.id)

        assert job.status == "succeeded"
        added_artifacts = mock_job_store.add_artifact.call_args_list
        assert len(added_artifacts) == 1
        art = added_artifacts[0][0][0]
        # Should resolve to all repos in temp_hub
        assert set(art.repos) == {"repoA", "repoB"}


def test_pre_pull_report_custom_merges_dir_validates_before_mkdir(mock_job_store, temp_hub):
    from merger.repoground.adapters.security import SecurityViolationError

    blocked_dir = temp_hub / "blocked-merges"

    runner = JobRunner(mock_job_store)
    job = _make_job(temp_hub, ["repoA"], pre_pull=True)
    job.request.merges_dir = "blocked-merges"
    mock_job_store.get_job.return_value = job

    cms = _patched()
    with cms["scan"] as scan, cms["write"], cms["validate"], \
         cms["plan"] as plan, cms["apply"] as apply, cms["self"], \
         patch("merger.repoground.service.runner.get_security_config") as mock_sec:

        security = MagicMock()
        security.validate_path.side_effect = SecurityViolationError("blocked merges_dir https://secret-token@host/repo")
        mock_sec.return_value = security

        runner._run_job(job.id)

    assert job.status == "failed"
    assert "blocked" in (job.error or "").lower() or "security" in (job.error or "").lower()
    assert "secret-token" not in (job.error or "")
    assert "[REDACTED]" in (job.error or "")
    for line in job.logs:
        assert "secret-token" not in line

    assert not blocked_dir.exists()
    plan.assert_not_called()
    apply.assert_not_called()
    scan.assert_not_called()


def test_pre_pull_false_skips_pre_pull(mock_job_store, temp_hub):
    runner = JobRunner(mock_job_store)
    job = _make_job(temp_hub, ["repoA"], pre_pull=False)
    mock_job_store.get_job.return_value = job
    cms = _patched()
    with cms["scan"] as scan, cms["write"] as write, cms["validate"], \
         cms["plan"] as plan, cms["apply"] as apply, cms["self"], \
         patch("merger.repoground.service.runner.get_security_config") as mock_sec:
        mock_sec.return_value.validate_path.side_effect = lambda x: x
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
         cms["plan"] as plan, cms["apply"] as apply, cms["self"], \
         patch("merger.repoground.service.runner.get_security_config") as mock_sec:
        mock_sec.return_value.validate_path.side_effect = lambda x: x
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
         cms["plan"] as plan, cms["apply"] as apply, cms["self"], \
         patch("merger.repoground.service.runner.get_security_config") as mock_sec:
        mock_sec.return_value.validate_path.side_effect = lambda x: x
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
         cms["plan"] as plan, cms["apply"] as apply, cms["self"], \
         patch("merger.repoground.service.runner.get_security_config") as mock_sec:
        mock_sec.return_value.validate_path.side_effect = lambda x: x
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
         cms["plan"] as plan, cms["apply"] as apply, cms["self"], \
         patch("merger.repoground.service.runner.get_security_config") as mock_sec:
        mock_sec.return_value.validate_path.side_effect = lambda x: x
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
         cms["plan"] as plan, cms["apply"] as apply, cms["self"], \
         patch("merger.repoground.service.runner.get_security_config") as mock_sec:
        mock_sec.return_value.validate_path.side_effect = lambda x: x
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
        restart = [w for w in job.warnings if "Restart" in w and "repoground.service" in w]
        assert restart, f"expected restart warning, got {job.warnings}"
        assert "does not reload modules automatically" in restart[0]

        log_lines = [call[0][1] for call in mock_job_store.append_log_line.call_args_list]
        assert any("Restart repoground.service" in line for line in log_lines)

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
         cms["plan"] as plan, cms["apply"] as apply, cms["self"], \
         patch("merger.repoground.service.runner.get_security_config") as mock_sec:
        mock_sec.return_value.validate_path.side_effect = lambda x: x
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
    with cms["scan"], cms["write"] as write, cms["validate"], \
         cms["plan"] as plan, cms["apply"] as apply, cms["self"], \
         patch("merger.repoground.service.runner.get_security_config") as mock_sec:
        mock_sec.return_value.validate_path.side_effect = lambda x: x
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
        assert len(added_artifacts) == 2
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
    with cms["scan"] as scan, cms["write"], cms["validate"], \
         cms["plan"] as plan, cms["apply"] as apply, cms["self"], \
         patch("merger.repoground.service.runner.get_security_config") as mock_sec:
        mock_sec.return_value.validate_path.side_effect = lambda x: x
        plan.return_value = [
            _plan("repoA", PrePullStatus.PLANNED_FAST_FORWARD, needs_apply=True),
            _plan("repoB", PrePullStatus.UNTRACKED_WOULD_BE_OVERWRITTEN, message="local untracked path would be overwritten by upstream"),
        ]

        runner._run_job(job.id)

        apply.assert_not_called()
        scan.assert_not_called()

        assert job.status == "failed"
        assert job.artifact_ids
        art = mock_job_store.add_artifact.call_args_list[0][0][0]
        assert art.repos == ["repoA", "repoB"]
        assert "pre_pull_report" in art.paths
        report_file = Path(art.merges_dir) / art.paths["pre_pull_report"]
        assert report_file.exists()

        log_lines = [call[0][1] for call in mock_job_store.append_log_line.call_args_list]
        assert any("Pre-pull report: effective=true" in line and "hard_failures=1" in line for line in log_lines)
        assert any("repoB: untracked_would_be_overwritten" in line and "local untracked path would be overwritten by upstream" in line for line in log_lines)


def test_pre_pull_report_registered_when_scan_fails_after_success(mock_job_store, temp_hub):
    runner = JobRunner(mock_job_store)
    job = _make_job(temp_hub, ["repoA"], pre_pull=True)
    mock_job_store.get_job.return_value = job
    cms = _patched()
    with cms["scan"] as scan, cms["write"], cms["validate"], \
         cms["plan"] as plan, cms["apply"] as apply, cms["self"], \
         patch("merger.repoground.service.runner.get_security_config") as mock_sec:
        mock_sec.return_value.validate_path.side_effect = lambda x: x
        plan.return_value = [_plan("repoA", PrePullStatus.PLANNED_FAST_FORWARD, needs_apply=True)]
        apply.return_value = [_result("repoA", PrePullStatus.FAST_FORWARDED, changed=True)]

        scan.side_effect = RuntimeError("scan boom")

        runner._run_job(job.id)

        assert job.status == "failed"
        assert "scan boom" in (job.error or "")

        added_artifacts = mock_job_store.add_artifact.call_args_list
        assert len(added_artifacts) == 1
        art = added_artifacts[0][0][0]
        assert art.repos == ["repoA"]
        assert "pre_pull_report" in art.paths
        report_file = Path(art.merges_dir) / art.paths["pre_pull_report"]
        assert report_file.exists()


def test_pre_pull_report_redacts_credentials(mock_job_store, temp_hub):
    runner = JobRunner(mock_job_store)
    job = _make_job(temp_hub, ["repoA"], pre_pull=True)
    mock_job_store.get_job.return_value = job
    cms = _patched()
    with cms["scan"], cms["write"] as write, cms["validate"], \
         cms["plan"] as plan, cms["apply"] as apply, cms["self"], \
         patch("merger.repoground.service.runner.get_security_config") as mock_sec:
        mock_sec.return_value.validate_path.side_effect = lambda x: x
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
        assert len(added_artifacts) == 2
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
    with cms["scan"], cms["write"] as write, cms["validate"], \
         cms["plan"] as plan, cms["apply"] as apply, cms["self"], \
         patch("merger.repoground.service.runner.get_security_config") as mock_sec:
        mock_sec.return_value.validate_path.side_effect = lambda x: x
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
    with cms["scan"], cms["write"] as write, cms["validate"], \
         cms["plan"] as plan, cms["apply"] as apply, cms["self"], \
         patch("merger.repoground.service.runner.get_security_config") as mock_sec:
        mock_sec.return_value.validate_path.side_effect = lambda x: x
        write.return_value = _fake_artifacts()

        runner._run_job(job.id)

        plan.assert_not_called()
        apply.assert_not_called()
        assert job.status == "succeeded"

        art = mock_job_store.add_artifact.call_args_list[0][0][0]
        assert "pre_pull_report" not in art.paths


def test_pre_pull_report_written_on_plan_exception(mock_job_store, temp_hub, caplog):
    runner = JobRunner(mock_job_store)
    job = _make_job(temp_hub, ["repoA"], pre_pull=True)
    mock_job_store.get_job.return_value = job
    cms = _patched()
    with cms["scan"], cms["write"], cms["validate"], \
         cms["plan"] as plan, cms["apply"], cms["self"]:

        plan.side_effect = RuntimeError("https://secret-token@host/repo.git plan boom")

        with caplog.at_level(logging.INFO, logger="merger.repoground.service.runner"):
            runner._run_job(job.id)

        assert job.status == "failed"
        assert "secret-token" not in (job.error or "")
        assert "[REDACTED]" in (job.error or "")
        assert "plan boom" in (job.error or "")

        assert "secret-token" not in caplog.text
        for line in job.logs:
            assert "secret-token" not in line

        added_artifacts = mock_job_store.add_artifact.call_args_list
        assert len(added_artifacts) == 1
        art = added_artifacts[0][0][0]
        assert "pre_pull_report" in art.paths
        assert art.repos == ["repoA"]
        report_file = Path(art.merges_dir) / art.paths["pre_pull_report"]
        assert report_file.exists()

        with open(report_file) as f:
            blob = f.read()

        assert "secret-token" not in blob
        assert "[REDACTED]" in blob

        report = json.loads(blob)
        assert report["schema"] == "lenskit.pre_pull_report.v1"
        assert report["phase"] == "plan_exception"
        assert report["effective_pre_pull"] is True
        assert report["repos"][0]["repo"] == "__pre_pull__"
        assert report["repos"][-1]["plan_status"] == "error"


def test_pre_pull_report_write_failure_aborts_job(mock_job_store, temp_hub):
    runner = JobRunner(mock_job_store)
    job = _make_job(temp_hub, ["repoA"], pre_pull=True)
    mock_job_store.get_job.return_value = job
    cms = _patched()
    with cms["scan"], cms["write"], cms["validate"], \
         cms["plan"] as plan, cms["apply"] as apply, cms["self"], \
         patch("json.dump", side_effect=OSError("disk full")):

        plan.return_value = [_plan("repoA", PrePullStatus.PLANNED_FAST_FORWARD, needs_apply=True)]
        apply.return_value = [_result("repoA", PrePullStatus.FAST_FORWARDED, changed=True)]

        runner._run_job(job.id)

        assert job.status == "failed"
        assert "failed to write pre_pull_report" in (job.error or "")
        assert "disk full" in (job.error or "")

        added_artifacts = mock_job_store.add_artifact.call_args_list
        assert len(added_artifacts) == 0


def test_pre_pull_report_uses_relative_merges_dir(mock_job_store, temp_hub):
    runner = JobRunner(mock_job_store)
    job = _make_job(temp_hub, ["repoA"], pre_pull=True)
    job.request.merges_dir = "custom-merges"
    mock_job_store.get_job.return_value = job
    cms = _patched()
    with cms["scan"], cms["write"] as write, cms["validate"], \
         cms["plan"] as plan, cms["apply"] as apply, cms["self"], \
         patch("merger.repoground.service.runner.get_security_config") as mock_sec:
        mock_sec.return_value.validate_path.side_effect = lambda x: x
        write.return_value = _fake_artifacts()

        plan.return_value = [_plan("repoA", PrePullStatus.PLANNED_FAST_FORWARD, needs_apply=True)]
        apply.return_value = [_result("repoA", PrePullStatus.FAST_FORWARDED, changed=True)]

        runner._run_job(job.id)

        assert job.status == "succeeded"

        added_artifacts = mock_job_store.add_artifact.call_args_list
        assert len(added_artifacts) == 2
        art = added_artifacts[0][0][0]
        assert "pre_pull_report" in art.paths
        assert art.merges_dir == str((temp_hub / "custom-merges").resolve())

        report_file = Path(art.merges_dir) / art.paths["pre_pull_report"]
        assert report_file.exists()

def test_pre_pull_report_registered_when_canceled_during_scan(mock_job_store, temp_hub):
    runner = JobRunner(mock_job_store)
    job = _make_job(temp_hub, ["repoA", "repoB"], pre_pull=True)

    get_job_calls = {"count": 0}
    def mock_get_job(jid):
        get_job_calls["count"] += 1
        if get_job_calls["count"] > 1:
            job.status = "canceled"
        return job

    mock_job_store.get_job.side_effect = mock_get_job

    cms = _patched()
    with cms["scan"], cms["write"], cms["validate"], \
         cms["plan"] as plan, cms["apply"] as apply, cms["self"], \
         patch("merger.repoground.service.runner.get_security_config") as mock_sec:

        mock_sec.return_value.validate_path.side_effect = lambda x: x
        plan.return_value = [
            _plan("repoA", PrePullStatus.PLANNED_FAST_FORWARD, needs_apply=True),
            _plan("repoB", PrePullStatus.UP_TO_DATE, needs_apply=False)
        ]
        apply.return_value = [_result("repoA", PrePullStatus.FAST_FORWARDED, changed=True)]

        runner._run_job(job.id)

        assert job.status == "canceled"
        assert apply.call_count == 1

        added_artifacts = mock_job_store.add_artifact.call_args_list
        assert len(added_artifacts) == 1
        art = added_artifacts[0][0][0]
        assert "pre_pull_report" in art.paths


def test_pre_pull_report_registered_when_canceled_at_pre_write(mock_job_store, temp_hub):
    runner = JobRunner(mock_job_store)
    job = _make_job(temp_hub, ["repoA"], pre_pull=True)

    get_job_calls = {"count": 0}
    def mock_get_job(jid):
        get_job_calls["count"] += 1
        if get_job_calls["count"] == 3:
            job.status = "canceled"
        return job

    mock_job_store.get_job.side_effect = mock_get_job

    cms = _patched()
    with cms["scan"] as scan, cms["write"] as write, cms["validate"], \
         cms["plan"] as plan, cms["apply"] as apply, cms["self"], \
         patch("merger.repoground.service.runner.get_security_config") as mock_sec:

        mock_sec.return_value.validate_path.side_effect = lambda x: x
        plan.return_value = [_plan("repoA", PrePullStatus.PLANNED_FAST_FORWARD, needs_apply=True)]
        apply.return_value = [_result("repoA", PrePullStatus.FAST_FORWARDED, changed=True)]

        runner._run_job(job.id)

        assert job.status == "canceled"
        assert scan.call_count == 1
        assert write.call_count == 0
        added_artifacts = mock_job_store.add_artifact.call_args_list
        assert len(added_artifacts) == 1
        art = added_artifacts[0][0][0]
        assert "pre_pull_report" in art.paths

def test_pre_pull_report_early_failure_before_registrar_definition(mock_job_store, temp_hub):
    runner = JobRunner(mock_job_store)
    # create a job without hub_resolved to trigger early failure before try: block
    job = _make_job(temp_hub, ["repoA"], pre_pull=True)
    job.hub_resolved = None
    mock_job_store.get_job.return_value = job

    cms = _patched()
    with cms["scan"], cms["write"], cms["validate"], \
         cms["plan"], cms["apply"], cms["self"]:

        runner._run_job(job.id)

        assert job.status == "failed"
        assert "Internal: hub_resolved missing on job" in job.error
        # add_artifact should NOT be called
        added_artifacts = mock_job_store.add_artifact.call_args_list
        assert len(added_artifacts) == 0

def test_pre_pull_report_written_on_apply_exception(mock_job_store, temp_hub):
    runner = JobRunner(mock_job_store)
    job = _make_job(temp_hub, ["repoA"], pre_pull=True)
    mock_job_store.get_job.return_value = job
    cms = _patched()
    with cms["scan"], cms["write"], cms["validate"], \
         cms["plan"] as plan, cms["apply"] as apply, cms["self"], \
         patch("merger.repoground.service.runner.get_security_config") as mock_sec:

        mock_sec.return_value.validate_path.side_effect = lambda x: x
        plan.return_value = [
            _plan("repoA", PrePullStatus.PLANNED_FAST_FORWARD, needs_apply=True),
        ]
        apply.side_effect = RuntimeError("https://secret-token@host/repo.git apply boom")

        runner._run_job(job.id)

        assert job.status == "failed"
        assert "secret-token" not in (job.error or "")
        assert "[REDACTED]" in (job.error or "")
        assert "apply boom" in (job.error or "")

        added_artifacts = mock_job_store.add_artifact.call_args_list
        assert len(added_artifacts) == 1
        art = added_artifacts[0][0][0]
        assert "pre_pull_report" in art.paths

        report_file = Path(art.merges_dir) / art.paths["pre_pull_report"]
        with open(report_file) as f:
            blob = f.read()

        assert "secret-token" not in blob
        assert "[REDACTED]" in blob

        report = json.loads(blob)
        assert report["phase"] == "apply_exception"
        assert report["repos"][-1]["plan_status"] == "error"


def test_pre_pull_report_artifact_registration_exception_redacted(mock_job_store, temp_hub, caplog):
    from merger.repoground.service.runner import _register_pre_pull_report_artifact_once

    job = _make_job(temp_hub, ["repoA"], pre_pull=True)
    report_path = temp_hub / "report.json"
    report_path.write_text("{}")

    mock_job_store.add_artifact.side_effect = RuntimeError("https://secret-token@host/artifact boom")

    with caplog.at_level(logging.WARNING, logger="merger.repoground.service.runner"):
        success = _register_pre_pull_report_artifact_once(
            job_store=mock_job_store,
            job=job,
            report_path=report_path,
            already_registered=False,
        )

    assert success is False
    assert "secret-token" not in caplog.text
    assert "[REDACTED]" in caplog.text

    for line in job.logs:
        assert "secret-token" not in line
