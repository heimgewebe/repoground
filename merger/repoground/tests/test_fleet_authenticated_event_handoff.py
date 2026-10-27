"""Publisher-authenticated provider reads feeding the existing event outbox."""
from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from merger.repoground.core.event_handoff import read_event_receipt
from merger.repoground.tests.test_agent_evidence_pack import (
    manifest, seeded_repo,
)

PUBLISHER = Path(__file__).resolve().parents[3] / "scripts/ops/repoground-publish-fleet"


def module():
    name = "repoground_fleet_authenticated_event_test"
    loader = importlib.machinery.SourceFileLoader(name, str(PUBLISHER))
    spec = importlib.util.spec_from_loader(name, loader)
    assert spec is not None
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[name] = loaded
    loader.exec_module(loaded)
    return loaded


def checked_setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    m = module()
    repo, base, head = seeded_repo(tmp_path)
    bundle = manifest(tmp_path, head)
    monkeypatch.setattr(m, "STATE_ROOT", tmp_path / "fleet-state")
    entry = SimpleNamespace(owner="heimgewebe", repo="demorepo")
    stamp = int(time.time()) - 300
    stamp_ci = int(time.time()) - 90

    def iso(n: int) -> str:
        return datetime.fromtimestamp(n, tz=timezone.utc).isoformat().replace(
            "+00:00", "Z"
        )

    values = {
        "user": {"login": "fixture-login", "id": 456},
        "commit": {
            "sha": head,
            "parents": [{"sha": base}],
            "committer": {"date": iso(stamp)},
        },
        "checks": {
            "total_count": 1,
            "check_runs": [{
                "id": 123456, "head_sha": head,
                "status": "completed", "conclusion": "success",
                "completed_at": iso(stamp_ci),
            }],
        },
    }

    def fake_api(endpoint: str):
        if endpoint == "/user":
            return values["user"], "c" * 64
        if endpoint.endswith("/git/commits/" + head):
            return values["commit"], "a" * 64
        if "/check-runs?" in endpoint:
            return values["checks"], "b" * 64
        raise AssertionError("unexpected authenticated read: " + endpoint)

    monkeypatch.setattr(m, "_github_event_api_get", fake_api)
    return m, entry, repo, base, head, bundle, values


def emit(m, entry, repo, head, bundle):
    return m._authenticated_fleet_event_handoff(
        entry, source_sha=head, source_wt=repo, manifest_path=str(bundle),
    )


def outbox(m, entry):
    return (m.STATE_ROOT / "authenticated-event-outbox"
            / f"{entry.owner}__{entry.repo}")


def test_verified_git_and_ci_produce_two_bound_receipts_and_deduplicate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    m, entry, repo, base, head, bundle, _values = checked_setup(tmp_path, monkeypatch)
    first = emit(m, entry, repo, head, bundle)
    assert first["status"] == "ok"
    assert [row["kind"] for row in first["events"]] == ["git.commit", "ci.completed"]
    assert [row["status"] for row in first["events"]] == ["published", "published"]
    assert all(row["provider_authority"].startswith("authenticated_github") for row in first["events"])
    assert all(row["source_revision"] == head for row in first["events"])
    assert all(row["receipt_sha256"] for row in first["events"])
    assert all(row["bundle_manifest_sha256"] for row in first["events"])
    saved = read_event_receipt(outbox_root=outbox(m, entry), event_key=first["events"][1]["event_key"])
    assert saved["read_only"] is True
    assert saved["receipt"]["event"]["check_id"] == "123456"
    assert saved["receipt"]["evidence_pack"]["revision"]["base"] == base
    assert saved["receipt"]["evidence_pack"]["revision"]["target"] == head
    # The deterministic adapter itself never upgrades caller assertions to
    # provider-authenticated claims; the separate publisher proof does that.
    assert saved["receipt"]["input_authority"] == "caller_assertion_not_verified_remote_event"
    before = {p.name: p.read_bytes() for p in outbox(m, entry).glob("event-*.json")}
    second = emit(m, entry, repo, head, bundle)
    assert [row["status"] for row in second["events"]] == ["deduplicated", "deduplicated"]
    assert {p.name: p.read_bytes() for p in outbox(m, entry).glob("event-*.json")} == before


def test_changed_check_conclusion_same_provider_id_conflicts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    m, entry, repo, _base, head, bundle, data = checked_setup(tmp_path, monkeypatch)
    emit(m, entry, repo, head, bundle)
    data["checks"]["check_runs"][0]["conclusion"] = "failure"
    blocked = m._attempt_authenticated_fleet_handoff(
        entry, source_sha=head, source_wt=repo, manifest_path=str(bundle),
    )
    assert blocked["status"] == "blocked"
    assert "event_identity_reused_with_new_payload" in blocked["reason"]
    assert len(list(outbox(m, entry).glob("event-*.json"))) == 2


def test_mismatched_commit_identity_creates_no_outbox(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    m, entry, repo, _base, head, bundle, data = checked_setup(tmp_path, monkeypatch)
    data["commit"]["sha"] = "0" * 40
    blocked = m._attempt_authenticated_fleet_handoff(
        entry, source_sha=head, source_wt=repo, manifest_path=str(bundle),
    )
    assert blocked == {"status": "blocked", "reason": "github_commit_source_identity_mismatch"}
    assert not outbox(m, entry).exists()


def test_mismatched_check_run_head_is_never_ci_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    m, entry, repo, _base, head, bundle, data = checked_setup(tmp_path, monkeypatch)
    data["checks"]["check_runs"][0]["head_sha"] = "f" * 40
    blocked = m._attempt_authenticated_fleet_handoff(
        entry, source_sha=head, source_wt=repo, manifest_path=str(bundle),
    )
    assert blocked["status"] == "blocked"
    assert blocked["reason"] == "github_check_run_source_identity_mismatch"
    stored = sorted(outbox(m, entry).glob("event-*.json"))
    assert len(stored) == 1
    assert json.loads(stored[0].read_text())["event"]["event_type"] == "git.commit"


def test_tampering_saved_evidence_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    m, entry, repo, _base, head, bundle, _data = checked_setup(tmp_path, monkeypatch)
    emit(m, entry, repo, head, bundle)
    saved = next(p for p in outbox(m, entry).glob("event-*.json")
                 if json.loads(p.read_text())["event"]["event_type"] == "git.commit")
    original = json.loads(saved.read_text())
    original["evidence_pack"]["revision"]["base"] = "0" * 40
    saved.write_text(json.dumps(original))
    blocked = m._attempt_authenticated_fleet_handoff(
        entry, source_sha=head, source_wt=repo, manifest_path=str(bundle),
    )
    assert blocked["status"] == "blocked"
    assert "integrity_failure" in blocked["reason"]


def test_outbox_capacity_blocks_without_deleting_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    m, entry, repo, _base, head, bundle, _data = checked_setup(tmp_path, monkeypatch)
    monkeypatch.setattr(m, "AUTH_EVENT_MAX_RECEIPTS", 0)
    blocked = m._attempt_authenticated_fleet_handoff(
        entry, source_sha=head, source_wt=repo, manifest_path=str(bundle),
    )
    assert blocked["status"] == "blocked"
    assert "capacity_requires_operator_retention" in blocked["reason"]
    assert not list(outbox(m, entry).glob("event-*.json"))


def test_gh_api_read_failure_never_trusted_and_no_secret_leaks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    m = module()

    def fail_run(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 1, b"", b"Authorization: bearer confidential")

    monkeypatch.setattr(m.subprocess, "run", fail_run)
    with pytest.raises(RuntimeError, match="authenticated_github_rest_read_failed") as exc:
        m._github_event_api_get("/repos/heimgewebe/demorepo/git/commits/" + "a" * 40)
    assert "confidential" not in str(exc.value)


def test_invalid_authenticated_time_rejected() -> None:
    m = module()
    with pytest.raises(RuntimeError, match="github_event_time"):
        m._github_event_unix("2026-10-27T18:00:00")
    with pytest.raises(RuntimeError, match="github_event_time"):
        m._github_event_unix("not-a-date")


def test_isolated_runtime_bootstraps_trusted_repo_modules(
    tmp_path: Path,
) -> None:
    """The managed Fleet launcher uses python -I, which drops cwd and PYTHONPATH."""
    script = (
        "import importlib.machinery, importlib.util, sys\n"
        f"script = {str(PUBLISHER)!r}\n"
        "loader = importlib.machinery.SourceFileLoader('fleet_isolated_probe', script)\n"
        "spec = importlib.util.spec_from_loader('fleet_isolated_probe', loader)\n"
        "assert spec is not None\n"
        "module = importlib.util.module_from_spec(spec)\n"
        "sys.modules['fleet_isolated_probe'] = module\n"
        "loader.exec_module(module)\n"
        "from merger.repoground.core.event_handoff import publish_event\n"
        "assert callable(publish_event)\n"
        "print('isolated_module_import_pass')\n"
    )
    proc = subprocess.run(
        [sys.executable, "-I", "-B", "-c", script],
        cwd=tmp_path, check=False, capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "isolated_module_import_pass"


def test_new_manifest_generation_never_relabels_old_receipts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    m, entry, repo, _base, head, manifest_path, _data = checked_setup(
        tmp_path, monkeypatch
    )
    first = emit(m, entry, repo, head, manifest_path)
    assert first["status"] == "ok"
    old = {row["event_key"]: row for row in first["events"]}
    current = json.loads(manifest_path.read_text(encoding="utf-8"))
    current["run_id"] = "same_revision_republished_new_bundle_generation"
    manifest_path.write_text(json.dumps(current), encoding="utf-8")
    second = emit(m, entry, repo, head, manifest_path)
    assert second["status"] == "ok"
    assert all(row["status"] == "deduplicated" for row in second["events"])
    for row in second["events"]:
        previous = old[row["event_key"]]
        assert row["receipt_sha256"] == previous["receipt_sha256"]
        assert row["bundle_manifest_sha256"] == previous["bundle_manifest_sha256"]
        assert row["observed_manifest_sha256"] != previous["bundle_manifest_sha256"]
        assert row["bundle_generation_binding"] == "existing_receipt_generation"
        readback = read_event_receipt(
            outbox_root=outbox(m, entry), event_key=row["event_key"],
        )
        assert (
            readback["receipt"]["evidence_pack"]["bundle"]["manifest_sha256"]
            == row["bundle_manifest_sha256"]
        )


def test_anonymous_or_invalid_identity_fails_before_event_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    m, entry, repo, _base, head, bundle, data = checked_setup(
        tmp_path, monkeypatch
    )
    data["user"] = {"login": "", "id": 0}
    result = m._attempt_authenticated_fleet_handoff(
        entry, source_sha=head, source_wt=repo, manifest_path=str(bundle),
    )
    assert result["status"] == "blocked"
    assert result["reason"] == "authenticated_github_principal_invalid"
    assert not outbox(m, entry).exists()


def test_unchanged_dirty_checkout_prunes_previous_clean_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Hourly unchanged polls must not accumulate disposable full worktrees."""
    m = module()
    repo, _base, head = seeded_repo(tmp_path)
    entry = SimpleNamespace(
        owner="heimgewebe", repo="demorepo",
        key="heimgewebe/demorepo", path=repo,
    )
    monkeypatch.setattr(m, "SOURCE_ROOT", tmp_path / "managed-sources")
    monkeypatch.setattr(m, "STATE_ROOT", tmp_path / "managed-fleet-state")
    canonical = m.ensure_source_worktree(entry, "main", head)
    # Never reset or delete the canonical source with valuable dirty data.
    dirty = canonical / "operator-untracked.txt"
    dirty.write_text("preserve me", encoding="utf-8")
    monkeypatch.setattr(
        m, "_attempt_authenticated_fleet_handoff",
        lambda *args, **kwargs: {"status": "blocked", "reason": "api_unavailable"},
    )

    def unchanged() -> dict:
        return m._unchanged_authenticated_event_with_prune(
            entry, ref_segment="main", source_sha=head,
            manifest_path=None,
        )

    first = unchanged()
    assert first["authenticated_events"]["status"] == "blocked"
    first_recoveries = list(m.SOURCE_ROOT.glob("*--recovery-*"))
    assert len(first_recoveries) == 1

    second = unchanged()
    assert second["authenticated_events"]["status"] == "blocked"
    assert second["prune_failed"] is False
    assert first_recoveries[0].exists() is False
    current_recoveries = list(m.SOURCE_ROOT.glob("*--recovery-*"))
    assert len(current_recoveries) == 1
    assert current_recoveries[0] != first_recoveries[0]
    assert str(first_recoveries[0]) in second["source_worktree_prune"]["removed"]
    assert canonical.exists() and dirty.read_text() == "preserve me"
    assert any(
        row["path"] == str(canonical)
        for row in second["source_worktree_prune"]["preserved"]
    )
