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
_FINDING_RE = re.compile(r"^af_[a-f0-9]{16}$")
_VERIFIER_STATES = frozenset({"verified", "wrong", "unresolved"})
_STATES = ("candidate", "verified", "stale", "wrong", "unresolved")
_MAX_TEXT_CHARS = 8192
_MAX_CITATIONS = 64
_CANDIDATE_KEYS = frozenset({"lane_id", "claim", "citation_ids"})
_VERDICT_KEYS = frozenset({"finding_id", "state", "verifier_id", "note"})


class AuditFindingError(ValueError):
    """Raised when audit finding input cannot be admitted safely."""


def _require_revision(value: str, field: str) -> str:
    if not isinstance(value, str) or _REVISION_RE.fullmatch(value) is None:
        raise AuditFindingError(f"{field} must be a lowercase 40-hex revision")
    return value


def _require_identifier(value: Any, field: str, pattern: re.Pattern[str]) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise AuditFindingError(f"{field} has an invalid identifier format")
    return value


def _require_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AuditFindingError(f"{field} must be a non-empty string")
    normalized = " ".join(value.split())
    if len(normalized) > _MAX_TEXT_CHARS:
        raise AuditFindingError(f"{field} exceeds {_MAX_TEXT_CHARS} characters")
    return normalized


def _require_items(values: Any, field: str) -> list[Any]:
    if isinstance(values, (str, bytes)):
        raise AuditFindingError(f"{field} must be an iterable")
    try:
        return list(values)
    except TypeError as exc:
        raise AuditFindingError(f"{field} must be an iterable") from exc


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


def make_audit_finding_id(lane_id: str, claim: str, citation_ids: Sequence[str]) -> str:
    """Return a stable semantic id for one normalized candidate."""

    payload = {
        "lane_id": _require_identifier(lane_id, "lane_id", _LANE_RE),
        "claim": _require_string(claim, "claim"),
        "citation_ids": list(_normalize_citations(citation_ids)),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return f"af_{hashlib.sha256(encoded).hexdigest()[:16]}"


def _plan_lane_ids(plan: Mapping[str, Any]) -> frozenset[str]:
    if not isinstance(plan, Mapping) or plan.get("version") != "audit_lane_plan.v1":
        raise AuditFindingError("plan must be an audit_lane_plan.v1 object")
    if plan.get("authority") != "navigation_index" or plan.get("risk_class") != "diagnostic":
        raise AuditFindingError("plan authority and risk class must match audit_lane_plan.v1")
    lanes = plan.get("lanes")
    if not isinstance(lanes, Sequence) or isinstance(lanes, (str, bytes)) or not lanes:
        raise AuditFindingError("plan lanes must be a non-empty array")
    lane_ids = []
    for lane in lanes:
        if not isinstance(lane, Mapping):
            raise AuditFindingError("plan lanes must be objects")
        lane_ids.append(
            _require_identifier(lane.get("id"), "plan lane id", _LANE_RE)
        )
    if len(lane_ids) != len(set(lane_ids)):
        raise AuditFindingError("plan lane ids must be unique")
    return frozenset(lane_ids)


def _citation_registry(values: Iterable[str]) -> frozenset[str]:
    items = _require_items(values, "resolvable_citation_ids")
    for value in items:
        if not isinstance(value, str) or _CITATION_RE.fullmatch(value) is None:
            raise AuditFindingError("resolvable_citation_ids contains an invalid citation id")
    return frozenset(items)


def _normalize_candidate(candidate: Any, lane_ids: frozenset[str]) -> dict[str, Any]:
    if not isinstance(candidate, Mapping):
        raise AuditFindingError("candidates must contain objects")
    if set(candidate) != _CANDIDATE_KEYS:
        raise AuditFindingError("candidate fields must be exactly lane_id, claim, citation_ids")
    lane_id = _require_identifier(candidate.get("lane_id"), "lane_id", _LANE_RE)
    if lane_id not in lane_ids:
        raise AuditFindingError(f"candidate references unselected lane: {lane_id}")
    claim = _require_string(candidate.get("claim"), "claim")
    citation_ids = _normalize_citations(candidate.get("citation_ids"))
    return {
        "finding_id": make_audit_finding_id(lane_id, claim, citation_ids),
        "lane_id": lane_id,
        "claim": claim,
        "citation_ids": list(citation_ids),
    }


def _normalize_verdicts(values: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, str]]:
    verdicts: dict[str, dict[str, str]] = {}
    for value in _require_items(values, "verifier_verdicts"):
        if not isinstance(value, Mapping):
            raise AuditFindingError("verifier_verdicts must contain objects")
        if set(value) != _VERDICT_KEYS:
            raise AuditFindingError(
                "verdict fields must be exactly finding_id, state, verifier_id, note"
            )
        finding_id = _require_identifier(
            value.get("finding_id"), "verdict finding_id", _FINDING_RE
        )
        state = _require_string(value.get("state"), "verdict state")
        if state not in _VERIFIER_STATES:
            raise AuditFindingError(f"unsupported verifier state: {state}")
        if finding_id in verdicts:
            raise AuditFindingError(f"duplicate verifier verdict: {finding_id}")
        verdicts[finding_id] = {
            "finding_id": finding_id,
            "state": state,
            "verifier_id": _require_string(value.get("verifier_id"), "verifier_id"),
            "note": _require_string(value.get("note"), "verifier note"),
        }
    return verdicts


def _classify(
    candidate: dict[str, Any],
    *,
    stale: bool,
    citation_registry: frozenset[str],
    verdict: dict[str, str] | None,
) -> dict[str, Any]:
    unresolved = [cid for cid in candidate["citation_ids"] if cid not in citation_registry]
    if stale:
        state = "stale"
        reason = "revision_mismatch"
    elif unresolved:
        state = "unresolved"
        reason = "citation_unresolved"
    elif verdict is None:
        state = "candidate"
        reason = "verification_missing"
    else:
        state = verdict["state"]
        reason = "verifier_verdict"
    return {
        **candidate,
        "state": state,
        "state_reason": reason,
        "unresolved_citation_ids": unresolved,
        "verification_record": verdict,
        "verification_applied": verdict is not None and reason == "verifier_verdict",
    }


def adapt_audit_findings(
    plan: Mapping[str, Any],
    candidates: Iterable[Mapping[str, Any]],
    *,
    reviewed_revision: str,
    current_revision: str,
    resolvable_citation_ids: Iterable[str],
    verifier_verdicts: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Return a deterministic, evidence-bound finding set.

    Revision mismatch and unresolved citations take precedence over a verifier verdict.
    The verdict remains preserved but is marked unapplied.
    """

    reviewed = _require_revision(reviewed_revision, "reviewed_revision")
    current = _require_revision(current_revision, "current_revision")
    lane_ids = _plan_lane_ids(plan)
    citation_registry = _citation_registry(resolvable_citation_ids)
    normalized = [
        _normalize_candidate(value, lane_ids)
        for value in _require_items(candidates, "candidates")
    ]
    by_id = {value["finding_id"]: value for value in normalized}
    if len(by_id) != len(normalized):
        raise AuditFindingError("duplicate semantic candidate finding")
    verdicts = _normalize_verdicts(verifier_verdicts)
    unknown_verdicts = sorted(set(verdicts) - set(by_id))
    if unknown_verdicts:
        raise AuditFindingError(f"verdict references unknown finding: {unknown_verdicts[0]}")

    stale = reviewed != current
    findings = [
        _classify(
            by_id[finding_id],
            stale=stale,
            citation_registry=citation_registry,
            verdict=verdicts.get(finding_id),
        )
        for finding_id in sorted(by_id)
    ]
    counts = Counter(finding["state"] for finding in findings)
    return {
        "version": "audit_finding_set.v1",
        "authority": "diagnostic_signal",
        "risk_class": "diagnostic",
        "plan_version": "audit_lane_plan.v1",
        "reviewed_revision": reviewed,
        "current_revision": current,
        "revision_fresh": not stale,
        "findings": findings,
        "state_counts": [
            {"state": state, "count": counts[state]}
            for state in _STATES
        ],
        "allowed_inferences": [
            "which candidate claims were bound to selected lanes and known citations",
            "whether verifier decisions were applied under the recorded revision",
        ],
        "does_not_prove": [
            "repository truth",
            "review completeness",
            "runtime correctness",
            "severity correctness",
            "permission to create issues, patches, commits, pushes, or merges",
        ],
    }
