"""Validate RepoGround outcome follow-ups without becoming Bureau authority."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

EXPECTED_POLICY = {
    "bureau_authority": "external_only",
    "offline_reference_state": "unavailable_not_valid",
    "repoground_role": "read_only_reference_and_drift",
    "task_done_does_not_imply_outcome_ready": True,
}
OUTCOME_GAP_STATES = {"not_established", "blocked", "partial"}
BUREAU_TASK_OPEN_STATES = {
    "planned",
    "ready",
    "blocked",
    "assigned",
    "running",
    "verifying",
}
BUREAU_TASK_TERMINAL_STATES = {
    "verified",
    "completed",
    "done",
    "closed",
    "cancelled",
    "superseded",
}
BUREAU_CANDIDATE_OPEN_STATES = {"observed", "active"}
BUREAU_CANDIDATE_TERMINAL_STATES = {
    "closed",
    "completed",
    "superseded",
    "cancelled",
}
BUREAU_SNAPSHOT_KIND = "bureau_status_truth_snapshot"
BUREAU_SNAPSHOT_SCHEMA_VERSION = 1
BUREAU_SNAPSHOT_MAX_AGE_SECONDS = 300.0
BUREAU_SNAPSHOT_FUTURE_TOLERANCE_SECONDS = 30.0
BUREAU_CANDIDATE_PROJECTION_SOURCE = "complete_event_scan"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class FollowupFinding:
    code: str
    detail: str


def _structured_followups(truth: dict[str, Any]) -> list[dict[str, Any]]:
    value = truth.get("open_followups")
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _declared_coverage(followups: list[dict[str, Any]]) -> set[str]:
    coverage: set[str] = set()
    for item in followups:
        covers = item.get("covers")
        if isinstance(covers, list):
            coverage.update(value for value in covers if isinstance(value, str))
    return coverage


def _required_gap_keys(
    truth: dict[str, Any],
    local_tasks: list[dict[str, Any]],
) -> set[str]:
    required: set[str] = set()
    maturity = truth.get("system_maturity")
    maturity = maturity if isinstance(maturity, dict) else {}
    for axis in (
        "operational_readiness",
        "product_readiness",
        "release_readiness",
    ):
        if maturity.get(axis) in OUTCOME_GAP_STATES:
            required.add(f"system_maturity:{axis}")

    packages = truth.get("audit_packages")
    packages = packages if isinstance(packages, list) else []
    for package in packages:
        if (
            isinstance(package, dict)
            and package.get("promotion") == "blocked"
            and isinstance(package.get("task_id"), str)
        ):
            required.add(f"audit_package:{package['task_id']}:promotion")

    for task in local_tasks:
        if (
            isinstance(task, dict)
            and task.get("status") != "done"
            and isinstance(task.get("id"), str)
            and isinstance(task.get("missing_evidence"), list)
            and task["missing_evidence"]
        ):
            required.add(f"task:{task['id']}:missing_evidence")
    return required


def _coverage_findings(
    truth: dict[str, Any],
    followups: list[dict[str, Any]],
    local_tasks: list[dict[str, Any]],
) -> list[FollowupFinding]:
    required = _required_gap_keys(truth, local_tasks)
    covered = _declared_coverage(followups)
    findings = [
        FollowupFinding(
            "STATUS_TRUTH_OUTCOME_FOLLOWUP_MISSING",
            f"current outcome gap has no binding: {key}",
        )
        for key in sorted(required - covered)
    ]
    findings.extend(
        FollowupFinding(
            "STATUS_TRUTH_OUTCOME_FOLLOWUP_STALE",
            f"follow-up no longer covers a current outcome gap: {key}",
        )
        for key in sorted(covered - required)
    )
    return findings


def _bureau_bindings(followups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in followups:
        binding = item.get("binding")
        if isinstance(binding, dict) and binding.get("kind") in {
            "bureau_task",
            "bureau_candidate",
        }:
            result.append(binding)
    return result


def _reference_state_finding(
    binding: dict[str, Any],
    bureau_snapshot: dict[str, Any],
) -> FollowupFinding | None:
    kind = str(binding.get("kind"))
    reference = str(binding.get("id"))
    collection_name = "tasks" if kind == "bureau_task" else "candidates"
    collection = bureau_snapshot.get(collection_name)
    record = collection.get(reference) if isinstance(collection, dict) else None
    if not isinstance(record, dict):
        return FollowupFinding("STATUS_TRUTH_BUREAU_REF_MISSING", reference)

    canonical_id = record.get("canonical_id", reference)
    if canonical_id != reference:
        return FollowupFinding(
            "STATUS_TRUTH_BUREAU_REF_RENAMED",
            f"{reference} -> {canonical_id}",
        )

    state_key = "state" if kind == "bureau_task" else "status"
    state = record.get(state_key)
    terminal_states = (
        BUREAU_TASK_TERMINAL_STATES
        if kind == "bureau_task"
        else BUREAU_CANDIDATE_TERMINAL_STATES
    )
    open_states = (
        BUREAU_TASK_OPEN_STATES
        if kind == "bureau_task"
        else BUREAU_CANDIDATE_OPEN_STATES
    )
    if state == "superseded":
        return FollowupFinding("STATUS_TRUTH_BUREAU_REF_SUPERSEDED", reference)
    if state in terminal_states:
        return FollowupFinding(
            "STATUS_TRUTH_BUREAU_REF_CLOSED",
            f"{reference}: {state}",
        )
    if state not in open_states:
        return FollowupFinding(
            "STATUS_TRUTH_BUREAU_REF_STATE_UNKNOWN",
            f"{reference}: {state!r}",
        )
    return None


def _parse_observed_at(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _candidate_snapshot_contract_finding(
    source: dict[str, Any],
    bureau_snapshot: dict[str, Any],
) -> FollowupFinding | None:
    if source.get("candidate_coverage_complete") is not True:
        return FollowupFinding(
            "STATUS_TRUTH_BUREAU_SNAPSHOT_INVALID",
            "candidate references require a complete Bureau Live Register projection",
        )
    if source.get("candidate_projection_source") != BUREAU_CANDIDATE_PROJECTION_SOURCE:
        return FollowupFinding(
            "STATUS_TRUTH_BUREAU_SNAPSHOT_INVALID",
            "candidate references require the authoritative complete_event_scan projection",
        )
    projection_records = source.get("candidate_projection_records")
    candidates = bureau_snapshot.get("candidates")
    candidate_count = len(candidates) if isinstance(candidates, dict) else 0
    if (
        isinstance(projection_records, bool)
        or not isinstance(projection_records, int)
        or projection_records < candidate_count
    ):
        return FollowupFinding(
            "STATUS_TRUTH_BUREAU_SNAPSHOT_INVALID",
            "candidate projection must carry a non-negative event-count revision binding",
        )
    return None


def _snapshot_contract_finding(
    bindings: list[dict[str, Any]],
    bureau_snapshot: dict[str, Any],
    *,
    now: datetime | None = None,
) -> FollowupFinding | None:
    if (
        bureau_snapshot.get("kind") != BUREAU_SNAPSHOT_KIND
        or bureau_snapshot.get("schema_version") != BUREAU_SNAPSHOT_SCHEMA_VERSION
    ):
        return FollowupFinding(
            "STATUS_TRUTH_BUREAU_SNAPSHOT_INVALID",
            "expected a versioned bureau_status_truth_snapshot",
        )

    source = bureau_snapshot.get("source")
    if not isinstance(source, dict):
        return FollowupFinding(
            "STATUS_TRUTH_BUREAU_SNAPSHOT_INVALID",
            "missing source metadata",
        )
    if (
        source.get("authority") != "bureau-state-store"
        or source.get("task_authority") != "state-store"
    ):
        return FollowupFinding(
            "STATUS_TRUTH_BUREAU_SNAPSHOT_INVALID",
            "snapshot must be read from the authoritative Bureau StateStore task projection",
        )
    task_root = source.get("task_spec_root_sha256")
    if not isinstance(task_root, str) or _SHA256_RE.fullmatch(task_root) is None:
        return FollowupFinding(
            "STATUS_TRUTH_BUREAU_SNAPSHOT_INVALID",
            "missing state-store task_spec_root_sha256 revision binding",
        )
    if any(binding.get("kind") == "bureau_candidate" for binding in bindings):
        candidate_finding = _candidate_snapshot_contract_finding(source, bureau_snapshot)
        if candidate_finding is not None:
            return candidate_finding

    observed_at = _parse_observed_at(bureau_snapshot.get("observed_at"))
    if observed_at is None:
        return FollowupFinding(
            "STATUS_TRUTH_BUREAU_SNAPSHOT_INVALID",
            "snapshot observed_at must be an offset-aware ISO-8601 timestamp",
        )
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    age_seconds = (current - observed_at).total_seconds()
    if age_seconds < -BUREAU_SNAPSHOT_FUTURE_TOLERANCE_SECONDS:
        return FollowupFinding(
            "STATUS_TRUTH_BUREAU_SNAPSHOT_FUTURE",
            f"snapshot observed_at is {-age_seconds:.1f}s in the future",
        )
    if age_seconds > BUREAU_SNAPSHOT_MAX_AGE_SECONDS:
        return FollowupFinding(
            "STATUS_TRUTH_BUREAU_SNAPSHOT_STALE",
            f"snapshot age {age_seconds:.1f}s exceeds {BUREAU_SNAPSHOT_MAX_AGE_SECONDS:.0f}s",
        )
    return None


def _resolve_bureau_bindings(
    bindings: list[dict[str, Any]],
    bureau_snapshot: dict[str, Any] | None,
    *,
    now: datetime | None = None,
) -> tuple[list[FollowupFinding], dict[str, Any]]:
    resolution = {
        "status": "not_required",
        "checked_reference_count": len(bindings),
        "valid_reference_count": 0,
    }
    if not bindings:
        return [], resolution
    if not isinstance(bureau_snapshot, dict) or bureau_snapshot.get("available") is not True:
        resolution["status"] = "unavailable"
        return [
            FollowupFinding("STATUS_TRUTH_BUREAU_UNAVAILABLE", str(binding.get("id")))
            for binding in bindings
        ], resolution

    contract_finding = _snapshot_contract_finding(bindings, bureau_snapshot, now=now)
    if contract_finding is not None:
        resolution["status"] = (
            "stale"
            if contract_finding.code == "STATUS_TRUTH_BUREAU_SNAPSHOT_STALE"
            else "invalid"
        )
        return [contract_finding], resolution

    findings: list[FollowupFinding] = []
    resolution["status"] = "verified"
    for binding in bindings:
        finding = _reference_state_finding(binding, bureau_snapshot)
        if finding is None:
            resolution["valid_reference_count"] += 1
        else:
            resolution["status"] = "drifted"
            findings.append(finding)
    return findings, resolution


def validate_outcome_followups(
    truth: dict[str, Any],
    bureau_snapshot: dict[str, Any] | None = None,
    *,
    local_tasks: list[dict[str, Any]] | None = None,
    now: datetime | None = None,
) -> tuple[list[FollowupFinding], dict[str, Any]]:
    """Validate current outcome gaps and resolve Bureau references read-only.

    Completed local tasks may retain ``missing_evidence`` as bounded limitations;
    they are not reopened automatically. Non-completed tasks with missing evidence,
    blocked audit-package promotions and non-established/partial maturity axes are
    current gaps and must be covered explicitly.

    Absence of a Bureau snapshot never turns a Bureau reference into success. A
    supplied snapshot must be revision-bound to the authoritative StateStore task
    projection and fresh enough to make drift claims meaningful. Candidate state
    additionally requires Bureau's complete event-scan projection plus its event
    count revision. Explicit ``no_task`` rationales require no Bureau access because
    they register no task and grant no task/queue/claim authority to RepoGround.
    """

    findings: list[FollowupFinding] = []
    if truth.get("outcome_followup_policy") != EXPECTED_POLICY:
        findings.append(
            FollowupFinding(
                "STATUS_TRUTH_FOLLOWUP_AUTHORITY",
                "Bureau must remain external and RepoGround must stay read-only",
            )
        )

    structured = _structured_followups(truth)
    findings.extend(_coverage_findings(truth, structured, local_tasks or []))
    bureau_findings, resolution = _resolve_bureau_bindings(
        _bureau_bindings(structured),
        bureau_snapshot,
        now=now,
    )
    findings.extend(bureau_findings)
    return findings, resolution
