"""Agent Consumption Trace validator.

Pure, deterministic comparison of Required Reading Protocol expectations (the
"should") against an Answer Compliance declaration (what the answer claims to
have used). The result is a machine-readable Agent Consumption Trace.

Strict separation of layers:

* Required Reading Protocol = expectation: which artifacts are required or
  recommended for a task profile.
* Answer Compliance = declaration: what the answer claims it used, did not use,
  or could not verify.
* Agent Consumption Trace = comparison: does the declaration formally line up
  with the expectation?

This module performs no I/O, holds no global state, and imports nothing from the
service / CLI layers. It makes no truth claim. It does not prove actual reading,
answer correctness, repo understanding, complete context use, runtime behavior,
test sufficiency, regression absence, forensic readiness, or claim truth. It
only reports whether a declared self-report formally matches the required-
reading expectation.
"""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy


KIND = "lenskit.agent_consumption_trace"
VERSION = "1.0"

# The nine boundaries this trace explicitly does not establish.
# Mirrors answer-compliance.v1 does_not_establish exactly.
DOES_NOT_ESTABLISH: tuple[str, ...] = (
    "actual_reading_proven",
    "answer_correct",
    "repo_understood",
    "all_relevant_context_used",
    "claims_true",
    "test_sufficiency",
    "regression_absence",
    "runtime_behavior",
    "forensic_ready",
)
_DOES_NOT_ESTABLISH_SET = frozenset(DOES_NOT_ESTABLISH)

_FAIL = "fail"
_WARN = "warn"
_INFO = "info"
_RESOLVED_STATUSES = frozenset({"pass", "warn", "fail", "not_applicable"})
_ROLE_CONTAINERS = (list, tuple, set, frozenset)


def validate_agent_consumption(
    required_reading_result: dict,
    answer_compliance: dict,
    *,
    available_roles: set[str] | None = None,
) -> dict:
    """Compare Required Reading expectations with an Answer Compliance claim.

    The function remains a comparison layer rather than a second full JSON
    Schema validator. It does, however, normalise its narrow input boundary so
    malformed fields cannot crash the comparison or make its own output violate
    the trace schema's basic types.
    """
    diagnostics: list[dict] = []
    rr = _input_mapping(required_reading_result, "required_reading_result", diagnostics)
    ac = _input_mapping(answer_compliance, "answer_compliance", diagnostics)

    rr_profile = _task_profile(rr.get("task_profile"), "required reading", diagnostics)
    ac_profile = _task_profile(ac.get("task_profile"), "answer compliance", diagnostics)
    task_profile = rr_profile or ac_profile or "unknown"
    resolved_status = _resolved_status(rr.get("status"), diagnostics)

    required_artifacts = _required_role_list(rr, "required", diagnostics)
    recommended_artifacts = _required_role_list(rr, "recommended", diagnostics)
    declared_artifacts = _required_role_list(ac, "declared_artifacts", diagnostics)
    unread_required = _role_list(
        ac.get("unread_required_artifacts"),
        "unread_required_artifacts",
        diagnostics,
    )
    unread_recommended = _role_list(
        ac.get("unread_recommended_artifacts"),
        "unread_recommended_artifacts",
        diagnostics,
    )

    # These declarations are comparison payload, not evidence. Deep copies
    # prevent later mutation of either input or trace from rewriting the other.
    declared_citations = _object_list(
        ac.get("declared_citations"), "declared_citations", diagnostics
    )
    declared_ranges = _object_list(
        ac.get("declared_ranges"), "declared_ranges", diagnostics
    )
    epistemic_gaps = _object_list(
        ac.get("epistemic_gaps"), "epistemic_gaps", diagnostics
    )

    if not _has_exact_negative_semantics(ac):
        diagnostics.append(
            _diag(
                "missing_negative_semantics",
                _FAIL,
                "Answer compliance does_not_establish must contain exactly the "
                "nine required boundaries.",
            )
        )

    diagnostics.extend(
        _declaration_consistency_diagnostics(
            declared_artifacts,
            unread_required,
            unread_recommended,
        )
    )

    # No Soll/Ist comparison is meaningful without an applicable profile.
    # Input and declaration invariants above still remain fail-closed.
    if resolved_status == "not_applicable":
        diagnostics.append(
            _diag(
                "task_profile_not_applicable",
                _INFO,
                f"No applicable task profile could be resolved for '{task_profile}'.",
            )
        )
        status = (
            "fail"
            if any(d["severity"] == _FAIL for d in diagnostics)
            else "not_applicable"
        )
        return _trace(
            task_profile=task_profile,
            status=status,
            required_artifacts=required_artifacts,
            recommended_artifacts=recommended_artifacts,
            declared_artifacts=declared_artifacts,
            missing_required_artifacts=[],
            missing_recommended_artifacts=[],
            unknown_declared_artifacts=[],
            unread_required_artifacts=unread_required,
            unread_recommended_artifacts=unread_recommended,
            declared_citations=declared_citations,
            declared_ranges=declared_ranges,
            epistemic_gaps=epistemic_gaps,
            diagnostics=diagnostics,
        )

    if rr_profile is not None and ac_profile is not None and ac_profile != rr_profile:
        diagnostics.append(
            _diag(
                "task_profile_mismatch",
                _FAIL,
                f"Answer compliance declared task profile '{ac_profile}' but "
                f"required reading resolved '{rr_profile}'.",
            )
        )

    declared_set = set(declared_artifacts)
    unread_required_set = set(unread_required)
    unread_recommended_set = set(unread_recommended)
    required_set = set(required_artifacts)
    recommended_set = set(recommended_artifacts)

    diagnostics.extend(
        _unexpected_unread_diagnostics(
            unread_required_set,
            unread_recommended_set,
            required_set,
            recommended_set,
        )
    )

    missing_required_artifacts, required_diagnostics = _expected_artifact_result(
        required_artifacts,
        declared_set,
        unread_required_set,
        severity=_FAIL,
        missing_code="missing_required_artifact",
        unread_code="unread_required_artifact",
        expectation="Required",
    )
    diagnostics.extend(required_diagnostics)

    missing_recommended_artifacts, recommended_diagnostics = _expected_artifact_result(
        recommended_artifacts,
        declared_set,
        unread_recommended_set,
        severity=_WARN,
        missing_code="missing_recommended_artifact",
        unread_code="unread_recommended_artifact",
        expectation="Recommended",
    )
    diagnostics.extend(recommended_diagnostics)

    known_roles = required_set | recommended_set
    if available_roles is not None:
        known_roles |= {x for x in available_roles if isinstance(x, str) and x}
    unknown_declared_artifacts, unknown_diagnostics = _unknown_declared_result(
        declared_artifacts, known_roles
    )
    diagnostics.extend(unknown_diagnostics)

    return _trace(
        task_profile=task_profile,
        status=_status_from_diagnostics(diagnostics),
        required_artifacts=required_artifacts,
        recommended_artifacts=recommended_artifacts,
        declared_artifacts=declared_artifacts,
        missing_required_artifacts=missing_required_artifacts,
        missing_recommended_artifacts=missing_recommended_artifacts,
        unknown_declared_artifacts=unknown_declared_artifacts,
        unread_required_artifacts=unread_required,
        unread_recommended_artifacts=unread_recommended,
        declared_citations=declared_citations,
        declared_ranges=declared_ranges,
        epistemic_gaps=epistemic_gaps,
        diagnostics=diagnostics,
    )


def _input_mapping(value, label: str, diagnostics: list[dict]) -> dict:
    if isinstance(value, Mapping):
        return dict(value)
    diagnostics.append(
        _diag(
            "invalid_input_field",
            _FAIL,
            f"{label} must be a JSON object.",
        )
    )
    return {}


def _task_profile(value, label: str, diagnostics: list[dict]) -> str | None:
    if isinstance(value, str) and value:
        return value
    diagnostics.append(
        _diag(
            "invalid_input_field",
            _FAIL,
            f"{label} task_profile must be a non-empty string.",
        )
    )
    return None


def _resolved_status(value, diagnostics: list[dict]) -> str | None:
    if isinstance(value, str) and value in _RESOLVED_STATUSES:
        return value
    diagnostics.append(
        _diag(
            "invalid_input_field",
            _FAIL,
            "Required reading status must be one of pass, warn, fail, or "
            "not_applicable.",
        )
    )
    return None


def _required_role_list(
    source: Mapping,
    field: str,
    diagnostics: list[dict],
) -> list[str]:
    if field not in source:
        diagnostics.append(
            _diag(
                "invalid_input_field",
                _FAIL,
                f"Required comparison field '{field}' is missing.",
            )
        )
        return []
    if source[field] is None:
        return _invalid_role_list(field, diagnostics)
    return _role_list(source[field], field, diagnostics)


def _role_list(value, field: str, diagnostics: list[dict]) -> list[str]:
    """Return sorted unique non-empty role strings without raising.

    A scalar string remains a compatibility shorthand for one role. Other
    scalar values and mappings are rejected instead of string-coerced.
    """
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else _invalid_role_list(field, diagnostics)
    if not isinstance(value, _ROLE_CONTAINERS):
        return _invalid_role_list(field, diagnostics)

    valid_roles = [x for x in value if isinstance(x, str) and x]
    if len(valid_roles) != len(value):
        diagnostics.append(
            _diag(
                "invalid_input_field",
                _FAIL,
                f"{field} must contain only non-empty strings; invalid entries were ignored.",
            )
        )
    return sorted(set(valid_roles))


def _invalid_role_list(field: str, diagnostics: list[dict]) -> list[str]:
    diagnostics.append(
        _diag(
            "invalid_input_field",
            _FAIL,
            f"{field} must be an array of non-empty strings.",
        )
    )
    return []


def _object_list(value, field: str, diagnostics: list[dict]) -> list[dict]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        diagnostics.append(
            _diag(
                "invalid_input_field",
                _FAIL,
                f"{field} must be an array of objects.",
            )
        )
        return []
    valid = [item for item in value if isinstance(item, dict)]
    if len(valid) != len(value):
        diagnostics.append(
            _diag(
                "invalid_input_field",
                _FAIL,
                f"{field} must contain only objects; invalid entries were ignored.",
            )
        )
    return deepcopy(valid)


def _has_exact_negative_semantics(answer_compliance: dict) -> bool:
    value = answer_compliance.get("does_not_establish")
    if not isinstance(value, (list, tuple)) or not all(
        isinstance(item, str) for item in value
    ):
        return False
    return set(value) == _DOES_NOT_ESTABLISH_SET and len(value) == len(
        DOES_NOT_ESTABLISH
    )


def _declaration_consistency_diagnostics(
    declared_artifacts: list[str],
    unread_required: list[str],
    unread_recommended: list[str],
) -> list[dict]:
    declared = set(declared_artifacts)
    unread_required_set = set(unread_required)
    unread_recommended_set = set(unread_recommended)
    diagnostics = []

    for role in sorted(declared & (unread_required_set | unread_recommended_set)):
        diagnostics.append(
            _diag(
                "contradictory_artifact_declaration",
                _FAIL,
                f"Artifact '{role}' was declared both read and unread.",
                artifact=role,
            )
        )
    for role in sorted(unread_required_set & unread_recommended_set):
        diagnostics.append(
            _diag(
                "contradictory_artifact_declaration",
                _FAIL,
                f"Artifact '{role}' was classified as both required-unread and "
                "recommended-unread.",
                artifact=role,
            )
        )
    return diagnostics


def _unexpected_unread_diagnostics(
    unread_required: set[str],
    unread_recommended: set[str],
    required: set[str],
    recommended: set[str],
) -> list[dict]:
    diagnostics = []
    for role in sorted(unread_required - required):
        diagnostics.append(
            _diag(
                "unexpected_unread_artifact",
                _FAIL,
                f"Artifact '{role}' was declared required-unread but is not "
                "required by the resolved profile.",
                artifact=role,
            )
        )
    for role in sorted(unread_recommended - recommended):
        diagnostics.append(
            _diag(
                "unexpected_unread_artifact",
                _FAIL,
                f"Artifact '{role}' was declared recommended-unread but is not "
                "recommended by the resolved profile.",
                artifact=role,
            )
        )
    return diagnostics


def _expected_artifact_result(
    expected: list[str],
    declared: set[str],
    unread: set[str],
    *,
    severity: str,
    missing_code: str,
    unread_code: str,
    expectation: str,
) -> tuple[list[str], list[dict]]:
    missing = []
    diagnostics = []
    for role in expected:
        if role in unread:
            diagnostics.append(
                _diag(
                    unread_code,
                    severity,
                    f"{expectation} artifact '{role}' was declared unread.",
                    artifact=role,
                )
            )
        elif role not in declared:
            missing.append(role)
            diagnostics.append(
                _diag(
                    missing_code,
                    severity,
                    f"{expectation} artifact '{role}' was not declared.",
                    artifact=role,
                )
            )
    return missing, diagnostics


def _unknown_declared_result(
    declared_artifacts: list[str], known_roles: set[str]
) -> tuple[list[str], list[dict]]:
    unknown = [role for role in declared_artifacts if role not in known_roles]
    diagnostics = [
        _diag(
            "unknown_declared_artifact",
            _WARN,
            f"Declared artifact '{role}' is not a known required, recommended, "
            "or available role.",
            artifact=role,
        )
        for role in unknown
    ]
    return unknown, diagnostics


def _status_from_diagnostics(diagnostics: list[dict]) -> str:
    severities = {item["severity"] for item in diagnostics}
    if _FAIL in severities:
        return "fail"
    if _WARN in severities:
        return "warn"
    return "pass"


def _diag(code: str, severity: str, detail: str, *, artifact: str | None = None) -> dict:
    diagnostic = {"code": code, "severity": severity, "detail": detail}
    if artifact is not None:
        diagnostic["artifact"] = artifact
    return diagnostic


def _trace(
    *,
    task_profile: str,
    status: str,
    required_artifacts: list[str],
    recommended_artifacts: list[str],
    declared_artifacts: list[str],
    missing_required_artifacts: list[str],
    missing_recommended_artifacts: list[str],
    unknown_declared_artifacts: list[str],
    unread_required_artifacts: list[str],
    unread_recommended_artifacts: list[str],
    declared_citations: list,
    declared_ranges: list,
    epistemic_gaps: list,
    diagnostics: list[dict],
) -> dict:
    severity_weight = {"fail": 0, "warn": 1, "info": 2}
    ordered_diagnostics = sorted(
        diagnostics,
        key=lambda d: (
            severity_weight.get(d.get("severity"), 3),
            d["code"],
            d.get("artifact", ""),
            d["detail"],
        ),
    )
    return {
        "kind": KIND,
        "version": VERSION,
        "task_profile": task_profile,
        "status": status,
        "required_artifacts": required_artifacts,
        "recommended_artifacts": recommended_artifacts,
        "declared_artifacts": declared_artifacts,
        "missing_required_artifacts": missing_required_artifacts,
        "missing_recommended_artifacts": missing_recommended_artifacts,
        "unknown_declared_artifacts": unknown_declared_artifacts,
        "unread_required_artifacts": unread_required_artifacts,
        "unread_recommended_artifacts": unread_recommended_artifacts,
        "declared_citations": declared_citations,
        "declared_ranges": declared_ranges,
        "epistemic_gaps": epistemic_gaps,
        "diagnostics": ordered_diagnostics,
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }
