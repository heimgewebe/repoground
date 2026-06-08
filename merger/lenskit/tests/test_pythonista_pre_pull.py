"""Pythonista (repoLens) pre-pull parity: shared two-phase helper + headless gates.

repolens.py imports headlessly (its Pythonista ``ui`` import is guarded), so we can
exercise ``run_pre_pull_two_phase`` and the ``--plan-only --pre-pull`` CLI gate
directly. The git semantics themselves live in test_repo_sync.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

import merger.lenskit.frontends.pythonista.repolens as repolens
from merger.lenskit.service.repo_sync import PrePullPlan, PrePullResult, PrePullStatus


def test_run_pre_pull_two_phase_unavailable_raises(monkeypatch):
    """Requested pre-pull must error (not silently skip) when repo_sync is missing."""
    monkeypatch.setattr(repolens, "plan_pre_pull_repos", None)
    monkeypatch.setattr(repolens, "apply_pre_pull_plans", None)
    with pytest.raises(RuntimeError, match="repo_sync module is unavailable"):
        repolens.run_pre_pull_two_phase([Path("/some/repo")], log=lambda m: None)


def test_run_pre_pull_two_phase_plan_hard_fail_skips_apply(monkeypatch):
    dirty = PrePullPlan(repo="a", path="/hub/a", status=PrePullStatus.DIRTY, message="dirty")
    applied = []
    monkeypatch.setattr(repolens, "plan_pre_pull_repos", lambda sources, *a, **k: [dirty])
    monkeypatch.setattr(
        repolens, "apply_pre_pull_plans", lambda plans, *a, **k: applied.append(plans) or []
    )
    with pytest.raises(ValueError, match="no repo HEADs or working trees were fast-forwarded"):
        repolens.run_pre_pull_two_phase([Path("/hub/a")], log=lambda m: None)
    assert applied == [], "apply must not run when a plan hard-fails"


def test_run_pre_pull_two_phase_multi_repo_no_partial_apply(monkeypatch):
    """A behind repo + a dirty repo → no apply at all (no partial fast-forward)."""
    plans = [
        PrePullPlan(repo="ff", path="/hub/ff", status=PrePullStatus.PLANNED_FAST_FORWARD, needs_apply=True),
        PrePullPlan(repo="dirty", path="/hub/dirty", status=PrePullStatus.DIRTY, message="dirty"),
    ]
    applied = []
    monkeypatch.setattr(repolens, "plan_pre_pull_repos", lambda sources, *a, **k: plans)
    monkeypatch.setattr(
        repolens, "apply_pre_pull_plans", lambda p, *a, **k: applied.append(p) or []
    )
    with pytest.raises(ValueError, match="no repo HEADs or working trees were fast-forwarded"):
        repolens.run_pre_pull_two_phase([Path("/hub/ff"), Path("/hub/dirty")], log=lambda m: None)
    assert applied == []


def test_run_pre_pull_two_phase_self_repo_fast_forward_warns(monkeypatch):
    plan = PrePullPlan(repo="lenskit", path="/repos/lenskit", status=PrePullStatus.PLANNED_FAST_FORWARD, needs_apply=True)
    result = PrePullResult(repo="lenskit", path="/repos/lenskit", status=PrePullStatus.FAST_FORWARDED, changed=True)
    monkeypatch.setattr(repolens, "plan_pre_pull_repos", lambda sources, *a, **k: [plan])
    monkeypatch.setattr(repolens, "apply_pre_pull_plans", lambda plans, *a, **k: [result])
    monkeypatch.setattr(repolens, "is_self_repo", lambda p: True)

    warnings = []
    repolens.run_pre_pull_two_phase([Path("/repos/lenskit")], log=lambda m: None, warn=warnings.append)
    assert any("restart" in w.lower() for w in warnings), warnings


def test_run_pre_pull_two_phase_self_repo_up_to_date_no_warn(monkeypatch):
    plan = PrePullPlan(repo="lenskit", path="/repos/lenskit", status=PrePullStatus.UP_TO_DATE)
    result = PrePullResult(repo="lenskit", path="/repos/lenskit", status=PrePullStatus.UP_TO_DATE)
    monkeypatch.setattr(repolens, "plan_pre_pull_repos", lambda sources, *a, **k: [plan])
    monkeypatch.setattr(repolens, "apply_pre_pull_plans", lambda plans, *a, **k: [result])
    monkeypatch.setattr(repolens, "is_self_repo", lambda p: True)

    warnings = []
    repolens.run_pre_pull_two_phase([Path("/repos/lenskit")], log=lambda m: None, warn=warnings.append)
    assert not any("restart" in w.lower() for w in warnings), warnings


def test_headless_plan_only_with_pre_pull_is_rejected(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["repolens.py", "--plan-only", "--pre-pull", "--headless"])
    with pytest.raises(SystemExit) as exc:
        repolens.main_cli()
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "mutually exclusive" in err


def test_headless_pre_pull_and_no_pre_pull_argparse_error(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["repolens.py", "--pre-pull", "--no-pre-pull", "--headless"])
    with pytest.raises(SystemExit) as exc:
        repolens.main_cli()
    assert exc.value.code == 2


# --- headless source mode ---------------------------------------------------

class _Args:
    def __init__(self, **kw):
        self.source_mode = kw.get("source_mode")
        self.pre_pull = kw.get("pre_pull")
        self.plan_only = kw.get("plan_only", False)


def test_resolve_headless_source_mode_mapping():
    r = repolens.resolve_headless_source_mode
    assert r(_Args(source_mode="remote-snapshot")) == "remote_snapshot"
    assert r(_Args(source_mode="local-current")) == "local_current"
    assert r(_Args(source_mode="local-ff")) == "local_ff"
    # local-ff under plan_only must not mutate → local_current.
    assert r(_Args(source_mode="local-ff", plan_only=True)) == "local_current"
    # Legacy derivation.
    assert r(_Args(pre_pull=True)) == "local_ff"
    assert r(_Args(pre_pull=False)) == "local_current"
    assert r(_Args(pre_pull=None, plan_only=True)) == "local_current"


@pytest.mark.parametrize("argv", [
    ["repolens.py", "--source-mode", "local-current", "--pre-pull", "--headless"],
    ["repolens.py", "--source-mode", "local-ff", "--no-pre-pull", "--headless"],
    ["repolens.py", "--source-mode", "remote-snapshot", "--pre-pull", "--headless"],
])
def test_headless_source_mode_pre_pull_conflicts(monkeypatch, argv):
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit) as exc:
        repolens.main_cli()
    assert exc.value.code == 2


# --- resolve_pre_pull_switch_value helper -----------------------------------

def test_resolve_pre_pull_switch_value_none_returns_true():
    """Absent switch defaults to True (matches the documented pre_pull default)."""
    assert repolens.resolve_pre_pull_switch_value(None) is True


def test_resolve_pre_pull_switch_value_switch_on():
    class FakeSwitch:
        value = True
    assert repolens.resolve_pre_pull_switch_value(FakeSwitch()) is True


def test_resolve_pre_pull_switch_value_switch_off():
    class FakeSwitch:
        value = False
    assert repolens.resolve_pre_pull_switch_value(FakeSwitch()) is False
