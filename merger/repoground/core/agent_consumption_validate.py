"""Agent Consumption Trace validator.

Pure, deterministic comparison of Required Reading Protocol expectations (the
"should") against an Answer Compliance declaration (what the answer claims to
have used).  The result is a machine-readable Agent Consumption Trace.

Strict separation of layers:

* Required Reading Protocol = expectation: which artifacts are required or
  recommended for a task profile.
* Answer Compliance = declaration: what the answer claims it used, did not use,
  or could not verify.
* Agent Consumption Trace = comparison: does the declaration formally line up
  with the expectation?

This module performs no I/O, holds no global state, and imports nothing from the
service / CLI layers.  It makes no truth claim.  It does not prove actual
reading, answer correctness, repo understanding, complete context use, runtime
behavior, test sufficiency, regression absence, forensic readiness, or claim
truth.  It only reports whether a declared self-report formally matches the
required-reading expectation.
"""
from __future__ import annotations


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

_FAIL = "fail"
_WARN = "warn"
_INFO = "info"


def validate_agent_consumption(
    required_reading_result: dict,
    answer_compliance: dict,
    *,
    available_roles: set[str] | None = None,
) -> dict:
    """Compare a resolved Required Reading result against an Answer Compliance
    declaration and return a deterministic Agent Consumption Trace dict.

    Parameters
    ----------
    required_reading_result:
        Output of ``resolve_required_reading`` (or an equivalent dict carrying
        ``task_profile``, ``required``, ``recommended`` and ``status``).  The
        existing Required Reading resolution is reused as-is; this validator does
        not re-derive it.
    answer_compliance:
        An ``answer-compliance.v1`` declaration dict.
    available_roles:
        Optional set of roles known to exist in the bundle context.  When
        provided, declared artifacts in this set are not flagged as unknown.
        When ``None``, only required + recommended roles are treated as known and
        any other declared role is conservatively warned.

    Returns
    -------
    dict
        A trace that validates against
        ``contracts/agent-consumption-trace.v1.schema.json``.
    """
    rr = required_reading_result or {}
    ac = answer_compliance or {}

    rr_profile = rr.get("task_profile")
    ac_profile = ac.get("task_profile")
    task_profile = rr_profile if rr_profile not in (None, "") else ac_profile
    if task_profile in (None, ""):
        task_profile = "unknown"

    required_artifacts = _norm_roles(rr.get("required"))
    recommended_artifacts = _norm_roles(rr.get("recommended"))
    declared_artifacts = _norm_roles(ac.get("declared_artifacts"))
    unread_required = _norm_roles(ac.get("unread_required_artifacts"))
    unread_recommended = _norm_roles(ac.get("unread_recommended_artifacts"))

    # Pass-through declarations.  The trace is a comparison artifact, not a second
    # Answer Compliance validator, so these are adopted verbatim.
    declared_citations = list(ac.get("declared_citations") or [])
    declared_ranges = list(ac.get("declared_ranges") or [])
    epistemic_gaps = list(ac.get("epistemic_gaps") or [])

    diagnostics: list[dict] = []

    # ── Negative semantics (contract invariant) ─────────────────────────────
    # A broken Answer Compliance artifact stays broken even when the task
    # profile is not applicable: the nine does_not_establish boundaries are a
    # contract invariant, not a profile question.  Evaluated before the
    # not_applicable short-circuit so invalid boundaries are never swallowed.
    if not _has_exact_negative_semantics(ac):
        diagnostics.append(
            _diag(
                "missing_negative_semantics",
                _FAIL,
                "Answer compliance does_not_establish must contain exactly the "
                "nine required boundaries.",
            )
        )

    # ── Rule 1: task profile resolution ─────────────────────────────────────
    # not_applicable stops the Soll/Ist comparison (there is no meaningful
    # expectation to compare against), but a failing contract invariant such as
    # invalid negative semantics still wins.
    if rr.get("status") == "not_applicable":
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

    if ac_profile is not None and ac_profile != rr_profile:
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

    # ── Rule 2: required artifacts ──────────────────────────────────────────
    # Honestly declaring a required artifact as unread is good practice, but it
    # is still a formal deviation from the expectation.
    missing_required_artifacts: list[str] = []
    for role in required_artifacts:
        if role in unread_required_set:
            diagnostics.append(
                _diag(
                    "unread_required_artifact",
                    _FAIL,
                    f"Required artifact '{role}' was declared unread.",
                    artifact=role,
                )
            )
        elif role not in declared_set:
            missing_required_artifacts.append(role)
            diagnostics.append(
                _diag(
                    "missing_required_artifact",
                    _FAIL,
                    f"Required artifact '{role}' was not declared.",
                    artifact=role,
                )
            )

    # ── Rule 3: recommended artifacts ───────────────────────────────────────
    missing_recommended_artifacts: list[str] = []
    for role in recommended_artifacts:
        if role in unread_recommended_set:
            diagnostics.append(
                _diag(
                    "unread_recommended_artifact",
                    _WARN,
                    f"Recommended artifact '{role}' was declared unread.",
                    artifact=role,
                )
            )
        elif role not in declared_set:
            missing_recommended_artifacts.append(role)
            diagnostics.append(
                _diag(
                    "missing_recommended_artifact",
                    _WARN,
                    f"Recommended artifact '{role}' was not declared.",
                    artifact=role,
                )
            )

    # ── Rule 4: unknown declared artifacts ──────────────────────────────────
    known_roles = set(required_artifacts) | set(recommended_artifacts)
    if available_roles is not None:
        known_roles |= {str(x) for x in available_roles}
    unknown_declared_artifacts: list[str] = []
    for role in declared_artifacts:
        if role not in known_roles:
            unknown_declared_artifacts.append(role)
            diagnostics.append(
                _diag(
                    "unknown_declared_artifact",
                    _WARN,
                    f"Declared artifact '{role}' is not a known required, "
                    f"recommended, or available role.",
                    artifact=role,
                )
            )

    # ── Status priority ─────────────────────────────────────────────────────
    # Negative semantics were already evaluated above, before the
    # not_applicable short-circuit.
    if any(d["severity"] == _FAIL for d in diagnostics):
        status = "fail"
    elif any(d["severity"] == _WARN for d in diagnostics):
        status = "warn"
    else:
        status = "pass"

    return _trace(
        task_profile=task_profile,
        status=status,
        required_artifacts=required_artifacts,
        recommended_artifacts=recommended_artifacts,
        declared_artifacts=declared_artifacts,
        missing_required_artifacts=sorted(missing_required_artifacts),
        missing_recommended_artifacts=sorted(missing_recommended_artifacts),
        unknown_declared_artifacts=sorted(unknown_declared_artifacts),
        unread_required_artifacts=unread_required,
        unread_recommended_artifacts=unread_recommended,
        declared_citations=declared_citations,
        declared_ranges=declared_ranges,
        epistemic_gaps=epistemic_gaps,
        diagnostics=diagnostics,
    )


def _norm_roles(value) -> list[str]:
    """Normalise a role list deterministically: stringify, dedupe, sort.

    Defensive only: a scalar string is treated as a single role rather than
    being decomposed into characters.  No schema validation, no exceptions.
    """
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if not value:
        return []
    return sorted({str(x) for x in value})


def _has_exact_negative_semantics(answer_compliance: dict) -> bool:
    """True iff Answer Compliance declares exactly the nine required boundaries.

    Rejects missing, extra, unknown, and duplicate values alike.
    """
    ac_negatives = [
        str(x) for x in (answer_compliance.get("does_not_establish") or [])
    ]
    return (
        set(ac_negatives) == set(DOES_NOT_ESTABLISH)
        and len(ac_negatives) == len(DOES_NOT_ESTABLISH)
    )


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
