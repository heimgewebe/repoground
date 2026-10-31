"""Fast level-triggered RepoGround fleet reconciliation, not a second publisher."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from merger.repoground.tests.test_fleet_runtime import load_publisher


@pytest.fixture
def observed_fleet(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    module = load_publisher()
    source = ["a" * 40]
    generator = ["b" * 64]
    entry = module.RepoEntry(
        key="heimgewebe/demo",
        owner="heimgewebe",
        repo="demo",
        path=tmp_path / "demo",
        remote="git@github.com:heimgewebe/demo.git",
    )
    membership = module.FleetMembership(
        keys=(entry.key,),
        source_commit="c" * 40,
        source_ref="origin/main",
        source_path="fleet/repos.yml",
        content_sha256="d" * 64,
    )
    fingerprint, _ = module.build_fingerprint(
        source_sha=source[0],
        generator_inputs_sha=generator[0],
        publication_repository=module.publication_repository(entry),
        config=module.publication_config(entry),
    )
    monkeypatch.setattr(module, "discover", lambda: [entry])
    monkeypatch.setattr(
        module, "load_authoritative_fleet_membership", lambda: membership,
    )
    monkeypatch.setattr(
        module, "ensure_tool_worktree", lambda: ("e" * 40, generator[0]),
    )
    monkeypatch.setattr(
        module, "remote_head_for_entry",
        lambda _entry: ("origin/main", "main", source[0]),
    )
    monkeypatch.setattr(module, "load_state", lambda _path: {"fingerprint": fingerprint})
    return module, entry, source, generator


def test_fingerprint_probe_is_quiet_for_identical_publication(observed_fleet) -> None:
    module, entry, _source, _generator = observed_fleet
    result = module._pending_fleet_head_reconciliation()
    assert result["status"] == "ok"
    assert result["count"] == 1
    assert result["pending_repositories"] == []
    assert result["generator_commit"] == "e" * 40


def test_external_merge_is_detected_without_a_webhook(observed_fleet) -> None:
    module, entry, source, _generator = observed_fleet
    source[0] = "f" * 40
    assert module._pending_fleet_head_reconciliation()["pending_repositories"] == [
        entry.key
    ]


def test_generator_fingerprint_invalidates_unchanged_source(observed_fleet) -> None:
    module, entry, _source, generator = observed_fleet
    generator[0] = "1" * 64
    assert module._pending_fleet_head_reconciliation()["pending_repositories"] == [
        entry.key
    ]


def test_missing_authoritative_member_fails_instead_of_silently_skipping(
    observed_fleet, monkeypatch: pytest.MonkeyPatch,
) -> None:
    module, entry, _source, _generator = observed_fleet
    membership = module.FleetMembership(
        keys=(entry.key, "heimgewebe/missing"),
        source_commit="c" * 40,
        source_ref="origin/main",
        source_path="fleet/repos.yml",
        content_sha256="d" * 64,
    )
    monkeypatch.setattr(
        module, "load_authoritative_fleet_membership", lambda: membership,
    )
    result = module._pending_fleet_head_reconciliation()
    assert result["count"] == 2
    assert result["pending_repositories"] == []
    assert result["errors"] == [
        {"repo": "heimgewebe/missing", "reason": "fleet_member_checkout_missing"}
    ]



def test_one_remote_failure_preserves_healthy_pending_publication(
    observed_fleet, monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    module, healthy, source, _generator = observed_fleet
    source[0] = "f" * 40
    broken = module.RepoEntry(
        key="heimgewebe/unavailable",
        owner="heimgewebe", repo="unavailable", path=tmp_path / "unavailable",
        remote="git@github.com:heimgewebe/unavailable.git",
    )
    monkeypatch.setattr(module, "discover", lambda: [healthy, broken])
    monkeypatch.setattr(
        module, "load_authoritative_fleet_membership",
        lambda: module.FleetMembership(
            keys=(healthy.key, broken.key), source_commit="c" * 40,
            source_ref="origin/main", source_path="fleet/repos.yml",
            content_sha256="d" * 64,
        ),
    )

    def remote_head(entry):
        if entry.key == broken.key:
            raise RuntimeError("remote_access_unavailable")
        return "origin/main", "main", source[0]

    monkeypatch.setattr(module, "remote_head_for_entry", remote_head)
    closed: list[bool] = []
    targeted: list[list[str]] = []
    monkeypatch.setattr(
        module, "acquire_lock", lambda: SimpleNamespace(close=lambda: closed.append(True)),
    )
    monkeypatch.setattr(module, "log", lambda _message: None)

    def fake_main(argv: list[str]) -> int:
        assert closed == [True]
        targeted.append(argv)
        return 0

    monkeypatch.setattr(module, "main", fake_main)
    assert module.reconcile_fleet_heads(retention=3, limit=8) == 1
    assert targeted == [[
        "--if-changed", "--retention", "3", "--limit", "8",
        "--repo", healthy.key,
    ]]
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "partial"
    assert report["probe_errors"] == [
        {"repo": broken.key, "reason": "remote_access_unavailable"}
    ]


def test_only_missing_member_is_a_visible_retryable_failure(
    observed_fleet, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module, entry, _source, _generator = observed_fleet
    monkeypatch.setattr(
        module, "load_authoritative_fleet_membership",
        lambda: module.FleetMembership(
            keys=(entry.key, "heimgewebe/missing"), source_commit="c" * 40,
            source_ref="origin/main", source_path="fleet/repos.yml",
            content_sha256="d" * 64,
        ),
    )
    monkeypatch.setattr(
        module, "acquire_lock", lambda: SimpleNamespace(close=lambda: None),
    )
    assert module.reconcile_fleet_heads(retention=3, limit=8) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "error"
    assert result["published"] == 0
    assert result["pending_repositories"] == []
    assert result["errors"][0]["repo"] == "heimgewebe/missing"

def test_busy_fast_probe_is_deferred_without_any_remote_reads(
    observed_fleet, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module, _entry, _source, _generator = observed_fleet
    monkeypatch.setattr(module, "acquire_lock", lambda: None)
    monkeypatch.setattr(
        module, "_pending_fleet_head_reconciliation",
        lambda: (_ for _ in ()).throw(AssertionError("busy probe performed remote reads")),
    )
    assert module.main(["--reconcile-heads"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "busy"
    assert result["needs_retry"] is True
    assert result["mode"] == "head-reconcile"


def test_unchanged_probe_never_invokes_main_publisher(
    observed_fleet, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module, _entry, _source, _generator = observed_fleet
    closed: list[bool] = []
    monkeypatch.setattr(
        module, "acquire_lock", lambda: SimpleNamespace(close=lambda: closed.append(True)),
    )
    assert module.main(["--reconcile-heads", "--retention", "3", "--limit", "8"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "unchanged"
    assert payload["count"] == 1
    assert payload["published"] == 0
    assert closed == [True]


def test_changed_probe_calls_existing_targeted_publisher_after_unlock(
    observed_fleet, monkeypatch: pytest.MonkeyPatch,
) -> None:
    module, entry, source, _generator = observed_fleet
    source[0] = "f" * 40
    closed: list[bool] = []
    publisher_argv: list[list[str]] = []
    monkeypatch.setattr(
        module, "acquire_lock", lambda: SimpleNamespace(close=lambda: closed.append(True)),
    )
    monkeypatch.setattr(module, "log", lambda _message: None)

    def fake_main(argv: list[str]) -> int:
        assert closed == [True]
        publisher_argv.append(argv)
        return 0

    monkeypatch.setattr(module, "main", fake_main)
    assert module.reconcile_fleet_heads(retention=3, limit=8) == 0
    assert publisher_argv == [[
        "--if-changed", "--retention", "3", "--limit", "8",
        "--repo", entry.key,
    ]]


def test_probe_failure_produces_real_error_and_releases_lock(
    observed_fleet, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module, _entry, _source, _generator = observed_fleet
    closed: list[bool] = []
    monkeypatch.setattr(
        module, "acquire_lock", lambda: SimpleNamespace(close=lambda: closed.append(True)),
    )
    monkeypatch.setattr(
        module, "_pending_fleet_head_reconciliation",
        lambda: (_ for _ in ()).throw(RuntimeError("provider temporarily unavailable")),
    )
    assert module.reconcile_fleet_heads(retention=3, limit=8) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["phase"] == "head_probe"
    assert payload["status"] == "error"
    assert closed == [True]


@pytest.mark.parametrize("other", [
    ["--if-changed"],
    ["--inventory"],
    ["--repo", "heimgewebe/demo"],
    ["--force-republish"],
    ["--prune-current"],
])
def test_probe_refuses_mixed_modes(other: list[str]) -> None:
    module = load_publisher()
    with pytest.raises(SystemExit) as exc:
        module.main(["--reconcile-heads", *other])
    assert exc.value.code == 2


def test_monotonic_probe_timer_keeps_hourly_full_reconciliation() -> None:
    root = Path(__file__).resolve().parents[3] / "ops/systemd/repoground-fleet"
    cheap_service = (root / "repoground-publish-head-watch.service").read_text()
    cheap_timer = (root / "repoground-publish-head-watch.timer").read_text()
    full_service = (root / "repoground-publish-fleet-watch.service").read_text()
    full_timer = (root / "repoground-publish-fleet-watch.timer").read_text()
    assert "--reconcile-heads" in cheap_service
    assert "--if-changed" in full_service
    assert "OnUnitInactiveSec=90s" in cheap_timer
    assert "AccuracySec=5s" in cheap_timer
    assert "OnCalendar=hourly" in full_timer
    installer = (
        root.parents[2] / "scripts/ops/install_repoground_publish_fleet_runtime.sh"
    ).read_text()
    assert "systemctl --user stop repoground-publish-head-watch.service" in installer


def test_changed_head_reconcile_forwards_disabled_event_policy(
    observed_fleet, monkeypatch: pytest.MonkeyPatch,
) -> None:
    module, entry, source, _generator = observed_fleet
    source[0] = "f" * 40
    monkeypatch.setattr(
        module, "acquire_lock", lambda: SimpleNamespace(close=lambda: None),
    )
    monkeypatch.setattr(module, "log", lambda _message: None)
    calls = []
    monkeypatch.setattr(module, "main", lambda argv: calls.append(argv) or 0)
    assert module.reconcile_fleet_heads(
        retention=3, limit=8, authenticated_events_enabled=False,
    ) == 0
    assert calls == [[
        "--if-changed", "--retention", "3", "--no-authenticated-events",
        "--limit", "8", "--repo", entry.key,
    ]]


def test_head_watch_cli_accepts_disabled_event_policy(
    observed_fleet, monkeypatch: pytest.MonkeyPatch,
) -> None:
    module, _entry, _source, _generator = observed_fleet
    seen = []
    monkeypatch.setattr(
        module, "reconcile_fleet_heads",
        lambda **kwargs: seen.append(kwargs) or 0,
    )
    assert module.main(["--reconcile-heads", "--no-authenticated-events"]) == 0
    assert seen == [{
        "retention": 3, "limit": 0, "authenticated_events_enabled": False,
    }]
