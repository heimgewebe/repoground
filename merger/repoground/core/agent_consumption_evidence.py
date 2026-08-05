"""Compare declared agent consumption with trusted tool-read receipts.

Layers:

* Answer Compliance = declaration only
* Trusted tool-read receipts = observation metadata only
* This module = deterministic comparison for the same task_id, repo_commit,
  artifact_role and immutable artifact identity

Comparison states (exactly):

* ``declared-only``
* ``observed-only``
* ``declared-and-observed``
* ``unavailable``

Rejected observations (missing, stale, task-mismatch, commit-mismatch, replay,
artifact-mismatch, untrusted issuer, privacy, invalid) never elevate evidence
to ``declared-and-observed``.

This comparison does not establish semantic reading, relevance, correctness,
completeness, forensic readiness, runtime interception or mandatory adoption.
It preserves the nine agent-consumption ``does_not_establish`` boundaries and
adds observation-specific non-claims.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from merger.repoground.core.agent_consumption_receipts import (
    RETENTION,
    ToolReadReceiptError,
    validate_tool_read_receipt,
)
from merger.repoground.core.agent_consumption_validate import (
    DOES_NOT_ESTABLISH as TRACE_DOES_NOT_ESTABLISH,
)

KIND = "lenskit.agent_consumption_evidence"
VERSION = "1.0"

COMPARISON_STATES = (
    "declared-only",
    "observed-only",
    "declared-and-observed",
    "unavailable",
)

# Preserve the nine declaration/trace boundaries and add observation non-claims.
DOES_NOT_ESTABLISH: tuple[str, ...] = (
    "actual_reading_proven",
    "semantic_reading",
    "relevance_to_answer",
    "answer_correct",
    "repo_understood",
    "all_relevant_context_used",
    "claims_true",
    "test_sufficiency",
    "regression_absence",
    "runtime_behavior",
    "forensic_ready",
    "runtime_interception",
    "mandatory_wrapper_adoption",
)

assert set(TRACE_DOES_NOT_ESTABLISH).issubset(set(DOES_NOT_ESTABLISH))

_FAIL = "fail"
_WARN = "warn"
_INFO = "info"

_COMMIT_LEN = 40


def compare_agent_consumption_evidence(
    answer_compliance: Mapping[str, Any] | None,
    receipts: Sequence[Any] | None,
    *,
    task_id: str,
    repo_commit: str,
    expected_roles: Sequence[str] | None = None,
    declared_identities: Mapping[str, Mapping[str, Any]] | None = None,
    as_of: str | None = None,
    max_age_seconds: int | None = None,
) -> dict[str, Any]:
    """Compare declarations with trusted receipts for one task and commit.

    ``answer_compliance`` may be a full Answer Compliance object or a minimal
    mapping that provides ``declared_artifacts``. Self-declarations never mint
    observed evidence.
    """
    diagnostics: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    task = _require_bound_str(task_id, "task_id", diagnostics)
    commit = _require_commit(repo_commit, diagnostics)
    declared_roles = _declared_roles(answer_compliance, diagnostics)
    expected = _role_set(expected_roles, "expected_roles", diagnostics)
    identity_index = _declared_identity_index(declared_identities, diagnostics)
    as_of_dt = _parse_as_of(as_of, diagnostics)
    max_age = _normalize_max_age(max_age_seconds, diagnostics)

    accepted_by_role: dict[str, dict[str, Any]] = {}
    accepted_refs: list[dict[str, str]] = []
    seen_events: dict[str, str] = {}
    raw_receipts = list(receipts) if isinstance(receipts, Sequence) and not isinstance(
        receipts, (str, bytes, bytearray)
    ) else []
    if receipts is not None and not isinstance(receipts, Sequence):
        diagnostics.append(
            _diag(
                "invalid_input_field",
                _FAIL,
                "receipts must be an array of receipt objects.",
            )
        )
        raw_receipts = []
    elif isinstance(receipts, (str, bytes, bytearray)):
        diagnostics.append(
            _diag(
                "invalid_input_field",
                _FAIL,
                "receipts must be an array of receipt objects.",
            )
        )
        raw_receipts = []

    for index, raw in enumerate(raw_receipts):
        _ingest_receipt(
            raw,
            index=index,
            task_id=task,
            repo_commit=commit,
            as_of_dt=as_of_dt,
            max_age=max_age,
            identity_index=identity_index,
            accepted_by_role=accepted_by_role,
            accepted_refs=accepted_refs,
            seen_events=seen_events,
            rejected=rejected,
            diagnostics=diagnostics,
        )

    roles = sorted(set(declared_roles) | set(accepted_by_role) | expected)
    comparisons: list[dict[str, Any]] = []
    for role in roles:
        declared = role in declared_roles
        observed_receipt = accepted_by_role.get(role)
        observed = observed_receipt is not None
        if declared and observed:
            state = "declared-and-observed"
        elif declared and not observed:
            state = "declared-only"
            diagnostics.append(
                _diag(
                    "declared_only",
                    _WARN,
                    f"Artifact role '{role}' was declared but not observed by a trusted receipt.",
                    artifact_role=role,
                )
            )
        elif observed and not declared:
            state = "observed-only"
            diagnostics.append(
                _diag(
                    "observed_only",
                    _WARN,
                    f"Artifact role '{role}' was observed but not declared.",
                    artifact_role=role,
                )
            )
        else:
            state = "unavailable"
            diagnostics.append(
                _diag(
                    "unavailable",
                    _WARN if role in expected else _INFO,
                    f"Artifact role '{role}' has neither declaration nor trusted observation.",
                    artifact_role=role,
                )
            )
        item: dict[str, Any] = {
            "artifact_role": role,
            "state": state,
            "declared": declared,
            "observed": observed,
        }
        if observed_receipt is not None:
            item["receipt_binding_sha256"] = observed_receipt["binding_sha256"]
            item["artifact_identity"] = deepcopy(observed_receipt["artifact_identity"])
        comparisons.append(item)

    if not roles:
        diagnostics.append(
            _diag(
                "missing",
                _WARN,
                "No declared roles, accepted receipts, or expected roles were supplied.",
            )
        )

    return _evidence(
        task_id=task or "unknown",
        repo_commit=commit or ("0" * _COMMIT_LEN),
        comparisons=comparisons,
        accepted_refs=accepted_refs,
        rejected=rejected,
        diagnostics=diagnostics,
    )


def _ingest_receipt(
    raw: Any,
    *,
    index: int,
    task_id: str | None,
    repo_commit: str | None,
    as_of_dt: datetime | None,
    max_age: int | None,
    identity_index: dict[str, dict[str, Any]],
    accepted_by_role: dict[str, dict[str, Any]],
    accepted_refs: list[dict[str, str]],
    seen_events: dict[str, str],
    rejected: list[dict[str, Any]],
    diagnostics: list[dict[str, Any]],
) -> None:
    label = f"receipts[{index}]"
    if not isinstance(raw, Mapping):
        _reject(
            rejected,
            diagnostics,
            reason="invalid_receipt",
            code="invalid_input_field",
            detail=f"{label} is not an object and cannot elevate evidence.",
        )
        return

    # Privacy fail-closed before structural validation so content-bearing forgeries
    # never become observations.
    forbidden = sorted(
        k
        for k in raw
        if isinstance(k, str)
        and k
        in {
            "content",
            "body",
            "text",
            "raw",
            "source_text",
            "source_content",
            "payload",
            "blob",
            "data",
            "file_bytes",
            "bytes_content",
            "secret",
            "secrets",
            "token",
            "password",
            "api_key",
            "private_key",
            "authorization",
        }
    )
    if forbidden:
        _reject(
            rejected,
            diagnostics,
            reason="privacy_violation",
            code="privacy_violation",
            detail=f"{label} contains forbidden content/secret fields: {', '.join(forbidden)}.",
            access_event_id=_maybe_str(raw.get("access_event_id")),
            artifact_role=_maybe_str(raw.get("artifact_role")),
            receipt_sha256=_maybe_hex(raw.get("receipt_sha256")),
        )
        return

    try:
        receipt = validate_tool_read_receipt(raw)
    except ToolReadReceiptError as exc:
        message = str(exc)
        if "allowlisted trusted source" in message or "issuer.kind" in message:
            reason = "untrusted_issuer"
            code = "untrusted_issuer"
        elif "secret-like" in message or "forbidden" in message:
            reason = "privacy_violation"
            code = "privacy_violation"
        elif "binding_sha256" in message or "receipt_sha256" in message:
            reason = "binding_mismatch"
            code = "binding_mismatch"
        else:
            reason = "invalid_receipt"
            code = "invalid_input_field"
        _reject(
            rejected,
            diagnostics,
            reason=reason,
            code=code,
            detail=f"{label} rejected: {message}",
            access_event_id=_maybe_str(raw.get("access_event_id")),
            artifact_role=_maybe_str(raw.get("artifact_role")),
            receipt_sha256=_maybe_hex(raw.get("receipt_sha256")),
        )
        return

    event_id = receipt["access_event_id"]
    if event_id in seen_events:
        _reject(
            rejected,
            diagnostics,
            reason="replay",
            code="replay",
            detail=(
                f"{label} replays access_event_id '{event_id}' already seen for "
                f"binding {seen_events[event_id][:12]}…; replay never elevates evidence."
            ),
            access_event_id=event_id,
            artifact_role=receipt["artifact_role"],
            receipt_sha256=receipt["receipt_sha256"],
        )
        # A replay must not keep a previously accepted observation for the same
        # event, and must not add a second observation.
        return

    if task_id is not None and receipt["task_id"] != task_id:
        _reject(
            rejected,
            diagnostics,
            reason="task_mismatch",
            code="task_mismatch",
            detail=(
                f"{label} task_id '{receipt['task_id']}' does not match bound "
                f"task_id '{task_id}'."
            ),
            access_event_id=event_id,
            artifact_role=receipt["artifact_role"],
            receipt_sha256=receipt["receipt_sha256"],
        )
        return

    if repo_commit is not None and receipt["repo_commit"] != repo_commit:
        _reject(
            rejected,
            diagnostics,
            reason="commit_mismatch",
            code="commit_mismatch",
            detail=(
                f"{label} repo_commit does not match the bound repository commit."
            ),
            access_event_id=event_id,
            artifact_role=receipt["artifact_role"],
            receipt_sha256=receipt["receipt_sha256"],
        )
        return

    if max_age is not None and as_of_dt is not None:
        observed_dt = _parse_timestamp(receipt["observed_at"])
        if observed_dt is None:
            _reject(
                rejected,
                diagnostics,
                reason="invalid_receipt",
                code="invalid_input_field",
                detail=f"{label} observed_at could not be parsed for freshness.",
                access_event_id=event_id,
                artifact_role=receipt["artifact_role"],
                receipt_sha256=receipt["receipt_sha256"],
            )
            return
        age = (as_of_dt - observed_dt).total_seconds()
        if age > max_age or age < 0:
            _reject(
                rejected,
                diagnostics,
                reason="stale",
                code="stale",
                detail=(
                    f"{label} is stale or not-yet-valid relative to as_of "
                    f"(age_seconds={age}, max_age_seconds={max_age})."
                ),
                access_event_id=event_id,
                artifact_role=receipt["artifact_role"],
                receipt_sha256=receipt["receipt_sha256"],
            )
            return

    role = receipt["artifact_role"]
    expected_identity = identity_index.get(role)
    if expected_identity is not None and expected_identity != receipt["artifact_identity"]:
        _reject(
            rejected,
            diagnostics,
            reason="artifact_mismatch",
            code="artifact_mismatch",
            detail=(
                f"{label} artifact identity for role '{role}' does not match the "
                "declared immutable identity."
            ),
            access_event_id=event_id,
            artifact_role=role,
            receipt_sha256=receipt["receipt_sha256"],
        )
        return

    prior = accepted_by_role.get(role)
    if prior is not None and prior["artifact_identity"] != receipt["artifact_identity"]:
        _reject(
            rejected,
            diagnostics,
            reason="artifact_mismatch",
            code="artifact_mismatch",
            detail=(
                f"{label} conflicts with a previously accepted identity for role "
                f"'{role}'; neither identity elevates evidence further."
            ),
            access_event_id=event_id,
            artifact_role=role,
            receipt_sha256=receipt["receipt_sha256"],
        )
        # Downgrade the prior acceptance: conflicting identities remove observed
        # elevation for the role.
        del accepted_by_role[role]
        accepted_refs[:] = [ref for ref in accepted_refs if ref["artifact_role"] != role]
        return

    seen_events[event_id] = receipt["binding_sha256"]
    if prior is None:
        accepted_by_role[role] = receipt
        accepted_refs.append(
            {
                "access_event_id": event_id,
                "artifact_role": role,
                "binding_sha256": receipt["binding_sha256"],
                "receipt_sha256": receipt["receipt_sha256"],
            }
        )


def _declared_roles(
    answer_compliance: Mapping[str, Any] | None,
    diagnostics: list[dict[str, Any]],
) -> set[str]:
    if answer_compliance is None:
        return set()
    if not isinstance(answer_compliance, Mapping):
        diagnostics.append(
            _diag(
                "invalid_input_field",
                _FAIL,
                "answer_compliance must be a JSON object.",
            )
        )
        return set()
    value = answer_compliance.get("declared_artifacts")
    if value is None:
        return set()
    if isinstance(value, str):
        return {value} if value else set()
    if not isinstance(value, (list, tuple, set, frozenset)):
        diagnostics.append(
            _diag(
                "invalid_input_field",
                _FAIL,
                "declared_artifacts must be an array of non-empty strings.",
            )
        )
        return set()
    roles = {item for item in value if isinstance(item, str) and item}
    if len(roles) != len(list(value)):
        diagnostics.append(
            _diag(
                "invalid_input_field",
                _FAIL,
                "declared_artifacts must contain only non-empty strings.",
            )
        )
    return roles


def _role_set(
    roles: Sequence[str] | None,
    label: str,
    diagnostics: list[dict[str, Any]],
) -> set[str]:
    if roles is None:
        return set()
    if isinstance(roles, str) or not isinstance(roles, Sequence):
        diagnostics.append(
            _diag(
                "invalid_input_field",
                _FAIL,
                f"{label} must be an array of non-empty strings.",
            )
        )
        return set()
    valid = {item for item in roles if isinstance(item, str) and item}
    if len(valid) != len(list(roles)):
        diagnostics.append(
            _diag(
                "invalid_input_field",
                _FAIL,
                f"{label} must contain only non-empty strings.",
            )
        )
    return valid


def _declared_identity_index(
    declared_identities: Mapping[str, Mapping[str, Any]] | None,
    diagnostics: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    if declared_identities is None:
        return {}
    if not isinstance(declared_identities, Mapping):
        diagnostics.append(
            _diag(
                "invalid_input_field",
                _FAIL,
                "declared_identities must be an object keyed by artifact role.",
            )
        )
        return {}
    result: dict[str, dict[str, Any]] = {}
    for role, identity in declared_identities.items():
        if not isinstance(role, str) or not role or not isinstance(identity, Mapping):
            diagnostics.append(
                _diag(
                    "invalid_input_field",
                    _FAIL,
                    "declared_identities entries must map roles to identity objects.",
                    artifact_role=role if isinstance(role, str) else None,
                )
            )
            continue
        path = identity.get("path")
        digest = identity.get("sha256")
        size = identity.get("bytes")
        if (
            not isinstance(path, str)
            or not path
            or not isinstance(digest, str)
            or not isinstance(size, int)
            or isinstance(size, bool)
            or size < 0
        ):
            diagnostics.append(
                _diag(
                    "invalid_input_field",
                    _FAIL,
                    f"declared identity for '{role}' is incomplete.",
                    artifact_role=role,
                )
            )
            continue
        result[role] = {"path": path, "sha256": digest, "bytes": size}
    return result


def _require_bound_str(
    value: Any, label: str, diagnostics: list[dict[str, Any]]
) -> str | None:
    if isinstance(value, str) and value:
        return value
    diagnostics.append(
        _diag(
            "invalid_input_field",
            _FAIL,
            f"{label} must be a non-empty string.",
        )
    )
    return None


def _require_commit(value: Any, diagnostics: list[dict[str, Any]]) -> str | None:
    if isinstance(value, str) and len(value) == _COMMIT_LEN and all(
        ch in "0123456789abcdef" for ch in value
    ):
        return value
    diagnostics.append(
        _diag(
            "invalid_input_field",
            _FAIL,
            "repo_commit must be a 40-character lowercase hex SHA-1.",
        )
    )
    return None


def _normalize_max_age(
    value: int | None, diagnostics: list[dict[str, Any]]
) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        diagnostics.append(
            _diag(
                "invalid_input_field",
                _FAIL,
                "max_age_seconds must be a non-negative integer when provided.",
            )
        )
        return None
    return value


def _parse_as_of(
    value: str | None, diagnostics: list[dict[str, Any]]
) -> datetime | None:
    if value is None:
        return datetime.now(timezone.utc)
    parsed = _parse_timestamp(value)
    if parsed is None:
        diagnostics.append(
            _diag(
                "invalid_input_field",
                _FAIL,
                "as_of must be an ISO-8601 UTC timestamp ending with Z.",
            )
        )
        return datetime.now(timezone.utc)
    return parsed


def _parse_timestamp(value: str) -> datetime | None:
    if not isinstance(value, str) or not value.endswith("Z"):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _maybe_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _maybe_hex(value: Any) -> str | None:
    if isinstance(value, str) and len(value) == 64 and all(
        ch in "0123456789abcdef" for ch in value
    ):
        return value
    return None


def _reject(
    rejected: list[dict[str, Any]],
    diagnostics: list[dict[str, Any]],
    *,
    reason: str,
    code: str,
    detail: str,
    access_event_id: str | None = None,
    artifact_role: str | None = None,
    receipt_sha256: str | None = None,
) -> None:
    item: dict[str, Any] = {"reason": reason, "detail": detail}
    if access_event_id is not None:
        item["access_event_id"] = access_event_id
    if artifact_role is not None:
        item["artifact_role"] = artifact_role
    if receipt_sha256 is not None:
        item["receipt_sha256"] = receipt_sha256
    rejected.append(item)
    # Forgeries and structural invalidity fail closed. Bound mismatches remain
    # explicit diagnostics but never elevate evidence.
    fail_reasons = {
        "privacy_violation",
        "untrusted_issuer",
        "invalid_receipt",
        "binding_mismatch",
    }
    severity = _FAIL if reason in fail_reasons else _WARN
    diagnostics.append(_diag(code, severity, detail, artifact_role=artifact_role))


def _diag(
    code: str,
    severity: str,
    detail: str,
    *,
    artifact_role: str | None = None,
) -> dict[str, Any]:
    item = {"code": code, "severity": severity, "detail": detail}
    if artifact_role is not None:
        item["artifact_role"] = artifact_role
    return item


def _status_from_diagnostics(diagnostics: list[dict[str, Any]]) -> str:
    severities = {item["severity"] for item in diagnostics}
    if _FAIL in severities:
        return "fail"
    if _WARN in severities:
        return "warn"
    return "pass"


def _evidence(
    *,
    task_id: str,
    repo_commit: str,
    comparisons: list[dict[str, Any]],
    accepted_refs: list[dict[str, str]],
    rejected: list[dict[str, Any]],
    diagnostics: list[dict[str, Any]],
) -> dict[str, Any]:
    severity_weight = {"fail": 0, "warn": 1, "info": 2}
    ordered_diagnostics = sorted(
        diagnostics,
        key=lambda d: (
            severity_weight.get(d.get("severity"), 3),
            d["code"],
            d.get("artifact_role", ""),
            d["detail"],
        ),
    )
    ordered_rejected = sorted(
        rejected,
        key=lambda item: (
            item["reason"],
            item.get("artifact_role", ""),
            item.get("access_event_id", ""),
            item["detail"],
        ),
    )
    ordered_refs = sorted(
        accepted_refs,
        key=lambda item: (
            item["artifact_role"],
            item["access_event_id"],
            item["binding_sha256"],
        ),
    )
    ordered_comparisons = sorted(
        comparisons, key=lambda item: item["artifact_role"]
    )
    return {
        "kind": KIND,
        "version": VERSION,
        "task_id": task_id,
        "repo_commit": repo_commit,
        "status": _status_from_diagnostics(ordered_diagnostics),
        "comparisons": ordered_comparisons,
        "accepted_receipt_refs": ordered_refs,
        "rejected_receipts": ordered_rejected,
        "diagnostics": ordered_diagnostics,
        "retention": dict(RETENTION),
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }
