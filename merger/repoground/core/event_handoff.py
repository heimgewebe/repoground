"""Publisher-invoked, idempotent RepoGround Git/CI event evidence outbox.

This is an explicit write-side operation. It is not a daemon, Git hook,
background watcher, PR reviewer, patcher or build trigger. Readers never call it.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import tempfile
from collections.abc import Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from merger.repoground.core.agent_evidence_pack import build_evidence_pack

KIND = "repoground.publisher_event_handoff"
VERSION = 1
MAX_EVENT_BYTES = 8192
MAX_RECEIPT_BYTES = 96 * 1024
_EVENT_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._:@/-]{0,127}$")
_REPO_ID = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_ALLOWED_EVENTS = {"git.commit", "ci.completed"}

# Per authenticated publisher handoff only. No global cache or durable state:
# repeated CI check runs for one immutable source/manifest share the same pack.
_BATCH_EVIDENCE_PACKS: ContextVar[
    dict[tuple[str, str, str, str, str, int], dict[str, Any]] | None
] = ContextVar("repoground_event_evidence_packs", default=None)


@contextmanager
def reuse_event_evidence_packs():
    """Coalesce equal evidence builds in one publisher-authenticated event batch.

    Event identity, payload collisions, provider authenticity, receipt locking and
    per-event write/readback remain independently verified by publish_event.
    """
    token = _BATCH_EVIDENCE_PACKS.set({})
    try:
        yield
    finally:
        _BATCH_EVIDENCE_PACKS.reset(token)


_CI_CONCLUSIONS = {"success", "failure", "cancelled", "skipped", "timed_out", "neutral", "action_required"}
_FORBIDDEN_APPROVAL = ("approval", "merge", "patch", "review_verdict", "test_sufficiency")


class EventInputError(ValueError):
    """Malformed or unsafe explicit publisher event."""


class EventIdentityConflict(EventInputError):
    """An event identifier was previously bound to a different payload."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _validate_revision_fields(event: Mapping[str, Any]) -> None:
    for key in ("base_revision", "target_revision"):
        sha = event.get(key)
        if not isinstance(sha, str) or len(sha) != 40 or not re.fullmatch("[0-9a-f]{40}", sha):
            raise EventInputError("invalid_" + key)
    if event["base_revision"] == event["target_revision"]:
        raise EventInputError("empty_revision_range")


def _validate_event_kind_fields(event: Mapping[str, Any], kind: str) -> None:
    if kind == "ci.completed":
        check_id = event.get("check_id")
        conclusion = event.get("ci_conclusion")
        if not isinstance(check_id, str) or not _EVENT_ID.fullmatch(check_id):
            raise EventInputError("missing_ci_check_id")
        if not isinstance(conclusion, str) or conclusion not in _CI_CONCLUSIONS:
            raise EventInputError("invalid_ci_conclusion")
    elif "check_id" in event or "ci_conclusion" in event:
        raise EventInputError("ci_fields_require_ci_event")


def _validate_event_timing_fields(event: Mapping[str, Any]) -> None:
    time_fields = ("source_occurred_at_unix", "publisher_observed_at_unix")
    supplied = [name in event for name in time_fields]
    if any(supplied) and not all(supplied):
        raise EventInputError("event_timing_requires_both_fields")
    if all(supplied):
        for name in time_fields:
            when = event[name]
            if type(when) is not int or not 0 <= when <= (2**53 - 1):
                raise EventInputError("invalid_" + name)
        if event["publisher_observed_at_unix"] < event["source_occurred_at_unix"]:
            raise EventInputError("publisher_observed_before_source")


def _check_event(event: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(event, dict):
        raise EventInputError("event_must_be_object")
    unknown = set(event) - {
        "event_type", "event_id", "repository",
        "base_revision", "target_revision", "check_id", "ci_conclusion",
        "source_occurred_at_unix", "publisher_observed_at_unix",
    }
    if unknown:
        raise EventInputError("unsupported_event_fields")
    if len(_canonical(event)) > MAX_EVENT_BYTES:
        raise EventInputError("event_too_large")
    kind, event_id, repo = (
        event.get("event_type"), event.get("event_id"), event.get("repository")
    )
    if not isinstance(kind, str) or kind not in _ALLOWED_EVENTS:
        raise EventInputError("invalid_event_type")
    if not isinstance(event_id, str) or _EVENT_ID.fullmatch(event_id) is None:
        raise EventInputError("invalid_event_id")
    if not isinstance(repo, str) or _REPO_ID.fullmatch(repo) is None:
        raise EventInputError("invalid_repository")
    _validate_revision_fields(event)
    _validate_event_kind_fields(event, kind)
    _validate_event_timing_fields(event)
    return dict(event)


def _delivery_timing(event: Mapping[str, Any]) -> dict[str, Any]:
    if "source_occurred_at_unix" not in event:
        return {
            "status": "unknown", "lag_seconds": None,
            "basis": "not_reported_by_publisher",
        }
    return {
        "status": "reported",
        "lag_seconds": (
            event["publisher_observed_at_unix"] - event["source_occurred_at_unix"]
        ),
        "basis": "caller_supplied_unverified_timestamps",
    }


def _bundle_revision_alignment(pack: Mapping[str, Any], event: Mapping[str, Any]) -> str:
    bundle = pack.get("bundle")
    if not isinstance(bundle, dict) or bundle.get("status") != "available":
        return "bundle_unavailable"
    source_commit = bundle.get("source_commit")
    if source_commit == event["target_revision"]:
        return "matches_target_revision"
    if source_commit == event["base_revision"]:
        return "matches_base_revision_only"
    return "bundle_revision_not_in_range_or_ambiguous"


def _target(outbox_root: Path, repo_root: Path) -> Path:
    supplied = outbox_root.expanduser().absolute()
    if supplied.is_symlink():
        raise EventInputError("outbox_root_symlink")
    root = supplied.resolve(strict=False)
    if root == repo_root or root in repo_root.parents or repo_root in root.parents:
        raise EventInputError("outbox_must_not_overlap_repository")
    if root.exists() and not root.is_dir():
        raise EventInputError("outbox_not_directory")
    return root


def _read_receipt(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_RECEIPT_BYTES:
        raise EventInputError("outbox_receipt_unsafe")
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeError, ValueError, OSError):
        raise EventInputError("outbox_receipt_invalid") from None
    if not isinstance(receipt, dict) or receipt.get("kind") != KIND or receipt.get("version") != VERSION:
        raise EventInputError("outbox_receipt_wrong_contract")
    embedded = receipt.get("evidence_pack")
    digest = receipt.get("evidence_pack_sha256")
    if not isinstance(embedded, dict) or hashlib.sha256(_canonical(embedded)).hexdigest() != digest:
        raise EventInputError("outbox_receipt_integrity_failure")
    event = _check_event(receipt.get("event"))
    identity = {key: event[key] for key in ("event_type", "event_id", "repository")}
    if receipt.get("event_key") != hashlib.sha256(_canonical(identity)).hexdigest():
        raise EventInputError("outbox_receipt_event_key_mismatch")
    if receipt.get("event_payload_sha256") != hashlib.sha256(_canonical(event)).hexdigest():
        raise EventInputError("outbox_receipt_event_payload_mismatch")
    revision = embedded.get("revision")
    if not isinstance(revision, dict) or any(
        revision.get(field) != event[source]
        for field, source in (("base", "base_revision"), ("target", "target_revision"))
    ):
        raise EventInputError("outbox_receipt_revision_mismatch")
    if (
        "delivery_timing" in receipt
        and receipt["delivery_timing"] != _delivery_timing(event)
    ):
        raise EventInputError("outbox_receipt_timing_mismatch")
    if (
        "bundle_revision_alignment" in receipt
        and receipt["bundle_revision_alignment"] != _bundle_revision_alignment(embedded, event)
    ):
        raise EventInputError("outbox_receipt_bundle_alignment_mismatch")
    return receipt


def read_event_receipt(
    *, outbox_root: str | Path, event_key: str
) -> dict[str, Any]:
    """Bounded evidence consumer, never creates outbox, snapshot or lockfiles.

    An event key is a SHA-256 from an authorized publisher receipt. It cannot
    select a path outside the outbox; no event identifiers become path strings.
    """
    if not isinstance(event_key, str) or re.fullmatch(r"[0-9a-f]{64}", event_key) is None:
        raise EventInputError("invalid_event_key")
    root = Path(outbox_root).expanduser().absolute()
    if root.is_symlink() or not root.is_dir():
        return {"status": "unavailable", "reason": "outbox_not_available"}
    path = root / f"event-{event_key}.json"
    if not path.exists() and not path.is_symlink():
        return {"status": "unavailable", "reason": "event_not_found", "event_key": event_key}
    receipt = _read_receipt(path)
    if receipt.get("event_key") != event_key:
        raise EventInputError("outbox_receipt_event_key_mismatch")
    return {
        "kind": KIND, "version": VERSION, "status": "available",
        "event_key": event_key, "receipt": receipt,
        "receipt_sha256": hashlib.sha256(_canonical(receipt)).hexdigest(),
        "read_only": True, "does_not_establish": [
            "publisher_authenticity", "github_event_authenticity",
            "ci_conclusion_authenticity", "current_git_freshness",
            "review_verdict", "test_sufficiency", "merge_authorization",
        ],
    }



def _event_evidence_pack(
    item: Mapping[str, Any],
    repo: Path,
    bundle_manifest: str | Path | None,
    use_case: str,
    context_budget_tokens: int,
) -> dict[str, Any]:
    """Reuse an immutable-revision evidence pack only within a publisher batch."""
    batch = _BATCH_EVIDENCE_PACKS.get()
    # The authenticated publisher pins one manifest and source worktree per batch.
    cache_key = (
        str(repo), item["base_revision"], item["target_revision"],
        str(bundle_manifest), use_case, context_budget_tokens,
    )
    cached = batch.get(cache_key) if batch is not None else None
    if cached is not None:
        return cached

    pack = build_evidence_pack(
        repo_root=repo,
        base_revision=item["base_revision"],
        target_revision=item["target_revision"],
        bundle_manifest=bundle_manifest,
        use_case=use_case,
        context_budget_tokens=context_budget_tokens,
    )
    if batch is not None and pack.get("status") != "invalid":
        batch[cache_key] = pack
    return pack


def publish_event(
    *,
    event: Mapping[str, Any],
    repo_root: str | Path,
    outbox_root: str | Path,
    bundle_manifest: str | Path | None = None,
    context_budget_tokens: int = 1200,
    max_records: int = 1,
) -> dict[str, Any]:
    """Persist exactly one completed evidence handoff per source event identity.

    Caller is the *already authorized* publisher, never a retrieval/client path.
    Global flock covers checks, evidence build and atomic JSON publication.
    An existing identical source event is read back without rebuilding anything.
    """
    item = _check_event(event)
    if type(max_records) is not int or max_records != 1:
        raise EventInputError("one_event_per_invocation")
    repo = Path(repo_root).expanduser().resolve()
    if not repo.is_dir():
        raise EventInputError("repository_not_found")
    out = _target(Path(outbox_root), repo)
    # Two authenticated publishers can arrive before this outbox exists. The
    # first creator must not make the second fail before the shared flock.
    out.mkdir(parents=True, mode=0o700, exist_ok=True)
    if out.is_symlink():
        raise EventInputError("outbox_root_symlink")
    key_material = {
        "event_type": item["event_type"],
        "event_id": item["event_id"],
        "repository": item["repository"],
    }
    key = hashlib.sha256(_canonical(key_material)).hexdigest()
    input_sha = hashlib.sha256(_canonical(item)).hexdigest()
    path = out / f"event-{key}.json"

    # A single bounded file lock reuses the operator's outbox as the authority:
    # no job database, out-of-band registry or second queue is introduced.
    lock_descriptor = os.open(out / ".handoff.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(lock_descriptor, "rb") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if path.exists() or path.is_symlink():
                receipt = _read_receipt(path)
                if receipt.get("event_key") != key or receipt.get("event_payload_sha256") != input_sha:
                    raise EventIdentityConflict("event_identity_reused_with_new_payload")
                return {"status": "deduplicated", "receipt_path": str(path),
                        "event_key": key, "receipt": receipt}
            use_case = "explain-change" if item["event_type"] == "git.commit" else "find-related-tests"
            pack = _event_evidence_pack(
                item, repo, bundle_manifest, use_case, context_budget_tokens,
            )
            if pack.get("status") == "invalid":
                # A failed analysis is never committed as a completed handoff.
                return {
                    "status": "blocked", "event_key": key,
                    "reason": pack.get("reason"), "receipt_path": None,
                }
            receipt = {
                "kind": KIND, "version": VERSION,
                "event_key": key, "event_payload_sha256": input_sha,
                "event": item,
                "input_authority": "caller_assertion_not_verified_remote_event",
                "git_authority": "existing_local_git_objects",
                "bundle_source": "existing_snapshot_only",
                "delivery_timing": _delivery_timing(item),
                "bundle_revision_alignment": _bundle_revision_alignment(pack, item),
                "evidence_pack": pack,
                "evidence_pack_sha256": hashlib.sha256(_canonical(pack)).hexdigest(),
                "consumer_handoff": {
                    "recommended_tool": "change_evidence_pack",
                    "use_case": use_case,
                    "review_authority": "none",
                    "effect": "read_only_evidence",
                    "automatic_agent_invocation": False,
                    "analysis_status": pack.get("status"),
                },
                "does_not_establish": [
                    "github_event_authenticity", "ci_conclusion_authenticity",
                    "publisher_timestamp_authenticity", "current_remote_freshness",
                    *_FORBIDDEN_APPROVAL,
                ],
            }
            raw = _canonical(receipt)
            if len(raw) > MAX_RECEIPT_BYTES:
                return {"status": "blocked", "event_key": key,
                        "reason": "receipt_size_limit", "receipt_path": None}
            name = None
            try:
                fd, name = tempfile.mkstemp(prefix=f".event-{key[:12]}-", suffix=".tmp", dir=out)
                with os.fdopen(fd, "wb") as handle:
                    os.fchmod(handle.fileno(), 0o600)
                    handle.write(raw)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(name, path)
                directory_fd = os.open(out, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            finally:
                if name is not None and os.path.exists(name):
                    os.unlink(name)
            return {"status": "published", "receipt_path": str(path), "event_key": key, "receipt": receipt}
    finally:
        # fd ownership transferred to fdopen and automatically closed
        pass