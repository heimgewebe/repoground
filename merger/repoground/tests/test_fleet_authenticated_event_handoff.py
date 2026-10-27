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
