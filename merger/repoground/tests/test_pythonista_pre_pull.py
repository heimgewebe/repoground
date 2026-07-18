"""Pythonista (repoLens) pre-pull parity: shared two-phase helper + headless gates.

repo_ground.py imports headlessly (its Pythonista ``ui`` import is guarded), so we can
exercise ``run_pre_pull_two_phase`` and the ``--plan-only --pre-pull`` CLI gate
directly. The git semantics themselves live in test_repo_sync.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

import merger.repoground.frontends.pythonista.build as repo_ground
from merger.repoground.service.repo_sync import PrePullPlan, PrePullResult, PrePullStatus


def test_run_pre_pull_two_phase_unavailable_raises(monkeypatch):
    """Requested pre-pull must error (not silently skip) when repo_sync is missing."""
    monkeypatch.setattr(repo_ground, "plan_pre_pull_repos", None)
    monkeypatch.setattr(repo_ground, "apply_pre_pull_plans", None)
    with pytest.raises(RuntimeError, match="repo_sync module is unavailable"):
        repo_ground.run_pre_pull_two_phase([Path("/some/repo")], log=lambda m: None)


def test_run_pre_pull_two_phase_plan_hard_fail_skips_apply(monkeypatch):
    dirty = PrePullPlan(repo="a", path="/hub/a", status=PrePullStatus.DIRTY, message="dirty")
    applied = []
    monkeypatch.setattr(repo_ground, "plan_pre_pull_repos", lambda sources, *a, **k: [dirty])
    monkeypatch.setattr(
        repo_ground, "apply_pre_pull_plans", lambda plans, *a, **k: applied.append(plans) or []
    )
    with pytest.raises(ValueError, match="no repo HEADs or working trees were fast-forwarded"):
        repo_ground.run_pre_pull_two_phase([Path("/hub/a")], log=lambda m: None)
    assert applied == [], "apply must not run when a plan hard-fails"


def test_run_pre_pull_two_phase_multi_repo_no_partial_apply(monkeypatch):
    """A behind repo + a dirty repo → no apply at all (no partial fast-forward)."""
    plans = [
        PrePullPlan(repo="ff", path="/hub/ff", status=PrePullStatus.PLANNED_FAST_FORWARD, needs_apply=True),
        PrePullPlan(repo="dirty", path="/hub/dirty", status=PrePullStatus.DIRTY, message="dirty"),
    ]
    applied = []
    monkeypatch.setattr(repo_ground, "plan_pre_pull_repos", lambda sources, *a, **k: plans)
    monkeypatch.setattr(
        repo_ground, "apply_pre_pull_plans", lambda p, *a, **k: applied.append(p) or []
    )
    with pytest.raises(ValueError, match="no repo HEADs or working trees were fast-forwarded"):
        repo_ground.run_pre_pull_two_phase([Path("/hub/ff"), Path("/hub/dirty")], log=lambda m: None)
    assert applied == []


def test_run_pre_pull_two_phase_self_repo_fast_forward_warns(monkeypatch):
    plan = PrePullPlan(repo="repoground", path="/repos/repoground", status=PrePullStatus.PLANNED_FAST_FORWARD, needs_apply=True)
    result = PrePullResult(repo="repoground", path="/repos/repoground", status=PrePullStatus.FAST_FORWARDED, changed=True)
    monkeypatch.setattr(repo_ground, "plan_pre_pull_repos", lambda sources, *a, **k: [plan])
    monkeypatch.setattr(repo_ground, "apply_pre_pull_plans", lambda plans, *a, **k: [result])
    monkeypatch.setattr(repo_ground, "is_self_repo", lambda p: True)

    warnings = []
    repo_ground.run_pre_pull_two_phase([Path("/repos/repoground")], log=lambda m: None, warn=warnings.append)
    assert any("restart" in w.lower() for w in warnings), warnings


def test_run_pre_pull_two_phase_self_repo_up_to_date_no_warn(monkeypatch):
    plan = PrePullPlan(repo="repoground", path="/repos/repoground", status=PrePullStatus.UP_TO_DATE)
    result = PrePullResult(repo="repoground", path="/repos/repoground", status=PrePullStatus.UP_TO_DATE)
    monkeypatch.setattr(repo_ground, "plan_pre_pull_repos", lambda sources, *a, **k: [plan])
    monkeypatch.setattr(repo_ground, "apply_pre_pull_plans", lambda plans, *a, **k: [result])
    monkeypatch.setattr(repo_ground, "is_self_repo", lambda p: True)

    warnings = []
    repo_ground.run_pre_pull_two_phase([Path("/repos/repoground")], log=lambda m: None, warn=warnings.append)
    assert not any("restart" in w.lower() for w in warnings), warnings


def test_headless_plan_only_with_pre_pull_is_rejected(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["repo_ground.py", "--plan-only", "--pre-pull", "--headless"])
    with pytest.raises(SystemExit) as exc:
        repo_ground.main_cli()
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "mutually exclusive" in err


def test_headless_pre_pull_and_no_pre_pull_argparse_error(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["repo_ground.py", "--pre-pull", "--no-pre-pull", "--headless"])
    with pytest.raises(SystemExit) as exc:
        repo_ground.main_cli()
    assert exc.value.code == 2


# --- headless source mode ---------------------------------------------------

class _Args:
    def __init__(self, **kw):
        self.source_mode = kw.get("source_mode")
        self.pre_pull = kw.get("pre_pull")
        self.plan_only = kw.get("plan_only", False)


# --- resolve_effective_headless_source_mode ---------------------------------

def test_resolve_effective_headless_source_mode_off_ios_preserves_default(monkeypatch):
    """Off-iOS: the implicit default still resolves to local_ff (no degrade)."""
    monkeypatch.setattr(repo_ground.sys, "platform", "linux")
    mode = repo_ground.resolve_effective_headless_source_mode(_Args())
    assert mode == "local_ff"


def test_resolve_effective_headless_source_mode_ios_implicit_default_degrades(monkeypatch):
    """On iOS: the implicit local_ff default is degraded to local_current with a log hint."""
    monkeypatch.setattr(repo_ground.sys, "platform", "ios")
    logs = []
    mode = repo_ground.resolve_effective_headless_source_mode(_Args(), log=logs.append)
    assert mode == "local_current"
    assert logs, "a log hint must be emitted on iOS implicit degrade"
    assert any("ios" in m.lower() for m in logs), logs
    assert any("local_ff" in m or "fast-forward" in m.lower() for m in logs), logs


def test_headless_ios_implicit_default_validates_before_degrade(monkeypatch):
    """The control-plane validator still runs before the iOS degrade path.

    A contradictory explicit combination (local-ff + plan-only) is rejected with
    exit 2 even on iOS — the validator sees the *pre-degrade* canonical mode, so
    the control plane never fails open.
    """
    monkeypatch.setattr(repo_ground.sys, "platform", "ios")
    monkeypatch.setattr(sys, "argv", ["repo_ground.py", "--headless", "--source-mode", "local-ff", "--plan-only"])
    with pytest.raises(SystemExit) as exc:
        repo_ground.main_cli()
    assert exc.value.code == 2


def test_resolve_headless_source_mode_mapping():
    r = repo_ground.resolve_headless_source_mode
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
    ["repo_ground.py", "--source-mode", "local-current", "--pre-pull", "--headless"],
    ["repo_ground.py", "--source-mode", "local-ff", "--no-pre-pull", "--headless"],
    ["repo_ground.py", "--source-mode", "remote-snapshot", "--pre-pull", "--headless"],
])
def test_headless_source_mode_pre_pull_conflicts(monkeypatch, argv):
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit) as exc:
        repo_ground.main_cli()
    assert exc.value.code == 2


@pytest.mark.parametrize("argv", [
    # local-ff + plan-only: local-ff would mutate, plan-only forbids mutation.
    ["repo_ground.py", "--source-mode", "local-ff", "--plan-only", "--headless"],
    # remote-ref without remote-snapshot.
    ["repo_ground.py", "--remote-ref", "origin/main", "--headless"],
    ["repo_ground.py", "--source-mode", "local-current", "--remote-ref", "origin/main", "--headless"],
    ["repo_ground.py", "--source-mode", "local-ff", "--remote-ref", "origin/main", "--headless"],
    # explicit non-default policy without remote-snapshot.
    ["repo_ground.py", "--remote-ref-policy", "default-branch", "--headless"],
])
def test_headless_source_mode_control_plane_conflicts(monkeypatch, argv):
    """The central control plane rejects contradictory headless invocations (exit 2).

    Validation runs before hub detection / any remote git access, so no network
    call happens: resolve_remote_ref / materialize_remote_snapshot are patched to
    blow up if reached.
    """
    def _boom(*a, **k):
        raise AssertionError("no remote git access on a local validation failure")

    monkeypatch.setattr(repo_ground, "resolve_remote_ref", _boom)
    monkeypatch.setattr(repo_ground, "materialize_remote_snapshot", _boom)
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit) as exc:
        repo_ground.main_cli()
    assert exc.value.code == 2


def test_repo_ground_falls_closed_when_service_validator_unavailable(monkeypatch):
    """If the service package cannot be imported, repoLens must not fail open.

    It ships a local fallback validator with the same source-mode rules, so a
    contradictory request (here: local_ff + plan_only) is still rejected even
    when ``merger.repoground.service.source_acquisition`` is unimportable.
    """
    import importlib

    # Block both import spellings so a reloaded repo_ground takes its ImportError
    # fallback branch instead of importing the real service validator.
    monkeypatch.setitem(sys.modules, "merger.repoground.service.source_acquisition", None)
    monkeypatch.setitem(sys.modules, "repoground.service.source_acquisition", None)
    try:
        importlib.reload(repo_ground)
        # The fallback must be a real callable — never None (that would fail open).
        assert repo_ground.validate_source_mode_request is not None
        with pytest.raises(repo_ground.SourceModeConflictError):
            repo_ground.validate_source_mode_request(
                repo_source_mode="local_ff",
                pre_pull=None,
                plan_only=True,
                remote_ref=None,
                remote_ref_policy=None,
            )
        # Unknown modes are rejected too, not silently passed through.
        with pytest.raises(repo_ground.SourceModeConflictError):
            repo_ground.validate_source_mode_request(
                repo_source_mode="wat",
                pre_pull=None,
                plan_only=False,
                remote_ref=None,
                remote_ref_policy=None,
            )
    finally:
        # Restore the real service import for the rest of the suite.
        sys.modules.pop("merger.repoground.service.source_acquisition", None)
        sys.modules.pop("repoground.service.source_acquisition", None)
        importlib.reload(repo_ground)


# --- resolve_pre_pull_switch_value helper -----------------------------------

def test_resolve_pre_pull_switch_value_none_returns_true():
    """Absent switch defaults to True (matches the documented pre_pull default)."""
    assert repo_ground.resolve_pre_pull_switch_value(None) is True


def test_resolve_pre_pull_switch_value_switch_on():
    class FakeSwitch:
        value = True
    assert repo_ground.resolve_pre_pull_switch_value(FakeSwitch()) is True


def test_resolve_pre_pull_switch_value_switch_off():
    class FakeSwitch:
        value = False
    assert repo_ground.resolve_pre_pull_switch_value(FakeSwitch()) is False


# ---------------------------------------------------------------------------
# iOS / Pythonista capability gate (no git subprocesses)
# ---------------------------------------------------------------------------
#
# Pythonista on iOS cannot spawn subprocesses, so every git-backed feature
# (pre-pull, source-mode local-ff, remote-snapshot) must be gated off *before*
# the subprocess path is reached. These tests pin that behaviour and prove the
# non-iOS semantics are untouched. ``sys.platform`` is patched per-test so the
# gate is exercised deterministically on any host.

def _boom(*args, **kwargs):
    raise AssertionError("git subprocess path must not be reached on iOS")


# --- capability primitives --------------------------------------------------

def test_is_ios_runtime_true_on_ios(monkeypatch):
    monkeypatch.setattr(repo_ground.sys, "platform", "ios")
    assert repo_ground.is_ios_runtime() is True
    assert repo_ground.git_subprocesses_supported() is False


def test_is_ios_runtime_false_off_ios(monkeypatch):
    monkeypatch.setattr(repo_ground.sys, "platform", "linux")
    assert repo_ground.is_ios_runtime() is False
    assert repo_ground.git_subprocesses_supported() is True


def test_git_subprocess_unavailable_message_mentions_feature_and_cause():
    msg = repo_ground.git_subprocess_unavailable_message("--pre-pull")
    assert "--pre-pull" in msg
    assert "subprocess" in msg.lower()
    assert "ios" in msg.lower()


# --- 7.1 non-iOS is unchanged ----------------------------------------------

def test_resolve_effective_pre_pull_off_ios_preserves_base_rule(monkeypatch):
    monkeypatch.setattr(repo_ground.sys, "platform", "linux")
    # Default (switch on, not plan-only) keeps the desktop pre-pull behaviour.
    assert repo_ground.resolve_effective_pre_pull(True, False) is True
    # plan_only still forces pre-pull off, exactly as before.
    assert repo_ground.resolve_effective_pre_pull(True, True) is False
    # Explicitly disabled stays disabled.
    assert repo_ground.resolve_effective_pre_pull(False, False) is False


def test_resolve_effective_pre_pull_off_ios_emits_no_hint(monkeypatch):
    monkeypatch.setattr(repo_ground.sys, "platform", "linux")
    logs = []
    assert repo_ground.resolve_effective_pre_pull(True, False, log=logs.append) is True
    assert logs == []


# --- 7.2 iOS UI/default: pre-pull never reaches the subprocess path ---------

def test_resolve_effective_pre_pull_ios_forces_false_with_hint(monkeypatch):
    monkeypatch.setattr(repo_ground.sys, "platform", "ios")
    logs = []
    notes = []
    # Even an explicitly-on switch (or a stored pre_pull=true default) → False.
    assert repo_ground.resolve_effective_pre_pull(
        True, False, log=logs.append, notify=notes.append
    ) is False
    assert any("ios" in m.lower() for m in logs), logs
    assert notes, "a HUD hint should be emitted on iOS"


def test_ios_ui_chokepoint_never_calls_pre_pull(monkeypatch):
    """Mirror the UI guard (``if effective: run_pre_pull_two_phase(...)``): on iOS
    the resolver returns False, so the git subprocess path is never reached."""
    monkeypatch.setattr(repo_ground.sys, "platform", "ios")
    monkeypatch.setattr(repo_ground, "run_pre_pull_two_phase", _boom)
    logs = []
    effective = repo_ground.resolve_effective_pre_pull(True, False, log=logs.append)
    if effective:  # never true on iOS — guards against a regression
        repo_ground.run_pre_pull_two_phase([Path("/hub/x")], log=print)
    assert effective is False
    assert any("ios" in m.lower() for m in logs)


def test_ios_ui_plan_only_reason_unchanged(monkeypatch):
    """plan_only — not the iOS gate — is why pre-pull is off under plan_only, so
    no iOS hint is emitted (effective is already False before the gate runs)."""
    monkeypatch.setattr(repo_ground.sys, "platform", "ios")
    logs = []
    assert repo_ground.resolve_effective_pre_pull(True, True, log=logs.append) is False
    assert logs == [], logs


# --- 7.3 / 7.4 / 7.5 iOS headless: explicit git features rejected early -----

@pytest.fixture
def ios_headless_no_git(monkeypatch):
    """iOS headless with every git/remote/hub entrypoint armed to explode, so a
    SystemExit proves main_cli bailed out before reaching any of them."""
    monkeypatch.setattr(repo_ground.sys, "platform", "ios")
    monkeypatch.setattr(repo_ground, "run_pre_pull_two_phase", _boom)
    monkeypatch.setattr(repo_ground, "resolve_remote_ref", _boom)
    monkeypatch.setattr(repo_ground, "materialize_remote_snapshot", _boom)
    monkeypatch.setattr(repo_ground, "detect_hub_dir", _boom)
    return monkeypatch


def test_headless_ios_explicit_pre_pull_rejected(ios_headless_no_git, capsys):
    ios_headless_no_git.setattr(sys, "argv", ["repo_ground.py", "--headless", "--pre-pull"])
    with pytest.raises(SystemExit) as exc:
        repo_ground.main_cli()
    assert exc.value.code == 2
    err = capsys.readouterr().err.lower()
    assert "ios" in err or "subprocess" in err


def test_headless_ios_local_ff_rejected(ios_headless_no_git, capsys):
    ios_headless_no_git.setattr(
        sys, "argv", ["repo_ground.py", "--headless", "--source-mode", "local-ff"]
    )
    with pytest.raises(SystemExit) as exc:
        repo_ground.main_cli()
    assert exc.value.code == 2
    err = capsys.readouterr().err.lower()
    assert "ios" in err or "subprocess" in err


def test_headless_ios_remote_snapshot_rejected(ios_headless_no_git, capsys):
    ios_headless_no_git.setattr(
        sys, "argv", ["repo_ground.py", "--headless", "--source-mode", "remote-snapshot"]
    )
    with pytest.raises(SystemExit) as exc:
        repo_ground.main_cli()
    assert exc.value.code == 2
    err = capsys.readouterr().err.lower()
    assert "ios" in err or "subprocess" in err


# --- iOS headless implicit default: degrade to local scan, never crash ------

def test_headless_ios_implicit_default_degrades_to_local_scan(monkeypatch, tmp_path, capsys):
    """A plain ``repo_ground.py --headless`` on iOS (no flags) resolves to local_ff;
    it must degrade to a local scan instead of crashing in run_pre_pull_two_phase."""
    monkeypatch.setattr(repo_ground.sys, "platform", "ios")
    monkeypatch.setattr(repo_ground, "run_pre_pull_two_phase", _boom)
    monkeypatch.setattr(repo_ground, "detect_hub_dir", lambda *a, **k: tmp_path)

    class _ScanReached(Exception):
        pass

    def _fake_scan(*a, **k):
        raise _ScanReached()

    monkeypatch.setattr(repo_ground, "scan_repo", _fake_scan)
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(sys, "argv", ["repo_ground.py", "--headless", str(repo)])

    # Reaches the local scan (no SystemExit, no _boom) → degrade worked.
    with pytest.raises(_ScanReached):
        repo_ground.main_cli()
    out = capsys.readouterr().out.lower()
    assert "ios" in out  # the degrade hint was printed before scanning
