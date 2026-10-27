"""Publisher-only Git/CI event handoff, dedup, clash and non-mutation tests."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest

from merger.repoground.core.event_handoff import (
    EventIdentityConflict,
    EventInputError,
    publish_event,
    read_event_receipt,
)
from merger.repoground.tests.test_agent_evidence_pack import seeded_repo, git, manifest


def event(base: str, head: str, *, kind: str = "git.commit", id: str = "push-123"):
    result = {
        "event_type": kind, "event_id": id,
        "repository": "heimgewebe/demorepo",
        "base_revision": base, "target_revision": head,
    }
    if kind == "ci.completed":
        result.update(check_id="test-123", ci_conclusion="failure")
    return result


def report_files(root: Path) -> list[Path]:
    return sorted(root.glob("event-*.json"))


def test_two_identical_git_events_produce_one_atomic_record(tmp_path):
    repo, base, head = seeded_repo(tmp_path)
    out = tmp_path / "publisher-outbox"
    item = event(base, head)
    first = publish_event(event=item, repo_root=repo, outbox_root=out)
    assert first["status"] == "published"
    assert len(report_files(out)) == 1
    path = report_files(out)[0]
    assert path.stat().st_mode & 0o077 == 0
    raw = path.read_bytes()
    saved = json.loads(raw)
    assert saved["event"] == item
    assert saved["input_authority"] == "caller_assertion_not_verified_remote_event"
    assert saved["consumer_handoff"]["automatic_agent_invocation"] is False
    assert saved["evidence_pack"]["revision"]["target"] == head
    assert saved["evidence_pack"]["changed_files"][0]["path"] == "alpha.py"
    assert saved["evidence_pack"]["mutation_boundary"]["writes"] == []
    assert saved["evidence_pack_sha256"] == hashlib.sha256(
        json.dumps(saved["evidence_pack"], ensure_ascii=False, sort_keys=True,
                   separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    again = publish_event(event=item, repo_root=repo, outbox_root=out)
    assert again["status"] == "deduplicated"
    assert path.read_bytes() == raw
    assert len(report_files(out)) == 1
    assert git(repo, "status", "--porcelain") == ""


def test_ci_event_is_a_claim_not_authoritative_ci_truth(tmp_path):
    repo, base, head = seeded_repo(tmp_path)
    out = tmp_path / "ci-events"
    ci = publish_event(event=event(base, head, kind="ci.completed"),
                       repo_root=repo, outbox_root=out,
                       bundle_manifest=manifest(tmp_path, base))
    assert ci["status"] == "published"
    receipt = ci["receipt"]
    assert receipt["event"]["ci_conclusion"] == "failure"
    assert receipt["consumer_handoff"]["use_case"] == "find-related-tests"
    assert "ci_conclusion_authenticity" in receipt["does_not_establish"]
    assert "test_sufficiency" in receipt["does_not_establish"]


def test_same_id_new_payload_is_a_conflict_not_reprocessed(tmp_path):
    repo, base, head = seeded_repo(tmp_path)
    out = tmp_path / "outbox"
    e = event(base, head)
    assert publish_event(event=e, repo_root=repo, outbox_root=out)["status"] == "published"
    changed = {**e, "base_revision": head, "target_revision": base}
    with pytest.raises(EventIdentityConflict, match="event_identity_reused"):
        publish_event(event=changed, repo_root=repo, outbox_root=out)
    assert len(report_files(out)) == 1


def test_invalid_inputs_fail_without_new_receipt(tmp_path):
    repo, base, head = seeded_repo(tmp_path)
    out = tmp_path / "outbox"
    bad = {**event(base, head), "event_id": "../../escape"}
    with pytest.raises(EventInputError):
        publish_event(event=bad, repo_root=repo, outbox_root=out)
    with pytest.raises(EventInputError, match="unsupported_event_fields"):
        publish_event(event={**event(base, head), "command": "rm -rf /"}, repo_root=repo, outbox_root=out)
    assert not out.exists()
    missing_commit = {**event(base, head), "target_revision": "0" * 40}
    result = publish_event(event=missing_commit, repo_root=repo, outbox_root=out)
    assert result["status"] == "blocked"
    assert not report_files(out)


def test_outbox_must_be_outside_checkout_and_symlink(tmp_path):
    repo, base, head = seeded_repo(tmp_path)
    with pytest.raises(EventInputError, match="overlap"):
        publish_event(event=event(base, head), repo_root=repo, outbox_root=repo / ".out")
    link = tmp_path / "out-link"
    actual = tmp_path / "real-out"
    actual.mkdir()
    link.symlink_to(actual, target_is_directory=True)
    with pytest.raises(EventInputError, match="symlink"):
        publish_event(event=event(base, head), repo_root=repo, outbox_root=link)


def test_parallel_redelivery_uses_one_receipt(tmp_path):
    repo, base, head = seeded_repo(tmp_path)
    out = tmp_path / "outbox"
    item = event(base, head)
    with ThreadPoolExecutor(max_workers=4) as pool:
        outcomes = list(pool.map(
            lambda _: publish_event(event=item, repo_root=repo, outbox_root=out),
            range(4),
        ))
    assert sorted(row["status"] for row in outcomes) == [
        "deduplicated", "deduplicated", "deduplicated", "published",
    ]
    assert len(report_files(out)) == 1


def test_cli_jsonl_backfill_is_bounded_and_deduplicated(tmp_path):
    repo, base, head = seeded_repo(tmp_path)
    out = tmp_path / "outbox"
    events = tmp_path / "batch.jsonl"
    payload = event(base, head)
    events.write_text("\n".join([
        json.dumps(payload),
        json.dumps(payload),
        json.dumps(event(base, head, kind="ci.completed", id="ci-456")),
    ]) + "\n", encoding="utf-8")
    script = Path(__file__).resolve().parents[3] / "scripts" / "repoground-event-handoff.py"
    cmd = [
        sys.executable, str(script),
        "--repo-root", str(repo), "--outbox-root", str(out),
        "--event-file", str(events), "--format", "jsonl", "--max-events", "3",
    ]
    first = subprocess.run(cmd, capture_output=True, text=True, check=True)
    result = json.loads(first.stdout)
    assert (result["published"], result["deduplicated"], result["blocked"]) == (2, 1, 0)
    assert len(report_files(out)) == 2
    second = json.loads(subprocess.run(cmd, capture_output=True, text=True, check=True).stdout)
    assert (second["published"], second["deduplicated"]) == (0, 3)
    assert len(report_files(out)) == 2

def test_cli_invalid_later_event_does_not_publish_earlier(tmp_path):
    repo, base, head = seeded_repo(tmp_path)
    out = tmp_path / "outbox"
    events = tmp_path / "invalid-batch.jsonl"
    events.write_text("\n".join([
        json.dumps(event(base, head)),
        json.dumps({**event(base, head, id="later"), "untrusted_command": "exec"}),
    ]) + "\n", encoding="utf-8")
    script = Path(__file__).resolve().parents[3] / "scripts" / "repoground-event-handoff.py"
    completed = subprocess.run(
        [sys.executable, str(script),
         "--repo-root", str(repo), "--outbox-root", str(out),
         "--event-file", str(events), "--format", "jsonl"],
        capture_output=True, text=True,
    )
    assert completed.returncode == 2
    assert "unsupported_event_fields" in completed.stderr
    assert not out.exists()


def test_read_only_event_receipt_is_exact_and_no_new_files(tmp_path):
    repo, base, head = seeded_repo(tmp_path)
    out = tmp_path / "outbox"
    published = publish_event(event=event(base, head), repo_root=repo, outbox_root=out)
    assert published["status"] == "published"
    prior = {p.name: p.read_bytes() for p in out.iterdir() if p.is_file()}
    result = read_event_receipt(outbox_root=out, event_key=published["event_key"])
    assert result["status"] == "available"
    assert result["read_only"] is True
    assert result["receipt"]["evidence_pack"]["revision"]["target"] == head
    assert result["receipt_sha256"] == hashlib.sha256(
        json.dumps(result["receipt"], sort_keys=True,
                   separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    assert {p.name: p.read_bytes() for p in out.iterdir() if p.is_file()} == prior
    script = Path(__file__).resolve().parents[3] / "scripts" / "repoground-event-handoff.py"
    command = [sys.executable, str(script), "--outbox-root", str(out),
               "--read-event-key", published["event_key"]]
    process = subprocess.run(command, capture_output=True, text=True, check=True)
    payload = json.loads(process.stdout)
    assert payload["receipt_sha256"] == result["receipt_sha256"]
    assert {p.name: p.read_bytes() for p in out.iterdir() if p.is_file()} == prior


def test_unavailable_event_read_does_not_create_outbox(tmp_path):
    out = tmp_path / "absent-outbox"
    result = read_event_receipt(outbox_root=out, event_key="f" * 64)
    assert result["status"] == "unavailable"
    assert not out.exists()
    with pytest.raises(EventInputError, match="invalid_event_key"):
        read_event_receipt(outbox_root=out, event_key="../passwd")


def test_receipt_tamper_event_identity_rejected_even_if_pack_digest_unchanged(tmp_path):
    repo, base, head = seeded_repo(tmp_path)
    out = tmp_path / "outbox"
    result = publish_event(event=event(base, head), repo_root=repo, outbox_root=out)
    path = Path(result["receipt_path"])
    data = json.loads(path.read_text(encoding="utf-8"))
    data["event"]["event_id"] = "tampered-event"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(EventInputError, match="event_key_mismatch"):
        read_event_receipt(outbox_root=out, event_key=result["event_key"])
