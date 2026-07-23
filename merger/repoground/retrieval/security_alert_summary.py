"""Classify GitHub code-scanning security-alert readback evidence.

An external audit that reads a live `GET .../code-scanning/alerts` response
cannot tell "zero alerts" apart from "endpoint unavailable" or "caller
unauthorized" from the HTTP status alone: GitHub returns 404 both when code
scanning is not enabled and when the caller lacks `security-events: read`
access, and a transport failure looks like silence, not a clean bill of
health. Treating any of those as "clean" is a fail-open bug.

This module classifies deterministic, repository-local evidence (the raw
CodeQL SARIF this repository's own CI job already produces) together with
optional live-API evidence into one explicit state. It never invents
"clean" from missing or unreachable evidence; when nothing is supplied, or
independently classified sources disagree, the result fails closed to
"unknown".
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

_STATES = ("clean", "alerts_present", "unavailable", "unauthorized", "unknown")
_DEFINITIVE_STATES = frozenset({"clean", "alerts_present"})
_UNAUTHORIZED_STATUS_CODES = frozenset({401, 403})
_OK_STATUS_CODE = 200

_REQUIRED_PERMISSIONS = {
    "sarif": (
        "none beyond the analysis job's existing 'contents: read'. Reads "
        "job-local CodeQL SARIF output already produced by "
        "github/codeql-action/analyze in the same job; no network call, no "
        "additional token scope."
    ),
    "api": (
        "security-events: read (least privilege, read-only). Never request "
        "security-events: write for a readback; write scope is only needed "
        "to upload SARIF, not to read alert state."
    ),
}

_SARIF_ALLOWED_FIELDS = frozenset({"available", "alert_count", "repository", "commit_sha", "stale"})
_API_ALLOWED_FIELDS = frozenset({"status_code", "open_alert_count", "repository", "commit_sha", "paginated", "page_count", "stale"})

_DOES_NOT_PROVE = (
    "the absence of code-scanning coverage gaps outside analyzed languages or paths",
    "severity, exploitability, or business impact of any reported alert",
    "that no alert existed before or appears after the evidence was captured",
    "runtime correctness or merge readiness",
    "permission to create issues, patches, commits, pushes, or merges",
)


class SecurityAlertSummaryError(ValueError):
    """Raised when readback evidence cannot be classified safely."""


def _require_evidence_mapping(
    value: Any, *, name: str, allowed_fields: set[str] | frozenset[str]
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SecurityAlertSummaryError(f"{name} must be an object")
    extra = set(value) - allowed_fields
    if extra:
        raise SecurityAlertSummaryError(
            f"{name} has unsupported fields: {sorted(extra)}"
        )
    return value


def _optional_string(value: Any, *, field: str, name: str) -> str | None:
    if value is not None and not isinstance(value, str):
        raise SecurityAlertSummaryError(f"{name}.{field} must be a string")
    return value


def _optional_bool(value: Any, *, field: str, name: str) -> bool | None:
    if value is not None and not isinstance(value, bool):
        raise SecurityAlertSummaryError(f"{name}.{field} must be a boolean")
    return value


def _non_negative_int(value: Any, *, field: str, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SecurityAlertSummaryError(
            f"{name}.{field} must be a non-negative integer"
        )
    return value


def _evidence_identity(
    value: Mapping[str, Any], *, name: str
) -> tuple[str | None, str | None]:
    return (
        _optional_string(value.get("repository"), field="repository", name=name),
        _optional_string(value.get("commit_sha"), field="commit_sha", name=name),
    )


def _parse_sarif_evidence(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    evidence = _require_evidence_mapping(
        value,
        name="sarif_evidence",
        allowed_fields=_SARIF_ALLOWED_FIELDS,
    )
    available = evidence.get("available")
    if not isinstance(available, bool):
        raise SecurityAlertSummaryError("sarif_evidence.available must be a boolean")
    repo, sha = _evidence_identity(evidence, name="sarif_evidence")
    stale = _optional_bool(evidence.get("stale"), field="stale", name="sarif_evidence")
    if stale is True:
        raise SecurityAlertSummaryError("sarif_evidence is marked stale (evidence may be from previous commit)")
    count = evidence.get("alert_count")
    if available:
        count = _non_negative_int(
            count, field="alert_count", name="sarif_evidence"
        )
    elif count is not None:
        raise SecurityAlertSummaryError(
            "sarif_evidence.alert_count must be omitted or null when unavailable"
        )
    return {
        "available": available,
        "alert_count": count,
        "repository": repo,
        "commit_sha": sha,
        "stale": stale,
    }


def _valid_http_status(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 100 <= value <= 599:
        raise SecurityAlertSummaryError(
            "api_evidence.status_code must be a valid HTTP status integer"
        )
    return value


def _parse_api_evidence(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    evidence = _require_evidence_mapping(
        value,
        name="api_evidence",
        allowed_fields=_API_ALLOWED_FIELDS,
    )
    status = _valid_http_status(evidence.get("status_code"))
    repo, sha = _evidence_identity(evidence, name="api_evidence")
    stale = _optional_bool(evidence.get("stale"), field="stale", name="api_evidence")
    if stale is True:
        raise SecurityAlertSummaryError("api_evidence is marked stale (evidence may be from previous commit)")
    paginated = _optional_bool(
        evidence.get("paginated"), field="paginated", name="api_evidence"
    )
    page_count = evidence.get("page_count")
    if page_count is not None:
        page_count = _non_negative_int(
            page_count, field="page_count", name="api_evidence"
        )
    count = evidence.get("open_alert_count")
    if status == _OK_STATUS_CODE:
        count = _non_negative_int(
            count, field="open_alert_count", name="api_evidence"
        )
    elif count is not None:
        raise SecurityAlertSummaryError(
            "api_evidence.open_alert_count must be omitted or null unless status_code is 200"
        )
    return {
        "status_code": status,
        "open_alert_count": count,
        "repository": repo,
        "commit_sha": sha,
        "paginated": paginated,
        "page_count": page_count,
        "stale": stale,
    }


def _sarif_verdict(sarif: dict[str, Any] | None) -> tuple[str, str, int | None] | None:
    if sarif is None:
        return None
    if not sarif["available"]:
        return ("unavailable", "sarif_unavailable", None)
    count = sarif["alert_count"]
    state = "clean" if count == 0 else "alerts_present"
    return (state, "sarif_result_count", count)


def _api_verdict(api: dict[str, Any] | None) -> tuple[str, str, int | None] | None:
    if api is None:
        return None
    status = api["status_code"]
    if status == _OK_STATUS_CODE:
        count = api["open_alert_count"]
        if count > 0:
            # One observed open alert is already definitive; incomplete pagination
            # can only mean the true count is larger, never zero.
            return ("alerts_present", "api_result_count", count)
        if api.get("paginated") is True:
            return ("clean", "api_result_count", 0)
        # A zero-length page without proof that pagination was exhausted cannot
        # establish absence of open alerts. Fail closed instead of treating it as clean.
        return ("unknown", "api_zero_count_pagination_unproven", None)
    if status in _UNAUTHORIZED_STATUS_CODES:
        return ("unauthorized", "api_unauthorized", None)
    # Covers 404 (GitHub returns 404 both for "code scanning disabled" and
    # "caller lacks security-events:read"; the two are indistinguishable
    # from the status code alone) and any other non-200/401/403 response,
    # including transport-level failures a caller may map to a status.
    return ("unavailable", "api_unavailable", None)


def _assemble(
    state: str,
    reason: str,
    source: str,
    alert_count: int | None,
    sarif: dict[str, Any] | None,
    api: dict[str, Any] | None,
    repository: str | None = None,
    commit_sha: str | None = None,
) -> dict[str, Any]:
    return {
        "version": "security_alert_summary.v1",
        "authority": "diagnostic_signal",
        "risk_class": "diagnostic",
        "state": state,
        "state_reason": reason,
        "evidence_source": source,
        "alert_count": alert_count,
        "fail_closed": state != "clean",
        "repository": repository,
        "commit_sha": commit_sha,
        "sarif_evidence": sarif,
        "api_evidence": api,
        "required_permissions": dict(_REQUIRED_PERMISSIONS),
        "does_not_prove": list(_DOES_NOT_PROVE),
    }


def _validate_cross_source_binding(
    sarif: dict[str, Any] | None, api: dict[str, Any] | None
) -> None:
    if sarif is None or api is None:
        return
    for field in ("repository", "commit_sha"):
        left = sarif.get(field)
        right = api.get(field)
        if left is not None and right is not None and left != right:
            raise SecurityAlertSummaryError(
                f"Evidence {field} mismatch: sarif {field} '{left}' does not match "
                f"api {field} '{right}'"
            )


def _validate_requested_binding(
    evidence: dict[str, Any] | None,
    *,
    source: str,
    repository: str | None,
    commit_sha: str | None,
) -> None:
    if evidence is None:
        return
    for field, expected in (("repository", repository), ("commit_sha", commit_sha)):
        actual = evidence.get(field)
        if expected is not None and actual is not None and actual != expected:
            raise SecurityAlertSummaryError(
                f"{source}_evidence {field} '{actual}' does not match requested "
                f"{field} '{expected}'"
            )


def _effective_binding(
    requested: str | None,
    sarif: dict[str, Any] | None,
    api: dict[str, Any] | None,
    field: str,
) -> str | None:
    if requested is not None:
        return requested
    if sarif is not None and sarif.get(field) is not None:
        return sarif.get(field)
    if api is not None and api.get(field) is not None:
        return api.get(field)
    return None


def _resolve_verdict(
    sarif_verdict: tuple[str, str, int | None] | None,
    api_verdict: tuple[str, str, int | None] | None,
) -> tuple[str, str, int | None, str]:
    if sarif_verdict is not None and sarif_verdict[0] in _DEFINITIVE_STATES:
        disagreement = (
            api_verdict is not None
            and api_verdict[0] in _DEFINITIVE_STATES
            and api_verdict[0] != sarif_verdict[0]
        )
        state, reason, count = (
            ("unknown", "sarif_api_state_disagreement", None)
            if disagreement
            else sarif_verdict
        )
        source = "sarif+api" if disagreement or (api_verdict is not None and api_verdict[0] in _DEFINITIVE_STATES) else "sarif"
        return state, reason, count, source
    if api_verdict is not None:
        state, reason, count = api_verdict
        return state, reason, count, "sarif+api" if sarif_verdict is not None else "api"
    if sarif_verdict is not None:
        state, reason, count = sarif_verdict
        return state, reason, count, "sarif"
    return "unknown", "no_evidence_supplied", None, "none"


def classify_security_alert_state(
    *,
    sarif_evidence: Mapping[str, Any] | None = None,
    api_evidence: Mapping[str, Any] | None = None,
    repository: str | None = None,
    commit_sha: str | None = None,
) -> dict[str, Any]:
    """Classify security-alert readback evidence into one explicit state.

    Repository-local SARIF evidence is authoritative whenever it resolves to
    a definitive state (clean or alerts_present): it is deterministic,
    CI-produced, and needs no additional permission or network call. Live
    API evidence is used to fill gaps when SARIF evidence is absent or
    unavailable, and to positively confirm agreement; a disagreement between
    two definitive sources fails closed to "unknown" rather than picking
    one silently. Supplying neither source fails closed to "unknown" rather
    than "clean".
    """

    repository = _optional_string(repository, field="repository", name="request")
    commit_sha = _optional_string(commit_sha, field="commit_sha", name="request")
    sarif = _parse_sarif_evidence(sarif_evidence)
    api = _parse_api_evidence(api_evidence)
    _validate_cross_source_binding(sarif, api)
    _validate_requested_binding(
        sarif, source="sarif", repository=repository, commit_sha=commit_sha
    )
    _validate_requested_binding(
        api, source="api", repository=repository, commit_sha=commit_sha
    )
    effective_repo = _effective_binding(repository, sarif, api, "repository")
    effective_sha = _effective_binding(commit_sha, sarif, api, "commit_sha")
    state, reason, count, source = _resolve_verdict(
        _sarif_verdict(sarif), _api_verdict(api)
    )
    return _assemble(
        state, reason, source, count, sarif, api, effective_repo, effective_sha
    )


def known_states() -> tuple[str, ...]:
    """Return the closed vocabulary of readback states, in fail-closed order."""

    return _STATES

