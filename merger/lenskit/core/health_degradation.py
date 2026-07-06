from __future__ import annotations

from typing import Any, Iterable

HEALTH_STATUS_MODEL = (
    "pass",
    "warn",
    "fail",
    "degraded",
    "not_applicable",
)

DEGRADATION_CLASSES = (
    "jsonschema_unavailable",
    "schema_validation_skipped",
    "range_strict_unavailable",
    "claim_evidence_validation_skipped",
    "environment_degraded",
    "profile_skipped",
)

_DOES_NOT_ESTABLISH = (
    "runtime_correctness",
    "test_sufficiency",
    "review_completeness",
    "forensic_readiness",
)


def degradation_item(
    degradation_class: str,
    status: str,
    reason: str,
    *,
    check: str | None = None,
) -> dict[str, Any]:
    if degradation_class not in DEGRADATION_CLASSES:
        raise ValueError(f"unknown degradation class: {degradation_class}")
    if status not in HEALTH_STATUS_MODEL:
        raise ValueError(f"unknown health degradation status: {status}")
    result: dict[str, Any] = {
        "class": degradation_class,
        "status": status,
        "reason": reason,
    }
    if check is not None:
        result["check"] = check
    return result


def degradation_summary(items: Iterable[dict[str, Any]]) -> dict[str, Any]:
    materialized = list(items)
    statuses = {str(item.get("status")) for item in materialized}
    if "fail" in statuses:
        status = "fail"
    elif "degraded" in statuses:
        status = "degraded"
    elif "warn" in statuses:
        status = "warn"
    elif materialized and statuses == {"not_applicable"}:
        status = "not_applicable"
    else:
        status = "pass"
    return {
        "status": status,
        "status_model": list(HEALTH_STATUS_MODEL),
        "classes": sorted({str(item.get("class")) for item in materialized}),
        "items": materialized,
        "does_not_establish": list(_DOES_NOT_ESTABLISH),
    }
