"""Bind audit-lane candidates to revision identity and resolvable citations.

The adapter is deterministic and non-agentic. It preserves candidate and verifier
provenance while preventing stale or citation-unresolved claims from becoming verified.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

_REVISION_RE = re.compile(r"^[a-f0-9]{40}$")
_CITATION_RE = re.compile(r"^cit_[a-f0-9]{16}$")
_LANE_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_FINDING_RE = re.compile(r"^af2_[a-f0-9]{16}$")
_STATES = ("candidate", "verified", "stale", "wrong", "unresolved")
_DECISION_TO_STATE = {
    "accepted": "verified",
    "rejected": "wrong",
    "unresolved": "unresolved",
}
_FINDING_ID_DOMAIN = "lenskit.audit_finding_id.v2"
_MAX_CLAIM_CHARS = 4_096
_MAX_VERIFIER_ID_CHARS = 256
_MAX_NOTE_CHARS = 2_048
_MAX_CITATIONS = 64
_MAX_CANDIDATES = 200
_MAX_VERIFICATION_RECORDS = 200
_MAX_RESOLVABLE_CITATIONS = 100_000
_CANDIDATE_KEYS = frozenset({"lane_id", "claim", "citation_ids"})
_VERIFICATION_KEYS = frozenset(
    {
        "version",
        "authority",
        "risk_class",
        "finding_id",
        "reviewed_revision",
        "decision",
        "verifier_id",
        "note",
        "does_not_prove",
    }
)
_VERIFICATION_DOES_NOT_PROVE = (
    "repository truth",
    "review completeness",
    "freshness beyond the recorded revision",
    "permission to create issues, patches, commits, pushes, or merges",
)
_FINDING_SET_DOES_NOT_PROVE = (
    "repository truth",
    "review completeness",
    "runtime correctness",
    "severity correctness",
    "permission to create issues, patches, commits, pushes, or merges",
)
_ALLOWED_INFERENCES = (
    "which candidate claims were bound to selected lanes and known citations",
    "whether neutral verifier decisions were applied under the recorded revision",
)


class AuditFindingError(ValueError):
    """Raised when audit finding input cannot be admitted safely."""


def _require_revision(value: Any, field: str) -> str:
    if not isinstance(value, str) or _REVISION_RE.fullmatch(value) is None:
        raise AuditFindingError(f"{field} must be a lowercase 40-hex revision")
    return value


def _require_identifier(value: Any, field: str, pattern: re.Pattern[str]) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise AuditFindingError(f"{field} has an invalid identifier format")
    return value


def _require_text(value: Any, field: str, max_chars: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AuditFindingError(f"{field} must be a non-empty string")
    normalized = " ".join(value.split())
    if len(normalized) > max_chars:
        raise AuditFindingError(f"{field} exceeds {max_chars} characters")
    return normalized


def _require_items(values: Any, field: str, max_items: int) -> list[Any]:
    if isinstance(values, (str, bytes)):
        raise AuditFindingError(f"{field} must be an iterable")
    try:
        items = list(values)
    except TypeError as exc:
        raise AuditFindingError(f"{field} must be an iterable") from exc
    if len(items) > max_items:
        raise AuditFindingError(f"{field} must contain at most {max_items} entries")
    return items


def _normalize_citations(values: Any) -> tuple[str, ...]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)) or not values:
        raise AuditFindingError("citation_ids must be a non-empty array")
    if len(values) > _MAX_CITATIONS:
        raise AuditFindingError(f"citation_ids must contain at most {_MAX_CITATIONS} entries")
    checked: list[str] = []
    for value in values:
        if not isinstance(value, str) or _CITATION_RE.fullmatch(value) is None:
            raise AuditFindingError("citation_ids must use the cit_<16 lower-hex> form")
        checked.append(value)
    if len(checked) != len(set(checked)):
        raise AuditFindingError("citation_ids must not contain duplicates")
    return tuple(sorted(checked))


def _build_finding_id(lane_id: str, claim: str, citation_ids: Sequence[str]) -> str:
    payload = [_FINDING_ID_DOMAIN, lane_id, claim, list(citation_ids)]
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return f"af2_{hashlib.sha256(encoded).hexdigest()[:16]}"


def make_audit_finding_id(lane_id: str, claim: str, citation_ids: Sequence[str]) -> str:
    """Return a version-domain-separated semantic id for one candidate."""

    checked_lane = _require_identifier(lane_id, "lane_id", _LANE_RE)
    checked_claim = _require_text(claim, "claim", _MAX_CLAIM_CHARS)
    checked_citations = _normalize_citations(citation_ids)
    return _build_finding_id(checked_lane, checked_claim, checked_citations)


def _plan_lane_ids(plan: Mapping[str, Any]) -> frozenset[str]:
    if not isinstance(plan, Mapping) or plan.get("version") != "audit_lane_plan.v1":
        raise AuditFindingError("plan must be an audit_lane_plan.v1 object")
    if plan.get("authority") != "navigation_index" or plan.get("risk_class") != "diagnostic":
        raise AuditFindingError("plan authority and risk class must match audit_lane_plan.v1")
    lanes = plan.get("lanes")
    if not isinstance(lanes, Sequence) or isinstance(lanes, (str, bytes)) or not lanes:
        raise AuditFindingError("plan lanes must be a non-empty array")
    lane_ids: list[str] = []
    for lane in lanes:
        if not isinstance(lane, Mapping):
            raise AuditFindingError("plan lanes must be objects")
        lane_ids.append(_require_identifier(lane.get("id"), "plan lane id", _LANE_RE))
    if len(lane_ids) != len(set(lane_ids)):
        raise AuditFindingError("plan lane ids must be unique")
    return frozenset(lane_ids)


def _citation_registry(values: Iterable[str]) -> frozenset[str]:
    items = _require_items(
        values,
        "resolvable_citation_ids",
        _MAX_RESOLVABLE_CITATIONS,
    )
    for value in items:
        if not isinstance(value, str) or _CITATION_RE.fullmatch(value) is None:
            raise AuditFindingError("resolvable_citation_ids contains an invalid citation id")
    if len(items) != len(set(items)):
        raise AuditFindingError("resolvable_citation_ids must not contain duplicates")
    return frozenset(items)


def _normalize_candidate(candidate: Any, lane_ids: frozenset[str]) -> dict[str, Any]:
    if not isinstance(candidate, Mapping):
        raise AuditFindingError("candidates must contain objects")
    if set(candidate) != _CANDIDATE_KEYS:
        raise AuditFindingError("candidate fields must be exactly lane_id, claim, citation_ids")
    lane_id = _require_identifier(candidate.get("lane_id"), "lane_id", _LANE_RE)
    if lane_id not in lane_ids:
        raise AuditFindingError(f"candidate references unselected lane: {lane_id}")
    claim = _require_text(candidate.get("claim"), "claim", _MAX_CLAIM_CHARS)
    citation_ids = _normalize_citations(candidate.get("citation_ids"))
    return {
        "finding_id": _build_finding_id(lane_id, claim, citation_ids),
        "lane_id": lane_id,
        "claim": claim,
        "citation_ids": list(citation_ids),
    }


def _normalize_verification_records(
    values: Iterable[Mapping[str, Any]],
    reviewed_revision: str,
) -> dict[str, dict[str, str | list[str]]]:
    records: dict[str, dict[str, str | list[str]]] = {}
    for value in _require_items(
        values,
        "verification_records",
        _MAX_VERIFICATION_RECORDS,
    ):
        if not isinstance(value, Mapping):
            raise AuditFindingError("verification_records must contain objects")
        if set(value) != _VERIFICATION_KEYS:
            raise AuditFindingError("verification record fields do not match the v1 contract")
        if value.get("version") != "audit_verification_record.v1":
            raise AuditFindingError("verification record version must be audit_verification_record.v1")
        if value.get("authority") != "diagnostic_signal" or value.get("risk_class") != "diagnostic":
            raise AuditFindingError("verification record authority and risk class are invalid")
        finding_id = _require_identifier(
            value.get("finding_id"), "verification finding_id", _FINDING_RE
        )
        record_revision = _require_revision(
            value.get("reviewed_revision"), "verification reviewed_revision"
        )
        if record_revision != reviewed_revision:
            raise AuditFindingError("verification record revision does not match reviewed_revision")
        decision = value.get("decision")
        if not isinstance(decision, str) or decision not in _DECISION_TO_STATE:
            raise AuditFindingError(f"unsupported verification decision: {decision}")
        does_not_prove = value.get("does_not_prove")
        if (
            not isinstance(does_not_prove, Sequence)
            or isinstance(does_not_prove, (str, bytes))
            or len(does_not_prove) != len(_VERIFICATION_DOES_NOT_PROVE)
            or any(not isinstance(item, str) for item in does_not_prove)
            or len(set(does_not_prove)) != len(does_not_prove)
            or set(does_not_prove) != set(_VERIFICATION_DOES_NOT_PROVE)
        ):
            raise AuditFindingError("verification record does_not_prove must match the contract")
        if finding_id in records:
            raise AuditFindingError(f"duplicate verification record: {finding_id}")
        records[finding_id] = {
            "version": "audit_verification_record.v1",
            "authority": "diagnostic_signal",
            "risk_class": "diagnostic",
            "finding_id": finding_id,
            "reviewed_revision": record_revision,
            "decision": str(decision),
            "verifier_id": _require_text(
                value.get("verifier_id"), "verifier_id", _MAX_VERIFIER_ID_CHARS
            ),
            "note": _require_text(value.get("note"), "verification note", _MAX_NOTE_CHARS),
            "does_not_prove": list(_VERIFICATION_DOES_NOT_PROVE),
        }
    return records


def _classify(
    candidate: dict[str, Any],
    *,
    stale: bool,
    citation_registry: frozenset[str],
    record: dict[str, str | list[str]] | None,
) -> dict[str, Any]:
    unresolved = [cid for cid in candidate["citation_ids"] if cid not in citation_registry]
    if stale:
        state = "stale"
        reason = "revision_mismatch"
        disposition = "blocked_revision" if record is not None else "not_supplied"
    elif unresolved:
        state = "unresolved"
        reason = "citation_unresolved"
        disposition = "blocked_citation" if record is not None else "not_supplied"
    elif record is None:
        state = "candidate"
        reason = "verification_missing"
        disposition = "not_supplied"
    else:
        state = _DECISION_TO_STATE[str(record["decision"])]
        reason = "verification_decision"
        disposition = "applied"
    return {
        **candidate,
        "state": state,
        "state_reason": reason,
        "unresolved_citation_ids": unresolved,
        "verification_record": record,
        "verification_disposition": disposition,
        "verification_applied": disposition == "applied",
    }


def adapt_audit_findings(
    plan: Mapping[str, Any],
    candidates: Iterable[Mapping[str, Any]],
    *,
    reviewed_revision: str,
    current_revision: str,
    resolvable_citation_ids: Iterable[str],
    verification_records: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Return a deterministic, evidence-bound finding set.

    Revision mismatch and unresolved citations take precedence over a neutral verifier
    decision. The complete verification record remains preserved with an explicit
    disposition explaining whether it was applied or blocked.
    """

    reviewed = _require_revision(reviewed_revision, "reviewed_revision")
    current = _require_revision(current_revision, "current_revision")
    lane_ids = _plan_lane_ids(plan)
    citation_registry = _citation_registry(resolvable_citation_ids)
    normalized = [
        _normalize_candidate(value, lane_ids)
        for value in _require_items(candidates, "candidates", _MAX_CANDIDATES)
    ]
    by_id = {value["finding_id"]: value for value in normalized}
    if len(by_id) != len(normalized):
        raise AuditFindingError("duplicate semantic candidate finding")
    records = _normalize_verification_records(verification_records, reviewed)
    unknown_records = sorted(set(records) - set(by_id))
    if unknown_records:
        raise AuditFindingError(
            f"verification record references unknown finding: {unknown_records[0]}"
        )

    stale = reviewed != current
    findings = [
        _classify(
            by_id[finding_id],
            stale=stale,
            citation_registry=citation_registry,
            record=records.get(finding_id),
        )
        for finding_id in sorted(by_id)
    ]
    counts = Counter(finding["state"] for finding in findings)
    return {
        "version": "audit_finding_set.v2",
        "authority": "diagnostic_signal",
        "risk_class": "diagnostic",
        "finding_id_algorithm": _FINDING_ID_DOMAIN,
        "plan_version": "audit_lane_plan.v1",
        "reviewed_revision": reviewed,
        "current_revision": current,
        "revision_fresh": not stale,
        "findings": findings,
        "state_counts": [
            {"state": state, "count": counts[state]}
            for state in _STATES
        ],
        "allowed_inferences": list(_ALLOWED_INFERENCES),
        "does_not_prove": list(_FINDING_SET_DOES_NOT_PROVE),
    }
