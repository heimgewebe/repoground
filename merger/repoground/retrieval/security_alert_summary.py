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
_DEFINITIVE_STATES = ("clean", "alerts_present")
_UNAUTHORIZED_STATUS_CODES = (401, 403)
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

_DOES_NOT_PROVE = (
    "the absence of code-scanning coverage gaps outside analyzed languages or paths",
    "severity, exploitability, or business impact of any reported alert",
    "that no alert existed before or appears after the evidence was captured",
    "runtime correctness or merge readiness",
    "permission to create issues, patches, commits, pushes, or merges",
)


class SecurityAlertSummaryError(ValueError):
    """Raised when readback evidence cannot be classified safely."""


def _parse_sarif_evidence(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise SecurityAlertSummaryError("sarif_evidence must be an object")
    extra = set(value) - {"available", "alert_count", "repository", "commit_sha", "stale"}
    if extra:
        raise SecurityAlertSummaryError(
            f"sarif_evidence has unsupported fields: {sorted(extra)}"
        )
    if value.get("stale") is True:
        raise SecurityAlertSummaryError("sarif_evidence is marked stale")
    available = value.get("available")
    if not isinstance(available, bool):
        raise SecurityAlertSummaryError("sarif_evidence.available must be a boolean")

    repo = value.get("repository")
    if repo is not None and not isinstance(repo, str):
        raise SecurityAlertSummaryError("sarif_evidence.repository must be a string")

    sha = value.get("commit_sha")
    if sha is not None and not isinstance(sha, str):
        raise SecurityAlertSummaryError("sarif_evidence.commit_sha must be a string")

    if available:
        count = value.get("alert_count")
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise SecurityAlertSummaryError(
                "sarif_evidence.alert_count must be a non-negative integer when available"
            )
        return {
            "available": True,
            "alert_count": count,
            "repository": repo,
            "commit_sha": sha,
            "stale": value.get("stale"),
        }
    if value.get("alert_count") is not None:
        raise SecurityAlertSummaryError(
            "sarif_evidence.alert_count must be omitted or null when unavailable"
        )
    return {
        "available": False,
        "alert_count": None,
        "repository": repo,
        "commit_sha": sha,
        "stale": value.get("stale"),
    }


def _parse_api_evidence(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise SecurityAlertSummaryError("api_evidence must be an object")
    extra = set(value) - {
        "status_code",
        "open_alert_count",
        "repository",
        "commit_sha",
        "paginated",
        "page_count",
        "stale",
    }
    if extra:
        raise SecurityAlertSummaryError(
            f"api_evidence has unsupported fields: {sorted(extra)}"
        )
    if value.get("stale") is True:
        raise SecurityAlertSummaryError("api_evidence is marked stale")

    status = value.get("status_code")
    if isinstance(status, bool) or not isinstance(status, int) or not 100 <= status <= 599:
        raise SecurityAlertSummaryError(
            "api_evidence.status_code must be a valid HTTP status integer"
        )

    repo = value.get("repository")
    if repo is not None and not isinstance(repo, str):
        raise SecurityAlertSummaryError("api_evidence.repository must be a string")

    sha = value.get("commit_sha")
    if sha is not None and not isinstance(sha, str):
        raise SecurityAlertSummaryError("api_evidence.commit_sha must be a string")

    paginated = value.get("paginated")
    if paginated is not None and not isinstance(paginated, bool):
        raise SecurityAlertSummaryError("api_evidence.paginated must be a boolean")

    page_count = value.get("page_count")
    if page_count is not None and (
        isinstance(page_count, bool) or not isinstance(page_count, int) or page_count < 0
    ):
        raise SecurityAlertSummaryError(
            "api_evidence.page_count must be a non-negative integer"
        )

    if status == _OK_STATUS_CODE:
        count = value.get("open_alert_count")
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise SecurityAlertSummaryError(
                "api_evidence.open_alert_count must be a non-negative integer "
                "when status_code is 200"
            )
        return {
            "status_code": status,
            "open_alert_count": count,
            "repository": repo,
            "commit_sha": sha,
            "paginated": paginated,
            "page_count": page_count,
            "stale": value.get("stale"),
        }
    if value.get("open_alert_count") is not None:
        raise SecurityAlertSummaryError(
            "api_evidence.open_alert_count must be omitted or null unless status_code is 200"
        )
    return {
        "status_code": status,
        "open_alert_count": None,
        "repository": repo,
        "commit_sha": sha,
        "paginated": paginated,
        "page_count": page_count,
        "stale": value.get("stale"),
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

    if repository is not None and not isinstance(repository, str):
        raise SecurityAlertSummaryError("repository must be a string")
    if commit_sha is not None and not isinstance(commit_sha, str):
        raise SecurityAlertSummaryError("commit_sha must be a string")

    sarif = _parse_sarif_evidence(sarif_evidence)
    api = _parse_api_evidence(api_evidence)

    # Validate binding consistency across evidence sources
    sarif_repo = sarif.get("repository") if sarif else None
    api_repo = api.get("repository") if api else None
    if sarif_repo is not None and api_repo is not None and sarif_repo != api_repo:
        raise SecurityAlertSummaryError(
            f"Evidence repository mismatch: sarif repository '{sarif_repo}' does not match api repository '{api_repo}'"
        )

    sarif_sha = sarif.get("commit_sha") if sarif else None
    api_sha = api.get("commit_sha") if api else None
    if sarif_sha is not None and api_sha is not None and sarif_sha != api_sha:
        raise SecurityAlertSummaryError(
            f"Evidence commit_sha mismatch: sarif commit_sha '{sarif_sha}' does not match api commit_sha '{api_sha}'"
        )

    effective_repo = repository or sarif_repo or api_repo
    if repository is not None:
        if sarif_repo is not None and sarif_repo != repository:
            raise SecurityAlertSummaryError(
                f"sarif_evidence repository '{sarif_repo}' does not match requested repository '{repository}'"
            )
        if api_repo is not None and api_repo != repository:
            raise SecurityAlertSummaryError(
                f"api_evidence repository '{api_repo}' does not match requested repository '{repository}'"
            )

    effective_sha = commit_sha or sarif_sha or api_sha
    if commit_sha is not None:
        if sarif_sha is not None and sarif_sha != commit_sha:
            raise SecurityAlertSummaryError(
                f"sarif_evidence commit_sha '{sarif_sha}' does not match requested commit_sha '{commit_sha}'"
            )
        if api_sha is not None and api_sha != commit_sha:
            raise SecurityAlertSummaryError(
                f"api_evidence commit_sha '{api_sha}' does not match requested commit_sha '{commit_sha}'"
            )

    sarif_verdict = _sarif_verdict(sarif)
    api_verdict = _api_verdict(api)

    if sarif_verdict is not None and sarif_verdict[0] in _DEFINITIVE_STATES:
        if (
            api_verdict is not None
            and api_verdict[0] in _DEFINITIVE_STATES
            and api_verdict[0] != sarif_verdict[0]
        ):
            state, reason, count = "unknown", "sarif_api_state_disagreement", None
        else:
            state, reason, count = sarif_verdict
        source = "sarif+api" if api_verdict is not None else "sarif"
        return _assemble(state, reason, source, count, sarif, api, effective_repo, effective_sha)

    if api_verdict is not None:
        state, reason, count = api_verdict
        source = "sarif+api" if sarif_verdict is not None else "api"
        return _assemble(state, reason, source, count, sarif, api, effective_repo, effective_sha)

    if sarif_verdict is not None:
        state, reason, count = sarif_verdict
        return _assemble(state, reason, "sarif", count, sarif, api, effective_repo, effective_sha)

    return _assemble("unknown", "no_evidence_supplied", "none", None, sarif, api, effective_repo, effective_sha)


def known_states() -> tuple[str, ...]:
    """Return the closed vocabulary of readback states, in fail-closed order."""

    return _STATES

