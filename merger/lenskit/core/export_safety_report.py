from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

_DOES_NOT_ESTABLISH = [
    "claims_true",
    "answer_safe_without_citations",
    "repo_understood",
    "runtime_correctness",
    "test_sufficiency",
    "regression_absence",
    "forensic_ready",
    "secret_absence",
    "pii_absence",
]


def _as_dict(value: Any) -> Dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    return None


def _bool_or_none(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    return None


def _str_or_none(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    return None


def _observe_redaction(post_emit_health: Any, output_health: Any) -> Tuple[bool | None, str | None]:
    peh = _as_dict(post_emit_health)
    if peh:
        rs = _as_dict(peh.get("redaction_status"))
        if rs is not None:
            enabled = _bool_or_none(rs.get("redact_secrets_enabled"))
            if enabled is not None:
                return enabled, "post_emit_health"

    oh = _as_dict(output_health)
    if oh:
        checks = _as_dict(oh.get("checks"))
        if checks is not None:
            enabled = _bool_or_none(checks.get("redact_secrets_enabled"))
            if enabled is not None:
                return enabled, "output_health"

        enabled = _bool_or_none(oh.get("redact_secrets_enabled"))
        if enabled is not None:
            return enabled, "output_health"

    return None, None


_KNOWN_POST_EMIT_STATUSES = {"pass", "warn", "fail", "error", "missing", "blocked"}
_AGENT_FACING_PROFILES = {"agent_minimal", "agent-portable", "agent-safe"}


def _post_emit_status(post_emit_health: Any) -> str:
    peh = _as_dict(post_emit_health)
    if not peh:
        return "missing"
    status = _str_or_none(peh.get("status"))
    if not status:
        return "missing"
    if status not in _KNOWN_POST_EMIT_STATUSES:
        return "error"
    return status


def _agent_gate_status(agent_export_gate: Any) -> str | None:
    gate = _as_dict(agent_export_gate)
    if not gate:
        return None
    return _str_or_none(gate.get("status"))


def _gate_passed(agent_export_gate: Any) -> bool:
    gate = _as_dict(agent_export_gate)
    if not gate:
        return False
    status = _str_or_none(gate.get("status"))
    errors = gate.get("errors")
    if isinstance(errors, list) and len(errors) > 0:
        return False
    if status in {"fail", "blocked", "error"}:
        return False
    return status == "pass"


def build_export_safety_report(
    *,
    profile: str,
    post_emit_health: Optional[Dict[str, Any]] = None,
    output_health: Optional[Dict[str, Any]] = None,
    agent_export_gate: Optional[Dict[str, Any]] = None,
    agent_facing: Optional[bool] = None,
    public_facing: Optional[bool] = None,
) -> Dict[str, Any]:
    errors: List[str] = []
    warnings: List[str] = []
    checks: List[Dict[str, Any]] = []

    profile_known = False

    # Defaults
    agent_facing_val = False
    public_facing_val = False
    redaction_required = False
    post_emit_health_required = False
    agent_export_gate_required = False

    if profile == "local-private":
        profile_known = True
        agent_facing_val = False
        public_facing_val = False
    elif profile == "debug-full":
        profile_known = True
        agent_facing_val = False
        public_facing_val = False
    elif profile in _AGENT_FACING_PROFILES:
        profile_known = True
        agent_facing_val = True
        public_facing_val = False
        redaction_required = True
        post_emit_health_required = True
        agent_export_gate_required = True
    elif profile == "public-share":
        profile_known = True
        agent_facing_val = False
        public_facing_val = True
        redaction_required = True
        post_emit_health_required = True
        agent_export_gate_required = True
    elif profile == "ci-artifact":
        profile_known = True
        agent_facing_val = True
        public_facing_val = False
        redaction_required = True
        post_emit_health_required = True
        agent_export_gate_required = True
    else:
        profile_known = False
        errors.append(f"unknown_profile:{profile}")

    if agent_facing is not None:
        agent_facing_val = agent_facing
    if public_facing is not None:
        public_facing_val = public_facing

    if agent_facing_val or public_facing_val:
        redaction_required = True
        post_emit_health_required = True
        agent_export_gate_required = True

    checks.append(
        {
            "name": "profile_known",
            "status": "pass" if profile_known else "fail",
            "detail": f"Profile '{profile}' is {'known' if profile_known else 'unknown'}",
        }
    )

    if profile == "debug-full":
        if agent_facing_val:
            errors.append("debug_full_cannot_be_agent_facing")
        if public_facing_val:
            errors.append("debug_full_cannot_be_public_facing")

    redaction_observed, redaction_source = _observe_redaction(post_emit_health, output_health)
    post_emit_doc = _as_dict(post_emit_health)
    raw_post_emit_status = _str_or_none(post_emit_doc.get("status")) if post_emit_doc else None
    post_emit_status = _post_emit_status(post_emit_health)
    post_emit_unknown_status = (
        raw_post_emit_status is not None
        and raw_post_emit_status not in _KNOWN_POST_EMIT_STATUSES
    )

    if post_emit_unknown_status and post_emit_health_required:
        errors.append(f"post_emit_health_unknown_status:{raw_post_emit_status}")

    agent_gate_status = _agent_gate_status(agent_export_gate)

    if redaction_required:
        if redaction_observed is not True:
            errors.append("redaction_required_but_not_observed")
            checks.append(
                {
                    "name": "redaction_observed",
                    "status": "fail",
                    "detail": "redaction is required but not observed as true",
                }
            )
        else:
            checks.append(
                {
                    "name": "redaction_observed",
                    "status": "pass",
                    "detail": "redaction is required and observed",
                }
            )
    else:
        checks.append(
            {
                "name": "redaction_observed",
                "status": "not_applicable",
                "detail": "redaction is not required",
            }
        )

    if post_emit_health_required:
        if post_emit_status != "pass":
            errors.append("post_emit_health_required_but_missing_or_not_pass")
            detail = f"post_emit_health is required for profile {profile} but status is {post_emit_status}"
            if post_emit_unknown_status:
                detail = f"post_emit_health is required for profile {profile} but raw status '{raw_post_emit_status}' is unknown and normalized to error"
                
            checks.append(
                {
                    "name": "post_emit_health_status",
                    "status": "fail",
                    "detail": detail,
                }
            )
        else:
            checks.append(
                {
                    "name": "post_emit_health_status",
                    "status": "pass",
                    "detail": "post_emit_health is pass",
                }
            )
    else:
        checks.append(
            {
                "name": "post_emit_health_status",
                "status": "not_applicable",
                "detail": "post_emit_health is not required",
            }
        )

    if agent_export_gate_required:
        if not _gate_passed(agent_export_gate):
            errors.append("agent_export_gate_required_but_missing_or_not_pass")
            checks.append(
                {
                    "name": "agent_export_gate_status",
                    "status": "fail",
                    "detail": f"agent_export_gate is required but status is {agent_gate_status}",
                }
            )
        else:
            checks.append(
                {
                    "name": "agent_export_gate_status",
                    "status": "pass",
                    "detail": "agent_export_gate is pass",
                }
            )
    else:
        checks.append(
            {
                "name": "agent_export_gate_status",
                "status": "not_applicable",
                "detail": "agent_export_gate is not required",
            }
        )

    if errors:
        status = "fail"
    elif warnings:
        status = "warn"
    else:
        status = "pass"

    return {
        "kind": "lenskit.export_safety_report",
        "version": "1.0",
        "profile": profile,
        "profile_known": profile_known,
        "agent_facing": agent_facing_val,
        "public_facing": public_facing_val,
        "redaction_required": redaction_required,
        "redaction_observed": redaction_observed,
        "redaction_source": redaction_source,
        "post_emit_health_required": post_emit_health_required,
        "post_emit_health_status": post_emit_status,
        "agent_export_gate_required": agent_export_gate_required,
        "agent_export_gate_status": agent_gate_status,
        "status": status,
        "checks": checks,
        "warnings": warnings,
        "errors": errors,
        "does_not_establish": list(_DOES_NOT_ESTABLISH),
    }
